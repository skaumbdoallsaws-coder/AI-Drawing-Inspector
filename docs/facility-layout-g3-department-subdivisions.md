# Facility Layout G3 Department Subdivisions

Date: 2026-08-28

Status: Implemented and production-browser accepted

Backlog capability: `FLI-022`

## Purpose

G3 extends the qualified Facility generation run from macro departments and
circulation into explicit nested work areas. Sage resolves the named parent,
child labels, proportions, and row intent. InspectorPro computes every boundary,
applies the operations to the active unsaved generation run, and proves that the
children tile their parent without moving unrelated layout entities.

## Qualified Behavior

- Divide one uniquely named rectangular department or existing child area.
- Require an explicit child count and label for every child.
- Use equal area when the user explicitly asks for it or supplies no other area
  proportions, and disclose that assumption.
- Support deterministic grids, rows, columns, and authored north-to-south row
  stacks.
- Support complete positive child-area proportions that total exactly 100%.
- Preserve the parent zone ID, label, type, and boundary byte for byte.
- Bind every child to the exact parent zone ID in revisioned knowledge metadata.
- Preserve all unrelated zones, routes, markings, placements, utilities,
  process bindings, and groups.
- Add or replace a subdivision within the same durable generation run.
- Subdivide an existing child area in program order without flattening the
  hierarchy.
- Keep the complete result as one unsaved cumulative draft until explicit Save.
- Restore the exact saved base with one Undo.

## Authority Boundary

Sage may express semantic subdivision intent only. Chat-authored coordinates are
refused. InspectorPro does not infer missing child labels, regulatory space,
aisles, access clearances, expansion reserves, equipment footprints, or process
requirements.

G3 is intentionally bounded to axis-aligned rectangular parents. Irregular
envelopes, cut-outs, adjacency solving, minimum-area constraints, and local
dependency-aware reflow remain separate future gates.

## Deterministic Contract

The closed tool contract is `generate_facility_subdivision_draft`. Its inputs
are the parent label, child count and labels, complete proportions when present,
arrangement, orientation, authored rows, parent-preservation flag, and
`authorized_draft_run` execution mode. It contains no coordinate field.

Compilation creates stable child IDs from the parent identity and child label.
Validation independently checks:

- exact expected child IDs and labels;
- exact parent binding;
- full containment;
- zero positive-area overlap;
- exact area closure against the parent;
- unchanged macro-parent and unrelated geometry; and
- unchanged non-zone collections.

Changing one parent's subdivision supersedes the prior subdivision receipt and
invalidates only that stage and its dependants. Completed upstream department and
circulation receipts remain immutable.

## Acceptance Queries

Complete build:

1. `Divide Assembly into four equal child areas named Kitting, Mechanical Build, Electrical Build, and Test.`
2. `Arrange them in two rows: Kitting and Mechanical Build in row 1; Electrical Build and Test in row 2.`
3. `Divide Mechanical Build into three equal areas named Frame Build, Lift Build, and Final Fit.`

Clarification or refusal:

1. `Divide Assembly into four areas.` Missing labels must be requested.
2. `Divide Assembly into three areas named Kitting and Test.` Count mismatch must
   be named.
3. `Divide Assembly into Kitting at x=20 and Test at x=40.` Coordinates must be
   refused.
4. `Divide Assembly 40%, 30%, and 20%.` Incomplete proportions must not be
   normalized silently.
5. `Divide Production into two areas.` An absent or duplicate parent label must
   fail closed.

## Automated Evidence

Current results:

- 190 focused subdivision, generation-coordinator, Sage-integration, and host
  tests passed;
- 390 shared Facility tests passed, with one existing opt-in performance test
  skipped;
- 6 of 6 browser transport checks passed;
- 70 of 70 Facility workspace checks passed; and
- 48 of 48 Facility session checks passed.

The focused coverage includes equal and proportional partitions, authored rows,
ambiguity, coordinate refusal, nested compilation, containment, exact coverage,
same-parent replacement, preservation of unrelated state, durable-run API
transport, direct deterministic Sage routing, Save, and exact Undo.

## Production Browser Evidence

Playwright drove two prompts through the visible Sage chat against the restarted
application at `http://127.0.0.1:8141/`:

1. Create a 120 m by 80 m four-department facility in two authored rows.
2. Divide Assembly into four equal named children in two authored rows.

The run proved:

- two successful production chat streams;
- one unchanged generation run ID;
- four exact macro labels and four exact child labels;
- four child areas of exactly 600 m2 covering the 2,400 m2 Assembly parent;
- exact parent binding, containment, and zero overlap;
- byte-identical parent and unrelated macro departments;
- an unchanged blank saved-layout revision;
- one Undo restoring the exact blank base; and
- no page, console, failed-request, or server errors.

Machine-readable evidence:

`tests/fixtures/facility_layout/knowledge_foundation/g3-subdivision-browser-evidence.json`

Screenshots:

1. `tests/fixtures/facility_layout/knowledge_foundation/g3-subdivision-browser/01-macro-departments.png`
2. `tests/fixtures/facility_layout/knowledge_foundation/g3-subdivision-browser/02-assembly-subdivided.png`

## Next Gate

Rollout stage 4 is authoritative asset search, placement, orientation, access,
and staging inside a named department or child area. It must use registered
footprints and access evidence, reject unsupported clearances, preserve the G3
hierarchy, and keep deterministic geometry ownership in InspectorPro.

## Continuous G1 Through G3 Integration Gate

Before starting G4, Playwright ran every qualified Facility capability in one
visible Sage conversation and one durable unsaved generation run. The 19-turn
thread covered:

1. a 120 m by 90 m, nine-department, three-row G1 partition;
2. two mixed-traffic routes, deterministic conflict detection, and exact 1.5 m
   G2.1 separation;
3. a material aisle crossing a protected zone and deterministic G2.2 rerouting
   with exactly 1 m user-authored clearance;
4. G2.3 direction-aware reachability, unmarked point-crossing derivation, one
   exact 4 m by 3 m crosswalk, dead-end reporting, and a fail-closed safety and
   fire-code question;
5. a four-child G3 subdivision that preserved every macro zone, route, and
   marking; and
6. a second G3 subdivision nested inside the first child hierarchy.

All 21 integration assertions passed. All 19 chat streams returned HTTP 200.
The conversation title and generation run ID remained stable, no response was
interrupted, no page/console/request error occurred, the saved blank layout was
never modified, and one Undo restored the exact blank base.

Machine-readable evidence:

`tests/fixtures/facility_layout/knowledge_foundation/g1-to-g3-continuous-browser-evidence.json`

Milestone screenshots:

1. `tests/fixtures/facility_layout/knowledge_foundation/g1-to-g3-continuous-browser/01-g1-departments.png`
2. `tests/fixtures/facility_layout/knowledge_foundation/g1-to-g3-continuous-browser/02-g21-conflict.png`
3. `tests/fixtures/facility_layout/knowledge_foundation/g1-to-g3-continuous-browser/03-g21-resolved.png`
4. `tests/fixtures/facility_layout/knowledge_foundation/g1-to-g3-continuous-browser/04-g22-obstacle.png`
5. `tests/fixtures/facility_layout/knowledge_foundation/g1-to-g3-continuous-browser/05-g22-rerouted.png`
6. `tests/fixtures/facility_layout/knowledge_foundation/g1-to-g3-continuous-browser/06-g23-crossing.png`
7. `tests/fixtures/facility_layout/knowledge_foundation/g1-to-g3-continuous-browser/07-g23-crosswalk.png`
8. `tests/fixtures/facility_layout/knowledge_foundation/g1-to-g3-continuous-browser/08-g3-subdivision.png`
9. `tests/fixtures/facility_layout/knowledge_foundation/g1-to-g3-continuous-browser/09-g3-nested-subdivision.png`
