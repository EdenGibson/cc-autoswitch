#!/usr/bin/env bash
# install.sh — install the quota-aware auto-switcher as a per-minute cron job.
#
# Idempotent: re-running it (or migrating from an older ~/.claude-based install)
# replaces any existing cc-autoswitch cron line with the canonical one. Other
# crontab entries are preserved untouched.
set -euo pipefail

REPO="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
SHIM="$REPO/cc-autoswitch.sh"
CRON_LINE="* * * * * $SHIM >/dev/null 2>&1"

chmod +x "$REPO/cc-autoswitch.sh" "$REPO/cc_autoswitch.py"

if ! command -v cswap >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/cswap" ]; then
  echo "WARNING: 'cswap' (claude-swap) not found on PATH or at ~/.local/bin/cswap." >&2
  echo "         Install it first: https://pypi.org/project/claude-swap/" >&2
fi

# Rebuild crontab: keep every line except prior cc-autoswitch entries, then add ours.
current="$(crontab -l 2>/dev/null || true)"
filtered="$(printf '%s\n' "$current" | grep -v 'cc-autoswitch' || true)"
{ printf '%s\n' "$filtered" | sed '/^$/d'; printf '%s\n' "$CRON_LINE"; } | crontab -

echo "Installed cron entry:"
echo "  $CRON_LINE"
echo
echo "Verify a decision now without switching:"
echo "  $SHIM --dry-run"
