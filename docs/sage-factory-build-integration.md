# Sage Factory Build Integration

October 1, 2026. The product objective is a genuine recorded conversation in
which Sage builds a detailed factory from a brief, then revises it. Factory 02
is the quality reference, not a template to copy or an execution script to hide
behind the chat. This extends the existing research-to-layout delivery plan.

## Baseline

The gateway is installed and the native desktop profile selects its planner.
It supplies model transport, not new layout tools or training of model weights.
Codex built Factory 02 using separate guarded authoring utilities and the kernel;
that work was not performed by Sage. At the start of this work, generation permitted a
clean empty base, eight departments, 24 resource batches and 120 placements.
Its tool schema and admission layer exclude cells, modules and markings.
Its current ownership contract does not compose arbitrary dirty drafts with
construction or navigation. Raising the count limit alone cannot close this gap.
The compiler already returns bounded stages, but `generation_admission.py`
flattens their operations into one authoritative preview with a 500-operation
limit; `generation_draft.py` flattens the plan again for editor adoption. Both
paths need the existing staged execution and recovery contract before scale
can be promoted. Do not remove the kernel's per-batch limit.

Reuse the existing FacilityPlanningPackage, FacilityProgram, staged generation,
construction adapter, candidate repository, navigation compiler, gateway and
editor recovery. Do not grant arbitrary Python/filesystem execution to Sage.

## Build Method

1. Ground the product/process, site and catalog identities. Retrieve equipment
   summaries, manuals and permitted primary sources only when needed. Record
   consequential unknowns; distinguish assumptions from approved requirements.
2. Allocate departments and material circulation. Derive resource quantities
   from requirements or supported calculations, not from a desired screenshot.
3. Design and validate one representative cell before repetition. Retain
   resource roles, access sides, staging, supports and attachment relationships.
4. Review every zone and repeated cell for function as well as fit. An operator
   facing a machine center is not proof of access to its controls. Check actual
   floor-marking occupants and keep-clear areas. Optional amenities are part of
   the brief, not mandatory decoration.
5. Derive movement from reviewed actor/station assignments through navigation
   tools. Distinguish illustrative walking from material transfer, machine
   operation, process precedence and throughput.
6. Explain actual receipts, show Plan and 3D, preserve requirements on corrections,
   and apply the selected unsaved candidate through normal authorization.
   Save remains explicit.

These are observable planning stages and validation obligations, not a request
to expose private model reasoning or reproduce a particular model's internals.

## Delivery Gates

| Gate | Work and existing owners | Required proof |
| --- | --- | --- |
| Build guidance and exact scope | `generation_build_method.py`, context projection, requirement predicates | Guidance reaches the real authorized context; no extra equipment and no routes are executable constraints; unchanged small gateway request passes |
| Cell and module composition | Package/program compilers, `generation_agent.py`, `generation_admission.py`, construction adapter | One model-selected cell, attachments and repeated copies; exact counts, relationship remapping, shared candidate ownership; reject unsupported details |
| Scale and staged continuation | Existing generation coordinator/run journal and program execution | Variable site and catalog inputs, several hundred to approximately 900 placements; bounded payloads, visible progress, resume and duplicate-free retry; no count-limit-only promotion |
| Functional review and local correction | Readiness projections, candidate inspection, deterministic geometry, existing semantic interfaces | Exact-revision operating-side evidence or explicit unknown; marking occupancy, approach clearance, attachment and affected-region checks; preserve unrelated geometry |
| Supporting areas and movement | Existing wall/attachment/navigation contracts through the shared candidate writer | Office/cafeteria/walls only when requested; no overwriting existing wall geometry; assigned actor paths validated and playable; no invented production claim |
| Recording qualification | Normal Electron chat, actual configured gateway, isolated saved stores | Full blank-to-factory conversation, unforeseen reasonable correction, Plan/3D, Apply/restart/exact Undo, explicit Save separately; no prerecorded tool responses or layout injection |

The first gate has the bounded native evidence below. The composition update
implements part of the next two gates; it does not close either full gate.
Functional review also needs revision-bound
Plan/3D observations where geometry and semantic interfaces alone cannot identify
the operating side; the current guide does not qualify a visual inspection tool.

Keep current feature, model-binding, source, lease, revision and Save checks.
Unsupported scope must be named, not silently dropped. Search-budget exhaustion
must not be relabelled as physical infeasibility.

## Initial Implementation

The initial change adds an on-demand, bounded build-method section to the
authorized generation context. It contains no Factory 02 IDs, coordinates,
catalog models or fixed inventory. It declares current support honestly.
Simple corrections do not require an extra method retrieval.

Two general deterministic predicates address the last recorded native promotion
failure: `resource_set` binds the exact allowed resource batches, and
`route_count` binds the exact route count, including zero. Exact batch quantities
and catalog assignments still require their existing separate predicates.
Both predicates reject unqualified nested cell/module content rather than
pretending to cover resources or routes expanded by future recipes.

This is the first integration gate, not full-factory chat qualification.
The subsequent gates remain pending and are not made available by prompt text.

## Verification: October 1

Evidence root: `.runtime/sage-factory-build-20261001/`.

- Complete regression run: **337 passed, 1 skipped**, in 514.08 seconds.
  Includes 32 new build-method/requirement checks plus generation admission,
  revisions, performance contracts, provider recovery and gateway regressions.
  The skipped test requires an explicit paid-run opt-in; the separate native
  run below exercised the actual paid provider. One existing Starlette/AnyIO
  deprecation warning remains. See `complete-tests.xml` and its receipt/logs.
- An initial focused run exposed an incorrect test expectation: its positive
  fixture already declared routes but demanded zero. The positive test now
  checks the fixture's actual count, with a separate zero-route refusal case.
  An earlier full-suite attempt was interrupted by the tool/child deadline;
  it is retained and is not counted as a passing run.
- Native Electron, actual installed desktop gateway profile, unchanged original
  two-workbench prompt: **passed**. Sage chose the catalog asset and produced
  two placements, one Assembly zone and zero routes. Plan and 3D captures were
  inspected; the 3D assets rendered. Unsaved Apply, owned-backend restart and
  exact Undo passed. This is one real small-build conversation, not a full
  Factory 02 conversation or broad reliability qualification.
- The retained ledger contains `resource_set = [assembly-benches]` and
  `route_count = 0`; their requirement checks passed. Correct scope was not
  inferred just from the screenshot. All 17 recorded requirements passed.
- Four actual planner calls used `astra-candidate` / `gpt-6-astra` through the
  configured gateway. All five tool calls succeeded. No web research was
  requested or performed. The small prompt did not need the optional detailed
  build-method section; its retrieval is covered by authorized-context tests,
  not by this native small-build conversation.
- Generation took **94.126 seconds**. This is not a latency pass against the
  existing small-workload target, and one run cannot establish p95. The final
  planner request used 71,940 input tokens; bounded stage/tool schema exposure
  needs profiling before scaling. Do not attribute this solely to the model.
- Electron exited successfully. Both owned backend instances confirm graceful
  termination, closed stdio/resources, and no cleanup errors. Zero application
  Save calls and zero network Save calls. All **52 saved layout JSON files**,
  including the registry, Factory 02 and the manual reference, match their
  before-run SHA-256 hashes. See `native01/launcher.json`,
  `native01/generation-check.json`, `native01/last-application-run.json`, and
  `final-audit.json`.

The next implementation must connect qualified cells/modules and staged
execution to generation admission and candidate adoption, with schema and
requirement coverage expanded together. First prove a variable, model-selected
cell and repetition against an isolated candidate; then prove several hundred
placements without flattening the operation journal. Retain existing ownership,
approval, cancellation, stale-revision and exact Undo tests throughout. Do not
claim full-factory readiness by increasing `MAX_PREVIEW_PLACEMENTS` alone.

## Composition Update: October 1

The generation adapter now admits named child-area partitions, seed-cell
recipes and exact translated module families through the existing compilers.
`generation_composition.py` defines the bounded adapter contract: up to eight
partitions/recipes/families, 64 child areas and 900 expanded placements. Copies
must target distinct empty sibling areas, and a recipe must cover every batch
in its own leaf area. Each family supports the G6 limit of 20 target areas;
the public schema and admission validator use that same constant.
Unsupported process-order, interface, attachment and
floor-communication fields remain unavailable instead of being ignored.

New requirement predicates bind the exact partition, recipe, repetition and
expanded resource counts. Seed quantities remain separate. Follow-up context
includes the retained composition collections, and semantic revisions preserve
unmodified fields. Candidate inventory is checked against admitted totals.

Cell programs use immutable staged execution and final authoritative dependency,
spatial and route checks. The 500-operation batch limit stays intact. Apply now
retains stage batches in the shared editor journal rather than flattening them.
Deferred G6 replay also respects that limit while constructing the isolated
program draft; the 900-placement boundary exposed and now tests this path.
Existing ownership, approval, revision, recovery and explicit Save rules remain.
This is not durable resume in the middle of compiler execution or permission
for arbitrary construction commands to edit an adopted candidate.

Full cell membership and process sequence provenance stays on the cell zone;
individual members retain compact, exact lineage to that zone and their source
placement. This avoids duplicating the entire membership list on every member.

The first native mixed-cell conversation exposed a real grid defect: operators
were placed at the grid centroid and could violate the requested physical gap.
The deterministic grid now gives each operator a footprint slot. A grid with
one station and an operator is supported; other strategies retain their existing
station-count restrictions. The authored gap and collision checks were not
relaxed. The frozen conversation and its failed evidence are retained under
`.runtime/sage-factory-composition-20261001/native01/`.

The live follow-up also exposed a policy/context pagination loop. A requirements
or previous-package page has no `researchPolicy` field; it is not evidence that
the policy was lost. The preflight now preserves the latest trusted policy
observation across those pages. A current overview or a failed policy operation
can still demand policy resolution, and pages alone cannot grant permission.
Nine targeted tests cover that distinction.

This update is not full Factory 02 chat qualification. Attachments, functional
operating-side review, floor markings, walls, amenities and motion still require
their generation integration and acceptance gates.

## Composition Local Verification

Final evidence: `.runtime/sage-factory-composition-20261001/`.

- **554 Python tests passed** in the final regression run (943.30 seconds),
  covering generation, evidence/research policy, correction, draft transactions,
  cells/modules, program execution, semantic geometry and the gateway. See
  `final-regression.xml` and its exit receipt. The existing Starlette/AnyIO
  deprecation warning remains; no test was skipped in this run.
- **7 additional Python tests passed** after that suite was collected: one
  real-tool nine-to-six mixed-cell correction and six staged-validation refusal
  cases. The correction preserves every unmodified package field, expanded
  operator totals, old immutable package and saved layout, and retries without
  recompiling. Missing, verdict-less or failed spatial/routing diagnostics
  cannot pass the staged admission path. JUnit identities establish **561
  distinct passing tests**, not repeated-test inflation.
- **152 JavaScript checks passed**: editor session 62, generation view 5,
  transport 30, structure tree 51 and native acceptance harness 4. The four
  harness checks were rerun after diagnostic changes. An initial invocation
  used a nonexistent tree-test filename and failed before running tests; the
  correct 51-check suite subsequently passed. Both receipts are retained.
- Real-kernel **600- and 900-placement** programs pass staged preview, durable
  retry and backend Apply/Undo transaction checks without Save. Each operation
  batch stays at or below 500. Frontend session checks separately exercise
  staged journal installation and restoration; these tests are not a native
  900-placement chat or rendered-performance qualification.
- Earlier failures remain in the evidence directory: mixed-grid refusal,
  oversized internal G6 replay, previous-package compatibility, and a regression
  invalidated by editing compiler sources while it ran. Those problems were
  corrected or rerun with frozen source bytes. The final suite is a new clean
  run; the compiler-change guard and geometric tolerances were not weakened.
- All **52 saved layout files**, including the registry, manual reference and
  Factory 02, match the initial SHA-256 hashes. No files were added or removed
  from that saved-layout set. `final-audit.json` and `source-manifest.json`
  retain the audit and 150 source/contract/test hashes. Scoped `git diff
  --check` passed. No commit or full-factory feature promotion was performed.

## Composition Native Evidence

Evidence root: `.runtime/sage-factory-composition-20261001/`. The acceptance
prompt stayed fixed: three cells, each with two model-selected catalog benches
and one operator, then a correction to one bench and one operator per cell.
No fixture asset IDs or coordinates were supplied in the prompt. All attempts
used the installed desktop gateway profile, with no model fallback.

| Run | Observed result | Remaining failure |
| --- | --- | --- |
| `native01` | Actual tool chain reached mixed-cell construction. | Deterministic grid gap refusal; generic operator-slot fix followed. |
| `native02` | Backend retained a nine-placement preview. | Desktop readiness deadline failed; parent deadline forced termination. Exact stall cause remains unconfirmed. |
| `native03` | Native chat displayed three cells and nine placements in 253.952 seconds. | Correction exhausted the bounded tool loop on policy/context pagination; fix followed. |
| `native04` | Native chat displayed three cells and nine placements in 136.394 seconds. | Correction stopped on a gateway provider failure before planning; that run did not retain its status code. |
| `native05` | Failed request left the editor unchanged. | Provider HTTP 429, `RateLimitError`, after 29.457 seconds; no further paid retries attempted. |

`native-composition-audit.json` independently checks the two displayed candidates:
three cell groups, nine unique members, complete copy mappings, exact catalog
revisions, retained orientation/scale, and translated relative geometry within
the existing tolerance. The provider chose different bench assets in the two
runs. These are actual model-selected previews, not replayed authoring scripts.

No run in this composition series completed the live correction followed by
Plan/3D, Apply, managed restart and exact Undo. The earlier two-bench native
success does not qualify that larger contract. The 136/254-second first previews
are not a latency pass, and engine tests at 900 placements are not evidence of
live model generation at that scale.

`native-timing-audit.json` retains provider and tool timings separately. Run 04
made six provider calls totaling 96.995 seconds and recorded 21.414 seconds in
tools; its largest request used 87,258 input tokens. Run 03's seven provider
calls totaled 81.649 seconds, with 19.428 seconds in tools and a maximum request
of 87,701 input tokens. Those timings do not account for the entire visible
delay in run 03. Profile stage-specific schema/context payloads and the remaining
transport/UI time before attributing latency to equipment count or hardware.
Two runs cannot establish p95 or a general scaling curve.

The final provider failure retains only a bounded code, integer status and
sanitized exception type, not credentials, raw response bodies or error text.
HTTP 429 alone does not establish whether the cause is a transient rate limit,
account quota or exhausted credit. No alternate provider was silently selected.

Runs 01, 03, 04 and 05 have confirmed owned-child cleanup and zero application
and network Save calls. Run 02 has a generation report with zero Save calls but
no final application/network report or graceful cleanup receipt. Its parent
terminated the process tree. A later PID audit found none of the five runs'
owned Electron/backend processes still running; this does not retroactively
make run 02 a successful graceful shutdown. Failed evidence is retained.

### Next Gate

First rerun the unchanged mixed-cell native conversation when the configured
provider can accept requests. Require the correction, Plan/3D, unsaved Apply,
restart and exact Undo to pass together. Then qualify scale and measured latency
before integrating the remaining Factory 02 functional-review, attachment,
marking, amenity, wall and movement capabilities. Recording readiness is still
open; this report does not promote the full-factory feature.

## Acceptance Records

Retain successful and failed conversations, provider/model/configuration identity,
tool inputs and receipts, requirement dispositions, source and catalog revisions,
candidate hashes, all timing samples, native captures, and cleanup evidence.
Use a new isolated sheet for qualification; preserve Factory 02 and the manual
reference. The recorded interaction can be conducted by Codex as the user once
the real end-to-end workflow passes. Do not advertise the recording as working
manufacturing capacity, safety compliance or optimal production flow.

Freeze at least one detailed brief, one sparse brief, one materially different
catalog/site mix, one late correction and one genuine infeasibility case before
tuning. The reference inventory is an evaluation target, never an input artifact
secretly loaded as the generated output.

## Conversation Follow-up: October 2

The product-owner review rejected the verbose exchange as a user experience.
The earlier prompt is a controlled contract test, not a model for user-facing
conversation. Keep that original evidence and test unchanged.

`generation_preview_summary` was the source of the fixed validation paragraph;
the provider did not freely choose that wording. Its success reply now reports
the actual cell/item counts and unsaved state briefly. Open details remain
flagged in chat; assumptions, unknowns and engineering limits remain visible in
Planning. Raw assumption prose cannot become a server-endorsed chat claim.
The success gate still requires a validated receipt and adds no provider call.

The planning prompt now directs conversational, request-specific wording and
ordinary-language input. It must resolve existing facts from context rather than
requesting schema fields, IDs or internal permission wording. Consequential
missing information still requires clarification; this changes neither tool
authority nor Save approval.

`tools/scenarios/sage-assembly-cells-natural.json` is a separate short-input
acceptance case: a three-cell request followed by "Actually, one bench per cell
is enough. Keep the operators and everything else." The counts are test
assertions, not a runtime recipe or a prompt classifier. It must pass through
the real provider and native chat before natural-language acceptance is claimed.
The provider-limited contract test is not replaced, softened or relabelled as a
pass. No paid provider calls were made for this presentation change.

Local verification: **85 Python tests and 6 planning-view JavaScript checks
passed**. Coverage includes validated-count summaries, singular/plural wording,
open-detail disclosure, refusal of unvalidated success, non-endorsement of raw
assumption prose, source cards, and retained visible engineering limits. Evidence
is under `.runtime/sage-conversation-20261002/`. Scoped whitespace checks passed.
The existing Starlette/AnyIO warning remains. No native recapture or live
short-prompt qualification was performed, and no layout was authored or saved.
