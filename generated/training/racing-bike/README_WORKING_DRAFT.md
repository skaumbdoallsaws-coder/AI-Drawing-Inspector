# Racing Bike Process Map

The current Racing Bike process map has been accepted as the approved baseline for the Training and Assembly-tab product-structure work.

The hierarchy uses four levels:

- Level 0: root assembly
- Level 1: 2 major build modules
- Level 2: 6 subassemblies
- Level 3: component leaves

The app still loads the working draft so future changes can be made without disturbing the frozen reference. The approved baseline is a separate JSON copy for comparison and rollback.

## Files

- `racing_bike_working_naming_draft.json` / `.csv`: current naming map to work from.
- `non_destructive_rename_plan.csv`: proposed file/part names; does not rename files.
- `racing_bike_process_map_working_draft.json`: current app-loaded product structure map.
- `racing_bike_process_map_approved_baseline.json`: frozen approved process-map baseline from 2026-05-31.
- `racing_bike_unique_items.json`: complete-assembly unique item inventory with quantity, thumbnail path, GLB path, and owning module/subassembly.
- `part_colored_iso/`: 47 component ISO thumbnails rendered from the part GLBs using the assembly-level `partColorMapping`.
- `part_iso_preview/`: cropped large isometric previews from the extractor; used by the click-to-expand popup for clearer shape reading.
- `assembly_glb/`: served full-assembly GLB used by the root-assembly popup.
- `part_colored_iso_manifest.json`: audit record for the thumbnail colors; source is `User Library-racing bike_assembly.json`.
- `assembly_reference/`: labeled full-assembly reference images used by the product-structure board.

## Review Flags To Verify

These parts remain flagged for future review, but the structure is accepted as the working baseline:

- RB-011
- RB-014
- RB-015
- RB-019
- RB-020
- RB-024
- RB-025
- RB-030
- RB-031
- RB-038
- RB-041
- RB-042
- RB-043

## Module Layout

- `internal_mechanical_assembly`
  - `swingarm_linkage`
  - `front_wheel_brake`
  - `rear_wheel_brake`
  - `exhaust_system`

- `bodywork_exterior_assembly`
  - `seat_tail`
  - `side_fairings`
