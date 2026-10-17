# Facility Object Appearance

## Controls

Select placed equipment or wall objects in Plan, 3D, or the structure tree.
Open **Appearance** in the Edit ribbon group (or More when the ribbon is narrow).
The 3D toolbar also has an Object appearance button.

- Choose a preset swatch or custom color, then Apply.
- Multi-selection uses one history entry. Mixed colors are identified explicitly.
- The reset arrow selects the default finish; Apply commits the reset.
- Undo/Redo use the ordinary session journal. Save remains explicit.
- Geometry locks do not lock appearance. Preview proposals and unresolved drafts
  retain their existing editing restrictions.

## Contract

Optional placement field: `appearance: { color: "#rrggbb" }`.
The `set_appearance` operation accepts `placementIds` and `color`; null removes
the override. IDs and colors are validated before the atomic batch is adopted.
This is a per-placement finish, not a catalog or source-CAD material edit.
The operation leaves transforms, attachments, asset revisions and geometry unchanged.
Existing duplication preserves the override.

Plan footprints and 3D geometry consume the same saved color. Selection and
proposal highlighting remain transient. Instanced CAD uses independent instance
colors; cloned meshes use their own materials. Color-only changes reuse the
loaded 3D scene, including pending detail loads, rather than reloading all assets.

This tool colors placed objects, including the wall assets used by Factory 02.
It does not edit the ground, floor markings, zones, generated perimeter-wall
settings, individual CAD faces, textures, or the independent walkthrough avatar.
Existing zone/marking color controls remain separate.

## Verification

Focused backend tests cover atomic updates, validation, exact reset, revisions,
same-model isolation, locked geometry and duplication. Session tests cover
multi-selection, Undo/Redo and reset. Renderer tests cover per-instance color,
selection restoration, color-only reuse and delayed detail loading. Workspace
tests cover swatches, custom colors, mixed selection, stale selection and gates.

Native verification uses `desktop/tools/facility-appearance-entry.cjs` with a
copied Factory 02 store and separate application profile. The harness checks
the actual ribbon-to-session path, Reset, Undo/Redo, mixed selection, narrow
window bounds, isolated Save/reload, nonblank screenshots and live-file hashes.
Native results are recorded under `.runtime/facility-appearance/`.

### Recorded Result (2026-10-03)

- 301 JavaScript checks passed: renderer 99, workspace 100, session 63, Plan 39.
- Ribbon organization check passed with all 33 commands reachable.
- 96 Python tests passed across appearance, operations, schema and service.
- `native03/report.json` passed in the normal Electron application at 1440 x 900
  and 900 x 700 window sizes. All panel controls fit. Four screenshots were
  inspected, including two green rack instances beside unchanged gray peers and
  an independently colored white dock wall.
- Native Reset, multi-selection, Undo/Redo, stale-selection refusal and isolated
  Save/reload passed. The live layout hash remained
  `ddb1120745f382c756361841f9fe1739c261eb922ec5191464ccfa7fab31637e`.
- Owned Electron and backend processes exited cleanly, with confirmed resource
  cleanup and no cleanup errors.

The first harness launch lacked its required data directory; this was corrected
in the launcher. Native02 passed functional checks but visual inspection found
clipped swatches; native03 includes the panel fix and a contents-fit assertion.
The original evidence remains available. This is focused feature verification,
not a new whole-application release qualification.
