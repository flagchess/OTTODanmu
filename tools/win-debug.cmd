@echo off
rem Sync the project to C:\hzys and start it with a console.
rem The desktop shortcut points here; output goes to win-run.log in the share.
rem (Comments are ASCII on purpose: cmd reads .cmd files with the ANSI code page.)
setlocal
set "SHARE=%~dp0.."
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"
robocopy "%SHARE%" "C:\hzys" /MIR /XD .venv __pycache__ .ruff_cache .build /NFL /NDL /NJH /NJS /NP >nul
cd /d C:\hzys
echo [win-debug] running, log: %SHARE%\win-run.log
"%PY%" -u main.py > "%SHARE%\win-run.log" 2>&1
echo [win-debug] app exit code: %ERRORLEVEL%
endlocal
