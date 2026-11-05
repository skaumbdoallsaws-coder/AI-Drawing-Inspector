"""Sage's floor-plan tools (docs/facility-floor-plan-import-plan.md, section 9): the drawing under the bound saved
layout read, placed from the user's points and converted, and each change staged for the user's review. No tool
saves anything; the user approves through the same review as the panel's. Expected numbers are fixture 1's
documented coordinates (tests/floor_plan_dxf_fixtures.py) moved by (5, 5), as tests/test_facility_floor_plan_review.py
places it."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway, edit_tool_specs
from ai_inspector.codex_runtime.facility_tools import FacilityReadGateway, tool_specs
from ai_inspector.codex_runtime.progress import describe
from ai_inspector.facility_layout import floor_plan_conversion as converter
from ai_inspector.facility_layout.plan_settings import default_plan_settings
from tests.test_facility_floor_plan_import import BASE, apply, made, reference, revision, saved, started, upload
from tests.test_facility_floor_plan_review import SESSION, SETTINGS, approve, preview, underlay
from tests.test_facility_layout_api import _principal

pytest.importorskip("ezdxf")

READS = {"inspect_floor_plan_import", "align_floor_plan_import", "plan_floor_plan_conversion"}


def gateway(service, kind=FacilityEditGateway):
    runtime = SimpleNamespace(service=service, asset_catalog_provider=lambda principal, site: [])
    return kind(runtime, _principal(), {"siteId": "site-a", "layoutId": "fl-api-cell", "revision": revision(service)},
                turn_id="fp-sage")


def calls(gate, *steps):
    """Each (name, arguments) called in turn; arguments may be a function of the results so far."""
    async def run():
        results = []
        for name, arguments in steps:
            results.append(await gate.call(name, arguments(results) if callable(arguments) else arguments))
        return results
    return asyncio.run(run())


def underlay_now(service):
    return saved(service)["extensions"]["facilityFloorPlanReferences"]["references"][0]


def approved(client, proposal_id, key):
    """The user's side: open the review, approve it and apply it, as the app does."""
    shown = preview(client, proposal_id)
    assert shown.status_code == 200, shown.text
    alternative = shown.json()["alternative"]
    approval = approve(client, alternative, proposal_id, key)
    assert approval.status_code == 200, approval.text
    applied = client.post(BASE + "/apply", headers=SESSION, json={
        "approvalToken": approval.json()["approvalToken"], "binding": alternative["transactionBinding"],
        "idempotencyKey": key})
    assert applied.status_code == 200, applied.text
    return alternative


def test_the_reads_are_published_and_the_staging_only_where_changes_are_staged():
    assert READS <= {spec["name"] for spec in tool_specs()}
    assert "preview_floor_plan_import" not in {spec["name"] for spec in tool_specs()}
    assert "preview_floor_plan_import" in {spec["name"] for spec in edit_tool_specs()}
    assert describe("plan_floor_plan_conversion", {})["running"] == "Checking the walls, doors and rooms in the drawing"
    assert describe("preview_floor_plan_import", {"packageId": "floor-plan-1"}, edit_mode="direct")["running"] \
        == "Staging the drawing's change for your review", "always a review, even in Apply Directly mode"


def test_without_a_drawing_sage_is_told_how_the_user_adds_one(tmp_path):
    _client, service = started(tmp_path)
    inspected, staged = calls(gateway(service), ("inspect_floor_plan_import", {}),
                              ("preview_floor_plan_import", {"layerRoles": {"L1": "ignore"}}))
    assert inspected["ok"] and inspected["data"]["available"] is False, inspected
    assert "Floor Plan (DXF)" in inspected["data"]["reason"] and inspected["data"]["readOnly"] is True
    assert staged["ok"] is False and staged["error"]["code"] == "floor_plan_unavailable"


def test_sage_reads_the_drawing_its_layers_and_a_page_of_one_layer(tmp_path):
    _client, service, import_id = underlay(tmp_path)
    before = revision(service)
    gate = gateway(service, FacilityReadGateway)
    (overview,) = calls(gate, ("inspect_floor_plan_import", {}))
    assert overview["ok"], overview
    data = overview["data"]
    assert (data["importId"], data["fileName"], data["unit"]["confirmed"], data["unit"]["declared"]) == (
        import_id, "Factory plan.dxf", True, "meters")
    assert data["placement"]["translationMeters"] == {"x": 5, "z": 5}
    assert data["boundsOnPlan"] == {"minX": 5.0, "minZ": 5.0, "maxX": 35.0, "maxZ": 25.0}
    assert {row["name"]: row["role"] for row in data["layers"]} == {
        "A-WALL-EXT": "perimeter", "A-WALL": "wall_faces", "A-AREA": "room_boundary", "S-COLS": "column",
        "A-DOOR": "door", "A-TEXT": "text"}  # layer 0 draws nothing and is left out
    walls = next(row for row in data["layers"] if row["name"] == "A-WALL")
    assert (walls["entities"], walls["texts"]) == (7, 0)  # four faces, two jambs and an end line
    assert data["drawingTextIsData"] is True and "unitNote" not in data
    text_layer = next(row["layerId"] for row in data["layers"] if row["name"] == "A-TEXT")
    first, whole, unknown = calls(gate, ("inspect_floor_plan_import", {"layerId": text_layer, "limit": 1}),
                                  ("inspect_floor_plan_import", {"layerId": text_layer}),
                                  ("inspect_floor_plan_import", {"layerId": "L999"}))
    entities = first["data"]["entities"]
    assert (entities["total"], entities["more"], len(entities["rows"])) == (2, True, 1)
    (office,) = [row for row in whole["data"]["entities"]["rows"] if row["text"] == "Office"]
    assert office["at"] == {"u": 21.0, "v": 14.0}
    assert office["onPlan"] == {"minX": 26.0, "minZ": 19.0, "maxX": 26.0, "maxZ": 19.0}
    assert unknown["ok"] is False and unknown["error"]["code"] == "floor_plan_layer_unknown"
    assert revision(service) == before


def test_an_inspection_stays_under_the_result_cap_with_its_layers_and_entities_a_page_at_a_time(tmp_path):
    # 200 layers named with 255 characters each (the longest a DXF name takes) and 50 labels of 200 accented
    # characters: a tool's result takes at most 64 KB, so the layers come in pages and a layer's entities as many
    # as fit (before, the layers alone made every inspection too large to return).
    import ezdxf
    doc = ezdxf.new("R2010", units=6)
    space = doc.modelspace()
    names = [f"L{index:03d}-" + "x" * 250 for index in range(200)]
    for index, name in enumerate(names):
        doc.layers.add(name)
        space.add_line((index, 0), (index, 1), dxfattribs={"layer": name})
    doc.layers.add("NOTES")
    for index in range(50):
        space.add_text("é" * 200, dxfattribs={"layer": "NOTES", "insert": (index, 5), "height": 0.2})
    path = made(tmp_path) / "layers.dxf"
    doc.saveas(path)
    client, service = started(tmp_path)
    response = upload(client, path)
    assert response.status_code == 200, response.text
    imported = response.json()
    response = apply(client, service, {"op": "set_plan_settings", "planSettings": default_plan_settings()},
                     {"op": "upsert_floor_plan_reference", "reference": reference(imported)})
    assert response.status_code == 200, response.text
    gate = gateway(service, FacilityReadGateway)
    seen, offset, pages = [], 0, 0
    while True:
        (answer,) = calls(gate, ("inspect_floor_plan_import", {"layersOffset": offset}))
        assert answer["ok"], answer
        assert len(json.dumps(answer).encode()) <= 65536
        data = answer["data"]
        assert (data["layersTotal"], data["layersOffset"]) == (201, offset)
        seen += [row["name"] for row in data["layers"]]
        pages += 1
        if "layersNextOffset" not in data:
            break
        assert data["layersNextOffset"] == offset + len(data["layers"]) > offset
        offset = data["layersNextOffset"]
    assert pages > 1 and sorted(seen) == sorted(names + ["NOTES"])
    notes = next(layer["layerId"] for layer in imported["manifest"]["layers"] if layer["name"] == "NOTES")
    shown, offset = [], 0
    while True:
        (answer,) = calls(gate, ("inspect_floor_plan_import", {"layerId": notes, "limit": 50, "offset": offset}))
        assert answer["ok"], answer
        assert len(json.dumps(answer).encode()) <= 65536
        entities = answer["data"]["entities"]
        assert entities["total"] == 50 and entities["rows"]
        shown += [row["entityId"] for row in entities["rows"]]
        if not entities["more"]:
            assert "nextOffset" not in entities
            break
        assert entities["nextOffset"] == offset + len(entities["rows"])
        offset = entities["nextOffset"]
    assert offset > 0 and len(shown) == len(set(shown)) == 50
    assert {row["text"] for row in entities["rows"]} == {"é" * 200}



def test_entities_whose_ids_are_too_long_to_show_are_clipped_and_every_page_moves_on(tmp_path, monkeypatch):
    # A broken file whose handles run to 60,000 hex digits (an entity's id is its handle): before, the first row did
    # not fit, and the page came back empty with nextOffset where it started, for ever.
    import ezdxf
    from ai_inspector.codex_runtime import floor_plan_tools
    doc = ezdxf.new("R2010", units=6)
    doc.layers.add("LONG")
    space = doc.modelspace()
    handles = [space.add_line((k, 0), (k, 1), dxfattribs={"layer": "LONG"}).dxf.handle for k in range(3)]
    path = made(tmp_path) / "long-handles.dxf"
    doc.saveas(path)
    data = path.read_bytes()
    eol = bytes([13, 10]) if bytes([13, 10]) in data else bytes([10])
    for k, handle in enumerate(handles):
        marker = b"LINE" + eol + b"  5" + eol + handle.encode() + eol
        assert data.count(marker) == 1
        data = data.replace(marker, b"LINE" + eol + b"  5" + eol + b"ABCDEF"[k:k + 1] * 60000 + eol)
    path.write_bytes(data)
    client, service = started(tmp_path)
    response = upload(client, path)
    assert response.status_code == 200, response.text
    imported = response.json()
    response = apply(client, service, {"op": "set_plan_settings", "planSettings": default_plan_settings()},
                     {"op": "upsert_floor_plan_reference", "reference": reference(imported)})
    assert response.status_code == 200, response.text
    layer = next(row["layerId"] for row in imported["manifest"]["layers"] if row["name"] == "LONG")
    gate = gateway(service, FacilityReadGateway)

    def pages(limit):
        shown, offset = [], 0
        while True:
            (answer,) = calls(gate, ("inspect_floor_plan_import", {"layerId": layer, "limit": limit,
                                                                    "offset": offset}))
            assert answer["ok"] and len(json.dumps(answer).encode()) <= 65536, answer
            entities = answer["data"]["entities"]
            assert entities["total"] == 3 and entities["rows"]
            shown += entities["rows"]
            if not entities["more"]:
                return shown
            assert entities["nextOffset"] == offset + len(entities["rows"]) > offset
            offset = entities["nextOffset"]

    for limit in (50, 1):
        rows = pages(limit)
        assert [row["entityId"] for row in rows] == [letter * 117 + "..." for letter in "ABC"]
        assert all(row["type"] == "LINE" and row["pointCount"] == 2 for row in rows)
    # A row that does not fit at all is summed up rather than left out, so the next page still starts after it.
    monkeypatch.setattr(floor_plan_tools, "ANSWER_BYTES", 0)
    rows = pages(1)
    assert [(row["entityId"][:1], row["type"], row["omitted"]) for row in rows] == [
        (letter, "LINE", "too large to show") for letter in "ABC"]

def test_a_placement_fitted_to_the_user_s_points_is_reviewed_then_saved(tmp_path):
    client, service, _import_id = underlay(tmp_path)
    before = revision(service)
    gate = gateway(service)
    points = [{"drawing": {"u": 0, "v": 0}, "plan": {"x": 6, "z": 5}},
              {"drawing": {"u": 30, "v": 0}, "plan": {"x": 36, "z": 5}}]
    fitted, sneaked, staged = calls(
        gate, ("align_floor_plan_import", {"points": points}),
        ("preview_planned_design", lambda done: {"packageId": done[0]["data"]["package"]["packageId"]}),
        ("preview_floor_plan_import", lambda done: {"packageId": done[0]["data"]["package"]["packageId"]}))
    assert fitted["ok"], fitted
    data = fitted["data"]
    # The unit is confirmed (the file declares meters), so its scale holds and the points only move the drawing.
    assert (data["scale"], data["unitSource"]) == ("held", "header")
    assert abs(data["placement"]["rotationDegrees"]) < 1e-9 and data["placement"]["metersPerDrawingUnit"] == 1
    assert data["maxOffMeters"] == 0.0 and data["pointsOffMeters"] == [0.0, 0.0]
    assert sneaked["ok"] is False and sneaked["error"]["code"] == "codex_design_package_unknown"
    assert staged["ok"], staged
    assert staged["data"]["approvalRequired"] is True and staged["data"]["saved"] is False
    assert staged["data"]["editMode"] == "preview"
    assert gate.proposal == {"siteId": "site-a", "layoutId": "fl-api-cell", "revision": before,
                             "proposalId": staged["data"]["proposalId"]}
    assert revision(service) == before, "staging saves nothing"
    alternative = approved(client, staged["data"]["proposalId"], "fp-sage-align")
    (operation,) = alternative["operations"]
    assert operation["op"] == "upsert_floor_plan_reference"
    alignment = underlay_now(service)["alignment"]
    assert alignment["translationMeters"] == {"x": 6, "z": 5}
    assert (alignment["unitSource"], alignment["confirmed"], len(alignment["controlPoints"])) == ("header", True, 2)


def test_an_unconfirmed_unit_takes_its_scale_from_the_points(tmp_path):
    client, service, _import_id = underlay(tmp_path)
    reference = underlay_now(service)
    reference["alignment"].update(metersPerDrawingUnit=1, unitSource="chosen", confirmed=False)
    response = client.put(BASE, json={"baseRevision": revision(service), "operations": [
        {"op": "upsert_floor_plan_reference", "reference": reference}]})
    assert response.status_code == 200, response.text
    gate = gateway(service)
    inspected, fitted = calls(
        gate, ("inspect_floor_plan_import", {}),
        ("align_floor_plan_import", {"points": [{"drawing": {"u": 0, "v": 0}, "plan": {"x": 5, "z": 5}},
                                                {"drawing": {"u": 30, "v": 0}, "plan": {"x": 20, "z": 5}}]}))
    assert inspected["data"]["unit"]["confirmed"] is False and "Never guess" in inspected["data"]["unitNote"]
    # As in the panel: points 30 drawing units apart set 15 m apart make a unit half a meter.
    assert (fitted["data"]["scale"], fitted["data"]["unitSource"]) == ("fit", "calibrated")
    assert fitted["data"]["placement"]["metersPerDrawingUnit"] == 0.5 and fitted["data"]["maxOffMeters"] == 0.0


def test_layer_roles_are_staged_only_for_the_drawing_s_own_layers(tmp_path):
    client, service, _import_id = underlay(tmp_path)
    ids = [layer["layerId"] for layer in underlay_now(service)["layers"]]
    gate = gateway(service)
    staged, unknown, both = calls(
        gate, ("preview_floor_plan_import", {"layerRoles": {ids[0]: "ignore"}}),
        ("preview_floor_plan_import", {"layerRoles": {"L999": "ignore"}}),
        ("preview_floor_plan_import", {"layerRoles": {ids[0]: "ignore"}, "packageId": "floor-plan-1"}))
    assert staged["ok"], staged
    assert unknown["ok"] is False and unknown["error"]["code"] == "floor_plan_layer_unknown"
    assert both["ok"] is False and both["error"]["code"] == "floor_plan_preview_invalid"
    assert gate.proposal is None, "a failed staging clears the last one"
    approved(client, staged["data"]["proposalId"], "fp-sage-roles")
    roles = {layer["layerId"]: layer["role"] for layer in underlay_now(service)["layers"]}
    assert roles[ids[0]] == "ignore"


def test_sage_plans_the_conversion_and_the_user_approves_it_bound_to_its_origin(tmp_path):
    client, service, _import_id = underlay(tmp_path)
    before = revision(service)
    gate = gateway(service)
    waiting, planned, sneaked, staged = calls(
        gate, ("plan_floor_plan_conversion", {}), ("plan_floor_plan_conversion", SETTINGS),
        ("preview_planned_design", lambda done: {"packageId": done[1]["data"]["package"]["packageId"]}),
        ("preview_floor_plan_import", lambda done: {"packageId": done[1]["data"]["package"]["packageId"]}))
    # Without heights or a zone type everything waits: nothing to stage.
    assert waiting["ok"] and "package" not in waiting["data"], waiting
    assert {row["state"] for kind in ("walls", "doors", "rooms", "outlines")
            for row in waiting["data"][kind]} == {"waiting"}
    assert waiting["data"]["reasons"] == {"wall_settings": "Give the wall height to add the walls.",
                                          "zone_type": "Choose its zone type.",
                                          "outline_settings": "Give the outer wall height to add the outer walls."}
    data = planned["data"]
    assert data["summary"]["operations"] == 3 and data["summary"]["blocked"] is None
    (wall,) = data["walls"]
    assert (wall["label"], wall["start"], wall["end"], wall["openings"], wall["state"]) == (
        "Drawing wall 1", {"x": 15.1, "z": 5.0}, {"x": 15.1, "z": 15.0}, [{"startMeters": 4.0, "endMeters": 5.2}],
        "new")
    assert [(row["kind"], row["widthMeters"], row["wallLabel"], row["state"]) for row in data["doors"]] == [
        ("single", 1.2, "Drawing wall 1", "new")]
    assert [(row["label"], row["areaSquareMeters"], row["zoneType"]) for row in data["rooms"]] == [
        ("Office", 20.0, "workcell")]
    assert [(row["corners"], row["areaSquareMeters"]) for row in data["outlines"]] == [(4, 600.0)]
    assert {row["reason"]: row["count"] for row in data["leftAsDrawing"]} == {"later_phase": 1, "wall_end": 3}
    assert data["roomNamesAreDrawingText"] is True
    assert sneaked["ok"] is False and sneaked["error"]["code"] == "codex_design_package_unknown"
    assert staged["ok"], staged
    assert staged["data"]["approvalRequired"] is True and staged["data"]["conversionId"].startswith("fpc-")
    assert staged["data"]["directApplyPolicy"]["eligible"] is False
    assert revision(service) == before, "staging saves nothing"
    alternative = approved(client, staged["data"]["proposalId"], "fp-sage-convert")
    assert alternative["origin"]["kind"] == "floor-plan-conversion"
    assert [op["op"] for op in alternative["operations"]] == ["set_perimeter_walls", "upsert_interior_wall",
                                                              "add_zone"]
    layout = saved(service)
    (applied,) = layout["extensions"]["facilityInteriorWalls"]["walls"]
    assert (applied["wallId"], applied["openings"]) == (wall["id"], wall["openings"])
    # Asked again on the new revision, what was added is there and nothing is left to stage.
    (again,) = calls(gateway(service), ("plan_floor_plan_conversion", SETTINGS))
    assert {row["state"] for kind in ("walls", "doors", "rooms", "outlines") for row in again["data"][kind]} \
        == {"there"} and "package" not in again["data"]


def test_a_package_belongs_to_the_turn_and_revision_it_was_planned_on(tmp_path):
    client, service, _import_id = underlay(tmp_path)
    gate = gateway(service)
    (planned,) = calls(gate, ("plan_floor_plan_conversion", SETTINGS))
    package = planned["data"]["package"]["packageId"]
    response = client.put(BASE, json={"baseRevision": revision(service), "operations": [
        {"op": "upsert_floor_plan_reference", "reference": dict(underlay_now(service), opacity=0.5)}]})
    assert response.status_code == 200, response.text
    (stale,) = calls(gate, ("preview_floor_plan_import", {"packageId": package}))
    assert stale["ok"] is False and stale["error"]["code"] == "codex_document_unavailable"
    (other_turn,) = calls(gateway(service), ("preview_floor_plan_import", {"packageId": package}))
    assert other_turn["ok"] is False and other_turn["error"]["code"] == "floor_plan_package_unknown"


def test_a_drawing_too_large_to_convert_is_named_to_sage(tmp_path, monkeypatch):
    _client, service, _import_id = underlay(tmp_path)
    monkeypatch.setattr(converter, "MAX_PIECES", 2)
    (refused,) = calls(gateway(service, FacilityReadGateway), ("plan_floor_plan_conversion", SETTINGS))
    assert refused["ok"] is False and refused["error"]["code"] == "floor_plan_conversion_too_large", refused
    assert "more than 2 straight pieces" in refused["error"]["message"]


def test_in_apply_directly_mode_a_drawing_s_change_still_opens_a_review(tmp_path):
    client, service, _import_id = underlay(tmp_path)
    before = revision(service)
    gate = gateway(service)
    gate.edit_mode = "direct"
    points = [{"drawing": {"u": 0, "v": 0}, "plan": {"x": 6, "z": 5}},
              {"drawing": {"u": 30, "v": 0}, "plan": {"x": 36, "z": 5}}]
    placed, converted = calls(
        gate, ("align_floor_plan_import", {"points": points}),
        ("plan_floor_plan_conversion", SETTINGS))
    for package in (placed["data"]["package"]["packageId"], converted["data"]["package"]["packageId"]):
        (staged,) = calls(gate, ("preview_floor_plan_import", {"packageId": package}))
        assert staged["ok"], staged
        assert (staged["data"]["approvalRequired"], staged["data"]["editMode"]) == (True, "preview")
        assert "editMode" not in gate.proposal, "the app applies directly only a proposal marked direct"
        shown = preview(client, staged["data"]["proposalId"])
        assert shown.status_code == 200 and shown.json()["alternative"]["editMode"] == "preview", shown.text
    assert revision(service) == before, "staging saves nothing"
