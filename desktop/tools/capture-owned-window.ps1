param(
    [Parameter(Mandatory=$true)][long]$WindowHandle,
    [Parameter(Mandatory=$true)][int]$OwnerProcessId,
    [Parameter(Mandatory=$true)][string]$OutputPath
)
$ErrorActionPreference = 'Stop'
if (-not [IO.Path]::IsPathRooted($OutputPath) -or (Test-Path -LiteralPath $OutputPath)) { throw 'A new absolute capture path is required' }
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class OwnedWindowCapture {
    [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr handle, out uint processId);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr handle, out Rect rect);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr handle, IntPtr dc, uint flags);
}
'@
$handle = [IntPtr]::new($WindowHandle)
$actualOwner = [uint32]0
[void][OwnedWindowCapture]::GetWindowThreadProcessId($handle, [ref]$actualOwner)
if ($actualOwner -ne $OwnerProcessId) { throw 'Native window does not belong to the expected process' }
$rect = [OwnedWindowCapture+Rect]::new()
if (-not [OwnedWindowCapture]::GetWindowRect($handle,[ref]$rect)) { throw 'Owned window rectangle unavailable' }
$width = $rect.Right - $rect.Left
$height = $rect.Bottom - $rect.Top
if ($width -lt 1 -or $height -lt 1 -or $width -gt 8192 -or $height -gt 8192) { throw 'Capture bounds rejected' }
$bitmap = [Drawing.Bitmap]::new($width,$height)
$graphics = [Drawing.Graphics]::FromImage($bitmap)
$dc = $graphics.GetHdc()
try {
    if (-not [OwnedWindowCapture]::PrintWindow($handle,$dc,2)) { throw 'Owned window rendering unavailable' }
} finally { $graphics.ReleaseHdc($dc); $graphics.Dispose() }
try {
    $colors = [Collections.Generic.HashSet[int]]::new()
    for ($y=0; $y -lt $height; $y += [Math]::Max(1,[int]($height/80))) {
        for ($x=0; $x -lt $width; $x += [Math]::Max(1,[int]($width/80))) { [void]$colors.Add($bitmap.GetPixel($x,$y).ToArgb()) }
    }
    if ($colors.Count -lt 4) { throw 'Native capture is blank' }
    $bitmap.Save($OutputPath,[Drawing.Imaging.ImageFormat]::Png)
    @{ method='PrintWindow-owned-hwnd'; processId=$actualOwner; width=$width; height=$height; sampledColors=$colors.Count } | ConvertTo-Json -Compress
} finally { $bitmap.Dispose() }
