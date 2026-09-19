# Facility Layout Manual Tools: Code Reference

Recorded: 2026-09-12

Scope: all 33 entries in `FACILITY_LAYOUT_RIBBON_COMMANDS`, plus the Asset Library and Properties controls used to build the manual 2D layout. This is a source-navigation reference, not a new implementation, exhaustive API schema, or proof that every command was used in the original build. Source line numbers reflect this inspection and can drift; function and command names are the durable lookup keys.

## 1. How a Tool Is Defined

The ribbon entry is only the visible command definition. Most tools have four layers:

```text
Ribbon: command ID, icon, label, tooltip, optional shortcut
    -> Workspace.executeCommand(command)
    -> dialog or pointer interaction gathers inputs
    -> geometry helper and/or session method
    -> unsaved operation preview and gesture history
    -> explicit Save through the configured persistence transport
```

Selection and camera commands do not follow the mutation path. Proposal generation, navigation authoring, and proposal-specific Undo/Save have specialized paths.

### Shared source map

| Responsibility | Source and lookup |
| --- | --- |
| Ribbon definitions | [index.html](../static/index.html), `FACILITY_LAYOUT_RIBBON_COMMANDS`, line 42700 vicinity |
| Command dispatch | [facility_layout_workspace.js](../static/facility_layout_workspace.js), `Workspace.prototype.executeCommand`, line 15049 vicinity |
| Enabled/disabled UI state | Same workspace file, `_renderToolbarState`, line 15983 |
| Pointer tool mode | Same workspace file, `_setToolMode`, line 15323 |
| Pattern inputs to geometry builders | Same workspace file, `_buildPatternResult`, line 8040 |
| Precision positioning application | Same workspace file, `_applyPrecisionPositioning`, line 11211 |
| Pattern geometry | [facility_layout_patterns.js](../static/facility_layout_patterns.js), exported as `InspectorProFacilityPatterns` |
| Draft gestures and history | [facility_layout_session.js](../static/facility_layout_session.js), `commitGesture`, line 1613 |
| Pattern results to operations | Same session file, `applyPattern`, line 3866 |
| Server operation kernel | [operations.py](../ai_inspector/facility_layout/operations.py), `apply_facility_layout_operations`, line 2179 |
| Server layout validation | [validate.py](../ai_inspector/facility_layout/validate.py), `validate_layout`, line 1079 |
| Service persistence | [service.py](../ai_inspector/facility_layout/service.py), `save_layout`, line 1648 |

The workspace checks capabilities and exposes command state. `commitGesture` also requires a loaded, idle session and rejects ordinary edits while a generated draft or design proposal requires review. It builds a candidate gesture journal, asks the configured preview path to evaluate it, and installs the returned draft. A click is not automatically a save.

## 2. Selection and Creation

Implementation names in the tables below are from the workspace or session files linked above unless another file is explicitly named. Inputs describe the principal contract, not every optional field.

| Tool / command ID | Inputs and behavior | Implementation entry point |
| --- | --- | --- |
| Select / `select` | Pointer selection and multi-selection; moving selected layout objects is a separate edit gesture. | `executeCommand` -> `_setToolMode`; ribbon shortcut `V`. |
| Pan / `pan` | Pointer movement changes the viewport, not object positions. | `executeCommand` -> `_setToolMode`; ribbon shortcut `H`. |
| Rectangle Zone / `rectangle-zone` | Start/end points and zone options. Constructs a rectangular boundary with label, zone type, elevation, anchors, evidence, and extensions. | Session `createRectangleZone`, line 4046 -> `add_zone`. |
| Polygon Zone / `polygon-zone` | Boundary points and zone options. Creates a polygonal zone rather than a rectangle. | Session `createPolygonZone`, line 4187 -> `add_zone`. |
| Bulk Zones / `bulk-zones` | Multiple named rectangular zone requests. Session inputs include `minX`, `minZ`, positive `width` and `depth`, plus zone options. | Workspace `_applyBulkZones`, line 6759 -> session `createZones`, line 4062. All requests are submitted as one gesture. |
| Aisle / `aisle` | Named route geometry and corridor settings, including width and direction. Drawing an aisle is not automatically a vehicle swept-volume validation. | Workspace `openAisleDialog`, line 7162; session `createAisle`, line 4342. |
| Floor Marking / `floor-marking` | Select a marking type and author its placement/style. Used for arrows, crosswalks, parking/staging boxes, and keep-clear areas. | Workspace `openFloorMarkingPalette`, line 5172; session `createFloorMarking`, line 4313. Ribbon shortcut `M`. |
| Motion Path / `motion-path` | Existing actor, drawn points, loop/direction/constraint mode, snap references, and locked segments; vehicle profile identity/revision when applicable. Authors navigation intent, not an extra actor. | Workspace `openNavigationDialog`, line 7344, and `_applyNavigationPath`, line 7580 -> navigation runtime `buildManualPathIntent`. Ribbon shortcut `Shift+P`. |

Motion Path is included because it is now in the ribbon, but it was not part of the original static-factory build. Its `complete_override` branch requests deterministic manual-path validation; authoring intent alone must not be described as accepted playback or safety evidence.

## 3. Basic Editing

| Tool / command ID | Inputs and behavior | Implementation entry point |
| --- | --- | --- |
| Rotate 90 / `rotate` | Selected objects; rotate by the session's 90-degree operation. | `executeCommand` -> session `rotateSelected90`, line 3271. Ribbon shortcut `R`. |
| Duplicate / `duplicate` | Selected objects and the workspace default duplication offset. Cell/support copying has additional session logic; it is not just a raw object clone. | `executeCommand` -> session `duplicateSelected`, line 3542. Ribbon shortcut `Ctrl+D`. |
| Delete / `delete` | Selected objects, with cell, stack, and supported-object expansion. Supported placements are ordered by attachment depth for deletion. | Session `deleteSelected`, line 3988 -> type-specific delete operations. Ribbon shortcut `Delete`. |
| Clear All / `clear-all` | Confirmation dialog, then clears authored layout content. This is distinct from deleting only the selection. | Workspace `openClearAllDialog`; session `clearLayout`, line 3981 -> `clear_layout_contents`. |
| Lock / `lock` | Toggles selected placements and floor markings between locked and manual position mode. Dispatcher unlocks when all selected movable records are already locked. | Session `setSelectedLocked`, line 4027 vicinity -> `set_position_mode` / `edit_floor_marking`. Ribbon shortcut `L`. |

Lock is an editing constraint, not an engineering approval or safety classification.

## 4. Precise Positioning

All five commands enter `openPrecisionDialog` and are applied through `_applyPrecisionPositioning`. These helpers are defined in [facility_layout_workspace.js](../static/facility_layout_workspace.js), not in a separate precision module.

| Tool / command ID | Principal inputs | Calculation and draft action |
| --- | --- | --- |
| Align / `align` | Selected placement IDs, alignment mode, anchor ID. | `buildAlignmentUpdates`, line 1229 -> `session.movePlacements`. Aligns selected equipment using the chosen edge/center relationship. |
| Distribute / `distribute` | Selected placements, axis, distribution method, gap. | `buildDistributionUpdates`, line 1275 -> `session.movePlacements`. Computes positioning updates for the selected distribution rule. |
| Relative / `relative` | Reference placement, moving placements, relation, distance, alignment. | `buildRelativePositionUpdates`, line 1367 -> `session.movePlacements`. The reference ID is excluded from moving IDs. |
| Distance / `distance` | Reference ID, moving ID, distance mode, requested distance. | `buildDistanceUpdate`, line 1462 -> `session.movePlacements`. Sets the requested relationship rather than merely displaying a measurement. |
| Offset / `offset` | X/Z displacement and whether to create copies. | `_applyPrecisionPositioning` constructs `{x, y: 0, z}`; calls `duplicatePlacements` for copies or `moveSelected` for movement. |

The panel displays distances in the selected plan unit. Inspect the input conversion path before calling geometry helpers directly; do not pass a displayed feet value as though it were the internal distance value.

## 5. Patterns and Cell Arrangement

These commands share `openPatternDialog`, `_buildPatternResult`, pattern preview, and `_applyPattern`. The session receives a result containing copies, moves, and/or relationships and converts it into draft operations.

All builder functions below are in [facility_layout_patterns.js](../static/facility_layout_patterns.js).

| Tool / command ID | Principal inputs | Builder and result |
| --- | --- | --- |
| Linear Pattern / `linear-pattern` | Seed selection, total count, pitch, direction/custom angle. | `buildLinearPattern`, line 520. Translates copies of the seed along a direction vector; original counts as the first instance. |
| Circular Pattern / `circular-pattern` | Seed, center X/Z, count, sweep angle, rotate-with-pattern flag. | `buildCircularPattern`, line 561. Places copies around the center; handles full-circle spacing separately from partial sweeps. |
| Perimeter / `perimeter-pattern` | Seed, rectangle/square shape, width count, depth count, clear gap, angle. | `buildRectangularPerimeter`, line 932. Builds a repeated rectangular perimeter, as used for robot guarding. |
| Cell Layout / `cell-layout` | Selected items, shape, width/depth, gap, rows, orientation rule, angle, invert-U flag. | `buildCellLayout`, line 1400. Computes an arrangement of existing items. It does not itself create a named persistent cell group. |
| Stack / `vertical-stack` | Seed, stack count, vertical gap. | `buildVerticalStack`, line 619. Builds vertical stacking output using the applicable geometry and relationship logic. |
| On Surface / `surface-stack` | Support placement ID, surface ID, side, support gap, item gap, inset. | `buildSurfaceStack`, line 690. Places selected items relative to a support surface and produces attachment-related output. |
| Mirror / `mirror` | Seed and two points defining the mirror axis. | `buildMirror`, line 1071. Produces mirrored arrangement output; inspect the builder for object-specific transformation semantics rather than assuming a mirrored CAD mesh. |
| Swap / `swap` | Layout, catalog, and selected IDs. | `buildSwap`, line 1133. Builds position-exchange output for selected objects/cells. No separate pitch or repeat count. |

### Supported Cell Layout shapes

`CELL_SHAPES` currently declares: `line`, `l`, `u`, `grid`, `parallel`, `serpentine`, `loop`, `spine`, `herringbone`, and `cluster`.

The builder requires at least two non-zone items and rejects locked seed items. It derives arrangement dimensions from selection geometry and the requested gap, checks usable width/depth, and computes positions and orientation. This is an arrangement recipe, not a process optimizer.

### Pattern limits and relationships

The pattern module declares `MAX_PATTERN_COUNT = 50` and `MAX_PATTERN_OBJECTS = 240`. These are this module's limits, not a 240-placement limit on the whole factory or a claim about every server operation budget.

`_buildPatternResult` also rejects certain nested patterns involving completed vertical stacks. Supported objects and copied cells require relationship remapping; `session.applyPattern` owns the conversion and provenance, including command, seed IDs, parameters, and cell numbering.

### Actual Linear Pattern calculation

The key code in `buildLinearPattern` is:

```javascript
for (let instance = 1; instance < count; instance += 1) {
    const target = {
        x: bounds.center.x + direction.x * pitch * instance,
        z: bounds.center.z + direction.z * pitch * instance,
    };
    seed.forEach(function (item) {
        copies.push(transformedCopy(
            item, bounds.center, target, 0, instance
        ));
    });
}
```

Every seed member gets the same displacement, preserving the group's internal arrangement. Four instances at 5 m pitch have offsets 0, 5, 10, and 15 m. Pitch is not automatically an edge-to-edge clearance.

## 6. Persistent Cell Grouping

| Tool / command ID | Inputs and behavior | Implementation entry point |
| --- | --- | --- |
| Create Cell / `create-cell-group` | Selection-derived envelope, family/base name, prefix, starting number, digit padding, envelope padding, and optional functional interfaces. | Workspace `_applyCellGroup`, line 7022 -> session `createCellGroup`, line 4097. Creates a workcell zone with `extensions.cellGroup`, geometric membership, auto-numbering, and authored interface sides. |
| Ungroup / `ungroup-cell` | Selected manufacturing-cell zone ID. | Workspace `_ungroupSelectedCell` -> session `ungroupCell`, line 4173 vicinity. Deletes the group zone, retaining the equipment. |

Cell Layout arranges items. Create Cell records the grouping. Linear Pattern can then repeat the completed cell. These are three distinct operations, not three names for one operation.

## 7. History, Proposals, and Persistence

| Tool / command ID | Behavior | Implementation entry point |
| --- | --- | --- |
| Undo / `undo` | Ordinary edits recompute the journal at the previous cursor. Design proposals and generated drafts have specialized restoration branches. | Session `undo`, line 4387; design branch `undoDesignProposal`. Ribbon shortcut `Ctrl+Z`. |
| Redo / `redo` | Ordinary history recomputation at the next cursor. Do not assume proposal recovery is equivalent to ordinary history. | Session `redo`, line 4430. Ribbon shortcut `Ctrl+Y`. |
| Fit / `fit` | Fits the facility in the viewport; no layout mutation. | Dispatcher calls controller `fitFacility`, falling back to `fit`. Ribbon shortcut `F`. |
| Auto Arrange / `auto-arrange` | Builds a proposal request from current state/catalog and submits it for review. Requires `fullLayoutProposals`; it is not an immediate Save. | Workspace `buildAutoArrangeRequest`, line 1698; dispatcher calls `session.requestLayoutProposal`. |
| Save / `save` | Explicit persistence, with special transports and eligibility/revision handling for design and generation drafts. A stale local restore requires rebinding. | Session `save`, line 4434; server service `save_layout`. Ribbon shortcut `Ctrl+S`. |

Undo is not universally "restore the last saved layout." Its behavior depends on the current draft type and journal. Consult the actual branch before extending it.

## 8. Supporting Controls Used During Manual Building

These are workflow controls, not additional entries in the 33-command ribbon registry.

| Control | Definition / implementation |
| --- | --- |
| Asset Library / `assets` | `executeCommand('assets')` opens/closes the browser. `openAssetBrowser`, line 11769; `_addAssetBrowserSelection`, line 11836; `buildAssetBatchPlacementRequests`, line 1553. Selected catalog records and quantities become placement requests. |
| Properties | `_renderProperties`, line 15674; `_handlePropertyChange`, line 15367. Selected-entity fields govern position, orientation, dimensions, labels, styling, or purpose as applicable. Not every entity exposes every property. |
| Plan / 3D tabs | `_setViewMode` changes presentation and coordinates adapter lifecycle. It is not an asset-creation command. |
| Grid, units, and plan navigation | Workspace plan preferences and `_handlePlanNavigationClick`, line 13620. These support precise authoring and viewing; they are not manufacturing authority. |

## 9. What This Means for Sage

The ribbon is a user interface, not automatically a Sage tool schema. A registered label does not prove the agent can invoke the underlying behavior. Agent exposure, authority checks, request contracts, and returned evidence need their own verified integration.

For future agent integration, reuse existing session/engine operations and preserve selection identity, draft revision, units, locks, relationships, and preview/save boundaries. Do not create a second pattern algorithm merely to expose the same behavior in chat.

Geometric repetition, grouping, a successfully authored route, and saved data do not by themselves establish obstacle-free travel, equipment capacity, guarding adequacy, compliance, manufacturing order, or optimality. Those require the applicable independent validators and evidence.

## 10. Verification Scope

This reference was assembled by reading ribbon definitions, command dispatch, pattern/precision builders, and relevant session methods. No application code or layout was modified. No behavioral test suite or browser acceptance run was performed for this documentation task.

Historical usage is recorded separately in [manual build directions](../../facility-layout-manual-build-directions.md). This reference intentionally includes available tools that may not have been used in that historical build.
