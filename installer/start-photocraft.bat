@echo off
rem Starts PhotoCraft with the control server and the work folder xp-photocraft needs (data\work).
rem Looks for PhotoCraft XP's photocraft.exe next to this script, or in a PhotoCraft* folder here, one
rem or two levels up (Windows' "Extract All" adds a folder named after each zip), possibly inside one
rem more PhotoCraft* folder; else drop photocraft.exe onto this file, or write its full path in
rem photocraft-path.txt next to this script. Never an installed PhotoCraft: it has no task bar.
setlocal
set "HERE=%~dp0"
set "WORK=%HERE%data\work"
mkdir "%WORK%" 2>nul
rem This folder first on PATH: PhotoCraft's task bar runs the bridge that sits next to this script.
set "PATH=%HERE:~0,-1%;%PATH%"
set "PC="
if not "%~1"=="" if exist "%~1" set "PC=%~1"
if not defined PC if exist "%HERE%photocraft-path.txt" set /p PC=<"%HERE%photocraft-path.txt"
if not defined PC if exist "%HERE%photocraft.exe" set "PC=%HERE%photocraft.exe"
if not defined PC for /d %%d in ("%HERE%PhotoCraft*" "%HERE%..\PhotoCraft*" "%HERE%..\..\PhotoCraft*") do (
    if not defined PC if exist "%%~d\photocraft.exe" set "PC=%%~d\photocraft.exe"
    if not defined PC for /d %%e in ("%%~d\PhotoCraft*") do if not defined PC if exist "%%~e\photocraft.exe" set "PC=%%~e\photocraft.exe"
)
if not defined PC (
    echo  PhotoCraft XP not found. Unzip PhotoCraft-XP-windows-x64.zip into the same folder as this
    echo  one, or drop its photocraft.exe onto this script, or write its full path in:
    echo  %HERE%photocraft-path.txt
    pause
    exit /b 1
)
start "" "%PC%" --control 7878 --control-token-file "%WORK%\control.token" --automation-read-root "%WORK%" --automation-write-root "%WORK%"
