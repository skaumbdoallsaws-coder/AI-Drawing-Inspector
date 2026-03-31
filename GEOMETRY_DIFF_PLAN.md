# Solid-Body Geometry Diff: Implementation Plan

**Status: Plan v6 — Codex review round 6**
**Date: 2026-03-29**

## Codex Round 1 Findings (All Addressed in v2)

| # | Finding | Resolution |
|---|---------|------------|
| 1 | pythonocc-core needs conda but server uses pip/venv — deployment unresolved | **Decision: separate geometry worker process.** A conda env runs a lightweight FastAPI worker on a local port. Main server proxies to it. No conda in the pip venv. |
| 2 | Cache/artifact URLs not keyed by revision pair — will collide | **Fixed.** Artifacts keyed `{part_number}/{revA}_vs_{revB}/removed.glb`. URLs include both revisions. |
| 3 | Standalone part storage layout doesn't match existing `parts/{pn}/revX/` structure | **Fixed.** STEP files stored at `400S_Sorted_Library/parts/{pn}/rev{X}/{pn}.stp`, matching existing convention. |
| 4 | STEP export/validation relies on file hashes instead of geometry checks | **Fixed.** Validation uses volume comparison (OCCT `GProp_GProps`) before and after import, not file hashes. AP214 explicitly set in SolidWorks export options. |

## Architecture Recommendation (TL;DR)

**Export STEP files from SolidWorks → boolean diff via Open CASCADE (pythonocc) → tessellate diff volumes to GLB → render as colored overlays in existing Three.js viewer.**

This is feasible, more accurate than property diff, and complementary to the existing feature-level comparison. The minimum viable path is ~3 weeks of focused work.

---

## 1. Feasibility

**Yes, true external solid diff is feasible from SolidWorks-exported data.**

### Format Comparison

| Format | Fidelity | OCCT Support | Export Cost | Recommendation |
|--------|----------|-------------|-------------|----------------|
| **STEP (.stp)** | Exact B-rep (NURBS surfaces, topology) | Native reader in OCCT | SolidWorks `SaveAs` — 1 API call | **Preferred** |
| Parasolid (.x_t) | Lossless (native kernel) | Requires commercial Parasolid license or converter | SolidWorks `SaveAs` — 1 API call | Best fidelity, but OCCT can't read it natively |
| IGES (.igs) | Surfaces only, no solid topology | OCCT reader exists | SolidWorks `SaveAs` | Inferior — no guaranteed watertight solids |
| GLB/STL (mesh) | Triangulated approximation | N/A for boolean | Already exported | Fallback only — noisy on curves |

**Decision: STEP.**
- OCCT reads STEP natively with full B-rep topology
- SolidWorks STEP export preserves all solid geometry (AP214 or AP242)
- No commercial kernel license needed
- Parasolid would be lossless but requires a Parasolid reader license ($$$) or converting through SolidWorks first — which means STEP is equivalent in practice

### What STEP Preserves
- Exact NURBS surface definitions
- Edge/face topology (B-rep)
- Solid body identity
- Coordinate system (origin matches SolidWorks part origin)
- Multi-body parts (each body as a separate solid)

---

## 2. Extractor Changes

### New Export Step in SolidWorksExtractor (C#)

Add to `SolidWorksExtractor/Services/GlbExporter.cs` (alongside existing GLB export) or a new `SolidWorksExtractor/Services/StepExporter.cs`:

```csharp
// After existing GLB export, add STEP export with explicit AP214 format
public void ExportStep(ModelDoc2 model, string outputPath)
{
    // Save the current STEP AP preference so we can restore it after export
    int previousAP = model.Extension.GetUserPreferenceInteger(
        (int)swUserPreferenceIntegerValue_e.swStepAP, 0
    );

    try
    {
        // Set STEP export format to AP214 explicitly
        model.Extension.SetUserPreferenceInteger(
            (int)swUserPreferenceIntegerValue_e.swStepAP,
            0, // general scope
            (int)214 // AP214
        );

        int errors = 0, warnings = 0;
        bool ok = model.Extension.SaveAs(
            outputPath,
            (int)swSaveAsVersion_e.swSaveAsCurrentVersion,
            (int)swSaveAsOptions_e.swSaveAsOptions_Silent,
            null, ref errors, ref warnings
        );
        if (!ok) throw new Exception($"STEP export failed: errors={errors}, warnings={warnings}");
        // outputPath must end in .stp or .step
    }
    finally
    {
        // Restore the user's original STEP AP preference
        model.Extension.SetUserPreferenceInteger(
            (int)swUserPreferenceIntegerValue_e.swStepAP, 0, previousAP
        );
    }
}
```

AP214 is explicitly set before export — no reliance on user's SolidWorks preferences.

### Sidecar Metadata

For each exported STEP, save a JSON sidecar:

```json
{
  "part_number": "1030001",
  "revision": "A",
  "export_time": "2026-03-29T10:00:00Z",
  "solidworks_version": "2025 SP2",
  "step_format": "AP214",
  "units": "mm",
  "origin": "part_origin",
  "configuration": "Default",
  "body_count": 1,
  "volume_mm3": 45678.9,
  "mass_grams": 245.3,
  "bounding_box_mm": [120.0, 80.0, 45.0]
}
```

**AP214 enforcement:** SolidWorks STEP export must explicitly set `swExportSTEPFormat_e.swExportSTEPFormat_AP214` in the export options. The sidecar records the format used.

**Import validation (geometry worker, before boolean diff):**
The worker runs three checks against sidecar metadata after loading each STEP file:
1. **Body count** — count solids via `TopExp_Explorer(shape, TopAbs_SOLID)` iteration; must match sidecar `body_count`
2. **Volume** — computed via `GProp_GProps` + `BRepGProp.VolumeProperties()`; must be within 0.01% of sidecar `volume_mm3`
3. **Bounding box** — computed via `Bnd_Box` + `BRepBndLib.Add()`; XYZ extents must match sidecar `bounding_box_mm` within 0.01mm

If all three pass: proceed with diff. If any fails: return a warning in the result JSON (`"import_warnings": ["Volume mismatch: expected 45678.9, got 45680.1"]`) but still compute the diff. The UI surfaces the warning so the user can judge trustworthiness.

This is a heuristic, not a proof of geometric equivalence. Different shapes can have identical volume. But combined with body count + bounding box, it catches the common import healing artifacts.

### Directory Structure

Follows the existing `parts/{pn}/rev{X}/` convention already used by GLB and feature color files:

```
400S_Sorted_Library/
  parts/
    1030001/
      revA/
        1030001.stp              ← STEP solid
        1030001_step_meta.json   ← sidecar metadata
        1030001_colored.glb      ← (existing)
        1030001_feature_colors.json ← (existing)
      revB/
        1030001.stp
        1030001_step_meta.json
        1030001_colored.glb
        1030001_feature_colors.json
```

Assembly part revisions use the same path under `assemblies/{assy}/rev{X}/parts/`:

```
400S_Sorted_Library/
  assemblies/
    6000300/
      revA/
        parts/
          1030001.stp
          1030001_step_meta.json
      revB/
        parts/
          1030001.stp
          1030001_step_meta.json
```

**Diff result cache** (computed artifacts, not source data):

```
400S_Sorted_Library/
  parts/
    1030001/
      geometry_diff/
        A_vs_B/
          removed.glb
          added.glb
          diff_result.json
```

Keyed by `{revA}_vs_{revB}` — no collision when comparing multiple revision pairs.

---

## 3. Diff Engine Architecture

### Technology Stack

| Component | Tool | Why |
|-----------|------|-----|
| STEP reader | `pythonocc-core` (Open CASCADE Python bindings) | Only production-grade open-source B-rep kernel |
| Boolean operations | OCCT `BRepAlgoAPI_Cut` | Exact solid boolean, not mesh approximation |
| Tessellation | OCCT `BRepMesh_IncrementalMesh` | Convert diff volumes to triangles for Three.js |
| GLB export | `trimesh` or manual buffer | Package tessellated diff as GLB for frontend |
| Service | **Separate geometry worker** (own conda env + FastAPI) | Isolates OCCT/conda from main pip venv |

### Deployment: Separate Worker Process

**Problem:** `pythonocc-core` requires conda. The main InspectorPro server runs from a pip/venv (`.venv313`). Mixing conda into the pip env is fragile and unsupported.

**Solution:** A lightweight geometry diff worker runs as a separate process:

```
Main server (.venv313, pip)          Geometry worker (.conda-geo, conda)
├── FastAPI on :8000                 ├── FastAPI on :8001
├── All existing endpoints           ├── POST /diff (accepts STEP paths, returns GLB paths)
├── Proxies /api/geometry-diff       ├── pythonocc-core + trimesh
│   to worker :8001                  ├── Stateless, lazy-started
└── No OCCT dependency               └── No InspectorPro dependency
```

See **Main Server Endpoints** section below for the canonical endpoint implementation (with sanitization, cache invalidation, and artifact serving).

**Worker startup:** `conda run -n geo-env python geometry_worker.py` (manual or scripted).

**Why not in-process:** Conda environments cannot be mixed into pip venvs reliably on Windows. A separate process is the standard solution for heavy native-library dependencies (same pattern as GPU inference servers).

### Diff Pipeline

```
Input: revA.stp, revB.stp
    ↓
1. Load STEP → OCCT TopoDS_Shape (solid)
    ↓
2. Align — verify same coordinate origin (sidecar metadata check)
    ↓
3. Boolean diff:
   - removed = BRepAlgoAPI_Cut(shapeA, shapeB)  → material in A but not B
   - added   = BRepAlgoAPI_Cut(shapeB, shapeA)  → material in B but not A
    ↓
4. Validate results:
   - Check volumes are non-zero (if both zero → parts are identical)
   - Check volumes are reasonable (not larger than either part)
    ↓
5. Compute statistics:
   - removed_volume_mm3
   - added_volume_mm3
   - removed_bounding_box
   - added_bounding_box
   - changed_region_centroids (for camera fly-to)
    ↓
6. Tessellate diff volumes:
   - BRepMesh_IncrementalMesh on removed/added shapes
   - Extract triangle buffers
    ↓
7. Export as GLB:
   - removed → red mesh
   - added → green mesh
   - Save to disk for frontend loading
    ↓
8. Return result JSON:
   {
     "identical": false,
     "removed_volume_mm3": 1234.5,
     "added_volume_mm3": 567.8,
     "removed_glb": "/api/geometry-diff/1030001/A_vs_B/removed.glb",
     "added_glb": "/api/geometry-diff/1030001/A_vs_B/added.glb",
     "volume_a_mm3": 45678.9,
     "volume_b_mm3": 45012.2,
     "changed_centroids": [[45.2, 12.1, 8.5], ...],
     "computation_time_s": 2.3
   }
```

### Python Module Structure

```
ai_inspector/
  geometry/
    __init__.py
    step_loader.py      # Load STEP → TopoDS_Shape
    solid_diff.py       # Boolean diff + volume stats
    tessellator.py      # Shape → triangle buffers → GLB
    diff_cache.py       # Cache computed diffs to disk
```

### Where It Runs

**Geometry worker process only.** The main server has zero OCCT dependency — it proxies requests and serves cached artifacts. See "Deployment: Separate Worker Process" above for the full architecture.

### Main Server Endpoints (server.py)

```python
def _sanitize_revision(rev: str) -> str:
    """Strip revision strings to alphanumeric only (A, B, C1, etc.)."""
    sanitized = re.sub(r'[^a-zA-Z0-9]', '', rev)
    if not sanitized:
        raise HTTPException(status_code=400, detail=f"Invalid revision: '{rev}'")
    return sanitized


@app.get("/api/geometry-diff/{part_number}")
async def geometry_diff(part_number: str, revA: str = Query(...), revB: str = Query(...)):
    """Compute or retrieve solid-body geometry diff between two part revisions.
    Proxies to the geometry worker if not cached."""
    safe_pn = sanitize_part_number(part_number)
    safe_revA = _sanitize_revision(revA)
    safe_revB = _sanitize_revision(revB)

    step_a = Path(f"400S_Sorted_Library/parts/{safe_pn}/rev{safe_revA}/{safe_pn}.stp")
    step_b = Path(f"400S_Sorted_Library/parts/{safe_pn}/rev{safe_revB}/{safe_pn}.stp")
    if not step_a.exists() or not step_b.exists():
        raise HTTPException(status_code=404, detail="STEP file(s) not found for requested revisions")

    cache_dir = Path(f"400S_Sorted_Library/parts/{safe_pn}/geometry_diff/{safe_revA}_vs_{safe_revB}")
    result_path = cache_dir / "diff_result.json"

    # Cache invalidation: if cached result exists, check STEP + sidecar freshness
    if result_path.exists():
        cache_mtime = result_path.stat().st_mtime
        # Collect mtimes of all source files (STEPs + sidecars)
        source_mtimes = [step_a.stat().st_mtime, step_b.stat().st_mtime]
        sidecar_a = step_a.parent / f"{safe_pn}_step_meta.json"
        sidecar_b = step_b.parent / f"{safe_pn}_step_meta.json"
        if sidecar_a.exists():
            source_mtimes.append(sidecar_a.stat().st_mtime)
        if sidecar_b.exists():
            source_mtimes.append(sidecar_b.stat().st_mtime)
        if cache_mtime > max(source_mtimes):
            # Cache is newer than all source files — serve cached result
            with open(result_path, "r") as f:
                return json.load(f)
        else:
            # A source file changed since last diff — invalidate cache
            import shutil
            shutil.rmtree(cache_dir, ignore_errors=True)

    # Proxy to geometry worker
    import httpx
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post("http://localhost:8001/diff", json={
            "step_a": str(step_a.resolve()),
            "step_b": str(step_b.resolve()),
            "output_dir": str(cache_dir.resolve()),
            "part_number": safe_pn,
            "revA": safe_revA, "revB": safe_revB,
        })
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Geometry worker error: {resp.text}")
    return resp.json()


@app.get("/api/geometry-diff/{part_number}/{rev_pair}/{filename}")
async def serve_geometry_diff_artifact(part_number: str, rev_pair: str, filename: str):
    """Serve cached geometry diff GLB artifacts (removed.glb, added.glb)."""
    safe_pn = sanitize_part_number(part_number)
    if not re.match(r'^\w+_vs_\w+$', rev_pair):
        raise HTTPException(status_code=400, detail="Invalid revision pair format")
    if filename not in ("removed.glb", "added.glb", "diff_result.json"):
        raise HTTPException(status_code=400, detail="Invalid artifact name")
    artifact = Path(f"400S_Sorted_Library/parts/{safe_pn}/geometry_diff/{rev_pair}/{filename}")
    if not artifact.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")
    media = "model/gltf-binary" if filename.endswith(".glb") else "application/json"
    return FileResponse(artifact, media_type=media)
```

---

## 4. Accuracy and Limitations

### What Solid Diff Catches That Feature/Property Diff Misses

| Scenario | Feature Diff | Solid Diff |
|----------|-------------|-----------|
| Sketch profile changed (no named feature affected) | **Misses** | **Catches** — volume delta |
| Fillet radius adjusted on unnamed edge | **Misses** (if not a SolidWorks feature) | **Catches** — surface change |
| Extrude depth changed by 0.001mm | **Catches** (if dimension tracked) | **Catches** — volume delta |
| Feature reordered but geometry identical | False positive possible | **Correct** — no diff |
| Import body replaced with different geometry | **Misses** (no feature tree) | **Catches** — complete body diff |
| Hole moved without renaming | **Misses** (feature name unchanged) | **Catches** — volume at old + new position |

### Failure Modes

| Failure | Cause | Mitigation |
|---------|-------|------------|
| **Import healing** | STEP import may heal/modify geometry slightly | Multi-check heuristic (not proof of equivalence): (1) body count matches sidecar, (2) volume delta < 0.01% via `GProp_GProps`, (3) bounding box extents match within 0.01mm. If all three pass, import is likely faithful. If any fails, flag as "possible import fidelity issue" and proceed with warning — do not silently treat as equivalent. |
| **Tolerance mismatch** | OCCT linear tolerance vs SolidWorks modeling tolerance | Use OCCT default tolerance (1e-7). If boolean fails, retry with relaxed tolerance (1e-5). |
| **Coordinate frame mismatch** | Parts exported with different origins | Sidecar metadata records origin. If mismatch detected, abort with clear error. |
| **Configuration mismatch** | SolidWorks configurations change geometry | Export must specify configuration. Sidecar records active configuration name. |
| **Multi-body parts** | Boolean on compound shapes can be slow/fail | Diff each body independently, aggregate results. |
| **Large parts** | Boolean on complex geometry (1000+ faces) can take >30s | Set timeout (60s). Cache results. Show progress indicator. |

### Trustworthiness Requirements

For the diff to be trustworthy:
1. Both STEP files must be exported from the same part origin (sidecar check)
2. Units must match (sidecar check)
3. Boolean operation must complete without OCCT error
4. Result volumes must be non-negative and less than max(volumeA, volumeB)
5. If any check fails, report the failure clearly — never show a wrong diff silently

---

## 5. UI/UX Integration

### Viewport Presentation

Add a **"Geometry Diff"** toggle in the existing Part Compare view:

```
[ Feature Diff ] [ Geometry Diff ]   ← toggle between modes
```

**Feature Diff mode** (existing): amber/red/green highlights on the solid model per feature.

**Geometry Diff mode** (new):
- Original part rendered in semi-transparent gray
- **Red translucent volume** overlaid where material was removed
- **Green translucent volume** overlaid where material was added
- Camera auto-flies to the largest changed region
- Stats panel: "Removed: 1,234 mm³ | Added: 567 mm³"

### Three.js Implementation

```javascript
// Load diff GLBs and overlay on the part model
const removedGltf = await loadGLB(diffResult.removed_glb);
const addedGltf = await loadGLB(diffResult.added_glb);

// Red translucent material for removed volume
removedGltf.scene.traverse(child => {
    if (child.isMesh) {
        child.material = new THREE.MeshStandardMaterial({
            color: 0xFF5252, opacity: 0.5, transparent: true, side: THREE.DoubleSide
        });
    }
});

// Green translucent material for added volume
addedGltf.scene.traverse(child => {
    if (child.isMesh) {
        child.material = new THREE.MeshStandardMaterial({
            color: 0x00E676, opacity: 0.5, transparent: true, side: THREE.DoubleSide
        });
    }
});
```

### Interaction with Existing Feature Diff

**Explanation hierarchy (most specific → most complete):**

1. **Feature diff** — "Hole1 diameter changed from ⌀12 to ⌀14" (semantic, engineering-meaningful)
2. **Property delta** — "Mass increased by 3.2g" (aggregate, no spatial detail)
3. **Solid diff** — "1,234 mm³ removed here, 567 mm³ added there" (geometric ground truth, spatially precise)

**Integration:**
- Feature diff remains the primary comparison view (engineering context)
- Solid diff is a secondary "verify" mode — confirms feature diff is complete
- If solid diff shows volume changes in regions not covered by feature diff → flag as "untracked geometry change"
- Sage receives both: feature diff for reasoning, solid diff stats for completeness check

---

## 6. Phased Roadmap

### Phase 1: Proof of Concept (1 week)

**Goal:** Validate the boolean diff pipeline on one real SolidWorks part.

1. Manually export two STEP files from SolidWorks (Rev A and Rev B of any part)
2. Write a standalone Python script using `pythonocc-core`:
   - Load both STEP files
   - Run `BRepAlgoAPI_Cut` in both directions
   - Print volume stats
   - Export diff shapes as STL for visual inspection
3. Validate: does the diff match what changed?
4. Measure: how long does the computation take?

**Deliverables:** Working script, timing data, visual validation.

**Blockers:** `pythonocc-core` Windows installation. May need conda.

### Phase 2: Reliable Part-Level Solid Diff (2 weeks)

**Goal:** End-to-end pipeline from SolidWorks export to GLB overlay.

1. Add STEP export to SolidWorksExtractor (C# — ~20 lines)
2. Build `ai_inspector/geometry/` Python module:
   - STEP loader with validation
   - Boolean diff with error handling + timeout
   - Tessellator → GLB export
   - Result caching
3. Add `/api/geometry-diff/{part_number}` endpoint to server.py
4. Add "Geometry Diff" toggle in the Part Compare view
5. Test on 3-5 parts with known changes

**Deliverables:** Working feature in the app, tested on real parts.

### Phase 3: Production Integration (1 week)

**Goal:** Polish and integrate with existing systems.

1. Wire solid diff stats into Sage's context (volume changes, region locations)
2. Add "untracked geometry change" detection (solid diff found changes not in feature diff)
3. Progress indicator for long computations
4. Caching: compute once, serve from disk thereafter
5. Error handling: clear messages for STEP import failures, timeout, etc.

**Deliverables:** Sage-aware geometry diff, cached, production-stable.

### Phase 4: Future Expansion

- **Assembly-level solid diff** — diff entire assemblies by diffing each component
- **Tolerance-aware diff** — filter out changes smaller than X mm³ (noise suppression)
- **Change classification** — map diff volumes to engineering categories (hole, pocket, fillet, etc.)
- **Automated validation** — "solid diff confirms feature diff is complete" as a QC check
- **Section view of diff** — clip the diff volume to show internal changes

---

## 7. Recommendation

### Is this worth pursuing?

**Yes.** It's the only way to guarantee you've caught every geometry change between revisions. Feature diff is semantic but incomplete. Solid diff is complete but not semantic. Together they form a verification system that no competitor offers.

### Minimum viable technical path

1. Install `pythonocc-core` via conda (Windows)
2. Manually export 2 STEP files from SolidWorks
3. Run the boolean diff script
4. If it works → build the module

### What to do first

**Export two STEP files of the same part at different revisions from SolidWorks.** Place them in the standard layout:
- `400S_Sorted_Library/parts/1030001/revA/1030001.stp`
- `400S_Sorted_Library/parts/1030001/revB/1030001.stp`

That's the prerequisite for everything else. The rest is engineering.

---

## Risks & Unknowns

| Risk | Severity | Mitigation |
|------|----------|------------|
| `pythonocc-core` hard to install on Windows | Medium | Use conda (`conda install -c conda-forge pythonocc-core`). Fallback: Docker container. |
| Boolean operation fails on complex geometry | Medium | Retry with relaxed tolerance. Timeout + error message. Never show wrong diff. |
| STEP import loses geometry fidelity | Low | SolidWorks STEP AP214 is well-tested. Compare volumes before/after import. |
| Computation too slow for interactive use (>10s) | Medium | Cache results. Show progress bar. Compute in background on revision upload. |
| pythonocc-core ~500MB dependency | Low | Lazy-load. Only downloaded when geometry diff feature is used. |
| Coordinate frame misalignment between revisions | Low | Both revisions come from same SolidWorks part file → same origin. Verify in sidecar. |

---

## Dependencies

### Main Server (.venv313, pip)

| Package | Version | Status | Purpose |
|---------|---------|--------|---------|
| `httpx` | ≥0.27 | **New — add to requirements.txt** | Async HTTP client for proxying to geometry worker |

All other main server dependencies are unchanged.

### Geometry Worker (.conda-geo, conda)

| Package | Version | Size | Purpose |
|---------|---------|------|---------|
| `pythonocc-core` | ≥7.8 | ~500MB | Open CASCADE B-rep kernel |
| `trimesh` | ≥4.0 | ~10MB | GLB export from triangle buffers |
| `numpy` | latest | — | Array operations for tessellation |
| `fastapi` | latest | — | Worker HTTP API |
| `uvicorn` | latest | — | Worker ASGI server |

**Worker env setup:**
```bash
conda create -n geo-env python=3.11
conda activate geo-env
conda install -c conda-forge pythonocc-core
pip install trimesh numpy fastapi uvicorn
```

**Worker startup:**
```bash
conda run -n geo-env python geometry_worker.py
# Listens on localhost:8001
```
