# Sage objective-to-layout: implementation plan

Date: 2026-09-17

Status: Implementation authorized by the user; foundation and preview-backend
work implemented. Integrated Sage/editor qualification remains open.
This is not release approval, manufacturing qualification, or permission to edit
the manual reference layout. The new path remains unavailable to live Sage until
its integration gates pass.

## Baseline and decisions

This project-local plan implements the reviewed contract at
`C:/Users/might/Documents/Codex/2026-09-05/can/outputs/sage-layout-first-slice-contract.md`.
It retains C1-C5 and resolves the Save revision finding below. Existing unrelated
working-tree changes must be preserved.

The target is one continuous conversation: reviewed inputs and an empty isolated
rectangular layout O; a newly admitted package and isolated candidate A; a
consequential quantity correction producing B; exact selection and unsaved Apply;
then Undo to O. A separate explicit Save case proves persistence.

- C1: only `new_empty_layout` is enabled. Replacement and incremental authoring
  remain unsupported. No silent destination switch or clearing of a live factory.
- C2: preserve exact process references and generated entity manifests. Executable
  process bindings and transfer optimization are a later, separate gate.
- C3: admit model-proposed coordinate-free packages through server-owned policy,
  authority, immutable storage, exact revisions, and current dependency checks.
  Keep the existing MMLE allowlist intact.
- C4: a separate generation ledger owns broad requirements. Do not broaden FDL v1
  or manufacture an FDL travel brief to obtain its transaction machinery.
- C5: previews do not install editor drafts. Reuse shared ownership and recovery
  through a typed adapter; retain construction's clean-base restriction.

## Save contract amendment

`repository.save_layout` assigns `updatedAt` on a changed Save. Consequently:

1. Selected and applied candidate canonical bytes/revisions must be identical.
2. Applied and saved approved content must be identical, except explicitly
   enumerated repository-owned `createdAt`/`updatedAt` handling. `createdAt` must
   remain the stored layout's creation time; `updatedAt` is assigned by Save.
3. A durable commit receipt binds candidate ID/revision, expected persisted base,
   resulting persisted revision, and approved content fingerprint. Reuse the
   content-fingerprint rule in `FacilityLayoutService`; do not change global
   canonical revision semantics or hide other changed fields.
4. Reload verifies the persisted revision and fingerprint. Retry resolves the
   same commit receipt and must not regenerate or substitute another candidate.

The receipt and Save integration are part of batch 3, not supplied by ledger
storage. No Save path is changed in the foundation batch.

## Scope and authority

No web retrieval, process-route synthesis, capacity claims, inferred staffing,
multi-transfer optimization, arbitrary-site solving, or brownfield preservation
is required here. The normal application and actual provider are required for
final acceptance, not for the foundation unit tests.

The existing MMLE planning package is illustrative/inferred/review-pending. It is
not proof of reviewed manufacturing inputs. Select a small assembly/staging/
inspection scenario, obtain applicable review records, and freeze exact source,
catalog, shell and policy revisions before the live acceptance run. Nominate a
quantity correction such as two to three assembly resources, only after proving
it fits. Two additional held-out feasible variants change dimensions and counts.
Synthetic fixtures remain explicitly unit-test evidence, not reviewed scenarios.

## Batch 1: guards and durable requirements

Owners: new `generation_requirements.py` and
`generation_requirement_repository.py`; reuse canonical layout functions,
operation validation, and `FacilityDesignRepository` storage/locking/pins.

- Guard all seven canonical collections, unknown root fields, and content-bearing
  extensions. Permit only validated `extensions.facilityPlan` settings. Preserve
  the exact approved shell/frame; this predicate does not validate the shell's
  physical coverage or grant authority to change it.
- Require exact saved/draft revision, a clean editor, and no pending or active
  generation/design transaction. Recheck at admission, operation acceptance and
  Apply when those adapters are connected.
- Reject clear, archive, deletion, navigation and other unqualified operations
  through an explicit first-slice operation allowlist. The existing kernel still
  validates operation fields and geometry; this guard does not replace it.
- Closed, bounded ledger: scoped identity, immutable base, source revisions,
  retained turns, exact text spans, typed requirements, explicit blockers and
  explicit supersession. Source-span coverage is structural evidence only; it
  cannot certify that a model understood every qualifier.
  Span offsets count Unicode code points, with an exclusive end. A browser
  adapter must convert UTF-16 selection offsets rather than silently reuse them.
- Initial executable requirement vocabulary: envelope dimensions, exact resource
  quantity, and unsaved preview. Extend the registry for mappings, departments,
  patterns and spacing before accepting those clauses in batch 2.
- Corrections append turns/requirements. Old requirements cannot disappear or be
  rewritten. Supersession must point to a new requirement in a new user turn.
- Persist immutable revisions and a CAS head using the existing site lock and
  atomic replacement. Commit retry identity in the same head update. Bound history
  and payload sizes. Pin referenced artifacts before publishing a new head.
- Keep ledger history durable without TTL in this slice. Retained revision pins
  survive run expiry/ordinary artifact collection. Deletion/retirement needs a
  separately implemented reference-aware protocol; do not release pins on expiry.

Exit: focused guards, schema, predicate, correction, concurrent-writer, retry,
fault-injection, corruption, namespace and retention tests pass. No chat tools,
HTTP routes, feature defaults, editor state or saved layouts change.

## Batch 2: package admission and isolated compilation

Owners: a planning admission service/tool adapter, `host.py` integration,
`facility_planning.py`, `program_execution.py`, immutable artifact repository.
Prefer adapters; do not replace existing compilers or weaken their contracts.

- Server resolves authenticated scope and authoritative source records. Model
  input cannot supply approval, confirmed review or production eligibility.
- Proposal requests include expected ledger revision and durable retry key.
  Execution accepts retained package ID plus exact revision, not an editable body.
- Bind eligibility to ledger, target base, sources, catalog, compiler and policy.
  Recheck source applicability and current revisions on execution.
- Validate ledger predicates against canonical package/program values; schema
  success alone cannot prove requirement compliance. Block unresolved clauses.
- Compile A and B against O. Replay operations through the existing kernel and
  dependency/spatial validation, and retain exact candidate and manifest receipts.
- All required checks must pass; unsupported/unknown is not pass. A failed B
  leaves O unchanged and A ineligible under the advanced ledger.
- Define one serialization boundary for correction head updates and Apply
  preparation. A correction committed first invalidates old adoption. An Apply
  prepared first must reconcile or abort before correction proceeds. Test both
  orderings and process failure between preparation and acknowledgment.

Exit: genuinely new packages compile without fixture coordinates. Forged
authority, wrong namespace, stale revisions, unsupported clauses and altered
artifacts fail closed. Preview has no write lease and no installation side effect.

Backend checkpoint: `generation_admission.py` now admits newly supplied packages
and compiles retained admissions into immutable candidates through the existing
engines. Its isolated HTTP actions are `admit`, `preview`, and `inspect`. The
new `generation_planning_preview` capability is off by default and depends on
`agent_preview`, not `agent_write`. That backend checkpoint did not include Sage
tool registration or draft installation. The subsequent preview integration below
adds gated Sage tools and candidate display, but still no draft installation.

The current admission vocabulary covers resource placement patterns, not cell
recipes or module replication; those arrays must be empty. Existing legacy
generation support is unchanged. This is an explicit coverage boundary, not a
claim that the legacy compilers cannot generate cells. Current preview limits
are eight departments, 24 resource batches, 120 placements and 500 cumulative
operations. Larger/reference-scale generation remains on its existing path.

Curator-only source publication records a prototype process/equipment mapping
assertion and re-resolves exact Process Maps and current eligible catalog assets.
It is not an automatic document-review or installed-machine feasibility service.
No real source context has been published by this implementation. The reviewed
scenario gate remains open.

Artifact publication and ledger corrections share a storage lock. The stronger
correction-versus-Apply preparation protocol remains a joint batch 2/3 gate:
this backend has no Apply action, reservation or writable lease. Do not infer
transaction qualification from successful preview publication.

## Batch 3: candidate UI and shared adoption

Owners: candidate-aware observation/preview adapter,
`static/facility_layout_workspace.js`, `static/facility_layout_session.js`,
transport, and shared `facility_draft_lease.py`/transaction machinery.

- Plan, 3D and queries read the same exact isolated candidate. Current, superseded
  and stale states are explicit. `installGenerationDraft` is not a preview API.
- Tool exposure, UI availability and execution independently check preview/write
  flags and actions. Apply requires `agent_write` before lease access.
- One exact Apply creates one unsaved reversible change. Capture existing editor
  frame fields: base/draft documents and revisions, batches/cursor, selection,
  generated draft, receipt IDs, proposal/transaction pointers, editor generation
  and journal hash. Preserve pending recovery metadata and Save gating.
- Camera/view is not part of document equality; specify its UI restoration policy
  before implementation rather than implying it is already in the editor frame.
- Preserve O/A/B recovery, lost acknowledgment handles, idempotent retry/reload,
  local Undo after authority loss and another writer's ownership.
- Implement and test the amended Save receipt contract in the separate Save case.

Exit: preview never mutates O; Apply/Undo restore the documented editor frame;
manual history survives where promised; only explicit Save persists.

Preview integration checkpoint (2026-09-17): four bounded Sage tools now inspect
reviewed context, record the actual user turn, compile an isolated package and
inspect its exact candidate. They are exposed only in explicitly selected
generation-planning mode behind `generation_planning_sage` (off by default).
Typed chat uses the existing provider loop; default tool discovery and legacy
generation do not receive these tools. Real HTTP integration has been exercised
with a synthetic provider, not a live model.

A source selector and shared Plan/3D candidate surface are implemented. Starting
a correction removes the old display; stale replies, changed source selection
and intervening editor changes cannot install it. The candidate is held outside
the session draft/history. Isolated Chromium checks cover desktop/narrow layouts,
nonblank Plan/3D output, camera movement and exact unchanged editor state.
No Apply/Undo/Save transaction is introduced by this checkpoint. Candidate
display qualification does not close the shared adoption or native-desktop gates.

## Batch 4: live qualification and promotion decision

Freeze prompts, reviewed evidence, independently feasible predicates, held-out
variants and numeric product latency thresholds before tuning. Record submission
to preview/corrected preview, provider/engine/render times and failures. Do not
reuse deterministic FDL latency as qualification of semantic planning.

Run actual normal-desktop chat through new package admission, candidate queries,
consequential correction, selection, Apply and Undo. Separately test Save and
reload on an isolated destination. Preserve complete immutable traces, provider
path, source hashes, manifests, validation/transaction receipts, screenshots and
saved hashes. Include negative language, real geometric refusal, stale sources,
permission revocation, concurrent writers and recovery faults.

Passing unit tests is not this milestone. Product-owner promotion remains an
explicit decision after all gates pass.

## Follow-on gates

Materialize canonical process bindings from actual generated occurrences,
reviewed Process Map nodes/edges, applicable catalog interfaces and valid routes
using `attach_process_binding`. Prove real FDL source admission before enabling
single-transfer optimization. Dirty-draft construction adoption, incremental
preservation and evidence acquisition remain separately qualified changes.

## Progress

- [x] Review decisions and Save amendment recorded in the project.
- [x] Batch 1 implemented and verified: 76 new and 54 adjacent tests passed.
- [ ] Reviewed live scenario and held-out cases frozen.
- [x] Batch 2 backend: dynamic admission, isolated compilation and regression checks.
- [x] Batch 2 Sage adapter: actual-turn tools and synthetic-provider HTTP verification.
- [ ] Batch 2 integrated qualification: live provider and shared Apply preparation.
- [x] Batch 3 isolated candidate UI: Plan/3D, stale-result protection and browser checks.
- [ ] Batch 3 shared Apply/Undo and Save qualified.
- [ ] Batch 4 actual provider/desktop acceptance and promotion decision.

Evidence and remaining boundaries:
[Foundation implementation report](sage-layout-first-slice-foundation-report.md).

[Admission/preview backend report](sage-layout-first-slice-admission-report.md).

[Sage tools and isolated candidate report](sage-layout-first-slice-sage-preview-report.md).
