# Recovery checkpoint replacement on Windows

Updated: 2026-09-14. **All ten native Electron recovery cases passed; the isolated managed-backend recovery checkpoint is verified. The original EPERM cause remains unknown.** General editing and embedded browsing remain gated.

See the [native acceptance and status follow-up](desktop-managed-backend-recovery.md) and [ten-case native evidence](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-managed-recovery-20260913-222008-375/native-matrix.json). No replacement errors or retries occurred in that run; the previous failed checkpoint remains unchanged.

## Saved native failure

The ordinary unelevated matrix `inspectorpro-managed-recovery-20260913-165650-573` passed `apply-success`, then stopped in `undo-success` before backend restart. Undo prepare had already returned HTTP 200 and the durable backend was `undo_pending` / `undo_unacknowledged`. Replacing the `undo-prepare-received` checkpoint failed at `fs.rename` with `EPERM`, errno `-4048`. Local Undo installation, the held acknowledgment, and restart had not happened. No Undo acknowledgment or duplicate preparation was sent. Eight cases were not started.

The stack points to the recovery-store implementation; the replacement target is the isolated runtime journal under `work/inspectorpro-desktop/.runtime/desktop-spike/managed-native-20260913-165650-573-undo-success/desktop-recovery/`.

The previous valid checkpoint remains unchanged:

- Checkpoint: `69ba3826-b815-463b-9ea5-b996f413e8a2`.
- State: `pending`, phase `undo-prepare-pending`.
- Request: `fl-layout-mu0cwxml-0002`; transaction: `fdlt-4cfbad99f6dd465aa5e0eca512e5b49d`.
- Size: 2,682,629 bytes; SHA-256: `526a8ad8eba7ab405e418a14b26143cb527bc13ef01758c14c3ea8396aac1384`.
- Exact selected zone and three history batches/cursor remain: manual edit 1, manual edit 2, Apply.

The retained checkpoint and durable transaction must be reconciled before retrying any transaction operation. The original failed-run directory was inspected read-only and was not used for new test writes.

Current file attributes are not read-only, and inherited ACLs grant the user FullControl. These observations do not establish the launch-time failure cause. No process owning a conflicting handle was identified; no antivirus, sync-service, GPU, or permission cause is claimed.

## Controlled Windows reproduction

A separate helper opened a fresh disposable checkpoint using actual `CreateFileW`, allowing read/write sharing while omitting `FILE_SHARE_DELETE`. Windows requires delete sharing for subsequent rename/delete access; this is a documented mechanism that can block replacement. [Microsoft CreateFileW reference](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew).

With the original store and real Windows `fs.rename`, both controlled cases reproduced `EPERM` and preserved the prior checkpoint. This demonstrates a possible sharing-lock mechanism, not the cause of the original native failure.

| Controlled case after change | Actual result |
| --- | --- |
| Lock released after 150 ms | Four real rename attempts; replacement acknowledged after success, approximately 234 ms including helper cleanup |
| Lock retained until write settles | Six real rename attempts; bounded EPERM failure, approximately 832 ms including cleanup; no acknowledgment; previous bytes and checkpoint ID unchanged |

Each attempt used the same already-flushed, closed temporary file and candidate checkpoint. No acknowledgment preceded replacement. Helper handle release, process exit, and output-stream closure were verified. The reproduction uses installed Node v24.11.1 on Windows, not an Electron renderer.

## Write-path change

- On Windows, only replacement failures `EPERM`, `EACCES`, and `EBUSY` are retry candidates. There are at most five additional attempts, delayed 20/50/100/200/400 ms, within a 1,000 ms scheduling window. Filesystem-operation latency is not claimed to have a hard deadline.
- The previous target is never unlinked as a workaround. Exact previous bytes are checked before each replacement attempt. A changed, missing, oversized, or unreadable target stops replacement instead of granting overwrite permission.
- The same durable temporary file/checkpoint is reused. No network transaction, Apply, Undo, Save, or lease request is retried by this code. The write queue remains serialized until the operation succeeds or fails.
- Permanent failures retain the original error code and give no durability acknowledgment. Cleanup only attempts removal of this operation's uncommitted temporary file. If cleanup itself fails, diagnostics report the retained temporary file.
- Existing single-main-process ownership remains required. Exact-byte rechecks are not a cross-process atomic compare-and-swap protocol.

## Diagnostics retained by the native harness

An optional diagnostic observer receives replacement attempts, error code/errno, stage, process/platform, candidate/prior checkpoint IDs and SHA-256 values, and the observed target state. It contains no draft payload or record contents. Observer exceptions or rejected promises cannot change the write result.

The managed engine and Electron main process write these events incrementally to `recovery-store-diagnostics.jsonl` and the parent-captured worker stream. This retains detail even when Electron's renderer IPC error drops custom error fields. A clean write produces no retry log.

Final diagnostics distinguish a preserved previous checkpoint, an unreadable/missing/changed target, and a candidate observed after replacement without a durability acknowledgment. For example, a post-rename directory-sync failure is not falsely reported as preserving the prior bytes. Windows keeps the existing `file-sync-atomic-replace` guarantee; no directory-flush claim was added.

## Verification and scope

- **130 Node tests passed**, including 14 new replacement tests and existing store, facility session/adapter, managed recovery, and lifecycle checks.
- The tests cover transient Windows errors, persistent failures, immediate nonretryable errors, exact target changes/deletion, queue ordering, diagnostic observer failures/redaction, unreadable targets, and post-rename sync failure.
- **All ten real-backend engine matrix cases passed again** after the store change. Both pending Apply and pending Undo were exercised across success, failed startup, identity mismatch, expired lease, and another writer's ownership. Every endpoint executed once; zero Save calls; original and isolated saved-layout hashes unchanged; owned worker/backend cleanup and unrelated-server survival verified.
- Python production/runner code was unchanged; Python unit suites were not repeated. No unchanged empty-window or asset-rendering check was run.
- Independent review found no new P1/P2 in the bounded retry, prior-checkpoint preservation, candidate reuse, queue, or acknowledgment path.

The original native cause is still unknown. The subsequent native matrix passed pending Apply, pending Undo and all eight fault cases. Native evidence, independently audited, now verifies this isolated recovery checkpoint; the controlled Node/engine results alone did not establish that pass.

## Evidence and retained launcher

- [Original native matrix](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-managed-recovery-20260913-165650-573/native-matrix.json) and [Undo failure report](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-managed-recovery-20260913-165650-573/undo-success/report.json).
- [Controlled pre-change lock evidence](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/checkpoint-windows-sharing-before.json) and [post-change lock evidence](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/checkpoint-windows-sharing-after.json).
- [Fresh ten-case engine matrix](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/checkpoint-replacement-engine-matrix-20260913-220818/matrix.json).
- [Node regression log](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/checkpoint-replacement-node-tests.log).
- Diagnostic scripts: `C:/Users/might/Documents/Codex/2026-09-12/hi/work/diagnose-checkpoint-windows-sharing.cjs` and `work/hold-checkpoint-sharing-lock.py`.

The existing native launcher remains available for future recovery changes. No unchanged full-matrix rerun is required for this status follow-up. It uses the snapshot and fresh isolated data for each selected case:

```powershell
& "C:\Users\might\Documents\Codex\2026-09-12\hi\outputs\check-inspectorpro-managed-recovery.ps1"
```

If replacement still fails, inspect the new checkpoint diagnostics alongside `worker.log`; keep the previous valid checkpoint and avoid replaying the operation. A subsequent process/file-access trace may be needed to identify the actual lock or access condition. No security setting, ACL, original layout, or failed-run checkpoint was changed.
