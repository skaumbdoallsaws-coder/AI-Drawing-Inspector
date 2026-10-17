"""Add an authored, open-top perimeter to Factory 02 using ordinary assets.

Defaults to isolated dry-run. --apply publishes three box assets and six locked
placements. Dimensions and openings are illustrative, not building approval.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.industrial_assets.artifacts import build_aabb_proxy_glb, inspect_glb
from tools.audit_independent_factory_layer2 import footprint, write_json

LAYOUT_ID = "fl-independent-factory-20260928"
SOURCE_ID = "fl-reference-manual-20260812"
BASE_REVISION = "4d3d7213064ee5a999e3b14e8771aff648e7dddf2b1d80515a33bb80cddabc7c"
SITE = "site-local"
THICKNESS = 0.25
HEIGHT = 6.0
JOINT = 0.01  # Authored panel joint; touching independent assets are collisions.
OPENING = (91.0, 106.0)
PREFIX = "asset-factory02-perimeter-"


def wall_segments(width, depth, thickness=THICKNESS, opening=OPENING):
    if not all(math.isfinite(v) for v in (width, depth, thickness, *opening)):
        raise ValueError("Wall dimensions must be finite.")
    start, end = opening
    if not (0 < thickness < width / 2 and thickness + JOINT < start < end < depth - thickness - JOINT):
        raise ValueError("Wall thickness or opening is outside the floor.")
    return [
        ("south", "end", (0, 0, width, thickness)),
        ("north", "end", (0, depth - thickness, width, depth)),
        ("west-south", "side-south", (0, thickness + JOINT, thickness, start)),
        ("east-south", "side-south", (width - thickness, thickness + JOINT, width, start)),
        ("west-north", "side-north", (0, end, thickness, depth - thickness - JOINT)),
        ("east-north", "side-north", (width - thickness, end, width, depth - thickness - JOINT)),
    ]


def asset_specs(segments):
    specs = {}
    for _key, kind, (x0, z0, x1, z1) in segments:
        aid = PREFIX + kind
        specs[aid] = {
            "assetId": aid, "displayName": "Factory 02 perimeter wall - " + kind,
            "category": "Building Structures",
            "description": "Authored rectangular perimeter wall, 6 m high and 250 mm thick. Illustrative dimensions; no structural, fire or egress approval.",
            "dimensions": {"width": x1 - x0, "depth": z1 - z0, "height": HEIGHT},
            "artifact": f"generated/industrial_assets/factory02_perimeter/{kind}/wall.glb",
            "sourceToCanonical": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
            "source": {"kind": "authored-primitive", "evidenceStatus": "authored",
                       "generator": "tools/add_independent_factory_walls.py"},
            "tags": ["wall", "perimeter", "building", "authored", "unverified"],
        }
    return list(specs.values())


def build_operations(segments, catalog):
    ops = []
    for key, kind, (x0, z0, x1, z1) in segments:
        asset = catalog[PREFIX + kind]
        title = key.replace("-", " ").title() + " perimeter wall"
        ops.append({"op": "add_zone", "zone": {
            # workcell is the existing generic "Department / equipment area" type.
            # Service zones mean reserved service clearance and prohibit objects.
            "zoneId": "zn-independent-wall-" + key, "zoneType": "workcell", "label": title,
            "boundary": [{"x": x0, "z": z0}, {"x": x1, "z": z0},
                         {"x": x1, "z": z1}, {"x": x0, "z": z1}],
            "floorElevation": 0, "anchors": [], "evidence": [],
            "extensions": {"style": {"fillColor": "#adb8bd"}},
        }})
        ops.append({"op": "place_asset", "placement": {
            "placementId": "pl-independent-wall-" + key,
            "assetId": asset["assetId"], "assetDefinitionRevision": asset["assetDefinitionRevision"],
            "transform": {"position": {"x": (x0+x1)/2, "y": 0, "z": (z0+z1)/2},
                          "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1}, "scale": 1},
            "positionMode": "locked", "snapRelationship": None,
            "metadata": {"instanceLabel": title, "inputMethod": "independent-authoring"},
        }})
    return ops


def require_base(doc):
    if doc["layoutId"] != LAYOUT_ID or layout_revision(doc) != BASE_REVISION:
        raise ValueError("Factory 02 changed since review; refusing to overwrite it.")


def atomic_bytes(path, payload):
    RevisionedAuthorityRepository._atomic_write(path, payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / "report.json").exists():
        raise ValueError("Use a new evidence directory; existing reports are preserved.")
    directory = ROOT / ".runtime/facility-layout/layouts/local/site-local/layouts"
    target, original = directory / (LAYOUT_ID + ".json"), directory / (SOURCE_ID + ".json")
    before_bytes, original_bytes = target.read_bytes(), original.read_bytes()
    before = json.loads(before_bytes)
    require_base(before)
    default = json.loads((directory / "registry.json").read_text())["defaultLayoutId"]
    plan = before["extensions"]["facilityPlan"]
    segments = wall_segments(plan["widthMeters"], plan["depthMeters"])
    specs = asset_specs(segments)
    catalog_path = ROOT / PRIVATE_ASSET_MANIFEST
    catalog_before = catalog_path.read_bytes()
    catalog_doc = json.loads(catalog_before)
    new_ids = {a["assetId"] for a in specs}
    if any(a["assetId"] in new_ids for a in catalog_doc["assets"]):
        raise ValueError("Wall asset IDs already exist; refusing replacement.")
    catalog_doc["assets"].extend(specs)
    catalog_doc["summary"] = {"total": len(catalog_doc["assets"]), "published": len(specs), "skipped": 0, "failed": 0}
    stage = args.output / "staged-project"
    (stage / PRIVATE_ASSET_MANIFEST).parent.mkdir(parents=True, exist_ok=True)
    write_json(stage / PRIVATE_ASSET_MANIFEST, catalog_doc)
    meshes = []
    for asset in specs:
        d = asset["dimensions"]
        bounds = {"minimum": {"x": -d["width"]/2, "y": 0, "z": -d["depth"]/2},
                  "maximum": {"x": d["width"]/2, "y": d["height"], "z": d["depth"]/2}}
        payload = build_aabb_proxy_glb(bounds)
        inspected = inspect_glb(payload)
        assert inspected.scene_triangle_count == 12
        destination = stage / asset["artifact"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        meshes.append({"assetId": asset["assetId"], **inspected.to_manifest_dict()})
    from shutil import copytree
    copytree(_native_fs_path(ROOT / ".runtime/facility-layout/authorities"),
             _native_fs_path((args.output / "validation-store/authorities").resolve()), dirs_exist_ok=True)
    host = LocalFacilityLayoutHost(args.output / "validation-store", private_assets=True, private_asset_root=stage)
    try:
        catalog = {a["assetId"]: a for a in host.authoritative_asset_catalog()}
        ops = build_operations(segments, catalog)
        after = apply_facility_layout_operations(before, ops, updated_at=datetime.now(timezone.utc).isoformat())["document"]
        assert after["placements"][:len(before["placements"])] == before["placements"]
        assert after["zones"][:len(before["zones"])] == before["zones"]
        for field in ("routes", "floorMarkings", "sourceShellRef", "processBindings", "utilityNetworks"):
            assert after[field] == before[field]
        principal = host.principal()
        deps = host.service.validate_dependencies(principal, SITE, after).to_dict()
        spatial = host.service._diagnose_spatial(principal, SITE, after)
        routing = host.service._diagnose_routing(principal, SITE, after)
        write_json(args.output / "validation.json", {"spatial": spatial, "routing": routing})
        host.service._require_spatially_valid(spatial)
        host.service._require_routing_valid(routing)
        walls = [p for p in after["placements"] if p["assetId"] in new_ids]
        from shapely.geometry import LineString, box
        shapes = [footprint(p, catalog[p["assetId"]]) for p in walls]
        for route in before["routes"]:
            corridor = LineString([(p["x"], p["z"]) for p in route["centerline"]]).buffer(route["corridorWidth"]/2)
            assert all(s.intersection(corridor).area < 1e-8 for s in shapes)
        for x in (0, plan["widthMeters"]):
            opening = box(x-0.5, OPENING[0], x+0.5, OPENING[1])
            assert all(s.intersection(opening).area < 1e-8 for s in shapes)
        # A genuine collision probe must see the wall, not just its drawing.
        probe = deepcopy(after)
        probe["placements"][0]["transform"]["position"] = deepcopy(walls[0]["transform"]["position"])
        probe_result = host.service._diagnose_spatial(principal, SITE, probe)
        assert probe_result["metrics"]["placementCollisions"] > 0
        report = {"status": "validated", "baseRevision": BASE_REVISION,
            "heightMeters": HEIGHT, "thicknessMeters": THICKNESS, "panelJointMeters": JOINT,
            "eastWestOpeningZ": list(OPENING), "roof": False,
            "originalEquipmentUnchanged": len(before["placements"]),
            "wallPlacements": [p["placementId"] for p in walls], "meshes": meshes,
            "dependencies": deps, "spatial": spatial, "routing": routing,
            "collisionProbeDetected": True, "allAislesUnobstructed": True,
            "originalSha256": hashlib.sha256(original_bytes).hexdigest(),
            "limitations": ["Authored concept dimensions, not measured building geometry.",
                            "No structural, fire, exit, forklift clearance or building-code approval.",
                            "Outdoor walkthrough remains bounded by the existing facility floor."]}
        write_json(args.output / "before.json", before)
        write_json(args.output / "after.json", after)
        write_json(args.output / "operations.json", ops)
        write_json(args.output / "report.json", report)
        if args.apply:
            if target.read_bytes() != before_bytes or original.read_bytes() != original_bytes or catalog_path.read_bytes() != catalog_before:
                raise ValueError("Layout or catalog changed during review; refusing publication.")
            (args.output / "catalog-before.json").write_bytes(catalog_before)
            for asset in specs:
                destination = ROOT / asset["artifact"]
                if destination.exists():
                    raise ValueError("Refusing to overwrite an existing wall artifact.")
                atomic_bytes(destination, (stage / asset["artifact"]).read_bytes())
            catalog_payload = (stage / PRIVATE_ASSET_MANIFEST).read_bytes()
            atomic_bytes(catalog_path, catalog_payload)
            live = None
            try:
                live = LocalFacilityLayoutHost(ROOT / ".runtime/facility-layout", private_assets=True, private_asset_root=ROOT)
                saved = live.service.save_layout(live.principal(), SITE, LAYOUT_ID, after, BASE_REVISION)
            except Exception:
                # Restore only our own catalog publication, never concurrent edits.
                if target.read_bytes() == before_bytes and catalog_path.read_bytes() == catalog_payload:
                    atomic_bytes(catalog_path, catalog_before)
                raise
            finally:
                if live is not None:
                    live.close()
            write_json(args.output / "saved.json", saved["layout"])
            report.update(status="saved", savedRevision=saved["revision"])
        assert original.read_bytes() == original_bytes
        assert json.loads((directory / "registry.json").read_text())["defaultLayoutId"] == default
        report["originalUnchanged"] = True
        write_json(args.output / "report.json", report)
        print(json.dumps({k: report[k] for k in ("status", "originalEquipmentUnchanged", "wallPlacements", "originalUnchanged")}))
    finally:
        host.close()


if __name__ == "__main__":
    main()
