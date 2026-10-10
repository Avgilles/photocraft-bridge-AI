@echo off
rem xp-photocraft installer (Windows): copies xp-photocraft.exe into your user programs, puts it on
rem your PATH, prepares its work folder and the example workflows, and tests the ComfyUI connection.
rem Run it from the unzipped release folder. No administrator rights needed.
setlocal
set "SRC=%~dp0"
set "DEST=%LOCALAPPDATA%\Programs\xp-photocraft"
set "DATA=%LOCALAPPDATA%\xp-photocraft"

echo.
echo  xp-photocraft - Generative Fill and Remove for PhotoCraft, on your own ComfyUI
echo  ------------------------------------------------------------------------------
if not exist "%SRC%xp-photocraft.exe" (
    echo  xp-photocraft.exe is not next to this script. Unzip the whole release folder first.
    goto :end
)

mkdir "%DEST%" 2>nul
copy /Y "%SRC%xp-photocraft.exe" "%DEST%\xp-photocraft.exe" >nul || (echo  Could not copy to %DEST% & goto :end)
copy /Y "%SRC%start-photocraft.bat" "%DEST%\" >nul
copy /Y "%SRC%INSTALL.md" "%DEST%\" >nul
echo  Installed:  %DEST%\xp-photocraft.exe

rem The user PATH, so PhotoCraft's task bar finds the bridge. PowerShell keeps %%VAR%% entries intact
rem (setx would expand them).
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p=[Environment]::GetEnvironmentVariable('Path','User'); if ($p -notlike '*\Programs\xp-photocraft*') { [Environment]::SetEnvironmentVariable('Path', ($p.TrimEnd(';') + ';%DEST%'), 'User'); 'PATH:       added %DEST% (new programs see it; restart PhotoCraft)' } else { 'PATH:       already there' }"
set "PATH=%PATH%;%DEST%"

mkdir "%DATA%\work" 2>nul
if not exist "%DATA%\workflows.json" (
    copy /Y "%SRC%workflows.json" "%DATA%\workflows.json" >nul
    copy /Y "%SRC%nano-banana-edit.api.json" "%DATA%\nano-banana-edit.api.json" >nul
    echo  Workflows:  %DATA%\workflows.json ^(built-in Qwen + Nano Banana example^)
) else (
    echo  Workflows:  kept your %DATA%\workflows.json
)

echo.
echo  Testing the ComfyUI connection ...
"%DEST%\xp-photocraft.exe" connect http://127.0.0.1:8188 2>nul
if errorlevel 1 (
    echo  No ComfyUI on http://127.0.0.1:8188 yet. Either run install-comfyui.bat ^(this PC, NVIDIA GPU^),
    echo  or connect to another PC later with:  xp-photocraft connect http://ADDRESS:8188
)

echo.
echo  Next: start PhotoCraft with start-photocraft.bat ^(it enables the control server the bridge needs^),
echo  select an area, and use the task bar under the selection. Guide: %DEST%\INSTALL.md
:end
echo.
pause
