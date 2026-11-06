"""CC: the lighting coverage estimate. One lamp checked by hand against the formula; lamps found in the real light
models as the 3D view finds them; the scene's switch and areas; dark spots; the areas it checks; Sage's tool."""
import base64
import json
import math

import numpy as np
import pytest
from shapely.geometry import Polygon, box

from ai_inspector.codex_runtime.facility_tools import tool_specs
from ai_inspector.codex_runtime.progress import describe
from ai_inspector.facility_layout.appearance_library import _valid_estimate, load_library
from ai_inspector.facility_layout.host import build_private_local_asset_catalog
from ai_inspector.facility_layout.light_coverage import (CAPTION, LOW_MIN_HEIGHT, NAME, OUTSIDE_VALUE, _dark_spots,
                                                         area_of, blocking_walls, check_lighting_coverage, estimate,
                                                         find_lamps, lamp_data, lamp_parts, view_payload)
from tools import factory02_light_models as models

LIBRARY = load_library()


def lamp(x, y, z, aim=(0.0, -1.0, 0.0), lumens=12000.0, beam=110.0, on=True, placement_id="pl-a"):
    return {"placementId": placement_id, "label": placement_id, "finish": "light-pole-led", "x": x, "y": y, "z": z,
            "aim": list(aim), "heightMeters": y, "lumens": lumens, "beamAngleDegrees": beam, "on": on, "off": None}


def lux_at(result, x, z):
    grid = result["grid"]
    return grid["lux"][int((z - grid["originZ"]) // 1), int((x - grid["originX"]) // 1)]


def test_one_lamp_by_hand():
    """12000 lm with a 110 degree beam. Theta off the aim the intensity is I0 cos^m(theta): half the peak at the beam's
    edge (55 degrees off), so m = ln 0.5 / ln cos 55 = 1.247, and I0 = 12000 (m + 1) / (2 pi) cd puts the whole output
    in the lamp's front half. On level ground 8 m below, a cell d away gets I0 cos^m(theta) x 8 / d^3, inside the
    beam and past its edge."""
    result = estimate({}, [lamp(10.5, 8.0, 10.5)], box(0, 0, 21, 21))
    power = math.log(0.5) / math.log(math.cos(math.radians(55)))
    peak = 12000 * (power + 1) / (2 * math.pi)
    assert (power, peak) == (pytest.approx(1.247, abs=0.001), pytest.approx(4291.4, abs=0.1))

    def by_hand(dx, dz):
        d = math.sqrt(dx * dx + dz * dz + 64)
        return peak * (8 / d) ** power * 8 / d ** 3
    assert lux_at(result, 10.5, 10.5) == pytest.approx(peak / 64)              # straight down: 67.1 lux
    assert lux_at(result, 13.5, 14.5) == pytest.approx(by_hand(3, 4))          # 3 m and 4 m off, 32 degrees: 33.3 lux
    assert lux_at(result, 10.5, 0.5) == pytest.approx(by_hand(0, 10))          # 10 m off, 51 degrees: 9.1 lux
    assert lux_at(result, 0.5, 0.5) == pytest.approx(by_hand(10, 10))          # 60.5 degrees, past the edge: 3.3 lux
    assert result["totals"] == {"minimum": 3.3, "mean": pytest.approx(result["grid"]["lux"].mean(), abs=0.05),
                                "maximum": round(peak / 64, 1)}
    assert result["cells"] == 21 * 21 and result["lampsReaching"] == 1
    # Half the peak at the beam's edge: a 120 degree lamp 4 sqrt(3) m up, at a cell 12 m off (60 degrees).
    height = 4 * math.sqrt(3)
    wide = estimate({}, [lamp(12.5, height, 0.5, beam=120.0)], box(0, 0, 25, 1))
    assert lux_at(wide, 0.5, 0.5) * math.hypot(12, height) ** 3 / height == pytest.approx(
        lux_at(wide, 12.5, 0.5) * height ** 2 / 2)
    # The whole output lands in front of the lamp: on a floor 60 m out every way, all but what passes 60 m.
    floor = estimate({}, [lamp(60.5, 6.0, 60.5)], box(0, 0, 121, 121))
    assert floor["grid"]["lux"].sum() == pytest.approx(12000 * (1 - (6 / math.hypot(60, 6)) ** (power + 1)), rel=1e-3)
    # A lamp 35 m off still adds a little, but under 0.5 lux it does not count as lighting the area; 65 m off, none.
    far = estimate({}, [lamp(5.5, 6.0, 5.5)], box(40, 0, 51, 11))
    assert far["lampsReaching"] == 0 and 0 < far["grid"]["lux"].max() < 0.5
    assert estimate({}, [lamp(5.5, 6.0, 5.5)], box(70, 0, 80, 11))["totals"]["maximum"] == 0
    # The ground below sets the height: over a yard 1.35 m down the same lamp is 9.35 m up.
    layout = {"extensions": {"facilityGround": {"schemaVersion": 1, "surfaces": [
        {"surfaceId": "yard", "minX": 0, "maxX": 21, "minZ": 0, "maxZ": 21, "startElevation": -1.35,
         "endElevation": -1.35, "slopeAxis": "x", "color": "#3d4247"}]}}}
    assert lux_at(estimate(layout, [lamp(10.5, 8.0, 10.5)], box(0, 0, 21, 21)), 10.5, 10.5) == pytest.approx(
        peak / 9.35 ** 2)
    # A 70 degree lamp (m = 3.47) aimed 30 degrees out, 4 m up: by hand 3 m out along its lean (6.9 degrees off the
    # aim), 25 times less 3 m the other way (66.9 degrees off), and nothing behind its front half (8 m back).
    aim = (math.sin(math.radians(30)), -math.cos(math.radians(30)), 0.0)
    tilted = estimate({}, [lamp(10.5, 4.0, 10.5, aim=aim, beam=70.0)], box(0, 0, 21, 21))
    steep = math.log(0.5) / math.log(math.cos(math.radians(35)))
    facing = (3 * aim[0] - 4 * aim[1]) / 5
    assert lux_at(tilted, 13.5, 10.5) == pytest.approx(12000 * (steep + 1) / (2 * math.pi) * facing ** steep * 4 / 125)
    assert lux_at(tilted, 13.5, 10.5) > 20 * lux_at(tilted, 7.5, 10.5) > 0 and lux_at(tilted, 2.5, 10.5) == 0
    # A lamp switched off lights nothing.
    assert estimate({}, [lamp(10.5, 8.0, 10.5, on=False)], box(0, 0, 21, 21))["totals"]["maximum"] == 0


def test_only_the_areas_cells_are_worked_out():
    """Two yards 90 m apart: each lamp works out only the cells of the area within its reach, so the yard by the lamp
    gets exactly what it gets alone, and the far one (over 60 m off) nothing."""
    both = estimate({}, [lamp(5.5, 6.0, 5.5)], box(0, 0, 10, 10).union(box(100, 0, 110, 10)))
    alone = estimate({}, [lamp(5.5, 6.0, 5.5)], box(0, 0, 10, 10))
    near = both["grid"]["lux"][:, :10]
    assert both["grid"]["lux"].shape == (10, 110) and near.min() > 0, "every cell of the near yard"
    assert np.array_equal(near, alone["grid"]["lux"])
    assert both["grid"]["lux"][:, 100:].max() == 0 and both["cells"] == 200 and both["lampsReaching"] == 1


def test_dark_spots_are_the_cells_below_half_the_mean_with_their_deepest_point_and_nearest_lamps():
    lamps = [lamp(5.5, 6.0, 5.5, placement_id="pl-west"), lamp(45.5, 6.0, 5.5, placement_id="pl-east")]
    result = estimate({}, lamps, box(0, 0, 51, 11))
    spots = result["darkSpots"]
    assert result["darkLevel"] == pytest.approx(result["totals"]["mean"] / 2, abs=0.1)
    middle = max(spots, key=lambda spot: spot["sizeSquareMeters"])
    assert middle["centre"]["x"] == pytest.approx(25.5, abs=1.5), "deepest in the band between the two pools"
    assert {near["placementId"] for near in middle["nearestLamps"]} == {"pl-west", "pl-east"}
    assert middle["nearestLamps"][0]["distanceMeters"] == pytest.approx(20, abs=1.6)
    assert 0 < middle["minimumLux"] < 2 and middle["extentMeters"]["z"] == 11, "past both beams' edges: a little light"
    assert all(spot["minimumLux"] < result["darkLevel"] for spot in spots)
    assert estimate({}, lamps, box(0, 0, 51, 11), dark_below=0.001)["darkLevel"] == 0.0


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    """The real light models installed in a project of their own, read by the host as the app reads them."""
    root = tmp_path_factory.mktemp("cc")
    manifest = root / models.CATALOG
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(json.dumps({"assets": [], "schemaVersion": 1, "summary": {"total": 0}}).encode("ascii"))
    models.install(root)
    return root, build_private_local_asset_catalog(root)


def place(catalog, asset_id, placement_id, x, y, z, yaw=0.0, roll=0.0, **extra):
    record = next(entry for entry in catalog if entry["assetId"] == asset_id)
    half, tip = math.radians(yaw) / 2, math.radians(roll) / 2
    quaternion = ({"x": 0, "y": math.sin(half), "z": 0, "w": math.cos(half)} if not roll else
                  {"x": math.sin(tip), "y": 0, "z": 0, "w": math.cos(tip)})
    return dict({"placementId": placement_id, "assetId": asset_id,
                 "assetDefinitionRevision": record["assetDefinitionRevision"],
                 "transform": {"position": {"x": x, "y": y, "z": z}, "quaternion": quaternion, "scale": 1},
                 "metadata": {"instanceLabel": placement_id}}, **extra)


def lens_centre(asset_id):
    """The area-weighted centre of a model's LED lens, from its GLB (the lens faces down all over)."""
    import struct
    raw = models.build(next(m for m in models.MODELS if m["assetId"] == asset_id))
    length = struct.unpack_from("<I", raw, 12)[0]
    doc = json.loads(raw[20:20 + length])
    binary = raw[20 + length + 8:]
    node = next(n for n in doc["nodes"] if n.get("name") == "led lens")
    primitive = doc["meshes"][node["mesh"]]["primitives"][0]

    def array(index, dtype, width):
        accessor = doc["accessors"][index]
        view = doc["bufferViews"][accessor["bufferView"]]
        data = np.frombuffer(binary, dtype=dtype, count=accessor["count"] * width,
                             offset=view.get("byteOffset", 0) + accessor.get("byteOffset", 0))
        return data.reshape(-1, width).astype(float)
    points = array(primitive["attributes"]["POSITION"], "<f4", 3)[array(primitive["indices"], "<u2", 1)
                                                                  .astype(int).reshape(-1, 3)]
    areas = np.linalg.norm(np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0]), axis=1) / 2
    return (points.mean(axis=1) * areas[:, None]).sum(axis=0) / areas.sum()


def test_lamps_are_found_in_the_real_models_as_the_view_finds_them(project):
    root, catalog = project
    by_revision = {(entry["assetId"], entry["assetDefinitionRevision"]): entry for entry in catalog}
    pole_lens = models.LED_LENS_KEYS[models.POLE_LIGHT]
    layout = {"placements": [
        place(catalog, models.POLE_LIGHT, "pl-pole", 10.0, 0.0, 20.0, yaw=90),             # lit by its model
        place(catalog, models.WALL_LIGHT, "pl-wall", 30.0, 3.0, 20.0, yaw=90),             # faces +x, 30 degrees out
        place(catalog, models.WALL_LIGHT, "pl-wall-low", 40.0, 0.0, 20.0),                 # under 3 m: no lamp
        place(catalog, models.POLE_LIGHT, "pl-pole-dock", 50.0, 0.0, 20.0, componentMaterials={
            "representation": "overview", "overrides": [{"key": pole_lens, "appearanceId": "light-dock-led"}]}),
        place(catalog, models.POLE_LIGHT, "pl-pole-painted", 60.0, 0.0, 20.0, componentMaterials={
            "representation": "overview", "overrides": [{"key": pole_lens, "color": "#808080", "roughness": 0.5,
                                                         "metalness": 0.0}]}),          # its own finish is no light
        place(catalog, models.POLE_LIGHT, "pl-pole-fallen", 70.0, 0.5, 20.0, roll=90),     # tipped over
        place(catalog, models.BEACON, "pl-beacon", 80.0, 3.0, 20.0)]}                      # a signal light
    lamps, notes = find_lamps(layout, by_revision, LIBRARY, root)
    assert [item["placementId"] for item in lamps] == ["pl-pole", "pl-wall", "pl-pole-dock"]
    assert notes == {"unreadModels": [], "signalLightParts": {"Beacon amber": 1}, "uplightParts": {}}
    pole, wall, dock = lamps
    centre = lens_centre(models.POLE_LIGHT)
    # Mirrored across the model's x = 0, then turned 90 degrees: model (x, z) lands at (z, x) about the placement.
    assert (pole["x"], pole["y"], pole["z"]) == pytest.approx((10.0 + centre[2], centre[1], 20.0 + centre[0]), abs=1e-4)
    assert pole["aim"] == pytest.approx([0, -1, 0], abs=1e-6) and pole["finish"] == "light-pole-led"
    assert pole["heightMeters"] == pytest.approx(models.POLE_HEIGHT - 0.15, abs=1e-3)
    tilt = math.radians(models.WALL_LIGHT_TILT)
    assert wall["aim"] == pytest.approx([math.sin(tilt), -math.cos(tilt), 0], abs=1e-6), "out along +x"
    assert wall["y"] > 3.0 and wall["finish"] == "light-wall-led" and wall["lumens"] == 4000
    assert dock["finish"] == "light-dock-led" and dock["beamAngleDegrees"] == 70, "its own Lights finish wins"
    assert all(item["on"] and item["off"] is None for item in lamps)


def test_a_low_outdoor_light_counts_from_any_height_and_an_uplight_not_at_all(project):
    """2026-11-05 (the gym's garden): a low outdoor light (a bollard, a lantern) counts from LOW_MIN_HEIGHT, as the view
    throws its pool; an uplight lights what it faces, not the ground, so it counts as none and is listed."""
    root, catalog = project
    by_revision = {(entry["assetId"], entry["assetDefinitionRevision"]): entry for entry in catalog}
    lens = models.LED_LENS_KEYS[models.WALL_LIGHT]

    def finish(appearance_id):
        return {"componentMaterials": {"representation": "overview",
                                       "overrides": [{"key": lens, "appearanceId": appearance_id}]}}
    layout = {"placements": [
        place(catalog, models.WALL_LIGHT, "pl-bollard", 10.0, 0.6, 20.0, **finish("light-bollard-warm")),
        place(catalog, models.WALL_LIGHT, "pl-wall-low", 20.0, 0.6, 20.0),               # its own finish: too low
        place(catalog, models.WALL_LIGHT, "pl-uplight", 30.0, 5.0, 20.0, **finish("light-garden-uplight"))]}
    lamps, notes = find_lamps(layout, by_revision, LIBRARY, root)
    assert [lamp["placementId"] for lamp in lamps] == ["pl-bollard"]
    (bollard,) = lamps
    assert (bollard["finish"], bollard["lumens"], bollard["beamAngleDegrees"]) == ("light-bollard-warm", 600, 150)
    assert LOW_MIN_HEIGHT <= bollard["heightMeters"] < 1.0, bollard["heightMeters"]
    assert notes == {"unreadModels": [], "signalLightParts": {}, "uplightParts": {"Garden uplight warm": 1}}
    result = estimate({}, lamps, box(0, 10, 20, 30))
    assert lux_at(result, bollard["x"], bollard["z"]) > lux_at(result, bollard["x"] + 4, bollard["z"]) > 0
    # Sage's summary lists the uplight it left out.
    summary, _ = check_lighting_coverage(layout, catalog, LIBRARY, {"rectangle": {"minX": 0, "minZ": 10, "maxX": 40,
                                                                                  "maxZ": 30}}, root)
    assert summary["lamps"]["uplightsNotCounted"] == {"Garden uplight warm": 1}
    assert summary["lamps"]["byFinish"] == {"light-bollard-warm": 1}


def test_a_low_lights_lamps_are_its_glowing_pieces_with_a_patch_facing_down():
    """As the view's bulbsOf: a lantern's glass (a closed box here) faces down only at its foot, a seventh of its
    surface: no lamp by the share rule, but a low outdoor light's lamp."""
    corners = [(-0.1, 0, -0.1), (0.1, 0, -0.1), (0.1, 0, 0.1), (-0.1, 0, 0.1),
               (-0.1, 0.25, -0.1), (0.1, 0.25, -0.1), (0.1, 0.25, 0.1), (-0.1, 0.25, 0.1)]
    triangles = [(0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
                 (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    assert lamp_parts(corners, triangles) == []
    ((centre, aim, area),) = lamp_parts(corners, triangles, share=0.0)
    assert list(centre) == pytest.approx([0, 0, 0]) and list(aim) == pytest.approx([0, -1, 0])
    assert area == pytest.approx(0.04)


def test_the_saved_scene_switch_and_areas_turn_lamps_off(project):
    root, catalog = project
    by_revision = {(entry["assetId"], entry["assetDefinitionRevision"]): entry for entry in catalog}
    layout = {"placements": [place(catalog, models.POLE_LIGHT, "pl-a", 10.0, 0.0, 10.0),
                             place(catalog, models.POLE_LIGHT, "pl-b", 40.0, 0.0, 10.0)],
              "extensions": {"facilityFloorSurfaces": {"version": 1, "surfaces": [
                  {"surfaceId": "fs-west", "label": "West", "boundary": [
                      {"x": 0, "z": 0}, {"x": 20, "z": 0}, {"x": 20, "z": 20}, {"x": 0, "z": 20}]}]}}}

    def states(adjustments):
        layout["extensions"]["facilityScene"] = {"sceneId": "evening", "version": 1, "adjustments": adjustments}
        return [(item["placementId"], item["on"], item["off"]) for item in find_lamps(layout, by_revision, LIBRARY, root)[0]]
    assert states({}) == [("pl-a", True, None), ("pl-b", True, None)]
    assert states({"lights": False}) == [("pl-a", False, "switch"), ("pl-b", False, "switch")]
    assert states({"lightAreas": {"mode": "only", "areas": [{"surfaceId": "fs-west"}]}}) == [
        ("pl-a", True, None), ("pl-b", False, "area")]
    assert states({"lightAreas": {"mode": "except", "areas": [
        {"rectangle": {"minX": 0, "minZ": 0, "maxX": 20, "maxZ": 20}}]}}) == [("pl-a", False, "area"), ("pl-b", True, None)]
    summary, _ = check_lighting_coverage(layout, catalog, LIBRARY, {"rectangle": {"minX": 0, "minZ": 0, "maxX": 50,
                                                                                    "maxZ": 20}}, root)
    assert summary["lamps"]["on"] == 1 and summary["lamps"]["offByArea"] == 1
    assert summary["scene"]["lightAreas"] == {"mode": "except", "areas": 1, "missingFloorAreas": []}


def test_the_areas_it_checks(project):
    root, catalog = project
    square = lambda x0, z0, x1, z1: [{"x": x0, "z": z0}, {"x": x1, "z": z0}, {"x": x1, "z": z1}, {"x": x0, "z": z1}]
    layout = {"placements": [], "zones": [
        {"zoneId": "zn-park", "label": "Visitor car park", "boundary": square(0, 0, 30, 20)},
        {"zoneId": "zn-bays", "label": "Area B", "boundary": square(40, 0, 60, 20)},
        {"zoneId": "zn-hall", "label": "Hall", "boundary": square(0, 30, 60, 60)}],
        "floorMarkings": [{"markingId": "bay", "markingType": "parking_box", "semanticRole": "parking", "width": 2.5,
                           "depth": 5, "transform": {"position": {"x": 50, "y": 0, "z": 10}, "rotationDegrees": 0}}],
        "extensions": {"facilityFloorSurfaces": {"version": 1, "surfaces": [
            {"surfaceId": "fs-kiosk", "label": "Kiosk", "boundary": square(0, 0, 5, 5)}]}}}
    shape, area = area_of(layout, {"lot": True})
    assert area["zoneIds"] == ["zn-park", "zn-bays"] and shape.area == pytest.approx(600 + 400 - 25)
    assert area_of(layout, {"zoneId": "zn-hall"})[1]["label"] == "Hall"
    assert area_of(layout, {"floorAreaId": "fs-kiosk"})[0].area == pytest.approx(25)
    for arguments, message in (({}, "exactly one"), ({"lot": True, "zoneId": "zn-hall"}, "exactly one"),
                               ({"zoneId": "zn-none"}, "zone"), ({"floorAreaId": "fs-none"}, "floor area"),
                               ({"rectangle": {"minX": 0, "minZ": 0, "maxX": 0.5, "maxZ": 9}}, "at least 1 m")):
        with pytest.raises(ValueError, match=message):
            area_of(layout, arguments)
    with pytest.raises(ValueError, match="too large"):
        check_lighting_coverage(layout, catalog, LIBRARY, {"rectangle": {"minX": 0, "minZ": 0, "maxX": 2000,
                                                                          "maxZ": 2000}}, root)
    with pytest.raises(ValueError, match="no car park"):
        area_of({"zones": layout["zones"][2:]}, {"lot": True})
    summary, _ = check_lighting_coverage(layout, catalog, LIBRARY, {"zoneId": "zn-park"}, root)
    assert summary["label"] == CAPTION and summary["estimatedLux"]["maximum"] == 0
    assert summary["darkSpots"]["note"] == "This layout has no general or outdoor lights."


def test_the_lot_is_outdoor_ground_not_the_building(project):
    """2026-11-01, a CC bug: Factory 02's lot took in the hall's Equipment Service + Utilities zone, whose equipment
    bays are parking bays. The lot leaves out the building: what a placement tagged roof and building covers, and the
    outline the perimeter walls follow. A bay in it marks no lot; a canopy tagged roof alone is not the building."""
    root, lamps_catalog = project
    square = lambda x0, z0, x1, z1: [{"x": x0, "z": z0}, {"x": x1, "z": z0}, {"x": x1, "z": z1}, {"x": x0, "z": z1}]

    def record(asset_id, tags):                             # a 40 x 20 m slab
        return {"assetId": asset_id, "assetDefinitionRevision": "r-" + asset_id, "definition": {"tags": list(tags),
                "geometry": {"aabb": {"minimum": {"x": -20.0, "y": 0.0, "z": -10.0},
                                      "maximum": {"x": 20.0, "y": 0.1, "z": 10.0}}}}}

    def placed(asset_id, x, z):
        return {"placementId": "pl-" + asset_id, "assetId": asset_id, "assetDefinitionRevision": "r-" + asset_id,
                "transform": {"position": {"x": x, "y": 10.0, "z": z}, "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1},
                              "scale": 1}}
    records = [record("asset-roof-deck", ("roof", "roof-sheeting", "building")), record("asset-canopy", ("roof",))]
    catalog = {(r["assetId"], r["assetDefinitionRevision"]): r for r in records}
    bay = {"markingId": "bay", "markingType": "parking_box", "semanticRole": "parking", "width": 2.5, "depth": 5,
           "transform": {"position": {"x": 10, "y": 0, "z": 40}, "rotationDegrees": 0}}
    zones = [{"zoneId": "zn-yard", "label": "Truck yard", "boundary": square(0, 0, 40, 20)},
             {"zoneId": "zn-service", "label": "Equipment service", "boundary": square(0, 30, 20, 50)},  # the bay
             {"zoneId": "zn-forklifts", "label": "Forklift parking", "boundary": square(20, 30, 40, 50)},
             {"zoneId": "zn-staff", "label": "Staff car park", "boundary": square(30, 30, 60, 50)}]
    layout = {"placements": [placed("asset-roof-deck", 20, 40),   # the hall's roof: x 0 to 40, z 30 to 50
                             placed("asset-canopy", 20, 10)],     # a canopy over the yard
              "zones": zones, "floorMarkings": [bay]}
    shape, area = area_of(layout, {"lot": True}, catalog)
    assert area["zoneIds"] == ["zn-yard", "zn-staff"] and shape.area == pytest.approx(800 + 20 * 20)
    old_shape, old = area_of(layout, {"lot": True})                 # no catalog, no roof known: as before
    assert old["zoneIds"] == ["zn-yard", "zn-service", "zn-forklifts", "zn-staff"]
    assert old_shape.area == pytest.approx(800 + 60 * 20)
    summary, _ = check_lighting_coverage(layout, [*lamps_catalog, *records], LIBRARY, {"lot": True}, root)
    assert summary["area"]["zoneIds"] == ["zn-yard", "zn-staff"] and summary["area"]["sizeSquareMeters"] == 1200
    # Perimeter walls: the building is the outline they follow, their own polygon or the plan's edges.
    walled = {"zones": zones, "floorMarkings": [bay], "extensions": {"facilityPerimeterWalls": {
        "settings": {"boundarySource": "polygon", "boundary": square(0, 25, 45, 55)}}}}
    shape, area = area_of(walled, {"lot": True})
    assert area["zoneIds"] == ["zn-yard", "zn-staff"] and shape.area == pytest.approx(800 + 15 * 20)
    walled["extensions"] = {"facilityPlan": {"widthMeters": 45, "depthMeters": 55},
                            "facilityPerimeterWalls": {"settings": {"boundarySource": "plan"}}}
    shape, area = area_of(walled, {"lot": True})
    assert area["zoneIds"] == ["zn-staff"] and shape.area == pytest.approx(15 * 20)


def test_lamp_data_is_typical_and_matches_the_outdoor_beams():
    data = lamp_data(LIBRARY)
    assert set(data) == {"light-cool-white-led", "light-warm-white", "light-pole-led", "light-wall-led",
                         "light-dock-led", "light-accent-spot", "light-bollard-warm", "light-lantern-warm"}, (
        "general, outdoor, low and accent lights; no signal lights, and no uplights (they light what they face)")
    for appearance_id in data:
        row = LIBRARY["appearances"][appearance_id]
        assert row["estimate"]["basis"] == "typical, for estimates"
        if "beamAngleDegrees" in row["emission"]:
            assert row["estimate"]["beamAngleDegrees"] == row["emission"]["beamAngleDegrees"]
    assert not _valid_estimate({"lumens": 0, "beamAngleDegrees": 120, "basis": "typical, for estimates"})
    assert not _valid_estimate({"lumens": 900, "beamAngleDegrees": 120, "basis": "measured"})


def test_sage_has_the_read_only_tool_with_its_caption():
    spec = next(spec for spec in tool_specs() if spec["name"] == NAME)
    assert set(spec["input_schema"]["properties"]) == {"floorAreaId", "zoneId", "rectangle", "lot", "darkBelowLux"}
    assert CAPTION in spec["description"] and "never claim" in spec["description"]
    assert describe(NAME, {"lot": True})["done"] == "Checked the lighting coverage"


def test_the_view_payload_packs_the_grid_and_outlines_the_listed_spots():
    """CC3: lux in tenths as little-endian uint16 (65535 outside the area), row by row from the south-west cell; each
    listed dark spot numbered, with the rings of its cells."""
    shape = box(0, 0, 51, 11).difference(box(20, 4, 22, 6))
    result = estimate({}, [lamp(5.5, 6.0, 5.5, placement_id="pl-west"), lamp(45.5, 6.0, 5.5, placement_id="pl-east")],
                      shape)
    listed = [{key: value for key, value in spot.items() if key != "cells"} for spot in result["darkSpots"]]
    payload = view_payload({"darkSpots": {"listed": listed}}, result)
    grid = payload["grid"]
    assert (grid["originX"], grid["originZ"], grid["cols"], grid["rows"], grid["encoding"]) == (
        0, 0, 51, 11, "uint16le-tenths")
    values = np.frombuffer(base64.b64decode(grid["values"]), dtype="<u2").reshape(11, 51)
    assert (values == OUTSIDE_VALUE).sum() == 4 and values[4, 20] == OUTSIDE_VALUE, "the 2 x 2 m hole is outside"
    assert values[5, 5] == round(lux_at(result, 5.5, 5.5) * 10) and values[5, 5] > values[5, 15], "row = z, col = x"
    spot = payload["spots"][0]
    assert spot["number"] == 1 and spot["sizeSquareMeters"] == result["darkSpots"][0]["sizeSquareMeters"]
    rings = [Polygon(list(zip(ring[0::2], ring[1::2]))) for ring in spot["outline"]]
    assert len(rings) == 2 and rings[1].area == 4, "the hole in the area is a hole in the spot"
    assert rings[0].area - rings[1].area == spot["sizeSquareMeters"]
    assert "outline" not in listed[0], "Sage's summary carries no outlines"


def test_the_route_estimates_the_layout_as_the_view_holds_it(tmp_path):
    """CC3: the view's request carries the saved revision and its unsaved operations; nothing is saved."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ai_inspector.facility_layout.host import LOCAL_LAYOUT_ID, LOCAL_SITE_ID, LocalFacilityLayoutHost
    host = LocalFacilityLayoutHost(tmp_path / "isolated", private_assets=False)
    revision = host.ensure_bootstrap()["layout"]["revision"]
    app = FastAPI()
    app.include_router(host.create_router())
    url = f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/lighting/coverage"
    zone = {"zoneId": "zn-car-park", "zoneType": "staging", "label": "Visitor car park", "floorElevation": 0.0,
            "boundary": [{"x": 0.0, "z": 0.0}, {"x": 3.0, "z": 0.0}, {"x": 3.0, "z": 2.0}, {"x": 0.0, "z": 2.0}],
            "anchors": [], "evidence": []}
    with TestClient(app) as client:
        saved = client.post(url, json={"baseRevision": revision, "operations": [], "area": {"lot": True}})
        assert saved.status_code == 422 and "no car park" in saved.json()["detail"]["error"]["message"]
        drafted = client.post(url, json={"baseRevision": revision, "area": {"lot": True},
                                         "operations": [{"op": "add_zone", "zone": zone}]})
        assert drafted.status_code == 200, drafted.text
        body = drafted.json()
        assert body["summary"]["label"] == CAPTION and body["summary"]["area"]["zoneIds"] == ["zn-car-park"]
        assert body["summary"]["darkSpots"]["note"] == "This layout has no general or outdoor lights."
        assert (body["grid"]["cols"], body["grid"]["rows"]) == (3, 2) and body["spots"] == []
        stale = client.post(url, json={"baseRevision": "0" * 64, "operations": [], "area": {"lot": True}})
        assert stale.status_code == 409 and stale.json()["detail"]["error"]["code"] == "revision_conflict"
        assert client.post(url, json={"baseRevision": revision, "operations": []}).status_code == 422
    assert host.ensure_bootstrap()["layout"]["revision"] == revision, "nothing is saved"


# Walls (2026-11-01, the user's go): a lamp lights a cell only if the line to it clears every wall ---------------------

def wall_record(asset_id="asset-test-wall", length=20.0, height=4.0, thickness=0.2, tags=("wall",)):
    """A catalog record shaped as the app's: a box LENGTH along x, centred, standing on y 0."""
    return {"assetId": asset_id, "assetDefinitionRevision": "r-" + asset_id, "definition": {"tags": list(tags),
            "geometry": {"aabb": {"minimum": {"x": -length / 2, "y": 0.0, "z": -thickness / 2},
                                  "maximum": {"x": length / 2, "y": height, "z": thickness / 2}}}}}


def test_a_wall_stops_the_light_up_to_its_top():
    """A lamp 8 m up at x 10.5 and a 4 m wall on x 15, 4.5 m from it. A line to the floor d m out along x crosses the
    wall's line 4.5 m out, at 8 - 8 x 4.5 / d m up: under the wall's top out to d = 9. So the floor from the wall to
    9 m out is dark and lit as before past it. A wall as tall as the lamp hides all behind it; light passes a gap."""
    area = box(0, 0, 30, 21)
    open_floor = estimate({}, [lamp(10.5, 8.0, 10.5)], area)
    walled = estimate({}, [lamp(10.5, 8.0, 10.5)], area, walls=[(15.0, 0.0, 15.0, 21.0, 0.0, 4.0)])
    assert lux_at(walled, 14.5, 10.5) == lux_at(open_floor, 14.5, 10.5) > 0
    assert [lux_at(walled, x, 10.5) for x in (15.5, 16.5, 17.5, 18.5)] == [0.0] * 4    # 3.5 m up at 8 m out
    assert lux_at(walled, 20.5, 10.5) == lux_at(open_floor, 20.5, 10.5) > 0           # 4.4 m up at 10 m out
    tall = estimate({}, [lamp(10.5, 8.0, 10.5)], area, walls=[(15.0, 0.0, 15.0, 21.0, 0.0, 9.0)])
    assert not tall["grid"]["lux"][:, 15:].any() and tall["grid"]["lux"][:, :15].all()
    gap = estimate({}, [lamp(10.5, 8.0, 10.5)], area, walls=[(15.0, 0.0, 15.0, 9.0, 0.0, 9.0),
                                                             (15.0, 12.0, 15.0, 21.0, 0.0, 9.0)])
    assert lux_at(gap, 25.5, 10.5) == lux_at(open_floor, 25.5, 10.5) > 0      # through the gap (z 9 to 12)
    assert lux_at(gap, 25.5, 2.5) == 0                                       # crosses x 15 at z 8.1: the wall
    # A wall wholly above the lamp (from 9 m up) stops none of its light.
    above = estimate({}, [lamp(10.5, 8.0, 10.5)], area, walls=[(15.0, 0.0, 15.0, 21.0, 9.0, 12.0)])
    assert lux_at(above, 16.5, 10.5) == lux_at(open_floor, 16.5, 10.5) > 0


def test_a_wall_on_the_floor_stops_light_to_lower_ground_behind_it():
    """Factory 02's truck yard is 1.35 m below the hall floor, where the dock wall stands. A wall counts down to the
    ground: the line from a hall lamp 8 m up at x 10.5 to the yard at x 15.5 crosses the wall's line at x 15 0.4 m
    below the floor, and is still stopped."""
    yard = {"extensions": {"facilityGround": {"surfaces": [
        {"minX": 15.0, "maxX": 30.0, "minZ": 0.0, "maxZ": 21.0, "slopeAxis": "x", "startElevation": -1.35,
         "endElevation": -1.35}]}}}
    area = box(0, 0, 30, 21)
    open_yard = estimate(yard, [lamp(10.5, 8.0, 10.5)], area)
    walled = estimate(yard, [lamp(10.5, 8.0, 10.5)], area, walls=[(15.0, 0.0, 15.0, 21.0, 0.0, 10.0)])
    assert lux_at(open_yard, 15.5, 10.5) > 0 and not walled["grid"]["lux"][:, 15:].any()
    assert walled["grid"]["lux"][:, :15].all()


def test_walls_come_from_wall_placements_and_the_shells_walls():
    records = [wall_record(), wall_record("asset-guard", tags=("machine guard", "panel", "wire mesh"))]
    catalog = {(record["assetId"], record["assetDefinitionRevision"]): record for record in records}

    def placed(asset_id, placement_id, x, y, z, yaw=0.0, roll=0.0, scale=1.0):
        half, tip = math.radians(yaw) / 2, math.radians(roll) / 2
        quaternion = ({"x": 0, "y": math.sin(half), "z": 0, "w": math.cos(half)} if not roll else
                      {"x": math.sin(tip), "y": 0, "z": 0, "w": math.cos(tip)})
        return {"placementId": placement_id, "assetId": asset_id, "assetDefinitionRevision": "r-" + asset_id,
                "transform": {"position": {"x": x, "y": y, "z": z}, "quaternion": quaternion, "scale": scale}}
    layout = {"placements": [placed("asset-test-wall", "pl-turned", 5.0, 0.0, 5.0, yaw=90.0),   # runs along z
                             placed("asset-guard", "pl-guard", 0.0, 0.0, 0.0),                  # a mesh guard
                             placed("asset-test-wall", "pl-tipped", 0.0, 0.0, 0.0, roll=90.0),  # on its side
                             placed("asset-test-wall", "pl-big", 0.0, 1.0, 0.0, scale=2.0)]}
    walls = blocking_walls(layout, catalog)
    assert [pytest.approx(wall, abs=1e-6) for wall in walls] == [(5.0, -5.0, 5.0, 15.0, 0.0, 4.0),
                                                                 (-20.0, 0.0, 20.0, 0.0, 1.0, 9.0)]
    # The shell's walls (the perimeter walls come as triangles): one outline per height, its edges.
    def triangle(*points):
        return [{"x": x, "z": z} for x, z in points]
    shell = {"features": [
        {"featureId": "w-a", "featureKind": "wall", "geometry": {
            "boundary": triangle((0, -0.1), (10, -0.1), (10, 0.1)), "elevation": 0.0, "height": 5.0}},
        {"featureId": "w-b", "featureKind": "wall", "geometry": {
            "boundary": triangle((0, -0.1), (10, 0.1), (0, 0.1)), "elevation": 0.0, "height": 5.0}},
        {"featureId": "c-1", "featureKind": "column", "geometry": {
            "boundary": triangle((20, 0), (21, 0), (21, 1)), "elevation": 0.0, "height": 5.0}}]}
    edges = blocking_walls({"placements": []}, {}, shell)
    assert len(edges) == 4 and {wall[4:] for wall in edges} == {(0.0, 5.0)}
    assert {point for wall in edges for point in (wall[:2], wall[2:4])} == {
        (0.0, -0.1), (10.0, -0.1), (10.0, 0.1), (0.0, 0.1)}


def test_a_dark_spots_nearest_lamps_are_the_ones_no_wall_hides():
    lux, inside, ground = np.zeros((10, 10)), np.ones((10, 10), dtype=bool), np.zeros((10, 10))
    lamps = [lamp(5.0, 8.0, -3.0, placement_id="pl-behind"), lamp(5.0, 8.0, 20.0, placement_id="pl-north"),
             lamp(25.0, 8.0, 5.0, placement_id="pl-east")]
    wall = np.array([(-10.0, -1.0, 20.0, -1.0, 0.0, 10.0)])

    def ids(spots):
        return [item["placementId"] for item in spots[0]["nearestLamps"]]
    assert ids(_dark_spots(lux, inside, 1.0, 0.0, 0.0, lamps)) == ["pl-behind", "pl-north", "pl-east"]
    assert ids(_dark_spots(lux, inside, 1.0, 0.0, 0.0, lamps, wall, ground)) == ["pl-north", "pl-east"]


def test_a_pole_behind_a_wall_lights_nothing_past_it(project):
    """The case that asked for walls, in small: the hall's light rows lit the truck yard through the dock wall."""
    root, catalog = project
    wall = wall_record("asset-test-dock-wall", length=30.0, height=10.0, thickness=0.25)
    catalog = [*catalog, wall]
    pole = place(catalog, models.POLE_LIGHT, "pl-pole", 10.0, 0.0, 10.0)
    layout = {"placements": [pole, place(catalog, wall["assetId"], "pl-dock-wall", 15.0, 0.0, 15.0, yaw=90.0)]}
    hall = {"rectangle": {"minX": 0, "minZ": 0, "maxX": 15, "maxZ": 30}}
    yard = {"rectangle": {"minX": 15, "minZ": 0, "maxX": 30, "maxZ": 30}}
    open_yard, _ = check_lighting_coverage({"placements": [pole]}, catalog, LIBRARY, yard, root)
    assert open_yard["wallLines"] == 0 and open_yard["lamps"]["lightingThisArea"] == 1
    walled_yard, _ = check_lighting_coverage(layout, catalog, LIBRARY, yard, root)
    assert walled_yard["wallLines"] == 1 and walled_yard["lamps"]["lightingThisArea"] == 0
    assert walled_yard["estimatedLux"]["maximum"] == 0
    assert walled_yard["darkSpots"]["note"] == "No lamp that is on lights this area: it is dark everywhere."
    walled_hall, _ = check_lighting_coverage(layout, catalog, LIBRARY, hall, root)
    assert walled_hall["lamps"]["lightingThisArea"] == 1 and walled_hall["estimatedLux"]["maximum"] > 0
    assert any("Walls stop it" in line for line in walled_hall["limitations"])


def test_sage_reads_the_saved_layouts_walls_with_its_shell(tmp_path, monkeypatch):
    """Sage's check_lighting_coverage (facility_tools) estimates the saved layout with its shell as the spatial checks
    see it, as the view's route does, so both count the same walls."""
    import asyncio
    from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway
    from ai_inspector.facility_layout import light_coverage
    from ai_inspector.facility_layout.host import LOCAL_LAYOUT_ID, LOCAL_SITE_ID, LocalFacilityLayoutHost
    host = LocalFacilityLayoutHost(tmp_path / "isolated", private_assets=False)
    revision = host.ensure_bootstrap()["layout"]["revision"]
    shells, real = [], light_coverage.check_lighting_coverage

    def spy(*args, shell=None, **kwargs):
        shells.append(shell)
        return real(*args, shell=shell, **kwargs)
    monkeypatch.setattr(light_coverage, "check_lighting_coverage", spy)
    reference = {"siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": revision}
    gateway = FacilityEditGateway(host.agent_runtime, host.principal(), reference, turn_id="coverage-walls")
    response = asyncio.run(gateway.call(NAME, {"rectangle": {"minX": 0, "minZ": 0, "maxX": 3, "maxZ": 2}}))
    assert response["ok"], response
    data = response["data"]
    assert data["readOnly"] and data["savedLayoutOnly"] and data["label"] == CAPTION
    layout = host.service.get_layout(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID)["layout"]
    assert shells == [host.service.effective_shell(host.principal(), LOCAL_SITE_ID, layout)]
    assert isinstance(shells[0].get("features"), list) and isinstance(data["wallLines"], int)

