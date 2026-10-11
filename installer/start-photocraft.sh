#!/usr/bin/env bash
# Starts PhotoCraft with the control server and the work folder xp-photocraft needs (data/work
# beside the bridge). photocraft: the argument, else next to this folder (PhotoCraft*/photocraft),
# else on the PATH.
set -u
here="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
work="$here/data/work"
mkdir -p "$work"
# This folder first on PATH: PhotoCraft's task bar runs the bridge that sits next to this script.
export PATH="$here:$PATH"
pc="${1:-}"
# A PhotoCraft* folder here, one or two levels up (an archive tool may add a folder per archive),
# possibly inside one more PhotoCraft* folder.
[ -n "$pc" ] || for d in "$here"/PhotoCraft* "$here"/../PhotoCraft* "$here"/../../PhotoCraft* \
  "$here"/../PhotoCraft*/PhotoCraft* "$here"/../../PhotoCraft*/PhotoCraft*; do
  [ -x "$d/photocraft" ] && { pc="$d/photocraft"; break; }
done
[ -n "$pc" ] || pc="$(command -v photocraft || true)"
[ -n "$pc" ] || { echo "photocraft not found: start-photocraft /path/to/photocraft"; exit 1; }
exec "$pc" --control 7878 --control-token-file "$work/control.token" \
  --automation-read-root "$work" --automation-write-root "$work"
