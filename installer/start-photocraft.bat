@echo off
rem Starts PhotoCraft with the control server and the work folder xp-photocraft needs (data\work).
rem Looks for photocraft.exe next to this script, in a PhotoCraft* folder here or one level up, in
rem the usual install places; else drop photocraft.exe onto this file, or write its full path in
rem photocraft-path.txt next to this script.
setlocal
set "HERE=%~dp0"
set "WORK=%HERE%data\work"
mkdir "%WORK%" 2>nul
set "PC="
if not "%~1"=="" if exist "%~1" set "PC=%~1"
if not defined PC if exist "%HERE%photocraft-path.txt" set /p PC=<"%HERE%photocraft-path.txt"
if not defined PC if exist "%HERE%photocraft.exe" set "PC=%HERE%photocraft.exe"
if not defined PC for /d %%d in ("%HERE%PhotoCraft*" "%HERE%..\PhotoCraft*") do if not defined PC if exist "%%~d\photocraft.exe" set "PC=%%~d\photocraft.exe"
if not defined PC if exist "%LOCALAPPDATA%\Programs\PhotoCraft\photocraft.exe" set "PC=%LOCALAPPDATA%\Programs\PhotoCraft\photocraft.exe"
if not defined PC if exist "%ProgramFiles%\PhotoCraft\photocraft.exe" set "PC=%ProgramFiles%\PhotoCraft\photocraft.exe"
if not defined PC (
    echo  photocraft.exe not found. Drop it onto this script, or write its full path in:
    echo  %HERE%photocraft-path.txt
    pause
    exit /b 1
)
start "" "%PC%" --control 7878 --control-token-file "%WORK%\control.token" --automation-read-root "%WORK%" --automation-write-root "%WORK%"
