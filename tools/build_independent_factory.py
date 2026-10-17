"""Author a new factory sheet with existing catalog assets and operation kernels.

This is an independently authored layout, not a Sage generation benchmark.
Only --publish creates/saves the new sheet; the reference layout is read-only.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost
from ai_inspector.facility_layout.operations import (
    apply_facility_layout_operations, create_layout_document,
)
from ai_inspector.facility_layout.canonical import layout_revision

SOURCE_ID = "fl-reference-manual-20260812"
LAYOUT_ID = "fl-independent-factory-20260928"
NAME = "Factory 02 - Integrated Production"
SITE = "site-local"


class Author:
    def __init__(self, catalog):
        self.catalog = {a["assetId"]: a for a in catalog}
        self.operations = []
        self.placements = []
        self.zones = []

    def zone(self, key, label, bounds, color, kind="workcell", cell=False):
        x0, z0, x1, z1 = bounds
        extensions = {"style": {"fillColor": color}}
        if cell:
            extensions["cellGroup"] = {"schemaVersion": 1, "groupKind": "manufacturing_cell",
                "membership": "geometric", "envelopePadding": 1,
                "autoNumber": {"seriesId": "cell-independent-" + key[0].lower(),
                               "baseName": label.rsplit(" ", 1)[0], "prefix": key[0].upper(),
                               "start": 1, "padding": 2, "sequence": int(key[1:])}}
        value = {"zoneId": "zn-independent-" + key, "label": label, "zoneType": kind,
                 "boundary": [{"x": x0, "z": z0}, {"x": x1, "z": z0},
                              {"x": x1, "z": z1}, {"x": x0, "z": z1}],
                 "floorElevation": 0, "anchors": [], "evidence": [], "extensions": extensions}
        self.zones.append(value)
        self.operations.append({"op": "add_zone", "zone": value})

    def place(self, asset, x, z, label, angle=0, support=None):
        asset_id = asset if asset.startswith("asset-") else "asset-" + asset
        definition = self.catalog[asset_id]
        assert definition["definition"]["readiness"]["placementReady"]["value"]
        pid = f"pl-independent-{len(self.placements) + 1:04d}"
        y = 0
        relationship = None
        if support:
            base = self.catalog[support["assetId"]]["definition"]["geometry"]["aabb"]
            assert support["transform"]["quaternion"] == {"x": 0., "y": 0., "z": 0., "w": 1.}
            p = support["transform"]["position"]
            y = p["y"] + base["maximum"]["y"]
            relationship = {"family": "surface_attachment", "attachmentId": "surface:" + pid,
                            "supportPlacementId": support["placementId"], "surfaceId": "derived-top",
                            "surfaceSource": "derived_aabb", "side": "above",
                            "localPosition": {"x": x - p["x"], "z": z - p["z"]},
                            "localRotationDegrees": angle, "normalOffsetMeters": 0,
                            "evidenceStatus": "unverified"}
        half = math.radians(angle) / 2
        value = {"placementId": pid, "assetId": asset_id,
                 "assetDefinitionRevision": definition["assetDefinitionRevision"],
                 "transform": {"position": {"x": x, "y": y, "z": z},
                               "quaternion": {"x": 0., "y": math.sin(half), "z": 0., "w": math.cos(half)}, "scale": 1},
                 "positionMode": "manual", "snapRelationship": relationship,
                 "metadata": {"instanceLabel": label, "inputMethod": "independent-authoring"}}
        self.placements.append(value)
        self.operations.append({"op": "place_asset", "placement": value})
        return value

    def aisle(self, key, label, points, width, pedestrian=False):
        self.operations.append({"op": "add_aisle", "routeId": "rt-independent-" + key, "aisle": {
            "label": label, "centerline": [{"x": x, "y": 0, "z": z} for x, z in points],
            "corridorWidth": width, "aisleKind": "pedestrian" if pedestrian else "forklift",
            "direction": "two_way", "color": "#38bdf8" if pedestrian else "#eab308",
            "clearanceEvidenceStatus": "unverified"}})

    def mark(self, label, x, z, width, depth, kind="parking_box", angle=0):
        self.operations.append({"op": "add_floor_marking", "floorMarking": {
            "label": label, "markingType": kind, "width": width, "depth": depth,
            "transform": {"position": {"x": x, "y": 0, "z": z}, "rotationDegrees": angle},
            "positionMode": "manual", "semanticRole": {"crosswalk": "pedestrian_lane",
                "direction_arrow": "forklift_lane", "keep_clear": "keep_clear"}.get(kind, "staging"),
            "fillColor": "#ffffff" if kind == "crosswalk" else "#facc15",
            "strokeColor": "#334155", "opacity": 1, "text": "", "evidence": [],
            "metadata": {"authoredIn": "facility_plan"}}})


def author_factory(catalog):
    a = Author(catalog)
    a.zone("receiving", "01 Receiving + Raw Stock", (6, 112, 64, 194), "#4a90c2", "receiving")
    a.zone("machining", "02 Machining + Fabrication", (78, 126, 186, 194), "#7c92a8")
    a.zone("toolroom", "Toolroom + Maintenance Support", (78, 108, 186, 120), "#bd9164")
    a.zone("automation", "03 Robotic Production", (200, 108, 294, 194), "#36a9a3")
    a.zone("assembly", "04 Assembly + Kitting", (78, 6, 186, 88), "#54ab7d")
    a.zone("quality", "05 Inspection + Packing", (200, 6, 258, 88), "#a58bc4", "inspection")
    a.zone("dispatch", "06 Finished Goods + Dispatch", (6, 6, 64, 88), "#6a9fbd", "receiving")
    a.zone("service", "Equipment Service + Utilities", (270, 6, 294, 88), "#bd9164")

    # Independently designed guarded islands, with an open south loading gate.
    for row in range(3):
        for col in range(4):
            n = row * 4 + col + 1
            x, z = 211 + col * 23, 122 + row * 26
            tag = f"R{n:02d}"
            a.zone(tag, "Robot Cell " + tag, (x - 9, z - 12, x + 10, z + 11), "#299a9b", cell=True)
            for side in (-1, 1):
                for j in range(10):
                    a.place("5987t55-wire-mesh-machine-guard-panel", x + side * 6.1, z - 6.75 + j * 1.5, tag + " side guard")
            for j in range(8):
                a.place("5987t55-wire-mesh-machine-guard-panel", x - 5.25 + j * 1.5, z + 7.6, tag + " rear guard", 90)
                if j not in (3, 4):
                    a.place("5987t55-wire-mesh-machine-guard-panel", x - 5.25 + j * 1.5, z - 7.6, tag + " front guard", 90)
            a.place("abb-irb6650-robot", x, z, tag + " robot")
            a.place("workbench-w84-d48", x - 3.2, z + 3.5, tag + " fixture bench")
            lift = a.place("lift-table-30x96", x + 3.2, z + 3.5, tag + " lift table")
            a.place("carr-lane-cl-400-ptpb", x + 3.2, z + 3.5, tag + " tooling plate", support=lift)
            a.place("roll-away-cabinet", x - 3.5, z - 3.5, tag + " tools")
            for side in (-1, 1):
                a.place("pallet-1200x1000", x + side * 3.5, z - 10, tag + (" input" if side < 0 else " output"))
                a.mark(tag + " staging", x + side * 3.5, z - 10, 2.8, 2.8)
            a.place("operator", x + 8, z, tag + " attendant")
            a.mark(tag + " gate clearance", x, z - 7.8, 2.8, 3.4, "keep_clear")

    # Two warehouses have different row lengths and independent staging lanes.
    for bank, start, count in (("Raw", 138, 12), ("Finished", 48, 8)):
        for row in range(6):
            x = 11 + row * 9
            a.zone(f"{bank.lower()}-{row}", f"{bank} Rack Row {row + 1:02d}",
                   (x - 2, start - 2, x + 2, start + (count - 1) * 4.4 + 2), "#6396ae")
            for i in range(count):
                a.place("pallet-rack", x, start + i * 4.4, f"{bank} rack {row + 1:02d}-{i + 1:02d}")
    for row in range(4):
        for col in range(6):
            a.place("pallet-1200x1000", 11 + col * 9, 115 + row * 5, f"Inbound {row + 1}-{col + 1}")
    for row in range(4):
        for col in range(4):
            a.place("pallet-1200x1000", 13 + col * 12, 14 + row * 7, f"Outbound {row + 1}-{col + 1}")
    for x in (17, 47):
        a.place("forklift-2610x2264x986-minimum-height-green", x, 191, "Receiving forklift")
        a.place("forklift", x, 41, "Dispatch forklift")
        a.mark("Forklift parking", x, 191, 4, 4)
        a.mark("Forklift parking", x, 41, 4, 4)
    for x in (25, 39):
        a.place("pallet-truck-simple", x, 191, "Receiving pallet truck")

    machining_rows = [
        (134, ["doosan-dbc130-ii"] * 6),
        (146, ["cnc-mill"] * 6),
        (170, ["haas-st30-lathe"] * 6),
        (184, ["lathe-acer-1760g", "vertical-band-saw", "okamoto-surface-grinder", "sinker-edm", "lathe-hardinge-hlv", "kalamazoo-h9aw-horizontal-band-saw"]),
    ]
    for row, (z, machines) in enumerate(machining_rows):
        a.zone(f"machine-row-{row}", ["Heavy Boring", "CNC Milling", "CNC Turning", "Toolmaking + Finishing"][row],
               (80, z - 5.5, 184, z + 5.5), "#889bab")
        for col, machine in enumerate(machines):
            x = 88 + col * 17
            a.place(machine, x, z, f"M{row + 1}{col + 1} {machine}")
            if row in (1, 2):
                a.place("operator", x, z + 3.5, f"M{row + 1}{col + 1} operator")
                a.place("roll-away-cabinet", x + 5, z, f"M{row + 1}{col + 1} tools")
    for i in range(8):
        a.place("pallet-1200x1000", 87 + i * 13, 162, f"Machining WIP {i + 1}")
        a.mark("WIP", 87 + i * 13, 162, 3, 3)
    for i in range(6):
        a.place("tooling-shelves", 86 + i * 18, 116, f"Tool crib {i + 1}")
        a.place("workbench-w84-d48", 86 + i * 18, 111, f"Tool preparation {i + 1}")

    for row in range(2):
        for col in range(4):
            n = row * 4 + col + 1
            x, z = 90 + col * 26, 27 + row * 39
            tag = f"A{n:02d}"
            a.zone(tag, "Assembly Cell " + tag, (x - 10, z - 15, x + 10, z + 15), "#65b991", cell=True)
            a.place("workbench-w84-d48", x - 3.5, z + 2, tag + " assembly bench")
            a.place("workbench-w72-d36", x + 3.5, z + 2, tag + " test bench")
            a.place("operator", x - 3.5, z - 0.5, tag + " operator")
            a.place("user-library-mobile-cart", x + 3.5, z - 3.5, tag + " kit cart")
            a.place("lift-table-30x96", x, z + 8, tag + " output lift")
            a.place("hideaway-cabinet", x - 3.5, z + 8, tag + " parts cabinet")
            a.mark(tag + " kit parking", x + 3.5, z - 3.5, 3, 3)

    for row in range(4):
        z = 16 + row * 20
        a.zone(f"q{row}", f"Inspection Q{row + 1:02d}", (202, z - 8, 225, z + 8), "#aa99c7", "inspection", cell=True)
        a.place("assembled-laboratory-workstation", 211, z + 3, f"Q{row + 1} workstation")
        a.place("operator", 211, z + 0.5, f"Q{row + 1} inspector")
        a.place("user-library-mobile-cart", 219, z - 3, f"Q{row + 1} sample cart")
        a.place("workbench-w60-d60", 219, z + 3, f"Q{row + 1} gauging table")
        a.zone(f"p{row}", f"Packing P{row + 1:02d}", (231, z - 8, 256, z + 8), "#9c8ebc", cell=True)
        a.place("workbench-w84-d48", 238, z + 3, f"P{row + 1} packing bench")
        a.place("operator", 238, z + 0.5, f"P{row + 1} packer")
        a.place("pallet-1200x1000", 248, z - 3, f"P{row + 1} shipment")
        a.place("pallet-truck-simple", 248, z + 3, f"P{row + 1} pallet truck")
        a.mark("Packing output", 248, z - 3, 3, 3)

    service_assets = ["crane-8-ton", "crane-2-ton", "crane-montagem", "mobile-lift-mmle-50d",
                      "all-terrain-pallet-truck", "2329t24-steel-flush-platform-truck",
                      "mobile-folding-worktable", "tooling-shelves", "hideaway-cabinet",
                      "roll-away-cabinet", "centralizing-jack", "reversible-fork-lift-truck"]
    for i, asset in enumerate(service_assets):
        x, z = 277 + (i % 2) * 10, 14 + (i // 2) * 13
        a.place(asset, x, z, "Service " + asset)
        a.mark("Service bay", x, z, 7, 9)

    a.aisle("spine", "Main Logistics Boulevard", [(6, 98), (294, 98)], 8)
    a.aisle("west", "Receiving to Dispatch", [(70, 6), (70, 194)], 6)
    a.aisle("east", "Production Supply Spine", [(193, 6), (193, 194)], 6)
    a.aisle("service", "Service Access", [(264, 6), (264, 98)], 4)
    a.aisle("machine", "Machining Cross Aisle", [(70, 155), (193, 155)], 5)
    a.aisle("walk-north", "North Pedestrian Promenade", [(6, 104), (294, 104)], 2, True)
    a.aisle("walk-south", "South Pedestrian Promenade", [(6, 93), (294, 93)], 2, True)
    a.aisle("walk-west", "West Pedestrian Spine", [(75, 6), (75, 194)], 2, True)
    a.aisle("walk-east", "East Pedestrian Spine", [(198, 6), (198, 194)], 2, True)
    for x in (70, 193, 264):
        a.mark("Pedestrian crossing", x, 98, 3, 12, "crosswalk")
    for x in (32, 112, 155, 228, 283):
        a.mark("Eastbound", x, 96, 2, 4, "direction_arrow", 90)
        a.mark("Westbound", x, 100, 2, 4, "direction_arrow", 270)
    return a


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime/independent-factory-20260928")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    store = ROOT / ".runtime/facility-layout"
    source_path = store / "layouts/local/site-local/layouts" / (SOURCE_ID + ".json")
    before = source_path.read_bytes()
    registry_path = source_path.with_name("registry.json")
    default_before = json.loads(registry_path.read_text(encoding="utf-8"))["defaultLayoutId"]
    source = json.loads(before)
    now = datetime.now(timezone.utc).isoformat()
    blank = create_layout_document(layout_id=LAYOUT_ID, display_name=NAME,
        association=source["association"], coordinate_frame=source["coordinateFrame"],
        source_shell_ref=source["sourceShellRef"], policy_set_ref=source["policySetRef"], created_at=now,
        extensions={"extensions": {"facilityPlan": deepcopy(source["extensions"]["facilityPlan"])}})
    host = LocalFacilityLayoutHost(store, private_assets=True, private_asset_root=ROOT)
    report = {"status": "building", "sourceSha256": hashlib.sha256(before).hexdigest(),
              "layoutId": LAYOUT_ID, "authorship": "independent manual design using existing operation kernel",
              "notQualified": ["production capacity", "regulatory compliance", "robot safety envelopes", "manufacturing route optimization"]}
    try:
        author = author_factory(host._agent_asset_catalog(host.principal(), SITE))
        doc = blank
        batches = []
        for start in range(0, len(author.operations), 400):
            result = apply_facility_layout_operations(doc, author.operations[start:start + 400], updated_at=now)
            doc = result["document"]
            batches.append({"operations": min(400, len(author.operations) - start), "revision": layout_revision(doc)})
        write_json(args.output / "blank.json", blank)
        write_json(args.output / "operations.json", author.operations)
        write_json(args.output / "layout.json", doc)
        deps = host.service.validate_dependencies(host.principal(), SITE, doc)
        spatial = host.service._diagnose_spatial(host.principal(), SITE, doc)
        routing = host.service._diagnose_routing(host.principal(), SITE, doc)
        report.update(batches=batches, placements=len(doc["placements"]), zones=len(doc["zones"]),
                      routes=len(doc["routes"]), markings=len(doc["floorMarkings"]),
                      assetCounts=dict(Counter(p["assetId"] for p in doc["placements"])),
                      dependencies=deps.to_dict(), spatial=spatial, routing=routing)
        write_json(args.output / "report.json", report)
        host.service._require_spatially_valid(spatial)
        host.service._require_routing_valid(routing)
        assert 800 <= len(doc["placements"]) <= 850
        assert not any("zoneId" in p for p in doc["placements"])
        assert source_path.read_bytes() == before
        if args.publish:
            target = source_path.with_name(LAYOUT_ID + ".json")
            if target.exists():
                raise RuntimeError("The independently authored sheet already exists; refusing to overwrite it.")
            created = host.service.create_layout(host.principal(), SITE, blank, make_default=False)
            saved = host.service.save_layout(host.principal(), SITE, LAYOUT_ID, doc, created["revision"])
            report["publishedRevision"] = saved["revision"]
            report["savedPath"] = str(target)
            assert json.loads(registry_path.read_text(encoding="utf-8"))["defaultLayoutId"] == default_before
            write_json(args.output / "profile.json", {
                "schemaVersion": 1, "mode": "application", "profileId": "independent-factory-review",
                "origin": "http://127.0.0.1:8508", "dataRoot": str(args.output.resolve()),
                "backendId": str(uuid.uuid4()), "storeId": str(uuid.uuid4()),
                "facilityRoot": str(store), "libraryRoot": str(ROOT / "400S_Sorted_Library"),
                "startupLayoutId": SOURCE_ID,
            })
        assert source_path.read_bytes() == before
        report["sourceUnchanged"] = True
        report["status"] = "published" if args.publish else "validated"
        write_json(args.output / "report.json", report)
        print(json.dumps({k: report[k] for k in ("status", "placements", "zones", "routes", "markings", "sourceUnchanged")}))
    except Exception as error:
        report.update(status="failed", error=str(error), details=getattr(error, "details", None))
        write_json(args.output / "report.json", report)
        raise
    finally:
        host.close()


if __name__ == "__main__":
    main()
