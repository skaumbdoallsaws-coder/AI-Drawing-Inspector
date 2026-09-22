# Facility Layout Structure Tree Plan

Date: 2026-09-22 (revision 1)

Status: proposed, not started. No code has been written for this plan.

Working name: FT0-FT5

## 1. Objective

Give the Facility Layout workflow a docked structure tree, in the manner of a
SOLIDWORKS FeatureManager, so the layout can be read and selected as a
hierarchy rather than only as geometry on a canvas.

```text
the saved or draft layout
  -> zones and placements are already in state.layout
  -> membership is derived geometrically, smallest containing zone wins
  -> the tree renders that derivation, lazily, per branch
  -> clicking a row calls the existing session selection API
  -> the session broadcast rebuilds the derivation on the next change
```

The tree adds **no new authority over the layout**. It does not decide where
anything belongs; it reports where geometry already places it. Every row it
shows is a zone or placement that exists in the layout, and every selection it
makes goes through `session.select` / `session.selectMany` exactly as a canvas
click does.

This work is orthogonal to the generation gates in
`sage-research-layout-implementation-report.md`. It requires only a layout; it
does not require generation, routing, or motion.

## 2. What Already Exists

Verified in the working tree on 2026-09-22.

**A vacated left slot, which is where the tree belongs.** `.left-panel` is a
240px column that the app **deliberately collapses on entering this workflow**:

```js
trainingState.type = 'facility_layout';
...
window._toggleLeftPanel();
_desktopAutoCollapsedPartPanel = true;   // restored when leaving
```

So the slot exists, has a known width, already has a toggle and a restore path,
and is empty precisely while Facility Layout is open. The tree docks here.

**The right edge is Sage's.** The agent panel is a flex sibling of the viewport
on the right. Putting a structure tree there would make the tree and the
assistant compete for one edge, and would break the convention every CAD tool
shares - SOLIDWORKS, Fusion and Inventor all place the feature tree on the left.
The reference screenshot for this request has it on the left too.

**A two-column shell, for the properties rail.** `.ip-flw-shell` is
`grid-template-columns: minmax(360px, 1fr) minmax(210px, 270px)`, with
`.ip-flw-properties` in the second column; the integrated workflow collapses it
to one and floats the properties pane at `top: 44px; right: 14px`. That rail
stays as it is. The tree is a left-side peer of it, not a second tenant.

**A properties pane with collapse states.** `.ip-flw-properties` supports
`[hidden]` and `[data-collapsed="true"]` - the pattern the tree pane should
reuse for its own collapse.

**A single state choke point.** `this.session.subscribe(this._handleSessionState)`
receives every layout change: zone creation, placement, deletion, undo, and
Sage-driven edits. Nothing needs per-command wiring.

**Commit-not-frame semantics for drags.** Pointer drags update
`_setPlacementMovePreview` locally and only reach the session through
`session.movePlacements` on release. The subscription therefore fires once per
completed operation.

**A selection API.** `Workspace.prototype.handleViewSelection` calls
`this.session.select(id, {additive, toggle})`, and marquee selection calls
`this.session.selectMany(ids, {additive})`. A tree row needs no new path.

**A tree precedent.** `process_map_editor.js` implements
`renderStructureTree` and `_renderStructureOccurrence`: recursive rows, carets,
selection, drag. The pattern transfers. The code does not - it is bound to
`ProcessMapEditor` and its occurrence model, and should be read, not imported.

**A panel-building precedent.** `Workspace.prototype._buildLayerPanel` shows
the established shape for a titled panel with rows inside this workspace.

## 3. The Derivation, And Why It Is The Whole Problem

**Zone membership is not stored.** Measured against the reference layout:

| Record | Fields | Membership link |
| --- | --- | --- |
| placement | assetDefinitionRevision, assetId, metadata, placementId, positionMode, snapRelationship, transform | none |
| zone | anchors, boundary, evidence, extensions, floorElevation, label, zoneId, zoneType | none |

There is no `zoneId` on a placement and no placement list on a zone. The
relationship exists only as geometry, and the tree must compute it the same way
`movement_inventory.py` already does: point in polygon, smallest containing
zone wins.

Three consequences follow, and they are the actual design content of this work.

### 3.1 Zones nest

Reference layout: 45 zones at three depths - 6 top level, 27 at depth 1, 12 at
depth 2. An asset inside `Inpection Station Q01` is also inside
`Inspection + Packing + Finished goods`. Smallest-containing is the rule; it
must be stated in the UI, not implied, because both answers are true.

The tree is therefore four levels, not the three a flat sketch suggests:

```text
Facility Layout
  Machining Hall                     (6 of these)
    Manufacturing Cell A01           (27 at this depth)
      Inpection Station Q01          (12 at this depth)
        placements
```

### 3.2 Membership is positional, so it changes silently

Dragging a bench from Assembly into Machining reparents its row with no
confirmation. That is correct for a derived hierarchy and will still feel like
the tree moved something by itself. The tree must not imply it authored the
move.

### 3.3 An asset can belong to no zone

No constraint requires a placement to sit inside a zone, and the empty fixture
starts at zero of both. Building from empty, a user will place something before
its zone exists. Those placements need an explicit home in the tree or they
disappear from a view that claims to show the whole layout.

## 4. Product Boundary

### 4.1 The tree may claim

- These zones and placements exist in this layout at this revision.
- This placement's position currently falls inside this zone's boundary.
- This row corresponds to that entity; selecting it selects that entity.

### 4.2 The tree must never claim

- That membership is authored, approved, or process-meaningful. It is geometric
  containment and nothing else.
- That a zone's contents constitute a work cell, a station, a capacity, or an
  ownership boundary.
- That the tree is a source of truth. The layout is; the tree is a projection.
- That an empty zone is unused, or that an unzoned asset is misplaced.

### 4.3 Required refusals

- With no layout loaded, the pane shows an explicit empty state, not a blank
  panel.
- Where a placement falls in no zone, it appears under an explicit unzoned
  branch, never omitted and never guessed into the nearest zone.
- Where geometry is unreadable for a zone, that zone reports the failure in
  place rather than rendering as empty.

## 5. Performance

Measured on the reference layout: 827 placements against 45 zones, ray casting,
200 runs.

| Approach | Full rebuild |
| --- | --- |
| naive | 0.51 ms |
| bounding-box prefilter | **0.19 ms** |

A full rebuild is about 1% of a frame, and fires once per committed operation
rather than per pointer move. **This plan therefore specifies full recomputation
on every change and forbids incremental diffing**, which would add invalidation
bugs to buy time that is not needed.

Rendering, not derivation, is the cost that matters. Of 827 placements, 456 are
the same wire-mesh guard panel, and the busiest leaves hold 114 and 41. A raw
expand produces a wall of identical rows.

## 6. Architecture

```text
state.layout  ->  deriveStructure(layout)        pure, no DOM, unit testable
                    |
                    +-> { roots, byZone, unzoned, counts }
                    |
                  renderTree(model, expanded)    lazy: children built on expand
                    |
                  row click  ->  session.select(...)
                    |
                  session broadcast -> _handleSessionState -> derive again
```

`deriveStructure` takes a layout and returns a plain object. It touches no DOM,
holds no state, and is the only place containment is decided. It is testable
without a browser, which is what makes the rule in 3.1 reviewable.

## 7. Implementation Phases

### FT0 - Baseline And Fixtures

Record the current state before changing anything: reference layout counts,
nesting depths, the 0.19 ms measurement, and screenshots of the workflow with
no pane. Add an empty layout and a single-zone layout to the fixtures so the
empty and shallow cases are covered from the first commit.

Exit: baseline committed, no production file touched.

### FT1 - Derived Hierarchy Module

`deriveStructure(layout)` as a pure function, with the bounding-box prefilter.
Smallest-containing resolution, explicit unzoned collection, per-zone counts,
stable ordering that does not depend on object key order.

Exit: unit tests for nested zones, an asset in no zone, an asset on a boundary,
overlapping equal-area zones, an empty layout, and a layout with zones but no
placements. No DOM, no workspace changes.

### FT2 - Pane Shell And Read-Only Tree

Dock the pane in the left slot described in section 2, reusing the existing
`_toggleLeftPanel` collapse rather than adding a second mechanism. The workflow
currently auto-collapses that slot on entry; this phase changes that to host the
tree instead, and must leave `_desktopAutoCollapsedPartPanel` restoring the
drawing panel correctly when the user leaves Facility Layout.

Lazy expansion: a branch computes and renders its children the first time it
opens. Grouping of identical assets within a zone (`Wire Mesh Guard Panel x38`)
rather than one row each. Empty state and unzoned branch per section 4.3.

Exit: the tree renders the reference layout, expands and collapses, shows the
unzoned branch on a fixture that has one, and leaving the workflow restores the
drawing panel exactly as it does today. No selection yet.

### FT3 - Selection Binding

Row click calls `session.select`; ctrl-click is additive, matching
`handleViewSelection`. Selection arriving from the canvas highlights the
corresponding row and reveals its ancestors. One selection model, two views.

Exit: canvas-to-tree and tree-to-canvas selection agree in both directions,
including multi-select, verified against the reference layout.

### FT4 - Dynamic Behaviour

Rebuild on `_handleSessionState`. Preserve expansion state across rebuilds by
zone ID, not by row index. Verify the cases from section 3: create a zone around
existing assets and watch them reparent, delete a zone and watch its contents
move to unzoned, undo and confirm the tree follows.

Exit: build-from-empty exercised end to end - place assets, draw zones around
them, move one across a boundary, delete a zone, undo each step.

### FT5 - Evaluation And Promotion

Screenshots at the reference layout and at an empty layout. Confirm the pane
can be collapsed and that collapsing it returns the full viewport width.
Accessibility pass: the tree is a `tree` role with `treeitem` rows, keyboard
navigable, and the pane is reachable without a pointer.

Exit: promotion decision recorded with evidence, or the gap that blocks it.

## 8. Milestones

| Milestone | Delivers | Blocked by |
| --- | --- | --- |
| FT0 | baseline, fixtures | - |
| FT1 | pure derivation + tests | FT0 |
| FT2 | read-only tree in the rail | FT1 |
| FT3 | two-way selection | FT2 |
| FT4 | dynamic rebuild, expansion state | FT3 |
| FT5 | evidence and promotion | FT4 |

FT1 is independently valuable: `deriveStructure` is the function Sage would
need if zone contents are ever exposed as a tool result, whether or not the
pane ships.

## 9. What Not To Do

- **Do not add `zoneId` to placements.** Writing membership into the layout
  makes a derived fact authoritative, requires a revision-bound migration, and
  changes a schema that Sage tools and the navigation contract already read.
  The derivation is 0.19 ms; it does not need to be cached in the document.
- **Do not implement drag-to-reparent.** Dragging a row to another zone is an
  authoring operation requiring undo semantics and geometry changes, and it
  lands directly on gate 4 of the generation report, which covers Apply/Undo and
  shared ownership. Read-only navigation stays clear of it; this does not.
- **Do not build incremental updates.** See section 5.
- **Do not import the Process Map tree.** Read it; do not couple two workflows
  through a component that was written for occurrences.
- **Do not claim a new Sage capability.** Sage already has
  `inspect_facility_region` - "inspect one named zone by stable ID" - and
  already reasons zone by zone. The tree aligns the operator's mental model with
  the one Sage uses. That is worth having and is not a new power.
- **Do not let the tree write to the layout** in any phase of this plan.

## 10. Test Suites To Extend

- `tests/test_facility_layout_workspace.js` - pane construction, selection in
  both directions, rebuild on state change, destroy removing listeners.
- A new suite for `deriveStructure` - the six FT1 cases, no DOM required.
- `tests/test_facility_layout_p11_contracts.js` - only if the shell grid
  changes, since it asserts `grid-template-rows` on the root.

## 11. Sequencing Risk

**Against Codex.** The active task in
`task-generation-research-source-cards.md` touches `server.py`,
`generation_agent.py`, `chat_content.py` and `chat_rich_content.js`. This plan
touches `facility_layout_workspace.js` and its stylesheet. No file overlap. The
workspace file is 17,168 lines and mentions generation on 37 of them.

**The one real collision** is gate 4, "exact selected-proposal adoption using
shared ownership, history, Apply/Undo recovery". That work lands on selection
and history, which FT3 and FT4 also touch. Mitigation: FT3 only *calls* the
existing selection API and adds no new selection state. If gate 4 begins first,
FT3 and FT4 should wait; FT0 through FT2 are unaffected either way.

**Against the reference layout.** Nothing in this plan writes to a layout, so
the manual reference stays untouched by construction, not by discipline.
