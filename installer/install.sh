#!/usr/bin/env bash
# xp-photocraft installer (Linux): copies the binary into ~/.local/bin, prepares the data folder and
# the example workflows, and tests the ComfyUI connection. Run from the unpacked release folder.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
dest="${HOME}/.local/bin"
data="${XDG_DATA_HOME:-$HOME/.local/share}/xp-photocraft"

echo
echo " xp-photocraft - Generative Fill and Remove for PhotoCraft, on your own ComfyUI"
echo " ------------------------------------------------------------------------------"
[ -f "$here/xp-photocraft" ] || { echo " xp-photocraft is not next to this script. Unpack the whole release folder first."; exit 1; }

mkdir -p "$dest" "$data/work"
install -m 755 "$here/xp-photocraft" "$dest/xp-photocraft"
install -m 755 "$here/start-photocraft.sh" "$dest/start-photocraft"
cp "$here/INSTALL.md" "$data/INSTALL.md"
echo " Installed:  $dest/xp-photocraft"
case ":$PATH:" in
  *":$dest:"*) echo " PATH:       ok" ;;
  *) echo " PATH:       add $dest to your PATH (most distributions do it at next login)" ;;
esac

if [ ! -f "$data/workflows.json" ]; then
  cp "$here/workflows.json" "$here/nano-banana-edit.api.json" "$data/"
  echo " Workflows:  $data/workflows.json (built-in Qwen + Nano Banana example)"
else
  echo " Workflows:  kept your $data/workflows.json"
fi

echo
echo " Testing the ComfyUI connection ..."
if ! "$dest/xp-photocraft" connect http://127.0.0.1:8188 2>/dev/null; then
  echo " No ComfyUI on http://127.0.0.1:8188 yet. Either run install-comfyui.sh (this PC, NVIDIA GPU),"
  echo " or connect to another PC later with:  xp-photocraft connect http://ADDRESS:8188"
fi
echo
echo " Next: start PhotoCraft with start-photocraft (it enables the control server the bridge needs),"
echo " select an area, and use the task bar under the selection. Guide: $data/INSTALL.md"
