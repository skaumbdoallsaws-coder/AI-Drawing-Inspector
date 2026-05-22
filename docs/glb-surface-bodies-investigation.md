# Surface-heavy GLB export gap — investigation findings

## Smoke case
Part **1030034 Vintage Plane** (revA + revB on disk in
`400S_Sorted_Library/parts/1030034/`). SOLIDWORKS shows a complete
surface-lofted airplane. InspectorPro 3D viewer shows fragments only.

## What the live GLB actually contains
`1030034_colored.glb` (172,872 bytes, identical bytes in revA and revB):

```
asset.generator = "SolidWorksExtractor-PartFeature"
scenes:    1
nodes:     10
meshes:    10
materials: 10
```

All 10 mesh names are solid-body-producing feature types:
```
revolution_revolve1
ice_boss_extrude1, ice_boss_extrude2, ice_boss_extrude5
cirpattern1
mirrorsolid_mirror4, mirrorsolid_mirror5, mirrorsolid_mirror6
sweep1, sweep3
```

`1030034_feature_colors.json` lists the same 10 entries (types:
`revolution`, `extrude`, `circularPattern`, `mirrorsolid`, `sweep`).

## What the part actually contains
`1030034.json` reports **96 features** in `featureTree`, including
both a `SurfaceBodyFolder` AND a `SolidBodyFolder` (so the part has
both kinds of bodies). Surface-producing feature types present:

| count | type                                |
|------:|-------------------------------------|
|     4 | `NetBlend` (Boundary Surface)       |
|     3 | `ExtruRefSurface` (Surface-Extrude) |
|     3 | `PlanarSurface`                     |
|     2 | `TrimRefSurface` (Surface-Trim)     |
|     1 | `RevolvRefSurf` (Surface-Revolve)   |
|     1 | `RuledSrfFromEdge`                  |
|     1 | `DelFace`                           |
|     1 | `PLine` (Split Line)                |

**None of these appear as GLB meshes.** The airplane skin (built from
NetBlend lofts + trimmed/extruded surfaces) is entirely missing.

## Root cause
`SolidWorksExtractor/Services/GlbExporter.cs` enumerates only solid
bodies:

```csharp
// line 211 — per-feature part GLB (the path that produced 1030034.glb)
object bodiesObj = partDoc.GetBodies2((int)swBodyType_e.swSolidBody, true);

// line 1159 — per-component assembly GLB
object bodiesObj = partDoc.GetBodies2((int)swBodyType_e.swSolidBody, true);
```

`swBodyType_e.swSolidBody` excludes `swSheetBody` (surfaces) entirely.
The downstream pipeline (per-face `GetTessTriangles` + `GetTessNorms`
+ owner-feature grouping via `IFace2.GetFeature()`) is body-type
agnostic and would work fine on sheet bodies — only the body-list
filter is wrong.

The same `swSolidBody`-only filter appears at two more sites in
`GeometryAnalyzer.cs:50` and `GeometryAnalyzer.cs:1521`. They affect
bounding-box / mass-properties computations rather than the visual
GLB, but they would under-report geometry for surface-heavy parts in
the same way.

## Fix surface area (proposed, not implemented)

Four call sites. The minimum viable change is to add a second
`GetBodies2(swSheetBody, true)` pass at each site and concatenate the
two body arrays before the existing face-walk. The downstream code
(per-face tessellation, owner-feature grouping, color assignment) does
not change.

| File                    | Line | Purpose                          |
|-------------------------|-----:|----------------------------------|
| `GlbExporter.cs`        |  211 | Per-feature part GLB (primary)   |
| `GlbExporter.cs`        | 1159 | Per-component assembly GLB       |
| `GeometryAnalyzer.cs`   |   50 | Geometry analysis (bbox/mass)    |
| `GeometryAnalyzer.cs`   | 1521 | Geometry analysis (second site)  |

### Open questions (need verification with SolidWorks API docs / live test)
1. **Body-type enum**: is there a `swAllBodies` constant or do we need
   two `GetBodies2` calls and concatenate? `swBodyType_e` typically
   uses `swSolidBody=0`, `swSheetBody=1`, `swWireBody=2`,
   `swMinimumBody=-1`, `swAllBodies=-2` — `swAllBodies` (or
   equivalent) would be one-call cleaner if it exists in our SDK
   binding. Otherwise: two calls, concatenate.
2. **Visible-only flag**: the existing call passes `true` for the
   second parameter (visible bodies only). Sheet bodies follow the
   same visibility rules; same flag should apply.
3. **Owner-feature mapping**: `IFace2.GetFeature()` on a sheet-body
   face should return the owning surface feature (NetBlend,
   ExtruRefSurface, etc.) — confirmed by SolidWorks API docs. The
   existing `featureFaces` dictionary will simply gain entries keyed
   by surface-feature names, which then flow through the existing
   GLB writer.
4. **Browser rendering**: surface bodies have no "interior" so the
   three.js viewer may show single-sided culling artifacts. Two
   options:
     - Set `material.doubleSided = true` (the existing material write
       in `GlbExporter` already supports the field).
     - Apply double-sided only to sheet-body-derived meshes by
       checking `body.GetBodyType() == swSheetBody` before writing
       the material.
   The double-sided polish is **not** required to meet this task's
   goal ("complete browser-viewable GLB even if feature coloring is
   partial or neutral").
5. **Coloring**: `PartColorizer` works at the body / face material
   property level, not at the body-type level — sheet body faces
   already pick up overrides if any. Surface features without
   explicit colors will render in the neutral default, which matches
   the acceptance criterion.

## Implementation (2026-05-21)

### What changed
`SolidWorksExtractor/Services/GlbExporter.cs`:

- New helper `EnumerateVisibleBodies(IPartDoc)` returns a list of
  `TaggedBody { IBody2 Body, bool IsSheet }` by calling
  `GetBodies2(swSolidBody, true)` first, then
  `GetBodies2(swSheetBody, true)`, and concatenating. Two calls used
  rather than a single `swAllBodies` enum because the value is not
  guaranteed by every SDK binding -- the two-call form is portable
  and the cost is one extra COM call per body enumeration.
- `FeatureMeshData` and `MeshData` both gained `bool IsSheetBody`.
- **Per-feature path** (`ExportPartFeatureGlb`): face walk now
  iterates `taggedBodies` instead of solid-only `bodies`. Per-bucket
  `(HasSolid, HasSheet)` tracking decides whether a feature mesh is
  doubleSided. `IFace2.GetFeature()` is unchanged -- surface
  features (NetBlend, ExtruRefSurface, ...) report themselves as
  the owner just like solid features do.
- **Ownerless sheet faces** get a stable `surface_body_<i>`
  fallback bucket (1-based, only advanced for sheet bodies). Solid
  ownerless faces still go to `__unowned__` -> `base_unowned`.
- **`surface_body_<i>` cad_feature_id**: bypasses the
  legacy `base_<slug>` synth path; the name is already final.
- **Per-component assembly path** (`ExtractComponentMesh`): same
  body-enumeration swap; `sawSolid` / `sawSheet` flags set
  `MeshData.IsSheetBody = sawSheet && !sawSolid` so mixed
  components stay single-sided.
- **GLB JSON writers** (`BuildFeatureGltfJson`,
  `BuildGltfJson`): per-material, append `"doubleSided":true`
  when the mesh's `IsSheetBody` is set. No other material
  property changes.

### What was deliberately NOT changed
- `GeometryAnalyzer.cs:50` and `:1521` -- per the task scope,
  GeometryAnalyzer changes were only in scope if "the change is
  low-risk and covered by tests/smoke". No tests cover those
  paths, and the mass/bbox values flow into downstream profile
  surfaces (mass-property card, semantic-property search, FAI
  report mass field). Skipped for now -- separate change.
- Library Intake Wizard code -- out of scope per the spec.
- Coloring: surface features without explicit overrides flow
  through the existing palette/gray assignment. They appear in
  neutral or palette colors depending on iteration order, which
  matches the "complete browser-viewable geometry over perfect
  feature-color mapping" acceptance bar.

### Build + deploy
- `dotnet build SolidWorksExtractor/SolidWorksExtractor.csproj -c
  Release` from the worktree root. Succeeded with one pre-existing
  unrelated CS0618 obsolete-API warning in `Program.cs:612`.
- Built EXE copied from
  `tmp/ui-bridge-telemetry-unified-.../SolidWorksExtractor/bin/Release/SolidWorksExtractor.exe`
  to the main project root
  `SolidWorksExtractor/bin/Release/SolidWorksExtractor.exe`, which
  is the path the wizard's `/api/library/intake/enrich-visuals`
  endpoint resolves by default.

### Operator smoke (needs SOLIDWORKS open)
The actual GLB regeneration cannot be driven from headless code --
SOLIDWORKS must be open against the right SLDPRT. Run these from
the wizard:

1. **Surface-heavy** (1030034 Vintage Plane):
   - Open `1030034_Vintage Plane.SLDPRT` in SOLIDWORKS.
   - In the wizard, open intake for 1030034 revB.
   - In Step 3 click **Enrich visuals**.
   - **Expected**: GLB mesh count > 10 (was: 10 solid-only). New
     mesh names should include `netblend_*`,
     `extrurefsurface_*`, `planarsurface_*`,
     `trimrefsurface_*`, `revolvrefsurf_*`, or
     `ruledsrffromedge_*` (the surface-feature types observed
     in the part's `featureTree`). Any sheet bodies whose owner
     features resolve cleanly will use their feature names;
     ownerless sheet bodies fall back to `surface_body_1`,
     `surface_body_2`, ...
   - In InspectorPro 3D viewer: the airplane skin should be
     visible from both sides (doubleSided material flag).

2. **Solid-only regression** (1020001 Piston):
   - Open `1020001_Piston.SLDPRT` in SOLIDWORKS.
   - Wizard intake for 1020001, Enrich visuals.
   - **Expected**: identical mesh / face count as before
     (the part has no sheet bodies, so `EnumerateVisibleBodies`
     produces the same body list the legacy call did). No
     `doubleSided` markers should appear in the GLB JSON.

### Quick GLB inspection one-liner
```python
import struct, json
with open(path, 'rb') as f:
    b = f.read()
clen = struct.unpack_from('<I', b, 12)[0]
doc = json.loads(b[20:20+clen].decode('utf-8', errors='replace').rstrip('\x00 '))
print('meshes:', len(doc['meshes']))
for m in doc['meshes']: print(' ', m['name'])
for i, mat in enumerate(doc.get('materials', [])):
    if mat.get('doubleSided'): print('doubleSided mat[%d] name=%r' % (i, mat.get('name')))
```
