param(
    [string]$Python = 'C:\Python314\python.exe',
    [switch]$NoBrowser,
    [switch]$NoErrorDialog
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$layoutId = 'fl-reference-manual-20260812'
$logs = Join-Path $root '.runtime/browser-launcher'
$mutex = $null
$ownsMutex = $false

function Test-Listening([int]$Port) {
    $client = [Net.Sockets.TcpClient]::new()
    try {
        $pending = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        if (-not $pending.AsyncWaitHandle.WaitOne(350)) { return $false }
        $client.EndConnect($pending)
        return $true
    } catch { return $false }
    finally { $client.Dispose() }
}

function Test-InspectorPro([int]$Port) {
    try {
        $origin = "http://127.0.0.1:$Port"
        $layout = Invoke-RestMethod -Uri "$origin/api/facility-layouts/site-local/$layoutId" -TimeoutSec 3
        if ($layout.layout.layoutId -ne $layoutId -or @($layout.layout.placements).Count -eq 0) { return $false }
        $page = Invoke-WebRequest -Uri "$origin/" -UseBasicParsing -TimeoutSec 3
        return $page.Content.Contains('<title>InspectorPro')
    } catch { return $false }
}

try {
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "Python was not found: $Python" }
    $layoutPath = Join-Path $root ".runtime/facility-layout/layouts/local/site-local/layouts/$layoutId.json"
    if (-not (Test-Path -LiteralPath $layoutPath -PathType Leaf)) { throw "The manual layout was not found: $layoutPath" }
    [IO.Directory]::CreateDirectory($logs) | Out-Null
    $hash = [Security.Cryptography.SHA256]::Create()
    try { $key = [BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($root))).Replace('-', '').Substring(0, 24) }
    finally { $hash.Dispose() }
    $mutex = [Threading.Mutex]::new($false, "Local\InspectorProBrowserLaunch-$key")
    try { $ownsMutex = $mutex.WaitOne(190000) }
    catch [Threading.AbandonedMutexException] { $ownsMutex = $true }
    if (-not $ownsMutex) { throw 'InspectorPro is already starting. Please try the shortcut again shortly.' }

    $port = $null
    $firstFree = $null
    foreach ($candidate in 8000..8009) {
        if (Test-Listening $candidate) {
            if (Test-InspectorPro $candidate) { $port = $candidate; break }
        } elseif ($null -eq $firstFree) { $firstFree = $candidate }
    }
    $startedServer = $false
    if ($null -eq $port) {
        if ($null -eq $firstFree) { throw 'Ports 8000-8009 are occupied. No existing server was stopped.' }
        $port = $firstFree
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
        $stdout = Join-Path $logs "$stamp.stdout.log"
        $stderr = Join-Path $logs "$stamp.stderr.log"
        $server = Start-Process -FilePath $Python -ArgumentList @('-m', 'uvicorn', 'server:app', '--host', '127.0.0.1', '--port', [string]$port) `
            -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
        $startedServer = $true
        $deadline = [DateTime]::UtcNow.AddSeconds(180)
        while (-not (Test-InspectorPro $port)) {
            $server.Refresh()
            if ($server.HasExited) { throw "InspectorPro could not start. See $stderr" }
            if ([DateTime]::UtcNow -ge $deadline) { throw "InspectorPro is taking longer than expected. Startup logs: $logs. The server was not forcibly stopped; try the shortcut again shortly." }
            Start-Sleep -Milliseconds 600
        }
    }
    $url = "http://127.0.0.1:$port/?facilityLayoutId=$layoutId"
    [pscustomobject]@{ status = 'ready'; url = $url; startedServer = $startedServer; mode = 'browser'; savedLayoutChangedByLauncher = $false } | ConvertTo-Json
    if (-not $NoBrowser) { Start-Process -FilePath $url | Out-Null }
} catch {
    $message = $_.Exception.Message
    if (-not $NoErrorDialog) {
        Add-Type -AssemblyName System.Windows.Forms
        [Windows.Forms.MessageBox]::Show($message, 'InspectorPro launch', 'OK', 'Error') | Out-Null
    }
    Write-Error $message
    exit 1
} finally {
    if ($ownsMutex) { $mutex.ReleaseMutex() }
    if ($null -ne $mutex) { $mutex.Dispose() }
}
