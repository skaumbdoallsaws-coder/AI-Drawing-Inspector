# Generation Performance and Reliability Pass

Status: implementation and measurement in progress. No new qualification claimed.

## Frozen Baseline

Native equipment-document scenario: 216.403 seconds initial, 62.145 seconds
for a quantity correction (`.runtime/equipment-doc-native-02`). Initial planning
made eleven provider requests; correction made seven. Saved layout bytes were
unchanged and Apply/restart/Undo passed. These are two timings, not a p95.

## Scope

1. Measure provider calls, tool stages and complete rendered desktop turns.
2. Supply freshly validated context before the first provider call.
3. Compose research policy, requirement recording and preview/revision through
   existing services. Charge internal actions against the existing budget.
4. Stop after a validated final preview and render a receipt-derived summary.
5. Prove retry, partial failure, stale state, authority and geometry rejection.
6. Run varied live-provider inputs and native Apply/restart/Undo on isolated data.

No changes to source documents, catalog, manual layout, structure-tree UI,
geometry tolerances, Save authority, evidence eligibility or tool budgets.
An unsuccessful search is not proof of infeasibility. Every consequential clause
still needs a recorded disposition; no prompt-specific candidate coordinates.

## Measurement Gates

Measure submission through visible results, including provider and rendering.
Immediate document scenario target: initial under 90 seconds, correction under
10 seconds. Report all samples and failures. A small sample does not establish
p95. Broader product targets (warm small layouts under 30 seconds, reviewed
reference-scale programs under 90 seconds) require their own measured workloads.
Historical supplied-program timing is not an end-to-end planning benchmark.

## Required Evidence

Retain actual prompts, identities, revisions, provider/tool timings, counts,
source receipts, validation results, native screenshots, saved hashes and cleanup.
Test equivalent retry, changed retry, partial compound failure, new user turn,
missing source, restrictive research policy, impossible fit and stale preview.
No test failure or missed latency target may be relabeled as passing.

## Implementation Checkpoint

- Provider timings and token/cache counts are returned separately from tool time.
- Context preflight executes through the authorized tool path before the model
  call, and consumes the existing call and response budgets.
- A compound policy/requirement/preview action reuses the same admission and
  geometry checks. Partial failure retains only repairable planning artifacts.
- Exact source-segment references avoid repeated long quotations. They are text
  locators, not proof of independent semantic understanding.
- Successful terminal previews use a receipt-derived response instead of another
  provider synthesis call. Pattern gaps are not described as operating clearance.
- Search/textless PDF results expose a discovery handle, not a document-read
  handle. Relabelling one still fails server-side admission.
- Corrections receive a smaller revision tool schema. If the full context cannot
  fit, a separately labelled projection preserves every active requirement and
  the exact previous package; omitted source detail remains paginated.
- Preservation now guards package fields as well as earlier requirements. A
  quantity correction cannot silently change department shares or route IDs.
  This guard applies at admission, including full-package and sparse revisions.

Anthropic tool-prefix caching is opt-in on the request-owned tool definitions,
following the [provider's documented tool caching contract](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-use-with-prompt-caching).
It does not cache user messages or waive current source/asset validation. No
model change, larger tool budget, tolerance relaxation or automatic Save was made.

## Evidence So Far

| Run | Initial / correction | Outcome |
| --- | --- | --- |
| `generation-performance-live-01` | 264.580 s / not reached | Failed requirement compilation; preserved, not excluded. |
| `generation-performance-live-02` | 148.046 s / 51.105 s | HTTP/live provider succeeded; not native evidence. Both speed targets missed. |
| `generation-performance-native-01` | 219.948 s / 64.044 s | Native rendering/restart/Undo passed. Independent package audit **failed**: correction also changed department shares, department/route IDs and route width. Not accepted as correct replanning. |
| `generation-performance-native-02` | 116.154 s / 48.834 s | Independent document/package/geometry audit passed: only lift quantity changed; lathe identical. Actual Plan/3D inspected, Apply/restart/exact Undo passed, zero Save, cleanup confirmed. Both speed targets missed. |
| `generation-performance-native-03` | 435.424 s / not reached | Varied workbench brief failed: inconsistent process/resource bindings and unsuccessful repairs. Thirteen provider calls included an unused 106.172 s final synthesis. No Apply/Save; owned backend cleaned up. |
| `generation-performance-native-04` | 284.518 s / not reached | Same unchanged workbench prompt failed again. Duplicate mappings, uncovered claim restrictions and malformed requirements caused repeated full-plan rewrites. No Apply/Save; owned backend cleaned up. |
| `generation-performance-native-05` | 146.237 s / not reached | Same prompt failed on a string-valued preview and nonconsecutive clause references. Failed arguments retained; no Apply/Save; cleanup confirmed. |
| `generation-performance-native-06` | 157.665 s / not reached | Requirements-only repair succeeded, then same-department routes were rejected by the compiler but surfaced as generic read errors. Sage repeated the invalid preview and stopped. No Apply/Save; cleanup confirmed. |
| `generation-performance-native-07` | 149.119 s / not reached | Same prompt reached repeated requirement repairs, then Anthropic rejected the seventh call for insufficient credit. No valid preview, Apply or Save; cleanup confirmed. This is a failed/incomplete sample, not an excluded timing. |

The native run made zero Save calls, retained the original manual hash
`a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088`,
restored the isolated concept exactly, and confirmed owned-backend cleanup.
Plan and 3D screenshots were inspected, with actual lathe/lift meshes present.
These successful checks do not override native-01's failed semantic correction
audit. Native-02 closes that specific correctness finding, not the speed gates.
Its complete responses show an omitted repeated restriction and a guessed ledger
revision during recovery; both were refused before successful correction.

The updated regression checkpoint passed 373 Python tests, including package
preservation, revision-context fallback, and reference-walk equivalence
(`.runtime/performance-tests-09.xml`). The focused frontend/recovery run passed
63 Node runner cases, including the legacy session (60 checks) and transport
(29 checks) suites. These counts overlap; do not add them together. The native
harness now retains complete SSE responses and distinguishes a completed
unsuccessful conversation from a timeout.

The first 20-sample reference-scale engine benchmark is retained at
`.runtime/generation-performance-reference-01.json`: full generation p95
47,896.173 ms (90,000 ms limit, passed), local amendment p95 19,983.559 ms
(10,000 ms limit, failed). Every result checks the expected 827 placements,
45 zones, eight routes and 50 markings, plus exact Undo and no Save. This measures
a supplied program, not Sage discovering that program from an open-ended brief.

Profiling identified repeated generic Mapping dispatch in the recursive
reference checker as the dominant amendment cost. The implementation now uses
an iterative JSON traversal, retaining generic mapping/list support and exactly
the prior key/value reference semantics. Deletion still checks every current
dependency; no reference check or geometry validation is bypassed. The profiler
is diagnostic, not a timing benchmark; a fresh 20-sample campaign is required.
No provider-inclusive p95 or product readiness is claimed at this checkpoint.

The second unchanged 20-sample engine campaign,
`.runtime/generation-performance-reference-02.json`, measured full-generation
p95 20,661.653 ms and amendment p95 19,435.143 ms. Amendment median improved
from 9,219.749 to 2,860.827 ms, but two stalls still violate the p95 gate. All
samples remain included. The next campaign additionally records process/thread
CPU time to investigate this variance; the wall-time gates are unchanged.

The third unchanged campaign, `.runtime/generation-performance-reference-03.json`,
passed all three engine gates across 20 measured samples: macro p95 1.2675 ms,
full generation p95 15,538.1288 ms, amendment p95 3,124.4822 ms. The slowest full
sample remains included (57,883.1463 ms wall, 23,437.5 ms process/thread CPU).
This establishes a substantial off-CPU delay in that sample, not its cause.
No competing test or provider campaign was launched during this measurement.
Ordinary machine workloads were not stopped. Earlier failed campaigns remain
part of the reliability evidence; this passing campaign does not erase them.

## Varied-Input Recovery Follow-Up

The unchanged workbench brief requests five benches across preparation,
assembly and visual checking, followed by an assembly-only quantity correction.
Neither native-03 nor native-04 reached that correction. These are product
failures on reasonable input, not successful conditional answers.

The source contract already allows the same catalog model for different
operations. An initial verbal diagnosis that it disallowed this was incorrect.
The actual duplicate check keys on asset, revision and process-step set. The
model first repeated a mapping, then changed assignments inconsistently.
New regression coverage proves distinct assignments remain allowed and exact
duplicates return the affected binding and actionable guidance.

Changes following those runs:

- Validate resource mappings before committing requirements; a failed attempt
  cannot poison the retained ledger with an unmappable resource requirement.
- Return failed predicates and their source clauses, not only hashed IDs.
- Preserve the compound action's partial-commit state in repair diagnostics.
- Stop without a discarded model synthesis when execution is exhausted.
- Do not offer a compound tool when the remaining execution budget cannot run it.
- Expose requirement-only or preview-only repair schemas according to trusted
  receipts, instead of repeatedly requesting a complete compound proposal.
- Narrow the preview mode and require current source-segment coverage in the
  provider-facing schema when the context establishes the candidate state.
- Factor repeated schema descriptions without changing predicate validation;
  retain failed arguments in the authenticated trace for reproducible diagnosis.

The first follow-up regression checkpoint passed 383 Python tests
(`.runtime/performance-tests-14.xml`). The subsequent focused run passed 94 and
failed two test-provider assertions that still expected the entire tool registry
after requirements had committed. Those assertions were updated to require the
exact new repair-stage tool set. The broader rerun then passed all 389 focused Python tests
(`.runtime/performance-tests-16b.xml`). The source/program/catalog/operation-plan
revisions are identical across all three engine timing campaigns. Native-03
through native-07 use the same frozen workbench prompts and expected counts.

## Compiler Findings and Provider Interruption

Native-06 exposed an error-boundary defect, not an invalid-routing allowance:
`FacilityCirculationError` was raised correctly for a route starting and ending
in Assembly, but it was not normalized into the agent's structured error contract.
The admission boundary now preserves codes, messages and details for the known
compiler exception classes. Unexpected runtime faults are not reclassified as
user mistakes. Tool guidance explicitly distinguishes department circulation
from unevaluated intradepartment station transfers. No route check was relaxed.

A real compiler regression adds an invalid self-route, verifies the precise
refusal, removes only that proposed extra route, and compiles successfully
under the unchanged ledger. Compound-action coverage additionally checks the
retained ledger and preview-only repair reference. The initial focused run
passed 150 Python tests (`.runtime/generation-performance-tests18.xml`).

Native-07 then exposed a diagnostic gap: a provider exception discarded the
preceding tool trace from the terminal SSE error, although individual provider
timings remained in server logs. New bounded `generationDiagnostics` accompany
the existing `response_error` event. They retain provider timings, tool findings,
binding IDs and bounded failed arguments, with explicit omission hashes/counts.
They exclude raw provider exceptions and do not claim a completed preview.
Synthetic-provider HTTP/SSE tests cover failure before the first answer and
after a tool refusal. The focused run passed 50 tests
(`.runtime/generation-performance-tests19.xml`); this is not fresh live evidence.

The final local checkpoint passed 403 focused Python tests
(`.runtime/generation-performance-tests20.xml`) and 21 additional chat-streaming
tests (`.runtime/generation-performance-stream-tests21.xml`). The Node command
covering generation view, session, transport, chat runtime/contracts and desktop
session passed all 25 runner cases. Wrapped legacy suites also report 60 session,
29 transport, 20 frontend-contract and 11 streaming-runtime checks; these are
included in that run, not additional runner cases. Its first invocation failed
a stale test requiring a hard-coded Iris placeholder/default. Only that test
was updated to the existing neutral placeholder and `DEFAULT_AGENT_KEY`;
application UI and Claude's structure-tree files were not edited. The rerun
passed. Focused `git diff --check` passed.

The original manual layout SHA was rechecked after native-07 and remains
`a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088`.
The native-07 lifecycle record confirms owned-backend termination, closed
resources, and no cleanup errors. That checkpoint paused live calls pending provider credit;
provider access was restored for the September 28 continuation below.

## September 28 Continuation

Provider access is working again. Additional retained samples:

- `generation-performance-native-08`: backend exited with Windows status
  `0xC0000005` during application import. No chat submission occurred. Child
  termination was recorded; graceful resource closure was not established.
- `generation-performance-native-09`: the test reached live generation, but a
  stale restricted filesystem view was mistaken for a startup stall. The test
  operator terminated this isolated run. It is an aborted sample, not a product
  startup failure or a successful generation result. The abort record is retained.
- `generation-performance-live-03`: live SSE API test on the verifier default
  40 x 30 m shell, using the same conversation text. It failed after 238.846 s
  without a preview or correction. This is not the unchanged 35 x 25 m native
  workload. Saved state was unchanged and Save was never called.

The API trace showed non-adjacent clause references, uncovered process edges,
and then provider responses with `stop_reason=refusal`. The old loop attempted
to execute and repair partial tool arguments from those refused responses.
The continuation stops generation on provider refusal or output truncation,
without executing those partial calls or requesting another repair response.
It reports a specific incomplete outcome and retains preceding diagnostics.

The first continuation changed provider-facing requirement schemas to ask for
one known segment per requirement, including repair and correction paths. Repeated clauses get
separate records; multiple predicates may still cite one segment. The server
continues accepting validated contiguous legacy spans and enforcing complete
clause coverage. String-valued requirement arrays receive a shape error, not a
misleading budget error. Process-step schema guidance explicitly distinguishes
operations from repeated physical equipment instances. This guidance alone is
not proof of semantic correctness.

Native-10 then failed after 121.930 s: two substantive clauses were omitted
before the provider refused its repair response. The new stop behavior was
observed in Electron: five provider calls, no execution of refused tool inputs,
and graceful owned-backend cleanup. This is a failed generation sample, not
positive layout qualification.

The follow-up replaces optional model locator lists with a required
`requirementsBySegment` object in current-turn tool schemas. Every actual
segment has a required nonempty slot; entries contain the model-selected
predicates or unresolved dispositions. The server supplies only the exact text
locator, then reuses the existing ledger compiler, authority checks, 64-entry
budget and durable retry identity. Flat legacy requests remain validated. The
shared item schema is emitted once, avoiding duplication for each segment. This
structural change does not independently prove that a model assigned the correct
meaning to a clause. Route-field guidance also makes the existing prohibition
on same-department self-routes explicit at the point of construction.

The live verifier also no longer shadows its saved-layout baseline while
comparing equipment quantities. No model, solver, numerical tolerance, tool
budget, authority rule or saved user layout was changed by this continuation.

Verification before the required-slot follow-up: 316 focused Python tests
passed with no skips (`.runtime/generation-performance-tests25.xml`). Earlier attempts are retained:
22 failed collection without jsonschema; 23 had nine schema dependency failures
and two over-strict new trace assertions (73 passed); 24 had 50 temporary-directory
setup errors (34 passed). The trace assertions now allow existing diagnostic
enrichment while still requiring the exact original finding. Run 25 used the
existing dependency bundle with a fresh workspace-owned temporary directory;
no dependency, product contract or test predicate was bypassed.

The required-slot follow-up passed all 61 focused provider-recovery and
performance tests (`.runtime/generation-performance-tests27.xml`). Run 26 is
retained: seven new fixture failures came from treating the two separately
segmented preview/Save clauses as one source span; one fingerprint failure
coincided with a source edit during that run. The fixture now gives the separate
clauses distinct records, and run 27 ran without concurrent source edits.
No new live success is implied by these synthetic-provider tests.

Native-11 completed unsuccessfully after 141.415 s. Required slots exposed two
empty qualifier slots, rather than allowing omission; the repair then incorrectly
used first-turn preservation for count/claim restrictions. Server validation
rejected it before the provider refused a subsequent response. Zero Save calls,
graceful backend exit, and closed resources are recorded in the lifecycle receipt.
The next change removes preservation from first-turn schemas (the ledger already
rejects it), defines count and prototype-limit semantics beside their parameters,
and explicitly permits identical predicates with distinct source-clause records.
Recovery diagnostics now name the requirement-only repair tool actually exposed,
rather than contradicting that tool set by asking for another compound call.

Provider grammar-constrained tool inputs are a possible follow-up for shape
failures, not an enabled change or a semantic correctness claim. The current
schemas need a compatibility audit before using the provider's supported subset;
local validation and refusal/truncation handling must remain authoritative.
See [strict tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use)
and [schema limitations](https://platform.claude.com/docs/en/build-with-claude/structured-outputs#json-schema-limitations).
No model or provider mode was changed in these runs.

All 326 broader regression tests passed in
`.runtime/generation-performance-tests28.xml` (no skips). This covers the
first-turn predicate and recovery-guidance changes, grouped compound execution,
and duplicate-free retries. A final entry-path review moved clause-slot binding
outside the existing-candidate-only branch, so immediately available reviewed
context receives the same clause coverage as discovery and follow-up paths.
That final small change passed all 65 focused tests in
`.runtime/generation-performance-tests29.xml`; run 28 predates it. Counts
overlap and must not be added together.

Native-12 stopped before any chat/provider call: the concept form was collapsed
and its checkbox was occluded. Inspection found that every panel refresh
recreated the form with default values, including late source-list completion.
The generation view now retains the same form controls and restores their focus
after refresh; existing dirty/pending/authority checks still determine whether
creation is available. A delayed-source DOM regression verifies expansion,
entered values, confirmation, focus and exact submitted dimensions. All five
generation-view tests and the existing 88 workspace checks passed (six Node
runner cases in `.runtime/generation-performance-ui30.json`). Native-12 recorded
zero Save calls and graceful cleanup; it is not a provider timing sample.

Native-13 passed concept creation but failed after 196.179 s, before a preview
or correction. It retained all clause slots, but omitted the mandatory envelope
predicate. The ledger committed before admission checked mandatory coverage;
six subsequent package rewrites could not repair an already committed omission.
This is an implementation recovery defect, not physical infeasibility. The run
recorded zero Save calls and graceful resource closure.

The mandatory coverage check is now shared between ledger recording and package
admission. Before commitment it requires envelope/preview predicates and counts
for mapped resource IDs; admission still checks every actual package resource.
Missing predicates are returned explicitly while the turn remains uncommitted,
and the repair tool is the requirements tool. Explicit unresolved clauses may
still be retained for clarification, but cannot admit a preview. No dimensions,
counts or clause meanings are inferred by this guard.

The complete focused generation suite passed all 331 Python tests with no skips
after that guard (`.runtime/generation-performance-tests31.xml`). Missing
envelope, preview permission, and resource-count cases each prove rejection
before commitment followed by successful same-turn repair and real compilation.
A separate case retains a genuinely unresolved requirement while rejecting its
preview. This supersedes the earlier Python checkpoints for the current code;
it does not replace native acceptance or the provider-inclusive speed campaign.

### Native-14: Preview And Correction Pass; Restart Fails

The unchanged 35 x 25 m workbench conversation produced five placements, then
four after the assembly-only correction. Submission-to-preview times were
109.738 s and 42.709 s. Both fail the unchanged 90 s / 10 s scenario gates;
this is not a passing performance sample or a p95 result.

The initial request used six provider calls, including recovery from a missing
envelope predicate before ledger commitment. The correction used one provider
call (17.756 s) and 18.554 s of recorded tool time. This is evidence that both
provider output/repair overhead and local execution latency need work, not that
either has been solved. No supplied coordinates or replacement fixture recipe
were introduced.

An independent read of the immutable admissions verified that `req-assy-bench`
changed from three to two and every other model-package field remained identical.
Preparation and checking stayed at one each. The receipt retains both preview
identities, candidate revisions, artifact paths and hashes:
`.runtime/generation-performance-native-14/independent-preview-audit.json`.
The Plan and 3D screenshots were inspected. Four real bench models are visible;
the transform audit reports four placements, 88 matrices, zero mismatches and
no degraded rendering. Unsaved Apply installed the evaluated candidate.

The subsequent owned-backend restart failed. Its Python child exited during
`application-import` with `0xC0000005` (`desktop_backend_early_exit`). The first
backend shut down gracefully; termination and closed streams were confirmed for
the failed replacement, but graceful resource closure was not established.
The ordinary UI kept the draft in the window and displayed the restart error.
After that notice was dismissed, the old harness advanced to Undo because it
checked only that a new instance existed. Undo failed with `Failed to fetch`.
The saved native report remains unmodified; it is a failed run, not successful
restart/Undo acceptance. The import crash's cause remains unidentified.

The harness now checks ready state, new instance identity and verified runtime
evidence before advancing beyond restart. It retains backend evidence and Save
counts on failure, and reports the actual restart error. Four new cases cover
ready success, failed startup, interrupted/unverified state and cancelled/reused
instances. All 47 Node tests in the combined acceptance-guard, application and
supervisor run passed (`.runtime/generation-performance-restart-tests32.json`).
That reporting change has not had a new native run and is not a crash fix.

The independent audit confirms zero Save calls and unchanged original/copy
manual hashes. The isolated concept's saved bytes still hash to its original
base revision. All processes owned by native-14 have exited; the normal user
application was not terminated or restarted. Original failures and artifacts
remain retained.

### Native-15: Full Lifecycle Pass; Latency Still Fails

The unchanged workbench prompts passed in the real Electron application:
five placements, assembly-only correction to four, Plan and 3D, exact unsaved
Apply, verified managed-backend restart, and exact Undo. The independent persisted
admission audit confirms that only `equip-assembly.quantity` changed from three
to two; every other package field stayed identical. Four real bench models
rendered, with 108 instance matrices and zero transform mismatches. Both captured
Plan/3D images were inspected. Saved original, copied manual, and concept bytes
remained unchanged; zero Save calls and graceful cleanup for both backends.

Evidence: `.runtime/generation-performance-native-15/generation-check.json`,
`independent-preview-audit.json`, and `last-application-run.json` in that directory.
One earlier invocation used relative launcher paths and exited before a backend
or provider request; it is not a generation sample.

Timings: 106.796 s initial, 21.426 s correction. Both miss the unchanged 90 s /
10 s limits. Initial generation made six provider calls; a missing envelope
predicate caused requirement repair plus package resubmission (43.058 s combined
provider time). Correction used one 18.513 s provider call and 1.087 s of tool
time. A separate real-kernel profiler with synthetic reviewed inputs measured
0.431 s for revision, including profiler overhead, at
`.runtime/demo-correction-profile-01/`. That diagnostic is not a live benchmark.

The startup investigation reproduced a crash in the installed interpreter's
asynchronous C stack watchdog, even without the application. Replacing it with
bounded cooperative Python frame sampling passed eight stress children and ten
real backend start/restart cases. Attribution and limits are documented in
[the startup report](desktop-startup-stack-sampling.md). This supersedes the
unidentified-cause status for the reproduced diagnostic failure class; earlier
unexplained wall-time stalls remain open.

The next change makes the existing mandatory envelope/quantity/preview rules
explicit in both model tool descriptions and the context overview, including
room references whose dimensions come from trusted context. It does not infer
requirements, silently add predicates, grant permission, or change source-clause
validation. The combined focused suite passed 217 Python tests and 30 subtests
(`.runtime/demo-readiness-tests03.xml`). Native-16 is the unchanged follow-up;
its outcome follows below.

### Native-16: Repeat Lifecycle Pass; Further Contract Friction

Native-16 again passed the complete native lifecycle and independent quantity-only
package audit, with zero Save calls, unchanged original/copied/concept hashes,
and graceful owned-process cleanup. The 3D screenshot was inspected. Timings
were 153.242 s initial and 32.224 s correction, so performance still fails.
The initial request used nine provider calls. Envelope coverage was present,
but two context proposals had malformed catalog revision strings, and a compound
turn attempted to change an already-recorded research decision. Existing server
checks rejected all three; recovery completed without relaxing authority.

The next provider-schema change uses successful catalog receipts to advertise
exact asset/revision pairs in context mappings. All observed pages remain
available, with the latest observed revision per asset; another catalog search
is still available. This is a bounded discovery aid, not proof of currentness or
manufacturing capability. Server-side current catalog checks still run.
After a successful current-turn policy receipt, the compound tool's policy input
is explicitly null. It cannot ask the model to record the decision a second time.
Generic tool execution and durable retry rules are unchanged.

The fresh combined generation/startup suite passed 393 tests and 30 subtests,
with 12 opt-in browser/provider tests skipped
(`.runtime/demo-readiness-tests04.xml`). Skipped tests are not qualification;
native/provider evidence is recorded separately. Native-17 repeats the unchanged
workbench scenario for these schema changes; its actual result follows.

### Native-17: Initial Timing Pass; Correction Timing Still Fails

The same scenario completed in 74.050 s initial and 20.345 s for correction.
Initial generation used four provider calls with no failed tools or repair
responses. This is one initial-turn sample below the frozen 90 s limit, not a
p95 claim. Correction still fails its 10 s limit: the single provider call took
13.037 s (864 output tokens), tools 3.845 s, with the remaining time in other
server/transport/render/test-observation work. That residual is not yet attributed
to a specific component and is not excluded from end-to-end timing.

Native lifecycle and independent audit passed again: five placements became four
by changing only `equip-assy.quantity` from three to two; every other package
field was identical. Real meshes were inspected in the captured 3D image.
Unsaved Apply installed the evaluated candidate, restart verified a new owned
backend, and Undo restored the promised editor state. Zero Save calls and
unchanged manual/copy/concept saved hashes. Both backends closed gracefully;
final cleanup is in `last-application-run.json` because the generation report
is written before final application shutdown.

Evidence: `.runtime/generation-performance-native-17/`, including the complete
conversation, native screenshots, immutable proposal artifacts, lifecycle report
and `independent-preview-audit.json`. The original manual hash was independently
rechecked after completion and remains
`a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088`.
The follow-up Node run passed all 47 application/supervisor/acceptance-guard tests
(`.runtime/demo-readiness-node05.stdout.log`). No user application was restarted.

Three consecutive native runs now pass this bounded workbench lifecycle.
Native-15/16 timing failures remain included, as do all earlier failures.
This is not qualification of unfamiliar briefs, station-to-station physical
flow, research fact applicability, reference-scale chat planning, or a 20-run
provider-inclusive performance campaign.

## Remaining Gates

1. Extend the now-passing native lifecycle checkpoint to repeated and varied
   inputs. Native-15 establishes the complete unchanged workbench lifecycle;
   the startup stress/campaign evidence does not eliminate every reliability risk.
2. Reduce provider-output and repair overhead without dropping user clauses or
   bypassing authority. Initial latency has one passing sample, while correction
   latency remains a failure. Investigate a smaller exact-revision-bound semantic
   correction contract and attribute the remaining local/render overhead; do not
   replace general planning with a prompt-specific shortcut or omit validation.
3. Repeat the local-equipment-document scenario and distinct held-out inputs,
   preserving complete successful and failed traces.
4. Run the unchanged 20-sample provider-inclusive campaign only after basic
   correctness succeeds. Report completion rate and all samples, not just
   successful response times. Keep the existing latency limits.

The pass remains incomplete. Provider-inclusive small-layout and correction
speed gates, varied-input native success, and a repeated provider-inclusive
latency campaign have not been established. No product-readiness claim is made.
