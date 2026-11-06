#!/usr/bin/env python3
"""server.py — Jarvis web server (Flask), http://127.0.0.1:4700 only.

  GET  /                 Jarvis UI (viewer/index.html)
  GET  /galaxy.html      Knowledge Galaxy (3D notes graph)
  POST /jarvis           {"text": "..."}        -> {"reply", "kind": chat|command|agent, ...}
  POST /jarvis/reset     forget the brainstorming memory
  GET  /agent/status     agent + last action state (never contains keys)
  POST /agent/cancel     stop a pending Claude paste / running Abacus agent
  GET  /boot             boot greeting text (persona block in brain.py)
  GET  /settings         key status (set / last 4 chars) + provider, agent mode, model
  POST /settings         save keys/options from the UI into config.json
  POST /settings/test    check the Gemini keys (each one) and the Groq key with free "list models" calls
  GET  /settings/keys    saved Groq key + Gemini key list for the settings modal (same-origin page only)
  POST /update-settings  {"groq_api_key": "...", "gemini_api_keys": ["...", ...]} -> config.json + live key ring
  POST /listen           audio/webm body -> {"text": "..."} (Groq Whisper Large V3, Turkish)
  GET  /remember         memory captures (captures/*.md): filename, title, excerpt, date, index, size
  POST /remember         {"text": "...", "title"?: "..."} -> new captures/<date>-<slug>.md, indexed at once
  DELETE /remember/<filename>   delete one capture (re-index + graph-data.js)
  DELETE /remember/all   delete every capture
  POST /mute | /unmute   server-side mute state (pages opened with ?mute=1 report it; daemon.py unmutes)
  POST /wake             {"text"?} from daemon.py on "Hey Jarvis" / "Tahta": unmute + tell the page to listen
  POST /wake/claim       {"seq"} the first page to claim a wake event handles it (no double speech)
  POST /wake/ack         {"seq", "spoken"} the page played "Dinliyorum, Hocam." (else daemon.py plays it)
  GET  /wake/state       mute / wake / page-listening state (daemon.py, preflight.py)
  POST /ui/state         {"listening": bool} the page's microphone state (daemon pauses while it listens)
  GET  /events           Server-Sent Events: "wake", "unmute" for open pages
  POST /speak            {"text": "..."}        -> audio/wav (Gemini API, Turkish)
  POST /chat             {"question", "session"} -> notes answer for the galaxy page
  POST /chat/reset       {"session"}

Only files inside viewer/ are served. config.json (API keys) lives in the project root and is
never reachable from the browser. All AI work happens in brain.py via cloud APIs.

Run:  python server.py            (JARVIS_DRY_RUN=1 python server.py  -> automation only logged)
"""
import json
import os
import sys
import threading
import time

from flask import Flask, Response, abort, jsonify, request, send_from_directory, stream_with_context

import brain
import controller
import ears

HOST, PORT = "127.0.0.1", 4700
ROOT = os.path.dirname(os.path.abspath(__file__))
VIEWER = os.path.join(ROOT, "viewer")
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 21 * 1024 * 1024   # /listen audio; JSON bodies are capped at 64 KB in guard()
JSON_MAX = 64 * 1024
app.json.ensure_ascii = False


# --------------------------------------------------------------------------
# Guards: only this page, on this machine, may use the API
# --------------------------------------------------------------------------
@app.before_request
def guard():
    if request.host not in ALLOWED_HOSTS:                      # blocks DNS-rebinding
        abort(403)
    api = request.method != "GET" or request.path.startswith(("/agent/", "/settings", "/boot", "/wake"))
    if api:
        origin = request.headers.get("Origin")
        if origin and origin.replace("http://", "") not in ALLOWED_HOSTS:   # blocks cross-site POSTs
            return jsonify(error="İzin verilmeyen kaynak"), 403
    if request.path in ("/settings/keys", "/update-settings", "/events") or request.path.startswith("/remember"):
        # Keys travel only between this server and its own page: refuse any cross-site or no-cors fetch.
        if request.headers.get("Sec-Fetch-Site", "same-origin") != "same-origin":
            return jsonify(error="İzin verilmeyen kaynak"), 403
    if request.path == "/listen":
        if request.method == "POST" and not (request.mimetype or "").startswith("audio/"):
            return jsonify(error="Ses gönderin (Content-Type: audio/...)."), 415
        return None
    if (request.content_length or 0) > JSON_MAX:
        return jsonify(error="İstek çok büyük."), 413
    if request.method == "POST" and not request.is_json:
        return jsonify(error="JSON gönderin (Content-Type: application/json)."), 415


@app.after_request
def headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.errorhandler(brain.BrainError)
def brain_error(e):
    return jsonify(error=str(e), reply="", answer="", nodes=getattr(e, "nodes", [])), e.status


@app.errorhandler(413)
def too_large(e):
    return jsonify(error="İstek çok büyük."), 413


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400)
    return data


# --------------------------------------------------------------------------
# Static: viewer/ only
# --------------------------------------------------------------------------
@app.get("/")
def index():
    return send_from_directory(VIEWER, "index.html")


@app.get("/<path:path>")
def static_files(path):
    if any(part.startswith(".") for part in path.split("/")):
        abort(404)
    return send_from_directory(VIEWER, path)      # safe_join: no escaping viewer/


# --------------------------------------------------------------------------
# Jarvis
# --------------------------------------------------------------------------
@app.post("/jarvis")
def jarvis():
    text = body().get("text")
    if not isinstance(text, str) or not text.strip():
        return jsonify(error="Bir şey söyleyin ya da yazın."), 400
    try:
        return jsonify(brain.handle(text))
    except brain.BrainError:
        raise
    except Exception as e:  # never crash the request thread
        app.logger.exception("jarvis failed")
        return jsonify(error=f"Sunucuda bir hata oluştu ({type(e).__name__}) — terminal günlüğüne bakın."), 500


@app.post("/jarvis/reset")
def jarvis_reset():
    brain.reset_memory()
    return jsonify(ok=True)


@app.get("/agent/status")
def agent_status():
    return jsonify(brain.status())


@app.post("/agent/cancel")
def agent_cancel():
    return jsonify(cancelled=brain.AGENT.cancel(), agent=brain.AGENT.snapshot())


# --------------------------------------------------------------------------
# Settings (API keys entered from the UI; written to config.json, never sent back)
# --------------------------------------------------------------------------
@app.get("/boot")
def boot():
    """The greeting text lives in the persona block of brain.py; the page speaks it after the first click."""
    return jsonify(greeting=brain.BOOT_GREETING, wake_reply=brain.WAKE_REPLY)


@app.get("/settings")
def settings_get():
    return jsonify(brain.public_settings())


@app.post("/settings")
def settings_save():
    return jsonify(brain.save_settings(body()))


@app.get("/settings/keys")
def settings_keys():
    return jsonify(brain.key_settings())


@app.post("/update-settings")
def update_settings():
    return jsonify(brain.update_keys(body()))


def test_all_gemini_keys():
    keys = brain.GEMINI_KEYS.keys()
    if len(keys) <= 1:
        return brain.test_gemini_key()
    results = [(k, brain.test_gemini_key(k)) for k in keys]
    good = [k for k, r in results if r["ok"]]
    bad = ", ".join(brain._key_hint(k) for k, r in results if not r["ok"])
    msg = f"{len(good)}/{len(keys)} anahtar çalışıyor." + (f" Çalışmayan: {bad}." if bad else "")
    return {"ok": bool(good), "message": msg}


@app.post("/settings/test")
def settings_test():
    data = body()
    gem = data.get("gemini_api_key")
    out = {"gemini": brain.test_gemini_key(gem) if isinstance(gem, str) and gem.strip() else test_all_gemini_keys()}
    grq = data.get("groq_api_key")
    if (isinstance(grq, str) and grq.strip()) or not brain.is_placeholder(brain.load_config().get("groq_api_key")):
        out["groq"] = ears.test_groq_key(grq if isinstance(grq, str) else None)
    hf = data.get("huggingface_api_key")
    if (isinstance(hf, str) and hf.strip()) or not brain.is_placeholder(brain.hf_key(brain.load_config())):
        out["huggingface"] = brain.test_hf_key(hf if isinstance(hf, str) else None)
    names = {"gemini": "Gemini", "groq": "Groq", "huggingface": "Hugging Face"}
    out["ok"] = all(r["ok"] for r in out.values())
    out["message"] = " ".join(f"{names[k]}: {r['message']}" for k, r in out.items() if k in names)
    return jsonify(out)


# --------------------------------------------------------------------------
# Listening — Groq Whisper Large V3 (ears.py). The text goes back to the page, which sends it
# through the same flow as typed text (voice routes -> /jarvis or /chat).
# --------------------------------------------------------------------------
@app.post("/listen")
def listen():
    audio = request.get_data(cache=False)
    try:
        return jsonify(ears.transcribe(audio, request.mimetype))
    except brain.BrainError:
        raise
    except Exception as e:
        app.logger.exception("listen failed")
        return jsonify(error=f"Ses metne çevrilemedi ({type(e).__name__})."), 500


# --------------------------------------------------------------------------
# Hafıza (memory captures) — brain.py writes captures/*.md and re-indexes immediately
# --------------------------------------------------------------------------
@app.get("/remember")
def remember_list():
    return jsonify(brain.list_captures())


@app.post("/remember")
def remember_add():
    data = body()
    return jsonify(brain.add_capture(data.get("text"), data.get("title"))), 201


@app.post("/remember/reindex")
def remember_reindex():
    """Re-read notes/ + captures/ from disk (used by preflight.py after restoring backed-up captures)."""
    brain.reindex()
    return jsonify(brain.list_captures())


@app.delete("/remember/all")
def remember_reset():
    return jsonify(brain.reset_captures())


@app.delete("/remember/<path:filename>")
def remember_delete(filename):
    return jsonify(brain.delete_capture(filename))


# --------------------------------------------------------------------------
# Wake word + mute state (daemon.py <-> pages). Plain state, no AI: the wake word itself is transcribed
# by Groq through /listen, the "Dinliyorum, Hocam." reply is Gemini audio from /speak.
# --------------------------------------------------------------------------
UI = {"muted": False, "wake_seq": 0, "wake_at": 0.0, "wake_text": "", "claimed": 0, "acked": 0, "spoken": False,
      "page_listening": False, "page_seen": 0.0}
_UI_COND = threading.Condition()
_EVENTS = []                       # (n, name, data) — short history so a reconnecting page misses nothing
_EVENT_N = 0


def publish(name, data):
    global _EVENT_N
    with _UI_COND:
        _EVENT_N += 1
        _EVENTS.append((_EVENT_N, name, data))
        del _EVENTS[:-50]
        _UI_COND.notify_all()


def ui_state():
    with _UI_COND:
        return {**UI, "now": time.time(), "pages": _PAGES[0]}


_PAGES = [0]


@app.get("/events")
def events():
    def gen():
        with _UI_COND:
            _PAGES[0] += 1
            last = _EVENT_N
        try:
            yield "retry: 2000\n\n"
            while True:
                with _UI_COND:
                    _UI_COND.wait_for(lambda: _EVENT_N > last, timeout=15)
                    new = [e for e in _EVENTS if e[0] > last]
                    UI["page_seen"] = time.time()
                if not new:
                    yield ": ping\n\n"                   # keeps the connection (and page_seen) alive
                    continue
                for n, name, data in new:
                    last = n
                    yield f"id: {n}\nevent: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        finally:
            with _UI_COND:
                _PAGES[0] -= 1
    return Response(stream_with_context(gen()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.post("/mute")
def mute():
    with _UI_COND:
        UI["muted"] = True
    return jsonify(ui_state())


@app.post("/unmute")
def unmute():
    with _UI_COND:
        UI["muted"] = False
    publish("unmute", {})
    return jsonify(ui_state())


@app.post("/wake")
def wake():
    text = body().get("text") or ""
    if not isinstance(text, str):
        abort(400)
    woke, rest = brain.split_wake(text)
    with _UI_COND:
        UI.update(muted=False, wake_seq=UI["wake_seq"] + 1, wake_at=time.time(), wake_text=rest[:500],
                  spoken=False)
        seq = UI["wake_seq"]
    publish("unmute", {})
    publish("wake", {"seq": seq, "text": rest[:500], "reply": brain.WAKE_REPLY})
    return jsonify({**ui_state(), "seq": seq, "reply": brain.WAKE_REPLY})


@app.post("/wake/claim")
def wake_claim():
    seq = body().get("seq")
    with _UI_COND:
        ok = isinstance(seq, int) and seq == UI["wake_seq"] and UI["claimed"] < seq
        if ok:
            UI["claimed"] = seq
    return jsonify(ok=ok)


@app.post("/wake/ack")
def wake_ack():
    data = body()
    with _UI_COND:
        if data.get("seq") == UI["wake_seq"]:
            UI.update(acked=UI["wake_seq"], spoken=bool(data.get("spoken")))
    return jsonify(ui_state())


@app.get("/wake/state")
def wake_state():
    return jsonify(ui_state())


@app.post("/ui/state")
def page_state():
    with _UI_COND:
        UI["page_listening"] = bool(body().get("listening"))
        UI["page_seen"] = time.time()
    return jsonify(ok=True)


# --------------------------------------------------------------------------
# Speech
# --------------------------------------------------------------------------
@app.post("/speak")
def speak():
    text = body().get("text")
    if not isinstance(text, str) or not text.strip():
        return jsonify(error="Okunacak metin yok."), 400
    try:
        return Response(brain.speak(text), mimetype="audio/wav")
    except brain.BrainError:
        raise
    except Exception as e:
        app.logger.exception("speak failed")
        return jsonify(error=f"Ses üretilirken hata oluştu ({type(e).__name__})."), 500


# --------------------------------------------------------------------------
# Knowledge Galaxy notes Q&A
# --------------------------------------------------------------------------
@app.post("/chat")
def chat():
    data = body()
    question = data.get("question")
    if not isinstance(question, str) or not question.strip():
        return jsonify(error="Önce bir soru sorun.", answer="", nodes=[]), 400
    session = str(data.get("session") or "default")[:64]
    try:
        return jsonify(brain.notes_chat(question.strip()[:500], session))
    except brain.BrainError:
        raise
    except Exception as e:
        app.logger.exception("chat failed")
        return jsonify(error=f"Sunucuda bir hata oluştu ({type(e).__name__}).", answer="", nodes=[]), 500


@app.post("/chat/reset")
def chat_reset():
    brain.notes_reset(str(body().get("session") or "default")[:64])
    return jsonify(ok=True)


def main():
    if hasattr(__import__("signal"), "SIGUSR1"):          # kill -USR1 <pid> -> thread stacks in data/sunucu.log
        import faulthandler
        import signal
        faulthandler.register(signal.SIGUSR1, all_threads=True)
    notes = brain.init()
    cfg = brain.load_config()
    if cfg.get("dry_run"):
        controller.DRY_RUN = True
    caps = sum(1 for n in notes.notes if n.get("capture"))
    print(f"Indexed {len(notes.nodes) - caps} notes + {caps} memory captures -> viewer/graph-data.js")
    print(f"AI: {cfg.get('ai_provider', 'gemini')} | agent_mode: {cfg.get('agent_mode', 'claude_desktop')}"
          f" | automation: {'DRY RUN (nothing is clicked)' if controller.DRY_RUN else 'LIVE'}")
    print(f"Jarvis: http://{HOST}:{PORT}   Galaksi: http://{HOST}:{PORT}/galaxy.html   (Ctrl+C ile durdurun)")
    app.run(host=HOST, port=PORT, threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    sys.exit(main())
