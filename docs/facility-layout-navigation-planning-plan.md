# Facility Layout Deterministic Navigation Planning Plan

Date: 2026-08-31

Status: NAV0 evidence captured; NAV1 through NAV9 implemented and verified
through 2026-09-01. Production promotion remains held pending explicit
reference-layout acceptance by the named product owner.

Scope: Replace heuristic actor paths with deterministic, GPS-like facility
navigation while retaining direct 2D path authoring as an explicit user control.

## Revision 2 Review Closures

1. **Revision invalidation:** durable navigation intent remains inside canonical
   layout bytes. NAV1 introduces motion-package v2 with a recomputed
   `validationContextFingerprint` before NAV2 may write navigation intent. V1
   retains full-layout-revision behavior for compatibility.
2. **Gold-scale graph construction:** local obstacle geometry is canonicalized,
   unioned, footprint-expanded, and unioned again before visibility vertices are
   extracted. NAV0 benchmarks the post-union graph in the 492-placement
   Automation scope, including its 456 contiguous guard panels.
3. **Geometry determinism:** precision, input order, buffer parameters,
   conservative disc discretization, ring normalization, output ordering, and
   cross-platform Shapely/GEOS fixtures are frozen before implementation.
4. **Performance evidence:** every p95 gate is bound to the checked-in Dell 15
   DC15250 hardware fixture, exact dependency versions, and 20-run sample rule.

The revision also adds a non-service `barrier` role, requires `motion_lanes.py`
and `motion_package.py` reuse, bounds the reference acceptance set, prohibits
generated overlap-hiding schedules, and gives NAV9 an explicit production
removal gate for the legacy rectangle-loop heuristic.

## 1. Executive Decision

InspectorPro should not ask Sage to draw motion paths and should not require a
user to draw every path manually.

The target workflow is:

```text
facility geometry and authored circulation
  -> navigation anchors and actor assignments
  -> revision-bound navigation graph
  -> deterministic route search
  -> footprint and direction validation
  -> complete handoff graph
  -> Plan and 3D preview
  -> user review and optional manual override
```

This is the same core separation used by GPS:

- the map owns roads, directions, intersections, and restrictions;
- the request owns the origin, destination, and required stops;
- a deterministic routing engine owns the path;
- the user may require a different road or waypoint;
- the presentation layer displays the result without becoming the source of
  truth.

For InspectorPro, the map is more demanding because it must also represent
walkable floor space, machine footprints, service sides, FIFO points, lane
direction, vehicle turning constraints, handoffs, and exact existing actor
identity.

Manual path drawing remains important, but it becomes:

1. an authored constraint or override;
2. a way to establish reviewed gold paths;
3. a fallback when operational intent is unavailable to the planner; and
4. a correction mechanism for Sage-generated proposals.

It is not the primary routing engine.

## 2. Grounded Current State

The repository already contains much of the required substrate.

### 2.1 Existing qualified capabilities

- `circulation.py` builds route-network reachability, direction-aware paths,
  crossing geometry, obstacle-aware reroutes, and semantic route amendments.
- `routing.py` contains a deterministic cardinal heading-lattice vehicle
  planner, minimum-turning-radius primitives, footprint sweep, obstacle checks,
  and resource ceilings.
- `motion_lanes.py` derives directional lanes from authored pavement arrows and
  can move a return traversal to the opposite marked lane.
- `motion_package.py` produces immutable, revision-bound route evidence and
  deterministic Plan/3D playback data.
- `activity_scenario.py` validates existing actor identities, operator paths,
  FIFO connections, and handoff topology.
- `facility_layout_editor.js` and `facility_layout_three_adapter.js` already
  render the same activity state in Plan and 3D.
- the layout schema already distinguishes infrastructure routes from
  placements, zones, markings, and process bindings.
- Shapely is already a project dependency and is used for exact 2.5D geometry.

### 2.2 Why the current operator paths are unsatisfactory

`lean_motion.py` currently:

- recognizes cells from label vocabulary;
- divides rectangular zone bounds into segments;
- assigns stations largely by proximity;
- creates rectangular station loops from zone bounds; and
- derives FIFO links from zone interfaces.

`service.py` improves those proposals by selecting cardinal service candidates
and routing each leg through the existing forklift heading-lattice planner.
This proves geometric feasibility for the chosen waypoints, but it does not
prove that the waypoints express the intended work.

The principal defect is therefore not missing line drawing. It is missing
navigation semantics:

- which operator owns which work;
- which face of each asset is serviced;
- which stations must be visited and in what order;
- where an operator may enter or leave a cell;
- which FIFO endpoint belongs to each participant;
- which walkable regions connect;
- where a vehicle may change lane or turn around; and
- which path preferences are authored rather than guessed.

The current rectangle-loop heuristic should no longer be the default path
source once this plan reaches NAV4. It may remain only as an explicitly labelled
prototype fixture until migration is complete.

### 2.3 Existing runtime limits to preserve

| Constraint | Current value | Planning consequence |
|---|---:|---|
| Facility tool calls per turn | 10 | A normal route request must fit observe, plan, validate, and preview without an unbounded loop. |
| Tool response bytes | 16,384 | Large graphs and paths stay server-side; Sage receives IDs and compact summaries. |
| Facility skill context | 12,000 `bytes4-v1` estimated tokens | New context targets at most 9,600 estimated tokens. |
| Activity actors | 20 | The first multi-actor gate remains bounded to the current scenario limit. |
| Activity scenario bytes | 65,536 | Scenario summaries reference motion packages rather than embedding dense paths. |
| Motion package bytes | 8 MiB | Full route evidence remains retrievable by package ID. |
| Swept samples | 25,000 | Vehicle and actor validation fails before excessive allocation. |
| Sweep comparisons | 5,000,000 | Static geometry checks retain the existing resource refusal. |

## 3. Product Responsibilities

### 3.1 User responsibilities

The user owns operational intent that geometry cannot prove:

- actor-to-task assignment;
- station visit order when process sequence matters;
- service side when the asset has no reviewed service connector;
- FIFO ownership and handoff pairing;
- required or forbidden routes;
- allowed turnaround locations;
- optional authored spacing or clearance;
- route locks and manual overrides; and
- approval of the final authored navigation program.

Direct pointer input in Plan view may author coordinates because the user is
explicitly drawing geometry. Chat coordinates remain prohibited.

### 3.2 Sage responsibilities

Sage may:

- identify existing actors, stations, routes, zones, and FIFO points by stable
  identity;
- translate natural language into origins, destinations, ordered stops,
  preferences, and exclusions;
- ask for a missing service side, route width, profile, or task order;
- select the correct deterministic planning and validation tools;
- compare bounded alternatives using published metrics;
- explain why a route is accepted, refused, stale, or incomplete; and
- request a local replan after a user changes intent.

Sage may not:

- author world coordinates or hidden waypoints;
- invent actor dimensions, walking clearances, vehicle profiles, speeds,
  priorities, dwell times, or regulatory rules;
- infer manufacturing sequence from proximity alone;
- create extra operators or substitute actor identities;
- claim safety, throughput, staffing sufficiency, or operational optimality;
- promote a derived or inferred anchor to authored authority; or
- Save a navigation program without the existing explicit approval boundary.

### 3.3 Deterministic engine responsibilities

The engine owns:

- compiling traversable geometry;
- creating graph nodes and edges;
- route search and tie-breaking;
- obstacle expansion by exact actor footprint;
- lane direction and transition enforcement;
- turning and swept-envelope validation;
- path simplification that preserves validity;
- handoff topology validation;
- identity and revision binding;
- stale-result rejection; and
- exact Plan/3D playback geometry.

## 4. Source Of Truth And Authority

### 4.1 Four different objects must remain separate

1. **Navigation infrastructure**

   Durable layout entities such as aisles, walkways, crossings, zones,
   placements, floor markings, and controlled connectors.

2. **Movement program**

   Durable authored intent: existing actor, ordered task anchors, loop behavior,
   handoff references, required routes, forbidden regions, and optional manual
   path constraints.

3. **Navigation snapshot**

   A derived, immutable graph compiled from one exact layout revision and actor
   class. It is a cache, never a second editable facility layout.

4. **Journey solution**

   A derived route result bound to the movement program, navigation snapshot,
   actor profile, and planner version. Dense solution data is fetched by ID.

The activity scenario references journey solutions. It does not become a new
geometry source.

### 4.2 Durable representation decision

Keep existing `routes` as facility infrastructure. Do not place every actor's
computed journey into `routes`.

Add one closed, versioned `extensions.facilityNavigation` contract to the
layout document for durable navigation intent:

```text
schemaVersion
anchors[]
movementPrograms[]
manualPathConstraints[]
handoffPrograms[]
```

This extension may reference zones, placements, routes, markings, process
bindings, and asset connectors by stable ID. It must not duplicate their
geometry or identity.

Computed navigation snapshots, route solutions, clearance samples, and
playback state remain outside the saved layout. They are reproducible from the
saved intent and revision-bound source geometry.

`extensions.facilityNavigation` participates in normal canonical layout bytes
and therefore changes `layoutRevision`. It is not excluded from the layout
hash. Excluding durable authored intent would weaken compare-and-swap, Undo,
Save, and stale-write protection.

To prevent an unrelated navigation-anchor edit from invalidating every motion
package, NAV1 brings the motion plan's narrower
`validationContextFingerprint` forward as a prerequisite. A motion package
retains its generation `layoutRevision` for provenance, but playback validity
after a layout revision changes is decided by recomputing the exact validation
context projection used by that solution. The package remains usable only when
the recomputed fingerprint is byte-identical. The first motion-package schema
continues to require full-revision equality; no durable navigation authoring is
enabled until the new package contract passes migration and stale-safety tests.

NAV1 must produce a field-level representation and migration matrix before the
contract is accepted. If an existing route endpoint, placement connector, zone
anchor, or process binding already represents a field without loss, the new
extension references it rather than copying it.

### 4.3 Evidence classes

Every anchor, restriction, and route result carries one of the existing
evidence statuses:

- `authored`: explicitly created or confirmed by a user or controlled source;
- `derived`: calculated deterministically from authored geometry;
- `inferred`: a proposal requiring review;
- `unknown`: required meaning is unavailable.

Examples:

- a point clicked by a user in Plan view is authored geometry;
- a lane center derived from two pavement-arrow clusters is derived;
- a guessed machine service side is inferred and cannot drive controlled
  release without confirmation;
- an absent operator profile is unknown and blocks physical-fit validation.

User-authored does not mean safe, compliant, or production-approved. Those
claims require separate controlled evidence.

## 5. Target Contracts

The exact JSON fields are frozen in NAV1. The following are behavior contracts,
not final serialization syntax.

### 5.1 Navigation anchor

```text
navigationAnchorId
anchorKind
ownerRef
interactionKind
positionAuthority
localPosition or derivedPositionRef
approachDirections[]
actorClasses[]
evidence[]
reviewStatus
```

Supported initial anchor kinds:

- actor home;
- station operate/load/unload/inspect point;
- FIFO input/output;
- cell entrance;
- aisle access;
- crossing;
- vehicle parking;
- vehicle turnaround; and
- handoff endpoint.

Asset-definition service connectors are preferred. A placement-specific
authored anchor is the fallback. Proximity alone may generate a proposal but
never silently establish the service side.

### 5.2 Movement program

```text
movementProgramId
actorPlacementId
actorClass
orderedStops[]
loopMode
requiredRouteIds[]
requiredAnchorIds[]
forbiddenZoneIds[]
forbiddenRouteIds[]
manualPathConstraintIds[]
handoffProgramIds[]
sourceRevisions
evidence[]
reviewStatus
```

Initial loop modes:

- `one_way`;
- `closed_loop`;
- `out_and_return`;
- `paired_lane_return`; and
- `task_cycle`.

The actor must reference an existing placement. The program cannot contain an
instruction to create or clone an actor.

### 5.2.1 Actor navigation profile

Pedestrian and vehicle profiles must remain distinct.

An operator profile publishes a rotation-invariant plan-view navigation
envelope, normally a reviewed disc or other conservative rotational envelope.
If only an oriented visual footprint exists, the compiler may derive a maximum
radial envelope and must label the result conservative. It may not claim that
the visual mesh itself is a validated human-clearance model.

A vehicle profile continues to publish the existing orientation-sensitive
footprint, steering limits, reverse policy, grade limits, and optional load
envelope. Vehicle suitability still requires the exact published profile
revision.

### 5.3 Manual path constraint

```text
manualPathConstraintId
movementProgramId
constraintMode
authoredPolyline[]
snapRefs[]
lockedSegmentIndexes[]
direction
positionAuthority: ui_authored
evidence[]
```

Constraint modes:

- `guide`: route through these points while the planner resolves intervening
  geometry;
- `locked_segment`: preserve specific authored segments;
- `complete_override`: use the authored polyline only after full validation;
- `avoid_region`: prohibit a user-drawn region; and
- `preferred_corridor`: add a deterministic cost preference without making it
  mandatory.

No Sage tool accepts `authoredPolyline` or world coordinates.

### 5.4 Navigation snapshot

```text
navigationSnapshotId
layoutRevision
compilerVersion
actorClass
actorProfileRevision
walkableRegions[]
obstacleRecords[]
nodes[]
edges[]
connectedComponents[]
sourceRevisions
geometryContextFingerprint
snapshotFingerprint
qualification
```

Large arrays stay in the server store. Sage receives counts, component facts,
missing-anchor findings, and the snapshot ID.

### 5.5 Journey solution

```text
journeySolutionId
movementProgramId
navigationSnapshotId
actorPlacementId
generationLayoutRevision
validationContextFingerprint
outcome
orderedAnchorIds[]
networkEdgeIds[]
centerline[]
poses[]
distanceMeters
turnCount
reverseUsed
validation
sourceRevisions
plannerVersions
solutionFingerprint
qualification
```

Outcomes are a closed union:

- `accepted`;
- `unreachable`;
- `constraint_conflict`;
- `physical_validation_refused`;
- `authority_missing`;
- `stale`; and
- `resource_refused`.

An unreachable result is not a safety finding. A resource refusal is not a
geometric finding.

The validation-context projection contains only canonical records that can
change the accepted solution or its displayed evidence:

- actor placement transform and exact asset-definition revision;
- actor/vehicle navigation profile and optional load revision;
- referenced movement program, anchors, handoffs, and manual constraints;
- every traversable polygon and directed lane edge used by the solution;
- route geometry, lane markings, turnarounds, and crossings used by the
  solution;
- shell and policy revisions used by validation;
- every current obstacle record selected by the frozen validation influence
  region around the accepted swept geometry; and
- geometry compiler, buffer, canonicalization, and planner versions.

On package fetch, InspectorPro rebuilds this projection from current sources.
A moved obstacle entering the influence region changes membership and the
fingerprint. A missing referenced record fails stale. An unrelated anchor,
label, or placement outside the frozen influence region does not invalidate the
package. The influence-region rule, margin, and computational epsilon are
frozen in NAV1 and are never represented as engineering clearance.

### 5.6 Handoff program

```text
handoffProgramId
sourceMovementProgramId
sourceFifoAnchorId
targetMovementProgramId
targetFifoAnchorId
materialIdentityRef
sequencePolicy
timingAuthority
evidence[]
```

The first release proves topology only unless timing is explicitly authored.
A visual pause may be used for presentation, but it is labelled as presentation
timing and never recorded as process dwell time.

## 6. Deterministic Algorithms

### 6.1 Pedestrian routing

Use a hybrid graph:

1. **Local free-space graph** inside a cell or department.
2. **Authored pedestrian-route graph** for travel between cells or departments.
3. **Connector edges** at cell entrances, crossings, station anchors, and FIFO
   anchors.

For local free space:

- compute allowed polygonal space from the containing zone;
- classify placements as service targets, barriers, or ordinary obstacles;
  barrier assets such as guard panels participate in subtraction but are never
  treated as service targets;
- canonicalize and union touching or overlapping source obstacle polygons
  before visibility vertices are extracted;
- expand the post-union obstacle geometry by the exact published
  rotation-invariant operator navigation envelope;
- union the expanded results again so gaps narrower than the actor envelope
  close deterministically;
- subtract the resulting composite obstacles, shell obstacles, and protected
  regions from allowed space;
- use zero additional clearance unless an authored policy or explicit value is
  supplied;
- build a deterministic visibility graph from start, goal, required anchors,
  connector points, and relevant obstacle vertices;
- run A* with Euclidean distance and stable ID/coordinate tie-breaking;
- remove redundant points only when exact line-of-sight remains inside free
  space; and
- derive heading from the final route tangent.

This is preferred over the current cardinal forklift planner for operators.
Operators do not require artificial 90-degree heading states, but their full
footprint must still remain in traversable space.

For very large local obstacle sets, spatial indexing limits candidate
visibility edges. NAV0 benchmarks this approach against a triangulated navmesh
plus funnel path. The visibility graph remains the initial implementation
unless it fails the frozen performance gate. No silent algorithm switch is
allowed after qualification.

The gold performance case is the `Automation + Robot cells` scope in the
archived manual factory, which contains 492 placements, including 456
wire-mesh guard panels. Placement count is not the graph-size metric. NAV0 must
record the vertex count after canonical source union and actor-envelope
expansion, the candidate visibility-pair count, the accepted edge count, and
the route-query p95. The visibility graph is not qualified by a small synthetic
cell alone.

### 6.1.1 Deterministic geometry contract

NAV1 freezes the complete obstacle-expansion and canonicalization operation:

```text
source precision                  6 decimal places in meters
input ordering                    stable obstacle ID, then canonical polygon
source composition                unary union before buffer
buffer quad_segs                  16
buffer cap_style                  round
buffer join_style                 round
buffer mitre_limit                5.0
buffer single_sided               false
disc discretization              conservative secant correction
post-buffer composition           unary union
exterior ring orientation         counterclockwise
hole ring orientation             clockwise
start vertex                      lowest x then z, lexicographic
polygon ordering                  first vertex, area, source ID
output precision                  6 decimal places in meters
duplicate/collinear handling      frozen deterministic normalization
invalid result                    fail closed, never auto-repaired silently
```

For an operator navigation radius `r` and `quad_segs = q`, round-arc buffering
uses an effective radius of `r / cos(pi / (4q))`. This prevents the chordal
buffer approximation from becoming smaller than the published circular
navigation envelope between arc vertices. The correction is computational
geometry, not additional engineering clearance.

The fixture records Shapely and GEOS versions and includes cases for touching
guard panels, holes, narrow passages, acute corners, multipolygons, and points
on the computational epsilon. Linux and Windows runs must produce identical
canonical polygons, graph IDs, accepted centerlines, and fingerprints. A
platform difference is a refusal to promote, not a tolerance-based pass.

### 6.2 Station sequencing

The planner does not invent manufacturing order.

- If stops are ordered, preserve that order exactly.
- If the source explicitly marks stops as order-independent, compute the
  shortest exact visit order only within a frozen small-N limit.
- Above that limit, return a deterministic candidate and label it non-optimal,
  or ask the user to provide order.
- Never reorder a process dependency to shorten walking distance.

The NAV1 contract freezes the exact small-N threshold and cost definition.

### 6.3 Forklift and vehicle routing

Use a two-level planner:

1. **Directed lane graph**

   Convert authored aisle centerlines, pavement arrows, intersections, and
   turnaround anchors into explicit directional lane edges. A two-way boulevard
   becomes two directional lanes, not one reversible centerline.

2. **Local vehicle planner**

   Reuse the existing heading-lattice planner and swept-volume validator for
   placement-to-lane, lane transitions, turnarounds, and lane-to-destination.

Vehicle rules:

- exact published vehicle profile and revision are required for physical
  validation;
- return travel uses the opposite directional lane when one is authored;
- lane changes occur only at a validated junction or authored turnaround;
- one-way edges are never traversed backward;
- reverse is permitted only by the bound vehicle profile and movement program;
- every accepted route passes the existing swept-volume validator; and
- without a profile, InspectorPro may report topological reachability but must
  not claim the vehicle fits or can turn.

### 6.4 Handoff routing

Treat handoffs as a task graph layered on the spatial graph:

```text
Operator A home
  -> assigned stations
  -> source FIFO anchor
  -> material-transfer edge
  -> target FIFO anchor
  -> Operator B assigned stations
  -> Operator B home
```

The material-transfer edge is not operator walking. Each participant must have
its own complete accepted route to its own FIFO endpoint. Handoff completeness
requires:

- two distinct existing actor identities where two participants are required;
- exact source and target FIFO identities;
- accepted actor journeys to both endpoints;
- a bound material or workpiece identity when one exists;
- no dangling connection; and
- explicit disclosure when sequence or timing is unavailable.

### 6.5 Multiple actors

Independent shortest paths do not prove collision-free traffic.

The first release provides:

- independent validated spatial routes;
- shared-clock playback;
- static path-intersection diagnostics;
- exact actor separation measurements during playback; and
- replay of an explicitly user-authored presentation offset when one exists,
  labelled as presentation metadata rather than process timing.

The system does not generate phase offsets, delay an actor, or alter a path to
make independently planned actors appear conflict-free. The zero-offset shared
clock is the default, and visible overlap is reported rather than concealed.

It does not claim traffic safety, throughput, capacity, queue behavior, or
staffing sufficiency.

Time-expanded routing, reservation tables, or Conflict-Based Search belong to a
later controlled gate. They require authored speeds, priorities, dwell times,
route capacities, and right-of-way rules. They must not be smuggled into the
prototype through animation defaults.

## 7. Manual 2D Authoring Experience

Plan view is the sole path-authoring surface for the first release. 3D is a
live preview and inspection surface.

### 7.1 Workflow

1. Select an existing operator, forklift, vehicle, or mobile asset.
2. Choose `Motion Path`.
3. Select `Guide`, `Locked segment`, or `Complete override`.
4. Choose one-way, loop, out-and-return, paired-lane return, or task cycle.
5. Click waypoints in Plan view.
6. Snap to station connectors, FIFO points, route lanes, crossings, cell
   entrances, turnaround anchors, existing path endpoints, or grid.
7. Press Enter to finish; use a closed-loop control rather than duplicating the
   first point manually.
8. Review deterministic validation findings.
9. Preview the exact existing actor in Plan and 3D.
10. Save the authored constraint only through the existing explicit Save flow.

### 7.2 Editing controls

- drag a waypoint;
- insert a waypoint on a segment;
- delete a waypoint;
- reverse path direction;
- mark a segment required or locked;
- convert a complete override to guide points;
- assign or change the actor without cloning it;
- attach an endpoint to a station or FIFO anchor;
- show/hide pedestrian, vehicle, FIFO, handoff, and validation overlays
  independently; and
- Undo the complete gesture atomically.

### 7.3 Validation feedback

The editor distinguishes:

- valid and physically checked;
- topologically valid but profile-unverified;
- inferred anchor requiring confirmation;
- obstacle or boundary conflict;
- wrong-way vehicle segment;
- missing turnaround;
- unreachable handoff;
- stale because the layout changed; and
- unsupported safety or operational claim.

The editor must never silently move a user-authored locked point to obtain a
valid route.

## 8. Sage Tool Surface

The target closed tool set is:

| Tool | Effect | Purpose |
|---|---|---|
| `observe_navigation_context` | read | Return bounded actors, routes, anchors, missing semantics, and graph summary. |
| `compile_navigation_snapshot` | read | Compile or retrieve one revision-bound graph and return its ID and summary. |
| `plan_actor_journey` | read | Resolve one actor, program, and bounded alternative set. |
| `validate_actor_journey` | read | Return identity, topology, direction, footprint, and stale-state findings. |
| `compare_journey_alternatives` | read | Compare published metrics without claiming operational optimality. |
| `propose_navigation_intent` | preview | Produce an unsaved semantic intent proposal with no coordinates. |
| `build_activity_scenario` | viewport | Load accepted journey IDs into shared Plan/3D playback. |

Direct path-point authoring remains UI-only. Sage may ask the user to draw a
guide or may refer to an already-authored constraint by ID.

Normal routing should require no more than:

1. observe;
2. compile/retrieve snapshot;
3. plan;
4. validate; and
5. preview.

Large data is always fetched by the browser with an opaque package ID. It is
never serialized into the model response.

## 9. Implementation Phases

The phase namespace is `NAV0` through `NAV9` to avoid collision with the
existing G, KF, RQ, and FM programs.

### 9.1 Proposed module ownership

New backend modules:

- `navigation_contract.py`: closed schemas, normalization, authority checks,
  canonicalization, and fingerprints;
- `navigation_snapshot.py`: free-space and directed-network compilation,
  spatial indices, components, and immutable snapshot storage;
- `pedestrian_routing.py`: visibility graph, A*, path simplification, and
  operator-envelope validation;
- `journey_planning.py`: multi-leg movement programs, ordered stops, route
  comparison, and handoff compilation; and
- `navigation_intent.py`: bounded semantic parsing and deterministic refusal
  rules.

Existing backend ownership:

- `routing.py` retains vehicle motion primitives and swept-volume validation;
- `motion_lanes.py` retains pavement-marking-to-directional-lane derivation;
- `circulation.py` retains durable aisle infrastructure, static crossings, and
  infrastructure-network analysis, not actor task journeys;
- `operations.py` applies authored navigation anchors, programs, and
  constraints through normal draft receipts;
- `activity_scenario.py` validates multi-actor presentation packages;
- `lean_motion.py` becomes a compatibility/presentation adapter and its
  rectangle-loop derivation is retired after NAV9; and
- `service.py` orchestrates repositories and APIs but does not calculate path
  geometry.

Frontend ownership:

- `facility_layout_editor.js` owns Plan path drawing, waypoint handles, snapping,
  and overlays;
- `facility_layout_session.js` owns atomic draft gestures, Undo, and Save
  integration;
- `facility_layout_workspace.js` owns tool state, path controls, findings, and
  visibility filters;
- `facility_layout_three_adapter.js` consumes accepted journey samples and
  never reconstructs planner geometry; and
- `facility_layout_transport.js` fetches packages by opaque ID and enforces
  revision identity.

This split is an exit requirement. Geometry must not migrate into chat parsing,
service orchestration, or the renderer.

### NAV0 - Baseline, Gold Paths, And Algorithm Freeze

Tasks:

1. Freeze the archived manual factory revision
   `a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088`.
2. Capture current heuristic operator and vehicle paths in Plan and 3D.
3. Record specific failure reasons per path: wrong service side, missed station,
   unnecessary loop, wrong lane, incomplete handoff, obstacle proximity, or
   unsupported assignment.
4. Inventory existing actors, route markings, station footprints, available
   service connectors, FIFO candidates, and published vehicle profiles.
5. Have the reference-layout author and product owner, Shadrack, review or
   manually author gold intent for the 12 currently moving existing operators,
   four current moving vehicles, and seven current handoffs. Record reviewer
   identity and revision; a substitute reviewer must be named in the receipt.
6. Add small synthetic fixtures for free-space routing, disconnected space,
   blocked service side, multi-stop loops, paired lanes, turnarounds, and
   unreachable handoffs.
7. Canonicalize, union, and expand the obstacle geometry in the 492-placement
   `Automation + Robot cells` scope. Record source polygons, post-union
   polygons, post-expansion vertices, candidate visibility pairs, accepted
   visibility edges, and graph bytes.
8. Benchmark visibility-graph A* and triangulated-navmesh A* on that frozen
   gold scope and the smaller synthetic fixtures.
9. Bind the reference machine to
   `tests/fixtures/facility_layout/performance/standard-hardware-profile.json`
   and record the exact Python, Shapely, GEOS, and browser versions used by the
   run.
10. Run 20 cold and 20 warm iterations for each performance metric and define
   the p95 method before implementation tuning.

Exit gates:

- source archive hash unchanged;
- every gold actor is an existing placement ID;
- every gold stop and handoff is tied to an authored or explicitly reviewed
  anchor;
- every rejected current path has a named reason;
- the Automation gold scope publishes post-union vertex and visibility-edge
  counts rather than using placement count as a complexity proxy;
- the buffer/canonicalization fixture is byte-identical on the frozen Windows
  runner and one pinned Linux/GEOS runner;
- one pedestrian local-routing algorithm is frozen by deterministic accuracy,
  reproducibility, and p95 evidence; and
- baseline screenshots and machine-readable gold artifacts are published.

### NAV1 - Contracts, Authority, And Migration

Tasks:

1. Freeze closed schemas for anchors, movement programs, manual constraints,
   navigation snapshots, journey solutions, and handoff programs.
2. Produce the field-level mapping against existing routes, route endpoints,
   placement connectors, zone anchors, process bindings, markings, and activity
   scenario fields.
3. Add `extensions.facilityNavigation` validation without weakening the base
   layout contract.
4. Define stable ID generation, canonical ordering, precision, and
   fingerprint inputs.
5. Introduce motion-package schema v2 with both generation `layoutRevision` and
   `validationContextFingerprint`. Freeze the projection, influence-region
   membership, computational epsilon, missing-record behavior, and v1 fallback.
   Full-revision-only packages remain conservative; NAV2 cannot enable
   navigation authoring until v2 fetch and stale tests pass.
6. Define actor-profile requirements separately for pedestrians and vehicles.
7. Define service-anchor promotion: inferred candidate -> user-confirmed
   authored anchor. Generators cannot self-promote.
8. Add an explicit `barrier` placement role. Barriers participate in free-space
   subtraction and may carry evidence, but never require or receive service
   anchors.
9. Freeze the deterministic geometry contract in section 6.1.1, including
   buffer parameters and cross-platform fixtures.
10. Add resource ceilings for graph nodes, edges, anchors, stops, candidate
   alternatives, and canonical bytes before allocation-heavy work.
11. Ensure Sage-facing schemas contain IDs and semantic constraints but no
   coordinates.

Exit gates:

- every behavior-bearing field has one owner and one canonical representation;
- no computed route is persisted as facility truth;
- generators cannot emit authored or approved authority;
- unknown fields and dangling identities fail closed;
- an unrelated navigation-anchor edit changes layout revision but does not
  invalidate a v2 package whose recomputed validation context is identical;
- a change to any projected source, or a current obstacle entering the frozen
  influence region, rejects playback before the first frame;
- every stale source revision or missing projected record is rejected before
  planning or playback;
- compact tool responses remain below 16,384 bytes; and
- assembled Facility context remains at or below the 9,600 estimated-token
  target.

### NAV2 - Manual Path Authoring And Gold-Correction Workflow

Tasks:

1. Add the Plan `Motion Path` tool and actor-first selection workflow.
2. Add waypoint, snap, loop, direction, lock, insert, delete, and reverse
   controls.
3. Add station-service, FIFO, entrance, crossing, lane, and turnaround anchor
   authoring.
4. Convert screen points to world points through the existing Plan projection;
   record them as `ui_authored`.
5. Validate complete overrides against the same deterministic geometry used by
   automatic routes.
6. Display guide paths and invalid segments distinctly from accepted routes.
7. Drive the exact existing GLB from the authored path in 3D preview.
8. Keep path visibility independent from actor visibility.
9. Integrate one gesture receipt, Undo, Save, reopen, and stale-edit handling.
10. Export authored constraints as reusable gold evaluation artifacts.

Exit gates:

- a user can author, edit, hide, preview, save, reopen, and undo one operator
  loop and one paired-lane vehicle route;
- the exact existing placement is animated and the stationary source visual is
  suppressed, with zero duplicate actor visuals;
- Plan and 3D agree on actor position and heading for the same normalized time;
- invalid geometry is visible but cannot be accepted as physically validated;
- chat cannot call the coordinate-authoring path; and
- the manual reference layout remains unchanged until explicit Save.

### NAV3 - Revision-Bound Navigation Snapshot Compiler

Tasks:

1. Add a dedicated navigation compiler module rather than expanding
   `lean_motion.py` or `circulation.py` into a mixed-responsibility module.
2. Compile local pedestrian free space from zone, shell, placement, exclusion,
   and authored-clearance geometry.
3. Compile directed pedestrian and vehicle infrastructure graphs from routes,
   markings, crossings, and connectors.
4. Canonicalize and union barrier and obstacle geometry before extracting
   visibility vertices; expose source and post-union complexity metrics.
5. Split route centerlines at exact intersections and retain stable derived
   node and edge IDs.
6. Bind entrances, station points, FIFO points, parking points, and turnarounds.
7. Compute components, dangling anchors, unreachable anchors, and direction
   facts.
8. Use spatial indices to bound visibility and obstacle queries.
9. Cache immutable snapshots by geometry-context fingerprint, actor class,
   profile revision,
   compiler version, and policy revision.
10. Return compact summaries through Sage and full packages through browser
   fetch.

Exit gates:

- identical inputs produce byte-identical snapshots and fingerprints;
- every node and edge traces to source geometry or a deterministic derivation;
- all free-space polygons lie inside allowed geometry and outside expanded
  obstacles;
- direction-aware components match independent fixtures;
- disconnected anchors return explicit findings rather than guessed bridges;
- post-union Automation-zone complexity and p95 remain inside NAV0's frozen
  graph and time ceilings;
- resource ceilings fail before excessive graph allocation; and
- the 45-zone, 827-placement reference compiles within the NAV0 frozen p95
  budget.

### NAV4 - Pedestrian Journey Planner

Tasks:

1. Resolve the selected existing operator's exact start placement.
2. Resolve authored station, entrance, and FIFO anchors.
3. Build the local visibility graph and connect it to authored pedestrian
   infrastructure.
4. Run deterministic A* for every ordered leg.
5. Support one-way, closed-loop, out-and-return, and task-cycle programs.
6. Preserve authored stop order and locked constraints.
7. Apply actor-footprint expansion and exact collision validation.
8. Simplify paths only with exact free-space line-of-sight proof.
9. Derive tangent-aligned headings for playback.
10. Return explicit missing-service-side, unreachable, constraint-conflict,
    stale, and resource outcomes.

Exit gates:

- 100% of accepted paths remain inside their traversable free space;
- 100% visit every required anchor in the authored order;
- closed loops end at the exact starting placement anchor;
- no route crosses a station footprint, protected region, or shell obstacle;
- no new operator placement is created;
- identical inputs produce identical centerlines and fingerprints;
- all NAV0 pedestrian gold cases pass product-owner review; and
- single-query p95 remains within the NAV0 frozen budget.

### NAV5 - Directed Vehicle Lane Planner

Tasks:

1. Compile distinct directional lanes from aisle geometry and pavement arrows.
   Call `motion_lanes.py` as the single lane-derivation implementation; NAV5
   must not duplicate its clustering, direction, offset, or qualification logic.
2. Add junction, lane-change, and turnaround nodes.
3. Run A* over the lane graph for requested stops.
4. Reuse the heading-lattice planner for local access and transitions.
5. Reuse exact vehicle-profile, load, reverse, grade, and swept-volume checks.
6. Support paired-lane return without reversing down the outbound lane.
7. Preserve route, placement, and marking identities.
8. Honor manual guide points and locked lane segments.
9. Refuse an unsupported vehicle profile or missing turnaround instead of
   creating a visually convenient maneuver.

Exit gates:

- every accepted lane edge follows its authored direction;
- every paired-lane return changes to the opposite lane at a validated
  transition;
- no accepted route uses an unmarked or unauthorized turnaround;
- every accepted vehicle journey passes the existing swept-volume validator;
- exact profile revision and source revisions are present;
- all NAV0 vehicle gold cases pass product-owner review; and
- single-vehicle p95 remains within the NAV0 frozen budget.

### NAV6 - Complete Task And Handoff Programs

Tasks:

1. Replace label/proximity-only operator assignment with explicit movement
   programs and reviewed process bindings.
2. Compile each handoff into two actor-to-FIFO journeys plus one material edge.
3. Require distinct participant identities where the handoff requires two
   operators.
4. Validate source/output and target/input FIFO roles.
5. Bind the material identity when available; otherwise disclose it as unknown.
6. Preserve authored process sequence independently from route-distance
   optimization.
7. Build complete home -> work -> FIFO -> return cycles.
8. Keep process timing unknown unless a controlled source provides it.
9. State explicitly in schema, UI, and qualification that sequence does not
   imply timing or simultaneous participant presence.

Exit gates:

- all seven manual-reference handoffs have two valid participant routes and no
  dangling endpoint;
- every participant is an existing placement;
- every operator returns to the exact authored home or next task anchor;
- material paths are never rendered as operator walking;
- no handoff is labelled complete when one participant journey failed; and
- topology, identity, and source revisions are machine-verifiable.

### NAV7 - Multi-Actor Playback And Conflict Diagnostics

Tasks:

1. Assemble accepted journey IDs into the existing bounded activity scenario.
   Every accepted journey is serialized through `motion_package.py`; NAV7 does
   not introduce a parallel coordinate-carrying playback artifact.
2. Keep one shared Plan/3D clock and exact existing GLB borrowing.
3. Loop closed programs and correctly reverse or transition open programs.
4. Expose per-class path visibility and actor focus controls.
5. Compute static path intersections and sampled actor-to-actor proximity.
6. Do not stagger start times or alter trajectories to conceal actor overlap.
   The same deterministic presentation clock may use an authored phase offset,
   but a generated collision-avoidance offset is prohibited.
7. Separate any authored presentation offset from every process timing field.
8. Warn when independently valid paths visually conflict; do not call them
   operationally unsafe without authority.
9. Keep fixed machines stationary unless revision-bound kinematic evidence
   exists.
10. Compile each immutable navigation snapshot once per exact geometry-context,
    actor-class/profile, compiler, and policy key, then reuse it for every actor
    sharing that key. The bounded scenario budget does not permit one full
    snapshot compilation per actor.

Exit gates:

- current 20-actor scenario ceiling is enforced before package construction;
- every moving actor borrows one existing placement and leaves no duplicate
  source visual;
- 2D and 3D pose agreement is exact at sampled checkpoints;
- operator orientation follows path tangent within the frozen numeric
  tolerance;
- path overlays may be hidden without stopping playback;
- no layout operation, dirty state, or Save occurs during playback; and
- independently valid paths are never rescheduled merely to avoid a visible
  overlap;
- instrumentation proves snapshot compilations equal the number of distinct
  frozen context keys rather than the actor count; and
- any visual conflict is reported without a safety, capacity, or staffing
  claim.

### NAV8 - Sage Intent And Local Replanning

Tasks:

1. Add the bounded tool surface from section 8.
2. Add deterministic intent routing before the general model fallback.
3. Support semantic requests such as:

   - route the existing operator in Cell A through the three authored service
     points and then to FIFO A;
   - use the east pedestrian walkway and avoid the inspection exclusion;
   - send the existing forklift from Receiving to Finished Goods and return on
     the opposite marked lane;
   - keep the segment beside Workbench 3 fixed and replan the rest;
   - show why Operator 07 cannot reach its assigned FIFO; and
   - compare the east and west routes by distance and turn count only.

4. Add clarifications for ambiguous actor, missing anchor, missing task order,
   absent vehicle profile, and conflicting constraints.
5. Add deterministic refusals for model-authored coordinates, invented
   clearances, unspecified vehicles, and safety/throughput/optimality claims.
6. Replan only the selected journey in release 1 while preserving unrelated
   accepted packages.
7. Present one cumulative semantic diff if navigation intent is edited.

Exit gates:

- at least 95% exact intent classification on a frozen held-out corpus;
- 100% deterministic refusal of unauthorized coordinates and unsupported
  engineering claims;
- no hidden coordinates in any Sage-facing request or response;
- unpredictable but valid follow-ups preserve stable actor and program IDs;
- local replan leaves unrelated movement programs byte-identical; and
- exact browser conversations succeed without provider-dependent geometry.

### NAV9 - Evaluation, Hardening, And Promotion

Implementation record: `docs/facility-layout-navigation-nav9-implementation-report.md`.
All implementation, deterministic, performance, persistence, and browser gates
pass. The reference acceptance receipt remains intentionally pending and no
production authority was granted automatically.

Tasks:

1. Add unit, property, integration, API, browser, stale-state, Save, Undo, and
   accessibility suites.
2. Randomize polygonal cells, obstacle sets, actors, stops, and disconnected
   components across supported bounds.
3. Test all algorithms against exact independent geometric assertions.
4. Test cold/warm performance on the NAV0 frozen machine.
5. Capture Plan and 3D screenshots in light/dark and desktop/mobile viewports.
6. Run full manual-reference acceptance with the 12 NAV0-reviewed existing
   operators, four NAV0-reviewed existing vehicles, seven NAV0-reviewed
   handoffs, paired vehicle lanes, and every reviewed station visit. Any
   unreachable gold case must return its frozen refusal code rather than being
   omitted from the scenario.
7. Add feature flags in dependency order: contract -> manual authoring ->
   snapshot -> pedestrian -> vehicle -> handoff -> multi-actor -> Sage write.
8. Retain the current heuristic scenario behind a prototype-only flag until
   migration evidence passes.
9. Remove the rectangle-loop derivation from production reachability. Either
   delete it or retain it only in an isolated test-fixture module that cannot be
   selected by server, Sage, API, UI, or feature-flag paths.

Exit gates:

- all automatic failure conditions in section 12 are tested;
- 100 randomized accepted routes satisfy containment and non-intersection;
- every rejected fixture returns the expected stable code;
- reference-layout Plan/3D evidence is nonblank and visually reviewed;
- 30 FPS playback remains sustained at 1920 x 1080 for the bounded scenario;
- snapshot, pedestrian query, vehicle query, and full-scenario p95 stay within
  the NAV0 frozen budgets;
- saved layout and navigation intent survive reopen byte-equivalently;
- no production flag is enabled until the named reviewer signs the reference
  acceptance receipt; and
- a call-path audit proves the legacy rectangle-loop heuristic is unreachable
  from every production entry point.

## 10. Phase Dependencies And Milestones

```text
NAV0 -> NAV1 -> NAV2 -------------------------------> NAV9
                |
                +-> NAV3 -> NAV4 -----+
                          NAV5 -----+  |
                                    v  v
                                    NAV6 -> NAV7 -> NAV8 -> NAV9
```

NAV4 and NAV5 may run in parallel after NAV3 freezes the snapshot contract.
NAV2 can provide user value and gold-path collection before automatic planning
is complete.

Milestones:

- **Milestone A: User-controlled motion** - NAV0 through NAV2. Users can draw
  and validate exact paths for existing actors in Plan and preview them in 3D.
- **Milestone B: GPS-like single-actor routing** - NAV3 through NAV5. Operators
  and vehicles receive deterministic routes from semantic destinations.
- **Milestone C: Complete factory handoffs** - NAV6 and NAV7. Existing actors
  perform complete, identity-bound work and FIFO cycles.
- **Milestone D: Sage-controlled navigation** - NAV8 and NAV9. Users express
  intent while Sage invokes bounded deterministic tools and preserves manual
  overrides.

## 11. Evaluation Matrix

Minimum fixed cases:

1. One operator, one machine, one valid service side.
2. One operator with the nearest service side blocked.
3. One operator, ordered multi-station loop.
4. Order-independent stops below the exact optimization threshold.
5. Disconnected pedestrian regions.
6. A guide point that forces a longer valid route.
7. A locked manual segment that makes the route infeasible.
8. An operator path that reaches one FIFO and returns home.
9. A two-operator complete FIFO handoff.
10. A missing second handoff participant.
11. One-way forklift route.
12. Two-way boulevard with separate outbound and return lanes.
13. Missing vehicle turnaround.
14. Vehicle turning-radius refusal.
15. Vehicle swept collision between graph nodes.
16. Exact profile revision changes after planning.
17. Layout changes after planning.
18. Existing actor renamed but identity preserved.
19. Existing actor deleted while referenced.
20. Two actors assigned to the same exclusive movement program.
21. Manual override in Plan with exact 3D playback.
22. Hide all paths while actors continue moving.
23. Unsupported request for a safe or OSHA-compliant route.
24. Chat request containing world coordinates.
25. Full manual-reference factory.

Held-out language must include commands, questions, corrections, pronouns,
negation, incomplete requests, and multi-turn changes. Cases used to implement
intent rules cannot be counted as held-out acceptance cases.

## 12. Automatic Failure Conditions

The program fails regardless of aggregate score if InspectorPro:

- creates or clones an actor to satisfy a movement request;
- renders both a moving actor and its stationary source placement;
- accepts Sage-authored coordinates;
- silently chooses an unknown service side or task sequence;
- routes through an exact obstacle or outside traversable geometry;
- sends a vehicle against an authored lane direction;
- turns a vehicle where no validated transition exists;
- claims vehicle fit without an exact profile revision;
- marks a handoff complete with a missing participant or dangling FIFO;
- displays stale route evidence as current;
- accepts a snapshot or journey whose validation-context source revision moved;
- produces different canonical obstacle geometry, graph IDs, or accepted paths
  on pinned supported platforms for identical inputs;
- staggers generated actor start times or changes paths solely to hide a visual
  overlap;
- changes the saved layout during route planning or playback;
- breaks exact Undo for an authored path edit;
- claims safety, regulatory compliance, throughput, staffing, or operational
  optimality without controlled evidence; or
- allows Plan and 3D to disagree about actor identity, position, or heading.

## 13. Performance Machine And Budgets

The named reference machine is the measured fixture
`tests/fixtures/facility_layout/performance/standard-hardware-profile.json`:

```text
machine label       dell-15-dc15250-standard
machine             Dell 15 DC15250
operating system    Microsoft Windows 11 Home 10.0.26200, build 26200
CPU                 13th Gen Intel Core i7-1355U
cores               10 physical, 12 logical
RAM                 16,849,256,448 bytes
GPU                 Intel UHD Graphics, 2,147,479,552 reported adapter bytes
display             1920 x 1080 at 120 Hz
Python              CPython 3.14.0
Shapely             2.1.2
GEOS                 3.13.1
browser baseline    Microsoft Edge 150.0.4078.105
```

NAV0 captures a fresh environment receipt and records any browser or driver
change beside the result. A result from a different machine or dependency set
is comparative evidence, not a pass against this machine-bound gate.

NAV0 freezes final budgets before planner implementation. The initial targets
for the current 45-zone, 827-placement reference on the named machine are:

| Operation | Proposed p95 ceiling | Sample definition |
|---|---:|---|
| Cold navigation snapshot compile | 5.0 s | 20 isolated runs |
| Warm snapshot lookup | 100 ms | 20 runs |
| Local pedestrian query | 1.5 s | 20 accepted and refused cases |
| Single vehicle query | 5.0 s | 20 accepted and refused cases |
| Complete bounded 16-actor scenario | 60 s | 20 end-to-end runs reusing one compiled snapshot per actor class/profile context |
| Browser playback | 30 FPS | 60 s at 1920 x 1080 |

These are engineering targets, not claims about travel time. If NAV0 evidence
shows one is unrealistic, the plan must revise the number before implementation
tuning rather than quietly weakening the exit gate afterward.

## 14. Migration And Compatibility

1. Current facility routes and floor markings remain unchanged.
2. Existing motion packages remain readable until their normal TTL expires.
3. Current `facility-lean-motion-v3` and `facility-activity-scenario-v6` remain
   supported during the compatibility window.
4. Current motion-package v1 remains full-layout-revision-bound. Motion-package
   v2 introduces the narrower validation-context gate before NAV2 authoring is
   enabled; v1 never inherits v2 behavior implicitly.
5. New scenarios declare whether each path source is `authored_constraint`,
   `deterministic_navigation`, or `legacy_heuristic`.
6. Legacy heuristic paths cannot be promoted to controlled navigation.
7. During the compatibility window before NAV9, the legacy heuristic is
   available only through an explicit prototype-fixture flag and cannot be
   promoted to controlled navigation.
8. NAV9 removes every production call path to that heuristic. An isolated
   fixture implementation may remain only for regression comparison and must
   be unreachable from server, Sage, API, UI, and production feature flags.
9. No migration writes computed paths into saved layouts.

## 15. Principal Risks

### Missing service semantics

Shortest-path algorithms cannot determine where work occurs on a machine.
Mitigation: require asset service connectors or a reviewed placement-specific
anchor. Treat proximity candidates as proposals only.

### False use of the word optimal

A* finds a shortest path in its frozen graph, not the best manufacturing
system. Mitigation: report the exact metric and graph scope. Reserve
`operationally optimal` for separately authorized analysis.

### Multi-agent overclaim

Independent valid paths may conflict in time. Mitigation: separate spatial
validity, zero-offset shared-clock presentation, explicitly user-authored
presentation offsets, and operational traffic analysis in the schema and UI.
Never generate a timing offset to conceal overlap.

### Graph explosion

Visibility graphs can grow quadratically with obstacle vertices. Mitigation:
spatially scope local queries, use STRtree filtering, enforce pre-allocation
ceilings, cache snapshots, and retain a measured navmesh alternative.

### Two sources of truth

Persisting both facility geometry and generated paths would drift. Mitigation:
persist infrastructure and intent only; regenerate derived paths by revision.

### Manual override becoming invisible tribal knowledge

A user-drawn path could correct a route without explaining why. Mitigation:
require an optional reason and preserve locked segment, author, revision, and
source references in the constraint receipt.

### Small layout changes invalidating everything

Motion-package v1 remains conservatively full-revision-bound for compatibility,
but durable navigation authoring is not enabled against v1. NAV1 introduces the
v2 validation-context projection and proves parity, influence-region membership,
missing-source refusal, and stale-safety behavior before NAV2 is enabled. Any
projected source change still invalidates the result; unrelated navigation
intent does not.

## 16. Review Questions For Claude

1. Is `extensions.facilityNavigation` the right durable boundary, or can the
   existing route, anchor, connector, and process-binding contracts represent
   all behavior without loss?
2. Does the plan preserve one source of truth between facility infrastructure,
   movement intent, derived graph, and journey solution?
3. Is a footprint-expanded visibility graph plus A* the correct initial
   pedestrian planner for the current geometry and scale?
4. Should a triangulated navmesh be frozen immediately instead, and what exact
   dependency would own it?
5. Are asset-definition service connectors and placement-specific authored
   anchors sufficient to eliminate proximity-based service-side guessing?
6. Does direct Plan pointer authoring correctly satisfy coordinate ownership
   while keeping chat coordinates forbidden?
7. Are vehicle lane graph, heading lattice, and swept validation divided at the
   correct boundary?
8. Is the validation-context projection sufficiently complete to replace
   full-layout-revision invalidation without admitting stale geometry?
9. Does NAV6 distinguish handoff topology from unsupported timing strongly
   enough?
10. Is the multi-agent boundary honest, including the prohibition on generated
    overlap-avoidance offsets and the labelling of user-authored presentation
    offsets as non-operational timing?
11. Are the proposed performance budgets and 20-run p95 samples meaningful on
    the frozen reference machine?
12. Which current schemas or modules would this duplicate rather than extend?
13. Are the automatic failure conditions complete?
14. Can NAV2 ship independently without creating a migration dead end for NAV3
    through NAV6?

## 17. Definition Of Done

The direction is complete when, on the archived manual factory:

- a user can manually author and edit a path in Plan and see the exact same
  existing actor follow it in 3D;
- Sage can route an existing operator through reviewed station anchors and a
  FIFO point without receiving or producing coordinates;
- Sage can route an existing forklift out and back on the correct separate
  directional lanes using an exact vehicle profile;
- all 12 NAV0-reviewed reference operator cycles visit every required anchor in
  authored order and return to the authored endpoint; any intentionally
  unreachable evaluation case returns its exact refusal code and is never
  silently omitted from an accepted scenario;
- all seven reference handoffs are topologically complete;
- no actor is added, cloned, or shown twice;
- every accepted route is deterministic, revision-bound, and geometrically
  validated;
- manual constraints survive Save/reopen and retain exact Undo;
- Plan and 3D remain synchronized and visually reviewed;
- stale, unreachable, ambiguous, and unauthorized requests fail with specific
  findings; and
- the UI clearly states that playback is route evidence and presentation, not
  proof of safety, throughput, staffing, or regulatory compliance.
