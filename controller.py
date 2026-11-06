#!/usr/bin/env python3
"""controller.py — OS-level control for Jarvis (pyautogui + standard library). No AI model runs here:
find_element_on_screen() only captures the screen and hands the image to brain.locate_on_image()
(Gemini vision API). No local OCR, no local model.

Computer use:  move_mouse_and_click(x, y), type_text(text, press_enter), scroll_screen(amount),
               press_keys("ctrl+l"), open_app("chrome"), capture_screen(), find_element_on_screen(target),
               find_and_click(target)

Teacher mode:  open_textbook(subject), scroll(direction), click_center(), search_and_play_youtube(query)
Agent mode:    deploy_to_claude(english_prompt)
Windows:       list_windows(), focus_window(pattern), focus_jarvis(url)  — used by daemon.py on "Hey Jarvis"

Cross-platform: PLATFORM is "windows" (Windows 11, developer PC), "linux" (smartboard) or "macos".
  * Windows: Win32 API through ctypes (EnumWindows / SetForegroundWindow), os.startfile, pyautogui input.
  * Linux:   wmctrl / xdotool for windows (X11), xdg-open / gtk-launch for apps, pyautogui input.
             Under Wayland, wmctrl/xdotool only see XWayland windows (Chrome/Chromium run as XWayland by default).

Safety:
  * pyautogui FAILSAFE is on: slam the mouse into any screen corner to abort a running automation.
  * Dry run: set JARVIS_DRY_RUN=1 (or "dry_run": true in config.json) and every step is only logged,
    nothing is clicked, typed or opened. Each public function returns the list of steps it took.
  * Text is entered by clipboard paste, so Turkish characters (ç, ğ, ı, ö, ş, ü) work everywhere.

Optional config.json keys (all have defaults):
  "textbooks": {"matematik": "https://...", "fizik": "textbooks/fizik-10.pdf"}
  "youtube_click": "position" | "resolve"      "youtube_first_video": [0.30, 0.36]
  "youtube_load_wait_s": 6, "youtube_results_wait_s": 4
  "claude_launch": "search" | "direct"         "claude_wait_s": 6
  "claude_new_chat_hotkey": ["ctrl", "n"]      "claude_input_xy": [0.5, 0.88]
"""
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import deque

ROOT = os.path.dirname(os.path.abspath(__file__))
TEXTBOOK_DIR = os.path.join(ROOT, "textbooks")
SYSTEM = platform.system()                      # "Linux", "Darwin", "Windows"


def detect_platform():
    """'windows' | 'linux' | 'macos' | other sys.platform value — from sys.platform AND os.name."""
    if sys.platform.startswith("win") or os.name == "nt":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    return sys.platform


PLATFORM = detect_platform()
SESSION = (os.environ.get("XDG_SESSION_TYPE") or ("wayland" if os.environ.get("WAYLAND_DISPLAY") else "x11")) \
    if PLATFORM == "linux" else PLATFORM
MOD = "command" if SYSTEM == "Darwin" else "ctrl"
WHEEL = {"Windows": 120, "Darwin": 3}.get(SYSTEM, 1)   # pyautogui scroll units differ per OS
TEXTBOOK_EXT = (".pdf", ".epub", ".html", ".htm", ".pptx", ".ppt", ".docx", ".odp", ".url", ".txt")

DRY_RUN = os.environ.get("JARVIS_DRY_RUN") == "1"
ACTIONS_LOG = deque(maxlen=300)                  # (timestamp, step) for debugging / tests
_tls = threading.local()
_LOCK = threading.Lock()                         # one OS automation at a time
GUI_PAUSE = 0.5


class ControllerError(Exception):
    pass


# --------------------------------------------------------------------------
# Primitives — the ONLY places that touch the OS. Each one logs, and does nothing in dry run.
# --------------------------------------------------------------------------
def _step(text):
    ACTIONS_LOG.append((time.time(), text))
    steps = getattr(_tls, "steps", None)
    if steps is not None:
        steps.append(text)
    print(f"[controller]{' [dry-run]' if DRY_RUN else ''} {text}")


def _gui():
    try:
        import pyautogui
    except Exception as e:  # missing package or no display (e.g. running headless / over SSH)
        raise ControllerError(f"pyautogui kullanılamıyor ({type(e).__name__}: {e}). "
                              "Bir masaüstü oturumunda 'pip install -r requirements.txt' ile kurun.")
    pyautogui.FAILSAFE = True          # mouse into any screen corner -> pyautogui.FailSafeException
    pyautogui.PAUSE = GUI_PAUSE        # pause after every pyautogui call
    return pyautogui


def _screen():
    if DRY_RUN:
        return 1920, 1080
    w, h = _gui().size()
    return int(w), int(h)


def _sleep(seconds):
    _step(f"wait {seconds:g}s")
    if not DRY_RUN:
        time.sleep(seconds)


def _press(key):
    _step(f"press {key}")
    if not DRY_RUN:
        _gui().press(key)


def _hotkey(*keys):
    _step("hotkey " + "+".join(keys))
    if not DRY_RUN:
        _gui().hotkey(*keys)


def _type_ascii(text):
    _step(f"type {text!r}")
    if not DRY_RUN:
        _gui().write(text, interval=0.04)


def _click(x, y):
    _step(f"click ({x}, {y})")
    if not DRY_RUN:
        _gui().click(x, y)


def _move(x, y):
    _step(f"move ({x}, {y})")
    if not DRY_RUN:
        _gui().moveTo(x, y, duration=0.15)


def _scroll_wheel(clicks):
    _step(f"scroll {clicks:+d}")
    if not DRY_RUN:
        _gui().scroll(clicks * WHEEL)


def _paste(text):
    """Unicode-safe typing: put text on the clipboard, paste it, then restore the old clipboard."""
    _step(f"paste {len(text)} chars: {text[:60]!r}{'…' if len(text) > 60 else ''}")
    if DRY_RUN:
        return
    try:
        import pyperclip
    except ImportError:
        if text.isascii():
            return _gui().write(text, interval=0.01)
        raise ControllerError("Türkçe karakterleri yazmak için pyperclip gerekli: pip install pyperclip")
    try:
        old = pyperclip.paste()
    except Exception:
        old = None
    try:
        pyperclip.copy(text)
    except Exception as e:
        raise ControllerError(f"Panoya yazılamadı ({e}). Linux'ta 'xclip' ya da 'xsel' kurun.")
    time.sleep(0.15)
    _gui().hotkey(MOD, "v")
    time.sleep(0.6)
    if old is not None:
        try:
            pyperclip.copy(old)
        except Exception:
            pass


def _open_url(url):
    _step(f"open url {url}")
    if not DRY_RUN and not webbrowser.open(url, new=2):
        raise ControllerError("Tarayıcı açılamadı.")


def _open_path(path):
    _step(f"open file {os.path.relpath(path, ROOT) if path.startswith(ROOT) else path}")
    if DRY_RUN:
        return
    if SYSTEM == "Windows":
        os.startfile(path)  # noqa: S606 (local file chosen from config/textbooks folder)
    elif SYSTEM == "Darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --------------------------------------------------------------------------
# Windows (pencereler): find a window by title and bring it to the very front
# --------------------------------------------------------------------------
JARVIS_TITLE = r"^(?:Jarvis|Bilgi Galaksisi)(?:\s+[-—–]\s+.*)?$"     # "Jarvis - Google Chrome", "Jarvis — Mozilla Firefox"


def _run(cmd, timeout=5):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _win32():
    import ctypes
    from ctypes import wintypes
    return ctypes, wintypes, ctypes.windll.user32


def list_windows():
    """[{"id": ..., "title": ...}] of visible top-level windows on this OS."""
    if PLATFORM == "windows":
        ctypes, wintypes, user32 = _win32()
        out = []
        proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def cb(hwnd, _):
            if user32.IsWindowVisible(hwnd):
                n = user32.GetWindowTextLengthW(hwnd)
                if n:
                    buf = ctypes.create_unicode_buffer(n + 1)
                    user32.GetWindowTextW(hwnd, buf, n + 1)
                    out.append({"id": int(hwnd), "title": buf.value})
            return True
        user32.EnumWindows(proto(cb), 0)
        return out
    if PLATFORM == "linux":
        if shutil.which("wmctrl"):
            r = _run(["wmctrl", "-l"])
            if r.returncode != 0:
                raise ControllerError(f"wmctrl çalışmadı: {r.stderr.strip()[:120]} (oturum: {SESSION})")
            out = []
            for line in r.stdout.splitlines():
                parts = line.split(None, 3)
                if len(parts) >= 3:
                    out.append({"id": parts[0], "title": parts[3] if len(parts) == 4 else ""})
            return out
        if shutil.which("xdotool"):
            r = _run(["xdotool", "search", "--onlyvisible", "--name", "."])
            out = []
            for wid in r.stdout.split():
                t = _run(["xdotool", "getwindowname", wid]).stdout.strip()
                out.append({"id": wid, "title": t})
            return out
        raise ControllerError("Pencere yönetimi için 'wmctrl' ya da 'xdotool' gerekli: sudo apt install wmctrl xdotool")
    if PLATFORM == "macos":
        r = _run(["osascript", "-e", 'tell application "System Events" to get name of every window of every process'])
        return [{"id": t.strip(), "title": t.strip()} for t in r.stdout.split(",") if t.strip()]
    raise ControllerError(f"Desteklenmeyen işletim sistemi: {PLATFORM}")


def active_window():
    """{"id", "title"} of the focused window, or None."""
    if PLATFORM == "windows":
        ctypes, wintypes, user32 = _win32()
        hwnd = user32.GetForegroundWindow()
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        return {"id": int(hwnd), "title": buf.value} if hwnd else None
    if PLATFORM == "linux" and shutil.which("xdotool"):
        r = _run(["xdotool", "getactivewindow"])
        if r.returncode == 0 and r.stdout.strip():
            wid = r.stdout.strip()
            return {"id": "0x%08x" % int(wid), "title": _run(["xdotool", "getwindowname", wid]).stdout.strip()}
    return None


def _activate(win):
    """Bring one window (from list_windows) to the front. Returns the method used."""
    if PLATFORM == "windows":
        ctypes, wintypes, user32 = _win32()
        hwnd = wintypes.HWND(win["id"])
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)                          # SW_RESTORE
        # Windows only lets the foreground process change focus; a synthetic Alt tap lifts that lock.
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 2, 0)
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0003)       # HWND_TOPMOST, no move/size
        user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0003)       # back to normal z-order, still on top
        user32.BringWindowToTop(hwnd)
        if not user32.SetForegroundWindow(hwnd):
            raise ControllerError("Windows pencereyi öne getirmeyi reddetti.")
        return "win32"
    if PLATFORM == "linux":
        if shutil.which("wmctrl"):
            r = _run(["wmctrl", "-i", "-a", str(win["id"])])     # un-minimise, switch desktop, raise, focus
            if r.returncode == 0:
                return "wmctrl"
        if shutil.which("xdotool"):
            r = _run(["xdotool", "windowactivate", "--sync", str(int(str(win["id"]), 16) if str(win["id"]).startswith("0x") else win["id"])])
            if r.returncode == 0:
                return "xdotool"
        raise ControllerError(f"Pencere öne getirilemedi (oturum: {SESSION}).")
    if PLATFORM == "macos":
        _run(["osascript", "-e", f'tell application "{win["title"]}" to activate'])
        return "osascript"
    raise ControllerError(f"Desteklenmeyen işletim sistemi: {PLATFORM}")


def focus_window(pattern=None, window_id=None):
    """Focus the first window whose title matches `pattern` (regex) or whose id is `window_id`.
    Returns {"ok", "found", "title", "method", "platform"}; never moves the mouse."""
    rx = re.compile(pattern, re.I) if pattern else None
    wins = list_windows()
    win = next((w for w in wins if (window_id is not None and str(w["id"]) == str(window_id))
                or (rx and rx.search(w["title"]))), None)
    if not win:
        return {"ok": False, "found": False, "title": "", "method": "", "platform": PLATFORM}
    _step(f"focus window {win['title']!r}")
    method = "dry-run" if DRY_RUN else _activate(win)
    return {"ok": True, "found": True, "title": win["title"], "method": method, "platform": PLATFORM}


def focus_jarvis(url="http://127.0.0.1:4700/", open_if_missing=True):
    """Bring the Jarvis browser window to the front; open it if no such window exists."""
    res = focus_window(JARVIS_TITLE)
    if res["found"] or not open_if_missing:
        return res
    _open_url(url)
    for _ in range(40):                                        # wait up to ~8 s for the window to appear
        time.sleep(0.2)
        res = focus_window(JARVIS_TITLE)
        if res["found"]:
            res["opened"] = True
            return res
    return {"ok": True, "found": False, "opened": True, "title": "", "method": "browser", "platform": PLATFORM}


def _check(cancel):
    if cancel is not None and cancel.is_set():
        raise ControllerError("İptal edildi.")


class _Run:
    """Collects the steps of one public call and serialises OS automation."""

    def __enter__(self):
        if not _LOCK.acquire(timeout=30):
            raise ControllerError("Başka bir otomasyon hâlâ çalışıyor.")
        _tls.steps = []
        return _tls.steps

    def __exit__(self, *exc):
        _tls.steps = None
        _LOCK.release()
        return False


# --------------------------------------------------------------------------
# Teacher mode
# --------------------------------------------------------------------------
def _fold(s):
    s = s.replace("İ", "i").replace("I", "ı").lower()
    s = s.translate(str.maketrans("çğıöşüâîû", "cgiosuaiu"))
    return re.sub(r"[^a-z0-9]+", "", s)


def find_textbook(subject, books=None):
    """Resolve a spoken subject ("matematik", "10 sınıf fizik") to a URL or a file path."""
    want = _fold(subject)
    if not want:
        raise ControllerError("Hangi dersin kitabını açayım?")
    candidates = []
    for key, target in (books or {}).items():
        candidates.append((_fold(key), str(target)))
    if os.path.isdir(TEXTBOOK_DIR):
        for fn in sorted(os.listdir(TEXTBOOK_DIR)):
            if fn.lower().endswith(TEXTBOOK_EXT):
                candidates.append((_fold(os.path.splitext(fn)[0]), os.path.join(TEXTBOOK_DIR, fn)))
    best = None
    for key, target in candidates:
        if not key:
            continue
        if key == want:
            best = target
            break
        if best is None and (key in want or want in key):
            best = target
    if best is None:
        raise ControllerError(f"“{subject}” için kitap bulunamadı. textbooks klasörüne örneğin "
                              f"'{_fold(subject) or 'ders'}.pdf' koyun ya da config.json'daki textbooks listesine ekleyin.")
    if not re.match(r"https?://", best) and not os.path.isabs(best):
        best = os.path.join(ROOT, best)
    if not re.match(r"https?://", best) and not os.path.exists(best):
        raise ControllerError(f"Kitap dosyası bulunamadı: {os.path.basename(best)}")
    return best


def open_textbook(subject, books=None):
    """Open the textbook for a subject: a URL in the browser, or a local PDF/EPUB/etc. with the OS viewer."""
    target = find_textbook(subject, books)
    with _Run() as steps:
        if target.endswith(".url"):           # Windows-style internet shortcut
            with open(target, encoding="utf-8", errors="replace") as f:
                m = re.search(r"^URL=(.+)$", f.read(), re.M)
            if not m:
                raise ControllerError("Geçersiz .url dosyası.")
            target = m.group(1).strip()
        if re.match(r"https?://", target):
            _open_url(target)
        else:
            _open_path(target)
        return list(steps)


def scroll(direction="aşağı", amount="normal"):
    """Scroll the window under the screen centre. direction: aşağı/down or yukarı/up.
    amount: biraz | normal | çok | en (jump to the very top/bottom)."""
    d = _fold(direction)
    if d in ("asagi", "asagiya", "down", "in"):
        sign = -1
    elif d in ("yukari", "yukariya", "up", "cik"):
        sign = 1
    else:
        raise ControllerError(f"Bilinmeyen yön: {direction}")
    with _Run() as steps:
        w, h = _screen()
        _move(w // 2, h // 2)                 # wheel events go to the window under the pointer
        if amount == "en":
            _press("end" if sign < 0 else "home")
        else:
            clicks = {"biraz": 3, "normal": 8, "çok": 20, "cok": 20}.get(amount, 8)
            _scroll_wheel(sign * clicks)
        return list(steps)


def click_center():
    with _Run() as steps:
        w, h = _screen()
        _click(w // 2, h // 2)
        return list(steps)


def _first_video_id(query):
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)",
                                               "Accept-Language": "tr-TR,tr;q=0.9"})
    with urllib.request.urlopen(req, timeout=10) as r:
        html = r.read().decode("utf-8", errors="replace")
    m = re.search(r'"videoRenderer":\{"videoId":"([A-Za-z0-9_-]{11})"', html) or \
        re.search(r'"videoId":"([A-Za-z0-9_-]{11})"', html)
    if not m:
        raise ControllerError("YouTube sonuçlarında video bulunamadı.")
    return m.group(1)


_REACH_CACHE = {"t": 0.0, "ok": None}


def youtube_reachable(timeout=4.0):
    """Quick network check: school/lab networks often block YouTube, and then every keystroke of the
    automation would land on a blank page. Returns True when www.youtube.com answers.
    `timeout` is a hard total deadline (urllib alone retries every DNS address, which can take 30 s+).
    A success is cached for 5 minutes, a failure for 30 seconds."""
    if DRY_RUN:
        return True
    age = time.time() - _REACH_CACHE["t"]
    if _REACH_CACHE["ok"] is not None and age < (300 if _REACH_CACHE["ok"] else 30):
        return _REACH_CACHE["ok"]
    result = {"ok": False}

    def probe():
        req = urllib.request.Request("https://www.youtube.com/", method="HEAD",
                                     headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                result["ok"] = r.status < 500
        except urllib.error.HTTPError as e:
            result["ok"] = e.code < 500
        except Exception:
            result["ok"] = False

    t = threading.Thread(target=probe, daemon=True)
    t.start()
    t.join(timeout)
    ok = bool(result["ok"]) and not t.is_alive()
    _REACH_CACHE.update(t=time.time(), ok=ok)
    return ok


def search_and_play_youtube(query, cfg=None):
    """Open the browser on YouTube, focus the search bar, type the exact query, press Enter and open
    the first video. The click on the first result is either a calibrated screen position
    ("youtube_click": "position", default) or, more robust, the first result's URL typed into the
    address bar ("youtube_click": "resolve")."""
    cfg = cfg or {}
    query = query.strip()
    if not query:
        raise ControllerError("Arama metni boş.")
    with _Run() as steps:
        _open_url("https://www.youtube.com/")
        _sleep(float(cfg.get("youtube_load_wait_s", 6)))
        _press("esc")                          # close any popup / leave the address bar
        _press("/")                            # YouTube shortcut: focus the search box
        _sleep(0.4)
        _hotkey(MOD, "a")                      # replace anything already in the box
        _paste(query)
        _press("enter")
        _sleep(float(cfg.get("youtube_results_wait_s", 4)))
        if cfg.get("youtube_click", "position") == "resolve":
            vid = "dQw4w9WgXcQ" if DRY_RUN else _first_video_id(query)
            _step(f"first result: {vid}")
            _hotkey(MOD, "l")
            _paste(f"https://www.youtube.com/watch?v={vid}")
            _press("enter")
        else:
            xr, yr = cfg.get("youtube_first_video", [0.30, 0.36])
            w, h = _screen()
            _click(int(w * float(xr)), int(h * float(yr)))
        return list(steps)


# --------------------------------------------------------------------------
# Computer use — mouse/keyboard via pyautogui, eyes via the Gemini vision API (brain.locate_on_image)
# --------------------------------------------------------------------------
APPS = {   # spoken/LLM app name -> launch candidates (Linux binaries / Windows "start" names)
    "chrome": {"linux": ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"],
               "windows": ["chrome"], "macos": ["Google Chrome"], "args": ["--new-window"]},
    "firefox": {"linux": ["firefox", "firefox-esr"], "windows": ["firefox"], "macos": ["Firefox"],
                "args": ["--new-window"]},
}
APP_ALIASES = {"google chrome": "chrome", "chromium": "chrome", "tarayıcı": "chrome", "tarayici": "chrome",
               "browser": "chrome", "internet": "chrome", "mozilla": "firefox", "mozilla firefox": "firefox"}
SCROLL_PX_PER_NOTCH = 100        # scroll_screen(-300) = 3 wheel notches down
SHOT_MAX_W = 1920                # screenshots wider than this are downscaled before upload
KEY_RE = re.compile(r"^[a-z0-9]+(?:\+[a-z0-9]+){0,3}$")


def _clamp(x, y):
    """Keep the pointer off the exact corners: a corner is pyautogui's FAILSAFE abort gesture."""
    w, h = _screen()
    return min(max(int(x), 2), w - 3), min(max(int(y), 2), h - 3)


def move_mouse_and_click(x, y, clicks=1):
    """Glide to (x, y) like a hand would, then click."""
    with _Run() as steps:
        x, y = _clamp(x, y)
        _step(f"move+click ({x}, {y})" + (f" x{clicks}" if clicks > 1 else ""))
        if not DRY_RUN:
            g = _gui()
            g.moveTo(x, y, duration=0.35, tween=g.easeInOutQuad)
            g.click(x, y, clicks=clicks, interval=0.12)
        return list(steps)


def type_text(text, press_enter=True):
    """Type into the focused field. ASCII is typed key by key; Turkish characters (which pyautogui
    cannot type) go through the clipboard."""
    text = str(text or "")
    if not text.strip():
        raise ControllerError("Yazılacak metin boş.")
    with _Run() as steps:
        if text.isascii():
            _step(f"type {text[:60]!r}")
            if not DRY_RUN:
                _gui().write(text, interval=0.05)
        else:
            _paste(text)
        if press_enter:
            _press("enter")
        return list(steps)


def scroll_screen(amount):
    """amount ≈ pixels: negative scrolls down, positive up (pyautogui sign). Wheel events go to the
    window under the pointer, so the pointer is parked in the screen centre first."""
    amount = int(amount)
    if amount == 0:
        raise ControllerError("Kaydırma miktarı 0.")
    notches = max(1, round(abs(amount) / SCROLL_PX_PER_NOTCH)) * (1 if amount > 0 else -1)
    with _Run() as steps:
        w, h = _screen()
        _move(w // 2, h // 2)
        _scroll_wheel(notches)
        return list(steps)


def press_keys(keys):
    """'enter', 'esc', 'ctrl+l', 'alt+left' ... (letters, digits and pyautogui key names only)."""
    k = str(keys or "").strip().lower().replace(" ", "")
    if not KEY_RE.match(k):
        raise ControllerError(f"Geçersiz tuş: {keys}")
    parts = k.split("+")
    valid = getattr(_gui(), "KEYBOARD_KEYS", None) if not DRY_RUN else None
    if valid and any(p not in valid for p in parts):
        raise ControllerError(f"Bilinmeyen tuş: {keys}")
    with _Run() as steps:
        if len(parts) == 1:
            _press(parts[0])
        else:
            _hotkey(*parts)
        return list(steps)


APP_FILLER = re.compile(r"\b(?:uygulama|program)\w*|\b(?:v|sürüm|versiyon)?\d+(?:[.,]\d+)*\b", re.I)
# A terminal + TYPE_AND_ENTER would turn a shouted sentence into a shell command; settings can lock the board.
APP_BLOCKED = {"terminalemulator", "settings", "packagemanager"}


def _launchers():
    """Installed apps -> [(display name, [folded names to match], launch target)]. Only what is installed."""
    out = []
    if PLATFORM == "windows":
        roots = [os.path.join(os.environ.get(v, ""), r"Microsoft\Windows\Start Menu\Programs")
                 for v in ("ProgramData", "APPDATA")]
        for root in roots:
            for dp, _, fns in os.walk(root):
                for fn in fns:
                    if fn.lower().endswith(".lnk") and "uninstall" not in fn.lower() and "kaldır" not in fn.lower():
                        out.append((fn[:-4], [(fn[:-4], 0)], os.path.join(dp, fn)))
        return out
    if PLATFORM == "macos":
        for root in ("/Applications", "/System/Applications", os.path.expanduser("~/Applications")):
            for fn in (os.listdir(root) if os.path.isdir(root) else []):
                if fn.endswith(".app"):
                    out.append((fn[:-4], [(fn[:-4], 0)], os.path.join(root, fn)))
        return out
    import configparser
    data_dirs = [os.path.expanduser("~/.local/share")] + \
        (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":") + \
        ["/var/lib/flatpak/exports/share", os.path.expanduser("~/.local/share/flatpak/exports/share"),
         "/var/lib/snapd/desktop"]
    dirs = [os.path.join(d, "applications") for d in data_dirs] + \
        [os.path.expanduser("~/Masaüstü"), os.path.expanduser("~/Desktop")]
    seen = set()
    for d in dirs:
        for fn in (sorted(os.listdir(d)) if os.path.isdir(d) else []):
            if not fn.endswith(".desktop") or fn in seen:
                continue
            path = os.path.join(d, fn)
            cp = configparser.RawConfigParser(strict=False)
            cp.optionxform = str
            try:
                cp.read(path, encoding="utf-8")
                e = cp["Desktop Entry"]
            except Exception:
                continue
            cats = {c.strip().lower() for c in e.get("Categories", "").split(";")}
            if e.get("Type") != "Application" or e.get("Hidden") == "true" or e.get("NoDisplay") == "true" \
                    or e.get("Terminal") == "true" or not e.get("Exec"):        # not in the menu / no window
                continue
            seen.add(fn)
            names = [e.get(k, "") for k in ("Name[tr]", "Name[tr_TR]", "Name", "GenericName[tr]", "GenericName")]
            exe = os.path.basename(e.get("Exec", "").split()[0]) if e.get("Exec", "").split() else ""
            exe = "" if exe in ("env", "sh", "bash", "flatpak", "snap", "python3", "java") else exe
            keys = [(n, 0) for n in names if n] + [(fn[:-8].split(".")[-1], -15), (exe, -15)] + \
                   [(k, -25) for k in re.split(r"[;,]", e.get("Keywords[tr]", "") + ";" + e.get("Keywords", "")) if k]
            blocked = bool(cats & APP_BLOCKED)   # kept, so a match is refused, not swapped
            out.append((e.get("Name[tr]") or e.get("Name") or fn[:-8], keys,
                        None if blocked else path))
    return out


def _words(text):
    return [w for w in (_fold(x) for x in re.split(r"[^\w]+", str(text or ""))) if w]


def _app_score(want, raw):
    """want = folded words the user said; raw = one launcher name. Higher is better, 0 = no match."""
    words = _words(raw)
    c, wc = "".join(words), "".join(want)
    if len(c) < 3:
        return 0
    if c == wc:
        return 100
    # "makinesini" still matches "makinesi": Turkish case suffixes hang off the end
    hit = sum(any(x.startswith(w) or (len(x) >= 4 and w.startswith(x)) for x in words) for w in want)
    if hit == len(want):
        return 60 - len(words)
    if len(wc) >= 4 and wc in c:
        return 40 - len(words)
    return 20 * hit / len(want) - len(words) if hit else 0


def find_app(name, launchers=None):
    """Spoken name ("flowingtr 3.2 uygulamasını", "hesap makinesi") -> (display name, launch target)."""
    want = [w for w in _words(APP_FILLER.sub(" ", str(name or ""))) if len(w) >= 3]
    if not want:
        raise ControllerError("Hangi uygulamayı açayım?")
    best, best_score = None, 0
    for label, keys, target in (launchers if launchers is not None else _launchers()):
        score = max([_app_score(want, raw) + weight for raw, weight in keys if _app_score(want, raw)] or [0])
        if score > best_score:
            best, best_score = (label, target), score
    if not best_score:
        raise ControllerError(f"“{name}” adında kurulu bir uygulama bulamadım.")
    if best[1] is None:
        raise ControllerError(f"{best[0]} uygulamasını güvenlik nedeniyle sesle açmıyorum (terminal/ayarlar).")
    return best


def _launch(target):
    if PLATFORM == "windows":
        os.startfile(target)  # noqa: S606 (a Start-menu shortcut found by find_app, not a command)
    elif PLATFORM == "macos":
        subprocess.Popen(["open", "-a", target])
    else:
        subprocess.Popen(["gio", "launch", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)


def open_app(name):
    """Start an app. Chrome/Firefox open a NEW window (address bar focused, ready to type); any other
    INSTALLED app is found by its launcher name (never run as a command)."""
    key = re.sub(r"\s+", " ", str(name or "").strip().lower())
    key = APP_ALIASES.get(key, key)
    spec = APPS.get(key)
    if not spec:
        label, target = find_app(name)
        with _Run() as steps:
            _step(f"open app {label!r} ({os.path.basename(target)})")
            if not DRY_RUN:
                _launch(target)
            return list(steps)
    with _Run() as steps:
        _step(f"open app {key}")
        if DRY_RUN:
            return list(steps)
        if PLATFORM == "windows":
            for exe in spec["windows"]:
                try:
                    subprocess.Popen(["cmd", "/c", "start", "", exe, *spec["args"]])
                    return list(steps)
                except OSError:
                    continue
        elif PLATFORM == "macos":
            subprocess.Popen(["open", "-na", spec["macos"][0], "--args", *spec["args"]])
            return list(steps)
        else:
            for exe in spec["linux"]:
                path = shutil.which(exe)
                if path:
                    subprocess.Popen([path, *spec["args"]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
                    return list(steps)
        raise ControllerError(f"{key} bu bilgisayarda kurulu değil.")


def capture_screen(max_w=SHOT_MAX_W, fmt="JPEG"):
    """Screenshot of the whole desktop -> {"bytes", "mime", "image_size", "screen_size"}.
    Read-only, so it runs in dry run too (dry run only skips clicks/typing)."""
    try:
        shot = _gui().screenshot()
    except ControllerError:
        raise
    except Exception as e:
        raise ControllerError(f"Ekran görüntüsü alınamadı ({type(e).__name__}: {e}).")
    if shot.width > max_w:
        shot = shot.resize((max_w, round(shot.height * max_w / shot.width)))
    import io
    buf = io.BytesIO()
    shot.convert("RGB").save(buf, fmt, quality=85) if fmt == "JPEG" else shot.save(buf, fmt)
    w, h = _gui().size()
    return {"bytes": buf.getvalue(), "mime": f"image/{fmt.lower()}", "image_size": shot.size,
            "screen_size": (int(w), int(h))}


def find_element_on_screen(target_description, shot=None):
    """Screenshot -> Gemini vision -> screen coordinates of the element.
    Returns {"found", "x", "y", "box": [x0, y0, x1, y1] (screen px), "label", "seen_in_ms"}."""
    target = str(target_description or "").strip()
    if not target:
        raise ControllerError("Neyi bulacağım? Hedef boş.")
    shot = shot or capture_screen()
    import brain                      # lazy: brain imports controller
    t = time.time()
    try:
        hit = brain.locate_on_image(shot["bytes"], shot["mime"], target)
    except brain.BrainError as e:
        raise ControllerError(f"Görsel arama başarısız: {e}")
    ms = int((time.time() - t) * 1000)
    if not hit.get("found"):
        _step(f"look for {target!r}: not found ({ms} ms)")
        return {"found": False, "x": None, "y": None, "box": None, "label": hit.get("label", ""), "seen_in_ms": ms}
    ymin, xmin, ymax, xmax = hit["box_2d"]             # Gemini: 0-1000, normalised to the image
    sw, sh = shot["screen_size"]
    box = [round(xmin / 1000 * sw), round(ymin / 1000 * sh), round(xmax / 1000 * sw), round(ymax / 1000 * sh)]
    x, y = _clamp((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    _step(f"look for {target!r}: {hit.get('label') or target!r} at ({x}, {y}) ({ms} ms)")
    return {"found": True, "x": x, "y": y, "box": box, "label": hit.get("label", ""), "seen_in_ms": ms}


def find_and_click(target_description, retries=1, retry_wait=1.5):
    """Look (Gemini vision), then click the centre of what was found. Re-looks once if the page
    was still loading. Raises ControllerError if the element is not on screen."""
    hit = None
    for attempt in range(retries + 1):
        hit = find_element_on_screen(target_description)
        if hit["found"]:
            break
        if attempt < retries:
            _sleep(retry_wait)
    if not hit["found"]:
        raise ControllerError(f"“{target_description}” ekranda bulunamadı.")
    move_mouse_and_click(hit["x"], hit["y"])
    return hit


# --------------------------------------------------------------------------
# Agent mode — paste the compiled English prompt into the Claude desktop app
# --------------------------------------------------------------------------
def _os_search_launch(app_name):
    """Open an app through the OS launcher: Start menu (Windows), Spotlight (macOS), Activities (GNOME/KDE)."""
    if SYSTEM == "Darwin":
        _hotkey("command", "space")
    else:
        _press("win")                          # Windows Start menu / GNOME Activities / KDE launcher
    _sleep(1.0)
    _type_ascii(app_name)
    _sleep(1.2)
    _press("enter")


def _direct_launch(app_name):
    _step(f"launch {app_name} directly")
    if DRY_RUN:
        return
    if SYSTEM == "Darwin":
        subprocess.Popen(["open", "-a", app_name])
        return
    if SYSTEM == "Windows":
        subprocess.Popen(["cmd", "/c", "start", "", app_name], shell=False)
        return
    dirs = ["/usr/share/applications", os.path.expanduser("~/.local/share/applications"),
            "/var/lib/flatpak/exports/share/applications"]
    for d in dirs:
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d)):
                if fn.endswith(".desktop") and app_name.lower() in fn.lower() and shutil.which("gtk-launch"):
                    subprocess.Popen(["gtk-launch", fn[:-8]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return
    raise ControllerError(f"{app_name} uygulaması bulunamadı.")


def deploy_to_claude(english_prompt, cfg=None, cancel=None):
    """Open the Claude desktop app, focus the chat input, paste the prompt and press Enter.
    `cancel` (threading.Event) is checked between steps so a spoken "dur" stops it."""
    cfg = cfg or {}
    if not english_prompt or not english_prompt.strip():
        raise ControllerError("Gönderilecek prompt boş.")
    with _Run() as steps:
        _check(cancel)
        try:
            focused = focus_window(r"^Claude$")["found"]           # already open: just bring it forward
        except ControllerError:
            focused = False
        if focused:
            _sleep(1.0)
        else:
            if cfg.get("claude_launch", "search") == "direct":
                _direct_launch("Claude")
            else:
                _os_search_launch("Claude")
            _sleep(float(cfg.get("claude_wait_s", 6)))
        _check(cancel)
        hotkey = cfg.get("claude_new_chat_hotkey")
        if hotkey:
            _hotkey(*hotkey)
            _sleep(1.0)
        xy = cfg.get("claude_input_xy")
        if xy:
            w, h = _screen()
            _click(int(w * float(xy[0])), int(h * float(xy[1])))
            _sleep(0.3)
        _check(cancel)
        _paste(english_prompt.strip())
        _sleep(0.8)
        _check(cancel)
        _press("enter")
        return list(steps)


if __name__ == "__main__":
    # Quick manual check:  JARVIS_DRY_RUN=1 python controller.py
    print("dry run:", DRY_RUN, "| system:", SYSTEM)
    for fn, args in ((scroll, ("aşağı",)), (click_center, ()), (search_and_play_youtube, ("fotosentez",)),
                     (deploy_to_claude, ("# Test prompt",))):
        try:
            print(fn.__name__, "->", fn(*args))
        except ControllerError as e:
            print(fn.__name__, "!!", e)
    sys.exit(0)
