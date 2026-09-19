# Facility Layout G2 Circulation Implementation Report

Date: 2026-08-27

Status: Complete in explicit prototype mode

## Scope

G2 is the first executable Sage circulation proof for Facility Layout. It
extends an active unsaved G1/G1.1 department draft with revision-bound aisle
routes. Sage resolves semantic intent; the deterministic Facility kernel owns
route coordinates, operation application, validation, receipts, and Undo.

The enabled request contract supports:

- material, forklift, and pedestrian routes;
- an exact user-authored width in `m`, `mm`, `ft`, or `in`;
- a named source and target department;
- an ordered list of named intermediate departments;
- one-way or two-way direction, with two-way disclosed as the default when the
  user omits direction;
- additional routes in the same generated draft; and
- follow-up width edits to the most recent generated route while preserving
  route identity, endpoints, and department bindings.

Every generated route currently uses explicit overlay area accounting. It does
not deduct aisle area from departments or imply a regulatory clearance.

## Authority Boundary

Sage cannot author route points or world coordinates. Chat coordinates are
rejected and the user is directed back to semantic relationships. Code,
egress, fire, accessibility, and safety widths require an authored policy or an
explicit user-provided width; no value is inferred from model knowledge.

Incomplete requests fail closed:

- missing width asks for a width and unit;
- missing endpoints asks for source, target, and optional through-departments;
- missing traffic class asks for material, forklift, or pedestrian intent;
- a follow-up with no recent generated aisle asks for a new route definition;
  and
- hypothetical or negated requests remain read-only and do not create a draft.

## Active Draft Binding

Facility agent context, read tools, route generation, and follow-up resolution
now use the exact owned active generation draft shown in the viewport. The
saved base revision is still checked first, then the active run pointer, owner,
layout, base revision, and draft revision are verified before the draft is
exposed to Sage.

This closes the context-identity failure recorded in
`facility-layout-circulation-intent-baseline.md`: Sage no longer answers route
questions from the saved reference factory while a different unsaved facility
is visible.

## Live Browser Proof

The production Playwright verifier sent six turns through the visible Sage
composer and the production SSE endpoint:

1. create a 120 x 90 m, four-department facility;
2. add a 6 m material aisle from Receiving to Shipping through Machining and
   Assembly;
3. resize that same aisle to 5 m;
4. ask which departments remain disconnected;
5. issue the ambiguous request `Add some aisles.`; and
6. request whatever fire aisles code requires.

All 15 checks passed. The route was added to the same run, rendered in the Plan
viewport, retained one route ID across the width edit, and did not revise the
draft during read-only or refused turns. The saved layout remained unchanged,
and one Undo restored the exact saved base.

Evidence:

- machine-readable result:
  `tests/fixtures/facility_layout/knowledge_foundation/g2-circulation-browser-evidence.json`
- department draft:
  `tests/fixtures/facility_layout/knowledge_foundation/g2-circulation-browser/01-departments.png`
- 6 m route:
  `tests/fixtures/facility_layout/knowledge_foundation/g2-circulation-browser/02-material-route-6m.png`
- 5 m follow-up:
  `tests/fixtures/facility_layout/knowledge_foundation/g2-circulation-browser/03-material-route-5m.png`
- clarification and policy refusal:
  `tests/fixtures/facility_layout/knowledge_foundation/g2-circulation-browser/04-circulation-guardrails.png`

### Exact Pre-Geometry Evaluation Replay

The original eight-question Playwright baseline was replayed verbatim against
the completed G2 path. It covered complete generation, a same-route follow-up,
ambiguity, unsupported fire-code policy, active-draft connectivity,
model-authored coordinates, hypothetical analysis, and a negated request.

All eight cases passed their explicit build, ask, refuse, or read-only grade.
All nine SSE streams, including setup, returned HTTP 200. The six non-build
turns left the draft revision unchanged, the saved layout remained unchanged,
and one Undo restored the exact saved base. There were no console errors, page
errors, failed responses, or interruption messages.

Evidence:

- machine-readable case-by-case result:
  `tests/fixtures/facility_layout/knowledge_foundation/g2-circulation-baseline-replay.json`
- screenshots for setup and all eight prompts:
  `tests/fixtures/facility_layout/knowledge_foundation/g2-circulation-baseline-replay/`

### Single-Thread Zone-To-Circulation Proof

A separate Playwright scenario kept one visible Sage conversation open for the
entire composition:

1. create a 120 x 90 m facility with eight equal-area departments in four
   authored rows;
2. add a 6 m two-way material aisle from Receiving to Shipping through
   Machining and Assembly; and
3. add a separate 3 m pedestrian walkway from Stores to Inspection through
   Automation.

All 13 checks passed. The same chat title and transcript contained all three
requests, the same generation run owned every stage, the first route remained
byte-equivalent after the second was added, and both routes resolved the exact
requested department bindings. All three streams returned HTTP 200 with no
browser errors. The saved layout remained unchanged and one Undo restored the
exact saved base.

Evidence:

- machine-readable result:
  `tests/fixtures/facility_layout/knowledge_foundation/g2-zone-to-two-aisles-thread.json`
- zone-only screenshot:
  `tests/fixtures/facility_layout/knowledge_foundation/g2-zone-to-two-aisles-thread/01-partitioned-zones.png`
- first material aisle:
  `tests/fixtures/facility_layout/knowledge_foundation/g2-zone-to-two-aisles-thread/02-material-aisle.png`
- final two-aisle state and chat:
  `tests/fixtures/facility_layout/knowledge_foundation/g2-zone-to-two-aisles-thread/03-two-aisles-one-thread.png`

### Blank-Default And Dirty-Editor Replacement Proof

The default `fl-main` layout now opens as a blank Facility workspace. The
previous manually assembled reference factory remains available separately as
`fl-reference-manual-20260812`; its source revision and all 45 zones, 8 routes,
827 placements, and 50 floor markings are preserved.

A production Playwright scenario first loaded the blank default, then created
an unsaved manual zone to reproduce the prior editor-state failure. It issued
the reported 150 x 100 m prompt verbatim, followed by a 5 m one-way forklift
lane and a 2.5 m two-way pedestrian walkway in the same conversation.

All 15 checks passed. The generation explicitly replaced the unsaved manual
zone, produced the six exact labels in three authored rows, retained one
generation run for both circulation amendments, left the saved blank base
unchanged, and restored that base with one Undo. All three SSE responses were
HTTP 200. There were no interruption messages, console errors, page errors, or
failed browser responses.

Evidence:

- machine-readable browser result:
  `tests/fixtures/facility_layout/knowledge_foundation/blank-default-replacement-evidence.json`
- blank default:
  `tests/fixtures/facility_layout/knowledge_foundation/blank-default-replacement/00-blank-default.png`
- deliberately dirty manual editor:
  `tests/fixtures/facility_layout/knowledge_foundation/blank-default-replacement/01-unsaved-manual-zone.png`
- exact six-department partition:
  `tests/fixtures/facility_layout/knowledge_foundation/blank-default-replacement/02-six-department-partition.png`
- final two-route state and chat:
  `tests/fixtures/facility_layout/knowledge_foundation/blank-default-replacement/03-two-aisles.png`
- archive and reset receipt:
  `tests/fixtures/facility_layout/knowledge_foundation/default-layout-reset-receipt.json`

## Deterministic Verification

The focused circulation, coordinator, agent-runtime, host, and Sage integration
suites report `189 passed`.

They cover:

- coordinate-free intent parsing and canonicalization;
- diverse phrasing including polite requests, `between`, `with`, `via`,
  written widths, imperial widths, and overlapping department names;
- deterministic orthogonal centerline generation;
- exact width conversion and corridor containment;
- route-to-department bindings and disconnected-department reads;
- same-run amendment and immutable superseded receipts;
- absolute, direction-only, traffic-class, and relative-width follow-ups;
- active-draft context ownership and revision checks;
- HTTP amendment without persistence;
- explicit Save of the final cumulative diff;
- exact Undo;
- clarification, policy refusal, coordinate refusal, hypothetical, and
  negated cases; and
- JavaScript transport syntax.

## Current Boundary

G2 does not yet claim:

- optimal route choice or shortest-path planning;
- crossing design or conflict separation;
- route capacity, travel time, throughput, or percentage benefit;
- code compliance or safety-clearance adequacy;
- aisle area deducted from department allocation;
- obstacle, equipment-footprint, door, dock, or turning-radius avoidance;
- service, emergency, evacuation, or utility-route policy; or
- circulation generation on an arbitrary saved layout without an active
  generated department run.

Those capabilities remain separately gated in
`facility-layout-intelligence-backlog.md`.
