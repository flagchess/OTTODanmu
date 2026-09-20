@echo off
rem Sync the project to C:\hzys and start it without a console.
rem (Comments are ASCII on purpose: cmd reads .cmd files with the ANSI code page.)
setlocal
set "SHARE=%~dp0.."
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
if not exist "%PY%" set "PY=pythonw"
robocopy "%SHARE%" "C:\hzys" /MIR /XD .venv __pycache__ .ruff_cache .build /NFL /NDL /NJH /NJS /NP >nul
cd /d C:\hzys
start "" "%PY%" main.py
echo [win-run] launched
endlocal
