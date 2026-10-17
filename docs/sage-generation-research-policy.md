# Generation research-policy enforcement

Date: 2026-09-23. Product-readiness checkpoint, not release or demo qualification.

## Gap addressed

Previously, Sage could search before recording the user's requirements. A
`catalog_only` predicate restricts equipment selection, not internet research.
An earlier native example made no web calls but did not retain an executable
no-web requirement. Prompt instructions alone were insufficient: live probes
also showed the model claiming a policy was recorded without calling a tool.

The selected generation workflow now requires context inspection followed by
`record_generation_research_policy` before continuing its provider tool loop.
Those are protocol prerequisites, not a fixed manufacturing plan. Product,
equipment, process, quantities, geometry recipes and layout choices are not
selected by the test scenario or a phrase matcher.

## Executable contract

The authenticated server supplies the actual message, turn identity and planning
binding. The model supplies only a typed decision, its expected policy revision,
and an exact user-text quote where a change is explicit:

| Decision | Behavior |
| --- | --- |
| `inherit` | Preserve the prior mode. With no prior policy, use the application's existing permission for public research. Quote must be null. |
| `allow` | Record explicit permission for new public research. Requires a unique current-user quote. |
| `deny` | Block new public search and read calls. Requires a unique current-user quote. Local catalog and geometry planning remain available. |
| `clarify` | Block research and preview until an ambiguous or unsupported conditional restriction is resolved. Do not turn conditional permission into unrestricted access or a blanket user prohibition. |

Both search and read reject a missing current-turn decision before query/source
resolution, cached-result lookup or provider dispatch. A stored denial survives
follow-up turns and service recreation. `inherit` cannot reset it. Exact quoted
text establishes provenance, **not independent proof of correct interpretation**.
Live language evaluation therefore remains separate from enforcement tests.

Explicit allow/deny decisions also require a matching `research_policy` hard
constraint targeting the actual layout ID, with boolean `publicWebAllowed`.
It cannot be an assumption or a catalog-only substitute. Re-enabling research
when the brief contains a denial requires explicit supersession in the current
requirement ledger before search/read can execute. Admission independently
checks the active predicate against retained policy state.

This policy controls public research tool calls, including their cached replies.
It does not revoke previously retained evidence, prohibit model-provider calls,
or promise an air-gapped application. A restriction on which evidence may be
used is a different contract and cannot silently become this boolean permission.

## Persistence and recovery

- Uses the existing generation repository namespace and atomic-write/write-lock
  primitives; no new draft manager, lease owner or geometry engine.
- Stores a hash-checked, bounded journal under the existing ledger directory as
  `research-policy.json`. Ledger identity already binds principal, tenant, site,
  layout, base revision, workspace and reviewed/provisional context identity.
- Up to 64 turn decisions, matching the ledger's conversation bound. No separate
  TTL; this metadata remains with its ledger namespace and does not reference
  expiring run artifacts.
- Expected-revision checks serialize changes. One immutable decision per actual
  turn. Reordered object keys retry identically; changed retry values conflict.
  Old-turn retries cannot replace a newer decision.
- A lost receipt is recoverable through context inspection, which exposes the
  original arguments and `currentTurnRecorded`. The provider loop then reuses the
  decision rather than forcing reinterpretation. Exact retries use the original
  expected revision, not the latest head.
- Failed atomic replacement preserves the previous policy. Corrupt stored data
  fails closed rather than reverting to the default.
- Policy is checked again after provider execution and before returning results.
  Changed authority prevents late results from being offered as planning evidence.
  An HTTP request already dispatched cannot be unsent; this is not cancellation
  of work already performed by the remote provider.

## Implementation owners

| File | Responsibility |
| --- | --- |
| `ai_inspector/facility_layout/generation_research_policy.py` | Bounded journal, current-turn policy, durable retry and research gate. |
| `ai_inspector/facility_layout/generation_agent.py` | Published tool/predicate schemas, context projection, requirement consistency and receipt-based required preflight. |
| `ai_inspector/facility_layout/generation_exploration.py` | Gate search/read and reject stale returns. Retained-evidence reading is unchanged. |
| `ai_inspector/facility_layout/generation_requirements.py` | Typed boolean predicate, layout binding and deterministic evaluation. |
| `ai_inspector/facility_layout/generation_admission.py` | Independent policy consistency during package admission. |
| `server.py` | Actual provider-loop prerequisites, semantic guidance and streaming progress mapping. |

Claude's structure-tree files, selection/history algorithms, the Electron browser
and the user's manual layout were not edited in this batch. Apply and Save
permissions are unchanged.

## Verification

Final focused rerun: **253 passed**, with no failures or skips, in
`.runtime/research-policy-final-02.xml`. This includes the final lost-receipt
recovery changes. The counts below describe overlapping and separate evidence;
do not add the overlapping Python runs together.

- `.runtime/research-policy-final-01.xml`: 252 passed, two browser cases skipped
  because that invocation did not enable their explicit opt-in.
- `.runtime/research-policy-recovery-final.xml`: 40 passed after receipt-recovery
  hardening. This overlaps the larger suite and is not an additional unique count.
- `.runtime/research-policy-browser-01.xml`: both opted-in Chromium cases passed,
  using the real workspace/backend and synthetic reviewed/brief inputs. These
  cover generation preview, Apply/Undo and lost-ack/reload behavior; not live chat
  or native Electron acceptance.
- `node --test tests/test_facility_generation_view.js`: four passed.
- `.runtime/research-policy-live-03.xml` and matching JSON directory: eight paid
  provider probes passed with the configured `claude-sonnet-4-5-20250929` model.
  They use the actual generation prompt/schema and required policy step after
  seeded context inspection, then execute the selected policy. They stop before
  research or layout generation. This is not a full chat-to-layout benchmark.
  The final receipt-recovery addition is covered by the deterministic reruns,
  not a repeated live-provider or native Electron campaign.

The eight live cases cover explicit no-web, an offline paraphrase, catalog-only
equipment with permitted research, inherited denial, explicit re-enabling, and
three narrower publisher/topic restrictions. Each passing probe used one provider
call, taking 2.601-3.803 seconds inside that bounded probe. No p95 or overall
preview-latency claim is made.

Earlier failures remain preserved:

- `research-policy-live-01`: five of six passed; conditional permission was
  misclassified as blanket denial.
- `research-policy-live-02`: five of eight passed; some model replies skipped the
  recording tool, including one unsupported claim that a restriction was recorded.
  These findings drove the required provider preflight, not a relaxed test.
- `research-policy-regression-01`: missing streaming progress mapping for the
  new tool; fixed and covered by streaming/non-streaming endpoint tests.
- `research-policy-regression-03`: the newly included failed-read recovery test
  needed the explicit preflight now required of all research callers. Its original
  read-failure/recovery assertions remain unchanged.

## Still open

1. Exact publisher/domain/topic restrictions and applicable source-fact admission.
   Conditional requests currently stop honestly; no manufacturer-only filter or
   equipment configuration verification is claimed.
2. Broader mixed-language/long-history qualification. Eight narrow probes cannot
   establish semantic completeness for arbitrary manufacturing requests.
3. Durable interrupted whole-request resumption, including failures before any
   policy decision is committed. The policy journal does not solve that larger
   conversation-lifecycle problem.
4. Overall provider-inclusive generation/correction latency and a frozen held-out
   product campaign. The earlier multi-minute layout turns remain open findings.
5. Native Electron recapture of this new preflight in a complete live conversation.
   Earlier desktop Apply/Undo/Save evidence is retained, not presented as a fresh
   run of this change.
