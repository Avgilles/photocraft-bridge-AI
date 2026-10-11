#!/usr/bin/env bash
# Builds the Linux release on the current machine: a single-file xp-photocraft (PyInstaller) and the
# release folder with the installer scripts, the guide and the Nano Banana example; then a tarball.
#   installer/build.sh
# Needs uv. Output: dist/release/xp-photocraft-<version>-linux-x64/ and its .tar.gz. The binary runs
# on distributions whose glibc is at least the build machine's (Fedora 41: glibc 2.40).
set -eu
repo="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo"
version="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1 | tr -d '
')"
name="xp-photocraft-$version-linux-x64"
out="$repo/dist/release/$name"

uv run --python 3.11 --with pyinstaller pyinstaller --noconfirm --clean --onefile --console --name xp-photocraft \
  --add-data "$repo/src/xp_photocraft/qwen-edit-2511.api.json:xp_photocraft" \
  --copy-metadata xp-photocraft --paths "$repo/src" \
  --distpath "$repo/dist/pyinstaller/linux" --workpath "$repo/build/pyinstaller" --specpath "$repo/build" \
  installer/entry.py

rm -rf "$out"; mkdir -p "$out"
cp "$repo/dist/pyinstaller/linux/xp-photocraft" "$out/"
for f in install.sh start-photocraft.sh install-comfyui.sh INSTALL.md; do cp "$repo/installer/$f" "$out/"; done
cp "$repo/installer/.env.example" "$repo/LICENSE-MIT" "$repo/LICENSE-APACHE" "$out/"
cp -r "$repo/examples/workflows" "$out/workflows"
echo "This file keeps xp-photocraft portable: its data (connection, workflows, work folder) lives in data/ next to it." > "$out/portable.txt"
chmod +x "$out"/*.sh "$out/xp-photocraft"
tar -czf "$out.tar.gz" -C "$repo/dist/release" "$name"
"$out/xp-photocraft" --version
echo "-> $out.tar.gz"
