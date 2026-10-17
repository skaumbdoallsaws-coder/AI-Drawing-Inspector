# Facility Decals

First general authoring slice, 2026-10-13. This is not a gym-specific command.

## User Workflow

Facility Layout > Edit > Decals opens a modal wall-elevation preview. Choose a
PNG/JPEG, a measured wall face and an uninterrupted section, then set the maximum
artwork region dimensions, its distance from the wall start, and its bottom
height. Alpha-margin trimming is enabled initially. Image proportions are always
preserved; dimensions describe a contain-fit region, not independent stretching.

Apply is one ordinary session gesture. Undo/Redo, edit, delete, explicit Save,
reload, and stale-dialog rejection use the existing layout/session machinery.
Deleting a placed wall removes its new decals in the same operation; removing
the perimeter removes perimeter-bound decals. Undo restores both. Existing wall
paint, openings, equipment, and legacy artwork are not migrated or changed.

## Contract

- Operation: `set_decals`, with `decals: {version: 1, artworks: [...]}`.
- Extension: `layout.extensions.facilityDecals`.
- Each record contains `artworkId`, `label`, `imagePath`, `uv`, `target`, `region`,
  and `coverage`. Region and UV coordinates are normalized to the host wall and
  image. Region coordinates have their origin at the wall's bottom/start.
- Targets are `{edge, side}` for generated perimeter walls, or
  `{placementId, face}` for exact catalogued wall occurrences. Placed faces are
  `positive_x`, `negative_x`, `positive_z`, and `negative_z`.
- The server checks scope, finite bounds, door intersections, unique IDs, the
  combined 48-image budget, and the placed target's wall metadata/measured AABB.
- Imports use `POST /api/facility-layouts/{site}/{layout}/decal-images` with raw
  PNG/JPEG bytes. Import requires `layout.edit` and the `manual_edit` capability.
- The importer decodes/re-encodes PNG, removes imported metadata, honors EXIF
  orientation, limits input to 10 MB / 20 megapixels, and caps output dimensions
  at 4096 pixels. Animated and fully transparent images are rejected.
- Images live in `<facility layout repository>/decal-images/<scope hash>/`, not
  under the source tree. Content hashes deduplicate images. Atomic writes and
  native long-path handling support Windows data roots.
- `GET /api/facility-decal-images/{site}/{hash}.png` requires `layout.read` and
  resolves only the authenticated tenant/site's store. Layouts contain no local
  filesystem paths. Image import alone does not save or dirty a layout.

## Limits

This slice supports planar wall faces, not arbitrary CAD faces, curved surfaces,
floors, or editable text. The selector manages new `facilityDecals` records;
script-authored legacy `artworks`/`fittedArtworks` remain rendered and unchanged.
Old artwork embedded in a GLB remains part of that asset. Automatic image cleanup
is intentionally absent because Undo and saved revisions may still reference it.

Wall Lettering, Component Materials, Interior Walls, Floor Surfaces, and Replace
Asset remain separate follow-up tools. No additional Sage write tools are exposed
by this change. The installed desktop snapshot is not promoted automatically.

## Verification

`tools/verify_facility_decals_browser.py <new output directory>` runs the actual
workspace, session, HTTP API, and Three renderer against an isolated store.
`--serve --port <unused port>` exposes the isolated preview for manual review.
It never saves Private Gym or Factory 02.

Evidence: `outputs/decals-browser-20261013-07/report.json` and sibling screenshots.
Passed checks include PNG import, proportional preview, invalid-size rejection,
one-gesture history, Undo/Redo, edit/delete, explicit Save/reload, failed-image
handling, stale-dialog rejection, and the dialog fitting at 1440x900 and 390x844.
Separate isolated-renderer checks verify visible logo pixels, framing and camera
movement at both sizes. The existing full workspace clips its viewport at phone
width; full mobile workspace acceptance is not claimed. Read-only compatibility
probes resolved 254 wall-face/section
choices in Private Gym and 188 in Factory 02; saved files remained byte-identical.
Those two probes validate geometry, not full-layout visual acceptance.

Targeted Python suite: 113 passed. Node suites passed for decals, existing fitted
art/walls, sessions (63 checks), workspace (100), Three (114), transport (30), app
(6), and ribbon reachability. The service/API suite passed 30 additional tests,
excluding one pre-existing failure in
`test_http_operation_preview_is_read_only_and_matches_put`: its comparison includes
the preview-only `revision` field. The same preview/apply difference exists in
HEAD; this change does not alter that response contract.
