"""FT4/FT5 app verification for the Facility Layout structure tree.

Drives the real app in a browser and exercises what unit tests cannot reach:
the workspace wiring, the notification path, and build-from-empty authoring.

Run with the app served locally:

    python tests/verify_facility_layout_structure_tree_app.py
    python tests/verify_facility_layout_structure_tree_app.py --base http://127.0.0.1:8000

It authors only in the draft and never calls session.save(), then asserts the
stored revision never moved. Nothing is written back to the layout store.
"""

import argparse
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_BASE = "http://127.0.0.1:8000"
BLANK_LAYOUT = "fl-main"
REFERENCE_LAYOUT = "fl-reference-manual-20260812"
# The server validates assetDefinitionRevision as a lowercase SHA-256, and the
# asset must exist in the site catalog, so the build-from-empty pass authors
# with a real pair read from the reference layout rather than an invented one.
REFERENCE_LAYOUT_FILE = (
    ROOT / ".runtime" / "facility-layout" / "layouts" / "local" / "site-local"
    / "layouts" / (REFERENCE_LAYOUT + ".json")
)


# Two authoritative server rules shape this exercise, both discovered by
# running it rather than by reading code:
#
# 1. The blank layout's building shell is a small room. A placement whose
#    footprint leaves the floor is rejected as placement_outside_floor. Probed
#    at 5 m granularity, the usable floor for this asset is x in [5, 35],
#    z in [5, 25].
# 2. Once any zone exists, every placement must be inside a zone. A commit that
#    would leave one out is rejected as zone_containment_violation with reason
#    footprint_or_setback, one finding per stranded placement. Unzoned is
#    therefore an authorable state only before the first zone is drawn, or
#    after the last one is removed - which is exactly what this exercise walks
#    through.
BUILD_POINTS = {
    "inner_a": {"x": 12.0, "z": 11.0},
    "inner_b": {"x": 17.0, "z": 11.0},
    "outer_only": {"x": 26.0, "z": 18.0},
    "moved": {"x": 26.0, "z": 12.0},        # inside Outer, outside Inner
    "moved_again": {"x": 28.0, "z": 12.0},
}
OUTER_RECT = {"start": {"x": 7.0, "z": 7.0}, "end": {"x": 32.0, "z": 22.0}}
INNER_RECT = {"start": {"x": 9.0, "z": 9.0}, "end": {"x": 20.0, "z": 14.0}}


def authoring_asset():
    """A real {assetId, assetDefinitionRevision} the server will accept."""
    document = json.loads(REFERENCE_LAYOUT_FILE.read_text(encoding="utf-8"))
    layout = document.get("layout") or document
    placement = next(
        p for p in layout["placements"] if p["assetId"] == "asset-pallet-1200x1000"
    )
    return {
        "assetId": placement["assetId"],
        "assetDefinitionRevision": placement["assetDefinitionRevision"],
    }

passed = 0
failures = []


def check(name, condition, detail=""):
    global passed
    if condition:
        passed += 1
        print("PASS " + name)
    else:
        failures.append(name + ((" - " + str(detail)) if detail else ""))
        print("FAIL " + name + ((" - " + str(detail)) if detail else ""))


def enter_facility_layout(page, layout_id):
    """Open the app and switch into the Facility Layout workflow."""
    page.goto("%s/?facilityLayoutId=%s" % (page.base_url, layout_id))
    page.wait_for_function("() => !!window.InspectorProFacilityStructure", timeout=60000)
    # The workflow selector lives in the Workflows ribbon tab. The visible
    # control is a custom combobox backed by a real <select>; driving the
    # select is the same code path chooseOption() takes, without the popup.
    page.get_by_role("tab", name="Workflows").click()
    page.wait_for_selector("#trainingTypeRibbonSelect", state="attached", timeout=30000)
    page.evaluate(
        """() => {
          const sel = document.getElementById('trainingTypeRibbonSelect');
          sel.value = 'facility_layout';
          sel.dispatchEvent(new Event('change', { bubbles: true }));
        }"""
    )
    page.wait_for_function(
        "() => !!(window._trainFacilityLayoutAuthoringApp"
        " && window._trainFacilityLayoutAuthoringApp.workspace)",
        timeout=120000,
    )
    # Show the pane, not just mount it. A hidden subtree cannot take focus, so
    # the keyboard checks are meaningless unless the slot is actually revealed.
    page.evaluate("() => window._setLeftPanelContent('structure', { reveal: true })")
    page.wait_for_function(
        "() => { const h = document.getElementById('structureTreeHost');"
        " return !!h && !!h.offsetParent; }",
        timeout=30000,
    )


# The page-side helper. Kept in one string so every step shares the same
# accessors and nothing drifts between them.
HELPERS = r"""
window.__fst = {
  ws: () => window._trainFacilityLayoutAuthoringApp.workspace,
  session: () => window._trainFacilityLayoutAuthoringApp.workspace.session,
  src: () => window._trainFacilityLayoutAuthoringApp.workspace.structureSource(),
  stats: () => Object.assign({}, window._structureTreeStats),
  rows: () => [...document.querySelectorAll('#structureTreeHost .ip-fst-row')].map(r => ({
    id: r.getAttribute('data-row-id'),
    kind: r.getAttribute('data-row-kind'),
    expanded: r.getAttribute('aria-expanded'),
    selection: r.getAttribute('data-selection'),
    label: r.childNodes[2] ? r.childNodes[2].textContent : '',
  })),
  // Which zone row currently holds a placement, by walking the derived model.
  parentOf: (placementId) => {
    const m = window.InspectorProFacilityStructure
      .deriveStructure(window.__fst.src().layout);
    let found = null;
    m.zoneOrder.forEach(z => m.zones[z].groups.forEach(g => {
      if (g.placementIds.includes(placementId)) found = z;
    }));
    if (found) return found;
    const u = m.unzoned;
    if (u && u.groups.some(g => g.placementIds.includes(placementId))) return 'unzoned';
    return null;
  },
  click: (rowId, mods) => {
    const row = [...document.querySelectorAll('#structureTreeHost .ip-fst-row')]
      .find(r => r.getAttribute('data-row-id') === rowId);
    if (!row) throw new Error('no row ' + rowId);
    row.childNodes[2].dispatchEvent(new MouseEvent('click',
      Object.assign({ bubbles: true }, mods || {})));
  },
  caret: (rowId) => {
    const row = [...document.querySelectorAll('#structureTreeHost .ip-fst-row')]
      .find(r => r.getAttribute('data-row-id') === rowId);
    row.childNodes[0].dispatchEvent(new MouseEvent('click', { bubbles: true }));
  },
};
'ready'
"""


def run(base, headed, shots_dir):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headed)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.base_url = base
        page.on("pageerror", lambda e: failures.append("page error: " + str(e)))

        # ---------------------------------------------- FT4: build from empty
        enter_facility_layout(page, BLANK_LAYOUT)
        page.evaluate(HELPERS)

        start = page.evaluate("() => ({"
                              " base: window.__fst.ws().state.baseRevision,"
                              " zones: window.__fst.src().layout.zones.length,"
                              " placements: window.__fst.src().layout.placements.length })")
        check(
            "the blank layout starts empty",
            start["zones"] == 0 and start["placements"] == 0,
            start,
        )
        check(
            "an empty layout shows the empty state, not a blank pane",
            page.evaluate(
                "() => { const e = document.querySelector('#structureTreeHost .ip-fst-empty');"
                " return !!e && /No zones or equipment yet/.test(e.textContent); }"
            ),
        )
        if shots_dir:
            page.screenshot(path=str(shots_dir / "ft5-empty-layout.png"))

        # Place equipment before any zone exists: it must land in Unzoned.
        placed = page.evaluate(
            """async (asset) => {
              const s = window.__fst.session();
              const ids = [];
              for (const point of asset.points) {
                const st = await s.placeAsset({
                  assetId: asset.assetId,
                  assetDefinitionRevision: asset.assetDefinitionRevision,
                  position: { x: point.x, y: 0, z: point.z },
                });
                const last = st.layout.placements[st.layout.placements.length - 1];
                ids.push(last.placementId);
              }
              return ids;
            }""",
            dict(
                authoring_asset(),
                points=[
                    BUILD_POINTS["inner_a"],
                    BUILD_POINTS["inner_b"],
                    BUILD_POINTS["outer_only"],
                ],
            ),
        )
        check("three assets placed on an empty layout", len(placed) == 3, placed)
        rows = page.evaluate("() => window.__fst.rows()")
        check(
            "placing before any zone exists puts them under Unzoned",
            any(r["id"] == "unzoned" for r in rows) and not any(r["kind"] == "zone" for r in rows),
            [r["id"] for r in rows],
        )

        # Draw a zone around three of them, and a nested zone around two.
        page.evaluate(
            """async (rects) => {
              const s = window.__fst.session();
              await s.createRectangleZone(rects.outer.start, rects.outer.end,
                { label: 'Outer', zoneType: 'receiving' });
              await s.createRectangleZone(rects.inner.start, rects.inner.end,
                { label: 'Inner', zoneType: 'workcell' });
            }""",
            {"outer": OUTER_RECT, "inner": INNER_RECT},
        )
        zones = page.evaluate(
            "() => window.__fst.src().layout.zones.map(z => [z.zoneId, z.label])"
        )
        check("two zones drawn around existing equipment", len(zones) == 2, zones)

        outer = next(z[0] for z in zones if z[1] == "Outer")
        inner = next(z[0] for z in zones if z[1] == "Inner")

        parents = page.evaluate(
            "(ids) => ids.map(id => window.__fst.parentOf(id))", placed
        )
        check(
            "the tree reparents existing equipment when a zone is drawn over it",
            parents[0] == inner and parents[1] == inner and parents[2] == outer,
            dict(zip(placed, parents)),
        )
        check(
            "nothing is left unzoned once zones exist",
            page.evaluate(
                "() => { const m = window.InspectorProFacilityStructure"
                ".deriveStructure(window.__fst.src().layout);"
                " return m.unzoned ? m.unzoned.directCount : 0; }"
            ) == 0,
        )

        # ------------------------------------------- rebuild vs redraw counts
        page.evaluate("() => { window._structureTreeStats.rebuilds = 0;"
                      " window._structureTreeStats.redraws = 0;"
                      " window._structureTreeStats.notifications = 0; }")
        page.evaluate(
            """() => {
              const s = window.__fst.session();
              for (let i = 0; i < 5; i += 1) {
                s.setCameraState({ zoom: 1 + i * 0.1, target: { x: i, y: 0, z: i } });
              }
            }"""
        )
        after_camera = page.evaluate("() => window.__fst.stats()")
        check(
            "a camera pan rebuilds nothing and redraws nothing",
            after_camera["rebuilds"] == 0 and after_camera["redraws"] == 0,
            after_camera,
        )
        check(
            "the camera still reached the structure subscriber",
            after_camera["notifications"] > 0,
            after_camera,
        )

        page.evaluate("(id) => window.__fst.session().select(id)", placed[0])
        after_select = page.evaluate("() => window.__fst.stats()")
        check(
            "a selection change redraws but does not rebuild",
            after_select["rebuilds"] == 0 and after_select["redraws"] > 0,
            after_select,
        )

        before_move = page.evaluate("() => window.__fst.stats().rebuilds")
        page.evaluate(
            """async (arg) => {
              const s = window.__fst.session();
              await s.movePlacements([{ placementId: arg.id, position:
                { x: arg.to.x, y: 0, z: arg.to.z } }]);
            }""",
            {"id": placed[0], "to": BUILD_POINTS["moved"]},
        )
        after_move = page.evaluate("() => window.__fst.stats().rebuilds")
        check("an edit does rebuild", after_move > before_move, (before_move, after_move))
        check(
            "moving equipment across a boundary moves it between zones",
            page.evaluate("(id) => window.__fst.parentOf(id)", placed[0]) == outer,
        )

        # ------------------------------------- expansion survives an edit (1,2)
        # The branch may already be open: selecting a placement earlier made
        # the tree reveal its ancestors, which is FT3 behaviour working. Open
        # it only if it is closed, so this step tests what it claims to.
        opened = page.evaluate(
            """(id) => {
              const row = () => [...document.querySelectorAll('#structureTreeHost .ip-fst-row')]
                .find(r => r.getAttribute('data-row-id') === id);
              if (row().getAttribute('aria-expanded') !== 'true') window.__fst.caret(id);
              return row().getAttribute('aria-expanded');
            }""",
            outer,
        )
        check("a draft branch is open", opened == "true", opened)
        before_children = page.evaluate("() => window.__fst.rows().length")
        check("its children are drawn", before_children > 1, before_children)

        page.evaluate(
            """async (arg) => {
              await window.__fst.session().movePlacements(
                [{ placementId: arg.id, position: { x: arg.to.x, y: 0, z: arg.to.z } }]);
            }""",
            {"id": placed[0], "to": BUILD_POINTS["moved_again"]},
        )
        still_open = page.evaluate(
            "(id) => { const r = window.__fst.rows().find(r => r.id === id);"
            " return r && r.expanded; }", outer
        )
        check(
            "step 2: moving equipment leaves the branch expanded",
            still_open == "true",
            still_open,
        )
        check(
            "and its children are still drawn",
            page.evaluate("() => window.__fst.rows().length") > 1,
        )

        # ----------------------------------------- deletion and reparenting
        page.evaluate(
            """async (zoneId) => {
              const s = window.__fst.session();
              s.select(zoneId);
              await s.deleteSelected();
            }""",
            inner,
        )
        check(
            "deleting a nested zone reparents its contents to the surviving parent",
            page.evaluate("(id) => window.__fst.parentOf(id)", placed[1]) == outer,
        )
        check(
            "and not to Unzoned",
            page.evaluate("(id) => window.__fst.parentOf(id)", placed[1]) != "unzoned",
        )

        page.evaluate("() => window.__fst.session().undo()")
        check(
            "undo restores the nested zone and its membership",
            page.evaluate("(id) => window.__fst.parentOf(id)", placed[1]) == inner,
        )

        # Removing the last zone is the only way back to Unzoned: rule 2 above
        # forbids deleting Outer on its own while Inner would strand equipment
        # outside it, so both go in one gesture.
        page.evaluate(
            """async (zoneIds) => {
              const s = window.__fst.session();
              s.selectMany(zoneIds);
              await s.deleteSelected();
            }""",
            [outer, inner],
        )
        parents_now = page.evaluate(
            "(ids) => ids.map(id => window.__fst.parentOf(id))", placed
        )
        check(
            "removing the last zone drops everything to Unzoned",
            all(parent == "unzoned" for parent in parents_now),
            dict(zip(placed, parents_now)),
        )
        check(
            "the Unzoned branch comes back on the tree",
            any(r["id"] == "unzoned" for r in page.evaluate("() => window.__fst.rows()")),
        )

        page.evaluate("() => window.__fst.session().undo()")
        parents_back = page.evaluate(
            "(ids) => ids.map(id => window.__fst.parentOf(id))", placed
        )
        check(
            "undo restores both zones and every membership",
            parents_back[1] == inner and parents_back[2] == outer,
            dict(zip(placed, parents_back)),
        )

        # ------------------------------ the four-step sequence, steps 3 and 4
        # A real candidate needs a live generation run, which is gated on
        # provider access (see AGENTS.md). The preview is therefore stubbed at
        # the seam this work owns - generationPlanningView.activeLayout() and
        # activePreviewRef() - which is exactly the pair _structureRepresented-
        # Layout reads. What is being verified is the tree's behaviour when a
        # candidate is represented, not the generation pipeline.
        draft_open = page.evaluate("() => window._structureTreeInstance.expandedRowIds()")
        check("the draft has an expanded branch to preserve", len(draft_open) > 0, draft_open)

        page.evaluate(
            """() => {
              const ws = window.__fst.ws();
              const draft = ws.structureSource().layout;
              // A candidate sharing the draft's zone IDs, which is the hard
              // case: shared row IDs must not share expansion state.
              const candidate = JSON.parse(JSON.stringify(draft));
              candidate.placements = candidate.placements.slice(0, 1);
              const view = ws.generationPlanningView || (ws.generationPlanningView = {});
              window.__fstRealActiveLayout = view.activeLayout;
              window.__fstRealPreviewRef = view.activePreviewRef;
              view.activeLayout = () => candidate;
              view.activePreviewRef = () => ({
                candidateRevision: 'cand-1', previewRevision: 'prev-1',
                baseRevision: 'base-1',
              });
              window._structureTreeRefresh();
            }"""
        )
        check(
            "step 3: a candidate is represented and marked read only",
            page.evaluate(
                "() => { const s = document.getElementById('structurePanelScope');"
                " return s ? s.textContent : ''; }"
            ) == "Preview (read only)",
        )
        candidate_open = page.evaluate("() => window._structureTreeInstance.expandedRowIds()")
        check(
            "step 3: its expansion is independent of the draft's",
            candidate_open == [],
            {"draft": draft_open, "candidate": candidate_open},
        )

        # A row click must not reach the session while a preview is represented.
        before_selection = page.evaluate("() => window.__fst.src().selection.length")
        page.evaluate(
            """() => {
              const row = document.querySelector('#structureTreeHost .ip-fst-row');
              if (row) row.childNodes[2].dispatchEvent(
                new MouseEvent('click', { bubbles: true }));
            }"""
        )
        check(
            "no row click reaches the session while a preview is active",
            page.evaluate("() => window.__fst.src().selection.length") == before_selection,
        )

        page.evaluate(
            """() => {
              const view = window.__fst.ws().generationPlanningView;
              view.activeLayout = window.__fstRealActiveLayout;
              view.activePreviewRef = window.__fstRealPreviewRef;
              window._structureTreeRefresh();
            }"""
        )
        check(
            "step 4: dismissing the candidate returns the draft's expansion",
            page.evaluate("() => window._structureTreeInstance.expandedRowIds()") == draft_open,
        )
        check(
            "step 4: the read-only marker is cleared",
            page.evaluate(
                "() => { const s = document.getElementById('structurePanelScope');"
                " return s ? s.textContent : 'missing'; }"
            ) == "",
        )

        # ----------------------------------------------- nothing was saved
        end = page.evaluate("() => ({ base: window.__fst.ws().state.baseRevision,"
                            " draft: window.__fst.ws().state.draftRevision })")
        check(
            "the stored layout was never written: base revision unmoved",
            end["base"] == start["base"],
            (start["base"], end["base"]),
        )
        check(
            "the draft did diverge, so the edits were real",
            end["draft"] != end["base"],
            end,
        )

        # ------------------------------------- FT5: reference layout + a11y
        enter_facility_layout(page, REFERENCE_LAYOUT)
        page.evaluate(HELPERS)
        ref = page.evaluate("() => ({ zones: window.__fst.src().layout.zones.length,"
                            " placements: window.__fst.src().layout.placements.length,"
                            " layoutId: window.__fst.src().layoutId })")
        check(
            "the reference layout loads",
            ref["zones"] == 45 and ref["placements"] == 827,
            ref,
        )
        roots = page.evaluate("() => window.__fst.rows()")
        total = page.evaluate(
            "() => { const m = window.InspectorProFacilityStructure"
            ".deriveStructure(window.__fst.src().layout);"
            " return m.roots.reduce((n, z) => n + m.zones[z].totalCount, 0)"
            "   + (m.unzoned ? m.unzoned.directCount : 0); }"
        )
        check(
            "every placement is accounted for exactly once",
            total == ref["placements"],
            (total, ref["placements"]),
        )

        check(
            "the tree exposes tree/treeitem roles and levels",
            page.evaluate(
                "() => { const h = document.getElementById('structureTreeHost');"
                " const r = h.querySelector('.ip-fst-row');"
                " return h.getAttribute('role') === 'tree'"
                "   && r.getAttribute('role') === 'treeitem'"
                "   && r.getAttribute('aria-level') === '1'"
                "   && r.getAttribute('tabindex') === '-1'; }"
            ),
        )

        # Keyboard: focus a row, open it, move down, and survive a rebuild.
        first_row = roots[0]["id"]
        page.evaluate(
            """(id) => {
              const row = [...document.querySelectorAll('#structureTreeHost .ip-fst-row')]
                .find(r => r.getAttribute('data-row-id') === id);
              row.focus();
              row.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
            }""",
            first_row,
        )
        check(
            "ArrowRight opens a branch from the keyboard",
            page.evaluate(
                "(id) => window.__fst.rows().find(r => r.id === id).expanded", first_row
            ) == "true",
        )
        page.evaluate(
            """(id) => {
              const row = document.activeElement;
              row.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
            }""",
            first_row,
        )
        focused_before = page.evaluate(
            "() => document.activeElement && document.activeElement.getAttribute('data-row-id')"
        )
        check("ArrowDown moves focus to the next row", focused_before not in (None, first_row),
              focused_before)

        # Force a rebuild and confirm focus is still on the same row.
        page.evaluate(
            """() => {
              const ws = window.__fst.ws();
              window._structureTreeView = null;     // force a rebuild
              window._structureTreeRefresh();
            }"""
        )
        focused_after = page.evaluate(
            "() => document.activeElement && document.activeElement.getAttribute('data-row-id')"
        )
        check(
            "keyboard focus survives a rebuild",
            focused_after == focused_before,
            (focused_before, focused_after),
        )

        # ------------------------------------------- FT5: layout competition
        page.evaluate(
            "(id) => window.__fst.session().select("
            "  window.__fst.src().layout.placements[0].placementId)"
        )
        page.wait_for_timeout(4000)
        if shots_dir:
            page.screenshot(path=str(shots_dir / "ft5-reference-layout.png"))

        def viewport_width():
            return page.evaluate(
                "() => { const r = window.__fst.ws().root;"
                " return r ? Math.round(r.getBoundingClientRect().width) : 0; }"
            )

        def pane_width():
            return page.evaluate(
                "() => { const p = document.getElementById('structurePanel');"
                " return p && !p.hidden ? Math.round(p.getBoundingClientRect().width) : 0; }"
            )

        with_pane = viewport_width()
        pane = pane_width()
        check("the structure pane occupies real width", pane > 100, pane)

        page.evaluate("() => window._toggleLeftPanel && window._toggleLeftPanel()")
        page.wait_for_timeout(1500)
        collapsed = viewport_width()
        check(
            "collapsing the pane returns its width to the viewport",
            collapsed >= with_pane + pane - 8,
            {"withPane": with_pane, "paneWidth": pane, "collapsed": collapsed},
        )
        if shots_dir:
            page.screenshot(path=str(shots_dir / "ft5-reference-collapsed.png"))

        # Re-open, then put Sage alongside it: they compete for the same budget.
        page.evaluate("() => window._toggleLeftPanel && window._toggleLeftPanel()")
        # The agent lives in the shared right dock, not in #rightPanel, which
        # is the inspection results panel.
        page.evaluate(
            """() => {
              if (window._setRightDockMode) window._setRightDockMode('agent');
              else {
                const icon = document.querySelector('.activity-bar-icon[data-panel="agent"]');
                if (icon) icon.click();
              }
            }"""
        )
        page.wait_for_timeout(2500)
        both = page.evaluate(
            """() => {
              const agent = document.getElementById('rightDock');
              const shown = agent && agent.offsetParent
                && agent.getBoundingClientRect().width > 0
                && (!window._getRightDockMode || window._getRightDockMode() === 'agent');
              const host = document.getElementById('structureTreeHost');
              return {
                sageOpen: Boolean(shown),
                sageWidth: agent ? Math.round(agent.getBoundingClientRect().width) : 0,
                treeVisible: Boolean(host && host.offsetParent),
                rows: document.querySelectorAll('#structureTreeHost .ip-fst-row').length,
                viewport: Math.round(window.__fst.ws().root.getBoundingClientRect().width),
              };
            }"""
        )
        check("Sage opens alongside the structure pane", both["sageOpen"], both)
        check(
            "the tree stays usable with Sage open",
            both["treeVisible"] and both["rows"] > 0,
            both,
        )
        check(
            "the viewport keeps usable width with both panes open",
            both["viewport"] > 400,
            both,
        )
        if shots_dir:
            page.screenshot(path=str(shots_dir / "ft5-reference-with-sage.png"))

        browser.close()

    print("")
    if failures:
        print("%d passed, %d FAILED" % (passed, len(failures)))
        for item in failures:
            print("  - " + item)
        return 1
    print("%d/%d app checks passed" % (passed, passed))
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--shots", default="")
    args = parser.parse_args()
    shots = pathlib.Path(args.shots) if args.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    return run(args.base, args.headed, shots)


if __name__ == "__main__":
    sys.exit(main())
