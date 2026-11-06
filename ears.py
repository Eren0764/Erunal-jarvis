#!/usr/bin/env python3
"""ears.py — Jarvis'in kulakları: konuşmayı metne çevirme (STT).

Groq API üzerinde Whisper Large V3 (bulut API; yerel model YOK). Tarayıcı MediaRecorder ile bir
cümlelik sesi kaydeder (900 ms duraklamada keser), server.py'deki POST /listen bu modüle iletir,
dönen Türkçe metin tarayıcıda yazılı soruyla AYNI akıştan (ses komutları → /jarvis ya da /chat) geçer.

config.json:  "groq_api_key": "gsk_..."      (isteğe bağlı: "groq_stt_model": "whisper-large-v3")
"""
import re
import threading

import brain

GROQ_STT_MODEL = "whisper-large-v3"
STT_LANGUAGE = "tr"
STT_TIMEOUT = 30
# Whisper'a özel adların yazımını öğretir (tanınma doğruluğunu artırır).
STT_PROMPT = "Hey Jarvis. Tahta. Hocam, YouTube, Claude, Gemini, Abacus."
MAX_AUDIO_BYTES = 20 * 1024 * 1024        # Groq ücretsiz katman sınırı 25 MB

NO_GROQ_KEY = ("Henüz Groq API anahtarı yok. Ayarlar'dan (⚙) ya da config.json'daki groq_api_key alanından "
               "console.groq.com/keys adresinden aldığınız anahtarı girin.")

# Whisper sessizlik/gürültüde bilinen "hayalet" Türkçe cümleler üretir; bunlar tek başına gelirse atılır.
HALLUCINATIONS = re.compile(
    r"^\W*(?:altyaz[ıi].*|.*abone ol.*|izledi[ğg]iniz i[çc]in te[şs]ekk[üu]r.*|bir sonraki videoda.*|"
    r"videoyu be[ğg]enmeyi unutmay[ıi]n.*|m\.?\s?k\.?|www\..*|\.\.\.|-+)\W*$", re.I)

# MediaRecorder MIME türü -> Groq'un tanıdığı dosya uzantısı
EXT = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "mp4", "audio/mpeg": "mp3",
       "audio/wav": "wav", "audio/x-wav": "wav", "audio/flac": "flac", "audio/m4a": "m4a"}

_CLIENTS = {}
_LOCK = threading.Lock()


def _client(key):
    try:
        from groq import Groq
    except ImportError:
        raise brain.BrainError("groq paketi kurulu değil: pip install -r requirements.txt", 500)
    import ssl
    import httpx
    with _LOCK:
        if key not in _CLIENTS:
            if len(_CLIENTS) > 4:
                _CLIENTS.clear()
            # Okul (MEB) ağı api.groq.com trafiğini kendi sertifikasıyla yeniden imzalıyor; o sertifika
            # işletim sisteminin güven deposunda var ama Python'un hazır listesinde (certifi) yok.
            # Sistem deposunu kullanırız: doğrulama AÇIK kalır, sadece OS'un güvendiğine güveniriz.
            http = httpx.Client(timeout=STT_TIMEOUT, verify=ssl.create_default_context())
            _CLIENTS[key] = Groq(api_key=key, max_retries=1, http_client=http)
        return _CLIENTS[key]


def _ext(mime):
    base = (mime or "").split(";")[0].strip().lower()
    return EXT.get(base, "webm")


def transcribe(audio, mime="audio/webm"):
    """Ses baytları -> {"text": Türkçe metin ('' ise konuşma yok), "duration": saniye, "dropped": [...]}"""
    if not audio:
        raise brain.BrainError("Ses verisi boş.", 400)
    if len(audio) > MAX_AUDIO_BYTES:
        raise brain.BrainError("Ses kaydı çok uzun.", 413)
    cfg = brain.load_config()
    key = cfg.get("groq_api_key")
    if brain.is_placeholder(key):
        raise brain.BrainError(NO_GROQ_KEY, 503)
    import groq
    try:
        resp = _client(key.strip()).audio.transcriptions.create(
            model=cfg.get("groq_stt_model") or GROQ_STT_MODEL,
            file=(f"konusma.{_ext(mime)}", audio),
            language=STT_LANGUAGE,
            prompt=STT_PROMPT,
            temperature=0.0,
            response_format="verbose_json",
        )
    except groq.AuthenticationError:
        raise brain.BrainError("Groq, API anahtarını reddetti. console.groq.com/keys adresinden kontrol edin.", 502)
    except groq.RateLimitError:
        raise brain.BrainError("Groq kullanım sınırı doldu (429); biraz bekleyip tekrar deneyin.", 429)
    except groq.BadRequestError as e:
        raise brain.BrainError(f"Groq sesi işleyemedi: {brain.scrub(getattr(e, 'message', e), cfg)[:200]}", 400)
    except (groq.APITimeoutError, groq.APIConnectionError):
        raise brain.BrainError("Groq'a ulaşılamadı; internet bağlantısını kontrol edin.", 503)
    except groq.APIStatusError as e:
        raise brain.BrainError(f"Groq hatası {e.status_code}: {brain.scrub(getattr(e, 'message', e), cfg)[:200]}", 502)

    data = resp.model_dump() if hasattr(resp, "model_dump") else {"text": getattr(resp, "text", "")}
    segments = data.get("segments") or []
    dropped = []
    if segments:
        # Konuşma olmayan (sessizlik/gürültü) parçaları at
        kept = []
        for s in segments:
            if (s.get("no_speech_prob") or 0) > 0.6 and (s.get("avg_logprob") or 0) < -0.7:
                dropped.append(s.get("text", "").strip())
            else:
                kept.append(s.get("text", "").strip())
        text = " ".join(t for t in kept if t)
    else:
        text = (data.get("text") or "").strip()
    text = re.sub(r"\s+", " ", text).strip()
    if text and HALLUCINATIONS.match(text):
        dropped.append(text)
        text = ""
    return {"text": text, "duration": data.get("duration"), "dropped": dropped}


def test_groq_key(key=None):
    """Ücretsiz bir çağrıyla (model listesi) Groq anahtarını dener."""
    cfg = brain.load_config()
    key = (key or "").strip() or cfg.get("groq_api_key")
    if brain.is_placeholder(key):
        return {"ok": False, "message": "Groq anahtarı girilmedi."}
    import groq
    try:
        ids = [m.id for m in _client(key.strip()).models.list().data]
    except groq.AuthenticationError:
        return {"ok": False, "message": "Groq bu anahtarı reddetti."}
    except Exception as e:
        return {"ok": False, "message": f"Groq'a ulaşılamadı: {brain.scrub(e, cfg)[:120]}"}
    model = cfg.get("groq_stt_model") or GROQ_STT_MODEL
    return {"ok": True, "message": "Groq anahtarı çalışıyor." + ("" if model in ids else f" Not: '{model}' listede yok.")}
