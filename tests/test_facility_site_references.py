"""Reference points: features a builder can find on site, kept in the site context and suggested from what the site
already holds (reference-points plan, R1 and R2)."""
import asyncio
from copy import deepcopy
import json
import math

import pytest

from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway
from ai_inspector.codex_runtime.edit_schemas import operation_batch_schema
from ai_inspector.codex_runtime.progress import SIMPLE
from ai_inspector.codex_runtime.site_tools import NAMES, read_site, tool_specs
from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.facility_layout.host import LOCAL_SITE_ID, LOCAL_LAYOUT_ID, LocalFacilityLayoutHost
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.facility_layout.site_context import KEY, building_outline, normalize_site_context, normalize_site_reference
from ai_inspector.facility_layout.site_references import compass, corners, suggest_references
from tests.test_facility_site_plan import ARTERIAL, RAIL, STREET, site_doc
from tests.test_facility_site_property import fixture

CORNER = {"referenceId": "rp-1", "label": "North-west property corner", "kind": "property_corner",
          "source": "county_parcel", "x": 0.12345, "z": 80, "accuracyMeters": 1.5}


def apply(doc, *operations):
    return apply_facility_layout_operations(deepcopy(doc), list(operations))["document"]


def test_a_reference_point_keeps_its_source_and_accuracy_and_an_independent_measurement():
    assert normalize_site_reference(CORNER) == dict(CORNER, x=0.123)
    surveyed = normalize_site_reference(dict(CORNER, measured={"x": 0.4, "z": 80.2, "source": "survey"}))
    assert surveyed["measured"] == {"source": "survey", "x": 0.4, "z": 80.2, "accuracyMeters": 0.05}
    for bad in (dict(CORNER, referenceId="corner"), dict(CORNER, kind="tree"), dict(CORNER, source="guess"),
                dict(CORNER, label=" "), dict(CORNER, accuracyMeters=0), dict(CORNER, colour="pink"),
                dict(CORNER, measured={"x": 1, "z": 2})):
        with pytest.raises(ValueError):
            normalize_site_reference(bad)


def test_reference_points_are_added_replaced_and_deleted_in_the_site_context():
    doc = fixture()
    added = apply(doc, {"op": "upsert_site_reference", "reference": CORNER},
                  {"op": "upsert_site_reference", "reference": dict(CORNER, referenceId="rp-2", label="Curb corner",
                                                                    kind="curb_corner", source="site_photo", x=40, z=5)})
    assert [r["referenceId"] for r in added["extensions"][KEY]["references"]] == ["rp-1", "rp-2"]
    moved = apply(added, {"op": "upsert_site_reference", "reference": dict(CORNER, x=1.0)})
    assert moved["extensions"][KEY]["references"][0]["x"] == 1.0 and len(moved["extensions"][KEY]["references"]) == 2
    removed = apply(moved, {"op": "delete_site_reference", "referenceId": "rp-1"})
    assert [r["referenceId"] for r in removed["extensions"][KEY]["references"]] == ["rp-2"]
    with pytest.raises(FacilityLayoutError, match="not found"):
        apply(removed, {"op": "delete_site_reference", "referenceId": "rp-1"})
    duplicate = deepcopy(added["extensions"][KEY])
    duplicate["references"].append(duplicate["references"][0])
    with pytest.raises(ValueError, match="unique"):
        normalize_site_context(duplicate, added)


def test_sage_can_stage_reference_points_and_reads_them_back():
    schema = json.dumps(operation_batch_schema())
    assert "upsert_site_reference" in schema and "delete_site_reference" in schema
    doc = apply(fixture(), {"op": "upsert_site_reference", "reference": CORNER})
    assert read_site(doc, "inspect_site_context", {})["references"] == [dict(CORNER, x=0.123)]


def test_a_whole_site_edit_keeps_the_stored_reference_points(tmp_path):
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=False)
    host.ensure_bootstrap()
    principal = host.principal()
    try:
        saved = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
        layout = deepcopy(saved["layout"])
        layout.setdefault("extensions", {})[KEY] = normalize_site_context(fixture()["extensions"][KEY], layout)
        layout["extensions"][KEY]["references"] = [normalize_site_reference(CORNER)]
        host.service.save_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, layout, saved["revision"])
        current = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
        context = {key: value for key, value in current["layout"]["extensions"][KEY].items() if key != "references"}
        context["areas"] = [{"areaId": "area-yard", "kind": "parking", "label": "Yard",
                             "boundary": [{"x": 10, "z": 10}, {"x": 30, "z": 10}, {"x": 30, "z": 30}]}]
        gateway = FacilityEditGateway(host.agent_runtime, principal, {"siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID,
                                                                       "revision": current["revision"]}, turn_id="refs")
        staged = asyncio.run(gateway.call("preview_facility_operations",
                                          {"operations": [{"op": "set_site_context", "siteContext": context}]}))
        assert staged["ok"], staged
        preview = host.service.get_layout_proposal_preview(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID,
                                                            staged["data"]["proposalId"])
        proposed = preview["alternative"]["ghostPreview"]["layout"]["extensions"][KEY]
        assert [r["referenceId"] for r in proposed["references"]] == ["rp-1"]
        assert [a["areaId"] for a in proposed["areas"]] == ["area-yard"]
    finally:
        host.close()


def test_corners_are_real_turns_and_compass_names_follow_the_lot():
    notched = [(0, 0), (50, 0), (50, 20), (49.5, 20.5), (50, 21), (50, 40), (0, 40)]
    assert [i for i, _ in corners(notched, 35, 4.0)] == [0, 1, 5, 6]  # the half-metre notch is not a corner
    assert compass(-10, 10) == "north-west" and compass(5, -1) == "east" and compass(-10, 4, 16) == "west-north-west"


def lot_with_pavement():
    doc, site = site_doc(STREET, ARTERIAL, RAIL)
    site["property"]["source"] = "county_parcel"
    site["areas"] = [{"areaId": "area-existing-pavement", "kind": "existing_pavement", "label": "Existing pavement",
                      "boundary": [{"x": 5, "z": 5}, {"x": 120, "z": 5}, {"x": 120, "z": 60}, {"x": 60, "z": 60},
                                   {"x": 60, "z": 90}, {"x": 5, "z": 90}]}]
    doc["extensions"][KEY] = normalize_site_context(site, doc)
    return doc, doc["extensions"][KEY]


def test_the_suggestion_starts_from_property_corners_then_photo_corners_and_keeps_road_points_for_checks():
    doc, site = lot_with_pavement()
    result = suggest_references(site, doc)
    suggested = result["suggested"]
    assert [r["referenceId"] for r in suggested] == ["rp-1", "rp-2", "rp-3", "rp-4", "rp-5"]
    assert [r["kind"] for r in suggested] == ["property_corner"] * 4 + ["pavement_corner"]
    assert {r["label"] for r in suggested[:4]} == {"South-west property corner", "South-east property corner",
                                                   "North-east property corner", "North-west property corner"}
    assert all(r["source"] == "county_parcel" and r["accuracyMeters"] == 3.0 for r in suggested[:4])
    assert suggested[4]["source"] == "site_photo" and suggested[4]["accuracyMeters"] == 6.0
    outline = building_outline(doc, site)
    centre = (sum(p["x"] for p in outline) / 4, sum(p["z"] for p in outline) / 4)
    nearest = min(suggested[:4], key=lambda r: math.dist((r["x"], r["z"]), centre))
    assert suggested[0] == nearest  # the first is nearest the building: short ties
    checks = {item["kind"]: item for item in result["candidates"]["checkPoints"]}
    assert set(checks) == {"road_intersection", "rail_crossing"}
    assert math.dist((checks["rail_crossing"]["x"], checks["rail_crossing"]["z"]), (-15, -8)) < 1
    assert all(item["source"] == "road_map" for item in checks.values())
    staged = apply_facility_layout_operations(deepcopy(doc), [{"op": "upsert_site_reference", "reference": r}
                                                              for r in suggested])["document"]  # stageable as given
    assert len(staged["extensions"][KEY]["references"]) == 5
    again = suggest_references(staged["extensions"][KEY], staged, 2)
    assert [r["referenceId"] for r in again["suggested"]] == ["rp-6", "rp-7"]  # new ids never reuse saved ones


def test_sage_has_the_reference_tool():
    spec = next(item for item in tool_specs() if item["name"] == "suggest_site_references")
    assert "suggest_site_references" in NAMES and "maxPoints" in spec["input_schema"]["properties"]
    assert "suggest_site_references" in SIMPLE
    doc, _ = lot_with_pavement()
    assert len(read_site(doc, "suggest_site_references", {"maxPoints": 3})["suggested"]) == 3
    assert read_site({"extensions": {}}, "suggest_site_references", {})["available"] is False
