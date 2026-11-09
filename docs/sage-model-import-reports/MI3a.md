# MI3a - chat attachment transport

## CHANGED

- server.py: added a closed ModelImportChatAttachment request type and a default-empty
  AgentChatRequest.attachments list (maximum three; exact mi-[0-9a-f]{24} IDs). Both HTTP
  transports and internal dispatch reject attachments outside Facility Layout Sage/Codex with
  attachments_unsupported (422). Scope resolution runs before the memory layer can start or
  replay a turn, and again at fresh pilot dispatch. The pilot receives resolved descriptions.
  Memory request identity and persisted user messages retain attachment IDs. Streaming error
  projection preserves attachment errors.
- ai_inspector/codex_runtime/chat_attachments.py (new): the two injectable host hook contracts,
  attachment identity projection, bounded/cleaned metadata, prompt JSON construction and receipt
  projection. File-derived data never enters system instructions or the fixed reference-data header.
- ai_inspector/codex_runtime/pilot.py: attachment IDs enter the journal request hash; all message
  branches carry attachedModels as JSON data when attached. Attachment-only turns get the neutral
  request "Review the attached 3D models." Successful results persist registeredAssets from host
  receipts, including turns with no attachments. A replay retains its original result/receipts.
- ai_inspector/memory/turn_lifecycle.py and ai_inspector/memory/policy.py: attachment-aware
  identity building and closed normalization, including the repository's second normalization pass.
  Empty/missing attachments preserve the existing frozen v1 hash exactly.
- tests/test_model_import_chat_transport.py (new): request validation, unsupported routes,
  missing/foreign IDs, validation before memory replay, server-to-pilot dispatch, metadata bounds,
  all four memory/selection combinations, attachment-only text, pilot hash conflicts and durable
  replay, registration receipts, memory identity/persistence, server lifecycle handoff and isolated
  payload copies. The server definitions are AST-loaded without importing its bootstrap; fake
  host/provider hooks and temporary SQLite roots avoid user data, credentials and network listeners.

MI1's files, the model_import package, static files and the prior MI2a changes were not edited.
No commits, branches, index changes, network access or package installs.

## TESTS

- Attempted through the hidden runner:
  C:/Python314/python.exe -B -m pytest tests/test_model_import_chat_transport.py -q -p no:cacheprovider --basetemp=C:/tmp/mi3a.
  Exit 1: No module named pytest. No tests were collected or executed.
- Compiled all six changed Python files with Python's compile(..., 'exec'): passed.
- git diff --check on the changed tracked files: passed.
- Byte checks: LF throughout all MI3a files; server's UTF-8 BOM retained; all newly written Python
  code and added server lines are ASCII.

## NOT RUN

- The new pytest suite and the related Codex route/pilot, memory-model, memory-lifecycle and
  memory-server regression suites require Claude's environment with installed dependencies.
- Browser, real server, real import store/registration integration and live inference: not run.
  MI3b owns the real hooks and tools.

## DEVIATIONS

- No functional deviations. Added a small dedicated module to keep server changes local.
- No existing hash fixtures needed updating: empty attachment lists deliberately preserve their
  previous identity, field order and hash. The new tests also assert the existing frozen fixture.
- The baseline server already contains eight non-ASCII literals (diameter/depth symbols and six
  cubic-unit labels, 18 UTF-8 bytes). They remain byte-identical to HEAD; unrelated strings were
  not rewritten. Every MI3a addition is ASCII and the BOM is preserved.

## OPEN QUESTIONS / MI3b HANDOFF

No blocking questions. MI3b must implement these synchronous attributes on host.agent_runtime:

1. describe_model_attachment(principal, binding, import_id) -> dict | None.
   binding is a dict containing tenantId, principalId, siteId, layoutId, and the starting
   layout revision. Tenant/principal come from the host-resolved principal; the layout reference
   is normalized and authorized with read_bound_layout before the resolver is called. Return
   None for missing or foreign IDs, never a distinguishable cross-scope error. An absent hook
   also fails closed with model_import_not_found (404). The hook may be called twice for a fresh
   memory-backed turn: before memory replay lookup and at actual pilot dispatch. It must be read-only.
   Return name, format, megabytes, state, and refusal; the supplied import ID is authoritative
   and extra metadata is not projected. Names lose paths/control characters and are capped at 80
   characters. Refusal may be null, a string, or a code/message object; text is bounded and remains data.
2. registrations_since(binding, started_at) -> list[str].
   The same scope dict is passed; started_at is Unix wall-clock seconds captured before the pilot
   begins its journaled turn. Return asset IDs from scoped registration receipts. IDs are deduplicated
   in order. Without this hook successful turns report an empty array. Model prose cannot populate it.
   Completed replay results retain the original array without consulting current receipts. Failed or
   interrupted turns do not claim successful registrations; MI4's unconditional catalog refresh handles
   assets published before those outcomes.

Attachment order is retained in both identities ("the first model" can be meaningful). Changing order,
adding/removing an ID, or replacing an ID conflicts with an existing turn ID. Mutable metadata is excluded
from the identity. No registration, worker, authoring or placement tools were added in MI3a.
