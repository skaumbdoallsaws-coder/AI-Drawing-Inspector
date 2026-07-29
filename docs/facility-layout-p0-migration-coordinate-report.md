# Facility Layout P0 Migration and Coordinate Golden Report

Date: 2026-07-28

Status: P0 contract report

Scope: Read-only inspection and additive fixtures only. This track does not
modify application code, endpoints, generated training artifacts, schemas, or
the legacy semantic source.

## 1. Decision summary

The current `facility-layout-semantic-v0.2` document can be imported without
losing JSON data, but it cannot be promoted automatically to a writable,
engineering-authoritative Facility Layout v1 document.

The migration contract is:

1. Preserve the complete parsed v0.2 tree under
   `extensions.inspectorproLegacySemanticV0_2.payload`.
2. Record the original byte length and SHA-256 before parsing.
3. Create only a `draft`, read-only v1 compatibility bundle.
4. Require server-supplied tenant, site, shell, policy, asset, orientation, and
   timestamp context. Do not invent those fields from v0.2.
5. Promote a legacy coordinate only when the mapped asset definition proves
   how the legacy component origin maps to its canonical placement origin.
6. Mark all rough envelopes, aisle polygons, path seeds, capacity facts, and
   screenshot annotations as `inferred` or `unknown`. They cannot satisfy a
   hard clearance, loading, route, utility, or safety requirement.
7. Require the layout coordinate frame to equal the referenced shell frame
   exactly. `shellToLayout` is identity and is not a persisted transform.
8. Keep camera and display-root recentering out of persisted geometry.
9. Open unsupported newer schemas read-only. Never pass them through the v0.2
   migrator, down-convert them, or rewrite their bytes.

The distinction that governs every row in this report is:

```text
Source fidelity:
    Was the legacy JSON value copied without changing its meaning?

Engineering authority:
    May that value satisfy a v1 deterministic hard requirement?
```

A literal source value can be authoritative for migration fidelity while still
being only `inferred` for engineering decisions.

## 2. Inspected baseline

### 2.1 Source and generated artifacts

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `facility_layout_semantic.json` | 99,910 | `269ed9e33c32f7937221b4cbf26c52ea61b529999c96c16f38b4cd5d02f6077d` |
| `facility_layout_probe_with_folders.json` | 243,131 | `f04adbc374622a7210377f9c43b4ebf35e166c63950cfeb125f93197865e40df` |
| `generated/training/facility-layout/facility_layout.json` | 243,131 | `c07f8bd574ea151d1a6e2060e8716ec96db1279bf11b6e0769a03e737e0b7c0a` |
| `generated/training/facility-layout/facility_layout_attach_check.json` | 243,131 | `30dbc74ad6cb2ea721607794bae467b6c2d5a6f3fd1a5e1b9154c035a2aa2f55` |
| `generated/training/facility-layout/facility_layout_check.json` | 243,131 | `9531b1d5b699fd0a81216c03c1d0835bc69dae9837005b0d58263443663458fe` |
| `generated/training/facility-layout/Assem3_colored.glb` | 327,184,996 | `da2be02acea430027324857e58db3ddee81713dcf9b54e38d45b830671898ce2` |

The semantic document names `facility_layout_probe_with_folders.json` as its
source and carries that source's extraction timestamp. The three generated
JSON files are later extractions. All four extractor JSON files contain 271
components, 29 mates, 30 level-one components, and the same ten semantic
groups.

The later `facility_layout.json` has a different component enumeration order,
but name-based comparison found every one of the 24 rack and five forklift
positions used by the semantic document.

The semantic payload contains:

| Collection | Count |
| --- | ---: |
| Rack rows | 5 |
| Rack instances | 24 |
| Material-handling assets | 5 |
| Inferred row-to-row aisles | 3 |
| Layout-map floor zones | 5 |
| Layout-map aisle corridors | 4 |
| Path-graph nodes / edges | 6 / 5 |
| Semantic-index aliases | 55 |

The implementation plan records the GLB as the `legacy-heavy` fixture, with
approximately 11.75 million vertices, 3.92 million triangles, 245 meshes, and
245 materials. It is compatibility evidence, not a normal editor payload.

### 2.2 Current code and endpoints

The current Facility Layout path remains an analysis viewer:

- `server.py:12626-12641` loads the semantic JSON without schema migration.
- `GET /api/training/facility-layout/semantic` returns it verbatim.
- `POST /api/training/facility-layout/capacity` returns a rough estimate.
- `POST /api/training/facility-layout/route` runs deterministic Dijkstra.
- `GET /api/training/facility-layout/layout-analysis` returns a what-if result.
- There is no v1 layout repository, CAS save, placement operation, or Facility
  Layout write endpoint in the inspected code.
- `static/index.html:15525` hard-codes the 327 MB GLB.
- `static/index.html:30150-30195` draws route geometry as a child of the
  recentered model root so the current display remains aligned.
- `static/index.html:38162-38195` implements Fit by mutating
  `group.position.sub(center)`.

The existing endpoints must remain legacy read-only endpoints during
migration. They must not be treated as a v1 repository API.

The P0 schemas inspected during this track are:

- `static/contracts/facility-layout-schema-v1.json`
- `static/contracts/facility-authority-schema-v1.json`
- `static/contracts/facility-layout-spatial-contract-v1.json`
- `static/contracts/facility-layout-authorization-v1.json`
- `static/contracts/facility-layout-observation-contract-v1.json`

The migration fixtures use their current field names and required structures.

## 3. Coordinate golden evidence

### 3.1 Extractor-to-semantic positions

`SolidWorksExtractor/Services/AssemblyExtractor.cs:663-684` reads
`IComponent2.Transform2.ArrayData` and labels translation indices 9 through 11
as meters. `tools/facility_layout_semantics.py:24-48` copies that translation
and rounds each component to six decimal places.

Name-based comparison of all 29 semantic occurrence positions against each of
the four extractor JSON files produced:

```text
matched positions:             29
missing positions:              0
maximum delta:  0.00000057336027128876049 m
mean delta:     0.00000045663771282918088 m
```

The maximum is below the v1 pure transform serialization gate of `1e-6 m`.
Therefore the six-decimal `positionMeters` values are a valid golden for
legacy-value retention. This does not prove that the component origin is the
correct v1 floor anchor.

The semantic generator drops occurrence rotation. The companion extractor
JSON contains quaternions in WXYZ order, while v1 requires XYZW. A semantic-only
migration therefore cannot create a complete placement transform. A pinned,
matching companion extractor plus an asset-origin binding may supply and
convert rotation. Row orientation is not a substitute for occurrence rotation.

### 3.2 Units and axes

The legacy evidence agrees on these facts:

- `source.units` is `meters`.
- `layoutMap.coordinateFrame.cadUnits` and `.units` are `meters`.
- Drawing dimensions are inches with `inchToMeter = 0.0254`.
- Rack labels are feet with `footToMeter = 0.3048`.
- The floor plane is X/Z and Y is vertical.
- Current routing defines `+X` as east and `+Z` as south.
- The stored SolidWorks-to-GLB matrix is exact identity.

The legacy JSON does not explicitly establish a named datum, reviewed floor
surface, floor elevation, or evidence-qualified handedness claim. Those fields
must come from the migration context and a draft shell. They cannot be inferred
silently by the v1 loader.

### 3.3 SolidWorks-to-GLB check

`tools/facility_coordinate_resolver.py` matches 24 rack component centerline
bounds to GLB mesh bounds and records:

```text
emitted transform:                identity
measured best-fit translation:    (0.045, -0.041647, 0) m
rotation from identity:           0.07395 degrees
fitted scale:                     1.001203
maximum residual:                 0.06131 m
mean residual:                    0.06120 m
RMS residual:                     0.06120 m
legacy residual tolerance:        0.50 m
legacy containment epsilon:       0.10 m
```

The live read-only check returned:

```text
CHECK PASS: 24 racks, maxResidual=0.0613m, within_bounds=True
```

That pass means only that the legacy viewer's permissive `0.50 m` check passed.
The maximum residual is 61.31 times the v1 `0.001 m` placement-readiness target.
It is demo-only and cannot support collision, clearance, swept-volume, or
safety claims.

The resolver emitted identity because its current thresholds treat rotation
below `0.5` degrees, scale error below `0.002`, and translation below `0.10 m`
as noise. Those are legacy display thresholds, not v1 engineering gates.

### 3.4 Floor elevation is unresolved

All 29 level-one rack and forklift transforms have raw
`Y = -1.566829203 m`; v0.2 rounds that to `-1.566829 m`.

Current code uses two different display heuristics:

- `tools/facility_routing.py:122-126` uses the minimum rack occurrence Y as the
  route floor.
- `static/index.html:30298-30310` uses the loaded GLB bounding-box minimum Y for
  the grid.

Neither is a reviewed floor surface. The fixture uses `-1.566829 m` only as an
explicit migration-context compatibility inference. Its companion shell is
`draft`, contains no floor feature, and carries an unresolved finding. A
production shell curator must confirm the datum and floor elevation.

### 3.5 Drawing and aisle evidence

The semantic document records:

```text
720 in x 552 in = 18.288 m x 14.0208 m
168 in          = 4.2672 m
```

The first two computed row-to-row spacings are `4.2672 m`; the third is
`4.2632 m`. The manually annotated layout map uses `4.2672 m` for all three
primary corridors. The discrepancy is small but proves that a drawing label,
row-center spacing, and clear driveable width are different claims.

The screenshot descriptions have no registered trusted-source revision,
locator, reviewer, or claim scope. They remain inferred until those authority
records exist.

## 4. Shell/layout frame invariant

For every v1 document:

```text
layout.coordinateFrame == referencedShell.coordinateFrame
SHA256(canonical(layout.coordinateFrame))
    == layout.sourceShellRef.coordinateFrameFingerprint
shellToLayout == identity
```

Equality is field-for-field after canonical numeric normalization:

```json
{
  "units": "m",
  "handedness": "right",
  "upAxis": "+Y",
  "floorAxes": ["+X", "+Z"],
  "datumId": "...",
  "floorElevation": 0.0
}
```

Rules:

1. `transformSolidWorksToGlb` remains legacy provenance. It is not
   `shellToLayout`.
2. The viewer's `group.position` is display state. It is not a datum offset.
3. Camera Fit may change only the camera and controls target in the new editor.
4. No loader may reconcile a shell/layout mismatch by translating placements.
5. A changed datum, axis, units, or floor elevation requires an explicit
   migration proposal.
6. A missing or stale shell revision makes the layout read-only and invalid
   for writes.
7. A draft compatibility shell cannot satisfy placement-ready or hard-safety
   validation.

The compact fixture pins this frame fingerprint:

```text
cca6e5480e44494e9e35aff98140e0297c0a0ff70bd1bddacd850bc8c34c1027
```

## 5. Authority classification

The v1 evidence vocabulary is exactly:

```text
authored | derived | inferred | unknown
```

`unverified` is a validator outcome, not an evidence status.

No engineering field in the current v0.2 file qualifies as `authored` merely
because it appears in JSON. The source CAD, drawings, and screenshots are not
registered in a `TrustedSourceRegistry`, and the extraction method is not a
pinned approved derivation in the authority repository.

| Legacy fact | Migration fidelity | Initial v1 status | Permitted use |
| --- | --- | --- | --- |
| Schema version, timestamps, file names, hashes, counts | Copy exactly | Provenance only | Audit and source matching |
| SolidWorks component translation in meters | Copy exactly | `inferred`, or `derived` only after trusted-source and method registration | Read-only display; placement only with asset-origin proof |
| Companion extractor quaternion | Not present in v0.2; bind explicitly | `derived` when source and method are pinned | Complete placement rotation after WXYZ-to-XYZW conversion |
| Component and semantic-group names | Copy exactly | `inferred` identity hint | Asset matching; never an asset-definition revision |
| GLB byte length and SHA-256 | Copy exactly | `derived` artifact identity | Detect stale semantic/GLB pairs |
| Identity SW-to-GLB matrix | Copy exactly | Demo alignment | Legacy rendering only |
| Drawing unit conversions | Copy exactly | `derived` arithmetic | Unit conversion, not source authority |
| 720 x 552 and 168 inch labels | Copy exactly | `inferred` until drawing is registered and reviewed | Annotation and warning |
| Rack centerline bounds and row spacing | Copy exactly | `derived` from occurrence origins, but not safety geometry | Explanation and candidate hints |
| Rack usable envelopes and shelf levels | Copy exactly | `inferred`, demo-only | Rough capacity estimate only |
| Nearest-rack relationships | Copy exactly | `derived` index | Search and explanation |
| Inferred aisles | Copy exactly | `inferred`, demo-only | Legacy route seed only |
| Approximate floor-zone polygons | Copy exactly | `inferred`, demo-only | Read-only overlay; never containment authority |
| Aisle-corridor polygons and west connector | Copy exactly | `inferred`, demo-only | Read-only overlay and seed |
| Path graph | Copy exactly | `inferred`, demo-only | Recomputable seed; not a v1 `Route` |
| Capacity model and answers | Copy exactly | `inferred`, demo-only | Planning estimate with assumptions |
| Assumptions and next-data-needed lists | Copy exactly | `unknown` unresolved items | Block or warn; never fill facts |
| Unknown properties at any depth | Copy exactly | Opaque | Round-trip only |

Sage, publication, approval, and repeated use cannot upgrade these statuses.

## 6. Lossless migration algorithm

### 6.1 Dispatch

Read the raw bytes once and reject ambiguous JSON such as duplicate object keys
or non-finite numbers.

| Detected version | Action |
| --- | --- |
| `"facility-layout-semantic-v0.2"` | Run the explicit legacy migrator |
| Integer `1` | Validate and open as v1 |
| Integer greater than `1` | Open raw document read-only; do not migrate |
| Missing, malformed, or unknown string | Preserve bytes and fail clearly; do not guess |

### 6.2 Required migration context

The v0.2 payload alone is insufficient. The server must supply:

- Authenticated tenant and site scope
- Stable layout ID
- Exact draft or reviewed shell ID and revision
- Exact shell coordinate frame and fingerprint
- Exact policy-set ID and revision
- Server-owned `createdAt` and `updatedAt`
- Asset ID and asset-definition revision for each promoted occurrence
- Source-origin-to-canonical-origin mapping for each promoted asset
- Pinned occurrence quaternion source and source order
- Evidence bindings for every promoted inferred claim

If any required context for an object is absent, preserve that object only in
the legacy extension. Do not create a partial placement with identity rotation,
an invented asset revision, or an assumed floor anchor.

### 6.3 Steps

1. Hash the original bytes and record their byte length.
2. Parse with duplicate-key and finite-number checks.
3. Deep-copy the complete source tree before projecting any field.
4. Resolve server context and authorize the migration site.
5. Load exact shell and policy revisions.
6. Assert layout/shell coordinate-frame equality and fingerprint equality.
7. Assign deterministic typed IDs.
8. Promote only context-qualified entities.
9. Keep every rough or approximate promotion visibly inferred and read-only.
10. Store the complete source copy, byte length, and source hash under the
    reserved legacy extension.
11. Validate schema, limits, references, evidence, and canonical numbers.
12. Assert deep equality between the parsed input and retained payload.
13. Assert every promoted coordinate against its source and expected
    normalization.
14. Persist companion authority/evidence records first, then the layout through
    the repository's atomic CAS path.
15. Return a read-only compatibility envelope until authority review removes
    every blocking condition.

Migration is all-or-nothing. Any truncation, unknown-field loss, shell mismatch,
or unresolved reference leaves the original source untouched and read-only.

### 6.4 Deterministic legacy IDs

Fixture IDs use:

```text
canonicalBytes =
    ASCII JSON with sorted keys, compact separators, finite numbers, and no
    trailing line terminator

digest = SHA256(canonicalBytes)

typedId = <typePrefix> + "-legacy-" + first20Hex(digest)
```

The identity input includes the source schema, facility identity, object kind,
and legacy object identity. The exact JSON values hashed for this fixture are:

```json
{
  "layout": {
    "facilityId": "Assem3-compact",
    "kind": "layout",
    "sourceSchemaVersion": "facility-layout-semantic-v0.2"
  },
  "shell": {
    "facilityId": "Assem3-compact",
    "kind": "shell",
    "sourceSchemaVersion": "facility-layout-semantic-v0.2"
  },
  "policy": {
    "facilityId": "Assem3-compact",
    "kind": "empty-policy",
    "siteId": "site-fixture"
  },
  "placement": {
    "componentName": "Rack-01",
    "facilityId": "Assem3-compact",
    "kind": "placement"
  },
  "zone": {
    "facilityId": "Assem3-compact",
    "kind": "zone",
    "legacyId": "Zone_North_Rack_Bank"
  }
}
```

Each named child object is canonicalized and hashed independently; the wrapper
object and labels above are explanatory and are not part of any digest. The
compact fixture pins:

```text
layout:    fl-legacy-33ea0aeb31bb98a2f8f0
shell:     shell-legacy-cc6490e95e7c50f92ed1
policy:    policy-legacy-bd9684d48638d0524305
placement: pl-legacy-a8a737880b15ffbae445
zone:      zn-legacy-b8c3ba5b369e128fd3af
```

The same input and migration context must regenerate the same IDs.

## 7. Migration matrix

| v0.2 path | v1 destination | Transformation | Gate |
| --- | --- | --- | --- |
| `schemaVersion` | `schemaVersion = 1` plus retained payload | Exact version dispatch | Must equal the one supported legacy string |
| `generatedAt` | Legacy extension only | Copy exactly | Never use as `createdAt` |
| `source.*` | Protected provenance plus legacy extension | Copy exactly; redact client path projections | Register source before authoritative use |
| `facility.id` | Deterministic `layoutId` input | Hash with schema and object kind | Never trust as tenant/site identity |
| `facility.displayName` | `displayName` | Copy if valid; otherwise sanitize without changing retained source | Label limit |
| `facility.statistics` | Legacy extension and optional digest | Copy exactly | Informational only |
| Server context | `association` | Server supplies site and optional area | Browser source cannot grant scope |
| Legacy frame evidence | `coordinateFrame` | Normalize tokens to `m`, `right`, `+Y`, `["+X","+Z"]`; bind datum and floor from shell context | Exact shell equality required |
| Migration shell | `sourceShellRef` | Copy exact IDs, revision, and frame fingerprint | Shell must exist; draft shell keeps import read-only |
| Migration policy | `policySetRef` | Copy exact IDs and revision | Never synthesize safety rules |
| `rackRows[*].rackInstances[*]` | `placements[*]` conditionally | Bind asset; map origin; copy rounded position; supply and convert pinned quaternion; scale 1 | All asset and transform context required |
| Rack row/group fields | Placement metadata or extension | Copy source identity hints | No geometry authority |
| `materialHandlingAssets[*]` | `placements[*]` conditionally | Same as racks | Vehicle identity does not create a vehicle profile |
| `layoutMap.floorZones[*]` | `zones[*]` conditionally | Normalize type and polygon; use shell floor elevation | Must be inferred/demo-only until authored |
| Top-level `aisles[*]` | Legacy extension | No direct projection | Centerline spacing is not clear width |
| `layoutMap.aisleCorridors[*]` | Optional inferred aisle zone, never a committed route | Copy polygon only under explicit inferred evidence | No hard route or clearance use |
| `layoutMap.pathGraph` | Legacy extension | No direct projection | Recompute v1 route geometry from typed endpoints |
| `rackBayRows` and configuration legend | Legacy extension or asset-match hints | Copy exactly | Cannot create asset capabilities or dimensions |
| `semanticIndex` and `queryAliases` | Legacy extension; rebuild runtime indexes | Copy source, recompute canonical indexes | Not canonical identity |
| `globalAssumptions` | Companion unresolved findings | Copy exactly | Cannot satisfy requirements |
| `nextDataNeeded` | Companion unresolved findings | Copy exactly | Blocks affected hard verdicts |
| Unknown root/nested fields | Retained source payload | Deep copy | Never drop, rename, or flatten |
| Server migration time | `createdAt`, `updatedAt` | Server owned | Must not come from legacy timestamps |
| Camera, selection, grid, viewer root | Nowhere | Do not persist | Session/display state only |

### 7.1 Placement transform condition

A legacy occurrence position may be copied directly only when the migration
binding proves:

```text
legacy component origin == canonical asset placement origin
legacy frame == layout frame
asset scale == 1
occurrence quaternion is available and converted to XYZW
```

Otherwise the correct placement translation must be computed from the pinned
asset normalization, or the occurrence must remain unpromoted. Copying
`positionMeters` while silently changing the origin would not be lossless.

### 7.2 Route condition

Neither the legacy `pathGraph` nor a response from the current route endpoint
is a v1 persisted route:

- Endpoints are not occurrence-qualified typed connectors.
- Corridor width is not authoritative.
- No vehicle-profile revision is bound.
- Turning radius and swept volume are not validated.
- Floor Y is inferred.
- Obstacle geometry is based on rough rack envelopes.

The v1 router may use the graph only as an inferred seed and must regenerate
geometry against exact current dependencies.

## 8. Unknown-field retention

The reserved container is:

```text
extensions.inspectorproLegacySemanticV0_2
```

It contains:

```text
migrationContractVersion
mode
sourceByteLength
sourceSha256
payload
```

Requirements:

1. `payload` is deeply equal to the parsed source object.
2. Unknown fields are retained at every depth, including unknown fields inside
   otherwise recognized legacy objects.
3. The raw byte hash identifies the original representation. Canonical v1
   serialization may reorder the retained object but may not change its JSON
   values.
4. A known-field projection never deletes or overwrites its retained source.
5. Unknown v1 extension properties on extension-capable objects round-trip
   subject to the 32-field-per-object and 5 MiB total extension limits.
6. Unknown properties inside a v1 object whose schema has
   `additionalProperties: false` are invalid. They are not silently moved.
7. If a source exceeds the extension or document limits, migration fails and
   leaves the source read-only. It does not truncate the source.

The production v0.2 source is 99,910 bytes and the compact fixture is 8,965
bytes, both below the current 5 MiB extension budget.

The compact fixture intentionally includes:

- `source.legacyVendorField`
- `rackRows[0].futureRowField`
- `layoutMap.futureLayoutField`
- `futureRootField`

The expected layout retains all four inside the complete source payload.

## 9. Unsupported newer schemas

For integer `schemaVersion > 1`:

```text
mode:                       read_only
reason:                     unsupported_newer_schema
readAllowed:                true
writeAllowed:               false
migrationAllowed:           false
canonicalRewriteAllowed:    false
originalBytesMustRemainUnchanged: true
```

Reader behavior:

1. Parse only enough metadata to identify the version and display a clear
   compatibility message.
2. Preserve and serve the original bytes subject to authorization.
3. Permit read-only raw export and any projection proven safe for that version.
4. Do not feed the document into the v1 validator and label it corrupt merely
   because v1 does not know its fields.
5. Do not update timestamps, revisions, registries, or backups as a side
   effect of opening it.
6. Reject save, archive, proposal, approval, apply, and auto-migration writes
   with HTTP `409` and code
   `unsupported_schema_version_read_only`.
7. Never down-convert in place. A future explicit migration must create a new
   reviewed result while retaining the original.

The compact newer-schema fixture pins this behavior.

## 10. Fixture bundle

All fixtures are sanitized and omit the 327 MB GLB and the 99 KB production
payload.

| File | Purpose |
| --- | --- |
| `tests/fixtures/facility_layout/migration/legacy-semantic-v0.2.input.json` | Compact representative v0.2 source with unknown fields |
| `tests/fixtures/facility_layout/migration/legacy-semantic-v0.2.migration-context.json` | Explicit server, authority, asset, and compatibility inputs |
| `tests/fixtures/facility_layout/migration/legacy-semantic-v0.2.expected-layout-v1.json` | Schema-v1 layout projection with complete opaque source retention |
| `tests/fixtures/facility_layout/migration/legacy-semantic-v0.2.expected-shell-v1.json` | Draft compatibility shell with unresolved frame findings |
| `tests/fixtures/facility_layout/migration/legacy-semantic-v0.2.expected-policy-v1.json` | Empty draft policy; no invented rules |
| `tests/fixtures/facility_layout/migration/legacy-semantic-v0.2.expected-evidence-v1.json` | Inferred evidence for the demo zone boundary |
| `tests/fixtures/facility_layout/migration/newer-schema-v2.input.json` | Minimal unsupported future document |
| `tests/fixtures/facility_layout/migration/newer-schema-v2.expected-read-only.json` | Expected non-mutating compatibility decision |

Pinned fixture values:

```text
legacy input:
    bytes  = 8965
    sha256 = 80c1fc1dd72b3a8fc7d931c214f01f2846886fa260730246401d0d6d1aa82199

coordinate frame:
    sha256 = cca6e5480e44494e9e35aff98140e0297c0a0ff70bd1bddacd850bc8c34c1027

draft shell canonical revision:
    sha256 = 1dc805a3fdd5cddcf9b9014cc8f557a38f7473512a67ea3537023f4790a07ec4

draft policy canonical revision:
    sha256 = c4e505590bbca83547283766f9666f6abd6ffe8843ecfec790155383c3a2a7e1

newer-schema input:
    bytes  = 197
    sha256 = 0aea43bcdaeb13aec43378e65fcdaf5afc8d950c09a5cd2b9de37e067a9e5149
```

The expected layout deliberately promotes only:

- One rack placement whose asset binding, origin equality, and companion
  quaternion are supplied by the migration context.
- One storage zone marked `inferred`, `demoOnly`, and read-only.

The forklift, inferred aisle, aisle corridor, path graph, rack envelope, and
capacity model remain only in the retained legacy payload.

## 11. Validation record

Completed checks:

```text
Production semantic/extractor coordinate comparison:
    PASS - 29 matched, 0 missing, max delta 5.733602712887605e-7 m

Production semantic/GLB legacy resolver:
    PASS at legacy tolerance - 24 racks, max residual 0.0613 m
    NOT placement-ready at the v1 0.001 m target

Fixture JSON parsing:
    PASS - 8 of 8 JSON files

Fixture ASCII scan:
    PASS - 8 of 8 JSON files

Report ASCII scan:
    PASS

Deterministic legacy ID derivation:
    PASS - 5 of 5 IDs regenerated from the Section 6.4 identity inputs
    using compact sorted ASCII JSON with no trailing line terminator

Current P0 contract suite:
    PASS - 17 tests in tests/test_facility_layout_p0_contracts.py

Migration layout executable contract:
    PASS - required fields, IDs, revisions, limits, finite coordinates,
    quaternion normalization, and forbidden camera/editor state

Authority required fields and cross-references:
    PASS - shell, policy, evidence, layout references, and zone evidence subject

Legacy retained-payload deep equality:
    PASS - 8,965 source bytes retained as an exactly equal parsed payload
    source sha256 80c1fc1dd72b3a8fc7d931c214f01f2846886fa260730246401d0d6d1aa82199

Promoted placement position equality:
    PASS

Layout/shell coordinate-frame equality:
    PASS

Coordinate-frame fingerprint:
    PASS - cca6e5480e44494e9e35aff98140e0297c0a0ff70bd1bddacd850bc8c34c1027

Shell canonical revision binding:
    PASS - 1dc805a3fdd5cddcf9b9014cc8f557a38f7473512a67ea3537023f4790a07ec4

Policy canonical revision binding:
    PASS - c4e505590bbca83547283766f9666f6abd6ffe8843ecfec790155383c3a2a7e1

Unsupported newer-schema executable compatibility check:
    PASS - schema v2 opened read-only above maximum v1; write was denied
    with status 409; migration and canonical rewrite remained disabled;
    all 197 source bytes remained unchanged
    source sha256 0aea43bcdaeb13aec43378e65fcdaf5afc8d950c09a5cd2b9de37e067a9e5149
```

The environment has no installed Python `jsonschema`, Node Ajv, or PowerShell
`Test-Json` validator. General Draft 2020-12 schema execution was therefore not
available without adding a dependency. The concurrent P0 executable validator
accepted the migration layout, and targeted checks covered authority required
fields and cross-references. Those checks do not replace a future full Draft
2020-12 schema test for every migration fixture.

Repository note: `.gitignore` has a global `*.json` rule and the scoped
`!tests/fixtures/facility_layout/**/*.json` exception. Git reports all eight
migration JSON files as visible, untracked files. This track did not edit
`.gitignore`; all authored files remain within the requested new-file paths.

## 12. P0 acceptance and blockers

This report closes the migration and coordinate-definition portion of P0:

- The v0.2 source can be retained without structural data loss.
- Coordinate values have a measured extractor golden.
- Camera recentering is explicitly excluded from saved geometry.
- Rough geometry is explicitly prevented from becoming safety authority.
- The shell/layout equality rule is testable.
- Unsupported newer schemas have a non-mutating read-only outcome.

Implementation must still stop if:

- The v1 schema does not reserve and bound the legacy extension.
- A migration drops an unknown property.
- A migration creates an asset placement without a pinned asset revision,
  source-origin mapping, and complete quaternion.
- A draft legacy shell is treated as published authority.
- The 61.31 mm residual is accepted for placement-ready geometry.
- A loader persists the current viewer's recenter offset.
- A newer schema can reach any write path.

The production migration should remain disabled until executable tests enforce
these conditions against the final P0 schemas and repository implementation.
