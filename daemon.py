#!/usr/bin/env python3
"""daemon.py — "Hey Jarvis" / "Tahta" arka plan servisi (Windows 11 + Linux).

Jarvis sayfası küçültülmüş, gizli ya da arka planda olsa bile mikrofonu dinler. Uyandırma sözcüğü duyulunca:
  a) POST /unmute (POST /wake içinde)  → sunucudaki sessiz mod kapanır, açık sayfalar ?mute=1'den çıkar
  b) controller.focus_jarvis()         → Jarvis tarayıcı penceresi en öne gelir (yoksa açılır)
  c) sayfa /events üzerinden "wake" alır → Groq dinlemesini başlatır ve "Dinliyorum, Hocam." der (Gemini sesi).
     Sayfanın sesi henüz açılmamışsa (hiç tıklanmamışsa) aynı Gemini sesini bu servis kendisi çalar.

YEREL YAPAY ZEKÂ MODELİ YOK:
  * speech_recognition yalnızca mikrofon + ses ENERJİSİ eşiği için kullanılır (Recognizer.listen). Hiçbir
    yerel tanıyıcı (pocketsphinx, vosk, whisper) çağrılmaz.
  * Kısa bir ifade yakalanınca sunucunun POST /listen ucuna gönderilir → Groq Whisper (API). Anahtar bu
    serviste değil, sunucuda kalır. Groq kotasını korumak için: yalnızca 0,35–5 sn'lik ifadeler gönderilir,
    sayfa zaten dinlerken hiçbir şey gönderilmez, dakikada en fazla MAX_PER_MIN istek yapılır.
  * Sesli yanıt sunucunun POST /speak ucundan gelir → Gemini API.

Mikrofon: PyAudio yerine sounddevice (Windows'ta tekerlek içinde gelir, Linux'ta libportaudio2 yeterli).

Çalıştırma:   .venv/bin/python daemon.py            (Linux)      .venv\\Scripts\\pythonw.exe daemon.py   (Windows)
Seçenekler:   --server URL   --device N   --list-devices   --tray (pystray kuruluysa bildirim alanı simgesi)
Durdurmak:    jarvis-durdur.sh  (ya da tepsideki "Çık")      Günlük: data/daemon.log
"""
import argparse
import os
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import controller                        # noqa: E402  (pencere odaklama, platform algılama)
from brain import WAKE_REPLY, split_wake  # noqa: E402  (yalnızca uyandırma sözcüğü kuralı; AI çağrısı yok)

SERVER = "http://127.0.0.1:4700"
PID_FILE = os.path.join(ROOT, "data", "daemon.pid")
SAMPLE_RATE = 16000
MIN_PHRASE_S = 0.35            # bundan kısası tık/öksürük
MAX_PHRASE_S = 5.0             # bundan uzunu sürekli konuşma (ders anlatımı) → gönderilmez
MAX_PER_MIN = 12               # Groq'a dakikada en fazla bu kadar uyandırma denemesi
WAKE_COOLDOWN_S = 4.0          # iki uyandırma arası en az bu kadar
ACK_WAIT_S = 2.0               # sayfanın "Dinliyorum"u kendisi söylemesi için beklenen süre


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------------------- mikrofon (PyAudio'suz)
try:
    import speech_recognition as sr
except ImportError:
    sys.exit("speech_recognition kurulu değil: pip install -r requirements.txt")


class SoundDeviceMic(sr.AudioSource):
    """speech_recognition AudioSource backed by sounddevice (no PyAudio build needed)."""

    def __init__(self, device=None, sample_rate=SAMPLE_RATE, chunk=1024):
        self.device, self.SAMPLE_RATE, self.CHUNK, self.SAMPLE_WIDTH = device, sample_rate, chunk, 2
        self.stream, self._s = None, None

    def __enter__(self):
        import sounddevice as sd
        self._s = sd.RawInputStream(samplerate=self.SAMPLE_RATE, blocksize=self.CHUNK, channels=1,
                                    dtype="int16", device=self.device)
        self._s.start()
        self.stream = self
        return self

    def read(self, frames):
        data, _overflow = self._s.read(frames)
        return bytes(data)

    def __exit__(self, *exc):
        if self._s:
            self._s.stop()
            self._s.close()
        self.stream = self._s = None


# ---------------------------------------------------------------------------- sunucu ile konuşma
class Jarvis:
    def __init__(self, server):
        self.server = server.rstrip("/")
        self.http = requests.Session()
        self.calls = deque()
        self.backoff_until = 0.0
        self.last_wake = 0.0
        self._state, self._state_at = {}, 0.0

    def state(self, max_age=1.0):
        if time.time() - self._state_at > max_age:
            try:
                self._state = self.http.get(self.server + "/wake/state", timeout=2).json()
            except (requests.RequestException, ValueError):
                self._state = {"offline": True}
            self._state_at = time.time()
        return self._state

    def allow(self):
        now = time.time()
        while self.calls and now - self.calls[0] > 60:
            self.calls.popleft()
        if now < self.backoff_until or len(self.calls) >= MAX_PER_MIN:
            return False
        self.calls.append(now)
        return True

    def transcribe(self, wav):
        r = self.http.post(self.server + "/listen", data=wav, headers={"Content-Type": "audio/wav"}, timeout=20)
        if r.status_code == 429:
            self.backoff_until = time.time() + 60
            log("Groq kotası doldu (429); 60 sn bekleniyor")
            return ""
        if r.status_code == 503 and "anahtar" in r.text.lower():
            self.backoff_until = time.time() + 300
            log("Groq anahtarı yok; Ayarlar'dan girin. 5 dk sonra tekrar denenecek.")
            return ""
        r.raise_for_status()
        return (r.json().get("text") or "").strip()

    def wake(self, rest):
        self.last_wake = time.time()
        r = self.http.post(self.server + "/wake", json={"text": rest}, timeout=5,
                           headers={"Origin": self.server}).json()
        seq, reply = r["seq"], r.get("reply") or WAKE_REPLY
        pages = r.get("pages", 0)
        try:                                   # b) pencereyi öne getir (yoksa ?wake=1 ile aç)
            res = controller.focus_jarvis(self.server + "/?wake=1", open_if_missing=True)
            log("pencere:", res.get("title") or ("açıldı" if res.get("opened") else "bulunamadı"), res.get("method"))
        except Exception as e:
            log("pencere öne getirilemedi:", e)
        t0 = time.time()                       # c) sayfa "Dinliyorum"u kendisi söyledi mi?
        while time.time() - t0 < ACK_WAIT_S and pages:
            st = self.state(max_age=0)
            if st.get("acked") == seq:
                if st.get("spoken"):
                    return
                break
            time.sleep(0.15)
        self.say(reply)

    def say(self, text):
        """Gemini sesini (/speak) bu bilgisayarın hoparlöründen çal."""
        try:
            r = self.http.post(self.server + "/speak", json={"text": text}, timeout=30, headers={"Origin": self.server})
            r.raise_for_status()
            play_wav(r.content)
        except Exception as e:
            log("ses çalınamadı:", e)


def play_wav(wav):
    if controller.PLATFORM == "windows":
        import winsound
        winsound.PlaySound(wav, winsound.SND_MEMORY)
        return
    fd, path = tempfile.mkstemp(suffix=".wav")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(wav)
        for cmd in (["pw-play", path], ["paplay", path], ["aplay", "-q", path], ["afplay", path]):
            try:
                if subprocess.run(cmd, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                    return
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
        log("ses çalınamadı: pw-play / paplay / aplay bulunamadı")
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------- ana döngü
class Daemon:
    def __init__(self, args):
        self.args, self.paused, self.stop = args, False, threading.Event()
        self.j = Jarvis(args.server)

    def run(self):
        rec = sr.Recognizer()
        rec.dynamic_energy_threshold = True
        rec.pause_threshold = 0.6              # bu kadar sessizlik ifadeyi bitirir
        rec.non_speaking_duration = 0.4
        rec.phrase_threshold = 0.25
        log(f"başladı · {controller.PLATFORM} ({controller.SESSION}) · sunucu {self.j.server} · "
            f"uyandırma: “Hey Jarvis” / “Tahta”")
        while not self.stop.is_set():
            try:
                with SoundDeviceMic(self.args.device) as mic:
                    rec.adjust_for_ambient_noise(mic, duration=1.0)
                    log(f"mikrofon hazır (eşik {rec.energy_threshold:.0f})")
                    while not self.stop.is_set():
                        self.once(rec, mic, sr)
            except Exception as e:             # mikrofon çıkarıldı, sunucu kapandı…: biraz bekle, yeniden dene
                log("hata:", type(e).__name__, e)
                self.stop.wait(5)

    def once(self, rec, mic, sr):
        try:
            audio = rec.listen(mic, timeout=2, phrase_time_limit=MAX_PHRASE_S)
        except sr.WaitTimeoutError:
            return
        dur = len(audio.frame_data) / (audio.sample_rate * audio.sample_width)
        if self.paused or not (MIN_PHRASE_S <= dur < MAX_PHRASE_S - 0.1):
            return
        st = self.j.state()
        if st.get("offline") or st.get("page_listening"):   # sayfa zaten dinliyor: o halleder
            return
        if time.time() - self.j.last_wake < WAKE_COOLDOWN_S or not self.j.allow():
            return
        try:
            text = self.j.transcribe(audio.get_wav_data(convert_rate=SAMPLE_RATE, convert_width=2))
        except requests.RequestException as e:
            log("dinleme isteği başarısız:", e)
            return
        woke, rest = split_wake(text)
        if not woke:
            return
        log(f"uyandırıldı: “{text}”")
        threading.Thread(target=self._wake, args=(rest,), daemon=True).start()

    def _wake(self, rest):
        try:
            self.j.wake(rest)
        except Exception as e:
            log("uyandırma başarısız:", e)


def single_instance():
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    try:
        with open(PID_FILE) as f:
            old = int(f.read().strip() or 0)
        if old and old != os.getpid():
            if controller.PLATFORM == "windows":
                alive = str(old) in subprocess.run(["tasklist", "/FI", f"PID eq {old}"], capture_output=True, text=True).stdout
            else:
                try:
                    os.kill(old, 0)
                    alive = True
                except OSError:
                    alive = False
            if alive:
                sys.exit(f"daemon zaten çalışıyor (pid {old}).")
    except (OSError, ValueError):
        pass
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def tray(d):
    """Bildirim alanı simgesi (pystray + Pillow kuruluysa). Windows'ta tam çalışır; GNOME'da
    AppIndicator eklentisi gerekir."""
    import pystray
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    g = ImageDraw.Draw(img)
    g.ellipse((4, 4, 60, 60), outline=(124, 196, 255, 255), width=6)
    g.ellipse((22, 22, 42, 42), fill=(124, 196, 255, 255))

    def toggle(icon, item):
        d.paused = not d.paused

    def quit_(icon, item):
        d.stop.set()
        icon.stop()

    icon = pystray.Icon("jarvis", img, "Jarvis — Hey Jarvis / Tahta", menu=pystray.Menu(
        pystray.MenuItem("Dinlemeyi duraklat", toggle, checked=lambda item: d.paused),
        pystray.MenuItem("Çık", quit_)))
    threading.Thread(target=d.run, daemon=True).start()
    icon.run()


def main():
    ap = argparse.ArgumentParser(description="Jarvis uyandırma sözcüğü servisi")
    ap.add_argument("--server", default=SERVER)
    ap.add_argument("--device", type=int, default=None, help="mikrofon numarası (--list-devices)")
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--tray", action="store_true", help="bildirim alanında simge göster (pystray gerekir)")
    args = ap.parse_args()
    if args.list_devices:
        import sounddevice as sd
        print(sd.query_devices())
        return
    single_instance()
    d = Daemon(args)
    try:
        if args.tray:
            try:
                tray(d)
                return
            except ImportError:
                log("pystray/Pillow yok; simgesiz arka planda çalışıyor")
        d.run()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            os.unlink(PID_FILE)
        except OSError:
            pass


if __name__ == "__main__":
    main()
