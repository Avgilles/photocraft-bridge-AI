#!/usr/bin/env bash
# Starts PhotoCraft with the control server and work folder xp-photocraft needs.
#   start-photocraft [path/to/photocraft]     (else: photocraft on the PATH, or ~/.local/bin/photocraft)
set -u
work="${XDG_DATA_HOME:-$HOME/.local/share}/xp-photocraft/work"
mkdir -p "$work"
pc="${1:-}"
[ -n "$pc" ] || pc="$(command -v photocraft || true)"
[ -n "$pc" ] || { [ -x "$HOME/.local/bin/photocraft" ] && pc="$HOME/.local/bin/photocraft"; }
[ -n "$pc" ] || { echo "photocraft not found: start-photocraft /path/to/photocraft"; exit 1; }
exec "$pc" --control 7878 --control-token-file "$work/control.token" \
  --automation-read-root "$work" --automation-write-root "$work"
