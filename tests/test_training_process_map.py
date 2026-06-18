"""Static guards for the Training-tab product-structure MVP.

The racing-bike process map is a working draft, but the frontend should
keep loading it and rendering the Product Structure selector while the
data is being curated.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]

# Mirror the generic-default detectors the frontend uses so the test asserts
# the same contract: robotic JSON copy is rewritten, hand-written copy is kept.
GENERIC_JOIN_RE = re.compile(r"^Bring in .+ and keep previously joined parts highlighted\.$")
GENERIC_VERIFY_RE = re.compile(r"^Confirm .+ is seated in the assembled pose before continuing\.$")


def test_training_tab_process_map_markers_present():
    html = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    for marker in [
        "trainProcessStructurePanel",
        "Product Structure",
        "train-process-tree",
        "train-process-children",
        "train-process-node-toggle",
        "trainProcessDiagram",
        "data-training-product-structure-diagram",
        "data-training-process-tree",
        "data-training-module-branch",
        "data-training-module-expanded",
        "data-training-subassembly-group",
        "data-training-component-card",
        "Racing Bike Product Structure",
        "Unique Items Needed",
        "trainUniqueItemsSection",
        "data-training-unique-items",
        "_trainEnsureProcessMapLoaded",
        "_trainBuildProcessMapProcedure",
        "_trainRenderProcessDiagram",
        "_trainRenderUniqueItemsSection",
        "_trainSelectUniqueItem",
        "_trainFindProcessNodeForPartId",
        "_trainHandleUniqueItemActivate",
        "_trainProcessNodeById",
        "_trainChildProcessNodes",
        "_trainSelectedProcessPathIds",
        "_trainExpandedModuleNodeIds",
        "expandedSubassemblyNodeIds",
        "_trainIsModuleExpanded",
        "_trainSetModuleExpanded",
        "_trainIsSubassemblyExpanded",
        "_trainSetSubassemblyExpanded",
        "_trainExpandAncestorModule",
        "_trainExpandAncestorSubassembly",
        "_trainProcessPathNodes",
        "_trainSelectedModuleNode",
        "_trainSelectedSubassemblyNode",
        "_trainSyncAssemblyPreviewToSelection",
        "_trainOpenUniqueItemPreview",
        "_trainCloseUniqueItemPreview",
        "_trainOpenAssemblyPreview",
        "_trainCloseAssemblyPreview",
        "_trainAssemblyPreviewConfig",
        "_trainRenderAssemblyPreviewFacts",
        "_trainInitUniqueItemPreviewViewer",
        "_trainDisposeUniqueItemPreviewViewer",
        "_trainCreateUniqueItemPreviewControls",
        "trainUniquePreviewBackdrop",
        "trainAssemblyPreviewBackdrop",
        "Back to board",
        "Interactive 3D preview",
        "Interactive 3D assembly preview",
        "Drag to orbit",
        "html[data-theme=\"dark\"] .train-process-diagram",
        "html[data-theme=\"dark\"] .train-unique-preview-panel",
        "assemblyGlbUrl",
        "_trainDiagramCard",
        "_trainDiagramComponentCard",
        "_trainAppendPartThumbStrip",
        "_trainAppendAssemblyShot",
        "_trainSelectedProcessNode",
        "train-diagram-module-lanes",
        "module-count-2",
        "train-diagram-module-card",
        "train-diagram-subassembly-card",
        "train-diagram-subassembly-stack",
        "train-diagram-component-list",
        "data-training-subassembly-expanded",
        "train-diagram-card-toggle",
        "Show components",
        "Hide components",
        "train-unique-preview-path",
        "train-unique-preview-path-chip",
        "train-connector-flow-vertical",
        "train-connector-flow-horizontal",
        "/generated/training/racing-bike/racing_bike_process_map_working_draft.json",
        "/generated/training/racing-bike/racing_bike_unique_items.json",
        "/generated/training/racing-bike/racing_bike_subassembly_visuals.json",
        "/generated/training/racing-bike/racing_bike_guided_build_plan.json",
        "/generated/training/racing-bike/part_cards",
        "/generated/training/racing-bike/part_colored_iso",
        "/generated/training/racing-bike/assembly_glb/racing_bike_assembly.glb",
        "/generated/training/racing-bike/assembly_reference",
        "subassemblyVisualsUrl",
        "guidedBuildPlanUrl",
        "processMapLoadPromise",
        "viewportMode",
        "assemblyContextLoadPromise",
        "pendingStepVisualState",
        "pendingCameraFrameTimer",
        "_trainVisualAssetForNode",
        "_trainGuidedBuildPlanForNode",
        "_trainAppendNodeVisual",
        "_trainRenderNodeVisualPlaceholder",
        "_trainBuildGuidedPlanProcedure",
        "_trainEnsureTrainingAssemblyContext",
        "_trainEnsureLiveAssemblyViewer",
        "_trainShowProcessBoard",
        "_trainFrameStepInViewport",
        "_assyCameraDistanceForBounds",
        "_trainingShowProcessBoard",
        "_trainingEnsureLiveAssemblyViewer",
        "_trainDimAllAssemblyParts",
        "_computeGuidedAssemblyTargetPositions",
        "_animateGuidedAssemblyState",
        "_trainingApplyNarrationSegmentView",
        "Loading racing-bike assembly context",
        "Show the product structure board",
        "data-training-subassembly-visual",
        "Visual pending",
        "_buildProductStructureConfigsFromProcessMap",
        "_renderProductStructureConfigSection",
        "_selectAssemblyPartConfig",
        "_toggleAssemblyPartConfig",
        "_syncProductStructureSelectionParts",
        "_clearProductStructureSelections",
        "partExplorerProductStructureSection",
        "partExplorerProductStructureSummary",
        "partExplorerStructureListScroll",
        "activeAssemblyConfigKeys",
        "activeAssemblyConfigParts",
        "data-assembly-product-structure-section",
        "data-assembly-product-structure-summary",
        "data-assembly-product-structure-list",
        "data-assembly-structure-config",
        "data-assembly-structure-module-group",
        "data-assembly-structure-subassemblies-for",
        "data-assembly-structure-subassembly-block",
        "data-assembly-structure-parts-for",
        "data-assembly-structure-part-number",
        "part-explorer-structure-module-group",
        "part-explorer-structure-sublist",
        "part-explorer-structure-subassembly-block",
        "part-explorer-structure-partlist",
        "part-explorer-structure-part-row",
        "part-explorer-structure-part-id",
        "part-explorer-structure-part-name",
        "Product Structure",
        "Root / module / subassembly review configs",
        "configs:",
        "modules",
        "subassemblies",
        "Loading product-structure configs",
        "Root Assembly",
        "Reset",
    ]:
        assert marker in html


def test_racing_bike_process_map_working_draft_shape():
    path = (
        REPO_ROOT
        / "generated"
        / "training"
        / "racing-bike"
        / "racing_bike_process_map_working_draft.json"
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schemaVersion"] == "racing-bike-process-map-working-draft-0.17"
    assert data["status"] == "working_draft_rb034_moved_to_swingarm"
    assert data["productName"] == "Racing Bike Assembly"
    # Internal Mechanical subtree (incl. Front Wheel) review cleared for the demo
    # recording; only the Bodywork part RB-024 remains under review.
    assert data["reviewRequiredPartIds"] == ["RB-024"]

    nodes = data["nodes"]
    assert any(node["level"] == 0 and node["name"] == "Complete Racing Bike Assembly" for node in nodes)
    level_1 = [node for node in nodes if node["level"] == 1]
    level_2 = [node for node in nodes if node["level"] == 2]
    level_3 = [node for node in nodes if node["level"] == 3]
    assert len(level_1) == 2
    assert len(level_2) == 6
    assert len(level_3) == 47
    assert [node["name"] for node in level_1] == [
        "Internal Mechanical Assembly",
        "Bodywork / Exterior Assembly",
    ]
    assert level_1[0]["partIds"] == [
        "RB-044",
        "RB-045",
        "RB-030",
        "RB-017",
        "RB-018",
        "RB-028",
        "RB-029",
        "RB-012",
        "RB-013",
        "RB-026",
        "RB-036",
        "RB-015",
        "RB-011",
        "RB-014",
        "RB-019",
        "RB-025",
        "RB-016",
        "RB-004",
        "RB-005",
        "RB-006",
        "RB-007",
        "RB-034",
        "RB-038",
        "RB-043",
        "RB-039",
        "RB-040",
        "RB-035",
        "RB-037",
        "RB-033",
        "RB-032",
        "RB-031",
        "RB-042",
        "RB-002",
        "RB-041",
        "RB-001",
        "RB-020",
        "RB-027",
        "RB-009",
        "RB-008",
        "RB-010",
    ]
    assert level_1[1]["partIds"] == [
        "RB-003",
        "RB-021",
        "RB-022",
        "RB-023",
        "RB-024",
        "RB-046",
        "RB-047",
    ]
    assert all("partIds" in node and "partNames" in node for node in level_1)
    assert {node["name"] for node in level_2} == {
        "Front Wheel & Brake",
        "Rear Wheel & Brake",
        "Swingarm & Linkage",
        "Side Fairings",
        "Seat & Tail",
        "Exhaust System",
    }
    parent_by_subassembly = {node["name"]: node["parentNodeId"] for node in level_2}
    part_ids_by_subassembly = {node["name"]: node["partIds"] for node in level_2}
    assert part_ids_by_subassembly["Swingarm & Linkage"] == [
        "RB-044",
        "RB-045",
        "RB-030",
        "RB-017",
        "RB-018",
        "RB-028",
        "RB-029",
        "RB-012",
        "RB-013",
        "RB-026",
        "RB-036",
        "RB-015",
        "RB-011",
        "RB-014",
        "RB-019",
        "RB-025",
        "RB-016",
        "RB-004",
        "RB-005",
        "RB-006",
        "RB-007",
        "RB-034",
    ]
    assert part_ids_by_subassembly["Front Wheel & Brake"] == [
        "RB-038",
        "RB-043",
        "RB-039",
        "RB-040",
        "RB-035",
        "RB-037",
        "RB-033",
        "RB-032",
    ]
    assert part_ids_by_subassembly["Rear Wheel & Brake"] == [
        "RB-031",
        "RB-042",
        "RB-002",
        "RB-041",
        "RB-001",
        "RB-020",
        "RB-027",
    ]
    assert part_ids_by_subassembly["Seat & Tail"] == [
        "RB-003",
        "RB-021",
        "RB-022",
    ]
    assert part_ids_by_subassembly["Side Fairings"] == [
        "RB-023",
        "RB-024",
        "RB-046",
        "RB-047",
    ]
    assert "Handlebar Controls" not in part_ids_by_subassembly
    assert "Fasteners & Small Hardware" not in part_ids_by_subassembly
    assert "Fairing Subframe / Stay" not in part_ids_by_subassembly
    assert "Fenders & Guards" not in part_ids_by_subassembly
    assert "Front Cowl & Screen" not in part_ids_by_subassembly
    assert "Foot Controls" not in part_ids_by_subassembly
    for name in {
        "Front Wheel & Brake",
        "Rear Wheel & Brake",
        "Swingarm & Linkage",
        "Exhaust System",
    }:
        assert parent_by_subassembly[name] == "L1-001"
    for name in {
        "Side Fairings",
        "Seat & Tail",
    }:
        assert parent_by_subassembly[name] == "L1-002"
    assert all(len(node["partIds"]) == 1 for node in level_3)
    part_names = {node["componentId"]: node["name"] for node in level_3}
    assert part_names["RB-046"] == "Side Fairing Panel (Left)"
    assert part_names["RB-047"] == "Side Fairing Panel (Right)"
    assert part_names["RB-009"] == "Exhaust Header & Muffler"
    assert part_names["RB-008"] == "Exhaust Clamp Band A"
    assert part_names["RB-010"] == "Exhaust Clamp Band B"
    assert part_names["RB-001"] == "Rear Brake Pad"
    assert part_names["RB-035"] == "Front Brake Pad A"
    assert part_names["RB-037"] == "Front Brake Pad B"
    assert part_names["RB-032"] == "Front Wheel Shaft"
    assert part_names["RB-033"] == "Front Hub Inner Sleeve Spacer"


def test_racing_bike_process_map_approved_baseline_shape():
    path = (
        REPO_ROOT
        / "generated"
        / "training"
        / "racing-bike"
        / "racing_bike_process_map_approved_baseline.json"
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schemaVersion"] == "racing-bike-process-map-approved-baseline-2026-05-31"
    assert data["status"] == "approved_baseline"
    assert data["approvedAt"] == "2026-05-31"
    assert data["approvedFrom"] == "racing_bike_process_map_working_draft.json"
    assert data["productName"] == "Racing Bike Assembly"
    assert data["reviewRequiredPartIds"] == [
        "RB-011",
        "RB-014",
        "RB-015",
        "RB-019",
        "RB-020",
        "RB-024",
        "RB-025",
        "RB-030",
        "RB-031",
        "RB-038",
        "RB-041",
        "RB-042",
        "RB-043",
    ]

    nodes = data["nodes"]
    level_1 = [node for node in nodes if node["level"] == 1]
    level_2 = [node for node in nodes if node["level"] == 2]
    level_3 = [node for node in nodes if node["level"] == 3]
    assert len(level_1) == 2
    assert len(level_2) == 6
    assert len(level_3) == 47
    assert [node["name"] for node in level_1] == [
        "Internal Mechanical Assembly",
        "Bodywork / Exterior Assembly",
    ]
    assert {node["name"] for node in level_2} == {
        "Front Wheel & Brake",
        "Rear Wheel & Brake",
        "Swingarm & Linkage",
        "Side Fairings",
        "Seat & Tail",
        "Exhaust System",
    }

    component_part_ids = [node["partIds"][0] for node in level_3]
    assert len(component_part_ids) == 47
    assert len(set(component_part_ids)) == 47
    assert set(component_part_ids) == {f"RB-{idx:03d}" for idx in range(1, 48)}


def test_racing_bike_visual_assets_are_served_with_process_map():
    base = REPO_ROOT / "generated" / "training" / "racing-bike"
    part_cards = sorted((base / "part_cards").glob("RB-*_card.png"))
    assert len(part_cards) == 47
    assert (base / "part_cards" / "RB-001_part-01_card.png").exists()
    assert (base / "part_cards" / "RB-047_part-47_card.png").exists()
    part_iso = sorted((base / "part_colored_iso").glob("RB-*_colored_iso.png"))
    assert len(part_iso) == 47
    assert (base / "part_colored_iso" / "RB-001_colored_iso.png").exists()
    assert (base / "part_colored_iso" / "RB-047_colored_iso.png").exists()
    part_preview = sorted((base / "part_iso_preview").glob("RB-*_preview.png"))
    assert len(part_preview) == 47
    assert (base / "part_iso_preview" / "RB-001_preview.png").exists()
    assert (base / "part_iso_preview" / "RB-047_preview.png").exists()
    part_glb = sorted((base / "part_glb").glob("RB-*_viewer.glb"))
    assert len(part_glb) == 47
    assert (base / "part_glb" / "RB-001_viewer.glb").exists()
    assert (base / "part_glb" / "RB-047_viewer.glb").exists()
    assert (base / "assembly_glb" / "racing_bike_assembly.glb").exists()
    manifest = json.loads((base / "part_colored_iso_manifest.json").read_text(encoding="utf-8"))
    assert manifest["source"] == "User Library-racing bike_assembly.json partColorMapping"
    assert manifest["thumbnailCount"] == 47
    assert manifest["missingColorPartIds"] == []
    assert manifest["colors"]["RB-001"] == "#E6194B"
    assert manifest["colors"]["RB-047"] == "#3CB44B"
    assert (base / "assembly_reference" / "assembly_reference_side_left_labeled.png").exists()


def test_racing_bike_subassembly_visual_manifest_and_guided_build_plan():
    base = REPO_ROOT / "generated" / "training" / "racing-bike"
    process = json.loads((base / "racing_bike_process_map_working_draft.json").read_text(encoding="utf-8"))
    visual = json.loads((base / "racing_bike_subassembly_visuals.json").read_text(encoding="utf-8"))
    plan = json.loads((base / "racing_bike_guided_build_plan.json").read_text(encoding="utf-8"))

    assert visual["schemaVersion"] == "racing-bike-subassembly-visuals-0.1"
    assert plan["schemaVersion"] == "racing-bike-guided-build-plan-0.1"
    assert visual["productName"] == "Racing Bike Assembly"
    assert plan["productName"] == "Racing Bike Assembly"
    assert "SolidWorks assemblies with exploded views" in visual["source"]
    assert "fully exploded and dimmed" in plan["motionModel"]
    assert plan["solidWorksExplodeSequenceRole"].startswith("Used only as motion vectors")

    expected_visual_nodes = {
        "L0-000": "User Library-racing bike.sldasm",
        "L1-001": "Internal Mechanical Assembly.SLDASM",
        "L1-002": "bodyworkAssembly.SLDASM",
        "L1-001-01": "Swingarm&Linkage.SLDASM",
        "L1-001-02": "Front wheel & brake.SLDASM",
        "L1-001-03": "rear wheel & brake.SLDASM",
        "L1-001-06": "Exhaust System.SLDASM",
        "L1-002-03": "seat_tail_subassembly.SLDASM",
        "L1-002-05": "Side_Fairings_Assembly.SLDASM",
    }
    expected_export_slugs = {
        "L1-001": "internal_mechanical_assembly",
        "L1-002": "bodywork_exterior_assembly",
        "L1-001-01": "swingarm_linkage",
        "L1-001-02": "front_wheel_brake",
        "L1-001-03": "rear_wheel_brake",
        "L1-001-06": "exhaust_system",
        "L1-002-03": "seat_tail",
        "L1-002-05": "side_fairings",
    }
    expected_explode_counts = {
        "L1-001": 4,
        "L1-002": 2,
        "L1-001-01": 14,
        "L1-001-02": 7,
        "L1-001-03": 7,
        "L1-001-06": 3,
        "L1-002-03": 2,
        "L1-002-05": 4,
    }
    assert set(visual["nodes"]) == set(expected_visual_nodes)
    for node_id, source_name in expected_visual_nodes.items():
        item = visual["nodes"][node_id]
        assert item["sourceSldasm"] == source_name
        assert item["sourceExists"] is True
        assert item["expectedGlbUrl"].startswith("/generated/training/racing-bike/")
        assert item["expectedPreviewImage"].startswith("/generated/training/racing-bike/")
    assert visual["nodes"]["L0-000"]["assetStatus"] == "web_assets_available"
    assert visual["nodes"]["L0-000"]["glbUrl"].endswith("/assembly_glb/racing_bike_assembly.glb")
    for node_id, slug in expected_export_slugs.items():
        item = visual["nodes"][node_id]
        assert item["assetStatus"] == "web_assets_available"
        assert item["glbUrl"] == f"/generated/training/racing-bike/subassembly_glb/{slug}.glb"
        assert item["previewImage"] == f"/generated/training/racing-bike/subassembly_preview/{slug}.png"
        assert item["extractionJsonUrl"] == f"/generated/training/racing-bike/subassembly_extracts/{slug}.json"
        assert item["explodeStepCount"] == expected_explode_counts[node_id]
        assert (base / "subassembly_glb" / f"{slug}.glb").exists()
        assert (base / "subassembly_preview" / f"{slug}.png").exists()
        assert (base / "subassembly_extracts" / f"{slug}.json").exists()

    nodes_by_id = {node["nodeId"]: node for node in process["nodes"]}
    plans = plan["plansByNodeId"]
    assert set(plans) == set(expected_visual_nodes)
    assert plans["L0-000"]["startState"] == "fully_exploded_dimmed"
    assert plans["L0-000"]["retentionMode"] == "previous_joined_parts_remain_highlighted"
    assert plans["L0-000"]["sequenceAuthority"] == "operator_defined_required_not_solidworks_explode_order"
    assert [step["targetNodeId"] for step in plans["L0-000"]["steps"]] == ["L1-001", "L1-002"]
    assert [step["targetNodeId"] for step in plans["L1-001"]["steps"]] == [
        "L1-001-01",
        "L1-001-02",
        "L1-001-03",
        "L1-001-06",
    ]
    assert [step["targetNodeId"] for step in plans["L1-002"]["steps"]] == [
        "L1-002-03",
        "L1-002-05",
    ]
    assert len(plans["L1-001-01"]["steps"]) == 22
    assert plans["L1-001-01"]["steps"][0]["targetPartIds"] == ["RB-044"]
    assert plans["L1-001-01"]["steps"][0]["accumulatedPartIds"] == ["RB-044"]
    assert plans["L1-001-01"]["steps"][-1]["targetPartIds"] == ["RB-034"]
    assert plans["L1-001-01"]["steps"][-1]["accumulatedPartIds"] == nodes_by_id["L1-001-01"]["partIds"]
    for node_id, build in plans.items():
        assert build["sourceSldasm"] == visual["nodes"][node_id]["sourceSldasm"]
        for step in build["steps"]:
            assert step["motion"] == "collapse_target_to_assembled_pose_keep_prior_joined_lit"
            assert set(step["targetPartIds"]).issubset(set(nodes_by_id[node_id]["partIds"]))
            assert set(step["accumulatedPartIds"]).issubset(set(nodes_by_id[node_id]["partIds"]))


def test_racing_bike_unique_items_inventory_shape():
    base = REPO_ROOT / "generated" / "training" / "racing-bike"
    data = json.loads((base / "racing_bike_unique_items.json").read_text(encoding="utf-8"))
    assert data["schemaVersion"] == "racing-bike-unique-items-0.14"
    assert data["productName"] == "Racing Bike Assembly"
    assert data["uniqueItemCount"] == 47
    assert data["totalQuantity"] == 47
    assert data["missingQuantityPartIds"] == []
    assert len(data["items"]) == 47
    assert all(item["partId"].startswith("RB-") for item in data["items"])
    assert all(item["quantity"] >= 1 for item in data["items"])
    assert data["items"][0]["image"].endswith("/RB-001_colored_iso.png")
    assert data["items"][0]["previewImage"].endswith("/RB-001_preview.png")
    assert data["items"][0]["glbUrl"].endswith("/RB-001_viewer.glb")
    assert data["items"][0]["displayColor"] == "#E6194B"
    item_map = {item["partId"]: item for item in data["items"]}
    assert item_map["RB-001"]["module"] == "internal_mechanical_assembly"
    assert item_map["RB-001"]["classificationGroup"] == "running_gear_brakes"
    assert item_map["RB-001"]["recommendedSubassembly"] == "rear_wheel_brake"
    assert item_map["RB-001"]["displayName"] == "Rear Brake Pad"
    assert item_map["RB-001"]["reviewRequired"] is False
    assert item_map["RB-020"]["module"] == "internal_mechanical_assembly"
    assert item_map["RB-020"]["classificationGroup"] == "running_gear_brakes"
    assert item_map["RB-020"]["recommendedSubassembly"] == "rear_wheel_brake"
    # Internal Mechanical subtree review cleared for the demo recording.
    assert item_map["RB-020"]["reviewRequired"] is False
    assert item_map["RB-035"]["recommendedSubassembly"] == "front_wheel_brake"
    assert item_map["RB-035"]["displayName"] == "Front Brake Pad A"
    assert item_map["RB-035"]["reviewRequired"] is False
    assert item_map["RB-037"]["recommendedSubassembly"] == "front_wheel_brake"
    assert item_map["RB-037"]["displayName"] == "Front Brake Pad B"
    assert item_map["RB-037"]["reviewRequired"] is False
    assert item_map["RB-031"]["module"] == "internal_mechanical_assembly"
    assert item_map["RB-031"]["classificationGroup"] == "running_gear_brakes"
    assert item_map["RB-031"]["recommendedSubassembly"] == "rear_wheel_brake"
    assert item_map["RB-041"]["module"] == "internal_mechanical_assembly"
    assert item_map["RB-041"]["classificationGroup"] == "running_gear_brakes"
    assert item_map["RB-041"]["recommendedSubassembly"] == "rear_wheel_brake"
    for moved_part_id in [
        "RB-017",
        "RB-018",
        "RB-028",
        "RB-029",
        "RB-012",
        "RB-013",
        "RB-026",
        "RB-036",
        "RB-015",
        "RB-011",
        "RB-014",
        "RB-019",
        "RB-025",
        "RB-016",
        "RB-004",
        "RB-005",
        "RB-006",
        "RB-007",
        "RB-034",
    ]:
        assert item_map[moved_part_id]["module"] == "internal_mechanical_assembly"
        assert item_map[moved_part_id]["classificationGroup"] == "running_gear_brakes"
        assert item_map[moved_part_id]["recommendedSubassembly"] == "swingarm_linkage"
    assert item_map["RB-032"]["displayName"] == "Front Wheel Shaft"
    assert item_map["RB-032"]["recommendedSubassembly"] == "front_wheel_brake"
    assert item_map["RB-032"]["reviewRequired"] is False
    assert item_map["RB-033"]["displayName"] == "Front Hub Inner Sleeve Spacer"
    assert item_map["RB-033"]["recommendedSubassembly"] == "front_wheel_brake"
    assert item_map["RB-033"]["reviewRequired"] is False
    assert item_map["RB-038"]["recommendedSubassembly"] == "front_wheel_brake"
    assert item_map["RB-040"]["recommendedSubassembly"] == "front_wheel_brake"
    assert item_map["RB-009"]["module"] == "internal_mechanical_assembly"
    assert item_map["RB-009"]["classificationGroup"] == "controls_exhaust_hardware"
    assert item_map["RB-027"]["module"] == "internal_mechanical_assembly"
    assert item_map["RB-027"]["classificationGroup"] == "running_gear_brakes"
    assert item_map["RB-027"]["recommendedSubassembly"] == "rear_wheel_brake"
    assert item_map["RB-021"]["recommendedSubassembly"] == "seat_tail"
    assert item_map["RB-022"]["recommendedSubassembly"] == "seat_tail"
    assert item_map["RB-023"]["recommendedSubassembly"] == "side_fairings"
    assert item_map["RB-024"]["recommendedSubassembly"] == "side_fairings"
    assert item_map["RB-046"]["module"] == "bodywork_exterior_assembly"
    assert item_map["RB-046"]["classificationGroup"] == "bodywork_cowls_seat"
    assert item_map["RB-046"]["displayName"] == "Side Fairing Panel (Left)"
    assert item_map["RB-009"]["displayName"] == "Exhaust Header & Muffler"


def test_racing_bike_assembly_context_names_follow_process_map():
    # The racing-bike assembly context ships in the bundled demo library for the
    # standalone package; fall back to the full library when developing in-repo.
    base = REPO_ROOT / "demo_library" / "assemblies"
    if not (base / "racing-bike_assembly.json").exists():
        base = REPO_ROOT / "400S_Sorted_Library" / "assemblies"
    data = json.loads((base / "racing-bike_assembly.json").read_text(encoding="utf-8"))
    part_data = {}
    for entry in data["partDataCache"].values():
        identity = entry["identity"]
        part_data[identity["partNumber"]] = identity

    assert part_data["RB-009"]["description"] == "Exhaust Header & Muffler"
    assert part_data["RB-009"]["customProperties"]["InspectorProModule"] == "internal_mechanical_assembly"
    assert part_data["RB-009"]["customProperties"]["InspectorProBuildModule"] == "internal_mechanical_assembly"
    assert part_data["RB-009"]["customProperties"]["InspectorProClassificationGroup"] == "controls_exhaust_hardware"
    assert part_data["RB-009"]["customProperties"]["InspectorProSubassembly"] == "exhaust_system"
    assert part_data["RB-046"]["description"] == "Side Fairing Panel (Left)"
    assert part_data["RB-046"]["customProperties"]["InspectorProName"] == "Side Fairing Panel (Left)"
    assert part_data["RB-046"]["customProperties"]["InspectorProModule"] == "bodywork_exterior_assembly"
    assert part_data["RB-046"]["customProperties"]["InspectorProClassificationGroup"] == "bodywork_cowls_seat"
    assert part_data["RB-034"]["customProperties"]["InspectorProModule"] == "internal_mechanical_assembly"
    assert part_data["RB-034"]["customProperties"]["InspectorProSubassembly"] == "swingarm_linkage"
    assert part_data["RB-027"]["customProperties"]["InspectorProSubassembly"] == "rear_wheel_brake"
    assert part_data["RB-016"]["customProperties"]["InspectorProModule"] == "internal_mechanical_assembly"
    assert part_data["RB-016"]["customProperties"]["InspectorProClassificationGroup"] == "running_gear_brakes"
    assert part_data["RB-016"]["customProperties"]["InspectorProSubassembly"] == "swingarm_linkage"
    assert part_data["RB-021"]["customProperties"]["InspectorProSubassembly"] == "seat_tail"
    assert part_data["RB-022"]["customProperties"]["InspectorProSubassembly"] == "seat_tail"
    assert part_data["RB-023"]["customProperties"]["InspectorProSubassembly"] == "side_fairings"
    assert part_data["RB-024"]["customProperties"]["InspectorProSubassembly"] == "side_fairings"
    for moved_part_id in ["RB-004", "RB-005", "RB-006", "RB-007"]:
        assert part_data[moved_part_id]["customProperties"]["InspectorProModule"] == "internal_mechanical_assembly"
        assert part_data[moved_part_id]["customProperties"]["InspectorProClassificationGroup"] == "running_gear_brakes"
        assert part_data[moved_part_id]["customProperties"]["InspectorProSubassembly"] == "swingarm_linkage"
    assert part_data["RB-017"]["customProperties"]["InspectorProModule"] == "internal_mechanical_assembly"
    assert part_data["RB-017"]["customProperties"]["InspectorProSubassembly"] == "swingarm_linkage"
    assert part_data["RB-012"]["customProperties"]["InspectorProSubassembly"] == "swingarm_linkage"
    assert part_data["RB-013"]["customProperties"]["InspectorProSubassembly"] == "swingarm_linkage"
    assert part_data["RB-026"]["customProperties"]["InspectorProSubassembly"] == "swingarm_linkage"
    assert part_data["RB-036"]["customProperties"]["InspectorProSubassembly"] == "swingarm_linkage"
    assert part_data["RB-015"]["customProperties"]["InspectorProSubassembly"] == "swingarm_linkage"
    assert part_data["RB-011"]["customProperties"]["InspectorProSubassembly"] == "swingarm_linkage"
    assert part_data["RB-014"]["customProperties"]["InspectorProSubassembly"] == "swingarm_linkage"
    assert part_data["RB-019"]["customProperties"]["InspectorProSubassembly"] == "swingarm_linkage"
    assert part_data["RB-025"]["customProperties"]["InspectorProModule"] == "internal_mechanical_assembly"
    assert part_data["RB-025"]["customProperties"]["InspectorProClassificationGroup"] == "running_gear_brakes"
    assert part_data["RB-025"]["customProperties"]["InspectorProSubassembly"] == "swingarm_linkage"
    assert part_data["RB-032"]["description"] == "Front Wheel Shaft"
    assert part_data["RB-032"]["customProperties"]["InspectorProSubassembly"] == "front_wheel_brake"
    assert part_data["RB-033"]["description"] == "Front Hub Inner Sleeve Spacer"
    assert part_data["RB-033"]["customProperties"]["InspectorProSubassembly"] == "front_wheel_brake"
    assert part_data["RB-038"]["customProperties"]["InspectorProSubassembly"] == "front_wheel_brake"
    assert part_data["RB-001"]["description"] == "Rear Brake Pad"
    assert part_data["RB-001"]["customProperties"]["InspectorProSubassembly"] == "rear_wheel_brake"
    assert part_data["RB-020"]["customProperties"]["InspectorProSubassembly"] == "rear_wheel_brake"
    assert part_data["RB-035"]["description"] == "Front Brake Pad A"
    assert part_data["RB-035"]["customProperties"]["InspectorProSubassembly"] == "front_wheel_brake"
    assert part_data["RB-037"]["description"] == "Front Brake Pad B"
    assert part_data["RB-037"]["customProperties"]["InspectorProSubassembly"] == "front_wheel_brake"


def test_training_guided_assembly_conversational_defaults():
    """The frontend rewrites robotic guided-build copy into conversational
    narration for every node, while preserving hand-written wording."""
    html = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    for marker in [
        "_trainFriendlyTargetName",
        "_trainPartListPhrase",
        "_trainBuildConversationalJoinInstruction",
        "_trainBuildConversationalVerification",
        "Start with",
        "Use the pieces already in place",
        "still under review",
        # The generic-default detectors must live in the frontend so the
        # robotic JSON copy is overridden at render time.
        "keep previously joined parts highlighted",
        "is seated in the assembled pose before continuing",
    ]:
        assert marker in html, marker

    base = REPO_ROOT / "generated" / "training" / "racing-bike"
    plan = json.loads((base / "racing_bike_guided_build_plan.json").read_text(encoding="utf-8"))
    plans = plan["plansByNodeId"]

    # Non-Side-Fairings nodes still ship the generic robotic JSON copy; the
    # frontend helper overrides it, so the same pattern the frontend uses must
    # still match those strings (proving the override path is exercised).
    generic_join_seen = 0
    for node_id, build in plans.items():
        if node_id == "L1-002-05":
            continue
        for step in build["steps"]:
            if GENERIC_JOIN_RE.match(step.get("sageInstruction", "")):
                generic_join_seen += 1
    assert generic_join_seen > 0

    # Front Wheel & Brake (a non-Side-Fairings subassembly) is fully generic
    # in the JSON, so the frontend is responsible for its conversational copy.
    fw_steps = plans["L1-001-02"]["steps"]
    assert GENERIC_JOIN_RE.match(fw_steps[0]["sageInstruction"])
    assert GENERIC_VERIFY_RE.match(fw_steps[0]["verificationCheck"])

    # Side Fairings keeps its hand-written, more specific wording and must NOT
    # be flagged generic, so the frontend leaves it untouched.
    sf_steps = plans["L1-002-05"]["steps"]
    assert sf_steps[0]["sageInstruction"].startswith("Start with RB-023")
    for step in sf_steps:
        assert not GENERIC_JOIN_RE.match(step["sageInstruction"])
        assert not GENERIC_VERIFY_RE.match(step["verificationCheck"])


# Words/phrases that must never reach the spoken/main operator narration.
SHOP_FLOOR_BANNED_RE = re.compile(
    r"(solidworks|\bcad\b|exploded|\bgeometry\b|assembled pose|process map|\bglb\b"
    r"|\bnode\b|target parts|part ids?|evidence level|highlighted)",
    re.IGNORECASE,
)
RB_ID_RE = re.compile(r"\bRB-\d")

# Node driver: extracts the real shop-floor helper block from index.html and
# runs it against the real data, so we assert on the ACTUAL generated narration
# rather than re-implementing the logic in Python.
_NARRATION_DRIVER = r"""
const fs = require('fs');
const root = process.env.TRAIN_ROOT;
const rd = p => fs.readFileSync(root + p, 'utf8');
const html = rd('/static/index.html');
const processMap = JSON.parse(rd('/generated/training/racing-bike/racing_bike_process_map_working_draft.json'));
const uniqueItems = JSON.parse(rd('/generated/training/racing-bike/racing_bike_unique_items.json'));
const guided = JSON.parse(rd('/generated/training/racing-bike/racing_bike_guided_build_plan.json'));
const start = html.indexOf('function _trainCleanShopFloorName(');
const end = html.indexOf('function _trainBuildMockProcedure(');
if (start < 0 || end < 0 || end <= start) { console.error('EXTRACT_FAIL'); process.exit(2); }
const block = html.slice(start, end);
const trainingState = { processMap, uniqueItems };
// Stub the two externals the fallback builder calls: force the fallback path
// (no guided plan) and feed it the real process-map nodes.
const guidedBuildPlanForNode = () => null;
const processNodes = (lvl) => processMap.nodes.filter(n => n && (typeof lvl !== 'number' || n.level === lvl));
const api = (new Function('trainingState', '_trainGuidedBuildPlanForNode', '_trainProcessNodes',
  block + '\n; return { _trainBuildGuidedPlanProcedure, _trainBuildProcessMapProcedure };'
))(trainingState, guidedBuildPlanForNode, processNodes);
const nodeById = id => processMap.nodes.find(n => n.nodeId === id);
const out = {};
for (const id of ['L1-002', 'L1-001-02', 'L1-002-05', 'L0-000', 'L1-001-01']) {
  const proc = api._trainBuildGuidedPlanProcedure(nodeById(id), 'operator', guided.plansByNodeId[id]);
  out[id] = proc.steps.map(s => ({ title: s.title, instruction: s.instruction, verificationCheck: s.verificationCheck }));
}
// Fallback path: a single level-3 component node has no guided plan.
const leaf = processMap.nodes.find(n => n && n.level === 3 && Array.isArray(n.partIds) && n.partIds.length === 1);
const fb = api._trainBuildProcessMapProcedure(leaf, 'operator');
out['FALLBACK'] = fb.steps.map(s => ({ title: s.title, instruction: s.instruction, verificationCheck: s.verificationCheck }));
process.stdout.write(JSON.stringify(out));
"""


def test_training_shop_floor_helper_markers():
    """Shop-floor name-resolution + narration helpers and phrasing exist."""
    html = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    for marker in [
        "_trainCleanShopFloorName",
        "_trainShopFloorAssemblyName",
        "_trainPartNameMap",
        "_trainPartNameById",
        "_trainPartNamesForIds",
        "_trainPartNameListPhrase",
        "_trainResolveTargetSpoken",
        "_trainTextHasShopFloorViolations",
        "_trainShopFloorJoinTitle",
        # shop-floor phrasing the generated narration leans on
        "one piece at a time",
        "Use the pieces already in place",
        "one clean assembly",
        "where the piece fits",
        # the id/jargon gate that forces hand-written id copy to be regenerated
        r"\bRB-\d",
    ]:
        assert marker in html, marker


@pytest.mark.skipif(not shutil.which("node"), reason="node.js not available to run the narration helpers")
def test_training_shop_floor_narration_behavior():
    """The ACTUAL generated narration is shop-floor: no RB ids, no CAD jargon,
    and it reads like an operator guide — verified across multiple assemblies."""
    env = dict(os.environ, TRAIN_ROOT=str(REPO_ROOT))
    proc = subprocess.run(
        ["node", "-"],
        input=_NARRATION_DRIVER,
        env=env,
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, f"node driver failed: {proc.stderr}"
    data = json.loads(proc.stdout)

    cues = ("laid out", "lay out", "bring", "seat", "gap", "line up", "lined up", "lines up", "clean assembly", "pieces")
    # Bodywork, Front Wheel & Brake, Side Fairings (and root + swingarm), plus the
    # no-guided-plan FALLBACK path, must all speak names, not ids, and avoid CAD
    # jargon in title + instruction + verify.
    for node_id in ("L1-002", "L1-001-02", "L1-002-05", "L0-000", "L1-001-01", "FALLBACK"):
        steps = data[node_id]
        assert steps, node_id
        joined = " ".join(f"{s['title']}. {s['instruction']}" for s in steps).lower()
        for step in steps:
            spoken = f"{step['title']}. {step['instruction']}"
            assert not RB_ID_RE.search(spoken), spoken
            assert not SHOP_FLOOR_BANNED_RE.search(spoken), spoken
            verify = step.get("verificationCheck") or ""
            assert not RB_ID_RE.search(verify), verify
            assert not SHOP_FLOOR_BANNED_RE.search(verify), verify
        assert any(cue in joined for cue in cues), node_id

    # Side Fairings ships hand-written copy WITH RB ids in the JSON; the spoken
    # text must strip those ids and speak the curated name instead.
    sf_text = " ".join(s["instruction"] for s in data["L1-002-05"])
    assert "RB-023" not in sf_text
    assert "nose cowl" in sf_text.lower()

    # Generic Bodywork / Front Wheel narration uses real names, not ids.
    assert "bodywork" in (data["L1-002"][0]["instruction"]).lower()
    assert "front wheel" in (data["L1-001-02"][0]["instruction"]).lower()

    # RB ids still live in the JSON/data for the selection/highlight logic.
    plans = json.loads(
        (REPO_ROOT / "generated" / "training" / "racing-bike" / "racing_bike_guided_build_plan.json")
        .read_text(encoding="utf-8")
    )["plansByNodeId"]
    assert plans["L1-002-05"]["steps"][0]["sageInstruction"].startswith("Start with RB-023")
    assert plans["L1-001-02"]["steps"][0]["targetPartIds"] == ["RB-038"]


# ---------------------------------------------------------------------------
# Guided-assembly motion orientation + scoped dimming (safe core)
# ---------------------------------------------------------------------------

def test_front_wheel_brake_extract_excludes_mudguard_after_reextract():
    """The refreshed Front Wheel & Brake extraction no longer contains
    the mudguard; RB-034 now belongs to Swingarm & Linkage in the app
    sequence."""
    path = (
        REPO_ROOT / "generated" / "training" / "racing-bike"
        / "subassembly_extracts" / "front_wheel_brake.json"
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["statistics"]["totalComponents"] == 9
    assert data["statistics"]["uniquePartCount"] == 8
    assert data["statistics"]["suppressedCount"] == 0
    assert len(data.get("explodeSteps", [])) == 7
    all_files = [
        file_name
        for step in data.get("explodeSteps", [])
        for file_name in step.get("componentFileNames", [])
    ]
    assert all("Part-34" not in file_name for file_name in all_files)
    assert {re.search(r"Part-(\d+)", file_name).group(1) for file_name in all_files} == {
        "32", "33", "35", "37", "38", "39", "40", "43",
    }


def test_front_wheel_brake_visual_manifest_has_glb_and_extract():
    base = REPO_ROOT / "generated" / "training" / "racing-bike"
    visual = json.loads((base / "racing_bike_subassembly_visuals.json").read_text(encoding="utf-8"))
    node = visual["nodes"]["L1-001-02"]
    assert node["glbUrl"] == "/generated/training/racing-bike/subassembly_glb/front_wheel_brake.glb"
    assert node["extractionJsonUrl"] == "/generated/training/racing-bike/subassembly_extracts/front_wheel_brake.json"
    assert (base / "subassembly_glb" / "front_wheel_brake.glb").exists()
    assert (base / "subassembly_extracts" / "front_wheel_brake.json").exists()


def test_training_motion_orientation_static_markers():
    html = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    for marker in [
        "_computeTrainingExplodeVectorsFromExtract",
        "_trainPartNumberFromComponentFile",
        "_trainDimTrainingScopeParts",
        "_trainActiveProcedureScopePartIds",
        "_trainSelectedProcedureNodeId",
        "_trainVisualNodeForProcedure",
        "_trainVisualAssetForProcedure",
        "activeViewerNodeId",
        "activeViewerExtract",
        # the guided procedure carries its node id for viewer scoping
        "nodeId: selectedNode.nodeId",
        # feature #162: subassembly-GLB guided viewer + explode-direction motion
        "_trainGuidedViewerAssetForNode",
        "_trainLoadViewerExtract",
        "_trainApplyExtractExplodeSteps",
        "_trainMountGuidedViewer",
        "_trainMountViewerForActiveProcedure",
        "_assyGuidedGltfCache",
        "onPostLoad",
    ]:
        assert marker in html, marker


def test_front_wheel_brake_operator_sequence_after_mudguard_move():
    """The operator build sequence is the authority for the current grouping."""
    base = REPO_ROOT / "generated" / "training" / "racing-bike"
    plans = json.loads((base / "racing_bike_guided_build_plan.json").read_text(encoding="utf-8"))["plansByNodeId"]
    assert [step["targetPartIds"] for step in plans["L1-001-02"]["steps"]] == [
        ["RB-038"],            # Front Wheel Rim (3-spoke)
        ["RB-033"],            # Front Hub Inner Sleeve Spacer
        ["RB-032"],            # Front Wheel Shaft
        ["RB-039"],            # Front Brake Rotor A
        ["RB-040"],            # Front Brake Rotor B
        ["RB-035", "RB-037"],  # Front Brake Pads A and B
        ["RB-043"],            # Front Tire / Outer Wheel Ring
    ]
    assert plans["L1-001-02"]["steps"][-1]["accumulatedPartIds"] == [
        "RB-038", "RB-033", "RB-032", "RB-039", "RB-040", "RB-035", "RB-037", "RB-043",
    ]
    assert plans["L1-001-01"]["steps"][-1]["targetPartIds"] == ["RB-034"]
    assert plans["L1-001-01"]["steps"][-1]["accumulatedPartIds"][-1] == "RB-034"


_EXPLODE_DRIVER = r"""
const fs = require('fs');
const root = process.env.TRAIN_ROOT;
const html = fs.readFileSync(root + '/static/index.html', 'utf8');
const extract = JSON.parse(fs.readFileSync(
  root + '/generated/training/racing-bike/subassembly_extracts/front_wheel_brake.json', 'utf8'));
const start = html.indexOf('function _trainPartNumberFromComponentFile(');
const end = html.indexOf('function _trainAssetStatusLabel(');
if (start < 0 || end < 0 || end <= start) { console.error('EXTRACT_FAIL'); process.exit(2); }
const block = html.slice(start, end);
const api = (new Function(block + '\n; return { _computeTrainingExplodeVectorsFromExtract };'))();
const steps = api._computeTrainingExplodeVectorsFromExtract(extract, []);
process.stdout.write(JSON.stringify(steps));
"""


@pytest.mark.skipif(not shutil.which("node"), reason="node.js not available to run the explode-vector helper")
def test_training_explode_vectors_from_extract_behavior():
    """The frontend helper maps the real extraction explodeSteps to RB-keyed
    motion vectors for the current Front Wheel & Brake subassembly."""
    env = dict(os.environ, TRAIN_ROOT=str(REPO_ROOT))
    proc = subprocess.run(["node", "-"], input=_EXPLODE_DRIVER, env=env, text=True, capture_output=True)
    assert proc.returncode == 0, f"node driver failed: {proc.stderr}"
    steps = json.loads(proc.stdout)
    assert len(steps) == 7
    by_name = {s["name"]: s for s in steps}
    resolved = {pn for step in steps for pn in step["partNumbers"]}
    assert resolved == {"RB-032", "RB-033", "RB-035", "RB-037", "RB-038", "RB-039", "RB-040", "RB-043"}
    assert "RB-034" not in resolved
    assert "RB-038" in by_name["Front wheel rim"]["partNumbers"]
    pads = by_name["Brake pads A and B"]["partNumbers"]
    assert "RB-037" in pads and "RB-035" in pads
    # Every mapped step resolves to at least one RB part number and a real vector.
    for s in steps:
        assert s["partNumbers"]
        assert len(s["direction"]) == 3
        assert s["distance"] > 0


# Drives _trainApplyExtractExplodeSteps with the real extraction JSON and a
# stubbed THREE/scene to confirm it builds state.assyExplodeSteps in the exact
# shape _computeGuidedAssemblyTargetPositions consumes (mesh refs + Vector3 dir).
_APPLY_EXPLODE_DRIVER = r"""
const fs = require('fs');
const root = process.env.TRAIN_ROOT;
const html = fs.readFileSync(root + '/static/index.html', 'utf8');
const extract = JSON.parse(fs.readFileSync(
  root + '/generated/training/racing-bike/subassembly_extracts/front_wheel_brake.json', 'utf8'));
const slice = (a, b) => { const s = html.indexOf(a), e = html.indexOf(b);
  if (s < 0 || e < 0 || e <= s) { console.error('SLICE_FAIL ' + a); process.exit(2); } return html.slice(s, e); };
const block = slice('function _trainPartNumberFromComponentFile(', 'function _trainAssetStatusLabel(')
            + '\n' + slice('function _trainApplyExtractExplodeSteps(', 'function _trainMountGuidedViewer(');
function V3(x,y,z){this.x=x||0;this.y=y||0;this.z=z||0;}
V3.prototype.length=function(){return Math.hypot(this.x,this.y,this.z);};
V3.prototype.normalize=function(){const l=this.length()||1;this.x/=l;this.y/=l;this.z/=l;return this;};
V3.prototype.clone=function(){return new V3(this.x,this.y,this.z);};
const THREE = { Vector3: V3 };
const win = { THREE };
const partNums = ['RB-032','RB-033','RB-035','RB-037','RB-038','RB-039','RB-040','RB-043'];
const meshMap = {};
partNums.forEach((pn,i) => { meshMap[pn] = [{ position: new V3(i+1, i+2, i+3), userData: {} }]; });
const state = { assyPartMeshMap: meshMap, assyExplodeSteps: null, assyExplodeVectors: null };
const assemblyContext = { part_color_legend: [] };
const trainingState = { activeViewerExtract: extract };
const api = (new Function('window','THREE','state','assemblyContext','trainingState',
  block + '\n; return { _trainApplyExtractExplodeSteps };'))(win, THREE, state, assemblyContext, trainingState);
const ok = api._trainApplyExtractExplodeSteps();
const out = { ok, steps: (state.assyExplodeSteps || []).map(s => ({
  partNumbers: s.partNumbers, direction: [s.direction.x, s.direction.y, s.direction.z],
  distance: s.distance, meshCount: s.meshes.length })),
  hasSW: !!(state.assyExplodeVectors && state.assyExplodeVectors._hasSWSteps),
  shaftOrigSnap: meshMap['RB-032'][0].userData._origPosition instanceof V3 };
process.stdout.write(JSON.stringify(out));
"""


@pytest.mark.skipif(not shutil.which("node"), reason="node.js not available to run the explode-step apply logic")
def test_training_apply_extract_explode_steps_behavior():
    """_trainApplyExtractExplodeSteps resolves extraction directions to mesh-keyed
    steps for the current Front Wheel & Brake extraction."""
    env = dict(os.environ, TRAIN_ROOT=str(REPO_ROOT))
    proc = subprocess.run(["node", "-"], input=_APPLY_EXPLODE_DRIVER, env=env, text=True, capture_output=True)
    assert proc.returncode == 0, f"node driver failed: {proc.stderr}"
    out = json.loads(proc.stdout)
    assert out["ok"] is True
    assert out["hasSW"] is True
    assert out["shaftOrigSnap"] is True
    assert len(out["steps"]) == 7
    resolved = {pn for step in out["steps"] for pn in step["partNumbers"]}
    assert "RB-034" not in resolved
    shaft = next(s for s in out["steps"] if "RB-032" in s["partNumbers"])
    assert shaft["direction"] == [0, 0, -1]
    assert abs(shaft["distance"] - 0.1380939686) < 1e-9
    assert shaft["meshCount"] == 1
    pads = next(s for s in out["steps"] if "RB-035" in s["partNumbers"])
    assert "RB-037" in pads["partNumbers"]
    assert pads["meshCount"] == 2


# ---------------------------------------------------------------------------
# Guided-assembly true visibility (uncalled parts hidden, not ghosted)
# ---------------------------------------------------------------------------

def test_training_visibility_static_markers():
    html = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    for marker in [
        "_trainSetMeshVisible",
        "_trainSetTrainingVisibility",
        "_trainVisiblePartsForStep",
        "_trainRestoreTrainingVisibility",
        "_origVisible",
        "_trainVisibilityActive",
        # true hide via mesh.visible (not opacity) + the cross-scope restore bridge
        "mesh.visible = !!visible",
        "_trainingRestoreVisibility",
    ]:
        assert marker in html, marker


_VISIBILITY_DRIVER = r"""
const fs = require('fs');
const root = process.env.TRAIN_ROOT;
const html = fs.readFileSync(root + '/static/index.html', 'utf8');
const s = html.indexOf('function _trainSetMeshVisible(');
const e = html.indexOf('// Guided start state: hide every part');
if (s < 0 || e < 0 || e <= s) { console.error('SLICE_FAIL'); process.exit(2); }
const block = html.slice(s, e);
function mkMesh(){ return { isMesh:true, visible:true, material:{opacity:1,transparent:false,depthWrite:true,needsUpdate:false},
  userData:{ _origOpacity:1, _origTransparent:false, _origDepthWrite:true } }; }
const meshes = {}; ['RB-038','RB-033','RB-032','RB-034'].forEach(pn => meshes[pn] = mkMesh());
const all = Object.values(meshes);
const liveScene = { traverse(cb){ all.forEach(cb); } };
const state = { assyLiveScene: liveScene,
  assyPartMeshMap: Object.fromEntries(Object.entries(meshes).map(([k,v])=>[k,[v]])), _trainVisibilityActive:false };
const win = {};
const api = (new Function('state','window',
  block + '\n; return { _trainSetTrainingVisibility, _trainVisiblePartsForStep, _trainRestoreTrainingVisibility };'))(state, win);
const out = {};
out.visibleForStep = api._trainVisiblePartsForStep({accumulatedPartIds:['RB-038','RB-033'], targetPartIds:['RB-033']}).sort();
api._trainSetTrainingVisibility([]);
out.startAllHidden = all.every(m => m.visible === false);
out.snappedOrig = all.every(m => m.userData._origVisible === true);
out.activeFlag = state._trainVisibilityActive === true;
meshes['RB-038'].material.opacity = 0.05;
api._trainSetTrainingVisibility(['RB-038']);
out.onlyRimVisible = meshes['RB-038'].visible === true &&
  ['RB-033','RB-032','RB-034'].every(k => meshes[k].visible === false);
out.relit = meshes['RB-038'].material.opacity === 1;
api._trainRestoreTrainingVisibility();
out.restoredAllVisible = all.every(m => m.visible === true);
out.flagCleared = state._trainVisibilityActive === false;
out.bridge = typeof win._trainingRestoreVisibility === 'function';
process.stdout.write(JSON.stringify(out));
"""


@pytest.mark.skipif(not shutil.which("node"), reason="node.js not available to run the visibility helpers")
def test_training_guided_visibility_behavior():
    """Uncalled guided parts are truly hidden (mesh.visible=false); each step
    shows only accumulated+target; restore returns original visibility."""
    env = dict(os.environ, TRAIN_ROOT=str(REPO_ROOT))
    proc = subprocess.run(["node", "-"], input=_VISIBILITY_DRIVER, env=env, text=True, capture_output=True)
    assert proc.returncode == 0, f"node driver failed: {proc.stderr}"
    out = json.loads(proc.stdout)
    assert out["visibleForStep"] == ["RB-033", "RB-038"]   # accumulated ∪ target
    assert out["startAllHidden"] is True                    # start => nothing visible
    assert out["snappedOrig"] is True
    assert out["activeFlag"] is True
    assert out["onlyRimVisible"] is True                    # step shows only its scope
    assert out["relit"] is True                             # revealed part is lit, not dimmed
    assert out["restoredAllVisible"] is True                # restore brings parts back
    assert out["flagCleared"] is True
    assert out["bridge"] is True


# ---------------------------------------------------------------------------
# LLM machinist-coach narration (dynamic server endpoint)
# ---------------------------------------------------------------------------

def test_training_narration_endpoint_and_prompt_builder():
    """The server exposes the narration endpoint, the body models parse, and the
    prompt names the assembly + pieces and asks for the per-step JSON shape."""
    import server  # lazy: only load the app when this test runs

    paths = {getattr(r, "path", "") for r in server.app.routes}
    assert "/api/training/guided-narration" in paths

    body = server.TrainingNarrationBody(
        nodeName="Exhaust System",
        steps=[
            {"kind": "layout", "names": ["Exhaust Header and Muffler", "Exhaust Clamp Band A", "Exhaust Clamp Band B"]},
            {"kind": "first_join", "name": "Exhaust Header and Muffler", "isFirst": True},
            {"kind": "mid_join", "name": "Exhaust Clamp Band A"},
            {"kind": "final_join", "name": "Exhaust Clamp Band B", "isFinal": True},
            {"kind": "final_check"},
        ],
    )
    prompt = server._build_training_narration_user_prompt("Exhaust System", body.steps)
    assert "Assembly: Exhaust System" in prompt
    assert "Exhaust Header and Muffler" in prompt
    assert "5 steps" in prompt
    assert '{"narration"' in prompt          # asks for the parseable JSON shape
    assert "exactly 5 strings" in prompt
    assert "SHOW THE GOAL" in prompt
    assert "FINAL LOOK" in prompt
    assert "FIRST PIECE" in prompt
    assert "LAST PIECE" in prompt

    # System prompt embodies the machinist-coach voice + the no-numbering rule.
    sysp = server.TRAINING_NARRATION_SYSTEM_PROMPT
    assert "machinist" in sysp.lower()
    assert "Never say" in sysp and "number anything" in sysp
    assert "2-4 sentences" in sysp


def test_training_llm_narration_static_markers():
    html = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    for marker in [
        "_trainBuildNarrationRequestSteps",
        "_trainApplyGeneratedNarration",
        "_trainMaybeGenerateNarration",
        "/api/training/guided-narration",
        "_narrationCacheByNode",
        "_narrationPromise",
        "machinist_llm",
    ]:
        assert marker in html, marker
    # The spoken segment text no longer prefixes "Step N" + the title.
    assert "Step ${idx + 1}. ${s.title}" not in html
    # Play captures + re-checks the narration session so a Stop during the
    # pre-play wait cancels playback (review fix #2).
    assert "playSessionId" in html
    assert "state.narrationSessionId !== playSessionId" in html


def test_training_narration_cleaning_preserves_positions():
    """A blank/None entry from the model keeps its slot (review fix #1) so the
    frontend's narration[i] -> step[i] mapping never shifts onto wrong steps."""
    import server

    assert server._clean_training_narration(["a", "", None, "d"]) == ["a", "", "", "d"]
    # Whitespace-only stays an empty slot (frontend keeps the template there);
    # the list length always equals the input length.
    out = server._clean_training_narration(["  lay out  ", "   ", "bring in B", "final"])
    assert out == ["lay out", "", "bring in B", "final"]
    assert len(out) == 4


def test_training_panel_typewriter_static_markers():
    html = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    for marker in [
        "_trainTypewrite",
        "_trainTypewriteCurrentInstruction",
        "_trainingTypewriteCurrentStep",
        ".train-step-instruction .typing-cursor",
    ]:
        assert marker in html, marker
    # The narration loop streams the SAME segment text the audio was made from,
    # so the words on screen match the voice (not a stale step.instruction).
    assert "window._trainingTypewriteCurrentStep(seg.text, duration * 1000)" in html
    assert "_activeNarrationText" in html
