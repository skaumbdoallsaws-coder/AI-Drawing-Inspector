"""Basic shapes BS3 and BS4 (docs/sage-basic-shapes-plan.md): Sage's tools. author_shape_asset adds one model to the
shared library and returns its picture; place_along_line, place_grid and roof_frame plan packages that
preview_planned_design stages, which the engine accepts and applies. The grid leaves out points where its item would be
in the way and says why, and runs stop short of what is in their way (obstacle_map.py)."""
from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import re

import pytest
from PIL import Image
from shapely.geometry import Polygon, box

from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway
from ai_inspector.codex_runtime.facility_tools import FacilityReadGateway
from ai_inspector.codex_runtime.progress import describe
from ai_inspector.facility_layout import sage_shapes as shapes
from ai_inspector.facility_layout.host import LOCAL_LAYOUT_ID, LOCAL_SITE_ID, LocalFacilityLayoutHost
from ai_inspector.facility_layout.obstacle_map import GRID_CLEARANCES, ObstacleMap
from ai_inspector.facility_layout.spatial import _rotate_vector
from ai_inspector.industrial_assets import shape_families as families
from ai_inspector.industrial_assets.primitives import size_of
from ai_inspector.industrial_assets.shape_preview import preview
from tests.test_authored_assets_live import project
from tests.test_facility_operation_proposals import apply, approve

ZONES = [("zn-bay", "Bay", "workcell", (0, 0, 40, 10)), ("zn-aisle", "Cross aisle", "aisle", (18, 0, 22, 30)),
         ("zn-walk", "Walkway", "aisle", (0, 14, 40, 16))]     # on the starter floor, 40 x 30 m


def zone_op(zone_id, label, kind, box):
    x0, z0, x1, z1 = box
    return {"op": "add_zone", "zone": {"zoneId": zone_id, "label": label, "zoneType": kind, "floorElevation": 0.0,
                                       "anchors": [], "evidence": [], "boundary": [
                                           {"x": x0, "z": z0}, {"x": x1, "z": z0}, {"x": x1, "z": z1},
                                           {"x": x0, "z": z1}]}}


def layout_with(zones):
    return {"zones": [zone_op(*zone)["zone"] for zone in zones], "placements": []}


@pytest.fixture
def host(tmp_path):
    live = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=True, private_asset_root=project(tmp_path))
    live.ensure_bootstrap()
    principal = live.principal()
    saved = live.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    live.service.apply_operations(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, saved["revision"],
                                  [zone_op(*zone) for zone in ZONES])
    try:
        yield live
    finally:
        live.close()


def saved(host):
    return host.service.get_layout(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID)


def gateway(host, turn="shapes"):
    return FacilityEditGateway(host.agent_runtime, host.principal(), {
        "siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": saved(host)["revision"]}, turn_id=turn)


def plan_and_apply(host, tool, arguments, turn):
    """One Sage turn: plan, stage the package for review, then the user's approval and apply."""
    sage = gateway(host, turn)
    before = saved(host)
    planned = asyncio.run(sage.call(tool, arguments))
    assert planned["ok"], planned
    assert saved(host) == before                     # planning never changes the layout
    staged = asyncio.run(sage.call("preview_planned_design", {"packageId": planned["data"]["package"]["packageId"]}))
    assert staged["ok"], staged
    introduced = staged["data"]["validation"]["introduced"]
    assert introduced["spatial"]["errorCount"] == 0, staged["data"]["validation"]
    proposal_id = staged["data"]["proposalId"]
    principal = host.principal()
    alternative = host.service.get_layout_proposal_preview(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID,
                                                           proposal_id)["alternative"]
    proposal, context = {"proposalId": proposal_id, "alternative": alternative}, (host.service, principal)
    key = f"shapes-test-{turn}"
    layout = apply(context, proposal, approve(context, proposal, key=key), key=key)["layout"]
    return planned["data"], layout


def fake_author(family, parameters):
    """What register_authored_asset returns, without the library."""
    record, values = families.resolve(family, parameters)
    size = size_of(families.model(family, parameters))
    return {"assetId": families.asset_id(family, parameters), "assetDefinitionRevision": "rev-test",
            "displayName": record.title(values), "category": record.category, "tags": list(record.tags),
            "dimensions": {key: round(value, 4) for key, value in size.items()}, "triangles": 0, "added": True}


def plan(tool, arguments, zones=ZONES):
    return shapes.plan(tool, layout_with(zones), arguments, revision="r1", author=fake_author)


def test_the_edit_gateway_offers_the_shape_tools_and_the_read_gateway_does_not(host):
    names = {spec["name"] for spec in gateway(host).specs}
    assert set(shapes.NAMES) <= names
    reader = FacilityReadGateway(host.agent_runtime, host.principal(), {
        "siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": saved(host)["revision"]}, turn_id="read")
    assert not set(shapes.NAMES) & {spec["name"] for spec in reader.specs}
    author_spec = next(spec for spec in shapes.tool_specs() if spec["name"] == shapes.AUTHOR_TOOL)
    assert all(name in author_spec["description"] for name in families.FAMILIES)
    assert all(ord(c) < 128 for spec in shapes.tool_specs() for c in spec["description"])


def test_author_shape_asset_adds_the_model_and_returns_its_picture(host):
    sage = gateway(host)
    before = saved(host)
    made = asyncio.run(sage.call(shapes.AUTHOR_TOOL, {"family": "bollard", "parameters": {"heightMeters": 1.4}}))
    assert made["ok"], made
    data = made["data"]
    assert data["assetId"].startswith("asset-authored-bollard-1400x168mm-")
    assert data["dimensions"]["height"] == 1.4 and data["parameters"]["color"] == "#f5c400"
    assert data["library"].startswith("added") and "not a certified product" in data["illustrative"]
    picture = sage.take_image()
    assert picture["mimeType"] == "image/jpeg" and sage.take_image() is None      # handed out once
    image = Image.open(io.BytesIO(base64.b64decode(picture["data"])))
    assert image.size == (640, 400) and len(set(image.convert("L").getdata())) > 20
    again = asyncio.run(sage.call(shapes.AUTHOR_TOOL, {"family": "bollard", "parameters": {"heightMeters": 1.4}}))
    assert again["data"]["assetId"] == data["assetId"] and again["data"]["library"].startswith("already")
    assert saved(host) == before
    refused = asyncio.run(sage.call(shapes.AUTHOR_TOOL, {"family": "bollard", "parameters": {"heightMeters": 9}}))
    assert not refused["ok"] and "heightMeters" in refused["error"]["message"]
    assert refused["error"]["code"] == "shape_plan_refused"


def test_without_the_private_library_the_tools_say_so(tmp_path):
    plain = LocalFacilityLayoutHost(tmp_path / "facility-plain", private_assets=False)
    plain.ensure_bootstrap()
    try:
        refused = asyncio.run(gateway(plain).call(shapes.AUTHOR_TOOL, {"family": "bin"}))
        assert not refused["ok"] and refused["error"]["code"] == "authored_assets_unavailable"
    finally:
        plain.close()


def test_a_long_model_s_picture_shows_its_first_stretch():
    picture, shown = preview("i_beam", {"lengthMeters": 300})
    assert shown["shownLengthMeters"] == 4.5 and picture[:2] == b"\xff\xd8"
    assert "shownLengthMeters" not in preview("tank")[1]


def test_a_line_runs_along_its_direction_as_the_engine_turns_it():
    result = plan(shapes.LINE_TOOL, {"family": "i_beam", "elevationMeters": 10.002,
                                     "lines": [{"from": {"x": 0, "z": 0}, "to": {"x": 6, "z": 8}}]}, zones=[])
    placement = result["operations"][0]["placement"]
    q = placement["transform"]["quaternion"]
    assert math.isclose(q["x"] ** 2 + q["y"] ** 2 + q["z"] ** 2 + q["w"] ** 2, 1.0, abs_tol=1e-12)
    x, _, z = _rotate_vector((1.0, 0.0, 0.0), (q["x"], q["y"], q["z"], q["w"]))
    assert math.isclose(x, 0.6, abs_tol=1e-9) and math.isclose(z, 0.8, abs_tol=1e-9)
    assert placement["transform"]["position"] == {"x": 3.0, "y": 10.002, "z": 4.0}
    assert placement["positionMode"] == "locked" and result["models"][0]["dimensions"]["width"] == 10.0
    assert result["zones"] == "overhead: no floor zone needed" and not result["gaps"]


def test_barriers_along_a_walkway_stop_at_the_aisle_and_get_strips(host):
    data, layout = plan_and_apply(host, shapes.LINE_TOOL, {"family": "pedestrian_barrier", "lines": [
        {"from": {"x": 1, "z": 16}, "to": {"x": 39, "z": 16}, "side": "left", "label": "Walkway north edge"},
        {"from": {"x": 1, "z": 14}, "to": {"x": 39, "z": 14}, "side": "right", "label": "Walkway south edge"}]},
        "barriers")
    assert data["placed"] == 4 and len(data["models"]) == 1          # one model for the four 16.95 m pieces
    assert data["models"][0]["dimensions"]["width"] == 16.95
    assert [gap["inTheWay"] for gap in data["gaps"]] == [["aisle zone 'Cross aisle'"]] * 2
    assert data["gaps"][0]["from"] == {"x": 17.95, "z": 16.17} and data["gaps"][0]["to"] == {"x": 22.05, "z": 16.17}
    assert data["pieces"][0]["label"] == "Walkway north edge (part 1 of 2)"
    assert data["zones"].startswith("4 thin floor-coloured workcell strips added (#a9adab)")
    placed = [item for item in layout["placements"] if item["placementId"].startswith("pl-line-")]
    assert sorted(round(item["transform"]["position"]["z"], 2) for item in placed) == [13.83, 13.83, 16.17, 16.17]
    strips = [zone for zone in layout["zones"] if zone["zoneId"].startswith("zn-line-")]
    assert len(strips) == 4 and all(zone["extensions"]["style"]["fillColor"] == "#a9adab" for zone in strips)
    assert all(zone["zoneType"] == "workcell" for zone in strips)


def test_a_column_grid_skips_points_reuses_zones_and_strips_its_rows(host):
    data, layout = plan_and_apply(host, shapes.GRID_TOOL, {
        "x": {"from": 5, "to": 35, "every": 10}, "z": {"at": [25, 5, 20]}, "skip": ["C-4", "b1"]}, "grid")
    assert [line["name"] for line in data["lines"]["z"]] == ["A", "B", "C"]
    assert data["lines"]["z"][0]["z"] == 5 and data["lines"]["x"][-1] == {"name": "4", "x": 35.0}
    assert data["points"] == 12 and data["placed"] == 10 and data["skipped"] == ["B-1", "C-4"]
    assert data["zones"] == ("4 thin floor-coloured workcell strips added (#a9adab), as no zone held those items; "
                             "already inside Bay (4)")
    columns = {item["metadata"]["instanceLabel"]: item for item in layout["placements"]
               if item["placementId"].startswith("pl-grid-")}
    assert len(columns) == 10 and "Column A-1" in columns and "Column B-1" not in columns
    assert columns["Column C-3"]["transform"]["position"] == {"x": 25.0, "y": 0.0, "z": 25.0}
    assert columns["Column C-3"]["positionMode"] == "locked"
    strips = sorted(zone["label"] for zone in layout["zones"] if zone["zoneId"].startswith("zn-grid-"))
    assert strips == ["Column strip B (1)", "Column strip B (2)", "Column strip C (1)", "Column strip C (2)"]
    # The strips stop short of the cross aisle on either side.
    for zone in layout["zones"]:
        if zone["zoneId"].startswith("zn-grid-"):
            xs = [point["x"] for point in zone["boundary"]]
            assert max(xs) < 18 or min(xs) > 22


def test_a_roof_frame_stacks_girders_and_joists_2_mm_apart(host):
    plan_and_apply(host, shapes.GRID_TOOL, {"x": {"from": 5, "to": 35, "every": 10}, "z": {"at": [5, 20, 25]}},
                   "columns")
    data, layout = plan_and_apply(host, shapes.ROOF_TOOL, {
        "area": {"west": 0, "east": 40, "south": 0, "north": 30}, "supportTopMeters": 10,
        "girders": {"at": [5, 20, 25]}}, "roof")
    assert data["girders"]["count"] == 3 and data["girders"]["bottomMeters"] == 10.002
    assert data["girders"]["topMeters"] == 10.902 and data["joists"]["bottomMeters"] == 10.904
    assert data["joists"]["count"] == 13 and data["joists"]["firstX"] == 2 and data["joists"]["lastX"] == 38
    assert data["girders"]["model"]["dimensions"]["width"] == 40.0
    assert data["joists"]["model"]["dimensions"]["width"] == 30.0
    roof = [item for item in layout["placements"] if item["placementId"].startswith("pl-roof-")]
    assert len(roof) == 16
    joist = next(item for item in roof if item["metadata"]["instanceLabel"] == "Roof joist 1")
    assert joist["transform"]["position"] == {"x": 2.0, "y": 10.904, "z": 15.0}
    q = joist["transform"]["quaternion"]
    x, _, z = _rotate_vector((1.0, 0.0, 0.0), (q["x"], q["y"], q["z"], q["w"]))
    assert abs(x) < 1e-9 and math.isclose(abs(z), 1.0)                # joists run north-south
    assert not [zone for zone in layout["zones"] if zone["zoneId"].startswith("zn-roof-")]


def test_a_layout_without_operational_zones_gets_no_strips():
    result = plan(shapes.LINE_TOOL, {"family": "low_traffic_barrier", "lines": [
        {"from": {"x": 1, "z": 25}, "to": {"x": 15, "z": 25}}]}, zones=[ZONES[1]])
    assert result["zones"].startswith("this layout has no workcell") and result["placed"] == 1
    assert all(operation["op"] == "place_asset" for operation in result["operations"])


def test_the_summary_names_at_most_eight_zones_that_hold_items():
    cells = [(f"zn-cell-{k}", f"Cell {k}", "workcell", (2 * k, 20, 2 * k + 1.5, 22)) for k in range(10)]
    result = plan(shapes.GRID_TOOL, {"family": "bollard", "x": {"at": [2 * k + 0.75 for k in range(10)]},
                                     "z": {"at": [21]}}, zones=cells)
    assert result["zones"] == ("already inside Cell 0 (1), Cell 1 (1), Cell 2 (1), Cell 3 (1), Cell 4 (1), Cell 5 (1), "
                               "Cell 6 (1), Cell 7 (1) and 2 more zones (2 items)")
    assert all(operation["op"] == "place_asset" for operation in result["operations"])


def test_a_run_inside_a_walkway_and_a_grid_point_in_an_aisle_are_named():
    with pytest.raises(shapes.ShapeError, match="Walkway: blocked all along by aisle zone 'Walkway'"):
        plan(shapes.LINE_TOOL, {"family": "guard_rail", "lines": [
            {"from": {"x": 1, "z": 15}, "to": {"x": 15, "z": 15}, "label": "Walkway"}]})
    result = plan(shapes.GRID_TOOL, {"family": "bollard", "x": {"at": [10, 20]}, "z": {"at": [25]}})
    assert result["dropped"] == [{"point": "A-2", "x": 20.0, "z": 25.0, "reasons": ["in aisle zone 'Cross aisle'"]}]
    assert result["placed"] == 1 and result["leftOut"] == 1


def test_what_the_tools_refuse():
    line = {"from": {"x": 1, "z": 25}, "to": {"x": 15, "z": 25}}
    cases = [
        (shapes.LINE_TOOL, {"family": "cable_tray", "elevationMeters": 2, "lines": [line]}, "need something to stand on"),
        (shapes.LINE_TOOL, {"family": "i_beam", "lines": [{"from": {"x": 0, "z": 0}, "to": {"x": 0.2, "z": 0}}]},
         "at least 0.5 m"),
        (shapes.LINE_TOOL, {"family": "i_beam", "lines": [{"from": {"x": 0, "z": 0}, "to": {"x": 401, "z": 0}}]},
         "split it"),
        (shapes.LINE_TOOL, {"family": "pedestrian_barrier", "parameters": {"lengthMeters": 4}, "lines": [line]},
         "Leave lengthMeters out"),
        (shapes.LINE_TOOL, {"family": "pedestrian_barrier", "parameters": {"heightMeters": 3}, "lines": [line]},
         "heightMeters"),
        (shapes.LINE_TOOL, {"family": "tank", "lines": [line]}, "use place_grid"),
        (shapes.GRID_TOOL, {"x": {"at": [1, 2]}, "z": {"at": [1]}, "skip": ["Z-9"]}, "No grid point 'Z-9'"),
        (shapes.GRID_TOOL, {"x": {"at": [1, 1.001]}, "z": {"at": [1]}}, "two lines"),
        (shapes.GRID_TOOL, {"x": {"at": [1], "from": 0, "to": 5, "every": 1}, "z": {"at": [1]}}, "not both"),
        (shapes.GRID_TOOL, {"x": {"from": 0, "to": 39, "every": 1}, "z": {"from": 0, "to": 39, "every": 1},
                            "elevationMeters": 8, "family": "high_bay_lights"}, "one apply takes at most 500"),
        (shapes.GRID_TOOL, {"family": "bollard", "x": {"from": 1, "to": 25, "every": 1},
                            "z": {"from": 1, "to": 21, "every": 1}}, "That is 525 operations; one apply takes at most 500"),
        (shapes.GRID_TOOL, {"x": {"at": [1, 2], "names": ["A", "a"]}, "z": {"at": [1]}},
         "the names 'A' and 'a' differ only in case"),
        (shapes.ROOF_TOOL, {"area": {"west": 0, "east": 40, "south": 0, "north": 30}, "supportTopMeters": 10,
                            "girders": {"at": [5, 10], "names": ["G", "g"]}}, "differ only in case"),
        (shapes.ROOF_TOOL, {"area": {"west": 0, "east": 40, "south": 0, "north": 30}, "supportTopMeters": 3,
                            "girders": {"at": [5]}}, "at least 4.5 m high"),
        (shapes.ROOF_TOOL, {"area": {"west": 0, "east": 40, "south": 0, "north": 30}, "supportTopMeters": 10,
                            "girders": {"at": [35]}}, "outside the area"),
        (shapes.ROOF_TOOL, {"area": {"west": 0, "east": 450, "south": 0, "north": 40}, "supportTopMeters": 10,
                            "girders": {"at": [5]}}, "split the area"),
    ]
    for tool, arguments, message in cases:
        with pytest.raises(shapes.ShapeError, match=message):
            plan(tool, arguments)


def test_the_chat_names_each_step():
    assert describe(shapes.AUTHOR_TOOL, {"family": "open_web_joist"})["running"] == "Building an open-web joist model"
    assert describe(shapes.LINE_TOOL, {"family": "pedestrian_barrier", "lines": [{}, {}]})["done"] == (
        "Planned pedestrian barriers along 2 lines")
    assert describe(shapes.GRID_TOOL, {})["running"] == "Planning a grid of steel columns"
    assert describe(shapes.ROOF_TOOL, {})["running"] == "Planning the roof frame"


def test_items_in_zones_whose_rules_they_break_are_refused_not_given_strips():
    """A strip of its own would get an item past a zone's height limit, categories or edge setback (Codex review)."""
    def ruled(zone_id, label, box, **rules):
        return dict(zone_op(zone_id, label, "workcell", box)["zone"], **rules)
    layout = {"placements": [], "zones": [
        ruled("zn-low", "Mezzanine bay", (0, 20, 10, 30), heightLimit=3.0),
        ruled("zn-machines", "Machine cell", (20, 20, 30, 30), allowedAssetCategories=["Machines"]),
        ruled("zn-kept", "Kept bay", (32, 20, 40, 30), edgeSetbacks={"east": 1.0}),
        zone_op(*ZONES[0])["zone"]]}
    with pytest.raises(shapes.ShapeError, match=re.escape(
            "Column A-1: zone 'Mezzanine bay' has a 3 m height limit; the item is 10 m high")):
        shapes.plan(shapes.GRID_TOOL, layout, {"x": {"at": [5]}, "z": {"at": [25]}}, revision="r1", author=fake_author)
    category = families.FAMILIES["pedestrian_barrier"].category
    with pytest.raises(shapes.ShapeError, match=re.escape(f"Rail: zone 'Machine cell' takes only Machines, not "
                                                          f"{category}")):
        shapes.plan(shapes.LINE_TOOL, layout, {"family": "pedestrian_barrier", "lines": [
            {"from": {"x": 21, "z": 25}, "to": {"x": 29, "z": 25}, "label": "Rail"}]}, revision="r1",
            author=fake_author)
    with pytest.raises(shapes.ShapeError, match=re.escape("Bollard A-1: zone 'Kept bay' keeps items 1 m inside")):
        shapes.plan(shapes.GRID_TOOL, layout, {"family": "bollard", "x": {"at": [39.5]}, "z": {"at": [25]}},
                    revision="r1", author=fake_author)
    # Unzoned floor, and a zone without rules an item only partly stands in, still get strips.
    result = shapes.plan(shapes.GRID_TOOL, layout, {"x": {"at": [5, 15]}, "z": {"at": [10, 12]}}, revision="r1",
                         author=fake_author)     # row A straddles the Bay's edge, row B is unzoned
    assert result["placed"] == 4 and result["zones"].startswith("3 thin floor-coloured workcell strips added")


LONG_RUNS = [{"from": {"x": 0, "z": 0.5 * k}, "to": {"x": float(k), "z": 0.5 * k},
              "label": f"Barrier run number {k:03d} along the north side of the hall"} for k in range(1, 201)]


def test_a_big_plan_s_summary_fits_in_one_tool_result_and_its_package_keeps_everything():
    """200 lines of 200 lengths make 200 models; the summary lists a few and counts the rest (Codex review)."""
    result = plan(shapes.LINE_TOOL, {"family": "pedestrian_barrier", "lines": LONG_RUNS}, zones=[])
    assert len(result["operations"]) == 200
    assert len(result["models"]) == shapes.MODELS_LISTED and result["moreModels"] == 200 - shapes.MODELS_LISTED
    assert len(result["pieces"]) + result["morePieces"] == 200
    summary = {key: value for key, value in result.items() if key != "operations"}
    assert len(json.dumps(summary)) <= shapes.RESULT_BUDGET


def test_a_summary_over_its_budget_is_shortened_longest_list_first(monkeypatch):
    monkeypatch.setattr(shapes, "RESULT_BUDGET", 4000)
    result = plan(shapes.LINE_TOOL, {"family": "pedestrian_barrier", "lines": LONG_RUNS[:60]}, zones=[])
    assert len(result["operations"]) == 60
    assert len(result["pieces"]) + result.get("morePieces", 0) == 60
    assert len(result["models"]) + result.get("moreModels", 0) == 60
    assert len(json.dumps({key: value for key, value in result.items() if key != "operations"})) <= 4000


# --- BS4: clearance-aware placement ---

LATHE = {"assetId": "asset-test-lathe", "assetDefinitionRevision": "r1", "displayName": "Test lathe",
         "geometry": {"obb": {"center": {"x": 0, "y": 1, "z": 0}, "size": {"x": 3, "y": 2, "z": 2}}},
         "clearances": [{"clearanceId": "svc", "clearanceKind": "service",
                         "geometry": {"minimum": {"x": -1.5, "z": 1.0}, "maximum": {"x": 1.5, "z": 2.5}}}]}
LIGHT_ROW = {"assetId": "asset-test-light-row", "assetDefinitionRevision": "r1", "displayName": "Light row",
             "geometry": {"obb": {"center": {"x": 0, "y": 0, "z": 0}, "size": {"x": 30, "y": 0.4, "z": 0.3}}}}


def placed(placement_id, asset, x, y, z, label):
    return {"placementId": placement_id, "assetId": asset["assetId"], "assetDefinitionRevision": "r1",
            "transform": {"position": {"x": x, "y": y, "z": z}, "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1},
                          "scale": 1}, "metadata": {"instanceLabel": label}}


def aisle(label, kind, points, width):
    return {"routeId": "rt-" + label.lower(), "label": label, "corridorWidth": width,
            "centerline": [{"x": x, "y": 0.0, "z": z} for x, z in points],
            "extensions": {"facilityAisle": {"aisleKind": kind}}}


def scene():
    """On the 40 x 30 m floor: a lathe with a service envelope in the bay, a light row hanging at 8 m, a forklift
    aisle along z 20, two walkways, the cross aisle zone, a keep-clear box and a 3 m interior wall."""
    layout = {
        "placements": [placed("pl-lathe", LATHE, 10, 0, 5, "Lathe 1"), placed("pl-lights", LIGHT_ROW, 20, 8, 25,
                                                                               "Light row 1")],
        "routes": [aisle("Boulevard", "forklift", [(0, 20), (40, 20)], 3.0),
                   aisle("Footpath", "pedestrian", [(30, 0), (30, 12)], 1.2),
                   aisle("Crossing", "pedestrian", [(28, 24), (28, 30)], 1.2)],
        "zones": [zone_op(*ZONES[0])["zone"], zone_op(*ZONES[1])["zone"]],
        "floorMarkings": [{"markingId": "fm-panel", "markingType": "keep_clear", "label": "Panel", "width": 2,
                           "depth": 1, "transform": {"position": {"x": 2.5, "y": 0, "z": 25}, "rotationDegrees": 0}}],
    }
    floor = [{"x": 0, "z": 0}, {"x": 40, "z": 0}, {"x": 40, "z": 30}, {"x": 0, "z": 30}]
    wall = [{"x": 35, "z": 0}, {"x": 35.2, "z": 0}, {"x": 35.2, "z": 8}, {"x": 35, "z": 8}]
    shell = {"features": [
        {"featureId": "floor-main", "featureKind": "floor_surface", "geometry": {"boundary": floor, "elevation": 0}},
        {"featureId": "layout-interior-wall-iw-office-0", "featureKind": "wall",
         "geometry": {"boundary": wall, "elevation": 0.0, "height": 3.0}}]}
    definitions = {("asset-test-lathe", "r1"): LATHE, ("asset-test-light-row", "r1"): LIGHT_ROW}
    return layout, ObstacleMap(layout, shell=shell, asset_definitions=definitions)


def column(x, z, half=0.25):
    return box(x - half, z - half, x + half, z + half)


def test_the_obstacle_map_says_why_a_column_cannot_stand_somewhere():
    _, obstacles = scene()
    expected = {
        (10, 5): ["on Lathe 1"],
        (11.85, 5): ["0.10 m from Lathe 1 (keeps 0.25 m)"],
        (12.1, 5): [],
        (10, 6.8): ["in the service clearance of Lathe 1"],
        (11.6, 6.1): ["on Lathe 1", "in the service clearance of Lathe 1"],
        (5, 20): ["in forklift aisle 'Boulevard'"],
        (5, 17.95): ["0.30 m from forklift aisle 'Boulevard' (keeps 0.5 m)"],
        (5, 17.6): [],
        (30, 6): ["in walkway 'Footpath'"],
        (28.9, 6): [],                                  # walkways: out of them is enough
        (20, 5): ["in aisle zone 'Cross aisle'"],
        (2.5, 25): ["on keep clear marking 'Panel'"],
        (35.1, 4): ["on interior wall iw-office"],
        (34.65, 4): ["0.10 m from interior wall iw-office (keeps 0.25 m)"],
        (39.9, 12): ["off the floor"],
        (25, 25): ["on Light row 1"],                    # a 10 m column meets the light row at 8 m
    }
    for (x, z), reasons in expected.items():
        assert obstacles.reasons(column(x, z), 0.0, 10.0, GRID_CLEARANCES) == reasons, (x, z)
    assert obstacles.reasons(column(25, 25), 0.0, 1.2) == []                # a bollard passes under it
    assert obstacles.reasons(column(5, 20), 9.0, 9.5) == []                  # overhead: no aisles, zones or floor
    assert obstacles.reasons(column(39.9, 12), 9.0, 9.5) == []
    assert obstacles.reasons(column(25, 25), 7.9, 8.4) == ["on Light row 1"]
    assert obstacles.reasons(column(35.1, 4), 7.9, 8.4) == []                # above the 3 m wall


def test_a_grid_leaves_out_points_in_the_way_and_its_strips_stop_at_walkways():
    layout, obstacles = scene()
    result = shapes.plan(shapes.GRID_TOOL, layout, {"x": {"at": [5, 10, 25, 30]}, "z": {"at": [5, 20, 27]},
                                                    "planImage": True},
                         revision="r1", author=fake_author, obstacles=obstacles)
    assert result["points"] == 12 and result["placed"] == 6 and result["leftOut"] == 6
    assert {item["point"]: item["reasons"] for item in result["dropped"]} == {
        "A-2": ["on Lathe 1"], "A-4": ["in walkway 'Footpath'"],
        **{f"B-{n}": ["in forklift aisle 'Boulevard'"] for n in range(1, 5)}}
    assert [item["name"] for item in result["items"]] == ["A-1", "A-3", "C-1", "C-2", "C-3", "C-4"]
    assert "0.5 m from forklift and material aisles" in result["clearances"]
    strips = [op["zone"] for op in result["operations"] if op["op"] == "add_zone"]
    assert [zone["label"] for zone in strips] == ["Column strip C (1)", "Column strip C (2)", "Column strip C (3)"]
    crossing = box(27.4, 24, 28.6, 30)
    for zone in strips:                                  # never across the walkway or the cross aisle
        shape = Polygon([(point["x"], point["z"]) for point in zone["boundary"]])
        assert not shape.intersects(crossing) and not shape.intersects(box(18, 0, 22, 30))
    assert result["zones"].startswith("3 thin floor-coloured workcell strips") and "Bay (2)" in result["zones"]
    image = result["_image"]
    picture = Image.open(io.BytesIO(base64.b64decode(image["data"]))).convert("RGB")
    assert image["mimeType"] == "image/png" and picture.size == (1100, 760)
    colours = set(picture.getdata())
    assert (31, 41, 51) in colours and any(r > 200 and g < 70 and b < 70 for r, g, b in colours)   # placed, left out
    with pytest.raises(shapes.ShapeError, match="Something is in the way at every grid point: A-1 in forklift"):
        shapes.plan(shapes.GRID_TOOL, layout, {"x": {"at": [5, 10]}, "z": {"at": [20]}}, revision="r1",
                    author=fake_author, obstacles=obstacles)


def test_runs_stop_short_of_items_and_overhead_runs_of_what_their_height_meets():
    layout, obstacles = scene()
    floor = shapes.plan(shapes.LINE_TOOL, layout, {"family": "pedestrian_barrier", "lines": [
        {"from": {"x": 1, "z": 5}, "to": {"x": 30, "z": 5}, "label": "Bay barrier"}]},
        revision="r1", author=fake_author, obstacles=obstacles)
    assert [(gap["from"]["x"], gap["to"]["x"], gap["inTheWay"]) for gap in floor["gaps"]] == [
        (8.45, 11.55, ["Lathe 1"]), (17.95, 22.05, ["aisle zone 'Cross aisle'"]),
        (29.35, 30.0, ["walkway 'Footpath'"])]              # the walkway route at x 30 crosses the run's end
    assert floor["placed"] == 3 and floor["pieces"][-1]["lengthMeters"] == 7.3
    across = shapes.plan(shapes.LINE_TOOL, layout, {"family": "pedestrian_barrier", "lines": [
        {"from": {"x": 24, "z": 5}, "to": {"x": 34, "z": 5}, "label": "Across the footpath"}]},
        revision="r1", author=fake_author, obstacles=obstacles)   # an opening where the walkway crosses it
    assert [(gap["from"]["x"], gap["to"]["x"], gap["inTheWay"]) for gap in across["gaps"]] == [
        (29.35, 30.65, ["walkway 'Footpath'"])]
    assert [piece["lengthMeters"] for piece in across["pieces"]] == [5.35, 3.35]
    overhead = shapes.plan(shapes.LINE_TOOL, layout, {"family": "cable_tray", "elevationMeters": 7.6, "lines": [
        {"from": {"x": 0.5, "z": 25}, "to": {"x": 39.5, "z": 25}, "label": "Tray"}]},
        revision="r1", author=fake_author, obstacles=obstacles)
    assert [(gap["from"]["x"], gap["to"]["x"], gap["inTheWay"]) for gap in overhead["gaps"]] == [
        (4.95, 35.05, ["Light row 1"])]                   # the keep-clear box below does not count up there
    assert [piece["lengthMeters"] for piece in overhead["pieces"]] == [4.45, 4.45]


def test_a_column_grid_keeps_clear_of_items_and_aisles_on_a_live_host(host):
    principal = host.principal()
    bench = host.register_authored_asset("workbench", {})
    host.service.apply_operations(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, saved(host)["revision"], [
        {"op": "place_asset", "placement": {
            "placementId": "pl-bench", "assetId": bench["assetId"],
            "assetDefinitionRevision": bench["assetDefinitionRevision"],
            "transform": {"position": {"x": 10.0, "y": 0.0, "z": 5.0},
                          "quaternion": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}, "scale": 1},
            "positionMode": "manual", "snapRelationship": None, "metadata": {"instanceLabel": "Bench 1"}}},
        {"op": "add_aisle", "aisle": {"label": "Test boulevard", "aisleKind": "forklift", "direction": "two_way",
                                      "color": "#d9a514", "corridorWidth": 3.0, "clearanceEvidenceStatus": "unverified",
                                      "centerline": [{"x": 0.0, "y": 0.0, "z": 22.0}, {"x": 40.0, "y": 0.0, "z": 22.0}]}},
        {"op": "add_aisle", "aisle": {"label": "Test walkway", "aisleKind": "pedestrian", "direction": "two_way",
                                      "color": "#2f80ed", "corridorWidth": 1.2, "clearanceEvidenceStatus": "unverified",
                                      "centerline": [{"x": 30.0, "y": 0.0, "z": 17.0}, {"x": 30.0, "y": 0.0, "z": 30.0}]}}])
    sage = gateway(host, "bs4")
    planned = asyncio.run(sage.call(shapes.GRID_TOOL, {"x": {"at": [5, 10, 30, 35]}, "z": {"at": [5, 22, 26]},
                                                       "planImage": True}))
    assert planned["ok"], planned
    data = planned["data"]
    assert {item["point"]: item["reasons"][0] for item in data["dropped"]} == {
        "A-2": "on Bench 1", "C-3": "in walkway 'Test walkway'",
        **{f"B-{n}": "in forklift aisle 'Test boulevard'" for n in range(1, 5)}}
    assert data["placed"] == 6 and data["picture"].startswith("attached")
    picture = sage.take_image()
    assert picture["mimeType"] == "image/png" and sage.take_image() is None
    staged = asyncio.run(sage.call("preview_planned_design", {"packageId": data["package"]["packageId"]}))
    assert staged["ok"], staged
    introduced = staged["data"]["validation"]["introduced"]["spatial"]
    assert introduced["errorCount"] == 0 and introduced["obstructedAisleCount"] == 0, introduced
    assert introduced["clearanceConflicts"] == 0 and introduced["placementCollisions"] == 0
