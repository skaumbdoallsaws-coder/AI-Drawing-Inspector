# Sage Local Equipment Evidence

Implementation checkpoint, September 24-25, 2026. This adds model-scoped document
retrieval to the existing research-to-layout path, not a manufacturing feasibility
evaluator or a new source of approved geometric constraints.

## Implemented

The equipment catalog query now reports whether a local document association is
registered, stale, unregistered, or unavailable. The new planning tool,
`read_generation_equipment_document`, supports:

1. `summary`: the existing five-question capability assessment for the selected
   equipment, its common basis, relevant source hazards, and exact document IDs.
2. `search`: bounded literal search of a registered manual, returning PDF file-page
   numbers, excerpts, continuation, and pages without extractable text.
3. `page`: bounded text from a one-based PDF file page, with a continuation offset.

The tool uses an explicit catalog identity and a nested `read` object containing
`action` plus its action-specific fields. Its root schema is a closed object;
action alternatives are nested because the configured provider rejects a root
`oneOf`. The underlying reader still accepts the flattened, validated request.

The generation prompt directs Sage to use the summary, then relevant manual
pages, then permitted public research for remaining consequential gaps. A user
can still explicitly request a known manual page; the reader does not force a
redundant summary call. Local reads do not call the internet and remain available
when new public research is denied. Existing unresolved source-use restrictions
are not weakened or silently resolved by this addition.

The six initial associations are catalog knowledge, not demo recipes: Haas
ST-30, Doosan DBC 130 II, ACER Dynamic 1760G, Nordson EFD E6, ABB IRB 6650, and
MMLE-50D. They reference nine existing PDFs. No layout coordinates, expected
candidate solutions, machine dimensions or resource quantities are added by the
reader. Unregistered equipment continues to have an explicit evidence gap.

## Binding And Authority

- The checked-in index binds exact catalog IDs and definition revisions to the
  existing assessment sections and document collection. Display-name matching
  cannot substitute another model. A catalog revision change requires reviewing
  the association, not silently accepting the old binding.
- Assessment text has a SHA-256 binding with normalized CRLF/LF line endings.
  The original verification manifest is byte-hash bound; each PDF is independently
  checked against its recorded byte hash before reading.
- Models supply document IDs, not arbitrary paths or URLs. Registered paths must
  resolve inside the project. Public browser sessions, cookies and desktop
  privileges are not involved.
- The original manufacturer/source-host descriptions remain distinct. Hosting
  a manufacturer brochure at a reseller does not make the reseller its author,
  and registration does not prove installed configuration.
- Every response carries configuration/edition scope and relevant reviewed
  source hazards. The Doosan bad pound conversion, optional-table differences,
  E6/sibling edition conflicts, MMLE sibling load-center and support ambiguity,
  ACER conflicting unit pair, and Nordson range notation remain visible.
- A family manual page remains readable even when it discusses sibling models.
  The reader does **not** automatically verify a table column or extract an
  engineering fact from it. Warnings are retained; numeric fact admission remains
  separate work.

All reads are supporting evidence with applicability review pending,
`productionEligible: false`, and `executableConstraints: false`. The reviewed
assessment is a screening reference, not an installed-machine approval.

## Bounds And Limitations

Uses the project's existing PyMuPDF dependency, loaded only when opening a PDF.
No vector store, browser automation, duplicate geometry engine or new draft owner
is introduced. Defaults: 32 MiB per document, 800 pages, 40 searched pages and six
matching pages per search response, 6,000 characters per page-text response.
The existing generation response-byte bound also applies.

Page reads and search hits expose up to 32 PDF-authored internal page links per
response, with bounded anchor labels, one-based file-page destinations and an
explicit truncation flag. External URLs, other-file links and launch actions are
excluded. These are navigation references, not evidence that their destinations
answer the question. No document-specific offsets are supplied. This matters
when printed table-of-contents numbers differ from file-page numbers.

Search is literal and paginated. No match is not a semantic absence finding.
Empty/scanned pages are explicitly reported; the ACER brochure does not become
"no specifications found" because it lacks a text layer. Table/figure structure
is not preserved by plain text, so visual review is explicitly still required.
Automatic OCR, visual table interpretation and arbitrary uploaded-document
registration are not implemented by this checkpoint.

## Retention And Planning

Successful reads produce immutable, principal/editor/base-bound artifacts in the
existing design repository. Identical reads return the same reference. Search
receipts and pages without text cannot stand in for a summary/page read when
preparing a context. Partial page text can be retained as bounded supporting
evidence; it is not relabeled as a complete manual.
The final continuation chunk remains truncated/incomplete when its text offset
is nonzero, even though it has no next chunk. Source cards preserve that label.

`propose_generation_context` accepts optional `localDocumentRefs`. These are
pinned alongside the source context and represented as
`local_equipment_document` evidence. They do not automatically become evidence
for every operation or equipment assignment. Existing brief-interpretation
provenance is preserved. The numeric-spacing admission check rejects these
receipts just as it rejects public research receipts as dimensional authority.

Local consultation has its own executable `local_document_consulted` predicate.
It binds the prepared context's `localConsultations.evidenceRef` to the exact
asset ID, definition revision and action (`summary` or `page`). Context inspection
exposes these receipts in a bounded `localDocuments` section. Both requirement
recording and candidate evaluation check the same receipt match. A summary
cannot satisfy a page-read predicate, another model/revision cannot substitute,
and a local read cannot impersonate a public `source_consulted` fetch. This proves
which evidence was consulted, not that a page contains an applicable fact.

Source-context revalidation checks current catalog association, index, summary,
manifest and referenced PDF hashes. Changed or missing inputs return a named
failure rather than falling back to a similarly named document. Retained text
remains in its artifact, but does not bypass this current-source check.

A copied document-reference mismatch returns the exact registered reference as
structured repair information. The tool still rejects that attempt; Sage must
issue a corrected request. A hash mismatch in actual file bytes does not return
that repair handle or silently accept the new contents. Recovery does not grant
permission to substitute a different requested edition.

Receipt-derived chat cards distinguish summary-only consultation from an actual
archived-page read, carry model/revision information, and disclose that the
original source URL may now serve different content. Cards do not infer publisher
identity or imply that clicking a current URL opens the retained byte revision.
Search hits do not generate a local "page read" card. Exact local-archive preview
links are separate work; the existing browser security policy is unchanged.

## Preflight Payload Reduction

The required context and research-policy calls now receive only their respective
schemas. Once preflight succeeds, the full planning toolkit is restored. This
changes neither permissions nor the available planning choices; failed-policy
recovery still returns to context inspection.

Measured UTF-8 schema sizes using compact, sorted-key JSON on this checkpoint:

| Tool set | Bytes |
| --- | ---: |
| Full toolkit, 11 tools | 58,901 |
| Context-only preflight | 960 |
| Policy-only preflight | 1,876 |

For the two mandatory preflight calls, schema payload falls from 117,802 to
2,836 bytes. System prompts, conversation, responses and subsequent planning
schemas are not included in that comparison. No end-to-end speed or p95 claim
follows from this measurement alone.

## Verification

- Evidence lives under `.runtime/`; runs below overlap and are not added together.
- `equipment-doc-navigation-01.xml`: 41 focused tests passed, including all six
  private assessment bindings, all nine hash-checked PDFs, local-link pagination,
  scanned pages, source mutation, scoped receipts and reference repair.
- `equipment-doc-full-05.xml`: 317 tests passed, including generation tests, local
  document tests, chat content and two opted-in Chromium cases. This predates
  the September 25 routing, local-consultation and recovery-context changes.
- `equipment-doc-full-06.xml`: final combined regression passed 329 tests,
  including both actual Chromium cases, with no skips. Two pre-existing
  websocket deprecation warnings remain. This run includes the final quote
  extension and partial-page fixes.
- `equipment-doc-routing-01.xml`: 37 routing/document-chat/documentation tests
  passed. A validated generation binding now keeps a manual-reading request in
  Facility Layout instead of switching to document authoring. Unbound document
  authoring remains unchanged. Client-supplied internal bindings remain stripped.
- `equipment-doc-consultation-03.xml`: 131 focused tests passed, including local
  consultation evaluation and contextual omission diagnostics. These include
  ordinary/streamed HTTP calls with a synthetic provider, not live-language proof.
- `equipment-doc-consultation-04.xml`: 133 passed after adding exact adjacent
  quote-extension options. These are bounded diagnostic suggestions, not automatic
  text changes or semantic approval; the original complete-coverage check remains.
- `equipment-doc-chunks-01.xml`: 46 reader/integration tests passed, including
  partial final chunks. Runs overlap; do not sum the counts.
- Actual ordinary and streamed HTTP chat tests use a synthetic provider with real
  readers, repositories and geometry kernels. They cover retained evidence and
  source cards, preview generation, unchanged saved state, and separate injected
  policy/reference failures followed by recovery. They are not live language tests.
- Generation-view tests: four passed. Rich-content checks: twelve passed,
  rerun after the final Python regression. The Node runner reports five cases
  because the twelve rich-content checks run inside one legacy test container;
  do not add the container count to its checks.
- `research-policy-narrow-live-03/*.json`: eight live policy probes passed, all
  in one provider call. Each sends 3,861-4,078 measured input tokens and takes
  3.699-5.578 seconds in this batch. Context is seeded, so these are not full-chat
  or submission-to-preview measurements and do not establish p95.
- `equipment-doc-live-05.xml` and `equipment-doc-live-05/*.json`: both live manual
  probes passed with the configured `claude-sonnet-4-5-20250929`, retaining the
  same six-call limit. Haas: summary, search, actual manual page 405 in three
  calls / 27.363 seconds. MMLE: summary, two searches, manual page 6 in four calls
  / 31.064 seconds. No web calls, browser interaction, generation, Apply or Save.
  Context/catalog are seeded; the model selects reads. This proves retrieval of
  the requested topics, not the accuracy of a complete engineering answer.
- `equipment-doc-live-06.xml`: both manual probes passed again with stricter
  content checks that distinguish body instructions from contents-page mentions.
  Haas: three calls / 31.391 s. MMLE: four calls / 27.712 s. Same six-call budget;
  no fixed page instructions or machine-specific routing were added.

### Actual Chat To Preview And Correction

`local-manual-layout-chat-05/report.json` passes two actual streamed HTTP turns
with the configured live provider and real private catalog. No synthetic provider,
seeded document receipt, supplied candidate coordinates or fixture solution is
used. The destination and repositories are isolated; this is not native Electron.

The initial prompt requests one Haas ST-30, one MMLE-50D, turning followed by
finished-part staging, local summaries and the G76 manual section, visible setup
unknowns, labelled provisional gaps, no internet, and preview only. It is unchanged
from failed runs 01-04. The second turn requests two lifts while preserving every
other requirement. Full exact messages and receipts are retained in the report.

| Check | Observed result |
| --- | --- |
| Initial preview | 3 zones, 2 placements, 1 route; 164.150 s |
| Quantity correction | 3 zones, 3 placements, 1 route; 46.681 s |
| Package comparison | Only `equip-lift.quantity` changes, 1 to 2 |
| Evidence | Both exact model summaries and Haas manual file page 405 retained |
| Process | One declared sequence checked; station transfers remain unvalidated |
| Recovery | One rejected incomplete-coverage attempt per turn, then successful explicit resubmission |
| Source cards | Both turn payloads match their trusted read receipts |
| Public research | Zero search or public-read attempts |
| Apply / Save | Neither invoked; zero Save calls; saved destination unchanged |

This is a technical integration pass, not a latency or broad-language gate. Both
times exceed the proposed small/medium product targets (90 s initial, 20 s
correction). Earlier failures remain part of the evidence, not discarded samples.
The model also describes pattern gaps as clearance "around" equipment. The grid
compiler spaces repeated placements; it does not validate an all-sided access
envelope. Receipt-based explanation fidelity therefore remains an open finding.

### Preserved Failures And Corrections

No failed evidence was overwritten or excluded to claim a success rate:

- Live batch 01 failed on the provider's unsupported root `oneOf`; the published
  contract was corrected to use nested action schemas.
- Batch 02 passed both manual probes and two policy probes, then failed when the
  model copied a layout revision into the policy revision field. Field guidance
  now distinguishes them; actual chat tests exercise context-refresh recovery.
- Batch 03 passed all eight policy probes, then rejected a copied manual hash
  typo. Exact reference repair was added without relaxing content checks.
- Batch 04 reached the six-call limit after confusing a printed contents number
  with a file page and repeatedly using over-specific literal phrases. Bounded
  PDF-authored navigation and explicit short-query guidance address that path;
  batch 05 passes without raising the budget or adding machine-specific routes.
- `equipment-doc-full-04.xml` records 314 passes and two failures in the newly
  added test assertions. Those assertions incorrectly expected provider-native
  tool-result messages; the application uses trusted JSON observation envelopes.
  The tests now parse the real envelope and check its exact repair details. No
  application error handling or success criteria were bypassed for this fix.
- `local-manual-layout-chat-01`: actual streamed HTTP chat misrouted a bound
  generation/manual request into Documentation and failed mandatory preflight.
  The bound-workflow routing guard fixes this without keyword exceptions.
- `local-manual-layout-chat-02`: actual chat read both summaries and Haas page
  405, but could not represent local consultation in the public-only predicate.
  It stopped incomplete after 403.378 s. The separate local predicate above
  closes this contract gap; no local receipt is relabeled as a web fetch.
- `local-manual-layout-chat-03`: local consultation was represented correctly,
  but the model repeatedly omitted a connector word between source quotes. It
  exhausted the unchanged round budget and stopped incomplete after 217.321 s.
  Omission diagnostics now include a bounded exact context and offsets, with
  guidance to extend the appropriate quote rather than match another occurrence.
  No coverage rule, accepted predicate or retry budget was weakened.
- `local-manual-layout-chat-04`: contextual diagnostics alone were insufficient.
  A malformed predicate was corrected, but repeated punctuation omissions still
  exhausted the round budget (286.069 s). The subsequent exact quote-extension
  options identify input requirement IDs and bounded, unambiguous source text.
  They require explicit model resubmission and revalidation; substantive clauses
  still need supported dispositions. Run 05 passed without increasing the budget.
- `equipment-doc-consultation-01.xml`: dependency import failed under restricted
  filesystem access. The authorized rerun (`02`) passed 101 tests. This was not
  treated as an implementation pass or repaired by bypassing access controls.

## Native Desktop Verification, September 25

Two normal-mode Electron runs used the same external prompts above, a separate
40 x 30 m concept, the real provider and catalog, and isolated facility stores.
No candidate coordinates, fabricated read receipts or fixture solutions were
supplied. The test runner now clicks the visible Planning, New concept,
confirmation, Create and open, New chat, Send and Apply unsaved controls. It fills
the actual input fields through DOM events. Fit, 3D and Undo use the application's
workspace/session methods; restart uses its owned-backend lifecycle. This is
native integration testing, not a claim that every step was manually clicked.

| Evidence | Result |
| --- | --- |
| `.runtime/equipment-doc-native-01/evidence/generation-check.json` | State checks passed; initial/correction 278.948/54.646 s. Some screenshots retained stale frames, so this run does not establish visual acceptance. Original evidence remains intact. |
| `.runtime/equipment-doc-native-02/generation-check.json` | Complete native rerun passed; initial/correction 216.403/62.145 s. Two zones, two then three placements, one route. |
| `independent-audit.json` in each run's evidence directory | Exact catalog counts, unique IDs, unchanged package except lift quantity, both summaries and G76 PDF file page 405, retained evidence references, zero public research and Save calls, exact Undo and unchanged saved hashes. |
| Native-02 `01-plan.png`, `02-three.png`, `03-applied.png` | Visually inspected: correct Plan, actual lathe and two lift meshes in 3D, then an unsaved applied draft. No blank canvas or overlapping panels observed at the captured desktop sizes. |
| Native-02 `last-application-run.json` | Backend PID 31824 replaced by 29824; final termination and resource cleanup confirmed. |

The capture correction is test-only: focus the window, await two renderer frames,
request repaint, and record bounds, image hashes and the represented preview.
Identical Plan/3D images now fail the visual checkpoint. This does not alter the
application renderer, Electron binary, security policy or timeout budgets.
[Electron repaint API](https://www.electronjs.org/docs/latest/api/web-contents#contentsinvalidate).

The independent audit initially required duplicate manual cards in the correction
response. That was an overly strict audit assumption: cards are emitted from
observed tool receipts, not necessarily duplicated when the model revises directly.
Both runs retain the three exact source references in both planning packages;
the original manual card remains in the conversation. Neither run emitted a
second copy of that card. The audit records this distinction explicitly.

The native test's explicit Apply is performed after the model finishes its
preview-only task, as a separate test-driver action. Sage did not Apply or Save.
Restart preserved the applied layout/history; Undo restored the original concept
document, draft/base revisions, selection, history and dirty state. Original and
copied manual layouts, and the concept's saved base, stayed unchanged.

Four generation-view and twelve rich-content JavaScript checks were rerun and
passed. No full Python rerun is claimed for these test-driver-only changes.
The native runs are two integration samples, not a latency campaign. Both exceed
the proposed 90 s generation/20 s correction targets. The existing gap-versus-
access-envelope explanation finding remains open. Source-link/PDF opening was
not retested in this offline-document scenario; numeric fact applicability and
station-level transfers remain outside its qualification.

## Remaining Product Work

Applicable structured fact admission still needs executable checks for model
column, configuration, edition, unit contradictions and numerical consumers.
Human-authored installed-configuration records and setup data remain necessary
where documentation cannot answer the question. This reader deliberately does
not fill those gaps by assumption.

Still open: broader research source/topic restrictions, durable whole-request
resumption, dirty-draft composition, complete explanation fidelity, held-out
conversations and end-to-end latency qualification. The bounded native reader
scenario above is now verified; it does not qualify arbitrary requests or every
research source, nor replace the separate explicit-Save acceptance.

No original PDFs, catalog records, saved layouts, Claude structure-tree code or
desktop browser privileges were changed. Native checks restart only their owned,
isolated backend; a previously running user backend needs a normal restart to
load the new reader.
The manual reference was independently rehashed on September 25: revision
`a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088`,
827 placements and 45 zones, unchanged.
