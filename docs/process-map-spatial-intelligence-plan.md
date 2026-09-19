# Process Map Spatial Intelligence Implementation Plan

Status: revision 8 - PHASE 8 ENGINEERING HARDENING IMPLEMENTED (2026-07-22).
Rollout: spatial capabilities remain default-off until the self-use soak gate is
reviewed.
Baseline: commit 96e678d (`feat: add process map select and pan modes`).
Scope: deterministic spatial awareness, placement, routing, and agent-assisted layout for the Process Map.

Approval boundary:

- Phases 0-3 are approved for implementation now.
- Phase 4 was explicitly approved after Phase 3 demonstrated the
  candidate-and-score approach and the routing dependency spike produced a
  written result.
- Phase 5 was explicitly approved and implemented after the Phase 4 checkpoint.
- Phase 7 was explicitly approved and implemented after the Phase 6 checkpoint.
- Phase 8 engineering hardening was explicitly approved and implemented after
  the Phase 7 checkpoint. Production default-on remains separately gated by a
  self-use soak and review of aggregate acceptance/dismissal metrics.
- This approval does not pre-authorize a production Node.js runtime dependency,
  ELK.js adoption, or full-map auto-arrangement.

Implementation checkpoint (2026-07-22):

- Phase 0 baseline captured: process-map backend 105/105, editor node harness
  50/50, and floating-surface harness 14/14.
- Phase 1 implemented: shared ASCII contract, Python and browser spatial
  runtimes, golden cross-runtime scene fixture, world/viewport conversion,
  canonical card/group/junction/port geometry, and non-visual editor delegation.
- Phase 1 post-change bars: process-map backend 118/118, editor 50/50, spatial
  browser harness 10/10, floating surface 14/14, and the pre-existing live
  Process Map smoke 111/111. A new live contract/runtime assertion is added to
  the next smoke count.
- Phase 2 implemented: deterministic overlap, clearance, card/wire,
  group-header, crossing, backward-flow, route, alignment, density, and open
  region diagnostics; a shared lightweight spatial index; sampled legacy
  Bezier geometry in Python and JavaScript; digest version 3 with a bounded
  trusted `spatial` section; and a read-only `Analyze Layout` ribbon command.
- Layout turns expose no provider tool and any emitted action is dropped by the
  runtime policy. Required-part questions retain their separate temporary tree
  highlight exception. Browser-supplied scenes and diagnostics are discarded.
- Phase 2 post-change bars: process-map backend 125/125, editor 50/50, spatial
  browser harness 15/15, floating surface 14/14, agent/routing/semantic
  regression 131 passed with 1 expected skip, chat streaming 17/17, and live
  Process Map smoke 113/113 with no page errors.
- Phase 3 implemented deterministic incremental placement, three ranked ghost
  card alternatives, exact-plan regeneration before acceptance, one-step
  accept/undo behavior, card locks, visible-region preference, and incident-wire
  collision checks. The reported anchorless performance risk was removed by a
  bounded region-occupancy pass (48.5 ms median on a synthetic 250-node,
  400-edge map), and floating-toolbar ownership is now explicit rather than
  inferred from transient placement state.
- Phase 4 implemented layoutVersion 3, additive route modes, a deterministic
  Python/JavaScript orthogonal router, obstacle fingerprints, nonmutating route
  previews, stale-plan regeneration, automatic route invalidation, manual-route
  repair warnings, shared visible/hit/label/junction/marquee/Fit geometry, and a
  feature-flagged legacy fallback. The ELK.js spike is recorded as a production
  NO-GO in `docs/process-map-router-spike.md`; no runtime dependency was added.
- Phase 4 post-change bars: process-map backend 150/150, editor 59/59, spatial
  browser harness 36/36, floating surface 14/14, and live Process Map smoke
  136/136 with no page errors. The legacy Training asset suite remains at its
  known 15 passed / 8 pre-existing asset failures.
- Phase 5 implemented deterministic spatialization of evidence-grounded
  suggestions without changing their semantic identities. Current connection
  suggestions receive exact orthogonal ghost routes, and supported unplaced
  semantic targets receive a ghost next-card plus ghost wire. Spatial proposal
  IDs are revision-, obstacle-, engine-, and policy-bound, then regenerated in
  the browser immediately before acceptance; stale geometry fails closed while
  semantic dismissal remains stable.
- Required-part results now support an optional organized batch preview. The
  preview is transient, does not dirty the map or history, places cards without
  overlap, revalidates the complete plan before acceptance, and commits every
  card as one mutation and one undo step.
- Phase 5 post-change bars: process-map backend 156/156, editor 61/61, spatial
  browser harness 39/39, floating surface 14/14, and live Process Map smoke
  145/145 with no page errors. The legacy Training asset suite remains at its
  known 15 passed / 8 pre-existing asset failures.
- Phase 6 implemented outcome-only Sage tools for spatial inspection, card
  placement/movement, and connection routing. Provider schemas accept stable
  semantic IDs and intent only; recursive geometry-key rejection prevents the
  model from supplying positions, routes, waypoints, viewport transforms, or
  approval claims.
- Deterministic proposals now use the existing Builder propose, exact-diff
  approval, CAS apply, idempotency, and receipt chain. Approval and apply both
  re-plan against the saved revision and bind the candidate/route identity,
  spatial versions, obstacle fingerprints, diff hash, user/session, and
  idempotency key. A separate
  `INSPECTORPRO_PROCESS_MAP_AGENT_LAYOUT_WRITE` flag disables spatial writes
  without disabling inspection or previews.
- The browser renders exact transient card/wire ghosts, supports Approve and
  Dismiss without dirtying the map, reports completion only from the execution
  receipt, and records one accepted proposal as one undo step. A capability
  initialization race found by Playwright was removed by resolving capability
  flags before mounting the editor. A preview merge defect and an empty-state
  overlap found by focused tests and screenshot review were also corrected.
- Phase 6 post-change bars: process-map backend 164/164, editor 62/62, spatial
  browser harness 39/39, floating surface 14/14, and live Process Map smoke
  150/150 with no page errors. The legacy Training asset suite remains at its
  known 15 passed / 8 pre-existing asset failures.
- Phase 7 implemented an explicit `Clean Map` command with context-sensitive
  `Clean Selection` and `Clean Group` scopes. Every cleanup is a transient
  card-and-wire preview first; Apply commits the exact regenerated plan as one
  mutation and one undo step, while Dismiss leaves map state and history
  byte-identical.
- The deterministic Python/JavaScript planner uses stable precedence ranks,
  grid snapping, bounded collision search, lexicographic quality metrics, and
  byte-parity golden fixtures. It preserves authored group frames, treats
  junctions as authored routing anchors, never moves locked cards, refreshes
  only automatic orthogonal routes, and rejects plans that add a hard spatial
  violation or fail to improve the configured metric.
- Preview acceptance is revision/fingerprint bound and regenerates the plan
  immediately before commit. Any intervening map change fails closed. ELK was
  not adopted because the Phase 4 production-runtime spike was a NO-GO; the
  shipped arrangement path adds no Node.js backend dependency.
- Phase 7 post-change bars: process-map backend 172/172, editor 65/65,
  spatial browser harness 43/43, floating surface 14/14, and live Process Map
  smoke 165/165 with no page errors. The smoke covers full-map, selection, and
  group previews; exact lock preservation; one-step apply/undo; dismiss;
  stale-plan rejection; and a visual preview artifact. The legacy Training
  asset suite remains at its known 15 passed / 8 pre-existing asset failures.
- Phase 8 hardened the spatial runtime for contract-maximum maps. Diagnostics
  now use precomputed bounded segments and segment-level spatial indexes;
  routing likewise indexes eligible edge segments before exact crossing tests.
  On the deterministic 250-node/400-edge fixture, isolated measurements are
  92.8 ms median compile-and-diagnose, 25.3 ms median / 31.0 ms p95 for three
  placement candidates, and 43.1 ms median for one affected reroute. All are
  below the binding 150/400/1000/100 ms targets.
- Full-map cleanup planning now runs in a dedicated browser Worker. Planning is
  cancellable, superseded workers are terminated, stale results cannot land,
  and the synchronous path remains only as a guarded compatibility fallback.
- The editor exposes polite live-status announcements, `aria-busy` planning
  state, keyboard-accessible cancellation, and reduced-motion-safe previews.
  Explicit light and dark artifacts are stored as
  `runtime_logs/process_flow_phase8_cleanup_preview_light.png` and
  `runtime_logs/process_flow_phase8_cleanup_preview_dark.png`.
- Spatial analysis has its own rollout flag in addition to the existing
  placement, routing, and agent-write flags. Every flag-off path fails closed
  without disabling the base Process Map editor.
- Aggregate spatial telemetry uses schema version 4 and accepts only bounded
  operation/outcome enums, version identifiers, counts, latency/quality
  metrics, rejection-code counts, and redacted fallback reasons. Labels,
  notes, coordinates, routes, waypoints, and arbitrary payload fields are not
  accepted.
- Phase 8 post-change bars: process-map backend 174/174, editor 65/65, spatial
  browser harness 43/43, floating surface 14/14, and live Process Map smoke
  169/169 with no page errors. The legacy Training asset suite remains at its
  known 15 passed / 8 pre-existing asset failures.
- The engineering exit gate is met. Default-on is intentionally not claimed:
  it follows a real self-use soak and review of aggregate acceptance,
  alternative, dismissal, cancellation, stale, and failure outcomes.

## 1. Objective

Give the Process Map the same kind of spatial awareness already proven by the
Drawing Map, adapted to an infinite, pannable graph canvas.

The completed system must know:

- The stable world-coordinate rectangle occupied by every card and group.
- The exact anchors and directions of every input and output port.
- The routed geometry and bounds of every wire.
- Which regions are occupied, crowded, available, or outside the current view.
- Where a proposed next card can be placed without overlapping existing content.
- Which port orientation and order produce the cleanest supported connection.
- Whether a proposed wire intersects a card, crosses another wire, travels
  backward against the map flow, or creates unnecessary bends.

This spatial knowledge supports three progressively more capable workflows:

1. Diagnose the layout of an existing map.
2. Suggest a clean position and route for the next card or connection.
3. Let Sage and Builder propose larger layout edits without giving the model
   direct authority over raw coordinates or persisted assets.

## 2. Non-goals

This work does not:

- Replace semantic process reasoning with geometry. A clean wire is not evidence
  that two process steps should be connected.
- Let an LLM freely emit arbitrary coordinates, paths, or file changes.
- Automatically rearrange a user-authored map when a card is added.
- Treat visual wire crossings as graph junctions. Junctions remain explicit
  topology created by the existing junction operation.
- Persist browser-screen pixels in the process-map asset.
- Make full-map auto-layout the first deliverable. Incremental placement and
  routing ship first because they preserve the user's mental map.
- Infer engineering sequence from proximity alone.

## 3. Current-state inventory

### 3.1 Persisted map geometry

The schema-v3 placement map already persists:

- `canvasNodes[].position` in map/world coordinates.
- Node kind, port orientation, and port order.
- `canvasGroups[].position` and `canvasGroups[].size`.
- `canvasEdges[]` topology, kind, endpoints, and `logicalConnectionId`.
- Explicit junction nodes.

At the plan baseline, `PROCESS_MAP_LAYOUT_VERSION` was 2. The Phase 4
checkpoint above records its migration to version 3 and the additive persisted
routing contract.

### 3.2 Editor geometry

At the plan baseline, `static/process_map_editor.js` provided:

- `layeredLayout()` for initial positions and restoration of saved positions.
- `graphBounds()` for Fit and world sizing.
- `portAnchor()` and `portDirection()` for node connection points.
- `bezierPath()` for all normal, ghost, pending, and junction wire rendering.
- One transient transform `{x, y, scale}` in `applyTransform()`.
- `clientToWorld()` for screen-to-world conversion.
- Group frames, junctions, drag/drop, pan/zoom, marquee selection, undo/redo,
  semantic ghost edges, and a revision-aware save path.

The current route is recomputed from endpoints on every render. It is not an
obstacle-aware route and is not represented in the asset.

### 3.3 Existing intelligence and write boundaries

- `digest.py` builds a trusted, server-side, revision-bound graph digest capped
  at 3,500 estimated tokens. It describes graph semantics, not detailed layout.
- `suggest.py` produces deterministic semantic connection suggestions with
  evidence, stable IDs, cycle checks, and dismissals. It does not place cards.
- `operations.py` already supports placement, movement, port layout, connect,
  junction, group, reference, and deletion operations.
- `builder.py` already enforces propose, validate, exact-diff approval, CAS
  apply, idempotency, and receipts.

These boundaries remain. Spatial intelligence extends them; it does not create
a second mutation path.

### 3.4 Drawing Map precedent

The Drawing Map's `_placeBalloon()` is the relevant design precedent:

- It separates the stable placement anchor from the precise leader endpoint.
- It generates multiple candidates instead of trusting one position.
- It scores collision clearance most heavily.
- It penalizes occupied view regions and edge proximity.
- It uses deterministic tie-breaking and a bounded nudge fallback.
- It computes placements before rendering.

The Process Map should reuse this candidate-and-score architecture, not copy the
fixed-sheet pixel implementation. Unlike a drawing page, the Process Map is an
unbounded world with movable obstacles and routed graph edges.

## 4. Binding architecture

### 4.1 Coordinate contract

Use three explicitly named coordinate spaces:

1. `world`: stable process-map coordinates. Persist nodes, groups, route
   waypoints, and spatial plans only in this space.
2. `viewport`: CSS pixels relative to the Process Map viewport after pan and
   zoom. Use only for pointer input, hit targets, and visible-region reporting.
3. `normalized_region`: qualitative map regions and normalized 0..1 positions
   derived from world bounds. Use these in compact agent context when exact
   coordinates are unnecessary.

Required conversion helpers:

    viewportToWorld(point, transform)
    worldToViewport(point, transform)
    viewportRectToWorld(rect, transform)
    worldRectToViewport(rect, transform)
    worldToNormalized(point, worldBounds)

Pan, zoom, pane width, browser location, and device pixel ratio must never alter
persisted world geometry.

### 4.2 Authority boundary

The model may request an outcome such as:

- Place the inspection after operation `op-10`.
- Connect these two cards.
- Clean up this selected group.
- Prefer left-to-right flow and keep these cards fixed.

The model may not author final `x`, `y`, bend points, or port changes. A
deterministic planner computes candidate geometry, validates it, scores it, and
returns an opaque candidate ID. The user accepts a candidate; the existing
operation and CAS layers apply the exact bound diff.

### 4.3 Semantic and spatial confidence remain separate

Every suggestion carries two independent records:

- `semanticEvidence`: why the card or connection belongs in the process.
- `spatialPlan`: where and how it can be rendered cleanly.

A high spatial score must never raise semantic confidence. A semantically weak
suggestion remains weak even if it fits perfectly on the canvas.

## 5. Shared spatial contract

Add a versioned, data-only contract consumed by Python and JavaScript:

`static/contracts/process-map-spatial-contract-v1.json`

It defines:

- Canonical card envelopes by node kind.
- Junction visual and hit radii.
- Port offsets and clearance.
- Group header geometry.
- Grid spacing and snap tolerance.
- Node, edge, and group clearance defaults.
- Supported flow directions.
- Supported route modes.
- Score names, units, and hard-rejection codes.
- Maximum node, edge, candidate, and route-point counts.

The renderer may measure DOM cards for diagnostics, but authoritative planning
uses canonical envelopes. A parity test must fail if rendered card dimensions
drift beyond tolerance from the contract.

Recommended initial policy:

    flowDirection: left_to_right
    gridSize: 20 world units
    nodeClearance: 44 world units
    edgeClearance: 14 world units
    portLeadLength: 28 world units
    routeMode: orthogonal_auto

Values are finalized through fixture screenshots and dense-map tests, not prompt
wording.

Version glossary:

- `layoutVersion` gates persisted process-map layout fields and migrations.
- `spatialVersion` gates the computed scene/digest shape and planner semantics.
- `routerVersion` identifies the algorithm that produced accepted edge-routing
  data so stale or incompatible routes can be invalidated deterministically.

## 6. Spatial scene model

Create `ai_inspector/process_map/spatial.py` initially. Split it into a package
only if file size or ownership makes that useful.

The pure compiler produces a deterministic `SpatialScene` from a validated map:

    {
      "spatialVersion": 1,
      "identity": {
        "productId": "...",
        "mapId": "...",
        "revision": "...",
        "layoutVersion": 3
      },
      "worldBounds": {"x": 0, "y": 0, "width": 0, "height": 0},
      "nodes": [{
        "nodeId": "...",
        "kind": "product_occurrence",
        "rect": {"x": 0, "y": 0, "width": 0, "height": 0},
        "center": {"x": 0, "y": 0},
        "ports": {"input": {...}, "output": {...}},
        "groupId": null,
        "locked": false
      }],
      "groups": [{
        "groupId": "...",
        "rect": {...},
        "headerRect": {...},
        "memberNodeIds": []
      }],
      "edges": [{
        "edgeId": "...",
        "logicalConnectionId": "...",
        "routeMode": "bezier_legacy",
        "points": [],
        "bounds": {...}
      }],
      "metrics": {...},
      "regions": [],
      "candidateSlots": []
    }

The scene is computed, not stored wholesale. Only user-authored layout policy,
node locks, and accepted route data are persisted.

## 7. Spatial diagnostics

The engine computes these deterministic metrics:

- Node-to-node overlap area and minimum clearance.
- Node-to-group-header intersection.
- Edge-to-node intersections, excluding its legal endpoint envelopes.
- Edge-to-group-header intersections.
- Edge-to-edge crossings, excluding shared endpoints and explicit junctions.
- Backward-flow edges relative to the configured flow direction.
- Route length, bend count, and unnecessary detour ratio.
- Dense regions and isolated whitespace regions.
- Alignment deviation from the configured grid and lanes.
- Number of cards that would need to move for a proposed cleanup.

Use axis-aligned rectangle tests, segment-rectangle tests, and segment
intersection tests over route polylines. Build a lightweight spatial index over
node and group rectangles so candidate evaluation does not scan the entire map
for every test.

Diagnostic severities:

- Error: persisted geometry is invalid or a route cannot be resolved.
- Warning: card overlap, edge-card intersection, or ambiguous hidden route.
- Information: crossings, backward flow, alignment, density, or optimization
  opportunity.

Layout diagnostics never block an otherwise structurally valid manual save in
v1. They block acceptance of an automatically generated candidate that violates
a hard constraint.

## 8. Incremental card placement planner

Incremental placement ships before full-map layout.

Inputs:

- Exact saved map revision and compiled spatial scene.
- New or existing target card envelope.
- Optional anchor node and intended connection direction.
- Required group or allowed region.
- Locked nodes and protected groups.
- Preferred flow direction.

Candidate generation:

1. Derive lanes from the anchor's output direction and existing rank.
2. Generate snapped candidate rectangles forward, above, below, and in the next
   lane, expanding outward in bounded rings.
3. Include candidate port-orientation and port-order combinations.
4. If no anchor exists, generate candidates in the least-dense visible region,
   then around the current world bounds.
5. Stop at the configured candidate cap.

Hard rejection:

- Card overlap or insufficient node clearance.
- Group containment violation when membership is required.
- Intersection with a group header.
- Inability to route the required connection without crossing a card.
- Invalid topology, duplicate connection, or precedence cycle.
- Movement of a locked node.

Weighted scoring, in priority order:

1. Zero edge-card intersections.
2. Fewer wire crossings.
3. Correct forward flow.
4. Fewer bends and shorter route.
5. Adequate card and port clearance.
6. Alignment with neighboring cards, lanes, and grid.
7. Proximity to the semantic anchor without crowding it.
8. Minimal movement of existing content.
9. Preference for the current visible region when the user initiated the action
   there.

Tie-break using stable candidate IDs, then rounded world `y`, then `x`. The same
map, revision, policy, and request must produce byte-identical ranked results.

The planner returns the best three candidates, not only one, so the UI can offer
alternatives without another model call.

## 9. Wire routing

### 9.1 Route modes

Support these modes additively:

- `bezier_legacy`: current endpoint-only behavior for existing maps.
- `orthogonal_auto`: deterministic obstacle-aware route generated by the
  spatial engine.
- `orthogonal_manual`: auto route plus user-authored waypoints.

Do not silently convert all existing edges. Newly accepted spatial proposals use
`orthogonal_auto`; legacy edges remain visually unchanged until the user asks to
optimize them.

### 9.2 Persisted edge shape

Bump `layoutVersion` from 2 to 3 and add optional routing data:

    routing: {
      mode: "orthogonal_auto",
      routerVersion: 1,
      waypoints: [{"x": 0, "y": 0}],
      obstacleFingerprint: "sha256..."
    }

Endpoints are always derived from current node ports; do not duplicate them in
`waypoints`. Moving a connected node or changing its ports invalidates the
obstacle fingerprint and recomputes auto routing. Manual waypoints are preserved
when still valid and surfaced for repair when invalid.

### 9.3 Router requirements

- Route around padded card rectangles and group headers.
- Permit travel through group bodies unless policy forbids crossing a boundary.
- Use explicit junction nodes for branches.
- Penalize, but do not universally forbid, edge crossings.
- Preserve source-to-target direction and arrow semantics.
- Keep label ownership on one logical connection, not every split segment.
- Return a deterministic failure reason rather than drawing through a card.

Run a short dependency spike before committing the router:

1. Evaluate a pinned local ELK.js build for whole-map layout and orthogonal edge
   routing.
2. Verify offline loading, deterministic output, package/license fit, groups,
   fixed-node constraints, junctions, and runtime at 250 nodes / 400 edges.
3. Verify whether the same engine can run in the packaged backend environment
   without adding an unmanaged Node.js process or a separately deployed service.
4. Produce a written dependency, packaging, timeout, cancellation, licensing,
   and failure-mode report.

Backend execution is a hard go/no-go gate:

- GO only if the packaged application can execute the same pinned engine through
  a supported, bounded, observable path with no hidden operational dependency.
- NO-GO if production must shell out to an assumed system Node installation,
  supervise a new Node service, or accept browser/server algorithm drift.
- Until a GO result is explicitly approved, the default architecture is the
  deterministic in-repo incremental planner/router for accepted suggestions.
  ELK may remain a browser-only experimental option for previewed full-map
  arrangement, but it cannot become authoritative or write persisted geometry.

No library is added until this spike has a checked-in result, parity tests, and
the post-Phase-3 approval checkpoint.

### 9.4 Editor changes caused by routed polylines

Every feature that currently assumes a Bezier path must use one shared
`edgeGeometry(edge, scene)` abstraction:

- Normal edge rendering.
- Ghost edge rendering.
- Pending connection preview.
- Wide edge hit target.
- Edge midpoint and context label placement.
- Wire-to-wire junction hit testing and nearest-point preview.
- Marquee edge selection.
- Graph bounds and Fit.

This avoids having one route on screen and another route used for interaction.

## 10. Regions and free-space model

The engine partitions the occupied world bounds plus a configurable margin into
coarse cells. It derives:

- `occupied`: intersects a padded card or protected header.
- `routed`: contains one or more wire segments.
- `dense`: exceeds node/edge density thresholds.
- `available`: can fit at least one canonical card envelope.
- `off_view`: outside the current visible world rectangle.

Regions receive stable IDs based on rounded world bounds, not screen pixels.
The model sees qualitative descriptions such as `right_of_group_bodywork` or
`open_lane_after_op_20`, plus candidate IDs. It does not need a dump of every
cell coordinate.

The browser may report `visibleWorldRect` with a request to favor on-screen
placement. This is ephemeral preference data, never trusted map truth and never
an authorization input.

## 11. Ghost preview UX

Spatial suggestions are previews first:

- Ghost card uses the real card envelope at the proposed world position.
- Ghost wire uses the exact proposed route.
- Suggested port changes appear on the ghost, not on the live card.
- Existing cards that would move in a cleanup preview show before/after outlines.
- A compact summary reports `0 overlaps`, crossing delta, bends, moved-card
  count, and any compromises.
- `Accept` commits one operation batch and one undo step.
- `Alternative` cycles through the other ranked candidates.
- `Dismiss` leaves the map byte-identical.

Never delay pointer interaction while the planner runs. Show a bounded planning
state and allow cancellation. A failed planner leaves the current map unchanged.

Recommended commands:

- `Suggest position` for a selected or pending card.
- `Route connection` for a selected edge.
- `Analyze layout` for diagnostics only.
- `Clean up selection` for selected nodes/groups.
- `Auto-arrange map` only in the later full-layout phase.
- `Lock position` / `Unlock position` for cards the planner must not move.

## 12. Sage context and behavior

Extend the trusted server digest with a bounded `process_map.spatial` section.
Do not send the full `SpatialScene` to the model.

Suggested digest content:

    {
      "spatial_version": 1,
      "layout_policy": {...},
      "world_region_count": 8,
      "layout_metrics": {
        "node_overlaps": 0,
        "edge_node_intersections": 1,
        "edge_crossings": 3,
        "backward_edges": 0
      },
      "problem_ids": [...],
      "open_regions": [...],
      "candidate_slots": [{
        "candidate_id": "slot-...",
        "relative_location": "right of op-20",
        "crossing_delta": -1
      }],
      "truncation": {...}
    }

Rules for Sage:

- Explain layout findings using card names and IDs, not unexplained coordinates.
- Ask the deterministic planner for exact geometry.
- Never claim a move or route occurred before an execution receipt.
- Never infer process order from visual proximity.
- Qualify recommendations when semantic evidence is missing.
- For read-only questions, return analysis without mutating tools.

The digest remains tied to `{productId, mapId, revision}`. A stale revision is
rejected before model or planner work.

## 13. Suggestion-engine integration

Keep the current semantic suggestion ID stable. Attach a revision-specific
spatial proposal separately:

    {
      "suggestionId": "semantic-stable-id",
      "spatialProposal": {
        "proposalId": "geometry-specific-id",
        "spatialVersion": 1,
        "obstacleFingerprint": "...",
        "candidateId": "...",
        "operations": [...],
        "metricsBefore": {...},
        "metricsAfter": {...}
      }
    }

This prevents a small card movement from resurrecting a semantically dismissed
suggestion while still invalidating stale geometry.

Cases:

- Both cards placed: suggest the connection and exact route.
- Target card absent: suggest a ghost card position plus the connection route.
- Many required cards absent: suggest an organized group or ranked incremental
  additions; do not dump overlapping cards into the viewport.
- Existing route blocked after a move: surface a reroute proposal without
  changing semantic evidence.

## 14. Builder operations and authorization

Add these domain operations only after the spatial engine is deterministic:

- `set_node_locked`
- `set_layout_policy`
- `set_edge_routing`
- `clear_edge_routing`

Add read/proposal tools:

- `inspect_spatial_layout(mapId, revision, scopeIds?)`
- `propose_node_placement(mapId, revision, request)`
- `propose_connection_route(mapId, revision, edgeOrEndpoints)`
- `propose_layout_cleanup(mapId, revision, scopeIds, constraints)`

All write behavior continues through:

    planner proposal
      -> structural + spatial validation
      -> exact visual diff
      -> explicit approval
      -> approval token
      -> CAS apply through operations.py
      -> execution receipt

The approval token additionally binds `spatialVersion`, obstacle fingerprint,
candidate ID, and diff hash. Any node movement, port change, group resize, or
revision change invalidates it.

## 15. Phased implementation

Approval structure:

- Committed near-term scope: Phases 0, 1, 2, and 3.
- Reconfirmation checkpoint: review real fixture results, planner quality,
  latency, user-preview behavior, and the router spike report.
- Directional follow-on scope: Phases 4-8 only after that checkpoint is approved.

### Phase 0 - Baseline and fixture capture

Work:

- Record exact current backend, editor-node, floating-surface, and Playwright
  bars at implementation start.
- Add synthetic fixture maps: linear, diamond, dense, grouped, junction-heavy,
  vertical ports, deliberate overlap, and crossing-heavy.
- Capture current Bezier screenshots and map fingerprints.

Exit gate:

- All existing bars green with no changed expectations.
- Fixture assets are deterministic and contain no product-specific assumptions.

### Phase 1 - Coordinate and geometry contract

Work:

- Add the versioned shared spatial contract.
- Add world/viewport conversion helpers and parity tests.
- Compile canonical node, group, port, and edge endpoint geometry in Python and
  JavaScript.
- Add DOM-envelope drift diagnostics in development/test mode.

User-visible change: none.

Exit gate:

- Python and JavaScript produce byte-equivalent canonical scenes for every
  fixture after numeric normalization.
- Pan/zoom/sidebar changes alter viewport coordinates but never world geometry.

### Phase 2 - Diagnostics and compact spatial digest

Work:

- Implement overlap, intersection, crossing, flow, clearance, density, and
  alignment metrics.
- Add spatial index and deterministic region derivation.
- Extend trusted digest with bounded spatial summaries.
- Add `Analyze layout` as read-only UI and Sage behavior.

Exit gate:

- Golden metric/digest fixtures pass.
- Browser-supplied geometry/digest is ignored as authority.
- No mutating tool is exposed for informational analysis.

### Phase 3 - Incremental placement and ghost cards

Work:

- Implement candidate generation, rejection, scoring, and stable ranking.
- Evaluate port orientation/order per candidate.
- Add ghost card and alternatives UX.
- Add card locking and accepted placement as one undoable operation.

Exit gate:

- The planner places a new card without overlap in every solvable fixture.
- Same input produces identical candidates.
- Pan/zoom do not alter accepted world coordinates.
- Reject/dismiss leaves the map fingerprint unchanged.

### Phase 4 - Obstacle-aware wire routing

Work:

- Complete the router dependency spike and record the decision.
- Add layoutVersion 3 migration and optional routing schema.
- Implement shared edge geometry and route invalidation.
- Update rendering, hit testing, labels, junction targeting, marquee selection,
  bounds, and Fit to use the same geometry.

Exit gate:

- Accepted auto routes do not intersect non-endpoint cards.
- Manual legacy edges remain unchanged.
- Junction and logical-connection behavior survives save/reload and undo/redo.
- No mismatch exists between visible path and interaction path.

### Phase 5 - Spatialized semantic suggestions

Work:

- Attach route proposals to current ghost connections.
- Support ghost next-card plus ghost wire for an unplaced semantic target.
- Preserve semantic dismissal identity independently from geometry proposals.
- Support optional organized batch preview for large part sets.

Exit gate:

- Suggestions remain evidence-grounded.
- Stale geometry proposals are discarded after any relevant edit.
- Batch preview has no overlaps and commits atomically or not at all.

### Phase 6 - Sage and Builder write integration

Work:

- Register read-only inspection and proposal tools.
- Add locked-position, routing, and layout-policy operations.
- Bind spatial proposals into the existing approval/CAS gate.
- Add receipt-grounded completion messages.

Exit gate:

- Sage never emits or applies free-form coordinates.
- Read-only questions cause no map mutation.
- Stale, replayed, altered, or unauthorized proposals fail closed.
- One accepted proposal equals one diff, one undo step, and one receipt.

### Phase 7 - Selection and full-map optimization

Work:

- Add `Clean up selection` with pinned nodes and groups.
- Add previewable group and full-map arrangement.
- Prefer minimal displacement and preserve user-authored grouping.
- Add optional ELK-backed arrangement only if the Phase-4 spike passed every
  packaging and parity gate.

Exit gate:

- No automatic arrangement occurs without explicit user request and preview.
- Locked cards never move.
- The proposed layout improves the configured metric without introducing a hard
  violation.

### Phase 8 - Hardening and default-on rollout

Work:

- Performance profiling and cancellation.
- Accessibility and reduced-motion review.
- Light/dark screenshot verification.
- Telemetry, feature flags, rollback, and soak.

Exit gate:

- Performance targets and full regression matrix pass.
- Flag-off path is current behavior.
- The engineering checkpoint is complete when the first two conditions pass.
- Default-on is a separate operational rollout decision after a self-use soak
  with acceptance/dismissal metrics reviewed; implementation completion alone
  does not satisfy that rollout gate.

### Post-phase authoring enhancement - source-tree batch placement

The source product structure supports temporary multi-selection without adding
selection state to the saved map. Ctrl-click or Command-click toggles occurrence
rows, while an unmodified click starts a new single-row selection. Dragging any
selected row carries only the stable occurrence IDs and creates the unplaced
cards as one deterministic batch near the world-space drop point.

Batch placement is viewport- and group-aware, avoids existing cards and group
headers, and never invokes full-map layout. A successful drop is one atomic map
mutation and one Undo step. Occurrences already on the canvas are not duplicated;
their existing cards are selected instead. Removing a canvas card leaves its
source occurrence available in the immutable product structure.

## 16. Test strategy

### Python unit and property tests

- Coordinate conversion round trips.
- Translation invariance: shifting an entire map shifts plans identically.
- Viewport invariance: pan/zoom never changes world-space results.
- AABB overlap and clearance boundaries.
- Segment-rectangle and segment-intersection cases.
- Shared-endpoint and explicit-junction crossing exclusions.
- Stable region, candidate, obstacle, and proposal fingerprints.
- Candidate ranking and deterministic tie-breaking.
- Route validity, invalidation, and waypoint preservation.
- Digest budget and deterministic ordering.
- Schema v2-to-v3 migration and unknown-field round trips.
- Failed operation batches never write.

Use generated/property cases for random non-overlapping rectangles and routes,
then pin failures as named fixtures.

### JavaScript node harness

- Python/JS contract parity fixtures.
- Edge geometry for all route modes.
- Bounds and Fit include routed segments.
- Nearest-point and hit testing use the rendered route.
- Ghost preview accept/dismiss lifecycle.
- One mutation and one history entry per accepted plan.
- Route invalidation after move, resize, group change, and port swap.

### Playwright

- Add next card at 0.28, 1.0, and 1.6 zoom after panning.
- Placement remains under the preview after tree-pane collapse/expand.
- No overlap in empty, sparse, dense, grouped, and junction maps.
- Route avoids cards in horizontal and vertical port modes.
- Existing Bezier maps render unchanged before explicit optimization.
- Ghost alternatives, cancellation, dismissal, acceptance, undo, redo, save,
  reload, and stale-revision behavior.
- Wire hit test, label, junction insertion, and marquee selection match the
  visible routed path.
- Light/dark and reduced-motion screenshots.
- Rapid edits invalidate stale plans without console errors or orphan overlays.

### Agent and authorization tests

- Spatial analysis question gets no mutating tools.
- Explicit placement request gets proposal tools but no direct write.
- Prompt injection cannot alter layout policy or tool permissions.
- Model-authored raw coordinates are rejected.
- Approval token mismatch, replay, stale revision, obstacle drift, and wrong
  user/session all fail closed.
- Completion prose follows the execution receipt, not the requested action.

### Performance targets

On the supported local workstation profile:

- Compile and diagnose 250 nodes / 400 edges in <= 150 ms median.
- Produce three incremental candidates in <= 400 ms median and <= 1 s p95.
- Reroute one affected connection in <= 100 ms median.
- Keep pan, zoom, drag, and selection at interactive frame rates; planning runs
  outside pointer-move handlers.
- Cancel a superseded plan promptly and never apply its result.

Targets are measured before default-on and adjusted only with recorded hardware
and fixture evidence.

## 17. Telemetry

Record per proposal:

- Spatial engine and router versions.
- Map size, scoped node/edge counts, and candidates evaluated.
- Compile, diagnose, plan, and route latency.
- Rejection-code counts.
- Before/after overlaps, crossings, edge-card intersections, bends, and route
  length.
- Number of existing cards moved.
- Accepted, alternative-selected, dismissed, cancelled, stale, or failed.
- Fallback route reason.

Do not log full customer labels or geometry unless diagnostic capture is
explicitly enabled. IDs and aggregate metrics are sufficient for product
telemetry.

## 18. Risks and mitigations

1. Card-size drift between DOM and server.
   Mitigation: shared contract, measured drift assertion, and screenshot tests.
2. Routing complexity expands into a graph-editor rewrite.
   Mitigation: incremental routes first, shared edge abstraction, bounded
   dependency spike, legacy fallback retained.
3. Auto-layout destroys the user's mental map.
   Mitigation: no silent movement, locks, scope-based cleanup, preview and exact
   move count.
4. Spatial context consumes the agent token budget.
   Mitigation: qualitative bounded digest and candidate IDs, never full scene.
5. Stale plans execute after map edits.
   Mitigation: revision + obstacle fingerprint + candidate ID + diff hash bound
   into approval.
6. Groups and junctions create ambiguous obstacles.
   Mitigation: explicit rules: group headers are obstacles, group bodies are not;
   junctions are topology and valid route endpoints.
7. Clean geometry is mistaken for process truth.
   Mitigation: separate semantic evidence and spatial score in data, UI, tests,
   and Sage instructions.
8. Large-map planning blocks interaction.
   Mitigation: spatial index, worker/background execution where available,
   cancellation, caps, and scoped planning.

## 19. Rollback

Use independent flags:

- `INSPECTORPRO_PROCESS_MAP_SPATIAL_ANALYSIS`
- `INSPECTORPRO_PROCESS_MAP_SPATIAL_PLACEMENT`
- `INSPECTORPRO_PROCESS_MAP_AUTO_ROUTING`
- `INSPECTORPRO_PROCESS_MAP_AGENT_LAYOUT_WRITE`

Flag off behavior:

- Existing positions, Bezier rendering, semantic suggestions, and manual editing
  remain unchanged.
- LayoutVersion-3 assets still load; optional routing data is ignored safely by
  old rendering behavior only after compatibility tests prove this path.
- Disabling agent writes does not disable read-only layout analysis.

Never make rollback depend on deleting persisted route data. The renderer must
always be able to derive a legacy endpoint path.

## 20. Recommended product decisions

1. Ship incremental placement before full-map auto-arrangement.
2. Keep existing Bezier routes for legacy/manual content; use orthogonal routes
   for newly accepted spatial proposals.
3. Always preview moves and routes before mutation.
4. Add card locks before any cleanup operation can move existing cards.
5. Keep viewport transform out of the shared map asset; optional per-user view
   restoration belongs in UI/session state.
6. Route around cards instead of relying on wires being visually behind them.
   A hidden segment is ambiguous even when layer ordering is technically correct.

## 21. Definition of done

Spatial intelligence is production-ready when:

- Every persisted card, group, port, junction, and routed edge has one canonical
  world-space representation independent of pan and zoom.
- The same map and request produce deterministic diagnostics and candidates.
- A supported next-card suggestion can show a correctly placed ghost card and a
  route that does not overlap or pass through unrelated cards.
- Port orientation/order can be selected by the planner but changes only after
  preview and acceptance.
- Semantic evidence and spatial scoring remain separate end to end.
- Sage explains spatial findings but never invents or directly applies geometry.
- Builder writes pass the existing authorization, exact-diff approval, CAS,
  idempotency, and receipt chain with added spatial fingerprint checks.
- Undo, redo, save, reload, groups, junctions, selection, and legacy Bezier maps
  remain correct.
- Stale, cancelled, rejected, or failed plans leave the map byte-identical.
- The full regression and performance matrices pass with flags on and off.
