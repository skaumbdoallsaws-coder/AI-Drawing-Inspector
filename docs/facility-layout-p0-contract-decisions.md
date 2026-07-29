# Facility Layout P0 Contract Decisions

Date: 2026-07-28

Status: P0 implementation complete; final integrated verification recorded in
the named baseline addendum

Governing plan:
`docs/industrial-layout-platform-implementation-plan.md`, revision 2

## 1. Purpose

P0 freezes the vocabulary and authority boundaries needed before a Facility
Layout editor can place machines, racks, workstations, vehicles, routes, or
utilities. It intentionally adds no user-visible feature and no production
write path.

The executable contracts prevent later phases from making these mistakes:

- Persisting browser pixels or camera transforms as facility geometry
- Treating render triangles as collision or clearance authority
- Treating repeated placements as one asset occurrence
- Binding a route endpoint to a visible label instead of a qualified object
- Persisting one zone ID when zones overlap
- Treating an inferred clearance or load as an authored safety rule
- Exposing protected source paths through normal catalog projections
- Letting a model author coordinates, approvals, evidence authority, or
  low-level mutations
- Applying a proposal after any bound dependency changes

## 2. Frozen Document Classes

The platform separates three asset classes:

1. `IndustrialAssetDefinition`
   Reusable equipment identity, normalized local geometry, placement rules,
   connectors, loading, clearances, capability, safe provenance, and readiness.
2. `FacilityLayoutDocument`
   Site-bound zones, placement occurrences, routes, utility networks, and
   Process Map bindings.
3. `ProcessMapDocument`
   Product occurrences, process stages, topology, precedence, and process
   requirements. It remains separate from the Facility Layout.

Supporting authority documents are:

- `FacilityShell`
- `PolicySet`
- `VehicleProfile`
- `TrustedSourceRegistry`
- `EvidenceRecord`

Deleting a placement never deletes its source asset. Updating a render bundle
never silently changes an asset definition or a layout.

## 3. Version And Revision Glossary

`schemaVersion`

: Integer compatibility version for one JSON document shape. Facility Layout
  v1 is editable. The semantic v0.2 source has a named migration. A document
  with a newer unsupported version must be surfaced read-only and must never be
  rewritten through a v1 writer.

`layoutRevision`

: Server-derived SHA-256 revision of canonical layout content. It is a CAS
  token and is not persisted inside the layout document.

`shellRevision`, `policySetRevision`, `vehicleProfileRevision`

: Server-derived revisions of authority documents. They are referenced by
  layouts and proposals but are not stored inside their own canonical content.

`sourceRevision`

: Hash over source-file hashes, selected configuration, and extraction inputs.
  A raw CAD file hash alone is not a complete source revision.

`assetDefinitionRevision`

: Hash over normalized spatial and semantic asset content used for planning.
  Layout placements bind this exact revision.

`renderBundleRevision`

: Hash over compatible visual artifacts such as LOD geometry, textures, and
  thumbnails. A render-only update does not invalidate a layout.

`coordinateFrameFingerprint`

: Hash of the exact shell coordinate-frame definition. The v1 layout frame must
  equal the referenced shell frame and `shellToLayout` is identity.

`dependencyFingerprint`

: Canonical hash binding a proposal to layout, asset-definition, shell, policy,
  vehicle-profile, Process Map, spatial-engine, router, and obstacle revisions.

## 4. Coordinate Contract

Persisted facility geometry uses:

- Meters
- Right-handed coordinates
- `+Y` vertical
- `X/Z` floor plane
- XYZW quaternions
- Finite values only
- Uniform placement scale exactly `1`

Meter positions round half-to-even to six decimals before hashing. Quaternion
components round to nine decimals, are normalized, and use one canonical sign.
Negative zero becomes zero.

The asset render transform remains inspectable:

```text
facilityWorld
    * placementTransform
    * assetNormalization
    * sourceGeometry
```

Camera orbit, pan, zoom, viewport size, pane width, display-root offsets, and
device pixel ratio are session state. They do not alter persisted positions,
zones, connectors, routes, or clearances.

## 5. Identity And Topology

Committed manual objects receive one stable server ID. Proposal-generated IDs
are deterministic functions of `proposalId` and a plan-local object ID.

Typed prefixes are frozen for proposals, placements, zones, zone anchors,
routes, utility networks, network nodes, network segments, and process
bindings.

Repeated placements of one asset definition:

- Have distinct `placementId` values
- May share one render prototype
- Retain independent transforms and position ownership

Route endpoints are discriminated and occurrence-qualified:

- Placement connector: `placementId + connectorId`
- Shell connector: `shellId + shellRevision + connectorId`
- Zone anchor: `zoneId + anchorId`

Utility networks use real endpoint and junction nodes. A segment references
network-node IDs; it does not terminate on an edge or visible label.

Zone membership is computed from world geometry. A placement does not persist a
singular `zoneId`, because a placement may occupy multiple overlapping zones.

Process bindings live at layout level and may refer to multiple placement and
route occurrences. They are not embedded as a single field on a placement.

## 6. Spatial Authority

The Python backend is authoritative for:

- Geometry normalization
- Collision and clearance validation
- Candidate generation and ranking
- Route and utility validation
- Proposal regeneration
- Commit eligibility

Browser geometry is advisory and optimized for interaction. Browser/backend
disagreement resolves to the backend result.

Initial collision authority uses reviewed 2.5D footprints and vertical
intervals, with exact typed proxies where required. Render meshes are never the
default collision, clearance, or safety model.

Position ownership is:

- `auto`: deterministic arrangement may move it
- `manual`: preserve by default after user movement
- `locked`: no automatic or manual planning movement

A user drag changes `auto` to `manual`.

## 7. Evidence And Safety Authority

Evidence status is one of:

- `authored`
- `derived`
- `inferred`
- `unknown`

Sage cannot upgrade an evidence status. Publication and approval do not convert
an inferred fact into an authored fact.

An inferred clearance remains advisory. A hard clearance rule requires
authoritative evidence and an applicable reviewed policy.

`floor_load_exceeded` may be emitted only when both the applicable floor
capacity and asset contact-load model are authored or validly derived. Missing
or inferred inputs produce `floor_load_unverified` and cannot yield a safe
verdict.

The legacy Facility Layout's rough rack envelopes and 0.06131 m alignment
residual remain demo/inferred evidence. They cannot support clearance, loading,
or placement-readiness claims.

## 8. Asset Catalog And Readiness

The registry is authoritative and is updated last. Directory scans may report
drift but cannot select the published definition or render bundle.

Visibility is:

- `private`
- `site_shared`
- `tenant_shared`
- `common`

Tenant and site scope come from the authenticated server principal, never a
browser field. Cross-scope assets are hidden as not found.

Normal viewer/editor projections omit:

- Raw source paths
- Local filesystem paths
- Internal storage keys
- Protected license documents
- Internal notes

Readiness gates are independent:

- `visualReady`
- `placementReady`
- `planningReady`
- `publicReady`

A useful picture does not imply valid placement geometry. Placement readiness
requires a reviewed canonical frame, alignment within tolerance, floor anchor,
footprint, and collision proxy. Planning readiness additionally requires the
applicable reviewed loading, connector, and clearance evidence.

The two selected real machine-library candidates are intentionally fail-closed.
Without CAD extraction, their frame, floor anchor, footprint, and collision
proxy remain unknown.

## 9. Authorization And Transactions

Initial roles are:

- `viewer`
- `editor`
- `approver`
- `catalog_curator`
- `authority_curator`
- `admin`

Proposal application requires:

- An approver role
- Explicit approval
- Principal and session binding
- Exact diff binding
- Dependency-fingerprint binding
- An idempotency key
- Fresh current dependencies

Implicit apply, altered proposals, stale proposals, and replay fail closed.

## 10. Observation Boundary

Trusted server objects are:

- `facility_layout.state`
- `facility_layout.evidence`

The model receives a bounded `facility_layout.digest` and may use bounded,
paginated read tools. It does not receive unrestricted geometry.

Sage cannot submit world coordinates or screen rectangles. It requests semantic
outcomes; the deterministic planner computes geometry.

`build_facility_layout_preview` is the high-level preview boundary. It stores an
expiring proposal and an authorized UI artifact, returns a compact structured
receipt, and writes no Facility Layout. Low-level mutations are not exposed to
the model.

## 11. P0 Artifact Index

Contracts:

- `static/contracts/facility-layout-schema-v1.json`
- `static/contracts/facility-authority-schema-v1.json`
- `static/contracts/facility-layout-spatial-contract-v1.json`
- `static/contracts/facility-layout-authorization-v1.json`
- `static/contracts/facility-layout-observation-contract-v1.json`
- `static/contracts/industrial-asset-definition-schema-v1.json`
- `static/contracts/industrial-asset-catalog-contract-v1.json`

Executable fixtures:

- `tests/fixtures/facility_layout/empty_cell.json`
- `tests/fixtures/facility_layout/two_asset_cell.json`
- `tests/fixtures/facility_layout/overlapping_zones.json`
- `tests/fixtures/facility_layout/repeated_assets.json`
- `tests/fixtures/facility_layout/utility_cell.json`
- `tests/fixtures/facility_layout/p0_authority_documents.json`
- `tests/fixtures/facility_layout/benchmark-fixture-manifest.json`
- `tests/fixtures/facility_layout/assets/synthetic-normalized-machine.json`
- Two fail-closed real asset-intake candidates and two reviewed private
  placement-ready normalized assets under
  `tests/fixtures/facility_layout/assets/`
- Migration compatibility fixtures under
  `tests/fixtures/facility_layout/migration/`
- Renderer, offline-loader, and real rack-instancing artifacts under
  `tests/fixtures/facility_layout/rendering/`

Executable contract tests:

- `tests/test_facility_layout_p0_contracts.py`

Named reports:

- `docs/facility-layout-p0-baseline-report.md`
- `docs/facility-layout-p0-asset-normalization-report.md`
- `docs/facility-layout-p0-migration-coordinate-report.md`
- `docs/facility-layout-p0-renderer-dependency-spike.md`

## 12. Exit-Gate Status

Implemented in the contract slice:

- Stable typed IDs
- Finite meter-space transforms
- Deterministic proposal and generated-object identity
- Camera/layout separation
- Executable layout, shell, policy, vehicle, route, utility, asset, evidence,
  visibility, authorization, and observation contracts
- Five canonical layout fixtures
- Fail-closed real asset intake
- Benchmark-fixture status manifest

Resolved by named P0 spikes:

- Two private real assets have reviewed local frames, floor anchors,
  conservative footprints, collision proxies, and nonblank render artifacts.
- WebGL/Three.js is selected as primary from measured evidence; virtualized SVG
  is the degraded fallback; full-redraw Canvas 2D is rejected as primary.
- Exact Three r184 modules are pinned locally with package provenance, hashes,
  and retained MIT license.
- A network-denied browser proof imports the official GLTFLoader, parses valid
  GLB, rejects corrupt GLB, and renders a nonblank WebGL 2 scene.
- One real 8x16 rack prototype represents six stable occurrences through
  instance groups with a 6x draw-call reduction and instance-aware picking.
- Semantic v0.2 retains its full parsed source payload and unsupported newer
  schemas open read-only without byte mutation.
- Final integrated frozen-bar results are appended to
  `docs/facility-layout-p0-baseline-report.md`.

P0 does not authorize public asset distribution, safety/planning claims,
production r184 application migration, or release-scale performance claims.
Those gates remain assigned to later phases.
