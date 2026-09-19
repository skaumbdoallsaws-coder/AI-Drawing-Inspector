param()
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$launcher = Join-Path $PSScriptRoot 'launch_inspectorpro.ps1'
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'InspectorPro - Manual Layout.lnk'
$powershell = Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
$arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $launcher + '"'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
if ((Test-Path -LiteralPath $shortcutPath) -and $shortcut.Arguments -ne $arguments) {
    throw "A different shortcut already exists at $shortcutPath. It was not overwritten."
}
$shortcut.TargetPath = $powershell
$shortcut.Arguments = $arguments
$shortcut.WorkingDirectory = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$shortcut.Description = 'Start InspectorPro in the browser and open the manually built facility layout.'
$shortcut.WindowStyle = 7
$edge = Join-Path ${env:ProgramFiles(x86)} 'Microsoft/Edge/Application/msedge.exe'
if (Test-Path -LiteralPath $edge) { $shortcut.IconLocation = "$edge,0" }
$shortcut.Save()
[pscustomobject]@{ shortcut = $shortcutPath; target = $shortcut.TargetPath; arguments = $shortcut.Arguments; mode = 'browser' } | ConvertTo-Json
