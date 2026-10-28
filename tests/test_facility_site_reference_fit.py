"""The fit check: the road map against the photo, and the plan dropped onto surveyed points (reference plan, R3)."""
from copy import deepcopy
import math

import pytest
from PIL import Image, ImageDraw

from ai_inspector.codex_runtime.progress import SIMPLE
from ai_inspector.codex_runtime.site_tools import NAMES, read_site, tool_specs
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.facility_layout.site_context import KEY, building_outline
from ai_inspector.facility_layout.site_reference_fit import check_references, photo_vs_map, rigid_fit, survey_fit
from ai_inspector.facility_layout.site_references import compass
from ai_inspector.facility_layout.site_trace import _Photo
from tests.test_facility_site_references import CORNER, lot_with_pavement


def test_the_fit_recovers_a_move_and_turn_and_one_pair_only_moves():
    turn, move = math.radians(1.5), (2.0, -1.0)
    points = [(0.0, 0.0), (100.0, 0.0), (100.0, 60.0), (0.0, 60.0)]
    moved = [(x * math.cos(turn) - z * math.sin(turn) + move[0], x * math.sin(turn) + z * math.cos(turn) + move[1])
             for x, z in points]
    fit = rigid_fit(list(zip(points, moved)))
    assert fit["rotationDegrees"] == pytest.approx(1.5) and fit["worstMeters"] < 1e-9
    expected = (50 * math.cos(turn) - 30 * math.sin(turn) + move[0], 50 * math.sin(turn) + 30 * math.cos(turn) + move[1])
    assert fit["apply"]((50.0, 30.0)) == pytest.approx(expected)  # any point maps as the plan would on the ground
    single = rigid_fit([((5.0, 5.0), (6.0, 4.0))])
    assert single["rotationDegrees"] == 0 and single["apply"]((0.0, 0.0)) == pytest.approx((1.0, -1.0))
    assert rigid_fit([]) is None


def surveyed(doc, site, shift):
    """The lot's reference points with measured positions shifted by `shift`, as a survey might find them."""
    corners = [(0, 0), (140, 0), (140, 100), (0, 100)]
    references = [dict(CORNER, referenceId=f"rp-{i + 1}", x=x, z=z,
                       measured={"x": x + shift[0], "z": z + shift[1], "source": "survey"})
                  for i, (x, z) in enumerate(corners)]
    return apply_facility_layout_operations(deepcopy(doc), [{"op": "upsert_site_reference", "reference": r}
                                                            for r in references])["document"]


def test_surveyed_points_move_the_building_and_say_how_far():
    doc, site = lot_with_pavement()
    assert "pending" in survey_fit(site, doc)
    moved = surveyed(doc, site, (1.2, -0.5))
    fit = survey_fit(moved["extensions"][KEY], moved)
    assert fit["moveMeters"] == pytest.approx(1.3) and fit["moveDirection"] == compass(1.2, -0.5)
    assert fit["worstResidualMeters"] < 1e-6 and abs(fit["turnDegrees"]) < 1e-6
    outline = building_outline(moved, moved["extensions"][KEY])
    assert [c["movesMeters"] for c in fit["buildingCorners"]] == [pytest.approx(1.3)] * 4
    assert fit["buildingCorners"][0]["x"] == pytest.approx(outline[0]["x"] + 1.2)
    assert -90 < fit["buildingCorners"][0]["latitude"] < 90 and "note" not in fit


def synthetic_site(tmp_path, photo_offset=(-3.0, 2.0)):
    """A 300 m square photo of grass with two roads crossing, drawn `photo_offset` from where the map puts them,
    and a grey strip beside one road (like rail ballast) that the check must ignore."""
    size, extent = 400, 300.0
    scale = size / extent
    picture = Image.new("RGB", (size, size), (60, 120, 50))
    draw = ImageDraw.Draw(picture)
    px = lambda x: (x + extent / 2) * scale  # noqa: E731
    pz = lambda z: (extent / 2 - z) * scale  # noqa: E731
    ox, oz = photo_offset
    draw.rectangle((0, pz(oz + 4), size, pz(oz - 4)), fill=(110, 110, 110))   # east-west road, 8 m
    draw.rectangle((px(ox - 4), 0, px(ox + 4), size), fill=(110, 110, 110))   # north-south road, 8 m
    draw.rectangle((px(ox + 9), 0, px(ox + 13), size), fill=(150, 145, 140))  # a 4 m grey strip, 9 m east of it
    path = tmp_path / "photo.jpg"
    picture.save(path, quality=95)
    half = extent / 2
    image = {"imageId": "a" * 64, "source": "usgs_naip", "captured": "2021-06-18", "attribution": "USGS",
             "corners": [{"x": -half, "z": -half}, {"x": half, "z": -half}, {"x": half, "z": half}, {"x": -half, "z": half}]}
    roads = {"items": [{"kind": "local", "label": "Mill St", "line": [{"x": -140, "z": 0}, {"x": 140, "z": 0}]},
                       {"kind": "local", "label": "Main St", "line": [{"x": 0, "z": -140}, {"x": 0, "z": 140}]}]}
    return {"roads": roads}, _Photo(image, path)


def test_the_photo_shows_where_the_map_crossing_really_is(tmp_path):
    site, photo = synthetic_site(tmp_path)
    check = photo_vs_map(site, (0.0, 0.0), photo)
    [point] = check["points"]
    assert point["label"] == "Main St and Mill St intersection" and check["found"] == 1
    assert point["photo"]["x"] == pytest.approx(-3.0, abs=0.8) and point["photo"]["z"] == pytest.approx(2.0, abs=0.8)
    assert point["offsetMeters"] == pytest.approx(math.hypot(3, 2), abs=0.8) and "east" in point["mapIs"]


def test_a_crossing_the_photo_does_not_show_is_left_out_not_guessed(tmp_path):
    site, photo = synthetic_site(tmp_path, photo_offset=(-30.0, 2.0))  # the north-south road is nowhere near the map
    check = photo_vs_map(site, (0.0, 0.0), photo)
    assert check["found"] == 0 and check["points"][0]["photo"] is None and "clearly" in check["points"][0]["note"]


def test_sage_has_the_check_tool():
    spec = next(item for item in tool_specs() if item["name"] == "check_site_references")
    assert "check_site_references" in NAMES and "check_site_references" in SIMPLE
    assert "never a stretch" in spec["description"]
    doc, site = lot_with_pavement()
    result = read_site(doc, "check_site_references", {})  # no photo stored: the survey part still answers
    assert result["available"] and result["photoVsMap"]["found"] == 0 and "pending" in result["survey"]
    assert check_references(site, doc)["summary"] == []
