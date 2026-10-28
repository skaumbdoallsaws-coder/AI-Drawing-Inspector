from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _html() -> str:
    return (ROOT / "static" / "index.html").read_text("utf-8")


def test_assembly_viewer_exposes_complete_display_style_set() -> None:
    html = _html()

    assert "Object.freeze({ id: 'shaded_edges', label: 'Shaded with Edges' })" in html
    assert "Object.freeze({ id: 'shaded', label: 'Shaded' })" in html
    assert "Object.freeze({ id: 'hidden_lines_removed', label: 'Hidden Lines Removed' })" in html
    assert "Object.freeze({ id: 'hidden_lines_visible', label: 'Hidden Lines Visible' })" in html
    assert "Object.freeze({ id: 'wireframe', label: 'Wireframe' })" in html
    assert "representationSelect.dataset.viewerDisplayStyle = 'assembly'" in html
    assert "toolbar.appendChild(_createDisplayStyleMenu(kind));" in html
    assert "item.setAttribute('role', 'menuitemradio')" in html


def test_display_styles_use_shared_depth_and_feature_edge_rendering() -> None:
    html = _html()

    assert "function _viewerRenderDisplayStyle(kind, renderer, scene, camera)" in html
    assert "_partsManualCreateHiddenLinesRemovedPass(meshes, width, height, options = {})" in html
    assert "presentation: style === 'shaded_edges' ? 'overlay' : 'technical'" in html
    assert "function _viewerCreateHiddenLinesVisiblePass(meshes, width, height, palette)" in html
    assert "depthFunc: THREE.GreaterDepth" in html
    assert "new THREE.LineDashedMaterial" in html
    assert "function _viewerCreateFeatureEdgeGeometry(sourceGeometry)" in html
    assert "new THREE.EdgesGeometry(sourceGeometry, 42)" in html
    assert "VIEWER_FEATURE_EDGE_TRIANGLE_BUDGET = 2000000" in html


def test_display_style_lifecycle_preserves_documentation_capture_authority() -> None:
    html = _html()

    documentation_render = html.index("_partsManualRenderDocumentationTechnicalPass(renderer, scene, camera)")
    viewer_render = html.index("_viewerRenderDisplayStyle('assembly', renderer, scene, camera)")
    assert documentation_render < viewer_render
    assert "const displayStyleRendered = !documentationRendered" in html
    assert "_disposeViewerDisplayPass('assembly');\n                state.assyRenderer.dispose()" in html
    assert "_disposeViewerDisplayPass('part');\n                state.threeRenderer.dispose()" in html
    assert "_viewerRenderDisplayStyle(\n                            'assembly', state.assyRenderer" in html


def test_display_style_is_persistent_and_no_longer_has_a_second_wireframe_toggle() -> None:
    html = _html()

    assert "assyDisplayStyle: 'shaded'," in html and "threeDisplayStyle: 'shaded'," in html
    assert "_setViewerDisplayStyle('assembly', state.assyDisplayStyle || 'shaded')" in html
    assert "select[data-viewer-display-style=\"${kind}\"]" in html
    assert "wireCb.id = 'assy-wireframe'" not in html


def test_each_display_style_has_a_cube_and_the_toolbar_button_is_a_cube() -> None:
    html = _html()

    assert "function _displayStyleIconSvg(style)" in html
    body = html[html.index("function _displayStyleIconSvg(style)"):]
    body = body[:body.index("\n        }\n")]
    for style in ("shaded_edges", "shaded", "hidden_lines_removed", "hidden_lines_visible", "wireframe", "xray"):
        assert f"                {style}: " in body, style
    assert "stroke-dasharray" in body and "currentColor" in body
    assert "swatch.innerHTML = _displayStyleIconSvg(style.id);" in html
    # The display style button shows the shaded-with-edges cube, not the coloured ball.
    assert "if (kind === 'display') {\n                return _displayStyleIconSvg('shaded_edges');" in html
    assert "ballGloss" not in html and ".display-style-swatch" not in html
    # Each item lays the cube and its label out in a row (an inline icon collapsed to a thin bar).
    menu_item = html[html.index("        .display-style-menu-item {"):]
    assert menu_item[:menu_item.index("}")].count("display: flex;") == 1


def test_a_finished_feature_rehydrate_stops_counting_as_pending_work() -> None:
    html = _html()

    # The desktop close handler refuses while the assembly row reports pending work.
    assert "state._assyRehydratePromise || state.pendingExecutionReceipts.length)" in html
    set_at = html.index("            state._assyRehydratePromise = rebuild;\n")
    assert html.index("if (state._assyRehydratePromise === rebuild) state._assyRehydratePromise = null;") - set_at < 300


def test_only_a_running_documentation_build_counts_as_pending_work() -> None:
    html = _html()

    observer = html[html.index("function _desktopInspectOtherWorkflows()"):][:4000]
    documentation = observer[observer.index("documentation: row("):observer.index("training: row(")]
    assert "state.partsManualDocumentationGeneration?.status === 'running'" in documentation
    assert "state.partsManualDocumentationSageWork?.active" in documentation
    assert "|| state.partsManualDocumentationGeneration\n" not in documentation


def test_an_unframed_camera_is_never_saved_as_the_view_to_restore() -> None:
    html = _html()

    save = html[html.index("function _saveAssemblyCameraState()"):][:900]
    assert save.index("if (state.assyCamera.position.distanceToSquared(state.assyControls.target) < 1e-12) return;") \
        < save.index("state.assyCameraState = {")
