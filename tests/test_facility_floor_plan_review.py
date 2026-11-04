"""Floor-plan import, FP2: a drawing converted, reviewed and applied through the routes
(docs/facility-floor-plan-import-plan.md, section 8 and section 11's integration and refusal checks)."""
import json
import shutil

import pytest

from ai_inspector.facility_layout import floor_plan_proposals
from ai_inspector.facility_layout.operation_proposals import create
from ai_inspector.facility_layout.plan_settings import default_plan_settings
from tests.floor_plan_dxf_fixtures import factory
from tests.test_facility_floor_plan_import import (BASE, IMPORTS, apply, code, made, reference, revision, saved,
                                                  started, store_folder, upload)
from tests.test_facility_layout_api import _principal

pytest.importorskip("ezdxf")

SESSION = {"X-InspectorPro-Session": "fp2-review"}
ROLES = {"A-WALL-EXT": "perimeter", "A-WALL": "wall_faces", "A-AREA": "room_boundary", "S-COLS": "column",
         "A-DOOR": "door", "A-TEXT": "text"}
SETTINGS = {"walls": {"heightMeters": 3}, "rooms": {"zoneType": "workcell"}, "outline": {"heightMeters": 6}}
ALIGNMENT = {"sourceOrigin": {"u": 0, "v": 0}, "metersPerDrawingUnit": 1, "rotationDegrees": 0,
             "translationMeters": {"x": 5, "z": 5}, "unitSource": "header", "confirmed": True, "controlPoints": []}


def underlay(tmp_path, roles=ROLES):
    """The API cell with a 40 m x 30 m plan and fixture 1 as its underlay, moved by (5, 5), its layers mapped."""
    client, service = started(tmp_path)
    response = upload(client, factory(made(tmp_path)))
    assert response.status_code == 200, response.text
    imported = response.json()
    names = {layer["layerId"]: layer["name"] for layer in imported["manifest"]["layers"]}
    value = reference(imported, alignment=dict(ALIGNMENT))
    value["layers"] = [{"layerId": layer_id, "visible": True, "role": roles.get(name, "reference")}
                       for layer_id, name in names.items()]
    response = apply(client, service, {"op": "set_plan_settings", "planSettings": default_plan_settings()},
                     {"op": "upsert_floor_plan_reference", "reference": value})
    assert response.status_code == 200, response.text
    return client, service, imported["import"]["importId"]


def conversion_url(import_id):
    return f"{IMPORTS}/{import_id}/conversion"


def stage(client, service, import_id, settings=SETTINGS):
    response = client.post(conversion_url(import_id), json={"baseRevision": revision(service), "settings": settings,
                                                            "stage": "proposal"})
    assert response.status_code == 200, response.text
    return response.json()


def preview(client, proposal_id):
    return client.get(f"{BASE}/proposals/{proposal_id}/preview")


def approve(client, alternative, proposal_id, key, **changes):
    body = {"proposalId": proposal_id, "binding": alternative["transactionBinding"], "idempotencyKey": key,
            "explicitApproval": True}
    body.update(changes)
    return client.post(BASE + "/approvals", headers=SESSION, json=body)


def test_candidates_are_listed_and_nothing_is_stored_or_changed(tmp_path):
    client, service, import_id = underlay(tmp_path)
    before = saved(service)
    response = client.post(conversion_url(import_id), json={"baseRevision": revision(service), "settings": SETTINGS})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stage"] == "candidates" and "proposal" not in body and "operations" not in body["conversion"]
    conversion = body["conversion"]
    assert [(row["start"], row["end"], row["state"]) for row in conversion["walls"]] == [
        ({"x": 15.1, "z": 5.0}, {"x": 15.1, "z": 9.0}, "new"), ({"x": 15.1, "z": 10.2}, {"x": 15.1, "z": 15.0}, "new")]
    assert [(row["label"], row["areaSquareMeters"]) for row in conversion["rooms"]] == [("Office", 20.0)]
    assert conversion["summary"]["operations"] == 4 and conversion["summary"]["blocked"] is None
    assert conversion["unconvertedCounts"] == {"later_phase": 2, "wall_end": 3}
    assert {layer["name"]: layer["role"] for layer in conversion["layers"].values()} == ROLES
    assert saved(service) == before
    assert not (store_folder(service) / "conversions").exists()
    # A viewer may not convert; settings and the request body are checked.
    viewer = client.post(conversion_url(import_id), headers={"X-Test-Role": "viewer"},
                         json={"baseRevision": revision(service), "settings": SETTINGS})
    assert viewer.status_code == 403
    for body, expected in (({"baseRevision": revision(service), "settings": {"walls": {"heightMeters": 99}}},
                            "floor_plan_conversion_settings_invalid"),
                           ({"baseRevision": revision(service)}, "invalid_request_body"),
                           ({"baseRevision": revision(service), "settings": {}, "stage": "apply"},
                            "invalid_request_body"),
                           ({"baseRevision": revision(service), "settings": {}, "extra": 1}, "invalid_request_body")):
        response = client.post(conversion_url(import_id), json=body)
        assert response.status_code == 422 and code(response) == expected, response.text


def test_a_conversion_is_reviewed_then_approved_and_applied_through_the_proposal_routes(tmp_path):
    client, service, import_id = underlay(tmp_path)
    before = saved(service)
    base = revision(service)
    body = stage(client, service, import_id)
    proposal = body["proposal"]
    assert proposal["approvalRequired"] is True and proposal["directApplyPolicy"]["eligible"] is False
    assert proposal["directApplyPolicy"]["reason"] == "Review a change converted from a drawing before applying it."
    assert revision(service) == base, "staging changes nothing"
    # The conversion's record: what it was made from, and where each candidate came from in the drawing.
    record = json.loads((store_folder(service) / "conversions" / (body["conversionId"] + ".json")).read_text())
    assert (record["layoutId"], record["baseRevision"], record["operationCount"]) == ("fl-api-cell", base, 4)
    assert record["origin"]["importId"] == import_id and record["origin"]["kind"] == "floor-plan-conversion"
    assert record["alignment"] == saved(service)["extensions"]["facilityFloorPlanReferences"]["references"][0][
        "alignment"]
    kinds = {}
    for row in record["candidates"]:
        kinds.setdefault(row["kind"], []).append(row)
    assert {kind: len(rows) for kind, rows in kinds.items()} == {"outline": 1, "wall": 2, "room": 1}
    assert all(row["sources"] and row["layers"] for row in record["candidates"])
    # The review: the server rebuilds it from the stored drawing's record and keeps its origin.
    opened = preview(client, proposal["proposalId"])
    assert opened.status_code == 200, opened.text
    alternative = opened.json()["alternative"]
    assert alternative["origin"] == record["origin"]
    assert alternative["directApplyPolicy"]["eligible"] is False
    assert [op["op"] for op in alternative["operations"]] == ["set_perimeter_walls", "upsert_interior_wall",
                                                              "upsert_interior_wall", "add_zone"]
    approval = approve(client, alternative, proposal["proposalId"], "fp2-apply")
    assert approval.status_code == 200, approval.text
    applied = client.post(BASE + "/apply", headers=SESSION, json={
        "approvalToken": approval.json()["approvalToken"], "binding": alternative["transactionBinding"],
        "idempotencyKey": "fp2-apply"})
    assert applied.status_code == 200, applied.text
    after = saved(service)
    walls = after["extensions"]["facilityInteriorWalls"]["walls"]
    assert [wall["wallId"] for wall in walls] == [row["candidateId"] for row in body["conversion"]["walls"]]
    assert [(wall["start"], wall["end"]) for wall in walls] == [
        ({"x": 15.1, "z": 5.0}, {"x": 15.1, "z": 9.0}), ({"x": 15.1, "z": 10.2}, {"x": 15.1, "z": 15.0})]
    assert [(zone["zoneId"], zone["label"]) for zone in after["zones"]] == [
        (body["conversion"]["rooms"][0]["candidateId"], "Office")]
    assert after["extensions"]["facilityPerimeterWalls"]["settings"]["boundary"] == body["conversion"]["outlines"][0][
        "boundary"]
    for key in ("facilityFloorPlanReferences", "facilityPlan"):
        assert after["extensions"][key] == before["extensions"][key], key
    # Converting again finds all of it there and stages nothing.
    again = client.post(conversion_url(import_id), json={"baseRevision": revision(service), "settings": SETTINGS})
    rows = again.json()["conversion"]
    assert {row["state"] for row in rows["walls"] + rows["rooms"] + rows["outlines"]} == {"there"}
    refused = client.post(conversion_url(import_id), json={"baseRevision": revision(service), "settings": SETTINGS,
                                                           "stage": "proposal"})
    assert refused.status_code == 422 and code(refused) == "floor_plan_conversion_nothing_to_add"


def test_a_conversion_is_never_applied_directly(tmp_path):
    client, service, import_id = underlay(tmp_path)
    body = stage(client, service, import_id)
    alternative = preview(client, body["proposal"]["proposalId"]).json()["alternative"]
    refused = approve(client, alternative, body["proposal"]["proposalId"], "fp2-direct", explicitApproval=False,
                      authorizationMode="direct", directConsent=True)
    assert refused.status_code >= 400 and "direct_review_required" in refused.text
    # Even staged in direct mode (as Sage stages with Apply directly on), the origin keeps it review-only.
    record = json.loads((store_folder(service) / "conversions" / (body["conversionId"] + ".json")).read_text())
    direct = create(service, _principal(), "site-a", "fl-api-cell", revision(service),
                    operations=alternative["operations"], edit_mode="direct",
                    limits=floor_plan_proposals.PACKAGE_LIMITS, origin=record["origin"])
    assert direct["alternative"]["directApplyPolicy"]["eligible"] is False
    assert direct["proposalId"] != body["proposal"]["proposalId"]
    refused = approve(client, direct["alternative"], direct["proposalId"], "fp2-direct-2", explicitApproval=False,
                      authorizationMode="direct", directConsent=True)
    assert refused.status_code >= 400 and "direct_review_required" in refused.text
    # The same operations without the origin are a different proposal: the origin is bound into the id.
    plain = create(service, _principal(), "site-a", "fl-api-cell", revision(service),
                   operations=alternative["operations"], edit_mode="direct",
                   limits=floor_plan_proposals.PACKAGE_LIMITS)
    assert plain["proposalId"] not in (direct["proposalId"], body["proposal"]["proposalId"])
    assert plain["alternative"]["transactionBinding"] != direct["alternative"]["transactionBinding"]
    assert "origin" not in plain["alternative"]


def test_a_conversion_whose_sources_changed_is_refused_until_converted_again(tmp_path, monkeypatch):
    client, service, import_id = underlay(tmp_path)
    body = stage(client, service, import_id)
    proposal_id = body["proposal"]["proposalId"]
    folder = store_folder(service)
    record_file = folder / "conversions" / (body["conversionId"] + ".json")
    assert preview(client, proposal_id).status_code == 200

    # The conversion's record is lost or altered.
    kept = record_file.read_bytes()
    record_file.unlink()
    assert code(preview(client, proposal_id)) == "floor_plan_conversion_missing"
    altered = json.loads(kept)
    altered["operationsSha256"] = "0" * 64
    record_file.write_text(json.dumps(altered))
    assert code(preview(client, proposal_id)) == "floor_plan_conversion_missing"
    record_file.write_bytes(kept)
    assert preview(client, proposal_id).status_code == 200

    # The drawing it was converted from is gone.
    geometry = next((folder / "geometry").glob("*.manifest.json"))
    aside = geometry.with_name("aside")
    shutil.move(geometry, aside)
    assert code(preview(client, proposal_id)) == "floor_plan_artifact_missing"
    shutil.move(aside, geometry)

    # The converter changed since.
    monkeypatch.setattr(floor_plan_proposals, "CONVERTER_VERSION", "fp-convert-0")
    assert code(preview(client, proposal_id)) == "floor_plan_conversion_stale"
    monkeypatch.undo()
    alternative = preview(client, proposal_id).json()["alternative"]

    # The underlay moved: a new revision, so the staged change is stale and applying it is refused.
    approval = approve(client, alternative, proposal_id, "fp2-stale")
    assert approval.status_code == 200, approval.text
    reference = saved(service)["extensions"]["facilityFloorPlanReferences"]["references"][0]
    moved = dict(reference, alignment=dict(reference["alignment"], translationMeters={"x": 6, "z": 5}))
    assert apply(client, service, {"op": "upsert_floor_plan_reference", "reference": moved}).status_code == 200
    stale = client.post(BASE + "/apply", headers=SESSION, json={
        "approvalToken": approval.json()["approvalToken"], "binding": alternative["transactionBinding"],
        "idempotencyKey": "fp2-stale"})
    assert stale.status_code == 409, stale.text
    assert "facilityInteriorWalls" not in saved(service)["extensions"]
    assert code(preview(client, proposal_id)) == "revision_conflict"
    # Converting the moved drawing gives new candidates (a new conversion), a metre to the east.
    moved_body = stage(client, service, import_id)
    assert moved_body["conversionId"] != body["conversionId"]
    assert moved_body["conversion"]["walls"][0]["start"] == {"x": 16.1, "z": 5.0}


def test_an_origin_is_checked_against_the_saved_underlay():
    origin = {"kind": "floor-plan-conversion", "conversionId": "fpc-" + "1" * 32, "referenceId": "fp-main",
              "importId": "fpi-" + "2" * 32, "sourceSha256": "3" * 64, "geometrySha256": "4" * 64,
              "alignmentSha256": "5" * 64, "layersSha256": "6" * 64, "settingsSha256": "7" * 64,
              "converterVersion": "fp-convert-1"}
    assert floor_plan_proposals.normalize_origin(dict(origin)) == origin
    for bad in ({**origin, "kind": "sage"}, {**origin, "extra": 1}, {k: v for k, v in origin.items() if k != "kind"},
                {**origin, "conversionId": "fpc-x"}, {**origin, "sourceSha256": "Z" * 64}, "origin", None):
        with pytest.raises(Exception) as caught:
            floor_plan_proposals.normalize_origin(bad)
        assert getattr(caught.value, "code", "") == "operation_proposal_origin_invalid"


def test_an_underlay_or_layout_that_is_not_the_saved_one_is_not_converted(tmp_path):
    client, service, import_id = underlay(tmp_path)
    stale = client.post(conversion_url(import_id), json={"baseRevision": "r-old", "settings": SETTINGS})
    assert stale.status_code == 409 and code(stale) == "revision_conflict"
    other = client.post(conversion_url("fpi-" + "0" * 32), json={"baseRevision": revision(service),
                                                                  "settings": SETTINGS})
    assert other.status_code == 409 and code(other) == "floor_plan_conversion_stale"
    elsewhere = client.post(f"/api/facility-layouts/site-b/fl-api-cell/floor-plan-imports/{import_id}/conversion",
                            json={"baseRevision": revision(service), "settings": SETTINGS})
    assert elsewhere.status_code in (403, 404)


def test_a_drawing_whose_unit_is_open_is_not_converted(tmp_path):
    client, service, import_id = underlay(tmp_path)
    value = saved(service)["extensions"]["facilityFloorPlanReferences"]["references"][0]
    open_unit = dict(value, alignment=dict(value["alignment"], unitSource="chosen", confirmed=False))
    assert apply(client, service, {"op": "upsert_floor_plan_reference", "reference": open_unit}).status_code == 200
    refused = client.post(conversion_url(import_id), json={"baseRevision": revision(service), "settings": SETTINGS})
    assert refused.status_code == 422 and code(refused) == "floor_plan_unit_unconfirmed"
