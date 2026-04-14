param(
    [string]$OutputDir = "",
    [string[]]$Views = @(
        "Detail View B (1 : 1)",
        "Section View C-C",
        "Drawing View1",
        "Drawing View2",
        "Drawing View3",
        "Drawing View4"
    ),
    [switch]$PauseBetweenRuns
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $repoRoot "tmp\extractor_validation"
}

$extractor = Join-Path $repoRoot "SolidWorksExtractor\bin\Debug\SolidWorksExtractor.exe"
$python = Join-Path $repoRoot ".venv313\Scripts\python.exe"
$mergeScript = Join-Path $repoRoot "scripts\merge_drawing_maps.py"

if (-not (Test-Path $extractor)) {
    throw "Extractor not found: $extractor"
}
if (-not (Test-Path $python)) {
    throw "Python not found: $python"
}
if (-not (Test-Path $mergeScript)) {
    throw "Merge script not found: $mergeScript"
}

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

function Get-SafeName([string]$value) {
    $safe = $value -replace '[^A-Za-z0-9]+', '_'
    $safe = $safe.Trim('_')
    if ([string]::IsNullOrWhiteSpace($safe)) { $safe = "view" }
    return $safe
}

$successful = @()
$failed = @()

Write-Host "Output directory: $OutputDir"
Write-Host "Views to extract: $($Views -join ', ')"
Write-Host ""

foreach ($view in $Views) {
    $slug = Get-SafeName $view
    $outFile = Join-Path $OutputDir ("1030017_" + $slug + "_drawing_map.json")

    Write-Host "=== Extracting: $view ===" -ForegroundColor Cyan
    & $extractor --active --output $outFile --drawing-target-view $view
    $exitCode = $LASTEXITCODE

    $usable = $false
    if (Test-Path $outFile) {
        try {
            $json = Get-Content $outFile -Raw | ConvertFrom-Json
            $viewCount = 0
            if ($json.sheets) {
                foreach ($sheet in $json.sheets) {
                    if ($sheet.views) {
                        $viewCount += @($sheet.views).Count
                    }
                }
            }
            $usable = ($viewCount -gt 0)
        } catch {
            $usable = $false
        }
    }

    if (($exitCode -eq 0 -or $exitCode -eq 2) -and $usable) {
        Write-Host "Saved: $outFile (exit $exitCode)" -ForegroundColor Green
        $successful += $outFile
    } else {
        Write-Host "Failed: $view (exit $exitCode, usable=$usable)" -ForegroundColor Red
        $failed += $view
    }

    Write-Host ""

    if ($PauseBetweenRuns) {
        Read-Host "Reopen/settle the drawing if needed, then press Enter for the next view"
    }
}

Write-Host "=== Summary ==="
Write-Host "Successful files: $($successful.Count)"
foreach ($file in $successful) {
    Write-Host "  $file"
}
if ($failed.Count -gt 0) {
    Write-Host "Failed views:" -ForegroundColor Yellow
    foreach ($view in $failed) {
        Write-Host "  $view"
    }
}

if ($successful.Count -ge 2) {
    $mergedOut = Join-Path $OutputDir "1030017_merged_drawing_map.json"
    Write-Host ""
    Write-Host "Merge command:" -ForegroundColor Cyan
    Write-Host "& '$python' '$mergeScript' -o '$mergedOut' " -NoNewline
    for ($i = 0; $i -lt $successful.Count; $i++) {
        Write-Host "'$($successful[$i])'" -NoNewline
        if ($i -lt $successful.Count - 1) { Write-Host " " -NoNewline }
    }
    Write-Host ""
}
