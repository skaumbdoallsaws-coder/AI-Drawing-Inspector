# Sage objective-to-layout: foundation implementation

Date: 2026-09-17

Status: Batch 1 implemented and unit/regression verified. The objective-to-layout
workflow is not yet connected to Sage or the editor and is not promoted.

Subsequent checkpoint: [Admission and isolated preview backend](sage-layout-first-slice-admission-report.md).
The inventory below describes the original foundation batch, not the latest
completion state.

## Changes

- `generation_requirements.py`: new-empty-layout guard covering all seven
  canonical collections, understood settings, revision/editor conditions and a
  per-kernel-batch operation allowlist. Replacement, clearing, deletion and other
  unqualified operations remain unsupported on this new path.
- The same module supplies a closed generation ledger with bounded payloads,
  exact retained text spans, revision hashing, explicit blockers and append-only
  corrections. Superseded requirements retain their original meaning and point
  to a new user-turn requirement. Unsupported predicates cannot claim to pass.
- Initial predicate checks compare exact resource quantities and unit-normalized
  envelope dimensions, plus the unsaved-preview policy. These checks explicitly
  return `admissionGranted: false`; they do not validate engineering authority,
  physical fit or operation-to-equipment applicability.
- `generation_requirement_repository.py`: typed ledger storage reusing the
  existing design repository's site lock, atomic writer, immutable artifacts and
  retention pins. A single head update commits the ledger and retry receipt.
  Canonical object-key ordering permits equivalent retries; array order remains
  significant. Conflicting retries and stale writers fail closed.
- Ledger path components are content-derived, so IDs containing colons or Windows
  reserved device names cannot become NTFS stream selectors or device paths.
- Revision-owned artifact pins precede head publication. A failure before commit
  may conservatively retain extra data, but cannot expose an uncommitted revision
  as current. Old retries return the original revision and disclose supersession.

No existing application module, feature default, API route, layout, catalog,
Process Map or Save implementation was edited. New modules are not registered as
live tools. These are callable foundation contracts, not already active guards
on every legacy generation path.

## Verification

Command run in the project root:

```powershell
python -m pytest tests/test_facility_generation_requirements.py tests/test_facility_layout_design_loop_contracts.py tests/test_facility_layout_facility_planning.py tests/test_facility_layout_planning_generation.py -q -p no:cacheprovider --basetemp=.runtime/generation-requirements-verified-tests --junitxml=.runtime/generation-requirements-verified-tests.xml
```

Result: **130 passed in 18.61 seconds**.

| Suite | Passed |
| --- | ---: |
| New generation requirements/storage | 76 |
| Existing design-loop contracts | 44 |
| Existing facility planning | 7 |
| Existing planning generation | 3 |

Evidence is in `.runtime/generation-requirements-verified-tests.xml`. An earlier
new test failed because its envelope request used `unit` rather than the existing
compiler's `sourceUnit`; the fixture was corrected without changing the compiler.
The ambient LangSmith plugin emitted its existing Python 3.14/Pydantic-v1 warning.

Covered: all nonempty collections, unknown extensions, dirty/active editor state,
stale revisions, forbidden operations, the existing 500-operation batch budget,
closed schema, unresolved text spans, predicate conflicts, quantity/dimension
bounds, explicit correction, namespace and digest checks, durable retries after
repository reconstruction, concurrent repository instances, failure before head
publication, failure after commit before response, missing dependencies, retained
artifact collection, corrupted records, Windows-safe IDs and revision budgets.

The kernel smoke test uses real G1 envelope operations and the operation kernel,
asserting a changed candidate revision and unchanged original document. It is
not a complete factory compilation, candidate UI test or manufacturing fixture.
Concurrency uses independent repository instances in threads; interruption tests
inject failures at the actual atomic-write boundary. Native process termination,
distributed filesystems and Electron recovery are not claimed by these tests.

## Deliberately unfinished

1. Reviewed scenario, asset/source applicability audit and held-out live prompts.
   Existing illustrative MMLE inputs are not promoted to reviewed evidence.
2. Server-authorized package admission, authenticated tools, complete supported
   generation vocabulary, exact-source resolution and execution eligibility.
3. Guard wiring before admission/operation acceptance/Apply; authenticated editor
   capture and authoritative active-owner lookup. Caller-provided context alone
   is not a trusted authorization source.
4. Full package/program compilation, dependency/spatial validation and isolated
   candidate manifests. Predicate checks alone are not candidate qualification.
5. Candidate-aware Plan/3D/query integration, shared Apply/Undo ownership,
   correction-versus-Apply serialization, pending acknowledgment recovery and
   the amended Save commit receipt.
6. Actual provider/normal-desktop conversation, numerical latency gates and
   product-owner promotion.

The point-in-time `require_current_ledger` check is not an Apply reservation.
Span coverage proves only that stored text is accounted for structurally; it
cannot prove complete semantic interpretation. Span offsets use Unicode code
points, not JavaScript UTF-16 offsets. These boundaries must remain explicit in
the next adapters and language acceptance tests.

Ledger revisions/pins intentionally have no automatic expiry in this slice.
Administrative retirement and reference-aware cleanup are separate work; do not
release pins merely because a generation run expires.

## Next implementation batch

Implement batch 2 of
[the project plan](sage-layout-first-slice-implementation-plan.md): a bounded,
server-authorized package admission adapter over exact ledger/source revisions,
followed by isolated compilation using the existing engines. Preserve all
existing allowlists, FDL vocabulary and construction ownership restrictions.
