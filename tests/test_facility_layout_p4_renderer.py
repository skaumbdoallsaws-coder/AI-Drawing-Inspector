import hashlib
import json
from pathlib import Path

from PIL import Image

from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.validate import validate_layout


ROOT = Path(__file__).resolve().parents[1]
RENDERING = ROOT / "tests" / "fixtures" / "facility_layout" / "rendering"
RESULT = RENDERING / "p4-renderer-result.json"
LAYOUT = RENDERING / "p4-facility-layout.json"
VENDOR = ROOT / "static" / "vendor" / "three" / "0.184.0"
RACK = (
    ROOT
    / "generated"
    / "industrial_assets"
    / "p0_spike"
    / "rack_prototypes"
    / "Pallet Racking_colored.glb"
)
RACK_OVERVIEW = RACK.with_name("Pallet Racking_colored_overview_proxy.glb")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_p4_browser_evidence_is_complete_and_bound_to_sources():
    result = json.loads(RESULT.read_text(encoding="ascii"))
    layout = json.loads(LAYOUT.read_text(encoding="ascii"))
    validate_layout(layout, require_canonical=True)

    assert result["schemaVersion"] == "facility-layout-p4-browser-evidence-v1"
    assert result["passed"] is True
    assert result["checks"]
    assert all(result["checks"].values())
    assert result["layout"]["revision"] == layout_revision(layout)
    assert result["layout"]["placementIds"] == sorted(
        placement["placementId"] for placement in layout["placements"]
    )

    source_paths = {
        "assetCatalogSha256": RENDERING / "p4-asset-catalog.json",
        "facilityLayoutEditorSha256": ROOT / "static" / "facility_layout_editor.js",
        "facilityThreeAdapterSha256": (
            ROOT / "static" / "facility_layout_three_adapter.js"
        ),
        "fixturePageSha256": RENDERING / "p4-renderer.html",
        "fixtureScriptSha256": RENDERING / "p4-renderer.js",
        "gltfLoaderSha256": (
            VENDOR / "examples" / "jsm" / "loaders" / "GLTFLoader.js"
        ),
        "layoutFixtureSha256": LAYOUT,
        "orbitControlsSha256": (
            VENDOR / "examples" / "jsm" / "controls" / "OrbitControls.js"
        ),
        "rackGlbSha256": RACK,
        "rackOverviewSha256": RACK_OVERVIEW,
        "threeModuleSha256": VENDOR / "build" / "three.module.min.js",
        "verifierSha256": ROOT / "tools" / "verify_facility_layout_p4.py",
    }
    for field, path in source_paths.items():
        assert result["source"][field] == _sha256(path)


def test_p4_desktop_and_mobile_screenshots_are_nonblank_and_exact():
    result = json.loads(RESULT.read_text(encoding="ascii"))
    for name, expected_size in (
        ("desktop", (1440, 900)),
        ("mobile", (390, 844)),
    ):
        record = result["screenshots"][name]
        path = ROOT / record["path"]
        assert path.stat().st_size == record["bytes"]
        assert _sha256(path) == record["sha256"]
        with Image.open(path) as image:
            assert image.size == expected_size
            rgb = image.convert("RGB")
            extrema = rgb.getextrema()
        assert all(high - low >= 40 for low, high in extrema)


def test_p4_evidence_covers_renderer_exit_gate():
    checks = json.loads(RESULT.read_text(encoding="ascii"))["checks"]
    required = {
        "desktop_webgl_canvas_nonblank",
        "mobile_webgl_canvas_nonblank",
        "plan_pick_synchronized",
        "real_proxy_glb_loaded",
        "real_three_click_synchronized",
        "six_repeated_racks_instanced",
        "fit_changes_camera_only",
        "context_loss_enters_degraded_mode",
        "degraded_mode_preserves_top_plan",
        "twenty_remounts_completed",
        "remount_leaves_one_canvas",
        "remount_leaves_no_observer_growth",
        "remount_leaves_no_orphan_render_request",
        "no_external_requests",
        "no_page_errors",
        "no_console_errors",
    }
    assert required <= set(checks)
    assert all(checks[name] for name in required)
