# Floating UI Integration Plan - Process-Map Card Toolbar

Status: revision 2 - PHASES 1-3 + FREQUENT ACTIONS IMPLEMENTED (2026-07-13).
Incorporates all four binding corrections from the approval review plus two
mandated tests. The vendored positioning foundation and contextual card
toolbar are implemented and verified. The frequent-action extension adds
connected step, edit label, and notes alongside preview and delete. Hardening
is complete; optional junction and edge-surface reuse remains separate.

Line references were verified against the working tree on 2026-07-13
(process_map_editor.js at 2,919 lines, placement-map model). Re-verify
anchors before editing; the file is under active development.

## 0. Approval record (binding corrections)

1. Selection is decoupled from the 3D preview. Today a card click selects
   the node AND opens the preview (index.html:25640-25643). After this
   change: single click selects and opens the toolbar only; the preview
   opens only from the toolbar's preview command; the card tooltip that
   promises "Open interactive 3D ... preview" on click
   (index.html:25645-25649) is updated to describe selection. Double-click
   as a preview shortcut is optional and, if adopted, applies only to leaf
   (childless) cards - container-node double-click is already taken by
   focus-into-subassembly (renderNode wrapper dblclick -> focus()).
2. z-index uses a documented contextual-surface layer BELOW modal
   overlays, not a value above every existing layer. The 3D preview
   backdrop is 5200 (index.html:7026) and its shell is 5201 (:7041); the
   toolbar surface sits at a new documented layer 5150. The preview
   command closes the toolbar BEFORE invoking the preview, so the two can
   never stack; the layer choice is defense in depth, not the mechanism.
3. Junction behavior is explicit: junctions are not cards. In Phase 1,
   selecting a junction closes (or never opens) the card toolbar. Junction
   controls remain the first follow-up use case.
4. The dependency pin is exact, not "current stable 1.x". Before any code
   lands, the implementer selects and tests one exact version pair of
   @floating-ui/core and @floating-ui/dom and records in VERSIONS.md:
   immutable package versions, source URLs, sha256 hashes of the vendored
   files, and license information. Recording VERSIONS.md is a Phase 1
   gate artifact.

Two mandated tests (in the Playwright matrix, Section 8):
- Selecting a product card opens only the toolbar and does not open the
  3D preview.
- Activating the preview command closes the toolbar before the preview
  backdrop appears; no toolbar is ever visible above the modal.

## 1. Verified current-state inventory

The editor (`static/process_map_editor.js`, 2,296 lines, UMD module
exposing `window.InspectorProProcessMap`):

- Selection model: `select(nodeId)` at :1427, `selectEdge(edgeId)` at
  :1448. One node OR one edge selected, never both. Junctions are nodes
  (`isJunctionNode` :75). The map has evolved into a placement model:
  `nodeKind: product_occurrence | process_step`, `processType` with
  `PROCESS_STEP_TYPES`, junctions, port orientation/order.
- All five toolbar commands already exist as handlers - nothing is
  invented:
  - Port orientation: `changeSelectedPortOrientation` :1601 ->
    `setNodePortOrientation` :324; values `horizontal`/`vertical`,
    default horizontal (:79); toolbar select at :794.
  - Port order swap: `changeSelectedPortOrder` :1610 ->
    `setNodePortOrder` :334; values `input_first`/`output_first` (:85).
  - Node type: `changeSelectedNodeType` :1596 -> `retypeNode` :344;
    gated: disabled for junctions and for `product_occurrence` nodes in
    placement maps (`updateEditControls` :1504-1530).
  - 3D preview: `_trainOpenProcessFlowCardPreview(node, sourceEl)` at
    index.html:25610; routes to `_trainOpenUniqueItemPreview` or
    `_trainOpenAssemblyPreview` by `productKind`. Currently fired on card
    click (changed by correction 1).
  - Delete: `deleteSelection` :1619; handles node and edge selection;
    undoable via `commitMutation`.
- All mutations flow through `commitMutation` :1582 -> `SnapshotHistory`
  (:358) -> `renderGraph`, so a toolbar built on these handlers inherits
  undo/redo, dirty tracking, validation, and save behavior.
- Reposition choke points: `applyTransform` :1765 is the single write
  point for pan/zoom/fit transforms; node drag updates wrapper style plus
  `_updateEdgeGeometry` :2055 inside `pointerMove` :2093; `renderGraph`
  :1158 rebuilds the node layer (destroys the selected card's element).
- Lifecycle: `destroy` :2229; disposal via
  `_trainDisposeProcessFlowEditor`; dirty guards at `switchTab`
  (index.html:13844), training-type change, board return. `keyDown` :2207
  handles Ctrl+Z/Y/Delete; Escape is currently unhandled.
- Command gating state lives in `updateEditControls` :1504
  (saving/conflict/junction/nodeKind predicates).

Canvas transform reality: `.pm-world` carries translate+scale; cards are
absolutely positioned children; `.pm-viewport` has `overflow: hidden`, so
anything appended inside it clips.

Layering (verified): 3D preview backdrop 5200 (:7026), preview shell 5201
(:7041); top of the app stack is 10000-10002 (global menus/toasts).

Theming: pm styles consume CSS custom properties (`--bg-main`,
`--text-primary`, `--viewport-bg-gradient`); light theme via
`:root[data-theme="light"]` overrides. `.pm-toolbar-button` has
hover/focus-visible/disabled states (:5760-5780). Three existing
`prefers-reduced-motion` blocks (6164, 7967, 9461).

Dependency infrastructure: no package.json, no node_modules, no vendor
directory, no build pipeline, no CSP (no header, no meta tag). All
frontend modules are classic scripts with globals, loaded at
index.html:12590-12592. One outlier: three.js from cdnjs (:11475), the
app's only network dependency.

Existing hand-positioned floating UI (expansion candidates):
`_showNoteContextMenu` (16294), viewer-canvas contextmenu (24109),
tree-row contextmenu (37721).

Tests: `tests/test_process_map_editor.js` (pure-require node harness) and
`tests/smoke_process_flow_editor.py` (Playwright, hermetic route
interception mirroring real endpoint shapes). The existing preview smoke
case (~:399-407, `#trainUniquePreviewShell`) rides the click path and must
be rewired to the toolbar command as part of correction 1.

## 2. Dependency-loading strategy

Recommendation: vendor pinned UMD builds as local static files.

`static/vendor/floating-ui/` contains:
- `floating-ui.core.umd.min.js` (global `FloatingUICore`)
- `floating-ui.dom.umd.min.js` (global `FloatingUIDOM`; requires core
  loaded first)
- `LICENSE` (MIT)
- `VERSIONS.md` - exact immutable versions, source URLs, sha256 of each
  vendored file, license note. Written at vendoring time; a Phase 1 gate
  artifact (correction 4).

Two script tags before `process_map_editor.js` at index.html:12590.
Combined cost ~14 kB gzipped.

Rejected alternatives:
- CDN: InspectorPro must work offline in plants and demos; a CDN outage
  during a pitch is unacceptable. (The existing three.js CDN tag is a
  pre-existing liability by the same logic - vendor it too, as a separate
  task.)
- ESM import: the codebase is uniformly classic-script/UMD; a lone module
  boundary creates a deferred-vs-sync loading seam for zero benefit.
- Bundler: a build step for two static files inverts cost/benefit.

Vendoring keeps a future strict CSP trivial (`script-src 'self'`) and
keeps future packaging self-contained.

Load guard: the feature checks `window.FloatingUIDOM` once; if absent it
logs one warning and stays off - the editor remains fully functional
through the existing top-toolbar controls.

## 3. Architecture and event lifecycle

Two new pieces:

1. `static/floating_surface.js` (~200 lines, UMD, global
   `InspectorProFloating`) - the shared surface manager.
2. A toolbar builder inside `process_map_editor.js` (~120 lines) that
   constructs the button row and delegates every action to existing
   handlers.

Positioning through the transformed canvas: Floating UI positions from
`getBoundingClientRect()`, which returns post-transform screen
coordinates, so transforms on the REFERENCE element's ancestors
(.pm-world translate/scale) are already accounted for. The failure mode
is a transformed/will-change/contain ancestor of the FLOATING element -
so the surface is appended to `document.body` with `strategy: 'fixed'`.
Overflow clipping by viewport/sidebar/shell becomes impossible.

Layering (correction 2): the surface uses a documented contextual-surface
layer, `--ip-z-contextual: 5150`, defined next to the pm CSS with a
comment recording the neighborhood: canvas content below, preview
backdrop 5200 and shell 5201 above, global menus/toasts 10000+. Modal
overlays stack above contextual surfaces by design. Additionally the
preview command closes the toolbar before invoking
`_trainOpenProcessFlowCardPreview`, so toolbar-over-modal cannot occur
regardless of layering.

Middleware stack:
- `offset(10)` - clears port stubs and selection outline.
- Placement chosen from the node's port orientation (the
  "avoid covering connection handles" answer): horizontal ports
  (left/right) -> placement `top`, flip to `bottom`; vertical ports
  (top/bottom) -> placement `right`, flip to `left`. Ports stay clear by
  construction.
- `flip()` then `shift({ padding: 12 })` for viewport-edge behavior.
- No `arrow` (toolbar, not a speech bubble). No `size` in v1.

Update policy - least expensive reliable combination:
- Pan/zoom/fit: one `surface.reposition()` appended inside
  `applyTransform` :1765. Frame-accurate during pan, free when idle.
- Dragging the anchored card: `surface.reposition()` beside the
  `_updateEdgeGeometry` call in `pointerMove` :2093, only when the
  dragged node is the anchor.
- Any re-render (`renderGraph` :1158): `surface.reanchor(newWrapperEl)` -
  re-query `[data-node-id]` after rebuild; close if the node is no longer
  rendered (covers deletion, focus change, scope change, undo past
  creation).
- Window resize, sidebar collapse, layout shifts: `autoUpdate()` with
  defaults (ancestorScroll, ancestorResize, elementResize,
  layoutShift: true - IntersectionObserver-based). Observers only.

`animationFrame: true` is rejected: it is a permanent per-frame loop to
solve exactly the two continuous cases the codebase already funnels
through two functions.

Open/close lifecycle:
- Open on node selection in `select()` :1427 when editable and the
  runtime guard passes. Junction selection does NOT open the toolbar and
  closes any open one (correction 3).
- Close on: `selectEdge`, junction selection, `deleteSelection`, `exit`,
  `destroy` :2229, conflict entering, Escape, outside pointerdown,
  renderGraph re-anchor miss, and BEFORE the preview command invokes the
  preview (correction 2).
- Command gating: extract the selected-node predicates from
  `updateEditControls` :1504 into `selectedNodeCommandStates()` consumed
  by both the top toolbar and the floating toolbar - one source of truth
  for junction/nodeKind/saving/conflict gating, including the
  map-kind-aware type option list (NODE_TYPES vs PROCESS_STEP_TYPES).

Click-behavior change (correction 1): `_trainCreateProcessFlowCard`'s
onClick (index.html:25640) drops the direct
`_trainOpenProcessFlowCardPreview` call; click selects only. The preview
runs from the toolbar command via a mount option
`onOpenPreview: _trainOpenProcessFlowCardPreview` (~:25660). Card
`title` text (:25645-25649) changes to describe selection (for example
"Select card; actions open in the card toolbar"). Optional leaf-only
double-click preview shortcut may be added; container-node double-click
remains focus-into-subassembly.

## 4. Exact files and functions to modify

- `static/vendor/floating-ui/*`: new - pinned UMD files + LICENSE +
  VERSIONS.md (exact versions, URLs, sha256; correction 4).
- `static/floating_surface.js`: new - surface manager (UMD,
  dependency-injected computePosition/autoUpdate for testability).
- `static/process_map_editor.js`:
  - `select` :1427 (open; skip and close for junctions),
  - `selectEdge` :1448 (close),
  - `deleteSelection` :1619 (close before mutation),
  - `renderGraph` :1158 (reanchor-or-close),
  - `applyTransform` :1765 (+1 line reposition),
  - `pointerMove` :2093 node branch (+1 line),
  - `keyDown` :2207 (Escape),
  - `destroy` :2229 (close),
  - `updateEditControls` :1504 (extract `selectedNodeCommandStates()`),
  - new `_buildCardToolbar()`; parameterize the three command methods
    (`applyPortOrientation(value)`, `applyPortOrder(value)`,
    `applyNodeType(value)`) so select-driven and button-driven paths
    share one implementation.
- `static/index.html`:
  - 2 script tags (~:12590),
  - onClick decoupling + tooltip text (~:25640-25649; correction 1),
  - mount option `onOpenPreview` (~:25660),
  - CSS block near pm styles including documented `--ip-z-contextual`,
  - `PM_CARD_TOOLBAR = true` rollback const.
- `tests/test_floating_surface.js`: new node harness.
- `tests/test_process_map_editor.js`: extend - toolbar action delegation,
  gating states, junction no-toolbar rule.
- `tests/smoke_process_flow_editor.py`: extend - matrix in Section 8,
  including rewiring the existing preview case to the toolbar command.

No server, schema, or persistence changes of any kind.

## 5. CSS and theme changes

One block beside the pm styles: `.ip-floating-surface` (position fixed,
`z-index: var(--ip-z-contextual)` = 5150 with a layer-map comment;
background/border/shadow from the same tokens `.pm-toolbar` uses) and
`.pm-card-toolbar` for the row. Buttons reuse `.pm-toolbar-button` as-is -
hover, focus-visible, and disabled states come free in both themes
because theming is custom-property-driven. Entry animation: 120ms opacity
fade only, removed under `prefers-reduced-motion: reduce` (matching the
three existing blocks). Never transition left/top (it would fight
repositioning).

## 6. Accessibility behavior

- `role="toolbar"`, `aria-label="Card actions for <node name>"`,
  `aria-orientation="horizontal"`.
- Opening does not steal focus. Keyboard entry: when the selected card
  (a `<button>`) has focus, Tab moves into the toolbar (manager
  intercepts on the anchor); inside, Left/Right roving tabindex; Tab
  exits forward.
- Escape closes and restores focus to the selected card's button.
  Manager-level document keydown - deliberately not the editor's
  `keyDown` :2207, which is bound to `this.root` and cannot see events in
  the body-appended surface.
- Icon buttons carry both `aria-label` and `title` (existing toolbar
  convention :796-797). The type control is a `<select>` with
  `aria-label`, as at :794.
- Repositioning writes only position styles - never re-creates buttons,
  so focus survives pan/zoom/drag.
- Not hover-only: opens on selection (click or keyboard) and is redundant
  with the always-visible top toolbar.

## 7. Implementation phases

1. Foundation (complete): vendor files + VERSIONS.md with exact
   versions and hashes (gate artifact) + script tags + load guard;
   `floating_surface.js` with injected positioning deps;
   `tests/test_floating_surface.js` green. Artifact: node harness passes
   with stub computePosition; app byte-identical with flag off.
2. Card toolbar (complete): builder + five commands via existing handlers;
   `selectedNodeCommandStates()` extraction; click/preview decoupling +
   tooltip text (correction 1); open/close lifecycle including the
   junction rule and close-before-preview; explicit reposition hooks;
   CSS with documented layer; Escape/outside-click/focus restore.
   Artifact: Playwright core cases green, including the two mandated
   tests; backend + node suites unchanged.
3. Hardening (complete): orientation-aware placement, viewport-edge flip/shift,
   themes, reduced motion, conflict-state close, rapid remount/tab-change
   churn. Artifact: full Playwright matrix green;
   `no_browser_page_errors` green; save/reload behavior unchanged. Verified
   with 14/14 floating-surface checks, 31/31 editor checks, 27/27 process-map
   schema/API checks, and 51/51 Playwright checks.
4. (Separate, optional) first reuse: junction chip + edge midpoint
   controls via virtual-element anchors - only after the manager proves
   itself.

## 8. Test matrix

Node harness (`test_floating_surface.js`, stub DOM + injected
deterministic computePosition): open/close lifecycle; one-active-surface
rule (second open closes first, exactly one cleanup); cleanup idempotence
(double-close calls autoUpdate cleanup once); action callbacks receive
expected nodeId/value; deletion closes; junction selection never opens;
`mapFingerprint` unchanged by open/close; orientation and port-swap via
toolbar land in SnapshotHistory and undo cleanly (asserting delegation,
not re-testing ops).

Playwright (extends the hermetic synthetic-route suite):
- Select card -> toolbar appears anchored per orientation rule.
- MANDATED: selecting a product card opens only the toolbar; the 3D
  preview does NOT open (no `#trainUniquePreviewShell.open`, no backdrop).
- MANDATED: activating the preview command closes the toolbar before the
  backdrop appears; at no frame is `.ip-floating-surface` present while
  the backdrop is open.
- Drag card 200px -> toolbar follows within tolerance.
- Pan and zoom (including scale 0.28 and 1.6) -> alignment maintained.
- Cards at all four viewport edges -> flip/shift keeps surface fully
  on-screen.
- Toolbar rect does not intersect port rects in either orientation.
- Execute orientation change and port swap -> visible port move; undo
  restores.
- Preview command opens the 3D viewer (rewired existing case).
- Delete removes card and toolbar.
- Escape and outside click dismiss with focus back on the card.
- Junction click -> no toolbar; any open toolbar closes.
- Switch app tab while open -> no orphan surface in DOM.
- Light and dark themes.
- Zero console errors; zero `.ip-floating-surface` residue after close.
- Full save/reload round trip unchanged.

## 9. Risks and mitigations

- Transform math regression at deep zoom: fixed strategy + body append
  eliminates ancestor-transform bugs; Playwright asserts alignment at
  min/max zoom.
- Gating drift between toolbars: prevented structurally by
  `selectedNodeCommandStates()`.
- Global listener leaks across remounts: manager owns exactly two
  document listeners, added on open, removed on close, idempotent close
  guard; churn test asserts zero residue.
- Behavior-change regression from click/preview decoupling: the existing
  smoke preview case is rewired in the same commit; the two mandated
  tests pin the new contract in both directions.
- Monolith CSS collisions: everything namespaced ip-floating- /
  pm-card-toolbar; no bare element selectors.
- Vendored staleness: exact pins + hashes in VERSIONS.md; upgrades are a
  deliberate two-file swap.
- Editor keyDown blind spot: Escape handled at document level in the
  manager (the editor's root-bound handler cannot see the body-appended
  surface).

## 10. Rollback strategy

Purely additive frontend feature: `PM_CARD_TOOLBAR` const plus the
`FloatingUIDOM` presence guard gates everything; off = today's editor
exactly, except correction 1's click decoupling, which is intentionally
NOT flag-gated (it is an approved UX change with its own tests; rolling
back the toolbar keeps click-select-only plus preview via existing card
affordances per the updated tooltip). Full removal = two script tags, the
vendor directory, floating_surface.js, one CSS block, ~10 hook lines. No
data, schema, or server surface touched.

## 11. Acceptance criteria

1. All five commands work from the toolbar and remain undoable/redoable,
   identical to the top-toolbar paths.
2. Single click selects and opens the toolbar only; the preview opens
   only from the toolbar command (or optional leaf-only double-click);
   card tooltip text matches the new behavior.
3. Toolbar stays anchored through drag, pan, zoom, fit, focus navigation,
   window/sidebar resize; never clipped by viewport, sidebar, or shell.
4. The surface renders at the documented contextual layer (5150), below
   the preview backdrop (5200); the preview command closes the toolbar
   first; the two are never visible together.
5. Placement avoids ports in both orientations; flip/shift keeps the
   surface fully visible at every canvas edge.
6. Exactly one surface can exist; junction selection never opens one;
   Escape, outside click, deletion, tab change, conflict state, and
   editor destroy all close it with focus restored.
7. Keyboard: reachable from the focused card, arrow-key traversal,
   Escape out; icon buttons named; reduced motion honored; both themes
   correct.
8. With the flag off or the library missing, the editor is fully
   functional via the top toolbar; all existing suites unchanged.
9. Opening/closing the toolbar alone never dirties the map
   (mapFingerprint invariant).
10. VERSIONS.md records exact immutable versions, source URLs, sha256
    hashes, and license before any dependent code merges.

## 12. Future expansion, ranked

1. Junction controls (renderJunction :1278 - delete/collapse chip):
   good follow-up, first. Same anchor pattern, tiny command set
   (correction 3 confirms junctions stay out of the card toolbar).
2. Edge controls (midpoint chip: delete / split-with-junction,
   `splitEdgeWithJunction` :223): good follow-up. Virtual-element anchor
   at the bezier midpoint - hard to hand-roll, high value.
3. Validation finding popovers (today title attrs on badges): good
   follow-up, high value. Rich, keyboard-accessible finding details.
4. Tree-item / feature-tree context menus (existing manual menus at
   16294, 37721): good follow-up. Port onto the manager; delete bespoke
   positioning code.
5. 3D-selection context actions (contextmenu on renderer, 24109): good
   follow-up (pointer-anchored virtual element). Labels that TRACK 3D
   parts during orbit are NOT suitable - that requires per-frame
   world-to-screen projection, which Floating UI does not do.
6. Viewer toolbar menus (static buttons): marginal. Only when a menu
   actually clips.
7. Engineering tooltips (hundreds of title attrs): not suitable at
   scale. Adopt selectively where title demonstrably fails.
