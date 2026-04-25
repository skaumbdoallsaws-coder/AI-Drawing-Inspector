# run_fea_extract.ps1
#
# Worker-side runner for the FEA extractor. Wraps SolidWorksExtractor.exe with
# the conventions defined in SolidWorksExtractor/FEA_WORKER_README.md:
#   * always run the locally-built .exe out of bin/Debug (never copy it)
#   * always require explicit study selection; pass -AllowImplicit to opt in to
#     the legacy "first completed static study" path
#   * always extract into a temp staging directory under incoming_fea/.staging/,
#     then move the artifacts into the canonical
#       incoming_fea/<part-slug>/<study-slug>/
#     directory based on the slug the extractor reports in its manifest. This
#     guarantees one placement convention regardless of how the study was
#     selected, and prevents a -StudyIndex / -AllowImplicit re-run from quietly
#     accumulating mixed artifacts in a placeholder directory.
#   * refuse to overwrite an existing canonical directory unless -Force is set
#   * refuse to move artifacts unless temp staging contains exactly the four
#     canonical files; view PNGs and other extras are contract violations
#
# Inspect-only modes:
#   -Preflight     prints SolidWorks version + add-in + study list, then exits
#   -ListStudies   prints just the study list, then exits
#
# Examples:
#   .\scripts\run_fea_extract.ps1 -Active -Preflight
#   .\scripts\run_fea_extract.ps1 -Active -ListStudies
#   .\scripts\run_fea_extract.ps1 -Active -PartNumber 1234567 -StudyName "Static 1"
#   .\scripts\run_fea_extract.ps1 -PartFile "C:\parts\Mounting Plate.SLDPRT" -PartNumber MP01 -StudyIndex 0

[CmdletBinding(DefaultParameterSetName = "Active")]
param(
    [Parameter(ParameterSetName = "Active", Mandatory = $true)]
    [switch]$Active,

    [Parameter(ParameterSetName = "File", Mandatory = $true)]
    [string]$PartFile,

    # Required for extraction (used in output directory + filenames). Optional
    # for -Preflight / -ListStudies. Spaces / unsafe chars get sanitised.
    [string]$PartNumber,

    # Pick exactly one (mutually exclusive with each other and with -AllowImplicit).
    [string]$StudyName,
    [Nullable[int]]$StudyIndex,

    # Inspect-only modes. Mutually exclusive with each other and with extraction.
    [switch]$Preflight,
    [switch]$ListStudies,

    # Opt in to the legacy "first completed static study" fallback. Off by default.
    [switch]$AllowImplicit,

    # Allow overwriting an existing canonical staging directory for the same
    # (part, study). Without this, the script refuses to clobber prior artifacts
    # so accidental re-runs cannot quietly destroy provenance.
    [switch]$Force,

    # If the picked study's mesh is "ExistsAndNotCurrent" (the part has been
    # modified since the mesh was generated), let the extractor call
    # study.MeshAndRun() to re-mesh and re-solve before extraction. Off by
    # default because re-meshing modifies the document's saved analysis state.
    [switch]$AllowRemesh
)

$ErrorActionPreference = "Stop"

# --- repo root and required tools ---
$repoRoot = Split-Path -Parent $PSScriptRoot
$extractor = Join-Path $repoRoot "SolidWorksExtractor\bin\Debug\SolidWorksExtractor.exe"

# --- mode validation: exactly one mode at a time ---
$inspectModeCount = 0
if ($Preflight) { $inspectModeCount++ }
if ($ListStudies) { $inspectModeCount++ }
if ($inspectModeCount -gt 1) {
    Write-Host "ERROR: -Preflight and -ListStudies are mutually exclusive." -ForegroundColor Red
    exit 1
}

$selectorCount = 0
if (-not [string]::IsNullOrWhiteSpace($StudyName)) { $selectorCount++ }
if ($null -ne $StudyIndex) { $selectorCount++ }
if ($AllowImplicit) { $selectorCount++ }

function Assert-ExtractorBuilt {
    if (-not (Test-Path $extractor)) {
        Write-Host "ERROR: Extractor not built." -ForegroundColor Red
        Write-Host "       Expected at: $extractor"
        Write-Host "       Build first per FEA_WORKER_README.md:"
        Write-Host '         msbuild SolidWorksExtractor\SolidWorksExtractor.csproj /p:Configuration=Debug'
        exit 1
    }
}

function Get-GitHeadCommit {
    $oldErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $head = @(& git -C $repoRoot rev-parse HEAD 2>&1)
        $gitExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $oldErrorActionPreference
    }

    $commit = @($head | Where-Object { $_ -match '^[0-9a-fA-F]{40}$' } | Select-Object -First 1)
    if ($gitExit -ne 0 -or $commit.Count -eq 0 -or [string]::IsNullOrWhiteSpace($commit[0])) {
        Write-Host "ERROR: Could not resolve git HEAD for provenance." -ForegroundColor Red
        Write-Host "       Ensure Git is installed and this runner is executed inside the repo."
        if ($head.Count -gt 0) {
            $head | ForEach-Object { Write-Host "       $_" }
        }
        exit 1
    }
    return $commit[0].Trim()
}

function Test-IsTransientStagingPath {
    param([string]$Path)
    $normalized = ($Path -replace '\\', '/').Trim('"')
    return ($normalized -eq "incoming_fea/.staging" -or $normalized.StartsWith("incoming_fea/.staging/"))
}

function Test-IsRunSourcePath {
    param([string]$Path)
    $normalized = ($Path -replace '\\', '/').Trim('"')
    if (Test-IsTransientStagingPath $normalized) { return $false }
    if ($normalized -eq "scripts/run_fea_extract.ps1") { return $true }
    if (-not $normalized.StartsWith("SolidWorksExtractor/")) { return $false }

    $extension = [System.IO.Path]::GetExtension($normalized).ToLowerInvariant()
    $leaf = [System.IO.Path]::GetFileName($normalized)
    $sourceExtensions = @(".cs", ".csproj", ".sln", ".config", ".resx", ".settings", ".props", ".targets")
    return (($sourceExtensions -contains $extension) -or $leaf -eq "packages.config")
}

function Assert-CleanRunSource {
    $head = Get-GitHeadCommit
    Write-Host "Git HEAD:  $head" -ForegroundColor Cyan

    $oldErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $statusLines = @(& git -C $repoRoot status --porcelain=v1 --untracked-files=all 2>&1)
        $gitExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $oldErrorActionPreference
    }

    if ($gitExit -ne 0) {
        Write-Host "ERROR: Could not inspect git worktree cleanliness." -ForegroundColor Red
        $statusLines | ForEach-Object { Write-Host "       $_" }
        exit 1
    }

    $dirtyRunSource = New-Object System.Collections.Generic.List[string]
    foreach ($line in $statusLines) {
        $lineText = [string]$line
        if ([string]::IsNullOrWhiteSpace($lineText)) { continue }

        $pathText = if ($lineText.Length -gt 3) { $lineText.Substring(3) } else { $lineText }
        $paths = @($pathText)
        if ($pathText.Contains(" -> ")) {
            $paths = @($pathText -split " -> ")
        }

        foreach ($path in $paths) {
            if (Test-IsRunSourcePath $path) {
                $dirtyRunSource.Add($lineText)
                break
            }
        }
    }

    if ($dirtyRunSource.Count -gt 0) {
        Write-Host ""
        Write-Host "ERROR: Worker extraction source is not clean." -ForegroundColor Red
        Write-Host "       Commit source changes first, then rerun extraction so the manifest"
        Write-Host "       extractor_git_commit identifies the exact code used."
        Write-Host ""
        Write-Host "Dirty source entries:" -ForegroundColor Red
        $dirtyRunSource | ForEach-Object { Write-Host "       $_" }
        exit 4
    }

    return $head
}

# --- inspect-only modes short-circuit, no slug needed ---
if ($Preflight -or $ListStudies) {
    if ($selectorCount -gt 0) {
        Write-Host "ERROR: Study selector flags do not apply in inspect-only modes." -ForegroundColor Red
        exit 1
    }

    Assert-ExtractorBuilt

    $args = New-Object System.Collections.Generic.List[string]
    if ($Active) {
        $args.Add("--active")
    } else {
        if (-not (Test-Path $PartFile)) {
            Write-Host "ERROR: PartFile not found: $PartFile" -ForegroundColor Red
            exit 1
        }
        $args.Add($PartFile)
    }
    if ($Preflight) { $args.Add("--fea-preflight") }
    elseif ($ListStudies) { $args.Add("--fea-list-studies") }

    Write-Host "Running: $extractor $($args -join ' ')" -ForegroundColor Cyan
    & $extractor @args
    exit $LASTEXITCODE
}

# --- extraction mode: enforce explicit selection (the reviewer's rule #2) ---
if ($selectorCount -eq 0) {
    Write-Host "ERROR: No study selector supplied." -ForegroundColor Red
    Write-Host "       Pass -StudyName <name>  OR  -StudyIndex <n>"
    Write-Host "       (Add -AllowImplicit to opt in to the 'first completed static' fallback.)"
    exit 1
}
if ($selectorCount -gt 1) {
    Write-Host "ERROR: -StudyName, -StudyIndex, -AllowImplicit are mutually exclusive." -ForegroundColor Red
    exit 1
}

if ([string]::IsNullOrWhiteSpace($PartNumber)) {
    if ($Active) {
        Write-Host "ERROR: -PartNumber is required for extraction with -Active." -ForegroundColor Red
        Write-Host "       (Cannot derive part number from active document -- pass it explicitly.)"
        exit 1
    } else {
        $PartNumber = [System.IO.Path]::GetFileNameWithoutExtension($PartFile)
        Write-Host "PartNumber not supplied; derived from filename: $PartNumber" -ForegroundColor Yellow
    }
}

$currentHead = Assert-CleanRunSource
Assert-ExtractorBuilt

# --- mirror the C# MakeStudySlug logic so the output directory matches the
#     actual filenames that the extractor will produce ---
function Get-StudySlug {
    param(
        [string]$Name,
        [int]$IndexFallback = -1
    )
    if ([string]::IsNullOrWhiteSpace($Name)) {
        if ($IndexFallback -ge 0) { return "study_$IndexFallback" }
        return "study_unknown"
    }
    $sb = New-Object System.Text.StringBuilder
    foreach ($c in $Name.ToCharArray()) {
        $code = [int][char]$c
        if ($code -lt 128 -and [char]::IsLetterOrDigit($c)) {
            [void]$sb.Append([char]::ToLowerInvariant($c))
        }
        elseif ($c -eq '-') {
            [void]$sb.Append('-')
        }
        else {
            [void]$sb.Append('_')
        }
    }
    $s = $sb.ToString()
    while ($s.Contains("__")) { $s = $s.Replace("__", "_") }
    $s = $s.Trim('_', '-')
    if ($s.Length -gt 64) { $s = $s.Substring(0, 64).TrimEnd('_', '-') }
    if ([string]::IsNullOrEmpty($s)) {
        if ($IndexFallback -ge 0) { return "study_$IndexFallback" }
        return "study_unknown"
    }
    return $s
}

# Pipeline:
#   1. Always extract into a temp staging directory under incoming_fea/.staging/.
#   2. Read the manifest the extractor emits to discover the *actual* study slug
#      (which the worker may not know in -StudyIndex / -AllowImplicit modes).
#   3. Compute the canonical staging directory  incoming_fea/<part-slug>/<study-slug>/
#      and move the artifacts there. This guarantees there is one and only one
#      placement convention regardless of how the study was selected, and that
#      previous runs of a *different* study cannot accumulate in the same folder.
#   4. If the canonical directory already has artifacts (re-run of the same
#      study), require -Force to overwrite, otherwise refuse.
# Validate -PartFile BEFORE creating any temp directory. Otherwise a typo in
# the path would leave an empty .staging\<part>-<timestamp>\ residue, weakening
# the "non-empty .staging means an interrupted run" rule documented in the README.
if (-not $Active) {
    if (-not (Test-Path $PartFile)) {
        Write-Host "ERROR: PartFile not found: $PartFile" -ForegroundColor Red
        exit 1
    }
}

$partSlug = Get-StudySlug -Name $PartNumber
$incomingRoot = Join-Path $repoRoot "incoming_fea"
$tempStagingRoot = Join-Path $incomingRoot ".staging"
New-Item -ItemType Directory -Path $tempStagingRoot -Force | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$tempDir = Join-Path $tempStagingRoot "$partSlug-$timestamp"
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

# --- build extractor argument list ---
$extractorArgs = New-Object System.Collections.Generic.List[string]

if ($Active) {
    $extractorArgs.Add("--active")
} else {
    $extractorArgs.Add($PartFile)
}

$extractorArgs.Add("--fea")
$extractorArgs.Add("--no-views")

if (-not [string]::IsNullOrWhiteSpace($StudyName)) {
    $extractorArgs.Add("--fea-study-name")
    $extractorArgs.Add($StudyName)
} elseif ($null -ne $StudyIndex) {
    $extractorArgs.Add("--fea-study-index")
    $extractorArgs.Add(([int]$StudyIndex).ToString())
}
# If -AllowImplicit, no selection flag -- extractor falls through to legacy path.

if ($AllowRemesh) {
    $extractorArgs.Add("--fea-allow-remesh")
}

# The extractor places FEA outputs in the same directory as its --output JSON.
# Point that JSON at the temp staging dir so all 4 FEA files land there together.
$extractorArgs.Add("--output")
$extractorArgs.Add((Join-Path $tempDir "$PartNumber.json"))

Write-Host "TempDir:   $tempDir" -ForegroundColor Cyan
Write-Host "Running:   $extractor $($extractorArgs -join ' ')" -ForegroundColor Cyan
Write-Host ""

& $extractor @extractorArgs
$extractorExit = $LASTEXITCODE

if ($extractorExit -ne 0) {
    Write-Host ""
    Write-Host "Extractor exited with code $extractorExit." -ForegroundColor Red
    Write-Host "Temp staging directory left in place for inspection: $tempDir" -ForegroundColor Yellow
    exit $extractorExit
}

# --- discover the actual study slug from the manifest ---
$manifests = @(Get-ChildItem -Path $tempDir -Filter "${PartNumber}_fea_*_manifest.json" -File -ErrorAction SilentlyContinue)
if ($manifests.Count -eq 0) {
    Write-Host ""
    Write-Host "ERROR: Extractor returned 0 but no FEA manifest was written to $tempDir." -ForegroundColor Red
    Write-Host "       The run is incomplete -- inspect console output above and the temp dir."
    exit 2
}
if ($manifests.Count -gt 1) {
    Write-Host ""
    Write-Host "ERROR: Extractor wrote more than one manifest in a single run -- this should never happen." -ForegroundColor Red
    Write-Host "       Manifests:" -ForegroundColor Red
    $manifests | ForEach-Object { Write-Host "         $($_.Name)" }
    Write-Host "       Temp dir left in place: $tempDir"
    exit 2
}

$manifestFile = $manifests[0]
try {
    $manifestObj = Get-Content -Raw $manifestFile.FullName | ConvertFrom-Json
} catch {
    Write-Host "ERROR: Could not parse manifest $($manifestFile.FullName): $($_.Exception.Message)" -ForegroundColor Red
    exit 2
}

$manifestCommit = $manifestObj.extractor_git_commit
if ([string]::IsNullOrWhiteSpace($manifestCommit) -or -not [string]::Equals([string]$manifestCommit, $currentHead, [System.StringComparison]::OrdinalIgnoreCase)) {
    Write-Host "ERROR: Manifest provenance does not match the extraction HEAD." -ForegroundColor Red
    Write-Host "       HEAD:      $currentHead"
    Write-Host "       Manifest:  $manifestCommit"
    Write-Host "       Temp staging directory left in place for inspection: $tempDir" -ForegroundColor Yellow
    exit 2
}

$actualStudySlug = $manifestObj.study.slug
$actualStudyName = $manifestObj.study.name
$selectionMode = $manifestObj.study.selection_mode
if ([string]::IsNullOrWhiteSpace($actualStudySlug)) {
    Write-Host "ERROR: Manifest does not contain study.slug -- cannot place artifacts canonically." -ForegroundColor Red
    Write-Host "       Manifest: $($manifestFile.FullName)"
    exit 2
}

$expectedBase = "${PartNumber}_fea_${actualStudySlug}"
$expectedNames = @(
    "$PartNumber.json",
    "$expectedBase.glb",
    "${expectedBase}_results.json",
    "${expectedBase}_manifest.json"
)
$tempFiles = @(Get-ChildItem -Path $tempDir -File -ErrorAction SilentlyContinue)
$tempNames = @($tempFiles | ForEach-Object { $_.Name })
$unexpectedTemp = @($tempNames | Where-Object { $expectedNames -notcontains $_ })
$missingTemp = @($expectedNames | Where-Object { $tempNames -notcontains $_ })
if ($unexpectedTemp.Count -gt 0 -or $missingTemp.Count -gt 0 -or $tempFiles.Count -ne 4) {
    Write-Host "ERROR: Worker FEA staging contract violation." -ForegroundColor Red
    Write-Host "       Expected exactly these 4 files in temp staging:"
    $expectedNames | ForEach-Object { Write-Host "         $_" }
    if ($missingTemp.Count -gt 0) {
        Write-Host "       Missing:" -ForegroundColor Red
        $missingTemp | ForEach-Object { Write-Host "         $_" }
    }
    if ($unexpectedTemp.Count -gt 0) {
        Write-Host "       Unexpected:" -ForegroundColor Red
        $unexpectedTemp | ForEach-Object { Write-Host "         $_" }
    }
    Write-Host "       Temp staging directory left in place for inspection: $tempDir" -ForegroundColor Yellow
    exit 2
}

# --- compute and prepare the canonical destination ---
$canonicalDir = Join-Path $incomingRoot "$partSlug\$actualStudySlug"

if (Test-Path $canonicalDir) {
    $existing = @(Get-ChildItem -Path $canonicalDir -File -ErrorAction SilentlyContinue)
    if ($existing.Count -gt 0) {
        if (-not $Force) {
            Write-Host ""
            Write-Host "ERROR: Canonical directory already contains artifacts:" -ForegroundColor Red
            Write-Host "       $canonicalDir"
            Write-Host "       Re-running the same study would overwrite prior provenance." -ForegroundColor Red
            Write-Host "       Pass -Force to confirm, or remove the directory first." -ForegroundColor Red
            Write-Host ""
            Write-Host "       Newly extracted artifacts left in temp dir:" -ForegroundColor Yellow
            Write-Host "       $tempDir"
            exit 3
        }
        Write-Host "NOTE: -Force -- clearing existing canonical directory:" -ForegroundColor Yellow
        Write-Host "       $canonicalDir"
        Get-ChildItem -Path $canonicalDir -File | Remove-Item -Force
    }
} else {
    New-Item -ItemType Directory -Path $canonicalDir -Force | Out-Null
}

# --- move only the four canonical files from temp staging into canonical ---
$movedFiles = @()
$expectedNames | ForEach-Object {
    $source = Join-Path $tempDir $_
    $dest = Join-Path $canonicalDir $_
    Move-Item -Path $source -Destination $dest -Force
    $movedFiles += $dest
}

# Clean up the temp staging directory (it should be empty now).
try { Remove-Item -Path $tempDir -Force -Recurse -ErrorAction Stop } catch { }

# --- post-move audit ---
$canonicalManifests = @(Get-ChildItem -Path $canonicalDir -Filter "${PartNumber}_fea_*_manifest.json" -File -ErrorAction SilentlyContinue)
if ($canonicalManifests.Count -ne 1) {
    Write-Host ""
    Write-Host "ERROR: Expected exactly one manifest in $canonicalDir, found $($canonicalManifests.Count)." -ForegroundColor Red
    exit 2
}
$canonManifest = $canonicalManifests[0]
$canonBase = $canonManifest.Name -replace "_manifest\.json$", ""
$canonGlb = Join-Path $canonicalDir "$canonBase.glb"
$canonResults = Join-Path $canonicalDir "${canonBase}_results.json"
# The standard part-data JSON is the fourth file in the contract documented in
# incoming_fea/README.md. The extractor writes it from --output regardless of
# the FEA path, so its absence here means the run is incomplete.
$canonPartData = Join-Path $canonicalDir "$PartNumber.json"

$missing = @()
if (-not (Test-Path $canonGlb)) { $missing += $canonGlb }
if (-not (Test-Path $canonResults)) { $missing += $canonResults }
if (-not (Test-Path $canonPartData)) { $missing += $canonPartData }
$canonicalFiles = @(Get-ChildItem -Path $canonicalDir -File -ErrorAction SilentlyContinue)
$canonicalNames = @($canonicalFiles | ForEach-Object { $_.Name })
$unexpectedCanonical = @($canonicalNames | Where-Object { $expectedNames -notcontains $_ })

Write-Host ""
Write-Host "Canonical staging directory: $canonicalDir" -ForegroundColor Cyan
Write-Host ("  manifest:  {0}" -f $canonManifest.Name) -ForegroundColor Green
if (Test-Path $canonGlb) { Write-Host ("  glb:       {0}" -f (Split-Path -Leaf $canonGlb)) -ForegroundColor Green }
if (Test-Path $canonResults) { Write-Host ("  results:   {0}" -f (Split-Path -Leaf $canonResults)) -ForegroundColor Green }
if (Test-Path $canonPartData) { Write-Host ("  part-data: {0}" -f (Split-Path -Leaf $canonPartData)) -ForegroundColor Green }

if ($missing.Count -gt 0) {
    Write-Host ""
    Write-Host "ERROR: Manifest moved but the run is incomplete -- expected files are missing:" -ForegroundColor Red
    $missing | ForEach-Object { Write-Host "   $_" }
    Write-Host "       Do not commit this directory until the missing files are produced." -ForegroundColor Red
    exit 2
}
if ($canonicalFiles.Count -ne 4 -or $unexpectedCanonical.Count -gt 0) {
    Write-Host ""
    Write-Host "ERROR: Canonical staging contains files outside the four-file contract:" -ForegroundColor Red
    $unexpectedCanonical | ForEach-Object { Write-Host "   $_" }
    Write-Host "       Do not commit this directory until it contains only the canonical files." -ForegroundColor Red
    exit 2
}

Write-Host ""
Write-Host "Study selection: $selectionMode -- '$actualStudyName' -> slug '$actualStudySlug'" -ForegroundColor Cyan
Write-Host "FEA extraction complete." -ForegroundColor Green
Write-Host "Next step: commit incoming_fea\$partSlug\$actualStudySlug\ per FEA_WORKER_README.md."
exit 0
