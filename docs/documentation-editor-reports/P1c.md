# Documentation editor P1c report

## P1c-1

Builder handoff, 2026-11-10. This diff is uncommitted and has not passed the
supervisor gate. P1c-2 and P1c-3 are not implemented. Read the limitations below
before treating this as complete coverage of arbitrary legacy input.

### CHANGED

- Added ai_inspector/documentation/identity.py: deterministic source-relation
  addresses, compiler alias catalogues, pure legacy log/snapshot migration,
  read-only identity orphans, deletion tombstones, and renderer projections.
  Generated IDs use document kind, compiler block/source keys, row/item relation
  keys and declared column roles. Neither displayed text, current array offset,
  source revision nor page placement participates in their identity hash.
  Fingerprints contain values for migration auditing; they do not allocate IDs.
- Updated the four compilers and operations flow/content declarations. Parts is
  version 6; operations, specification and work instructions are version 3.
  Work-instruction plan remains version 2. Existing definition-keyed part fields
  and slot: addresses remain intact. Tables keep scalar cells plus parallel
  cellIds/columnIds; rows carry rowId, items itemId, blocks stableId. Legacy
  blockId remains the renderer/DOM alias.
- DocumentationSceneRepository is version 4. It owns migrations, identities,
  orphans, stable overrides, history before/after paths, field versions and
  receipts in documentation-scene.json. SlotStore is version 3 to retain its
  existing keyed identities and deleted-slot tombstones in slots.json. There is
  no edit.json envelope and no generatedBaseline implementation in this round.
- Updated targets.py, provenance.py, commands.py and changes.py so reads, hashes,
  provenance scopes, change records and named inverses use stable addresses.
  Updated server.py and codex_runtime/documentation_tools.py to provide the
  compiler baseline to the owner and expose aliasRevision/aliasMap in reads.
  Tool names and public input schemas did not change; inventory pins did not
  need schema updates.
- Updated operations exports to prefer stable identityOverrides with the legacy
  alias fallback. Disposable composition views project stable overrides back to
  the renderer's aliases. Stable keys are kept out of figure composition inputs.
  Work-instruction legacy capture projection strips additive identity metadata.
  Operations plan hashing strips new sourceKey/columnKeys declarations, retaining
  the existing plan binding.
- Added tests/test_documentation_refresh.py and the sanitized
  tests/fixtures/documentation_editor/scene-v3-positional.json. Adjusted version
  and provenance expectations in test_documentation_transactions.py,
  test_documentation_provenance.py, test_documentation_change_undo.py,
  test_parts_manual.py and test_work_instruction_workflow.py. The smoke driver
  changes only its scene-version assertion to 4. Its existing
  data-documentation-edit-target lookups remain legacy aliases, including table
  and list positions; no static JS/HTML changed and no cache URL bump is needed.
- tools/documentation_baseline.py now binds the compiled identity catalogue
  before its parts edit and synthetic table edit. Its table adapter still checks
  the original block's displayed result. No baseline expectation JSON was edited.

### Identity and migration details

Compiler-owned literal rows/items have opaque declaration keys checked into the
compiler beside the declaration. These keys were allocated once during this
implementation; runtime code never derives them from enumeration or wording.
Moving or revising a declaration keeps its key. Blank log rows and multiple
controls sharing a claim have different declaration keys. For dynamic sources,
part definitions, approved section/stage/operation IDs, claim IDs and slot keys
supply the source relation. Explicit sourceKey + relationId distinguishes two
uses of one source and survives their reordering. Repeated indistinguishable
source relations are unresolved; there is no occurrence-number tie breaker.

Aliases carry targetId, sourceBinding, fingerprint and safe/legacyAmbiguous
flags. The catalogue is bounded, reproducible compiler data, not a permission or
read-token cache. Server builders explicitly supply their current baseline to
DocumentationSceneRepository.read. A legacy positional command maps only with a
matching source and plan binding, available baseline and unambiguous row/item
fingerprint. A changed/missing/ambiguous binding quarantines the whole log entry
and its snapshots as an orphan; replay skips it and named undo returns
undo_conflict. The orphan retains the original command and source binding.
Specification positional migration is also refused when native stored slot
changes mean source/plan revisions cannot prove the old row layout.

Scene versions 1, 2 and 3 upgrade purely in memory. The first explicit write
preserves exact original bytes beside the file: documentation-scene.v2.json for
old scene 1/2, documentation-scene.v3.json for scene 3; slots.v1.json or
slots.v2.json for the respective old slot shape. Open/read/export paths do not
save. Stable changes retain their original storage page, and a disposable join
places the override on its current page. A later edit to a relocated field uses
that original storage address so pre-existing named inverse snapshots remain
valid. A relocated arrange operation refuses a stale binding instead of moving
an override to a guessed page.

P1b-3 snapshots, fieldMeta keys and generated-value addresses migrate together.
Legacy confirmation hashes retain a recorded address translation. Migrated
receipt records expose stable changedIds, while an exact old request retry still
returns its original receipt. Quarantined changes are not undoable. Authored
object IDs are kept, not regenerated; deletion retains them as tombstones and a
new add cannot recycle a known ID. Columns, cells, rows, items and blocks are
included in the generated identity registry. Slot IDs retain their established
naming/finalization behavior and deletion state is inferred from retained rows,
values and journal records.

Bound Sage writes resolve old aliases through the read's captured target ID.
The host rejects an aliasRevision mismatch before applying the edit. Workspace
legacy writes retain their exact scene revision check, now including the alias
revision. Thus an old positional alias is not reinterpreted after reorder.
Learning a compiler catalogue alone can change the projected scene revision;
the owner allows its exact pre-identity revision only for non-page-element,
non-selection actions whose targets cannot be retargeted by that alias change.
The existing source/plan and content-hash checks still apply.

DocumentationSceneRepository.rebaseline and the general regeneration callers'
rebaseline behavior are unchanged. rebind_manual_plan is unchanged. No refresh
service, conflict resolution tools, conflict UI or P1c browser phase was added.

### TESTS

Executed only static checks, with no application imports:

- Python ast.parse accepted all 25 changed/new Python files (exit 0), through
  pythonw.exe and tools/run_hidden.pyw with a hidden parent process. Reparsed the
  three files changed during final review successfully.
- git diff --check passed. LF/CR scanning, server.py UTF-8 BOM preservation,
  ASCII-only server additions, and untouched baseline expectation paths were
  checked. The new sanitized JSON fixture parsed successfully.

No pytest tests, application server, document exports, baseline collector or
browser smoke ran in this sandbox. No package installation or network access
was attempted. No git history/index mutation was performed.

Authored coverage includes reorder following identity, duplicate-source refusal,
explicit relation disambiguation, schema 1/2/3 pure reads and original-byte
backups, read-bound alias refusal, stable regeneration/restart IDs, repeated
compilation, source/plan mismatch orphans, anonymous-item refusal, deleted row
and column tombstones, slot v2 migration/deletion, authored object tombstones,
pre-migration named undo/redo, receipt retry, page relocation and column reorder.
The real-compiler migration test is parameterized across all four documents.
Parts never had positional BOM targets: that case verifies an invented
bom.r0.c1 override becomes an orphan and definition-keyed fields remain intact,
rather than inventing a historical mapping that never existed.

### NOT RUN

Claude must review the diff, run these outside this sandbox, inspect failures,
re-record/promote baselines after review, run the isolated real-browser smokes,
and commit this round before P1c-2 starts. No runtime pass counts are claimed.

Focused tests, including every changed documentation test and collector/smoke
contracts:

~~~text
python -m pytest -q tests/test_documentation_refresh.py tests/test_documentation_transactions.py tests/test_documentation_provenance.py tests/test_documentation_change_undo.py tests/test_parts_manual.py tests/test_work_instruction_workflow.py tests/test_documentation_baseline.py tests/test_documentation_editor_smoke.py
python tools/documentation_baseline.py --check
python tools/documentation_baseline.py --local --check
python tests/smoke_documentation_editor.py --phase P1a
python tests/smoke_documentation_editor.py --phase P1b
~~~

Full documentation suites, with Python glob expansion so Windows does not pass
literal wildcard filenames to pytest:

~~~text
python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_documentation*.py','tests/test_parts_manual*.py','tests/test_operations_manual*.py','tests/test_specification_sheet*.py','tests/test_work_instruction*.py','tests/test_inspection_sheet*.py') for p in glob.glob(pattern)})))"
python -m pytest -q tests/test_codex_readonly_pilot.py tests/test_codex_assisted_tools.py tests/test_codex_documentation_tools.py tests/test_codex_specification_sheet_tools.py tests/test_codex_mcp_schema_types.py
~~~

Wider suites:

~~~text
python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_codex*.py','tests/test_facility*.py','tests/test_authored*.py','tests/test_sage*.py','tests/test_industrial*.py') for p in glob.glob(pattern)})))"
~~~

Compare against the committed P1b gate. The known pre-existing documentation
failure is
 test_operations_manual_precoding_contracts.py::test_source_ids_references_and_local_hashes_are_closed.
It is not a waiver for any additional failure.

### Expected baseline changes

Expected to move: document versions (parts 6; other generated documents 3),
scene 4 and slots 3, document/scene/store hashes, stable provenance target IDs,
field metadata addresses, alias maps/revisions, identity registries and their
serialization fingerprints, including edited/reopened facts and synthetic table
scene storage. Existing before/after export facts remain assertions.

Expected unchanged: visible page text, page count and geometry, table/list
ordering and dimensions, PDF/Word text, CAD figure geometry and persisted
work-instruction capture compatibility. The raw synthetic table's editedBlock
fingerprint is intended to remain unchanged. Identity/provenance projection
hashes are not export-layout evidence. These expectations have not been measured
here; Claude must distinguish intentional metadata changes from any text,
geometry, provenance or capture regression before promotion. Baseline JSON
files under docs/documentation-editor-reports/baseline were not modified.

### DEVIATIONS

- Slot schema advances to 3 in this round for a deletion registry, even though
  existing slot addresses already are stable. Later P1c rounds must add keys to
  this version, not bump it again.
- Some external work-instruction benchmark actions are anonymous strings. They
  have no action/source-relation key from which a distinct deterministic ID can
  be derived without text or position. They retain their displayed text but
  receive an unresolved audit-group identity and are excluded from editable
  targets; their legacy positional overrides become orphans. Keyed action
  objects with actionId are accepted additively. The external evidence packages
  were not rewritten. This is a coverage limit, not proof that those anonymous
  items have distinct persistent editable IDs.
- A single logical row/paragraph split across layout fragments is likewise
  withheld when a full-value replacement would have to choose a fragment.
  Logical source identity is retained; distinct editable fragment identities
  are not invented from pagination. Repeated identical legacy fingerprints also
  remain ambiguous even if new compiler declarations now have distinct keys.
- Parts' real-compiler positional migration test checks conservative orphaning,
  because its historical BOM targets already were definition-keyed.

### OPEN QUESTIONS

- Supervisor gate: confirm that anonymous benchmark actions and split logical
  fragments should remain unaddressable until their source producer supplies
  action IDs / a logical-value layout operation. If distinct editable IDs for
  all such legacy instances are a P1c-1 requirement, that coverage remains open;
  it cannot be established by assigning current offsets or matching text.
- Claude's runtime/baseline/browser gates remain open. No P1c-2 work should start
  until this round is reviewed and committed.


## P1c-1 round 2

Builder handoff, 2026-11-10. This section supersedes round 1's anonymous-item /
split-fragment limitation and its reliance on the process catalogue cache.
P1c-2 has not started. No versions were bumped again and no commit was made.

### CHANGED

- ai_inspector/documentation/identity.py now captures compiler source relations
  before provenance removes active claim/source IDs. Generated ID annotations,
  provenance and authored scene objects do not become catalogue inputs. Native
  collection cell roles are captured once instead of expanding when projection
  adds metadata. Recompilation uses these generated-source relations, not the
  projected evidence state. catalog_from(document) returns the catalogue
  directly. The bounded cache remains diagnostic only; there are no production
  calls to catalog_for.
- ai_inspector/parts_manual/documentation.py accepts identity_document explicitly
  on command, batch, inspect, named undo, history undo/redo, rebaseline and plan
  rebind paths. Each internal read, including the response read and nested undo,
  receives that same document. Catalogues are checked against document kind,
  assembly, source and plan binding. A read without a document uses only the
  file's state, never a process cache. The round 1 pre-identity-revision exception
  was removed: apply_command again requires an exact scene revision.
- server.py supplies the current compiled document for every affected mutation,
  including confirmation and Sage batches/inverses. Parts section moves compile
  the previous plan before moving and provide that exact previous catalogue to
  rebind_manual_plan. Native SlotStore writes already use an explicit current
  snapshot and binding and have no catalogue-cache dependency; their observed
  alias binding is now checked at the route boundary too.
- Anonymous generated children and split logical values get revision-scoped IDs.
  The identity registry records scope=revision, parentId, ordinal and
  sourceBinding. The ID includes the binding. Anonymous items use the ordinal
  within their keyed logical parent, continuing across layout blocks. Split
  paragraphs/containers and split rows use their logical source parent and
  fragment ordinal. Source-keyed children of split containers remain keyed to
  the logical parent, so pagination does not change those children. Genuine
  duplicate keyed relations without a distinguishing relation ID remain
  unresolved. Both unresolved aliases and their IDs are excluded from
  editableTargets, and the owner rejects an unresolved stable ID explicitly.
- ai_inspector/documentation/provenance.py and the independent capture oracle in
  tests/test_work_instruction_workflow.py exclude the new identity annotations
  from historical work-instruction capture inputs. No renderer text, geometry,
  static JS/HTML, tool input schema or cache URL changed in this round.
- tools/documentation_baseline.py passes explicit documents for its direct
  owning-store edits, rereads and undo/redo. Expected baseline JSON was not
  edited. Additional identity scope/source metadata and resulting hashes are
  expected to move; export text and geometry must still remain unchanged.
- tests/test_documentation_refresh.py now exercises all four real compilers
  through isolated MMLE workspace GET routes. It checks compile(compile(x)),
  compile(bind(x)), and the actual provenance/artifact-projected document against
  the first raw generated catalogue. New route tests clear or evict the cache
  between GET and POST, forbid cache reads, and clear it again immediately before
  the owner mutation. They check successful alias-to-stable-ID editing, including
  anonymous work-instruction actions, and named undo. Other added coverage checks
  action pre-image hashes/batches, plan rebinding, split paragraph/table-row
  editing, cross-binding ID changes and unresolved editable-target filtering.

The 13 failing tests listed in Claude's review were not changed. One other test,
 test_legacy_override_marked_edited in test_documentation_provenance.py, now
passes its compiler baseline explicitly to read/apply_command instead of relying
on a prior compile populating the cache. Round 1 identity tests were adjusted for
the same explicit contract and the supervisor's revised anonymous-item rule.
The work-instruction test change only extends its independent legacy metadata
stripping oracle.

### Supervisor decision carried forward to P1c-2

Anonymous values and layout fragments remain editable in their current source
and plan binding through ordinary hashes, provenance and named undo. They are
not automatically carried to another binding by ordinal. P1c-2 refresh must
match the same keyed parent and ordinal AND require the old generated value to
exactly equal the new generated value. If that exact value check fails, retain
the edit as a conflict or orphan for user review. No fuzzy text matching or
positional-only carry is authorized. This round records identity scope and makes
cross-binding IDs different; it does not implement refresh or its conflict rule.

### MMLE identity inventory

The new real-compiler inventory test prints one MMLE_IDENTITY_COUNTS JSON line
per document with sourceKeyed, revisionScoped and unresolved totals, separately
for unique generated registry identities and aliases. It asserts zero unresolved
for every MMLE document and exactly 20 revision-scoped anonymous action aliases
in work instructions. It also checks every advertised alias is writable.

These counts have NOT been measured in this sandbox. The requested numerical
inventory remains a supervisor-run result; the prior alias counts below are
Claude's supplied measurements, not counts claimed for this revision. Alias
counts must not be reported as unique identity counts (columns and logical
parents also have identities; some aliases share one identity).

| MMLE document | Claude's prior alias measurement | Round 2 source-keyed identities | Round 2 revision-scoped identities | Round 2 unresolved identities |
| --- | --- | --- | --- | --- |
| Parts | Not supplied | NOT RUN | NOT RUN | Expected 0; NOT RUN |
| Operations | 474 aliases, 0 unresolved | NOT RUN | NOT RUN | Expected 0; NOT RUN |
| Specification | 28 aliases, 0 unresolved | NOT RUN | NOT RUN | Expected 0; NOT RUN |
| Work instructions | 335 aliases, 20 unresolved actions | NOT RUN | Includes the 20 action targets; total NOT RUN | Expected 0; NOT RUN |

### TESTS

- Python ast.parse succeeded on all 25 changed/new Python files from this
  worktree; the eight Python files edited in round 2 were reparsed successfully
  after the final test additions. No application imports were used.
- git diff --check passed. Static searches found no production calls to
  catalog_for. LF, the server.py UTF-8 BOM, ASCII-only server additions and the
  untouched baseline expectation directory were verified.
- Python execution used pythonw.exe plus tools/run_hidden.pyw with a hidden
  parent process. No pytest, app server, browser, export or baseline run was
  attempted. The earlier 15 failed / 210 passed result belongs to Claude's
  review of round 1, not validation of round 2.

### NOT RUN

Claude must run the following outside this sandbox. The first command prints
all four requested identity/alias inventories; retain its four JSON lines in the
supervisor gate report. No runtime pass counts are claimed here.

~~~text
python -m pytest -q -s tests/test_documentation_refresh.py -k real_compiler_catalog_idempotence_and_mmle_inventory
python -m pytest -q tests/test_documentation_refresh.py tests/test_documentation_provenance.py tests/test_documentation_change_undo.py tests/test_documentation_transactions.py tests/test_parts_manual.py tests/test_work_instruction_workflow.py tests/test_documentation_baseline.py tests/test_documentation_editor_smoke.py
python tools/documentation_baseline.py --check
python tools/documentation_baseline.py --local --check
python tests/smoke_documentation_editor.py --phase P1a
python tests/smoke_documentation_editor.py --phase P1b
python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_documentation*.py','tests/test_parts_manual*.py','tests/test_operations_manual*.py','tests/test_specification_sheet*.py','tests/test_work_instruction*.py','tests/test_inspection_sheet*.py') for p in glob.glob(pattern)})))"
python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_codex*.py','tests/test_facility*.py','tests/test_authored*.py','tests/test_sage*.py','tests/test_industrial*.py') for p in glob.glob(pattern)})))"
~~~

The known pre-existing documentation failure remains
 test_operations_manual_precoding_contracts.py::test_source_ids_references_and_local_hashes_are_closed.
Review/re-record/promote both baselines only after the revision-conflict and
identity gates pass; no expectation JSON was updated by the builder.

### DEVIATIONS

- The supervisor explicitly authorizes binding-scoped ordinals for anonymous
  children and layout fragments. This replaces round 1's uneditable audit-group
  behavior. Duplicate keyed sources still require distinct relation keys.
- The requested actual MMLE counts cannot be supplied without running the real
  compilers and their dependencies. Runtime execution remains reserved to Claude
  under the phase rules. The diagnostic test and exact command above produce the
  inventory without accessing the user's stores; all mutable roots are isolated.
- No other scope deviation. Versions remain parts 6, operations/specification/
  work instructions 3, scene 4, slots 3 and work-instruction plan 2. No refresh
  service, generatedBaseline, new conflict commands, conflict UI or P1c smoke.

### OPEN QUESTIONS

No identity-policy decision remains open. Runtime proof that the 13 original
regressions pass unchanged, the four numerical MMLE inventories, both reviewed
baselines and the isolated browser gates remain pending Claude's execution.


## P1c-1 round 3

Builder handoff, 2026-11-10. Uncommitted; P1c-2 has not started. This section
supersedes round 2's use of the displayed document as the mutation catalogue.

### CHANGED

- ai_inspector/documentation/identity.py: bind_document now returns the projected,
  alias-keyed scene and leaves documentationComposition, documentationObjects
  and renderRequest.composition to the owner. sync_identity_overrides indexes
  the final owner-applied composition without changing it. There are no copied
  cover or specification policies in the shared identity module.
- ai_inspector/operations_manual/document.py and
  ai_inspector/work_instructions/document.py apply their existing _apply_scene
  after address projection. Cover occurrence/manual-group transforms remain
  removed; work instructions retain their existing figure-composition filter.
  Their earlier helper call supplies theme/page-master defaults only.
- ai_inspector/parts_manual/document.py moves its existing page-application loop
  into an owner-local _apply_scene helper and invokes it after address projection.
  Parts figure revisions are still calculated by the parts compiler. Early
  definition-keyed part text and callout processing are retained.
- ai_inspector/specification_sheet/document.py projects the scene against its
  scene-free baseline before _apply_scene / _legacy_text_values. Legacy text
  conversion also recognizes the generated block and table-cell slot aliases.
  It consumes those text overrides once, before slot data and displayed blocks
  are built. The final stable override index is synchronized from that cleaned
  composition, so a consumed viewport value cannot shadow a later slot value in
  either the viewport or Sage's reads. Routes supply their existing baseline;
  standalone compiler calls can obtain a scene-free baseline themselves.
- server.py carries the generated baseline alongside the compiled display
  document as a request-local dict-subclass attribute. It is not a JSON field,
  store, global cache, or replacement generatedBaseline feature. All four
  builders retain the same baseline they pass to repository.read. Command,
  history, batch, named inverse, inspect and confirmation paths retrieve that
  exact baseline for the owner, whose internal response reads already propagate
  the explicit argument. Parts' outer artifact attachment preserves the private
  handoff. Sage snapshot aliasRevision now comes from the read's baseline.
  Native slot writes still rebuild the baseline for their new stored slot state.
- aliasRevision still includes the fingerprints. Its calculation and the
  source/plan/hash checks were not weakened. Parts plan rebinding still receives
  its explicitly compiled previous plan.
- tests/test_documentation_refresh.py adds the real-route sequence for every
  MMLE document: edit, edit a second target using the returned revision, compare
  GET revision, undo, edit again, compare GET revision. It also checks the
  snapshot uses the scene-free baseline, that the private baseline is absent
  from JSON, that binding leaves owner compositions untouched, and that the real
  work-instruction compiler preserves cover policy.
- tests/test_specification_sheet_workflow.py adds viewport-title edit followed
  by a native slot write, parameterized for the workspace endpoint and Sage's
  typed two-slot batch. It checks both compositions and identityOverrides have
  no stale title text, block/slot/Sage reads show the new value, and the real PDF
  contains the new title rather than the old viewport title.
- tests/test_operations_manual_workspace.py updates its two direct generated-
  document repository tests to use the operations owner and pass the baseline
  explicitly to read/apply_command. The invalid positional alias assertion now
  checks the round-2 ambiguous_legacy_target code. The assembled-cover regression
  test is unchanged. The requested documentation/parts/operations/specification/
  work-instruction/inspection test families were searched for the same pattern;
  the other positional mutation fixtures already pass explicit baselines.
  Low-level authored-object/CAD/store-only tests retain their direct contracts.
- tools/documentation_baseline.py passes identity_document=before to the final
  parts rebaseline call. No expected*.json was edited.

Kept Claude's approved-plan copy/absent-plan skip in mmle_client and the stable-
cell-ID, column-order assertions in test_user_confirmation_removes_active_citation.
The known precoding-contract failure was not changed. No static JS/HTML, public
Sage input schemas, document/store versions or inventory pins changed.

### TESTS

Builder execution was static only:

- Python ast.parse passed for all 10 Python files changed in this round, using
  pythonw.exe and tools/run_hidden.pyw with a hidden parent process.
- git diff --check passed. LF, the server.py UTF-8 BOM and ASCII-only server
  additions were checked. Static searches found no remaining mutation argument
  passing current_document, document, or snapshot[document] as its catalogue.
- No pytest, application server, PDF export, baseline recording or browser run
  was performed by the builder. No network/install or git history/index mutation.

Claude's reported round-2 evidence is retained, not claimed as a round-3 result:
239 focused passes; P1a smoke 27/27; P1b smoke 46/46; no new wide-suite failure;
both baselines recorded twice byte-identically and promoted. Claude also supplied
these measured counts (source-keyed / revision-scoped / unresolved):

| MMLE document | Unique identities | Aliases |
| --- | --- | --- |
| Parts | 989 / 0 / 0 | 72 / 0 / 0 |
| Operations | 629 / 7 / 0 | 467 / 7 / 0 |
| Specification | 30 / 0 / 0 | 28 / 0 / 0 |
| Work instructions | 315 / 20 / 0 | 315 / 20 / 0 |

Identity allocation rules are unchanged in round 3; these counts are expected
to remain the same, subject to the existing inventory test.

### NOT RUN

Claude must run these outside the sandbox. The original cover and viewport
workflow tests remain in the listed files; they were not relaxed to mask the
regressions. The focused command includes all documentation test files touched
across P1c-1 plus collector/smoke contracts.

~~~text
python -m pytest -q tests/test_documentation_refresh.py tests/test_operations_manual_workspace.py tests/test_specification_sheet_workflow.py tests/test_documentation_provenance.py tests/test_documentation_change_undo.py tests/test_documentation_transactions.py tests/test_parts_manual.py tests/test_work_instruction_workflow.py tests/test_documentation_baseline.py tests/test_documentation_editor_smoke.py
python -m pytest -q -s tests/test_documentation_refresh.py -k real_compiler_catalog_idempotence_and_mmle_inventory
python tools/documentation_baseline.py --check
python tools/documentation_baseline.py --local --check
python tests/smoke_documentation_editor.py --phase P1a
python tests/smoke_documentation_editor.py --phase P1b
python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_documentation*.py','tests/test_parts_manual*.py','tests/test_operations_manual*.py','tests/test_specification_sheet*.py','tests/test_work_instruction*.py','tests/test_inspection_sheet*.py') for p in glob.glob(pattern)})))"
python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_codex*.py','tests/test_facility*.py','tests/test_authored*.py','tests/test_sage*.py','tests/test_industrial*.py') for p in glob.glob(pattern)})))"
~~~

### Baseline expectation

Hash-only movement is possible in either baseline because final compositions
now come from the owner. I expect no schema, identity-count, export-text or
geometry changes in either. The existing fixture and local probes use native
slot edits and do not inject component overrides onto covers, so they may remain
byte-identical; the new regression cases specifically cover the previously
missing combinations. This is a static expectation, not a measured check.
Claude's promoted expected*.json files are preserved. Review any composition /
document hash differences before re-recording, and treat text/geometry drift as
a regression rather than an automatic promotion.

### DEVIATIONS

- No scope deviation. The request-local baseline handoff is private runtime
  context; it adds no persistent store/envelope and no serialized baseline.
- The optional internal specification compiler argument avoids recompiling a
  baseline when its caller already has one. It does not change any Sage input.
- The sibling-worktree scratch script was not read; the requested sequence was
  implemented in the existing isolated MMLE test fixture inside this worktree.
- P1c-2 refresh, generatedBaseline storage, conflict resolution and UI remain out
  of scope. Schema versions remain parts 6; operations/specification/work
  instructions 3; scene 4; slots 3; work-instruction plan 2.

### OPEN QUESTIONS

No design question remains. Fingerprints remain in aliasRevision. Round-3
runtime tests, baseline comparisons and isolated smokes remain Claude's gates;
no new runtime pass count is claimed by the builder.

## P1c-1 supervisor gate (Claude, 2026-11-10)

Result: PASSED on the round 3 code; committed together with this section.

### Rounds

- Round 1 (identities) failed my run. The first workspace edit returned 409 because compile_identities was not
  idempotent and the write paths took their catalogue from the bounded process cache. Twenty MMLE work-instruction
  step actions were unresolved yet still listed as editable.
- Round 2 made the catalogue explicit on every write path (the cache is diagnostic only) and added revision-scoped
  identities: the supervisor decision recorded above, with an exact-value refresh rule for P1c-2. The documentation
  suites then found three regressions:
  - bind_document overwrote the owners' composition rules. The operations cover regained component transforms, and
    the specification legacy viewport text came back and would shadow later slot values in the workspace.
  - On the specification sheet, every edit after the first viewport text edit returned 409. GETs compiled the
    identity catalogue from the scene-free baseline but writes compiled it from the displayed document, and alias
    fingerprints digest displayed text.
  - A direct-repository test needed the round 2 contract.
- Round 3 fixed all three: owners apply the projected scene with their own rules, and GETs and every write path use
  one scene-free baseline.

### Numbers (round 3 code)

- Focused suites (refresh, operations workspace, specification workflow, provenance, change undo, transactions,
  parts, work instructions, baseline, smoke unit): 280 passed and 2 failed. The local baseline was then
  re-recorded, and the work-instructions sentinel was fixed (below). The fixed test passes 4/4.
- MMLE identity inventory, as sourceKeyed / revisionScoped / unresolved:

  | Document          | Identities   | Aliases      |
  |-------------------|--------------|--------------|
  | Parts             | 989 / 0 / 0  | 72 / 0 / 0   |
  | Operations        | 629 / 7 / 0  | 467 / 7 / 0  |
  | Specification     | 30 / 0 / 0   | 28 / 0 / 0   |
  | Work instructions | 315 / 20 / 0 | 315 / 20 / 0 |

- Real routes, on all four MMLE documents: edit, edit a second target, GET revision equals the last response, undo,
  edit again. All succeed; the specification sheet failed this before round 3.
- Baselines. Each was recorded twice, byte-identical, then reviewed and promoted:
  - Synthetic: parts and specification document hashes, and the table scene hash.
  - Local, round 2: hashes and identity metadata only (rowId, cellIds, sourceKey, identityScope, identitySourceKey,
    identityStatus), plus the citation export targetId, which is now a gen-row ID.
  - Local, round 3: only the work-instructions edited/reopened document hash moved, because the owner now applies
    the composition after projection. Exports and undo are unchanged.
  - Neither baseline has an export text or geometry change.
- Smokes P1a 27/27 and P1b 46/46, in Chromium headless on the GPU.
- Documentation suites: 535 passed, plus the pre-existing failure
  test_source_ids_references_and_local_hashes_are_closed. JS 5/5.
- Wide suites: 3849 passed, 170 failed, 9 errors. No new failure against the base set.
- Checked: the private baseline never reaches JSON responses or Sage tool results. LF line endings, the server.py
  BOM and ASCII-only additions to server.py are intact.

### Supervisor fixes (Claude)

- tests/test_documentation_refresh.py, mmle_client: copies only the local approved parts plan into the temporary
  root. The parts cases skip without it; without it the parts GET returned 422.
- tests/test_documentation_provenance.py, test_user_confirmation_removes_active_citation: the confirmation values
  are keyed by stable cell IDs and asserted in column order, with the displayed values.
- tests/test_documentation_refresh.py, test_workspace_repeated_edits_and_undo_share_scene_free_baseline: accepts the
  work instructions' pre-existing "baseline" documentationSceneRevision sentinel, which they set when compiled
  without a scene.

### Notes for later slices

- Invariant: the identity catalogue for a stored state comes from the scene-free generated baseline, for the GET
  and every write path. aliasRevision includes fingerprints (digests of displayed values), so any other document
  gives a different revision. The baseline rides as a request-local dict-subclass attribute; a copy that drops it
  fails closed with document_read_required.
- An unknown positional alias, even with a baseline supplied, is now refused as ambiguous_legacy_target ("read
  again") rather than target_not_found. No consumer depends on the code. Revisit the wording when P1c-2 reports
  orphans.
- The specification compiler builds its own scene-free baseline when a standalone caller passes none, which costs
  a double compile. Routes pass theirs.
- P1c-2: the 7 operations and 20 work-instruction revision-scoped identities follow the exact-value refresh rule
  recorded above.


## P1c-2a

Builder handoff, 2026-11-10. Uncommitted. Read the P1c-1 supervisor gate,
plan section 3.5, the P1c slice of section 4 and section 3.3's conflict contracts.
This slice stops at persisted refresh state, guarded writes and explicit reset.

### CHANGED

- Added ai_inspector/documentation/refresh.py. The shared transformation takes
  stored state, a scene-free compiler baseline and owner-supplied refresh ID,
  actor and time. It returns a candidate and receipt without store I/O. It
  compares exact generated/authored payloads, carries reordered source IDs,
  preserves manual status when C equals N, adopts N when C still equals B,
  and retains divergent values as value/evidence/missing_baseline conflicts.
  Revision-scoped values require a unique keyed parent/ordinal and exact old/new
  generated payload equality. A changed value conflicts; a missing identity is
  orphaned. No fuzzy/text search or positional fallback is used.
- generatedBaseline entries contain payload/hash, source/plan binding, evidence,
  display address, scope and identity metadata. The first target write captures
  B from its request's scene-free baseline; later edits retain B. Matching older
  stores derive missing B only in memory. A stale missing B remains missing in
  its conflict, including after reopen. Refresh advances adopted baselines,
  including targets whose earlier manual edit was undone.
- ai_inspector/parts_manual/documentation.py integrates baseline capture,
  validators, refresh preparation/commit, read-only conflict/orphan exposure and
  mutation guards. Refresh uses the existing restore_change replay format as a
  non-user checkpoint; older named inverses remain guarded. Scene commands,
  batches, confirmation batches and history cannot overwrite an open conflict.
  Deleted generated targets also refuse an older inverse with undo_conflict.
- ai_inspector/documentation/provenance.py clears obsolete text-history effects
  for values adopted by a refresh checkpoint. Adopted generated text can regain
  its generated provenance; kept/preserved manual values retain manual status.
  Authored objects retain content, frame, order and ID. Theme/page masters and
  surviving figure/camera composition remain. Deleted page/target content is
  retained in orphans with its value, address, reason and stale link. Numbered
  callout overrides without a proven original source relation are orphaned,
  never attached to whichever part now occupies that number.
- ai_inspector/specification_sheet/slots.py adds the same optional metadata to
  slots schema 3, native-slot baseline capture, guarded mutations/inverses,
  refresh and reset. Generated slot defaults supply B/N; stored manual slot
  values do not become their own generated baseline. Explicitly authored rows
  retain their values and order. Legacy slot version byte backups also apply to
  refresh writes. ai_inspector/specification_sheet/document.py accepts a private
  staged slot state so compilation can validate a refresh before persistence.
  Existing viewport text overrides remain in their existing scene owner; their
  native-slot aliases are checked against both owners' conflicts. Native slot
  values and their B/conflicts remain in slots.json.
- server.py retains _DocumentationDocument.identity_document as the one
  scene-free catalogue used by GETs, writes and response reads. The operations,
  specification and work-instruction builders stage refresh when
  rebaseline_stale / generate?rebaseline=true is requested, compile the candidate,
  then commit through the owners. These parameters remain accepted. Reads,
  opening and export do not refresh. Existing rebind_manual_plan is unchanged.
- Parts recovery is GET then POST
  /api/parts-manual/{assembly_number}/documentation-scene/refresh. GET compiles
  the candidate and returns expectedRevision and expectedPlanRevision; POST
  requires both. ai_inspector/parts_manual/repository.py carries the unchanged
  plan grouping only when every referenced occurrence, including exclusions and
  occurrence order, exists. Missing references return document_binding_changed
  with missingOccurrences. Item assignments follow definitions. Both the plan
  and scene candidates compile before writes; a scene write exception restores
  the original plan bytes.
- Each owner checks its revision under its lock and uses its existing atomic
  replace. Coordinated specification writes stage both candidates first and
  restore original slot bytes if the second owner fails. There is no new
  cross-store envelope. Refreshing the same binding produces no receipt or
  write. Later refreshes update proposed N while retaining original conflict
  B/C and IDs, including conflicts whose targets became unplaced.
- Refresh receipts retain the newest **100** entries. Each contains refreshId,
  from/to binding, actor, time, adopted/preserved/kept/conflicts/orphans/
  carriedRevisionScoped counts and conflictIds. Conflict/orphan counts describe
  the retained open/unplaced state; adopted includes generated targets without
  manual overrides. Manual content is not evicted with receipts.
- Explicit reset is GET then POST
  /api/documentation/{document_type}/{assembly_number}/reset. Preview returns
  affected IDs/counts, expectedRevision and previewHash. Specification also
  returns a slots preview; execute sends that preview's revision/hash pair.
  POST uses the existing trusted-origin/user-principal boundary, rejects actor
  input and has no Sage tool. It retains exact prior bytes as short
  sr-<id>.json / sl-<id>.json siblings and returns recovery IDs. Destructive
  rebaseline is now reachable only through this reset contract. Reset responses
  reopen the current stored state so slot resets return the current catalogue.
- ai_inspector/documentation/commands.py, targets.py and
  codex_runtime/documentation_tools.py expose an open conflict count and per-read
  target hasOpenConflict/conflictIds, retaining existing inputs and outputs.
  Workspace payloads expose conflicts and orphans. No conflict-resolution tool,
  HTTP conflict route, export-policy change or UI is included.
- tests/test_documentation_refresh.py now covers every three-way row, missing
  and derived baselines, persistence/restart, idempotence/later proposals,
  revision-scoped exact-value carry/refusal, authored content, generated
  provenance adoption, guarded writes, denied replaces, reset/recovery, real
  operations/WI regeneration, real specification native/viewport/Sage refusal,
  the parts description/note refresh route, missing-occurrence refusal, and the
  existing real parts section-move/capture test under the requested rebind test
  name. tests/test_codex_documentation_tools.py checks additive read markers and
  pins the absence of reset/resolution tools. The operations obsolete-scene
  test now expects refreshReceipt rather than destructive rebaselined.
- tools/documentation_baseline.py uses the explicit reset preview/execute
  contract for its existing reset probe. No expected*.json was edited.
- Added tests/fixtures/documentation_editor/slots-v3-pre-refresh.json, a small
  sanitized old shape. **It is ignored by the existing .gitignore rule *.json;
  Claude must explicitly include this exact fixture in the commit.** No ignore
  rules were changed and no index/history mutation was performed.

### TESTS

Builder execution is static only:

- Python ast.parse passed for the 14 changed/added Python files through the
  hidden pythonw.exe / tools/run_hidden.pyw launcher. No application imports.
- git diff --check passed. Checked LF, server.py's UTF-8 BOM, ASCII-only server
  additions, fixture JSON syntax and unchanged promoted baseline files.
- Searched production rebaseline callers: the sole caller is the explicit
  user reset endpoint. The baseline tool uses the same preview contract.
- No pytest, server, PDF, baseline check/recording or browser was run. No network,
  package installs, commits, branching or index writes. The existing .runtime/
  directory was left alone.

### NOT RUN

Claude must run these outside the sandbox:

~~~text
python -m pytest -q tests/test_documentation_refresh.py tests/test_documentation_provenance.py tests/test_documentation_change_undo.py tests/test_documentation_transactions.py tests/test_operations_manual_workspace.py tests/test_specification_sheet_workflow.py tests/test_parts_manual.py tests/test_work_instruction_workflow.py tests/test_codex_documentation_tools.py tests/test_codex_readonly_pilot.py tests/test_codex_assisted_tools.py tests/test_documentation_baseline.py
python -m pytest -q tests/test_documentation_store_chokepoint.py
python tools/documentation_baseline.py --check
python tools/documentation_baseline.py --local --check
python tests/smoke_documentation_editor.py --phase P1a
python tests/smoke_documentation_editor.py --phase P1b
python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_documentation*.py','tests/test_parts_manual*.py','tests/test_operations_manual*.py','tests/test_specification_sheet*.py','tests/test_work_instruction*.py','tests/test_inspection_sheet*.py') for p in glob.glob(pattern)})))"
python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_codex*.py','tests/test_facility*.py','tests/test_authored*.py','tests/test_sage*.py','tests/test_industrial*.py') for p in glob.glob(pattern)})))"
~~~

The known pre-existing failure
 test_operations_manual_precoding_contracts.py::test_source_ids_references_and_local_hashes_are_closed
was not changed.

### Baseline expectation

Expect stored-state fingerprints to move when B and refresh metadata are first
persisted. Scene/document hashes may move in either baseline; neither expected
file was edited. No generated/store version, identity-allocation rule, export
text or geometry change is intended for documents without edits/conflicts.
The baseline reset probe still measures explicit reset, not regeneration.
Claude must review actual differences before promoting either baseline.

### DEVIATIONS

- No phase expansion. Scene 4 and slots 3 remain; generated versions remain
  parts 6 and operations/specification/work instructions 3. No static JS/HTML or
  Sage input/tool-list changes. Resolution, its undo, conflict HTTP/Sage APIs,
  export marking/blocking and UI remain P1c-2b/P1c-3 work.
- Multi-owner operations use existing owner locks and atomic replaces, with
  compensation on a reported second-write failure. They do not introduce a
  distributed transaction file. A process interruption between owner replaces
  can leave a stale binding requiring another explicit refresh; no manual
  payload is discarded by that interruption.
- Reset preview currently requires an open/current document. A stale parts plan
  must first pass the explicit source-carry check; reset cannot bypass missing
  occurrence validation or infer a new grouping approval.

### OPEN QUESTIONS

No product decision is requested. Runtime gates are pending. In particular,
Claude should verify the real parts source-refresh scenario, specification's two
owners, and the unchanged P1a/P1b smokes before committing. The exact new fixture
must be included despite the JSON ignore rule. Recovery copies are retained;
restoring/detaching content and conflict resolution are deliberately not exposed
in this round.

## P1c-2a supervisor gate (Claude, 2026-11-10)

Result: PASSED after supervisor fixes; committed together with this section.

Codex's round took 44 minutes, with static checks only. My first run of the focused suites gave 70 failed and 407
passed. After the fixes below, the targeted run gave 110 passed, and the full gate chain followed.

### Supervisor fixes (Claude)

- parts_manual/documentation.py, apply_batch: the local `command, command_targets = normalize_command(...)`
  shadowed the imported refresh helper command_targets, so every batch crashed with "'dict' object is not
  callable". The local is renamed normalized_targets.
- refresh.command_targets / guard_command: route commands come from Pydantic model_dump with transforms,
  fieldMeta or identityResetTargets set to None. Iterating them crashed every workspace edit made through the
  routes, so None now reads as empty.
- refresh.guard_change: refused undo of any tombstoned non-authored identity, which blocked undoing a user's own
  slot-row rename (P1b test_compound_slot_row_undo_checks_dependencies). Refresh now marks the tombstones it
  creates with tombstonedBy "refresh", and clears the mark when the identity returns. The guard refuses only
  those.
- Parts refresh: PartsManualRepository.read() defaults known_occurrence_ids to an empty tuple and validates a
  source-current plan against it. _parts_refresh_inputs and commit_source_refresh called it without IDs, so any
  preview on a current plan returned 422 manual_occurrence_unknown: before a source change, or on a repeat after
  a refresh. Both now pass the catalogue's occurrence IDs; the prepared candidate carries knownOccurrenceIds.
- Tests:
  - The parts fixture's source revision must be SHA-256.
  - Specification feature blocks carry slots.text, not slot.
  - The work-instructions regeneration case now picks a revision-scoped action.
  - The adoption test asserts that the adopted row equals the no-scene projection of N. The synthetic fixture
    projects claimIds [] even without a scene.

### Numbers

- Baselines, each recorded twice, byte-identical, then reviewed and promoted:
  - Synthetic: only the table scene hash.
  - Local: only the edited/reopened hashes of operations, specification and work instructions, because an edit
    now stores generatedBaseline.
  - The before-edit hashes, exports and undo records are unchanged.
- Smokes P1a 27/27 and P1b 46/46.
- Documentation suites: 584 passed, plus the pre-existing failure
  test_source_ids_references_and_local_hashes_are_closed. JS 5/5.
- Wide suites: 3850 passed, 170 failed, 9 errors; no new failure against the base set.
- Parts route scenario (test):
  1. Edit a description and an unrelated note.
  2. A source change reorders the BOM and changes that description.
  3. Refresh. The note is kept and the description holds a value conflict that survives a restart.
  4. A repeat refresh is a no-op, and the store stays byte-identical.
- A source change alone, checked by me through the routes: 1020 identities adopted, the edited description
  preserved, 0 conflicts.
- Checked: the reset route sits behind the confirm-values origin boundary, requires the preview hash and
  expected revision, and has no Sage tool.

### For P1c-2b (deviations from plan 3.5 to correct)

- three_way checks for a missing baseline before checking C == N. An edit that equals the new generated value
  therefore still raises a missing_baseline conflict. The plan's "C == N: keep value" row does not depend on B.
- An evidence-only change (B payload == N payload, evidence differs) on an edited value raises an "evidence"
  conflict. The plan's row "C changed; N == B: preserve C exactly" calls for keeping C without a conflict, with B
  then moving to N. My P1c-2a brief listed "evidence" as a conflict kind; that was my over-specification.
- Notes:
  - Refresh receipts are capped at 100.
  - The two-owner parts refresh (plan, then scene) uses compensation rather than a joint transaction. An
    interruption between the two owners may need another explicit refresh; manual payloads are retained.


## P1c-2b

### CHANGED

- Read the P1c-2a supervisor gate first and re-read plan sections 3.3 and 3.5. Kept all four supervisor runtime fixes: no helper-name collision in batches, None-safe command fields, refresh-only tombstone guards, and occurrence IDs on parts-plan reads. Versions remain scene 4 and slots 3. No P1c-3 UI or static assets changed.
- ai_inspector/documentation/refresh.py: C == N now wins even without B and for revision-scoped identities; evidence-only changes preserve C and advance B. New refreshes no longer create evidence conflicts. Conflict/orphan hashes are pure read projections for old stores and persist on refresh/resolution writes. Non-text orphan kinds support explicit same-kind restoration.
- New ai_inspector/documentation/resolution.py: shared pure candidate builder for keep_manual, use_generated, merge_text, detach and restore. Requests require exact owner revision, request ID and each conflict hash; restore also checks the explicit destination's content hash and kind. A deleted conflict linked to an orphan closes with that orphan's hashed detach/restore transaction.
- parts_manual/documentation.py, specification_sheet/slots.py and documentation/changes.py: locked atomic writes, original-receipt retries, named/history undo and redo, and per-entry conflict/orphan/audit before/after images. Undo reopens the same B/C/N while preserving unrelated resolutions. Resolution history is capped at **100 entries** per owner; existing caps remain **1,000** edit receipts, **100** refresh receipts and **2,000** retained changes. Store size guards remain.
- Native use_generated selections suppress older viewport fallback text and use the current default and its evidence status. They are not manual values or confirmations. Merge/restore stay manual; keep_manual retains manual status. documentation/provenance.py recomputes support through the existing projection and effective history.
- server.py: GET /api/documentation/{document_type}/{assembly_number}/conflicts (zero-based from, limit) and POST .../conflicts/resolve share host methods with Sage. POST records actor user; Sage records actor sage. Responses include receipt, revisions, conflict/orphan/audit exposure and reload: true. Reads include owner/revision per entry, exact B/C/N text and payloads, evidence changes, hashes, counts, pagination totals and restore destinations/hashes. Specification slot and legacy scene owners resolve separately, using each entry's reported revision. Named inspection/undo selects the actual owner.
- codex_runtime/documentation_tools.py: added read_document_conflicts and resolve_document_conflicts, including restore target/hash fields and "Read conflicts and resolve only the requested targets." Existing tools keep their inputs; confirmation and reset stay UI-only.
- New documentation/conflict_exports.py, operations/specification exporters, parts PDF exporter, specification compiler and provenance projection: review/draft exports mark targets and give conflict/orphan counts. Work instructions reuse the operations renderer. Customer/controlled exports fail with manual_edit_conflict and open conflictIds before existing evidence gates. Parts PDF accepts additive mode query input. Orphans alone do not block.
- tests/test_documentation_refresh.py covers corrected policy, all choices in both owners, stale hashes/revisions, atomic failure, retries, named/history inverses, independent resolutions, detach/restore, deleted-conflict links, audit bounds, restart/old-shape reads, parts HTTP/Sage twin stores, native specification routes and four-document export paths. Updated test_codex_documentation_tools.py, test_codex_readonly_pilot.py, test_codex_assisted_tools.py, test_codex_specification_sheet_tools.py and the isolated smoke server's tool allowlist.
- **Baseline expectation:** neither promoted baseline should move. Current probes exercise no conflict resolutions; no-conflict export text/geometry and ordinary text-edit stores retain their paths. New conflict/audit and non-text restoration-kind metadata affect stores using those paths. Expected baseline JSON was not edited.

### TESTS

- Ran git diff --check: passed.
- Node file checks: changed/new files use LF; server.py retains its UTF-8 BOM; all added server.py lines are ASCII. Its eight pre-existing non-ASCII characters outside the BOM remain unchanged.
- Manually traced HTTP/Sage dispatch, explicit scene-free identity baselines, owner locks, retries, candidate persistence, inverse records, specification default/viewport precedence and renderer calls. This found and fixed a DOCX row-variable error before handoff.
- **No Python was run**, including imports or syntax/AST checks. No runtime or visual-export pass is claimed. No browser, network, installation, commit, branch or index mutation occurred.

### NOT RUN

Claude must run outside the sandbox, including the additional touched specification tool tests:

    python -m pytest -q tests/test_documentation_refresh.py tests/test_documentation_provenance.py tests/test_documentation_change_undo.py tests/test_documentation_transactions.py tests/test_operations_manual_workspace.py tests/test_specification_sheet_workflow.py tests/test_parts_manual.py tests/test_work_instruction_workflow.py tests/test_codex_documentation_tools.py tests/test_codex_readonly_pilot.py tests/test_codex_assisted_tools.py tests/test_codex_specification_sheet_tools.py tests/test_documentation_baseline.py tests/test_documentation_store_chokepoint.py
    python tools/documentation_baseline.py --check
    python tools/documentation_baseline.py --local --check
    python tests/smoke_documentation_editor.py --phase P1a
    python tests/smoke_documentation_editor.py --phase P1b
    python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_documentation*.py','tests/test_parts_manual*.py','tests/test_operations_manual*.py','tests/test_specification_sheet*.py','tests/test_work_instruction*.py','tests/test_inspection_sheet*.py') for p in glob.glob(pattern)})))"
    python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_codex*.py','tests/test_facility*.py','tests/test_authored*.py','tests/test_sage*.py','tests/test_industrial*.py') for p in glob.glob(pattern)})))"

The pre-existing test_operations_manual_precoding_contracts.py::test_source_ids_references_and_local_hashes_are_closed failure was left untouched. Please visually review conflict notices in PDF/DOCX during the gate; their placement has not been rendered here.

### DEVIATIONS

- No phase-scope deviation. Validators accept obsolete evidence conflicts only to read P1c-2a-shaped saved records; no new refresh emits them. They remain reviewable/resolvable without a silent save on read.
- Added owner revision/destination metadata because specification retains native slots and legacy scene content. Mixed-owner batches are refused under the existing one-store transaction contract.
- Native generated selection uses an internal selectedGenerated marker to suppress old scene fallback. Neither public tool accepts it, and it grants no source approval.

### OPEN QUESTIONS

None requiring a product decision. Runtime, baseline, smoke and rendered-export validation remain pending Claude's gate.

## P1c-2b supervisor gate (Claude, 2026-11-10)

Result: PASSED after supervisor fixes; committed together with this section.

Codex's round took 31 minutes, with static checks only. My first run of the focused suites gave 536 passed and
5 failed. After the fixes below, the focused run gave 542 passed and the full gate chain followed.

### Supervisor fixes (Claude)

- provenance.project_document, a latent P1b-2 defect exposed by the new resolution tests. A bound block can mix
  rows that carry claimIds with rows that do not. When the unbound remainder was not source-backed, its cleanup
  loop ran over every row and cleared the cited rows' own citations and provenance. It now skips rows processed as
  bound in the same projection.
  - The whole-block fallback (an unknown row edited) still clears every row, as before.
  - The real MMLE documents have 13 bound blocks and none mixed, so no export or baseline changes.
  - Regression test: test_documentation_provenance.py::test_mixed_block_remainder_keeps_bound_row_citations.
- Tests:
  - The request-ID reuse check now drops mergedText when it switches the choice to detach. Request validation
    otherwise refuses the reused payload before the reuse check.
  - The parts export test now uses the parts capture fixture, which has line geometry. It also spreads the
    synthetic balloons over y 0.08-0.92: the fixture's single column overlaps above 13 callouts, and MMLE pages
    carry up to 16.

### Visual review (review exports rendered to PNG)

- Inline markers are visible on all four documents:
  - Parts: under the BOM description cell.
  - Specification sheet: under the title.
  - Operations and work instructions: in the cover kicker.
  The footer summary ("Open manual edit conflicts: N; unplaced manual content: M") is legible on every page.
- For P4:
  - The top-left per-page conflict list is drawn over the dark header bands of parts and specification pages,
    where it is nearly illegible.
  - The operations and work-instructions marker shares its line with the edited-values legend.
  - The specification marker sits tight against the subtitle.

### Numbers

- Focused suites: 542 passed.
- Baseline checks (synthetic and local): both pass unchanged, as Codex predicted.
- Smokes: P1a 27/27, P1b 46/46.
- Documentation suites: 639 passed, plus the pre-existing failure test_source_ids_references_and_local_hashes_are_closed; JS 5/5.
- Wide suites: 3851 passed, 170 failed, 9 errors; no new failure against the base set.
- Checked:
  - Sage's resolve_document_conflicts schema matches validate_request exactly (documentId, expectedRevision,
    requestId, resolutions).
  - The resolve route takes a JSON body and records actor "user". Like the other edit routes it has no origin
    boundary, since Sage may resolve too. Confirmation and reset keep their origin boundary.

### For P1c-3

- read_document_conflicts also returns restoreTargets: same-kind destinations with their content hashes,
  paginated.
- Resolve responses carry reload: true plus the refreshed exposure.
- Specification scene conflicts and slot conflicts resolve in separate requests.
- Undo re-appends a reopened conflict at the end of its list, so the UI should order conflicts by page and target,
  not by storage order.

## P1c-3

### CHANGED

- `static/documentation_conflicts.js` adds one review controller for parts, operations, specification and work instructions. The status bar reads persisted conflict/orphan counts. The pane sorts by page and stable target, shows C/B/N and old/new evidence, and uses the existing page-selection/highlight path. Open targets have page markers and redirect attempted inline edits to review.
- Keep mine, Use generated, nonempty Merge, Detach and explicit same-kind Restore use the existing resolve route. Each request carries the item's owner revision and conflict hash. Restore destinations come from every page of the server's restoreTargets catalogue, with no default selection. A transport retry retains its request ID; refused revisions/hashes reload the workspace and review without resolving automatically. Specification owners are resolved separately.
- `static/index.html` loads the new module with `?v=20261110-p1c-3`, connects payload/page updates and edit guards, and adds stable target attributes to existing master text. Cover notes now also accept the existing two-press edit gesture. Review follows history undo/redo; a five-second read-only check while a reviewed workspace remains open observes external/named undo without interrupting an inline edit.
- Parts has preview/execute Refresh from source both beside the manual-plan stale-source message and in a stale documentation workspace. Existing operations/specification/WI generation shows refresh receipt counts. Reset to generated uses an in-page preview/confirmation, shows affected IDs (first 20 plus remaining count), retains the scene and specification slot preview pairs, and states that a recoverable copy is kept. No native alert/confirm/prompt dialogs were added.
- `tests/documentation_editor_smoke_server.py` owns the sole source-fixture reader and route, `POST /__p1c/source-fixture`. It persists a deterministic SHA-256 source binding and definition-keyed description/order changes in scratch/source-fixture.json, reapplies them on startup, validates the requested definition, and never mutates the underlying catalogue.
- `tests/smoke_documentation_editor.py` adds restart on a new port with the same scratch stores and isolation assertions, plus a separate P1c scenario: browser description/note edits, source refresh, identity-preserving row movement, persisted C/B/N and marker/count, real captures and review/customer export checks, restart and Sage agreement, browser merge/undo/redo, restored-store Sage twin, and resolved reopen. It records a ten-minute budget check and writes p1c-refresh-receipt.png, p1c-page-marker.png, p1c-conflict-pane.png, p1c-resolved.png, p1c-resolved-reopen.png and p1c-review.pdf under .runtime/de for supervisor review.
- `tests/documentation_conflicts.test.cjs` adds controller/request and pure-helper tests. `tests/test_documentation_conflicts_ui.py` adds pytest coverage for the launcher-only route, persisted fixture replay/refusal, and process restart/store isolation.
- No production server route, exporter, compiler, store version, scene-free identity baseline, Sage schema or inventory changed. All P1c-2b supervisor fixes remain intact. **Neither baseline is expected to move.** Expected baseline JSON files were not edited.

### TESTS

- `node --test tests/documentation_conflicts.test.cjs`: **14 passed**. Covers owner revisions, hashes, explicit restore/hash validation, nonempty merge, evidence comparison, identity markers, deterministic ordering, combined receipts, stale rejection without automatic resolution, same-ID transport retry, paginated reads, specification reset pairs, named undo observation and parts refresh preview/execute.
- `node --check static/documentation_conflicts.js`: passed.
- Extracted all four executable inline scripts from index.html in memory and checked each with `node --input-type=module --check`: passed. Parsed its import map separately as JSON.
- `git diff --check`: passed.
- Node file checks: all changed/new files use LF; every added index.html line and the new module are ASCII. Existing non-ASCII index.html content is untouched. server.py is unchanged, including its BOM.
- Compared the P1a body after removing its added branch indentation and the complete P1b function against HEAD: both are identical. Shared launcher changes were traced through initial launch, restart and final cleanup.
- Manually traced the new Python paths and the UI against real route bodies, catalogue ordering/item assignment rules, owner revisions, target maps, reset previews and export response fields. **No Python was run**, including imports or syntax/AST checks. No runtime, browser, visual or ten-minute pass is claimed.

### NOT RUN

Claude must run outside the sandbox:

    python -m pytest -q tests/test_documentation_refresh.py tests/test_documentation_provenance.py tests/test_documentation_change_undo.py tests/test_documentation_transactions.py tests/test_operations_manual_workspace.py tests/test_specification_sheet_workflow.py tests/test_parts_manual.py tests/test_work_instruction_workflow.py tests/test_codex_documentation_tools.py tests/test_codex_readonly_pilot.py tests/test_codex_assisted_tools.py tests/test_codex_specification_sheet_tools.py tests/test_documentation_baseline.py tests/test_documentation_store_chokepoint.py tests/test_documentation_conflicts_ui.py tests/test_documentation_editor_smoke.py
    python tools/documentation_baseline.py --check
    python tools/documentation_baseline.py --local --check
    python tests/smoke_documentation_editor.py --phase P1a
    python tests/smoke_documentation_editor.py --phase P1b
    python tests/smoke_documentation_editor.py --phase P1c
    python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_documentation*.py','tests/test_parts_manual*.py','tests/test_operations_manual*.py','tests/test_specification_sheet*.py','tests/test_work_instruction*.py','tests/test_inspection_sheet*.py') for p in glob.glob(pattern)})))"
    python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_codex*.py','tests/test_facility*.py','tests/test_authored*.py','tests/test_sage*.py','tests/test_industrial*.py') for p in glob.glob(pattern)})))"

The pre-existing test_operations_manual_precoding_contracts.py::test_source_ids_references_and_local_hashes_are_closed failure remains untouched. Please inspect the generated PNGs; exporter marker cosmetics remain deferred to P4.

### DEVIATIONS

- No production phase-scope deviation or missing server field.
- The P1c smoke starts with a disposable copy of the approved plan whose itemAssignments are empty, and removes only that scratch copy's seed scene before the two browser edits. Grouping and occurrence membership remain approved and unchanged. This is necessary to exercise actual source-driven BOM movement: build_scoped_bom deliberately preserves explicit item numbers, so reversing catalogue input alone cannot reorder a pinned section. The source-fixture wrapper then changes the selected definition's sort key and description; the smoke asserts changed order and the unchanged definition/cell identity. P1a/P1b retain their original seed stores.
- The stale workspace repeats the manual-plan refresh affordance so a reopened stale manual has a visible recovery path without first finding the plan panel.
- Screenshot production and the under-ten-minute budget remain supervisor-run checks, not claimed results from this sandbox.

### OPEN QUESTIONS

None requiring a product decision. Runtime, shared-launcher regression, real-browser visual review and baseline gates remain pending Claude.

## P1c-3 supervisor gate (Claude, 2026-11-10)

Result: PASSED after supervisor fixes; committed together with this section. P1c is complete.

Codex's round took 29 minutes: static checks, plus the new Node tests (14 passed) in its sandbox. My focused run
gave 545 passed. The first P1c smoke stopped at its setup. The fixed smoke then exposed two real UI defects
that only a browser could show.

### Supervisor fixes (Claude)

- Smoke setup: BOM cells are definition-keyed (part.<definitionId>.<field>) and carry that stable ID in the DOM.
  They have no aliasMap entry, so the alias lookup raised StopIteration. It now falls back to the stable ID.
- Review pane unusable (defect): #documentationWorkspace is a click-through overlay (pointer-events:none) whose
  children opt back in. The pane did not opt in, so it was painted on screen while every click passed through to
  the page beneath. It now sets pointer-events:auto.
- Review pane covered the page (defect). In workflow mode the canvas spans the full workspace width, so the pane:
  - hid the right-hand side of the page, where the conflicted BOM cells are;
  - let the contextual selection toolbar (z-index 5150) sit over the pane's buttons.
  The fix:
  - While open, the pane docks into the workspace's right column. The workspace class
    documentation-review-open reserves its width through --documentation-properties-width, so the canvas shrinks
    beside it, and the inspector column is hidden.
  - Opening the review clears the page selection.
  - Focusing a conflict scrolls to the marked target instead of selecting it; a conflicted target is not
    editable.
- Polling: the five-second change check now runs only while the pane is open, because each check recompiles the
  document on the server.
- Node harness: the gate chain's Node run caught that the docking change broke 6 of the 14 controller tests (the
  fake DOM element had no classList). The fake element now has a classList backed by className, and the host
  counts clearSelection calls. Two new tests:
  - opening docks the pane (workspace class) and clears the page selection once; Close undocks it;
  - a closed pane never polls, and reopening resumes the change check.
  Each new test fails on a mutant of the module without the matching code (scratch copies, not committed).
- Count text: "1 conflict" instead of "1 conflicts" (Node test and smoke expectations updated).
- Gate runner: doc-editor-night/baseline.sh now also runs tests/documentation*.test.cjs.

### Visual review (smoke PNGs)

- The refresh receipt shows: adopted 1019 | preserved 1 | kept 0 | conflicts 1 | orphans 0.
- The page marker (orange outline and "Conflict" badge) is on the edited description cell, after the BOM rows
  moved by identity (the fixture's part number is now item 2).
- With the pane open, the page sits fully visible beside the docked pane. The card shows C, B, N, the evidence
  ("unchanged"), the merge box and the three choices.
- After the browser merge: "0 conflicts", and the BOM shows the merged text.

### Numbers

- Focused suites: 545 passed. Node: documentation_conflicts.test.cjs 16/16 (14 from Codex, 2 added).
- Smoke P1c, run alone: 35/35 in 238 s (budget: 10 minutes).
- Gate chain:
  - smokes: P1a 27/27, P1b 46/46, P1c 35/35;
  - baseline checks: both unchanged (exit 0);
  - documentation suites: 642 passed, 1 failed. The failure is the pre-existing
    test_operations_manual_precoding_contracts.py::test_source_ids_references_and_local_hashes_are_closed
    (recorded since P1a). P1c-2b had 639 passed; the 3 new are Codex's UI pytest;
  - wide suites: 170 failed, 9 errors, 3851 passed, the same totals as P1c-2b. Every failure is in the
    base set; none is new.

### Notes

- Accepted Codex deviation: the P1c smoke clears the copied plan's item assignments in scratch only. Approved
  item numbers keep BOM order fixed by design, so without this a source reorder cannot move rows. Grouping and
  membership are unchanged.
- Not ours: tests/packaging_host.test.cjs (packaging work, last changed in d20baac before this branch) fails
  1 of 13 in this worktree. It is left for the packaging owner.

### P1c summary

- P1c-1 (f28cd8f): stable identities.
- P1c-2a (68855f3): three-way refresh with persisted conflicts and orphans.
- P1c-2b (b073edd): resolution, undo, Sage conflict tools and export marking.
- P1c-3 (this commit): the review UI, refresh and reset controls, and smoke --phase P1c.
The plan's P1c gate holds:
- the browser edits a description and an unrelated note;
- a fixture source revision reorders the BOM and changes the same field;
- the note survives and the field shows a persistent conflict, including after a restart;
- the user and Sage resolutions agree.
