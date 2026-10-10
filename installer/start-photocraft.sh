#!/usr/bin/env bash
# Starts PhotoCraft with the control server and the work folder xp-photocraft needs (data/work
# beside the bridge). photocraft: the argument, else next to this folder (PhotoCraft*/photocraft),
# else on the PATH.
set -u
here="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
work="$here/data/work"
mkdir -p "$work"
pc="${1:-}"
[ -n "$pc" ] || for d in "$here"/PhotoCraft* "$here"/../PhotoCraft*; do [ -x "$d/photocraft" ] && { pc="$d/photocraft"; break; }; done
[ -n "$pc" ] || pc="$(command -v photocraft || true)"
[ -n "$pc" ] || { echo "photocraft not found: start-photocraft /path/to/photocraft"; exit 1; }
exec "$pc" --control 7878 --control-token-file "$work/control.token" \
  --automation-read-root "$work" --automation-write-root "$work"
