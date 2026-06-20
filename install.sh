#!/usr/bin/env bash
# install.sh — install the quota-aware auto-switcher as a per-minute scheduler.
#
# Two backends (Linux only):
#   (default)    per-minute cron job.
#   --systemd    per-minute systemd *user* timer.
#
# Idempotent: re-running it (or migrating from an older ~/.claude-based install)
# replaces any existing cc-autoswitch cron line / timer with the canonical one.
# Other crontab entries are preserved untouched. Selecting one backend removes
# the other, so you never get double-runs.
set -euo pipefail

REPO="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
SHIM="$REPO/cc-autoswitch.sh"
CRON_LINE="* * * * * $SHIM >/dev/null 2>&1"

UNIT_DIR="$HOME/.config/systemd/user"
SERVICE_SRC="$REPO/systemd/cc-autoswitch.service"
TIMER_SRC="$REPO/systemd/cc-autoswitch.timer"
SERVICE_NAME="cc-autoswitch.service"
TIMER_NAME="cc-autoswitch.timer"

usage() {
  cat <<EOF
Usage: install.sh [--systemd | --uninstall | --help]

  (no flag)     Install a per-minute cron job (default).
  --systemd     Install a per-minute systemd user timer instead of cron.
  --uninstall   Remove both the cron job and the systemd timer/service.
  --help, -h    Show this help.

Cron and systemd are mutually exclusive: installing one removes the other, so
cc-autoswitch never runs twice per minute.
EOF
}

# --- cron backend ------------------------------------------------------------

remove_cron() {
  # Drop any prior cc-autoswitch cron line; leave every other entry intact.
  local current filtered
  current="$(crontab -l 2>/dev/null || true)"
  filtered="$(printf '%s\n' "$current" | grep -v 'cc-autoswitch' || true)"
  printf '%s\n' "$filtered" | sed '/^$/d' | crontab -
}

install_cron() {
  # Switching to cron: make sure the systemd timer isn't also firing.
  remove_systemd quiet

  chmod +x "$REPO/cc-autoswitch.sh" "$REPO/cc_autoswitch.py"

  if ! command -v cswap >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/cswap" ]; then
    echo "WARNING: 'cswap' (claude-swap) not found on PATH or at ~/.local/bin/cswap." >&2
    echo "         Install it first: https://pypi.org/project/claude-swap/" >&2
  fi

  # Rebuild crontab: keep every line except prior cc-autoswitch entries, then add ours.
  local current filtered
  current="$(crontab -l 2>/dev/null || true)"
  filtered="$(printf '%s\n' "$current" | grep -v 'cc-autoswitch' || true)"
  { printf '%s\n' "$filtered" | sed '/^$/d'; printf '%s\n' "$CRON_LINE"; } | crontab -

  echo "Installed cron entry:"
  echo "  $CRON_LINE"
  echo
  echo "Verify a decision now without switching:"
  echo "  $SHIM --dry-run"
}

# --- systemd backend ---------------------------------------------------------

require_systemctl() {
  if ! command -v systemctl >/dev/null 2>&1 || ! systemctl --user show-environment >/dev/null 2>&1; then
    echo "ERROR: 'systemctl --user' is unavailable; cannot use the systemd backend." >&2
    echo "       Use the default cron install instead: ./install.sh" >&2
    exit 1
  fi
}

# remove_systemd [quiet] — disable the timer and remove the unit files.
# In quiet mode it skips when systemctl --user is unavailable (used as a
# best-effort cleanup before installing cron).
remove_systemd() {
  local quiet="${1:-}"
  if ! command -v systemctl >/dev/null 2>&1 || ! systemctl --user show-environment >/dev/null 2>&1; then
    [ "$quiet" = "quiet" ] && return 0
    return 0
  fi

  if systemctl --user list-unit-files "$TIMER_NAME" >/dev/null 2>&1; then
    systemctl --user disable --now "$TIMER_NAME" >/dev/null 2>&1 || true
  fi
  systemctl --user stop "$SERVICE_NAME" >/dev/null 2>&1 || true

  rm -f "$UNIT_DIR/$TIMER_NAME" "$UNIT_DIR/$SERVICE_NAME"
  systemctl --user daemon-reload >/dev/null 2>&1 || true
}

install_systemd() {
  require_systemctl

  chmod +x "$REPO/cc-autoswitch.sh" "$REPO/cc_autoswitch.py"

  if ! command -v cswap >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/cswap" ]; then
    echo "WARNING: 'cswap' (claude-swap) not found on PATH or at ~/.local/bin/cswap." >&2
    echo "         Install it first: https://pypi.org/project/claude-swap/" >&2
  fi

  # Switching to systemd: make sure cron isn't also firing.
  remove_cron

  mkdir -p "$UNIT_DIR"
  # Resolve the ExecStart placeholder to this repo's real shim path.
  sed "s#__CC_AUTOSWITCH_SH__#$SHIM#g" "$SERVICE_SRC" > "$UNIT_DIR/$SERVICE_NAME"
  cp "$TIMER_SRC" "$UNIT_DIR/$TIMER_NAME"

  systemctl --user daemon-reload
  systemctl --user enable --now "$TIMER_NAME"

  echo "Installed systemd user timer:"
  echo "  $UNIT_DIR/$TIMER_NAME -> $SHIM"
  echo
  echo "Inspect it:"
  echo "  systemctl --user status $TIMER_NAME"
  echo "  systemctl --user list-timers $TIMER_NAME"
  echo
  echo "Verify a decision now without switching:"
  echo "  $SHIM --dry-run"
}

# --- uninstall ---------------------------------------------------------------

uninstall_all() {
  remove_cron
  remove_systemd
  echo "Removed cc-autoswitch cron job and systemd timer/service (if present)."
}

# --- dispatch ----------------------------------------------------------------

case "${1:-}" in
  --systemd)            install_systemd ;;
  --uninstall)          uninstall_all ;;
  -h|--help)            usage ;;
  "")                   install_cron ;;
  *)
    echo "Unknown option: $1" >&2
    echo >&2
    usage >&2
    exit 2
    ;;
esac
