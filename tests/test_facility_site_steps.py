"""The warehouse built step by step (docs/facility-site-step-build-plan.md, approved 2026-10-24)."""
import asyncio
from copy import deepcopy
import math

import pytest

from ai_inspector.facility_layout import site_steps
from ai_inspector.facility_layout.site_context import KEY
from ai_inspector.facility_layout.site_interior import FORKLIFT_ASSET, RACK_ASSET
from ai_inspector.facility_layout.site_parking import CAR_ASSETS
from ai_inspector.facility_layout.site_steps import StepError
from ai_inspector.facility_layout.site_trucks import TRUCK_ASSET
from tests.test_facility_site_plan import ARTERIAL, RAIL, STREET, site_doc, staged, warnings

# The planner tests' lot: 140 x 100 m, Mill St along the south edge (the street edge), State Hwy 95 just east,
# a railway just west. The traced pavement covers it with a 4 m margin.
OUTLINE = [{"x": 4, "z": 4}, {"x": 136, "z": 4}, {"x": 136, "z": 96}, {"x": 4, "z": 96}]
BUILDING = {"lengthMeters": 70, "widthMeters": 40, "alignWith": "Mill St", "dockWall": "east", "fromStreetMeters": 20}
ARGS = {"building": BUILDING, "zones": {"dockWall": "east"}, "markings": {"dockWall": "east", "stagingLanes": 7},
        "layout": {"dockWall": "east"}, "docks": {"doors": 7, "entranceStreet": "State Hwy 95", "truckCourtDepthMeters": 30},
        "parking": {"stalls": 20, "side": "west", "entranceStreet": "Mill St"}}


def record(asset, x, z, y=2.0):
    return {"assetId": asset, "assetDefinitionRevision": "c" * 64, "definition": {"geometry": {"aabb": {
        "minimum": {"x": -x, "y": 0, "z": -z}, "maximum": {"x": x, "y": y, "z": z}}}}}


CATALOG = {TRUCK_ASSET: record(TRUCK_ASSET, 1.275, 7.937, 3.79), RACK_ASSET: record(RACK_ASSET, 0.6135, 1.264, 5.0),
           FORKLIFT_ASSET: record(FORKLIFT_ASSET, 0.565, 0.98), CAR_ASSETS[0]: record(CAR_ASSETS[0], 1.0, 2.9)}


def lot(setbacks=6):
    doc, site = site_doc(STREET, ARTERIAL, RAIL, setbacks=setbacks)
    site["areas"] = [{"areaId": "area-existing-pavement", "label": "Existing pavement (test photo)",
                      "kind": "existing_pavement", "surface": "asphalt", "boundary": deepcopy(OUTLINE)}]
    doc["extensions"][KEY] = site
    return doc


def step(doc, name, args, catalog=CATALOG):
    if name == "layout":
        result = site_steps.plan_layout(doc, args, catalog)
    elif name == "contents":
        result = site_steps.plan_contents(doc, args, catalog)
    else:
        result = site_steps.PLANNERS[name](doc, args)
    return staged(doc, result["operations"]), result


def built(*names):
    doc = lot()
    for name in names:
        doc, _ = step(doc, name, ARGS[name])
    return doc


def prefixed(rows, key, prefix):
    return [row for row in rows if str(row.get(key, "")).startswith(prefix)]


def walls(doc):
    return doc["extensions"]["facilityPerimeterWalls"]["settings"]


def test_the_building_is_the_users_size_along_the_named_street_its_distance_back_and_plain():
    doc, result = step(lot(), "building", BUILDING)
    plan = doc["extensions"]["facilityPlan"]
    assert (plan["widthMeters"], plan["depthMeters"]) == (70, 40)
    pose = doc["extensions"][KEY]["buildingPose"]
    # Long side along Mill St (east-west), centred along it on the traced lot, its south wall 20 m from the lot line.
    assert (pose["x"], pose["z"], pose["bearingDegrees"]) == pytest.approx((35.0, 20.0, 0.0))
    assert "exteriorFinish" not in walls(doc) and walls(doc)["openings"] == [] and walls(doc)["heightMeters"] == 10
    summary = result["summary"]
    assert summary["building"]["fromStreet"] == {"street": "Mill St", "meters": 20.0, "measuredFrom": "its lot line"}
    assert summary["building"]["clearanceToLotEdgesMeters"] == {"south": 20.0, "north": 40.0, "west": 35.0, "east": 35.0}
    assert summary["dockWall"]["roomBeyondItMeters"] == 35.0 and summary["dockWall"]["maxDoors"] == 7
    ground = doc["extensions"]["facilityGround"]
    assert {tile["surfaceId"].split("-")[1] for tile in ground["surfaces"]} == {"slab", "yard"} and "marks" not in ground
    assert not warnings(doc)


def test_a_county_parcel_with_no_street_edges_still_measures_back_from_the_street_lot_line():
    """A county parcel marks no street edges; "60 m back from the street" still means from its lot line, the
    property edge along the street, not the street's centre line 8 m beyond it."""
    doc = lot()
    doc["extensions"][KEY]["property"]["streetEdges"] = []
    summary = site_steps.plan_building(doc, BUILDING)["summary"]
    assert summary["building"]["fromStreet"] == {"street": "Mill St", "meters": 20.0, "measuredFrom": "its lot line"}
    assert summary["building"]["clearanceToLotEdgesMeters"]["south"] == 20.0


def test_a_building_that_breaks_the_setbacks_or_names_no_street_is_refused_with_why():
    with pytest.raises(StepError, match="It fits 4 m to the north"):  # 2 m from a lot line with a 6 m street setback
        site_steps.plan_building(lot(), {**BUILDING, "fromStreetMeters": 2})
    with pytest.raises(StepError, match="largest building that fits is about"):
        site_steps.plan_building(lot(), {"lengthMeters": 200, "widthMeters": 150, "alignWith": "Mill St"})
    with pytest.raises(StepError, match="No mapped street is called Elm St"):
        site_steps.plan_building(lot(), {**BUILDING, "alignWith": "Elm St"})


def test_zones_put_receiving_and_shipping_along_the_dock_wall_storage_behind_and_charging_at_the_back():
    doc, result = step(built("building"), "zones", {"dockWall": "east", "stagingDepthMeters": 12,
                                                    "chargingLengthMeters": 16, "chargingDepthMeters": 5})
    zones = {zone["zoneId"]: zone for zone in doc["zones"]}
    assert set(zones) == {"zn-receiving", "zn-shipping", "zn-storage", "zn-forklift-charging"}
    xs = lambda zone_id: sorted({p["x"] for p in zones[zone_id]["boundary"]})  # noqa: E731
    assert xs("zn-receiving") == xs("zn-shipping") == [58.0, 70.0]  # 12 m in from the east wall
    assert xs("zn-forklift-charging") == [0.0, 5.0]  # along the back (west) wall
    assert result["summary"]["areasSquareMeters"] == {"receiving": 240.0, "shipping": 240.0,
                                                      "storage": 70 * 40 - 2 * 240 - 80, "charging": 80.0}
    assert site_steps.plan_markings(doc, {})["summary"]["dockWall"] == "east"  # found again from the receiving zone
    with pytest.raises(StepError, match="The docks are on the east wall"):  # a different wall is refused
        site_steps.plan_markings(doc, {"dockWall": "west"})


def test_staging_lanes_and_dock_doors_use_the_same_slots():
    doc, marked = step(built("building", "zones"), "markings", {"dockWall": "east", "stagingLanes": 7})
    assert len(prefixed(doc["floorMarkings"], "markingId", "fm-interior-door-")) == 7
    assert marked["summary"]["laneCentresMeters"] == [7.1, 11.4, 15.7, 20.0, 24.3, 28.6, 32.9]
    doc, docked = step(doc, "docks", {"truckCourtDepthMeters": 30})  # doors default to the lanes, the wall to the zones
    centres = sorted(round((o["startMeters"] + o["endMeters"]) / 2, 2) for o in walls(doc)["openings"] if o["edge"] == 1)
    assert centres == marked["summary"]["laneCentresMeters"] and docked["summary"]["doorsLinedUpWithStagingLanes"]
    assert {o["heightMeters"] for o in walls(doc)["openings"] if o["edge"] == 1} == {3.05}  # door-high: wall above
    with pytest.raises(StepError, match="takes at most 7 doors"):
        site_steps.door_slots(40, 9)


def test_the_layout_outlines_rack_rows_and_aisles_without_any_models():
    doc = built("building", "zones", "markings")
    across, result = step(doc, "layout", {"dockWall": "east"})
    rows = prefixed(across["floorMarkings"], "markingId", "fm-interior-row-")
    assert rows and result["summary"]["rackRows"] == len(rows) and not across.get("placements")
    assert {"rt-interior-cross-aisle", "rt-interior-back-aisle"} <= {r["routeId"] for r in across["routes"]}
    # The aisles keep the width asked for: the PDF labels it (live 2026-10-24 it printed 3.6 m for a 3.7 m ask).
    wide, _ = step(doc, "layout", {"dockWall": "east", "aisleWidthMeters": 3.7})
    assert {r["corridorWidth"] for r in prefixed(wide["routes"], "routeId", "rt-interior-")} == {3.7}
    assert {round(m["transform"]["rotationDegrees"]) % 360 for m in rows} == {270}  # inward from the east wall
    along, _ = step(doc, "layout", {"dockWall": "east", "rowDirection": "along"})
    assert {round(m["transform"]["rotationDegrees"]) % 360 for m in
            prefixed(along["floorMarkings"], "markingId", "fm-interior-row-")} == {0}  # along the east wall
    again, _ = step(across, "layout", {"dockWall": "east"})  # running it again replaces its rows
    assert len(prefixed(again["floorMarkings"], "markingId", "fm-interior-row-")) == len(rows)


def test_a_truck_court_that_does_not_fit_is_refused_with_the_room_there():
    with pytest.raises(StepError, match="allows 35 m"):
        site_steps.plan_docks(built("building", "zones"), {"truckCourtDepthMeters": 40})


def test_the_car_park_has_its_own_entrance_and_keeps_clear_of_the_trucks():
    doc = built("building", "zones", "markings", "docks")
    doc, result = step(doc, "parking", ARGS["parking"])
    summary = result["summary"]
    assert summary["stallsPlaced"] == 20 and summary["carEntranceFromTruckEntranceMeters"] >= 40
    assert summary["clearOfTrucksMeters"] >= 10
    # Its own two-way aisle runs straight on to Mill St, and the dashed centre line with it (the user, 2026-10-24).
    assert summary["carDrive"]["fromAisle"] and summary["carDrive"]["road"] == "Mill St"
    aisle_line = next(m for m in doc["floorMarkings"] if m["markingId"] == "fm-car-park-aisle-center")
    [drive_line] = [m for m in doc["floorMarkings"] if m["markingId"].startswith("fm-car-park-drive-center-")]
    assert drive_line["markingType"] == "dashed_line" and drive_line["transform"]["rotationDegrees"] ==         aisle_line["transform"]["rotationDegrees"]
    assert abs(drive_line["transform"]["position"]["x"] - aisle_line["transform"]["position"]["x"]) < 0.05
    entrances = {e["entranceId"]: (e["x"], e["z"]) for e in doc["extensions"][KEY]["property"]["entrances"]}
    assert set(entrances) == {"entrance-truck", "entrance-cars"}
    assert math.dist(entrances["entrance-truck"], entrances["entrance-cars"]) >= 40  # measured, not the rounded summary
    openings = walls(doc)["openings"]
    assert sum(1 for o in openings if o["edge"] == 1) == 7  # the dock doors stay
    assert any(o["edge"] == 3 and round(o["endMeters"] - o["startMeters"], 2) == 1.8 and o["heightMeters"] == 2.4
               for o in openings)  # the employee door
    assert not warnings(doc)


def test_a_car_park_with_room_only_in_the_trucks_way_is_refused():
    # A 70 m deep building: its east court and the drive to State Hwy 95 take the whole east side.
    doc, _ = step(lot(), "building", {**BUILDING, "widthMeters": 70})
    doc, _ = step(doc, "docks", {"dockWall": "east", "truckCourtDepthMeters": 30, "entranceStreet": "State Hwy 95"})
    with pytest.raises(StepError, match="No car park for 20 stalls fits east of the building: .*truck court and drive"):
        site_steps.plan_parking(doc, {"stalls": 20, "side": "east"})
    assert site_steps.plan_parking(doc, {"stalls": 20, "side": "west"})["summary"]["clearOfTrucksMeters"] >= 10


def test_contents_fill_the_outlined_rows_and_park_forklifts_trucks_and_cars_unpainted():
    doc = lot()
    for name in ("building", "zones", "markings"):
        doc, _ = step(doc, name, ARGS[name])
    doc, laid = step(doc, "layout", ARGS["layout"])
    for name in ("docks", "parking"):
        doc, _ = step(doc, name, ARGS[name])
    rows = prefixed(doc["floorMarkings"], "markingId", "fm-interior-row-")
    doc, result = step(doc, "contents", {"forklifts": 3, "trucks": 4, "cars": 12})
    assert result["summary"]["rackBays"] == laid["summary"]["rackBays"]  # every outlined bay is filled
    filled = prefixed(doc["floorMarkings"], "markingId", "fm-interior-row-")
    assert len(filled) == len(rows) and all(m["opacity"] == 0 for m in filled)  # no yellow floor under the racks
    summary = result["summary"]
    assert (summary["rackRows"], summary["forklifts"], summary["trucks"], summary["cars"]) == (len(rows), 3, 4, 12)
    placements = doc["placements"]
    assert all("componentMaterials" not in p for p in placements)
    trucks = [p for p in placements if p["assetId"] == TRUCK_ASSET]
    assert all(p["transform"]["position"]["x"] == pytest.approx(70 + 0.25 + 7.937, abs=1e-3) for p in trucks)
    bay = next(z for z in doc["zones"] if z["zoneId"] == "zn-forklift-charging")
    forklifts = [p["transform"]["position"] for p in placements if p["assetId"] == FORKLIFT_ASSET]
    assert all(min(q["x"] for q in bay["boundary"]) < f["x"] < max(q["x"] for q in bay["boundary"]) and
               min(q["z"] for q in bay["boundary"]) < f["z"] < max(q["z"] for q in bay["boundary"]) for f in forklifts)
    # A dock door with no truck at it is closed: a door panel just inside the opening.
    closed = [w for w in doc["extensions"]["facilityInteriorWalls"]["walls"] if w["wallId"].startswith("iw-dock-door-")]
    assert summary["closedDoors"] == len(closed) == 7 - 4
    assert all(w["heightMeters"] == 3.05 and w["start"]["x"] == w["end"]["x"] == 69.9 for w in closed)
    truck_z = {round(p["transform"]["position"]["z"], 2) for p in trucks}
    assert not truck_z & {round((w["start"]["z"] + w["end"]["z"]) / 2, 2) for w in closed}
    again, _ = step(doc, "contents", {"forklifts": 2})  # running it again replaces the contents
    assert sum(1 for p in again["placements"] if p["assetId"] == FORKLIFT_ASSET) == 2
    assert not any(p["assetId"] in (TRUCK_ASSET, CAR_ASSETS[0]) for p in again["placements"])
    assert len([w for w in again["extensions"]["facilityInteriorWalls"]["walls"]
                if w["wallId"].startswith("iw-dock-door-")]) == 7  # no trucks: every door closed


def test_paint_gives_the_plain_walls_their_finish_and_logo_and_the_yard_its_target(monkeypatch):
    from pathlib import Path
    from ai_inspector.facility_layout.site_paint import plan_paint
    doc = built("building", "zones", "markings", "docks")
    with monkeypatch.context() as patched:
        patched.setattr(Path, "is_file", lambda self: True)  # the app has the logo and target images
        result = plan_paint(doc, None, {"walls": {"color": "cyan", "bandColor": "white", "logoWalls": ["beside_docks"]}, "pavementLogo": True})
    patch = next(op for op in result["operations"] if op["op"] == "edit_perimeter_walls")["patch"]
    finish = patch["exteriorFinish"]
    assert finish["color"] == "#06b6d4" and finish["bands"][0]["color"] == "#ffffff"
    assert {logo["edge"] for logo in finish["artworks"]} == {0, 2}  # the walls beside the east docks
    painted = staged(doc, result["operations"])
    assert walls(painted)["openings"] == walls(doc)["openings"]  # the doors stay
    assert walls(painted)["exteriorFinish"]["color"] == "#06b6d4"
    assert [mark["markId"] for mark in painted["extensions"]["facilityGround"]["marks"]] == ["gm-target"]
    # In the truck yard, as asked: on the court's asphalt past the apron the trucks stand on, half way along the
    # dock wall (the user, 2026-10-24: the logo had gone to the open paving behind the building).
    mark = painted["extensions"]["facilityGround"]["marks"][0]
    court = next(z for z in doc["zones"] if z["zoneId"] == "zn-truck-court")
    far = max(p["x"] for p in court["boundary"])
    assert 70 + 18.3 + mark["widthMeters"] / 2 <= mark["x"] <= far - mark["widthMeters"] / 2
    assert mark["z"] == pytest.approx(sum(p["z"] for p in court["boundary"]) / 4)
    with monkeypatch.context() as patched:
        patched.setattr(Path, "is_file", lambda self: True)
        assert plan_paint(painted, None, {"walls": {"color": "cyan", "bandColor": "white", "logoWalls": ["beside_docks"]}, "pavementLogo": True})["available"] is False  # nothing left to paint


def test_building_again_clears_every_later_step():
    doc = built("building", "zones", "markings", "layout", "docks", "parking")
    doc, result = step(doc, "building", {**BUILDING, "lengthMeters": 60})
    assert not doc["zones"] and not prefixed(doc["floorMarkings"], "markingId", ("fm-interior-", "fm-truck-court-", "fm-car-park-"))
    assert not prefixed(doc["routes"], "routeId", ("rt-interior-", "rt-car-park-"))
    assert {a["areaId"] for a in doc["extensions"][KEY]["areas"]} == {"area-existing-pavement"}
    assert not doc["extensions"][KEY]["property"].get("entrances") and walls(doc)["openings"] == []
    assert doc["extensions"]["facilityPlan"]["widthMeters"] == 60


def test_each_step_adds_its_layer_and_leaves_the_earlier_ones_alone():
    doc = built("building", "zones", "markings", "layout")
    zones, markings, routes = deepcopy(doc["zones"]), deepcopy(doc["floorMarkings"]), deepcopy(doc["routes"])
    doc, _ = step(doc, "docks", ARGS["docks"])
    assert all(zone in doc["zones"] for zone in zones) and all(m in doc["floorMarkings"] for m in markings)
    assert all(route in doc["routes"] for route in routes)
    aprons = prefixed(doc["extensions"]["facilityGround"]["surfaces"], "surfaceId", "gr-apron-")
    court = next(a for a in doc["extensions"][KEY]["areas"] if a["areaId"] == "area-truck-court")
    doc, _ = step(doc, "parking", ARGS["parking"])
    assert prefixed(doc["extensions"]["facilityGround"]["surfaces"], "surfaceId", "gr-apron-") == aprons
    assert court in doc["extensions"][KEY]["areas"] and all(zone in doc["zones"] for zone in zones)


def test_the_whole_build_runs_as_one_review_per_step_on_a_saved_layout(tmp_path):
    """Sage's path: each step's package staged as one review, approved and saved, then the next step."""
    from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway
    from ai_inspector.facility_layout.host import LOCAL_LAYOUT_ID, LOCAL_SITE_ID, LocalFacilityLayoutHost
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=False)
    host.ensure_bootstrap()
    principal = host.principal()
    try:
        saved = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
        layout = deepcopy(saved["layout"])
        layout.setdefault("extensions", {})[KEY] = lot()["extensions"][KEY]
        saved = host.layout_repository.save_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, layout, saved["revision"])
        steps = [("plan_warehouse_building", BUILDING), ("plan_warehouse_zones", ARGS["zones"]),
                 ("plan_floor_markings", ARGS["markings"]), ("plan_storage_layout", {**ARGS["layout"], "aisleWidthMeters": 3.7}),
                 ("plan_site_docks", ARGS["docks"]), ("plan_site_parking", ARGS["parking"]),
                 ("plan_warehouse_contents", {"forklifts": 3}), ("plan_design_paint", {"walls": {"color": "cyan", "bandColor": "white", "logoWalls": ["beside_docks"]},
                                       "pavementLogo": True})]
        for number, (tool, args) in enumerate(steps):
            gateway = FacilityEditGateway(host.agent_runtime, principal, {
                "siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": saved["revision"]}, turn_id=f"step-{number}")
            read = gateway._read_data(tool, args)
            staged_result = asyncio.run(gateway.call("preview_planned_design", {"packageId": read["package"]["packageId"]}))
            assert staged_result["ok"], (tool, staged_result)
            proposal_id = gateway.proposal["proposalId"]
            preview = host.service.get_layout_proposal_preview(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, proposal_id)
            if tool == "plan_warehouse_contents":  # the racks stand clear of aisles kept at the asked 3.7 m (live 2026-10-24
                # the full width touched the rack faces: 108 obstructions, and the step opened a review)
                assert "aisleObstructions" not in (preview["alternative"].get("validation") or {})
                assert preview["alternative"]["directApplyPolicy"]["eligible"] is True
            binding = preview["alternative"]["transactionBinding"]
            approval = host.service.approve_layout_proposal(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, proposal_id, binding,
                                                            session_id="test-approver", idempotency_key=f"build-step-{number:02}",
                                                            explicit_approval=True)
            host.service.apply_layout_proposal(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, approval["approvalToken"],
                                               binding, session_id="test-approver", idempotency_key=f"build-step-{number:02}")
            saved = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
        final = saved["layout"]
        # Sage prepares the printable sheets from the saved layout; the reply carries them as a file card.
        from ai_inspector.chat_content import normalize_chat_content_blocks
        reader = FacilityEditGateway(host.agent_runtime, principal, {
            "siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": saved["revision"]}, turn_id="pdf")
        made = reader._read_data("prepare_layout_pdf", {})
        assert made["pages"] == 3 and made["sheets"] == ["C-101 site plan", "C-102 setting-out plan", "A-101 floor plan"]
        [card] = normalize_chat_content_blocks([reader.pdf])
        assert card["type"] == "file" and card["mimeType"] == "application/pdf" and card["fileName"].endswith(".pdf")
        assert card["url"].startswith(f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/plan.pdf?revision=")
        assert {z["zoneId"] for z in final["zones"]} >= {"zn-receiving", "zn-shipping", "zn-storage", "zn-forklift-charging",
                                                        "zn-truck-court", "zn-employee-parking"}
        assert sum(1 for p in final["placements"] if p["assetId"] == RACK_ASSET) > 100
        assert sum(1 for p in final["placements"] if p["assetId"] == FORKLIFT_ASSET) == 3
        assert walls(final)["exteriorFinish"]["color"] == "#06b6d4"
    finally:
        host.close()


def test_a_wall_opening_may_be_door_high_with_the_wall_closed_above_it():
    from ai_inspector.facility_layout.perimeter_walls import compile_perimeter_walls
    layout = {"extensions": {"facilityPlan": {"widthMeters": 20, "depthMeters": 10, "gridSpacingMeters": 1,
                                              "majorGridSpacingMeters": 5}}}
    door = {"edge": 0, "startMeters": 4, "endMeters": 7, "heightMeters": 3.05}
    settings = {"boundarySource": "plan", "heightMeters": 10, "thicknessMeters": 0.3, "openings": [door]}
    compiled = compile_perimeter_walls(settings, layout)
    assert compiled["settings"]["openings"] == [{"edge": 0, "startMeters": 4.0, "endMeters": 7.0, "heightMeters": 3.05}]
    with pytest.raises(ValueError, match="Opening height"):  # a door must be lower than its wall
        compile_perimeter_walls({**settings, "openings": [{**door, "heightMeters": 10}]}, layout)


def test_the_car_park_stays_inside_a_property_line_off_the_metre_grid():
    # Live at Bayport (2026-10-24) the car park crossed the street line by 0.27 m: a metre cell of its search
    # counted when only its centre was inside. Here the north line is 0.3 m off that grid and the car park,
    # asked for more stalls than fit, fills its side up to the line.
    doc = lot(setbacks=0)
    for point in doc["extensions"][KEY]["property"]["boundary"]:
        if point["z"] == 100:
            point["z"] = 99.7
    for name in ("building", "zones", "docks"):
        doc, _ = step(doc, name, ARGS[name])
    doc, result = step(doc, "parking", {**ARGS["parking"], "stalls": 400})
    park = next(a for a in doc["extensions"][KEY]["areas"] if a["areaId"] == "area-employee-parking")
    assert result["summary"]["stallsPlaced"] > 20 and max(p["z"] for p in park["boundary"]) > 98.5
    assert not warnings(doc)


def test_walls_are_painted_only_as_asked_logo_and_band_included():
    from ai_inspector.facility_layout.site_paint import plan_paint
    doc = built("building", "zones", "markings", "docks")
    plain = plan_paint(doc, None, {"walls": {"color": "light grey"}})
    [walls_op] = plain["operations"]
    finish = walls_op["patch"]["exteriorFinish"]
    assert finish["color"] == "#b9bdc1" and finish["bands"] == [] and finish["artworks"] == []
    assert plain["look"] == {"walls": "light grey panels"}  # no band, no logo, no yard mark: none was asked for
    north = plan_paint(doc, None, {"walls": {"color": "cyan", "bandColor": "white", "logoWalls": ["north"]}})
    finish = north["operations"][0]["patch"]["exteriorFinish"]
    assert finish["bands"][0]["color"] == "#ffffff" and [a["edge"] for a in finish["artworks"]] == [2]
    beside = plan_paint(doc, None, {"walls": {"color": "cyan", "logoWalls": ["beside_docks"]}})
    assert sorted(a["edge"] for a in beside["operations"][0]["patch"]["exteriorFinish"]["artworks"]) == [0, 2]


def test_apply_directly_takes_a_planner_package_whole_and_reference_points_as_a_routine_batch():
    from ai_inspector.facility_layout.direct_edit_policy import evaluate
    building = [{"op": op} for op in ("set_plan_settings", "set_building_pose", "set_perimeter_walls", "set_ground")]
    prepared = {"affectedIds": [f"id-{n}" for n in range(300)], "createdIds": []}
    assert evaluate(building, prepared)["eligible"] is False  # Sage's own batch of these needs a review
    assert evaluate(building, prepared, planned=True)["eligible"] is True  # the planner's package applies whole
    assert evaluate([{"op": "set_site_context"}, {"op": "rename_facility_shell"}], prepared, planned=True)["eligible"] is False
    assert evaluate([{"op": "add_zone"}] * 1001, prepared, planned=True)["eligible"] is False
    references = [{"op": "upsert_site_reference"}] * 4
    assert evaluate(references, {"affectedIds": [], "createdIds": ["rp-1", "rp-2", "rp-3", "rp-4"]})["eligible"] is True
    traced = {"op": "upsert_site_area", "area": {"areaId": "area-lot", "kind": "existing_pavement"}}
    assert evaluate([traced], {"affectedIds": [], "createdIds": ["area-lot"]})["eligible"] is True  # the measured lot
    court = {"op": "upsert_site_area", "area": {"areaId": "area-court", "kind": "truck_court"}}
    assert evaluate([court], {"affectedIds": [], "createdIds": ["area-court"]})["eligible"] is False  # a design needs review


def test_a_finding_the_saved_layout_already_has_does_not_hold_back_a_direct_edit(tmp_path):
    # Bayport (2026-10-24): placed by its street address, a new layout's placeholder building sat off the lot,
    # and the measured lot opened a review instead of applying directly.
    from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway
    from ai_inspector.facility_layout.host import LOCAL_LAYOUT_ID, LOCAL_SITE_ID, LocalFacilityLayoutHost
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=False)
    host.ensure_bootstrap()
    principal = host.principal()
    try:
        saved = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
        layout = deepcopy(saved["layout"])
        site = lot()["extensions"][KEY]
        site["areas"] = []
        site["buildingPose"] = {"x": 900.0, "z": 900.0, "bearingDegrees": 0.0}  # far off the lot
        layout.setdefault("extensions", {})[KEY] = site
        saved = host.layout_repository.save_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, layout, saved["revision"])
        gateway = FacilityEditGateway(host.agent_runtime, principal, {
            "siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": saved["revision"]}, turn_id="trace")
        gateway.edit_mode = "direct"
        result = asyncio.run(gateway.call("preview_facility_operations", {"operations": [{"op": "upsert_site_area", "area": {
            "areaId": "area-lot", "label": "Parking lot (test photo)", "kind": "existing_pavement", "surface": "asphalt",
            "boundary": deepcopy(OUTLINE)}}]}))
        data = result.get("data", result)
        assert result["ok"], result
        assert "site_building_outside_property" in [f["code"] for f in data["validation"]["siteContext"]["findings"]]
        assert data["validation"]["siteContext"]["newWarnings"] == []
        assert data["directApplyPolicy"]["eligible"] is True and data["approvalRequired"] is False
    finally:
        host.close()


def test_a_keep_away_circle_holds_the_whole_distance_all_round():
    from shapely.geometry import Point
    from ai_inspector.facility_layout.site_access import circle_around
    circle = circle_around(Point(3.0, -7.0), 40.0)
    ring = circle.exterior
    samples = [ring.interpolate(i / 2000, normalized=True) for i in range(2000)]  # the vertices and the edges between
    assert min(Point(3.0, -7.0).distance(q) for q in samples) >= 40.0 - 1e-9
    assert max(Point(3.0, -7.0).distance(q) for q in samples) < 40.05  # and not much more


def test_the_car_park_is_the_same_wherever_the_site_point_falls():
    """The search grid steps from the building's corner, not the site point (the geocoded address)."""
    from tests.site_cases import moved
    def car_park(doc):
        for name in ("building", "zones", "markings", "docks", "parking"):
            doc, _ = step(doc, name, ARGS[name])
        return sorted((m["markingId"], round(m["transform"]["position"]["x"], 4), round(m["transform"]["position"]["z"], 4),
                       m["width"], m["depth"]) for m in doc["floorMarkings"] if m["markingId"].startswith("fm-car-park-"))
    here = lot()
    there = deepcopy(here)
    there["extensions"][KEY] = moved(here["extensions"][KEY], 0.37, 0.61)
    assert car_park(here) == car_park(there)
