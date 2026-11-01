"""Factory 02 lighting pass (docs/facility-lighting-plan.md, L5 and L8). Re-runnable, on this store or another one.

    python tools/light_factory02.py --store STORE [--root PROJECT_ROOT] [--output DIR] [--save]

STORE is a facility-layout store (the test copy: ui-data/facility-layout; the desktop app: .runtime/facility-layout
in the app's folder). PROJECT_ROOT holds generated/ (default: this script's project). For Factory 02
(fl-independent-factory-20260928) the pass gives:

- every high-bay light row's lens: Cool-white LED, the same finish on all rows so they still draw as one batch;
- a stack light on the fence at each robot cell's entrance (the end of the front guard panel beside the opening):
  green lit, and R06 amber lit (decision 4);
- a rotating beacon on the guard roof of each powered forklift, turning amber (the hand-winch lift truck gets none);
- a rotating beacon on a wall bracket beside each dock door, 4.6 m up, turning amber;
- outdoor lights (L8), each LED lens with an outdoor Lights finish, so in the evening scene it shows a soft beam down
  to the ground and a pool of light where the beam lands:
  - an 8 m pole light (Pole light LED) in the strip between each pair of back-to-back parking rows of the employee
    car park, about 14 m apart along it;
  - 8 m pole lights (Pole light LED) along the far (west) edge of the sunken truck yard, 3 m in, about 25 m apart;
  - an LED wall light (Dock light LED) over each dock door, outside, 4.6 m up, aimed down and out over the apron.

Exit signs are left as they are: their models already glow green, with their lettering.

It installs the light models first (tools/factory02_light_models.py), works out what is missing or different, applies
that to Factory 02 in a staged copy of the store and checks it there: no spatial errors, the same warnings as before,
and new notes only about the pass's own placements (the notes every placement gets). It writes report.json to the
output folder. With --save it then saves the checked result to STORE, only if Factory 02 has not changed meanwhile.
When everything is in place already it says so and saves nothing. Restart the app afterwards: it reads the asset
catalog when it starts.
"""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from shutil import copy2, copytree
import argparse
import hashlib
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai_inspector.facility_layout.authority_repository import _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.component_materials import normalize_component_materials
from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.facility_layout.spatial import _local_height_interval, _quaternion, _rotate_vector
from tools import factory02_light_models as models

LAYOUT_ID = "fl-independent-factory-20260928"
SITE = "site-local"
LAYOUTS = Path("layouts/local/site-local/layouts")
ROW = "asset-factory02-high-bay-light-row-294m"
LENS_KEY = "p:high-bay-light-row-294m/lens#0"
ROBOT = "asset-abb-irb6650-robot"
GUARD = "asset-5987t55-wire-mesh-machine-guard-panel"
DOCK = "asset-factory02-dock-door-open"
AMBER_CELL = "R06"
# Where each forklift's beacon stands on its guard roof, in the forklift's own frame (x, z), checked against the
# models as the 3D view draws them. The forklift: on the flat roof plate, by its rear corner. The compact truck (forks
# at +x): its roof is open slats under two side rails, so the beacon stands on the rear end of the left rail
# (z -0.45), as far out as its bounds allow (0.075 m from the side at z -0.493).
FORKLIFT_ROOFS = {"asset-forklift": (-0.40, -0.85),
                  "asset-forklift-2610x2264x986-minimum-height-green": (-0.945, -0.415)}
# Beside a dock door's opening, in the door's frame: left of the door tracks (x -1.58) and clear of the guard posts'
# footprint (x -1.92), against the inside face of the wall infill (z 0.1237) with a 3 mm gap, and 4.6 m up, so the
# spatial check counts it as hung overhead (4.5 m or more) instead of standing on the floor.
DOCK_BEACON_X, DOCK_BEACON_Y, DOOR_FACE_Z, WALL_GAP = -2.05, 4.6, 0.1237, 0.003
STACK_FOOT_MARGIN = 0.045   # from the end of the guard panel to the middle of the stack light's foot
# Outdoor lights (L8). Car park: the wheel stops of two parking rows parked head to head stand 1.5 to 2.1 m apart (in
# Factory 02, 1.8 m, and no car reaches into the middle 2.2 m), so a pole light's 0.5 m base stands on the line
# between them, the poles about CAR_PARK_SPACING apart. Truck yard: the ground lying below the floor; its poles stand on
# it YARD_INSET in from its far (west) edge, about YARD_SPACING apart, clear of the waiting trucks. Dock light: on the
# outside face of the dock door's wall infill (z -0.1213 in the door's frame) with a 3 mm gap, centred on the door and
# 4.6 m up (hung overhead, above the dock shelter's top at 3.55 m), facing out of the building.
WHEEL_STOP = "asset-factory02-parking-wheel-stop"
STRIP_GAP = (1.5, 2.1)
CAR_PARK_SPACING = 14.0
YARD_SPACING, YARD_INSET = 25.0, 3.0
DOCK_LIGHT_Y, WALL_OUTSIDE_Z = 4.6, -0.1213
POLE_FINISH, DOCK_FINISH = "light-pole-led", "light-dock-led"
OWN_PREFIXES = ("pl-factory02-stack-light-", "pl-factory02-beacon-", "pl-factory02-pole-light-", "pl-factory02-dock-light-")
OWN_ASSETS = {models.STACK_LIGHT, models.BEACON, models.WALL_BEACON, models.POLE_LIGHT, models.WALL_LIGHT}


def _label(placement):
    return str((placement.get("metadata") or {}).get("instanceLabel") or "")


def _asset(catalog, asset_id):
    if asset_id not in catalog:
        raise ValueError(f"{asset_id} is not in the asset catalog.")
    return catalog[asset_id]


def _transform(support, local, height):
    """Upright and turned with SUPPORT, at the point LOCAL (x, z) of its frame, HEIGHT above the datum."""
    q = _quaternion(support["transform"]["quaternion"])
    dx, _, dz = _rotate_vector((local[0], 0.0, local[1]), q)
    position = support["transform"]["position"]
    return {"position": {"x": round(position["x"] + dx, 6), "y": round(height, 6), "z": round(position["z"] + dz, 6)},
            "quaternion": dict(support["transform"]["quaternion"]), "scale": 1}


def _on_top(child_id, support, support_asset, local):
    """Standing on SUPPORT's top, as the 3D view's own surface attachments do (derived-top of its bounds)."""
    top = support["transform"]["position"]["y"] + _local_height_interval(support_asset)[1]
    relationship = {"attachmentId": "surface:" + child_id, "evidenceStatus": "unverified",
                    "family": "surface_attachment", "localPosition": {"x": local[0], "z": local[1]},
                    "localRotationDegrees": 0.0, "normalOffsetMeters": 0, "side": "above",
                    "supportPlacementId": support["placementId"], "surfaceId": "derived-top",
                    "surfaceSource": "derived_aabb"}
    return _transform(support, local, top), relationship


def _upright(x, y, z):
    return {"position": {"x": round(x, 6), "y": round(y, 6), "z": round(z, 6)},
            "quaternion": {"w": 1, "x": 0, "y": 0, "z": 0}, "scale": 1}


def _turned_around(quaternion):
    """QUATERNION followed by half a turn about its own up axis, written with w >= 0."""
    x, y, z, w = (quaternion.get(k, 0) for k in ("x", "y", "z", "w"))
    turned = {"x": -z, "y": w, "z": x, "w": -y}
    if turned["w"] < 0 or (turned["w"] == 0 and turned["y"] < 0):
        turned = {k: -v for k, v in turned.items()}
    return {k: v + 0 for k, v in turned.items()}   # + 0 writes -0 as 0


def parking_strips(placements):
    """The strips between parking rows parked head to head: (z, first stop's x, last stop's x, y) for each pair of
    wheel stop rows STRIP_GAP apart. The rows run along X, as in Factory 02's car park."""
    rows = {}
    for p in placements:
        if p["assetId"] == WHEEL_STOP:
            position = p["transform"]["position"]
            rows.setdefault(round(position["z"], 1), []).append(position)
    keys = sorted(rows)
    strips = []
    for a, b in zip(keys, keys[1:]):
        if STRIP_GAP[0] <= b - a <= STRIP_GAP[1]:
            stops = rows[a] + rows[b]
            middle = (sum(s["z"] for s in rows[a]) / len(rows[a]) + sum(s["z"] for s in rows[b]) / len(rows[b])) / 2
            strips.append((middle, min(s["x"] for s in stops), max(s["x"] for s in stops), max(s["y"] for s in stops)))
    return strips


def truck_yard(doc):
    """The truck yard: the level ground surfaces lying below the floor, or [] when there are none."""
    floor = float((doc.get("coordinateFrame") or {}).get("floorElevation", 0))
    rows = ((doc.get("extensions") or {}).get("facilityGround") or {}).get("surfaces") or []
    return [s for s in rows if s["startElevation"] == s["endElevation"] and s["startElevation"] < floor - 0.5]


def _spread(first, last, spacing):
    """Points from FIRST to LAST about SPACING apart, each in the middle of its share."""
    count = max(1, round((last - first) / spacing))
    return [first + (i + 0.5) * (last - first) / count for i in range(count)]


def _placement(placement_id, asset, transform, label, mode, relationship=None):
    return {"placementId": placement_id, "assetId": asset["assetId"],
            "assetDefinitionRevision": asset["assetDefinitionRevision"], "transform": transform,
            "positionMode": mode, "snapRelationship": relationship,
            "metadata": {"inputMethod": "independent-authoring", "instanceLabel": label}}


def _finish(doc, key, appearance_id):
    return normalize_component_materials(
        {"representation": "overview", "overrides": [{"key": key, "appearanceId": appearance_id}]}, doc)


def targets(doc, catalog):
    """The pass's own placements, each with its finishes: [(placement, componentMaterials)]."""
    placements = doc["placements"]
    stack, beacon, wall = (_asset(catalog, a) for a in (models.STACK_LIGHT, models.BEACON, models.WALL_BEACON))
    guard = _asset(catalog, GUARD)
    result = []
    for robot in sorted((p for p in placements if p["assetId"] == ROBOT), key=_label):
        cell = _label(robot).split(" ")[0]
        fronts = [p for p in placements if p["assetId"] == GUARD and _label(p) == cell + " front guard"]
        if len(fronts) < 2:
            raise ValueError(f"Robot cell {cell} has no front guard row.")
        axis = _rotate_vector((0.0, 0.0, 1.0), _quaternion(fronts[0]["transform"]["quaternion"]))
        along = lambda p: p["transform"]["position"]["x"] * axis[0] + p["transform"]["position"]["z"] * axis[2]
        fronts.sort(key=along)
        gaps = [along(b) - along(a) for a, b in zip(fronts, fronts[1:])]
        widest = max(range(len(gaps)), key=gaps.__getitem__)
        half = guard["definition"]["geometry"]["aabb"]["maximum"]["z"]
        if gaps[widest] - 2 * half < 1.0:
            raise ValueError(f"Robot cell {cell} has no entrance in its front guard row.")
        panel = fronts[widest + 1]    # the first panel after the opening: the opening is at its -Z end
        placement_id = "pl-factory02-stack-light-" + cell.lower()
        transform, relationship = _on_top(placement_id, panel, guard, (0.0, -(half - STACK_FOOT_MARGIN)))
        lamp = "amber" if cell == AMBER_CELL else "green"
        result.append((_placement(placement_id, stack, transform, cell + " stack light", "manual", relationship),
                       _finish(doc, models.STACK_LAMP_KEYS[lamp], "light-stack-" + lamp)))
    for forklift in sorted((p for p in placements if p["assetId"] in FORKLIFT_ROOFS), key=lambda p: p["placementId"]):
        placement_id = "pl-factory02-beacon-" + forklift["placementId"][3:]
        transform, relationship = _on_top(placement_id, forklift, _asset(catalog, forklift["assetId"]),
                                          FORKLIFT_ROOFS[forklift["assetId"]])
        result.append((_placement(placement_id, beacon, transform, _label(forklift) + " beacon", "manual", relationship),
                       _finish(doc, models.BEACON_LENS_KEYS[models.BEACON], "light-beacon-amber")))
    half_depth = wall["definition"]["geometry"]["aabb"]["maximum"]["z"]
    for door in sorted((p for p in placements if p["assetId"] == DOCK), key=lambda p: p["placementId"]):
        placement_id = "pl-factory02-beacon-" + re.sub(r"^pl-(factory02-support-)?", "", door["placementId"])
        transform = _transform(door, (DOCK_BEACON_X, DOOR_FACE_Z + WALL_GAP + half_depth),
                               door["transform"]["position"]["y"] + DOCK_BEACON_Y)
        result.append((_placement(placement_id, wall, transform, _label(door).replace(" - open", "") + " beacon", "locked"),
                       _finish(doc, models.BEACON_LENS_KEYS[models.WALL_BEACON], "light-beacon-amber")))
    result += outdoor_targets(doc, catalog)
    return result


def outdoor_targets(doc, catalog):
    """L8: pole lights in the car park and the truck yard, and a light over each dock door: [(placement, finishes)]."""
    placements = doc["placements"]
    result = []
    strips = parking_strips(placements)
    yard = truck_yard(doc)
    doors = sorted((p for p in placements if p["assetId"] == DOCK), key=lambda p: p["placementId"])
    if not (strips or yard or doors):
        return result
    pole, wall_light = (_asset(catalog, a) for a in (models.POLE_LIGHT, models.WALL_LIGHT))
    pole_lens = _finish(doc, models.LED_LENS_KEYS[models.POLE_LIGHT], POLE_FINISH)
    spots = [(x, y, z) for z, first, last, y in strips for x in _spread(first, last, CAR_PARK_SPACING)]
    for n, (x, y, z) in enumerate(spots, 1):
        result.append((_placement(f"pl-factory02-pole-light-car-park-{n:02d}", pole, _upright(x, y, z),
                                  f"Car park light {n:02d}", "locked"), pole_lens))
    if yard:
        x = min(s["minX"] for s in yard) + YARD_INSET
        for n, z in enumerate(_spread(min(s["minZ"] for s in yard), max(s["maxZ"] for s in yard), YARD_SPACING), 1):
            under = [s for s in yard if s["minX"] <= x <= s["maxX"] and s["minZ"] <= z <= s["maxZ"]]
            if not under:
                raise ValueError(f"The truck yard has no ground under its light at x {x}, z {z}.")
            result.append((_placement(f"pl-factory02-pole-light-yard-{n:02d}", pole,
                                      _upright(x, under[0]["startElevation"], z), f"Truck yard light {n:02d}", "locked"),
                           pole_lens))
    half_depth = wall_light["definition"]["geometry"]["aabb"]["maximum"]["z"]
    for door in doors:
        name = re.sub(r"^pl-(factory02-support-)?", "", door["placementId"])
        transform = _transform(door, (0.0, WALL_OUTSIDE_Z - WALL_GAP - half_depth),
                               door["transform"]["position"]["y"] + DOCK_LIGHT_Y)
        transform["quaternion"] = _turned_around(door["transform"]["quaternion"])
        label = _label(door).replace(" - open", "").replace("Dock door", "Dock light")
        result.append((_placement("pl-factory02-dock-light-" + name, wall_light, transform, label, "locked"),
                       _finish(doc, models.LED_LENS_KEYS[models.WALL_LIGHT], DOCK_FINISH)))
    return result


def _same(existing, placement, materials):
    def close(a, b):
        return all(abs(float(a.get(k, float("nan"))) - b[k]) <= 1e-9 for k in b)
    have, want = existing.get("transform") or {}, placement["transform"]
    return (existing.get("assetId") == placement["assetId"]
            and existing.get("assetDefinitionRevision") == placement["assetDefinitionRevision"]
            and close(have.get("position") or {}, want["position"]) and close(have.get("quaternion") or {}, want["quaternion"])
            and have.get("scale", 1) == 1 and existing.get("snapRelationship") == placement["snapRelationship"]
            and existing.get("positionMode") == placement["positionMode"] and _label(existing) == _label(placement)
            and existing.get("componentMaterials") == materials)


def light_operations(doc, catalog):
    """Operations that bring DOC to the pass's state (none when it is there already), and a summary."""
    ops = []
    lens = _finish(doc, LENS_KEY, "light-cool-white-led")["overrides"][0]
    rows = [p for p in doc["placements"] if p["assetId"] == ROW]
    rows_set = 0
    for row in rows:
        current = row.get("componentMaterials") or {}
        kept = {o["key"]: o for o in current.get("overrides", [])} if current.get("representation") == "overview" else {}
        if kept.get(LENS_KEY) == lens:
            continue
        kept[LENS_KEY] = lens
        ops.append({"op": "set_component_materials", "placementId": row["placementId"],
                    "materials": {"representation": "overview", "overrides": [kept[k] for k in sorted(kept)]}})
        rows_set += 1
    wanted = targets(doc, catalog)
    wanted_ids = {placement["placementId"] for placement, _ in wanted}
    existing = {p["placementId"]: p for p in doc["placements"]}
    stale = sorted(pid for pid, p in existing.items()
                   if pid.startswith(OWN_PREFIXES) and p.get("assetId") in OWN_ASSETS and pid not in wanted_ids)
    ops += [{"op": "delete_placement", "placementId": pid} for pid in stale]
    placed, unchanged = [], []
    for placement, materials in wanted:
        old = existing.get(placement["placementId"])
        if old is not None and _same(old, placement, materials):
            unchanged.append(placement["placementId"])
            continue
        if old is not None:
            ops.append({"op": "delete_placement", "placementId": placement["placementId"]})
        ops.append({"op": "place_asset", "placement": placement})
        ops.append({"op": "set_component_materials", "placementId": placement["placementId"], "materials": materials})
        placed.append(placement["placementId"])
    summary = {"lightRows": len(rows), "lightRowsSet": rows_set,
               "stackLights": sorted(p["placementId"] for p, _ in wanted if p["assetId"] == models.STACK_LIGHT),
               "amberCell": AMBER_CELL,
               "forkliftBeacons": sorted(p["placementId"] for p, _ in wanted if p["assetId"] == models.BEACON),
               "dockBeacons": sorted(p["placementId"] for p, _ in wanted if p["assetId"] == models.WALL_BEACON),
               "carParkLights": sorted(p["placementId"] for p, _ in wanted if "-pole-light-car-park-" in p["placementId"]),
               "yardLights": sorted(p["placementId"] for p, _ in wanted if "-pole-light-yard-" in p["placementId"]),
               "dockLights": sorted(p["placementId"] for p, _ in wanted if p["assetId"] == models.WALL_LIGHT),
               "placed": placed, "unchanged": unchanged, "removed": stale, "operations": len(ops)}
    return ops, summary


def audit(before, after, ops):
    """Only the light rows' finishes, the pass's own placements and updatedAt may differ."""
    own = {op["placement"]["placementId"] for op in ops if op["op"] == "place_asset"}
    own |= {op["placementId"] for op in ops if op["op"] == "delete_placement"}
    rows = {op["placementId"] for op in ops if op["op"] == "set_component_materials"} - own
    old = {p["placementId"]: p for p in before["placements"]}
    new = {p["placementId"]: p for p in after["placements"]}
    for placement_id, placement in old.items():
        if placement_id in own:
            continue
        if placement_id in rows:
            strip = lambda p: {k: v for k, v in p.items() if k != "componentMaterials"}
            if strip(new[placement_id]) != strip(placement):
                raise AssertionError(f"{placement_id} changed beyond its lens finish.")
        elif new.get(placement_id) != placement:
            raise AssertionError(f"{placement_id} changed.")
    if set(new) - set(old) - own:
        raise AssertionError("Unexpected new placements.")
    rest = lambda doc: {k: v for k, v in doc.items() if k not in ("placements", "updatedAt")}
    if rest(before) != rest(after):
        raise AssertionError("Layout content other than placements changed.")
    return {"placementsBefore": len(old), "placementsAfter": len(new), "rowsFinished": len(rows),
            "otherContentUnchanged": True}


def _diagnose(host, doc):
    principal = host.principal()
    host.service.validate_dependencies(principal, SITE, doc)
    return {"spatial": host.service._diagnose_spatial(principal, SITE, doc),
            "routing": host.service._diagnose_routing(principal, SITE, doc)}


def compare_findings(before, after, own):
    """Errors and warnings must stay exactly as they were. Notes may change only about the pass's placements: a note
    added or removed must name one of them, and a note that names many placements at once may only gain or lose
    the pass's own (the spatial check gives one such note for all placements when it has no policy set)."""
    key = lambda f: (f.get("severity"), f.get("code"), tuple(sorted(str(s) for s in f.get("subjectRefs") or [])))
    result, problems = {}, []
    for name in ("spatial", "routing"):
        old = Counter(key(f) for f in before[name].get("findings", []))
        new = Counter(key(f) for f in after[name].get("findings", []))
        added, removed = new - old, old - new
        for gone in sorted(removed.elements()):
            if gone[0] not in ("unverified", "info"):
                continue
            twin = next((k for k in sorted(added) if added[k] > 0 and k[:2] == gone[:2]
                         and set(k[2]) - own == set(gone[2]) - own), None)
            if twin is not None:
                added[twin] -= 1
                removed[gone] -= 1
        added, removed = +added, +removed
        hard = [k for k in (added + removed) if k[0] not in ("unverified", "info")]
        stray = [k for k in (added + removed) if not set(k[2]) & own]
        result[name] = {
            "before": dict(Counter(k[0] for k in old.elements())), "after": dict(Counter(k[0] for k in new.elements())),
            "addedNotes": dict(Counter(k[1] for k in added.elements())),
            "removedNotes": dict(Counter(k[1] for k in removed.elements())),
            "errorsAndWarningsUnchanged": not hard, "onlyAboutOwnPlacements": not stray}
        if hard:
            problems.append(f"{name}: errors or warnings changed: {hard[:5]}")
        if stray:
            problems.append(f"{name}: findings about other placements changed: {stray[:5]}")
    return result, problems


def _write(path, value):
    Path(path).write_bytes(json.dumps(value, indent=2, sort_keys=True).encode("utf-8"))


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def run(store, root=ROOT, output=None, save=False):
    store, root = Path(store).resolve(), Path(root).resolve()
    output = Path(output or root / ".runtime" / "light-factory02" / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"))
    output.mkdir(parents=True, exist_ok=False)
    report = {"layoutId": LAYOUT_ID, "store": str(store), "root": str(root), "status": "started"}
    report["assets"] = models.install(root)
    target = store / LAYOUTS / (LAYOUT_ID + ".json")
    before_bytes = target.read_bytes()
    before = json.loads(before_bytes)
    report.update(baseRevision=layout_revision(before), baseSha256=_sha256(before_bytes))
    stage = output / "staged-store"
    copytree(_native_fs_path(store / "authorities"), _native_fs_path(stage / "authorities"))
    (stage / LAYOUTS).mkdir(parents=True)
    for name in ("registry.json", LAYOUT_ID + ".json"):
        copy2(store / LAYOUTS / name, stage / LAYOUTS / name)
    host = LocalFacilityLayoutHost(stage, private_assets=True, private_asset_root=root)
    try:
        catalog = {asset["assetId"]: asset for asset in host.authoritative_asset_catalog()}
        report["assetRevisions"] = {a: catalog[a]["assetDefinitionRevision"] for a in sorted(OWN_ASSETS)}
        operations, report["plan"] = light_operations(before, catalog)
        _write(output / "operations.json", operations)
        if not operations:
            report["status"] = "already-applied"
            _write(output / "report.json", report)
            return report
        candidate = apply_facility_layout_operations(
            before, operations, updated_at=datetime.now(timezone.utc).isoformat())["document"]
        report["audit"] = audit(before, candidate, operations)
        own = {op["placement"]["placementId"] for op in operations if op["op"] == "place_asset"} | set(report["plan"]["removed"])
        report["findings"], problems = compare_findings(_diagnose(host, before), _diagnose(host, candidate), own)
        if problems:
            report.update(status="refused", problems=problems)
            _write(output / "report.json", report)
            raise SystemExit("Not saved: " + "; ".join(problems))
        staged = host.service.save_layout(host.principal(), SITE, LAYOUT_ID, candidate, report["baseRevision"])
        report.update(status="validated", candidateRevision=staged["revision"])
        _write(output / "candidate.json", staged["layout"])
        if save:
            if _sha256(target.read_bytes()) != report["baseSha256"]:
                report["status"] = "stale"
                _write(output / "report.json", report)
                raise SystemExit("Factory 02 changed after it was checked; nothing saved. Run the pass again.")
            live = LocalFacilityLayoutHost(store, private_assets=True, private_asset_root=root)
            try:
                saved = live.service.save_layout(live.principal(), SITE, LAYOUT_ID, candidate, report["baseRevision"])
            finally:
                live.close()
            left, _ = light_operations(json.loads(target.read_bytes()), catalog)
            report.update(status="saved", savedRevision=saved["revision"], nothingLeftToDo=not left)
    except FacilityLayoutError as exc:
        report.update(status="refused", problems=[f"{exc.code}: {exc}"], details=getattr(exc, "details", None))
        _write(output / "report.json", report)
        raise SystemExit(f"Not saved: {exc.code}: {exc}")
    finally:
        host.close()
    _write(output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", type=Path, required=True, help="the facility-layout store holding Factory 02")
    parser.add_argument("--root", type=Path, default=ROOT, help="project root holding generated/ (default: this one)")
    parser.add_argument("--output", type=Path, help="new folder for the report (default: ROOT/.runtime/light-factory02/...)")
    parser.add_argument("--save", action="store_true", help="save the checked result to STORE")
    args = parser.parse_args()
    report = run(args.store, args.root, args.output, args.save)
    plan = report.get("plan", {})
    print(json.dumps({"status": report["status"], "baseRevision": report["baseRevision"],
                      "candidateRevision": report.get("candidateRevision"), "savedRevision": report.get("savedRevision"),
                      "operations": plan.get("operations"), "placed": len(plan.get("placed", [])),
                      "rowsSet": plan.get("lightRowsSet"), "findings": report.get("findings")}, indent=1))


if __name__ == "__main__":
    main()
