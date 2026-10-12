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

# The shipped workflows, a folder each (in a category folder); a file already there (maybe edited)
# is kept. A 0.1 loose copy first moves into its folder, edits and all.
mkdir -p "$here/data/workflows"
for f in "$here"/workflows/*/*/workflow.json "$here"/workflows/*/workflow.json; do
  [ -f "$f" ] || continue
  rel="${f#"$here/workflows/"}"
  folder="$here/data/workflows/$(dirname "$rel")"
  old="$here/data/workflows/$(basename "$(dirname "$f")").json"
  if [ -f "$old" ] && [ ! -e "$folder/workflow.json" ]; then mkdir -p "$folder"; mv "$old" "$folder/workflow.json"; fi
done
(cd "$here/workflows" && find . -type f) | while IFS= read -r f; do
  [ -e "$here/data/workflows/$f" ] || { mkdir -p "$(dirname "$here/data/workflows/$f")"; cp "$here/workflows/$f" "$here/data/workflows/$f"; }
done
echo " Workflows:  data/workflows/ (XP menu > Import Workflow adds a graph exported from ComfyUI)"
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
