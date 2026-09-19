"""Provision the coordinate-free FDL browser acceptance layout once."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.facility_layout.errors import FacilityNotFoundError
from ai_inspector.facility_layout.feature_flags import FacilityLayoutFeatureFlags
from ai_inspector.facility_layout.host import LOCAL_SITE_ID, LocalFacilityLayoutHost
from ai_inspector.facility_layout.routing import persisted_route_fingerprint
from ai_inspector.process_map.repository import load_named_process_map


DEFAULT_LAYOUT_ID = "fl-fdl-generic-material-travel-v6"
PROCESS_PRODUCT_ID = "synthetic-process-map-eval"
PROCESS_MAP_ID = "default"
PROCESS_EDGE_ID = "eval-edge-3"
FIXTURE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "design_loop"
    / "fdl-material-travel-v1.json"
)


def build_demo_layout(host: LocalFacilityLayoutHost, layout_id: str) -> dict:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    bootstrap = host.ensure_bootstrap()
    bootstrap_layout = bootstrap["layout"]["layout"]
    layout = deepcopy(fixture["facilityLayout"])
    layout["layoutId"] = layout_id
    layout["displayName"] = "FDL Coordinate-Free Material Travel Demo"
    layout["association"] = {
        "siteId": LOCAL_SITE_ID,
        "areaId": "area-fdl-generic-material-travel",
    }
    layout["coordinateFrame"] = deepcopy(bootstrap_layout["coordinateFrame"])
    layout["sourceShellRef"] = deepcopy(bootstrap_layout["sourceShellRef"])
    layout["policySetRef"] = deepcopy(bootstrap_layout["policySetRef"])

    substitutions = {
        "asset-cnc-mill": "asset-cnc-mill",
        "asset-inspection-station": "asset-workbench",
        "asset-fifo-buffer": "asset-material-transfer-buffer",
        "asset-fixed-obstacle": "asset-pallet-rack",
    }
    for placement in layout["placements"]:
        asset_id = substitutions[placement["assetId"]]
        definition = host._catalog[asset_id]
        placement["assetId"] = asset_id
        placement["assetDefinitionRevision"] = definition[
            "assetDefinitionRevision"
        ]

    process_map = load_named_process_map(
        ROOT / "generated" / "training",
        PROCESS_PRODUCT_ID,
        PROCESS_MAP_ID,
    )
    process_revision = process_map["revision"]
    for binding in layout["processBindings"]:
        binding["productId"] = PROCESS_PRODUCT_ID
        binding["processMapId"] = PROCESS_MAP_ID
        binding["processMapRevision"] = process_revision
        if binding["processBindingId"] == "pb-machining-resource":
            binding["processNodeIds"] = ["eval-machine"]
        elif binding["processBindingId"] == "pb-inspection-resource":
            binding["processNodeIds"] = ["eval-release"]
        elif binding["processBindingId"] == "pb-machining-inspection-transfer":
            binding["processEdgeIds"] = [PROCESS_EDGE_ID]

    zones = {item["zoneId"]: item for item in layout["zones"]}
    zones["zn-machining"]["boundary"] = [
        {"x": 0.0, "z": 0.0},
        {"x": 40.0, "z": 0.0},
        {"x": 40.0, "z": 30.0},
        {"x": 0.0, "z": 30.0},
    ]
    zones["zn-inspection"]["boundary"] = [
        {"x": 40.0, "z": 0.0},
        {"x": 60.0, "z": 0.0},
        {"x": 60.0, "z": 30.0},
        {"x": 40.0, "z": 30.0},
    ]

    placements = {item["placementId"]: item for item in layout["placements"]}
    positions = {
        "pl-cnc-mill-03": (5.0, 20.0),
        "pl-inspection-station-02": (55.0, 14.0),
        "pl-output-buffer-a": (10.0, 8.0),
        "pl-input-buffer-b": (50.0, 22.0),
        "pl-obstacle-west": (25.0, 4.0),
        "pl-obstacle-east": (47.0, 4.0),
    }
    for placement_id, (x, z) in positions.items():
        placements[placement_id]["transform"]["position"].update(
            {"x": x, "y": 0.0, "z": z}
        )

    routes = {item["routeId"]: item for item in layout["routes"]}
    output_approach = routes["rt-material-transfer-aisle"]
    output_approach["sourceEndpoint"] = {
        "kind": "placement_connector",
        "placementId": "pl-output-buffer-a",
        "connectorId": "material-output",
    }
    output_approach["targetEndpoint"] = {
        "kind": "world_point",
        "position": {"x": 39.0, "y": 0.0, "z": 18.0},
    }
    output_approach["centerline"] = [
        {"x": 10.0, "y": 0.0, "z": 8.0},
        {"x": 39.0, "y": 0.0, "z": 18.0},
    ]

    boulevard = routes["rt-main-boulevard"]
    boulevard["sourceEndpoint"] = {
        "kind": "world_point",
        "position": {"x": 39.0, "y": 0.0, "z": 18.0},
    }
    boulevard["targetEndpoint"] = {
        "kind": "world_point",
        "position": {"x": 41.0, "y": 0.0, "z": 12.0},
    }
    boulevard["centerline"] = [
        {"x": 39.0, "y": 0.0, "z": 18.0},
        {"x": 39.0, "y": 0.0, "z": 28.0},
        {"x": 41.0, "y": 0.0, "z": 28.0},
        {"x": 41.0, "y": 0.0, "z": 12.0},
    ]

    input_approach = deepcopy(boulevard)
    input_approach["routeId"] = "rt-input-approach-aisle"
    input_approach["label"] = "Input Approach Aisle"
    input_approach["sourceEndpoint"] = {
        "kind": "world_point",
        "position": {"x": 41.0, "y": 0.0, "z": 12.0},
    }
    input_approach["targetEndpoint"] = {
        "kind": "placement_connector",
        "placementId": "pl-input-buffer-b",
        "connectorId": "material-input",
    }
    input_approach["centerline"] = [
        {"x": 41.0, "y": 0.0, "z": 12.0},
        {"x": 50.0, "y": 0.0, "z": 22.0},
    ]
    layout["routes"].append(input_approach)

    transfer_binding = next(
        item
        for item in layout["processBindings"]
        if item["processBindingId"] == "pb-machining-inspection-transfer"
    )
    transfer_binding["routeIds"] = [
        "rt-material-transfer-aisle",
        "rt-main-boulevard",
        "rt-input-approach-aisle",
    ]
    for route in layout["routes"]:
        route["routeFingerprint"] = persisted_route_fingerprint(route)
    return layout


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layout-id", default=DEFAULT_LAYOUT_ID)
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT / ".runtime" / "facility-layout",
    )
    arguments = parser.parse_args()
    host = LocalFacilityLayoutHost(
        arguments.root,
        process_map_root=ROOT / "generated" / "training",
        feature_flags=FacilityLayoutFeatureFlags.all_enabled(),
        private_assets=False,
    )
    principal = host.principal()
    try:
        result = host.layout_repository.get_layout(
            principal,
            LOCAL_SITE_ID,
            arguments.layout_id,
        )
        outcome = "already_exists"
    except FacilityNotFoundError:
        result = host.layout_repository.create_layout(
            principal,
            LOCAL_SITE_ID,
            build_demo_layout(host, arguments.layout_id),
        )
        outcome = "created"
    print(
        json.dumps(
            {
                "outcome": outcome,
                "layoutId": result["layout"]["layoutId"],
                "revision": result["revision"],
                "placements": len(result["layout"]["placements"]),
                "routes": len(result["layout"]["routes"]),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
