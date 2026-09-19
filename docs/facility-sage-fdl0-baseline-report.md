# Facility Sage Persistent Design Loop - FDL0 Baseline

Status: **COMPLETE**

Baseline manifest:
`tests/fixtures/facility_layout/design_loop/fdl0-baseline-manifest-v1.json`

## Frozen Result

- The reviewed synthetic fixture canonicalizes to layout revision
  `f6a5a20d38884a92b2fa36a8244ab721e43abd2c35d30c8e95f398a071e1ea6e`.
- Its baseline route is exactly `60 m`; at 24 reviewed loaded trips per Day
  Shift, the weighted baseline is exactly `1,440 m/shift`.
- Three reviewed candidates improve route distance through distinct permitted
  edits. Their operation-plan hashes and exact expected metrics live in the
  fixture, not in model-authored output.
- Locking Main Boulevard removes a real route candidate. Locking Output Buffer
  A removes the buffer-relocation candidate and leaves the reviewed direct
  Material Transfer Aisle candidate.
- Shadrack approved the artifact only as synthetic deterministic test gold.
  The receipt grants no capacity, safety, compliance, timing, manufacturing,
  or production authority.

## Existing Behavior

The replayed pre-FDL Facility chat router does not preserve the design objective
through the six-turn conversation. It classifies turns 2 and 6 as unrelated and
routes turns 4 and 5 into a commit mode with no callable commit tool. This is a
deterministic routing capture; no provider response was fabricated.

## Test Baseline

The first adjacent Python run produced 497 passes and one fixture failure. The
planner followed the renderer's established arrow convention correctly; the
NAV3 fixture had labelled 270-degree arrows as forward on a +X route. The fixture
was corrected to 90 degrees and its full 26-test module now passes.

The FDL contract suite passes 17/17. Existing browser-side contracts pass
50/50 session, 75/75 workspace, and 25/25 transport checks. The ordinary
generation, operation, routing, navigation, Process Map, memory, service, host,
and agent contracts remain the implementation substrate.

## Manual Reference

`fl-reference-manual-20260812` remains byte-identical at revision
`a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088`:
45 zones, 8 routes, 827 placements, and 50 floor markings. It contains zero
persisted process bindings and no reviewed transfer-frequency evidence, so FDL0
does not infer either one.

No production FDL feature flag is enabled.
