"""Revision-bound functional review of Factory 02, not a general Sage evaluator.

Default is dry-run. --apply saves only the reviewed Factory 02 revision, through
the existing service. Geometry checks do not certify manufacturing or safety.
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
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.facility_layout.planning_readiness import compile_asset_planning_readiness
from ai_inspector.facility_layout.spatial import (
    _local_footprints, _rotate_vector, _transform_polygon_and_interval,
    oriented_box_polygon,
)

LAYOUT_ID = "fl-independent-factory-20260928"
SOURCE_ID = "fl-reference-manual-20260812"
BASE_REVISION = "a6454eb6812b8f1798a0eab50b33bfa0313ae9a242c8ad15a8b64fa60733e250"
VISUAL_REVIEW_REVISION = "58426c49bcf6a68b49a3366dafe9836bdbe77d9bdc1520516574295feb49e05e"
SITE = "site-local"
OPERATOR = "asset-operator"
WORKSTANDOFF = 0.4  # Authored illustration choice, not an ergonomic standard.
WALK_RADIUS = 0.35  # Geometric probe only; no egress or access qualification.


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def label(p):
    return p["metadata"]["instanceLabel"]


def position(p):
    return p["transform"]["position"]


def footprint(p, asset):
    h = asset["definition"]["geometry"]["heightInterval"]
    return unary_union([Polygon(_transform_polygon_and_interval(
        poly, (h["minimumY"], h["maximumY"]), p["transform"])[0])
        for poly in _local_footprints(asset)])


def marking_polygon(m):
    p = m["transform"]["position"]
    return Polygon(oriented_box_polygon((p["x"], p["z"]),
        (m["width"] / 2, m["depth"] / 2), math.radians(m["transform"]["rotationDegrees"])))


def facing_quaternion(origin, target):
    dx, dz = target["x"] - origin["x"], target["z"] - origin["z"]
    if math.hypot(dx, dz) < 1e-8:
        raise ValueError("An operator cannot face a coincident target.")
    angle = math.atan2(dx, dz)
    return {"x": 0.0, "y": math.sin(angle / 2), "z": 0.0, "w": math.cos(angle / 2)}


def heading_error(p, target):
    q = p["transform"]["quaternion"]
    forward = _rotate_vector((0, 0, 1), tuple(q[k] for k in ("x", "y", "z", "w")))
    d = (target["x"] - position(p)["x"], target["z"] - position(p)["z"])
    dot = (forward[0] * d[0] + forward[2] * d[1]) / math.hypot(*d)
    return math.degrees(math.acos(max(-1, min(1, dot))))


def operator_bindings(doc):
    """Explicit authored workstation relationships, not inferred machine interfaces."""
    by_label = {label(p): p for p in doc["placements"]}
    rows = []
    for p in doc["placements"]:
        if p["assetId"] != OPERATOR:
            continue
        name = label(p)
        tag = name.split()[0]
        if name.endswith(" attendant"):
            target = by_label[tag + " robot"]
            t = position(target)
            aim = {"x": t["x"], "y": 0, "z": t["z"] - 7.6}
            kind = "gate_observer"
        elif tag.startswith("M"):
            matches = [v for n, v in by_label.items() if n.startswith(tag + " ")
                       and not n.endswith((" operator", " tools"))]
            if len(matches) != 1:
                raise ValueError("Ambiguous machine assignment: " + name)
            target, kind = matches[0], "machine_observer"
            aim = position(target)
        else:
            suffix = {"A": " assembly bench", "Q": " workstation", "P": " packing bench"}[tag[0]]
            target, kind = by_label[tag + suffix], "bench_operator"
            aim = position(target)
        rows.append({"operatorId": p["placementId"], "targetId": target["placementId"],
                     "kind": kind, "aim": aim, "evidenceStatus": "authored",
                     "interfaceAuthority": "unknown"})
    return rows


def box_purpose(p):
    name, asset = label(p), p["assetId"]
    if name.endswith(" input"):
        return "INPUT", "staging"
    if name.endswith(" output") or name.endswith(" shipment"):
        return "OUTPUT", "staging"
    if name.startswith("Machining WIP"):
        return "WIP", "staging"
    if name.endswith(" kit cart"):
        return "KIT CART", "staging"
    if "forklift" in name.lower() or "fork-lift" in asset:
        return "FORKLIFT", "parking"
    if name.startswith("Service "):
        if "crane" in asset:
            return "CRANE", "parking"
        if "lift" in asset:
            return "LIFT", "parking"
        if "truck" in asset:
            return "CART", "parking"
        if "shelves" in asset or "cabinet" in asset:
            return "TOOLS", "staging"
        return "WORK AREA", "staging"
    raise ValueError("No reviewed marking purpose for " + name)


def aisle_kind(route):
    return route.get("extensions", {}).get("facilityAisle", {}).get("aisleKind")


def expected_crossings(doc):
    pedestrians = [r for r in doc["routes"] if aisle_kind(r) == "pedestrian"]
    vehicles = [r for r in doc["routes"] if aisle_kind(r) == "forklift"]
    if not pedestrians or not vehicles:
        raise ValueError("The reviewed pedestrian and vehicle networks must both be present.")
    result = []
    for walk in pedestrians:
        points = walk["centerline"]
        if len(points) != 2:
            raise ValueError("This review only supports straight authored aisles.")
        a, b = points
        angle = math.degrees(math.atan2(b["x"] - a["x"], b["z"] - a["z"])) % 180
        line = LineString([(p["x"], p["z"]) for p in points])
        for vehicle in vehicles:
            v = vehicle["centerline"]
            crossing = line.intersection(LineString([(p["x"], p["z"]) for p in v]))
            if crossing.is_empty:
                continue
            if crossing.geom_type != "Point":
                raise ValueError("Overlapping pedestrian/vehicle centerlines need separate review.")
            u = (b["x"] - a["x"], b["z"] - a["z"])
            w = (v[-1]["x"] - v[0]["x"], v[-1]["z"] - v[0]["z"])
            if abs(u[0] * w[0] + u[1] * w[1]) > 1e-6:
                raise ValueError("This review requires perpendicular crossings.")
            result.append({"pedestrianRouteId": walk["routeId"], "vehicleRouteId": vehicle["routeId"],
                "x": crossing.x, "z": crossing.y, "width": walk["corridorWidth"],
                "depth": vehicle["corridorWidth"] + 2, "angle": angle})
    return result


def build_corrections(doc, catalog):
    by_id = {p["placementId"]: p for p in doc["placements"]}
    shapes = {pid: footprint(p, catalog[(p["assetId"], p["assetDefinitionRevision"])]) for pid, p in by_id.items()}
    operations = []
    for bind in operator_bindings(doc):
        p, target = by_id[bind["operatorId"]], by_id[bind["targetId"]]
        desired = deepcopy(position(p))
        if bind["kind"] == "bench_operator":
            own_half_depth = (shapes[p["placementId"]].bounds[3] - shapes[p["placementId"]].bounds[1]) / 2
            if label(p).startswith("Q"):
                # Native CAD review shows drawers/work surface on the +Z side.
                desired["z"] = shapes[target["placementId"]].bounds[3] + own_half_depth + WORKSTANDOFF
            else:
                desired["z"] = shapes[target["placementId"]].bounds[1] - own_half_depth - WORKSTANDOFF
        elif bind["kind"] == "gate_observer":
            desired.update(x=position(target)["x"] + 1.6, z=position(target)["z"] - 11.4)
        if desired != position(p):
            operations.append({"op": "move_placement", "placementId": p["placementId"],
                               "position": desired, "movementKind": "user"})
        q = facing_quaternion(desired, bind["aim"])
        if q != p["transform"]["quaternion"]:
            operations.append({"op": "rotate_placement", "placementId": p["placementId"],
                               "quaternion": q, "movementKind": "user"})
    for marking in doc["floorMarkings"]:
        if marking["markingType"] == "parking_box":
            shape = marking_polygon(marking)
            occupants = [p for p in doc["placements"] if shape.covers(shapes[p["placementId"]])]
            if len(occupants) != 1:
                raise ValueError("Expected exactly one fully contained box occupant: " + marking["markingId"])
            text, role = box_purpose(occupants[0])
            operations.append({"op": "edit_floor_marking", "markingId": marking["markingId"],
                "patch": {"text": text, "semanticRole": role, "label": label(occupants[0]) + " bay"}})
        elif marking["markingType"] == "crosswalk":
            operations.append({"op": "delete_floor_marking", "markingId": marking["markingId"]})
    for i, c in enumerate(expected_crossings(doc), 1):
        operations.append({"op": "add_floor_marking", "floorMarking": {
            "markingId": f"fm-independent-crossing-{i:02d}", "label": "Pedestrian crossing " + str(i),
            "markingType": "crosswalk", "width": c["width"], "depth": c["depth"],
            "transform": {"position": {"x": c["x"], "y": 0, "z": c["z"]}, "rotationDegrees": c["angle"]},
            "positionMode": "manual", "semanticRole": "pedestrian_lane", "fillColor": "#ffffff",
            "strokeColor": "#334155", "opacity": 1, "text": "", "evidence": [],
            "metadata": {"authoredIn": "facility_plan"}}})
    return operations


def audit(doc, catalog):
    by_id = {p["placementId"]: p for p in doc["placements"]}
    shapes = {pid: footprint(p, catalog[(p["assetId"], p["assetDefinitionRevision"])]) for pid, p in by_id.items()}
    zshapes = {z["zoneId"]: Polygon([(p["x"], p["z"]) for p in z["boundary"]]) for z in doc["zones"]}
    membership = {}
    for pid, shape in shapes.items():
        containers = sorted((z.area, zid) for zid, z in zshapes.items() if z.covers(shape))
        membership[pid] = containers[0][1] if containers else None
    gates = [m for m in doc["floorMarkings"] if m["markingType"] == "keep_clear"]
    blocked = unary_union([shape for pid, shape in shapes.items() if by_id[pid]["assetId"] != OPERATOR]).buffer(WALK_RADIUS)
    plan = doc["extensions"]["facilityPlan"]
    free = box(WALK_RADIUS, WALK_RADIUS, plan["widthMeters"] - WALK_RADIUS,
               plan["depthMeters"] - WALK_RADIUS).difference(blocked)
    components = list(free.geoms) if free.geom_type == "MultiPolygon" else [free]
    walks = unary_union([LineString([(p["x"], p["z"]) for p in r["centerline"]])
                        for r in doc["routes"] if aisle_kind(r) == "pedestrian"])
    operators = []
    for bind in operator_bindings(doc):
        p = by_id[bind["operatorId"]]
        pt = Point(position(p)["x"], position(p)["z"])
        row = {**bind, "label": label(p), "headingErrorDegrees": round(heading_error(p, bind["aim"]), 6),
               "targetFootprintGapMeters": round(shapes[p["placementId"]].distance(shapes[bind["targetId"]]), 6),
               "geometricConnectionToPedestrianNetwork": any(c.covers(pt) and c.intersects(walks) for c in components),
               "overlapsKeepClear": any(shapes[p["placementId"]].intersection(marking_polygon(m)).area > 1e-8 for m in gates),
               "functionalWorkstationApproval": "unknown"}
        operators.append(row)
    boxes = []
    for m in doc["floorMarkings"]:
        if m["markingType"] != "parking_box":
            continue
        occupants = [p for pid, p in by_id.items() if marking_polygon(m).covers(shapes[pid])]
        expected = box_purpose(occupants[0]) if len(occupants) == 1 else (None, None)
        boxes.append({"markingId": m["markingId"], "placementIds": [p["placementId"] for p in occupants],
                      "text": m["text"], "expectedText": expected[0], "expectedRole": expected[1],
                      "passed": len(occupants) == 1 and (m["text"], m["semanticRole"]) == expected})
    crossing_checks = []
    crosswalks = [m for m in doc["floorMarkings"] if m["markingType"] == "crosswalk"]
    matched = set()
    for c in expected_crossings(doc):
        ids = [m["markingId"] for m in crosswalks
               if abs(m["transform"]["position"]["x"] - c["x"]) < 1e-6
               and abs(m["transform"]["position"]["z"] - c["z"]) < 1e-6
               and abs(m["transform"]["rotationDegrees"] % 180 - c["angle"]) < 1e-6
               and m["width"] >= c["width"] and m["depth"] >= c["depth"]]
        matched.update(ids)
        crossing_checks.append({**c, "markingIds": ids, "passed": len(ids) == 1})
    clear_checks = [{"markingId": m["markingId"], "overlappingPlacementIds": [pid for pid, shape in shapes.items()
                     if shape.intersection(marking_polygon(m)).area > 1e-8]} for m in gates]
    arrow_checks = []
    main = next(r for r in doc["routes"] if r["routeId"] == "rt-independent-spine")
    corridor = LineString([(p["x"], p["z"]) for p in main["centerline"]]).buffer(main["corridorWidth"] / 2, cap_style=2)
    for m in doc["floorMarkings"]:
        if m["markingType"] == "direction_arrow":
            angle = m["transform"]["rotationDegrees"] % 360
            arrow_checks.append({"markingId": m["markingId"], "label": m["label"],
                "containedInMainAisle": corridor.covers(marking_polygon(m)),
                "headingMatchesLabel": angle == {"Eastbound": 90, "Westbound": 270}.get(m["label"])})
    attachments = []
    for p in doc["placements"]:
        link = p.get("snapRelationship")
        if not link:
            continue
        support = by_id[link["supportPlacementId"]]
        support_asset = catalog[(support["assetId"], support["assetDefinitionRevision"])]
        top = position(support)["y"] + support_asset["definition"]["geometry"]["aabb"]["maximum"]["y"]
        attachments.append({"placementId": p["placementId"], "supportPlacementId": support["placementId"],
            "footprintSupported": shapes[support["placementId"]].covers(shapes[p["placementId"]]),
            "heightMatchesSupport": abs(position(p)["y"] - top) < 1e-6,
            "loadAndMountingApproval": "unknown", "surfaceSource": link["surfaceSource"]})
    robots = []
    for p in doc["placements"]:
        if p["assetId"] != "asset-abb-irb6650-robot":
            continue
        tag = label(p).split()[0]
        targets = [q for q in doc["placements"] if label(q) in (tag + " fixture bench", tag + " tooling plate")]
        robots.append({"robotId": p["placementId"], "cell": tag,
            "placementOriginDistancesMeters": {q["placementId"]: round(math.hypot(position(q)["x"] - position(p)["x"], position(q)["z"] - position(p)["z"]), 6) for q in targets},
            "verdict": "unknown", "priority": "high",
            "reason": "4.742 m origin separation warrants reach review. Origins are not robot-base/TCP/task coordinates; installed variant, base frame, tooling, target pose and joint limits are missing.",
            "source": "docs/facility-equipment-documented-capability-answers-2026-09-09.md"})
    readiness = [compile_asset_planning_readiness(catalog[key]) for key in sorted({(p["assetId"], p["assetDefinitionRevision"]) for p in doc["placements"]})]
    zones = [{"zoneId": z["zoneId"], "label": z["label"],
              "directPlacementIds": [pid for pid, zid in membership.items() if zid == z["zoneId"]],
              "containedPlacementCount": sum(zshapes[z["zoneId"]].covers(s) for s in shapes.values()),
              "functionalApproval": "unknown; catalog interfaces/clearances and process assignments are incomplete"} for z in doc["zones"]]
    counts = {
        "placements": len(by_id), "zones": len(zones), "markings": len(doc["floorMarkings"]),
        "uncontainedPlacements": sum(v is None for v in membership.values()),
        "operators": len(operators), "operatorHeadingFailures": sum(r["headingErrorDegrees"] > 1 for r in operators),
        "operatorNetworkDisconnections": sum(not r["geometricConnectionToPedestrianNetwork"] for r in operators),
        "operatorKeepClearOverlaps": sum(r["overlapsKeepClear"] for r in operators),
        "benchStandoffMismatches": sum(r["kind"] == "bench_operator" and abs(r["targetFootprintGapMeters"] - WORKSTANDOFF) > 1e-5 for r in operators),
        "boxLabelFailures": sum(not b["passed"] for b in boxes), "boxes": len(boxes),
        "crossings": len(crossing_checks), "missingOrIncorrectCrosswalks": sum(not c["passed"] for c in crossing_checks),
        "unmatchedCrosswalks": len(crosswalks) - len(matched),
        "blockedKeepClearMarkings": sum(bool(c["overlappingPlacementIds"]) for c in clear_checks),
        "arrowFailures": sum(not (c["containedInMainAisle"] and c["headingMatchesLabel"]) for c in arrow_checks),
        "attachmentGeometryFailures": sum(not (c["footprintSupported"] and c["heightMatchesSupport"]) for c in attachments),
        "unresolvedRobotCells": len(robots), "assetsMissingControlledReadiness": sum(not r["readiness"]["controlledPlanningReady"] for r in readiness),
    }
    return {"counts": counts, "operators": operators, "boxes": boxes, "crossings": crossing_checks,
            "keepClear": clear_checks, "arrows": arrow_checks, "attachments": attachments,
            "robotReachReview": robots, "assetReadiness": readiness, "zones": zones,
            "geometricWalkingProbe": {"radiusMeters": WALK_RADIUS, "freeComponents": len(components),
                "limitations": "Static footprints only. Unmarked floor travel is permitted in this probe; no approved route, traffic separation, robot safety, headroom or egress conclusion."}}


def require_base(doc):
    if doc["layoutId"] != LAYOUT_ID or layout_revision(doc) != BASE_REVISION:
        raise ValueError("Factory 02 has changed since review. Refusing to overwrite a different revision.")


def finish_visual_review(args):
    store = ROOT / ".runtime/facility-layout"
    directory = store / "layouts/local/site-local/layouts"
    target, original = directory / (LAYOUT_ID + ".json"), directory / (SOURCE_ID + ".json")
    original_bytes, before_bytes = original.read_bytes(), target.read_bytes()
    before = json.loads(before_bytes)
    if layout_revision(before) != VISUAL_REVIEW_REVISION:
        raise ValueError("Visual follow-up requires the exact reviewed first-pass revision.")
    previous = json.loads((args.output / "report.json").read_text())
    if previous["savedRevision"] != VISUAL_REVIEW_REVISION:
        raise ValueError("Visual follow-up evidence does not match the current layout.")
    host = LocalFacilityLayoutHost(store, private_assets=True, private_asset_root=ROOT)
    try:
        catalog = {(a["assetId"], a["assetDefinitionRevision"]): a for a in host.authoritative_asset_catalog()}
        inspectors = {p["placementId"] for p in before["placements"] if p["assetId"] == OPERATOR and label(p).startswith("Q")}
        operations = [op for op in build_corrections(before, catalog) if op.get("placementId") in inspectors]
        assert len(inspectors) == 4 and len(operations) == 8
        after = apply_facility_layout_operations(before, operations, updated_at=datetime.now(timezone.utc).isoformat())["document"]
        assert before["zones"] == after["zones"] and before["routes"] == after["routes"]
        assert before["floorMarkings"] == after["floorMarkings"]
        assert [p for p in before["placements"] if p["placementId"] not in inspectors] == [p for p in after["placements"] if p["placementId"] not in inspectors]
        checked = audit(after, catalog)
        assert all(r["headingErrorDegrees"] < 1 and r["geometricConnectionToPedestrianNetwork"]
                   and not r["overlapsKeepClear"] for r in checked["operators"])
        assert checked["counts"]["benchStandoffMismatches"] == 0
        principal = host.principal()
        deps = host.service.validate_dependencies(principal, SITE, after).to_dict()
        spatial = host.service._diagnose_spatial(principal, SITE, after)
        routing = host.service._diagnose_routing(principal, SITE, after)
        host.service._require_spatially_valid(spatial)
        host.service._require_routing_valid(routing)
        evidence = {"status": "dry-run", "baseRevision": VISUAL_REVIEW_REVISION,
            "operations": operations, "after": checked,
            "reason": "Native detail-inspection.png shows the inspectors behind the laboratory workstations. Move to the visible +Z drawer/work-surface side.",
            "evidenceStatus": "inferred", "manufacturerApprovedInterface": False}
        write_json(args.output / "visual-review.json", evidence)
        if args.apply:
            if target.read_bytes() != before_bytes or original.read_bytes() != original_bytes:
                raise ValueError("A layout changed during visual review; refusing Save.")
            for name in ("report", "after", "operations", "saved"):
                destination = args.output / ("first-pass-" + name + ".json")
                if destination.exists():
                    raise ValueError("First-pass evidence already exists; refusing to overwrite it.")
                destination.write_bytes((args.output / (name + ".json")).read_bytes())
            saved = host.service.save_layout(principal, SITE, LAYOUT_ID, after, VISUAL_REVIEW_REVISION)
            evidence.update(status="saved", savedRevision=saved["revision"])
            cumulative = json.loads((args.output / "operations.json").read_text()) + operations
            previous.update(after=checked, savedRevision=saved["revision"], resultRevision=layout_revision(after),
                spatial=spatial, routing=routing, dependencies=deps, visualReview=evidence,
                operationCounts=dict(Counter(op["op"] for op in cumulative)))
            previous["assumptions"].append("Inspection work side is +Z, inferred from visible CAD drawers/work surface in the native close-up, not a catalog-approved interface.")
            write_json(args.output / "after.json", after)
            write_json(args.output / "saved.json", saved["layout"])
            write_json(args.output / "operations.json", cumulative)
            write_json(args.output / "report.json", previous)
            write_json(args.output / "visual-review.json", evidence)
        assert original.read_bytes() == original_bytes
        print(json.dumps({"status": evidence["status"], "inspectorsCorrected": len(inspectors), "savedRevision": evidence.get("savedRevision")}))
    finally:
        host.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--visual-followup", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime/independent-factory-layer2-20260928")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.visual_followup:
        return finish_visual_review(args)
    store = ROOT / ".runtime/facility-layout"
    directory = store / "layouts/local/site-local/layouts"
    target, original = directory / (LAYOUT_ID + ".json"), directory / (SOURCE_ID + ".json")
    original_bytes, target_bytes = original.read_bytes(), target.read_bytes()
    before = json.loads(target_bytes)
    require_base(before)
    registry = json.loads((directory / "registry.json").read_text())
    host = LocalFacilityLayoutHost(store, private_assets=True, private_asset_root=ROOT)
    try:
        catalog = {(a["assetId"], a["assetDefinitionRevision"]): a for a in host.authoritative_asset_catalog()}
        operations = build_corrections(before, catalog)
        after = apply_facility_layout_operations(before, operations, updated_at=datetime.now(timezone.utc).isoformat())["document"]
        assert before["zones"] == after["zones"] and before["routes"] == after["routes"]
        assert [p["placementId"] for p in before["placements"]] == [p["placementId"] for p in after["placements"]]
        assert [p for p in before["placements"] if p["assetId"] != OPERATOR] == [p for p in after["placements"] if p["assetId"] != OPERATOR]
        report = {"status": "dry-run", "baseRevision": layout_revision(before), "resultRevision": layout_revision(after),
            "originalSha256": hashlib.sha256(original_bytes).hexdigest(),
            "before": audit(before, catalog), "after": audit(after, catalog),
            "operationCounts": dict(Counter(o["op"] for o in operations)),
            "preservation": {"allPlacementIds": True, "nonOperatorPlacements": 790, "zonesAndRoutes": True},
            "assumptions": ["Standing-avatar canonical forward is +Z (facility_layout_avatar.js).",
                "Operator-target assignments are authored design intent, not catalog-certified operating sides.",
                "0.4 m bench standoff is illustrative and not an ergonomic or safety certification.",
                "Robot attendants are moved outside the south loading gate, not inside its keep-clear marking.",
                "Crosswalks follow perpendicular pedestrian/vehicle centerline intersections, with 1 m authored overrun on each side. No regulatory dimensions are asserted."],
            "notQualified": ["machine loading/service sides", "robot task reach and guarding", "ergonomic reach",
                "workholding/support capacity", "truck turning/loading access", "egress", "utilities", "manufacturing process/capacity"]}
        failures = [k for k, v in report["after"]["counts"].items() if v and k in {
            "uncontainedPlacements", "operatorHeadingFailures", "operatorNetworkDisconnections", "operatorKeepClearOverlaps",
            "benchStandoffMismatches", "boxLabelFailures", "missingOrIncorrectCrosswalks", "unmatchedCrosswalks",
            "blockedKeepClearMarkings", "arrowFailures", "attachmentGeometryFailures"}]
        principal = host.principal()
        report["dependencies"] = host.service.validate_dependencies(principal, SITE, after).to_dict()
        report["spatial"] = host.service._diagnose_spatial(principal, SITE, after)
        report["routing"] = host.service._diagnose_routing(principal, SITE, after)
        write_json(args.output / "before.json", before)
        write_json(args.output / "after.json", after)
        write_json(args.output / "operations.json", operations)
        write_json(args.output / "report.json", report)
        if failures:
            raise ValueError("Layer 2 geometric checks failed: " + ", ".join(failures))
        host.service._require_spatially_valid(report["spatial"])
        host.service._require_routing_valid(report["routing"])
        if original.read_bytes() != original_bytes:
            raise ValueError("Original manual layout changed during audit.")
        if args.apply:
            if target.read_bytes() != target_bytes:
                raise ValueError("Factory 02 changed during audit; no save attempted.")
            saved = host.service.save_layout(principal, SITE, LAYOUT_ID, after, report["baseRevision"])
            report.update(status="saved", savedRevision=saved["revision"])
            write_json(args.output / "saved.json", saved["layout"])
            write_json(args.output / "profile.json", {
                "schemaVersion": 1, "mode": "application", "profileId": "independent-factory-layer2-review",
                "origin": "http://127.0.0.1:8509", "dataRoot": str(args.output.resolve()),
                "backendId": str(uuid.uuid4()), "storeId": str(uuid.uuid4()), "facilityRoot": str(store),
                "libraryRoot": str(ROOT / "400S_Sorted_Library"), "startupLayoutId": SOURCE_ID})
        assert original.read_bytes() == original_bytes
        assert json.loads((directory / "registry.json").read_text())["defaultLayoutId"] == registry["defaultLayoutId"]
        report["originalUnchanged"] = True
        write_json(args.output / "report.json", report)
        print(json.dumps({"status": report["status"], "counts": report["after"]["counts"], "operationCounts": report["operationCounts"]}))
    finally:
        host.close()


if __name__ == "__main__":
    main()
