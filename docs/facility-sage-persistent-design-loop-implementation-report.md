# Facility Sage Persistent Design Loop Implementation Report

Date: 2026-09-07

Status: **ALL TECHNICAL PROMOTION GATES PASS; PRODUCT-OWNER SIGN-OFF PENDING**

This report supersedes the earlier FDL0-FDL9 completion claim. The persistent
design-loop foundation is implemented, and the latest authority, acceptance,
and latency findings have been addressed. The unchanged 20-run rendered-chat
benchmark now passes all five product gates. Formal promotion remains pending
the named product owner's evidence review; no production feature flag is
enabled by this report.

The first objective remains deliberately narrow:
`reduce_loaded_material_travel_v1`. Nothing in this implementation grants
safety, compliance, capacity, throughput, staffing, scheduling, production,
or global-optimality authority.

## Review Findings

| Finding | Status | Implemented resolution |
| --- | --- | --- |
| Disconnected routes could be scored as improvements | Closed | Every baseline and candidate route is now checked against its exact transfer endpoints for connected route order, allowed direction, and static-obstacle intersection. Distance is measured only from the validated path. Invalid geometry fails closed before metrics or improvement verdicts are produced. |
| Production depended on predefined fixture recipes and coordinates | Closed | Production source resolution now reads the current layout, exact brief referents, process bindings, and asset catalog. Coordinate-free candidate recipes are compiled by deterministic fit and visibility-graph engines. `server.py` no longer installs the reviewed fixture source, recipe, or operation providers. |
| Lost Undo acknowledgment discarded the recovery handle | Closed | Undo preparation and acknowledgment are idempotent. The browser keeps a pending recovery record, disables Save, retries after response loss, and resumes recovery after reload. An already-completed server Undo returns `already_undone` so the browser can reconcile without undoing an earlier manual edit. |
| Reported latency bypassed Sage interpretation | Closed | The old direct semantic-intent benchmark is not accepted as end-to-end evidence. The replacement completed one discarded warmup and 20 measured runs through rendered Sage chat. Exact, complete requests use the same deterministic semantic resolver as production Sage; ambiguous or incomplete requests retain provider fallback. The artifact records both tool sources, and all five latency gates pass. |
| Acceptance did not prove generalization or consequential correction | Closed | Four positive held-out layouts are generated without candidate coordinates or fixture recipes, including obstacle and >500-placement cases. A sealed negative case fails from real geometry. The live six-turn conversation changes the feasible set at each consequential lock and successfully exercises Apply plus exact Undo. |
| Invalid or incompatible connectors could fall back to route-authored geometry | Closed | Catalog envelopes are normalized from `definition`, `document`, or `assetDefinition` without synthesizing identity or revision. Endpoint resolution now rejects missing, stale, or direction-incompatible connectors. Placement origins and route centerlines are never accepted as independent endpoint authority. |
| Missing or stale Process Maps could be replaced by an inferred graph carrying the requested revision | Closed | Source compilation now requires the exact authoritative product, map ID, and revision. Missing, identity-mismatched, revision-mismatched, or invalid maps return named findings. No inferred graph can impersonate an authoritative Process Map. |
| The recorded conversation did not match the accepted preference-and-correction contract | Closed | The acceptance fixture was amended to a three-segment connected path so strict endpoint validation and both post-lock buffer alternatives are simultaneously possible. A new uninterrupted six-turn trace preserves proposal IDs, revisions, diffs, metrics, transaction state, and exact Undo state. |
| Turn 3 could not prove that preference order changes selection | Closed | A separate uninterrupted trace starts from the two Turn 1 alternatives, changes the primary preference to fewer equipment moves, and then reverses it. Selection changes from 45.476056 m/one move to 50.453903 m/zero moves and back to the original one-move result revision. |
| Initial requests could silently lose unsupported qualifiers or targets | Closed | The deterministic resolver now requires complete clause coverage. Exclusive choices, unsupported movement bounds, unknown lock targets, unresolved negation, and unconsumed change directives use provider fallback or clarification instead of compiling a partial brief. |
| Corrections could merge mixed lock/move instructions or reverse contrastive preferences | Closed | Correction clauses are validated independently against exact referents. Mixed lock and move-permission language cannot broaden a lock, and `rather than X, prefer Y` makes Y the primary metric. Any unresolved correction uses provider fallback without partially updating the brief. |

## Route Validity Contract

`design_routing.py` is now the metric admission gate. For every route set it:

1. resolves the source and target endpoint geometry from the current candidate;
2. orders route segments into one continuous chain;
3. rejects gaps, disconnected fragments, and invalid directional traversal;
4. checks the exact route corridor against static candidate obstacles; and
5. returns distance only after the path reaches the target endpoint.

The source and target placements are excluded only as endpoint obstacles; all
other current candidate geometry remains active. Missing source geometry or
ambiguous endpoint binding fails closed. A disconnected 1 m replacement can no
longer produce a shorter-distance improvement verdict.

The archived manual reference now terminates honestly with:

`facility_design_route_path_disconnected`

It produces no baseline metric, candidate result, or proposal. The previous
`facility_design_no_improved_alternative` result was invalid because it summed
segments without first proving a connected transfer path.

## Generic Candidate Compilation

The production path no longer reads reviewed candidate coordinates. The
runtime pipeline is:

1. resolve the current revision-bound Facility layout;
2. ground exact source, target, movable-placement, mutable-route, and lock IDs;
3. compile the objective-scoped manufacturing source bundle;
4. derive coordinate-free source-fit, destination-fit, route-only, and
   combined-fit recipes when the brief permits them;
5. use the existing deterministic fit and visibility-graph engines to produce
   operations; and
6. validate and score each isolated candidate from the same immutable base.

Fixture providers remain available only to explicit tests. Production Sage and
Lab Mode call the same deterministic runtime after semantic grounding.

The runnable acceptance layout is:

`fl-fdl-generic-material-travel-v6`

Its saved revision is:

`e685d547bc201c266170f1315ebc2229340ef416ed513fff740dc6630c23617b`

The provisioner creates this layout only when absent and never overwrites it.

## Manual Reference Readiness

The archived manual factory is intact and independently loadable in the browser:

`fl-reference-manual-20260812`

The verified editor state contains 45 zones, 827 placements, 8 routes, and 50
floor markings. The Asset Library contains and renders all 148 current catalog
entries. The `facilityAssets=1` query option opens the library after the
Facility workspace mounts; closing it reveals the loaded factory without
changing the layout.

Opening the reference is not evidence that it is eligible for the first FDL
objective. The immutable archive has zero Process Map bindings. A separate
review copy contains three bindings, but the current catalog has no authored,
revision-bound service connectors and its reviewed transfer route does not
connect the exact machine service endpoints. The strict authority gates
therefore refuse optimization instead of substituting placement origins,
labels, proximity, or route centerlines.

The remaining reference-specific input is a reviewed objective package on a
copy: exact Process Map bindings and transfer frequency, compatible asset
service connectors, and a connected route chain. Those records must be authored
or approved explicitly; this implementation does not infer them from the
factory drawing.

Browser evidence is retained in:

- `.runtime/fdl-manual-access/manual-layout-with-asset-library.png`
- `.runtime/fdl-manual-access/report.json`

## Held-Out Controls

The held-out suite supplies no candidate recipes or candidate coordinates.

| Case | Distinct coverage | Required result |
| --- | --- | --- |
| `direct-transfer` | Straight topology and unseen labels | Feasible improved proposal, exact Apply, exact Undo |
| `obstacle-detour` | Visibility-graph detour around an exclusion | Feasible improved proposal with no obstacle intersection |
| `dense-spine` | Spine topology with more than 500 placements | Feasible improved proposal at full density |
| `loop-multiple-buffers` | Loop topology and multiple movable buffers | Feasible improved proposal |
| `sealed-transfer` | Source and target separated by actual blocked geometry | Named geometric refusal and no proposal |

All four positive controls are required to produce feasible improved proposals;
"feasible or blocked" is not an accepted positive result. Production Sage and
Lab Mode produce byte-identical deterministic artifacts for equal semantic
input.

## Undo Recovery

Proposal Undo now keeps two distinct facts until reconciliation:

- the original editor frame to restore; and
- the server transaction that must acknowledge that restoration.

After the browser restores the local frame, it persists the pending
acknowledgment instead of clearing `designProposalDraft`. Save and new proposal
application remain unavailable. Retrying Undo repeats the design acknowledgment
rather than consuming a prior manual-history entry. Reload resumes the same
recovery before mounting the workspace.

If the server completed acknowledgment but the response was lost, a repeated
prepare call returns `already_undone`. If another writer owns the Facility lease,
local history recovery does not release or alter that writer's lease.

## Live Six-Turn Proof

A successful continuous browser run used natural-language Sage turns against
the generic v6 layout:

| Turn | Request effect | Verified state |
| ---: | --- | --- |
| 1 | Optimize loaded travel; fix CNC Mill 03 and Inspection Station 02; permit both buffers and all three routes | Two proposals: Output Buffer A move at 45.476056 m and Main Boulevard reflow at 50.453903 m; saved layout unchanged |
| 2 | Lock Main Boulevard | Two one-move proposals remain: Output Buffer A at 45.476056 m and Input Buffer B at 62.698155 m; the boulevard proposal is removed |
| 3 | Prefer fewer equipment moves over shortest route | Both candidates move one placement, so measured route distance selects the Output Buffer A proposal; prior locks remain active |
| 4 | Lock Output Buffer A and rebuild without applying | Exactly one corrected proposal remains; it moves Input Buffer B, reroutes only Input Approach Aisle, and measures 62.698155 m |
| 5 | Apply that exact proposal without saving | One unsaved editor transaction; dirty local draft; saved bytes unchanged |
| 6 | Undo that proposal | Original revision, clean state, history cursor zero, and no active transaction |

The full run recorded zero page errors, console errors, failed requests, and
HTTP 5xx responses. The saved layout revision before and after was the same v6
revision listed above.

Visual proof remains in:

- `.runtime/fdl-sage-proof-agreed-six-turn-v6/04-turn-4.png`
- `.runtime/fdl-sage-proof-agreed-six-turn-v6/05-turn-5.png`
- `.runtime/fdl-sage-proof-agreed-six-turn-v6/06-turn-6.png`
- `.runtime/fdl-sage-proof-agreed-six-turn-v6/agreed-six-turn-result.json`

Partial smoke runs write separate `partial-N-turn-result.json` files and cannot
overwrite the complete six-turn trace.

## Preference-Order Proof

The six-turn trace proves correction, exact Apply, and exact Undo. Because its
Turn 3 alternatives both move one placement, a separate three-turn browser run
proves that preference order itself changes selection:

| Turn | Primary preference | Selected result |
| ---: | --- | --- |
| 1 | Shortest loaded route | 45.476056 m; one move; Output Buffer A |
| 2 | Fewer equipment moves | 50.453903 m; zero moves; Main Boulevard |
| 3 | Shortest loaded route | 45.476056 m; one move; Output Buffer A |

All three turns retain two evaluated alternatives and the same two hard locks.
Turns 1 and 3 resolve to the same result-layout revision; Turn 2 resolves to the
distinct zero-move revision. Saved layout bytes remain unchanged, and the run
recorded no page, console, failed-request, or HTTP 5xx errors.

Evidence is retained in:

- `.runtime/fdl-sage-proof-preference-switch-v6-r9/01-turn-1.png`
- `.runtime/fdl-sage-proof-preference-switch-v6-r9/02-turn-2.png`
- `.runtime/fdl-sage-proof-preference-switch-v6-r9/03-turn-3.png`
- `.runtime/fdl-sage-proof-preference-switch-v6-r9/preference-switch-result.json`

## Latency Evidence

`tools/benchmark_facility_design_loop.py` now measures the actual user path:

- natural-language submission through `#agentInput`;
- Sage semantic interpretation through the production chat endpoint;
- time to visible exact targets;
- time to the first rendered, selectable proposal;
- a natural-language correction; and
- time to the updated rendered proposal.

The protocol requires one discarded warmup and 20 measured runs on the named
Dell 15 DC15250, using nearest-rank p95 at 1920 x 1080 and device scale factor
1. Direct calls to `createDesignBrief` do not satisfy this gate.

The exact benchmark request is complete and unambiguous against the loaded
layout, so production Sage now resolves it before a provider round trip. This is
not a direct runtime or fixture call: every sample enters through rendered chat,
creates a new brief through the normal tool executor, and renders the resulting
proposal. The artifact requires and records
`facility_design_deterministic_create` for the initial turn and
`facility_design_deterministic_correction` for the correction. Any incomplete
or ambiguous request still falls through to the provider path.

The run completed one discarded warmup and 20 measured samples. Every sample
used a new brief and recorded the rendered target text `Targets: Input Buffer B,
Output Buffer A` before measuring the first useful preview.

| Gate | p95 | Threshold | Result |
| --- | ---: | ---: | --- |
| Submission to visible targets | 4,360.634 ms | 10,000 ms | PASS |
| Submission to useful preview | 10,293.258 ms | 30,000 ms | PASS |
| Deterministic first preview | 6,303 ms | 15,000 ms | PASS |
| Deterministic correction preview | 6,664 ms | 10,000 ms | PASS |
| Correction to updated preview | 10,464.659 ms | 20,000 ms | PASS |

All page, console, failed-request, HTTP 5xx, and provider-error arrays are empty.
The machine-readable result is:

`.runtime/fdl-evidence/fdl-chat-performance-r9.json`

## Current Regression Evidence

Tests run after the review fixes:

| Suite | Result |
| --- | ---: |
| Design contracts, reference/generalization, intent, agent integration, host, and service | 343 passed |
| Facility editor session | 56/56 passed |
| Facility app | 6/6 passed |
| Facility workspace | 80/80 passed |
| Facility transport | 26/26 passed |
| Chat frontend, ribbon organization, and inline-script syntax | 25/25 passed |

The backend run emitted only the existing Pydantic-v1 compatibility warning on
Python 3.14. A separate exact reference/generalization probe passed six
parameterized cases. Python compilation of all changed design-loop modules and
tools succeeded.

The previously stored 1,266-test XML is corroborative pre-review evidence, not
a substitute for rerunning the changed surface. This report does not claim a
new full-suite result.

## Promotion Decision

Every automated technical promotion gate now passes. The frozen prompt,
viewport, percentile, run count, and thresholds were unchanged; all browser
error arrays are empty, and the replacement artifact is retained.

Formal promotion still requires the named product owner's evidence review, as
specified by FDL9. No production feature flag is enabled by this report.

## Runtime

The reviewed generic acceptance layout is running at:

`http://127.0.0.1:8171/?facilityLayoutId=fl-fdl-generic-material-travel-v6&build=fdl-r9-semantic-coverage`

The manually built factory with the Asset Library opened is running at:

`http://127.0.0.1:8171/?facilityLayoutId=fl-reference-manual-20260812&facilityAssets=1&build=fdl-r9-manual-assets`

Close the Asset Library with its `X` to inspect the factory. Reopen it from the
four-square Asset Library control on the left rail. The FDL prompt below is for
the generic acceptance layout; the manual archive intentionally refuses it
until the reviewed inputs listed in Manual Reference Readiness exist.

The initial prompt used by the successful run is:

> Reduce loaded material travel from Machining Output FIFO to Inspection Input
> FIFO. Keep CNC Mill 03 and Inspection Station 02 fixed. You may move Output
> Buffer A and Input Buffer B, and you may reroute Material Transfer Aisle,
> Main Boulevard, and Input Approach Aisle. Use the reviewed 24 loaded trips
> per Day Shift.
