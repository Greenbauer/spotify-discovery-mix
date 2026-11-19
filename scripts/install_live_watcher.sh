#!/usr/bin/env bash
# Install, check, or remove the live skip watcher (live_watch.py).
#
#   scripts/install_live_watcher.sh             install (or reinstall) and start it
#   scripts/install_live_watcher.sh --ensure    restart it only if watcher_health --live says it is dead
#   scripts/install_live_watcher.sh --uninstall stop it and remove the service
#
# Uses a systemd user service when `systemctl --user` works (Restart=always,
# survives reboots with linger). Otherwise falls back to a nohup supervisor
# loop that restarts the watcher 10 s after any exit; the hourly routine's
# `--ensure` brings the supervisor back after a reboot.
# Written for the Linux mixer box; also runs on macOS (nohup path only).
# Portable bash: no bash 4 features.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="${MIX_STATE_DIR:-$ROOT/state}"
PY="$ROOT/.venv/bin/python"
UNIT="discovery-mix-live.service"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SUP_PID="$STATE/live_watcher_supervisor.pid"
LOG="$STATE/live_watcher.log"

have_systemd() {
  command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1
}

write_unit() {
  mkdir -p "$UNIT_DIR"
  cat >"$UNIT_DIR/$UNIT" <<EOF
[Unit]
Description=Discovery Mix live skip watcher
After=network-online.target

[Service]
WorkingDirectory=$ROOT
Environment=PYTHONUNBUFFERED=1
Environment=MIX_STATE_DIR=$STATE
ExecStart=$PY $ROOT/live_watch.py
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF
}

supervisor_running() {
  [[ -f "$SUP_PID" ]] && kill -0 "$(cat "$SUP_PID")" 2>/dev/null
}

stop_supervisor() {
  if supervisor_running; then
    # The supervisor's TERM trap stops its watcher child too.
    kill "$(cat "$SUP_PID")" 2>/dev/null || true
  fi
  rm -f "$SUP_PID"
}

# The supervisor loop itself, run under nohup by start_supervisor.
supervise() {
  local child=""
  echo $$ >"$SUP_PID"
  trap '[[ -n "$child" ]] && kill "$child" 2>/dev/null; exit 0' TERM INT
  while true; do
    MIX_STATE_DIR="$STATE" PYTHONUNBUFFERED=1 "$PY" "$ROOT/live_watch.py" &
    child=$!
    wait "$child" || true
    child=""
    sleep 10
  done
}

start_supervisor() {
  stop_supervisor
  mkdir -p "$STATE"
  nohup "$ROOT/scripts/install_live_watcher.sh" --supervise >>"$LOG" 2>&1 &
  echo "install_live_watcher: started nohup supervisor (log: $LOG)"
}

install() {
  "$ROOT/scripts/ensure_venv.sh"
  if have_systemd; then
    stop_supervisor
    write_unit
    systemctl --user daemon-reload
    systemctl --user enable --now "$UNIT"
    systemctl --user restart "$UNIT"
    if ! loginctl enable-linger "$(id -un)" 2>/dev/null; then
      echo "install_live_watcher: could not enable linger; the service stops at logout." \
        "Run: sudo loginctl enable-linger $(id -un)" >&2
    fi
    echo "install_live_watcher: systemd user service $UNIT is running"
  else
    start_supervisor
  fi
}

ensure() {
  local report
  report="$("$PY" "$ROOT/scripts/watcher_health.py" --live --state-dir "$STATE")" && {
    echo "$report"
    return 0
  }
  echo "$report"
  # Only a dead watcher is restarted. An auth failure needs a new refresh
  # token; restarting would not fix it, so exit 1 and let the routine ping.
  case "$report" in
    *'"needs_restart":true'*) install ;;
    *) return 1 ;;
  esac
}

uninstall() {
  if have_systemd; then
    systemctl --user disable --now "$UNIT" 2>/dev/null || true
    rm -f "$UNIT_DIR/$UNIT"
    systemctl --user daemon-reload
  fi
  stop_supervisor
  echo "install_live_watcher: removed"
}

case "${1:-}" in
  "") install ;;
  --ensure) ensure ;;
  --uninstall) uninstall ;;
  --supervise) supervise ;;
  *) echo "usage: $0 [--ensure|--uninstall]" >&2; exit 2 ;;
esac
