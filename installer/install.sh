#!/usr/bin/env bash
# xp-photocraft installer (Linux, portable): everything stays in this folder. It links the binary
# into ~/.local/bin (PhotoCraft's task bar finds it there), creates data/ (connection, workflows,
# work folder) beside the binary, and tests the ComfyUI connection.
# To uninstall: delete this folder and the two links in ~/.local/bin.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
bin="${HOME}/.local/bin"

echo
echo " xp-photocraft - Generative Fill and Remove for PhotoCraft, on your own ComfyUI"
echo " ------------------------------------------------------------------------------"
[ -f "$here/xp-photocraft" ] || { echo " xp-photocraft is not next to this script. Unpack the whole release folder first."; exit 1; }
echo " Folder:     $here"

chmod +x "$here/xp-photocraft" "$here"/*.sh
mkdir -p "$bin" "$here/data/work"
ln -sfn "$here/xp-photocraft" "$bin/xp-photocraft"
ln -sfn "$here/start-photocraft.sh" "$bin/start-photocraft"
echo " Linked:     $bin/xp-photocraft, $bin/start-photocraft"
case ":$PATH:" in
  *":$bin:"*) echo " PATH:       ok" ;;
  *) echo " PATH:       add $bin to your PATH (most distributions do it at next login)" ;;
esac

# The shipped workflows; a file already there (maybe edited) is kept.
mkdir -p "$here/data/workflows"
for f in "$here"/workflows/*.json; do [ -e "$here/data/workflows/${f##*/}" ] || cp "$f" "$here/data/workflows/"; done
echo " Workflows:  data/workflows/ (drop a graph exported from ComfyUI there)"
if [ ! -f "$here/data/.env" ]; then
  cp "$here/.env.example" "$here/data/.env"
  echo " Settings:   data/.env (your comfy.org API key goes there, for Nano Banana)"
fi

echo
echo " Testing the ComfyUI connection ..."
# Quiet: the command's report and its JSON line are for the task bar, not for this terminal.
if "$here/xp-photocraft" connect http://127.0.0.1:8188 >/dev/null 2>&1; then
  echo " ComfyUI:    connected on http://127.0.0.1:8188"
else
  echo " No ComfyUI on http://127.0.0.1:8188 yet. Either run install-comfyui.sh (this PC, NVIDIA GPU),"
  echo " or connect to another PC later with:  xp-photocraft connect http://ADDRESS:8188"
fi
echo
echo " Next: start PhotoCraft with start-photocraft (it enables the control server the bridge needs),"
echo " select an area, and use the task bar under the selection. Guide: INSTALL.md"
