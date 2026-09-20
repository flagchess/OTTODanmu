@echo off
rem Sync the project, then run any command inside the VM (dev/verification helper).
rem Usage: win-cmd.cmd tools\win-check.py
rem (Comments are ASCII on purpose: cmd reads .cmd files with the ANSI code page.)
setlocal
robocopy "%~dp0.." "C:\hzys" /MIR /XD .venv __pycache__ .ruff_cache .build /NFL /NDL /NJH /NJS /NP >nul
cd /d C:\hzys
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" %*
endlocal
