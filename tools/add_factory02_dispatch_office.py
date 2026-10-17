"""Author a two-person dispatch office using existing catalog models.

Dry-run creates an isolated validated candidate. Publication requires --publish
and the original saved revision; neither command edits the reference layout.
This is a layout-authoring utility, not a new Sage planning capability.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from shutil import copytree
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shapely.geometry import LineString, Polygon, box
from ai_inspector.facility_layout.authority_repository import _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from tools.audit_independent_factory_layer2 import footprint, marking_polygon, write_json

LAYOUT_ID = "fl-independent-factory-20260928"
MANUAL_ID = "fl-reference-manual-20260812"
SITE = "site-local"
BASE_REVISION = "4fafb486dcb067fb4067771a9d34cf9b58f2f5125baf5733be182c373d3830d6"
ZONE_ID = "zn-independent-dispatch-office"
ROUTE_ID = "rt-independent-dispatch-office-walk"
PREFIX = "pl-independent-office-"
BOUNDS = (55.0, 7.0, 63.0, 15.0)
STORE = ROOT / ".runtime/facility-layout"
ASSET_IDS = tuple("asset-" + name for name in (
    "desk-1400-clear-wood", "chair-black", "screen-21", "keyboard",
    "mouse", "computer-case", "phone-tel1",
))


def require_base(doc):
    if doc["layoutId"] != LAYOUT_ID or layout_revision(doc) != BASE_REVISION:
        raise ValueError("Factory 02 has changed; review the current revision before adding the office.")


def office_operations(doc, catalog):
    require_base(doc)
    for aid in ASSET_IDS:
        if not catalog[aid]["definition"]["readiness"]["placementReady"]["value"]:
            raise ValueError("Office asset is not placement-ready: " + aid)
    x0, z0, x1, z1 = BOUNDS
    ops = [{"op": "add_zone", "zone": {
        "zoneId": ZONE_ID, "label": "Dispatch Office", "zoneType": "workcell",
        "boundary": [{"x": x0, "z": z0}, {"x": x1, "z": z0},
                     {"x": x1, "z": z1}, {"x": x0, "z": z1}],
        "floorElevation": 0, "anchors": [], "evidence": [],
        "extensions": {"style": {"fillColor": "#81ada9"}},
    }}]

    def place(key, aid, x, z, name, angle=0, support=None):
        asset = catalog["asset-" + aid]
        relationship, y = None, 0.0
        pid = PREFIX + key
        if support:
            definition = catalog[support["assetId"]]
            surface = next(s for s in definition["supportSurfaces"] if s["surfaceId"] == "worktop")
            base = support["transform"]["position"]
            y = base["y"] + surface["localFrame"]["origin"]["y"]
            relationship = {
                "family": "surface_attachment", "attachmentId": "surface:" + pid,
                "supportPlacementId": support["placementId"], "surfaceId": "worktop",
                "surfaceSource": "asset_definition", "side": "above",
                "localPosition": {"x": x - base["x"], "z": z - base["z"]},
                "localRotationDegrees": angle, "normalOffsetMeters": 0,
                "evidenceStatus": surface["evidenceStatus"],
            }
        half = math.radians(angle) / 2
        value = {
            "placementId": pid, "assetId": asset["assetId"],
            "assetDefinitionRevision": asset["assetDefinitionRevision"],
            "transform": {"position": {"x": x, "y": y, "z": z},
                          "quaternion": {"x": 0, "y": math.sin(half), "z": 0, "w": math.cos(half)},
                          "scale": 1},
            "positionMode": "manual", "snapRelationship": relationship,
            "metadata": {"instanceLabel": name, "inputMethod": "independent-authoring"},
        }
        ops.append({"op": "place_asset", "placement": value})
        return value

    for number, z in enumerate((9.0, 12.5), 1):
        key = str(number) + "-"
        name = "Dispatch office " + str(number) + " "
        desk = place(key + "desk", "desk-1400-clear-wood", 56.5, z, name + "desk")
        # Desk modesty panel is on -X. Chair back is on local -Z: -90 faces -X.
        place(key + "chair", "chair-black", 57.55, z, name + "chair", -90)
        place(key + "monitor", "screen-21", 56.32, z - 0.04, name + "monitor", 90, desk)
        place(key + "keyboard", "keyboard", 56.70, z - 0.04, name + "keyboard", 90, desk)
        place(key + "mouse", "mouse", 56.70, z - 0.40, name + "mouse", 90, desk)
        place(key + "phone", "phone-tel1", 56.40, z + 0.42, name + "telephone", 90, desk)
        place(key + "computer", "computer-case", 56.45, z - 1.05, name + "computer")
    ops.append({"op": "add_aisle", "routeId": ROUTE_ID, "aisle": {
        "label": "Dispatch Office Pedestrian Access",
        "centerline": [{"x": 62, "y": 0, "z": 14}, {"x": 62, "y": 0, "z": 93}],
        "corridorWidth": 1.5, "aisleKind": "pedestrian", "direction": "two_way",
        "color": "#38bdf8", "clearanceEvidenceStatus": "unverified",
    }})
    return ops


def audit(before, after, catalog):
    new = after["placements"][len(before["placements"]):]
    assert len(new) == 14
    assert after["placements"][:len(before["placements"])] == before["placements"]
    assert after["zones"][:len(before["zones"])] == before["zones"]
    assert after["routes"][:len(before["routes"])] == before["routes"]
    for key in ("floorMarkings", "extensions", "processBindings", "utilityNetworks", "sourceShellRef"):
        assert before[key] == after[key], key
    assert len(after["zones"]) == len(before["zones"]) + 1
    assert len(after["routes"]) == len(before["routes"]) + 1
    zone = box(*BOUNDS)
    department = next(z for z in before["zones"] if z["zoneId"] == "zn-independent-dispatch")
    assert Polygon([(p["x"], p["z"]) for p in department["boundary"]]).covers(zone)
    shapes = {p["placementId"]: footprint(p, catalog[p["assetId"]]) for p in after["placements"]}
    assert all(zone.covers(shapes[p["placementId"]]) for p in new)
    assert all(zone.intersection(shapes[p["placementId"]]).area < 1e-8 for p in before["placements"])
    assert all(zone.intersection(marking_polygon(m)).area < 1e-8 for m in before["floorMarkings"])
    by_id = {p["placementId"]: p for p in after["placements"]}
    attachments = []
    for p in new:
        link = p["snapRelationship"]
        if not link:
            continue
        support = by_id[link["supportPlacementId"]]
        surface = next(s for s in catalog[support["assetId"]]["supportSurfaces"] if s["surfaceId"] == link["surfaceId"])
        base, b = support["transform"]["position"], surface["bounds"]
        supported = box(base["x"] + b["minimumX"], base["z"] + b["minimumZ"],
                        base["x"] + b["maximumX"], base["z"] + b["maximumZ"])
        assert supported.covers(shapes[p["placementId"]])
        assert abs(p["transform"]["position"]["y"] - surface["localFrame"]["origin"]["y"]) < 1e-8
        attachments.append(p["placementId"])
    assert len(attachments) == 8
    access = next(r for r in after["routes"] if r["routeId"] == ROUTE_ID)
    corridor = LineString([(p["x"], p["z"]) for p in access["centerline"]]).buffer(access["corridorWidth"] / 2)
    clearance = min(corridor.distance(shape) for shape in shapes.values())
    assert clearance > 0
    for route in before["routes"]:
        existing = LineString([(p["x"], p["z"]) for p in route["centerline"]]).buffer(route["corridorWidth"] / 2)
        assert all(existing.intersection(shapes[p["placementId"]]).area < 1e-8 for p in new)
    promenade = next(r for r in before["routes"] if r["routeId"] == "rt-independent-walk-south")
    assert corridor.intersects(LineString([(p["x"], p["z"]) for p in promenade["centerline"]]))
    return {"officeBounds": list(BOUNDS), "addedPlacements": len(new), "supportedDesktopItems": attachments,
            "existingPlacementsUnchanged": len(before["placements"]), "existingNavigationUnchanged": True,
            "existingMarkingsUnchanged": True, "officeWithinDispatch": True,
            "pedestrianAccessWidthMeters": 1.5, "accessToObstacleGapMeters": clearance,
            "joinsExistingPromenade": True,
            "limitations": ["Open-plan concept, not an enclosed or acoustically isolated room.",
                            "Published library has desktop computers, not a laptop model.",
                            "No electrical, fire, accessibility, ergonomic or traffic-safety qualification."]}


def publish(output):
    report = json.loads((output / "report.json").read_text())
    if report["status"] != "validated":
        raise ValueError("Only a validated, unpublished candidate can be saved.")
    before_bytes = (output / "before.json").read_bytes()
    directory = STORE / "layouts/local/site-local/layouts"
    target = directory / (LAYOUT_ID + ".json")
    manual = directory / (MANUAL_ID + ".json")
    if target.read_bytes() != before_bytes or hashlib.sha256(manual.read_bytes()).hexdigest() != report["manualSha256"]:
        raise ValueError("Saved layouts changed since validation; no Save attempted.")
    candidate = json.loads((output / "candidate.json").read_text())
    if layout_revision(candidate) != report["candidateRevision"]:
        raise ValueError("The validated candidate has changed.")
    live = LocalFacilityLayoutHost(STORE, private_assets=True, private_asset_root=ROOT)
    try:
        saved = live.service.save_layout(live.principal(), SITE, LAYOUT_ID, candidate, report["baseRevision"])
    finally:
        live.close()
    assert hashlib.sha256(manual.read_bytes()).hexdigest() == report["manualSha256"]
    assert json.loads((directory / "registry.json").read_text())["defaultLayoutId"] == report["defaultLayoutId"]
    write_json(output / "saved.json", saved["layout"])
    report.update(status="saved", savedRevision=saved["revision"], manualUnchanged=True)
    write_json(output / "report.json", report)
    print(json.dumps({"status": "saved", "revision": saved["revision"], "placements": len(saved["layout"]["placements"])}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    if args.publish:
        publish(args.output)
        return
    args.output.mkdir(parents=True, exist_ok=False)
    directory = STORE / "layouts/local/site-local/layouts"
    before_bytes = (directory / (LAYOUT_ID + ".json")).read_bytes()
    before = json.loads(before_bytes)
    require_base(before)
    stage = (args.output / "validation-store").resolve()
    copytree(_native_fs_path(STORE / "authorities"), _native_fs_path(stage / "authorities"))
    copytree(_native_fs_path(STORE / "layouts/local"), _native_fs_path(stage / "layouts/local"))
    host = LocalFacilityLayoutHost(stage, private_assets=True, private_asset_root=ROOT)
    try:
        catalog = {a["assetId"]: a for a in host.authoritative_asset_catalog()}
        ops = office_operations(before, catalog)
        after = apply_facility_layout_operations(before, ops, updated_at=datetime.now(timezone.utc).isoformat())["document"]
        result = audit(before, after, catalog)
        principal = host.principal()
        dependencies = host.service.validate_dependencies(principal, SITE, after).to_dict()
        spatial = host.service._diagnose_spatial(principal, SITE, after)
        routing = host.service._diagnose_routing(principal, SITE, after)
        write_json(args.output / "validation.json", {"dependencies": dependencies, "spatial": spatial, "routing": routing})
        host.service._require_spatially_valid(spatial)
        host.service._require_routing_valid(routing)
        saved = host.service.save_layout(principal, SITE, LAYOUT_ID, after, layout_revision(before))
        (args.output / "before.json").write_bytes(before_bytes)
        write_json(args.output / "candidate.json", saved["layout"])
        write_json(args.output / "operations.json", ops)
        report = {"status": "validated", "baseRevision": layout_revision(before),
                  "candidateRevision": saved["revision"], **result,
                  "manualSha256": hashlib.sha256((directory / (MANUAL_ID + ".json")).read_bytes()).hexdigest(),
                  "defaultLayoutId": json.loads((directory / "registry.json").read_text())["defaultLayoutId"],
                  "totalPlacements": len(after["placements"]), "spatialMetrics": spatial["metrics"],
                  "officeAssetRevisions": {aid: catalog[aid]["assetDefinitionRevision"] for aid in ASSET_IDS}}
        write_json(args.output / "report.json", report)
        print(json.dumps(report))
    finally:
        host.close()


if __name__ == "__main__":
    main()
