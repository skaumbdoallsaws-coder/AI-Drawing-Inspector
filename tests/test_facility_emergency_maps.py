"""Emergency teams (set_emergency_plan) and the evacuation and emergency map PDFs."""
from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest
from jsonschema import Draft202012Validator

from ai_inspector.codex_runtime.edit_schemas import operation_batch_schema
from ai_inspector.facility_layout import direct_edit_policy
from ai_inspector.facility_layout.emergency_pdf import EmergencyMapError, render_emergency_pdf
from ai_inspector.facility_layout.emergency_plan import (KEY, farthest_from, normalize_emergency_plan, symbol_for,
                                                         suggest_emergency_plan)
from ai_inspector.facility_layout.operations import FacilityLayoutOperationError, apply_facility_layout_operations
from tests.test_facility_layout_api import _client, _layout, _principal
from tests.test_facility_plan_pdf import check_structure, contents

NOW = datetime(2026, 10, 30, tzinfo=timezone.utc)
IDENTITY = {"x": 0, "y": 0, "z": 0, "w": 1}


def box(zid, label, x0, z0, x1, z1, zone_type="workcell"):
    return {"zoneId": zid, "zoneType": zone_type, "label": label, "floorElevation": 0, "anchors": [], "evidence": [],
            "boundary": [{"x": x0, "z": z0}, {"x": x1, "z": z0}, {"x": x1, "z": z1}, {"x": x0, "z": z1}]}


def placed(pid, asset_id, x, z):
    return {"placementId": pid, "assetId": asset_id, "assetDefinitionRevision": "r1",
            "transform": {"position": {"x": x, "y": 0, "z": z}, "quaternion": dict(IDENTITY), "scale": 1}}


def definition(asset_id, tags, half=(0.3, 1.0, 0.2)):
    return {"assetId": asset_id, "displayName": asset_id, "tags": tags,
            "geometry": {"obb": {"center": {"x": 0, "y": half[1], "z": 0},
                                 "halfExtents": {"x": half[0], "y": half[1], "z": half[2]}}}}


ASSETS = {
    "asset-exit": definition("asset-exit", ["emergency-exit", "door"], (0.6, 1.2, 0.07)),
    "asset-ext": definition("asset-ext", ["fire-extinguisher", "safety"]),
    "asset-aed": definition("asset-aed", ["aed", "first-aid", "safety"]),
    "asset-sign": definition("asset-sign", ["assembly-point", "sign"]),
    "asset-wall": definition("asset-wall", ["wall"], (20.0, 2.0, 0.1)),
    "asset-machine": definition("asset-machine", [], (1.5, 1.0, 1.0)),
    "asset-car": definition("asset-car", ["car", "vehicle", "employee parking"], (0.9, 0.7, 2.2)),
}


def resolve(asset_id, _revision):
    return ASSETS.get(asset_id)


def hall():
    """A 40 x 30 m hall: production and warehouse inside, an office annex beside it, a parking lot outside."""
    return {"layoutId": "fl-test-hall", "displayName": "Test hall", "association": {"siteId": "site-a"},
            "extensions": {"facilityPlan": {"widthMeters": 80, "depthMeters": 40}},
            "zones": [box("zn-machining", "Machining", 2, 2, 20, 28), box("zn-cnc", "CNC row", 4, 4, 10, 10),
                      box("zn-receiving", "Receiving + Storage", 22, 2, 38, 28, "receiving"),
                      box("zn-annex", "Office + Parking", 40, 0, 80, 30, "service"),
                      box("zn-office", "Office", 41, 1, 50, 10, "service"),
                      box("zn-restrooms", "Restrooms", 41, 12, 46, 16, "service"),
                      box("zn-parking", "Employee Parking - 40 Spaces", 55, 2, 78, 28, "staging")],
            "placements": [placed("pl-exit-1", "asset-exit", 10, 0.4), placed("pl-exit-2", "asset-exit", 30, 29.6),
                           placed("pl-ext-1", "asset-ext", 5, 15), placed("pl-ext-2", "asset-ext", 25, 15),
                           placed("pl-aed", "asset-aed", 21, 15), placed("pl-sign", "asset-sign", 70, 20),
                           placed("pl-wall", "asset-wall", 20, 0.1), placed("pl-machine", "asset-machine", 12, 20)],
            "floorMarkings": [], "routes": []}


def team_plan():
    return {"version": 1, "teams": [
        {"teamId": "production-team", "name": "Red Team - Production", "color": "#dc2626", "zoneIds": ["zn-machining"],
         "meetingPoint": {"label": "Employee Parking", "placementId": "pl-sign"}},
        {"teamId": "warehouse-team", "name": "Blue Team - Warehouse", "color": "#2563EB", "zoneIds": ["zn-receiving"],
         "meetingPoint": {"label": "Lot corner", "position": {"x": 76, "z": 4}}}],
        "shelterZoneIds": ["zn-restrooms"], "restroomZoneIds": ["zn-restrooms"], "phone": " +1 (612) 555-0100 "}


def test_the_plan_is_checked_against_the_layout():
    layout = hall()
    plan = normalize_emergency_plan(team_plan(), layout)
    assert plan["teams"][0]["color"] == "#DC2626" and plan["phone"] == "+1 (612) 555-0100"
    assert plan["teams"][1]["meetingPoint"] == {"label": "Lot corner", "position": {"x": 76.0, "z": 4.0}}
    for change, message in [
            (lambda p: p["teams"][0]["zoneIds"].append("zn-missing"), "not in this layout"),
            (lambda p: p["teams"][1]["zoneIds"].append("zn-machining"), "at most one team"),
            (lambda p: p["teams"][0].update(color="red"), "#rrggbb"),
            (lambda p: p["teams"][0]["meetingPoint"].update(position={"x": 1, "z": 2}), "either a placementId"),
            (lambda p: p["teams"][0]["meetingPoint"].update(placementId="pl-gone"), "not in this layout"),
            (lambda p: p["teams"][1].update(teamId="production-team"), "unique"),
            (lambda p: p.update(phone="call me"), "digits"),
            (lambda p: p.update(extra=1), "fields")]:
        broken = team_plan()
        change(broken)
        with pytest.raises(ValueError, match=message):
            normalize_emergency_plan(broken, layout)


def test_set_emergency_plan_stores_and_removes_the_plan_and_applies_directly(tmp_path):
    _, _, shell, policy = _client(tmp_path)
    layout = _layout(shell, policy)
    layout["zones"] += [z for z in hall()["zones"] if z["zoneId"] in ("zn-machining", "zn-receiving", "zn-restrooms")]
    plan = team_plan()
    plan["teams"][0]["meetingPoint"] = {"label": "Employee Parking", "position": {"x": 70, "z": 20}}
    after = apply_facility_layout_operations(layout, [{"op": "set_emergency_plan", "emergencyPlan": plan}])
    stored = after["document"]["extensions"][KEY]
    assert [t["teamId"] for t in stored["teams"]] == ["production-team", "warehouse-team"]
    cleared = apply_facility_layout_operations(after["document"], [{"op": "set_emergency_plan", "emergencyPlan": None}])
    assert KEY not in cleared["document"]["extensions"]
    broken = deepcopy(plan)
    broken["teams"][0]["zoneIds"] = ["zn-missing"]
    with pytest.raises(FacilityLayoutOperationError) as error:
        apply_facility_layout_operations(layout, [{"op": "set_emergency_plan", "emergencyPlan": broken}])
    assert error.value.code == "invalid_emergency_plan"
    operation = {"op": "set_emergency_plan", "emergencyPlan": team_plan()}
    assert direct_edit_policy.evaluate([operation], {"affectedIds": [], "createdIds": []})["eligible"] is True
    errors = list(Draft202012Validator(operation_batch_schema()).iter_errors({"operations": [operation]}))
    assert not errors, errors[0].message


def test_the_most_specific_tag_gives_the_symbol():
    assert symbol_for(["aed", "first-aid"]) == "aed" and symbol_for(["first-aid"]) == "first_aid"
    assert symbol_for(["emergency-exit", "door"]) == "exit" and symbol_for(["wall"]) is None


def test_teams_are_suggested_from_zone_names_with_meeting_points_in_the_lots():
    result = suggest_emergency_plan(hall(), resolve)
    teams = {t["teamId"]: t for t in result["plan"]["teams"]}
    # The CNC row sits inside machining; the annex mixes offices and parking, so its office is listed instead.
    assert teams["production-team"]["zoneIds"] == ["zn-machining"]
    assert teams["warehouse-team"]["zoneIds"] == ["zn-receiving"]
    assert teams["office-team"]["zoneIds"] == ["zn-office"]
    assert teams["production-team"]["meetingPoint"] == {"label": "Employee Parking", "placementId": "pl-sign"}
    assert result["plan"]["restroomZoneIds"] == ["zn-restrooms"] and result["plan"]["shelterZoneIds"] == []
    assert result["operation"]["op"] == "set_emergency_plan"
    normalize_emergency_plan(result["plan"], hall())


def test_the_farthest_floor_point_is_measured_in_a_straight_line():
    far = farthest_from([(0, 0)], [[(0, 0), (10, 0), (10, 10), (0, 10)]], step=2.0)
    assert far["at"] == {"x": 9.0, "z": 9.0} and far["meters"] == pytest.approx(12.7, abs=0.05)
    assert farthest_from([], [[(0, 0), (1, 0), (1, 1)]]) is None


def test_the_evacuation_map_needs_teams_then_draws_them():
    layout = hall()
    with pytest.raises(EmergencyMapError, match="no emergency teams"):
        render_emergency_pdf(layout, resolve, kind="evacuation", now=NOW)
    layout["extensions"][KEY] = normalize_emergency_plan(team_plan(), layout)
    before = deepcopy(layout)
    pdf, info = render_emergency_pdf(layout, resolve, kind="evacuation", revision="abc123", now=NOW)
    assert check_structure(pdf) == 1 and layout == before
    [page] = contents(pdf)
    for text in (b"(Test hall Evacuation Map) Tj", b"(RED TEAM - PRODUCTION) Tj", b"(BLUE TEAM - WAREHOUSE) Tj",
                 b"(Meeting point - Employee Parking) Tj", b"(RED TEAM MEETING POINT) Tj",
                 b"(Proceed to any exit door and continue to your meeting point for evacuation roll call.) Tj"):
        assert text in page, text
    assert info["exits"] == 2 and [t["name"] for t in info["teams"]] == ["Red Team - Production",
                                                                         "Blue Team - Warehouse"]
    assert info["farthestFromExit"]["meters"] > 0


def test_parked_cars_are_left_off_the_printed_plans():
    from ai_inspector.facility_layout.emergency_pdf import MapData
    from ai_inspector.facility_layout.plan_pdf import PlanData
    empty, parked = hall(), hall()
    parked["placements"].append(placed("pl-car", "asset-car", 60, 10))
    assert len(MapData(parked, resolve).items) == len(MapData(empty, resolve).items) >= 1  # the machine stays
    labels = [item["label"] for item in PlanData(parked, resolve).items]
    assert "asset-car" not in labels and "asset-machine" in labels


def test_the_emergency_map_counts_each_symbol_and_lists_only_those_present():
    layout = hall()
    layout["extensions"][KEY] = normalize_emergency_plan(team_plan(), layout)
    pdf, info = render_emergency_pdf(layout, resolve, kind="emergency", revision="abc123", now=NOW)
    assert check_structure(pdf) == 1
    [page] = contents(pdf)
    assert info["counts"] == {"Emergency exit": 2, "Fire extinguisher": 2, "AED": 1, "Assembly point": 1,
                              "Restroom": 1, "Severe weather shelter": 1}
    for text in (b"(Test hall Emergency Map) Tj", b"(Fire extinguisher) Tj", b"(Severe weather shelter) Tj",
                 b"(Site phone +1 \\(612\\) 555-0100) Tj", b"(EXIT) Tj"):
        assert text in page, text
    assert b"(Eyewash) Tj" not in page and b"(First aid kit) Tj" not in page
    assert b"Generated from the saved layout. Check exits, routes and equipment on site" in page


def test_the_route_serves_the_maps_by_kind(tmp_path):
    client, service, shell, policy = _client(tmp_path)
    service.create_layout(_principal(), "site-a", _layout(shell, policy))
    response = client.get("/api/facility-layouts/site-a/fl-api-cell/plan.pdf?kind=emergency")
    assert response.status_code == 200 and response.headers["content-type"] == "application/pdf"
    assert 'filename="fl-api-cell-emergency-map.pdf"' in response.headers["content-disposition"]
    assert check_structure(response.content) == 1
    no_teams = client.get("/api/facility-layouts/site-a/fl-api-cell/plan.pdf?kind=evacuation")
    assert no_teams.status_code == 409
    assert json.loads(no_teams.content)["error"]["code"] == "emergency_map_unavailable"
    assert client.get("/api/facility-layouts/site-a/fl-api-cell/plan.pdf?kind=poster").status_code == 400


def test_sage_suggests_teams_stages_them_directly_and_prepares_each_map_as_a_file_card(tmp_path):
    import asyncio
    from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway
    from ai_inspector.facility_layout.host import LOCAL_LAYOUT_ID, LOCAL_SITE_ID, LocalFacilityLayoutHost
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=False)
    host.ensure_bootstrap()
    principal = host.principal()
    reference = {"siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID}
    try:
        saved = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
        layout = deepcopy(saved["layout"])
        layout["zones"] = [z for z in hall()["zones"] if z["zoneId"] in ("zn-machining", "zn-receiving", "zn-parking")]
        saved = host.layout_repository.save_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, layout, saved["revision"])
        gateway = FacilityEditGateway(host.agent_runtime, principal, dict(reference, revision=saved["revision"]),
                                      turn_id="teams")
        missing = gateway._read_data("prepare_layout_pdf", {"kind": "evacuation"})
        assert missing["available"] is False and "no emergency teams" in missing["reason"] and gateway.pdfs == []
        suggestion = gateway._read_data("suggest_emergency_teams", {})
        assert [t["name"] for t in suggestion["teams"]] == ["Red Team - Production", "Blue Team - Warehouse"]
        gateway.edit_mode = "direct"
        staged_result = asyncio.run(gateway.call("preview_facility_operations", {"operations": [suggestion["operation"]]}))
        data = staged_result.get("data", staged_result)
        assert staged_result["ok"], staged_result
        assert data["directApplyPolicy"]["eligible"] is True
        layout = deepcopy(host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)["layout"])
        layout.setdefault("extensions", {})[KEY] = suggestion["plan"]
        saved = host.layout_repository.save_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, layout, saved["revision"])
        reader = FacilityEditGateway(host.agent_runtime, principal, dict(reference, revision=saved["revision"]),
                                     turn_id="maps")
        evacuation = reader._read_data("prepare_layout_pdf", {"kind": "evacuation"})
        emergency = reader._read_data("prepare_layout_pdf", {"kind": "emergency"})
        plan = reader._read_data("prepare_layout_pdf", {})
        assert evacuation["available"] and evacuation["pages"] == 1 and len(evacuation["teams"]) == 2
        assert emergency["available"] and emergency["fileName"].endswith(" - emergency map.pdf")
        assert plan["fileName"].endswith(" - layout plan.pdf")
        urls = [card["url"] for card in reader.pdfs]
        assert len(urls) == 3 and urls[0].endswith("&kind=evacuation") and urls[1].endswith("&kind=emergency")
    finally:
        host.close()
