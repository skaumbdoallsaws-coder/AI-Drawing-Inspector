# Sage brief-first research and layout preview

Date: 2026-09-17

Status: implementation and local verification checkpoint, not demo acceptance.
The user's complete request remains open. One live provider turn produced an
isolated prototype; general research-to-preview, live corrections, and normal
desktop adoption have not passed acceptance. No manual reference layout was edited.

## What changed

The Planning surface now offers **Start from your brief** on a clean, saved,
empty destination. A manually published reviewed context is no longer required
for a provisional concept. The reviewed path still uses its exact Process Map
identity/revision checks. Neither path grants manufacturing approval.

Sage has eight typed tools in this explicitly selected mode:

| Tool | Actual role |
| --- | --- |
| `inspect_generation_planning_context` | Read floor bounds, retained requirements, applicable mappings, and historical package pages. |
| `search_generation_equipment` | Inspect eligible current catalog records and exact revisions, with bounded pagination. |
| `search_generation_sources` | Search public evidence using the provider's real web search tool. |
| `read_generation_source` | Fetch a URL from an exact retained search receipt. |
| `propose_generation_context` | Propose an explicitly unreviewed process/resource interpretation with assumptions and unknowns. |
| `record_generation_requirements` | Bind executable requirements or unresolved clauses to the actual user turn. |
| `preview_generation_package` | Compile and validate a coordinate-free package through the existing engines. |
| `inspect_generation_candidate` | Read entities from that exact isolated candidate, not the saved layout. |

There are no product-name branches, task-selected fixture solutions, or model
coordinates in this path. Pattern enums select existing deterministic geometry
algorithms. Tests supply synthetic data; runtime planning is not backed by those
fixtures. This is an architectural property, not proof of generalization.

### Research and evidence

`ai_inspector/research/web.py` implements reusable, bounded Anthropic search and
fetch. It accepts public HTTP(S) destinations, rejects local/private targets and
credential URLs, and passes no desktop browser cookies or application credentials.
Research requests must use task-relevant public terms rather than whole private
documents or layouts. Source text is untrusted data, never application authority.

Returned citations must originate from actual provider search/fetch blocks, not
model prose alone. Results retain provider/model, retrieval time, source URLs,
locators where returned, bounded citations, truncation, usage and a result hash.
That hash identifies the retained result, not an independently archived whole web
page. Cited sources are prioritized before unused hits when bounding the result.

Research remains supporting/pending evidence. It is not automatically attributed
to every equipment assignment. A `source_consulted` requirement must name an exact
retained source/evidence pair before the turn can be committed. This proves
consultation, not model applicability, engineering approval or a parsed capacity
limit. Structured source-fact admission and local manual retrieval remain work.

Scout's separate missing `ai_inspector.search` dependency is not repaired by this
adapter. No claim is made that Scout now uses it.

### Continuity and recovery

- Unique exact user-text quotes are accepted in addition to Unicode spans; the
  server computes the quote offsets. Missing/ambiguous quotes fail explicitly.
- New predicates cover subject, department presence, catalog-only selection,
  disclosed assumptions and actual source consultation. Existing deterministic
  quantity, dimensions, mapping, pattern and spacing predicates remain active.
- Provisional spacing and quantities remain disclosed assumptions, not safety or
  capacity evidence. A recorded requested quantity cannot be reduced to make fit
  pass. The compiler now returns bounded affected batches and actual findings.
- The last successfully published preview has a durable, checked per-ledger
  reference. Its original model package is retrievable in bounded pages so a
  correction can reuse exact assignments, instead of rebuilding from chat prose.
- Historical packages require fresh admission under the current ledger/source;
  retrieval does not restore old eligibility. A failed preview leaves the last
  successful artifact intact. Publication and retry use existing repositories.
- Incomplete chat outcomes name a recorded question, unsupported clause, or tool
  error. Missing receipts cannot become success because the model says "done."
  An unsuccessful replacement is incomplete, not approval of its previous result.
- The old generation fallback no longer overwrites this selected mode's response.
  Caller-supplied outcome metadata is stripped before trusted context is rebuilt.

Coverage of text spans is structural. It does not independently prove that Sage
interpreted every clause correctly. Natural-language generalization remains an
acceptance obligation, not something these predicates alone establish.

### UI and boundaries

The existing shared Plan/3D candidate surface shows assumptions, unknowns and safe
HTTP(S) evidence links. Late results cannot replace a newer editor/source state.
This path still supports at most eight departments, 24 equipment batches and 120
placements, with circulation. Cells, module families, subdivisions and markings
are outside this adapter; their existing other generation paths are unchanged.

There is no editor Apply, lease acquisition or Save action in this new path. It
requires an empty destination with actual supported floor geometry. It cannot
generate directly into the occupied manual reference, adopt a dirty FDL draft,
or silently invent a larger factory floor. New destination creation and shared
draft adoption are required before a complete normal desktop demonstration.

## Verification

Final local run:

| Check | Evidence | Result |
| --- | --- | --- |
| Six focused Python suites | `.runtime/gen-research-final-09.xml` | 189 passed |
| Shared workspace JavaScript | `node tests/test_facility_layout_workspace.js` | 88/88 |
| Transport JavaScript | `node tests/test_facility_layout_transport.js` | 28/28 |
| Session JavaScript | `node tests/test_facility_layout_session.js` | 60/60 |
| Isolated Chromium, reviewed and provisional paths | `.runtime/gen-research-browser-02.xml` | 2 passed |

Python suites: generation agent, exploration, requirements, admission, program
execution and industrial patterns. New coverage includes source URL admission,
truncated citation retention, prior-package correction reuse, scoped retrieval,
failed-candidate preservation, and actual HTTP chat with synthetic provider
clarification/unsupported outcomes. Fake completion text cannot override them.

Chromium exercised Plan/3D at 1440x900, 900x700 and 430x820 with canvas pixel and
camera assertions, untouched editor state and no Save. Screenshots and reports:
`.runtime/generation-preview-evidence/gen-research-browser-02/`. Desktop 3D and
narrow Plan screenshots were visually inspected. These fixtures use simple
synthetic asset geometry, not GLB/native Electron acceptance. Provider calls are
not part of these browser tests. Python emitted existing Pydantic/websockets
compatibility/deprecation warnings; no dependency migration is claimed.

### Live provider evidence, including failures

`tools/verify_generation_research_live.py` exercises the real `/api/agent/chat`
endpoint and provider with an isolated host, optionally the real catalog, arbitrary
CLI prompts and a correction. It records tool inputs/results/errors and timings;
Save is prohibited. It is not a normal desktop/browser harness.

| Saved run | Observed result |
| --- | --- |
| `generation-live-brief-01` | Search worked; requirement classification/feedback failed. |
| `generation-live-brief-02` | Search and fetch worked; clause/obligation handling failed. |
| `generation-live-brief-03` | Requirements recorded; mapping evidence attribution failed. |
| `generation-live-brief-04` | Real research worked; collisions and an impermissible quantity reduction prevented completion. |
| `generation-live-brief-05` | Cited URLs lost during truncation prevented source-consultation validation. |
| `generation-live-valves-01` | Initial preview succeeded; correction failed, then provider credit exhausted. |
| `generation-live-brief-06` | Provider rejected the request for insufficient credit before tools ran. |

All paths above are under `.runtime/`, with `report.json` and retained artifacts.
Defects found during those attempts prompted fixes described above. The final
source-retention, historical-package and response changes have local evidence,
not a successful subsequent live research/correction conversation. Earlier runs
were development probes while code was changing, not a frozen release campaign.

The successful valve-workshop turn took **145.574 seconds** and produced four
departments, 11 placements and two routes using actual catalog identities:
four assembly benches, two inspection benches, four racks and one forklift.
Its receipt reports `prototype_geometry_valid`, two warnings and 48 unverified
findings. This does not establish manufacturing, throughput or safety feasibility.
It needed no web research and therefore cannot qualify research-to-preview.
The requested correction from four to three assembly benches did not complete.

There is no p95 claim or completed held-out acceptance corpus. Failed runs are
retained rather than excluded. Further provider calls stopped after the credit
error; no alternate paid account or provider was used to bypass it.

## Remaining gates, in order

1. Live verification of corrected research-to-preview and quantity-change flows
   after provider access is restored. Do not treat local mocks as substitute proof.
2. Typed provider/network failure and resumable progress, plus real in-app progress
   feedback. The observed multi-minute turns are not a qualified demo experience.
3. Explicit isolated destination/site selection and normal desktop real-asset
   chat-to-Plan/3D verification, without touching the manual reference.
4. Exact selected-proposal adoption using shared ownership, history, Apply/Undo
   recovery and separately authorized Save. Do not create another draft manager.
5. Bounded manual/source-fact retrieval and applicability admission where required.
6. Frozen held-out feasible/infeasible/ambiguous prompts, consequential corrections,
   actual provider-inclusive latency/failure rates, recovery and rehearsal.

The complete capability is **not demo-ready**. The delivery plan remains active
as project work, not a claim that broad manufacturing layout planning is finished.
