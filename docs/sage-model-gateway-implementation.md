# Sage Model Gateway

Started October 1, 2026. Scope: Facility Layout model routing, not a replacement layout engine or a general release qualification.

## Contract

Sage calls stable roles through one backend-owned interface. A versioned JSON gateway configuration maps `facility-planner`, `facility-router`, and `research-reader` to immutable deployment settings. LiteLLM supplies the provider transport; no new public listening port or Electron credential bridge is needed for this desktop slice. The interface can later use a hosted proxy without changing layout tools.

On October 1 the product owner requested promotion. The normal native desktop profile now explicitly enables the gateway and selects Astra for Facility Layout planning. The direct Claude path remains available as rollback and remains unchanged for launches without gateway activation. This is an authorized default change, not closure of the planning reliability or latency findings below. Compatible model changes are configuration-only; incompatible capabilities fail visibly. No automatic cross-model fallback, silent parameter dropping, tool execution by the gateway, or automatic Save.

A request captures one configuration snapshot. Active generation work must retain its provider binding across turns and restart, or reject a changed binding before further provider/tool execution. Receipts record actual provider/model and gateway configuration identity, never keys or raw provider exceptions. Research remains isolated from the logged-in Electron browser and preserves source provenance and pending-review status.

## Implementation Status

1. [complete] Strict configuration, lazy pinned LiteLLM transport, normalized tools/history/streaming, bounded errors, cancellation, request snapshots.
2. [complete] Facility planning, semantic routing, provider-side research, generation-ledger binding and staged-run configuration binding. Deterministic engines and existing write authorization remain the execution owners.
3. [complete] Offline transport, HTTP/kernel, repair, cache isolation, persistent binding, rollback, and configuration-edit tests.
4. [complete] Live OpenAI/Anthropic protocol checks, real HTTP-to-kernel generation, manufacturer search, and public document reading.
5. [complete for the bounded slice] Native two-bench generation, real asset rendering, Apply, restart and Undo passed; evidence and rollback instructions are recorded below. Limited-information generation qualification remains open.
6. [active on next native launch by explicit owner request] Normal desktop gateway binding and Astra default selection. A fresh native run verified actual Astra calls through that binding; layout generation failed requirement validation. Historical and fresh failures are not relabelled.

## Code Owners

| Owner | Responsibility |
| --- | --- |
| `ai_inspector/model_gateway.py` | Closed configuration, stable roles, provider transport, safe receipts/errors, native research provenance, immutable generation model binding. |
| `config/sage-gateway.json` | Deployment settings and role assignments; contains no API keys. |
| `server.py` | Request scope, planning/answer calls, routing and shadow routing, truthful streaming errors. |
| `ai_inspector/facility_layout/provider_config.py` | Explicit gateway opt-in versus existing frozen Claude configuration. |
| `generation_agent.py`, `generation_coordinator.py`, `generation_run_repository.py`, `knowledge_foundation.py` | Binding validation before generation tools, durable staged-run identity and its optional backward-compatible `gatewayRevision`. |
| `ai_inspector/agent_skills/shadow.py` | Configuration-scoped routing cache. |
| `ai_inspector/research/web.py` | Existing search/read normalization and supporting, pending-review evidence. |
| `tools/sage_gateway.py` | Inspect, validate and atomically change the JSON configuration without a paid call. |
| `tools/check_sage_gateway.py`, `tools/verify_sage_gateway_desktop.py` | Explicitly opted-in API and isolated native checks. |
| `desktop/src/application-profile.cjs`, `desktop/runtime/application_profile.py`, `desktop/src/runtime-supervisor.cjs` | Optional validated desktop gateway binding and isolated backend dependency path. Profile identity, stores and renderer partition do not change. |

The published Facility skill contracts opt into `gateway-facility-planner`; they do not assert that every compatible deployment is qualified for layout planning. Other workflows retain their existing routing. FDL/construction sessions do not gain a new universal conversation-migration mechanism from this work.

## Configuration And Rollback

Promoted mappings are `facility-planner -> astra-candidate`, `facility-router -> haiku-router`, and `research-reader -> claude-research`. The planner is `gpt-6-astra`, medium reasoning. The existing deployment ID is retained to avoid gratuitous identity changes. Research remains an explicitly assigned Claude deployment; this is not a fallback.

From the project root, these commands require no provider requests:

```powershell
python tools/sage_gateway.py show
python tools/sage_gateway.py validate
python tools/sage_gateway.py select facility-planner astra-candidate
python tools/sage_gateway.py select facility-planner claude-baseline
```

Each deployment declares provider, exact model ID, supported endpoint, capabilities, timeout, output limit and reasoning setting. Compatible model IDs/settings can change here without application edits. A new provider, endpoint, tool protocol or capability still requires adapter work and qualification. Configuration capabilities are administrative declarations, not evidence that a model can perform a manufacturing task.

The update command uses an exclusive lock and atomic replacement. Validation/replacement failures retain the old file. If the process dies while owning `gateway.json.lock`, verify no updater is running before removing that stale lock; the tool deliberately does not guess ownership.

The optional dependency is pinned in `requirements-gateway.txt`. The tested isolated packages were copied into `.runtime/model-gateway/dependencies` for ordinary native use and the pinned LiteLLM import was verified. No global Python packages were upgraded. The original test install under `.runtime/sage-gateway-20261001/dependencies` is preserved.

The existing shortcut's `../.runtime/desktop-native/application-profile.json` now has a `modelGateway` object containing absolute `configPath` and `dependencyRoot` paths. Both Python and Electron validate it. Only the owned application backend receives this profile binding; restricted managed profiles still strip gateway settings and credentials. No API key is stored in the profile. The renderer's storage partition, existing startup layout, backend/store IDs, shortcut and saved layouts are unchanged.

Close the ordinary application normally, reopen **InspectorPro Desktop**, and start a new Facility Layout planning conversation. An already-running backend is not switched in place. Existing generation sessions reject changed bindings rather than silently adopting Astra. The profile binding overrides conflicting inherited gateway environment variables.

Activation is backend-side and explicit:

```powershell
$env:INSPECTORPRO_LLM_GATEWAY_CONFIG = (Resolve-Path 'config/sage-gateway.json').Path
```

For non-profile activation, the backend must also be able to import the pinned dependency. Prepend the private dependency directory to the launching process's `PYTHONPATH`. Setting a variable in a terminal does not change an already running backend or an Explorer-launched shortcut. The normal native shortcut now obtains activation directly from its profile, without a persistent environment variable, `.env` change or shortcut update.

To retain the gateway but return to Claude, select `claude-baseline` with the command above and use a new planning session. To disable the gateway for the normal desktop, remove the profile's optional `modelGateway` field and any inherited `INSPECTORPRO_LLM_GATEWAY_CONFIG`, then restart normally. Pre-promotion profile and configuration backups are retained under `.runtime/sage-gateway-promotion-20261001/`. Restore the original configuration to continue a gateway-bound generation session; disabling or editing it deliberately rejects further commands on that session. Finish/Undo pending work and start a new planning session when switching. The entire configuration hash is bound, so changing even another deployment invalidates that run's configuration. There is no silent migration.

Keys remain in `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`, loaded only by backend processes. Do not put credentials into the JSON, prompts, browser pane or receipts.

## Verification And Known Limits

Evidence lives under `.runtime/sage-gateway-20261001/` and the separate `.runtime/sage-gateway-native-20261001-0N/` directories. Early failed attempts are retained, not overwritten.

- Actual Astra and Claude calls both passed forced tool invocation, call-ID-preserving tool results, and streamed follow-up checks. These are two-call protocol checks, not statistical performance benchmarks.
- The exact Haiku router snapshot passed. An initial rolling alias was rejected when the provider reported a different snapshot ID; the configuration now pins the observed snapshot explicitly.
- A fully specified, isolated reviewed fixture passed actual HTTP chat through Astra and the deterministic kernel: two placements, valid preview, unchanged saved base, no Save. The successful observed request took about 29.4 seconds. Earlier incomplete briefs did not pass.
- Closed finite requirement maps are lowered to equivalent explicit named-property schemas for OpenAI. Constraint branches remain in shared definitions; unsupported predicates, missing clauses and invalid values remain rejected. This changes the provider's schema presentation, not the deterministic validator.
- Manufacturer search returned actual Haas server-tool results and citations, still marked supporting/pending. Direct reading of the Haas page returned `url_not_accessible` and admitted no fact. Reading the public LiteLLM documentation succeeded with fetched-document provenance; that response had no extracted citation spans and is not evidence of a successful manufacturing-manual read.
- Native limited-information five-bench generation failed requirement satisfaction with both Astra (91.665 seconds) and Claude (328.569 seconds). All model calls and tool refusals remain in the traces. Neither reached Apply. Both recorded zero Save calls and confirmed owned-backend cleanup. These results do not isolate whether model behavior or provider schema translation dominates the failure.
- A separate, fully specified native case exposed a pre-provider routing defect: inactive Documentation context turned "manual assembly" into a Parts Manual command. The fix prevents generic document-type inference in Facility mode while preserving explicit Parts Manual requests. The unchanged prompt subsequently passed in native run `04`.
- The first broad regression run exposed obsolete tool allowlists in two routing test fixtures and an AST test tied to the former chat function body. Fixtures now include the already existing navigation/generation tools; the AST check follows the scoped implementation. No tool authorization was loosened to satisfy tests.

The gateway makes model transport and selection configurable. It does not by itself solve planning quality, research-source availability, manufacturing feasibility or interactive latency. It does not authorize Save. Owner-requested default promotion does not establish general demo readiness.

### Final Offline Results

- `final-regressions-2.log`: **460 passed, 1 skipped** across 19 files covering gateway, provider policy, HTTP chat/kernel integration, routing, generation, requirements, research policy, documents, revision control and recovery. Runtime 290.99 seconds.
- `final-followup-2.log`: **50 passed, 1 skipped** after the final scope/UTF-8 fixes, including the real generated requirement-schema equivalence check and Parts Manual, Operations Manual, Specification Sheet and Work Instructions routing. Runtime 7.69 seconds. This overlaps the first suite; do not add the counts.
- The skipped test is an explicitly opt-in paid provider case, executed separately during the live verification above. A Starlette/AnyIO deprecation warning remains.
- `tools/sage_gateway.py validate` passed against the project configuration. The final synchronous router transport also passed a live check (`router-final.log`).
- Vision/history conversion is covered offline; there is no new live image-understanding qualification. None of these counts represents a complete repository-wide suite.

### Native Run 04

Evidence directory: `.runtime/sage-gateway-native-20261001-04/`.

- Actual chat through the configured Astra deployment produced two real catalog workbenches in one department in the new, isolated 35 m by 25 m concept. No coordinates or operation recipe were injected by the harness. The external test prompt supplied the quantities, area allocation and gap.
- The generation request took **166.701 seconds**. Four provider calls were recorded (about 89.575, 2.575, 8.533 and 41.808 seconds), plus 7.234 seconds in tools. One call had 66,030 input tokens. These observations warrant cold-start/context investigation; they are not a p95 benchmark and are not acceptable interactive-demo latency.
- `01-plan.png` and `02-three.png` were visually inspected. Both benches render in 3D; load diagnostics report no degradation, pending loads or transform mismatches.
- Apply installed the exact candidate as a dirty draft. A new owned backend instance started and passed identity checks; document and history survived. Undo restored the original document, draft/base revision, selection, history and clean state.
- Both network and workflow counters recorded **zero Save calls**. Manual-layout and concept hashes were unchanged. Both backend instances have `terminationConfirmed`, `stdioClosed`, `resourcesClosed`, and no cleanup errors.
- The original native launcher could not decode one character in Electron's UTF-8 report using Windows CP1252, leaving `launcher.json` at `running` after exit. This diagnostic bug is fixed with explicit UTF-8 and cleanup checks. The original record is preserved; `launcher-reconciled.json` is a separately labelled re-read of saved evidence, not a fresh native run. The original Electron exit code was not persisted. An elevated `Get-Process` query returned no processes for the owned host and two backend IDs. A fresh paid native run solely to repeat this report-reader fix was not performed.

`verification-summary.json` under `.runtime/sage-gateway-20261001/` preserves all four outcomes and the original hashes. The final two original-layout checks matched:

| Layout | Unchanged SHA-256 |
| --- | --- |
| Manual reference | `a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088` |
| Factory 02 | `e8433641ed1c870b23aed9bd71c87c762a919f877c8d423aa25a27e3f7ceb9eb` |

### Next Qualification Gate

The earlier recommendation to withhold default promotion was superseded by the owner's explicit request, not by new broad planning evidence. Still reproduce the unchanged limited-information scenario with matched direct/gateway settings, inspect the requirement refusals, and fix general schema/semantic defects rather than adding a canned layout. Then qualify corrections and wider resource mixes, and measure latency with failures included. The native two-bench pass establishes a bounded execution path, not those broader claims.

## Owner-Requested Promotion Verification

October 1, 2026: configuration revision
`d62922d4cff1daf5778005e10b46e2472688a00c9ed84f3bb589279d525a3c78`.

- **Profile activation verified:** the existing native profile selects the project gateway configuration and stable private dependency directory. Optional profile fields preserve existing renderer partition and store identity; the profile wins over inherited model settings. Restricted managed mode remains isolated.
- **59 Python tests passed, one opt-in live test skipped, seven subtests passed.** These cover the gateway, HTTP integration, application profile and application boundary. Earlier missing `jsonschema` came from the test runner omitting the private dependency path and was resolved by using that path. Provider-specific fixtures now select their Claude baseline explicitly instead of depending on the user's configurable default.
- **28 focused Node tests passed.** The broader desktop suite recorded **662 passed, four failed** (including the parent test): `runtime-startup.test.cjs` has VM fixtures missing `_trainSetupFacilitySheets` and `_trainRenderFacilitySheets`. Those unrelated fixture failures were not repaired or hidden in this promotion. The retained log is `.runtime/sage-gateway-promotion-20261001/desktop-node-suite.log`. An earlier run lacked Python's app dependency path; rerunning with the correct path resolved its other failures.
- **Fresh native generation failed**, with evidence in `.runtime/sage-gateway-native-promotion-20261001-01/`. The verifier's `--desktop-profile` path copied only the installed gateway binding into an isolated application profile, rather than injecting a special test gateway environment. Five actual planner calls reported `gpt-6-astra` and the promoted configuration revision. All five calls succeeded at the transport layer.
- The unchanged two-workbench prompt finished in **76.217 seconds without a validated preview**. The requirement ledger contained two hard constraints without executable predicates: no interdepartment routes and no additional equipment. `generation_requirements_not_satisfied` correctly blocked the package. No Apply, 3D-candidate, restart or Undo success is claimed for this run.
- Workflow and network counters both recorded **zero Save calls**. Owned backend termination, closed streams and resource cleanup were confirmed. Electron exited and the UTF-8 launcher report finalized normally. Both original layout hashes still match the table above.

The normal user app was not force-restarted or closed. Reopening its existing shortcut activates this selection; use a new planning conversation. The remaining generation and performance work is independent of configuration promotion.

## Reproduce Checks

Paid calls require an explicit flag:

```powershell
python tools/check_sage_gateway.py --live --deployment astra-candidate --output .runtime/astra-check.json
python tools/check_sage_gateway.py --live --deployment claude-baseline --output .runtime/claude-check.json
```

The native verifier takes an external scenario, an unused port and a fresh project-local output directory. It copies the layout store, refuses a scenario authorizing Save, captures the real application/provider flow, and retains failure screenshots and shutdown evidence. On Windows launch it through `pythonw.exe tools/run_hidden.pyw` to avoid console flashes. Native GUI permissions may still be required. The verifier does not replace the normal shortcut.

## Acceptance

- Changing a stable role mapping selects a compatible model without editing application source.
- Ordinary and required tool calls, tool results, multimodal context, incomplete/refusal responses, and streaming preserve their meaning.
- Unsupported capabilities and invalid configurations fail before provider invocation.
- No model change mid-run, duplicated layout operation after retry, lost cancellation, or saved-layout mutation in non-Save cases.
- Actual provider/transport tests remain distinct from mocked tests and actual Electron acceptance.

## Sources

- [LiteLLM Responses API](https://docs.litellm.ai/docs/response_api)
- [LiteLLM Anthropic Messages API](https://docs.litellm.ai/docs/anthropic_unified)
- [OpenAI GPT-6 migration guidance](https://developers.openai.com/api/docs/guides/latest-model)

The configured API keys were checked for presence only. No credential values are included in this document.
