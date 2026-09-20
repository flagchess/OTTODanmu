# Click inside a window found by title (dev helper for driving the GUI in the VM).
#
# Usage (inside the Windows VM):
#   powershell -ExecutionPolicy Bypass -File win-click.ps1 -List
#   powershell -ExecutionPolicy Bypass -File win-click.ps1 -X 887 -Y 468
#
# X / Y are window-relative, the same coordinates you measure on a screenshot
# taken by win-shot.ps1 (both include the title bar).
#
# This file is ASCII-only on purpose: PowerShell reads .ps1 files without a BOM
# using the ANSI code page, so non-ASCII would be mangled here.

param(
    [string]$Match = "ver.2026",
    [int]$X = -1,
    [int]$Y = -1,
    [string]$Keys = "",
    [switch]$List
)

$signature = @"
using System;
using System.Text;
using System.Runtime.InteropServices;

public class ClickHelper {
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr hWnd, StringBuilder text, int count);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, int extra);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
}
"@
Add-Type -TypeDefinition $signature
[void][ClickHelper]::SetProcessDPIAware()

$script:found = [IntPtr]::Zero
$callback = [ClickHelper+EnumProc] {
    param($hWnd, $lParam)
    if (-not [ClickHelper]::IsWindowVisible($hWnd)) { return $true }
    $text = New-Object System.Text.StringBuilder 512
    [void][ClickHelper]::GetWindowTextW($hWnd, $text, $text.Capacity)
    if ($text.ToString() -like "*$Match*") {
        $script:found = $hWnd
        return $false
    }
    return $true
}
[void][ClickHelper]::EnumWindows($callback, [IntPtr]::Zero)

if ($script:found -eq [IntPtr]::Zero) {
    Write-Output "NOTFOUND $Match"
    exit 1
}

$rect = New-Object ClickHelper+RECT
[void][ClickHelper]::GetWindowRect($script:found, [ref]$rect)
$w = $rect.Right - $rect.Left
$h = $rect.Bottom - $rect.Top
Write-Output ("WINDOW left={0} top={1} size={2}x{3}" -f $rect.Left, $rect.Top, $w, $h)

if ($List) { exit 0 }
if ($X -lt 0 -or $Y -lt 0) {
    Write-Output "NOCLICK (pass -X and -Y, or -List)"
    exit 0
}

[void][ClickHelper]::SetForegroundWindow($script:found)
Start-Sleep -Milliseconds 300
$absX = $rect.Left + $X
$absY = $rect.Top + $Y
[void][ClickHelper]::SetCursorPos($absX, $absY)
Start-Sleep -Milliseconds 200
[ClickHelper]::mouse_event(0x0002, 0, 0, 0, 0)
Start-Sleep -Milliseconds 80
[ClickHelper]::mouse_event(0x0004, 0, 0, 0, 0)
Write-Output ("CLICKED {0},{1} (window {2},{3})" -f $absX, $absY, $rect.Left, $rect.Top)

if ($Keys -ne "") {
    Add-Type -AssemblyName System.Windows.Forms
    Start-Sleep -Milliseconds 300
    [System.Windows.Forms.SendKeys]::SendWait($Keys)
    Write-Output ("TYPED {0}" -f $Keys)
}
