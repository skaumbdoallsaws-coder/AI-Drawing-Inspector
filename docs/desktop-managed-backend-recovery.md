# Managed-backend facility recovery checkpoint

Updated: 2026-09-14. Scope: explicitly authorized isolated facility harness. **All ten native Electron cases passed; the isolated managed-backend recovery checkpoint is verified.** General editing and embedded browsing remain disabled.

## Latest status recapture

**The Apply and Undo status-bar follow-up is closed.** The ordinary unelevated Undo recapture `20260914-164703-058` passed all five recovery checks; the screenshot was inspected and shows `Unsaved changes | 1 selected | Plan view | select` without the stale interruption error. Exact draft, selection and Undo restoration, one durable read-only lookup, once-only transaction endpoints, zero Save calls, process cleanup and both backend resource receipts were verified. Source/isolated saved layouts and the earlier failed checkpoint remain unchanged.

Backend startup took 13.479 s and 18.706 s. All nine spatial jobs completed; the longest execution was 430.037 ms. The earlier intermittent timeout causes remain unresolved. Retain their diagnostics as reliability follow-ups; this successful recapture does not establish a performance fix or rewrite the previous failures.

[Native result](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-managed-recovery-20260914-164703-058/undo-success/check.json), [inspected screenshot](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-managed-recovery-20260914-164703-058/undo-success/managed-recovery.png), and [independent evidence audit](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-managed-recovery-20260914-164703-058-independent-audit.json). The earlier ten-case managed recovery acceptance stands. General editing and embedded browsing remain gated. No application code, tests or native checks were run or changed during this documentation review.

## Native acceptance and status follow-up — 2026-09-14

**The isolated managed-backend recovery checkpoint is verified.** The ordinary unelevated [native Electron matrix](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-managed-recovery-20260913-222008-375/native-matrix.json) passed all ten cases. A separate [read-only audit](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-managed-recovery-20260913-222008-375-independent-audit.json) verified all 50 checks against retained checkpoints, transaction registries, identity evidence and resource receipts. It recomputed exact draft, selection and history hashes and confirmed the permitted proposal-metadata transitions.

Across the ten isolated cases, 38 transaction endpoint executions occurred, each endpoint once; zero Save calls. Six usable restarted backends performed one durable read-only lookup each. The four unavailable or mismatched backends received no authenticated lookup. All eight injected faults retained pending state/recovery handles and kept Save blocked. Ten workers and all owned backends terminated, including the two injected pre-import failures; 16 application resource-cleanup receipts were verified. Unrelated and mismatched fixture servers survived recovery. The source layout, all isolated saved layouts and the previous failed checkpoint remain unchanged. No checkpoint replacement errors or retries were logged. The original EPERM cause remains unknown.

The successful native captures retained the old interruption error in the bottom status bar. The follow-up clears the session error only after all verified-reconciliation guards pass, and removes the workspace's cached copy only when it is the same previous session error. A newer workspace error survives. Failed or stale reconciliation retains the interruption. This changes feedback, not ownership, transaction execution, editing authorization or Save gates.

The follow-up passed **76 Node recovery/session tests and 85 workspace checks**, including same-process Apply/Undo recovery, rejected reconciliation, visible status text, and preservation of a newer workspace error. These were the original code and DOM-fixture checks; the subsequent native Apply and Undo captures now verify both corrected status bars, as recorded above. The unchanged ten-case native matrix was not repeated. General editing and embedded browsing remain gated.

The audit also retained unrelated missing Documentation-fixture and Chromium cache-index log messages. This checkpoint does not claim those workflows or cache behavior are accepted.

## Historical native replacement follow-up

The ordinary native run `inspectorpro-managed-recovery-20260913-165650-573` passed pending Apply, then stopped before Undo restart on a recovery-checkpoint replacement EPERM. Its previous valid checkpoint remains unchanged. A controlled Windows sharing lock reproduces that API error, but the original cause has not been identified. Bounded atomic-replacement retries and main-process diagnostics are implemented; 130 Node tests, real Windows lock checks, and a fresh ten-case real-backend engine matrix pass. See [checkpoint replacement investigation and evidence](desktop-recovery-checkpoint-replacement.md). The subsequent native matrix passed all ten cases, as recorded above. Editing and browsing remain gated.

## What is verified

The real facility session remained alive while its owned Python backend stopped and restarted. The same saved manual layout was copied into fresh isolated stores for each case. Real operation-kernel proposals, design transactions, leases, journals, and recovery files were used. Provider-generated planning was not involved.

| Restart condition | Pending Apply | Pending Undo | Required result |
| --- | --- | --- | --- |
| Successful restart | Passed | Passed | Same origin/backend/store/principal/document/owner; new process ID and instance ID; one durable lookup; verified adoption |
| Failed startup | Passed | Passed | Explicit recovery required; exact pending draft/history and handle retained; Save blocked |
| Identity mismatch | Passed | Passed | Reject public identity before private lookup; retain draft/handle; no credential sent to mismatched server |
| Lease expired | Passed | Passed | Durable lookup returns `lease_expired`; retain recovery; no lease renewal or write authority |
| Another writer owns lease | Passed | Passed | Actual repository acquisition by another writer; lookup returns `ownership_conflict`; no takeover or write authority |

All ten cases recorded zero Save calls and each transaction endpoint executed once. Read-only reconciliation did not change endpoint counts. The original and every isolated saved-layout SHA-256 remained:

`a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088`

Six cases relaunched the real application backend. Each retained its logical identities and origin, changed process/instance IDs, and performed exactly one read-only lookup from that new instance before adoption or reporting an ownership conflict. The failed-start and identity-mismatch cases performed no private transaction lookup.

## Exact state and authority checks

- The two manual edits, selected zone, draft/base layouts and revisions, complete command batches/cursor, generated-draft fields, editor generation, recent receipts, and journal hash remain exact through restart. Successful Undo returns the complete original two-edit manual frame.
- Successful reconciliation may only change verified proposal bookkeeping: Apply adopts `active` and the transaction revision returned by authoritative lookup; Undo clears the matching active proposal. No other editor-frame field is normalized or ignored. The evidence retains pending, expected-after, and actual-after hashes.
- Cancel before restart preserves the exact draft, selection, journal, and pending transaction identity. A pending operation keeps Save blocked. Preparation may retain the startup recovery gate because the actual session prohibits clearing it while a transaction is unresolved.
- Save is checked through the actual session before restart, before runtime verification, immediately before durable lookup, and after the outcome. The native driver additionally checks the visible Save control; that UI assertion passed in the native matrix above.
- Lease expiry and takeover produce explicit recovery-required states with retained handles and no write authority. This slice does not implement automatic renewal, takeover, or completion of a user's ownership-resolution procedure.
- Repeated/concurrent controller restart calls share one operation. The supervisor accepts one correlated control request and owns only its original process handles. It never terminates a server discovered by port or executable name.

## Real interruption and fault boundaries

Success, failed-start, and identity-mismatch cases hold the client acknowledgment after the backend has completed it, then discard that reply and reconcile durable state. Lease-conflict cases hold immediately before acknowledgment dispatch, after Apply commit or Undo prepare and local frame installation. This leaves a live lease that can actually expire; an already released Undo lease is not mislabeled as expired.

Expiry uses a persisted, harness-only clock offset beyond the actual lease deadlines. Takeover uses the real lease repository to acquire ownership as a different manual writer. It is not a separately running competing editor. Failed startup is an owned child that flushes diagnostics then exits 73 before application import. Identity mismatch uses a separately owned fixture server on the original origin; it receives one public identity probe and no credential/private lookup. All fault controls require the explicit managed-harness environment flag and authenticated fixture routes.

These are controlled owned-backend restart cases at defined transaction boundaries. They do not establish arbitrary crash, disk-failure, power-loss, or production multiwriter acceptance.

## Process cleanup and isolation

All ten worker exits and diagnostic-stream EOF/closure were confirmed. Sixteen actual application shutdown/resource-cleanup receipts were verified. The two deliberate pre-import failures correctly have no application cleanup receipt; their exit and stream closure are separately verified.

Ten unrelated fixture servers and two same-origin mismatched fixture servers survived the recovery operation with zero credential requests and no termination request from recovery. Their later teardown was explicit fixture cleanup, separate from the backend supervisor. Descendant-process termination is not separately claimed.

Privileged Node and Python HTTP requests reject redirects. The native driver also blocks renderer backend requests during restart and leaves them blocked on failed reconciliation. Chromium sandboxing, context isolation, and the absence of renderer Node access remain required for the native pass. Ordinary desktop main/preload and all general workflow capabilities are unchanged.

## Earlier implementation verification

- 103 Node tests passed, including 39 new managed-controller cases and existing facility/session/lifecycle coverage.
- 78 Python tests executed: 77 passed; one symlink-capability test skipped. Includes 12 new backend and 17 new supervisor tests plus existing facility fixture/backend/runner coverage.
- All ten engine cases passed with actual stopped/restarted backend processes and real on-disk repositories.
- Independent read-only review cross-checked reports against durable request registries, layout bytes, runtime identities, cleanup receipts, and sentinel evidence; no new scoped blocker was found.
- Native worker JavaScript and the PowerShell launcher passed syntax/parser checks. Those checks do not establish a native pass.

The earlier failed engine attempt exposed an overbroad full-frame assertion during legitimate proposal-metadata adoption. The corrected checks retain every draft/history field and validate only the authoritative metadata transition. An initial matrix launcher preflight used an already-created output folder and stopped before backend startup; the unused fixtures were then run with fresh output paths. Failed-attempt evidence remains retained.

## Evidence

[Combined engine evidence](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-managed-backend-recovery-evidence.json)

- [apply-success](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/managed-recovery-engine-apply-success-v2/check.json)
- [apply-failed-restart](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/managed-recovery-engine-failures-20260913-145000/apply-failed-restart/check.json)
- [apply-identity-mismatch](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/managed-recovery-engine-failures-20260913-145000/apply-identity-mismatch/check.json)
- [apply-lease-expired](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/managed-recovery-engine-failures-20260913-145000/apply-lease-expired/check.json)
- [apply-other-writer](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/managed-recovery-engine-failures-20260913-145000/apply-other-writer/check.json)
- [undo-success](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/managed-recovery-engine-undo-success-v2/check.json)
- [undo-failed-restart](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/managed-recovery-engine-failures-20260913-145000/undo-failed-restart/check.json)
- [undo-identity-mismatch](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/managed-recovery-engine-failures-20260913-145000/undo-identity-mismatch/check.json)
- [undo-lease-expired](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/managed-recovery-engine-failures-20260913-145000/undo-lease-expired/check.json)
- [undo-other-writer](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/managed-recovery-engine-failures-20260913-145000/undo-other-writer/check.json)

[Node regression log](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/managed-recovery-node-tests.log) and [Python regression log](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/managed-recovery-python-tests.log).

## Historical ten-case native launcher

This launcher was used for the already accepted ten-case matrix. The UI follow-up is now closed; no unchanged recapture is requested. The full-matrix command is retained for reference:

```powershell
& "C:\Users\might\Documents\Codex\2026-09-12\hi\outputs\check-inspectorpro-managed-recovery.ps1"
```

It executes the ten cases sequentially using a fresh isolated copy per case, retains the same actual renderer through each backend restart, and captures the final recovery state. It checks visible Save blocking and native isolation. A recovery-required outcome in an injected failure case is a pass only when all preservation/authority assertions pass. Any failed native case stops the matrix with diagnostics retained. `-Cases` selects a subset; a subset is not full ten-case acceptance.

This launcher does not repeat the accepted empty-window or all-asset visual audits. After it passes, inspect the new screenshots before closing the native managed-recovery gate. Complete top-level InspectorPro integration, the other workflows, live Sage in Electron, the application-wide backend access boundary, and embedded browsing remain separate gates.
