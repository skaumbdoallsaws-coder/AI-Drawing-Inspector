# Research-to-layout draft integration

Date: September 23, 2026. This is an implementation/evidence record, not broad
manufacturing qualification or demo promotion.

## Implemented

- `generation_destination.py` creates a separate empty concept with explicit
  user-confirmed dimensions. It never replaces the selected layout or changes
  the default layout. A scoped request key makes retries idempotent. Its floor
  carries `conceptual_floor_requires_site_review`; repository publication makes
  the concept usable by the geometry engine, not surveyed/site-approved data.
- `generation_draft.py` adapts one exact, current preview to the existing FDL
  transaction protocol. It does not introduce another draft manager. The
  compatibility `briefRevision` contains the generation ledger revision; the
  artifact explicitly records `origin: generation_preview` and grants no travel
  optimization claim. Candidate, evaluation, source and recovery references are
  pinned. Existing permanent pins are retained; a new GC policy is not claimed.
- Selection, prepare, commit and Save revalidate generation source/catalog/base
  bindings. `agent_write`, `design_loop_apply` and generation preview permissions
  are required before selection/lease access. Model tools still cannot Apply or
  Save. The user selects Apply unsaved; the existing Save action is separate.
- The shared editor operation allowlist now includes the existing kernel's
  `rename_layout`, `set_plan_settings` and `add_route` operations. No selection or
  history algorithm was replaced. Claude's structure-tree accessor is preserved.
- Generation planning offers New concept and Apply unsaved. Apply is above the
  notes. Corrections render current predicate values; unrevalidated initial
  assumptions are retained under a historical heading, not asserted as current.
  Destination retries retain their request key across view recreation; a new
  saved base gets a new key. A late response cannot navigate after an intervening
  edit/Undo, even if the document revision has returned to its original value.
- Small contexts return a bounded compact projection with exact prior package
  and active requirement IDs/predicates. Oversized contexts explicitly require
  pagination. This is an optimization, not a measured latency qualification.
- A fetched research result cannot be cited as a numeric `authoredSpacing` fact.
  Authorized provisional geometric gaps must use the brief interpretation and
  remain assumptions. A requirement for a documented operating limit stays
  unresolved until an applicable fact/validator exists. General web guidance is
  not equipment configuration approval.
- Source cards distinguish search discovery, a confirmed document read and an
  unconfirmed read. A successful exact-URL read upgrades the earlier search card;
  later search results cannot downgrade it. This is retrieval status, not source
  quality, applicability or approval. Truncation is disclosed separately.

## Verification

| Evidence | Result and boundary |
| --- | --- |
| `.runtime/gen-finish-full-01.xml` | 248 focused Python tests passed before the final spacing-attribution guard. |
| `.runtime/gen-finish-attribution-01.xml` | 37 targeted tests passed with that guard, including preservation of the earlier valid preview after refusal. |
| `.runtime/gen-finish-browser-04.xml` | Two actual Chromium cases passed with the real workspace/backend. Apply matched the preview; Undo restored the original document/revision/history. One case lost an Undo acknowledgment after server acceptance and recovered after page reload, with Save blocked while unresolved. Synthetic source/geometry, not a live provider or Electron qualification. |
| Session/transport checks | 60 session checks and 29 transport checks passed. |
| Desktop regressions | Managed recovery, desktop session and recovery adapter checks passed; 11 application-link/CLI checks passed. These are separate from a native run. |
| `.runtime/gen-finish-full-03.xml` | Final admission/agent/revision/requirements/flow/exploration/draft/chat regression: 248 passed, including the spacing guard. The preceding `full-02` collection failed because the local jsonschema dependency path was omitted; no implementation tests ran in that attempt. |
| `.runtime/gen-finish-browser-05.xml` | Two Chromium cases rerun successfully after moving Apply and formatting assumptions. |
| Final Node rerun | 89 runner cases passed (including the session and transport script containers, which report 60 and 29 checks respectively). Four additional generation-view cases passed for destination retry/navigation protection. Do not add the container counts twice. |
| `.runtime/gen-finish-final-01.xml` | 52 chat-content/exploration/draft tests passed after the final retrieval-status presentation change. That presentation change and the destination navigation guard were not recaptured in Electron. |
| `.runtime/gen-finish-full-04.xml` | Final combined regression after all backend changes: 249 passed in 149.20 s. |

Explicit Save was exercised in an isolated backend test and subsequently the
native Save case below. The backend test refuses without approval, then permits
one persistence call for the selected candidate. The saved revision
includes the normal Save timestamp; it must not be confused with the unsaved
candidate revision.

## Native runs

The new explicit `--generation-acceptance-output` flag runs
`desktop/tools/application-generation-check.cjs` only in normal application mode.
It requires the existing isolated-copy preparation receipt and an external
`scenario.json`. Scenario prompts are test inputs, never production recipes.
Other diagnostic modes are mutually exclusive. Ordinary startup is unchanged.

- `.runtime/generation-native-01`: actual chat research, initial generation
  (274.164 s), correction (51.080 s), Plan and real GLBs passed. Apply verification
  failed because the test driver did not scroll its target into view. The failure
  is preserved. Background Python regression tests also ran during this probe;
  its timing is not a controlled performance benchmark. Backend cleanup confirmed.
- The same run exposed a source-attribution defect: a numeric assumed gap cited
  general guidance that supplied no numeric clearance. The new guard addresses
  that contract, without claiming source applicability is solved generally.
- `.runtime/generation-native-02`: two real previews (268.292/53.235 s), followed
  by a failed source-card click check. Backend cleanup confirmed.
- `.runtime/generation-native-03`: two real previews (229.475/45.576 s), followed
  by a false negative in the click-delivery assertion. The preload intentionally
  intercepts links during document capture and stops propagation; a listener on
  the target cannot witness that click. The test now observes window capture,
  without changing application link handling. A subsequent isolated input-only
  diagnostic (`generation-input-01`) opened the research pane successfully.
- `.runtime/generation-native-04`: **passed the complete native integration**.
  Live initial generation took 239.074 s and correction took 48.167 s. Five actual
  catalog workbenches became four, retaining four departments and three routes.
  A native source-card click loaded ErgoPlus in the research pane. Plan and real
  GLBs rendered without degradation. Native Apply installed the exact candidate
  as an unsaved draft. Restart preserved layout/history, and Undo restored the
  original document, revisions, selection, history and dirty state. Zero Save
  calls occurred; both the concept's saved base and manual-layout hashes stayed
  unchanged. Screenshot paths are `evidence/00-source-browser.png`, `01-plan.png`,
  `02-three.png` and `03-applied.png`; they were visually inspected.
  `last-application-run.json` independently confirms two backend instances/PIDs
  (42100 then 3984), startup in 6.102/11.921 s, and confirmed final cleanup.
  The test now also asserts the restart instance change directly in future runs.
- `.runtime/generation-native-save-01`: **passed the separate explicit Save case**.
  A supplied cable-harness brief on a 32 x 24 m conceptual floor describes parallel
  wire/connector preparation joining final assembly, then visual inspection and
  packing. The model generated five real catalog workbenches, six departments
  and six routes in 162.221 s, without supplied candidate coordinates. Apply and
  backend restart passed; a native click on the ordinary ribbon Save persisted
  exactly once. Reload returned the exact saved document/revision. Only the new
  concept changed; original and copied manual layouts stayed unchanged.
  Saved revision: `18ea5108dfd3803ea9ec6d19d083dc4201c7dfbaffc01c61f1ebdfee4979f12d`.
  Backend PIDs changed from 32524 to 27480, with confirmed cleanup. The saved
  screenshot `evidence/04-saved-reloaded.png` was inspected. This run includes the
  latest destination guard and explicit restart-instance assertion; it contains
  no web research, so does not recapture the final source-card read-status labels.

These probes used external prompt inputs, not fixture coordinates or hidden
product recipes. They are not a latency campaign: background regression tests
ran during some probes. Source quality remains limited: native-04 read a reseller
guide and explicitly called it a reseller, not manufacturer documentation. Its
prose still loosely attributed a provisional gap to general guidance. The exact
stored spacing and UI remain assumptions, not an admitted numeric source fact.
Native integration success must not be promoted to primary-source or complete
explanation-fidelity acceptance.

Arbitrary dirty-draft generation adoption, general machine-fact admission,
durable provider resumption, a frozen held-out conversation campaign
and product latency promotion are not established by these tests. The generation
base remains a clean, empty layout. The general demo-readiness gate remains open.

## Using the implemented path

After restarting the desktop app to load this code, open Facility Layout's
Generation planning pane. From the clean manual layout, use New concept, supply
dimensions and explicitly confirm they are conceptual. This opens a separate
empty layout; it does not copy or overwrite the manual facility. Leave Start
from your brief selected, ask Sage for a layout, and review the candidate and
disclosed unknowns. Request corrections before Apply unsaved. Ordinary Undo
restores the prior editor state. Save remains an independent user action.
