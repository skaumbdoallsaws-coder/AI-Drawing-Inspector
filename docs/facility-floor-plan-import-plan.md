# Facility floor-plan import plan (DXF)

Date: 2026-11-03  
Status: proposed; no implementation or dependency installation performed.  
Written by a read-only Codex job (job 3) from the code at 7cae4ae; reviewed by the main session.

## 1. Goal and recommended scope

Let a user bring an existing factory drawing into Facility Layout, establish its real scale and position, and use it to reconstruct the building.

The user's starting point, 2026-10-28: importing an existing floor plan should be "an easy addition"; SolidCraft's DXF export code might help, and a real factory plan will follow.

There are two useful deliverables:

1. **Reference underlay:** display selected DXF layers at the correct scale beneath the layout. The user can measure, snap to reference geometry, and trace walls and zones with the layout's authoring tools.
2. **Reviewed conversion:** turn selected drawing geometry into native walls, openings, zones and, later, columns. Show the proposed result before the user applies it.

Recommend shipping the underlay first, followed by bounded wall and zone conversion. A useful underlay does not depend on correctly interpreting every CAD convention. Conversion needs more work because DXF entities describe drawing geometry, not necessarily building objects.

The intended flow:

1. Choose **Import floor plan** in the Plan workspace.
2. Upload a DXF and inspect its layers, units, extent and unsupported entities.
3. Choose the floor and useful layers; exclude title blocks and unrelated drawings.
4. Confirm units, measure a known distance, and align the drawing.
5. Apply the reference underlay.
6. Trace manually, or ask Sage to propose conversion of selected layers.
7. Review the proposed geometry against the underlay, correct uncertain items, and apply.
8. Continue placing equipment in the existing layout.

Importing requires no street address, aerial photograph or internet connection.

### First-release exclusions

- DWG, PDF and scanned-image import.
- Complete CAD editing, DXF round-trip export or preservation of CAD plotting styles.
- Automatic reconstruction of every wall, door, room or equipment symbol.
- Multiple floors, elevations, sections, sloping geometry and 3D solids.
- Automatic updates from a subsequently revised CAD file.
- Engineering certification, structural interpretation or inferred fire/egress classifications.
- Automatic replacement of the current layout, its shell authority or its Site position.

An underlay is reference information. It creates no collision geometry until native objects are accepted.

## 2. What exists and constrains the design

| Existing implementation | Consequence for import |
| --- | --- |
| `validate.py` requires meters, `+Y` up and floor axes `+X/+Z`. `canonical.py` rounds known meter geometry to six decimal places. | Normalize imported geometry into the existing frame. Do not change the layout coordinate convention. |
| `sourceShellRef` pins a shell revision and coordinate-frame fingerprint; `service.py` verifies frame agreement. | Import must not redefine the datum or rewrite the shell reference to accommodate CAD coordinates. |
| `facilityPlan` stores width, depth and grid spacing. Without explicit ground, `shell_with_plan_boundary()` makes the effective floor a rectangle starting at `(0,0)`. | Drawing alignment and plan resizing are separate, reviewed changes. A polygon wall perimeter is not an authoritative polygon floor. |
| `facilityInteriorWalls` stores straight centerline segments, thickness, height, base elevation and openings. Its compiler derives physical panels and shell obstacles. | Reuse native wall operations and compilers; never trust imported panel meshes. |
| Interior walls are limited to 128; each supports 32 openings. | A large factory can exceed the authoring model even when its underlay renders successfully. |
| Perimeter walls support a plan rectangle or a simple polygon, up to 128 vertices and 128 openings. | Reuse this for explicitly selected building outlines, subject to the floor limitation above. |
| Zones are simple, implicitly closed, counter-clockwise polygons. Limits include 500 zones, 256 vertices per zone and 50,000 total zone vertices. | Closed CAD loops require validation and semantic review before becoming zones. |
| Spatial validation checks floor support and applicable zone containment. | Imported rooms can invalidate existing equipment placement. Run the authoritative checks on the whole proposed result. |
| Site references store property-frame points; `site_reference_fit.py` fits translation and rotation, never scale. | Reuse the reference-point interaction and residual reporting, but implement a distinct DXF calibration transform. |
| `decal_images.py` provides streamed, bounded uploads and content-addressed, tenant/site-scoped storage. `api.py` mounts specialized routers. | Follow that storage and API pattern for DXF artifacts. |
| Exact operation proposals already provide previews, dependency binding, approval, application and receipt-bound Undo. | Import conversion should use that pipeline. |

Two distinctions matter:

- Native interior-wall openings currently remove the wall's full height. Perimeter openings can carry an opening height. A door symbol cannot promise identical architectural treatment in both representations.
- `wall_attachments.py` attaches equipment to revision-bound **asset placements**, using their upright faces. A native imported wall ID is not a `supportPlacementId`.

## 3. Reader choice

**Recommend ezdxf, subject to the user's approval to install it.**

The supplied environment facts say ezdxf is not installed and is MIT licensed. No installation or external verification was attempted for this plan.

SolidCraft's DXF implementation is an exporter. Its entity concepts and unit handling may be useful references, but its writer does not supply the reader this feature needs. Porting Rust code into this Python service would also introduce integration work without solving parsing.

| Option | Benefits | Limits and rough effort |
| --- | --- | --- |
| Own minimal ASCII reader | No new dependency; a tightly controlled subset is possible. | A LINE/polyline demonstration could take several days. Real factory compatibility requires encodings, versions, object coordinate systems, blocks, bulges and malformed-file handling. Allow several additional weeks, with continuing compatibility work. |
| ezdxf plus a restricted adapter | Existing DXF parsing and entity access; fits the Python backend; MIT license. | Still needs isolation, limits, geometry normalization, warnings and tests. Allow roughly 3-5 days for the initial reader adapter within the underlay phase. It does not infer building semantics. |
| Reuse SolidCraft's writer | Potentially useful entity/unit reference under the supplied MIT/Apache-2.0 licensing facts. | Does not parse DXF. Not the implementation route. |

Pin the approved ezdxf version, review its dependency notices, and include the applicable license notices in distribution. Do not add an automatic installer.

If installation is declined, explicitly narrow the product to an agreed ASCII entity subset or defer implementation. Do not quietly ship a toy parser as general DXF support.

### Initial supported drawing subset

Start with ASCII DXF model space. Establish the tested version range in the reader spike.

| Entity | Initial treatment |
| --- | --- |
| `LINE` | Exact reference segment. |
| `LWPOLYLINE`, planar `POLYLINE` | Preserve closure and bulges; flatten curved portions with bounded error. |
| `ARC`, `CIRCLE` | Reference curves; bounded tessellation for display and geometric queries. |
| `INSERT` and local blocks | Bounded expansion with nested transforms, insertion base points, rotation, scale and layer inheritance. Preserve instance provenance. |
| `TEXT`, `MTEXT` | Sanitized reference labels; approximate font/layout fidelity is acceptable and disclosed. Never execute fields or formatting commands. |
| `HATCH` | Initially report as unsupported. Add explicit boundary extraction later; do not expand decorative hatch strokes. |

Also report unsupported entities by type and layer. Paper-space sheets, external references, proxy objects, embedded objects, images, dimensions and unsupported curves must not disappear without explanation.

Nonuniform or mirrored block transforms need explicit fixtures. Supported geometry must transform correctly; entities the adapter cannot transform faithfully remain unsupported. Nonplanar geometry must be reported rather than silently flattened.

## 4. Storage and document model

### Artifact storage

Add a dedicated floor-plan artifact store beside the existing layout artifact stores.

Store:

- Original DXF bytes, identified by SHA-256.
- An immutable normalized geometry artifact.
- A bounded manifest: parser/version, source units, layers, extents, entity counts and warnings.
- Derived previews or display tiles.
- Conversion provenance artifacts when native objects are created.

Scope all artifacts by tenant and site, following `decal_images.scope_directory()`. Use generated identifiers and digest-based names. Original filenames are display metadata only.

The normalized artifact contains drawing geometry and source identities, not serialized parser objects. Each entity records its source handle where available, layer, block-instance path and supported geometry.

Keep large entity arrays, original bytes and thumbnails **outside layout JSON**. Existing extensions share a 5 MiB budget.

### Layout extension

Propose `extensions.facilityFloorPlanReferences`, version 1. Support one active reference initially; retain an array shape for later expansion.

Illustrative shape:

```json
{
  "version": 1,
  "references": [
    {
      "referenceId": "fp-main-floor",
      "label": "Factory ground floor",
      "sourceSha256": "...",
      "geometrySha256": "...",
      "parserVersion": "...",
      "alignment": {
        "sourceOrigin": {"u": 0, "v": 0},
        "metersPerDrawingUnit": 0.001,
        "rotationDegrees": 0,
        "translationMeters": {"x": 0, "z": 0},
        "unitSource": "header",
        "confirmed": true,
        "controlPoints": []
      },
      "layers": [
        {"layerId": "layer-1", "visible": true, "role": "reference"}
      ],
      "opacity": 0.35,
      "showIn3D": false
    }
  ]
}
```

Finalize field limits during FP0. Source coordinates retain sufficient precision in drawing units; transformed native geometry follows layout canonicalization.

Roles should include `reference`, `wall_centerline`, `wall_faces`, `perimeter`, `room_boundary`, `column`, `door`, `text` and `ignore`. Roles express the user's mapping, not an automatic assertion of meaning.

Add targeted operations:

- `upsert_floor_plan_reference`
- `delete_floor_plan_reference`

Register them in operations, validation, schemas and proposal handling. Add an explicit normalizer; preservation of unknown extension fields is not sufficient validation.

Persist reference settings and alignment. Keep upload progress, temporary selections, camera state and drag previews outside the document.

### Provenance and lifecycle

For each conversion, retain a manifest linking source entities, alignment, conversion settings and resulting native IDs. Wall records have a closed field contract, so do not insert arbitrary provenance fields into them.

Bind conversion artifacts to their hashes and converter version. Preserve artifacts needed by saved revisions and Undo. A conversion staged for review that is never applied is removed two hours after it was last staged (a proposal lives 15 minutes); an applied conversion's record is kept for good as its manifest: it is checked and marked as being applied just before the layout is saved, under the same hold the removal honors, then marked with the revision it gave (so a stop in between keeps it too). Undo needs neither: an undo carries no origin. Removing an underlay removes its current reference, not converted walls or historical source material.

A missing reference artifact should produce an actionable warning without destroying access to native layout geometry. Applying a proposal that depends on a missing or changed artifact must fail.

Reimporting the same file should detect the existing reference. A revised file starts a new comparison; it must not overwrite previously converted and manually edited objects.

## 5. Units, scale and alignment

### Units

Read `$INSUNITS` and present the interpreted unit prominently.

- Convert recognized drawing units to meters once.
- Keep display units independent. The workspace already supports meters and feet.
- Treat missing or unitless units as unresolved.
- Do not infer physical scale from paper-space plotting scale, dimension labels or apparent building size.
- Present suspicious extents and inconsistent measurements for correction.
- Characterize block-unit behavior in the pinned reader and test against double scaling.

For unitless drawings, offer:

1. Choose the drawing unit explicitly.
2. Pick two points and enter their real distance.

Even with declared units, offer a known-distance check. A wrong unit header is possible.

### Transform

After resolving entity/block coordinates into the drawing's common plane:

```text
layoutPoint = translation
            + metersPerDrawingUnit * R(rotation) * (drawingPoint - sourceOrigin)

drawing X -> layout X
drawing Y -> layout Z
layout height -> coordinateFrame.floorElevation
```

Define rotation explicitly as counter-clockwise in the numeric X/Z plane. Use one implementation and shared test cases across conversion and display.

The transform supports translation, rotation and uniform scale. It does not stretch one axis or automatically reflect the whole drawing.

Subtract a source origin before rendering to avoid precision loss from large survey coordinates. Preserve the original origin and transform in provenance.

### Two-point workflow

1. Select source points A and B.
2. Enter their real distance, or select corresponding layout points.
3. Set the target location of A and the direction from A to B.
4. Show resulting scale, rotation, extents and measured dimensions.
5. Check a third independent point or distance when available.
6. Apply the alignment.

Reject coincident or inadequately separated control points. With additional controls, report residuals and conflicting measurements. Two fitted points alone cannot prove drawing accuracy or detect every orientation mistake.

For declared, confirmed units, default to a rigid alignment. Changing scale remains an explicit correction.

### Origin and Site relationship

For a new layout, suggest placing the selected building extent near the plan origin, with room for wall thickness. Do not use title-block or distant annotation extents.

For an existing layout, align the drawing to existing geometry. Do not move existing equipment, zones, the datum or Site `buildingPose`.

The reference lives in the **building frame**. Site georeferencing remains separate. Moving the building on the property carries its aligned reference with it; it does not recalibrate the DXF.

## 6. Workspace and rendering

### Plan view

Add an Import floor plan action and a reference panel in `facility_layout_workspace.js`, backed by a small dedicated import controller.

The panel provides:

- Upload status and parse warnings.
- Layer names, counts, extents, visibility and role selection.
- Unit confirmation and calibration.
- Opacity, lock, hide, remove and fit-reference controls.
- Selected-entity inspection.
- Conversion preview and exclusions.

Integrate drawing into `facility_layout_editor.js`, whose `TopPlanAdapter` owns the SVG plan.

Render the underlay above opaque floor fills and below the editing grid and authored geometry. The current environment function draws floor and grid together, so that ordering needs a deliberate insertion point. Provide a tracing display mode that dims obstructing fills without editing their saved appearance.

Default reference geometry to noninteractive. Enable endpoint/intersection snapping and point selection only while calibrating or tracing. Reference picks must not masquerade as native layout selections.

Use grouped paths or a tiled canvas layer for large drawings, not one DOM element per entity. Retain exact normalized geometry separately for snapping and conversion.

### 3D view

The initial underlay may remain Plan-only. An optional 3D reference display should use a flat, noncollidable drawing overlay at floor elevation with a small rendering offset.

It is not a 3D CAD import. Accepted native walls, zones and columns use their normal 3D representations.

Plan X/Z and 3D X/Z remain identical. The adapter already has display-mirroring behavior; do not add another coordinate flip for DXF. Test with an asymmetric drawing and readable labels.

Underlay visibility must not affect collision checks, routes or floor support.

### Preview consistency

Use the same represented layout that the workspace sends to its controller, including proposal previews. Do not display a saved underlay beneath geometry from a different candidate.

Key cached display data by artifact hash, alignment, selected layers and represented layout identity. Switching layouts, previews or views must invalidate the appropriate caches.

Underlay inclusion in exported plan PDFs is deferred. Accepted native geometry should continue through the existing plan-output path.

## 7. Conversion rules and honest limits

Conversion is deterministic geometry processing over explicit selections. Sage supplies intent and explains ambiguity; it does not generate thousands of coordinates.

| Input | Proposed conversion | Required review and limitations |
| --- | --- | --- |
| Lines on a centerline layer | Native straight interior walls. | Height and thickness must be supplied or explicitly accepted defaults. |
| Paired parallel wall-face lines | Centerline halfway between faces; thickness from separation. | Require sufficient overlap and consistent spacing. Reject ambiguous pairings, decorative lines and competing neighbors. |
| Closed room polylines | Native zones with approved label and type. | Validate closure, simplicity, area and containment. A CAD room is not automatically a manufacturing zone. |
| Selected exterior loop | Native perimeter-wall settings. | Require explicit exterior selection; preserve or explicitly replace current openings and finishes. Does not redefine an irregular floor. |
| Rectangles, circles or recognized blocks on a column layer | Reviewed column candidates. | Dimensions and height must be supported by native geometry or a matching approved catalog asset. |
| Door arcs or recognized door blocks | Candidate opening on a specific wall, with width and possible swing. | An arc alone is insufficient evidence. Match jambs, wall location and symbol orientation. |
| Text inside a room | Suggested room label. | Multiple or missing labels remain unresolved; sanitize and bound text. |
| Hatch boundaries, later | Candidate boundaries using explicit loops. | Holes and nested boundaries require deliberate handling; never fill them silently. |

### Walls

- Deduplicate coincident segments within a declared tolerance.
- Join collinear runs only when this preserves openings and branch topology.
- Pair wall faces using a spatial index and bounded candidate search.
- Show the original faces and resulting centerline together.
- Preserve junction gaps that cannot be resolved confidently.
- Do not infer thickness from lineweight or height from a 2D drawing.
- Keep curved walls as reference geometry initially.

Current interior-wall constraints include a 0.1 m minimum length, 0.05-2 m thickness and 0.5-30 m height. The compiler also requires supported base elevation and the wall's thickness to remain inside the plan.

The 128-wall limit is global. Importing several batches does not bypass it. Exceeding it requires a separate measured capacity change, simplification accepted by the user, or retaining some geometry as reference.

### Rooms and zones

Remove an explicit repeated closing vertex, establish canonical winding, and validate after meter conversion and rounding.

Reject self-intersections, collapsed polygons and unsupported holes. Resolve nested and duplicate loops explicitly. Report any simplification error; never simplify only to make validation pass.

Use the existing zone-type enum. There is no generic `room` type today. The user must accept a functional mapping; labels alone do not establish safety classifications.

Before adding zones, check all existing placements against the resulting applicable zones. Do not invent a building-wide catch-all zone to conceal containment failures.

### Columns

Phase FP3 should first use approved catalog assets when their dimensions and placement semantics match the source.

For arbitrary rectangular or circular columns, recommend a small native `facilityColumns` extension if needed: footprint, height, base elevation and stable ID, compiled into authoritative column obstacles and matching 2D/3D geometry. This is additional work, not an existing import capability.

Do not represent structural columns as decorative zones or silently distort catalog models. Until supported, leave them as visible, unconverted candidates.

### Doors

Accept conversion only when an opening can be associated with one wall and its position and width are defensible.

- Interior openings use distance intervals along their wall and are currently full height.
- Perimeter openings use edge indices and intervals, with optional opening height.
- Door leaves, frames and swing graphics are separate from the opening.
- Unsupported, sliding, double or unusual doors remain candidates until reviewed.

Do not claim door swing clearance is represented merely because a wall gap was created.

### Irregular building footprints

An L-shaped perimeter can be displayed and authored as walls, but `facilityPlan` still supplies a rectangular floor unless another supported floor authority is used.

For the initial conversion release, disclose that limitation and avoid claiming exact reconstruction of an irregular shell. If the real factory requires accurate floor containment around recesses or courtyards, add polygon-floor authority as a separately scoped prerequisite. Do not solve it by directly replacing `sourceShellRef`.

## 8. Review, application and Undo

Every import-derived layout change must be reviewable.

The review shows:

- Source file, selected layers, units and alignment.
- Added, changed and removed native objects.
- Assumed height, thickness, tolerances and semantic mappings.
- Unconverted and ambiguous entities, with reasons.
- New spatial/routing errors and warnings.
- Underlay and proposed geometry together.

Users can exclude individual candidates or change settings and regenerate. Apply saves exactly the reviewed result. Cancel leaves the layout unchanged.

Use targeted operations such as `upsert_interior_wall` and `add_zone`. Whole-collection setters replace their collections; preserve unrelated records whenever one is necessary. Existing perimeter replacement requires explicit review of what changes.

Reuse `operation_proposals.py` and the service's authoritative preparation pipeline:

1. Bind the saved layout revision and source artifacts.
2. Generate native operations server-side.
3. Canonicalize and validate.
4. Check dependencies, spatial findings and routing changes.
5. Show the exact proposal.
6. Approve and apply through the existing API.
7. Retain the receipt for existing Undo behavior.

**Require review even in Apply Directly mode.** Server-generated packages currently have a standing-consent path. Add an import-specific review requirement enforced during approval and application, not just a UI flag. Include the package origin and source dependencies in the binding so a conversion cannot become direct-applicable merely because it contains otherwise eligible operations.

Bind source/geometry hashes, alignment, layer mapping, converter version and tolerances. A stale layout or changed source requires regeneration.

Existing model-written batches are limited to 50 operations and 24,000 serialized bytes. Server packages advertise larger limits, but the operation kernel caps a transaction at 500 operations. Set an import package budget within the effective limits. Larger conversions need explicit, independently valid stages; never apply a partial conversion silently.

Realigning or removing an underlay does not move or delete previously converted native objects. Show that relationship clearly and offer a new comparison proposal when appropriate.

## 9. Sage tools

Add bounded contracts through `codex_runtime/facility_tools.py`, `edit_schemas.py`, authoring reads and the assisted preview gateway.

Proposed tools:

| Tool | Purpose |
| --- | --- |
| `inspect_floor_plan_import` | Read an authorized uploaded artifact's units, layers, counts, bounds, warnings and paginated entity summaries. |
| `align_floor_plan_import` | Calculate an alignment from specified controls and units; return dimensions and residuals without saving. |
| `plan_floor_plan_conversion` | Convert selected layers/entities using explicit roles and parameters; return a server-owned package and unresolved candidates. |
| `preview_floor_plan_import` | Stage reference settings or a conversion package with mandatory review. |

The tool names are proposed, not existing capabilities.

Uploading belongs to the UI/API. Sage receives an authorized artifact ID, not permission to read arbitrary paths or fetch arbitrary URLs.

Sage may independently:

- Inspect and explain the uploaded drawing.
- Suggest layer roles and candidate matches.
- Calculate a transform from user-provided controls.
- Prepare deterministic conversion candidates.
- Explain unsupported entities and validation failures.

Sage must not independently:

- Commit imported geometry.
- Resolve unknown units or ambiguous alignment by guessing.
- Replace a perimeter, resize a populated plan or move existing objects.
- Turn labels into safety classifications.
- Install dependencies, invoke CAD converters or follow external references.

Return compact summaries and candidate IDs rather than full drawings in tool output. Drawing text is untrusted source data, never instructions. Raw DXF files remain local by default.

## 10. API, security and performance

### API integration

Mount a dedicated router from `create_facility_layout_router()`.

Proposed route family:

- `POST /api/facility-layouts/{site_id}/{layout_id}/floor-plan-imports`: stream upload and start parsing.
- `GET .../floor-plan-imports/{import_id}`: job status, manifest and warnings.
- `GET .../floor-plan-imports/{import_id}/geometry`: bounded normalized geometry or tiles.
- `POST .../floor-plan-imports/{import_id}/alignment`: calculate an alignment.
- `POST .../floor-plan-imports/{import_id}/conversion-preview`: create a bound conversion proposal.

Use existing approval/apply endpoints for committing. Uploading and parsing do not modify the layout.

Reuse existing principal resolution, permissions and feature gates. Check layout/site access before accepting upload bytes and on every artifact request. A digest alone grants no access.

### Proposed initial limits

These are implementation targets to benchmark, not measured guarantees.

| Resource | Initial limit |
| --- | --- |
| Upload size | 25 MiB, enforced while streaming |
| File form | One ASCII DXF; no archives |
| Parsed source entities | 100,000 |
| Expanded block entities | 250,000 |
| Total flattened vertices/segments | 1,000,000 |
| Block nesting | 16 levels, with cycle detection |
| Layers | 512 |
| Text per entity | 4 KiB after normalization |
| Parse/normalize job | 30-second wall-clock limit; 512 MiB worker memory ceiling |
| Concurrent parsing | One job per principal, plus a bounded global queue |

Apply limits during processing, before oversized intermediate structures are allocated where possible. Also bound per-entity vertices, record lengths, artifact output size, conversion candidates and geometry-search work.

### Untrusted input

- Verify file structure; do not trust suffix or MIME type alone.
- Parse in a killable worker with enforced limits. A timed-out thread that continues running is insufficient.
- Disable network access and external resource resolution.
- Never load XREF files, linked images, fonts, URLs or paths from the drawing.
- Never execute scripts, fields, embedded objects, shell commands or imported serialization.
- Reject nonfinite numbers, recursive block expansion and unsupported coordinate magnitudes.
- Treat labels as escaped text. Build rendering from normalized primitives, not uploaded SVG/HTML.
- Serve original DXF only as an attachment, with appropriate content type and `nosniff`.
- Use atomic artifact writes and clean incomplete jobs.
- Bound logs and avoid recording entire factory drawings or their text.

Unsupported references must appear in the import report. A drawing missing its external architectural reference is not a successful complete import.

### Large-plan behavior

Parse once and cache immutable normalized geometry. Alignment changes must not reparse the file.

Use spatial indexing for snapping and wall-face pairing, bounded curve tessellation, viewport culling, layer grouping and display detail levels. Keep exact geometry separate from simplified display geometry.

Benchmark a synthetic 100,000-entity plan. Initial targets:

- Parse completes within the enforced limit or fails cleanly.
- Progress and cancellation remain responsive.
- Cached display opens within roughly two seconds on the agreed test machine.
- Pan/zoom does not create one DOM node per source entity or repeatedly rebuild the full drawing.
- Hiding the underlay restores near-baseline rendering cost.

Record actual timings and memory. Tune limits from evidence before accepting the real factory plan.

## 11. Phases, fixtures and acceptance gates

Estimates are engineering days for one developer familiar with this repo. They include targeted tests and integration work, exclude approval waits, and are provisional until the real DXF is available.

| Phase | Work | Acceptance gate | Effort |
| --- | --- | --- | --- |
| **FP0: contracts and reader spike** | Approve dependency, pin version, define artifacts/alignment/entity support, characterize block and unit behavior. | Small synthetic drawings produce independently checked normalized geometry; unsupported input is reported; limits have a concrete enforcement design. | 2-3 days |
| **FP1: usable underlay** | Upload/store/parser worker, layer panel, calibration, snapping, reference operations, persistence and Plan rendering. | Import, align, trace, apply reference, reload and Undo work end to end; cancel changes nothing; no new collision geometry. | 8-12 days |
| **FP2: walls and zones** | Centerline and paired-face conversion, room loops, perimeter proposals, provenance, authoritative validation and mandatory review. | Exact golden geometry, existing-layout preservation, stale-proposal rejection and Apply Directly refusal all pass. | 7-10 days |
| **FP3: columns and doors** | Approved block mappings, column representation, door candidates/openings, limited hatch boundaries if justified. | Asymmetric/mirrored symbols behave correctly; accepted obstacles agree in validation, Plan and 3D; ambiguity remains visible. | 6-10 days |
| **FP4: real-factory acceptance** | Performance tuning, browser and isolated Electron checks, real-file review, packaging and regression fixes. | User's factory drawing meets the agreed dimensional and workflow checks; limitations and timings are recorded. | 3-5 days |

Expected range: about 2-3 weeks for the underlay foundation, 3-5 weeks through wall/zone conversion, and 5-8 weeks through the fuller scope. Unusual source conventions or model-capacity changes can extend this.

Security and responsiveness belong in FP1; FP4 is validation and tuning.

### Fixture DXFs to create

Use small synthetic fixtures with documented coordinates and ownership. Generate large stress drawings during tests rather than checking bulk generated files into the repository.

1. **Asymmetric factory:** a 30 m by 20 m outline, a 10 m partition, a 0.2 m wall, a 1.2 m door gap, a 4 m by 5 m room and an off-center column.
2. **Equivalent unit drawings:** the same geometry authored in meters, millimeters, inches and feet.
3. **Unitless and misleading units:** require calibration; detect a known-distance mismatch.
4. **Large source origin:** translated survey-like coordinates normalize without losing local precision.
5. **Blocks:** nested, rotated, scaled, mirrored, arrayed and layer-inheriting instances; unsupported transform cases are explicit.
6. **Curves:** bulged polylines, clockwise/counter-clockwise arcs and circles.
7. **Room boundaries:** reversed winding, duplicate closure, small gaps, self-intersections, nested loops and holes.
8. **Wall ambiguity:** duplicate lines, branches, varying thickness, near-parallel furniture and dimension lines.
9. **Doors:** clear single-leaf example, mirrored symbol, ambiguous arc and unsupported sliding/double-door cases.
10. **Hostile/oversized drawings:** recursive blocks, excessive text/vertices, nonfinite values, XREF paths, HTML-like text and truncated files.
11. **Large factory:** many layers and repeated blocks within and just beyond each limit.

### Golden checks

- Equivalent unit fixtures produce equivalent meter geometry.
- A unitless 10,000-unit segment calibrated to 10 m uses `0.001` meters per drawing unit.
- A known rotation/translation maps endpoints correctly in both renderers and in native operations.
- Straight-wall centerlines, thickness, room areas and door intervals match hand-calculated expectations.
- Curved display error remains within the declared tessellation tolerance.
- Repeated parsing and conversion with pinned versions produce stable artifacts and IDs.
- Preview and application produce the same canonical native result.
- Repeating a conversion does not duplicate objects.
- Unrelated walls, zones, placements, Site context and finishes remain unchanged.

### Integration and refusal checks

Exercise:

- Save/reload, reference removal and historical artifact retention.
- Missing artifacts and cross-scope access refusal.
- Stale layout, stale alignment and stale package rejection.
- Mandatory review while Apply Directly is selected.
- Receipt-bound Undo under its existing current-revision rules.
- New wall/equipment collisions and route obstruction.
- Zone conversion that strands existing placements.
- Interior-wall, polygon and transaction limits.
- Existing explicit ground that prevents silent plan resizing.
- Preview switching, layout switching and Plan/3D agreement.
- Cancellation and worker termination with no layout mutation.

Extend relevant Python and JavaScript suites, then run an actual workspace browser test during implementation. Renderer unit tests alone do not prove workspace wiring. If structure-source or generation-preview identity code changes, run `tests/verify_facility_layout_structure_tree_app.py` as required by `AGENTS.md`.

Verify Electron separately using its isolated-snapshot procedure. Keep Windows helpers hidden and report actual runner results.

The real factory DXF remains the release acceptance case. Synthetic fixtures cannot establish compatibility with an unseen drawing. Confirm its unit system, a few independent dimensions, layer mapping, representative walls/doors/columns and acceptable omissions with the user.

## 12. Later formats

### DWG

Recommend asking for a DXF export first.

The supplied alternatives are ODA File Converter, which is free but closed-license, and LibreDWG, which is GPL. Either requires a separate product, licensing and packaging decision. Do not automatically download, bundle or invoke one.

If approved later, conversion should produce a local DXF that enters the same bounded import pipeline, with converter/version provenance.

### PDF

Treat PDF as a later underlay feature.

The supplied environment includes MIT-licensed pdfplumber, which may help extract vector geometry and text. A PDF's drawing scale still needs calibration, and scans require a raster workflow.

PyMuPDF/fitz is supplied as AGPL licensed. That is a licensing concern for a commercial product; do not adopt it merely because it is already installed. Decide on a compatible licensing route before using it in the feature.

PDF walls and rooms are generally less structured than CAD entities. Reuse the reference, alignment and proposal architecture, but estimate PDF conversion separately.

## 13. Decisions for the user

1. **Install ezdxf?** Recommend yes, with a pinned version and license notices. Installation requires your approval.
2. **First delivery:** underlay and manual tracing, or underlay plus wall/zone conversion? Recommend underlay first.
3. **Real factory plan:** provide the DXF later, with its expected units and several known dimensions. It is needed before claiming factory-plan compatibility.
4. **Private fixture use:** may the real drawing be retained as a local acceptance fixture, and may any sanitized portion enter the repository? Default: keep it private and outside version control.
5. **Conversion semantics:** confirm wall heights, uncertain thicknesses, room-to-zone mappings and any replacement of existing geometry.
6. **Irregular footprint:** if the factory has recesses or courtyards, is a reference/perimeter sufficient initially, or must exact floor containment be included?
7. **DWG route:** request DXF, use an approved ODA workflow, or evaluate another licensed route? Recommend DXF.
8. **Optional presentation:** include a 3D reference overlay and underlay in exported PDFs? Recommend Plan-only underlay first.

## 14. Decisions taken and implementation notes

The user answered section 13 on 2026-11-04, taking every recommendation: install ezdxf; underlay first, then the rest of this plan; share the real DXF early; keep it private, outside the repository; ask during review for heights, unclear thicknesses and room-to-zone types, and never replace existing geometry without approval; walls are enough for an irregular outline (the floor stays a rectangle); ask for a DXF instead of a DWG; Plan view only at first.

### FP0 (reader, worker, alignment)

- **Dependency.** `ezdxf==1.4.5`, installed without extras (the `draw` extras would bring PyMuPDF). Licenses from the installed metadata: ezdxf MIT; its requirements are pyparsing (MIT), typing_extensions (PSF-2.0), numpy (BSD-3-Clause) and fonttools (MIT). `docs/facility-layout-python-third-party-notices-draft.md` is machine generated by `tools/inventory_facility_python_dependencies.py`; regenerate it with that tool at release time rather than by hand.
- **Reader** (`ai_inspector/facility_layout/floor_plan_reader.py`). It imports only the standard library and ezdxf, so the worker loads it by path without the app package. Before parsing it refuses binary DXF, DWG, archives, PDFs, files over 25 MiB and files that do not end in `0`/`EOF` (truncated). It handles entities as section 3 describes, plus these details:
  - Layer names match case-insensitively.
  - Entities on layer `0` inside a block take the layer of the insert that places them.
  - MINSERT copies count toward the expanded-entity limit.
  - A block's own unit is reported but not applied.
  - External references are reported by file name only, never by folder.
  - Invisible entities are reported, not drawn.
- **Curves.** Lines, polylines (including bulges), arcs and circles are sampled on the true curve. Ellipses and splines use ezdxf's adaptive sampling of the exact curve. ezdxf's Bezier path conversion was tried first and rejected: its arc approximation strays about 0.027% of the radius (13 mm on a 50 m arc) before any flattening. Each chord stays within the tolerance after block scaling: 2 mm when the units are declared, otherwise 1/100,000 of the header extents. A curve over 50,000 points is retried at 10, 100 and 1,000 times the tolerance, then reported.
- **Worker** (`floor_plan_worker.py`). The child is `python -E -B` with no window, run from its own job folder. On Windows it runs inside a job object with a 512 MiB per-process memory cap that kills it when the job closes, and it is terminated after 30 s.
  - The child reads nothing until the parent has placed it in the job (a one-byte start signal on stdin).
  - It runs with `OPENBLAS_NUM_THREADS=1`. Without it, numpy's OpenBLAS commits a buffer per CPU thread at import: 431 MB for a 13-entity drawing, against 77 MB with one thread. A cap below the import baseline then hangs until the timeout instead of failing.
  - Measured: 60,000 lines (an 8.6 MB DXF) parse in about 3.5 s with a 188 MB peak, so a dense 25 MiB file should stay near 400 MB.
  - Release the parsed document before building the output.
  - The desktop's managed isolated runtime (`desktop/runtime/managed_backend.py`) forbids subprocesses, so imports are unavailable there (503 `parse_unavailable`); the application backend allows them.
- **Alignment** (`floor_plan_alignment.py`) implements the section 5 transform, a least-squares similarity fit (or rigid, with the declared scale held) with residuals and the scale ratio implied by the picks, and a closed, idempotent stored form. Its cases are in `tests/fixtures/facility_layout/floor_plan/alignment_cases.json` for the browser copy to share.
- **Fixtures** are generated by `tests/floor_plan_dxf_fixtures.py` (fixtures 1-6, 10 and the limit cases of 11); the tests compare against hand-written coordinates.

### FP1a (store, routes, underlay record)

- **Store** (`floor_plan_store.py`), per tenant and site beside the decal images: `sources/<sha256>.dxf`, `geometry/<sha256>.json` with its manifest, and `imports/<fpi-id>.json`. The import id is a digest of the source digest and the reader version, so the same file read by the same reader is the same import and a second upload reuses it. Files are written atomically and never rewritten. One parse per person, two at once, four waiting; one request at a time per stored source, so two people sending the same file read it once. A failed import removes only what that attempt stored.
- **Routes** (`floor_plan_imports.py`): POST the DXF as the raw body (25 MiB, counted while streaming; the name in a percent-encoded `X-Floor-Plan-Name` header), GET the record and manifest, the geometry, the original as an attachment, and POST an alignment (computed, never saved). Every route checks the layout first; an import id alone grants nothing.
- **Record** (`floor_plan_references.py`): `extensions.facilityFloorPlanReferences` v1, one underlay per layout, closed fields only; it carries the import id, which must equal the import of its source digest by its reader version. The operations `upsert_floor_plan_reference` / `delete_floor_plan_reference` are in the kernel, validation, the authoring schema and proposals, and are not direct-applicable, so a Sage change to an underlay is always reviewed. A layout that adds or repoints an underlay must name a drawing stored for that site: checked on create, save, prepare and at commit.

### FP1b (Plan view)

- **Panel** (`static/facility_layout_floor_plan.js`): Floor Plan (DXF) in the ribbon's Walls / Floors menu (in More when the ribbon is narrow). Import shows a draft that changes nothing until Add to plan; adding, aligning, scaling, layer visibility, strength and removal are each one undoable edit, and like every layout edit they are kept by Save. Closing the panel drops a draft, a pick in progress and the answer to anything still being read. Layers that draw nothing (0, Defpoints, unused standards) are not listed. "Show the drawing" hides it for now without changing the layout.
- **Units and alignment.** A declared unit is used and confirmed. Without one the panel asks for the unit, or a known length: two picks on the drawing and the real length set the scale (calibrated). Align by two points takes two drawing points and where they belong on the plan; with a confirmed unit the server holds the scale (a rigid fit, `metersPerDrawingUnit` in the request) and reports how far the picks disagree with it, otherwise the picks set the scale too. Drawing picks snap to the nearest vertex of a shown layer within 12 px; plan picks follow the plan's grid snap.
- **Drawing** (`facility_layout_editor.js`): one `<path>` per layer and up to 3,000 labels, built once per drawing and layer set and placed by a single SVG matrix, between the floor surfaces and the zones (zones are translucent, so tracing needs no extra mode). The ink follows the theme (slate on light, light slate on dark). Pick markers and the snap ring stay the same size on screen while zooming.
- **Reader not installed.** A missing ezdxf now answers 503 `reader_unavailable` with that reason instead of "stopped unexpectedly", and the worker drops its job folder from `sys.path`.
- **Picks own the plan while they run.** A zone tool is set aside and given back; tools with their own panel (Aisle, Floor marking, Motion path) and light areas must finish first; any tool chosen (button, key, panel) ends the picks, Escape ends them first in the Plan view, leaving the Plan view ends them, and a double click on the last point never reaches the tool given back.
- **Checks.** `tests/test_facility_layout_floor_plan.js` (the panel, the shared alignment cases, snapping against a full search), the editor and transport checks, and a browser run of the whole flow against the clone (`Documents/InspectorPro-FloorPlan/tools/fp_browser_check.py`, 50 checks after the review rounds: placements measured from the outline path's on-screen box, undo and redo, save and reload, a unitless drawing scaled by a measured length, picks against tools, keys and views).

### FP2 (walls, rooms and the outline from the drawing)

- **Roles.** Each layer of the underlay says what it shows: drawing only (the default), walls as center lines or as both faces, the building outline, room outlines, room names, columns (listed for a later step), doors (FP3), or ignore. A role is one undoable edit kept with the underlay; nothing is read from layer names.
- **Converter** (`floor_plan_conversion.py`, pure; its module notes give the geometry rules). It reads the stored drawing placed by the saved alignment and roles, and the saved layout, and lists every candidate wall, room and outline with a state (new, already there, edited since, waiting, refused, left out) and the reason, what stays as drawing and why, and the native operations for the new ones (outer walls, then interior walls, then zones). Ids are digests of the import and the geometry (FP3 dropped the converter version from them), so converting again finds what is there; existing walls and zones are never changed, and the outer walls are replaced only when the user says so. Heights are never guessed: walls and outer walls wait for theirs, while thicknesses and the outline chosen apply before it. Limits: 128 interior walls on the plan, 500 operations, 128 outline corners, 256 zone corners; anything off the plan's rectangle is refused, and without a saved plan size everything waits.
- **Route.** `POST .../floor-plan-imports/{id}/conversion` with `{baseRevision, settings, stage}`. `candidates` lists and stores nothing. `proposal` stages the change as a layout proposal with an origin (conversion id; source, geometry, alignment, layers and settings digests; converter version) and keeps the conversion's record under `conversions/`. The proposal is never direct-applicable, and every prepare checks its origin against the saved underlay and the stored record. Moving the drawing or changing its roles saves a new revision, so a staged change is then refused as 409 `revision_conflict` and the drawing is converted again; a lost or altered record is `floor_plan_conversion_missing`, a lost drawing `floor_plan_artifact_missing`, another converter version or a drawing that is not the saved underlay 409 `floor_plan_conversion_stale`. A drawing whose unit is not confirmed is refused (422 `floor_plan_unit_unconfirmed`, since it would be drawn at a guessed size), and so is staging nothing (422 `floor_plan_conversion_nothing_to_add`).
- **Panel.** A Walls and rooms section for a saved underlay once a layer has a wall, room or outline role, the layout is saved and the unit is set. It asks for what those roles need (wall height, the thickness for center lines or the thickest wall drawn as faces, the outer walls' height and thickness, the zone type rooms become). Find walls and rooms lists the candidates (the first 300) with their states and reasons, and what stays as drawing. A box leaves a candidate out, a choice picks which outline is the building, a room can take its own zone type, and Replace the outer walls appears when the plan has some. A field changed marks the list as older than it; Review the change stages exactly the list on show and shows it on the plan, where Approve applies it and Dismiss leaves the layout as it was, and the panel says which happened.
- **Review summary.** The layout proposal's change summary counts walls too ("Changes: new outer walls, 1 new wall, 1 new zone.").
- **Checks.** `tests/test_facility_floor_plan_conversion.py` (hand-worked walls, rooms and outline from the factory drawing, every refusal and limit), `tests/test_facility_floor_plan_review.py` (the route, the proposal and its origin, stale and refused cases, applied through the approval routes), the panel's checks, the workspace's summary check, and the browser run (73 checks): from a reset layout, Plant 3 (meters) aligned by two picks, its layers given roles, listed, a wall left out, reviewed and dismissed, then reviewed and approved, the server's layout checked, and a second conversion finding it all there.

### FP3 (doors; columns wait for a decision)

- **Doors in walls.** A swing on a door layer (an arc, or the curved stretch of a polyline, turning 60 to 120 degrees about its hinge) hinged at one jamb of a break 0.5 to 4 m wide between two pieces of one wall, and shut against the other jamb, joins the pieces into one wall with a native opening there; interior openings are full height. Two half-width swings hinged at both jambs are a double door, and swings drawn on both sides of one jamb are one door that swings both ways. Swings that disagree about a break, or one swing that fits two breaks, leave the door unclear: it is listed as not added and the break stays. Only the opening is converted: the leaf and its swing are not modelled, so nothing claims door clearance.
- **Doors in the outer walls.** An unbroken outline has no jambs to confirm a door, so a swing hinged on an edge and shut along it is a door only with its leaf drawn from the hinge. It becomes an opening `{edge, startMeters, endMeters, heightMeters}` and waits for the outer doors' height (the wall closes above the door). A swing without its leaf stays as drawing, with that reason.
- **Rows.** Each door is a candidate (`dr-fp-...`) with its kind, width, place and the wall or outer walls it opens, and it takes that wall's state. Leaving a door out keeps its break (or leaves its opening out); leaving its wall out takes the door with it. On door layers, swings that fit nothing, outer swings without a leaf and any other lines stay as drawing, each with its reason.
- **Ids and version.** Candidate ids are digests of the import and the geometry, a wall's openings included, so a later converter still finds what an earlier one added. The converter version (now `fp-convert-3`) still binds a staged change.
- **Columns** stay listed as drawing until their representation is chosen: a small native columns extension, or catalog shapes.
- **Panel.** The Doors role is no longer marked "later". The list counts and lists doors with the wall they open, and the Outer door height field shows when a layer has the building outline and one has doors.
- **Checks.** `tests/test_facility_floor_plan_conversion.py` adds hand-worked doors: hinged at either jamb and opening to either side, a door drawn as one polyline, double and two-way doors, swings that disagree, a swing that fits two breaks, a door or its wall left out, what stays as drawing and why, and outer doors with and without their leaf and height, in either entity order. The factory's door now joins its partition into one wall with an opening 4 to 5.2 m along it, there and in the route checks. The panel checks cover the door rows and the outer door height. The browser run's conversion step is updated for the joined partition and a door left out, but it has not been run yet.

### Converter review (fp-convert-3)

A read-only review of FP2, FP3 and the Sage tools found the following; each fix has a test.

- **Jambs and end lines.** With a large thickest-wall setting, the two jamb lines of a doorway are parallel and close enough to pair: that "wall" filled the doorway, the pieces joined across it and the door was lost. A wall's end line also paired with the face of a cross wall just beyond it, leaving that face paired on both sides and the cross wall refused as ambiguous. A line now closes a pair's end when it is not parallel to the pair and its two ends are ends of the pair's two lines. Two lines that each close another wall are the jambs of an opening and never pair; a pair one of whose lines closes another wall, and that is no longer than it is wide, is dropped too (the short sides of a box drawn closed, or an end line and a wall beyond it). A box drawn closed is one wall along its longer sides. "No longer than wide" allows only rounding for a side of a closed box (the pair's lines and two parallel lines closing its ends make a closed loop, whether or not those two pair: a small box's short sides may overlap too little to), so a pier 1 mm longer than wide is still one wall along its longer sides, and 5 mm for an end line and a wall beyond it. Known limit: an end line more than 5 mm longer than its gap to a cross wall beyond (a 0.2 m wall stopping 0.1 m short of one) still pairs with that wall's face, and the gap becomes a short wall; the review shows it, and Sage or the user removes it.
- **Bounded work.** Grids keep a line in the cells along it, not in every cell of its box, so a long diagonal line costs its length: a 50 km line converts in under a second, where its box alone was about 800 million cells. Every cell and neighbor visited counts toward 6 million per conversion. Dense drawings (stacked copies, hatching on a wall layer) are refused in under 4 s as `floor_plan_conversion_too_large`, which also covers more than 20,000 wall pieces, 5,000 outlines, or 20,000 door swings and lines. The 200 m x 120 m stress drawing spends about 71,000 and the densest test (2,700 face lines) about 920,000. Face lines pair nearest first on each side, a loop drops its straight points in one pass (it was quadratic), and the outline's door search looks only at nearby edges and is skipped for an outline with more corners than the outer walls take.
- **Outer doors.** A door drawn twice, or swinging both ways (two swings from one hinge on either side of the edge), gave two doors with one id and overlapping openings, which the outer walls refused. It is now one door; swings that overlap without matching stay drawing (`door_overlap`).
- **Errors and records.** A drawing too large to convert answers 422 `floor_plan_conversion_too_large` with the reason, to the panel and to Sage (it was a 500, and `codex_tool_failed` for Sage). Changes larger than one review holds (600 KB) block the conversion (`changes_too_large`) instead of failing at staging. Staging checks the right to propose before it writes, and removes a record it wrote when the proposal is not made; a record already stored is kept, since an earlier proposal may be bound to it.
- **Smaller rules.** An outline choice that names none of the outlines counts as no choice, so they wait to be chosen. A room holds only the rooms inside it that can still be added, or that wait on rooms inside them, since only those can be left out. A room around zones already on the plan says so (`holds_zones`), and one outside the plan says that. A wall far off the plan is "outside the plan" rather than a coordinate error, and the duplicate message no longer says "outline" for walls and rooms.

### Sage tools (section 9)

- **Reach.** Sage reads only the drawing that is the bound saved layout's underlay, through its import: no artifact id, path or URL comes from the model, and uploading stays in the app. Without an underlay each tool says how the user adds one.
- **Reads** (`codex_runtime/floor_plan_tools.py`, no edits). `inspect_floor_plan_import`: file name, unit (declared, confirmed or not), placement, the layers that draw something with their roles and counts, bounds on the plan, warnings, and a page of one layer's entities (points in drawing units and their box on the plan, text up to 200 characters). `align_floor_plan_import`: the panel's fit from user points (a confirmed unit holds its scale; an unconfirmed one takes it from the points; scale or metersPerDrawingUnit when the user states one), with how far each point lands. `plan_floor_plan_conversion`: the route's candidate list, compact (40 rows of each kind, reasons and messages once, what stays as drawing). Drawing text is marked as data. Each read that has something to stage keeps it as a package for the turn.
- **Staging.** `preview_floor_plan_import` (edit gateway only) takes a packageId or layerRoles. An alignment or role change is one `upsert_floor_plan_reference`, built by the server (package limits, not the model's batch size); a conversion goes through the route's own staging, so it carries its origin and record. Both are staged in preview mode, so the app opens the review even in Apply Directly mode. Floor-plan packages are kept apart from planned-design packages: `preview_planned_design` cannot stage a conversion without its origin. Packages belong to the turn; the gateway refuses every call once the layout moves on.
- **Instructions.** Sage reads the drawing first, suggests roles from layer names and contents, never guesses a unit, point, height or zone type, says what will be added, what waits and what stays as drawing, and replaces outer walls only when asked. The read-only pilot gets the reads and the data rule.
- **Checks.** `tests/test_codex_floor_plan_tools.py`: the tools published where they belong, no drawing, the reads on the factory drawing, a fitted placement and new layer roles reviewed and applied, an unconfirmed unit fitted from the points, the conversion planned, staged with its origin, approved and found there again, packages refused across turns and revisions, a change staged in Apply Directly mode that still opens a review, and a drawing too large to convert named as such.
