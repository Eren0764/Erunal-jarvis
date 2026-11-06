#!/usr/bin/env bash
# Jarvis sunucusunu ve "Hey Jarvis" servisini kapatır (yalnızca kendi süreçlerine dokunur).

DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
ICON="$DIR/jarvis-icon.svg"
notify() { notify-send -i "$ICON" "Jarvis" "$1" 2>/dev/null || true; }

# Önce "Hey Jarvis" servisi (daemon.py)
DPID_FILE="$DIR/data/daemon.pid"
if [ -f "$DPID_FILE" ]; then
  DPID="$(cat "$DPID_FILE")"
  if tr '\0' ' ' < "/proc/$DPID/cmdline" 2>/dev/null | grep -q "daemon.py"; then kill "$DPID" 2>/dev/null; fi
  rm -f "$DPID_FILE"
fi

PID="$(ss -ltnpH 'sport = :4700' 2>/dev/null | grep -o 'pid=[0-9]*' | head -n1 | cut -d= -f2)"
if [ -z "$PID" ]; then
  notify "Jarvis zaten kapalı."
  exit 0
fi
if ! tr '\0' ' ' < "/proc/$PID/cmdline" 2>/dev/null | grep -q "server.py"; then
  zenity --error --title="Jarvis" --text="4700 portunu Jarvis dışında bir program kullanıyor; dokunulmadı." 2>/dev/null
  exit 1
fi
kill "$PID"
for _ in $(seq 1 20); do kill -0 "$PID" 2>/dev/null || break; sleep 0.25; done
kill -0 "$PID" 2>/dev/null && kill -9 "$PID"
echo "=== $(date '+%F %T') Jarvis kapatıldı ===" >>"$DIR/data/sunucu.log"
notify "Jarvis kapatıldı."
