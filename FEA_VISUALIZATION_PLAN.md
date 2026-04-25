# FEA Visualization — Implementation Plan (v2, Codex-reviewed)

## Overview

Visualize FEA simulation results in the 3D Model tab: stress heatmap on the part surface, deformed shape animation, and Sage reasoning about structural consequences.

**Primary extraction path:** COM API via `SimulationExtractor.cs` on a machine with SolidWorks Simulation license. Exports surface mesh + nodal results once. No CWR parsing required.

**Secondary path (no-license fallback):** Direct CWR file parsing via Python `olefile`. Research-grade — requires reverse engineering undocumented binary streams. Treat as a spike, not a delivery commitment.

---

## What We Have

### CWR File (Verified Structure)

We confirmed the CWR file is an OLE2 container with these streams:

| Stream | Size (shaft test) | Content |
|---|---|---|
| **GEN** | 18.3 MB | Node positions |
| **ELF** | 20.7 MB | Element connectivity |
| **STE** | 64.6 MB | Nodal stress/displacement results |
| **LCD** | 9.9 MB | Load/constraint data |
| **OUT** | 9 KB | Solver text output (proven parseable) |

### Key Results Extracted (from OUT stream — proven)

```
Study: Static Analysis (SOLIDWORKS Simulation 2023 SP5)
Mesh: 85,705 elements, 123,421 nodes
Max von Mises stress: 91.9 MPa at node 97,315
Max displacement: 9.42 µm at node 30
Reaction forces: Fx = -13,830 N, Fy = 4,448 N
Error estimate: 20.4% APE
Units: SI (meters, pascals, newtons)
```

### Current Infrastructure

| Capability | Status |
|---|---|
| Part 3D viewer (STL/GLB) | Live |
| Feature coloring on GLB | Live |
| Display settings panel | Live |
| `GlbExporter.cs` (assembly + per-feature GLB export) | Live |
| Sage context injection | Live |
| `olefile` Python package | Installed |

---

## Extraction Strategy

### Path A: COM API (Primary — Recommended)

Use `ICWResults` from the SolidWorks Simulation COM API in a new `SimulationExtractor.cs`:

```csharp
ISimulation simulation = (ISimulation)swModel.Extension.GetSimulation();
ICWStudyManager studyMgr = simulation.GetStudyManager();
ICWStudy study = studyMgr.GetStudy(studyIndex);
ICWResults results = study.GetResults();

// Extract:
// 1. Surface mesh (boundary faces only — not volume tets)
// 2. Nodal von Mises stress on surface nodes
// 3. Nodal displacement vectors on surface nodes
// 4. Study metadata (loads, fixtures, material, yield strength)
```

**Why this is better than CWR parsing:**
- Documented API — no reverse engineering
- Returns **surface mesh** directly (no tet→surface extraction needed)
- Gives material properties and yield strength (not in CWR)
- Handles tet4/tet10 transparently
- Works across SolidWorks versions
- Can re-run the study if the CWR is missing

**Prerequisite:** Machine with SolidWorks Simulation license. User has SolidWorks Premium which includes Simulation.

**Output:** Same as Path B — stress-colored GLB + results JSON.

### Path B: CWR Parsing (Secondary — Research Spike)

Direct Python parsing of CWR binary streams. Treat as a research spike:

1. Attempt to decode GEN (nodes), ELF (elements), STE (stress/displacement)
2. Use OUT stream values as validation anchors
3. If successful: provides a no-license extraction path
4. If unsuccessful: fall back to Path A

**Key unsolved problems:**
- Binary format is undocumented — may vary across SolidWorks versions
- Volume mesh (tet4/tet10) requires surface extraction before rendering
- Material/yield strength not recoverable from CWR (not in any stream)
- Non-static study types may have different stream layouts

**Do not plan delivery timelines around this path.**

---

## Surface Extraction (Critical Step)

**Codex finding #2:** FEA meshes are volume tetrahedra. Three.js renders surface triangles. This step is mandatory regardless of extraction path.

### From COM API (Path A)
Use `ICWResults` to extract the solver's own result plot mesh — this is the simulation surface mesh with nodal results already mapped to it. Do NOT use `IBody2.GetFaces()` (that's CAD tessellation, not the solver mesh — node indices won't align with stress/displacement data). The result plot mesh guarantees that vertex positions, stress values, and displacement vectors are all on the same nodes.

### From CWR (Path B) — if attempted
Must extract external boundary faces from the tet mesh:

```python
def extract_surface_faces(elements):
    """Find faces that appear in exactly one element (external boundary)."""
    face_count = {}
    for elem in elements:
        # For tet4: 4 triangular faces per element
        faces = [
            tuple(sorted([elem[0], elem[1], elem[2]])),
            tuple(sorted([elem[0], elem[1], elem[3]])),
            tuple(sorted([elem[0], elem[2], elem[3]])),
            tuple(sorted([elem[1], elem[2], elem[3]])),
        ]
        for f in faces:
            face_count[f] = face_count.get(f, 0) + 1

    # External faces appear exactly once
    surface_faces = [f for f, count in face_count.items() if count == 1]
    return surface_faces
```

After surface extraction:
- Resample nodal stress/displacement onto surface nodes only
- For tet10 (quadratic): collapse midside nodes or interpolate to corner nodes
- Validate: surface node count should be ~10-20% of total node count

---

## Output Schema

> **Updated 2026-04-24**: After the Stage 1-5 extractor hardening pass, every
> output filename is suffixed with the deterministic study slug, so multiple
> studies on the same part never overwrite each other. The legacy unsuffixed
> names below (`{partNumber}_fea.glb`, `{partNumber}_fea_results.json`) are
> no longer produced. The current contract is documented in
> `SolidWorksExtractor/FEA_WORKER_README.md` and `incoming_fea/README.md`.

### `{partNumber}_fea_{studySlug}.glb` — Stress-Colored Surface Mesh

GLB with vertex colors baked in:
- Blue (0% of max stress) → Cyan (25%) → Green (50%) → Yellow (75%) → Red (100%)
- Surface triangles only (not volume tetrahedra)
- Normals computed from surface faces for proper lighting
- Typical size: 2-5 MB for a part with ~20K surface nodes

`{studySlug}` is the deterministic transformation of the SolidWorks study
name produced by `MakeStudySlug()` in `SimulationExtractor.cs`: lowercase
ASCII alphanumerics, hyphens preserved, everything else replaced with `_`,
runs collapsed, 64-char cap, fallback `study_{index}` for empty.

### `{partNumber}_fea_{studySlug}_results.json` — Schema v2 results

The schema-v2 file is a superset of the legacy v1 fields shown below
(study_name, study_type, units, summary{...}, has_morph_target are all
preserved at the same paths). Stage 3 added top-level `study`,
`units_detail`, `material`, `mesh`, `loads[]`, `fixtures[]`, `results`,
and `warnings[]` sections that mirror the SolidWorks Simulation report.
See `SolidWorksExtractor/Services/SimulationExtractor.cs` (`WriteFeaResultsJson`)
for the complete shape.

```json
{
  "schema_version": "2",
  "study_name": "Static 1",
  "study_type": "static",
  "units": "SI",
  "summary": {
    "surface_node_count": 24000,
    "element_count": 85705,
    "max_von_mises_mpa": 91.943,
    "max_displacement_mm": 0.00942,
    "max_stress_location": [0.025, 0.012, 0.008],
    "reaction_forces": { "fx": -13830, "fy": 4448, "fz": -10.59 },
    "material": "4140 Steel",
    "yield_strength_mpa": 655,
    "safety_factor": 7.12
  },
  "has_morph_target": true
}
```

### `{partNumber}_fea_{studySlug}_manifest.json` — Provenance manifest

Per-run audit record added in Stage 2. Captures `solidworks_version`,
`extractor_git_commit`, `study.{name, slug, index, type, selection_mode}`,
the file list, an embedded summary snapshot, and the warnings collected
during the run. The reviewer-side validator
(`scripts/validate_fea_run.ps1`) cross-checks this against the results
JSON before any merge.

### Deformation Data — Baked as GLB Morph Target

The deformed shape is baked directly into the GLB as a **morph target** (glTF blend shape). No separate binary endpoint needed. The GLB contains:
- Base positions: undeformed surface mesh (morph influence = 0)
- Morph target 0: deformed positions (morph influence = 1)

The frontend animates deformation by sliding `mesh.morphTargetInfluences[0]` from 0 to 1. The GPU handles interpolation — no JS per-vertex work.

Morph target overhead: ~300KB additional in the GLB for 24K surface nodes. Total GLB size: ~3-6MB.

---

## Implementation Phases

### Phase 1: C# Extractor — SimulationExtractor.cs (1-2 weeks)

**What to build:**
1. `SimulationExtractor.cs` in `SolidWorksExtractor/Services/`
2. Access `ISimulation3` → `ICWStudyManager` → `ICWStudy` → `ICWResults`
3. Extract surface mesh with nodal stress values
4. Extract nodal displacement vectors for surface nodes
5. Extract study metadata: material, yield strength, loads, fixtures
6. Map stress to vertex colors (blue→red gradient)
7. Bake deformed positions as morph target 0 in the GLB
8. Export as `{partNumber}_fea_{studySlug}.glb` (reuse `GlbExporter` infrastructure)
9. Export `{partNumber}_fea_{studySlug}_results.json` (schema v2) with summary
10. Export `{partNumber}_fea_{studySlug}_manifest.json` provenance manifest
11. Add `--fea`, `--fea-preflight`, `--fea-list-studies`, `--fea-study-name`,
    `--fea-study-index` CLI flags to `Program.cs` (Stage 1 of the hardening pass)

**Validation:** Compare extracted max stress and displacement against the OUT stream values (91.9 MPa, 9.42 µm).

### Phase 2: Server — Endpoints + Sage Context (0.5 day)

**Endpoints:** (the path resolver picks the slug-suffixed file from the canonical
staging directory `incoming_fea/<part-slug>/<study-slug>/`; the API surface
hides the slug from callers when only one study has been extracted, and
takes a `?study=<slug>` query parameter when multiple are present)
```
GET /api/part-fea/{part_number}[?study=<study-slug>]
  → Returns {partNumber}_fea_{studySlug}_results.json (schema v2 summary + metadata)

GET /api/part-fea-model/{part_number}[?study=<study-slug>]
  → Returns {partNumber}_fea_{studySlug}.glb (stress-colored surface mesh + morph target for deformation)

GET /api/part-fea-manifest/{part_number}[?study=<study-slug>]
  → Returns {partNumber}_fea_{studySlug}_manifest.json (provenance — version, SW build, git commit)
```

**Sage context injection:**
```
FEA SIMULATION RESULTS (Static Analysis):
  Max von Mises stress: 91.9 MPa (at shoulder transition region)
  Max displacement: 9.42 µm
  Material: 4140 Steel (yield: 655 MPa)
  Safety factor: 7.12
  Reaction forces: Fx = -13,830 N, Fy = 4,448 N
```

**Sage prompt — scoped to factual summary only:**
```
FEA REASONING:
When FEA SIMULATION RESULTS are present, use the actual values to answer structural questions.
- Report max stress, displacement, safety factor as factual data.
- Describe stress hotspot by region/feature association, not node ID.
- For "what if" geometry change questions: state that the study would need to be re-run
  for accurate results. You can note the direction of impact (e.g., "reducing cross-section
  at a stress concentration will increase stress") but do NOT give specific numbers for
  modified geometries without re-analysis.
- Do NOT present approximate re-interpolation as authoritative.
```

### Phase 3: Frontend — FEA Visualization (2-3 weeks)

#### Step 3.1: Simulation Toggle

Add to Display settings panel:
```
☐ Simulation Results
```

When checked:
- Load FEA GLB (`/api/part-fea-model/{pn}`) — replaces current model
- Show stress heatmap (vertex colors already baked in)
- Show color bar legend with MPa scale
- Deformation is built into the GLB as a morph target — no extra data load

When unchecked:
- Restore normal gray/feature-colored model

#### Step 3.2: Color Bar Legend

```javascript
const legend = document.createElement('div');
legend.innerHTML = `
  <div style="display:flex;align-items:center;gap:8px;padding:8px 12px;">
    <span style="font-size:11px;">0 MPa</span>
    <div style="width:200px;height:12px;border-radius:6px;
      background:linear-gradient(to right, #0000ff, #00ffff, #00ff00, #ffff00, #ff0000);"></div>
    <span style="font-size:11px;">${maxStress} MPa</span>
  </div>
`;
```

#### Step 3.3: Deformation Animation via Morph Targets

**Why morph targets (not per-frame setXYZ):**
- Three.js morph targets are GPU-accelerated
- Set `morphTargetInfluence[0]` from 0.0 to 1.0 to animate
- No JS per-vertex loop — the GPU handles interpolation
- Works smoothly at 60 FPS even for large meshes

The FEA GLB includes the deformed shape as a morph target (blend shape). Animation is just sliding a single float:

```javascript
function animateDeformation(progress, scaleFactor) {
    // progress: 0.0 (undeformed) → 1.0 (fully deformed)
    mesh.morphTargetInfluences[0] = progress * scaleFactor;
}
```

#### Step 3.4: Deformation Controls

When simulation is active:
```
Simulation Results ☑
├── Scale: [——●——] 50x
├── ▶ Play  ⏸ Pause
└── Progress: [——●——] 75%
```

- **Scale slider:** 1x, 10x, 50x, 100x, 500x exaggeration
- **Play/Pause:** Auto-animate 0% → 100% → 0% in a smooth loop
- **Progress slider:** Manual scrub

---

## Total Effort

| Phase | Effort | Cumulative |
|-------|--------|------------|
| Phase 1: SimulationExtractor.cs | 1-2 weeks | 1-2 weeks |
| Phase 2: Server + Sage Context | 0.5 day | 1.5-2.5 weeks |
| Phase 3: Frontend Visualization | 2-3 weeks | 3.5-5.5 weeks |
| **Total** | **3.5-5.5 weeks** | |

### CWR Research Spike (Optional, Parallel)

| Task | Effort |
|------|--------|
| Attempt GEN/ELF/STE binary decode | 1-2 weeks |
| Surface extraction from tet mesh | 1 week |
| Validation against COM-extracted truth | 0.5 week |
| **Total if successful** | **2.5-3.5 weeks** |

The CWR spike can run in parallel with Phase 3 frontend work. If it succeeds, it becomes an alternative extraction path for users without Simulation licenses.

---

## Risks

| Risk | Mitigation |
|---|---|
| CWR binary format varies across SW versions | Use COM API as primary path. CWR parsing is secondary. |
| Surface extraction from tet mesh is complex | COM API returns surface directly. CWR path needs explicit surface extraction step. |
| 123K nodes too many for browser animation | Use surface-only mesh (~20K nodes). Morph targets for GPU-accelerated deformation. |
| Material/yield not in CWR | COM API provides material data. CWR path requires user to input material manually or read from part profile. |
| Non-static studies (frequency, thermal) | Scope v1 to static studies only. Other types need different result interpretation. |
| Sage gives false structural confidence | Prompt explicitly scoped: factual summary only, no off-nominal re-analysis without recomputation. |

---

## Prerequisites

- SolidWorks machine with Simulation license (for Path A)
- At least one completed static study with results saved
- CWR file available for Path B research spike
- No changes needed to existing frontend infrastructure — reuses GLB pipeline

## Alignment with IDEAS.md / BACKLOG.md

This plan aligns with the original FEA specification in IDEAS.md (lines 491-591) for:
- Stress heatmap visualization
- Deformation animation
- Sage reasoning with FEA values

**Updated from original:** Extraction strategy changed from "SimulationExtractor.cs only" to "COM API primary + CWR secondary." Effort estimate increased from original "Medium" to 3.5-5.5 weeks to account for surface extraction, morph targets, and proper scoping.
