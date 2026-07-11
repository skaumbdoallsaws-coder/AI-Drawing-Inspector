# Agent Skills Phase 4 Tool Policy and Receipts Report

Date: 2026-07-10

## Scope

Phase 4 formalizes browser-executed UI actions and makes visible action claims depend on verified execution results. It does not add tools, change workflow routing, or add a second LLM response pass.

## Shared Action Contract

`static/contracts/ui-action-contract-v1.json` is the canonical policy for 21 existing UI actions. It defines:

- allowed workspaces and action types
- required and optional fields
- field types, ranges, enums, and item limits
- deterministic action IDs
- bundle size limits
- incompatible action pairs
- viewport domains each action must preserve

The server validates every `ui_actions` call against this contract before returning it to the browser. The browser validates the same payload again before dispatch. Unknown actions, unknown fields, invalid values, duplicate IDs, oversized bundles, and declared conflicts fail closed.

## Browser Receipts

Each accepted action is executed through the existing dispatcher. The browser captures compact state before and after dispatch and verifies the action's postcondition. A receipt contains:

- tool-call and action identity
- requested and applied arguments
- succeeded, failed, or rejected status
- before and after viewport state
- evidence references
- duration and timestamp
- a bounded error when execution or verification fails

Success requires both dispatcher success and a passing postcondition. The preservation canary rejects an action if an unrelated highlight, display, motion-control, or rotation domain changes. Crank angle is intentionally excluded from preservation comparison because it advances naturally during active playback.

## Execution Honesty

The same-turn assistant status is deterministic and receipt-grounded. A successful highlight-plus-motion bundle produces a status such as:

`Showing Pin bore affected motion group at 30 RPM. Related parts are highlighted in the assembly viewport.`

If no action succeeds, the response states that the viewport change was not applied. If a `ui_actions` bundle fails before action receipts can be emitted, affirmative model prose is replaced with a validation or execution failure. Legacy state-based confirmation remains only as a fallback for older non-receipt tool paths.

## Receipt Round Trip

The browser keeps a bounded page-session history and a separate pending queue. Pending receipts are included in the next request under `attachments.viewport.execution_receipts`. The server:

1. validates and bounds the receipt shape
2. renders a compact prior-turn receipt section for the main agent
3. exposes compact receipt facts to semantic routing and workflow state
4. treats live viewport state as authoritative over historical receipts

The browser acknowledges only receipt IDs included in a request that received a successful response. Failed requests leave receipts pending for retry. No second model call is used to rewrite the same-turn response.

## Live Defect Found

The first live receipt smoke exposed an asynchronous ordering defect. From the Report tab, `set_part_highlight` switched to Assembly and returned before the scene was ready. The highlight appeared later during `play_motion`, so the highlight receipt failed its own postcondition and the motion receipt detected an unrelated highlight change.

The dispatcher now waits for the Assembly scene and part mesh map before highlight or display operations. The repeated live smoke passed all checks with separate successful highlight and motion receipts.

## Verification

- Python policy and frozen regressions: 149/149
- Browser authorization and intent mapping: 115/115
- Browser receipt runtime: 8/8
- Inline application scripts: 4/4 syntax checks
- Phase 4 live receipt round trip: 9/9
- Existing FAI-to-motion live workflow: 32/32

The initial broader-workflow run was 31/32 because a read-only model answer omitted the numeric deviation. Investigation found that the deterministic grounding backstop only parsed rendered `[FAIL]` lines while production supplied `fai_characteristics` as JSON. The parser now handles both formats through one failed-row prefix builder, and a regression test reproduces the exact production call shape. After restart, the full live workflow passed 32/32.

## Operational State

The server reports Phase 4 with action contract version 1 and 21 registered UI actions. `INSPECTORPRO_SKILLS_ENABLED=0` and `INSPECTORPRO_SKILLS_SHADOW=1` remain the current posture. Production skill activation is still blocked on router latency optimization; Phase 4 does not change that decision.

Phase 4 exit gate is met: no receipt-capable action is presented as completed without a successful browser postcondition receipt.
