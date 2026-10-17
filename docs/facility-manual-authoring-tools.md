# Manual Facility Authoring Tools

Implemented in the source checkout on 2026-10-13, following Decals. These are
general layout tools, not Private Gym or Factory 02 authoring recipes. No saved
customer layouts are migrated or edited by installing the tools.

## Ribbon

- Edit > Appearance: Object Appearance and Component Materials.
- Edit > Replace Asset.
- Surfaces > Wall Art: Decals and Wall Lettering.
- Surfaces > Walls / Floors: Interior Walls and Floor Surfaces.
- At narrower ribbon widths, these commands remain in More.

All tools use the current layout session, backend operation preview, one undoable
gesture per Apply, and explicit Save. Dialogs reject changes after the opening
layout revision or selection becomes stale. The normal `--application` desktop
entry serves this checkout. The older restricted rendering diagnostic uses an
isolated source snapshot; that requirement does not apply to normal application
mode.

## Wall Lettering

Reuses `set_decals` and the tenant/site-scoped decal image store. A lettering
record adds bounded editable `lettering` metadata: text, reference, font,
alignment, and color. The browser creates a transparent PNG; the existing image
import endpoint validates and content-addresses it. Text is not sent to a model
provider. Editing retains semantic text and regenerates the texture.

Arial and Georgia are the initial font choices. Text is limited to 1,000
characters / 16 explicit lines; the smaller reference line to 160 characters.
Existing artwork is preserved. Lettering shares the 48 combined artwork budget
and wall-region/doorway checks with Decals. This is flat graphic lettering, not
extruded text or a physically metallic surface.

## Component Materials

`set_component_materials` stores `componentMaterials` on one placement, bound
to that placement's exact asset revision and loaded overview/detail
representation. Mesh traversal plus material-slot keys distinguish even unnamed
meshes and multi-material meshes. Controls provide color, roughness, metalness,
and per-component reset. Selection highlights the component bounds.

Overrides are applied to owned material clones. Edited occurrences leave shared
instancing groups; unaffected copies can remain instanced. Display settings and
whole-object tint do not overwrite component finishes. Saved finishes retain
their source visual representation to avoid applying slots to a different LOD.

This is exported mesh/material editing, not SolidWorks B-rep face selection.
Merged models expose only the components actually present in the export. Mesh
names are shown when available; the software does not guess which mesh is a
seat or frame. The server validates bounded slot identifiers and finish values;
it does not parse GLBs to verify each slot exists.

## Interior Walls

`set_interior_walls` creates/edit/deletes `facilityInteriorWalls`. Each named
partition has stable identity, X/Z endpoints, base elevation, height, thickness,
color, and full-height openings. A plan preview supports endpoint clicks and
precise numeric inputs. The backend compiles physical panels and verifies that
their geometry matches the authored settings.

The same panels feed plan rendering, 3D geometry, authoritative shell features,
and walkthrough collision volumes. Partitions must fit inside the plan and rest
on a flat supporting floor. This first tool supports straight partitions, not
curved walls, windows, lintels, or structural design ratings.

Decals and lettering can target either partition side, split around openings.
Resizing retains normalized artwork regions; conflicting new door openings are
rejected. Deleting a wall removes its bound new decals in the same gesture.

## Floor Surfaces

`set_floor_surfaces` creates/edit/deletes `facilityFloorSurfaces`: named polygon
finishes with color, roughness, and concrete/rubber/turf/paving/wood/solid styles.
The UI accepts a rectangle, a selected zone boundary snapshot, or an existing
surface boundary. Patterns are deterministic local textures, not downloads.

These are visual finishes over existing floors. They do not alter
`facilityGround`, elevations, ramps, support references, or equipment placement.
The backend rejects overlapping finishes, out-of-plan regions, unsupported
elevations, slopes, and gaps. Curved/sloping finish authoring is not included.
Structural walls and floor finishes remain when equipment contents are cleared;
their own tools provide deletion.

## Replace Asset

`replace_asset` replaces one unlinked occurrence with an exact library asset
revision while retaining placement ID, transform, label, and grouping identity.
The dialog searches measured library models, compares local footprint bounds
and dimensions, and performs a read-only placement check before enabling Apply.
Apply revalidates against current authoritative spatial/routing constraints.

Whole-object color can be retained or reset. Old component overrides are removed
because mesh slots belong to the old definition. The tool refuses replacements
with attached children, snap relationships, route/process bindings, movement
references, or bound wall artwork. It does not silently disconnect or remap
machine-specific interfaces. A placement check is not certification of process,
accessibility, structural, or regulatory suitability.

## Verification

- Focused Python tests cover schema validation, atomic operations, geometry
  preservation, image permissions, linked replacements, and invalid placements.
- JavaScript regression suites cover the shared session, workspace, renderer,
  transport, ribbon reachability, wall targets, and mesh/material helpers.
- `tools/verify_facility_decals_browser.py` tests actual image/lettering dialogs,
  API persistence, Undo/Redo, stale requests, and loaded 3D textures.
- `tools/verify_facility_authoring_browser.py` tests the other four tools through
  real browser controls and the actual local API using isolated synthetic asset
  fixtures. Screenshots and pixel checks verify component color and floor finish.
- Dialogs are checked at desktop and phone widths. The pre-existing full
  workspace phone-width clipping is not resolved by this work.
- These browser checks do not constitute a packaged-installer acceptance pass
  or a visual audit of every imported CAD model in the private library.

Final browser evidence is in `outputs/authoring-browser-20261013-11/report.json`
and `outputs/lettering-browser-20261013-02/report.json`. Both passed with zero
page errors. Desktop (1440 px) and narrow (390 px) render probes verified visible
textures and interactive cameras; dialog checks cover fixed actions, no
horizontal overflow, cancellation, and stale selection rejection. The saved
Gym and Factory files were checked byte-for-byte unchanged.

## Desktop Promotion - 2026-10-13

The normal Electron 44.3.0 application passed
`desktop/tools/facility-authoring-entry.cjs` against an isolated copy of Private
Gym. Evidence: `.runtime/facility-authoring-native-20261013-01/evidence/authoring-native.json`.
All six tools opened from visible ribbon commands. Five dialogs also passed
compact-window overflow-menu checks. A real commercial workout bench exposed
five material slots. All seven served authoring modules matched checkout
SHA-256 hashes. Cancel preserved the draft and both saved layout copies; zero
Save calls were made. Backend shutdown was graceful with resources closed.

This is native ribbon/dialog and real-model loading acceptance; mutation,
Undo/Redo, and save/reload coverage remains in the isolated browser/API suites.
The installed shortcut now explicitly selects `desktop/node_modules/electron/dist/electron.exe`
with its previous target backed up. Its existing application profile and
Private Gym startup selection were preserved. No packaged installer was built.

The pre-existing API regression
`test_http_operation_preview_is_read_only_and_matches_put` compares a preview
result containing `revision` to an apply result without that extra key. It is
tracked separately and excluded from this focused regression run.
