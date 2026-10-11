# Builds the Windows release: a single-file xp-photocraft.exe (PyInstaller) and the portable release
# folder with the installer scripts, the guide and the Nano Banana example; then zips it.
#   powershell -ExecutionPolicy Bypass -File installer\build.ps1
# Needs uv. Output: dist\release\xp-photocraft-<version>-windows-x64\ and its .zip.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$version = (Select-String -Path pyproject.toml -Pattern '^version = "(.*)"').Matches[0].Groups[1].Value
$name = "xp-photocraft-$version-windows-x64"
$out = Join-Path $repo "dist\release\$name"

uv run --with pyinstaller pyinstaller --noconfirm --clean --onefile --console --name xp-photocraft `
    --add-data "$repo\src\xp_photocraft\qwen-edit-2511.api.json;xp_photocraft" `
    --copy-metadata xp-photocraft --paths "$repo\src" `
    --distpath "$repo\dist\pyinstaller\windows" --workpath "$repo\build\pyinstaller" --specpath "$repo\build" `
    installer\entry.py
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed" }

if (Test-Path $out) { Remove-Item -Recurse -Force $out }
New-Item -ItemType Directory -Force $out | Out-Null
Copy-Item "$repo\dist\pyinstaller\windows\xp-photocraft.exe" $out
foreach ($f in "install.bat", "start-photocraft.bat", "install-comfyui.bat", "INSTALL.md") {
    Copy-Item "$repo\installer\$f" $out
}
Copy-Item "$repo\installer\.env.example" $out
Copy-Item -Recurse "$repo\examples\workflows" "$out\workflows"
# The built-in workflow too, as the file that is it (see registry.load): the catalog is the folder.
Copy-Item "$repo\src\xp_photocraft\qwen-edit-2511.api.json" "$out\workflows\Qwen Edit 2511 (ComfyUI).json"
Copy-Item "$repo\LICENSE-MIT", "$repo\LICENSE-APACHE" $out
# The marker that keeps the release portable: data\ next to the executable (see cli._data_dir).
Set-Content -Path "$out\portable.txt" -Value "This file keeps xp-photocraft portable: its data (connection, workflows, work folder) lives in data\ next to it."
Compress-Archive -Path $out -DestinationPath "$out.zip" -Force
& "$out\xp-photocraft.exe" --version
Write-Host "-> $out.zip"
