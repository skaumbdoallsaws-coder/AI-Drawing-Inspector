"""A warehouse concept on a traced outline (find-and-build plan, step B)."""
from copy import deepcopy
import math

import pytest

from ai_inspector.facility_layout.geo import from_property, geographic_box
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.facility_layout.site_context import KEY, analyze_site_context, normalize_site_context
from ai_inspector.facility_layout.site_plan import plan_warehouse
from tests.test_facility_site_property import fixture

LOT = [{"x": 0, "z": 0}, {"x": 140, "z": 0}, {"x": 140, "z": 100}, {"x": 0, "z": 100}]


def lonlat(x, z):
    latitude, longitude, _ = from_property(x, z, 45.0, -93.0)
    return [longitude, latitude]


def road(road_id, mtfcc, name, *points):
    return {"roadId": road_id, "names": [name] if name else [], "mtfcc": mtfcc, "lonLat": [lonlat(x, z) for x, z in points]}


def staged(doc, operations):
    """Apply a plan as Sage's proposal does: the stored roads ride along with its site edit."""
    operations = deepcopy(operations)
    stored = doc["extensions"].get(KEY, {})
    for op in operations:
        if op["op"] == "set_site_context":
            for field in ("overlays", "layerChecks", "roads"):
                if field in stored and field not in op["siteContext"]:
                    op["siteContext"][field] = stored[field]
    return apply_facility_layout_operations(deepcopy(doc), operations)["document"]


def warnings(document):
    return [f for f in analyze_site_context(document)["findings"] if f["severity"] != "info"]


def site_doc(*roads, setbacks=0):
    doc = fixture()
    context = doc["extensions"][KEY]
    context["property"] = {"boundary": deepcopy(LOT), "setbacksMeters": {"street": setbacks, "side": 0, "rear": 0},
                           "streetEdges": [0], "rearEdges": [2]}
    context["roads"] = {"source": "census_tiger", "fetched": "2026-10-23", "geoBounds": geographic_box(45.0, -93.0, 300, 300),
                        "items": list(roads)}
    return doc, normalize_site_context(context, doc)


STREET = road("street", "S1400", "Mill St", (-200, -8), (150, -8), (400, -8))       # local, along the south side
ARTERIAL = road("hwy", "S1200", "State Hwy 95", (150, -200), (150, -8), (150, 300))  # arterial, 10 m east; they meet
RAIL = road("rail", "R1011", None, (-15, -200), (-15, 300))               # railway just west of the lot
WEST_ROAD = road("west", "S1400", "River Rd", (-30, -200), (-30, 300))    # a road beyond the railway


def test_options_cover_each_facing_and_the_arterial_side_is_preferred():
    doc, site = site_doc(STREET, ARTERIAL, RAIL, WEST_ROAD)
    plan = plan_warehouse(doc, site, LOT)
    options = {item["facing"]: item for item in plan["options"]}
    assert set(options) == {"north", "east", "south", "west"}
    assert plan["chosen"] == "east" and options["east"]["drive"]["kind"] == "arterial"
    assert options["east"]["drive"]["road"] == "State Hwy 95"
    # The west court is nearest River Rd, but a drive may not cross the railway: it goes to Mill St.
    assert options["west"]["drive"]["road"] == "Mill St"
    east = options["east"]
    assert east["buildingWidthMeters"] * east["buildingDepthMeters"] == pytest.approx(east["buildingAreaSquareMeters"])
    assert east["buildingWidthMeters"] <= 140 - 2 * 6 - 40 + 1 and east["dockDoors"] >= 10


def test_the_chosen_design_applies_cleanly_with_walls_doors_zones_court_drive_and_entrance():
    doc, site = site_doc(STREET, ARTERIAL, RAIL, setbacks=10)
    doc["extensions"][KEY] = site
    plan = plan_warehouse(doc, site, LOT, "south")
    names = [op["op"] for op in plan["operations"]]
    assert names == ["set_site_context", "set_plan_settings", "set_building_pose", "set_perimeter_walls", "set_ground",
                     "upsert_floor_surface", "add_zone", "add_zone", "add_zone", "upsert_site_area", "upsert_site_area",
                     "upsert_site_area", "upsert_site_area"]  # truck court and drive, car park and its drive
    built = staged(doc, plan["operations"])
    plan_size = built["extensions"]["facilityPlan"]
    [slab] = built["extensions"]["facilityFloorSurfaces"]["surfaces"]
    assert slab["material"] == "concrete" and slab["boundary"] == [
        {"x": 0, "z": 0}, {"x": plan_size["widthMeters"], "z": 0},
        {"x": plan_size["widthMeters"], "z": plan_size["depthMeters"]}, {"x": 0, "z": plan_size["depthMeters"]}]
    walls = built["extensions"]["facilityPerimeterWalls"]["settings"]
    [entrance] = [o for o in walls["openings"] if o["endMeters"] - o["startMeters"] < 2]  # the employee door
    docks = [o for o in walls["openings"] if o is not entrance]
    assert docks and {opening["edge"] for opening in docks} == {0} and entrance["edge"] != 0
    finish = walls["exteriorFinish"]  # the user's look: cyan panels, a white band along the top
    assert finish["color"] == "#06b6d4" and finish["bands"] == [
        {"bottomMeters": walls["heightMeters"] - 1, "heightMeters": 1.0, "color": "#ffffff"}]
    assert plan["appearance"]["employeeEntrance"] is True
    assert {zone["zoneType"] for zone in built["zones"]} >= {"receiving", "shipping", "storage"}
    context = built["extensions"][KEY]
    # Even from the south court the drive heads for the arterial, entering through the lot's east edge.
    assert context["property"]["entrances"][0]["use"] == "trucks" and context["property"]["entrances"][0]["edgeIndex"] == 1
    assert any(area["label"] == "Truck drive to State Hwy 95" for area in context["areas"])
    assert {area["kind"] for area in context["areas"]} == {"truck_court", "drive", "parking"}
    assert not warnings(built), warnings(built)  # the drive crosses the 10 m street setback through its entrance
    assert built["extensions"][KEY]["routes"][0]["mainRoad"] == "State Hwy 95"  # direct onto the arterial


def test_a_ragged_outline_is_smoothed_and_a_requested_facing_is_kept():
    doc, site = site_doc(STREET, ARTERIAL)
    notched = deepcopy(LOT)
    notched[1:1] = [{"x": 60, "z": 0}, {"x": 64, "z": 9}, {"x": 68, "z": 0}]  # a 9 m dent in the south edge
    plain = plan_warehouse(doc, site, LOT, "north")
    ragged = plan_warehouse(doc, site, notched, "north")
    area = lambda plan: next(o for o in plan["options"] if o["facing"] == "north")["buildingAreaSquareMeters"]  # noqa: E731
    assert ragged["chosen"] == "north" and area(ragged) >= 0.95 * area(plain)


def test_outlines_too_small_or_outside_the_lot_are_refused():
    doc, site = site_doc(STREET)
    with pytest.raises(ValueError):
        plan_warehouse(doc, site, [{"x": 0, "z": 0}, {"x": 10, "z": 0}, {"x": 10, "z": 10}])
    with pytest.raises(ValueError):
        plan_warehouse(doc, site, [{"x": 500, "z": 500}, {"x": 600, "z": 500}, {"x": 600, "z": 600}, {"x": 500, "z": 600}])


def test_sage_builds_step_by_step_and_the_one_shot_planner_is_retired():
    """plan_warehouse stays as the step tools' geometry; Sage no longer designs a whole site in one call (2026-10-24)."""
    from ai_inspector.codex_runtime.site_tools import NAMES, STEP_TOOLS, tool_specs
    listed = {spec["name"] for spec in tool_specs()}
    assert "plan_warehouse_on_outline" not in NAMES | listed
    assert set(STEP_TOOLS) <= NAMES and set(STEP_TOOLS) <= listed


def test_the_slab_is_left_out_when_the_layout_has_finishes_and_replaced_when_it_is_the_only_one():
    doc, site = site_doc(STREET, ARTERIAL)
    doc["extensions"]["facilityFloorSurfaces"] = {"version": 1, "surfaces": [{"surfaceId": "fs-epoxy"}]}
    plan = plan_warehouse(doc, site, LOT, "east")
    assert "upsert_floor_surface" not in [op["op"] for op in plan["operations"]]
    assert any("no concrete slab" in note for note in plan["assumptions"]["notes"])
    doc["extensions"]["facilityFloorSurfaces"]["surfaces"] = [{"surfaceId": "fs-warehouse-slab"}]
    replanned = plan_warehouse(doc, site, LOT, "east")
    assert "upsert_floor_surface" in [op["op"] for op in replanned["operations"]]
    assert not any("no concrete slab" in note for note in replanned["assumptions"]["notes"])


def test_a_drive_leaves_only_through_an_edge_that_faces_its_street():
    # 4th Ave N runs along the north-west part of the lot only, then turns north: the north-east part of
    # the lot faces a field, as at Bayport. The east court must reach the street through the frontage.
    fourth = road("fourth", "S1400", "4th Ave N", (-200, 110), (50, 110), (50, 400))
    doc, site = site_doc(fourth)
    doc["extensions"][KEY] = site
    plan = plan_warehouse(doc, site, LOT, "east")
    drive = next(o for o in plan["options"] if o["facing"] == "east")["drive"]
    assert drive and drive["road"] == "4th Ave N" and drive["toRoadMeters"] <= 15
    entrance = drive["entrance"]
    assert entrance["edgeIndex"] == 2 and entrance["x"] <= 50 + 15  # on the north edge, where the street is
    east = next(o for o in plan["options"] if o["facing"] == "east")
    assert east["shortenedForDriveMeters"] >= 6  # the 6 m lane is too narrow: the building gave way to the drive
    built = staged(doc, plan["operations"])
    assert not warnings(built), warnings(built)


def test_driveways_keep_clear_of_intersections_and_rail_crossings():
    from ai_inspector.facility_layout.site_access import frontage
    from shapely.geometry import LineString, Point
    ring = [(0, 0), (140, 0), (140, 100), (0, 100)]
    street = LineString([(-200, -8), (400, -8)])
    stretches = frontage(ring, street, [(Point(70, -8), 23.0)], 12.0)
    assert [index for index, _ in stretches] == [0, 0]
    assert all(Point(x, -8).distance(Point(70, -8)) >= 23.0 - 1e-6 for _i, piece in stretches for x, _z in piece.coords)
    assert all(6.0 <= x <= 134.0 for _i, piece in stretches for x, _z in piece.coords)  # the driveway stays on the edge


def test_vehicle_entrances_are_checked_against_the_street_corners_rail_and_queue():
    doc, site = site_doc(STREET, RAIL)
    site["property"]["entrances"] = [
        {"entranceId": "far", "edgeIndex": 2, "x": 70, "z": 100, "use": "trucks", "widthMeters": 12},  # faces nothing
        {"entranceId": "rail", "edgeIndex": 0, "x": 10, "z": 0, "use": "cars", "widthMeters": 7},       # 25 m from the rail
        {"entranceId": "queue", "edgeIndex": 0, "x": 90, "z": 0, "use": "trucks", "widthMeters": 12}]
    site["areas"] = [{"areaId": "court", "label": "Truck court", "kind": "truck_court", "surface": "concrete",
                      "boundary": [{"x": 60, "z": 20}, {"x": 120, "z": 20}, {"x": 120, "z": 60}, {"x": 60, "z": 60}]}]
    doc["extensions"][KEY] = site
    found = {(f["entranceId"], f["code"]) for f in analyze_site_context(doc)["findings"] if "entranceId" in f}
    assert found == {("far", "site_entrance_far_from_street"), ("rail", "site_entrance_near_rail_crossing"),
                     ("queue", "site_truck_queue_short")}


def test_planning_again_replaces_the_previous_design():
    doc, site = site_doc(STREET, ARTERIAL)
    doc["extensions"][KEY] = site
    first = staged(doc, plan_warehouse(doc, site, LOT, "east")["operations"])
    again = plan_warehouse(first, first["extensions"][KEY], LOT, "south")
    assert [op["op"] for op in again["operations"]][:5] == ["set_site_context", "delete_zone", "delete_zone", "delete_zone",
                                                            "set_perimeter_walls"]
    second = staged(first, again["operations"])
    assert sorted(zone["zoneId"] for zone in second["zones"]) == ["zn-receiving", "zn-shipping", "zn-storage"]
    docks = [o for o in second["extensions"]["facilityPerimeterWalls"]["settings"]["openings"]
             if o["endMeters"] - o["startMeters"] > 2]  # beside the employee door
    assert {o["edge"] for o in docks} == {0}
    assert not warnings(second), warnings(second)


def test_the_lot_is_paved_square_to_the_building_with_a_concrete_apron_and_the_slab_on_ground():
    from shapely.geometry import box
    from shapely.ops import unary_union
    doc, site = site_doc(STREET, ARTERIAL, setbacks=10)
    doc["extensions"][KEY] = site
    plan = plan_warehouse(doc, site, LOT, "south")
    built = staged(doc, plan["operations"])
    tiles = built["extensions"]["facilityGround"]["surfaces"]
    shape = lambda rows: unary_union([box(t["minX"], t["minZ"], t["maxX"], t["maxZ"]) for t in rows])  # noqa: E731
    size = built["extensions"]["facilityPlan"]
    slab = shape([t for t in tiles if t["surfaceId"].startswith("gr-slab")])
    assert slab.symmetric_difference(box(0, 0, size["widthMeters"], size["depthMeters"])).area < 1e-6
    apron = shape([t for t in tiles if t["surfaceId"].startswith("gr-apron")])
    assert apron.area == pytest.approx(18.3 * size["widthMeters"]) and apron.bounds[3] <= 0 + 1e-6  # south of the wall
    assert {t["color"] for t in tiles if t["surfaceId"].startswith("gr-apron")} == {"#a7abae"}
    asphalt = shape([t for t in tiles if t["color"] == "#4a4f55"])
    assert asphalt.area > 0 and len(tiles) <= 64
    assert all(t["startElevation"] == t["endElevation"] == 0 for t in tiles)
    assert not warnings(built), warnings(built)


def test_the_car_park_gets_its_own_driveway_and_route_and_the_building_gives_way():
    from ai_inspector.facility_layout.site_parking import CAR_ASSETS, accessible_needed
    doc, site = site_doc(STREET, ARTERIAL)
    doc["extensions"][KEY] = site
    catalog = {CAR_ASSETS[0]: {"assetId": CAR_ASSETS[0], "assetDefinitionRevision": "a" * 64}}
    plan = plan_warehouse(doc, site, LOT, "east", catalog=catalog)
    park = plan["carPark"]
    assert park["stalls"] >= 0.9 * park["stallsNeeded"] and park["accessibleStalls"] == accessible_needed(park["stallsNeeded"])
    east = next(o for o in plan["options"] if o["facing"] == "east")
    assert east.get("shortenedForCarParkMeters", 0) > 0  # a maximal building leaves only 6 m lanes
    entrance = park["driveway"]["entrance"]
    built = staged(doc, plan["operations"])
    context = built["extensions"][KEY]
    by_id = {e["entranceId"]: e for e in context["property"]["entrances"]}
    assert set(by_id) == {"entrance-truck", "entrance-cars"} and by_id["entrance-cars"]["use"] == "cars"
    assert math.dist((entrance["x"], entrance["z"]), (by_id["entrance-truck"]["x"], by_id["entrance-truck"]["z"])) >= 30
    assert {r["use"] for r in context["routes"] if r["mainRoad"]} == {"trucks", "cars"}
    # The planner reports the very routes the saved design derives, so Sage can describe them before staging.
    assert plan["routesToMainRoad"] == [{key: route[key] for key in route if key in plan["routesToMainRoad"][0]}
                                        for route in context["routes"]]
    assert {a["kind"] for a in context["areas"]} >= {"parking", "drive", "truck_court"}
    assert not warnings(built), warnings(built)
    ops = plan["parkingOperations"]
    zone = next(op["zone"] for op in ops if op["op"] == "add_zone")
    assert zone["zoneType"] == "workcell" and zone["zoneId"] == "zn-employee-parking"
    boxes = [op["floorMarking"] for op in ops if op["op"] == "add_floor_marking" and op["floorMarking"]["markingType"] == "parking_box"]
    assert len(boxes) == park["stalls"] and sum(b["text"] in ("ACCESSIBLE", "VAN") for b in boxes) == park["accessibleStalls"]
    cars = [op for op in ops if op["op"] == "place_asset"]
    assert 0 < len(cars) == park["parkedCars"] and all(c["placement"]["assetDefinitionRevision"] == "a" * 64 for c in cars)
    # The pickups arrive unpainted: their colours come in the paint review once they are saved (site_paint.py).
    assert all("componentMaterials" not in c["placement"] for c in cars)
    painted = staged(built, [op for op in ops if op["op"] != "place_asset"])  # the paint and zone apply cleanly
    assert len([m for m in painted["floorMarkings"] if m["markingType"] == "parking_box"]) == park["stalls"]
    # The walk arrives at the employee door, a gap in the wall centred on it, without cutting into the wall.
    from shapely.geometry import LineString, Point, Polygon
    from shapely.ops import unary_union
    walls = unary_union([Polygon([(p["x"], p["z"]) for p in panel])
                         for panel in painted["extensions"]["facilityPerimeterWalls"]["panels"]])
    walk = next(r for r in painted["routes"] if r["routeId"] == "rt-car-park-walk")
    corridor = LineString([(p["x"], p["z"]) for p in walk["centerline"]]).buffer(walk["corridorWidth"] / 2, cap_style=2)
    start = Point(walk["centerline"][0]["x"], walk["centerline"][0]["z"])
    assert not corridor.intersects(walls) and start.distance(walls) == pytest.approx(0.9, abs=0.05)  # half the door
    again = plan_warehouse(painted, painted["extensions"][KEY], LOT, "east")
    assert sum(op["op"] == "delete_floor_marking" for op in again["operations"]) == len(painted["floorMarkings"])


def test_a_car_park_off_a_corner_gets_a_door_clear_of_the_corner_and_a_walk_square_to_the_wall():
    from shapely.geometry import LineString, box
    from ai_inspector.facility_layout.site_parking import DOOR_CORNER_METERS, _door, operations
    building, park = (0.0, 0.0, 60.0, 40.0), (-30.0, 46.0, -5.0, 70.0)  # the car park lies north-west
    door, normal = _door(building, park, (0.0, 40.0))  # the nearest point was the building's corner
    assert normal == (0, 1) and door == (DOOR_CORNER_METERS, 40.0)
    ops = operations({"alongU": True, "rect": park, "stalls": [], "aisle": ((-30.0, 58.0), (-5.0, 58.0)),
                      "door": door, "doorNormal": normal}, (0.0, 0.0), None)
    walk = next(op["aisle"] for op in ops if op["op"] == "add_aisle" and op["routeId"] == "rt-car-park-walk")
    points = [(p["x"], p["z"]) for p in walk["centerline"]]
    assert points[0][0] == pytest.approx(points[1][0], abs=1e-9)  # out of the door square to the north wall
    assert box(*park).contains(LineString(points[-2:]).interpolate(1.0, normalized=True))  # ends inside the car park
    ring = box(*building).buffer(0.15, join_style=2).difference(box(*building).buffer(-0.15, join_style=2))
    corridor = LineString(points).buffer(walk["corridorWidth"] / 2, cap_style=2)
    assert not corridor.intersects(ring) and corridor.distance(ring) < 0.1


def test_trucks_back_up_to_every_other_door_with_counter_clockwise_arrows():
    from ai_inspector.facility_layout.site_trucks import TRUCK_ASSET
    doc, site = site_doc(STREET, ARTERIAL)
    doc["extensions"][KEY] = site
    truck = {"assetId": TRUCK_ASSET, "assetDefinitionRevision": "b" * 64,
             "definition": {"geometry": {"aabb": {"minimum": {"x": -1.275, "y": 0, "z": -7.937},
                                                  "maximum": {"x": 1.275, "y": 3.79, "z": 7.937}}}}}
    plan = plan_warehouse(doc, site, LOT, "east", catalog={TRUCK_ASSET: truck})
    ops = plan["truckOperations"]
    zone = next(op["zone"] for op in ops if op["op"] == "add_zone")
    assert zone["zoneType"] == "dock" and zone["zoneId"] == "zn-truck-court"
    width = plan["options"][[o["facing"] for o in plan["options"]].index("east")]["buildingWidthMeters"]
    trucks = [op["placement"] for op in ops if op["op"] == "place_asset"]
    doors = next(o for o in plan["options"] if o["facing"] == "east")["dockDoors"]
    assert plan["truckCourt"]["trucksAtDocks"] == len(trucks) >= doors // 2 - 1
    assert all("componentMaterials" not in placed for placed in trucks)  # painted in their own review (site_paint.py)
    for placed in trucks:  # east docks: cab toward +x (yaw 90), container doors 0.25 m off the east wall
        q = placed["transform"]["quaternion"]
        assert math.degrees(2 * math.atan2(q["y"], q["w"])) == pytest.approx(90)
        assert placed["transform"]["position"]["x"] == pytest.approx(width + 0.25 + 7.937, abs=1e-3)
    arrows = [op["floorMarking"] for op in ops if op["op"] == "add_floor_marking"]
    along = {a["transform"]["rotationDegrees"] % 360 for a in arrows if "Along Docks" in a["label"]}
    outside = {a["transform"]["rotationDegrees"] % 360 for a in arrows if "Outside" in a["label"]}
    assert along == {0.0} and outside == {180.0}  # north along the east wall, south on the far side


def test_the_interior_has_rack_rows_square_to_the_dock_wall_aisles_markings_and_forklifts():
    from ai_inspector.facility_layout.site_interior import FORKLIFT_ASSET, RACK_ASSET
    doc, site = site_doc(STREET, ARTERIAL)
    doc["extensions"][KEY] = site
    box = lambda x, z: {"definition": {"geometry": {"aabb": {"minimum": {"x": -x, "y": 0, "z": -z},  # noqa: E731
                                                              "maximum": {"x": x, "y": 3, "z": z}}}}}
    catalog = {RACK_ASSET: {"assetId": RACK_ASSET, "assetDefinitionRevision": "d" * 64, **box(0.6136, 1.2642)},
               FORKLIFT_ASSET: {"assetId": FORKLIFT_ASSET, "assetDefinitionRevision": "e" * 64, **box(0.565, 0.981)}}
    plan = plan_warehouse(doc, site, LOT, "east", catalog=catalog)
    ops, summary = plan["interiorOperations"], plan["interior"]
    rows = [op for op in ops if op["op"] == "place_asset_array"]
    assert summary["rackRows"] == len(rows) > 0 and summary["rackBays"] == sum(op["count"] for op in rows)
    assert all(op["step"]["z"] == 0 and abs(op["step"]["x"]) == pytest.approx(2.5284) for op in rows)  # along x: square to the east wall
    assert all("componentMaterials" not in op["placement"] for op in rows)  # painted bay by bay after saving
    doors = next(o for o in plan["options"] if o["facing"] == "east")["dockDoors"]
    lanes = [op["floorMarking"] for op in ops if op["op"] == "add_floor_marking" and op["floorMarking"]["semanticRole"] == "staging"]
    assert len(lanes) == doors and lanes[0]["text"] == "DOOR 1"
    assert summary["forklifts"] == max(2, round(doors / 2.5))
    zone = next(op["zone"] for op in ops if op["op"] == "add_zone")
    assert zone["zoneType"] == "charging"
    built = staged(staged(doc, plan["operations"]), [op for op in ops if op["op"] in ("add_aisle", "add_floor_marking", "add_zone")])
    assert len([r for r in built["routes"] if r["routeId"].startswith("rt-interior-")]) == summary["aisles"]
    again = plan_warehouse(built, built["extensions"][KEY], LOT, "east")
    assert sum(op["op"] == "delete_route" for op in again["operations"]) == summary["aisles"]


def test_the_logo_is_centred_on_both_walls_beside_the_dock_wall_and_clear_of_doors(monkeypatch):
    from pathlib import Path
    from ai_inspector.facility_layout import site_plan
    monkeypatch.setattr(Path, "is_file", lambda self: True)  # the app has the logo image
    # Warehouse 5's shape: west docks (edge 3), 93 x 56 m, 9 m of wall below the band; a door on the north wall.
    logos = site_plan._logos(93.0, 56.0, 9.0, [0, 2], [{"edge": 2, "startMeters": 43.0, "endMeters": 44.8}])
    assert [logo["edge"] for logo in logos] == [0, 2]  # the south and north walls
    south, north = logos
    assert south["heightMeters"] == 6.5 and south["bottomMeters"] == 1.25 and south["imagePath"] == site_plan.LOGO_IMAGE
    assert south["startMeters"] + south["widthMeters"] / 2 == pytest.approx(46.5, abs=1e-3)  # centred
    assert north["startMeters"] == pytest.approx(45.3)  # the nearest place clear of the door, 0.5 m from it
    monkeypatch.setattr(Path, "is_file", lambda self: False)  # an app without the image: no logos
    assert site_plan._logos(93.0, 56.0, 9.0, [0, 2], []) == []


def test_the_target_is_painted_at_the_centre_of_the_largest_open_yard(monkeypatch):
    from pathlib import Path
    from ai_inspector.facility_layout import site_plan
    monkeypatch.setattr(Path, "is_file", lambda self: True)  # the app has the target image
    tiles = [dict(surfaceId="gr-asphalt-1", minX=0, maxX=80, minZ=0, maxZ=80),  # the truck court: not open yard
             dict(surfaceId="gr-yard-2", minX=100, maxX=130, minZ=0, maxZ=40),
             dict(surfaceId="gr-yard-3", minX=100, maxX=110, minZ=50, maxZ=60)]
    [mark] = site_plan._ground_marks(tiles)
    assert (mark["x"], mark["z"], mark["widthMeters"], mark["depthMeters"]) == (115.0, 20.0, 12.0, 12.0)
    assert mark["imagePath"] == site_plan.TARGET_IMAGE
    assert site_plan._ground_marks(tiles[:1]) == []  # no open yard, no target
