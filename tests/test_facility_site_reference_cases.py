"""Reference cases for the site build (docs/facility-site-reference-cases-plan.md, approved 2026-10-25).

Each case rebuilds a whole site on a frozen lot through Sage's own path: each step's package staged as one review,
the review opened, approved and saved. After every step the hard rules are checked on the saved layout, and the
step's numbers are compared with the recorded ones in tests/site_cases/recorded.py. No model, no network, a
temporary store only.

  pytest tests/test_facility_site_reference_cases.py
  python -m tests.test_facility_site_reference_cases [CASE ...] [--accept]
      prints each case's table; --accept rewrites the recorded numbers and prints each old and new value
"""
from __future__ import annotations

import asyncio
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
import math
from pathlib import Path
import pprint
import re
import sys
import tempfile
import time
from unittest import mock

import pytest
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway
from ai_inspector.codex_runtime.policy import PilotError
from ai_inspector.facility_layout import host as host_module
from ai_inspector.facility_layout.host import LOCAL_LAYOUT_ID, LOCAL_SITE_ID, LocalFacilityLayoutHost
from ai_inspector.facility_layout.parking_review import review_parking
from ai_inspector.facility_layout.site_context import KEY, analyze_site_context, building_outline, normalize_site_context
from ai_inspector.facility_layout.site_interior import FORKLIFT_ASSET, RACK_ASSET
from ai_inspector.facility_layout.site_parking import CAR_ASSETS
from ai_inspector.facility_layout.site_plan import SIDES
from ai_inspector.facility_layout.site_steps import CAR_ENTRANCE_GAP_METERS, DOOR_HEIGHT_METERS
from ai_inspector.facility_layout.site_trucks import TRUCK_ASSET
from tests.site_cases import CASES

RECORDED_FILE = Path(__file__).parent / "site_cases" / "recorded.py"
LENGTH, AREA = 0.01, 0.1  # tolerances: rounding only
CAR_CLEARANCE_METERS = 10.0  # the car park keeps this far from the truck court and drive
ALWAYS_UNVERIFIED = {"parking_maneuvering_unverified"}  # the parking review always asks for a vehicle check
STEP_PREFIXES = {  # what each step owns, by id prefix; anything else it changes is an earlier layer touched
    "building": None,  # the first step: replaces everything
    "zones": ("zn-receiving", "zn-shipping", "zn-storage", "zn-forklift-charging"),
    "markings": ("fm-interior-door", "fm-interior-cross-aisle-edge", "fm-interior-walkway"),
    "layout": ("fm-interior-row", "rt-interior-"),
    "docks": ("zn-truck-court", "fm-truck-court-", "area-truck-", "gr-", "entrance-truck", "route-entrance-truck"),
    "parking": ("zn-employee-parking", "fm-car-park-", "rt-car-park-", "area-employee-parking", "area-car-drive", "gr-",
                "entrance-cars", "route-entrance-cars"),
    "contents": ("pl-", "fm-interior-row", "iw-dock-door-"),
    "paint": ("gm-",),
    "references": ("rp-",),
}
WALL_CHANGES = {"building": None, "docks": "openings", "parking": "openings", "paint": "exteriorFinish"}


def recorded():
    namespace = {}
    if RECORDED_FILE.exists():
        exec(RECORDED_FILE.read_text(encoding="utf-8"), namespace)
    return namespace.get("RECORDED", {})


@contextmanager
def store(models):
    """A temporary layout store whose model library is the case's frozen records."""
    with tempfile.TemporaryDirectory(prefix="rc-", ignore_cleanup_errors=True) as root:
        with mock.patch.object(host_module, "build_private_local_asset_catalog", lambda *a, **k: deepcopy(models)):
            host = LocalFacilityLayoutHost(Path(root) / "facility", private_assets=True)
            try:
                host.ensure_bootstrap()
                yield host
            finally:
                host.close()


def place(host, principal, lot):
    saved = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    layout = deepcopy(saved["layout"])
    layout.setdefault("extensions", {})[KEY] = normalize_site_context(deepcopy(lot), layout)
    return host.layout_repository.save_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, layout, saved["revision"])


def run_step(host, principal, saved, number, tool, args):
    """One prompt's worth: the tool Sage calls, its package staged as one review, the review opened and approved."""
    reference = {"siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": saved["revision"]}
    gateway = FacilityEditGateway(host.agent_runtime, principal, reference, turn_id=f"case-{number:02}")
    try:
        read = gateway._read_data(tool, args)
    except PilotError as error:
        if error.code == "site_step_refused":
            return {"refused": str(error)}
        raise
    if tool == "suggest_site_references":  # Sage keeps the suggested points as one routine batch
        call = ("preview_facility_operations", {"operations": [{"op": "upsert_site_reference", "reference": point}
                                                               for point in read["suggested"]]})
    else:
        call = ("preview_planned_design", {"packageId": read["package"]["packageId"]})
    staged = asyncio.run(gateway.call(*call))
    if not staged["ok"]:
        return {"read": read, "notStaged": staged}
    proposal_id = gateway.proposal["proposalId"]
    preview = host.service.get_layout_proposal_preview(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, proposal_id)
    binding = preview["alternative"]["transactionBinding"]
    key = f"case-step-{number:02}"
    approval = host.service.approve_layout_proposal(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, proposal_id, binding,
                                                    session_id="reference-cases", idempotency_key=key,
                                                    explicit_approval=True)
    host.service.apply_layout_proposal(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, approval["approvalToken"], binding,
                                       session_id="reference-cases", idempotency_key=key)
    return {"read": read, "review": preview["alternative"],
            "saved": host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)}


# --- what the saved layout holds -------------------------------------------------------------------------------

def site(layout):
    return normalize_site_context(layout["extensions"][KEY], layout)


def shape(points):
    return Polygon([(p["x"], p["z"]) for p in points])


def items(layout):
    """Every identified thing a step can add, by id."""
    ext, context = layout["extensions"], layout["extensions"][KEY]
    rows = {}
    for collection, key in (("zones", "zoneId"), ("floorMarkings", "markingId"), ("routes", "routeId"),
                            ("placements", "placementId")):
        rows.update({row[key]: row for row in layout.get(collection, [])})
    rows.update({row["areaId"]: row for row in context.get("areas", [])})
    rows.update({row["referenceId"]: row for row in context.get("references", [])})
    rows.update({row["entranceId"]: row for row in (context.get("property") or {}).get("entrances", [])})
    rows.update({row["routeId"]: row for row in context.get("routes", [])})
    ground = ext.get("facilityGround") or {}
    rows.update({row["surfaceId"]: row for row in ground.get("surfaces", [])})
    rows.update({row["markId"]: row for row in ground.get("marks", [])})
    rows.update({row["wallId"]: row for row in (ext.get("facilityInteriorWalls") or {}).get("walls", [])})
    return rows


def wall_settings(layout):
    return layout["extensions"]["facilityPerimeterWalls"]["settings"]


def counts(layout):
    marks = Counter(group(row["markingId"]) for row in layout.get("floorMarkings", []))
    return {"placements": dict(sorted(Counter(p["assetId"] for p in layout.get("placements", [])).items())),
            "zones": len(layout.get("zones", [])), "markings": dict(sorted(marks.items())),
            "routes": len(layout.get("routes", []))}


def group(identity):
    return re.sub(r"-\d+[a-z]?(-\d+)*$", "", identity)


def extent(points):
    xs, zs = [x for x, _ in points], [z for _, z in points]
    return [round(min(xs), 3), round(min(zs), 3), round(max(xs), 3), round(max(zs), 3)]


def geometry(layout):
    """Where things are and how big, so a change that keeps every count still shows: marking areas and extents and
    route lengths by kind, and the spread of each model's placements."""
    marks, spots, lengths, models = Counter(), {}, Counter(), {}
    for row in layout.get("floorMarkings", []):
        key, at = group(row["markingId"]), row["transform"]["position"]
        marks[key] += row.get("width", 0) * row.get("depth", 0)
        spots.setdefault(key, []).append((at["x"], at["z"]))
    for row in layout.get("routes", []):
        line = row.get("centerline") or []
        lengths[group(row["routeId"])] += sum(math.dist((a["x"], a["z"]), (b["x"], b["z"])) for a, b in zip(line, line[1:]))
    for row in layout.get("placements", []):
        at = row["transform"]["position"]
        models.setdefault(row["assetId"], []).append((at["x"], at["z"]))
    return {"markingArea": {key: round(value, 1) for key, value in sorted(marks.items())},
            "markingExtent": {key: extent(value) for key, value in sorted(spots.items())},
            "routeLength": {key: round(value, 2) for key, value in sorted(lengths.items())},
            "modelExtent": {key: extent(value) for key, value in sorted(models.items())}}


def placed(layout, asset):
    return [p for p in layout.get("placements", []) if p["assetId"] == asset]


def zone(layout, zone_id):
    return next((shape(z["boundary"]) for z in layout.get("zones", []) if z["zoneId"] == zone_id), None)


def area_named(layout, area_id):
    return next((shape(a["boundary"]) for a in layout["extensions"][KEY].get("areas", []) if a["areaId"] == area_id),
                None)


def entrance(layout, entrance_id):
    return next(((e["x"], e["z"]) for e in (layout["extensions"][KEY].get("property") or {}).get("entrances", [])
                 if e["entranceId"] == entrance_id), None)


def dock_doors(layout, dock_wall):
    edge = SIDES.index(dock_wall)
    return [o for o in wall_settings(layout).get("openings", [])
            if o["edge"] == edge and abs(o.get("heightMeters", 0) - DOOR_HEIGHT_METERS) < 1e-9]


def wall_length(layout, dock_wall):
    plan = layout["extensions"]["facilityPlan"]
    return plan["widthMeters"] if dock_wall in ("south", "north") else plan["depthMeters"]


def ties(layout):
    """C-102's ties: from each building corner, the two nearest reference points (plan_pdf.setting_out)."""
    context = site(layout)
    corners = [(p["x"], p["z"]) for p in building_outline(layout, context)]
    references = context.get("references", [])
    return [(name, r["referenceId"], round(math.dist((r["x"], r["z"]), corner), 2))
            for name, corner in zip("ABCD", corners)
            for r in sorted(references, key=lambda r: math.dist((r["x"], r["z"]), corner))[:2]]


def numbers(step, layout, read):
    """The step's numbers, from the saved layout (and the planner's own summary)."""
    context = site(layout)
    plan = layout["extensions"]["facilityPlan"]
    summary = {key: value for key, value in (read.get("summary") or {}).items()
               if isinstance(value, (int, float, str)) and not isinstance(value, bool)}
    out = {"summary": summary}
    if step == "building":
        pose = context["buildingPose"]
        out.update(planWidth=plan["widthMeters"], planDepth=plan["depthMeters"],
                   buildingArea=round(plan["widthMeters"] * plan["depthMeters"], 1),
                   pose=[round(pose["x"], 3), round(pose["z"], 3), round(pose["bearingDegrees"], 3)],
                   wallHeight=wall_settings(layout).get("heightMeters"))
    if step in ("zones", "docks", "parking"):
        out["zoneAreas"] = {z["zoneId"]: round(shape(z["boundary"]).area, 1) for z in layout.get("zones", [])}
    if step in ("markings", "layout", "parking", "contents"):
        out["counts"] = counts(layout)
    if step in ("markings", "layout", "docks", "parking", "contents"):
        out["geometry"] = geometry(layout)
    if step == "layout":
        aisles = [r for r in layout.get("routes", []) if r["routeId"].startswith("rt-interior-rack-aisle")]
        out["rackAisles"] = len(aisles)
        out["rackAisleWidths"] = sorted({round(r["corridorWidth"], 3) for r in aisles})
    if step in ("docks", "parking"):
        out["doors"] = [[o["edge"], o["startMeters"], o["endMeters"], o.get("heightMeters")]
                        for o in wall_settings(layout).get("openings", [])]
        out["siteRoutes"] = {r["routeId"]: r["lengthMeters"] for r in context.get("routes", [])}
        out["groundTileArea"] = round(unary_union([box(s["minX"], s["minZ"], s["maxX"], s["maxZ"]) for s in
                                                   layout["extensions"]["facilityGround"].get("surfaces", [])]).area, 1)
    if step == "parking":
        truck, cars = entrance(layout, "entrance-truck"), entrance(layout, "entrance-cars")
        out["entranceGap"] = round(math.dist(truck, cars), 3) if truck and cars else None
    if step == "contents":
        out["closedDoors"] = sum(1 for w in (layout["extensions"].get("facilityInteriorWalls") or {}).get("walls", [])
                                 if w["wallId"].startswith("iw-dock-door-"))
    if step == "paint":
        finish = wall_settings(layout).get("exteriorFinish") or {}
        out.update(wallColor=finish.get("color"), bands=[b.get("color") for b in finish.get("bands", [])],
                   logoEdges=sorted(a.get("edge") for a in finish.get("artworks", [])),
                   groundMarks=[m["markId"] for m in layout["extensions"]["facilityGround"].get("marks", [])])
    if step == "references":
        out["references"] = [[r["referenceId"], r["kind"], r["source"], r["accuracyMeters"]]
                             for r in context.get("references", [])]
        out["ties"] = [list(tie) for tie in ties(layout)]
    return out


# --- the hard rules -----------------------------------------------------------------------------------------------

def broken_rules(step, args, before, result, done):
    """Every hard rule this step breaks, in words. `done` maps each earlier step to its arguments and numbers."""
    broken = []
    review, layout = result["review"], result["saved"]["layout"]
    if not (review.get("directApplyPolicy") or {}).get("eligible"):
        broken.append(f"Apply directly would hold it back: {review.get('directApplyPolicy')}")
    metrics = (review.get("spatial") or {}).get("metrics") or {}
    for key in ("placementCollisions", "shellObstacleCollisions", "clearanceConflicts", "obstructedAisleCount",
                "errorCount", "warningCount"):
        if metrics.get(key):
            broken.append(f"review: {key} {metrics[key]}")
    broken += [f"site check: {f['code']}: {f.get('message', '')}" for f in analyze_site_context(layout)["findings"]
               if f["severity"] != "info"]
    # Earlier layers are left alone: everything saved before this step that it does not own is unchanged.
    owned = STEP_PREFIXES[step]
    if owned is not None:
        now = items(layout)
        broken += [f"earlier layer changed: {key}" for key, row in items(before).items()
                   if not key.startswith(owned) and now.get(key) != row]
        walls_before, walls_now = wall_settings(before), wall_settings(layout)
        allowed = WALL_CHANGES.get(step)
        for key in sorted(set(walls_before) | set(walls_now)):
            if key == allowed == "openings":
                if not all(o in walls_now.get(key, []) for o in walls_before.get(key, [])):
                    broken.append("earlier wall openings changed")
            elif key != allowed and walls_before.get(key) != walls_now.get(key):
                broken.append(f"walls changed: {key}")
    if "paint" not in done and step != "paint" and wall_settings(layout).get("exteriorFinish"):
        broken.append("walls painted before the paint step")
    if step == "building":
        plan, height = layout["extensions"]["facilityPlan"], wall_settings(layout).get("heightMeters")
        if (plan["widthMeters"], plan["depthMeters"]) != (args["lengthMeters"], args["widthMeters"]):
            broken.append(f"building is {plan['widthMeters']} x {plan['depthMeters']} m, "
                          f"asked {args['lengthMeters']} x {args['widthMeters']} m")
        if "heightMeters" in args and height != args["heightMeters"]:
            broken.append(f"walls {height} m high, asked {args['heightMeters']} m")
    if step == "layout":
        narrow = [r["routeId"] for r in layout.get("routes", []) if r["routeId"].startswith("rt-interior-rack-aisle")
                  and r["corridorWidth"] < args["aisleWidthMeters"] - 1e-9]
        if narrow:
            broken.append(f"aisles narrower than {args['aisleWidthMeters']} m: {narrow}")
    if step == "docks":
        doors = dock_doors(layout, args["dockWall"])
        if len(doors) != args["doors"]:
            broken.append(f"{len(doors)} dock doors on the {args['dockWall']} wall, asked {args['doors']}")
        court = zone(layout, "zn-truck-court")
        expected = args["truckCourtDepthMeters"] * wall_length(layout, args["dockWall"])
        if court is None or abs(court.area - expected) > AREA:
            broken.append(f"truck court {court.area if court else 0:.1f} m2, not "
                          f"{args['truckCourtDepthMeters']} m deep along the dock wall ({expected:.1f} m2)")
    if step == "parking":  # fewer stalls than asked is allowed when the tool says so (Sage tells the user and asks)
        stalls = sum(1 for m in layout.get("floorMarkings", []) if m["markingId"].startswith("fm-car-park-stall"))
        summary = result["read"].get("summary") or {}
        if (summary.get("stallsRequested"), summary.get("stallsPlaced")) != (args["stalls"], stalls):
            broken.append(f"{stalls} stalls marked for {args['stalls']} asked, the tool reports "
                          f"{summary.get('stallsPlaced')} of {summary.get('stallsRequested')}")
    if "parking" in done or step == "parking":
        broken += parking_rules(layout)
    if step == "contents":
        asked = {TRUCK_ASSET: args.get("trucks", 0), CAR_ASSETS[0]: args.get("cars", 0),
                 FORKLIFT_ASSET: args.get("forklifts", 4)}
        for asset, count in asked.items():
            if len(placed(layout, asset)) != count:
                broken.append(f"{len(placed(layout, asset))} x {asset}, asked {count}")
        outlined = done["layout"]["numbers"]["summary"].get("rackBays")
        if len(placed(layout, RACK_ASSET)) != outlined:
            broken.append(f"{len(placed(layout, RACK_ASSET))} racks in {outlined} outlined bays")
        for asset, zone_id in ((FORKLIFT_ASSET, "zn-forklift-charging"), (CAR_ASSETS[0], "zn-employee-parking")):
            home = zone(layout, zone_id)
            outside = [p["placementId"] for p in placed(layout, asset) if home is None or not home.contains(
                Point(p["transform"]["position"]["x"], p["transform"]["position"]["z"]))]
            if outside:
                broken.append(f"{asset} outside {zone_id}: {outside[:5]}")
        if any("componentMaterials" in p for p in layout.get("placements", [])):
            broken.append("models arrived painted")
    if step == "paint":
        finish = wall_settings(layout).get("exteriorFinish") or {}
        beside = sorted((SIDES.index(done["building"]["args"]["dockWall"]) + turn) % 4 for turn in (1, 3))
        if finish.get("color") != "#06b6d4" or [b.get("color") for b in finish.get("bands", [])] != ["#ffffff"]:
            broken.append(f"walls not cyan with a white band: {finish.get('color')}, {finish.get('bands')}")
        if sorted(a.get("edge") for a in finish.get("artworks", [])) != beside:
            broken.append(f"logo not on the two walls beside the docks {beside}: {finish.get('artworks')}")
        if "gm-target" not in [m["markId"] for m in layout["extensions"]["facilityGround"].get("marks", [])]:
            broken.append("no logo on the yard pavement")
    if step == "references":
        context = site(layout)
        lot = shape(context["property"]["boundary"])
        broken += [f"{r['referenceId']} lies outside the property line" for r in context.get("references", [])
                   if lot.buffer(1e-6).disjoint(Point(r["x"], r["z"]))]
        if len(context.get("references", [])) != args["maxPoints"]:
            broken.append(f"{len(context.get('references', []))} reference points, asked {args['maxPoints']}")
        tied = Counter(corner for corner, _, _ in ties(layout))
        if sorted(tied.values()) != [2, 2, 2, 2]:
            broken.append(f"building corners without two ties: {dict(tied)}")
    return broken


def parking_rules(layout):
    """The car park keeps clear of the trucks (docs/facility-site-step-build-plan.md, car park rules)."""
    broken = []
    park = area_named(layout, "area-employee-parking")
    if park is None:
        return ["the car park area is missing"]
    truck, cars = entrance(layout, "entrance-truck"), entrance(layout, "entrance-cars")
    if truck and cars and math.dist(truck, cars) < CAR_ENTRANCE_GAP_METERS:
        broken.append(f"car entrance {math.dist(truck, cars):.3f} m from the truck entrance "
                      f"(rule: at least {CAR_ENTRANCE_GAP_METERS:g} m)")
    trucks = [s for s in (area_named(layout, "area-truck-court"), area_named(layout, "area-truck-drive")) if s is not None]
    if trucks:
        reach = unary_union(trucks)
        if park.distance(reach) < CAR_CLEARANCE_METERS - 1e-6:
            broken.append(f"car park {park.distance(reach):.3f} m from the truck court and drive "
                          f"(rule: at least {CAR_CLEARANCE_METERS:g} m)")
        between = unary_union([reach, *([Point(truck)] if truck else [])]).convex_hull
        if park.intersection(between).area > 1e-6:
            broken.append("car park lies between the truck entrance and the court")
    if any(z["zoneId"] == "zn-employee-parking" for z in layout.get("zones", [])):
        [reviewed] = review_parking(layout, ["zn-employee-parking"])["reviews"]
        codes = {f["code"] for f in reviewed["findings"]} - ALWAYS_UNVERIFIED
        if codes:
            broken.append(f"parking review: {sorted(codes)}")
        if reviewed["markedBays"] != reviewed["containedBays"]:
            broken.append(f"parking review: {reviewed['markedBays']} bays marked, {reviewed['containedBays']} inside")
    return broken


# --- a case -------------------------------------------------------------------------------------------------------

def run_case(name):
    case = CASES[name]
    lot = case["lot"]() if callable(case["lot"]) else case["lot"]
    rows, seen, done = [], set(), {}
    started = time.monotonic()
    with store(case["models"]) as host:
        principal = host.principal()
        saved = place(host, principal, lot)
        for number, (step, tool, args) in enumerate(case["recipe"]):
            before = saved["layout"]
            began = time.monotonic()
            result = run_step(host, principal, saved, number, tool, args)
            row = {"step": step, "seconds": round(time.monotonic() - began, 1)}
            rows.append(row)
            if "refused" in result:
                row.update(numbers={"refused": result["refused"]}, broken=[])
                break
            if "notStaged" in result:
                row.update(numbers={"notStaged": str(result["notStaged"])[:400]}, broken=["the package did not stage"])
                break
            row["numbers"] = numbers(step, result["saved"]["layout"], result["read"])
            # A rule still broken at a later step is reported once, where it broke.
            row["broken"] = [text for text in broken_rules(step, args, before, result, done) if text not in seen]
            seen.update(row["broken"])
            done[step] = {"args": args, "numbers": row["numbers"]}
            saved = result["saved"]
    return {"case": name, "rows": rows, "seconds": round(time.monotonic() - started, 1)}


def differences(old, new, path=""):
    """Each recorded number that moved, beyond rounding."""
    if isinstance(old, dict) and isinstance(new, dict):
        return [d for key in sorted(set(old) | set(new), key=str)
                for d in differences(old.get(key, "<none>"), new.get(key, "<none>"), f"{path}.{key}" if path else key)]
    if isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        return [d for i, (a, b) in enumerate(zip(old, new)) for d in differences(a, b, f"{path}[{i}]")]
    if isinstance(old, (int, float)) and isinstance(new, (int, float)) and not isinstance(old, bool):
        tolerance = AREA if "area" in path.lower() else LENGTH
        return [] if abs(old - new) <= tolerance + 1e-9 else [(path, old, new)]
    return [] if old == new else [(path, old, new)]


def tally(steps):
    """What a moved lot must share with its original: everything in the building's own frame (counts, doors, zones,
    markings, routes, models, ground tiles). Site-frame positions move with the lot, so they are left out."""
    keys = ("counts", "closedDoors", "rackAisles", "rackAisleWidths", "doors", "zoneAreas", "geometry", "groundTileArea",
            "planWidth", "planDepth", "wallColor", "logoEdges")
    return {step: {k: v for k, v in numbers_.items() if k in keys} for step, numbers_ in steps.items()}


def by_step(result):
    return {row["step"]: row["numbers"] for row in result["rows"]}


def table(result):
    lines = [f"{result['case']} ({result['seconds']} s)"]
    for row in result["rows"]:
        numbers_ = row["numbers"]
        if "refused" in numbers_:
            key = f"refused: {numbers_['refused']}"
        else:
            key = ", ".join(f"{k} {v}" for k, v in numbers_.items() if k != "summary" and not isinstance(v, (dict, list)))
        lines.append(f"  {row['step']:<10} {row['seconds']:>5} s  {'OK' if not row['broken'] else 'BROKEN'}  {key}")
        lines += [f"      ! {text}" for text in row["broken"]]
    return "\n".join(lines)


def record(results, accept):
    """Compare with the recorded numbers; with accept, write the new ones. Returns each change."""
    book = recorded()
    changes = []
    for result in results:
        new, old = by_step(result), book.get(result["case"])
        changes += ([(result["case"], *d) for d in differences(old, new)] if old is not None
                    else [(result["case"], "(new case)", None, "recorded")])
        if accept:
            book[result["case"]] = new
    if accept:
        RECORDED_FILE.write_bytes(('"""Recorded numbers for the site reference cases. Written by\n'
                                   '`python -m tests.test_facility_site_reference_cases --accept`; review each change."""\n\n'
                                   f"RECORDED = {pprint.pformat(book, width=118, sort_dicts=True)}\n").encode("utf-8"))
    return changes


@pytest.mark.parametrize("name", list(CASES))
def test_reference_case(name):
    result = run_case(name)
    print(table(result))
    broken = [(row["step"], text) for row in result["rows"] for text in row["broken"]]
    assert not broken, broken
    last = result["rows"][-1]
    if CASES[name].get("refuses"):
        assert last["step"] == CASES[name]["refuses"] and "refused" in last["numbers"], last
    else:
        assert len(result["rows"]) == len(CASES[name]["recipe"]) and "refused" not in last["numbers"], last
    twin = CASES[name].get("sameCountsAs")
    if twin:  # against the original's recorded numbers, which its own case checks
        assert not differences(tally(recorded()[twin]), tally(by_step(result)))
    changes = record([result], accept=False)
    assert not changes, "recorded numbers moved (review, then --accept): " + pprint.pformat(changes)


if __name__ == "__main__":
    accept = "--accept" in sys.argv
    names = [a for a in sys.argv[1:] if not a.startswith("--")] or list(CASES)
    results = []
    for case_name in names:
        results.append(run_case(case_name))
        print(table(results[-1]), flush=True)
    for result in results:
        twin = CASES[result["case"]].get("sameCountsAs")
        if twin:
            original = next((by_step(r) for r in results if r["case"] == twin), None) or recorded().get(twin, {})
            moved = differences(tally(original), tally(by_step(result)))
            print(f"{result['case']} vs {twin}: " + ("the same in the building frame" if not moved else f"differs {moved}"))
    for case_name, path, old, new in record(results, accept):
        print(f"{'accepted' if accept else 'moved'}: {case_name} {path}: {old} -> {new}")
