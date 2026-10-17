"""Contracts for the one-layout office authoring change."""
from copy import deepcopy
import math
import pytest

import tools.add_factory02_dispatch_office as tool


def inputs(monkeypatch):
    monkeypatch.setattr(tool, "layout_revision", lambda _doc: tool.BASE_REVISION)
    catalog = {aid: {"assetId": aid, "assetDefinitionRevision": "revision-" + aid,
                    "definition": {"readiness": {"placementReady": {"value": True}}}}
               for aid in tool.ASSET_IDS}
    catalog["asset-desk-1400-clear-wood"]["supportSurfaces"] = [{
        "surfaceId": "worktop", "evidenceStatus": "derived",
        "localFrame": {"origin": {"x": 0, "y": 0.727, "z": 0}},
    }]
    return {"layoutId": tool.LAYOUT_ID}, catalog


def test_reference_layout_is_not_a_valid_target():
    with pytest.raises(ValueError, match="has changed"):
        tool.require_base({"layoutId": tool.MANUAL_ID})


def test_stale_factory_is_not_a_valid_target(monkeypatch):
    monkeypatch.setattr(tool, "layout_revision", lambda _doc: "newer")
    with pytest.raises(ValueError, match="has changed"):
        tool.require_base({"layoutId": tool.LAYOUT_ID})


def test_fourteen_unique_revision_bound_items_and_one_zone_without_membership_writes(monkeypatch):
    doc, catalog = inputs(monkeypatch)
    before = deepcopy((doc, catalog))
    ops = tool.office_operations(doc, catalog)
    placements = [op["placement"] for op in ops if op["op"] == "place_asset"]
    assert len(placements) == len({p["placementId"] for p in placements}) == 14
    assert len([op for op in ops if op["op"] == "add_zone"]) == 1
    assert len([op for op in ops if op["op"] == "add_aisle"]) == 1
    assert all("zoneId" not in p for p in placements)
    assert all(p["assetDefinitionRevision"] == catalog[p["assetId"]]["assetDefinitionRevision"] for p in placements)
    assert (doc, catalog) == before
    assert ops == tool.office_operations(doc, catalog)


def test_desktop_items_use_each_own_explicit_worktop(monkeypatch):
    doc, catalog = inputs(monkeypatch)
    placements = [op["placement"] for op in tool.office_operations(doc, catalog) if op["op"] == "place_asset"]
    by_id = {p["placementId"]: p for p in placements}
    attached = [p for p in placements if p["snapRelationship"]]
    assert len(attached) == 8
    for p in attached:
        link = p["snapRelationship"]
        assert link["surfaceSource"] == "asset_definition"
        assert link["surfaceId"] == "worktop"
        assert link["evidenceStatus"] == "derived"
        assert p["transform"]["position"]["y"] == pytest.approx(0.727)
        desk = by_id[link["supportPlacementId"]]
        assert desk["placementId"].rsplit("-", 1)[0] == p["placementId"].rsplit("-", 1)[0]
        for axis in ("x", "z"):
            assert link["localPosition"][axis] == pytest.approx(
                p["transform"]["position"][axis] - desk["transform"]["position"][axis])


def test_chairs_face_negative_x_towards_desks(monkeypatch):
    doc, catalog = inputs(monkeypatch)
    chairs = [op["placement"] for op in tool.office_operations(doc, catalog)
              if op["op"] == "place_asset" and op["placement"]["assetId"] == "asset-chair-black"]
    assert len(chairs) == 2
    for p in chairs:
        q = p["transform"]["quaternion"]
        assert 2 * q["y"] * q["w"] == pytest.approx(-1)
        assert q["y"] == pytest.approx(math.sin(-math.pi / 4))


def test_pedestrian_connector_joins_existing_south_walkway(monkeypatch):
    doc, catalog = inputs(monkeypatch)
    route = tool.office_operations(doc, catalog)[-1]
    assert route["routeId"] == tool.ROUTE_ID
    assert route["aisle"]["aisleKind"] == "pedestrian"
    assert route["aisle"]["corridorWidth"] == 1.5
    assert route["aisle"]["centerline"][-1] == {"x": 62, "y": 0, "z": 93}
    assert route["aisle"]["clearanceEvidenceStatus"] == "unverified"


@pytest.mark.parametrize("aid", tool.ASSET_IDS)
def test_unready_furniture_is_rejected(monkeypatch, aid):
    doc, catalog = inputs(monkeypatch)
    catalog[aid]["definition"]["readiness"]["placementReady"]["value"] = False
    with pytest.raises(ValueError, match="not placement-ready"):
        tool.office_operations(doc, catalog)
