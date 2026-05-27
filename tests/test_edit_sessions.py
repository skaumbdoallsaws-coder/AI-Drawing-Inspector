"""Tests for the Edit Session Log MVP.

Covers:
- POST /api/edit-sessions: create from a real cad-edit-handoff payload,
  reject canEdit=true / stale handoffVersion / matched=false / missing
  parts, dedupe duplicate open sessions with a warning
- GET single + GET handoff-payload + GET list with filters
- PATCH FSM: legal/illegal transitions, terminal locking, per-status
  required co-fields (extraction packageId, promoted rev exists on
  disk, comparison revA/revB pinned), immutable-field rejection,
  noteToAppend append + terminal-note acceptance, atomic write on
  failure, embedded handoff snapshot survives later regions edits

The fixture reuses the synthetic aircraft library + the real
POST /cad-edit-handoff endpoint so the captured handoffPayload is
byte-for-byte the same shape operators will see in production.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import server  # noqa: E402
from ai_inspector.semantic_regions import (
    build_draft_regions,
    semantic_regions_path,
    write_semantic_regions,
)

# Reuse the synthetic GLB + feature_colors fixture from the broader
# semantic_regions test module so the captured handoff payload has the
# same shape operators see in production.
sys.path.insert(0, str(REPO_ROOT / "tests"))
import test_semantic_regions as _sr_tests  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PN = "1030099"
REV = "revA"


@pytest.fixture
def aircraft_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    library = tmp_path / "lib"
    rev_dir = library / "parts" / PN / REV
    rev_dir.mkdir(parents=True)
    _sr_tests._write_synthetic_glb(rev_dir / f"{PN}_colored.glb",
                                   _sr_tests._aircraft_fixture())
    (rev_dir / f"{PN}_feature_colors.json").write_text(json.dumps({
        "partNumber": PN,
        "features": [
            {
                "cad_feature_id": n,
                "glb_node_name":  n,
                "sw_name":        n.replace("_", " ").title(),
                "type":           n.split("_", 1)[0],
                "display_label":  n.replace("_", " ").title(),
            }
            for n, *_ in _sr_tests._aircraft_fixture()
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(server, "LIBRARY_DIR", library)
    yield library


@pytest.fixture
def aircraft_library_with_draft(aircraft_library: Path) -> Path:
    doc = build_draft_regions(aircraft_library, PN, REV)
    write_semantic_regions(aircraft_library, PN, REV, doc)
    return aircraft_library


def _capture_handoff_payload(
    client: TestClient, phrase: str = "top wing",
    instruction: str = "make the top wing 2 inches thicker",
) -> dict:
    """Hit the real POST /cad-edit-handoff endpoint and return its
    response so the session test exercises the exact byte shape the
    handoff layer emits in production."""
    r = client.post(
        f"/api/part-semantic-regions/{PN}/cad-edit-handoff",
        json={"revision": REV, "phrase": phrase, "userInstruction": instruction},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _create_session(client: TestClient, handoff: dict, notes: str = "") -> dict:
    body = {"handoffPayload": handoff}
    if notes:
        body["notes"] = notes
    r = client.post("/api/edit-sessions", json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Create: happy path + immutable identity derivation
# ---------------------------------------------------------------------------

def test_POST_create_session_preserves_enriched_handoff_classification(
    aircraft_library_with_draft: Path,
):
    """Per spec test 4: when the propeller-thickness handoff has
    classified editTargets / propagationFeatures / referenceFeatures,
    the create-session round-trip must preserve those arrays in the
    embedded handoffPayload verbatim. The session log is the audit
    snapshot; later curator edits to the regions file must NOT
    retroactively change what the log said was being mutated."""
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(
        client, phrase="propeller",
        instruction="make the propeller blades 2 inches thicker",
    )
    # Sanity-check the handoff itself carries the classification before
    # we even create the session.
    assert handoff["target"]["editTargets"], \
        "fixture should produce a non-empty editTargets for propeller thickness"
    captured_edit_ids = [e["cadFeatureId"] for e in handoff["target"]["editTargets"]]
    captured_prop_ids = [e["cadFeatureId"] for e in handoff["target"]["propagationFeatures"]]
    captured_ref_ids  = [e["cadFeatureId"] for e in handoff["target"]["referenceFeatures"]]

    body = _create_session(client, handoff)
    sid = body["session"]["sessionId"]
    # Re-fetch via GET so we exercise the on-disk round-trip, not just
    # the in-memory POST response.
    persisted = client.get(f"/api/edit-sessions/{sid}").json()
    target = persisted["handoffPayload"]["target"]
    assert [e["cadFeatureId"] for e in target["editTargets"]]         == captured_edit_ids
    assert [e["cadFeatureId"] for e in target["propagationFeatures"]] == captured_prop_ids
    assert [e["cadFeatureId"] for e in target["referenceFeatures"]]   == captured_ref_ids
    # And the per-entry shape survives -- each entry has all three
    # identifier fields the executor will eventually need.
    for entry in target["editTargets"]:
        assert "cadFeatureId"  in entry
        assert "sourceFeature" in entry
        assert "glbNode"       in entry


def test_POST_create_session_happy_path(aircraft_library_with_draft: Path):
    """Successful create returns a prepared session with a 26-char ULID,
    the embedded handoff payload preserved verbatim, and a session file
    on disk at the expected path."""
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(client)
    body = _create_session(client, handoff, notes="initial")
    session = body["session"]

    sid = session["sessionId"]
    assert isinstance(sid, str) and len(sid) == 26
    assert session["schemaVersion"]   == "edit-session-log-0.1"
    assert session["status"]          == "prepared"
    assert session["partNumber"]      == PN
    assert session["sourceRevision"]  == REV
    assert session["semanticPhrase"]  == "top wing"
    assert session["requestedEdit"].startswith("make the top wing")
    assert session["handoffVersion"]  == "semantic-region-cad-edit-handoff-0.1"
    assert session["handoffPayload"]  == handoff
    assert session["intent"]["action"] == "dimension_change"
    assert session["intent"]["source"] == "parser"
    assert session["target"]["regionIds"] == ["top_wing"]
    assert session["target"]["multiRegion"] is False
    assert session["createdAtUtc"]    == session["updatedAtUtc"]
    assert session["notes"] and session["notes"][0]["text"] == "initial"

    # File on disk at the expected path.
    p = aircraft_library_with_draft / "_edit_sessions" / f"{sid}.json"
    assert p.exists()


def test_send_edit_session_to_solidworks_posts_narrow_bridge_payload(
    aircraft_library_with_draft: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Browser-created edit sessions must become real SolidWorks Sage
    inbox handoffs. The server narrows the audited handoff to the
    executor-safe add-in contract."""
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(
        client, phrase="propeller",
        instruction="set the single propeller blade thickness to 6 mm",
    )
    sid = _create_session(client, handoff)["session"]["sessionId"]

    captured = {}

    async def _fake_send(payload):
        captured["payload"] = payload
        return {
            "accepted": True,
            "message": "Handoff received",
            "activeDocument": {"type": "Part", "title": "Fixture.SLDPRT"},
        }

    monkeypatch.setattr(server, "_send_sage_handoff_to_bridge", _fake_send)
    r = client.post(f"/api/edit-sessions/{sid}/send-to-solidworks")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["bridgeResponse"]["accepted"] is True

    payload = captured["payload"]
    assert payload["editSessionId"] == sid
    assert payload["partNumber"] == PN
    assert payload["sourceRevision"] == REV
    assert payload["semanticRegion"]["regionId"] == "propeller"
    assert payload["intent"] == {
        "action": "dimension_change",
        "dimension": "thickness",
        "mode": "set_absolute",
        "value": 6.0,
        "units": "mm",
    }
    assert [e["cadFeatureId"] for e in payload["editTargets"]] == ["ice_boss_extrude1"]
    assert payload["propagationFeatures"] == []
    assert payload["policy"]["requiresHumanApproval"] is True
    assert payload["policy"]["executeAfterApproval"] is False


# ---------------------------------------------------------------------------
# Batch send-to-SolidWorks (demo path). Fans N session IDs out to the
# SolidWorks Sage pane via the SAME single-session pipeline -- the
# batch endpoint owns NO new payload-building logic. Execution stays
# strictly one-at-a-time on the SolidWorks side; this only removes the
# typing burden on the operator.
# ---------------------------------------------------------------------------

def test_batch_send_fans_out_to_single_send_for_each_session(
    aircraft_library_with_draft: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """The batch endpoint must call the single-session pipeline ONCE
    per sessionId. Mocking _send_one_edit_session_to_solidworks
    isolates the fan-out contract from the per-payload transformer
    (separate tests cover that)."""
    client = TestClient(server.app)
    # Use the propeller fixture twice with two different requestedEdits
    # so dedupe does not collapse them into one session. The real
    # cad-edit-handoff endpoint produces real ULIDs we can pass to
    # the batch endpoint.
    sids: list = []
    for instruction in [
        "set the single propeller blade thickness to 6 mm",
        "set the single propeller blade thickness to 7 mm",
    ]:
        handoff = _capture_handoff_payload(client, phrase="propeller", instruction=instruction)
        sid = _create_session(client, handoff)["session"]["sessionId"]
        sids.append(sid)

    # Mock the per-session helper itself -- the fan-out test asserts
    # WIRING, not transformer correctness.
    helper_calls: list = []
    async def _fake_single(safe_id):
        helper_calls.append(safe_id)
        return {
            "ok":             True,
            "sessionId":      safe_id,
            "sentHandoff":    {"editSessionId": safe_id},
            "bridgeResponse": {"accepted": True, "queueCount": len(helper_calls)},
        }
    monkeypatch.setattr(server, "_send_one_edit_session_to_solidworks", _fake_single)

    r = client.post("/api/edit-sessions/batch-send-to-solidworks", json={
        "sessionIds": sids,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"]      is True
    assert body["sent"]    == 2
    assert body["failed"]  == 0
    assert len(body["results"]) == 2
    assert all(item["ok"] for item in body["results"])
    assert [item["sessionId"] for item in body["results"]] == sids
    # Per-item record carries the bridge response shape the queue UI
    # needs (accepted + queueCount).
    assert body["results"][0]["solidWorksResponse"]["accepted"] is True
    # Single-session helper was invoked once per sessionId, in order.
    assert helper_calls == sids


def test_batch_send_continueOnError_true_records_failures_and_keeps_going(
    aircraft_library_with_draft: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """When the bridge rejects one item (e.g. session terminal,
    bridge transient error), continueOnError=true must record the
    failure and try the remaining items. Overall endpoint still 200."""
    client = TestClient(server.app)
    handoff_a = _capture_handoff_payload(
        client, phrase="propeller",
        instruction="set the single propeller blade thickness to 6 mm",
    )
    handoff_b = _capture_handoff_payload(
        client, phrase="propeller",
        instruction="set the single propeller blade thickness to 7 mm",
    )
    sid_a = _create_session(client, handoff_a)["session"]["sessionId"]
    sid_b = _create_session(client, handoff_b)["session"]["sessionId"]
    # Patch sid_a to terminal so the per-item send fails at the
    # session-status gate inside _send_one_edit_session_to_solidworks.
    abandon = client.patch(f"/api/edit-sessions/{sid_a}",
                            json={"status": "abandoned", "abandonReason": "test"})
    assert abandon.status_code == 200, abandon.text

    sent_payloads: list = []
    async def _fake_bridge(payload):
        sent_payloads.append(payload)
        return {"accepted": True, "message": "Queued", "queueCount": len(sent_payloads)}
    monkeypatch.setattr(server, "_send_sage_handoff_to_bridge", _fake_bridge)

    r = client.post("/api/edit-sessions/batch-send-to-solidworks", json={
        "sessionIds":      [sid_a, sid_b],
        "continueOnError": True,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sent"]   == 1
    assert body["failed"] == 1
    # Per-item shape: failure records statusCode + message; success
    # records the bridge response.
    fail_item = body["results"][0]
    pass_item = body["results"][1]
    assert fail_item["sessionId"]  == sid_a
    assert fail_item["ok"]         is False
    assert fail_item["statusCode"] == 409
    assert "terminal" in fail_item["message"]
    assert pass_item["sessionId"]  == sid_b
    assert pass_item["ok"]         is True
    # Only the successful item produced a bridge POST.
    assert len(sent_payloads) == 1
    assert sent_payloads[0]["editSessionId"] == sid_b


def test_batch_send_continueOnError_false_stops_at_first_failure(
    aircraft_library_with_draft: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """continueOnError=false aborts after the first failure -- the
    remaining sessions are NOT attempted (no bridge POST for them)."""
    client = TestClient(server.app)
    handoff_a = _capture_handoff_payload(
        client, phrase="propeller",
        instruction="set the single propeller blade thickness to 6 mm",
    )
    handoff_b = _capture_handoff_payload(
        client, phrase="propeller",
        instruction="set the single propeller blade thickness to 7 mm",
    )
    sid_a = _create_session(client, handoff_a)["session"]["sessionId"]
    sid_b = _create_session(client, handoff_b)["session"]["sessionId"]
    client.patch(f"/api/edit-sessions/{sid_a}",
                 json={"status": "abandoned", "abandonReason": "test"})

    sent_payloads: list = []
    async def _fake_bridge(payload):
        sent_payloads.append(payload)
        return {"accepted": True, "message": "Queued", "queueCount": len(sent_payloads)}
    monkeypatch.setattr(server, "_send_sage_handoff_to_bridge", _fake_bridge)

    r = client.post("/api/edit-sessions/batch-send-to-solidworks", json={
        "sessionIds":      [sid_a, sid_b],
        "continueOnError": False,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sent"]          == 0
    assert body["failed"]        == 1
    assert len(body["results"])  == 1
    assert body["results"][0]["ok"] is False
    # The healthy second session was never attempted.
    assert sent_payloads == []


def test_batch_send_empty_sessionids_returns_400(aircraft_library_with_draft: Path):
    client = TestClient(server.app)
    r = client.post("/api/edit-sessions/batch-send-to-solidworks", json={"sessionIds": []})
    assert r.status_code == 400, r.text
    assert "sessionIds" in r.text


def test_batch_send_invalid_sessionid_recorded_as_per_item_400(
    aircraft_library_with_draft: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Garbage sessionIds are recorded as per-item 400 entries, NOT
    raised globally. The endpoint contract is "report per-item;
    keep going" when continueOnError=true."""
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(
        client, phrase="propeller",
        instruction="set the single propeller blade thickness to 6 mm",
    )
    sid = _create_session(client, handoff)["session"]["sessionId"]

    async def _fake_bridge(payload):
        return {"accepted": True, "message": "Queued"}
    monkeypatch.setattr(server, "_send_sage_handoff_to_bridge", _fake_bridge)

    r = client.post("/api/edit-sessions/batch-send-to-solidworks", json={
        "sessionIds": ["not-a-ulid", sid],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sent"]   == 1
    assert body["failed"] == 1
    assert body["results"][0]["statusCode"] == 400
    assert body["results"][1]["sessionId"]  == sid


# ---------------------------------------------------------------------------
# Demo-batch Sage fast path. Builds 3 real cad-edit-handoff payloads
# against 1030035 Rev A, creates 3 edit sessions, batch-sends them to
# the SolidWorks Sage pane. Default response is concise and physical-
# language; CAD internals stay out of the user-facing reply.
# ---------------------------------------------------------------------------

def test_demo_batch_detector_recognises_canonical_phrasings():
    assert server._is_demo_batch_handoff_request("queue the caster demo handoffs")
    assert server._is_demo_batch_handoff_request("prepare the three caster demo changes")
    assert server._is_demo_batch_handoff_request("prepare demo handoffs for 1030035 Rev A")
    assert server._is_demo_batch_handoff_request("Send the demo handoffs")
    assert server._is_demo_batch_handoff_request(
        "For 1030035 Rev A set the mounting plate length to 150 mm, "
        "mounting plate thickness\n  to 15 mm, and mounting slot width to 10 mm."
    )
    # Plain single-handoff phrasings must NOT match.
    assert not server._is_demo_batch_handoff_request(
        "prepare a SolidWorks handoff: set the mounting plate length to 150 mm")
    assert not server._is_demo_batch_handoff_request("compare rev A and rev B")
    assert not server._is_demo_batch_handoff_request("")

def _make_sketch_handoff_payload(
    sketch_feature: str | None  = "Sketch270",
    dimension_short: str | None = "D1",
    downstream:      list | None = None,
    value:           float = 3.0,
    units:           str   = "mm",
    mode:            str   = "set_absolute",
    feature_id:      str   = "boss_extrude2",
    feature_name:    str   = "Boss-Extrude2",
) -> dict:
    """Build a minimal sketch_dimension_change cad-edit-handoff payload
    that the bridge transformer can chew on. Shape mirrors what
    _semantic_region_cad_edit_handoff_payload emits for the sketch
    action -- the sketch fields land on target as additive keys."""
    target: dict = {
        "regions": [{"regionId": "outer_wing_strut",
                      "label":    "Outer Wing Strut",
                      "confidence": "medium",
                      "reviewed":  False}],
        "cadFeatureIds":  [feature_id],
        "sourceFeatures": [feature_name],
        "glbNodes":       [feature_id],
        "multiRegion":    False,
        "editTargets": [{
            "cadFeatureId":  feature_id,
            "sourceFeature": feature_name,
            "glbNode":       feature_id,
        }],
        "propagationFeatures": [],
        "referenceFeatures":   [],
    }
    target["sketchFeature"]      = sketch_feature
    target["dimensionShortName"] = dimension_short
    target["downstreamFeatures"] = downstream if downstream is not None else []
    return {
        "handoffVersion":   "semantic-region-cad-edit-handoff-0.1",
        "supportedActions": [
            "dimension_change", "sketch_dimension_change",
            "hole_pattern", "sketch_on_face", "unknown",
        ],
        "matched":          True,
        "partNumber":       PN,
        "revision":         REV,
        "userInstruction":  "set the outer wing strut thickness to 3 mm via sketch dimension",
        "resolvedPhrase":   "outer wing strut",
        "intent": {
            "action":         "sketch_dimension_change",
            "parameterHints": {
                "value":     value,
                "units":     units,
                "dimension": "thickness",
                "mode":      mode,
            },
            "parserAction":    "sketch_dimension_change",
            "requestedAction": None,
            "source":          "parser",
            "confidence":      "high",
        },
        "target":          target,
        "placement":       {"surfaces": [], "capabilities": [], "editReadiness": "not_ready"},
        "operationPolicy": {
            "canEdit":                   False,
            "requiresHumanReview":       True,
            "multiRegionReviewRequired": False,
            "blockedReason":             "sketch_dimension_change is preview-only in InspectorPro.",
        },
    }


def test_bridge_transformer_dimension_change_payload_unchanged_by_track_b(
    aircraft_library_with_draft: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Regression: the existing dimension_change wire payload must stay
    byte-identical after Track B teaches the transformer about sketch
    handoffs. Sketch fields must NOT leak onto the direct path."""
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(
        client, phrase="propeller",
        instruction="set the single propeller blade thickness to 6 mm",
    )
    sid = _create_session(client, handoff)["session"]["sessionId"]

    captured = {}

    async def _fake_send(payload):
        captured["payload"] = payload
        return {"accepted": True, "message": "ok"}

    monkeypatch.setattr(server, "_send_sage_handoff_to_bridge", _fake_send)
    r = client.post(f"/api/edit-sessions/{sid}/send-to-solidworks")
    assert r.status_code == 200, r.text
    payload = captured["payload"]
    assert payload["intent"]["action"] == "dimension_change"
    # Sketch fields MUST NOT appear on direct-dim payloads -- the add-in
    # SageHandoff DTO can still deserialize them as null but emitting
    # them on the wire would expand the contract for no benefit.
    assert "sketchFeature"      not in payload
    assert "dimensionShortName" not in payload
    assert "downstreamFeatures" not in payload


def test_bridge_transformer_sketch_action_forwards_with_intent_and_sketch_fields(
    aircraft_library_with_draft: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Happy path: a sketch_dimension_change session sends through
    /send-to-solidworks, the narrow Sage payload preserves the
    intent.action verbatim, and the three additive sketch fields land
    on the wire as top-level keys (matching the add-in SageHandoff
    [JsonProperty] shape)."""
    client = TestClient(server.app)
    handoff = _make_sketch_handoff_payload(
        sketch_feature="Sketch270",
        dimension_short="D1",
        downstream=[
            {"cadFeatureId": "cirpattern_struts", "sourceFeature": "CirPattern1", "glbNode": "cirpattern_struts"},
            {"cadFeatureId": "fillet_strut_root", "sourceFeature": "Fillet3",     "glbNode": "fillet_strut_root"},
        ],
    )
    sid = _create_session(client, handoff)["session"]["sessionId"]

    captured = {}

    async def _fake_send(payload):
        captured["payload"] = payload
        return {"accepted": True, "message": "ok"}

    monkeypatch.setattr(server, "_send_sage_handoff_to_bridge", _fake_send)
    r = client.post(f"/api/edit-sessions/{sid}/send-to-solidworks")
    assert r.status_code == 200, r.text
    payload = captured["payload"]
    assert payload["intent"]["action"]    == "sketch_dimension_change"
    assert payload["intent"]["mode"]      == "set_absolute"
    assert payload["intent"]["units"]     == "mm"
    assert payload["intent"]["value"]     == 3.0
    assert payload["intent"]["dimension"] == "thickness"
    assert [e["cadFeatureId"] for e in payload["editTargets"]] == ["boss_extrude2"]
    assert payload["sketchFeature"]      == "Sketch270"
    assert payload["dimensionShortName"] == "D1"
    ds_ids = [d["cadFeatureId"] for d in payload["downstreamFeatures"]]
    assert ds_ids == ["cirpattern_struts", "fillet_strut_root"]
    # Each downstream entry carries the SW-target shape the add-in
    # expects (cadFeatureId, sourceFeature, role).
    assert payload["downstreamFeatures"][0]["role"]          == "downstream_feature"
    assert payload["downstreamFeatures"][0]["sourceFeature"] == "CirPattern1"


def test_bridge_transformer_sketch_action_passes_null_when_metadata_unknown(
    aircraft_library_with_draft: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Per spec: InspectorPro must NOT synthesize fake sketch names.
    Null in -> null out, empty list when no downstream. The add-in then
    requires the operator to pick a sketch candidate before Apply
    enables (its sketch_operator_must_select gate)."""
    client = TestClient(server.app)
    handoff = _make_sketch_handoff_payload(
        sketch_feature=None,
        dimension_short=None,
        downstream=[],
    )
    sid = _create_session(client, handoff)["session"]["sessionId"]

    captured = {}
    async def _fake_send(payload):
        captured["payload"] = payload
        return {"accepted": True, "message": "ok"}

    monkeypatch.setattr(server, "_send_sage_handoff_to_bridge", _fake_send)
    r = client.post(f"/api/edit-sessions/{sid}/send-to-solidworks")
    assert r.status_code == 200, r.text
    payload = captured["payload"]
    assert payload["intent"]["action"]   == "sketch_dimension_change"
    assert payload["sketchFeature"]      is None
    assert payload["dimensionShortName"] is None
    assert payload["downstreamFeatures"] == []


def test_bridge_transformer_sketch_action_treats_empty_string_metadata_as_null(
    aircraft_library_with_draft: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Defence-in-depth: an empty/whitespace string is functionally the
    same as null -- the transformer normalises both to None so the
    add-in's gate never sees an empty-but-not-null name and tries to
    look up a feature named ''. """
    client = TestClient(server.app)
    handoff = _make_sketch_handoff_payload(
        sketch_feature="   ",
        dimension_short="",
        downstream=[],
    )
    sid = _create_session(client, handoff)["session"]["sessionId"]

    captured = {}
    async def _fake_send(payload):
        captured["payload"] = payload
        return {"accepted": True, "message": "ok"}

    monkeypatch.setattr(server, "_send_sage_handoff_to_bridge", _fake_send)
    r = client.post(f"/api/edit-sessions/{sid}/send-to-solidworks")
    assert r.status_code == 200, r.text
    payload = captured["payload"]
    assert payload["sketchFeature"]      is None
    assert payload["dimensionShortName"] is None


def test_bridge_transformer_unsupported_action_still_returns_409(
    aircraft_library_with_draft: Path,
):
    """Wrong intent.action must still 409 (not silently send). Tests
    the union {dimension_change, sketch_dimension_change}; anything
    else refuses with a clear message naming both supported actions."""
    client = TestClient(server.app)
    handoff = _make_sketch_handoff_payload()
    handoff["intent"]["action"] = "hole_pattern"
    sid = _create_session(client, handoff)["session"]["sessionId"]

    r = client.post(f"/api/edit-sessions/{sid}/send-to-solidworks")
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert "dimension_change" in detail
    assert "sketch_dimension_change" in detail


def test_bridge_transformer_sketch_action_non_mm_units_returns_409(
    aircraft_library_with_draft: Path,
):
    """Same shape gates apply to the sketch action: units must be mm."""
    client = TestClient(server.app)
    handoff = _make_sketch_handoff_payload(units="in")
    sid = _create_session(client, handoff)["session"]["sessionId"]

    r = client.post(f"/api/edit-sessions/{sid}/send-to-solidworks")
    assert r.status_code == 409, r.text
    assert "millimeters" in r.json()["detail"]


def test_bridge_transformer_sketch_action_non_set_absolute_mode_returns_409(
    aircraft_library_with_draft: Path,
):
    """Sketch action must also gate mode == set_absolute (no delta)."""
    client = TestClient(server.app)
    handoff = _make_sketch_handoff_payload(mode="delta")
    sid = _create_session(client, handoff)["session"]["sessionId"]

    r = client.post(f"/api/edit-sessions/{sid}/send-to-solidworks")
    assert r.status_code == 409, r.text
    assert "set_absolute" in r.json()["detail"]


def test_bridge_transformer_sketch_action_invalid_value_returns_409(
    aircraft_library_with_draft: Path,
):
    """Finite positive value gate applies to both actions."""
    client = TestClient(server.app)
    handoff = _make_sketch_handoff_payload(value=-1.0)
    sid = _create_session(client, handoff)["session"]["sessionId"]

    r = client.post(f"/api/edit-sessions/{sid}/send-to-solidworks")
    assert r.status_code == 409, r.text
    assert "greater than zero" in r.json()["detail"]


def test_bridge_transformer_sketch_action_no_edit_targets_returns_409(
    aircraft_library_with_draft: Path,
):
    """No editTargets means the add-in has nothing to anchor the
    sketch edit to. Must refuse rather than send a half-payload."""
    client = TestClient(server.app)
    handoff = _make_sketch_handoff_payload()
    handoff["target"]["editTargets"] = []
    sid = _create_session(client, handoff)["session"]["sessionId"]

    r = client.post(f"/api/edit-sessions/{sid}/send-to-solidworks")
    assert r.status_code == 409, r.text
    assert "editTargets" in r.json()["detail"]


def test_POST_create_session_returns_existing_on_duplicate_intent(
    aircraft_library_with_draft: Path,
):
    """Duplicate-intent policy: second create with the same (pn, rev,
    phrase, action, requestedEdit) tuple returns the EXISTING session
    + a warning, NOT a new file."""
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(client)
    first = _create_session(client, handoff)
    first_id = first["session"]["sessionId"]

    second = _create_session(client, handoff)
    assert second["session"]["sessionId"] == first_id
    assert "warning" in second
    assert "already exists" in second["warning"]

    # Only ONE file on disk for the intent.
    sessions_dir = aircraft_library_with_draft / "_edit_sessions"
    files = [f for f in sessions_dir.iterdir() if f.suffix == ".json"]
    assert len(files) == 1


def test_POST_create_session_allows_same_region_action_with_different_requested_edit(
    aircraft_library_with_draft: Path,
):
    """Regression for sketch-dimension naming: a refined instruction
    like "front strut diameter" must not reuse an older "outer strut
    thickness" sketch session just because pn/rev/phrase/action match."""
    client = TestClient(server.app)
    first_handoff = _make_sketch_handoff_payload(
        sketch_feature=None,
        dimension_short=None,
    )
    first_handoff["resolvedPhrase"] = "Outer wing strut"
    first_handoff["userInstruction"] = (
        "edit the sketch dimension controlling the outer wing strut thickness to 3 mm"
    )
    second_handoff = json.loads(json.dumps(first_handoff))
    second_handoff["userInstruction"] = "set the front strut diameter to 3 mm"
    second_handoff["target"]["sketchFeature"] = "Sketch270"
    second_handoff["target"]["dimensionShortName"] = "D1"
    second_handoff["target"]["sketchDimensionIntent"] = {
        "displayName": "front strut diameter",
        "sketchFeature": "Sketch270",
        "dimensionShortName": "D1",
    }

    first = _create_session(client, first_handoff)
    second = _create_session(client, second_handoff)

    assert second["session"]["sessionId"] != first["session"]["sessionId"]
    assert "warning" not in second
    assert second["session"]["handoffPayload"]["target"]["sketchFeature"] == "Sketch270"
    assert second["session"]["handoffPayload"]["target"]["dimensionShortName"] == "D1"


def test_POST_create_session_dedupe_after_abandon_creates_new(
    aircraft_library_with_draft: Path,
):
    """Once the prior session is abandoned (terminal), a follow-up
    create for the same intent must produce a NEW session because the
    duplicate gate only considers OPEN (non-terminal) sessions."""
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(client)
    first_id = _create_session(client, handoff)["session"]["sessionId"]
    # Abandon the first.
    r = client.patch(f"/api/edit-sessions/{first_id}",
                     json={"status": "abandoned", "abandonReason": "test"})
    assert r.status_code == 200, r.text

    second_id = _create_session(client, handoff)["session"]["sessionId"]
    assert second_id != first_id


# ---------------------------------------------------------------------------
# Create: validation
# ---------------------------------------------------------------------------

def test_POST_create_rejects_canEdit_true(aircraft_library_with_draft: Path):
    """Defensive gate: MVP only accepts read-only handoffs. The error
    message must mention executor implementation so operators know
    this is a temporary limit, not a permanent reject."""
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(client)
    handoff["operationPolicy"]["canEdit"] = True
    r = client.post("/api/edit-sessions", json={"handoffPayload": handoff})
    assert r.status_code == 400, r.text
    assert "edit execution is implemented" in r.text


def test_POST_create_rejects_stale_handoffVersion(aircraft_library_with_draft: Path):
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(client)
    handoff["handoffVersion"] = "semantic-region-cad-edit-handoff-0.0.99"
    r = client.post("/api/edit-sessions", json={"handoffPayload": handoff})
    assert r.status_code == 400, r.text
    assert "handoffVersion" in r.text


def test_POST_create_rejects_matched_false(aircraft_library_with_draft: Path):
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(client)
    handoff["matched"] = False
    r = client.post("/api/edit-sessions", json={"handoffPayload": handoff})
    assert r.status_code == 400, r.text
    assert "matched" in r.text


def test_POST_create_rejects_missing_part_dir(aircraft_library_with_draft: Path):
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(client)
    handoff["partNumber"] = "9999999"
    r = client.post("/api/edit-sessions", json={"handoffPayload": handoff})
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# GET single + handoff-payload + list filters
# ---------------------------------------------------------------------------

def test_GET_single_returns_full_doc(aircraft_library_with_draft: Path):
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(client)
    sid = _create_session(client, handoff)["session"]["sessionId"]
    r = client.get(f"/api/edit-sessions/{sid}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sessionId"] == sid
    assert body["handoffPayload"] == handoff


def test_GET_single_404_when_missing(aircraft_library_with_draft: Path):
    client = TestClient(server.app)
    r = client.get("/api/edit-sessions/01HKZZZZZZZZZZZZZZZZZZZZZZ")
    assert r.status_code == 404


def test_GET_handoff_payload_returns_embedded_snapshot_only(
    aircraft_library_with_draft: Path,
):
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(client)
    sid = _create_session(client, handoff)["session"]["sessionId"]
    r = client.get(f"/api/edit-sessions/{sid}/handoff-payload")
    assert r.status_code == 200, r.text
    assert r.json() == handoff


def test_GET_list_filters_by_partNumber_and_status_and_openOnly(
    aircraft_library_with_draft: Path,
):
    client = TestClient(server.app)
    # Two sessions on different revs/phrases so the dedupe doesn't
    # collapse them.
    h1 = _capture_handoff_payload(client, phrase="top wing")
    h2 = _capture_handoff_payload(client, phrase="lower wing",
                                  instruction="add 4 holes to the lower wing")
    sid1 = _create_session(client, h1)["session"]["sessionId"]
    sid2 = _create_session(client, h2)["session"]["sessionId"]
    # Move sid2 to abandoned so we can prove openOnly excludes it.
    client.patch(f"/api/edit-sessions/{sid2}",
                 json={"status": "abandoned", "abandonReason": "test"})

    all_listed = client.get("/api/edit-sessions").json()
    assert all_listed["count"] == 2
    listed_ids = {s["sessionId"] for s in all_listed["sessions"]}
    assert listed_ids == {sid1, sid2}

    open_only = client.get("/api/edit-sessions", params={"openOnly": "true"}).json()
    assert open_only["count"] == 1
    assert open_only["sessions"][0]["sessionId"] == sid1

    by_status = client.get("/api/edit-sessions", params={"status": "abandoned"}).json()
    assert by_status["count"] == 1
    assert by_status["sessions"][0]["sessionId"] == sid2

    by_pn = client.get("/api/edit-sessions", params={"partNumber": PN}).json()
    assert by_pn["count"] == 2
    by_rev = client.get("/api/edit-sessions", params={"sourceRevision": "A"}).json()
    assert by_rev["count"] == 2


def test_GET_list_rejects_unknown_status_filter(aircraft_library_with_draft: Path):
    client = TestClient(server.app)
    r = client.get("/api/edit-sessions", params={"status": "not_a_status"})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# PATCH FSM
# ---------------------------------------------------------------------------

def test_PATCH_legal_transition_prepared_to_applied(
    aircraft_library_with_draft: Path,
):
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(client)
    sid = _create_session(client, handoff)["session"]["sessionId"]

    r = client.patch(f"/api/edit-sessions/{sid}", json={
        "status":  "applied_in_solidworks",
        "applied": {"appliedAtUtc": "2026-05-22T18:32:44.881Z",
                    "appliedByUser": "skaumb"},
    })
    assert r.status_code == 200, r.text
    session = r.json()["session"]
    assert session["status"] == "applied_in_solidworks"
    assert session["applied"]["appliedByUser"] == "skaumb"
    assert session["updatedAtUtc"] != session["createdAtUtc"]


def test_PATCH_illegal_transition_returns_409(aircraft_library_with_draft: Path):
    """prepared -> compared skips four legal states. Must be rejected
    with 409 + an explanatory message listing the allowed successors."""
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(client)
    sid = _create_session(client, handoff)["session"]["sessionId"]
    r = client.patch(f"/api/edit-sessions/{sid}", json={"status": "compared"})
    assert r.status_code == 409, r.text
    assert "Illegal status transition" in r.text


def test_PATCH_promoted_without_promotedRevision_rejected(
    aircraft_library_with_draft: Path,
):
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(client)
    sid = _create_session(client, handoff)["session"]["sessionId"]
    # Walk through legal transitions until we can attempt 'promoted'.
    client.patch(f"/api/edit-sessions/{sid}", json={"status": "applied_in_solidworks"})
    client.patch(f"/api/edit-sessions/{sid}", json={
        "status":     "extracted",
        "extraction": {"resultingPartPackageId": "pkg-xyz"},
    })
    client.patch(f"/api/edit-sessions/{sid}", json={"status": "linked_to_revision"})

    r = client.patch(f"/api/edit-sessions/{sid}", json={"status": "promoted"})
    assert r.status_code == 400, r.text
    assert "promotion.promotedRevision" in r.text


def test_PATCH_promoted_requires_existing_revision_dir(
    aircraft_library_with_draft: Path,
):
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(client)
    sid = _create_session(client, handoff)["session"]["sessionId"]
    for kw in (
        {"status": "applied_in_solidworks"},
        {"status": "extracted", "extraction": {"resultingPartPackageId": "pkg"}},
        {"status": "linked_to_revision"},
    ):
        client.patch(f"/api/edit-sessions/{sid}", json=kw)

    # Rev directory 'revZ' does not exist; PATCH must reject.
    r = client.patch(f"/api/edit-sessions/{sid}", json={
        "status":    "promoted",
        "promotion": {"promotedRevision": "Z"},
    })
    assert r.status_code == 400, r.text
    assert "does not exist on disk" in r.text


def test_PATCH_promoted_then_compared_full_loop(
    aircraft_library_with_draft: Path,
):
    """End-to-end happy path through prepared -> compared, including
    creating the new revision directory the promotion will point at."""
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(client)
    sid = _create_session(client, handoff)["session"]["sessionId"]
    # Create the post-edit revision directory the promotion will link to.
    rev_b_dir = aircraft_library_with_draft / "parts" / PN / "revB"
    rev_b_dir.mkdir(parents=True)
    # Minimal GLB so the dir is not just an empty marker.
    _sr_tests._write_synthetic_glb(
        rev_b_dir / f"{PN}_colored.glb",
        _sr_tests._aircraft_fixture(),
    )

    for kw in (
        {"status": "applied_in_solidworks"},
        {"status": "extracted", "extraction": {"resultingPartPackageId": "pkg-revb"}},
        {"status": "linked_to_revision"},
        {"status": "promoted", "promotion": {"promotedRevision": "B"}},
    ):
        r = client.patch(f"/api/edit-sessions/{sid}", json=kw)
        assert r.status_code == 200, r.text

    # comparison.revA must equal sourceRevision (revA); revB must equal promoted (revB).
    bad = client.patch(f"/api/edit-sessions/{sid}", json={
        "status":     "compared",
        "comparison": {"revA": "B", "revB": "A"},
    })
    assert bad.status_code == 400
    good = client.patch(f"/api/edit-sessions/{sid}", json={
        "status":     "compared",
        "comparison": {"revA": "revA", "revB": "revB"},
    })
    assert good.status_code == 200, good.text
    final = good.json()["session"]
    assert final["status"] == "compared"
    assert final["promotion"]["promotedRevision"] == "revB"


def test_PATCH_failed_requires_failureReason(aircraft_library_with_draft: Path):
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(client)
    sid = _create_session(client, handoff)["session"]["sessionId"]
    client.patch(f"/api/edit-sessions/{sid}", json={"status": "applied_in_solidworks"})
    r = client.patch(f"/api/edit-sessions/{sid}", json={"status": "failed"})
    assert r.status_code == 400, r.text
    assert "failureReason" in r.text

    r2 = client.patch(f"/api/edit-sessions/{sid}", json={
        "status":        "failed",
        "failureReason": "SolidWorks rebuild failed: missing reference",
    })
    assert r2.status_code == 200, r2.text


def test_PATCH_terminal_session_rejects_status_change_but_allows_note(
    aircraft_library_with_draft: Path,
):
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(client)
    sid = _create_session(client, handoff)["session"]["sessionId"]
    client.patch(f"/api/edit-sessions/{sid}",
                 json={"status": "abandoned", "abandonReason": "test"})

    # Status change rejected.
    r = client.patch(f"/api/edit-sessions/{sid}", json={"status": "prepared"})
    assert r.status_code == 409, r.text
    assert "terminal" in r.text.lower()

    # noteToAppend still accepted.
    r2 = client.patch(f"/api/edit-sessions/{sid}", json={
        "noteToAppend": "post-mortem: this was the wrong target region",
        "byUser":       "skaumb",
    })
    assert r2.status_code == 200, r2.text
    session = r2.json()["session"]
    assert any("post-mortem" in n["text"] for n in session["notes"])
    assert session["status"] == "abandoned"  # still terminal


# ---------------------------------------------------------------------------
# Immutable-field guard
# ---------------------------------------------------------------------------

def test_PATCH_rejects_immutable_field_mutation(aircraft_library_with_draft: Path):
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(client)
    sid = _create_session(client, handoff)["session"]["sessionId"]

    for field, value in [
        ("partNumber",    "9999999"),
        ("sourceRevision","revQ"),
        ("semanticPhrase","tail"),
        ("handoffPayload",{"different": "doc"}),
        ("target",        {"regionIds": []}),
        ("intent",        {"action": "unknown"}),
        ("sessionId",     "01HZZZZZZZZZZZZZZZZZZZZZZZ"),
    ]:
        r = client.patch(f"/api/edit-sessions/{sid}", json={field: value})
        assert r.status_code == 400, f"expected 400 mutating {field!r}, got {r.status_code}: {r.text}"
        assert "immutable" in r.text.lower()


# ---------------------------------------------------------------------------
# noteToAppend semantics
# ---------------------------------------------------------------------------

def test_PATCH_noteToAppend_appends_with_timestamp_and_byUser(
    aircraft_library_with_draft: Path,
):
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(client)
    sid = _create_session(client, handoff, notes="created")["session"]["sessionId"]

    r1 = client.patch(f"/api/edit-sessions/{sid}", json={
        "noteToAppend": "first follow-up",
        "byUser":       "skaumb",
    })
    assert r1.status_code == 200, r1.text
    r2 = client.patch(f"/api/edit-sessions/{sid}", json={
        "noteToAppend": "second follow-up",
    })
    assert r2.status_code == 200, r2.text

    session = client.get(f"/api/edit-sessions/{sid}").json()
    notes = session["notes"]
    assert [n["text"] for n in notes] == [
        "created", "first follow-up", "second follow-up",
    ]
    assert notes[1]["byUser"] == "skaumb"
    assert notes[2]["byUser"] is None
    # Timestamps monotonically advance.
    assert notes[0]["atUtc"] <= notes[1]["atUtc"] <= notes[2]["atUtc"]


# ---------------------------------------------------------------------------
# Atomicity + embedded snapshot durability
# ---------------------------------------------------------------------------

def test_failed_PATCH_leaves_no_tmp_file(aircraft_library_with_draft: Path):
    """A validation-rejected PATCH must NOT leave a .tmp file on disk
    AND must not modify the existing session contents."""
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(client)
    sid = _create_session(client, handoff)["session"]["sessionId"]
    p = aircraft_library_with_draft / "_edit_sessions" / f"{sid}.json"
    before = p.read_bytes()

    # Illegal transition -> 409, no write should occur.
    r = client.patch(f"/api/edit-sessions/{sid}", json={"status": "compared"})
    assert r.status_code == 409, r.text

    # Doc bytes unchanged + no .tmp left behind.
    assert p.read_bytes() == before
    tmp = p.with_suffix(p.suffix + ".tmp")
    assert not tmp.exists()


def test_embedded_handoffPayload_survives_regions_file_edits(
    aircraft_library_with_draft: Path,
):
    """Provenance contract: a curator editing {pn}_semantic_regions.json
    AFTER session creation must NOT retroactively change what the
    session log captured. The embedded handoffPayload is a snapshot."""
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(client)
    sid = _create_session(client, handoff)["session"]["sessionId"]

    # Mutate the regions file: rename the top_wing label.
    p = semantic_regions_path(aircraft_library_with_draft, PN, REV)
    doc = json.loads(p.read_text(encoding="utf-8-sig"))
    for r in doc["regions"]:
        if r["regionId"] == "top_wing":
            r["label"] = "OPERATOR-RENAMED"
    write_semantic_regions(aircraft_library_with_draft, PN, REV, doc)

    # Session's embedded payload still shows the ORIGINAL label.
    persisted = client.get(f"/api/edit-sessions/{sid}").json()
    target_regions = persisted["handoffPayload"]["target"]["regions"]
    labels = [r.get("label") for r in target_regions]
    assert "OPERATOR-RENAMED" not in labels, \
        "embedded handoffPayload must NOT change when regions file is edited later"


# ===========================================================================
# POST /api/library/intake/post-edit-sync-preview
# ===========================================================================
#
# Read-only matcher: given a newly-extracted bridge package, find candidate
# open sessions waiting at applied_in_solidworks and return ranked
# suggestions. The bridge sidecar manifest's optional sessionId /
# editSessionId field auto-promotes a candidate to high confidence;
# otherwise candidates are ranked by appliedAtUtc desc with medium
# confidence. The endpoint never mutates session files.

PKG_ID = "pkg-2026-05-22-abc"


def _write_bridge_package_manifest(
    library: Path, pn: str, package_id: str,
    *, session_id: Optional[str] = None,
    edit_session_id: Optional[str] = None,
    source_path: Optional[str] = None,
) -> Path:
    """Plant a minimal bridge sidecar manifest at the canonical path so
    the sync-preview endpoint has something to read."""
    bridge_dir = library / "_bridge_imports" / "part" / pn / package_id
    bridge_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"partNumber": pn, "packageId": package_id}
    if session_id is not None:
        manifest["sessionId"] = session_id
    if edit_session_id is not None:
        manifest["editSessionId"] = edit_session_id
    if source_path is not None:
        manifest["sourceDocument"] = {"path": source_path}
    p = bridge_dir / "manifest.json"
    p.write_text(json.dumps(manifest), encoding="utf-8")
    return p


def _advance_to_applied(client: TestClient, session_id: str) -> None:
    """Walk a freshly-created session to applied_in_solidworks. Tests
    that need an applied-state session use this helper."""
    r = client.patch(f"/api/edit-sessions/{session_id}", json={
        "status":  "applied_in_solidworks",
        "applied": {"appliedAtUtc": _iso_marker(session_id),
                    "appliedByUser": "skaumb"},
    })
    assert r.status_code == 200, r.text


def _iso_marker(seed: str) -> str:
    """Stable, sortable timestamps derived from the session id so we
    can prove ordering deterministically. Uses the ULID's first chars
    to spread timestamps a known distance apart."""
    base = "2026-05-22T18:"
    # Use seed length parity to spread minutes apart deterministically.
    minute = (sum(ord(c) for c in seed) % 50) + 10
    return f"{base}{minute:02d}:00.000Z"


def test_sync_preview_missing_manifest_returns_404(
    aircraft_library_with_draft: Path,
):
    """No sidecar manifest at the package path -> 404 with a clear
    remediation message."""
    client = TestClient(server.app)
    r = client.post("/api/library/intake/post-edit-sync-preview", json={
        "partNumber":    PN,
        "partPackageId": "does-not-exist",
    })
    assert r.status_code == 404, r.text
    assert "No bridge sidecar manifest" in r.text


def test_sync_preview_no_applied_sessions_returns_empty(
    aircraft_library_with_draft: Path,
):
    """Sidecar exists but no session is at applied_in_solidworks ->
    matched=false, empty candidates, recommendedNextAction signals it."""
    _write_bridge_package_manifest(aircraft_library_with_draft, PN, PKG_ID)
    client = TestClient(server.app)
    # Create a session and leave it at the default 'prepared' state.
    handoff = _capture_handoff_payload(client)
    _create_session(client, handoff)
    r = client.post("/api/library/intake/post-edit-sync-preview", json={
        "partNumber":    PN,
        "partPackageId": PKG_ID,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["matched"]               is False
    assert body["candidateSessions"]     == []
    assert body["recommendedNextAction"] == "no_candidate_session"
    assert body["packageManifestPath"].endswith(f"/{PKG_ID}/manifest.json")


def test_sync_preview_single_applied_session_returns_medium(
    aircraft_library_with_draft: Path,
):
    """One applied session for the part + no manifest stamp -> single
    candidate with confidence=medium, reason=recent_applied_session."""
    _write_bridge_package_manifest(aircraft_library_with_draft, PN, PKG_ID,
                                   source_path=r"C:\CAD\Aircraft\Top.SLDPRT")
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(client)
    sid = _create_session(client, handoff)["session"]["sessionId"]
    _advance_to_applied(client, sid)

    r = client.post("/api/library/intake/post-edit-sync-preview", json={
        "partNumber":    PN,
        "partPackageId": PKG_ID,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["matched"]                                is True
    assert body["packageSourcePath"]                      == r"C:\CAD\Aircraft\Top.SLDPRT"
    assert body["recommendedNextAction"]                  == "patch_session_to_extracted"
    assert len(body["candidateSessions"])                 == 1
    cand = body["candidateSessions"][0]
    assert cand["sessionId"]                              == sid
    assert cand["confidence"]                             == "medium"
    assert cand["reason"]                                 == "recent_applied_session"
    assert cand["recommendedPatch"] == {
        "status":     "extracted",
        "extraction": {"resultingPartPackageId": PKG_ID},
    }


def test_sync_preview_candidates_sorted_by_appliedAtUtc_desc(
    aircraft_library_with_draft: Path,
):
    """Two applied sessions for the same part, no manifest stamp ->
    most-recent appliedAtUtc comes first."""
    _write_bridge_package_manifest(aircraft_library_with_draft, PN, PKG_ID)
    client = TestClient(server.app)
    h1 = _capture_handoff_payload(client, phrase="top wing")
    h2 = _capture_handoff_payload(client, phrase="lower wing",
                                  instruction="add 4 holes to the lower wing")
    sid1 = _create_session(client, h1)["session"]["sessionId"]
    sid2 = _create_session(client, h2)["session"]["sessionId"]
    # Pin appliedAtUtc explicitly so the test is order-deterministic.
    client.patch(f"/api/edit-sessions/{sid1}", json={
        "status":  "applied_in_solidworks",
        "applied": {"appliedAtUtc": "2026-05-22T18:10:00.000Z"},
    })
    client.patch(f"/api/edit-sessions/{sid2}", json={
        "status":  "applied_in_solidworks",
        "applied": {"appliedAtUtc": "2026-05-22T18:30:00.000Z"},
    })

    r = client.post("/api/library/intake/post-edit-sync-preview", json={
        "partNumber":    PN,
        "partPackageId": PKG_ID,
    })
    assert r.status_code == 200, r.text
    ids = [c["sessionId"] for c in r.json()["candidateSessions"]]
    assert ids == [sid2, sid1], \
        f"expected most-recent applied session first, got {ids}"


def test_sync_preview_manifest_sessionId_match_promotes_to_high(
    aircraft_library_with_draft: Path,
):
    """Manifest stamps an exact sessionId that matches an open applied
    session -> that session is first with confidence=high. Other applied
    sessions for the same part remain as medium fallbacks."""
    client = TestClient(server.app)
    h1 = _capture_handoff_payload(client, phrase="top wing")
    h2 = _capture_handoff_payload(client, phrase="lower wing",
                                  instruction="add 4 holes to the lower wing")
    sid1 = _create_session(client, h1)["session"]["sessionId"]
    sid2 = _create_session(client, h2)["session"]["sessionId"]
    # Both applied -- sid1 EARLIER, sid2 LATER.
    client.patch(f"/api/edit-sessions/{sid1}", json={
        "status":  "applied_in_solidworks",
        "applied": {"appliedAtUtc": "2026-05-22T18:10:00.000Z"},
    })
    client.patch(f"/api/edit-sessions/{sid2}", json={
        "status":  "applied_in_solidworks",
        "applied": {"appliedAtUtc": "2026-05-22T18:30:00.000Z"},
    })
    # Manifest stamps the OLDER session id -> still wins over the
    # newer one because the explicit stamp outranks recency.
    _write_bridge_package_manifest(aircraft_library_with_draft, PN, PKG_ID,
                                   session_id=sid1)

    r = client.post("/api/library/intake/post-edit-sync-preview", json={
        "partNumber":    PN,
        "partPackageId": PKG_ID,
    })
    assert r.status_code == 200, r.text
    cands = r.json()["candidateSessions"]
    assert [c["sessionId"] for c in cands] == [sid1, sid2]
    assert cands[0]["confidence"] == "high"
    assert cands[0]["reason"]     == "manifest_session_id"
    assert cands[1]["confidence"] == "medium"
    assert cands[1]["reason"]     == "recent_applied_session"


def test_sync_preview_manifest_editSessionId_match_also_promotes(
    aircraft_library_with_draft: Path,
):
    """The endpoint accepts both `sessionId` and `editSessionId` keys
    in the manifest -- a future bridge add-in may pick either name."""
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(client)
    sid = _create_session(client, handoff)["session"]["sessionId"]
    _advance_to_applied(client, sid)
    _write_bridge_package_manifest(aircraft_library_with_draft, PN, PKG_ID,
                                   edit_session_id=sid)

    r = client.post("/api/library/intake/post-edit-sync-preview", json={
        "partNumber":    PN,
        "partPackageId": PKG_ID,
    })
    cand = r.json()["candidateSessions"][0]
    assert cand["sessionId"]  == sid
    assert cand["confidence"] == "high"
    assert cand["reason"]     == "manifest_session_id"


def test_sync_preview_wrong_status_session_excluded(
    aircraft_library_with_draft: Path,
):
    """A session that's still 'prepared' (not applied) must NOT show
    up as a candidate, even when the manifest stamps its sessionId."""
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(client)
    sid = _create_session(client, handoff)["session"]["sessionId"]
    # Stay at 'prepared'. Manifest stamps it -- but it's still excluded.
    _write_bridge_package_manifest(aircraft_library_with_draft, PN, PKG_ID,
                                   session_id=sid)

    r = client.post("/api/library/intake/post-edit-sync-preview", json={
        "partNumber":    PN,
        "partPackageId": PKG_ID,
    })
    body = r.json()
    assert body["matched"]               is False
    assert body["candidateSessions"]     == []
    assert body["recommendedNextAction"] == "no_candidate_session"


def test_sync_preview_different_part_session_excluded(
    aircraft_library_with_draft: Path,
):
    """Applied sessions for a DIFFERENT part must not match the
    incoming package's partNumber. We synthesize a second part rev
    on disk so a separate session can validly exist."""
    client = TestClient(server.app)
    # Plant a second revisioned part 1030199 with its own GLB / colors /
    # regions so a session can validly exist against it.
    pn_other = "1030199"
    other_rev_dir = aircraft_library_with_draft / "parts" / pn_other / REV
    other_rev_dir.mkdir(parents=True)
    _sr_tests._write_synthetic_glb(other_rev_dir / f"{pn_other}_colored.glb",
                                   _sr_tests._aircraft_fixture())
    (other_rev_dir / f"{pn_other}_feature_colors.json").write_text(
        (aircraft_library_with_draft / "parts" / PN / REV / f"{PN}_feature_colors.json")
            .read_text(encoding="utf-8-sig")
            .replace(f'"partNumber": "{PN}"', f'"partNumber": "{pn_other}"'),
        encoding="utf-8",
    )
    other_doc = build_draft_regions(aircraft_library_with_draft, pn_other, REV)
    write_semantic_regions(aircraft_library_with_draft, pn_other, REV, other_doc)
    # Capture a handoff against the OTHER part and create an applied session.
    r_handoff = client.post(
        f"/api/part-semantic-regions/{pn_other}/cad-edit-handoff",
        json={"revision": REV, "phrase": "top wing",
              "userInstruction": "make the top wing 2 inches thicker"},
    )
    assert r_handoff.status_code == 200, r_handoff.text
    other_sid = _create_session(client, r_handoff.json())["session"]["sessionId"]
    _advance_to_applied(client, other_sid)
    # Sidecar is for PN, not pn_other.
    _write_bridge_package_manifest(aircraft_library_with_draft, PN, PKG_ID)

    r = client.post("/api/library/intake/post-edit-sync-preview", json={
        "partNumber":    PN,
        "partPackageId": PKG_ID,
    })
    body = r.json()
    assert body["matched"]           is False
    assert body["candidateSessions"] == []


def test_sync_preview_does_not_mutate_session_json(
    aircraft_library_with_draft: Path,
):
    """Read-only contract: a sync-preview POST must not modify any
    session file's mtime or contents."""
    _write_bridge_package_manifest(aircraft_library_with_draft, PN, PKG_ID,
                                   source_path="C:/CAD/Top.SLDPRT")
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(client)
    sid = _create_session(client, handoff)["session"]["sessionId"]
    _advance_to_applied(client, sid)

    session_path = aircraft_library_with_draft / "_edit_sessions" / f"{sid}.json"
    before_mtime = session_path.stat().st_mtime_ns
    before_bytes = session_path.read_bytes()

    r = client.post("/api/library/intake/post-edit-sync-preview", json={
        "partNumber":    PN,
        "partPackageId": PKG_ID,
    })
    assert r.status_code == 200, r.text

    after_mtime = session_path.stat().st_mtime_ns
    after_bytes = session_path.read_bytes()
    assert after_mtime == before_mtime, \
        "session file mtime changed: sync-preview must be read-only"
    assert after_bytes == before_bytes, \
        "session file bytes changed: sync-preview must be read-only"


def test_sync_preview_recommendedPatch_uses_provided_package_id(
    aircraft_library_with_draft: Path,
):
    """The returned recommendedPatch must carry the EXACT partPackageId
    that the caller provided in the request body -- this is the value
    the operator will PATCH into extraction.resultingPartPackageId."""
    custom_pkg = "pkg-custom-deadbeef-2026"
    _write_bridge_package_manifest(aircraft_library_with_draft, PN, custom_pkg)
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(client)
    sid = _create_session(client, handoff)["session"]["sessionId"]
    _advance_to_applied(client, sid)

    r = client.post("/api/library/intake/post-edit-sync-preview", json={
        "partNumber":    PN,
        "partPackageId": custom_pkg,
    })
    cand = r.json()["candidateSessions"][0]
    assert cand["recommendedPatch"]["status"] == "extracted"
    assert cand["recommendedPatch"]["extraction"]["resultingPartPackageId"] == custom_pkg


# ===========================================================================
# GET /api/library/intake/recent-packages/{partNumber}
# ===========================================================================
#
# Powers the Sessions UI's "Run Sync Preview" action: list bridge sidecar
# packages newest first so the UI can pick the freshest without making
# the operator paste a packageId.

def _touch_package_dir(library: Path, pn: str, package_id: str,
                       *, manifest: Optional[dict] = None,
                       mtime_offset_s: float = 0.0) -> Path:
    """Plant a bridge sidecar package dir. mtime_offset_s shifts the
    directory's stat() mtime so the ordering test is deterministic
    regardless of how fast pytest's file ops resolve."""
    import os
    bridge_dir = library / "_bridge_imports" / "part" / pn / package_id
    bridge_dir.mkdir(parents=True, exist_ok=True)
    if manifest is not None:
        (bridge_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8")
    if mtime_offset_s:
        # Walltime-anchored so newest-first ordering tests are stable
        # even when two packages land in the same wall-clock second.
        target = bridge_dir.stat().st_mtime + mtime_offset_s
        os.utime(bridge_dir, (target, target))
    return bridge_dir


def test_recent_packages_returns_empty_when_dir_absent(
    aircraft_library_with_draft: Path,
):
    """Missing _bridge_imports/part/{pn}/ -> 200 with packages: []
    (NOT 404), so the UI can render a clean 'no extractions' state
    without exception handling."""
    client = TestClient(server.app)
    r = client.get(f"/api/library/intake/recent-packages/{PN}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"partNumber": PN, "packages": []}


def test_recent_packages_sorted_newest_first(
    aircraft_library_with_draft: Path,
):
    """Multiple package dirs -> sorted by directory mtime descending."""
    _touch_package_dir(aircraft_library_with_draft, PN, "pkg-older",
                       manifest={"partNumber": PN, "packageId": "pkg-older"},
                       mtime_offset_s=-3600.0)
    _touch_package_dir(aircraft_library_with_draft, PN, "pkg-middle",
                       manifest={"partNumber": PN, "packageId": "pkg-middle"},
                       mtime_offset_s=-1800.0)
    _touch_package_dir(aircraft_library_with_draft, PN, "pkg-newest",
                       manifest={"partNumber": PN, "packageId": "pkg-newest"})

    client = TestClient(server.app)
    body = client.get(f"/api/library/intake/recent-packages/{PN}").json()
    ids = [p["partPackageId"] for p in body["packages"]]
    assert ids == ["pkg-newest", "pkg-middle", "pkg-older"], \
        f"expected newest-first ordering, got {ids}"


def test_recent_packages_includes_source_path(
    aircraft_library_with_draft: Path,
):
    """manifest.sourceDocument.path is echoed as sourcePath so the
    UI can show 'C:/CAD/.../foo.SLDPRT' without parsing the manifest
    itself."""
    _touch_package_dir(aircraft_library_with_draft, PN, "pkg-with-src",
                       manifest={"partNumber": PN, "packageId": "pkg-with-src",
                                 "sourceDocument": {"path": r"C:\CAD\Aircraft\Top.SLDPRT"}})
    client = TestClient(server.app)
    pkgs = client.get(f"/api/library/intake/recent-packages/{PN}").json()["packages"]
    assert pkgs[0]["sourcePath"]  == r"C:\CAD\Aircraft\Top.SLDPRT"
    assert pkgs[0]["hasManifest"] is True


def test_recent_packages_ignores_non_directory_files(
    aircraft_library_with_draft: Path,
):
    """Stray files like _latest.txt under _bridge_imports/part/{pn}/
    must NOT appear as packages -- only subdirectories are package
    candidates."""
    part_dir = aircraft_library_with_draft / "_bridge_imports" / "part" / PN
    part_dir.mkdir(parents=True, exist_ok=True)
    (part_dir / "_latest.txt").write_text("pkg-newest", encoding="utf-8")
    _touch_package_dir(aircraft_library_with_draft, PN, "pkg-newest",
                       manifest={"partNumber": PN, "packageId": "pkg-newest"})

    client = TestClient(server.app)
    pkgs = client.get(f"/api/library/intake/recent-packages/{PN}").json()["packages"]
    ids = [p["partPackageId"] for p in pkgs]
    assert ids == ["pkg-newest"]
    assert "_latest.txt" not in ids


def test_recent_packages_handles_malformed_manifest(
    aircraft_library_with_draft: Path,
):
    """A package dir whose manifest.json is corrupt must still appear
    in the listing (hasManifest=true) but with sourcePath=null so the
    operator sees something is wrong instead of the package silently
    disappearing."""
    bridge_dir = _touch_package_dir(aircraft_library_with_draft, PN, "pkg-corrupt")
    # Write invalid JSON to manifest.json.
    (bridge_dir / "manifest.json").write_text("not valid json {", encoding="utf-8")

    client = TestClient(server.app)
    pkgs = client.get(f"/api/library/intake/recent-packages/{PN}").json()["packages"]
    assert len(pkgs) == 1
    assert pkgs[0]["partPackageId"] == "pkg-corrupt"
    assert pkgs[0]["hasManifest"]   is True
    assert pkgs[0]["sourcePath"]    is None


# ===========================================================================
# Sessions tab UI (frontend static guards)
# ===========================================================================
#
# The Sessions tab JS is wired by string-matched element IDs and function
# names. If any of these drift, the tab silently misbehaves -- the only
# guard is asserting their presence in the served HTML.

def test_served_html_contains_sessions_tab_marker():
    """Top-level Sessions tab must exist in the tab bar so users can
    actually reach the panel. data-tab="sessions" is the load-bearing
    attribute the click handler matches on."""
    client = TestClient(server.app)
    html = client.get("/").text
    assert 'data-tab="sessions"' in html, \
        "Sessions tab must be present in the top-level tab bar"
    assert 'id="sessionsTab"' in html, \
        "Sessions tab must carry id='sessionsTab' for keyboard shortcuts + tests"


def test_served_html_sessions_tab_uses_correct_endpoint_urls():
    """All four backend endpoints the Sessions UI depends on must
    appear in the served HTML. Drift here means the UI silently
    fails on action click."""
    client = TestClient(server.app)
    html = client.get("/").text
    # GET list + GET single
    assert "'/api/edit-sessions'" in html, \
        "Sessions tab must call GET /api/edit-sessions to load the list"
    assert "/api/edit-sessions/${encodeURIComponent(sessionId)}" in html, \
        "Sessions tab must call GET /api/edit-sessions/{id} for details"
    # recent-packages helper
    assert "/api/library/intake/recent-packages/${encodeURIComponent(partNumber)}" in html, \
        "Run Sync Preview must list recent bridge packages"
    # post-edit-sync-preview
    assert "'/api/library/intake/post-edit-sync-preview'" in html, \
        "Run Sync Preview must POST to post-edit-sync-preview"
    # PATCH for actions
    assert "method: 'PATCH'" in html, \
        "row actions must PATCH /api/edit-sessions/{id}"


def test_served_html_sessions_tab_action_labels_present():
    """The four MVP action button labels must be in the served HTML
    so operators can find them and tests can interact by label."""
    client = TestClient(server.app)
    html = client.get("/").text
    for label in [
        "Mark Applied in SolidWorks",
        "Run Sync Preview",
        "Link Extracted Package",
        "Mark Abandoned",
    ]:
        assert label in html, f"Sessions row action missing: {label!r}"


def test_served_html_sessions_tab_filter_markers_present():
    """Filter pills + part-number dropdown DOM IDs must be in the
    served HTML so the Open/All toggle and part filter are wired
    up the way the JS expects."""
    client = TestClient(server.app)
    html = client.get("/").text
    for marker in [
        # IDs assigned in JS (not literal HTML attributes), so the bare
        # string is the right check.
        "sessionsFilterOpen",
        "sessionsFilterAll",
        "sessionsPartFilter",
        "sessionsRefreshBtn",
        "sessionsTabState",
        "_renderSessionsTab",
        "_sessionsTabFetchList",
        "_sessionsTabMarkApplied",
        "_sessionsTabRunSyncPreview",
        "_sessionsTabLinkExtractedPackage",
        "_sessionsTabMarkAbandoned",
    ]:
        assert marker in html, f"Sessions tab marker missing: {marker!r}"


def test_served_html_sessions_tab_tracks_empty_loaded_state():
    """Regression: an empty sessions list is a valid loaded result.
    The tab must not use `sessions.length === 0` as the trigger to
    re-fetch forever; it needs an explicit loaded flag."""
    client = TestClient(server.app)
    html = client.get("/").text
    assert "loaded:            false" in html, \
        "Sessions tab must track loaded state separately from list length"
    assert "!sessionsTabState.loaded" in html, \
        "initial fetch gate must use loaded flag, not sessions.length"
    assert "sessionsTabState.loaded = true" in html, \
        "fetch completion must mark empty lists as loaded"


def test_served_html_create_edit_session_tool_wired():
    """Sage handoff-prep responses emit create_edit_session; the
    frontend must POST the cad-edit-handoff payload into the Session Log
    and refresh the Sessions tab state."""
    client = TestClient(server.app)
    html = client.get("/").text
    markers = [
        "create_edit_session",
        "handoffPayload",
        "fetch('/api/edit-sessions'",
        "/send-to-solidworks",
        "solidWorksSent",
        "Edit session sent to SolidWorks",
        "Created from Sage CAD edit handoff",
        "sessionsTabState.loaded = false",
        "_sessionsTabFetchList()",
    ]
    for marker in markers:
        assert marker in html, f"create_edit_session frontend marker missing: {marker!r}"


def test_served_html_sessions_tab_links_extracted_session_to_promoted_revision():
    """Regression: once a session is already extracted, Run Sync Preview
    should not keep trying to match it against applied sessions. The UI
    needs the next lifecycle action: find the promoted rev whose
    intake_manifest.sourcePart.packageId matches the session package and
    PATCH extracted -> linked_to_revision -> promoted."""
    client = TestClient(server.app)
    html = client.get("/").text
    markers = [
        "_sessionsTabFindRevisionForExtractedPackage",
        "_sessionsTabLinkPromotedRevision",
        "sessionsLinkPromotedRevision",
        "Link Promoted Revision",
        "/api/library/revisions/",
        "intakeManifest.sourcePart",
        "linked_to_revision",
        "promotedRevision",
        "promotedManifestPath",
        "s.status === 'applied_in_solidworks'",
        "sync preview only matches sessions waiting",
    ]
    for marker in markers:
        assert marker in html, f"promoted-revision link marker missing: {marker!r}"


def test_served_html_sessions_tab_refresh_from_solidworks_button_wired():
    """The Sessions tab must expose the Refresh From SolidWorks
    orchestrator so the operator can promote + draft regions +
    advance the session FSM in one click. The button is the only
    surface for the /refresh-from-solidworks endpoint; if any of
    these markers drift the demo loop silently regresses to the
    7-click manual flow."""
    client = TestClient(server.app)
    html = client.get("/").text
    markers = [
        # Button label + DOM id
        "Refresh From SolidWorks",
        "sessionsRefreshFromSolidWorks",
        # JS surface area
        "_sessionsTabRefreshFromSolidWorks",
        "_sessionsTabSuggestNextRevision",
        "_sessionsTabReadHttpDetail",
        "_sessionsTabOpenCompareForRefresh",
        "_sessionsTabEnsurePartLoadedForCompare",
        "_sessionsTabOpenPersistedPromotionCompare",
        "_sessionsTabBareRevision",
        "await selectPartNumber(pn, false)",
        # State slot for stashing the orchestrator response + the
        # cached compare context Sage reads.
        "refreshResults:    {}",
        "sessionsTabState.refreshResults",
        "lastRefreshCompare",
        # Endpoint URL (template literal form)
        "/refresh-from-solidworks",
        # Request body fields -- must match _RefreshFromSolidWorksBody.
        # assumeApplied is the new demo-path flag; we no longer send
        # partPackageId (server auto-extracts).
        "targetRevision",
        "draftSemanticRegions:",
        "assumeApplied:",
        # Gating: button must enable for these five statuses (prepared
        # is now in the gate -- the backend lifts it via assumeApplied).
        "s.status === 'prepared'",
        "s.status === 'applied_in_solidworks'",
        "s.status === 'extracted'",
        "s.status === 'linked_to_revision'",
        "s.status === 'promoted'",
        # Compare action wired off the orchestrator response
        "sessionsCompareAfterRefresh_",
        "sessionsComparePromotedRevision",
        "Compare Promoted Revision",
        "Compare Rev ",
        "_autoOpenPartCompareAndHighlight([], revA, revB)",
        "loads the part first",
        "Loads part ${refresh.partNumber}, then opens Compare.",
        "no_revisions_available",
        # No-overwrite warning text in the confirm dialog so the
        # operator understands the safety guarantee.
        "will not overwrite if it already exists",
        # Operator-confirm copy for prepared sessions (assumeApplied
        # path). Spec wording.
        "This marks the edit as applied in SolidWorks",
    ]
    for marker in markers:
        assert marker in html, f"Refresh From SolidWorks marker missing: {marker!r}"
    # Anti-markers -- the demo path must NOT prompt the operator to
    # paste a packageId. The whole point of auto-extract is removing
    # that copy/paste step.
    assert "Paste a partPackageId" not in html, \
        "packageId paste prompt must be removed; backend auto-extracts now"
    # The retired packageId-resolver helper must not be referenced.
    assert "_sessionsTabResolvePackageIdForRefresh" not in html, \
        "retired packageId resolver helper must not be referenced"
    assert "Open part ${pn} first -- Part Compare needs the diff state populated" not in html, \
        "Sessions compare launcher must hydrate the part instead of asking the operator to open it"


def test_agent_answers_promoted_edit_session_compare_from_diff(
    aircraft_library_with_draft: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """If the browser fails to attach partDiffState.diffResult, Sage
    should still answer "what changed after the edit session" from the
    promoted edit session + /api/part-feature-diff data."""
    client = TestClient(server.app)

    rev_a_dir = aircraft_library_with_draft / "parts" / PN / "revA"
    rev_b_dir = aircraft_library_with_draft / "parts" / PN / "revB"
    rev_b_dir.mkdir(parents=True)
    rev_a_features = rev_a_dir / f"{PN}_feature_colors.json"
    rev_b_features = rev_b_dir / f"{PN}_feature_colors.json"
    data_a = json.loads(rev_a_features.read_text(encoding="utf-8"))
    data_b = json.loads(rev_a_features.read_text(encoding="utf-8"))
    for data, depth in ((data_a, 0.5), (data_b, 5.0)):
        for feat in data["features"]:
            if feat["cad_feature_id"] == "ice_boss_extrude1":
                feat["parameters"] = {"depth1_mm": depth}
                feat["display_label"] = "Boss-Extrude1"
                feat["sw_name"] = "Boss-Extrude1"
            if feat["cad_feature_id"] == "cirpattern1":
                feat["display_label"] = "CirPattern1"
                feat["sw_name"] = "CirPattern1"
    data_b["features"] = [
        feat for feat in data_b["features"]
        if feat["cad_feature_id"] != "netblend_horiz_stab_pm"
    ]
    rev_a_features.write_text(json.dumps(data_a), encoding="utf-8")
    rev_b_features.write_text(json.dumps(data_b), encoding="utf-8")

    handoff = _capture_handoff_payload(
        client, phrase="propeller",
        instruction="make the propeller blades 5 mm thicker",
    )
    sid = _create_session(client, handoff)["session"]["sessionId"]
    assert client.patch(f"/api/edit-sessions/{sid}", json={
        "status": "applied_in_solidworks",
        "applied": {"appliedAtUtc": "2026-05-23T00:00:00.000Z"},
    }).status_code == 200
    assert client.patch(f"/api/edit-sessions/{sid}", json={
        "status": "extracted",
        "extraction": {"resultingPartPackageId": "pkg-revB"},
    }).status_code == 200
    assert client.patch(f"/api/edit-sessions/{sid}", json={
        "status": "linked_to_revision",
    }).status_code == 200
    assert client.patch(f"/api/edit-sessions/{sid}", json={
        "status": "promoted",
        "promotion": {"promotedRevision": "revB"},
    }).status_code == 200

    _sr_tests._stub_anthropic_response(monkeypatch, "SHOULD NOT BE CALLED")
    r = client.post("/api/agent/chat", json={
        "message": "Compare Rev A and Rev B. What changed in the propeller after the edit session?",
        "agent_type": "deviation-analyst",
        "inspection_context": {"part_number": PN},
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tool_source"] == "edit_session_compare_direct"
    assert "Boss-Extrude1 changed depth1_mm: 0.5 mm" in body["response"]
    assert "5.0 mm" in body["response"]
    assert "Cirpattern1" in body["response"] or "CirPattern1" in body["response"]
    assert "non-target Rev B/C changes outside the propeller edit" in body["response"]
    assert "Horizontal stabilizer" in body["response"]
    assert "Netblend Horiz Stab Pm" in body["response"]
    assert body["compare_features"] == ["pair_0", "removed_netblend_horiz_stab_pm"]
    assert body["tool_calls"] == [{
        "name": "compare_features",
        "args": {
            "markers": ["pair_0", "removed_netblend_horiz_stab_pm"],
            "revA": "A",
            "revB": "B",
        },
    }]


def test_served_html_compare_features_tool_switches_to_requested_revision_pair():
    html = (Path(server.__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
    assert "_resolvePartCompareRevisionToken" in html
    assert "_autoOpenPartCompareAndHighlight(pairIds, revA = null, revB = null)" in html
    assert "revisionPairChanged" in html
    assert "diffPairMismatch" in html
    assert "State can say \"compare\" while the DOM is stale/not mounted" in html
    assert "_autoOpenPartCompareAndHighlight(args.markers, args.revA, args.revB)" in html
    assert "async execute(args)" in html
    assert "return await _autoOpenPartCompareAndHighlight(args.markers, args.revA, args.revB)" in html
    assert "Highlight mesh counts" in html
    assert "mesh.material.opacity = 0.28" in html
    assert "mesh.material.emissiveIntensity = 1.15" in html
    assert "_clearPartCompareAgentHighlightHelpers" in html
    assert "_addPartCompareHighlightBox" in html
    assert "new THREE.BoxHelper(mesh, color.getHex())" in html


def test_agent_explicit_rev_pair_compare_ignores_stale_context(
    aircraft_library_with_draft: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Regression: after a fresh promote, the browser may still attach
    the prior compare payload. If the user explicitly asks for Rev D/E,
    Sage must compute D/E from disk instead of answering from stale B/C
    context."""
    client = TestClient(server.app)

    rev_a_dir = aircraft_library_with_draft / "parts" / PN / "revA"
    rev_d_dir = aircraft_library_with_draft / "parts" / PN / "revD"
    rev_e_dir = aircraft_library_with_draft / "parts" / PN / "revE"
    rev_d_dir.mkdir(parents=True)
    rev_e_dir.mkdir(parents=True)

    source = json.loads((rev_a_dir / f"{PN}_feature_colors.json").read_text(encoding="utf-8"))
    data_d = json.loads(json.dumps(source))
    data_e = json.loads(json.dumps(source))
    for data, depth in ((data_d, 0.5), (data_e, 5.5)):
        for feat in data["features"]:
            if feat["cad_feature_id"] == "ice_boss_extrude1":
                feat["parameters"] = {"depth1_mm": depth}
                feat["display_label"] = "Boss-Extrude1"
                feat["sw_name"] = "Boss-Extrude1"
            if feat["cad_feature_id"] == "cirpattern1":
                feat["display_label"] = "CirPattern1"
                feat["sw_name"] = "CirPattern1"
    data_e["features"] = [
        feat for feat in data_e["features"]
        if feat["cad_feature_id"] != "cirpattern1"
    ]
    (rev_d_dir / f"{PN}_feature_colors.json").write_text(json.dumps(data_d), encoding="utf-8")
    (rev_e_dir / f"{PN}_feature_colors.json").write_text(json.dumps(data_e), encoding="utf-8")

    _sr_tests._stub_anthropic_response(monkeypatch, "SHOULD NOT BE CALLED")
    stale_bc = {
        "revA": "B",
        "revB": "C",
        "summary": "stale B/C summary",
        "changed_features": {},
        "added_features": [],
        "removed_features": [],
    }
    r = client.post("/api/agent/chat", json={
            "message": "what changed between rev d and e?",
        "agent_type": "deviation-analyst",
        "inspection_context": {
            "part_number": PN,
            "attachments": {
                "part": {"part_number": PN},
                "compare": {"part_feature_diff": stale_bc},
            },
        },
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tool_source"] == "part_feature_compare_direct"
    assert "Between D and E" in body["response"]
    assert "Boss-Extrude1 changed depth1_mm: 0.5 mm -> 5.5 mm" in body["response"]
    assert "Removed feature(s): CirPattern1" in body["response"]
    assert "stale B/C" not in body["response"]
    assert body["part_feature_diff"]["revA"] == "D"
    assert body["part_feature_diff"]["revB"] == "E"
    assert body["compare_features"] == ["pair_0", "removed_cirpattern1"]
    assert body["tool_calls"] == [{
        "name": "compare_features",
        "args": {
            "markers": ["pair_0", "removed_cirpattern1"],
            "revA": "D",
            "revB": "E",
        },
    }]


def test_served_html_agent_context_skips_stale_part_feature_diff():
    html = (Path(server.__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
    markers = [
        "diffMatchesActivePair",
        "Skipping stale part feature diff",
        "part_compare_revA",
        "part_compare_revB",
        "prior B/C diff must not be",
    ]
    for marker in markers:
        assert marker in html, f"stale compare guard marker missing: {marker!r}"


def test_served_html_compare_highlight_has_camera_focus_and_legend():
    """Static guard for the camera-focus + legend rail. Material-only
    highlights are invisible when the highlighted features are tiny
    (propeller blades vs full-aircraft framing), so the Compare flow
    needs BOTH an auto-fit camera AND a clickable text legend so the
    operator can find each change. Drift on any of these wires
    silently breaks the visible-highlight contract."""
    html = (Path(server.__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
    # Camera focus helper -- fits both compare cameras to the union
    # bbox of the highlighted meshes.
    assert "function _focusCompareCamerasOnFeatures(" in html, \
        "missing camera-focus helper"
    assert "_focusCompareCamerasOnFeatures(highlightA, highlightB)" in html, \
        "_applyAgentCompareFeatures must call the focus helper after applying highlights"
    # Bbox-union math should be in the helper so we know it actually
    # computes a frame target rather than no-op'ing.
    assert "new THREE.Box3()" in html
    assert "primary.controls.target.copy(center)" in html
    # Camera focus must preserve the operator's current view direction
    # rather than snapping to a fixed angle.
    assert "subVectors(primary.camera.position, primary.controls.target)" in html

    # Clickable legend rail -- per-feature pills + Fit all changes.
    assert "function _renderCompareHighlightLegend(" in html, \
        "missing legend rail helper"
    assert "_renderCompareHighlightLegend({" in html, \
        "_applyAgentCompareFeatures must render the legend after highlights"
    assert "compare-highlight-pill" in html, \
        "legend pills must carry a stable class hook"
    assert "compareHighlightFitAllBtn" in html, \
        "legend must include a Fit-all-changes button"
    # Per-pill click must focus the camera on just that feature.
    assert "_focusCompareCamerasOnFeatures(setA, setB)" in html

    # Diagnostic surface so Playwright + browser console can probe
    # state from outside the IIFE.
    assert "window.__compareDbg" in html
    assert "applyAgentCompareFeatures:" in html
    assert "focusCompareOnFeatures:" in html
    assert "autoOpenPartCompareAndHighlight:" in html


def test_served_html_sessions_tab_does_not_regress_other_tabs():
    """Regression guard: adding the Sessions tab must NOT remove or
    rename the existing tabs the rest of the app depends on. The
    Regions sub-tab is still under the 3D Model tab, the Compare
    sub-tab markers still exist, and Drawing/3D Model/Report still
    declare their data-tab attributes."""
    client = TestClient(server.app)
    html = client.get("/").text
    for marker in [
        'data-tab="drawing"',
        'data-tab="3dmodel"',
        'data-tab="report"',
        # 3D-Model sub-tabs
        "{ id: '3dmodel', label: '3D Model' }",
        "{ id: 'compare', label: 'Compare' }",
        "{ id: 'regions', label: 'Regions' }",
        # Compare-tab JS surfaces
        "_renderPartCompareSubtab",
        "partCompareRevASelect",
        # Regions-curator JS surfaces
        "_renderRegionsCuratorSubtab",
        "regionsCuratorState",
    ]:
        assert marker in html, f"Regression: required marker missing after Sessions tab change: {marker!r}"
