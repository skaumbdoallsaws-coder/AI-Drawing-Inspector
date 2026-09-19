# Facility Layout G6: Reusable Cell Modules

Date: 2026-08-28

Status: Qualified for explicit prototype use

## Scope

G6 turns one qualified G5 manufacturing cell into a reusable, revision-bound
module. Sage accepts semantic source and target names. InspectorPro owns every
copied identity and transform, validates the complete draft, and leaves the
result unsaved until the user explicitly selects Save.

The qualified path supports:

- one uniquely named G5 source cell;
- one through twenty uniquely named empty target areas;
- exact asset-definition revision preservation;
- exact relative placement geometry and orientation preservation;
- remapping of internal placement relationships to the new placement IDs;
- new stable placement and cell-module identities per target;
- byte preservation of the source cell, department boundaries, routes,
  markings, unrelated placements, and prior manual or locked work;
- deterministic containment, collision, route-obstruction, and static spatial
  validation;
- read-only source and replica conformance reporting;
- explicit authority to copy a manually edited current source state;
- durable `repeated_modules` stage receipts in the existing generation run;
- one cumulative Save boundary; and
- one Undo that restores the exact saved base.

## Ownership Boundary

```text
user names a qualified source and empty targets
  -> Sage resolves semantic cell intent
  -> InspectorPro loads exact source members and asset revisions
  -> deterministic compiler translates relative geometry by zone centroids
  -> new identities and internal relationship mappings are generated
  -> deterministic validators prove the resulting draft
  -> user reviews one unsaved cumulative diff
  -> Save still requires explicit approval
```

Chat-authored coordinates, translations, angles, offsets, scale factors, and
polygon geometry are rejected. The model cannot approve, save, or supply
geometry.

## Provenance And Drift

G5 now records authored geometry snapshots for every source-cell member,
including members whose position did not change during composition. G6 binds
each replica to:

- the source cell ID;
- source member IDs;
- the source module revision;
- exact asset-definition revisions;
- the replication request ID;
- a stable module ID and instance index;
- a source-to-copy placement ID map; and
- either `authored_g5_snapshot` or `explicit_current_edited_state` authority.

Conformance analysis compares current geometry against those snapshots. It
reports modified, missing, extra, or stale members without overwriting the
source or replicas.

## Fail-Closed Cases

G6 does not create a draft when:

- no qualified G5 source resolves;
- a target is missing, ambiguous, duplicated, or occupied;
- a target already owns a cell or module;
- the source has diverged and current-state copying was not explicit;
- a source relationship depends on a placement outside the source cell;
- an exact asset revision is unavailable;
- unchanged translated geometry does not fit;
- a static spatial or route conflict is introduced;
- the request exceeds twenty targets or 480 copied placements;
- model-authored geometry is supplied; or
- the user asks for unsupported safety, compliance, ergonomic, throughput,
  capacity, or operational-optimality conclusions.

## Verification

Automated results:

- Facility-focused Python integration: `236 passed`.
- Shared operations, routing, and spatial kernel: `125 passed, 1 skipped`.
  The skip is the existing opt-in wall-clock benchmark.
- Browser transport: `6/6 passed`.
- Facility workspace: `70/70 passed`.
- Facility session: `48/48 passed`.
- Python compile checks passed for the changed runtime modules and `server.py`.

The continuous production-browser proof used one visible Sage conversation and
one durable generation run across G1 through G6. In fifteen turns it created a
120 m by 90 m facility, two routes, three Cell Hall child areas, populated every
operating leaf area, qualified a three-workbench source cell, and created two
exact replicas with six new placement IDs. All twenty evidence assertions
passed in 51.753 seconds. Fifteen of fifteen chat streams returned HTTP 200;
there were no console errors, page errors, failed responses, or interrupted
answers.

The saved layout remained the blank revision
`54cee1725b4a2103b00f4b2f98ca66a8e31245383a9291be953968bd10f85a4c`.
One Undo restored that exact blank base.

Evidence:

- `tests/fixtures/facility_layout/knowledge_foundation/g1-to-g6-continuous-browser-evidence.json`
- `tests/fixtures/facility_layout/knowledge_foundation/g1-to-g6-continuous-browser/06-g6-replicated-cells.png`
- `tests/fixtures/facility_layout/knowledge_foundation/g1-to-g6-continuous-browser/07-g6-conformance.png`
- `tests/fixtures/facility_layout/knowledge_foundation/g1-to-g6-continuous-browser/08-g6-authority-refusal.png`
- `tests/fixtures/facility_layout/knowledge_foundation/g1-to-g6-continuous-browser/09-g6-coordinate-refusal.png`
- `tests/fixtures/facility_layout/knowledge_foundation/g1-to-g6-continuous-browser/10-one-undo-blank.png`

## Deliberate Limits

G6 performs exact translation into geometrically compatible empty targets. It
does not rotate, scale, mirror, reflow, substitute, or partially copy a module.
It does not infer regulatory clearance, utility capacity, process equivalence,
throughput, staffing, ergonomics, or safety. A later manual edit is reported as
drift; G6 does not automatically synchronize the family.

Those extensions require separate semantic contracts and deterministic
validation. They are not implied by this qualification.
