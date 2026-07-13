# Process Map Flow Editor (n8n-style) - Implementation Plan

Status: revision 2 - PHASE 1 IMPLEMENTED (2026-07-12).
Supersedes the chat-delivered revision 1. Incorporates all four binding
corrections from the approval review plus the resolved open decisions.
Phase 1 (schema v2 migration, deterministic validation, revision-safe
endpoints, backups, and atomic persistence) is implemented. Phases 2-6 are
not implemented yet.

## 0. Approval record (binding corrections)

1. Product structure and process flow are separate relations. `parentNodeId`
   stays assembly containment and is never drawn as a canvas wire. New edges
   represent process precedence; the v1 edge kind is `precedence`, not a
   generic `flow`.
2. Node types ship in v1: `assembly`, `subassembly`, `operation`,
   `inspection`, `decision`, `input`, `output`. Without types the canvas is
   an editable BOM, not a manufacturing process map.
3. Saves are revision-aware: content-hash revision in GET/PUT, 409 on stale
   base revision, atomic writes, `productId` validated against known assets.
   Backups remain recovery insurance, not concurrency control.
4. Cycle validation is edge-kind-specific: a cycle over `precedence` edges is
   a structural error; reserved kinds (`rework`, `feedback`, `material`) are
   excluded from that check so legitimate loops can arrive later without a
   validator change.

Resolved decisions:
- Canvas shows levels 1-2 initially, with focus-into-subassembly so level-3
  nodes remain editable.
- Saves with warnings are allowed; structural errors block.
- Lives inside Training as a viewport mode for v1.
- AI describes fan-in as a "bottleneck candidate" only; actual bottleneck
  claims require timing, capacity, or utilization evidence the map does not
  contain.
- The analyze digest carries node types, precedence dependencies, part
  references, and validator findings - names/levels/part counts alone are
  insufficient.

## 1. Current-state inventory (verified)

- Where the process map lives today: the Training tab.
  `_trainRenderProcessDiagram()` (`static/index.html:24616`) renders a
  static, tree-laid-out product-structure board (`train-process-board`) from
  `trainingState.processMap`, using `_trainDiagramCard()` (24337) - a rich
  reusable card component with thumbnails, selection state, review badges,
  and click handlers. A parallel panel renderer
  (`_trainRenderProcessPanelBranch`, ~24067) shows the tree plus part pills.
  CSS: `.train-process-node*` (5198-5286), `.train-diagram-*` (5749+).
- Data: loaded read-only via `fetch(trainingState.processMapUrl)` (21998)
  from `generated/training/racing-bike/racing_bike_process_map_working_draft.json`
  - `schemaVersion`, 56 nodes with `nodeId, level (0-3), name, parentNodeId,
  purpose, partIds, partNames, suggestedBuildOrder, reviewRequired`. It is a
  hierarchy: zero edges, zero positions, zero types. There is no save
  endpoint - the only `/api/training/*` POSTs are narration/facility/blender.
- Builder alignment already on paper: `docs/builder-agent-plan.md` defines
  the tool vocabulary this editor needs server-side - `read_process_map`,
  `find/move/rename/add_process_node`, `update_process_step`,
  `validate_process_map`, `backup_asset`, `write_asset`, `show_diff`,
  `revert_last_asset_change` - plus the safety posture (backup before write,
  ask before overwrite).
- Precedents to reuse: `static/ui_action_runtime.js` proves the pattern of a
  standalone JS module beside the monolith (index.html is 53K lines - do not
  grow it by another 1,500); the shared-fixture parity discipline;
  ASCII-enforced asset writes; `schemaVersion`-gated loaders.

Gap summary: the node cards, the data asset, the validation tool plan, and
the AI layer exist; missing are node types, edges plus positions in the
schema, a canvas with pan/zoom/drag/wire interactions, a revision-safe save
path with validation and backup, and the analyze skill.

## 2. Target architecture

```
generated/.../<product>_process_map.json  (schema v2 - single source of truth)
        ^ GET / PUT (revision-checked, validated, backed up, atomic)
server: ai_inspector/process_map/ (schema + deterministic validators)
        endpoints /api/training/process-map/{productId}
frontend: static/process_map_editor.js  (self-contained editor module)
        - DOM node layer: reused _trainDiagramCard bodies wrapped in
          .pm-node with type badge and ports
        - SVG edge underlay: cubic beziers, live pending wire, hit-area
          strokes
        - pan/zoom via CSS transform; graph ops as pure functions (testable)
        mounts into Training viewport as a new viewportMode ('process_flow')
AI:     "Analyze flow" button -> graph digest as context attachment ->
        analyze-process-map skill (read-only); deterministic validator
        findings render as canvas badges regardless of AI
```

### Schema v2 (additive; v1 loadable)

- Every node gains required `type`, one of: `assembly`, `subassembly`,
  `operation`, `inspection`, `decision`, `input`, `output`. Unknown type is
  a structural error.
- Nodes gain optional `position {x, y}`.
- `parentNodeId` is unchanged and containment-only. The flow canvas never
  renders containment as a wire; containment is expressed by canvas scope
  (Section 3, focus mode).
- Map gains `edges: [{edgeId, from: {nodeId, port}, to: {nodeId, port},
  kind, label?}]` and `layoutVersion`. `kind` enum: `precedence` (the only
  creatable kind in v1), with `rework`, `feedback`, and `material` reserved
  so typed edges arrive later without migration.
- `schemaVersion: 2`. The loader accepts v1: edges `[]`, positions
  auto-laid-out from `level` + `suggestedBuildOrder` (free layered initial
  layout, no dagre dependency), and types assigned by the migration rule
  below.

Migration typing rule (defaults; every migrated node is retypeable in the
editor): `level 0 -> assembly`; `level 1 and 2 -> subassembly`; leaf part
nodes (level 3) `-> input`, on the reading that purchased/fabricated parts
enter the process as material inputs. Migration emits one informational
finding per auto-typed node group so the operator reviews the assignments;
migration never invents `operation`/`inspection`/`decision`/`output` nodes -
those are authored by the user (or later by Builder).

### Ports

Rendered per existing edge plus one `+` stub per side (n8n's model, per the
reference screenshot). BOM/`partIds` overlap powers suggested connections in
a later phase - ghost edges the user accepts - never auto-created wires.

## 3. Exact changes

### Server (new module + 2 endpoints)

`ai_inspector/process_map/validate.py` - deterministic validators returning
typed findings `{severity: error|warning|info, code, nodeId/edgeId, message}`.
This is the same function Builder's `validate_process_map` tool will call -
written once here.

Errors (block save):
- duplicate `nodeId`; dangling `parentNodeId`; edge endpoint does not exist;
  self-edge; duplicate edge (same from/to/kind); unknown node `type`;
  unknown edge `kind`; cycle detected over `precedence` edges only (the
  validator filters edges by kind before running DFS; a future `rework` or
  `feedback` edge closing a loop does not trigger this error).

Warnings (saveable, surfaced as badges):
- orphan/unreachable nodes; parts referenced but unknown to the product;
  type-shape checks: `input` node with incoming precedence edges, `output`
  node with outgoing precedence edges, `decision` node with fewer than two
  outgoing precedence edges.

Info:
- migration auto-typing notices (Section 2).

Endpoints (both gated by `INSPECTORPRO_PROCESS_MAP_EDIT`; flag off = today's
static-fetch behavior, byte-for-byte):
- `GET /api/training/process-map/{productId}` -> `{map, revision, findings}`.
  Serves v1 files migrated on read. `revision` is the sha256 hex of the
  canonical serialization (sorted keys, ASCII) of the stored asset.
- `PUT /api/training/process-map/{productId}` with body
  `{map, baseRevision}`:
  1. `productId` must match `^[a-z0-9][a-z0-9-]*$` AND resolve (realpath,
     no traversal) to an existing product directory under
     `generated/training/` that contains a process-map asset; otherwise 404.
  2. Recompute the stored asset's revision; mismatch with `baseRevision` ->
     409 `{error: "revision_conflict", currentRevision}`. No merge in v1;
     the frontend offers reload.
  3. Validate; any `error` finding -> 422 with the findings list.
  4. Timestamped backup copy beside the asset, then atomic write: canonical
     ASCII serialization to a temp file in the same directory, then
     `os.replace`. Response returns the new revision.

### Frontend

`static/process_map_editor.js` (~1,200 lines): pure graph ops (`addEdge`,
`deleteEdge`, `moveNode`, `retypeNode`, undo/redo via bounded snapshot
stack), layout (`layeredLayout(nodes)` keyed off `level` +
`suggestedBuildOrder`), geometry (port anchors, bezier path builder), and
the interaction controller (node drag, port-drag with live wire + snap,
edge select/delete, wheel zoom-to-cursor, empty-space pan, fit). Node bodies
delegate to `_trainDiagramCard` via a small bridge
(`window._pmCreateNodeCard`) so cards keep their visuals and click-to-select
semantics; the wrapper adds a type badge and accent per node type.

Canvas scope (resolved decision): the default canvas shows levels 1-2
(~20 cards). Double-click (or a focus button) on a `subassembly` enters a
focused scope showing its level-3 children and their precedence edges, with
a breadcrumb to exit. In v1, edge creation is restricted to nodes visible in
the current scope; an edge whose far endpoint is outside the scope renders
as a labeled boundary stub, not a hidden wire.

`static/index.html`: register `viewportMode 'process_flow'` in the Training
viewport switch (next to `_trainRenderProcessDiagram` at 24616); an "Edit as
flow" toggle on the board header (24634 area); dirty-state guard on
mode/tab switch; save button wired to PUT (carrying `baseRevision`; on 409,
offer reload); validator findings rendered as node/edge badges; node type
picker in the selection panel; "Analyze flow" button that sends one normal
Sage turn with the digest attached. The read-only diagram remains untouched
and remains the default view.

CSS block: `.pm-canvas`, `.pm-node` (+ per-type accents), `.pm-port`,
`.pm-edge` (+ selected/invalid states), reusing the existing training
palette.

### AI layer

New read-only skill `ai_inspector/agent_skills/analyze-process-map/`
(agents: sage; modes: training/plant_process;
`requires_context: process_map.graph`; no side effects).

`process_map.graph` context digest (registered provider, same philosophy as
the motion digest) - per the approval refinement it carries:
- per node: `{id, name, type, level, parentNodeId, partIds}` (ids, not just
  counts);
- edges: `[{from, to, kind}]`;
- validator findings (codes + severities);
- derived facts: entry nodes (no incoming precedence), terminal nodes,
  fan-in list (nodes with 3+ incoming precedence edges), parallelizable
  branch sets, node/edge counts.

Skill procedure: compare user-drawn sequence vs `suggestedBuildOrder`; flag
fan-in nodes as "bottleneck candidates" (mandated language - the map has no
timing, capacity, or utilization evidence, so the skill must not assert an
actual bottleneck); identify parallelizable branches; flag contradictions
with assembly containment. Boundaries: never invent takt times or costs;
cite nodes by id + name.

Deterministic findings never wait for the AI: validation runs locally on
every edit batch and badges the canvas.

## 4. Phases with checkable artifacts

1. Schema v2 + types + validators + endpoints (no UI): validator unit tests
   green including kind-filtered cycle detection and type-shape warnings;
   PUT round trip proven with backup file, atomic write, and revision
   conflict (409); v1 fixture loads migrated with default types.
   Artifacts: `tests/test_process_map_validate.py`,
   `tests/test_process_map_endpoints.py`.
2. Read-only canvas: flow view renders the 56-node fixture with layered
   auto-layout, type badges, pan/zoom/fit, cards reused.
   Artifact: Playwright render + node-harness layout tests.
3. Editing: node drag, port-drag wiring with live bezier, edge
   select/delete, node retype, undo/redo, dirty-guard, revision-aware save.
   Artifact: Playwright edit-save-reload round trip including a stale-save
   409 path.
4. Validation UX + AI: canvas badges from validator; `analyze-process-map`
   skill + digest + button.
   Artifact: skill registry green (runtime suite); one live analyze turn in
   Playwright; digest content test.
5. Suggestions (deferrable): ghost edges from shared `partIds`/mate data,
   accept/dismiss.
6. Builder convergence (later): Builder's
   `write_asset`/`validate_process_map` tools call the same module and
   endpoints - no second implementation. Revision-aware PUT is what makes
   concurrent Builder/user edits safe when that day comes.

## 5. Test strategy

- Python validator matrix: cycle over precedence edges; the same loop closed
  by a `rework` edge does NOT raise the cycle error; orphan; duplicate id;
  dangling edge; unknown part; unknown type; type-shape warnings (input with
  incoming, output with outgoing, decision with <2 outgoing); v1 migration
  typing defaults; warning-vs-error severity mapping.
- Python endpoint tests: 422 on structural error; 409 on stale
  `baseRevision` with asset left unchanged; atomic write (no partial file on
  simulated failure, temp file cleaned); backup created; ASCII output;
  `productId` traversal and unknown-id rejection (404); flag off -> 404.
- Node harness (same pattern as `test_ui_action_receipts.js`; the editor is
  a standalone file): graph-op purity (add/delete/retype/undo sequences),
  layout determinism, port-anchor and bezier math, snapshot-stack bounds.
- Playwright (`tests/smoke_process_flow_editor.py`; assertions data-driven
  off whatever the endpoint serves): render; drag-persist-reload; wire two
  nodes port-to-port; delete edge; introduced precedence cycle shows error
  badge and blocks save; save with only warnings succeeds; stale-revision
  save surfaces the reload prompt; undo restores; focus into a subassembly
  and edit a level-3 node; pan/zoom; dirty-guard on tab switch; read-only
  diagram identical with the flag off; analyze button yields exactly one
  chat turn.
- Frozen bars: existing training/product-structure behavior unchanged
  (flag off = today, byte-for-byte).

## 6. Risks and rollback

Risks: interaction-polish creep (mitigation: the v1 scope list is the
contract - no minimap, no edge routing around nodes, no touch); index.html
growth (mitigated by the standalone module); fixture specificity (everything
keyed by `productId` and schema - no racing-bike or engine hardcoding in
code); typed-node scope creep (v1 authors types and validates shapes; it
does not add per-type node editors beyond the existing card + type picker).

Rollback: the flow editor is a new `viewportMode` behind a frontend const
plus the PUT behind `INSPECTORPRO_PROCESS_MAP_EDIT`; both off = current app
exactly.
