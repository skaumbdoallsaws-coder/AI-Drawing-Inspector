import hashlib
import json
from pathlib import Path

from PIL import Image

from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.validate import validate_layout


ROOT = Path(__file__).resolve().parents[1]
FACILITY_FIXTURES = ROOT / "tests" / "fixtures" / "facility_layout"
AUTHORING = FACILITY_FIXTURES / "authoring"
RENDERING = FACILITY_FIXTURES / "rendering"
RESULT = AUTHORING / "p5-authoring-result.json"
VENDOR = ROOT / "static" / "vendor" / "three" / "0.184.0"
OVERVIEW = (
    ROOT
    / "generated"
    / "industrial_assets"
    / "p0_spike"
    / "rack_prototypes"
    / "Pallet Racking_colored_overview_proxy.glb"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _result() -> dict:
    return json.loads(RESULT.read_text(encoding="ascii"))


def test_p5_browser_evidence_is_complete_and_bound_to_real_sources():
    result = _result()
    layout = result["finalLayout"]
    validate_layout(layout, require_canonical=False)

    assert result["schemaVersion"] == "facility-layout-p5-browser-evidence-v1"
    assert result["passed"] is True
    assert result["checks"]
    assert all(result["checks"].values())
    assert result["final"]["layoutRevision"] == layout_revision(layout)
    assert result["final"]["placementCount"] == len(layout["placements"])
    assert result["final"]["zoneCount"] == len(layout["zones"])
    assert len(result["final"]["revision"]) == 64
    assert result["scope"] == {
        "actualFacilityService": True,
        "actualPlanAdapter": True,
        "actualSessionModule": True,
        "actualThreeAdapter": True,
        "actualWorkspaceModule": True,
        "p6ConstraintValidationIncluded": False,
        "phase": "P5",
        "sageLoaded": False,
    }

    source_paths = {
        "assetCatalogSha256": RENDERING / "p4-asset-catalog.json",
        "authorityFixtureSha256": (
            FACILITY_FIXTURES / "p0_authority_documents.json"
        ),
        "facilityLayoutEditorSha256": (
            ROOT / "static" / "facility_layout_editor.js"
        ),
        "facilityLayoutSessionSha256": (
            ROOT / "static" / "facility_layout_session.js"
        ),
        "facilityLayoutWorkspaceSha256": (
            ROOT / "static" / "facility_layout_workspace.js"
        ),
        "facilityLayoutWorkspaceCssSha256": (
            ROOT / "static" / "facility_layout_workspace.css"
        ),
        "facilityThreeAdapterSha256": (
            ROOT / "static" / "facility_layout_three_adapter.js"
        ),
        "fixturePageSha256": AUTHORING / "p5-authoring.html",
        "fixtureScriptSha256": AUTHORING / "p5-authoring.js",
        "gltfLoaderSha256": (
            VENDOR / "examples" / "jsm" / "loaders" / "GLTFLoader.js"
        ),
        "orbitControlsSha256": (
            VENDOR / "examples" / "jsm" / "controls" / "OrbitControls.js"
        ),
        "overviewGlbSha256": OVERVIEW,
        "p4LayoutSeedSha256": RENDERING / "p4-facility-layout.json",
        "threeModuleSha256": VENDOR / "build" / "three.module.min.js",
        "verifierSha256": ROOT / "tools" / "verify_facility_layout_p5.py",
    }
    assert set(result["source"]) == set(source_paths)
    for field, path in source_paths.items():
        assert result["source"][field] == _sha256(path)


def test_p5_exit_gate_checks_cover_requested_browser_behaviors():
    checks = _result()["checks"]
    required = {
        "actual_production_backend_preview_apply",
        "workspace_loaded_without_sage",
        "asset_tree_uses_stable_id_payload",
        "server_allocates_stable_placement_ids",
        "plan_drop_after_fit_resize_pan_zoom_exact",
        "three_drop_after_fit_orbit_resize_exact",
        "plan_ghost_is_transient_in_both_views",
        "three_ghost_is_transient_in_both_views",
        "grid_snap_applied_to_plan_and_three",
        "each_drop_is_one_undo_gesture",
        "marquee_selects_two_placements",
        "multi_move_is_one_undo_gesture",
        "user_drag_converts_auto_to_manual",
        "undo_redo_restore_exact_multi_move",
        "duplicate_and_delete_cover_multi_selection",
        "rotation_is_exact_quarter_turn",
        "locked_placement_never_moves",
        "invalid_floor_drop_changes_nothing",
        "rectangle_zone_has_exact_dimensions",
        "polygon_zone_has_measured_dimensions",
        "save_is_one_atomic_apply",
        "save_reopen_preserves_exact_layout",
        "save_reopen_clears_history",
        "real_local_three_proxy_rendered",
        "p6_constraint_warning_visible",
        "light_and_dark_themes_render",
        "mobile_workspace_remains_visible",
        "mobile_ghost_and_three_canvas_work",
        "desktop_teardown_leaves_no_leaks",
        "mobile_teardown_leaves_no_leaks",
        "no_external_requests",
        "no_failed_requests",
        "no_page_errors",
        "no_unexpected_failed_http_responses",
        "no_unexpected_console_errors",
    }
    assert required <= set(checks)
    assert all(checks[name] for name in required)


def test_p5_evidence_preserves_exact_world_state_and_transaction_semantics():
    result = _result()
    evidence = result["evidence"]
    authoring = evidence["authoring"]
    persistence = evidence["persistence"]

    assert evidence["plan"]["drop"]["actualWorld"] == (
        evidence["plan"]["drop"]["expectedWorld"]
    )
    assert evidence["three"]["drop"]["actualWorld"] == (
        evidence["three"]["drop"]["expectedWorld"]
    )
    assert authoring["move"]["operationCount"] == 2
    assert authoring["move"]["historyAfter"] == (
        authoring["move"]["historyBefore"] + 1
    )
    assert authoring["move"]["autoPositionMode"] == "manual"
    assert authoring["locking"]["placementUnchanged"] is True
    assert authoring["locking"]["historyUnchanged"] is True
    rectangle_dimensions = authoring["zones"]["rectangleDimensions"]
    assert rectangle_dimensions["depth"] == 5
    assert rectangle_dimensions["width"] == 8
    assert len(authoring["zones"]["polygonBoundary"]) == 4
    assert persistence["exact"] is True
    assert persistence["before"]["placements"] == (
        persistence["reopened"]["placements"]
    )
    assert persistence["before"]["zones"] == persistence["reopened"]["zones"]
    assert persistence["reopened"] == result["finalLayout"]
    assert persistence["applyCalls"] == 1
    assert persistence["appliedOperationCount"] == (
        persistence["operationCount"]
    )

    assert result["network"]["offlineOnly"] is True
    assert result["network"]["sageRequests"] == []
    assert result["network"]["blockedExternalRequests"] == []
    assert result["network"]["unexpectedFailedResponses"] == []
    assert result["network"]["failedRequests"] == []
    assert result["pageErrors"] == []
    assert result["unexpectedConsoleErrors"] == []


def test_p5_desktop_mobile_and_three_screenshots_are_exact_and_nonblank():
    result = _result()
    expected_sizes = {
        "desktop": (1440, 900),
        "mobile": (390, 844),
    }
    for name, record in result["screenshots"].items():
        path = ROOT / record["path"]
        assert path.stat().st_size == record["bytes"]
        assert _sha256(path) == record["sha256"]
        with Image.open(path) as image:
            size = image.size
            extrema = image.convert("RGB").getextrema()
        if name in expected_sizes:
            assert size == expected_sizes[name]
        else:
            assert size[0] > 500
            assert size[1] > 400
        assert all(high - low >= 40 for low, high in extrema)
