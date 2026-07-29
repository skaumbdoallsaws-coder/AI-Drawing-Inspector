# InspectorPro Industrial Spatial Layout Platform

Revision: 2

Status: READY FOR PHASE APPROVAL - PLANNING ONLY

Date: 2026-07-28

Revision 2 incorporates the final independent architecture review. It adds
first-class shell, policy, vehicle, utility-network, authorization, stable-ID,
bounded-observation, evidence-authority, and revision-envelope contracts. It
also makes the backend the authoritative spatial engine and moves the first
complete vertical-slice gate through deterministic constraints.

Review state: six specialist reviews plus two independent final architecture
reviews completed with no unresolved implementation blockers.

Related product vision:

- `docs/industrial-layout-platform-vision.md`

This document is the proposed implementation and release contract for turning
InspectorPro's current Facility Layout viewer into an editable industrial
spatial-planning environment for warehouses and manufacturing cells.

No implementation is authorized by this document alone. Each phase requires an
explicit start decision after the prior checkpoint has been independently
verified.

## 1. Executive decision

InspectorPro should build one authoritative `FacilityLayoutDocument` edited by
two synchronized views:

```text
FacilityLayoutDocument
    |
    +-- Top-down plan view
    |      Precision authoring for zones, dimensions, placement, and routes
    |
    +-- Three.js 3D view
           Height, orientation, access, clearance, and visual verification
```

The top-down view is the primary precision surface. The 3D view is a full-bleed
engineering viewport over the same state, not a separate scene file or a second
layout model.

The Process Map and Facility Layout remain separate domain assets:

```text
Process Map
    What must happen, in what order, and with which requirements

Facility Layout
    Where it happens, which resources perform it, and how material moves
```

The Facility Layout owns revision-bound references to Process Map nodes and
edges. It does not copy process topology or write reciprocal spatial fields into
the Process Map.

The implementation must preserve this authority split:

```text
Sage:
    Intent, resource roles, alternatives, assumptions, and tradeoffs

Deterministic InspectorPro code:
    Coordinates, transforms, snapping, collision, clearance, containment,
    connector compatibility, route geometry, revisions, and exact diffs

User:
    Review assumptions, resolve missing engineering facts, and approve writes
```

Sage never authors final coordinates, transforms, route geometry, camera
values, or safety verdicts.

## 2. Product outcome

The first useful product is not autonomous plant design. It is a dependable
manual spatial editor that can produce and revise a credible first layout
quickly.

The first vertical slice is:

1. Open a dimensioned workcell floor.
2. Draw one workcell zone.
3. Browse a SolidWorks-style industrial asset tree.
4. Drag one normalized machine and one normalized rack or workstation into the
   zone.
5. Preview each placement at the correct world position.
6. Snap to a dimensioned grid and rotate in controlled increments.
7. Detect footprint collisions and zone containment errors.
8. Move, duplicate, lock, delete, undo, and redo.
9. Switch between top and 3D views without changing saved transforms.
10. Save with optimistic concurrency and reopen the same layout exactly.

Sage, utilities, forklift motion, full-cell optimization, and simulation are not
part of this first slice.

The first end-to-end manufacturing-cell milestone is an automated CNC tending
cell using a subset of the current machine library:

- CNC lathe or Haas ST30
- SA6 or ABB robot
- Bar loader
- Guarding gate
- Workstation
- Material cart
- Operator zone
- Forklift access route

This cell exercises placement, zones, clearances, connectors, routes, process
bindings, and agent alternatives without requiring a whole plant.

## 3. Non-goals

The initial platform does not:

- Replace a licensed facility, safety, electrical, fire-code, or industrial
  engineering review.
- Treat an AI-generated layout as production approved.
- Infer process order from spatial proximity.
- Treat mates or assembly structure as proof of manufacturing sequence.
- Use raw CAD triangles as the collision or clearance authority.
- Load every source CAD model at full detail into the browser.
- Persist browser pixels, camera coordinates, or display-root offsets.
- Allow arbitrary non-uniform scaling of production equipment.
- Automatically move manual or locked placements.
- Simulate operators, robots, forklifts, queues, or throughput before a
  validated domain engine exists.
- Publish third-party machine assets without verified redistribution rights.
- Rewrite the existing Facility Layout semantic fixture as if its rough
  envelopes were authoritative safety geometry.

## 4. Verified current state

Six read-only specialist reviews covered the current Three.js viewer, raw
machine library, deterministic geometry, Process Map transaction model,
performance, and release testing.

### 4.1 Current Facility Layout

The existing Facility Layout is an analysis and visualization workflow:

- It loads one static semantic JSON document through `server.py`.
- It exposes read-only semantic, capacity, route, and layout-analysis endpoints.
- It mounts a hard-coded `Assem3_colored.glb` in `static/index.html`.
- It derives four warehouse operating zones in browser code.
- It highlights rack groups and forklifts.
- It draws floor overlays and route polylines.
- It computes deterministic rack-capacity and aisle-route estimates.

It does not provide:

- General layout identity
- Revisioned layout storage
- Placement operations
- Zone authoring
- Asset drag/drop
- 2D/3D synchronized editing
- Ghost placement proposals
- Facility-specific undo and redo
- Trusted server-side layout state for Sage
- Facility Builder writes

The current facility semantic document is version `facility-layout-semantic-v0.2`.
Its rack envelopes are explicitly rough. Its 24-point coordinate alignment
check has a maximum residual of approximately 0.0613 m. That is acceptable for
the current explanatory demo but not for safety or clearance validation.

### 4.2 Current 3D payload

`generated/training/facility-layout/Assem3_colored.glb` is 327,184,996 bytes,
about 312 MiB.

The specialist binary audit found approximately:

- 11.75 million vertices
- 3.92 million triangles
- 245 meshes
- 245 materials
- No occurrence transforms or mesh reuse in the final GLB
- Five repeated shape signatures covering the 245 meshes

The current loader downloads the complete buffer and copies the GLB binary
chunk. Combined CPU and GPU memory can approach 1 GB during load. This artifact
must become the `legacy-heavy` failure/fallback fixture. It must not be the
automatic editor payload.

### 4.3 Current viewer limitations

Important implementation constraints found in `static/index.html`:

- Camera Fit currently recenters by mutating the model group's position.
- Routes remain visually aligned because they are children of the same shifted
  model root.
- Editable world geometry cannot use this behavior.
- Selection is based on mesh-name maps rather than stable placement IDs.
- Rendering runs continuously.
- Pixel ratio is not capped.
- The guided GLB cache is unbounded.
- Teardown does not fully own all controls, observers, caches, and scene assets.
- No scalable instance-aware picking, LOD system, or facility spatial index
  exists.

Fit in the new editor must change only the camera and controls target. It must
never change the facility root or a placement transform.

### 4.4 Current machine library

The raw library at:

```text
C:\Users\might\OneDrive\Desktop\machine library
```

contains:

- 276 files
- 262 `SLDPRT` files
- 12 `SLDASM` files
- 2 metadata text files
- 109,733,622 source bytes, about 104.65 MiB
- 38 top-level candidates
- About 22 logical asset families after consolidating workstation variants

Useful initial categories include:

- CNC machines and lathes
- Industrial robots
- Bar loader
- Forklift
- Guarding
- Workstations
- Cart
- Operator model
- Oven, saw, and EDM equipment

The source library is not yet a usable runtime catalog. It lacks normalized
coordinates, floor anchors, footprint proxies, clearance envelopes,
connectors, utilities, web LODs, thumbnails, and sufficient licensing records.

Several folders contain multiple assemblies. Root selection must use an
assembly-reference graph and operator review when ambiguous. Filename size or
folder name is not a reliable root rule.

`User Library-1D601.sldprt` is unidentified and remains quarantined until its
identity and provenance are resolved.

### 4.5 Reusable Process Map foundation

The Process Map already proves these patterns:

- Stable source occurrences separate from placed canvas nodes
- World coordinates independent from pan and zoom
- `auto`, `manual`, and `locked` position ownership
- Deterministic spatial compilation and diagnostics
- Spatial indexes and bounded candidate scoring
- Obstacle-aware routing and route fingerprints
- Pure domain operations
- Exact diffs
- Undo and redo
- Canonical serialization and SHA-256 revisions
- Atomic writes and backups
- Proposal, approval, idempotency, CAS apply, and receipts
- Trusted server-side state and evidence
- Model-authored coordinate rejection
- Complete ghost previews
- One approval and one atomic commit

These concepts are reused. Their current Process Map-specific implementation is
not copied into a second Builder.

### 4.6 Existing facility algorithms worth retaining

The following remain useful as bounded components:

- Kabsch alignment, GLB hashing, scale checks, and coordinate matrices in
  `tools/facility_coordinate_resolver.py`
- Deterministic aisle-network Dijkstra in `tools/facility_routing.py`
- Rack capacity estimates in `tools/facility_capacity_query.py`
- Semantic extraction in `tools/facility_layout_semantics.py`
- Lightweight proxy generation in `tools/facility_semantic_glb.py`
- Assembly scene mounting, highlighting, floor overlays, route rendering, and
  labels in `static/index.html`

The existing Dijkstra engine remains an aisle-topology and distance-estimation
tool. It is not a forklift swept-volume validator.

## 5. Governing architecture

### 5.1 Domain separation

Use three authoritative asset classes:

```text
IndustrialAssetDefinition
    Reusable source equipment, geometry, capabilities, and placement rules

FacilityLayoutDocument
    Zones, placed asset occurrences, routes, utilities, and process bindings

ProcessMapDocument
    Product occurrences, operations, stages, precedence, and requirements
```

Deleting a placement never deletes its source asset. Editing a source asset
revision never silently mutates an existing placement.

### 5.2 Shared transaction control plane

Extract the generic transaction behavior currently embedded in Process Map
Builder:

```text
Domain proposal
    -> deterministic validation
    -> exact diff
    -> explicit approval
    -> bound approval token
    -> reload current asset
    -> regenerate proposal
    -> compare exact diff
    -> CAS atomic save
    -> canonical execution receipt
```

The shared kernel owns:

- Proposal lifetime
- Approval lifetime
- User and session binding
- Idempotency and replay protection
- Revision and dependency bindings
- Exact diff hash binding
- Receipt creation and resolution
- Expiry and cancellation

Domain adapters own:

- Asset loading
- Operation validation
- Proposal generation
- Diff generation
- Domain persistence
- Receipt details

The Process Map adapter must remain behaviorally identical throughout the
extraction. Every existing Process Map Builder and Playwright test is a frozen
regression gate for this refactor.

### 5.3 Frontend module boundary

Do not add the editor as another large block inside `static/index.html`.

Target modules:

```text
static/facility_layout_editor.js
static/facility_layout_plan_view.js
static/facility_layout_renderer.js
static/facility_layout_spatial.js
static/facility_layout_spatial_worker.js
static/facility_layout_asset_tree.js
```

`static/index.html` should mount the editor, supply application services, and
host shared ribbon/shell integration. Domain state and interactions belong in
the modules above.

### 5.4 Backend module boundary

Target modules:

```text
ai_inspector/facility_layout/
    __init__.py
    schema_v1.py
    repository.py
    operations.py
    geometry.py
    spatial.py
    validate.py
    routing.py
    state.py
    semantic_plan.py
    builder_adapter.py

ai_inspector/industrial_assets/
    __init__.py
    schema_v1.py
    repository.py
    discover.py
    root_resolver.py
    normalize.py
    web_artifacts.py
    validate.py

ai_inspector/transactions/
    kernel.py
    policy.py
    receipts.py
```

The exact names may follow existing conventions, but domain ownership must stay
this clear.

### 5.5 Spatial authority

The Python backend is the sole authority for:

- Geometry normalization
- Constraint validation
- Candidate generation and ranking
- Route and utility-network validation
- Proposal regeneration
- Commit eligibility

Browser-side JavaScript may provide immediate advisory ghosts, coarse overlap
feedback, picking, and rendering. It must never become a second authority.
Every save and proposal is revalidated by the backend against the current
revision-bound inputs. If browser and backend results disagree, the backend
result wins and the browser replaces its advisory result.

Python/JavaScript parity tests cover shared coordinate conversions, geometry
primitives, fingerprints, and display contracts. They do not imply two
co-equal planning engines.

### 5.6 Stable generated identity

Stable IDs are part of the exact-diff contract:

- IDs for manually created committed objects are assigned once by the server.
- `dependencyFingerprint` is the canonical hash of the base layout revision,
  exact referenced asset-definition revisions, shell revision, policy revision,
  vehicle-profile revisions, Process Map revision, spatial-engine version,
  router version, and obstacle fingerprint.
- `proposalId` is deterministically derived from `layoutId`, `baseRevision`,
  `proposalType`, `semanticPlanHash`, and `dependencyFingerprint`.
- Proposal-generated placement, zone, zone-anchor, route, utility-network,
  network-node, network-segment, and process-binding IDs are deterministic
  functions of `proposalId` and the plan-local object ID.
- Generated IDs use stable type prefixes such as `fp-`, `pl-`, `zn-`, `za-`,
  `rt-`, `un-`, `nn-`, `ns-`, and `pb-`.
- Regenerating the same proposal against the same dependencies produces the
  same IDs.
- Changing a plan-local object's meaning produces a different ID rather than
  silently reusing an unrelated identity.

Canonical diffs include all object IDs. Only server-owned timestamps and the
derived content revision are excluded from diff hashing. Preview, approval,
regeneration, apply, and receipt must therefore agree on exact identities as
well as geometry and properties.

### 5.7 Authorization boundary

The authenticated principal, not a URL path or browser field, determines the
tenant and sites that may be accessed. Every catalog, layout, proposal,
approval, receipt, source-shell, policy-set, and vehicle-profile operation is
authorized server-side.

Initial roles:

```text
viewer:
    Read published catalog assets and permitted layouts

editor:
    Create and edit permitted layouts and proposals

approver:
    Approve and apply exact proposals

catalog_curator:
    Intake, review, publish, deprecate, and quarantine assets

authority_curator:
    Create, review, publish, deprecate, and archive facility shells, policy
    sets, and vehicle profiles for permitted sites

admin:
    Manage site policy, principals, and recovery operations
```

Local single-user mode maps to an explicit local principal with a configured
local site. It does not bypass the same authorization checks.

## 6. Coordinate and transform contract

### 6.1 Canonical facility frame

All persisted spatial geometry uses:

- Meters
- Right-handed coordinates
- `+Y` vertical
- `X/Z` floor plane
- XYZW quaternion order
- Finite numeric values only

Every layout stores a named datum and floor elevation.

### 6.2 Asset normalization

Every asset-definition revision stores:

- Native source units
- Source handedness and up axis
- `sourceToCanonical` matrix
- Canonical local origin
- Floor anchor
- Default facing vector
- Allowed mounting surfaces
- Canonical bounds

The rendered placement matrix is:

```text
facilityWorld
    * placementTransform
    * assetNormalization
    * sourceGeometry
```

These factors must remain inspectable rather than being baked into one
unexplained matrix.

### 6.3 Placement transform

Initial floor placements allow:

- X and Z translation
- Y derived from floor or mounting surface
- Yaw rotation
- Uniform scale of exactly `1`

Roll, pitch, and scaling are prohibited unless the asset's mounting contract
explicitly allows them.

### 6.4 Camera contract

Camera state is user/session state, not facility geometry.

Fit, orbit, pan, zoom, pane resize, browser resize, and device pixel ratio must
not alter:

- Zone coordinates
- Placement transforms
- Connector positions
- Route points
- Clearance volumes

Top-view display conversion is:

```text
world X/Z <-> plan-view CSS X/Y
```

Only the conversion result uses screen pixels.

### 6.5 Numeric gates

- Pure transform serialization and Python/JavaScript parity: error `<= 1e-6 m`
- Exact CAD-derived source-to-canonical alignment target: `<= 0.001 m`
- Assets above the alignment target cannot become `placement_ready` until
  reviewed.
- The current facility fixture's 0.0613 m residual is marked demo-only and
  cannot support clearance claims.

### 6.6 Canonical geometry normalization and limits

Schema validation enforces finite values and these initial hard caps:

| Field | Limit |
| --- | ---: |
| Placements per layout | 5,000 |
| Zones per layout | 500 |
| Vertices per zone | 256 |
| Total zone vertices | 50,000 |
| Routes per layout | 2,000 |
| Points per route | 2,048 |
| Total route points | 250,000 |
| Utility networks per layout | 100 |
| Utility-network nodes per network / total | 2,000 / 20,000 |
| Utility-network segments per network / total | 4,000 / 40,000 |
| Points per utility segment / total | 2,048 / 250,000 |
| Process bindings per layout | 5,000 |
| Zone anchors per zone / total | 128 / 10,000 |
| Connectors per asset definition | 128 |
| Clearance envelopes per asset definition | 64 |
| Requirements or evidence records per target | 64 each |
| Deterministic rules per policy set | 5,000 |
| Shell geometric objects / total vertices | 100,000 / 1,000,000 |
| Per-object metadata | 16 KiB canonical JSON |
| Extension fields per object / total extension payload | 32 / 5 MiB |
| Canonical JSON nesting depth | 32 |
| Canonical Facility Layout document | 100 MiB |
| Stable ID length | 128 characters |
| Label length | 120 characters |
| Description or note length | 2,000 characters |
| Absolute world coordinate | 1,000,000 m |

Canonicalization rules:

- Polygon winding is counterclockwise in the X/Z floor plane.
- Polygon closure is implicit; a duplicate closing point is rejected.
- Polygons require at least three distinct vertices and may not self-intersect.
- Meter-based positions, dimensions, and distances round half-to-even to six
  decimal places before hashing.
- Quaternion components round half-to-even to nine decimal places, must be
  normalized within `1e-9`, and are renormalized once before serialization.
- Quaternion sign is canonical: `w` is positive; when `w` is zero, the first
  nonzero component in X/Y/Z order is positive.
- Other physical scalars use the field scale frozen in the spatial contract;
  an undeclared floating-point scale is a schema error.
- `-0` becomes `0`.
- Nonuniform and negative placement scale are rejected in v1.
- Empty strings are normalized or rejected according to field semantics, never
  used as stable IDs.

## 7. Industrial asset catalog

### 7.1 Storage layout

```text
generated/industrial_assets/
    <tenantId>/
        registry.json
        assets/<assetId>/
            definitions/<assetDefinitionRevision>/
                asset.json
                source_binding.json
                geometry.json
                placement.json
                capabilities.json
                provenance.json
                proxies/collision.glb
                proxies/footprint.json
                proxies/clearances.json
            render_bundles/<renderBundleRevision>/
                manifest.json
                visuals/lod0.glb
                visuals/lod1.glb
                visuals/lod2.glb
                visuals/thumbnail.webp
                proxies/overview.glb
    _common/
        registry.json
        assets/...
```

The registry is atomically updated last. Directory scanning may detect drift,
but must not decide authoritative revisions. Registry records own the mutable
published-definition and default-render-bundle pointers plus:

```text
ownerTenantId
visibility: private | site_shared | tenant_shared | common
allowedSiteIds
publishedAssetDefinitionRevision
defaultRenderBundleRevision
```

Asset-definition and render-bundle directories are immutable. Changing the
default render bundle updates authorized registry metadata; it never mutates or
rehashes an asset definition.

### 7.2 Identity and revisions

- `assetId`: immutable server-assigned identity
- `sourceRevision`: hash of source files, configuration, and extraction inputs
- `assetDefinitionRevision`: hash of canonical frame, semantic capabilities,
  connectors, collision proxies, footprints, and clearances
- `renderBundleRevision`: hash of compatible LOD, thumbnail, texture, and
  overview-render artifacts
- `placementId`: independent identity for one occurrence in a layout

Layouts bind exact `assetDefinitionRevision` values. They resolve a compatible
render bundle at read time. Publishing a better LOD or thumbnail does not
invalidate a layout or open proposal when its asset definition is unchanged.
Likewise, an unrelated catalog publication does not invalidate layouts that do
not reference it.

Repeated placements of the same asset definition have distinct `placementId`
values and share render prototypes when possible.

### 7.3 Asset definition

Each asset-definition revision includes:

```text
Identity:
    assetId, assetDefinitionRevision, sourceRevision, displayName, familyId,
    variantId, category, tags

Lifecycle:
    draft, reviewed, published, deprecated, quarantined

Coordinate frame:
    source units, sourceToCanonical, local origin, floor anchor, facing

Geometry:
    AABB, OBB, footprint polygons, height interval, selection bounds

Rendering:
    compatible render-bundle schema and geometry-interface constraints

Collision:
    2.5D footprint, vertical interval, compound box or convex proxies

Loading:
    transport, installed, and operating mass; center of gravity; support and
    contact points; contact areas or point loads; dynamic load factors;
    anchoring assumptions; evidence per value

Clearances:
    operating, loading, service, maintenance, door swing, safety, operator

Connectors:
    material input/output, conveyor, foundation, row/bay, utility, process

Utilities:
    electrical, air, water, exhaust, network, gas, drains, foundation

Mobility:
    static or mobile, footprint, heading, turning radius, speed, load limits

Capabilities:
    process types, capacity, envelope, compatible products or fixtures

Provenance:
    source path, vendor, model, source URL, license evidence, attribution

Evidence:
    authored, derived, inferred, unknown status per semantic property

Readiness:
    visual_ready, placement_ready, planning_ready, public_ready
```

Raw source paths, private license documents, and internal storage keys are
server-only provenance. Normal viewer/editor projections expose safe source
labels, attribution, status, and hashes, not local filesystem paths. Curators
may inspect protected provenance through an authorized endpoint.

### 7.4 Clearance authority

Every clearance envelope records:

- Clearance kind
- Geometry
- Source
- Revision
- Evidence status
- Whether it is advisory or a hard rule

An AI proposal may suggest a clearance envelope. It cannot mark it authored or
regulatory. Missing safety evidence creates an `unverified` validation outcome,
not a `safe` verdict or a new evidence status.

Floor-load validation follows the same authority rule. `floor_load_exceeded`
may be emitted only when the applicable shell load limit and the asset's
installed or operating contact-load model are authored or validly derived.
Missing mass, support, dynamic-factor, or floor-capacity evidence emits
`floor_load_unverified` and cannot yield a safe verdict.

### 7.5 Intake pipeline

1. Discover and hash files without opening CAD.
2. Build the assembly-reference graph.
3. Identify unreferenced root candidates.
4. Require operator selection for ambiguous roots.
5. Use the canonical package writer or bridge package for structure and stable
   occurrence identity.
6. Use the standalone extractor only for geometry enrichment, views, physical
   properties, GLB, and masks.
7. Convert units and axes into the canonical frame.
8. Derive bounds, support plane, floor anchor candidate, and footprint.
9. Generate proxy and LOD web artifacts.
10. Generate actual PNG or WebP thumbnails, not renamed BMP payloads.
11. Generate collision proxies separately from render geometry.
12. Propose semantic metadata and clearances with evidence status.
13. Review ambiguous geometry, semantics, and provenance.
14. Validate the complete revision.
15. Preview the publication diff.
16. Publish artifacts atomically and update the registry last.

Each intake runs as a durable `IndustrialAssetIntakeJob`:

```text
intakeJobId
tenantId
requestedBy
sourceFingerprint
requestedRoot
configuration
status
currentStage
stageCheckpoints
stagingPath
attempts
createdAt, updatedAt, completedAt
findings
candidateAssetId
candidateDefinitionRevision
candidateRenderBundleRevision
```

Requirements:

- A stable idempotency key prevents duplicate jobs for the same request.
- Every stage writes only to a job-scoped staging directory.
- Completed stage outputs are hash-checked and resumable after process restart.
- Cancellation stops new work and records which staged artifacts are retained.
- Bounded retry applies only to classified transient failures.
- Invalid or abandoned staging directories are quarantined and later pruned by
  a deterministic recovery task.
- No partial job output appears in the authoritative registry.
- Publication reloads the staged result, validates it, shows an exact diff, and
  updates immutable artifacts and registry metadata atomically.

Reuse or adapt the existing bridge-job lifecycle rather than creating an
untracked background-task pattern. P2 may stage and validate candidates while
P1 is in progress, but publication-diff approval and authoritative catalog
writes are disabled until the shared transaction kernel passes P1.

### 7.6 Initial readiness policy

```text
visual_ready:
    Valid nonblank web geometry and thumbnail

placement_ready:
    Verified units, canonical frame, floor anchor, footprint, and collision

planning_ready:
    Reviewed connectors, relevant clearances, and unresolved facts visible

public_ready:
    Verified licensing and attribution for redistribution
```

An asset may be used privately while not `public_ready`. It may not be shipped
in a public InspectorPro common library until licensing is resolved.

### 7.7 Initial pilot assets

Start with:

- One CNC machine
- One robot assembly
- One bar loader
- One guarding asset
- One workstation family
- One cart
- Toyota forklift

Quarantine unknown assets and variants with unresolved root assemblies.

### 7.8 Supporting authority assets

Facility planning depends on three additional revisioned authority assets. They
are not untyped blobs inside a layout.

`FacilityShellDefinition`:

```text
shellId
tenantId
siteId
status: draft | reviewed | published | deprecated | archived
coordinateFrame
floorSurfaces and mountingSurfaces
boundaries, walls, columns, doors, docks, and fixed obstacles
floorLoadZones
egressFeatures
shellConnectors and utilityEntryPoints
sourceDocuments
evidence and unresolvedItems
```

`PolicySetDefinition`:

```text
policySetId
tenantId
siteId
status: draft | reviewed | published | deprecated | archived
applicability
deterministicRules
severityByRule
sourceDocuments
evidence and unresolvedItems
```

Rules are declarative inputs to deterministic validators. Free-form policy text
may be evidence, but it cannot directly execute code or grant authority.

`VehicleProfileDefinition`:

```text
vehicleProfileId
tenantId
siteId
status: draft | reviewed | published | deprecated | archived
displayName
overallDimensions
footprint
wheelbase and axle geometry
steeringLimits and minimumTurningRadius
speed, load, grade, and reverse constraints
sourceDocuments
evidence and unresolvedItems
```

The immutable content files do not persist their own content revision. The
repository response envelope supplies `shellRevision`, `policySetRevision`, or
`vehicleProfileRevision`, derived from canonical bytes. Registry pointers select
the current published revision while older revisions remain directly
addressable.

These assets have repositories, canonical serializers, CAS revisions, atomic
writes, authorization checks, and explicit lifecycle status. Only an
`authority_curator` for the permitted site may move them through review and
publication states. P0 freezes their schemas. P3 implements their repositories
and APIs before manual authoring or route validation depends on them.

Initial ingestion paths:

- Facility shells come from reviewed CAD, IFC/DXF where supported, or manual
  plan authoring. An `authority_curator` confirms units, datum, floor surfaces,
  and fixed obstacles before publication.
- Policy sets are compiled from site-approved rules by an authorized reviewer.
  Model-extracted policy text remains a draft suggestion until a human maps it
  to a deterministic rule and evidence source.
- Vehicle profiles come from manufacturer specifications or reviewed site
  records. Missing load-dependent geometry or steering data blocks
  heading-aware route validation.

### 7.9 Evidence authority matrix

The evidence-status vocabulary is exactly:

```text
authored | derived | inferred | unknown
```

`unverified` is a validator outcome, never an evidence status.

Authority rules:

| Evidence status | Permitted deterministic use |
| --- | --- |
| Authored | May satisfy a hard requirement when the current trusted source and applicable revision are valid |
| Derived | May satisfy a hard requirement only when deterministically derived from a current authoritative source by a pinned method |
| Inferred | May support a proposal or warning; may not satisfy a hard process, utility, loading, clearance, or safety requirement |
| Unknown | May not satisfy a requirement; must remain unresolved |

Sage cannot upgrade evidence authority. Publication and approval do not convert
an inferred fact into an authored fact without an authoritative source.

Every semantic or engineering claim uses a canonical `EvidenceRecord`:

```text
evidenceId
tenantId
subjectRef
claimKey
valueFingerprint
status: authored | derived | inferred | unknown
sourceRef:
    trustedSourceId
    sourceRevision
    locator
derivation:
    methodId
    methodVersion
    inputEvidenceIds
assertedBy
assertedAt
validFrom
validUntil
revokedAt
revocationReason
```

The revisioned `TrustedSourceRegistry` defines each source's owner, type,
issuer, lifecycle status, permitted claim scopes, site applicability, freshness
policy, and access policy.

Deterministic authority rules:

- Only an authorized `authority_curator` may create an authored record, and
  only from a current trusted source whose claim scope covers `claimKey`.
- A derived record is valid only when its pinned derivation method is approved
  for that claim and every input record remains current.
- Inferred and unknown records cannot be upgraded by Sage, approval, or usage.
- Revocation or expiry makes all dependent derived records stale.
- Conflicting current authoritative records emit `evidence_conflict` and block
  the affected hard verdict. No source wins silently unless the applicable
  published policy set contains an explicit deterministic precedence rule.
- Evidence resolution is revision-bound and produces stable finding IDs.

## 8. Facility layout data model

### 8.1 Top-level document

```json
{
  "schemaVersion": 1,
  "layoutId": "fl-...",
  "displayName": "CNC Tending Cell",
  "status": "draft",
  "association": {
    "siteId": "plant-a",
    "areaId": "cell-04"
  },
  "coordinateFrame": {
    "units": "m",
    "handedness": "right",
    "upAxis": "+Y",
    "floorAxes": ["+X", "+Z"],
    "datumId": "plant-a-origin",
    "floorElevation": 0.0
  },
  "sourceShellRef": {
    "shellId": "shell-...",
    "shellRevision": "...",
    "coordinateFrameFingerprint": "..."
  },
  "catalogSnapshotRevision": "...",
  "policySetRef": {
    "policySetId": "policy-...",
    "policySetRevision": "..."
  },
  "zones": [],
  "placements": [],
  "routes": [],
  "utilityNetworks": [],
  "processBindings": [],
  "dismissedSuggestions": [],
  "createdAt": "...",
  "updatedAt": "..."
}
```

The content revision is a server-derived SHA-256 CAS token and is not stored
inside the document.

`schemaVersion` governs the persisted Facility Layout contract, compatibility,
and migration. There is no separate persisted `layoutVersion` in v1. Spatial
engine, router, and policy algorithm versions belong in proposals and receipts,
not as a second ambiguous document-schema counter.

`createdAt` and `updatedAt` are server-owned.

Camera, viewport mode, current selection, open panels, and temporary ghosts are
not persisted in the shared layout.

The layout `coordinateFrame` is an immutable snapshot of the referenced shell
frame, not an independently authored frame. In v1 its canonical fields and
fingerprint must exactly match `FacilityShellDefinition.coordinateFrame`.
Floor and mounting-surface geometry is therefore already expressed in layout
world coordinates and `shellToLayout` is identity. A shell revision that moves
the datum or changes axes requires an explicit migration proposal; it may not be
silently reconciled during load, Fit, placement, or save.

`catalogSnapshotRevision` is informational provenance for the authoring
session. Proposal validity binds only the exact asset-definition revisions
actually referenced by the proposal or layout; unrelated catalog changes do not
make a proposal stale.

### 8.2 Placement

```json
{
  "placementId": "pl-...",
  "assetId": "asset-cnc-lathe",
  "assetDefinitionRevision": "...",
  "transform": {
    "position": {"x": 3.5, "y": 0.0, "z": 4.0},
    "quaternion": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
    "scale": 1.0
  },
  "positionMode": "manual",
  "snapRelationship": null,
  "metadata": {}
}
```

Position ownership:

- `auto`: deterministic layout may move it.
- `manual`: user moved it; preserve by default.
- `locked`: no automatic or manual batch operation may move it until unlocked.

Dragging an `auto` placement changes it to `manual`.

Zone membership is computed from authoritative geometry because zones may
overlap and one placement may be contained by several applicable zones. It is
not persisted as a singular `zoneId`.

Process relationships are owned only by the document-level
`processBindings` collection. Placement views derive their bindings from that
collection and never dual-write them.

### 8.3 Zone

Zones support rectangles and polygons in X/Z world coordinates:

```text
zoneId
zoneType
label
boundary
floorElevation
heightLimit
allowedAssetCategories
gridSpacing
preferredOrientation
edgeSetbacks
loadLimit
policyRefs
evidence
anchors:
    anchorId
    anchorKind
    position and facing in layout world coordinates
    allowedRouteKinds
    evidence
```

Zone anchors are optional authored or derived connection points with stable
`za-` identities. They are not created implicitly from arbitrary polygon
vertices.

Initial types:

- Workcell
- Storage
- Staging
- Receiving
- Shipping
- Inspection
- Aisle
- Dock
- Charging
- Safety
- Exclusion
- Utility
- Service
- Operator

### 8.4 Connector

Connector compatibility is typed. A connector may define:

- Stable connector ID
- Position and facing in asset-local coordinates
- Service type
- Source, sink, or bidirectional role
- Interface standard
- Capacity
- Reach
- Allowed route types
- Evidence status

Utility-specific fields may include:

- Voltage, phase, frequency, and current
- Pressure and flow
- Diameter and interface
- Exhaust capacity
- Network type
- Bend radius
- Required separation

Unknown specifications produce an unresolved finding. They do not become an
assumed match.

### 8.5 Route

```json
{
  "routeId": "rt-...",
  "routeKind": "forklift",
  "sourceEndpoint": {
    "kind": "placement_connector",
    "placementId": "pl-source",
    "connectorId": "material-out"
  },
  "targetEndpoint": {
    "kind": "shell_connector",
    "shellId": "shell-...",
    "connectorId": "dock-04"
  },
  "routingMode": "orthogonal",
  "centerline": [],
  "corridorWidth": 2.4,
  "sweptEnvelope": {},
  "vehicleProfileRef": {
    "vehicleProfileId": "vehicle-forklift-a",
    "vehicleProfileRevision": "..."
  },
  "routeFingerprint": "...",
  "sourceRevisions": {},
  "requirements": [],
  "evidence": []
}
```

Endpoint variants:

```text
placement_connector:
    placementId + connectorId

shell_connector:
    shellId + shellRevision + connectorId

zone_anchor:
    zoneId + anchorId
```

An asset-local connector ID is never a route endpoint by itself because the
same asset may be placed many times.

External endpoints are out of scope for v1. A route entering or leaving the
modeled facility terminates at a revisioned shell connector. A future external
endpoint type requires its own owner, repository, revision, and authorization
contract before being added.

Initial route kinds:

- Material
- Operator
- Forklift
- Conveyor

### 8.6 Utility network

Electrical, air, water, exhaust, network, gas, and drain geometry belongs only
to utility networks. It is not duplicated as an ordinary `Route`.

Utility networks are explicit topology:

```json
{
  "utilityNetworkId": "un-...",
  "networkKind": "compressed_air",
  "label": "Cell air branch",
  "sourceRevisionRefs": {},
  "nodes": [
    {
      "networkNodeId": "nn-...",
      "nodeKind": "endpoint",
      "networkRole": "supply",
      "endpointRef": {
        "kind": "shell_connector",
        "shellId": "shell-...",
        "shellRevision": "...",
        "connectorId": "air-drop-01"
      }
    },
    {
      "networkNodeId": "nn-...",
      "nodeKind": "junction",
      "networkRole": "junction",
      "position": {"x": 4.0, "y": 2.5, "z": 3.0}
    }
  ],
  "segments": [
    {
      "networkSegmentId": "ns-...",
      "sourceNetworkNodeId": "nn-source",
      "targetNetworkNodeId": "nn-target",
      "centerline": [],
      "interface": {},
      "capacity": {},
      "requirements": [],
      "evidence": []
    }
  ],
  "requirements": [],
  "evidence": []
}
```

A network node is a discriminated union:

- `endpoint` requires exactly one `endpointRef` and forbids `position`. Its
  world position and facing are derived from the current revision-bound
  placement connector, shell connector, or zone anchor.
- `junction` requires a world `position` and forbids `endpointRef`.

Every segment resolves network-node IDs, occurrence-qualified endpoint
references, and compatible service types. Segment `centerline` is the sole
owner of routed utility geometry. Unknown capacity, pressure, voltage,
interface, or separation data remains unresolved and cannot pass a hard rule.

### 8.7 Process binding

Facility-owned bindings contain:

```text
processBindingId
productId
processMapId
processMapRevision
processNodeIds
processEdgeIds
placementIds
routeIds
bindingRole
```

Changing the referenced Process Map revision marks the binding stale and
invalidates any open layout proposal.

## 9. Spatial geometry and validation

### 9.1 Authoritative geometry

Use 2.5D geometry by default:

- X/Z footprint polygons or oriented rectangles
- Y minimum and maximum intervals
- Named clearance polygons and intervals

Use compound boxes or convex proxies only when necessary for:

- Overhangs
- Stacking
- Door movement
- Suspended equipment
- Genuine 3D interference

Full render meshes are never the normal validator input.

### 9.2 Placement pipeline

1. Convert the pointer to a camera ray.
2. Intersect the trusted floor or mounting surface.
3. Convert the hit to facility-world coordinates.
4. Identify containing zones.
5. Generate the enabled candidate families: grid, boundary, row, bay,
   foundation, and alignment in P6; connector candidates after P7.
6. Query a broad-phase X/Z spatial index.
7. Run exact polygon, OBB, vertical-interval, and clearance tests.
8. Reject invalid candidates with typed findings.
9. Rank valid candidates lexicographically.
10. Return stable candidate IDs.
11. Render a translucent ghost and clearance volumes in both views.
12. On acceptance, regenerate against current revisions and obstacle
    fingerprint.
13. Commit one operation batch and one undo step.

### 9.3 Candidate ranking

Use a deterministic lexicographic score, not an unexplained weighted float.

Suggested order:

1. Hard violations
2. Physical collisions
3. Sourced safety-rule violations
4. Zone compatibility
5. Connector compatibility
6. Clearance conflicts
7. Process-flow distance
8. Route feasibility
9. Alignment and snap quality
10. Movement of existing content
11. Distance from requested area
12. Stable candidate ID

### 9.4 Position ownership

- Automatic planning moves only `auto` placements by default.
- Manual placements act as strong obstacles and anchors.
- Locked placements are hard constraints.
- A proposal that needs to move manual content must list every move explicitly.
- No proposal may move locked content.

### 9.5 Validator findings

Identity and revision:

- `invalid_coordinate_frame`
- `unsupported_units`
- `stale_shell_revision`
- `stale_asset_definition_revision`
- `incompatible_render_bundle_revision`
- `stale_process_map_revision`
- `non_finite_transform`
- `asset_geometry_missing`

Placement:

- `placement_collision`
- `placement_outside_floor`
- `zone_containment_violation`
- `zone_kind_incompatible`
- `floor_load_exceeded`
- `floor_load_unverified`
- `locked_placement_movement`
- `unsupported_mounting_surface`

Clearance:

- `safety_clearance_violation`
- `service_clearance_violation`
- `loading_clearance_violation`
- `operator_clearance_violation`
- `door_swing_obstructed`
- `egress_obstructed`
- `clearance_rule_unavailable`

Utilities:

- `utility_type_incompatible`
- `utility_spec_mismatch`
- `utility_capacity_exceeded`
- `connector_direction_invalid`
- `utility_route_obstructed`

Routes:

- `route_unreachable`
- `route_width_insufficient`
- `route_turning_radius_violation`
- `route_swept_volume_collision`
- `route_grade_exceeded`
- `stale_route_geometry`

### 9.6 Severity rules

Errors:

- Invalid identity or revision
- Non-finite transforms
- Physical collision
- Movement of a locked placement
- Out-of-floor placement
- Sourced hard-policy violation
- Invalid connector direction
- Structurally invalid route

Unverified or blocked:

- Missing safety clearance evidence
- Missing utility specifications
- Unknown floor capacity or asset contact loading
- Unknown foundation requirements
- Unknown vehicle profile

Warnings:

- Advisory clearance conflict
- Long material route
- Manual placement outside preferred zone
- Suboptimal alignment

A draft may be saved with unresolved findings when product policy allows it, but
the UI must not label it validated or safe.

## 10. Routes and mobile resources

### 10.1 Static route topology

Retain deterministic Dijkstra for:

- Aisle-network connectivity
- Coarse distance estimates
- Candidate corridor selection
- Existing warehouse analysis compatibility

Existing fallback constants remain explicitly labeled assumptions.

### 10.2 Forklift route geometry

Add a heading-aware planner over:

```text
x, z, heading
```

Use deterministic straight and minimum-radius arc primitives, such as a bounded
Hybrid A* implementation.

The route engine must:

- Inflate obstacles by vehicle and load footprint.
- Respect corridor width.
- Respect minimum turning radius.
- Model forward and reverse policy.
- Generate a swept envelope.
- Recheck the complete swept envelope independently after planning.
- Bind output to the layout, asset, vehicle-profile, and policy revisions.

### 10.3 Process and material flow

Process Map edges describe required flow. Facility routes describe spatial
realization.

The route planner may minimize:

- Travel distance
- Handling count
- Backtracking
- Cross-traffic
- Operator walking

It may not invent process precedence or change the Process Map.

## 11. Synchronized editor experience

### 11.1 Workspace

The Process Map's source-tree/catalog pattern is reused:

```text
Left pane:
    Company assets
    InspectorPro common assets
    Search, filters, categories, readiness

Main viewport:
    Top view or 3D view over one layout state

Right pane:
    Selection properties, transforms, connectors, clearances, findings

Ribbon:
    Context-sensitive layout authoring commands
```

The 3D scene is full-bleed and unframed within the main viewport.

### 11.2 View modes

Initial segmented modes:

- Plan
- 3D

An optional split view may follow only after rendering budgets pass. The first
release does not render two full 3D scenes.

### 11.3 Manual commands

V1 commands:

- Select
- Pan/orbit
- Draw rectangular zone
- Draw polygon zone
- Dimension zone
- Place asset
- Move
- Rotate
- Duplicate
- Multi-select
- Delete
- Lock/unlock
- Snap modes
- Show/hide footprint
- Show/hide clearances
- Connect route
- Fit
- Undo/redo
- Save

Every 3D action must also have a tree, ribbon, keyboard, or property-panel
equivalent.

### 11.4 Drag payload

The drag payload contains:

```text
assetId
assetDefinitionRevision
dragSessionId
```

It never contains the GLB binary or mutable asset metadata.

The editor resolves and caches the correct artifacts.

### 11.5 Selection and picking

- Placement identity is `placementId`, not mesh name.
- Repeated assets maintain an occurrence-to-instance mapping.
- Plan view uses the X/Z spatial index.
- 3D uses instance-aware raycasting against selection proxies.
- Detailed mesh BVH is optional and limited to selected detailed assets.
- Marquee selection is available in plan view.
- Selection is synchronized between tree, plan view, 3D view, and properties.

### 11.6 Undo and history

One user gesture creates one history entry:

- Drag/drop
- Transform drag
- Multi-object move
- Zone resize
- Route edit
- Duplicate
- Delete
- Accepted proposal

Camera changes and selection changes do not dirty the layout.

## 12. Rendering and web-asset architecture

### 12.1 Source versus web artifacts

Source CAD and full-fidelity geometry remain non-web assets.

The browser loads:

1. Layout manifest
2. Two-dimensional footprints
3. Lightweight proxy scene
4. Overview LODs
5. Selected-object detail on demand

### 12.2 Prototype and occurrence model

Export local geometry once per:

```text
source hash + configuration + tessellation profile
```

Store occurrence transforms separately.

Use `THREE.InstancedMesh` for repeated racks, pallets, fixtures, guards, and
other compatible repeated assets. Maintain:

```text
placementId -> prototypeId -> instanceId
```

Merge only non-selectable static geometry and partition it by spatial tile and
material.

### 12.3 Three.js dependency

Replace the inline custom GLB loader and remote CDN dependency with pinned local
Three.js modules:

- Official `GLTFLoader`
- Meshopt or Draco decoding after a measured spike
- Optional KTX2 textures when textures become material

No compression dependency is adopted without:

- Offline operation
- License review
- Packaging proof
- Corrupt-payload handling
- Cancellation
- Performance comparison

### 12.4 Rendering loop

Use one shared renderer and demand-driven rendering.

Continuous rendering is allowed only while:

- Orbiting
- Dragging
- Animating
- Showing active visual effects
- Streaming visible scene chunks

Idle rendering stops within 250 ms.

### 12.5 Cache and lifecycle

Use a byte-bounded, reference-counted LRU cache.

Editor teardown owns and releases:

- Animation frames
- Controls
- Resize observers
- Event listeners
- Fetch and decode tasks
- Scene objects
- Geometry
- Materials
- Textures
- Worker jobs
- WebGL resources

### 12.6 Degraded operation

If detailed 3D fails or WebGL is unavailable:

- The top-down editor remains fully usable.
- Proxy geometry remains available where possible.
- Saving and deterministic validation remain available.
- The user receives a specific degraded-mode finding.

## 13. Persistence and APIs

### 13.1 Storage

```text
generated/facility_layouts/<tenantId>/<siteId>/layouts/
    registry.json
    <layoutId>.json
    backups/
    receipts/

generated/facility_layouts/<tenantId>/<siteId>/authority/
    shells/registry.json
    shells/<shellId>/revisions/<shellRevision>.json
    policy_sets/registry.json
    policy_sets/<policySetId>/revisions/<policySetRevision>.json
    vehicle_profiles/registry.json
    vehicle_profiles/<vehicleProfileId>/revisions/<vehicleProfileRevision>.json
```

The exact root can follow current generated-asset conventions.

`siteId` is unique only within its tenant. Repository paths are constructed
from the server-resolved principal scope, never directly from browser or path
text.

### 13.2 Repository rules

- Canonical ASCII JSON
- SHA-256 content revision returned by the server
- Revision never persisted inside the asset
- Temp file, flush, fsync, and atomic replace
- Bounded retry for OneDrive file locks
- Revision-addressable backups
- Explicit registry pointer for defaults
- Server-owned timestamps
- No hard delete in v1
- Archive instead of delete

### 13.3 API outline

```text
GET  /api/facility-layouts/{siteId}
POST /api/facility-layouts/{siteId}
GET  /api/facility-layouts/{siteId}/{layoutId}
PUT  /api/facility-layouts/{siteId}/{layoutId}
POST /api/facility-layouts/{siteId}/{layoutId}/archive

GET  /api/industrial-assets
GET  /api/industrial-assets/{assetId}/{assetDefinitionRevision}

GET  /api/facility-shells/{siteId}
POST /api/facility-shells/{siteId}
GET  /api/facility-shells/{siteId}/{shellId}
GET  /api/facility-shells/{siteId}/{shellId}/revisions/{shellRevision}
PUT  /api/facility-shells/{siteId}/{shellId}
POST /api/facility-shells/{siteId}/{shellId}/archive

GET  /api/facility-policy-sets/{siteId}
POST /api/facility-policy-sets/{siteId}
GET  /api/facility-policy-sets/{siteId}/{policySetId}
GET  /api/facility-policy-sets/{siteId}/{policySetId}/revisions/{policySetRevision}
PUT  /api/facility-policy-sets/{siteId}/{policySetId}
POST /api/facility-policy-sets/{siteId}/{policySetId}/archive

GET  /api/facility-vehicle-profiles/{siteId}
POST /api/facility-vehicle-profiles/{siteId}
GET  /api/facility-vehicle-profiles/{siteId}/{vehicleProfileId}
GET  /api/facility-vehicle-profiles/{siteId}/{vehicleProfileId}/revisions/{vehicleProfileRevision}
PUT  /api/facility-vehicle-profiles/{siteId}/{vehicleProfileId}
POST /api/facility-vehicle-profiles/{siteId}/{vehicleProfileId}/archive

POST /api/facility-layouts/{siteId}/{layoutId}/validate
POST /api/facility-layouts/{siteId}/{layoutId}/proposals
GET  /api/facility-layouts/{siteId}/{layoutId}/proposals/{proposalId}/preview
POST /api/facility-layouts/{siteId}/{layoutId}/approvals
POST /api/facility-layouts/{siteId}/{layoutId}/apply
GET  /api/facility-layouts/{siteId}/{layoutId}/receipts/{receiptId}
```

Existing Facility Layout analysis endpoints remain available during migration.

Every endpoint resolves tenant and site access from the authenticated principal
and enforces the role matrix in Section 5.7. A caller cannot gain access by
supplying another `siteId`, object ID, registry path, or revision.

### 13.4 Dependency revisions

Every save validates the exact dependencies referenced by its document. Every
proposal must bind:

- Layout revision
- Exact referenced asset-definition revisions
- Facility shell revision
- Policy-set revision
- Referenced vehicle-profile revisions
- Process Map revision
- Spatial engine version
- Router version
- Obstacle fingerprint

Any relevant mismatch invalidates an open proposal. Catalog snapshot changes
that do not alter a referenced asset definition do not invalidate it. Compatible
render-bundle changes never invalidate layout geometry, validation, or approval.

## 14. Sage environment architecture

### 14.1 Skill contract

Add a concise Facility Layout Environment Contract defining:

- Asset definitions versus placements
- Zones
- Connectors
- Utilities
- Material, operator, and vehicle routes
- Clearances
- World coordinates
- `auto`, `manual`, and `locked`
- Process Map bindings
- Evidence states
- Ghost preview
- Approval and atomic commit
- The rule that proximity does not prove process order
- The rule that missing safety evidence is not validation

### 14.2 Trusted observation

Add server-origin context:

```text
facility_layout.state
facility_layout.digest
facility_layout.evidence
```

`facility_layout.state` is the revision-bound structured server object used by
deterministic tools. It includes:

- Layout identity and revision
- Dependency revisions
- Coordinate frame
- Zones
- Placements and dimensions
- Transforms and position modes
- Connectors and routes
- Deterministic diagnostics
- Sanitized current selection
- Dirty and conflict state
- Supported capabilities
- Active proposal identity and status
- Canonical receipt references

`facility_layout.evidence` includes:

- Exact asset definitions and revisions
- Facility shell revision
- Footprints and collision proxies
- Clearances and their authority
- Connector and utility definitions
- Mobility profiles
- Applicable policy revisions
- Process Map requirements and revision
- Provenance and unresolved facts

The language model does not receive an unbounded dump of either object. It
receives `facility_layout.digest`, a deterministic summary carrying a pinned
`digestContractVersion`, `tokenizerId`, and `tokenizerRevision`. The compiled
digest must satisfy both:

```text
maximumTokens: 4,500 under the repository-pinned tokenizer
maximumCanonicalUtf8Bytes: 24 KiB
```

If either bound cannot be met after deterministic truncation, compilation fails
closed rather than attaching an oversized context. The digest contains:

- Layout, shell, policy, and process identities and revisions
- Counts by placement, zone, route, network, and position mode
- Referenced asset families and capabilities
- Zone occupancy and resource summaries
- Validation findings grouped by severity and code
- Active selection and proposal summary
- Assumptions, unresolved facts, and stale dependencies
- Stable IDs needed for follow-up observation tools

Ordering and truncation are deterministic. High-severity findings, selected
entities, active-proposal entities, unresolved authority gaps, and user-named
regions have priority. Each truncated collection reports the omitted count.
Golden tests pin digest bytes at contract-scale and 5,000-placement scale.

The browser may report live selection and viewport status through a tightly
validated attachment. It cannot supply authoritative geometry, evidence,
revisions, policies, or receipts.

### 14.3 Semantic Facility Layout Plan v1

Sage produces a declarative plan containing:

```text
Scope and objective
Required process capabilities
Selected asset definitions
Resource roles
Required zones
Placement relationships
Process bindings
Material and utility flows
Preferred adjacency and orientation
Evidence
Assumptions
Unresolved items
Alternatives
```

Every semantic claim uses the evidence states and authority rules in Section
7.9. Geometry quality and semantic authority remain separate.

The semantic schema rejects:

- X, Y, or Z coordinates
- Quaternions
- Matrices
- Route points
- Screen pixels
- Camera values
- Approval claims
- Unsupported safety verdicts

### 14.4 High-level tool

Expose one Sage mutation tool:

```text
build_facility_layout_preview
```

Expose bounded read-only observation tools:

```text
search_industrial_assets
inspect_facility_entities
inspect_facility_region
inspect_facility_findings
inspect_process_bindings
```

Read tools accept stable entity, zone, shell, process, or finding IDs. They do
not accept model-authored world coordinates or screen rectangles. Results are
server-loaded, revision-bound, authorization-filtered, deterministically
ordered, and enforce:

```text
maximum IDs per request: 50
maximum search text: 120 characters
maximum page size: 50 records
maximum response: 16 KiB canonical UTF-8 and 3,000 pinned-tokenizer tokens
maximum execution time: 2 seconds
maximum observation calls per Sage turn: 8
```

Pagination uses an opaque authenticated cursor bound to principal, tenant,
site, layout ID, layout revision, query hash, stable sort key, and five-minute
expiry. A stale revision, expired cursor, altered query, or forged cursor fails
closed. Responses report returned count, omitted count, and `nextCursor`.

The tool:

1. Resolves the trusted current state.
2. Validates the semantic plan.
3. Selects exact asset-definition revisions.
4. Compiles domain operations in memory.
5. Runs deterministic placement.
6. Runs route planning.
7. Runs spatial validation.
8. Stores one complete 2D/3D ghost-preview artifact for the authorized UI.
9. Returns a bounded model receipt containing `proposalId`,
   `previewArtifactRef`, counts, assumptions, unresolved items, alternatives,
   and summarized findings.
10. Writes no Facility Layout or authority asset; only expiring proposal and
    preview-artifact state is stored.

The model receipt obeys the same 16 KiB and 3,000-token result limits. The full
layout diff, geometry, and preview payload are not injected into Sage context;
the UI retrieves the artifact through an authorized proposal endpoint. The
artifact is temporary proposal state, expires with the proposal, and cannot be
mistaken for a committed layout.

Manual UI commands may use low-level operations. Sage does not simulate ribbon
clicks or type into property forms.

Sage plans from the bounded digest, requests exact details through read tools,
then invokes the single preview tool. Low-level mutation operations are never
exposed directly to the model.

### 14.5 Preview and commit

The complete preview shows:

- Translucent assets
- Zone boundaries
- Footprints
- Clearance volumes
- Material routes and utility networks
- Before/after positions for moved automatic assets
- Semantic assumptions
- Spatial findings
- Unresolved engineering data
- Asset and process revision bindings

Approval binds:

- User and session
- Layout revision
- Exact referenced asset-definition revisions
- Shell and policy revisions
- Vehicle-profile revisions
- Process Map revision
- Semantic-plan hash
- Dependency fingerprint
- Spatial-engine version
- Router version
- Spatial-policy version
- Obstacle fingerprint
- Exact diff hash
- Idempotency key

Apply reloads and regenerates the proposal before one atomic save.

The receipt returns:

- New layout revision
- Created, moved, and removed placement IDs
- Created route and zone IDs
- Warnings
- Unresolved items
- Validation summary
- Dependency revisions
- Proposal and approval IDs

## 15. Multi-agent implementation model

The work is complex enough to use specialist subagents, but integration remains
owned by one lead agent.

### 15.1 Roles

```text
Lead/integration agent:
    Owns phase scope, contracts, integration, final test runs, and user updates

Contract and persistence agent:
    Schemas, migrations, repositories, CAS, transaction adapter

Asset pipeline agent:
    Discovery, root resolution, normalization, web artifacts, provenance

Renderer/editor agent:
    Three.js renderer, plan view, selection, transforms, synchronized state

Spatial engine agent:
    Geometry, zones, snapping, collision, clearances, routing, workers

Sage/Builder agent:
    Trusted state, skill, semantic plan, high-level tool, preview receipts

Verification agent:
    Independent code review, test matrices, screenshots, performance evidence
```

### 15.2 Delegation rules

- Subagents receive narrow, concrete, disjoint write scopes.
- No two subagents edit `server.py` or `static/index.html` concurrently.
- New modules are preferred over adding more monolithic inline code.
- One integration agent owns application-shell wiring.
- The verification agent does not implement the feature it verifies.
- A worker's reported pass is not the exit gate. The lead reruns critical tests
  and inspects artifacts.
- Every agent lists exact files changed and commands run.
- No agent may weaken existing assertions to force a green result.
- No agent may clean or revert unrelated dirty-worktree changes.

### 15.3 Phase loop

Every phase follows:

```text
1. Capture baseline
2. Assign disjoint work packages
3. Implement in isolated agent branches/workspaces
4. Review each patch
5. Integrate one work package at a time
6. Run focused tests
7. Run frozen regression bars
8. Run independent verification
9. Capture required visual/performance evidence
10. Record checkpoint report
11. Commit only the phase scope
12. Request approval for the next phase
```

### 15.4 Stop conditions

Stop a phase when:

- A coordinate contract is ambiguous.
- A migration loses unknown fields.
- Process Map regressions appear after transaction extraction.
- An asset lacks sufficient identity or provenance.
- A preview differs from the applied result.
- A stale proposal can apply.
- A safety claim lacks authoritative evidence.
- The renderer requires the 327 MB legacy GLB to function.
- Performance exceeds a binding budget without a documented decision.

### 15.5 Phase ownership matrix

| Phase | Primary worker packages | Independent gate owner |
| --- | --- | --- |
| P0 | Contracts; asset spike; 2D/3D renderer spikes | Verification agent |
| P1 | Transaction kernel; Process Map adapter | Verification agent |
| P2 | Discovery/root resolution; normalization; web artifacts; catalog authorization | Verification and performance agents |
| P3 | Layout domain; authority repositories; persistence/API authorization | Security-focused verification agent |
| P4 | Plan renderer; Three.js renderer; synchronization/lifecycle | Browser/performance verification agents |
| P5 | Manual interactions; ribbon/tree/properties integration | Browser/accessibility verification agents |
| P6 | Spatial index; exact constraints; workers/cancellation | Geometry/property-test verification agent |
| P7 | Connector/utility topology; vehicle routing; Process Map binding | Routing and domain verification agents |
| P8 | Deterministic planner; alternatives; preview transaction adapter | Exact-diff and visual verification agents |
| P9 | Skill/digest/read tools; semantic plan; model evaluation | Agent-safety and authorization verification agents |
| P10 | Warehouse package; manufacturing-cell package | Workflow verification agent |
| P11 | Performance; accessibility; rollback; soak/pilot evidence | Lead plus independent release verifier |

The lead agent assigns disjoint files and may split a package further when it
has a stable contract boundary. `server.py`, `static/index.html`, schema
registries, and shared transaction files are serialized integration zones:
only one designated agent edits each at a time.

### 15.6 Integration order within a phase

For phases with parallel work, integrate in this order:

1. Contracts and pure data structures.
2. Pure operations and backend validation.
3. Repositories and authorization.
4. Render or browser adapters.
5. Application-shell wiring.
6. Focused tests for each package.
7. Cross-package integration tests.
8. Frozen Process Map and application regressions.
9. Independent review, screenshots, and performance evidence.
10. Scoped commit and checkpoint report.

An agent's branch is not merged merely because its own tests pass. The lead
inspects the diff, reruns the package tests from the integrated worktree, and
then the independent verifier tests the resulting behavior without relying on
the worker's report.

## 16. Delivery phases

### P0 - Contract freeze, baseline, and spikes

Purpose:

Define the shared vocabulary and prove critical technical choices before
building editor behavior.

Work:

- Recapture all relevant Process Map, Assembly, Facility mode, and frontend
  baselines from the current worktree.
- Add `facility-layout-schema-v1.json`.
- Add `facility-layout-spatial-contract-v1.json`.
- Add schemas for facility shells, policy sets, vehicle profiles, route
  endpoints, and utility networks.
- Freeze identity, deterministic generated-ID, revision-envelope, coordinate,
  transform, geometry-normalization, limit, and evidence-authority contracts.
- Freeze `EvidenceRecord`, `TrustedSourceRegistry`, derivation, freshness,
  revocation, and deterministic conflict contracts.
- Freeze the single `schemaVersion` compatibility rule and shell/layout
  coordinate-frame equality invariant.
- Freeze tenant-owned catalog visibility, site grants, client provenance
  redaction, and operating/contact-load schemas.
- Freeze principal, tenant, site, and role authorization rules.
- Freeze the bounded `facility_layout.digest` and read-tool contracts.
- Record that backend validation is authoritative and browser checks are
  advisory.
- Define migration from the current semantic v0.2 fixture.
- Mark imported rough geometry as demo/inferred, not safety authority.
- Select named reference hardware for performance tests.
- Select the first machine and rack/workstation assets.
- Run a local Three.js module, loader, compression, and offline-packaging spike.
- Run a top-view renderer spike comparing SVG, Canvas 2D, and WebGL for
  500-placement editing and 5,000-placement navigation.
- Run a prototype/instance export spike on repeated rack geometry.
- Create five canonical synthetic fixtures.
- Create the benchmark-fixture manifest.

Subagent split:

- Contract agent: schemas and migration matrix.
- Rendering agent: Three.js packaging plus top-view renderer spikes.
- Asset agent: two-asset normalization spike.
- Verification agent: baseline and coordinate report.

Required artifacts:

- Contract documents
- Migration matrix
- Coordinate golden report
- Dependency spike report
- Asset normalization report
- Frozen test-count report
- No user-visible feature

Exit gate:

- Stable IDs and finite meter-based transforms.
- Same proposal input regenerates the same typed object IDs.
- Camera explicitly separate from layout.
- Shell, policy, vehicle, route-endpoint, utility-network, limit, and
  authorization contracts are executable test fixtures.
- Top-view renderer choice is recorded from measured evidence, with a fallback.
- Current semantic v0.2 imports without losing source data.
- Newer unsupported schemas fail clearly and read-only.
- Two assets have verified local frames, floor anchors, and footprints.
- No unmanaged production dependency is introduced.

### P1 - Shared transaction kernel

Purpose:

Reuse proposal, approval, idempotency, CAS, and receipts without duplicating
Process Map Builder.

Work:

- Extract a domain-neutral transaction kernel.
- Add a Process Map adapter preserving all current APIs and behavior.
- Add expiry, cancellation, replay, principal, and dependency binding.
- Keep proposal state fail-closed on restart.
- Define durable receipt storage for Facility Layout.
- Add adapter isolation tests.

Subagent split:

- Transaction agent implements the kernel and Process Map adapter.
- Verification agent independently audits exact-diff and replay behavior.

Exit gate:

- All existing Process Map backend, editor, spatial, and Playwright bars pass.
- Approval token mismatch, replay, wrong user/session, stale revision, and
  altered diff fail closed.
- No Process Map persisted bytes change in no-op round trips.

### P2 - Industrial asset intake and web artifacts

Purpose:

Turn selected raw CAD files into versioned, lightweight, placeable assets.

Work:

- Implement discovery and hashing.
- Implement durable intake jobs, staging, resume, cancellation, idempotency,
  recovery, and cleanup.
- Implement dependency-graph root resolution.
- Integrate canonical package identity.
- Add standalone-extractor enrichment.
- Add coordinate normalization.
- Generate bounds, footprints, floor anchors, thumbnails, proxies, and LODs.
- Preserve repeated local geometry and occurrence transforms.
- Add asset registry and readiness states.
- Add provenance and licensing gates.
- Implement the tenant trusted-source registry and evidence-record validator.
- Enforce tenant/site catalog visibility and `catalog_curator` publication
  authority.
- Publish definition and render-bundle revisions independently.
- Quarantine unknown or ambiguous assets.

After P0 is approved, P2 discovery, hashing, normalization experiments, and
job-scoped staging may run in parallel with P1. Catalog publication, registry
writes, publication approval, and any shared transaction integration remain
blocked until P1 independently passes and P2 receives its own start decision.

Exit gate:

- One CNC machine, one robot or rack, one workstation, and one forklift are
  `visual_ready`.
- At least one machine and one rack/workstation are `placement_ready`.
- LOD bounds remain consistent.
- Thumbnails are valid nonblank images.
- Public publication fails when licensing is unknown.
- Conflicting, expired, or revoked authoritative evidence blocks affected hard
  publication claims.
- Private use remains possible with visible provenance status.
- A render-only update leaves the asset definition revision unchanged.
- Unauthorized catalog read or publication fails without disclosing existence.
- Restart resumes a checkpointed intake job without publishing partial output.
- Repeating an idempotent intake request does not create a duplicate job or
  asset.

### P3 - Facility domain, operations, and persistence

Purpose:

Create the authoritative editable layout asset without frontend mutation.

Work:

- Implement schema and migration.
- Implement registry and repository.
- Implement revisioned repositories and APIs for facility shells, policy sets,
  and vehicle profiles.
- Implement principal-derived tenant/site authorization for every repository
  and API.
- Implement pure operations:
  - create/rename/archive layout
  - add/edit/delete zone
  - place/move/rotate/duplicate/delete placement
  - set position mode
- Implement structural validation.
- Implement canonical diff.
- Add APIs and CAS conflict responses.
- Add revision-addressable backups.

Exit gate:

- Same operation input produces identical bytes and diff hash.
- Failed batches write nothing.
- Stale CAS returns 409.
- Cross-tenant and cross-site object access fails closed.
- Repeated asset placements remain independent.
- Save/reopen is exact.
- No-op load/save is byte-stable.
- Unknown compatible fields round-trip.

### P4 - Scalable renderer and synchronized views

Purpose:

Render one authoritative layout in top and 3D views without authoring yet.

Work:

- Add the modular facility editor controller.
- Add top-view projection.
- Add Three.js renderer adapter.
- Stop moving the model root during Fit.
- Load manifest, footprints, proxy, overview LOD, then detail.
- Add instancing and stable picking identities.
- Add demand-driven rendering.
- Add complete lifecycle disposal.
- Add 2D-only degraded mode.
- Synchronize selection across tree, plan, 3D, and properties.

Exit gate:

- Nonblank correctly framed scene.
- Plan and 3D selections address the same placement IDs.
- Repeated assets use instancing where eligible.
- Fit changes camera only.
- Context loss or unavailable WebGL preserves 2D operation.
- Twenty remounts leave one canvas, no growing observers, and no orphan render
  loops.

### P5 - Manual authoring alpha

Purpose:

Deliver the first human-controlled authoring surface before deterministic
engineering constraints are complete.

Work:

- Asset tree drag/drop by stable ID.
- Floor raycasting and top-view coordinate conversion.
- Ghost placement.
- Grid snap and 90-degree rotation.
- Move, duplicate, multi-select, delete, lock, undo, redo.
- Rectangle and polygon zone authoring.
- Dimension display and editing.
- One shared history.
- CAS save and reload.
- Plan/3D transform synchronization.

Exit gate:

- Drop after pan, zoom, orbit, resize, and Fit lands at the same intended world
  point.
- One gesture equals one undo entry.
- User drag converts `auto` to `manual`.
- Locked placements never move.
- Invalid drops leave state unchanged.
- Save/reopen restores exact transforms and zones.
- The manual authoring alpha is usable without Sage.
- The UI clearly labels collision, containment, and clearance validation as
  incomplete until P6; P5 is not the complete vertical-slice gate.

### P6 - Deterministic snapping, collision, and clearances

Purpose:

Make placement engineering-aware and preview-first.

Work:

- Spatial index and exact 2.5D narrow phase.
- Grid, boundary, row, bay, alignment, and foundation snaps.
- Zone compatibility.
- Collision and height-interval validation.
- Named clearance envelopes.
- Floor and mounting checks.
- Typed findings and deterministic ordering.
- Ghost alternatives with before/after metrics.
- Browser Web Worker for immediate coarse advisory feedback and cancellation.
- Backend worker/executor for authoritative candidate generation, exact
  diagnostics, and cancellation.

Exit gate:

- Broad-phase results match a brute-force oracle on seeded fixtures.
- Zero collision false negatives in golden fixtures.
- Same input produces identical candidate IDs and ranking.
- Missing safety evidence cannot yield a `safe` result.
- Authored clearance data is not overwritten.
- Dismiss leaves the layout byte-identical.
- Acceptance regenerates and commits one exact transaction.
- The complete first vertical slice in Section 2 passes end to end without
  Sage, including collision and zone-containment enforcement.

### P7 - Connectors, utilities, routes, and Process Map binding

Purpose:

Connect the physical layout to manufacturing intent and material movement.

Work:

- Add pure add/edit/delete route operations.
- Add pure add/edit/delete utility-network, network-node, and network-segment
  operations.
- Add pure attach/detach Process Map binding operations.
- Typed asset connectors.
- Connector snapping and compatibility candidates.
- Material, operator, forklift, and conveyor routes plus utility networks.
- Aisle topology and distance estimates.
- Heading-aware forklift planning and swept-volume recheck.
- Process operation-to-resource assignments.
- Route-to-process-edge bindings.
- Stale Process Map revision handling.
- Route requirements and findings.

Exit gate:

- Every route endpoint resolves to an allowed occurrence-qualified connector or
  zone-anchor endpoint variant.
- Repeated placements with identical asset-local connector IDs remain
  unambiguous through occurrence-qualified endpoints.
- Every utility-network segment resolves valid network nodes and service types.
- Utility incompatibility is rejected deterministically.
- Forklift goldens cover straight, 90-degree, narrow aisle, cul-de-sac,
  reverse-required, loaded, and unreachable cases.
- Every accepted vehicle route passes independent swept-volume validation.
- Spatial proximity never creates process precedence.
- A changed Process Map revision invalidates the bound proposal.

### P8 - Deterministic layout proposals and ghost alternatives

Purpose:

Prove automatic placement and arrangement before introducing Sage.

Work:

- Declarative deterministic layout requests.
- Candidate placement of complete asset sets.
- Minimal-displacement cleanup.
- Respect `auto`, `manual`, and `locked`.
- Zone sizing around content where explicitly requested.
- Route generation and diagnostics.
- Complete synchronized 2D/3D ghost preview.
- Alternatives and comparison metrics.
- One exact approval and atomic apply.

Exit gate:

- Preview never dirties saved state.
- Locked placements never move.
- Manual placements move only when listed in the exact diff.
- No hard finding is introduced.
- Preview and applied result are identical.
- Stale obstacle, referenced asset-definition, shell, vehicle, process, or
  policy revisions reject apply.
- Unrelated catalog or compatible render-bundle changes do not reject apply.

### P9 - Sage semantic planning

Purpose:

Let Sage propose a complete warehouse or manufacturing-cell layout while
deterministic systems retain spatial authority.

Work:

- Add Facility Layout skill and workflow.
- Add trusted state, bounded digest, and evidence providers.
- Add the bounded read-only observation tools from Section 14.4.
- Add Semantic Facility Layout Plan v1.
- Add deterministic semantic validation.
- Add one `build_facility_layout_preview` tool.
- Compile semantic plan into facility operations.
- Run deterministic placement and routing.
- Return one complete ghost preview.
- Add assumption, evidence, and unresolved-item review.
- Add receipt-grounded completion responses.

Exit gate:

- Sage never emits or applies raw coordinates.
- Forged browser geometry or evidence is discarded.
- The 5,000-placement fixture stays within the digest budget and can be
  investigated through stable-ID read tools.
- Unsupported safety claims are rejected.
- Read-only questions expose no write tool.
- One explicit approval binds every dependency and exact diff.
- No response claims success without a canonical receipt.
- Process and spatial reasoning remain separate in fixtures and model evals.

### P10 - Workflow packages

Purpose:

Deliver practical warehouse and manufacturing-cell workflows over the stable
editor.

Warehouse package:

- Rack rows, bays, slots, and pallets
- Staging and docks
- Aisles and charging
- Capacity estimates
- Forklift access and travel

Manufacturing-cell package:

- Machines, robots, fixtures, guards, workstations, and conveyors
- Operator and maintenance zones
- Utilities
- Process operation assignments
- Material input/output routes
- Reusable cell templates

Exit gate:

- One warehouse lane and one CNC tending cell can be built manually and through
  a reviewable Sage proposal.
- Capacity and routing results cite their assumptions and source revisions.
- No workflow depends on hard-coded Assem3 IDs or Tricycle/Process Map fixtures.

### P11 - Hardening, soak, and pilot release

Purpose:

Prove the system is dependable before enabling agent writes for pilot users.

Work:

- Performance and memory profiling.
- Accessibility review.
- Light/dark visual review.
- WebGL recovery.
- Offline and corrupt-artifact handling.
- Feature-flag matrix.
- Complete RBAC, IDOR, tool-authorization, stale-proposal, and replay suites with
  agent write enabled in the test environment.
- Rollback drill.
- Two-week self-use soak.
- Pilot documentation and safety disclaimer.

Exit gate:

- Every performance budget passes on named hardware.
- Zero critical accessibility findings.
- Zero data loss.
- Zero unapproved writes.
- Zero stale proposals applied.
- At least 10 receipt-backed approved Sage applies complete during soak.
- Every role and cross-tenant/site authorization matrix passes.
- Read-only and ambiguous requests expose no write capability.
- No severity-one defects.
- Rollback succeeds without data conversion.
- Asset licensing is documented.

## 17. Test strategy

### 17.1 Pure backend tests

- Schema type and limit matrix
- Migration and unknown-field round trips
- Canonical serialization
- Revision determinism
- Definition/render-bundle revision independence and registry-pointer updates
- Atomic-write failure injection
- CAS conflicts
- Backup resolution
- Path traversal rejection
- Stable asset and placement identity
- Stable zone-anchor, route, utility-network, and process-binding identity
- Deterministic proposal-generated IDs and exact-diff regeneration
- Dependency-fingerprint and deterministic proposal-ID coverage
- Root discovery and ambiguity
- Intake-job idempotency, restart/resume, cancellation, and staged cleanup
- Unit and axis normalization
- Shell/layout coordinate-frame equality and migration rejection
- Finite transform validation
- Connector compatibility
- Occurrence-qualified route endpoint resolution
- Utility-network topology and capacity rules
- Evidence and authority rules
- Evidence derivation, expiry, revocation, conflict, and source-scope rules
- Floor-capacity and asset contact-load authority matrix
- Facility-shell, policy-set, and vehicle-profile revision rules
- Process binding staleness
- Semantic-plan coordinate rejection
- Proposal, approval, replay, and receipt rules
- Tenant/site authorization and role matrix
- Cross-tenant, cross-site, and cross-object IDOR rejection
- Catalog visibility, site grants, and provenance-redaction projections

### 17.2 Geometry property tests

- Transform round trips
- Translation and rotation invariance
- Camera invariance
- Polygon containment
- AABB and OBB intersection
- Height-interval intersection
- Clearance boundary conditions
- Broad phase compared with brute force
- Stable candidate ranking
- Swept-volume route recheck
- Deterministic finding IDs and order

Failures from generated cases become named regression fixtures.

### 17.3 Python/JavaScript parity

The backend remains authoritative. Pin byte-normalized parity only for the
shared coordinate, primitive, fingerprint, and display contracts used to keep
browser advisory feedback aligned:

- Coordinate conversion
- Canonical placement envelopes
- Zone geometry
- Coarse collision primitives
- Candidate and finding display identity
- Finding codes
- Route fingerprints
- Layout fingerprints

Authoritative candidate ranking, full constraint validation, route planning,
proposal regeneration, and commit eligibility are tested against Python
backend results. A browser mismatch must be replaced by the backend result.

### 17.4 Browser interaction tests

Playwright cases:

- Drag from catalog in plan mode
- Drag from catalog in 3D mode
- Pan, zoom, orbit, Fit, resize, and pane collapse before drop
- Move and rotate
- Duplicate with modifier
- Multi-select
- Lock and unlock
- Zone draw and resize
- Snap alternatives
- Invalid placement
- Clearance visibility
- Route authoring
- Process binding
- Undo and redo
- Save and reopen
- Stale revision
- Ghost dismiss
- Ghost approve
- Editor destroy and remount
- WebGL loss and 2D fallback
- Flag-on and flag-off behavior

### 17.5 Visual evidence

Required screenshot viewports:

- 1920 x 1080
- 1440 x 960
- 1366 x 768
- 390 x 844 fallback

Both light and dark themes.

Canvas checks:

- Luminance variance proves nonblank rendering.
- No clipping.
- Projected 2D/3D selection markers align within 2 pixels.
- Ghost and accepted placement occupy the same projected location.
- Referenced asset geometry is visible and correctly framed.
- Controls and overlays do not overlap.

Scene-occupancy and orbit-difference thresholds are fixture-specific entries in
the benchmark manifest, not universal constants. For example, a dense cell may
target 20 to 85 percent occupancy, while a long warehouse aisle requires a
different framing range. Pixel-change thresholds are omitted for fixtures where
symmetry or proxy rendering makes them meaningless.

The visual manifest enumerates every required test row as:

```text
fixture
view: plan | 3d
theme
viewport
camera or interaction action
expected visible placement IDs
occupancy range
pixel-change threshold, or named replacement assertions
```

Every listed row must produce a screenshot and machine-readable measurement
record. Omitting a pixel threshold requires replacement assertions such as
camera-matrix change, projected-bound movement, visible-ID stability, and
nonblank canvas variance; a rationale alone is not a pass.

### 17.6 Accessibility

- Focusable viewport with accessible name
- Keyboard move and rotate
- Tree and property alternatives for every 3D action
- Visible focus
- Live selection and validation announcements
- Reduced motion
- No keyboard trap
- Zero critical automated accessibility findings

### 17.7 Model and authorization tests

- Read-only request gets no mutation tool.
- Explicit layout request gets one preview tool.
- Model-authored coordinates are rejected.
- Browser-spoofed trusted state is ignored.
- Prompt-injected asset metadata cannot alter tool permissions.
- Unsupported authoritative clearances are rejected.
- Stale layout, referenced asset-definition, shell, policy, vehicle-profile, or
  Process Map revisions fail closed.
- Unrelated catalog and compatible render-bundle updates remain valid.
- Wrong user/session and idempotency replay fail closed.
- Viewer, editor, approver, `catalog_curator`, `authority_curator`, and admin
  role boundaries are enforced.
- URL/path/site/object-ID substitution cannot access another tenant or site.
- Completion language follows receipts.
- No paid model calls in normal PR tests.
- Shadow model evaluations run on pinned fixtures before agent-write rollout.

## 18. Performance budgets

Budgets are enforced on named reference hardware and may change only through a
recorded benchmark decision.

### 18.1 Asset and loading budgets

| Metric | Gate |
| --- | ---: |
| Warehouse-500 boot manifest, compressed transfer | `<= 250 KB` |
| Warehouse-5000 boot manifest, compressed transfer | `<= 500 KB` |
| Warehouse-5000 initially required tile metadata, compressed transfer | `<= 2 MB` |
| First-frame proxy payload | `<= 2 MB` |
| Initial overview geometry | `<= 15 MB compressed` |
| Default individual asset LOD target | `<= 10 MB and <= 150k triangles` |
| Maximum automatically loaded asset | `<= 30 MB` |
| Explicit detail-load threshold | `> 50 MB` |
| Proxy first frame, local | `<= 1.5 s` |
| Proxy first frame at 50 Mbps | `<= 3 s` |
| Interactive overview at 50 Mbps | `<= 4 s` |

The 327 MB legacy facility GLB must enter proxy mode rather than load
automatically.

The boot manifest is the browser projection containing identities, revisions,
bounds, prototype table, and spatial-tile index needed to start interaction. It
does not embed all 5,000 placement records or routes. Canonical repository JSON
is not subject to the 250 KB transfer gate; it remains governed by schema caps.
Transfer measurements use the actual `Content-Encoding` response length under
the protocol in Section 18.3.

### 18.2 Runtime budgets

| Metric | Gate |
| --- | ---: |
| Plan-view scripted pan/zoom/drag frame time p95, standard hardware | `<= 22 ms` |
| Plan-view scripted pan/zoom/drag frame time p95, minimum hardware | `<= 33 ms` |
| 3D scripted orbit/pan/select frame time p95, standard hardware | `<= 22 ms` |
| 3D scripted orbit/pan/select frame time p95, minimum hardware | `<= 33 ms` |
| Picking p95 | `<= 50 ms` |
| Moved-object spatial query p95 | `<= 20 ms` |
| Backend candidate generation p95 | `<= 50 ms` |
| Backend collision/clearance query p95 | `<= 16 ms` |
| Backend full diagnostics worker p95 | `<= 250 ms` |
| Browser advisory spatial response p95 | `<= 50 ms` |
| Forklift route p95 | `<= 500 ms` |
| Main-thread long task | `<= 100 ms` |
| Overview draw calls | `<= 300` |
| Visible overview triangles | `<= 2 million` |
| JavaScript and ArrayBuffer memory | `<= 400 MB` |
| Estimated GPU allocation | `<= 512 MB` |
| Idle rendering stop | `<= 250 ms` |
| Memory growth after 20 remounts | `<= 10 percent` |

Primary contract-scale fixture:

- 500 placements
- 100 zones
- 200 routes

Extended warehouse fixture:

- 5,000 occurrences
- 20 prototypes
- 10,000 clearance volumes

### 18.3 Measurement protocol

Every reported performance gate records:

- Exact fixture hash, browser build, application commit, operating system, CPU,
  GPU, RAM, display resolution, and device-pixel ratio
- Cold-cache and warm-cache runs
- Local and Chrome-emulated 50 Mbps network runs where loading is measured
- Resource Timing entries and actual response lengths
- `PerformanceObserver` long-task entries
- `renderer.info` draw calls, triangles, geometries, and textures
- JavaScript heap and ArrayBuffer memory where the browser exposes them
- A documented GPU-memory estimate from buffer and texture allocations
- Cancellation, context-loss, and remount behavior

Measurement counts:

- Load and discrete-operation latency: one discarded warm-up plus 30 measured
  iterations for each cache and network condition.
- Plan and 3D frame scenarios: five 60-second measured runs after a 10-second
  warm-up per run, with at least 3,000 measured frames in total.
- Backend worker and route microbenchmarks: one warm-up plus 30 measured runs.
- Remount memory: the required 20-cycle sequence repeated five times in a fresh
  browser context.

Report median and p95 over the recorded raw samples using the pinned benchmark
script. The artifact stores every sample as well as the summary. A pass cannot
be based on one favorable run or an unrecorded developer machine.

## 19. Benchmark fixtures

```text
legacy-heavy:
    Current 327 MB Assem3; verifies refusal and fallback

assem3-instanced:
    Same repeated content represented by prototypes and transforms

industrial-cell:
    CNC, robot, bar loader, guard, workstation, cart, routes, and zones

unique-machines-100:
    Limited instancing and heavy LOD switching

warehouse-500:
    Contract-scale authoring and diagnostics

warehouse-5000:
    Large repeated layout and clearance stress

forklift-routing:
    Straight, turn, narrow, reverse, loaded, and unreachable cases

utility-network:
    Compatible, incompatible, capacity, and obstruction cases

lifecycle-churn:
    Remounts, cancellation, LOD transitions, failed chunks, and context loss

degraded-runtime:
    WebGL unavailable, low memory, corrupt hash, and offline operation
```

## 20. Continuous integration and release cadence

Pull request:

- Schema
- Pure operations
- Geometry and property tests
- Python/JavaScript parity
- Deterministic RBAC, IDOR, tool-policy, and provenance-redaction tests
- Proposal dependency, generated-ID, stale, replay, and receipt tests
- No paid model calls

Merge:

- Endpoint and CAS tests
- Failure injection
- Synthetic Playwright
- Process Map frozen regression bars
- Full authorization matrix across repository, API, proposal, approval, apply,
  artifact, and receipt endpoints
- Agent-write flag-on and flag-off deterministic tests

Nightly:

- Screenshot and canvas-pixel matrix
- Geometry fuzzing
- Lifecycle churn
- Performance smoke
- Prompt-injection and forged-observation regression fixtures
- Bounded digest, read-tool pagination, and cursor security tests

Weekly on target Windows/GPU hardware:

- Real GLBs
- Full performance budgets
- Memory and remount profile
- WebGL recovery
- Large warehouse fixture
- Real-server cross-tenant/site isolation probe
- Receipt-backed approved Sage apply and stale-apply rejection

## 21. Feature flags and rollback

Independent flags:

```text
INSPECTORPRO_FACILITY_LAYOUT_VIEWER_V2
INSPECTORPRO_INDUSTRIAL_ASSET_LIBRARY
INSPECTORPRO_FACILITY_LAYOUT_MANUAL_EDIT
INSPECTORPRO_FACILITY_LAYOUT_CONSTRAINTS
INSPECTORPRO_FACILITY_LAYOUT_ROUTING
INSPECTORPRO_FACILITY_LAYOUT_AGENT_PREVIEW
INSPECTORPRO_FACILITY_LAYOUT_AGENT_WRITE
```

Enable agent write last.

Rollback order:

1. Disable agent write.
2. Disable agent preview.
3. Disable routing and constraints if necessary.
4. Keep saved layouts readable.
5. Fall back to the manual editor or legacy read-only viewer.

Rollback must never depend on deleting new layout data. Unsupported newer
schemas open read-only with a clear message rather than being silently
rewritten.

## 22. Security, privacy, provenance, and safety

- The authenticated principal determines tenant and site scope; browser-supplied
  `tenantId` or `siteId` values never grant access.
- Viewer, editor, approver, `catalog_curator`, `authority_curator`, and admin
  permissions are enforced independently at repository, API, proposal,
  approval, and apply boundaries.
- Object existence is not disclosed across tenant or site boundaries.
- Local single-user mode uses an explicit local principal and the same policy
  checks.
- Raw customer CAD is not sent to models unless explicitly authorized.
- Sage receives bounded semantic evidence, not raw triangles.
- Browser state cannot become trusted evidence by naming convention.
- Asset and policy origins are explicit.
- Customer geometry and labels are excluded from telemetry by default.
- Proposal telemetry uses IDs, counts, timings, findings, and outcomes.
- Public asset publication requires licensing evidence.
- AI-inferred capabilities and clearances remain visibly inferred.
- InspectorPro reports planning validation, not regulatory approval.
- Site-specific code and safety review remain customer responsibilities.

## 23. Telemetry

Record:

- Engine, schema, router, and policy versions
- Layout size and asset counts
- Prototype and instance counts
- Load, decode, render, pick, plan, route, and commit latency
- Draw calls and visible triangles
- Memory estimates
- Candidate and rejection counts
- Finding-code counts
- Accepted, alternative, dismissed, cancelled, stale, and failed proposals
- Number of automatic, manual, and locked placements
- Number of existing placements moved
- Process binding revision status

Do not record raw geometry, full customer labels, notes, route coordinates, or
clearance shapes without explicit diagnostic capture.

## 24. Major risks and mitigations

### Risk: The current monolithic viewer becomes the editor

Mitigation:

- New modular renderer and layout document.
- Legacy viewer remains a read-only compatibility surface.

### Risk: Camera fitting corrupts world coordinates

Mitigation:

- Fit changes camera only.
- Camera-invariance parity and Playwright tests.

### Risk: Heavy CAD makes editing unusable

Mitigation:

- Prototypes, instancing, LODs, proxies, progressive load, strict budgets.

### Risk: Render geometry becomes collision authority

Mitigation:

- Separate 2.5D and compound collision/clearance proxies.

### Risk: Process Map Builder is duplicated

Mitigation:

- Shared transaction kernel and domain adapters.
- Frozen Process Map regression bars.

### Risk: Shared-kernel refactor breaks Process Map

Mitigation:

- P1 is isolated.
- Process Map adapter lands first.
- No facility work depends on P1 until all existing bars pass.

### Risk: Machine-library roots are selected incorrectly

Mitigation:

- Dependency-graph root resolver.
- Ambiguity blocks automatic publication.

### Risk: Third-party assets cannot be redistributed

Mitigation:

- Private/local-only readiness separate from public readiness.
- Licensing review before common-library publication.

### Risk: Missing clearances are mistaken for safe placement

Mitigation:

- Missing evidence yields an `unverified` or blocked validation outcome while
  retaining its actual evidence status.
- Only sourced hard rules can produce hard safety validation.

### Risk: Sage invents geometry or approval

Mitigation:

- Semantic schema rejects coordinates.
- One preview tool.
- Receipt-grounded responses.

### Risk: Visual proximity changes process meaning

Mitigation:

- Process Map is the source of process intent.
- Facility links are revision-bound and one-way.

### Risk: Large-layout planning blocks interaction

Mitigation:

- Spatial indexes, workers, cancellation, scoped planning, demand rendering.

### Risk: Browser/GPU incompatibility blocks all work

Mitigation:

- Functional 2D and proxy fallback.

## 25. Self-use soak and pilot gates

### 25.1 Self-use soak

Duration:

- Two weeks

Coverage:

- At least 10 saved layouts
- At least 50 editing sessions
- At least 20 agent previews
- At least 10 explicitly approved, receipt-backed Sage applies
- At least five dismissed previews that leave saved bytes unchanged
- At least five deliberately stale or unauthorized apply attempts that fail
  closed
- At least five reopen cycles per layout
- At least one warehouse zone
- At least one manufacturing cell
- At least one rollback drill

The agent-write flag is enabled in the controlled soak environment for the
approved-apply cases. The rejected, stale, wrong-role, and dismissal cases run
against the same write-capable build so their safety results are meaningful.

Required result:

- Zero data loss
- Zero unapproved writes
- Zero stale proposals applied
- Every approved apply matches its preview diff and canonical receipt
- Zero severity-one defects
- No unresolved memory growth above budget
- Successful rollback

### 25.2 Pilot gate

Pilot scope:

- Two or three users
- One real manufacturing cell
- One warehouse lane
- Five successfully saved and reopened layouts
- Reviewed safety and unresolved findings
- Documented asset provenance and licensing

Required product statement:

```text
InspectorPro assists industrial layout planning and validation. It does not
replace required facility, safety, regulatory, or professional engineering
approval.
```

## 26. Definition of done

The industrial spatial-layout platform is complete for pilot when:

1. Industrial source assets are versioned separately from placed occurrences.
2. Each placement has a stable ID and a canonical meter-based transform.
3. Top and 3D views edit one state and remain synchronized.
4. Camera actions never change saved geometry.
5. Users can create dimensioned zones and place assets from a tree.
6. Drag/drop remains correct after pan, zoom, orbit, Fit, pane resize, and
   browser resize.
7. Users can move, rotate, duplicate, multi-select, lock, delete, undo, redo,
   save, and reopen.
8. Repeated assets render through prototypes and instancing where eligible.
9. Collision, zone, and clearance validation uses deterministic proxies.
10. Missing safety evidence is visible and never reported as safe.
11. Routes use typed connectors and revision-bound geometry.
12. Forklift routes validate vehicle heading, turning, width, and swept volume.
13. Process Map bindings reference exact nodes, edges, and revision.
14. A Process Map change invalidates a stale layout proposal.
15. Sage observes trusted state and evidence.
16. Sage proposes semantic outcomes but never coordinates.
17. One complete ghost preview appears in synchronized 2D and 3D.
18. Dismissal changes nothing.
19. One explicit approval applies the exact preview atomically.
20. Stale, replayed, altered, unauthorized, or invalid proposals fail closed.
21. Execution receipts report exactly what changed.
22. Performance, visual, accessibility, lifecycle, and rollback gates pass.
23. The legacy 327 MB facility asset is never required for normal authoring.
24. The two-week soak and pilot gates are met.
25. Facility shells, policy sets, and vehicle profiles are first-class,
    revisioned authority assets.
26. Tenant, site, and role authorization is enforced at every read and write
    boundary.
27. Regenerated proposals preserve exact deterministic object identities.
28. Sage uses a bounded trusted digest plus stable-ID read tools at large scale.
29. The backend revalidates every save and proposal and wins any browser
    disagreement.
30. Repeated-placement connectors and utility-network endpoints resolve without
    ambiguity.
31. Layout and shell coordinate frames match exactly or require an explicit
    migration proposal.
32. Floor-load verdicts use evidence-qualified capacity, mass, support, and
    contact-load data.
33. Render-bundle publication can improve visuals without invalidating layout
    geometry or mutating an asset definition.
34. Interrupted asset-intake jobs resume or clean up without exposing partial
    catalog state.
35. Client projections redact protected source paths and cross-tenant asset
    metadata.

## 27. Recommended approval boundary

Use three planning and review blocks:

```text
Block A: P0-P6
    Contracts, shared transaction kernel, asset intake, domain persistence,
    scalable rendering, manual editing, and deterministic constraints

Block B: P7-P8
    Routes, Process Map binding, and ghost proposals

Block C: P9-P11
    Sage planning, workflow packages, hardening, soak, and pilot
```

These blocks are not bulk implementation authorization. Every phase still
requires an explicit start decision after its prior required checkpoint.

Do not pre-authorize Block B until the complete P6 vertical slice saves,
restores, and enforces deterministic collision and containment correctly.

Do not pre-authorize Block C until deterministic complete-layout previews are
useful without Sage.

The governing implementation principle is:

> Sage decides what the proposed industrial layout means. Deterministic
> InspectorPro systems decide where assets can go, how they connect, what is
> supported by evidence, and whether the exact proposal is allowed to commit.
