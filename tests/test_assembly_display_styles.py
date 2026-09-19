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

    assert "assyDisplayStyle: 'shaded_edges'" in html
    assert "_setViewerDisplayStyle('assembly', state.assyDisplayStyle || 'shaded_edges')" in html
    assert "select[data-viewer-display-style=\"${kind}\"]" in html
    assert "wireCb.id = 'assy-wireframe'" not in html
