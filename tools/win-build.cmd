@echo off
rem Sync the project to C:\hzys, then build the Windows exe there.
rem The real work is win-build.py: it names the exe "<version>-win-<arch>.exe"
rem and copies it into release\ (in the VM that folder is the Mac project
rem folder, reached through the \\Mac\HZYS share).
rem
rem NOTE: keep this file ASCII-only with CRLF endings - cmd.exe reads .cmd files
rem using the OEM code page, and non-ASCII + LF endings break the parser.
setlocal
chcp 65001 >nul
set "SHARE=%~dp0.."
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"

robocopy "%SHARE%" "C:\hzys" /MIR /XD .venv __pycache__ .ruff_cache .build dist build .git release /NFL /NDL /NJH /NJS /NP >nul
cd /d C:\hzys

"%PY%" tools\win-build.py
echo [win-build] exit=%ERRORLEVEL%
endlocal
