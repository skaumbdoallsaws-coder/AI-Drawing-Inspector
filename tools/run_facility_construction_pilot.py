"""Isolated Sage construction demo; never opens the manual reference store."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai_inspector.facility_layout.feature_flags import FACILITY_LAYOUT_FEATURE_FLAGS
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, LOCAL_SITE_ID, LOCAL_LAYOUT_ID


def prepare():
    store = ROOT / ".runtime/construction-sage-pilot/store"
    host = LocalFacilityLayoutHost(store, private_assets=True, private_asset_root=ROOT)
    try:
        host.ensure_bootstrap()
        principal = host.principal()
        current = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
        if not current["layout"]["placements"]:
            operations = []
            seeds = [("asset-assembled-laboratory-workstation", "Table A", 8),
                     ("asset-assembled-laboratory-workstation", "Table B", 15),
                     ("asset-carr-lane-cl-400-ptpb", "Device", 21)]
            for index, (asset_id, label, x) in enumerate(seeds):
                asset = host._catalog[asset_id]
                operations.append({"op": "place_asset", "placement": {
                    "placementId": "pl-construction-" + str(index), "assetId": asset_id,
                    "assetDefinitionRevision": asset["assetDefinitionRevision"],
                    "transform": {"position": {"x": x, "y": 0, "z": 5},
                                  "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1}, "scale": 1},
                    "positionMode": "manual", "snapRelationship": None, "metadata": {"instanceLabel": label}}})
            current = host.service.apply_operations(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, current["revision"], operations)
        if len(current["layout"]["placements"]) != 3 or current["layout"]["zones"]:
            raise RuntimeError("Pilot store has existing user edits; refusing to overwrite it")
        evidence = {"baseRevision": current["revision"], "layoutId": LOCAL_LAYOUT_ID,
                    "placements": current["layout"]["placements"], "saved": "isolated seed fixture only"}
        (store.parent / "seed.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        return store
    finally:
        host.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8187)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    store = prepare()
    if not args.prepare_only:
        for flag in FACILITY_LAYOUT_FEATURE_FLAGS:
            os.environ[flag] = "1"
        os.environ["INSPECTORPRO_FACILITY_LAYOUT_CONSTRUCTION_SAGE"] = "1"
        os.environ["INSPECTORPRO_FACILITY_PRIVATE_ASSETS"] = "1"
        os.environ["INSPECTORPRO_FACILITY_LAYOUT_ROOT"] = str(store)
        import uvicorn
        uvicorn.run("server:app", host="127.0.0.1", port=args.port, log_level="warning")
