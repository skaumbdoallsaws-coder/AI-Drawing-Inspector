# Factory 02: CNC Operating-Side Correction

Subsequent addition: [perimeter walls](independent-factory-walls-20260928.md).
The CNC correction is preserved in that newer layout revision; this report
and its evidence describe the preceding checkpoint.

September 28, 2026. User screenshot review exposed a limitation in the earlier
Layer 2 check: looking toward a machine origin does not prove the operator is
standing on its operating side.

## Evidence And Correction

Four cardinal native Electron close-ups of the exact `asset-cnc-mill` GLB show
the loading opening and control pendant on canonical local -Z. The six machines
had identity orientation, while their operators stood on +Z, facing the rear.

Rotated only the six CNC mills 180 degrees about Y. Their fronts now face +Z,
toward their existing operators and the machining aisle. No translations,
operator poses, Haas orientations, zones, routes, markings or catalog records
changed. All other 824 placements are byte-equivalent in the layout document.

- Sheet: `fl-independent-factory-20260928` (Factory 02 - Integrated Production).
- Previous revision: `5d6e4bbf96076a6752abfab93d7d763c3a9e0be6962c9bbafac6f17082239517`.
- Saved revision: `4d3d7213064ee5a999e3b14e8771aff648e7dddf2b1d80515a33bb80cddabc7c`.
- Asset revision: `2c33d6899de6e048418bb848df6d36d96f2ac067cfb0b7aa5b0798efd5f90186`.
- Machines: `pl-independent-0677`, `0680`, `0683`, `0686`, `0689`, `0692`.

This operating-side inference is scoped to that exact model/revision. It is not
manufacturer-approved access, reach, clearance, ergonomics or process evidence.
The operators remain illustrative observer positions, not certified stations.
No general Sage planner capability or catalog authority is claimed.

## Verification

- 62 Python tests passed: 11 new CNC-side checks, 21 Layer 2 checks and 30
  operation-kernel checks. The new regression rejects the original rear-side
  arrangement even though its center-facing heading error is zero. It also
  checks transformed fronts, reversed operator headings and model/revision scope.
- Existing service validation: zero placement collisions, shell collisions,
  obstructed aisles or spatial errors. The existing 3,343 unverified findings
  remain; this is not operational qualification.
- All six CAD-side checks pass; the previous 40 operator heading checks,
  containment, markings, crossings and attachment checks remain satisfied.
- Native Electron before and after checks passed with nine captures each,
  including four cardinal CNC views and one oblique view. After captures were
  visually inspected; the loading opening/control side faces the operators.
- All 830 rendered placement transforms match; 7,420 stored instance matrices
  match. All six CNC instances use the real 33-mesh overview asset.
- Both native passes leave saved bytes unchanged. The original manual layout
  remains SHA-256 `a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088`.
  The default layout remains the original manual sheet.
- Both test backends have confirmed termination and closed resources. The
  after-check receipt records forced process termination after resource cleanup;
  it is not evidence of a wholly graceful shutdown.

## Reproduction

`tools/correct_independent_factory_cnc_side.py` uses ordinary operation-kernel
rotations and revision-bound service Save. It defaults to dry-run, refuses a
different base revision and refuses to overwrite an existing report directory.
The patch is saved offline; it does not add an Undo entry to an already-open
editor. `correction/before.json` retains the exact preceding document.

Evidence directory: `.runtime/independent-factory-cnc-side-20260928/`.
`before/` and `after/` contain native reports and screenshots. `dry-run/` and
`correction/` contain validation, operations and exact before/after documents.
The prior Layer 2 reports and images are preserved without relabeling them.

Existing desktop windows can still hold the previous revision in memory. Reload
from disk after resolving any unsaved edits; the review did not force-reload or
close the user's existing window. No provider requests were made.
