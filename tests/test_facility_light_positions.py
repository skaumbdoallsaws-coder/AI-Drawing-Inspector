"""FIX 3b: suggest_facility_light_positions finds clear spots for a pole light (a car park's head-to-head strip, an
island between painted lanes, the zone's edge) and wall mounts beside a room's door, on small made-up layouts.
3c: a new pole light on one of those spots skips the parking review; the server checks the spot itself."""
import json
import math

import pytest

from ai_inspector.codex_runtime.facility_tools import tool_specs
from ai_inspector.codex_runtime.progress import describe
from ai_inspector.facility_layout.host import LOCAL_LAYOUT_ID, LOCAL_SITE_ID, LocalFacilityLayoutHost, _asset
from ai_inspector.facility_layout.light_positions import (NAME, SPACING, USER_POSITION, _pole_candidates,
                                                          cleared_pole_spots, suggest_light_positions)
from ai_inspector.facility_layout.spatial import diagnose_layout, oriented_box_polygon
from ai_inspector.facility_layout.wall_attachments import validate_relationship
from shapely.geometry import Point, Polygon


def asset(asset_id, width, depth, height, tags):
    record = _asset(asset_id=asset_id, display_name=asset_id, category="Facilities", width=width, depth=depth,
                    height=height, description="")
    record["definition"]["tags"] = list(tags)
    return record


POLE = asset("asset-pole", 0.5, 0.5, 8.0, ["lighting", "pole light", "outdoor"])
WALL_LIGHT = asset("asset-wall-light", 0.4, 0.25, 0.32, ["lighting", "wall light", "wall-mounted"])
CHAIR = asset("asset-chair", 0.5, 0.5, 0.9, ["chair"])


def mark(mark_id, kind, x, z, width, depth, rotation=0, role="decorative"):
    return {"markingId": mark_id, "markingType": kind, "semanticRole": role, "label": mark_id, "width": width,
            "depth": depth, "transform": {"position": {"x": x, "y": 0, "z": z}, "rotationDegrees": rotation}}


def place(placement_id, record, x, y, z, yaw=0.0, relationship=None):
    half = math.radians(yaw) / 2
    return {"placementId": placement_id, "assetId": record["assetId"],
            "assetDefinitionRevision": record["assetDefinitionRevision"],
            "transform": {"position": {"x": x, "y": y, "z": z},
                          "quaternion": {"x": 0, "y": math.sin(half), "z": 0, "w": math.cos(half)}, "scale": 1},
            "positionMode": "locked", "snapRelationship": relationship, "metadata": {"instanceLabel": placement_id}}


def zone(zone_id, max_x, max_z, floor=0.0):
    return {"zoneId": zone_id, "label": zone_id, "floorElevation": floor,
            "boundary": [{"x": 0, "z": 0}, {"x": max_x, "z": 0}, {"x": max_x, "z": max_z}, {"x": 0, "z": max_z}]}


def yard():
    """A 60 x 60 m yard: lines at x 10, 18, 28 and 36 (z 5 to 55); arrows between 10 and 18 and between 28 and 36
    make those lanes, so 18 to 28 is an island; IN painted at the entrance; a truck bay at the east side."""
    marks = [mark(f"line-{x}", "solid_line", x, 30, 0.15, 50) for x in (10, 18, 28, 36)]
    marks += [mark(f"arrow-{x}-{z}", "direction_arrow", x, z, 3, 5) for x in (14, 32) for z in (15, 40)]
    marks += [mark("in", "floor_text", 14, 2, 6, 2), mark("bay", "parking_box", 52, 15, 14, 4)]
    return {"zones": [zone("zn-yard", 60, 60)], "floorMarkings": marks, "routes": [], "placements": []}


def car_park(existing=None):
    """Two rows of five car bays parked head to head, 1.4 m apart."""
    marks = [mark(f"bay-{row}-{n}", "parking_box", 10 + 2.8 * n, z, 2.8, 5.8, role="parking")
             for row, z in (("a", 10.0), ("b", 17.2)) for n in range(5)]
    placements = [place("pl-old-pole", POLE, *existing)] if existing else []
    return {"zones": [zone("zn-park", 40, 30)], "floorMarkings": marks, "routes": [], "placements": placements}


CATALOG = {record["assetId"]: record for record in (POLE, WALL_LIGHT, CHAIR)}


def positions(layout, **arguments):
    return suggest_light_positions(layout, CATALOG, {"assetId": POLE["assetId"], **arguments})["positions"]


def spot(item):
    p = item["placement"]["transform"]["position"]
    return p["x"], p["z"]


def test_a_pole_at_the_yards_south_end_goes_on_the_island_never_in_a_lane_or_on_paint():
    layout = yard()
    found = positions(layout, zoneId="zn-yard", edge="south", count=4)
    assert len(found) == 4
    assert "island" in found[0]["where"] and spot(found[0]) == pytest.approx((23.0, 6.5))
    lanes = [Polygon(oriented_box_polygon((x, 30), (4, 31), 0)) for x in (14, 32)]   # past the lines' ends, too
    paint = [Polygon(oriented_box_polygon((m["transform"]["position"]["x"], m["transform"]["position"]["z"]),
                                          (m["width"] / 2, m["depth"] / 2), 0)) for m in layout["floorMarkings"]]
    approach = Polygon(oriented_box_polygon((38, 15), (7, 2), 0))   # the bay's length again, west of it
    for item in found:
        x, z = spot(item)
        base = Point(x, z).buffer(0.25, cap_style=3)
        assert z <= 12, "near the south edge"
        assert not any(shape.intersects(base) for shape in lanes + paint + [approach]), (x, z)
        assert item["placement"]["transform"]["position"]["y"] == 0
        assert item["placement"]["transform"]["quaternion"] == {"x": 0, "y": 0, "z": 0, "w": 1}
        assert item["placement"]["snapRelationship"] is None
    assert all(math.dist(spot(a), spot(b)) >= SPACING for i, a in enumerate(found) for b in found[i + 1:])


def test_a_car_park_pole_goes_on_the_strip_between_head_to_head_rows_clear_of_other_lights():
    found = positions(car_park(), zoneId="zn-park", count=2)
    assert [spot(item) for item in found] == [pytest.approx((10.0, 13.6)), pytest.approx((21.2, 13.6))]
    assert all("head to head" in item["where"] for item in found)
    found = positions(car_park(existing=(10.0, 0.0, 13.6)), zoneId="zn-park", count=1)
    assert spot(found[0]) == pytest.approx((21.2, 13.6)), "10 m from the light already there"


def test_a_low_light_keeps_no_pole_away_and_a_pole_does():
    """2026-11-05: only another pole (a light whose top stands at least POLE_HEIGHT up) keeps a new pole SPACING away;
    a bollard, an uplight or a festoon string near the spot does not (it still blocks the ground it stands on), and
    a short flood head mounted high does."""
    bollard = asset("asset-bollard", 0.18, 0.18, 0.85, ["lighting", "bollard", "outdoor"])
    catalog = dict(CATALOG, **{bollard["assetId"]: bollard})
    layout = car_park()
    layout["placements"].append(place("pl-bollard", bollard, 13.0, 0.0, 13.6))
    found = suggest_light_positions(layout, catalog, {"assetId": POLE["assetId"], "zoneId": "zn-park",
                                                      "count": 2})["positions"]
    assert [spot(item) for item in found] == [pytest.approx((10.0, 13.6)), pytest.approx((21.2, 13.6))]
    flood = asset("asset-flood", 0.4, 0.3, 0.3, ["lighting", "flood light", "outdoor"])
    catalog[flood["assetId"]] = flood
    for blocker in (place("pl-pole", POLE, 13.0, 0.0, 13.6), place("pl-flood", flood, 13.0, 5.5, 13.6)):
        layout["placements"][-1] = blocker
        found = suggest_light_positions(layout, catalog, {"assetId": POLE["assetId"], "zoneId": "zn-park",
                                                          "count": 2})["positions"]
        assert found and all(math.dist(spot(item), (13.0, 13.6)) >= SPACING for item in found), blocker["placementId"]


def test_the_ground_and_placements_decide_where_a_pole_can_stand():
    layout = yard()
    layout["extensions"] = {"facilityGround": {"schemaVersion": 1, "surfaces": [
        {"surfaceId": "yard", "minX": 0, "maxX": 60, "minZ": 0, "maxZ": 60, "startElevation": -1.35,
         "endElevation": -1.35, "slopeAxis": "x", "color": "#3d4247"}]}}
    layout["zones"][0]["floorElevation"] = -1.35
    layout["placements"] = [place("pl-chair", CHAIR, 23.0, -1.35, 6.5)]
    found = positions(layout, zoneId="zn-yard", edge="south", count=1)
    assert found[0]["placement"]["transform"]["position"]["y"] == -1.35
    assert math.dist(spot(found[0]), (23.0, 6.5)) > 1.0, "not on the chair"
    layout["extensions"]["facilityGround"]["surfaces"][0].update(startElevation=-2.0, endElevation=-1.0)
    assert positions(layout, zoneId="zn-yard", edge="south") == [], "never on a slope"


def room(door_wall="east"):
    """A 10 x 8 m room with a 1.2 m door gap in its east wall (two segments along Z) or its north wall (along X),
    in a site zone that takes the light outside it."""
    walls, records = [], {}

    def wall(placement_id, x, z, width, depth):
        record = asset(f"asset-{placement_id}", width, depth, 3.6, ["wall"])
        records[record["assetId"]] = record
        walls.append(place(placement_id, record, x, 0, z))
    if door_wall == "east":
        wall("pl-east-a", 9.9, 1.5, 0.2, 3.0)
        wall("pl-east-b", 9.9, 6.0, 0.2, 3.6)
        wall("pl-north", 4.9, 7.9, 9.8, 0.2)
    else:
        wall("pl-north-a", 2.0, 7.9, 4.0, 0.2)
        wall("pl-north-b", 7.5, 7.9, 5.0, 0.2)
        wall("pl-east", 9.9, 3.9, 0.2, 7.8)
    site = dict(zone("zn-site", 20, 20), boundary=[{"x": -5, "z": -5}, {"x": 20, "z": -5}, {"x": 20, "z": 20},
                                                   {"x": -5, "z": 20}])
    layout = {"zones": [zone("zn-room", 10, 8), site], "floorMarkings": [], "routes": [], "placements": walls}
    return layout, {**CATALOG, **records}


def diagnose(layout, catalog, light):
    shell = {"features": [{"featureId": "floor", "featureKind": "floor_surface", "geometry": {"elevation": 0,
             "boundary": [{"x": -10, "z": -10}, {"x": 20, "z": -10}, {"x": 20, "z": 20}, {"x": -10, "z": 20}]}}]}
    trial = dict(layout, placements=layout["placements"] + [dict(light, placementId="pl-light", positionMode="locked",
                                                                   metadata={"instanceLabel": "Door light"})])
    return [f for f in diagnose_layout(trial, list(catalog.values()), shell=shell)["findings"]
            if "pl-light" in (f.get("subjectRefs") or [])]


@pytest.mark.parametrize("door_wall,face,heading", [("east", "positive_x", 90), ("north", "positive_z", 0)])
def test_a_wall_light_goes_beside_the_door_on_the_outside_of_the_wall(door_wall, face, heading):
    layout, catalog = room(door_wall)
    result = suggest_light_positions(layout, catalog, {"assetId": WALL_LIGHT["assetId"], "zoneId": "zn-room"})
    assert result["method"] == "wall"
    found = result["positions"]
    assert len(found) == 2, "one on each side of the door"
    for item in found:
        relationship = item["placement"]["snapRelationship"]
        validate_relationship(relationship)
        assert relationship["face"] == face and relationship["normalGapMeters"] == 0.003
        assert relationship["localY"] == pytest.approx(3.6 - 0.32 - 0.05), "as high as the 3.6 m wall allows"
        q = item["placement"]["transform"]["quaternion"]
        assert math.degrees(2 * math.atan2(q["y"], q["w"])) == pytest.approx(heading), "facing out of the room"
        findings = diagnose(layout, catalog, item["placement"])
        assert not [f for f in findings if f["severity"] == "error"], findings
        assert any(f["code"] == "wall_attachment_safety_unverified" for f in findings)
    x, z = zip(*(spot(item) for item in found))
    if door_wall == "east":
        assert x == pytest.approx((10.128, 10.128)) and z == pytest.approx((2.7, 4.5)), "0.3 m from the door's edges"
    else:
        assert z == pytest.approx((8.128, 8.128)) and x == pytest.approx((3.7, 5.3))
    other = "north" if door_wall == "east" else "east"
    result = suggest_light_positions(layout, catalog, {"assetId": WALL_LIGHT["assetId"], "zoneId": "zn-room",
                                                       "edge": other})
    assert result["positions"] == [] and "No opening" in result["none"]


def test_a_mount_that_would_stand_in_a_walkway_is_left_out():
    layout, catalog = room("east")
    layout["routes"] = [{"routeId": "rt-door", "corridorWidth": 2.0,
                         "centerline": [{"x": 6, "y": 0, "z": 3.2}, {"x": 14, "y": 0, "z": 3.2}]}]
    result = suggest_light_positions(layout, catalog, {"assetId": WALL_LIGHT["assetId"], "zoneId": "zn-room"})
    assert [spot(item)[1] for item in result["positions"]] == [pytest.approx(4.5)], "the one at z 2.7 is in the walk"
    assert result["skipped"] == {"inWalkway": "1 mounts left out: the light would stand in a walkway or route corridor"}


def test_a_mount_outside_every_zone_is_left_out_with_the_reason():
    layout, catalog = room("east")
    layout["zones"] = layout["zones"][:1]   # no zone outside the room
    result = suggest_light_positions(layout, catalog, {"assetId": WALL_LIGHT["assetId"], "zoneId": "zn-room"})
    assert result["positions"] == [] and set(result["skipped"]) == {"outsideZones"}
    assert "see skipped" in result["none"]


def test_only_light_fittings_and_saved_zones():
    with pytest.raises(ValueError, match="light fittings"):
        suggest_light_positions(yard(), CATALOG, {"assetId": CHAIR["assetId"], "zoneId": "zn-yard"})
    with pytest.raises(ValueError, match="zone"):
        suggest_light_positions(yard(), CATALOG, {"assetId": POLE["assetId"], "zoneId": "zn-missing"})
    with pytest.raises(ValueError, match="catalog"):
        suggest_light_positions(yard(), CATALOG, {"assetId": "asset-missing", "zoneId": "zn-yard"})


def test_the_server_clears_a_new_pole_only_on_the_helpers_own_spot():
    """3c: by the helper's rules on the layout as proposed, whatever the batch says. Pinned definitions are keyed by
    (assetId, revision)."""
    pinned = {(record["assetId"], record["assetDefinitionRevision"]): record for record in (POLE, WALL_LIGHT, CHAIR)}
    layout = yard()
    found = positions(layout, zoneId="zn-yard", edge="south", count=2)
    (x, z), (x2, z2) = spot(found[0]), spot(found[1])

    def check(*placed, new=None):
        proposed = dict(layout, placements=list(placed))
        return cleared_pole_spots(proposed, pinned, new or [item["placementId"] for item in placed])
    assert check(place("pl-a", POLE, x, 0.0, z)) == {"pl-a": found[0]["where"]}
    assert check(place("pl-a", POLE, x, 0.0, z, yaw=30)) == {"pl-a": found[0]["where"]}, "its turn does not matter"
    assert check(place("pl-a", POLE, x, 0.0, z), place("pl-b", POLE, x2, 0.0, z2)).keys() == {"pl-a", "pl-b"}
    # Placed by hand: off the spot, in a lane or raised; tipped over; within 10 m of a light already there.
    tipped = place("pl-a", POLE, x, 0.0, z)
    tipped["transform"]["quaternion"] = {"x": math.sin(math.radians(45)), "y": 0, "z": 0, "w": math.cos(math.radians(45))}
    for placed in (place("pl-a", POLE, x + 0.5, 0.0, z), place("pl-a", POLE, 14.0, 0.0, 30.0),
                   place("pl-a", POLE, x, 1.0, z), tipped):
        assert check(placed) == {}, placed["transform"]
    assert check(place("pl-a", POLE, x, 0.0, z), place("pl-old", POLE, x, 0.0, z + 6), new=["pl-a"]) == {}
    # Two new poles on island spots about 4 m apart: neither (the helper never offers both).
    island = [item for item in _pole_candidates(layout, CATALOG, POLE, layout["zones"][0], None)[0] if "island" in item[4]]
    (_, ax, _, az, _, _), (_, bx, _, bz, _, _) = island[0], island[2]
    assert 3 < math.dist((ax, az), (bx, bz)) < SPACING
    assert check(place("pl-a", POLE, ax, 0.0, az), place("pl-b", POLE, bx, 0.0, bz)) == {}
    assert check(place("pl-w", WALL_LIGHT, x, 0.0, z), place("pl-c", CHAIR, x2, 0.0, z2)) == {}, "poles only"


@pytest.fixture
def lit_host(tmp_path):
    """A host whose catalog has the real light fittings (tools/factory02_light_models.py)."""
    from tools import factory02_light_models as models
    root = tmp_path / "project"
    manifest = root / models.CATALOG
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(json.dumps({"assets": [], "schemaVersion": 1, "summary": {"total": 0}}).encode("ascii"))
    models.install(root)
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=True, private_asset_root=root)
    host.ensure_bootstrap()
    try:
        yield host
    finally:
        host.close()


def test_a_pole_on_a_helper_spot_applies_directly_and_one_placed_by_hand_is_reviewed(lit_host):
    """3c through a real proposal in direct mode: the car park is saved, then the pole is previewed."""
    from tests.test_facility_operation_proposals import apply, approve, propose
    from tools import factory02_light_models as models
    service, principal = context = lit_host.service, lit_host.principal()
    park = car_park()
    paint = {"fillColor": "#ffffff", "strokeColor": "#ffffff", "opacity": 1, "text": "", "positionMode": "manual",
             "metadata": {}, "evidence": []}
    saved = propose(context, operations=[
        {"op": "add_zone", "zone": dict(park["zones"][0], zoneType="workcell", label="Visitor Parking", anchors=[],
                                        evidence=[])},
        *[{"op": "add_floor_marking", "floorMarking": dict(mark, markingId="fm-" + mark["markingId"], **paint)}
          for mark in park["floorMarkings"]]])
    apply(context, saved, approve(context, saved))
    layout = service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)["layout"]
    catalog = {record["assetId"]: record for record in lit_host._agent_asset_catalog(principal, LOCAL_SITE_ID)}
    first = suggest_light_positions(layout, catalog, {"assetId": models.POLE_LIGHT, "zoneId": "zn-park"})["positions"][0]
    assert "head to head" in first["where"]

    def pole(**moved):
        placement = dict(first["placement"], placementId="pl-pole", positionMode="locked",
                         metadata={"instanceLabel": "Pole light 1"})
        placement["transform"] = dict(placement["transform"], position=dict(placement["transform"]["position"], **moved))
        return [{"op": "place_asset", "placementId": "pl-pole", "placement": placement}]
    on_spot = propose(context, operations=pole(), edit_mode="direct")["alternative"]
    assert on_spot["directApplyPolicy"]["eligible"] is True and "functionalDesign" not in on_spot["validation"]
    assert on_spot["validation"]["clearedLightSpots"] == [{"placementId": "pl-pole", "where": first["where"]}]
    by_hand = propose(context, operations=pole(x=first["placement"]["transform"]["position"]["x"] + 1),
                      edit_mode="direct")["alternative"]
    assert by_hand["directApplyPolicy"] == {"version": 1, "eligible": False,
                                            "reason": "Review the parking access and circulation findings before applying."}
    assert "functionalDesign" in by_hand["validation"] and "clearedLightSpots" not in by_hand["validation"]


def test_a_light_goes_where_the_user_says_and_the_helper_is_for_no_position():
    """Sage refused "Put a pole light in Employee Parking South at x 312, z 197.5" (the main session's desktop check,
    2026-11-01): the light texts read as a rule that only the helper's spots were allowed. Every text Sage reads about
    placing a light now says the user's position wins; the server stages such a pole for review (the test above)."""
    from ai_inspector.codex_runtime.edit_schemas import operation_batch_schema
    from ai_inspector.codex_runtime.pilot import EDIT_INSTRUCTIONS
    variants = operation_batch_schema()["properties"]["operations"]["items"]["oneOf"]
    texts = {"standing instructions": EDIT_INSTRUCTIONS,
             "place_asset": next(v for v in variants if v["properties"]["op"]["const"] == "place_asset")["description"],
             "the helper": next(spec for spec in tool_specs() if spec["name"] == NAME)["description"],
             "its howToUse": suggest_light_positions(car_park(), CATALOG, {"assetId": POLE["assetId"],
                                                                           "zoneId": "zn-park"})["howToUse"]}
    for name, value in texts.items():
        flat = " ".join(value.split())
        assert USER_POSITION in flat, name
        assert "with no position from the user" in flat.casefold(), name
    assert "place it there with place_asset" in USER_POSITION and "not a reason to refuse or move it" in USER_POSITION


def test_sage_has_the_tool_with_a_progress_line():
    spec = next(spec for spec in tool_specs() if spec["name"] == NAME)
    assert spec["input_schema"]["required"] == ["assetId", "zoneId"]
    assert "snapRelationship" in spec["description"] and "come lit" in spec["description"]
    assert describe(NAME, {"zoneId": "zn-yard-all"})["done"] == "Checked clear spots for the light"


def test_sage_has_a_lighting_playbook_for_its_opinions():
    """2026-11-05 (the gym lighting demo): asked where lights should go or how many, Sage chooses from a few rules
    and says what it chose; the position helper is only for outdoor poles and wall lights by a door."""
    from ai_inspector.codex_runtime.pilot import EDIT_INSTRUCTIONS
    text = " ".join(EDIT_INSTRUCTIONS.split())
    for rule in ("The position helper is only for outdoor pole lights and wall lights by an outside door",
                 "bollards every 3 to 5 m", "an uplight 0.3 to 0.5 m from the trunk or wall, facing it",
                 "festoon strings hung under the roof (metadata.mountingSurface with the roof's placementId)",
                 "about 3 times their height apart", "0.75 to 0.9 m above its top",
                 "sconces with their base about 1.5 m up, 2.5 to 3 m apart", "warm, layered light"):
        assert rule in text, rule
