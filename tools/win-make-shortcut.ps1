# Create a desktop shortcut that syncs the project from the Mac share
# and starts the program with a console (log goes to win-run.log).
#
# Usage (inside the Windows VM):
#   powershell -ExecutionPolicy Bypass -File \\Mac\HZYS\tools\win-make-shortcut.ps1
#   powershell -ExecutionPolicy Bypass -File \\Mac\HZYS\tools\win-make-shortcut.ps1 -Name "My name"
#
# This file is ASCII-only on purpose: Windows PowerShell reads .ps1 files
# without a BOM using the ANSI code page, so non-ASCII would be mangled here.

param(
    [string]$Name = 'HZYS debug',
    [string]$Share = '\\Mac\HZYS'
)

$ErrorActionPreference = 'Stop'

$desktop = [Environment]::GetFolderPath('Desktop')
$link = Join-Path $desktop ($Name + '.lnk')

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\cmd.exe'
$shortcut.Arguments = '/k "' + (Join-Path $Share 'tools\win-debug.cmd') + '"'
$shortcut.WorkingDirectory = Join-Path $Share 'tools'
$shortcut.IconLocation = (Join-Path $Share 'assets\lizi.ico') + ',0'
$shortcut.Description = 'Sync project from the Mac share and start it with console + log'
$shortcut.Save()

Write-Output ('CREATED ' + $link)
