#!/usr/bin/env python3
"""preflight.py — Jarvis canlı sistem kontrolü (self-diagnostics).

Çalışan Jarvis sunucusuna (http://127.0.0.1:4700) GERÇEK istekler atar; sahte/mock yoktur:
  sunucu → grafik verisi → /chat → API anahtarları → model → eylem etiketi → /remember →
  sıfırlama → dosya tutarlılığı → güvenlik (config.json) → ?mute=1 ve Hafıza çekmecesi
  (gerçek, başsız Chromium içinde). Gerçek hafıza kayıtlarınız sıfırlama testinden önce yedeklenip geri konur.

Her kontrol ✔ (geçti), ✘ (başarısız) ya da ⚠ (uyarı) yazar; sonda tek satır özet:
  "N pass, N fail, N warn". Herhangi bir ✘ varsa çıkış kodu 1'dir.

Not: eylem etiketi kontrolü Gemini'nin etiketi ÜRETTİĞİNİ doğrular; etiketi ÇALIŞTIRMAZ
(fare/klavye hareket etmez). Sunucuyu başlatmak için: ./jarvis-baslat.sh

Kullanım:  .venv/bin/python preflight.py [--url http://127.0.0.1:4700] [--no-browser]
"""
import argparse
import asyncio
import hashlib
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
VIEWER = os.path.join(ROOT, "viewer")
CAPTURES = os.path.join(ROOT, "captures")
TURKISH = re.compile(r"[çğıöşüÇĞİÖŞÜ]|\b(?:ve|bir|bu|için|notlar|değil|var|yok|ile)\b", re.I)

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"
if not sys.stdout.isatty():
    GREEN = RED = YELLOW = DIM = RESET = ""


class Check:
    def __init__(self):
        self.passed = self.failed = self.warned = 0

    def ok(self, name, detail=""):
        self.passed += 1
        print(f"{GREEN}✔{RESET} {name}" + (f" {DIM}— {detail}{RESET}" if detail else ""))

    def fail(self, name, detail=""):
        self.failed += 1
        print(f"{RED}✘ {name}{RESET}" + (f" — {detail}" if detail else ""))

    def warn(self, name, detail=""):
        self.warned += 1
        print(f"{YELLOW}⚠ {name}{RESET}" + (f" — {detail}" if detail else ""))


C = Check()


def load_graph(base):
    r = requests.get(base + "/graph-data.js", timeout=10)
    r.raise_for_status()
    t = r.text
    return json.loads(t[t.index("{"): t.rindex("}") + 1])


def post(base, path, data, timeout=60):
    return requests.post(base + path, json=data, timeout=timeout,
                         headers={"Origin": base, "Sec-Fetch-Site": "same-origin"})


# ---------------------------------------------------------------------------- 1. server
def check_server(base):
    try:
        r = requests.get(base + "/", timeout=5)
        g = requests.get(base + "/galaxy.html", timeout=5)
    except requests.RequestException as e:
        C.fail("Sunucu çalışıyor ve arayüzü sunuyor", f"{base} yanıt vermiyor ({type(e).__name__}). ./jarvis-baslat.sh ile başlatın.")
        return False
    if r.status_code == 200 and "J.A.R.V.I.S" in r.text and g.status_code == 200 and "Bilgi Galaksisi" in g.text:
        C.ok("Sunucu çalışıyor ve arayüzü sunuyor", f"{base}/ ve /galaxy.html → 200")
        return True
    C.fail("Sunucu çalışıyor ve arayüzü sunuyor", f"/ → {r.status_code}, /galaxy.html → {g.status_code}")
    return False


# ---------------------------------------------------------------------------- 2. graph data
def check_graph(base):
    try:
        graph = load_graph(base)
    except Exception as e:
        C.fail("3B grafik verisi yükleniyor", f"graph-data.js okunamadı: {e}")
        return None
    nodes, links = graph.get("nodes", []), graph.get("links", [])
    if any(n.get("id") != i for i, n in enumerate(nodes)):
        C.fail("3B grafik verisi yükleniyor", "node id ≠ dizin (build.py kuralı bozuk)")
        return graph
    bad_links = [l for l in links if not (0 <= l["source"] < len(nodes) and 0 <= l["target"] < len(nodes))]
    if bad_links:
        C.fail("3B grafik verisi yükleniyor", f"{len(bad_links)} bağlantı olmayan bir düğümü gösteriyor")
        return graph
    notes = [n for n in nodes if not n.get("capture")]
    caps = len(nodes) - len(notes)
    if not notes:
        C.fail("3B grafik verisi: ders/not sayısı > 0",
               f"notes/ klasörü boş (0 not, {caps} hafıza kaydı). Kendi .md notlarınızı notes/ içine koyun.")
    else:
        C.ok("3B grafik verisi: ders/not sayısı > 0", f"{len(notes)} not, {caps} hafıza kaydı, {len(links)} bağlantı")
    return graph


# ---------------------------------------------------------------------------- 3. /chat
def check_chat(base, graph):
    q = "Notlarımda hangi konular var? İki cümleyle özetle."
    try:
        r = post(base, "/chat", {"question": q, "session": "preflight-" + uuid.uuid4().hex[:8]}, timeout=90)
        data = r.json()
    except Exception as e:
        C.fail("/chat Türkçe yanıt ve nodes dizisi", f"istek başarısız: {e}")
        return
    n = len((graph or {}).get("nodes", []))
    nodes = data.get("nodes")
    if r.status_code != 200 or data.get("error"):
        C.fail("/chat Türkçe yanıt ve nodes dizisi", f"HTTP {r.status_code}: {data.get('error')}")
    elif not isinstance(nodes, list) or not all(isinstance(i, int) and 0 <= i < max(n, 1) for i in nodes):
        C.fail("/chat Türkçe yanıt ve nodes dizisi", f"nodes geçersiz: {nodes!r}")
    elif not isinstance(data.get("answer"), str) or not TURKISH.search(data["answer"]):
        C.fail("/chat Türkçe yanıt ve nodes dizisi", f"yanıt Türkçe görünmüyor: {str(data.get('answer'))[:80]!r}")
    else:
        C.ok("/chat Türkçe yanıt ve nodes dizisi", f"{len(nodes)} kaynak not · “{data['answer'][:70]}…”")


# ---------------------------------------------------------------------------- 4–5. keys + model
def check_keys_and_model():
    import brain
    cfg = brain.load_config()
    keys = brain.GEMINI_KEYS.keys()
    provider = str(cfg.get("ai_provider", "gemini"))
    model = str(cfg.get("model") or brain.DEFAULT_GEMINI_MODEL)
    good = []
    if not keys:
        C.fail("Gemini API anahtarları geçerli", "config.json'da Gemini anahtarı yok (Ayarlar ⚙)")
    else:
        bad = []
        for k in keys:                      # free, minimal live call per key
            res = brain.test_gemini_key(k)
            (good if res["ok"] else bad).append((k, res["message"]))
        if good:
            msg = f"{len(good)}/{len(keys)} anahtar canlı çağrıya yanıt verdi"
            (C.warn if bad else C.ok)("Gemini API anahtarları geçerli",
                                      msg + ("; çalışmayan: " + ", ".join(f"{brain._key_hint(k)} ({m})" for k, m in bad) if bad else ""))
        else:
            C.fail("Gemini API anahtarları geçerli", "; ".join(f"{brain._key_hint(k)}: {m}" for k, m in bad))
    if brain.is_placeholder(cfg.get("abacus_api_key")):
        if provider == "abacus" or cfg.get("agent_mode") == "abacus_full_auto":
            C.fail("Abacus.AI API anahtarı", "ai_provider/agent_mode Abacus kullanıyor ama anahtar yok")
    else:
        try:
            brain._abacus(cfg, "Reply with OK.", [{"role": "user", "text": "OK?"}], 5, 0)
            C.ok("Abacus.AI API anahtarı geçerli", "canlı RouteLLM çağrısı yanıt verdi")
        except brain.BrainError as e:
            (C.fail if provider == "abacus" else C.warn)("Abacus.AI API anahtarı", str(e)[:160])

    if provider == "groq":                  # the chat brain: one real call through the model chain
        g_name = f"Groq sohbet beyni ({brain.GROQ_MODELS[0][0]} → yedekler)"
        if brain.is_placeholder(cfg.get("groq_api_key")):
            C.fail(g_name, "groq_api_key yok (Ayarlar ⚙)")
        else:
            try:
                start = time.time()
                reply = brain._groq(cfg, "Yalnızca Türkçe yanıt ver.", [{"role": "user", "text": "Sadece 'tamam' yaz."}], 64, 0)
                C.ok(g_name, f"requests ile POST api.groq.com → {reply[:30]!r} · {time.time() - start:.1f} sn")
            except brain.BrainError as e:
                C.fail(g_name, str(e)[:200])
    if provider == "huggingface":           # the chat brain: token check (free), then one real Gemma call
        hf_name = f"Hugging Face sohbet modeli ({cfg.get('huggingface_model') or brain.HF_DEFAULT_MODEL})"
        if brain.is_placeholder(brain.hf_key(cfg)):
            C.fail(hf_name, "huggingface_api_key yok (Ayarlar ⚙ ya da config.json)")
        else:
            t = brain.test_hf_key()
            try:
                if not t["ok"]:
                    raise brain.BrainError(t["message"])
                start = time.time()
                reply = brain._huggingface(cfg, "Yalnızca Türkçe yanıt ver.", [{"role": "user", "text": "Sadece 'tamam' yaz."}], 16, 0)
                C.ok(hf_name, f"anahtar geçerli · requests ile POST {brain.HF_URL.split('//')[1].split('/')[0]} → "
                              f"{reply[:30]!r} · {time.time() - start:.1f} sn")
            except brain.BrainError as e:
                C.fail(hf_name, str(e)[:200])

    # Configured model through the official google-genai SDK (no fallback: we test THIS model).
    if not good:
        C.fail(f"Model erişilebilir ({model})", "çalışan Gemini anahtarı yok")
        return
    from google.genai import types
    pool = [k for k, _ in good]
    attempt = 0
    while pool:
        key = pool[0]
        attempt += 1
        client = brain.gemini_client(key, 30)
        try:
            resp = client.models.generate_content(
                model=model, contents="Sadece 'tamam' yaz.",
                config=types.GenerateContentConfig(max_output_tokens=256, temperature=0))
            fin = resp.candidates[0].finish_reason if resp.candidates else None
            C.ok(f"Model erişilebilir ({model})", f"google-genai yanıtı: {(resp.text or '').strip()[:30]!r} (bitiş: {fin})")
            return
        except Exception as e:
            code, msg, kind = brain._gemini_error(e, cfg)
            if kind == "quota":                 # this key's quota is used up: Jarvis rotates, so do we
                print(f"  {DIM}{brain._key_hint(key)} kotası dolu, sıradaki anahtar deneniyor{RESET}")
                pool.pop(0)
                if not pool:
                    C.fail(f"Model erişilebilir ({model})", "tüm Gemini anahtarlarının kotası dolu (429)")
                continue
            if kind == "busy" and attempt == 1:
                time.sleep(3)
                continue
            if kind == "busy":
                C.warn(f"Model erişilebilir ({model})", f"model şu an yoğun (503); Jarvis yedek modele geçer: {msg[:100]}")
            else:
                C.fail(f"Model erişilebilir ({model})", f"{code or ''} {kind}: {msg[:160]} — Ayarlar'dan model adını düzeltin")
            return


# ---------------------------------------------------------------------------- 6. action tags
def check_action_tags():
    import brain
    cfg = brain.load_config()
    phrase = "Sınıfa fotosentez ile ilgili bir YouTube videosu açar mısın?"
    route, _ = brain.match_route("YouTube'da fotosentez videosu aç")
    if not route or route["name"] != "youtube":
        C.fail("Eylem: sabit komut yolu", "“YouTube'da fotosentez videosu aç” youtube rotasına düşmedi")
    else:
        C.ok("Eylem: sabit komut yolu", "“YouTube'da fotosentez videosu aç” → youtube (controller.search_and_play_youtube)")
    try:
        system = brain.build_system(brain.NOTES_RULES, brain.PROJECT_RULES)
        raw = brain.complete(cfg, system, [{"role": "user", "text": phrase}], max_tokens=1024, temperature=0.2)
    except brain.BrainError as e:
        C.fail("Eylem etiketi üretimi (LLM)", str(e)[:160])
        return
    tag = brain.parse_tag(raw)
    spec = tag and next((t for t in brain.ACTION_TAGS if t["tag"] == tag[0]), None)
    if not tag:
        C.fail("Eylem etiketi üretimi (LLM)", f"etiket yok; model yanıtı: {raw[:120]!r}")
    elif tag[0] != "YOUTUBE" or not tag[1].get("QUERY"):
        C.fail("Eylem etiketi üretimi (LLM)", f"beklenen YOUTUBE+QUERY, gelen {tag}")
    elif not callable(getattr(brain, spec["run"], None)):
        C.fail("Eylem etiketi üretimi (LLM)", f"{spec['run']} yürütücüsü yok")
    else:
        C.ok("Eylem etiketi üretimi (LLM)",
             f"[ACTION: YOUTUBE, QUERY: {tag[1]['QUERY']}] → brain.{spec['run']} (çalıştırılmadı)")


# ---------------------------------------------------------------------------- 7. /remember
def check_remember(base):
    token = "zümrütkaplumbağa" + uuid.uuid4().hex[:5]
    text = (f"Preflight test notu: {token} protokolü, laboratuvarda pH ölçümünden önce "
            f"cam elektrotun saf suyla durulanmasını gerektirir.")
    filename = None
    try:
        r = post(base, "/remember", {"text": text, "title": f"Preflight {token}"})
        data = r.json()
        if r.status_code != 201 or not data.get("ok"):
            C.fail("/remember yazar, indeksler ve /chat bulur", f"HTTP {r.status_code}: {data.get('error')}")
            return
        cap = data["capture"]
        filename = cap["filename"]
        path = os.path.join(CAPTURES, filename)
        if not os.path.isfile(path) or token not in open(path, encoding="utf-8").read():
            C.fail("/remember yazar, indeksler ve /chat bulur", f"captures/{filename} diskte yok")
            return
        graph = load_graph(base)
        idx = next((n["id"] for n in graph["nodes"] if n.get("path") == "captures/" + filename), None)
        if idx is None:
            C.fail("/remember yazar, indeksler ve /chat bulur", "graph-data.js yeni notu içermiyor")
            return
        listed = requests.get(base + "/remember", timeout=10).json()
        if not any(c["filename"] == filename for c in listed.get("captures", [])):
            C.fail("/remember yazar, indeksler ve /chat bulur", "GET /remember yeni notu listelemiyor")
            return
        q = f"{token} protokolü ne gerektirir?"
        cr = post(base, "/chat", {"question": q, "session": "preflight-" + uuid.uuid4().hex[:8]}, timeout=90)
        cd = cr.json()
        if idx not in (cd.get("nodes") or []):
            C.fail("/remember yazar, indeksler ve /chat bulur",
                   f"/chat yeni notu kaynak göstermedi (nodes={cd.get('nodes')}, hata={cd.get('error')})")
            return
        C.ok("/remember yazar, indeksler ve /chat bulur",
             f"captures/{filename} → düğüm {idx} → /chat kaynak olarak döndürdü")
    except Exception as e:
        C.fail("/remember yazar, indeksler ve /chat bulur", f"{type(e).__name__}: {e}")
    finally:
        if filename:
            try:
                d = requests.delete(f"{base}/remember/{filename}", timeout=10,
                                    headers={"Origin": base, "Sec-Fetch-Site": "same-origin"})
                gone = not os.path.exists(os.path.join(CAPTURES, filename))
                still = any(n.get("path") == "captures/" + filename for n in load_graph(base)["nodes"])
                if d.status_code == 200 and gone and not still:
                    C.ok("Test notu silindi (DELETE /remember/<dosya>)", "dosya ve galaksi düğümü kaldırıldı")
                else:
                    C.fail("Test notu silindi (DELETE /remember/<dosya>)",
                           f"HTTP {d.status_code}, dosya duruyor={not gone}, grafikte={still}")
            except Exception as e:
                C.fail("Test notu silindi (DELETE /remember/<dosya>)", str(e))


# ---------------------------------------------------------------------------- 7b. reset (backs up real captures)
def check_reset(base):
    name = "DELETE /remember/all hafızayı temizler"
    hdr = {"Origin": base, "Sec-Fetch-Site": "same-origin"}
    backup = tempfile.mkdtemp(prefix="jarvis-captures-yedek-")
    saved = []
    try:
        if os.path.isdir(CAPTURES):                    # the user's real captures are copied out first
            for fn in os.listdir(CAPTURES):
                if fn.lower().endswith(".md"):
                    shutil.copy2(os.path.join(CAPTURES, fn), backup)
                    saved.append(fn)
        for i in (1, 2):
            post(base, "/remember", {"text": f"Sıfırlama testi {i} {uuid.uuid4().hex[:6]}"})
        before = requests.get(base + "/remember", timeout=10).json()["count"]
        r = requests.delete(base + "/remember/all", headers=hdr, timeout=20)
        d = r.json()
        after = requests.get(base + "/remember", timeout=10).json()["count"]
        left = [f for f in os.listdir(CAPTURES) if f.lower().endswith(".md")] if os.path.isdir(CAPTURES) else []
        in_graph = sum(1 for n in load_graph(base)["nodes"] if n.get("capture"))
        if r.status_code == 200 and before >= 2 and after == 0 and not left and in_graph == 0 \
                and d.get("spoken") == "Tüm hafıza sıfırlandı, Hocam.":
            C.ok(name, f"{before} kayıt silindi, dizin/grafik boş, onay: “{d['spoken']}”"
                       + (f"; {len(saved)} gerçek kaydınız yedeklenip geri yüklendi" if saved else ""))
        else:
            C.fail(name, f"HTTP {r.status_code}, önce={before}, sonra={after}, diskte={len(left)}, grafikte={in_graph}")
    except Exception as e:
        C.fail(name, f"{type(e).__name__}: {e}")
    finally:
        for fn in saved:
            shutil.copy2(os.path.join(backup, fn), os.path.join(CAPTURES, fn))
        try:
            restored = requests.post(base + "/remember/reindex", json={}, headers=hdr, timeout=20).json()["count"]
            if restored != len(saved):
                C.fail("Gerçek hafıza kayıtları geri yüklendi", f"{len(saved)} yedek, {restored} geri geldi — yedek: {backup}")
                return
        except Exception as e:
            C.fail("Gerçek hafıza kayıtları geri yüklendi", f"{e} — yedek: {backup}")
            return
        shutil.rmtree(backup, ignore_errors=True)


# ---------------------------------------------------------------------------- 8. static files
def check_static(base):
    mismatched, checked = [], 0
    for dirpath, dirnames, files in os.walk(VIEWER):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in files:
            if fn.startswith(".") or fn.endswith(".tmp"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), VIEWER).replace(os.sep, "/")
            with open(os.path.join(dirpath, fn), "rb") as f:
                disk = hashlib.sha256(f.read()).hexdigest()
            r = requests.get(f"{base}/{rel}", timeout=10)
            checked += 1
            if r.status_code != 200 or hashlib.sha256(r.content).hexdigest() != disk:
                mismatched.append(f"{rel} ({r.status_code})")
    if mismatched:
        C.fail("Sunulan dosyalar diskteki dosyalarla aynı", ", ".join(mismatched))
    else:
        C.ok("Sunulan dosyalar diskteki dosyalarla aynı", f"{checked} dosya, sha256 eşleşti")


# ---------------------------------------------------------------------------- 9. security
def raw_get(host, port, path, host_header=None):
    c = http.client.HTTPConnection(host, port, timeout=5)
    c.putrequest("GET", path, skip_host=True)          # path sent byte-for-byte (no normalisation)
    c.putheader("Host", host_header or f"{host}:{port}")
    c.endheaders()
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, body


def check_security(base):
    m = re.match(r"https?://([^:/]+):(\d+)", base)
    host, port = m.group(1), int(m.group(2))
    with open(os.path.join(ROOT, "config.json"), "rb") as f:
        cfg = json.loads(f.read())
    secrets = [v.encode() for k, v in cfg.items() if k.endswith("api_key") and isinstance(v, str) and len(v) > 8
               and not v.startswith("PUT-")] + [k.encode() for k in cfg.get("gemini_api_keys", [])]
    probes = ["/config.json", "/../config.json", "/%2e%2e/config.json", "/..%2fconfig.json", "/%2e%2e%2fconfig.json",
              "/viewer/../config.json", "/viewer/..%2f..%2fconfig.json", "//config.json", "/config.json.tmp",
              "/.%2e/config.json", "/brain.py", "/server.py", "/%2e%2e/%2e%2e/config.json", "/static/../config.json"]
    leaks = []
    for p in probes:
        status, body = raw_get(host, port, p)
        if status == 200 or b"api_key" in body or any(s in body for s in secrets):
            leaks.append(f"{p} → {status}")
    status, body = raw_get(host, port, "/settings/keys", host_header="evil.example:4700")
    if status != 403:
        leaks.append(f"DNS-rebinding Host başlığı → {status}")
    r = requests.get(base + "/settings/keys", headers={"Sec-Fetch-Site": "cross-site", "Origin": "http://evil.example"}, timeout=5)
    if r.status_code != 403:
        leaks.append(f"başka siteden /settings/keys → {r.status_code}")
    if leaks:
        C.fail("GÜVENLİK: config.json tarayıcıdan erişilemez", "SIZINTI: " + "; ".join(leaks))
    else:
        C.ok("GÜVENLİK: config.json tarayıcıdan erişilemez", f"{len(probes)} yol denemesi + yabancı Host/Origin reddedildi")


# ---------------------------------------------------------------------------- 10. ?mute=1 (real browser)
def find_chromium():
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        p = shutil.which(name)
        if p:
            return p
    return None


# Runs before the page's own scripts: counts /speak requests and any browser speechSynthesis use.
SPY = """
window.__spy = { speak: 0, speakStatus: [], synth: 0, texts: [] };
const __f = window.fetch;
window.fetch = function (u, o) {
  const url = String(u && u.url || u);
  if (url.endsWith('/speak')) { window.__spy.speak++;
    try { window.__spy.texts.push(JSON.parse(o.body).text); } catch (e) {}
    return __f.apply(this, arguments).then(r => { window.__spy.speakStatus.push(r.status); return r; }); }
  return __f.apply(this, arguments);
};
if (window.speechSynthesis) {
  const s = window.speechSynthesis.speak.bind(window.speechSynthesis);
  window.speechSynthesis.speak = u => { window.__spy.synth++; return s(u); };
}
"""


class Browser:
    """Headless Chromium driven over the DevTools protocol (websockets). Real page, real server."""

    def __init__(self, chrome):
        self.chrome, self.seq, self.sid = chrome, 0, None

    async def __aenter__(self):
        import websockets
        self.tmp = tempfile.mkdtemp(prefix="jarvis-preflight-")
        self.proc = subprocess.Popen(
            [self.chrome, "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={self.tmp}",
             "--no-first-run", "--no-default-browser-check", "--mute-audio", "--window-size=1280,860",
             "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",   # fake mic, auto-allowed
             "--autoplay-policy=no-user-gesture-required", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        ws_url, t0 = None, time.time()
        while time.time() - t0 < 20 and not ws_url:
            m = re.search(r"DevTools listening on (ws://\S+)", self.proc.stderr.readline() or "")
            ws_url = m and m.group(1)
        if not ws_url:
            await self.__aexit__()
            raise RuntimeError("Chromium başlatılamadı")
        self.ws = await websockets.connect(ws_url, max_size=None)
        target = (await self.cdp("Target.createTarget", {"url": "about:blank"}))["targetId"]
        self.sid = (await self.cdp("Target.attachToTarget", {"targetId": target, "flatten": True}))["sessionId"]
        await self.cdp("Page.enable", session=True)
        await self.cdp("Runtime.enable", session=True)
        await self.cdp("Page.addScriptToEvaluateOnNewDocument", {"source": SPY}, session=True)
        return self

    async def __aexit__(self, *exc):
        try:
            if getattr(self, "ws", None):
                await self.ws.close()
        finally:
            self.proc.kill()
            self.proc.wait()
            shutil.rmtree(self.tmp, ignore_errors=True)

    async def cdp(self, method, params=None, session=False):
        self.seq += 1
        my = self.seq
        msg = {"id": my, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = self.sid
        await self.ws.send(json.dumps(msg))
        while True:
            data = json.loads(await self.ws.recv())
            if data.get("id") == my:
                if "error" in data:
                    raise RuntimeError(f"{method}: {data['error']}")
                return data.get("result", {})

    async def ev(self, expr):
        r = await self.cdp("Runtime.evaluate", {"expression": expr, "awaitPromise": True,
                                                "returnByValue": True, "userGesture": True}, session=True)
        if r.get("exceptionDetails"):
            d = r["exceptionDetails"]
            raise RuntimeError((d.get("exception", {}).get("description") or d.get("text") or "JS hatası")[:200])
        return r["result"].get("value")

    async def until(self, expr, timeout=15):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                if await self.ev(expr):
                    return True
            except RuntimeError:
                pass
            await asyncio.sleep(0.1)
        return False

    async def goto(self, url):
        await self.cdp("Page.navigate", {"url": url}, session=True)
        await asyncio.sleep(0.3)
        if not await self.until("!!(window.Voice && window.Memory && window.__spy && document.readyState === 'complete')", 20):
            raise RuntimeError(f"{url} yüklenmedi (Voice/Memory hazır değil)")


async def _speak_probe(b, url, text):
    await b.goto(url)
    await b.ev("document.body.click(); true")              # the one click that unlocks audio
    await b.ev(f"window.Voice.playGeminiAudio({json.dumps(text)}); true")
    for i in range(300):                                    # up to 30 s for a real TTS round trip
        await asyncio.sleep(0.1)
        spy = await b.ev("window.__spy")
        if spy["speakStatus"] or (spy["speak"] == 0 and i > 25):
            break
    return await b.ev("window.__spy")


async def _mute_run(chrome, base):
    async with Browser(chrome) as b:
        muted = await _speak_probe(b, base + "/?mute=1", "Sessiz mod testi.")
        loud = await _speak_probe(b, base + "/", "Ses testi.")
        return muted, loud


def check_mute(base, use_browser=True):
    name = "?mute=1 Gemini sesini susturur, tarayıcı sesi yok"
    js = open(os.path.join(VIEWER, "voice.js"), encoding="utf-8").read()
    native = [fn for fn in os.listdir(VIEWER) if fn.endswith((".js", ".html")) and
              re.search(r"speechSynthesis|SpeechSynthesisUtterance",
                        open(os.path.join(VIEWER, fn), encoding="utf-8", errors="replace").read())]
    if native:
        C.fail(name, "tarayıcının kendi sesi kullanılıyor: " + ", ".join(native))
        return
    fn = re.search(r"async function playGeminiAudio\(text\) \{\n(.*?)\n", js)
    if not fn or "mute" not in fn.group(1):
        C.fail(name, "mute kontrolü playGeminiAudio'nun ilk satırında değil")
        return
    chrome = find_chromium()
    if not use_browser or not chrome:
        C.warn(name, "kod doğrulandı ama canlı tarayıcı testi atlandı (Chromium yok ya da --no-browser)")
        return
    try:
        muted, loud = asyncio.run(_mute_run(chrome, base))
    except Exception as e:
        C.fail(name, f"başsız Chromium testi çalışmadı: {e}")
        return
    if muted["speak"] != 0 or muted["synth"] or loud["synth"]:
        C.fail(name, f"?mute=1 ile /speak çağrısı={muted['speak']}, speechSynthesis={muted['synth'] + loud['synth']}")
    elif loud["speak"] < 1 or 200 not in loud["speakStatus"]:
        C.fail(name, f"sessiz mod olmadan Gemini sesi çalmadı: /speak={loud['speak']} durum={loud['speakStatus']}")
    else:
        C.ok(name, f"Chromium: ?mute=1 → 0 /speak (açılış selamı dahil); normal → {loud['speak']} /speak "
                   f"(Gemini, HTTP 200); speechSynthesis 0")


# ---------------------------------------------------------------------------- 11. Hafıza UI + live galaxy
async def _memory_ui_run(chrome, base, token):
    """Real galaxy page: Hafıza drawer lists a capture, its Sil button deletes it, the star dissolves and
    leaves the live graph without a reload, and the Gemini confirmation goes through /speak."""
    out = {}
    async with Browser(chrome) as b:
        await b.goto(base + "/galaxy.html?mute=1")         # mute: this check must not need TTS quota
        await b.ev("window.__marker = 1; true")             # survives only if the page never reloads
        r = post(base, "/remember", {"text": f"Hafıza arayüz testi {token}: geçici not.", "title": f"Arayüz {token}"})
        cap = r.json()["capture"]
        out["file"] = cap["filename"]
        path = "captures/" + cap["filename"]
        await b.ev("Memory.changed({capture: true, removed: [], count: 1}); true")
        out["added"] = await b.until(f"__galaxy.nodes.some(n => n.path === {json.dumps(path)})", 15)
        await b.ev("document.getElementById('memBtn').click(); true")
        sel = f"#memList .memItem[data-file={json.dumps(cap['filename'])}]"
        out["listed"] = await b.until(f"!!document.querySelector({json.dumps(sel)})", 10)
        out["meta"] = await b.ev(f"document.querySelector({json.dumps(sel + ' .meta')})?.textContent || ''")
        await b.ev("window.__spy.speak = 0; true")
        await b.ev(f"""(() => {{ const n = __galaxy.nodes.find(n => n.path === {json.dumps(path)});
            window.__dissolveSeen = false;
            const tick = () => {{ if (n && n.__glow && n.__glow.material.opacity < 0.5) window.__dissolveSeen = true;
                                 else if (!window.__dissolveSeen) requestAnimationFrame(tick); }};
            requestAnimationFrame(tick);
            document.querySelector({json.dumps(sel + ' .del')}).click(); return true; }})()""")
        out["dissolved"] = await b.until("window.__dissolveSeen === true", 5)
        out["removed"] = await b.until(f"!__galaxy.nodes.some(n => n.path === {json.dumps(path)})", 10)
        out["gone_from_list"] = await b.until(f"!document.querySelector({json.dumps(sel)})", 5)
        out["no_reload"] = await b.ev("window.__marker === 1")
        out["file_gone"] = not os.path.exists(os.path.join(CAPTURES, cap["filename"]))
        out["confirm_text"] = await b.ev("(() => { document.getElementById('memReset').disabled = false;"
                                         " document.getElementById('memReset').click();"
                                         " return document.querySelector('#memConfirm.show p')?.textContent || ''; })()")
        await b.ev("document.getElementById('memNo').click(); true")   # never reset from the UI test
    return out


def check_memory_ui(base, use_browser=True):
    name = "Hafıza çekmecesi: listele → Sil → galakside söner ve kalkar"
    chrome = find_chromium()
    if not use_browser or not chrome:
        C.warn(name, "tarayıcı testi atlandı (Chromium yok ya da --no-browser)")
        return
    token = "arayuz" + uuid.uuid4().hex[:6]
    try:
        o = asyncio.run(_memory_ui_run(chrome, base, token))
    except Exception as e:
        C.fail(name, f"{type(e).__name__}: {e}")
        return
    finally:
        for fn in os.listdir(CAPTURES) if os.path.isdir(CAPTURES) else []:
            if token in fn:                                 # never leave the test note behind
                requests.delete(f"{base}/remember/{fn}", headers={"Origin": base, "Sec-Fetch-Site": "same-origin"}, timeout=10)
    bad = [k for k in ("added", "listed", "dissolved", "removed", "gone_from_list", "no_reload", "file_gone") if not o.get(k)]
    if "token" not in o.get("meta", "") or "karakter" not in o.get("meta", ""):
        bad.append("token/karakter bilgisi")
    if o.get("confirm_text") != "Tüm kayıtlı hafızayı silmek istediğinizden emin misiniz?":
        bad.append(f"onay metni ({o.get('confirm_text')!r})")
    if bad:
        C.fail(name, "başarısız adımlar: " + ", ".join(bad))
    else:
        C.ok(name, f"Chromium: eklendi → listede ({o['meta']}) → Sil → söndü → grafikten çıktı, sayfa yenilenmedi; "
                   "sıfırlama onayı doğru metinle açıldı")


# ---------------------------------------------------------------------------- 12. platform + window focus
def check_platform():
    import controller
    expect = "windows" if (sys.platform.startswith("win") or os.name == "nt") else \
        "linux" if sys.platform.startswith("linux") else "macos" if sys.platform == "darwin" else sys.platform
    got = controller.detect_platform()
    if got != expect or controller.PLATFORM != got:
        C.fail("İşletim sistemi algılama", f"beklenen {expect}, controller {got}/{controller.PLATFORM}")
    elif got not in ("windows", "linux"):
        C.warn("İşletim sistemi algılama", f"{got}: yalnızca Windows 11 ve Linux hedefleniyor")
    else:
        extra = ""
        if got == "linux":
            tools = [t for t in ("wmctrl", "xdotool") if shutil.which(t)]
            extra = f" · oturum {controller.SESSION} · araçlar: {', '.join(tools) or 'YOK'}"
            if not tools:
                C.fail("İşletim sistemi algılama", "linux ama wmctrl/xdotool yok: sudo apt install wmctrl xdotool")
                return
        C.ok("İşletim sistemi algılama", f"sys.platform={sys.platform}, os.name={os.name} → {got}{extra}")


def check_focus():
    import controller
    name = "Pencere odaklama (controller.focus_window)"
    try:
        wins = controller.list_windows()
        act = controller.active_window()
        if act:                                   # re-focus the window that is already in front: real call, no visible change
            res = controller.focus_window(window_id=act["id"])
        elif wins:
            res = {"ok": True, "found": True, "method": "list-only", "title": wins[0]["title"]}
        else:
            res = {"ok": False, "found": False}
        jarvis = [w["title"] for w in wins if re.search(controller.JARVIS_TITLE, w["title"], re.I)]
    except Exception as e:
        C.fail(name, f"{type(e).__name__}: {e}")
        return
    if not res.get("ok"):
        C.fail(name, f"etkin pencere bulunamadı/odaklanamadı ({len(wins)} pencere)")
    else:
        C.ok(name, f"{controller.PLATFORM}: {len(wins)} pencere listelendi, “{res['title'][:40]}” → {res['method']}; "
                   + (f"Jarvis penceresi: “{jarvis[0][:40]}”" if jarvis else "Jarvis penceresi şu an açık değil (daemon gerekince açar)"))


# ---------------------------------------------------------------------------- 13. mute state
def check_unmute(base):
    name = "POST /unmute sessiz modu kapatır (true → false)"
    try:
        a = post(base, "/mute", {}).json()
        b = post(base, "/unmute", {}).json()
        c = requests.get(base + "/wake/state", timeout=5).json()
    except Exception as e:
        C.fail(name, str(e))
        return
    if a.get("muted") is True and b.get("muted") is False and c.get("muted") is False:
        C.ok(name, "muted: true → false (GET /wake/state ile doğrulandı)")
    else:
        C.fail(name, f"/mute→{a.get('muted')}, /unmute→{b.get('muted')}, durum→{c.get('muted')}")


# ---------------------------------------------------------------------------- 14. daemon: mic + live wake word through the APIs
def check_daemon(base):
    name = "daemon.py: mikrofon + “Hey Jarvis”/“Tahta” Groq üzerinden tanınıyor"
    try:
        import speech_recognition  # noqa: F401  (energy detection only)
        import sounddevice as sd
        import daemon
        from brain import split_wake
    except Exception as e:
        C.fail(name, f"içe aktarılamadı: {e}")
        return
    try:
        mic = sd.query_devices(kind="input")["name"]
        rec = speech_recognition.Recognizer()
        with daemon.SoundDeviceMic() as src:          # the daemon's real microphone path (energy only)
            rec.adjust_for_ambient_noise(src, duration=0.5)
        mic += f", eşik {rec.energy_threshold:.0f}"
    except Exception as e:
        mic = None
        C.fail("Mikrofon (daemon.SoundDeviceMic)", f"{type(e).__name__}: {e}")
    # Real chain without a human: Gemini says the wake phrase, Groq transcribes it, daemon's rule must fire.
    j, heard = daemon.Jarvis(base), []
    for phrase in ("Hey Jarvis.", "Tahta."):
        try:
            r = post(base, "/speak", {"text": phrase}, timeout=60)
            r.raise_for_status()
            text = j.transcribe(r.content)
        except Exception as e:
            C.fail(name, f"{phrase!r}: ses/çeviri zinciri çalışmadı: {e}")
            return
        heard.append((phrase, text, split_wake(text)[0]))
    bad = [f"{p!r}→{t!r}" for p, t, ok in heard if not ok]
    neg = [t for t in ("Tahtaya bakın.", "Bugün Jarvis'ten bahsettik.") if split_wake(t)[0]]
    running = False
    try:
        pid = int(open(daemon.PID_FILE).read().strip())
        os.kill(pid, 0)
        running = True
    except (OSError, ValueError):
        pass
    if bad or neg:
        C.fail(name, ("tanınmadı: " + ", ".join(bad) if bad else "") + (" yanlış uyandırma: " + ", ".join(neg) if neg else ""))
    else:
        C.ok(name, " · ".join(f"Gemini “{p}” → Groq “{t}”" for p, t, _ in heard)
             + f" · mikrofon: {mic or 'yok'} · servis {'çalışıyor' if running else 'çalışmıyor'}")
    if not running:
        C.warn("daemon.py çalışmıyor", "./jarvis-baslat.sh onu da başlatır (ya da: .venv/bin/python daemon.py)")


# ---------------------------------------------------------------------------- 15. wake chain in a real page
async def _wake_run(chrome, base):
    async with Browser(chrome) as b:
        await b.goto(base + "/?mute=1")
        await b.until("true", 0.1)
        ok_sse = False
        for _ in range(50):                               # page reported ?mute=1 and opened /events
            st = requests.get(base + "/wake/state", timeout=5).json()
            if st.get("muted") and st.get("pages", 0) >= 1:
                ok_sse = True
                break
            await asyncio.sleep(0.1)
        await b.ev("document.body.click(); window.__spy.speak = 0; window.__spy.texts = []; window.__spy.speakStatus = []; true")
        w = post(base, "/wake", {"text": "Hey Jarvis"}).json()
        await b.until("Voice.state.listening === true", 8)
        await b.until("window.__spy.speakStatus.length > 0", 30)
        await b.until("document.getElementById('status').dataset.mode === 'listening'", 15)   # after "Dinliyorum"
        page = await b.ev("({url: location.search, listening: Voice.state.listening, awake: Voice.state.awake,"
                          " status: document.getElementById('statusText').textContent,"
                          " mode: document.getElementById('status').dataset.mode, spy: window.__spy})")
        st = requests.get(base + "/wake/state", timeout=5).json()
        await b.ev("Voice.stopListening(); true")
        return ok_sse, w, page, st


def check_wake_chain(base, use_browser=True):
    name = "Uyandırma zinciri: /wake → sesi aç → dinlemeye geç → “Dinliyorum, Hocam.” (Gemini)"
    chrome = find_chromium()
    if not use_browser or not chrome:
        C.warn(name, "tarayıcı testi atlandı (Chromium yok ya da --no-browser)")
        return
    try:
        ok_sse, w, page, st = asyncio.run(_wake_run(chrome, base))
    except Exception as e:
        C.fail(name, f"{type(e).__name__}: {e}")
        return
    spy = page["spy"]
    if ok_sse and page["mode"] != "listening" and st.get("claimed") == w.get("seq") and not spy["texts"]:
        # The wake WAS handled, by another open Jarvis tab (the teacher's own browser), not the test page.
        C.warn(name, f"uyandırmayı açık olan başka bir Jarvis sekmesi üstlendi (sesli={bool(st.get('spoken'))}; "
                     "sessizse daemon.py çalar) — test sayfası sınanamadı; o sekmeyi kapatıp tekrar deneyin")
        return
    problems = []
    if not ok_sse:
        problems.append("sayfa ?mute=1 bildirmedi ya da /events bağlanmadı")
    if "mute=1" in page["url"]:
        problems.append("?mute=1 adresten kalkmadı")
    if st.get("muted"):
        problems.append("sunucu hâlâ sessiz modda")
    if not page["listening"] or page["mode"] != "listening":
        problems.append(f"dinlemeye geçmedi (mod={page['mode']})")
    if "Dinliyorum, Hocam." not in spy["texts"] or 200 not in spy["speakStatus"]:
        problems.append(f"Gemini sesi yok (/speak metinleri={spy['texts']}, durum={spy['speakStatus']})")
    if spy["synth"]:
        problems.append("tarayıcının kendi sesi kullanıldı")
    if st.get("acked") != w.get("seq") or not st.get("spoken"):
        problems.append("sayfa uyandırmayı onaylamadı")
    if not st.get("page_listening"):
        problems.append("sunucu sayfanın dinlediğini bilmiyor (daemon duraklamaz)")
    if problems:
        C.fail(name, "; ".join(problems))
    else:
        C.ok(name, f"Chromium: ?mute=1 kalktı, durum “{page['status']}”, /speak “Dinliyorum, Hocam.” → 200, "
                   "sunucu: muted=false, page_listening=true")


# ---------------------------------------------------------------------------- 16. computer use
def check_pyautogui():
    name = "pyautogui kurulu, FAILSAFE etkin"
    try:
        import controller
        g = controller._gui()
    except Exception as e:
        C.fail(name, f"{type(e).__name__}: {e} — pip install -r requirements.txt")
        return
    if g.FAILSAFE is not True or g.PAUSE != controller.GUI_PAUSE or controller.GUI_PAUSE != 0.5:
        C.fail(name, f"FAILSAFE={g.FAILSAFE}, PAUSE={g.PAUSE} (beklenen True / 0.5)")
        return
    real_pos = g.position                         # prove the corner abort fires, without moving the real mouse
    try:
        g.position = lambda *a, **k: g.Point(0, 0)
        try:
            g.failSafeCheck()
            fired = False
        except g.FailSafeException:
            fired = True
    finally:
        g.position = real_pos
    if not fired:
        C.fail(name, "fare köşedeyken FailSafeException gelmedi")
    else:
        C.ok(name, f"pyautogui {g.__version__} · FAILSAFE=True (köşe → FailSafeException doğrulandı) · PAUSE={g.PAUSE}s · ekran {g.size()[0]}×{g.size()[1]}")


def check_screenshot():
    name = "Ekran görüntüsü (controller.capture_screen)"
    try:
        import io
        import controller
        from PIL import Image
        t = time.time()
        shot = controller.capture_screen()
        ms = int((time.time() - t) * 1000)
        im = Image.open(io.BytesIO(shot["bytes"]))
        im.load()
        lo, hi = im.convert("L").getextrema()
    except Exception as e:
        C.fail(name, f"{type(e).__name__}: {e}")
        return
    if im.size != tuple(shot["image_size"]) or min(im.size) < 200:
        C.fail(name, f"bozuk görüntü: {im.size}")
    elif hi - lo < 10:
        C.fail(name, f"görüntü tek renk (parlaklık {lo}-{hi}): ekran yakalanamıyor olabilir (Wayland?)")
    else:
        C.ok(name, f"{im.size[0]}×{im.size[1]} {shot['mime']} · {len(shot['bytes']) // 1024} KB · {ms} ms · "
                   f"ekran {shot['screen_size'][0]}×{shot['screen_size'][1]} · diske yazılmadı")


def _fake_page():
    """A synthetic 'YouTube-like' page with known element positions (no screen, no local OCR)."""
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", (1280, 720), "white")
    d = ImageDraw.Draw(im)
    try:
        f = ImageFont.load_default(size=26)
    except TypeError:
        f = ImageFont.load_default()
    d.rectangle([0, 0, 1280, 70], fill=(245, 245, 245))
    d.text((24, 20), "VideoTüp", fill=(200, 0, 0), font=f)
    search = (420, 15, 860, 55)
    d.rounded_rectangle(search, 20, outline=(160, 160, 160), width=2, fill="white")
    d.text((440, 21), "Ara", fill=(130, 130, 130), font=f)
    d.rectangle([862, 15, 930, 55], outline=(160, 160, 160), width=2, fill=(240, 240, 240))
    d.text((1120, 20), "Oturum aç", fill=(6, 95, 212), font=f)
    channel = (140, 330, 330, 365)
    d.ellipse([60, 320, 120, 380], fill=(30, 140, 60))
    d.text((140, 333), "Evrim Ağacı", fill=(20, 20, 20), font=f)
    d.text((140, 400), "Hücre Bölünmesi: Mitoz ve Mayoz", fill=(20, 20, 20), font=f)
    d.rectangle([700, 300, 1180, 570], fill=(60, 60, 60))
    import io
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue(), {"search": search, "channel": channel}


def check_vision_locate():
    name = "Gemini görsel konum bulma (find_element_on_screen)"
    import brain
    try:
        png, where = _fake_page()
        t = time.time()
        hit = brain.locate_on_image(png, "image/png", "Ara or Search bar")
        hit2 = brain.locate_on_image(png, "image/png", "Evrim Ağacı")
        miss = brain.locate_on_image(png, "image/png", "a purple elephant riding a bicycle")
        sec = time.time() - t
    except Exception as e:
        C.fail(name, f"{type(e).__name__}: {e}")
        return

    def inside(h, box, pad=25):
        if not h.get("found"):
            return None
        ymin, xmin, ymax, xmax = h["box_2d"]
        x, y = (xmin + xmax) / 2 * 1280 / 1000, (ymin + ymax) / 2 * 720 / 1000
        ok = box[0] - pad <= x <= box[2] + pad and box[1] - pad <= y <= box[3] + pad
        return ok, round(x), round(y)

    a, b = inside(hit, where["search"]), inside(hit2, where["channel"])
    if not a or not a[0]:
        C.fail(name, f"arama çubuğu yanlış/bulunamadı: {hit}")
    elif not b or not b[0]:
        C.fail(name, f"“Evrim Ağacı” yanlış/bulunamadı: {hit2}")
    elif miss.get("found"):
        C.fail(name, f"olmayan öğe 'bulundu' (uydurma konum): {miss}")
    else:
        C.ok(name, f"yapay sayfada arama çubuğu → ({a[1]}, {a[2]}), “Evrim Ağacı” → ({b[1]}, {b[2]}), "
                   f"olmayan öğe → found=false · 3 çağrı {sec:.1f} sn · yerel OCR yok")


def check_sequence():
    name = "Çok adımlı [ACTION] dizisi (deneme modu)"
    import brain
    import controller
    plan = """[ACTION: OPEN_APP, NAME: chrome]
[ACTION: TYPE_AND_ENTER, TEXT: youtube.com]
[ACTION: PRESS, KEYS: ctrl+l]
[ACTION: TYPE_AND_ENTER, TEXT: Evrim Ağacı hücre bölünmesi]
[ACTION: SCROLL, AMOUNT: -300]"""
    old = controller.DRY_RUN
    controller.DRY_RUN = True                     # log only: no app opens, nothing is typed or scrolled
    try:
        cfg = {**brain.load_config(), "youtube_preflight": False}
        tags = brain.parse_tags(plan)
        r = brain.execute_tags(tags, cfg)
        risky = brain.execute_tags(brain.parse_tags('[ACTION: FIND_AND_CLICK, TARGET: "Abone ol"]'), cfg)
        bad_app = brain.execute_tags(brain.parse_tags("[ACTION: OPEN_APP, NAME: rm -rf]"), cfg)
        fake = [("FlowingTR", [("FlowingTR", 0)], "/x/flowingtr.desktop"),
                ("Konsol", [("Konsol", 0), ("terminal", -25)], None),          # blocked category
                ("Hesap Makinesi", [("Hesap Makinesi", 0)], "/x/calc.desktop")]
        app_ok = controller.find_app("flowingtr 3.2 uygulamasını", fake)[1] == "/x/flowingtr.desktop" and \
            controller.find_app("hesap makinesini", fake)[0] == "Hesap Makinesi"
        try:
            controller.find_app("terminal", fake)
            app_ok = False
        except controller.ControllerError:
            pass
        app_count = len(controller._launchers())
    except Exception as e:
        C.fail(name, f"{type(e).__name__}: {e}")
        return
    finally:
        controller.DRY_RUN = old
    steps = "\n".join(r.get("steps", []))
    want = ["open app chrome", "type 'youtube.com'", "hotkey ctrl+l", "paste 27 chars", "scroll -3"]
    missing = [w for w in want if w not in steps]
    if len(tags) != 5 or not r["ok"] or r.get("completed", []).__len__() != 5 or missing:
        C.fail(name, f"ok={r['ok']} {r.get('error', '')} eksik adımlar: {missing}")
    elif risky["ok"] or bad_app["ok"]:
        C.fail(name, "riskli hedef ya da izinsiz uygulama engellenmedi")
    elif not app_ok or not app_count:
        C.fail(name, f"uygulama adı eşleştirme bozuk (kurulu başlatıcı: {app_count})")
    else:
        C.ok(name, "5 etiket ayrıştırıldı ve sırayla yürütüldü (makbuz: 5/5, dry_run) · “Abone ol” tıklaması reddedildi · "
                   f"bilinmeyen/terminal uygulaması reddedildi · {app_count} kurulu uygulama adıyla açılabilir")


def main():
    ap = argparse.ArgumentParser(description="Jarvis canlı sistem kontrolü")
    ap.add_argument("--url", default="http://127.0.0.1:4700")
    ap.add_argument("--no-browser", action="store_true", help="?mute=1 için başsız Chromium testini atla")
    args = ap.parse_args()
    base = args.url.rstrip("/")
    sys.path.insert(0, ROOT)
    print(f"Jarvis preflight → {base}\n")
    if check_server(base):
        graph = check_graph(base)
        check_chat(base, graph)
        check_keys_and_model()
        check_action_tags()
        check_remember(base)
        check_reset(base)
        check_static(base)
        check_security(base)
        check_mute(base, not args.no_browser)
        check_memory_ui(base, not args.no_browser)
        check_platform()
        check_focus()
        check_unmute(base)
        check_daemon(base)
        check_wake_chain(base, not args.no_browser)
        check_pyautogui()
        check_screenshot()
        check_vision_locate()
        check_sequence()
    print(f"\n{C.passed} pass, {C.failed} fail, {C.warned} warn")
    return 1 if C.failed else 0


if __name__ == "__main__":
    sys.exit(main())
