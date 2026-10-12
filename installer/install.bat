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
rem The shipped workflows, a folder each (in a category folder); a file already there (maybe edited)
rem is kept. A 0.1 loose copy first moves into its folder, edits and all.
mkdir "%HERE%\data\workflows" 2>nul
for /r "%HERE%\workflows" %%f in (workflow.json) do if exist "%%f" call :move_old_copy "%%f"
robocopy "%HERE%\workflows" "%HERE%\data\workflows" /E /XC /XN /XO /NFL /NDL /NJH /NJS /NP >nul
echo  Workflows:  data\workflows\ ^(XP menu ^> Import Workflow adds a graph exported from ComfyUI^)
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
goto :eof

:move_old_copy
rem %1: a shipped workflow.json. Its 0.1 copy, data\workflows\<its folder's name>.json, becomes the
rem workflow.json of the same folder under data\workflows, unless that folder has one already.
set "SHIPPED=%~dp1"
for %%d in ("%~dp1.") do set "OLD=%HERE%\data\workflows\%%~nxd.json"
call set "FOLDER=%%SHIPPED:%HERE%\workflows\=%HERE%\data\workflows\%%"
if exist "%OLD%" if not exist "%FOLDER%workflow.json" (
    mkdir "%FOLDER%" 2>nul
    move "%OLD%" "%FOLDER%workflow.json" >nul
)
goto :eof
