# validate_fea_run.ps1
#
# Source-of-truth-side validator for FEA artifacts produced by the worker
# computer and committed under  incoming_fea/<part-slug>/<study-slug>/ .
#
# This script does NOT touch the running app. Its job is to let the reviewer
# answer "is this worker run plausible enough to merge?" before any UI/backend
# integration is attempted.
#
# What it checks:
#   1. The four-file contract from incoming_fea/README.md is satisfied:
#        <PartNumber>.json
#        <PartNumber>_fea_<slug>.glb
#        <PartNumber>_fea_<slug>_results.json
#        <PartNumber>_fea_<slug>_manifest.json
#      No extra files are allowed in canonical staging.
#   2. Required manifest fields are present and non-trivial (manifest_version,
#      timestamp_utc, solidworks_version, source.{document_path, part_number},
#      study.{name, slug, type, selection_mode}, outputs[], summary, warnings).
#   3. Required results JSON fields are present (schema_version, summary,
#      study, units_detail, material, mesh, loads, fixtures, results,
#      warnings) and key numbers are non-zero / non-null where they should be.
#   4. Filename consistency: the slug embedded in the filenames matches
#      manifest.study.slug, and the directory matches incoming_fea/<part-slug>/<slug>/.
#   5. Cross-check: overlapping fields in manifest.summary and results.json
#      summary block agree to within 1e-6 absolute / 0.1% relative.
#   6. Provenance hygiene:
#        - selection_mode != "implicit"  (warn — should normally be explicit)
#        - extractor_git_commit not null (warn  -- worker had git on PATH)
#   7. Visualization honesty:
#        - manifest.visualization.approximate must be false
#        - manifest.visualization.mode must be solver_fe_mesh
#
# What it does NOT check:
#   - GLB binary integrity (out of scope; the visualisation layer will surface
#     load-time failures).
#   - Whether engineering values are physically sensible (engineer judgement).
#   - Whether the worker chose the correct study (engineer judgement).
#
# Optional: pass -ExpectedReport <json> to compare specific results against a
# reference extracted from the SolidWorks report. See
# scripts/expected_fea_mounting_plate.json for the sample format.
#
# Usage:
#   .\scripts\validate_fea_run.ps1 -Directory incoming_fea\1234567\static_1
#   .\scripts\validate_fea_run.ps1 -Directory incoming_fea\1234567\static_1 `
#        -ExpectedReport scripts\expected_fea_mounting_plate.json
#
# Exit codes:
#   0 = all checks passed (warnings allowed)
#   1 = at least one FAIL
#   2 = directory not found or no manifest
#   3 = bad CLI args

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Directory,

    # Optional reference values (derived from the SolidWorks report) to compare
    # selected fields against. Each entry can carry its own tolerance. See
    # scripts/expected_fea_mounting_plate.json for the schema.
    [string]$ExpectedReport
)

$ErrorActionPreference = "Stop"

# --- result counters ---
$passes = 0
$warns = 0
$fails = 0
$failMessages = New-Object System.Collections.Generic.List[string]

function Write-Pass([string]$msg) {
    $script:passes++
    Write-Host ("[ PASS ] {0}" -f $msg) -ForegroundColor Green
}
function Write-Warn([string]$msg) {
    $script:warns++
    Write-Host ("[ WARN ] {0}" -f $msg) -ForegroundColor Yellow
}
function Write-Fail([string]$msg) {
    $script:fails++
    $script:failMessages.Add($msg)
    Write-Host ("[ FAIL ] {0}" -f $msg) -ForegroundColor Red
}

# --- input validation ---
if (-not (Test-Path -PathType Container $Directory)) {
    Write-Host "ERROR: Directory not found: $Directory" -ForegroundColor Red
    exit 2
}
$Directory = (Resolve-Path $Directory).Path

if (-not [string]::IsNullOrWhiteSpace($ExpectedReport)) {
    if (-not (Test-Path -PathType Leaf $ExpectedReport)) {
        Write-Host "ERROR: ExpectedReport file not found: $ExpectedReport" -ForegroundColor Red
        exit 3
    }
}

Write-Host ""
Write-Host ("Validating FEA artifacts in: {0}" -f $Directory) -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------------------
# 1. Required files contract (the four-file guarantee from incoming_fea/README.md)
# ---------------------------------------------------------------------------

$manifestFiles = @(Get-ChildItem -Path $Directory -Filter "*_fea_*_manifest.json" -File -ErrorAction SilentlyContinue)
if ($manifestFiles.Count -eq 0) {
    Write-Host "ERROR: No *_fea_*_manifest.json found in $Directory" -ForegroundColor Red
    Write-Host "       Was extraction completed? See incoming_fea/README.md for the layout."
    exit 2
}
if ($manifestFiles.Count -gt 1) {
    Write-Fail "Found multiple manifests in directory ($($manifestFiles.Count)); a canonical staging directory must contain exactly one."
}

$manifestFile = $manifestFiles[0]
$baseName = $manifestFile.Name -replace "_manifest\.json$", ""
# baseName looks like "1234567_fea_static_1"; PartNumber is everything before "_fea_"
$splitIdx = $baseName.IndexOf("_fea_")
if ($splitIdx -lt 1) {
    Write-Fail "Manifest filename does not match expected pattern '<PartNumber>_fea_<slug>_manifest.json': $($manifestFile.Name)"
    Write-Host ""
    Write-Host "Cannot continue without a parseable manifest filename." -ForegroundColor Red
    exit 1
}
$partNumber = $baseName.Substring(0, $splitIdx)
$studySlugFromFilename = $baseName.Substring($splitIdx + 5)

$expectedFiles = @{
    "manifest"  = $manifestFile.FullName
    "glb"       = Join-Path $Directory ($baseName + ".glb")
    "results"   = Join-Path $Directory ($baseName + "_results.json")
    "part_data" = Join-Path $Directory ($partNumber + ".json")
}
foreach ($kvp in $expectedFiles.GetEnumerator()) {
    if (Test-Path $kvp.Value) {
        Write-Pass ("File present ({0}): {1}" -f $kvp.Key, (Split-Path -Leaf $kvp.Value))
    } else {
        Write-Fail ("Missing required file ({0}): {1}" -f $kvp.Key, $kvp.Value)
    }
}
$allFiles = @(Get-ChildItem -Path $Directory -File -ErrorAction SilentlyContinue)
$expectedLeafNames = @($expectedFiles.Values | ForEach-Object { Split-Path -Leaf $_ })
$extraFiles = @($allFiles | Where-Object { $expectedLeafNames -notcontains $_.Name })
if ($allFiles.Count -eq 4 -and $extraFiles.Count -eq 0) {
    Write-Pass "Directory contains exactly the four canonical files"
} else {
    Write-Fail ("Directory must contain exactly the four canonical files; found {0} file(s), {1} unexpected" -f $allFiles.Count, $extraFiles.Count)
    $extraFiles | ForEach-Object { Write-Fail ("Unexpected file in canonical staging: {0}" -f $_.Name) }
}

# ---------------------------------------------------------------------------
# 2. Manifest schema + required fields
# ---------------------------------------------------------------------------

$manifest = $null
try {
    $manifest = Get-Content -Raw $manifestFile.FullName | ConvertFrom-Json
} catch {
    Write-Fail "Could not parse manifest as JSON: $($_.Exception.Message)"
    Write-Host ""
    Write-Host "Cannot continue without a parseable manifest." -ForegroundColor Red
    exit 1
}

function Test-FieldNonEmpty([object]$root, [string]$path) {
    $cur = $root
    foreach ($seg in $path.Split('.')) {
        if ($null -eq $cur) { return $false }
        $cur = $cur.$seg
    }
    if ($null -eq $cur) { return $false }
    if ($cur -is [string] -and [string]::IsNullOrWhiteSpace($cur)) { return $false }
    return $true
}

# Walks a dotted path and returns $true iff every segment exists as a property
# on its parent (regardless of value -- $null, 0, "" all count as "present").
# Used to enforce the *presence* of array properties like results.loads, where
# an empty array [] is a valid run state but a missing property is not.
function Test-FieldPropertyPresent([object]$root, [string]$path) {
    $cur = $root
    foreach ($seg in $path.Split('.')) {
        if ($null -eq $cur) { return $false }
        if ($cur -isnot [psobject] -or $null -eq $cur.PSObject.Properties[$seg]) {
            return $false
        }
        $cur = $cur.$seg
    }
    return $true
}

$manifestRequiredNonEmpty = @(
    "manifest_version",
    "timestamp_utc",
    "solidworks_version",
    "source.document_path",
    "source.part_number",
    "study.name",
    "study.slug",
    "study.type",
    "study.selection_mode"
)
foreach ($p in $manifestRequiredNonEmpty) {
    if (Test-FieldNonEmpty $manifest $p) {
        Write-Pass ("manifest.{0} present" -f $p)
    } else {
        Write-Fail ("manifest.{0} missing or empty" -f $p)
    }
}

# Arrays must exist (empty is allowed for outputs[] only if extractor truly
# wrote nothing, which would be a separate failure caught above)
if ($null -ne $manifest.outputs -and $manifest.outputs.Count -ge 3) {
    Write-Pass ("manifest.outputs has {0} entries" -f $manifest.outputs.Count)
} else {
    Write-Fail "manifest.outputs missing or has fewer than 3 entries"
}
if ((Test-FieldPropertyPresent $manifest "visualization.approximate")) {
    if ($manifest.visualization.approximate -eq $true) {
        Write-Fail "manifest.visualization.approximate is true -- approximate visualization is not mergeable as a normal worker FEA GLB"
    } else {
        Write-Pass "manifest.visualization.approximate is false"
    }
} else {
    Write-Fail "manifest.visualization.approximate missing"
}
if ((Test-FieldNonEmpty $manifest "visualization.mode")) {
    if ($manifest.visualization.mode -eq "solver_fe_mesh") {
        Write-Pass "manifest.visualization.mode = solver_fe_mesh"
    } else {
        Write-Fail ("manifest.visualization.mode must be solver_fe_mesh, got '{0}'" -f $manifest.visualization.mode)
    }
} else {
    Write-Fail "manifest.visualization.mode missing"
}
if ($null -ne $manifest.warnings) {
    Write-Pass ("manifest.warnings present ({0} entries)" -f $manifest.warnings.Count)
} else {
    Write-Fail "manifest.warnings array missing entirely (should be present, may be empty)"
}

# ---------------------------------------------------------------------------
# 3. Provenance hygiene (warn-only, not fail)
# ---------------------------------------------------------------------------

if ((Test-FieldNonEmpty $manifest "study.selection_mode")) {
    if ($manifest.study.selection_mode -eq "implicit") {
        Write-Warn "manifest.study.selection_mode = 'implicit' -- worker did not pick the study explicitly. Confirm this was intentional."
    } else {
        Write-Pass ("manifest.study.selection_mode = '{0}' (explicit)" -f $manifest.study.selection_mode)
    }
}

if ($null -eq $manifest.extractor_git_commit -or [string]::IsNullOrWhiteSpace($manifest.extractor_git_commit)) {
    Write-Warn "manifest.extractor_git_commit is null/empty -- worker did not have git on PATH; provenance is reduced."
} else {
    if ($manifest.extractor_git_commit -match '^[0-9a-f]{7,40}$') {
        Write-Pass ("manifest.extractor_git_commit = {0}" -f $manifest.extractor_git_commit)
    } else {
        Write-Warn ("manifest.extractor_git_commit does not look like a SHA: '{0}'" -f $manifest.extractor_git_commit)
    }
}

# ---------------------------------------------------------------------------
# 4. Filename / directory / manifest slug consistency
# ---------------------------------------------------------------------------

if ((Test-FieldNonEmpty $manifest "study.slug")) {
    if ($manifest.study.slug -eq $studySlugFromFilename) {
        Write-Pass ("study.slug ('{0}') matches filename slug" -f $manifest.study.slug)
    } else {
        Write-Fail ("study.slug ('{0}') disagrees with filename slug ('{1}')" -f $manifest.study.slug, $studySlugFromFilename)
    }
}
if ((Test-FieldNonEmpty $manifest "source.part_number")) {
    if ($manifest.source.part_number -eq $partNumber) {
        Write-Pass ("source.part_number ('{0}') matches filename PartNumber" -f $manifest.source.part_number)
    } else {
        Write-Fail ("source.part_number ('{0}') disagrees with filename PartNumber ('{1}')" -f $manifest.source.part_number, $partNumber)
    }
}

# Directory layout sanity: leaf dir name should equal study slug, parent should
# equal part slug. Skip this check if the user pointed at a non-canonical path.
$leafDir = Split-Path -Leaf $Directory
$parentDir = Split-Path -Leaf (Split-Path -Parent $Directory)
if ((Test-FieldNonEmpty $manifest "study.slug")) {
    if ($leafDir -eq $manifest.study.slug) {
        Write-Pass ("Directory leaf '{0}' matches study slug" -f $leafDir)
    } else {
        Write-Warn ("Directory leaf '{0}' does not match study slug '{1}'. Expected canonical layout incoming_fea/<part-slug>/<study-slug>/." -f $leafDir, $manifest.study.slug)
    }
}

# ---------------------------------------------------------------------------
# 5. Results JSON schema + required fields
# ---------------------------------------------------------------------------

$results = $null
$resultsPath = $expectedFiles["results"]
if (Test-Path $resultsPath) {
    try {
        $results = Get-Content -Raw $resultsPath | ConvertFrom-Json
    } catch {
        Write-Fail "Could not parse results JSON: $($_.Exception.Message)"
    }
}

if ($null -ne $results) {
    $resultsRequiredNonEmpty = @(
        "schema_version",
        "study_name",
        "study_type",
        "summary",
        "study.name",
        "study.type",
        "units_detail.system",
        "material.name",
        "mesh.node_count",
        "mesh.element_count",
        "results.max_von_mises_mpa",
        "results.max_displacement_mm"
    )
    foreach ($p in $resultsRequiredNonEmpty) {
        if (Test-FieldNonEmpty $results $p) {
            Write-Pass ("results.{0} present" -f $p)
        } else {
            Write-Fail ("results.{0} missing or empty" -f $p)
        }
    }

    # Required array properties from the schema-v2 contract. Empty array is a
    # valid run state (a study can have no loads, fixtures, or warnings), but
    # the property itself must exist so consumers don't have to defend against
    # a missing key.
    $resultsRequiredArrays = @("loads", "fixtures", "warnings")
    foreach ($p in $resultsRequiredArrays) {
        if (Test-FieldPropertyPresent $results $p) {
            $count = if ($null -ne $results.$p) { @($results.$p).Count } else { 0 }
            Write-Pass ("results.{0} array property present ({1} entries)" -f $p, $count)
        } else {
            Write-Fail ("results.{0} array property missing from results JSON" -f $p)
        }
    }

    # Sanity: max stress / displacement / mesh counts should be > 0 for any
    # solved study with successful metadata extraction. Test-FieldNonEmpty
    # treats numeric 0 as present, so we need explicit positive checks here
    # otherwise a run with failed mesh extraction (counts = 0) would slip past
    # the schema check.
    if ($null -ne $results.results -and $results.results.max_von_mises_mpa -gt 0) {
        Write-Pass ("results.results.max_von_mises_mpa = {0:F3} MPa (>0)" -f $results.results.max_von_mises_mpa)
    } else {
        Write-Fail "results.results.max_von_mises_mpa is zero or missing -- study not solved or extraction failed silently?"
    }
    if ($null -ne $results.results -and $results.results.max_displacement_mm -gt 0) {
        Write-Pass ("results.results.max_displacement_mm = {0:F5} mm (>0)" -f $results.results.max_displacement_mm)
    } else {
        Write-Fail "results.results.max_displacement_mm is zero or missing -- study not solved or extraction failed silently?"
    }
    if ($null -ne $results.mesh -and [int]$results.mesh.node_count -gt 0) {
        Write-Pass ("results.mesh.node_count = {0:N0} (>0)" -f [int]$results.mesh.node_count)
    } else {
        Write-Fail "results.mesh.node_count is zero or missing -- mesh metadata extraction failed?"
    }
    if ($null -ne $results.mesh -and [int]$results.mesh.element_count -gt 0) {
        Write-Pass ("results.mesh.element_count = {0:N0} (>0)" -f [int]$results.mesh.element_count)
    } else {
        Write-Fail "results.mesh.element_count is zero or missing -- mesh metadata extraction failed?"
    }
}

# ---------------------------------------------------------------------------
# 6. Cross-check: manifest.summary vs results.json summary
# ---------------------------------------------------------------------------

function Test-NumericMatch([double]$a, [double]$b, [double]$relTol = 0.001, [double]$absTol = 1e-6, [string]$fieldName) {
    $diff = [math]::Abs($a - $b)
    if ($diff -le $absTol) {
        Write-Pass ("Cross-check {0}: manifest={1:G6}, results={2:G6} (delta {3:G3}, within abs tol)" -f $fieldName, $a, $b, $diff)
        return
    }
    $denom = [math]::Max([math]::Abs($a), [math]::Abs($b))
    $rel = if ($denom -gt 0) { $diff / $denom } else { 0 }
    if ($rel -le $relTol) {
        Write-Pass ("Cross-check {0}: manifest={1:G6}, results={2:G6} (delta {3:P3}, within {4:P1} rel tol)" -f $fieldName, $a, $b, $rel, $relTol)
    } else {
        Write-Fail ("Cross-check {0}: manifest={1:G6} vs results={2:G6} differ by {3:P3} (tol {4:P1})" -f $fieldName, $a, $b, $rel, $relTol)
    }
}

if ($null -ne $manifest -and $null -ne $manifest.summary -and $null -ne $results -and $null -ne $results.summary) {
    Test-NumericMatch $manifest.summary.max_von_mises_mpa  $results.summary.max_von_mises_mpa  -fieldName "max_von_mises_mpa"
    Test-NumericMatch $manifest.summary.max_displacement_mm $results.summary.max_displacement_mm -fieldName "max_displacement_mm"
    Test-NumericMatch $manifest.summary.safety_factor       $results.summary.safety_factor       -fieldName "safety_factor"
    Test-NumericMatch $manifest.summary.yield_strength_mpa  $results.summary.yield_strength_mpa  -fieldName "yield_strength_mpa"
    if ($manifest.summary.material -eq $results.summary.material) {
        Write-Pass ("Cross-check material name matches: '{0}'" -f $manifest.summary.material)
    } else {
        Write-Fail ("Cross-check material name differs: manifest='{0}' vs results='{1}'" -f $manifest.summary.material, $results.summary.material)
    }
}

# ---------------------------------------------------------------------------
# 7. Optional: compare against the SolidWorks report expectations
# ---------------------------------------------------------------------------

if (-not [string]::IsNullOrWhiteSpace($ExpectedReport)) {
    Write-Host ""
    Write-Host "--- Comparison against expected report ---" -ForegroundColor Cyan
    $expected = $null
    try {
        $expected = Get-Content -Raw $ExpectedReport | ConvertFrom-Json
    } catch {
        Write-Fail "Could not parse expected report JSON: $($_.Exception.Message)"
    }

    if ($null -ne $expected) {
        $tols = $expected.tolerances
        $relStress = if ($null -ne $tols -and $null -ne $tols.stress_pct) { [double]$tols.stress_pct / 100.0 } else { 0.01 }
        $relDisp   = if ($null -ne $tols -and $null -ne $tols.displacement_pct) { [double]$tols.displacement_pct / 100.0 } else { 0.01 }
        $relMod    = if ($null -ne $tols -and $null -ne $tols.modulus_pct) { [double]$tols.modulus_pct / 100.0 } else { 0.01 }
        $absNodes  = if ($null -ne $tols -and $null -ne $tols.node_count_abs) { [int]$tols.node_count_abs } else { 100 }

        function Compare-StringField($actual, $expectedVal, $name) {
            if ($null -eq $expectedVal) { return }  # skip when expectation isn't supplied
            if ($actual -eq $expectedVal) {
                Write-Pass ("Expected {0}: '{1}' matches" -f $name, $expectedVal)
            } else {
                Write-Fail ("Expected {0} = '{1}', got '{2}'" -f $name, $expectedVal, $actual)
            }
        }
        function Compare-NumericField($actual, $expectedVal, $relTol, $name) {
            if ($null -eq $expectedVal) { return }
            if ($null -eq $actual) {
                Write-Fail ("Expected {0} = {1}, got null" -f $name, $expectedVal)
                return
            }
            $a = [double]$actual; $e = [double]$expectedVal
            $denom = [math]::Max([math]::Abs($a), [math]::Abs($e))
            $rel = if ($denom -gt 0) { [math]::Abs($a - $e) / $denom } else { 0 }
            if ($rel -le $relTol) {
                Write-Pass ("Expected {0}: {1:G6} vs actual {2:G6} (delta {3:P3}, within {4:P1})" -f $name, $e, $a, $rel, $relTol)
            } else {
                Write-Fail ("Expected {0} = {1:G6}, got {2:G6} (delta {3:P3} > tol {4:P1})" -f $name, $e, $a, $rel, $relTol)
            }
        }
        function Compare-IntField($actual, $expectedVal, $absTol, $name) {
            if ($null -eq $expectedVal) { return }
            if ($null -eq $actual) {
                Write-Fail ("Expected {0} = {1}, got null" -f $name, $expectedVal)
                return
            }
            $diff = [math]::Abs([int]$actual - [int]$expectedVal)
            if ($diff -le $absTol) {
                Write-Pass ("Expected {0}: {1} vs actual {2} (delta {3}, within {4})" -f $name, $expectedVal, $actual, $diff, $absTol)
            } else {
                Write-Fail ("Expected {0} = {1}, got {2} (delta {3} > tol {4})" -f $name, $expectedVal, $actual, $diff, $absTol)
            }
        }

        Compare-StringField $results.study_name $expected.study_name "study_name"
        Compare-StringField $results.study_type $expected.study_type "study_type"
        if ($null -ne $results.study) {
            Compare-StringField $results.study.configuration_name $expected.configuration_name "configuration_name"
        }
        if ($null -ne $results.material) {
            Compare-StringField  $results.material.name                       $expected.material_name             "material.name"
            Compare-NumericField $results.material.yield_strength_mpa         $expected.yield_strength_mpa $relMod "material.yield_strength_mpa"
            Compare-NumericField $results.material.tensile_strength_mpa       $expected.tensile_strength_mpa $relMod "material.tensile_strength_mpa"
            Compare-NumericField $results.material.elastic_modulus_mpa        $expected.elastic_modulus_mpa $relMod "material.elastic_modulus_mpa"
            Compare-NumericField $results.material.poissons_ratio             $expected.poissons_ratio $relMod "material.poissons_ratio"
            Compare-NumericField $results.material.mass_density_kg_per_m3     $expected.mass_density_kg_per_m3 $relMod "material.mass_density_kg_per_m3"
        }
        if ($null -ne $results.mesh) {
            Compare-IntField $results.mesh.node_count    $expected.mesh_node_count    $absNodes "mesh.node_count"
            Compare-IntField $results.mesh.element_count $expected.mesh_element_count $absNodes "mesh.element_count"
        }
        if ($null -ne $results.results) {
            Compare-NumericField $results.results.max_von_mises_mpa  $expected.max_von_mises_mpa  $relStress "results.max_von_mises_mpa"
            Compare-NumericField $results.results.max_displacement_mm $expected.max_displacement_mm $relDisp   "results.max_displacement_mm"
            if ($null -ne $results.results.reaction_forces_n) {
                Compare-NumericField $results.results.reaction_forces_n.fx $expected.reaction_fx_n $relStress "results.reaction_forces_n.fx"
            }
        }
    }
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "===== SUMMARY =====" -ForegroundColor Cyan
Write-Host ("  PASS : {0}" -f $passes) -ForegroundColor Green
if ($warns -gt 0) { Write-Host ("  WARN : {0}" -f $warns) -ForegroundColor Yellow } else { Write-Host ("  WARN : 0") }
if ($fails -gt 0) { Write-Host ("  FAIL : {0}" -f $fails) -ForegroundColor Red } else { Write-Host ("  FAIL : 0") }

if ($fails -gt 0) {
    Write-Host ""
    Write-Host "Failures:" -ForegroundColor Red
    $failMessages | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    Write-Host ""
    Write-Host "Validation FAILED -- do not merge this worker run." -ForegroundColor Red
    exit 1
}

Write-Host ""
if ($warns -gt 0) {
    Write-Host "Validation passed with warnings. Review the warnings above before merging." -ForegroundColor Yellow
} else {
    Write-Host "Validation passed with no warnings." -ForegroundColor Green
}
exit 0
