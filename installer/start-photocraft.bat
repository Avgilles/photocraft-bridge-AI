@echo off
rem Starts PhotoCraft with the control server and work folder xp-photocraft needs.
rem Looks for photocraft.exe in the usual places; otherwise drop photocraft.exe onto this file,
rem or write its full path in photocraft-path.txt next to this script.
setlocal
set "WORK=%LOCALAPPDATA%\xp-photocraft\work"
mkdir "%WORK%" 2>nul
set "PC="
if not "%~1"=="" if exist "%~1" set "PC=%~1"
if not defined PC if exist "%~dp0photocraft-path.txt" set /p PC=<"%~dp0photocraft-path.txt"
if not defined PC if exist "%~dp0photocraft.exe" set "PC=%~dp0photocraft.exe"
if not defined PC if exist "%LOCALAPPDATA%\Programs\PhotoCraft\photocraft.exe" set "PC=%LOCALAPPDATA%\Programs\PhotoCraft\photocraft.exe"
if not defined PC if exist "%ProgramFiles%\PhotoCraft\photocraft.exe" set "PC=%ProgramFiles%\PhotoCraft\photocraft.exe"
if not defined PC (
    echo  photocraft.exe not found. Drop it onto this script, or write its full path in:
    echo  %~dp0photocraft-path.txt
    pause
    exit /b 1
)
start "" "%PC%" --control 7878 --control-token-file "%WORK%\control.token" --automation-read-root "%WORK%" --automation-write-root "%WORK%"
