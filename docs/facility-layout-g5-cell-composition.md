# Facility Layout G5 Manufacturing-Cell Composition

Date: 2026-08-28

Status: Implemented and browser-qualified

Backlog capability: `FLI-024`

## Purpose

G5 turns exact resources already placed by G4 into a bounded manufacturing
cell. Sage resolves the named area, candidate strategy set, geometric objective,
optional exact spacing, and explicit process order. InspectorPro owns candidate
geometry, fit analysis, ranking, positions, validation, durable receipts, and
Undo.

This is not generic factory optimization. It is a deterministic comparison and
composition gate over the current revision-bound layout.

## Qualified Scope

- Target one uniquely named macro department or G3 child area.
- Require at least two exact-revision G4 placements in that area.
- Compare any subset of the ten registered strategies: line, L, U, grid,
  parallel, serpentine, loop, spine, herringbone, and cluster.
- Rank by one explicit geometric objective: shortest travel, smallest envelope,
  minimum movement, or maximum expansion reserve.
- Apply one selected feasible strategy, or deterministically choose the highest
  ranked feasible candidate when the user asks for the best of a named set.
- Support an explicit inverted-U option.
- Preserve user-authored process order only as exact placement IDs. An absent
  order does not become an inferred manufacturing sequence.
- Keep the result in the same durable unsaved G1-G5 run.
- Recompose the active cell in a follow-up by superseding `seed_cells` and its
  downstream receipts only.

## Authority Boundary

Sage may supply semantic strategy names, one supported objective, an exact
user-authored spacing value, an inversion choice, and an exact evidence-backed
sequence. It cannot supply coordinates, transforms, rotations, route points,
machine footprints, or clearance geometry.

When no spacing is supplied, G5 uses zero additional gap and establishes
physical non-overlap only. It explicitly reports clearance evidence as
incomplete. A geometric result does not establish:

- operator or service access;
- safety or regulatory compliance;
- ergonomics;
- throughput, takt, capacity, staffing, or cycle time;
- utilities or connection feasibility;
- floor loading, anchoring, or maintenance suitability; or
- operational optimality.

Questions that ask Sage to claim those outcomes are refused deterministically.
Chat-authored coordinates are also refused.

## Deterministic Contract

The closed tool is `generate_facility_cell_draft`. It carries only:

- target area;
- candidate and optional selected strategy;
- geometric objective;
- optional exact preferred gap;
- inverted-U flag;
- optional exact process-sequence placement IDs;
- preservation flags; and
- `authorized_draft_run` execution mode.

The compiler resolves the current target members and exact catalog revisions,
builds analysis geometry from their authoritative footprints, invokes the
existing cell-alternative analyzer, selects only a feasible registered
strategy, and emits ordinary `edit_zone` plus `move_placement` operations.
The model never sees or authors those positions.

Post-validation proves:

- target membership, asset IDs, and asset-definition revisions are unchanged;
- all placement rotations are unchanged;
- target positions exactly replay the selected deterministic candidate;
- physical containment and non-overlap hold;
- every department ID and boundary is unchanged;
- all routes and floor markings are byte-identical;
- unrelated placements are byte-identical;
- user-authored spacing and sequence provenance are retained; and
- access remains validated only when exact authoritative evidence supports it.

Manual and locked resources are preserved. The current bounded gate asks for
resolution instead of moving them or silently optimizing around them.

## Acceptance Queries

Read-only comparison:

`Compare line, L, and U layouts in Mechanical Build for shortest travel with 1 m spacing.`

Build from a bounded candidate set:

`Arrange Mechanical Build using the shortest feasible of line, L, and U layouts with 1 m spacing.`

Explicit strategy follow-up:

`Convert that cell to an L-shaped layout for minimum movement with 1 m spacing.`

Missing spacing:

`Arrange Mechanical Build as a U-shaped cell for the smallest envelope.`

The result may be composed for physical non-overlap, but must state that access
and clearance remain unverified.

Required refusals:

1. `Arrange the cell at x=20 z=30.`
2. `Make this cell OSHA compliant.`
3. `Is this cell safe for operators?`
4. `What throughput will this cell achieve?`

Required clarification:

1. an area with fewer than two exact resources;
2. an ambiguous area name;
3. a candidate set with no feasible strategy;
4. a selected strategy that was not compared; and
5. a target containing manual or locked resources that would need to move.

## Qualification Evidence

- 228 focused Python tests pass across G5 composition, durable generation,
  host API, Sage routing, G4 placement, and KF4 cell intelligence.
- 125 shared operations, routing, and spatial tests pass; the one skipped test
  is the opt-in wall-clock benchmark.
- Browser contracts pass: transport 6/6, workspace 70/70, session 48/48.
- One 36-turn Playwright conversation built G1 through G5: 15 zones, four
  routes, one crossing marking, and 20 exact-revision assets.
- The G5 read-only turn compared line, L, and U without changing the draft.
  The build turn selected the registered Straight / I-line strategy for the
  smallest envelope with exactly 1 m user-authored spacing.
- A follow-up recomposed only Electrical Build as an L-shaped cell for minimum
  movement. Department boundaries, routes, markings, asset identities,
  revisions, and rotations remained unchanged.
- A safety/OSHA question was refused without mutation. No chat stream,
  browser response, page, or console error occurred.
- The entire conversation used one durable generation run, remained unsaved,
  and one Undo restored revision
  `54cee1725b4a2103b00f4b2f98ca66a8e31245383a9291be953968bd10f85a4c`
  with zero zones, routes, markings, or placements.

Machine-readable evidence:

`tests/fixtures/facility_layout/knowledge_foundation/all-qualified-populated-browser-evidence.json`

Focused screenshots:

- `all-qualified-populated-browser/15-g5-comparison.png`
- `all-qualified-populated-browser/16-g5-composed.png`
- `all-qualified-populated-browser/17-g5-converted.png`
- `all-qualified-populated-browser/18-g5-authority.png`
- `all-qualified-populated-browser/19-one-undo-blank.png`

## Next Gate

G6 is reusable manufacturing-cell modules and patterns. It must copy an
approved cell's exact member set, strategy provenance, spacing authority, and
relationships without identity drift, while preserving manual edits and
reporting divergence from the source module.
