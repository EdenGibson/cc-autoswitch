#!/usr/bin/env bash
# cc-autoswitch.sh — cron entry point. Thin shim into cc_autoswitch.py.
#
# Resolves its own real location (via readlink -f) so it works whether invoked
# directly or through a symlink (e.g. ~/.claude/cc-autoswitch.sh -> here).
set -euo pipefail
DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
exec "${CC_AUTOSWITCH_PYTHON:-/usr/bin/python3}" "$DIR/cc_autoswitch.py" "$@"
