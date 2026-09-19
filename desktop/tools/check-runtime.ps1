param(
    [Parameter(Mandatory=$true)][string]$ElectronDesktop,
    [string]$Python = 'python',
    [ValidateRange(1024,65535)][int]$Port = 8464,
    [switch]$StartupDiagnosticsOnly,
    [switch]$Research
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Use an ordinary, unelevated PowerShell terminal.'
}
if ($Research -and $StartupDiagnosticsOnly) { throw 'Research requires full application checks.' }
$source = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$electron = (Resolve-Path -LiteralPath $ElectronDesktop).Path
$pythonPath = (Get-Command $Python -CommandType Application -ErrorAction Stop).Source
$root = Join-Path (Split-Path $source -Parent) '.runtime/desktop-acceptance'
$stamp = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0,8)
$snapshot = Join-Path $root ('source-' + $stamp)
$output = Join-Path $root 'evidence'

# The snapshot and fixture tools independently reject overlap, links and reuse.
# No original directory is deleted, moved or used as a writable fixture.
& $pythonPath -B (Join-Path $source 'desktop/tools/prepare-snapshot.py') --source $source --destination $snapshot
if ($LASTEXITCODE -ne 0) { throw 'Source snapshot failed; native application was not launched.' }
$arguments = @('-B', (Join-Path $snapshot 'desktop/tools/run-runtime-integration.py'),
    '--electron-desktop', $electron, '--output-root', $output, '--port', [string]$Port)
if ($StartupDiagnosticsOnly) { $arguments += '--startup-diagnostics-only' }
if ($Research) { $arguments += '--research-check' }
& $pythonPath @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Acceptance is incomplete. The saved reports under $output identify the failed or pending gate."
}
Write-Output "Native checks finished. Inspect the new screenshots and reports under $output before promotion."
