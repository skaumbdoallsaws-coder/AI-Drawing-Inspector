"""Basic shapes BS3 (docs/sage-basic-shapes-plan.md): Sage's tools. author_shape_asset adds one model to the shared
library and returns its picture; place_along_line, place_grid and roof_frame plan packages that
preview_planned_design stages, which the engine accepts and applies."""
from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import re

import pytest
from PIL import Image

from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway
from ai_inspector.codex_runtime.facility_tools import FacilityReadGateway
from ai_inspector.codex_runtime.progress import describe
from ai_inspector.facility_layout import sage_shapes as shapes
from ai_inspector.facility_layout.host import LOCAL_LAYOUT_ID, LOCAL_SITE_ID, LocalFacilityLayoutHost
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
    assert [gap["zones"] for gap in data["gaps"]] == [["Cross aisle"], ["Cross aisle"]]
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
    with pytest.raises(shapes.ShapeError, match="Walkway: it runs inside Walkway all along"):
        plan(shapes.LINE_TOOL, {"family": "guard_rail", "lines": [
            {"from": {"x": 1, "z": 15}, "to": {"x": 15, "z": 15}, "label": "Walkway"}]})
    result = plan(shapes.GRID_TOOL, {"family": "bollard", "x": {"at": [10, 20]}, "z": {"at": [25]}})
    assert result["standInNoPlacementZones"] == [{"point": "A-2", "zone": "Cross aisle"}]
    assert "skip" in result["note"]


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
