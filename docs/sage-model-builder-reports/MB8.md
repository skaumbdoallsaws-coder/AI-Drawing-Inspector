# MB8 - Verification and evaluation (Claude, 2026-11-17)

Final commit verified: 1ff9763 (MB0 through MB7 on branch sage-model-builder, worktree only). Plan section 8 MB8:
- the suites against the MB0 baseline;
- E1-E3 (section 9);
- up to two fix rounds;
- then, with the user's OK, the port.
This report covers everything that can run without the user. It stops before the port.

## Suites against the MB0 baseline

- Wide suite: the codex, facility, authored, sage and industrial files, 20 pieces, run outside the sandbox on a
  detached checkout.
  - Result: 3,856 passed, 178 failed, 9 errors, 68 skipped. The failure set is exactly the baseline's: no new
    failures.
  - Passed went from 3,848 to 3,856: the 8 measure_facility_gap tests (MB5c).
  - The same held after MB5a, MB5c and MB5b.
- Outside that set, run one file at a time:
  - all 51 model_builder, model_import and agent_chat files pass;
  - 9 memory files fail, with the same 32 failures at e949f41 (before MB5b changed memory/policy.py) as at
    1ff9763: missing fixture and registry files in the test checkouts, not this work.
- Node: chat attachments 29/29, transport 31/31.
- Browser, isolated real app, outside the sandbox, no provider call:
  - tools/verify_model_builder_browser.py: 14/14 checks (MB7);
  - tools/verify_model_import_chat_browser.py: 11/11 checks (the model-only flow still works after MB7's
    shared-chip changes).

## E1 parity (deterministic, no Sage)

- tests/test_model_builder_cookbook_recipes.py (30 tests) holds the parity numbers:
  - Baler and pack station: bounds within 1 cm of the hand-built originals, the same part names, triangles within
    25 %.
  - Gaylord body: names, and bounds within the C42 rule; the pallet is scored against its own spec.
  - Carrier tag: size and centring equal to the hand-placed pair, its top 15 mm under the rail (within 1 cm).
- Side by side with the originals (same renderer; model-builder-night/out/e1, not in the repo): the baler and pack
  station look the same view for view.
- Two cookbook fixes came out of this: gaylord cartons up to the rim (0393b5f), and the cage tag at the hand-placed
  height (410773f).
- In the real 3D view (MB7 verifier screenshots) the printed text reads forward on the floor sign, the cabinet
  (both lines) and the eyewash (PUSH and the sign). A part finish on a non-print part leaves the prints alone.

## E2 / E3 (live Sage): not run

- They need Sage signed in on this code: either after the port (the user's OK) or on an isolated server with its
  own test sign-in.
- Tier 5 also needs the user's two photos and an OK to download one public spec-sheet page.
- The run sheet: model-builder-night/E2-E3-run-sheet.md. It has 24 E2 runs and 2 E3 runs, the exact prompts from the
  frozen items.json, the setups, what to record and the blind rating steps.
- Fix rounds (up to two) follow the E2 results. None has run yet.

## Fixes made in review during MB5-MB7 (all committed with tests)

- MB5a:
  - the room-check exception moved to the edit instructions;
  - the playbook's 10 steps restored;
  - turn_budget_low names the turn's draft;
  - a failed turn reports only the registrations that completed;
  - cookbook categories exist on a clean site.
- MB5c: rotated floor markings were measured mirrored by the gap tool (it now uses the app's own marking shape).
- MB5b: phone photos were refused (the stored page was over 4 MB), and pages over 1.5 MB could not be shown to Sage.
  Both are fixed and tested with a phone-sized photo. The sweep also drops stale page-choice files.
- MB7 verifier: it tolerates an evicted response body, and allows exactly the two deliberate refusal console lines.

## Waiting on the user

1. The port into the real repo: backup branch, desktop restart (graceful), check the ?v= versions.
2. Where E2/E3 run, plus the tier-5 photos and the spec-sheet download OK.
3. Decision 6, the PyMuPDF licence. PDF reading stays off by default, and PDFs are refused with "attach a screenshot
   of the page".
4. Whether every site gets a fixed set of builder categories (today Sage uses only the site's existing ones).
