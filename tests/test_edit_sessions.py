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


def test_POST_create_session_returns_existing_on_duplicate_intent(
    aircraft_library_with_draft: Path,
):
    """Duplicate-intent policy: second create with the same (pn, rev,
    phrase, action) tuple returns the EXISTING session + a warning,
    NOT a new file."""
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
