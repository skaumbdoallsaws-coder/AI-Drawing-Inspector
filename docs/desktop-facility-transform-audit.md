# Facility placement-transform audit follow-up

Updated: 2026-09-13. Transform finding closed by the successful native facility run; isolated facility checkpoint accepted. Complete desktop integration remains gated.

## Native closure

The ordinary native run `inspectorpro-facility-recovery-20260913-141702-926` passed both Electron phases. The [native run report](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-facility-recovery-20260913-141702-926/check.json) closes the isolated facility recovery and loaded-asset checkpoint, including the transform-audit finding.

- All 827 placements passed with zero transform mismatches; 9,418 instance matrices were audited with zero storage-format error. The `1e-5` tolerance is unchanged, and the 49 raw precision differences remain recorded.
- All 37 referenced GLBs were served and loaded. All 37 referenced library cards and thumbnails passed visibility/loading checks. Both saved screenshots were independently inspected during this follow-up; the full facility renders and the library capture shows populated cards and thumbnails. Per-card evidence covers entries outside the screenshot's current scroll position.
- Two manual edits followed by Close/Cancel, Close/Cancel during Apply and Undo, lost-acknowledgment recovery across two Electron processes, exact Undo restoration, and Close without Save passed. Save remained blocked before restoration and during unresolved recovery.
- Phase 1 recorded eight distinct transaction endpoints once each. Phase 2 retained those counts and added only the recovered Undo's two endpoints. Both phases recorded zero Save calls.
- Original and isolated saved-layout hashes remained unchanged. Both Electron worker exits and diagnostic-stream closure were confirmed; backend termination and its resource-cleanup receipt were verified. Electron descendant-process termination is not separately verified.

This follow-up inspected the saved reports and screenshots; it did not rerun native tests, regression suites, or the unchanged empty-window test. Only acceptance documentation changed. A minor encoding artifact is visible in the test-harness banner separators; it does not invalidate the scoped transform, asset, or recovery evidence.

The backend stayed running between Electron processes. Managed-backend restart, complete top-level desktop integration, other loaded workflows, live Sage in Electron, and ordinary unsaved-edit crash recovery outside the tested transaction boundaries remain unverified. General editing and embedded browsing remain gated.

## Finding

The 49 native mismatches are reproducible Float32 storage differences in the audit. The production renderer supplies a double-precision placement × prototype matrix to Three's `InstancedMesh.setMatrixAt`. The pinned Three 0.184.0 stores those values in a `Float32Array`; `getMatrixAt` returns the rounded values. The old audit compared this read-back against the unrounded double matrix with a fixed `1e-5` absolute tolerance.

Before changing the audit, an offline reproduction used the actual production adapter, pinned Three/GLTF loader, and the copied guard, rack, and pallet GLBs. It reproduced **exactly the same 49 placement IDs** as the native report: 21 guards, 24 racks, and four pallets. Every read-back element exactly equaled the Float32 encoding of the matrix actually supplied to `setMatrixAt`. There was no stored-transform drift in this reproduction. GPU rasterization and native UI were not exercised by this offline test.

Representative component comparisons, including the actual prototype and canonical transforms:

| Asset | Expected double component | Actual Float32 read-back | Actual − expected |
| --- | ---: | ---: | ---: |
| asset-5987t55-wire-mesh-machine-guard-panel | 263.506 | 263.506011962891 | 1.19628906531943e-05 |
| asset-pallet-rack | 280.416 | 280.415985107422 | -1.48925781218168e-05 |
| asset-pallet-1200x1000 | 268.714000016987 | 268.713989257812 | -1.07591748133018e-05 |

The pallet's source-to-canonical X offset is `0.49000001698732376`, which explains why checking placement translation alone predicts the wrong pallet IDs. Full matrix/prototype comparison is required.

Maximum raw rounding difference: `1.4892578121816769e-5`. The original evidence contains all 16 expected-double, expected-Float32, actual, and delta components for every mismatching matrix row.

## Change

- The absolute matrix tolerance remains **`1e-5`**. Object/quaternion tolerance remains `1e-6`.
- For an actual Float32 instance buffer, the audit compares read-back with the expected matrix encoded to Float32. It does not modify the renderer, placement coordinates, prototype transforms, instance buffers, or layout files.
- The audit now checks every prototype mesh in each instanced asset; previously it checked only the first mesh. An unreadable secondary mesh makes coverage incomplete.
- Nonfinite components cannot be converted to zero and treated as a match.
- `placementTransformAudit.matrixComparison` retains the raw double values, encoded expected values, actual values, deltas, maximum errors, comparison tolerance, and matrix count. JSON diagnostics explicitly retain invalid values such as `NaN`. It supplies one representative matrix per affected placement, prioritizes real mismatches, and caps returned samples at 128 with explicit truncation metadata.

The stored-matrix check establishes faithful storage of the intended transform. Raw quantization errors remain visible separately; storage agreement does not create extra floating-point precision.

## Verification

- **Eight real-Three tests passed.** They independently compose compound prototype/placement matrices and verify every stored element. Negative cases retain detection of a `0.001` translation error, one representable Float32 step at the tested coordinates, wrong rotation, wrong scale, drift in a nonfirst mesh, nonfinite values, and missing secondary-mesh coverage.
- **70 existing Three-adapter checks passed.**
- **Post-fix actual-GLB reproduction passed:** 638 placements across the three affected asset types; 3,172 matrices audited; zero storage-format mismatches; maximum stored-format delta zero.
- The post-fix evidence still identifies the same 49 raw precision-affected placements and 362 raw matrix differences, with all 49 representative matrix samples retained and none truncated.
- Independent read-only review found no new P1/P2 issue in the changed audit path.

The offline audit-fix verification above initially covered 638 placements. The subsequent accepted native run covers all 827 placements and the native facility checkpoint. No native, backend, or empty-window test was rerun during the audit fix or this documentation-only closure.

## Evidence

- Native run: `C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-facility-recovery-20260913-132133-349/check.json`
- Native asset evidence: `C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-facility-recovery-20260913-132133-349/phase-1/facility-asset-evidence.json`
- Original matrix reproduction: `C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/facility-instance-float32-repro-20260913.json`
- Corrected audit reproduction: `C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/facility-instance-float32-postfix-20260913.json`
- Reproduction script: `C:/Users/might/Documents/Codex/2026-09-12/hi/work/diagnose-facility-instance-matrices.cjs` (use `--post-fix` for the corrected-audit assertions).
- Existing regression log: `C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/facility-transform-audit-existing-tests.log`

Source, layout, pinned Three and GLB hashes are included in the reproduction evidence. Original native evidence is unchanged.

## Native regression launcher

The successful native run used the existing ordinary, unelevated launcher. Keep it for relevant regressions; an unchanged rerun is not required:

```powershell
& "C:\Users\might\Documents\Codex\2026-09-12\hi\outputs\check-inspectorpro-facility-recovery.ps1"
```

The corrected audit, facility/library captures, card/thumbnail checks, and two-Electron-process recovery all passed. Managed-backend restart remains separate because the backend stayed alive between those processes. Editing and embedded browsing remain disabled outside the explicitly authorized test harness. The launcher does not run the unchanged empty-window test.
