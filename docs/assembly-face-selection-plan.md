# Pick a face of a part, for a finish or a sign, in the Assembly tab

## Why

The user, 2026-10-26: "I thought because solidcraft was open source we could see if its code on face selection
could be implemented in inspectorpro. this way we can select any face to give any color or logo more precisely."

Today a finish covers a whole part, and a sign goes on a side of a part (front, top ...) where the view finds a
spot. Neither can say "the top plate of the platform" or "the outer face of this arm".

## What SolidCraft does (read 2026-10-26)

SolidCraft (github.com/tangency-labs/solidcraft, Apache-2.0, Rust with its own wgpu renderer):

- **Every drawn triangle remembers its CAD face.** Tessellating a B-rep body writes each triangle's face index
  (`tri_face`). A click casts a ray, takes the nearest triangle and reads its face (`crates/ui-egui/src/view_pick.rs`).
- **A BVH per mesh** makes picks fast (`pick_index.rs`). We already ship the JavaScript equivalent,
  `three-mesh-bvh` 0.5.23.
- **Hover highlights the face before the click** ("preselect"), and a second click cycles through faces stacked
  under the pointer ("select other").
- **A plain mesh has no faces.** An STL or 3MF imported into SolidCraft gets face 0 on every triangle. Its own
  `docs/formats/3mf-face-tags.md`: "A tessellated body loses its faces". SolidCraft therefore writes the face index
  into its 3MF export.
- **A face kept across edits** uses history names (`docs/face-attachments.md`); a face that can't be found again
  is reported lost, never swapped for a nearby one.

Nothing there can be copied as code: the language, renderer and B-rep kernel are not ours, and three.js already
gives the triangle under the pointer (`hit.faceIndex`). We borrow the method: face numbers kept on the triangles,
hover then click, lost faces reported.

## What exists (read 2026-10-26)

- **Our GLBs lose the faces at export.** Assembly and library-machine GLBs are written by
  `SolidWorksExtractor/Services/GlbExporter.cs` (generator "SolidWorksExtractor"; same file in the test copy and
  the real repo).
  - It already tessellates face by face (`IFace2.GetTessTriangles` over `body.GetFirstFace/GetNextFace`), and each
    face's triangles land as one unbroken run in the part's index buffer.
  - It then writes one mesh per component with POSITION, NORMAL and indices only: no extras, no record of the runs.
  - MMLE-50D: 206 meshes, 511,580 triangles. ABB IRB 6650: 13 meshes, 19,686 triangles.
- **The sources are here.** SOLIDWORKS 2024 is installed, and VS 2022 Build Tools (MSBuild) can build the
  extractor.
  - MMLE-50D: `OneDrive\Desktop\additional library item\MMLE-50D\User Library-MMLE-50D.SLDASM`.
  - Robot: `OneDrive\Desktop\machine library\User Library-6-axis robot abb6650_320_125\...SLDASM`.
  - `tools/publish_local_machine_library.py --asset <id> --force` rebuilds one library machine. It starts
    SOLIDWORKS when asked and closes only the instances it started.
- **Both machines live in the machine library** (`generated/industrial_assets/local_library/<asset>/`). That
  library holds 514 assets: 363 exported from SOLIDWORKS (177 STEP-type files, 149 parts, 37 assemblies), 134
  shapes we generate, and a few others.
- **What is tied to the exact files.**
  - The MMLE-50D knowledge package pins `extracted.json`, not the GLB. So a GLB-only re-export keeps its documents
    bound.
  - The thumbnail evidence and the catalog record the GLB's hash.
  - A library machine's source revision changes with its GLB, so the Specification Sheet picture becomes stale and
    is captured again.
  - Neither machine has a motion package. One that did would pin its GLB and refuse a new file.
- **The Assembly view** loads GLBs with our own minimal r128 loader (`THREE.GLTFLoader = class` in
  `index.html`), which reads POSITION, NORMAL and indices.
  - `_assemblyPickSurfaceAt` already turns a click into part, side and point, but ignores `hit.faceIndex`.
  - Finishes are drawn per mesh (`_assemblyFinishForMesh`, `_applyAssemblyMeshBaseMaterial`, which already loops
    over material lists).
- **The appearance store** (`assembly_appearance.py`) keeps a whole-machine finish, part finishes by part name,
  the scene, and signs.
  - A sign has part, side, across/up, width and rotation, plus an optional anchor (mesh, point, normal) from a
    drop or pick.
  - The viewer reports part bounds and sign results (`write_geometry`); Sage reads them.
- **The Assembly library pane** puts finishes on the whole machine or the selected parts, and signs on a side.
  Both can be dragged onto the 3D view or placed with "Pick on the machine".

## Decisions

Defaults I would take; the ones marked **(needs your answer)** change what gets built.

1. **Faces come from the exporter.** Each mesh's primitive gets `extras.inspectorpro.faces`:
   - its runs as [first triangle, triangle count, surface kind, feature];
   - the kind (plane, cylinder, cone, sphere, torus, other) from `IFace2.GetSurface()`;
   - the feature that made the face (`IFace2.GetFeature()`, e.g. "Cut-Extrude2"), named once per mesh.

   Geometry, node names and triangle order stay exactly as today, so existing finishes, signs and anchors keep
   working. Other glTF readers (the Facility r184 viewer) ignore extras.
2. **Which models get re-exported (needs your answer).**
   - Now: MMLE-50D and the ABB robot, GLB only, into a scratch folder first.
   - Each is checked against today's file: the same nodes, positions and indices byte for byte, and runs that
     cover every triangle once.
   - Only then is the GLB replaced, with its hashes updated as the library tool does, and `extracted.json` left
     alone.
   - The other 361 SOLIDWORKS-made machines can follow later in one batch run. That takes SOLIDWORKS for a long
     while, so it is your call.
3. **SOLIDWORKS (needs your answer).** The export needs SOLIDWORKS running. I can start it myself, run the export
   and close only the instance I started, at a time you're not using it. Or you open it and tell me.
4. **A face finish is on every copy of the part,** as part finishes are today (the three SHAFT TUBEs together). One
   copy alone would need occurrence keys; that can come later.
5. **Models without face data** get faces by smooth patches, worked out in the browser the first time a part is
   hovered, and marked approximate:
   - the patch grows across edges that turn less than 30 degrees;
   - this covers shapes we generate and GLBs not yet re-exported;
   - measured: the robot's largest part has 4,680 triangles in 154 patches;
   - the limit: a face that blends smoothly into the next (a rounded edge into a flat top) merges with it.
6. **Edges (needs your answer).** The CAD edges are where one face's run meets another's, so they come almost free.
   But colours and logos don't need them. I'd leave edge picking out unless you want it (a stripe along an edge,
   say).
7. **A face is kept by number plus a fingerprint:** its area, centre and direction, measured on the part's first
   copy.
   - On load, the number is checked against the fingerprint, then the part's faces are searched for a match.
   - When nothing matches, the finish or sign is not drawn and the view reports `face_missing`, as `no_fit` today.
   - A nearby face is never used instead.
8. **Picking: the literal minimum.**
   - The pane gains a target "Faces" and a "Pick faces" button.
   - While it is on, hovering tints the face under the pointer, a click selects it, Shift-click adds, and Esc ends.
   - Selected faces stay tinted while the pane shows them. No labels or outlines beyond that.
   - Dropping a finish or sign while picking faces lands it on the face under the pointer.
9. **Sage works with faces too.**
   - The viewer measures each part's faces once per model revision and reports them compactly: number, kind, area,
     centre, direction, side, feature. That is at most 40 per part, the largest first.
   - Sage can therefore pick "the largest flat face facing up on the platform".
   - The user's selected faces are reported too, so "make these faces red" works.
   - Sage says when it chose a face by size or direction rather than from the selection.
10. **Facility layouts are out of scope.** The re-exported robot carries face data there too, but Facility's own
    store and r184 viewer are left as they are.

## Phases

- **F0 - exporter and re-export.**
  - `MeshData` gains face runs. `ExtractLocalPartMesh` and `ExtractComponentMesh` record them with the kind and
    feature; `TransformLocalMeshForComponent` keeps them; `BuildGltfJson` writes them. Build with MSBuild.
  - Re-export MMLE-50D and the robot to a scratch folder (decisions 2 and 3).
  - A Python check, kept as a test on a small fixture: identical geometry to today's file, runs tiling every
    triangle once.
  - Back up, then replace the two GLBs in the test copy's library.
- **F1 - faces in the view.**
  - The loader reads the runs into `geometry.userData`. A face is found from `hit.faceIndex` by binary search, and
    the smooth-patch fallback (decision 5) is cached per geometry.
  - "Pick faces" in the pane: hover tint, click, Shift-click, Esc. A face's triangles are drawn as an index subset
    sharing the part's vertices. BVH raycasts on large parts while picking.
  - Node tests: lookup, the fallback on a box with a rounded edge and on a cylinder, hover and selection.
- **F2 - face finishes.**
  - The store gains face finishes [{part, face {number, fingerprint}, finish}], in the revision, validated.
  - Precedence: face over part over whole machine.
  - The view draws them as geometry groups on the part's own mesh, one material per finished face. Highlights,
    exploded views, transparency and the Specification Sheet capture then treat them like the part. I'll check the
    paths that assume one material per mesh.
  - Fingerprint matching and `face_missing` in the geometry report.
  - The pane applies a finish to the selected faces.
  - Tests.
- **F3 - signs on a face.**
  - A sign row gains an optional face. The fit check then requires every ray to land on that face's triangles.
    The search starts at the face's centre, and the existing centring and sizes down to 3 cm apply.
  - A drop or pick while picking faces stores the face.
  - Test: on two faces of a diagonal bar, the sign stays on the chosen one even when the other is larger.
- **F4 - Sage.**
  - The face report (decision 9) and the selection go into the geometry document. `inspect_assembly` says what is
    selected.
  - A new read tool `list_part_faces` (part, optional side, kind, minimum area).
  - `set_assembly_appearance` gains the target "faces"; `place_assembly_signs` gains a face.
  - Instructions, then tests and one live Codex turn (free, plan quota).
- **F5 - live test, port, desktop.**
  - MMLE-50D: "paint the top face of the platform yellow and its sides black; put the pinch-point sign on the
    outer face of the scissor arm".
  - Robot: one face picked by hand, then "put the logo on the selected face".
  - Port with the usual backup and byte check: code, exporter, the two re-exported GLBs and their hash records.
    Then restart the desktop app.
- **F6 - later, if wanted:** the batch re-export of the library (decision 2), edges (decision 6), one copy of a
  part at a time (decision 4).

## Status

- 2026-10-26: plan written. Waiting for answers on decisions 2 (which models), 3 (SOLIDWORKS) and 6 (edges).
- 2026-10-26: the user answered: re-export MMLE-50D, the robot and two more models; start SOLIDWORKS as needed;
  edges (for smart dimensions in the viewport) are not pressing. F0-F5 built in the test copy (0664cf1, fef678e,
  76d3f82) and live-tested; then ported to the real repo.

## As built

- **F0.** `GlbExporter.cs` writes `primitive.extras.inspectorpro = {faceVersion: 1, faceKinds, faceFeatures,
  faces: [[firstTriangle, count, kind, feature, radius]]}`; each triangle has its own three vertices in order.
  Re-exported: MMLE-50D (206 meshes, 3697 faces), ABB IRB 6650 (13, 2333), the red forklift (11, 681) and the
  FANUC 14tes2 (55, 2037). The robot, forklift and FANUC have byte-identical geometry; on MMLE-50D SOLIDWORKS
  retessellated 21 fastener and channel meshes (same bounds, triangle counts within 0.5%; no sign was anchored to
  them). Each library entry's `thumbnail-evidence.json` and the operations manual's source register
  (SRC-CAD-MMLE-GLB) carry the new hashes. `tests/test_glb_face_runs.py` checks that the runs tile every triangle.
- **F1.** A face is found from the hit's vertex numbers, not `faceIndex`: three-mesh-bvh reorders the index in
  place. Models without CAD faces get smooth patches (vertices welded, neighbours within 30 degrees); a mesh over
  400,000 triangles is one face. Tints are subsets of the part's index sharing its vertices, in a group beside the
  model, hidden in captures.
- **F2.** A finished mesh gets its own geometry (the same vertices) with the index regrouped: unfinished triangles
  first, then one group and one material per finished face. Display styles, X-ray and the Specification Sheet
  capture work with the material list. A face is kept across exports by its fingerprint (area, centre, average
  normal in the mesh's own coordinates); one not found again is `face_missing`, never a neighbour.
- **F3.** A sign with a face searches up to 32 spots on that face, centre first, and every ray must land on it.
- **F4.** `list_part_faces` (the view reports each part's 40 largest faces once per load), target `faces` in
  `set_assembly_appearance`, `face` in `place_assembly_signs` (side optional), the selection in `inspect_assembly`.
- **F5 live (Sage on Codex, plan quota, no money).**
  - MMLE-50D, the top face picked by hand: "Paint the selected face safety orange and the four side faces of that
    same platform part matte black. Then put the pinch-point sign on the outer face of one of the scissor arms."
    7 steps in 45 s, applied directly: five face finishes drawn; W024 on the outer arm's front face, 3.9 cm whole.
    The Specification Sheet's picture shows them.
  - Robot, a 0.11 m2 flat face of the arm picked by hand: "Put the InspectorPro logo on the selected face." 4 steps
    in 24 s; the logo is drawn 10.5 cm on that face.
  - Forklift: two faces picked (Shift-click), matte black from the pane. FANUC: all 55 meshes read their faces.
  - Found live: the browser showed the GLB cached from before the export, without its faces. `/api/assembly-model`
    now answers no-cache with an ETag (304 while unchanged) and the page's loader asks with
    `fetch(cache: 'no-cache')`, so models cached earlier, the desktop's too, are checked again.
- **Left for F6:** edges and smart dimensions (the face runs keep each face's feature and radius for them), the
  library-wide re-export, one copy of a part at a time.

## Changed after F6: selecting as SOLIDWORKS does (2026-10-26)

The user: picking a face took too many steps (open the pane, press Pick faces, then pick). Now it works by
default on any machine in the Assembly view, as in SOLIDWORKS:

- With no tool on, the face or edge under the pointer is highlighted in orange: a face by its edges and a light
  tint, an edge (within 6 px) by itself. A click selects it in blue; Ctrl- or Shift-click adds or removes one; a
  click on empty space or Esc clears. A drag still orbits.
- Edges are drawn as bands a few pixels wide with the depth test (a small shader: GL lines are one pixel wide
  here), so an edge behind the part stays hidden. Highlights still wanted are kept between redraws.
- The pane's "Pick faces" mode is gone. The pane names the selected faces and has Clear faces; selecting faces
  makes "Selected faces" the finish's target. A finish dropped on a selected face goes on all the selected faces,
  a sign on that face; dropped elsewhere it lands on the part as before. "Pick on the machine" still works, and
  the view does not select while it waits.
- Smart Dimension takes one or two selected faces or edges as its first picks (the selection is used up), and
  highlights its picks and hover the same way. Selected edges are not reported to Sage.
- Test copy 9338ae9; port 26 (backup `Documents\InspectorPro-Backups\2026-10-26-before-select-on-hover-port`).
- Then a part-name tooltip, as SOLIDWORKS shows: after half a second at rest over the machine (no tool on), the
  part's description and number sit beside the pointer; it goes when the pointer moves, leaves, presses or zooms.
  Test copy 5b7ecf6; port 27 (backup `Documents\InspectorPro-Backups\2026-10-26-before-part-tooltip-port`).
- Desktop app, MMLE-50D: hovering the deck's top face drew its orange outline and tint and, after the pause,
  "Top (1030071)"; a click selected it in blue, Ctrl-click added an edge, Smart Dimension started with both as its
  picks, and an empty click and Esc each cleared the selection.
