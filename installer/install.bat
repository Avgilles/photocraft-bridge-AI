@echo off
rem xp-photocraft installer (Windows, portable): everything stays in this folder. It puts this folder
rem on your PATH (so PhotoCraft's task bar finds xp-photocraft.exe), creates data\ (connection,
rem workflows, work folder) and tests the ComfyUI connection. No administrator rights needed.
rem To uninstall: delete this folder and remove it from your PATH.
setlocal
set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"

echo.
echo  xp-photocraft - Generative Fill and Remove for PhotoCraft, on your own ComfyUI
echo  ------------------------------------------------------------------------------
if not exist "%HERE%\xp-photocraft.exe" (
    echo  xp-photocraft.exe is not next to this script. Unzip the whole release folder first.
    goto :end
)
echo  Folder:     %HERE%

rem The user PATH, kept as is otherwise (PowerShell keeps %%VAR%% entries intact; setx would expand them).
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p=[Environment]::GetEnvironmentVariable('Path','User'); if (($p -split ';') -notcontains '%HERE%') { [Environment]::SetEnvironmentVariable('Path', ($p.TrimEnd(';') + ';%HERE%'), 'User'); ' PATH:       added this folder (programs started from now on see it)' } else { ' PATH:       already there' }"
set "PATH=%PATH%;%HERE%"

mkdir "%HERE%\data\work" 2>nul
rem The shipped workflows; a file already there (maybe edited) is kept.
mkdir "%HERE%\data\workflows" 2>nul
for %%f in ("%HERE%\workflows\*.json") do if not exist "%HERE%\data\workflows\%%~nxf" copy "%%f" "%HERE%\data\workflows\" >nul
echo  Workflows:  data\workflows\ ^(drop a graph exported from ComfyUI there^)
if not exist "%HERE%\data\.env" (
    copy "%HERE%\.env.example" "%HERE%\data\.env" >nul
    echo  Settings:   data\.env ^(your comfy.org API key goes there, for Nano Banana^)
)

echo.
echo  Testing the ComfyUI connection ...
rem Quiet: the command's report and its JSON line are for the task bar, not for this console.
"%HERE%\xp-photocraft.exe" connect http://127.0.0.1:8188 >nul 2>nul
if not errorlevel 1 echo  ComfyUI:    connected on http://127.0.0.1:8188
if errorlevel 1 (
    echo  No ComfyUI on http://127.0.0.1:8188 yet. Either run install-comfyui.bat ^(this PC, NVIDIA GPU^),
    echo  or connect to another PC later with:  xp-photocraft connect http://ADDRESS:8188
)

echo.
echo  Next: start PhotoCraft with start-photocraft.bat ^(it enables the control server the bridge needs^),
echo  select an area, and use the task bar under the selection. Guide: INSTALL.md
:end
echo.
pause
