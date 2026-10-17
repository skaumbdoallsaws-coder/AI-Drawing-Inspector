param(
    [Parameter(Mandatory = $true)][string]$Electron,
    [Parameter(Mandatory = $true)][string]$ProfileFile,
    [string]$Python = 'C:\Python314\python.exe',
    [switch]$UpgradeManagedProfile,
    [switch]$RepairRuntimeTarget
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$application = Join-Path $project 'desktop'
$icon = Join-Path $application 'assets\inspectorpro.ico'
foreach ($file in @($Electron, $ProfileFile, $Python, $icon, (Join-Path $application 'package.json'))) {
    if (-not [IO.Path]::IsPathRooted($file) -or -not (Test-Path -LiteralPath $file -PathType Leaf)) {
        throw "Required absolute file path is missing: $file"
    }
    if ($file.Contains('"')) { throw 'Quoted paths are not supported.' }
}
$profile = Get-Content -LiteralPath $ProfileFile -Raw | ConvertFrom-Json
if ($profile.mode -eq 'application') {
    if ($null -ne $profile.startupLayoutId -and $profile.startupLayoutId -notmatch '^fl-[A-Za-z0-9._-]{1,128}$') { throw 'The application profile has an invalid startup layout.' }
} elseif ($profile.mode -ne 'managed' -or $profile.acceptanceLayoutId -ne 'fl-reference-manual-20260812') {
    throw 'A normal application or isolated manual-layout profile is required.'
}

$shortcutPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'InspectorPro Desktop.lnk'
$modeFlag = if ($profile.mode -eq 'application') { ' --application' } else { '' }
$arguments = '"' + $application + '"' + $modeFlag + ' --profile-file "' + $ProfileFile + '" --python "' + $Python + '"'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
if ((Test-Path -LiteralPath $shortcutPath) -and
    ($shortcut.TargetPath -ne $Electron -or $shortcut.Arguments -ne $arguments)) {
    $repair = $RepairRuntimeTarget -and $profile.mode -eq 'application' -and
        $shortcut.Arguments -eq $arguments -and
        [IO.Path]::GetFileName($shortcut.TargetPath) -eq 'electron.exe'
    $oldPattern = '^' + [regex]::Escape('"' + $application + '" --profile-file "') + '([^\"]+)" --python "([^\"]+)"$'
    if ($repair) {
        Copy-Item -LiteralPath $shortcutPath -Destination ($shortcutPath + '.runtime-target-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.bak')
    } elseif (-not $UpgradeManagedProfile -or $profile.mode -ne 'application' -or $shortcut.TargetPath -ne $Electron -or $shortcut.Arguments -notmatch $oldPattern) {
        throw "A different shortcut already exists at $shortcutPath. It was not overwritten."
    } else {
        $oldProfile = Get-Content -LiteralPath $Matches[1] -Raw | ConvertFrom-Json
        if ($oldProfile.mode -ne 'managed') { throw 'Only the known managed-profile shortcut may be upgraded.' }
        Copy-Item -LiteralPath $shortcutPath -Destination ($shortcutPath + '.managed-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.bak')
    }
}
$shortcut.TargetPath = $Electron
$shortcut.Arguments = $arguments
$shortcut.WorkingDirectory = $application
$shortcut.Description = if ($profile.mode -eq 'application') { 'InspectorPro desktop - full application and configured startup layout.' } else { 'InspectorPro native desktop shell - isolated diagnostic profile.' }
# The GUI must launch normally; hiding it can suppress Electron's first window.
$shortcut.WindowStyle = 1
$shortcut.IconLocation = "$icon,0"
$shortcut.Save()
[pscustomobject]@{
    shortcut = $shortcutPath
    target = $shortcut.TargetPath
    arguments = $shortcut.Arguments
    mode = 'native-electron'
    profileFile = $ProfileFile
    icon = $shortcut.IconLocation
} | ConvertTo-Json
