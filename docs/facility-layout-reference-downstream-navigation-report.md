# Reference Downstream Operator Cycles

Date: 2026-09-04

## Scope

This implementation adds reviewed Packaging and Quality Inspection work-cycle intent to the read-only Sage prototype activity preset for the reference layout's Inspection, Packaging, and Finished Goods area.

Exact Quality Inspection prompt:

> Play the prototype Quality Inspection activity. Each existing Inspection operator picks from the left input table, loads and inspects the part at the current laboratory workstation, records and unloads the result, places the inspected part in the right container, then returns empty to the input table and repeats. Reuse existing operators and equipment; do not duplicate placements and do not save.

Reference layout:

- Layout ID: `fl-reference-manual-20260812`
- Frozen revision: `a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088`
- URL: `http://127.0.0.1:8165/?facilityLayoutId=fl-reference-manual-20260812&build=20260904-inspection-cycle`

## Implementation

- Reuses the eight existing operator placement IDs and their exact catalog visuals. It does not add moving operator placements.
- Persists no navigation coordinates and creates no replacement operators, stations, containers, or routes.
- Compiles cell-scoped navigation snapshots through the supported effective facility boundary derived by `shell_with_plan_boundary` from the layout's `extensions.facilityPlan`.
- Keeps the reviewed Packaging cycle as three deterministic legs: `carry_in`, `carry_out`, and `return_empty`.
- Identifies each Inspection station only when it has exactly one left folding worktable, one central laboratory workstation, one right drawer container, and one existing operator.
- Resolves Inspection A at the input table's southwest access corner, B at the workstation's south service side, and C at the output container's south service side. The corner choice is deterministic because the input table's cardinal-side candidates are obstructed at the exact operator footprint.
- Compiles `inspection_pick` from A to B and `inspection_place` from B to C. Both render as solid blue paths.
- Compiles `return_empty` from C around the output's northeast side and the input's northwest side back to A. It renders as a dashed green perimeter path.
- Uses the shared corrected navmesh funnel. Each one-way leg must be a simple path and remain inside compiled free space; repeated endpoint/backtracking paths fail closed.
- Holds the operator position for one second at each segment boundary and continuously loops the three packages. The heading may turn in place toward the next leg during a hold.
- Records the user-described B actions as `load`, `inspect`, `record`, and `unload` process evidence. Playback does not fabricate a workpiece, inspection result, or measured process duration.
- Keeps the source layout read-only; playback state, snapshots, journeys, and candidate programs are transient.

The earlier 40 m by 30 m shell blocker does not apply on the supported service path. The effective prototype boundary is derived from the existing facility plan without modifying the saved shell or reference layout.

## Browser Evidence

The live Sage acceptance run produced:

- 8 displayed operator cycles: 4 Packaging and 4 Quality Inspection.
- 8 unique existing operator placement IDs; 0 duplicate visible source placements.
- 24 accepted path segments: 4 carry-in, 4 carry-out, 4 Inspection pick-to-inspect, 4 Inspection inspect-to-place, and 8 empty returns.
- 0 unavailable actors and 0 partial programs.
- All 8 actors moved and faced their current direction of travel.
- All actors used exact catalog visuals; each stationary source rendering was suppressed while its borrowed visual moved.
- Inspection Station Q01 remained at one fixed X/Z position at B over two sampled times in the process hold, then entered B-to-C and return phases in order.
- One complete cycle returned Q01 to the first package without teleporting.
- Path visibility toggled `24 -> 0 -> 24` through the playback control.
- The Movement Playback panel stayed docked outside the layout viewport.
- 0 page errors, console errors, failed requests, or HTTP 5xx responses.
- Reference hash unchanged before and after playback.

Evidence:

- `.runtime/inspection-cycle/report.json`
- `.runtime/inspection-cycle/01-sage-inspection-plan-and-chat.png`
- `.runtime/inspection-cycle/02-inspection-cycles-plan-closeup.png`
- `.runtime/inspection-cycle/03-inspection-cycles-3d-top.png`
- `.runtime/inspection-cycle/04-inspection-existing-operator-focus.png`

## Verification

- Navigation, intent, itinerary, and navmesh Python tests: 58 passed; 1 unrelated NAV5 fixture deselected.
- Sage deterministic dispatch tests: 3 passed.
- JavaScript Three.js adapter: 68/68 passed.
- JavaScript Plan editor: 37/37 passed.
- JavaScript Facility workspace: 75/75 passed.

The excluded broader-suite case is the pre-existing `test_nav5_uses_marked_directed_lane_and_passes_exact_vehicle_sweep` fixture. Its authored lane rotation conflicts with the frozen lane-direction convention used by the motion-lane tests. This operator-cycle change does not weaken lane-direction enforcement.

## Claim Boundary

This proves deterministic, obstacle-free candidate path geometry and read-only playback for existing operator identities against the exact reference revision. The user described the process order; the generated path remains pending-review prototype evidence. It does not establish ergonomics, staffing, inspection efficacy, process time, throughput, traffic interaction, safety, regulatory compliance, operational optimality, or production readiness.
