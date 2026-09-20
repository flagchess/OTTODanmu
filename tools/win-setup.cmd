@echo off
rem Install this project's dependencies on Windows (dev helper, safe to re-run).
rem (Comments are ASCII on purpose: cmd reads .cmd files with the ANSI code page.)
setlocal
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"
echo [win-setup] interpreter: %PY%
"%PY%" -m pip install --disable-pip-version-check numpy soundfile pypinyin psola websocket-client requests Pillow httpx qrcode brotli playsound3 sv-ttk darkdetect pywebview
echo [win-setup] pip exit code: %ERRORLEVEL%
endlocal
