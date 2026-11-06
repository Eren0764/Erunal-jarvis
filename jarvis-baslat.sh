#!/usr/bin/env bash
# Jarvis'i başlatır.
#  - Sunucu zaten çalışıyorsa yalnızca arayüzü açar (ikinci kez başlatmaz).
#  - Çalışmıyorsa arka planda başlatır (terminal penceresi gerekmez), hazır olunca Chrome'da açar.
#  - İlk çalıştırmada .venv yoksa kurar (pip install -r requirements.txt).
#  - "Hey Jarvis" / "Tahta" servisini (daemon.py) de başlatır.
# Günlük: data/sunucu.log, data/daemon.log    Kapatmak için: jarvis-durdur.sh

DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
URL="http://127.0.0.1:4700"
LOG="$DIR/data/sunucu.log"
ICON="$DIR/jarvis-icon.svg"
mkdir -p "$DIR/data"

notify() { notify-send -i "$ICON" "Jarvis" "$1" 2>/dev/null || true; }
fail()   { zenity --error --title="Jarvis" --width=440 --text="$1" 2>/dev/null || notify "$1"; exit 1; }
up()     { curl -sf -o /dev/null --max-time 1 "$URL/boot"; }

# Günlük dosyası 5 MB'ı geçerse sıfırla
[ -f "$LOG" ] && [ "$(stat -c %s "$LOG")" -gt 5242880 ] && : > "$LOG"

if ! up; then
  if ss -ltnH 'sport = :4700' 2>/dev/null | grep -q .; then
    fail "4700 numaralı portu başka bir program kullanıyor; Jarvis başlatılamadı."
  fi
  if [ ! -x "$DIR/.venv/bin/python" ]; then
    notify "İlk kurulum yapılıyor, 1-2 dakika sürebilir…"
    { python3 -m venv "$DIR/.venv" && "$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"; } >>"$LOG" 2>&1 \
      || fail "Kurulum başarısız oldu. Ayrıntılar: data/sunucu.log"
  fi
  echo "=== $(date '+%F %T') Jarvis başlatılıyor ===" >>"$LOG"
  cd "$DIR" || fail "Proje klasörüne girilemedi: $DIR"
  setsid -f "$DIR/.venv/bin/python" -u server.py >>"$LOG" 2>&1 < /dev/null
  for _ in $(seq 1 60); do up && break; sleep 0.25; done
  up || fail "Sunucu açılamadı. Son satırlar:\n\n$(tail -n 6 "$LOG" | sed 's/[<>&]//g')"
  notify "Sunucu çalışıyor: $URL"
fi

# "Hey Jarvis" / "Tahta" arka plan servisi (daemon.py). JARVIS_NO_DAEMON=1 ile kapatılabilir.
DPID_FILE="$DIR/data/daemon.pid"
daemon_up() { [ -f "$DPID_FILE" ] && kill -0 "$(cat "$DPID_FILE")" 2>/dev/null; }
if [ "${JARVIS_NO_DAEMON:-0}" != "1" ] && ! daemon_up; then
  cd "$DIR" && setsid -f "$DIR/.venv/bin/python" -u daemon.py >>"$DIR/data/daemon.log" 2>&1 < /dev/null
fi

# Mikrofon (tr-TR ses tanıma) Chrome'da çalışır; yoksa varsayılan tarayıcı.
[ "${JARVIS_NO_BROWSER:-0}" = "1" ] && exit 0
if command -v google-chrome >/dev/null 2>&1; then
  setsid -f google-chrome --new-window "$URL" >/dev/null 2>&1
else
  setsid -f xdg-open "$URL" >/dev/null 2>&1
fi
