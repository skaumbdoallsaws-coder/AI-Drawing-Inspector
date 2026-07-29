# Facility Layout P0 Asset Normalization Report

Date: 2026-07-28

Status: P0 private placement-readiness exit gate met by the lead integration
addendum; planning and public-readiness remain blocked

Contract: `docs/industrial-layout-platform-implementation-plan.md`, revision 2

Sections 1 through 12 preserve the asset worker's initial, intentionally
fail-closed read-only assessment. Section 13 records the subsequently approved
standalone SolidWorks extraction and supersedes only those earlier
placement-readiness conclusions. It does not weaken the planning, safety,
license, or publication blocks.

## 1. Initial result

This section records the pre-extraction result and is superseded for
placement readiness by Section 13.

Two source candidates were selected:

1. Machine: `User Library-CNC Milling machine.sldprt`
2. Workstation: `RF--WA01-W48-D36-H34-T0_375-UF-F0-P5002.sldprt`

Both are suitable intake candidates because each is a loose part backed by a
one-entry acquisition ZIP and an official 3D ContentCentral source-page URL.
Neither is a normalized asset definition yet.

The P0 contract requires verified units, canonical local frame, floor anchor,
footprint, and collision geometry before `placement_ready`. None of those
properties can be verified from filenames, filesystem metadata, provider-page
descriptions, or the existing monolithic facility artifacts. Both fixtures
therefore remain `draft` with:

- `visual_ready: false`
- `placement_ready: false`
- `planning_ready: false`
- `public_ready: false`

This spike does not satisfy the P0 exit condition that two assets have verified
local frames, floor anchors, and footprints. That condition requires a later
authorized CAD-aware intake and review.

## 2. Initial scope and method

The inspection was read-only except for the three new report/fixture files.
SolidWorks was not launched. No standalone extractor, bridge extraction,
geometry export, CAD parser, or source-file modification was run.

Evidence methods:

- Filesystem inventory by path, extension, byte length, and top-level location
- SHA-256 of primary NTFS data streams
- Read-only inspection of `Zone.Identifier` acquisition metadata
- ZIP central-directory listing without writing archive contents
- Structured JSON reads of current facility extraction and semantic data
- Review of the P0 contract and current official provider pages/terms

The primary-stream hashes do not include NTFS alternate streams. The acquisition
ZIP entry names and lengths match the selected loose files. Archive-entry
content hashing did not complete, so byte identity between each ZIP entry and
loose source file is not claimed.

## 3. Raw library inventory and root ambiguity

Inspected root:

```text
<machine-library-root>
```

Observed inventory:

| Measure | Value |
| --- | ---: |
| Top-level directories | 10 |
| Top-level loose files | 28 |
| Top-level candidates | 38 |
| Recursive files | 276 |
| Source bytes | 109,733,622 |
| `SLDASM` files | 12 |
| `SLDPRT` files | 262 |
| Text metadata files | 2 |

The two text sidecars belong to the SA6 robot and SGG guarding assets. Neither
selected candidate has a local license, attribution, README, dependency
manifest, or provenance sidecar.

### 3.1 Ambiguous assembly folders

Filename-level scanning confirms these folders have multiple possible assembly
roots:

| Folder | Assemblies | Root status without reference graph |
| --- | ---: | --- |
| `8020-Wood Storage Cart` | 3 | Ambiguous |
| `User Library-6-axis robot abb6650_320_125` | 2 | Ambiguous |
| `User Library-Fanuc_14tes2` | 5 | Ambiguous |

Folders containing one assembly provide a plausible root, not a verified root.
The contract requires an assembly-reference graph because references,
configurations, external links, and suppressed dependencies are not established
by directory shape.

The two selected files have no folder-level root ambiguity: each is a loose
top-level `SLDPRT`, and each acquisition ZIP lists one same-name part. Their
CAD-internal external-reference status remains unknown. The fixture root status
is consequently `candidate_only`, not `resolved`.

### 3.2 Workstation family

The root contains 17 loose files matching `RF--WA01-*.sldprt`. One representative
variant was selected for this spike. Tokens such as `W48`, `D36`, `H34`, and
`T0_375` are retained only as source identity. They are not treated as
dimensions, units, material properties, or configuration authority.

## 4. Candidate source sets and hashes

All hashes are lowercase SHA-256 over the primary file data stream.

| Candidate | Source object | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| CNC machine | `User Library-CNC Milling machine.sldprt` | 980,184 | `f26678cafa91cd752ca0abd3ed2b2373c18941e6240f7132a91a0326129da2f1` |
| CNC machine | `User Library-CNC Milling machine.zip` | 946,837 | `bd47f8bcadf243487b7fc46dfce6fbab27839c6ed22f4f30b47ee6788d0dbbf0` |
| Workstation | `RF--WA01-W48-D36-H34-T0_375-UF-F0-P5002.sldprt` | 265,982 | `e773742615b2d72827d623556051297335a60412e0f5fb50f7455c8992fa61d2` |
| Workstation | `RF--WA01-W48-D36-H34-T0_375-UF-F0-P5002.zip` | 260,457 | `e77a3259b576e75ec58b93dd3cadcf3bbb7f45df13a2c393f14e452c093bbdd5` |

The two file hashes are source-file fingerprints, not contract
`sourceRevision` values. A `sourceRevision` also binds configuration and
extraction inputs, which do not exist for this spike.

### 4.1 CNC machine root and dependencies

Protected source root:

```text
<machine-library-root>\User Library-CNC Milling machine.sldprt
```

Protected acquisition package:

```text
<acquisition-cache>\User Library-CNC Milling machine.zip
```

The ZIP directory lists one entry:

```text
User Library-CNC Milling machine.sldprt
```

No additional package dependency is visible. This does not prove that the part
has no external references, linked design data, configurations, or missing
resources.

### 4.2 Workstation root and dependencies

Protected source root:

```text
<machine-library-root>\RF--WA01-W48-D36-H34-T0_375-UF-F0-P5002.sldprt
```

Protected acquisition package:

```text
<acquisition-cache>\RF--WA01-W48-D36-H34-T0_375-UF-F0-P5002.zip
```

The ZIP directory lists one entry:

```text
RF--WA01-W48-D36-H34-T0_375-UF-F0-P5002.sldprt
```

No additional package dependency is visible. CAD-internal dependency
completeness remains unknown for the same reason as the machine candidate.

## 5. Provenance and licensing

The acquisition ZIP `Zone.Identifier` streams establish these exact provider
pages:

- [CNC VMC milling machine](https://www.3dcontentcentral.com/Download-Model.aspx?catalogid=171&id=212592)
- [Selected WA01 source variant](https://www.3dcontentcentral.com/secure/download-model.aspx?catalogid=12368&id=1050942)

The CNC page identifies:

- Supplier label: `User Library`
- Model name: `CNC VMC Milling machine`
- Description: `CNC Vertical Machining Center`
- Contributor: `Rafael de Souza Clark`

That is source attribution, not verification of geometry, machine identity,
dimensions, condition, capability, or manufacturer approval.

The selected WA01 URL is exact acquisition metadata. An official neighboring
WA01 entry under catalog `12368` identifies the family as Rhino Frame machine
tables. Because the selected page's detailed metadata was not independently
retrieved, that family evidence supports only the inferred `workstation`
category. It is not promoted to selected-variant vendor, model, or attribution.

The current [3D ContentCentral terms of use](https://www.3dcontentcentral.com/Terms-of-use.aspx)
were observed on 2026-07-28 and show revision date 2023-10-11. They describe
internal CAD use and restrict distribution, public posting/display, and
service-based redistribution. No separate asset-owner permission was found.

Conservative catalog gate:

- Public/common InspectorPro distribution: blocked
- `public_ready`: false
- Private normalization into InspectorPro web artifacts: legal/owner review
  required
- Attribution completeness: partial for the CNC candidate, unresolved for the
  workstation candidate

This is a product publication gate based on observed evidence, not a legal
opinion.

## 6. Existing facility-layout evidence

Inspected generated data:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `generated/training/facility-layout/Assem3_colored.glb` | 327,184,996 | `da2be02acea430027324857e58db3ddee81713dcf9b54e38d45b830671898ce2` |
| `generated/training/facility-layout/facility_layout.json` | 243,131 | `c07f8bd574ea151d1a6e2060e8716ec96db1279bf11b6e0769a03e737e0b7c0a` |
| `generated/training/facility-layout/facility_layout_attach_check.json` | 243,131 | `30dbc74ad6cb2ea721607794bae467b6c2d5a6f3fd1a5e1b9154c035a2aa2f55` |
| `generated/training/facility-layout/facility_layout_check.json` | 243,131 | `9531b1d5b699fd0a81216c03c1d0835bc69dae9837005b0d58263443663458fe` |

Related current semantic evidence:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `facility_layout_probe_with_folders.json` | 243,131 | `f04adbc374622a7210377f9c43b4ebf35e166c63950cfeb125f93197865e40df` |
| `facility_layout_semantic.json` | 99,910 | `269ed9e33c32f7937221b4cbf26c52ea61b529999c96c16f38b4cd5d02f6077d` |

The generated extraction identifies `Assem3.SLDASM` at a separate protected
source path under `Assembly Modeling`, not under the machine library. It records
271 resolved component occurrences:

| Referenced file | Occurrences |
| --- | ---: |
| `Crossmember.SLDPRT` | 192 |
| `Legs.SLDPRT` | 48 |
| `Pallet Racking.SLDASM` | 24 |
| `Forklift.SLDPRT` | 5 |
| `Assem3.SLDASM` | 1 |
| `Warehouse Layout.SLDASM` | 1 |

This proves repeated rack/forklift occurrences in the legacy assembly. It does
not establish a reusable normalized rack or forklift asset definition because:

- The GLB is a monolithic facility export, not an isolated source binding.
- No source hashes for `Pallet Racking.SLDASM`, `Forklift.SLDPRT`, or their
  original dependencies are present.
- The semantic document is based on
  `facility_layout_probe_with_folders.json`, whose hash differs from all three
  generated JSON copies.
- Rack envelopes are explicitly rough, centerline-derived estimates.
- The semantic-to-GLB check has maximum residual `0.06131 m`.

The contract's CAD-derived normalization target is `<= 0.001 m`. The legacy
residual is therefore about 61 times the placement-readiness target. Its
historical `passed` flag used a `0.5 m` demo tolerance and cannot be reused as a
P0 placement or clearance gate.

No geometry, dimension, transform, floor anchor, footprint, mobility profile,
or safety claim from the legacy facility fixture is copied into either
candidate asset definition.

## 7. Verification boundary

| Property | Without CAD extraction | Evidence status |
| --- | --- | --- |
| Source path exists | Verified | Derived |
| Source and acquisition-package byte lengths/hashes | Verified | Derived |
| ZIP package has one same-name, same-length part | Verified | Derived |
| ZIP entry and loose file are byte-identical | Not verified | Unknown |
| Provider source-page association | Verified from acquisition metadata | Derived |
| Candidate display/category | CNC display authored; categories inferred | Authored/inferred |
| Complete CAD dependency graph | Not verified | Unknown |
| Native units/handedness/up axis | Not verified | Unknown |
| Canonical local frame and `sourceToCanonical` | Not verified | Unknown |
| Local origin/facing/mounting surfaces | Not verified | Unknown |
| Floor support plane and floor anchor | Not verified | Unknown |
| AABB/OBB/height/selection bounds | Not verified | Unknown |
| Footprint and collision proxy | Not verified | Unknown |
| Mass/center of gravity/support/load model | Not verified | Unknown |
| Clearances/connectors/utilities | Not verified | Unknown |
| Capacity/operating envelope/mobility | Not verified | Unknown |
| Safety, floor-load, or code compliance | Cannot be claimed | Unknown |
| Public redistribution right | No permission evidence; provider terms restrictive | Blocked |

An empty connector, clearance, render-artifact, or dependency list in the
fixtures means "none verified in this spike", not "the asset has none."

## 8. Local-frame, anchor, and footprint readiness

| Candidate | Local frame | Floor anchor | Footprint | Placement status |
| --- | --- | --- | --- | --- |
| CNC VMC milling machine | Unknown | Unknown | Unknown | Blocked |
| WA01 workstation candidate | Unknown | Unknown | Unknown | Blocked |

There is no justified identity matrix. There is no justified zero-valued floor
anchor. There is no justified rectangle derived from filename tokens. Writing
any of those values would invent geometry and would violate the evidence and
numeric gates in sections 6 and 7 of the contract.

## 9. Fixture decisions

The two candidate fixtures use
`facility-layout-p0-asset-definition-candidate-v1`. This is a spike fixture
shape, not a replacement for the P0 frozen production schema.

Important choices:

- `assetId` is null because IDs are server-assigned.
- `sourceRevision` is null because extraction configuration/input identity is
  absent.
- `assetDefinitionRevision` is null because canonical geometry and semantics
  are incomplete.
- Raw local paths are marked `server_only`.
- Source hashes are retained separately from content revisions.
- Every geometry, loading, clearance, connector, utility, and mobility section
  is explicitly `unknown`.
- Each null or empty unresolved section is tied to an explicit reason.
- The CNC process type is inferred from the official model description.
- The workstation category is inferred; filename tokens are not decoded into
  dimensions.
- Readiness flags are false with contract-specific blockers.
- No clearance envelope or safety status is created.

## 10. Blockers and next evidence

To reach `placement_ready` for either candidate:

1. Confirm the exact source root/configuration and build the CAD reference graph.
2. Resolve all external references and hash every source dependency plus intake
   configuration.
3. Extract and review native units, handedness, up axis, geometry, and stable
   source identity.
4. Compute and verify `sourceToCanonical` against the `<= 0.001 m` target.
5. Review the canonical local origin, support plane, floor anchor, facing, and
   allowed mounting surfaces.
6. Derive and review bounds, footprint, height interval, and a separate
   collision proxy.
7. Generate nonblank web LOD and thumbnail artifacts.

To reach `planning_ready`, add reviewed engineering evidence for applicable
connectors, utilities, loading, operation, service, and clearance properties.
Missing safety evidence must remain `unverified`, never `safe`.

To reach `public_ready`, obtain and record asset-owner permission that covers
the intended transformed web artifacts, catalog distribution, and required
attribution. Current provider terms alone do not satisfy that gate.

## 11. New files

- `docs/facility-layout-p0-asset-normalization-report.md`
- `tests/fixtures/facility_layout/assets/cnc-vmc-milling-machine.asset-definition-candidate.json`
- `tests/fixtures/facility_layout/assets/wa01-w48-d36-machine-table.asset-definition-candidate.json`

## 12. Validation results

All content checks exited `0`.

JSON parse and fixture-invariant check:

| File | Parse | Required root fields | Readiness flags false |
| --- | --- | ---: | ---: |
| `cnc-vmc-milling-machine.asset-definition-candidate.json` | Pass | 11/11 | 4/4 |
| `wa01-w48-d36-machine-table.asset-definition-candidate.json` | Pass | 11/11 | 4/4 |

ASCII and whitespace check:

| File | Non-ASCII bytes | Trailing-whitespace matches | Result |
| --- | ---: | ---: | --- |
| `docs/facility-layout-p0-asset-normalization-report.md` | 0 | 0 | Pass |
| `tests/fixtures/facility_layout/assets/cnc-vmc-milling-machine.asset-definition-candidate.json` | 0 | 0 | Pass |
| `tests/fixtures/facility_layout/assets/wa01-w48-d36-machine-table.asset-definition-candidate.json` | 0 | 0 | Pass |

Source-binding consistency check:

| Fixture | Binding | Byte length | SHA-256 | Result |
| --- | --- | ---: | --- | --- |
| CNC | Requested root | 980,184 | `f26678cafa91cd752ca0abd3ed2b2373c18941e6240f7132a91a0326129da2f1` | Pass |
| CNC | Acquisition package | 946,837 | `bd47f8bcadf243487b7fc46dfce6fbab27839c6ed22f4f30b47ee6788d0dbbf0` | Pass |
| Workstation | Requested root | 265,982 | `e773742615b2d72827d623556051297335a60412e0f5fb50f7455c8992fa61d2` | Pass |
| Workstation | Acquisition package | 260,457 | `e77a3259b576e75ec58b93dd3cadcf3bbb7f45df13a2c393f14e452c093bbdd5` | Pass |

Spatial-authority guard:

- CNC: Pass; coordinate-frame, geometry, and collision values are null;
  clearance and connector counts are zero.
- Workstation: Pass; coordinate-frame, geometry, and collision values are
  null; clearance and connector counts are zero.

Path-scope/status check:

```text
?? docs/facility-layout-p0-asset-normalization-report.md
!! tests/fixtures/facility_layout/assets/cnc-vmc-milling-machine.asset-definition-candidate.json
!! tests/fixtures/facility_layout/assets/wa01-w48-d36-machine-table.asset-definition-candidate.json
```

The two JSON files are ignored by the existing `.gitignore:22` rule `*.json`.
They exist and passed all checks, but a normal `git status` hides them. This
spike did not edit `.gitignore`; adding the fixtures to version control will
require an explicit force-add or a separately authorized ignore-rule change.

## 13. Lead integration addendum

The user approved the standalone extractor path after the initial read-only
inspection. SolidWorks 2024 and
`SolidWorksExtractor/bin/Release/SolidWorksExtractor.exe` were then used
against both protected source parts. No source CAD file was modified.

Extractor identity:

| Field | Value |
| --- | --- |
| SolidWorks | `SolidWorks 2024 (v32.5.0)` |
| Extractor SHA-256 | `c2b2e58d70392f78eb61f2638547d802838fcd9a09a071668c7843f0e763a5c9` |
| Inputs | `full`, `views`, `part-glb` |
| Geometry values | SI meters |
| Geometry interface revision | `c8b9dd44c45266ba501b3116856fae43657ce31f6c7bbf8bedaa357e70a5717d` |

### 13.1 Extracted machine evidence

| Field | CNC VMC | WA01 workstation |
| --- | ---: | ---: |
| Active configuration | `Valor predeterminado` | `Default` |
| Native source units | `mm` | `in` |
| Extracted JSON bytes | 41,268 | 185,496 |
| Extracted JSON SHA-256 | `c48808f66cf9e3f2983564870ad2f825d016f1216b6f4dab09c088a4e55f091d` | `9851f4475897bd163d8091536cdd466abf260bc5ea6644e83a811d60ec9056fd` |
| Feature-colored GLB bytes | 525,844 | 350,816 |
| Feature-colored GLB SHA-256 | `7055aceb64674764bac4bdaae187229eead1aa0d877fc12a5b90cca581309a43` | `dd15e9453916b303c6bef406106bcbbded061302778c3139d1221e8c1f44e590` |
| CAD mass property | 7,078.47471 kg | 20.18477886 kg |

Raw complete-body AABBs in source meter coordinates:

```text
CNC:
    min = (-1.500000000, -0.000000050, -3.018251521)
    max = ( 1.500000000,  2.700000000,  0.700000025)

WA01:
    min = (-0.6096001031, -0.8540751031, -0.5270500000)
    max = ( 0.6096001031,  0.0095250000,  0.5270500000)
```

Front, right, top, and isometric exports were inspected for both assets. They
confirmed source `+Y` as vertical and the complete-body minimum Y as the
conservative floor-support datum for this private spike.

### 13.2 Canonical frame and footprint decision

The normalization centers the complete X/Z AABB on the canonical local origin
and translates the reviewed minimum-Y support datum to canonical `Y = 0`.
The full AABB X/Z projection becomes a counter-clockwise conservative
footprint. No service, operating, loading, or safety clearance is inferred.

| Asset | Canonical footprint extents | Height | Placement |
| --- | --- | ---: | --- |
| CNC VMC | X `[-1.5, 1.5]`, Z `[-1.859126, 1.859126]` m | 2.7 m | Ready |
| WA01 | X `[-0.6096, 0.6096]`, Z `[-0.52705, 0.52705]` m | 0.8636 m | Ready |

The normalized production-schema P0 fixtures are:

- `tests/fixtures/facility_layout/assets/cnc-vmc-milling-machine.normalized-p0.json`
- `tests/fixtures/facility_layout/assets/wa01-w48-d36-machine-table.normalized-p0.json`
- `tests/fixtures/facility_layout/assets/p0-normalization-evidence.json`

They set:

```text
visualReady:    true
placementReady: true
planningReady:  false
publicReady:    false
```

Planning remains blocked because contact loads, clearances, connectors,
utilities, operating envelopes, and installation requirements are not
authoritative. Public readiness remains blocked by attribution and
redistribution evidence. CAD mass is qualified as transport evidence only and
is not a floor contact-load model.

### 13.3 Executable verification

The P0 contract tests recompute:

- source revisions from source hashes, configurations, and extractor inputs;
- column-major source-to-canonical transforms;
- normalized AABBs and center-of-mass coordinates;
- counter-clockwise, non-self-intersecting footprint polygons;
- evidence references and independent readiness states.

The original candidate fixtures remain intentionally fail-closed. They prove
that filesystem/provider metadata alone cannot establish placement geometry.
The normalized fixtures prove that approved CAD extraction plus visual review
can close only the placement gate without manufacturing safety overclaiming.
