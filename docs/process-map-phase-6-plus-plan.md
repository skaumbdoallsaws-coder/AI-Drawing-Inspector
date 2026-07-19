# Process Map Phases A-F - Intelligence, Identity, and Management Plan

Status: revision 2 - APPROVED IMPLEMENTATION CONTRACT (2026-07-16).
Baseline: commit c0c2ccc (complete process map authoring workspace).
Incorporates all eleven binding corrections from the approval review.
Nothing in this document is implemented yet.

Frozen regression bars at baseline, independently reproduced:
- Backend/schema: 39/39 (test_process_map_validate.py +
  test_process_map_endpoints.py + test_process_map_schema_v3.py)
- Editor node suite: 34/34
- Floating-surface node suite: 14/14
- Process-flow Playwright smoke: 53/53
These bars stay green, untouched, through every phase. New capability
means new tests; existing tests change only when a correction explicitly
requires it (none do).

## 0. Approval record (eleven binding corrections)

1. mapId is not greenfield. `migrate_to_placement_map` already stamps
   `mapId: "default"` (schema_v3.py:335, :408). "default" is preserved as
   the adopted legacy map identity and its semantics evolve in place; only
   NEW maps receive generated IDs.
2. The revision is never persisted inside the asset. It remains a
   server-derived SHA-256 CAS token over the stored content, returned in
   responses and compared on writes. `createdAt`/`updatedAt` are stored in
   the asset but are server-owned: PUT/create/duplicate ignore any
   client-supplied values and the server stamps them.
3. Group schema compatibility is explicit. `canvasGroups` ships additively
   on schema v3 WITH `layoutVersion` advancing 1 -> 2 as the version
   signal, plus round-trip tests proving assets with missing/older group
   fields load and save without loss. No silently added persisted
   semantics.
4. Default-map resolution never depends on directory scanning. The legacy
   endpoint targets the adopted `mapId: "default"`; an explicit, atomically
   written registry pointer records `defaultMapId`. Directory scanning is
   for LISTING maps only, never for deciding which map is authoritative.
5. The analysis digest is trusted server context. The browser sends only
   `{productId, mapId, revision}`. The server loads that exact revision,
   validates it, and compiles `process_map.graph` itself. A
   browser-supplied digest is never accepted as authoritative.
6. Router generalization covers the full second-workflow surface: prompt
   composition, workflow-state continuity, context providers, fallback
   behavior, tool/executor dispatch, and safe compilation - not just the
   three named hardcoded sites. Existing FAI routing fixtures and
   compiled-prompt fixtures must remain unchanged (byte-identical
   compiled output) after the second workflow lands.
7. Ghost suggestions are versioned. `suggestionId` incorporates rule ID,
   rule version, evidence fingerprint, and endpoints. A dismissal
   suppresses only that identity; materially different future evidence
   produces a new ID that reappears. Shared equipment yields a
   resource-contention CANDIDATE, never precedence, unless another
   evidence source supplies ordering.
8. Builder write authorization is a permanent asset-write gate, separate
   from viewport authorization. Every write follows
   propose -> validate -> exact-diff approval -> CAS apply. The approval
   binds mapId, baseRevision, diff hash, user/session, and an idempotency
   key; apply rejects on any mismatch or replay.
9. Revert is not "restore newest backup." Revert targets a NAMED prior
   revision (or execution receipt) and creates a new forward revision
   through CAS, so concurrent Builder and editor changes can never
   restore the wrong asset.
10. Global templates live in product-neutral storage, not under one
    product's map directory. Cloning regenerates node, edge, group,
    junction, and logical-connection IDs.
11. Grouping interaction is disambiguated: group layers are sibling
    layers inside the transformed world; frame bodies use
    `pointer-events: none` with only headers, borders, and resize handles
    interactive; membership commits on pointer-up; overlapping frames
    resolve to the smallest containing frame; a toolbar command provides
    the alternative to Alt-drag.

Deferral note: collapsed groups may be deferred out of Phase A without
renegotiating this contract.

## Baseline verification notes (c0c2ccc)

- Schema v3 placement model confirmed: `canvasNodes`
  (product_occurrence | process_step | junction), `canvasEdges` with
  `logicalConnectionId`, immutable `productStructure.occurrences`
  (occurrenceId, parentOccurrenceId, itemId, kind, level, partIds,
  carried suggestedBuildOrder/purpose), `referenceCatalog` with kinds
  machine/tool/requirement/standard, caps 24 per target and 500 catalog
  items, and the rule that junctions cannot carry references.
- `PROCESS_STEP_TYPES` = operation/inspection/decision/input/output;
  assembly/subassembly are PRODUCT kinds. All later phases speak the v3
  vocabulary.
- Dual revision checking already exists: map revision plus
  `sourceStructureRevision` (repository.py:286).
- `mapId: "default"` and `layoutVersion: 1` already exist in migration
  output (schema_v3.py:335/338/408/412). `canvasGroups` has zero hits -
  groups are greenfield; identity is adoption, not invention.
- Evidence asymmetry: functional relationships are implemented only for
  engine assembly 100001; racing-bike has no mates/functional assets.
  Ghost evidence adapters must no-op silently per product.
- Single-workflow assumptions live at routing.py:172 (catalog prompt),
  executors.py:186, server.py:19030, plus the broader surfaces named in
  correction 6.
- Working tree carries unrelated uncommitted streaming work in server.py
  and index.html; every phase commits with scoped hunks.

## Phase A - Grouping frames

Data model (additive on schema v3; `layoutVersion` 1 -> 2 per
correction 3):

    canvasGroups: [{
      groupId, label (max 120), description (optional),
      position {x, y}, size {width, height},
      colorKey (palette token, not raw color),
      memberNodeIds: [canvasNodeId...],
      collapsed: false
    }]

- Non-topological by construction: the validator never feeds groups into
  cycle/edge/reference checks. Group findings: `dangling_group_member`
  (error), `node_in_multiple_groups` (error), `empty_group` (warning).
- Membership lives only on the group (no groupId on nodes - no
  dual-write). A node belongs to at most one group. Junctions may be
  members and move with the frame.
- No nesting in v1. Frames may visually overlap; there is no
  group-in-group semantics. Overlap resolution for membership drops is
  deterministic: the smallest containing frame wins (correction 11).
- Compatibility tests (correction 3): a layoutVersion-1 asset without
  canvasGroups loads, edits, and saves losslessly at layoutVersion 2; a
  layoutVersion-2 asset with groups reloads byte-stable; a
  layoutVersion-2 asset opened by any code path that predates groups is
  out of scope (single-app deployment) but the loader tolerates unknown
  group fields by preserving them.

Rendering and interaction (correction 11):
- `.pm-group-layer` is a sibling layer inside the transformed
  `.pm-world`, below the edge SVG and node layer. Z-order:
  groups < edges < nodes < selection artifacts.
- Frame bodies are `pointer-events: none`. Only the header (title bar),
  borders, and resize handles are interactive, so clicks and drags inside
  a frame body always reach nodes and canvas panning.
- Header drag moves frame plus members as ONE mutation; Alt-drag moves
  the frame only; the group toolbar carries an explicit "Move frame only"
  toggle as the keyboard-free alternative (correction 11).
- Membership changes commit on pointer-up (correction 11): dropping a
  node whose center lands inside a frame joins it; dragging out leaves.
  No mid-drag membership churn.
- Selection: click header. Group toolbar rides the existing
  floating-surface manager (rename, recolor via fixed palette, move-only
  toggle, collapse if shipped, delete). One-active-surface rule already
  enforced; card and group toolbars never coexist.
- Delete removes the frame only, never members. All group mutations are
  pure ops through `commitMutation` (undo/redo/dirty/save inherited):
  addGroup, moveGroup(withMembers), resizeGroup, renameGroup,
  recolorGroup, setGroupMembers, deleteGroup.
- Colors: fixed ~8-key palette as CSS custom-property pairs for both
  themes (`--pm-group-<key>-bg/border`); assets store the key.
- Cross-group edges, junction drops, wire splitting, pan/zoom, drag/drop
  placement, validation, and 3D preview are unaffected. The group layer
  lives inside `.pm-world`, so the existing transform covers it.
- Collapse (deferable): visual pill only - frame shrinks to header,
  members hidden, edges to hidden members hidden behind a count badge;
  data model untouched beyond the `collapsed` flag.

Tests: node op purity + single-membership invariant + smallest-frame
resolution; backend validator matrix + layoutVersion round-trips;
Playwright: create/rename/recolor/resize/move-with-members/move-only
(toolbar and Alt)/join-leave on pointer-up/overlap targeting/delete keeps
nodes/undo chain/body click-through/z-order/save-reload/both themes.

## Phase B - Map identity foundation

Identity: `mapId` immutable. The adopted legacy map keeps
`mapId: "default"` (correction 1); new maps get `pm-<8 random hex>`.
Metadata block inside the asset: `displayName`, association
`{productId, assemblyId?, configuration?}`, `status:
draft|active|template|archived`, `createdAt`, `updatedAt` (server-owned,
UTC ISO; client-supplied values ignored - correction 2).

Revision (correction 2): NOT a stored field. It remains the server-derived
SHA-256 of the canonical stored asset, returned by GET/PUT/create and
required as the CAS token on every write. Metadata edits flow through the
same PUT and bump the same token. `sourceStructureRevision` checking is
unchanged.

Layout and registry (correction 4):
- `generated/training/<productId>/process_maps/<mapId>.json`.
- `generated/training/<productId>/process_maps/registry.json` - an
  explicit, atomically written (temp + os.replace, same machinery)
  pointer file: `{registryVersion, defaultMapId, maps: [...summary]}`.
  The registry decides which map is authoritative for the legacy alias;
  directory scanning is used only to build LIST responses and to detect
  drift (a scan/registry mismatch is a surfaced warning, never silently
  resolved).
- Migration on first registry access: the existing working-draft asset is
  adopted as mapId "default", moved/registered, `defaultMapId: "default"`
  written. Legacy `/api/training/process-map/{productId}` GET/PUT becomes
  an alias for the registry's defaultMapId; existing contracts, tests,
  and the 39/39 + 53/53 bars stay green unmodified.

API (same flag, validators, 409/422 semantics):
- GET `/api/training/process-maps/{productId}` - list (registry +
  scan-verified), archived excluded by default.
- POST `/api/training/process-maps/{productId}` - create blank or
  `duplicateOf: mapId` (server stamps identity + timestamps; duplicate
  regenerates nothing in v1 since it stays same-product).
- GET/PUT `/api/training/process-maps/{productId}/{mapId}`.
- POST `.../{mapId}/archive` - status change. No hard delete.

Product structure stays the per-product sidecar shared by all maps.
Map switching runs the existing confirmDiscard dirty guard; stale-revision
handling is per-map CAS, already built. Builder precondition satisfied:
every future write names `{mapId, baseRevision}`.

## Phase C - Sage analyze-process-map

Skill package `ai_inspector/agent_skills/analyze-process-map/`
(manifest.yaml + contract.yaml + SKILL.md, loader-validated, following
the existing schema exactly):
- manifest: agents [sage]; workflows [process-map-analysis] (the second
  workflow); modes [training]; requires_context [process_map.graph];
  side_effects []; evidence_policy computed_fields_only.
- contract: side_effect_policy.default prohibited; failure_behavior
  missing_required_context -> report_missing_evidence,
  contradictory_context -> abstain_and_report_conflict; context_budget
  maximum_tokens 3500, priority process_map.graph.

Trusted server digest (correction 5):
- Browser sends ONLY `{productId, mapId, revision}` with the analyze
  request. The server resolves the map through the registry, verifies the
  stored revision matches the named one (mismatch -> the same 409-style
  conflict surface; the UI prompts reload/save), validates the asset, and
  compiles `process_map.graph` server-side in
  `ai_inspector/process_map/digest.py`. No browser-supplied digest is
  ever trusted. The Analyze button save-guards first so the named
  revision reflects what the user sees.
- Digest content (deterministic, bounded <= 3500 tokens, stable
  ordering, top-N truncation with "and N more"): identity {mapId,
  displayName, productId, revision, structureRevision}; nodes (id, kind,
  processType or occurrence name, group); groups (label, member count);
  logical connections (junction chains collapsed by logicalConnectionId,
  junction count); typed edges by kind; references aggregated per target
  as kind:name; validator findings; derived facts computed in Python:
  entry nodes, terminal nodes, weakly connected regions, fan-in >= 3
  emitted as `bottleneck_candidates`, parallel branch sets, precedence
  cycle report. Golden tests pin digest output for fixture maps.

Router generalization (correction 6 - full surface, shadow-first):
- Catalog prompt composition (routing.py:172 single-workflow text becomes
  workflow-enumerated), workflow-state continuity (workflow_state
  isolation and continuation semantics keyed per workflow), context
  providers (process_map.graph registered alongside existing providers),
  fallback behavior (no-route and invalid-route paths re-verified with
  two workflows), tool/executor dispatch (analyze has NO executors;
  dispatch stays fail-closed per workflow id), and safe prompt
  compilation.
- Frozen gate: existing FAI routing fixtures pass unchanged, and
  compiled FAI prompt fixtures remain byte-identical after the second
  workflow registers. This is a named checkpoint artifact, not a hope.
- Routing eval: analyze positives, FAI negatives, clarification case
  added to skill_route_cases.json; existing thresholds hold.

SKILL.md behavioral contract: "bottleneck candidate" language mandated
(no timing/capacity/utilization evidence exists in the repo); compare
authored sequence vs suggestedBuildOrder where present; cite nodeId +
name; never invent takt times or costs; empty canvas or missing map ->
report_missing_evidence; digest/revision mismatch ->
abstain_and_report_conflict.

UI: one "Analyze flow" button in the flow header -> save-guard -> one
normal Sage turn. Eval fixtures: three synthetic placement maps (linear;
diamond with fan-in + parallel branches; broken with cycle + disconnected
region) with labeled expected derived facts; one live operator eval per
the eval_skill_route_shadow.py pattern.

## Phase D - Ghost connections

Engine: `ai_inspector/process_map/suggest.py`, deterministic, read-only,
exposed via GET
`/api/training/process-maps/{productId}/{mapId}/suggestions?revision=...`
computed against the named revision. Non-mutating until accepted.

Evidence adapters (each optional per product; absent evidence is a
silent no-op): authored-precedence patterns; containment (same-parent
placed siblings); mates/functional relationships (engine 100001 only
today); suggestedBuildOrder; shared machine/tool references;
process-step compatibility (inspection-after-operation on the same
occurrence chain).

Hard rules:
- BOM guardrail: containment or build-order evidence ALONE never yields a
  precedence suggestion; it must corroborate at least one other class.
- Resource rule (correction 7): shared equipment produces a
  `resource_contention` candidate annotation, never a precedence wire,
  unless another evidence source supplies ordering.

Suggestion identity (correction 7):

    suggestionId = hash(ruleId, ruleVersion, evidenceFingerprint,
                        fromId, toId, edgeKind)

where evidenceFingerprint hashes the specific evidence rows that produced
the suggestion. Dismissals (persisted as
`dismissedSuggestions: [suggestionId]` in the map asset - an undoable,
revision-aware mutation) suppress exactly that identity. New or changed
evidence, or a rule-version bump, yields a new ID that legitimately
reappears. Tests pin: same input -> same IDs; changed evidence -> new ID;
dismissal survives reload and does not suppress the new ID.

Record: `{suggestionId, edge {from, to, kind} | annotation, confidence
tier, provenance [{source, ruleId, ruleVersion, detail, ids}],
explanation, validation {wouldCreateCycle, duplicateOfExisting},
affectedIds}`. Pipeline: generate -> suppress duplicates of existing
edges/logical connections -> suppress dismissed identities ->
per-suggestion cycle check -> rank, cap ~20.

UI: dashed ghost layer under real edges; accept = existing addEdge via
commitMutation (undoable); dismiss = mutation as above; batch accept =
one mutation applying in rank order with cumulative cycle re-check,
skipped items reported; suggestions fetched for revision R are discarded
on conflict/reload.

## Phase E - Builder generation and editing

Domain-operation boundary: `ai_inspector/process_map/operations.py`.
Builder never writes JSON or files. Registered ops mirror the editor's
pure ops server-side: place_occurrence, add_process_step, add_junction,
move_node, retype_step, set_port_layout, set_label, set_note, connect,
split_edge_with_junction, delete_node, delete_edge, add_group,
set_group_members, edit_group, delete_group, attach_reference,
detach_reference (reference ops respect the junction prohibition and the
24/500 caps). Unknown op -> reject. Op batches are all-or-nothing: apply
in memory -> full validator -> any structural error writes NOTHING.

Write authorization (correction 8): a permanent asset-write gate,
separate from viewport authorization, with its own deterministic
predicate and its own committed fixture file (same parity discipline as
viewport authorization). LLM/classifier output can REQUEST an op batch;
only the gate plus explicit approval AUTHORIZES it. Initial protocol for
every write:

1. propose_operations(mapId, baseRevision, ops[]) -> {diff, diffHash,
   findings, wouldSave} - dry-run, no write, ever.
2. Exact-diff approval: the user approves the rendered diff. The approval
   token binds {mapId, baseRevision, diffHash, user/session,
   idempotencyKey}.
3. apply_operations(approvalToken) -> CAS apply: rejects if mapId,
   baseRevision, or diffHash mismatch the current state or the token;
   rejects idempotencyKey replays; atomic save through the existing
   repository with one backup; returns the new revision.

Revert (correction 9): `revert_to_revision(mapId, targetRevision,
baseRevision)` - the target is a NAMED prior revision resolved through
the backup index (backups become revision-addressable: each backup
records the revision of the content it holds) or an execution receipt.
Revert materializes the target content as a NEW forward revision through
the same CAS apply path (propose/approve/apply). "Restore newest backup
file" does not exist as an operation.

Read/locate tools: list_process_maps(productId), read_process_map(mapId),
find_nodes(mapId, query) covering nodes, groups, edges, references,
validate_process_map(mapId), show_diff. Generation is composition: a
drafted flow is an op batch (optionally seeded by Phase D's corroborated
suggestions) through the same propose/approve/apply gate. Writes sit
behind `INSPECTORPRO_BUILDER_WRITE`, separate from the editor flag.

## Phase F - Multi-map and template management

Map switcher in the flow header over Phase B's API: list with status
badges, create, duplicate, rename, archive; dirty guard on switch is
Phase B machinery.

Templates (correction 10): product-neutral catalog at
`generated/training/_templates/process_maps/<templateId>.json` - never
under a product's map directory. A template is a process skeleton:
process steps, junctions, edges, groups, references; NO product
occurrences (which is what makes it cross-product without a rebinding
wizard). Instantiation clones the skeleton into a target product draft
and regenerates ALL identifiers - node, edge, group, junction, and
logicalConnectionId - via a deterministic remap table so no two maps
ever share IDs. Save-as-template strips occurrences and their edges,
reporting what was dropped. Same-product occurrence-bearing duplication
remains Phase B's duplicateOf. Archived maps: hidden from default list,
readable, never hard-deleted. Occurrence rebinding wizard: explicitly
out of scope until demanded.

## Cross-cutting discipline

- Frozen bars (39/39, 34/34, 14/14, 53/53) stay green untouched.
- Commit-per-phase checkpoints with scoped hunks (the tree carries
  unrelated streaming work in server.py/index.html).
- ASCII-only assets and code; canonical serialization unchanged.
- Flags: editor surfaces stay behind INSPECTORPRO_PROCESS_MAP_EDIT;
  Builder writes behind INSPECTORPRO_BUILDER_WRITE.
- Playwright additions ride the hermetic synthetic-route pattern; real
  server coverage only where persistence is the subject.

## Checkpoint artifacts per phase

- A: group op node tests + validator matrix + layoutVersion 1->2
  round-trip proofs + ~14 Playwright cases (incl. body click-through,
  pointer-up membership, smallest-frame overlap targeting, toolbar
  move-only).
- B: migration test proving the legacy alias byte-compatible; registry
  pointer atomicity test; server-owned timestamp test (client values
  ignored); new endpoint suite; scan/registry drift warning test.
- C: digest golden tests; trusted-context test (server rejects analyze
  for a stale named revision; browser-supplied digest ignored); routing
  eval green at existing thresholds; FAI compiled-prompt fixtures
  byte-identical post-registration; one live analyze turn.
- D: determinism tests (same input -> same suggestionIds); versioned
  dismissal tests (changed evidence -> new ID reappears); BOM-guardrail
  and resource-rule negative tests; accept/dismiss/batch Playwright.
- E: gate fixture + parity tests; propose-never-writes property; failed
  batch writes nothing; approval binding rejects mapId/revision/diffHash
  mismatch and idempotency replays; revert-to-named-revision creates a
  forward revision and rejects stale CAS.
- F: template catalog isolation test (nothing written under products);
  ID-regeneration test (zero shared IDs between template and instance);
  switcher + template clone Playwright.
