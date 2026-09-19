# Facility Layout G1 Implementation Report

Date: 2026-08-26

Status: Complete in explicit prototype mode

## Scope

G1 is the first executable Sage proof for Facility Layout. From an empty
layout, Sage can request an exact facility envelope and labeled macro
departments. The deterministic partition planner calculates geometry; Sage
does not place rectangles by coordinates.

G1 intentionally does not create aisles, assets, workcells, repeated modules,
floor markings, utilities, or safety separations.

## Live Proof

The production tool registry generated an unsaved review draft with:

- facility size: 100 x 80 m;
- departments: Receiving and Stores, Machining, Assembly, and Inspection and
  Shipping;
- execution mode: `authorized_draft_run`;
- prototype mode: enabled;
- ordered revision-bound stage receipts: 10;
- no unrequested routes, placements, cells, modules, or markings.

The viewport showed the facility envelope first and then the department
partition. The draft remained actionable and unsaved until a separate Save.
Undo restored the exact empty base. Regeneration produced the same cumulative
diff. Explicit Save persisted that exact draft, and reload preserved its
dimensions, labels, hierarchy, and geometry.

## Browser Evidence

`g1-browser-evidence.json` records 17 of 17 passing checks with:

- real production tool dispatch through the shared tool registry;
- exact dimensions and labels;
- exact ten-stage order and ten receipts;
- untouched saved state before approval;
- deterministic second run;
- exact Undo;
- explicit Save and reload persistence;
- no console, page, response, or network errors;
- nonblank light and dark Plan and 3D captures.

The evidence set includes envelope, department, light/dark Plan, light/dark
3D, Undo, and saved-reload screenshots at 1920 x 1080. A zone-label placement
regression found during visual review was corrected so boundary labels remain
visible instead of being clamped beneath workspace metadata.

The separate live-chat verifier sends the stakeholder prompt through the
visible Sage composer and production SSE endpoint. It confirms a terminal
response, exact 100 x 80 m dimensions, all four requested labels, an unsaved
review draft, no unrequested entities, and no browser or network errors. Its
evidence is recorded in `g1-chat-browser-evidence.json` with the corresponding
`g1-chat-browser.png` screenshot.

## Deterministic Coverage

- Supported source units normalize without changing authored intent.
- Randomized partitions cover 1 through 50 departments.
- User labels remain exact.
- Bands, rows, columns, deterministic grids, and authored proportions are
  solved by the planner.
- Containment and zero-overlap validation fail closed.
- Corridors, safety policy, clearances, and expansion space are never invented.
- A greenfield generation request rejects a nonempty layout.
- Coordinate-bearing intent is rejected.

## Exit Gates

- Exact normalized dimensions and units: PASS.
- Exact department count and labels: PASS.
- Containment and zero overlap: PASS.
- Authored proportions and arrangements: PASS.
- No unrequested entities: PASS.
- Exact Undo: PASS.
- Explicit Save and identical reopen: PASS.
- Light/dark Plan and 3D browser evidence: PASS.
- One through 50 department randomized coverage: PASS.
- Call, response, context, operation, and receipt budgets: PASS.

## Next Capability Boundary

The knowledge foundation for later stages is implemented and qualified, but
the production generation tool remains deliberately limited to G1. Aisles,
nested subdivisions, assets, cells, modules, full-factory generation, and live
dependency-aware reflow require their own rollout gates before enablement.

The post-G1 capability inventory and promotion requirements are maintained in
`docs/facility-layout-intelligence-backlog.md`. Items in that document are not
current G1.1 acceptance criteria.
