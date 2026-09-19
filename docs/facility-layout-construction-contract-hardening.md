# Facility Construction Contract Hardening

Date: 2026-09-12

Status: first execution-contract slice implemented and tested. This is not a
claim that a live Sage conversation can execute the new adapter, or that a
complete agent-generated factory has passed browser acceptance.

## Scope

The published command knowledge and the existing JavaScript geometry builders
previously used different parameter names, defaults, and limits. This change
gives four commands a shared, closed input schema and an explicit adapter.
It reuses the current builders, session journal, preview path, and Undo.
There is no second layout engine and no new Save path.

| Command | Contract and translation |
| --- | --- |
| Linear Pattern | Explicit seed IDs, total count 2-50 including the original, positive spacing, direction, and source unit. Spacing becomes builder pitch, not edge clearance. |
| Cell Layout | Explicit placement IDs, supported strategy, width/depth, gap, rows, orientation, angle, and U inversion. The center comes from the selected equipment, not model-authored coordinates. |
| Create Cell | Explicit placement IDs and series label, numeric envelope padding, source unit. Existing geometric membership and numbering are retained; the series begins at 01. |
| On Surface | Explicit support, children, published surface ID, side, gap, item gap, inset, and source unit. Top/bottom translate to the builder's above/below. |

Asset placement remains the existing session/semantic-placement functionality.
The integration fixtures use explicit trusted seed positions; this pass does
not give Sage authority to invent placement coordinates.

The shared schema is
`static/contracts/facility-construction-commands-v1.json`.
`knowledge_foundation.py` publishes it through the existing command registry;
`query_command_prerequisites` returns that same schema. Generic ID arrays and
asset-search fields also receive explicit item/value types.

## Execution Boundary

`static/facility_layout_command_adapter.js` provides normalization, translation,
and revision-bound execution. `Workspace.executeConstructionCommand(request)`
loads the contract and delegates to that adapter when manual authoring is
available. The adapter never reads the dialog's last-used parameters or uses
the current selection to substitute for requested IDs.

Example local host request, with IDs and revision obtained from the session:

```javascript
await workspace.executeConstructionCommand({
    commandId: 'linear-pattern',
    requestId: 'repeat-assembly-001',
    expectedDraftRevision: currentDraftRevision,
    arguments: {
        seedIds: [sourceCellId],
        count: 3,
        direction: 'north',
        spacing: 15,
        sourceUnit: 'm'
    }
});
```

This is a local programming interface, not a newly exposed Sage tool or a chat
prompt. Sage's existing semantic-plan preview and permission checks remain in
place. An agent host must still bind authorization and approved targets before
calling any mutation boundary. The manual-authoring flag is not agent-write
authorization.

Coordinates use the existing meter-based X/Z floor and +Y up convention.
The existing builder's positive 90-degree yaw points toward -Z. For compatibility,
horizontal maps to +X and vertical to -Z; explicit north is +Z, south -Z,
east +X, and west -X. Units accepted: m, mm, ft, in.

## Failure and Recovery Rules

- Unknown fields, omitted required inputs, invalid types/counts/units, and
  non-finite numbers reject before a session edit.
- Unknown entities, routes used as seeds, locked equipment, stale/missing
  catalog revisions, and missing published dimensions reject.
- Surface attachment requires a real published surface. No object-bounds
  fallback supplies missing surface evidence.
- A selected attachment must include its support, and selected supports must
  include their attached children. Cell Layout must run before attachment.
- Vertical stacks and detected nested-zone repetition are unsupported in this
  slice and reject rather than silently dropping relationships.
- Create Cell rejects an envelope that would capture unselected placements or
  markings. Membership still follows the existing geometric membership model.
- Execution checks the exact draft revision and pending-edit state. A repeated
  request ID with the same payload returns its cached receipt only while the
  resulting draft/journal/editor-generation fingerprint still matches. A changed
  payload conflicts; a changed draft requires a fresh request. Request signatures
  recursively sort object keys and preserve array order, so reordering JSON keys
  is an equivalent retry but reordering selected IDs remains a different request.
- The adapter retains at most 128 receipts for its lifetime. Receipt recovery
  across page reload, process loss, or a new adapter instance is **not** provided.
- Existing session preview failures leave the local journal unchanged. Each
  successful command remains one ordinary Undo gesture. Nothing auto-saves.

Receipts contain created/changed IDs, resulting draft revision, and new cell IDs
with their geometric member IDs. They identify the validation scope as session
preview, not manufacturing, collision-safety, or production approval. They do
not substitute for the existing authoritative spatial-analysis tools.

## Verification

Focused Python run: **72 passed** across construction contract, knowledge
foundation, tool knowledge, agent runtime, and semantic-plan suites.

JavaScript suites:

| Suite | Passed checks |
| --- | ---: |
| Construction adapter | 8 |
| Existing patterns | 23 |
| Session, including construction workflow, retry ordering, and preview failure | 59 |
| Workspace, including contract loading and delegation | 81 |
| Transport | 26 |

The conformance tests use independent Python JSON Schema validation and the
JavaScript adapter over valid, invalid, missing-field, whitespace, and boundary
inputs. Geometry tests compare adapter output with existing manual builders,
including the originally reported vertical/5 m regression.

The real-kernel integration runs the actual JavaScript session and builders
against `apply_facility_layout_operations` on in-memory fixture documents:

1. Place two tables and one device using trusted fixture positions.
2. Arrange the tables, then attach the device to a published worktop.
3. Create one cell and repeat it to three total cells.
4. Verify nine placements, three cell zones, and copied attachments pointing to
   the copied supports with preserved asset revisions.
5. Retry, including reordered request/argument keys, without another preview or
   duplicate placements. Separately verify changed array order and changed values
   conflict in the session regression.
6. Undo the repetition, then all earlier gestures, restoring the starting draft.
7. Assert each edit advances the draft revision, an earlier revision rejects a
   fresh command before preview, and Undo restores the corresponding revision.
8. Assert zero Save calls and unchanged base revision.

### Review Follow-Up

Both reported issues were reproduced by failing regressions before applying the
fixes. The earlier real-kernel fixture returned the base revision alongside its
edited document; it therefore did not establish advancing draft revisions.
It now returns `layout_revision(result["document"])` while retaining the original
base revision for journal replay. The corrected run records six distinct draft
revisions across the initial state and five edits, rejects a stale-revision new
command without changing state or making another preview call, and restores the
original draft revision on complete Undo.

The full focused rerun passes **72 Python tests and 197 JavaScript checks**.
The real-kernel workflow also passes independently, with 10 kernel previews and
zero Save calls. These fixes do not change the live-agent promotion boundary.

This tests actual operation-kernel compatibility, canonicalization, identity,
and session restoration. It is not a live service/catalog spatial-clearance or
Sage-provider acceptance test. The manual reference layout is not used as a
write target.

The catalog pagination regression now compares against the fixture host's asset
count instead of assuming that the evolving local catalog always has four items.
Stage knowledge remains inside its existing byte budget by omitting duplicated
description text, not by dropping input fields or raising the limit.

## Reproduce

Install the independent schema validator in the test environment:

```powershell
python -m pip install -r tests/requirements-construction-contract.txt
python -m pytest tests/test_facility_layout_construction_contract.py tests/test_facility_layout_knowledge_foundation.py tests/test_facility_layout_tool_knowledge.py tests/test_facility_layout_agent_runtime.py tests/test_facility_layout_semantic_plan.py -q
node tests/test_facility_layout_command_adapter.js
node tests/test_facility_layout_patterns.js
node tests/test_facility_layout_session.js
node tests/test_facility_layout_workspace.js
node tests/test_facility_layout_transport.js
```

Node must be on PATH. The Python test passes its interpreter to the Node/real-
kernel integration fixture. This execution installed test-only dependencies
under `.runtime/command-contract-deps` and supplied that folder via PYTHONPATH;
it did not change the application's installed dependencies.
That private dependency directory is not a prerequisite for independent review:
install the pinned test requirements above into the reviewer's own Python
environment. No test hard-codes the private directory. The follow-up run needed
approved access to that existing directory to run both schema-specific tests.

## Remaining Before Live-Agent Promotion

- Connect the explicit command request to an authorized Sage proposal path;
  do not expose the local manual bridge as unrestricted agent-write access.
- Carry the host's durable idempotency and exact proposal-approval bindings
  through that path; the adapter's in-memory retry cache is not a replacement.
- Test a real chat request through preview, inspected geometry and relationships,
  approved unsaved application, and Undo in the browser.
- Benchmark growing operation journals before claiming large-build latency.
- Extend explicit schemas and behavior tests to other ribbon commands separately.

No live-provider timing, browser screenshots, full-factory generation, or
production promotion is claimed by this report.
