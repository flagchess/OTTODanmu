# 在 Windows 里截取指定窗口（显示器休眠时也能抓到内容），保存为 PNG
# 用法: powershell -ExecutionPolicy Bypass -File win-shot.ps1 [-Match "ver.2026"] [-Out "C:\hzys\win-shot.png"]
param(
    [string]$Match = "ver.2026",
    [string]$Out = "C:\hzys\win-shot.png"
)

Add-Type -AssemblyName System.Drawing

# 先声明 DPI 感知，否则在高缩放（比如 200%）的屏幕上会被 GDI 虚拟化，
# 抓到的位图只有实际尺寸的一半
Add-Type -TypeDefinition @"
using System.Runtime.InteropServices;
public class DpiHelper {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
"@
[void][DpiHelper]::SetProcessDPIAware()

$signature = @"
using System;
using System.Text;
using System.Runtime.InteropServices;

public class ShotHelper {
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr hWnd, StringBuilder text, int count);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdc, uint flags);

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
}
"@
Add-Type -TypeDefinition $signature

$script:found = [IntPtr]::Zero
$callback = [ShotHelper+EnumProc] {
    param($hWnd, $lParam)
    if ([ShotHelper]::IsWindowVisible($hWnd)) {
        $builder = New-Object System.Text.StringBuilder 512
        [void][ShotHelper]::GetWindowTextW($hWnd, $builder, 512)
        $title = $builder.ToString()
        if ($title -like "*$Match*") {
            Write-Output "MATCH: [$title]"
            $script:found = $hWnd
            return $false
        }
    }
    return $true
}

[void][ShotHelper]::EnumWindows($callback, [IntPtr]::Zero)

if ($script:found -eq [IntPtr]::Zero) {
    Write-Output "WINDOW_NOT_FOUND"
    exit 1
}

$rect = New-Object ShotHelper+RECT
[void][ShotHelper]::GetWindowRect($script:found, [ref]$rect)
$width = $rect.Right - $rect.Left
$height = $rect.Bottom - $rect.Top

$bitmap = New-Object System.Drawing.Bitmap $width, $height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$hdc = $graphics.GetHdc()
[void][ShotHelper]::PrintWindow($script:found, $hdc, 2)   # 2 = PW_RENDERFULLCONTENT
$graphics.ReleaseHdc($hdc)
$graphics.Dispose()
$bitmap.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$bitmap.Dispose()

Write-Output "SAVED $width x $height -> $Out"
