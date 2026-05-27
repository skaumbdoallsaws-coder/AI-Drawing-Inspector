"""Tests for the post-edit Refresh From SolidWorks orchestrator.

Spec scenarios covered:
  - session in applied_in_solidworks + supplied partPackageId promotes
    targetRevision + drafts semantic regions + auto-drafts intent map
    + advances FSM to promoted + response includes nextCompare.
  - existing targetRevision returns 409 (no overwrite in MVP).
  - missing partPackageId returns 409 with a clear "extract first" hint.
  - session in wrong status (prepared) returns 409.
  - response carries stages map so a partial run is visible.

The fixture builds a synthetic library with:
  - parts/{pn}/{sourceRev}/  (existing rev dir -- contents irrelevant)
  - _bridge_imports/part/{pn}/{packageId}/manifest.json
  - _bridge_imports/part/{pn}/{packageId}/part/part.json   (valid JSON)
  - _bridge_imports/part/{pn}/{packageId}/part/{pn}_colored.glb
  - _bridge_imports/part/{pn}/{packageId}/part/{pn}_feature_colors.json
  - _edit_sessions/{sessionId}.json   (built from a real cad-edit-handoff
    so the embedded payload + shape matches production)
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
    write_semantic_regions,
)

sys.path.insert(0, str(REPO_ROOT / "tests"))
import test_semantic_regions as _sr_tests  # noqa: E402

PN          = "1030099"
SOURCE_REV  = "revA"
TARGET_REV  = "revB"
PACKAGE_ID  = "pkg-refresh-test-2026-05-25"


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

def _write_sidecar_package(library: Path, pn: str, pkg_id: str,
                           include_colored_glb: bool = True,
                           include_feature_colors: bool = True) -> Path:
    """Plant a bridge sidecar package with the parts the wizard's
    copy-from-sidecar pass needs. Returns the package directory."""
    pkg_dir = library / "_bridge_imports" / "part" / pn / pkg_id
    pkg_part_dir = pkg_dir / "part"
    pkg_part_dir.mkdir(parents=True, exist_ok=True)

    # Bridge manifest at the package root.
    (pkg_dir / "manifest.json").write_text(json.dumps({
        "partNumber": pn,
        "packageId":  pkg_id,
        "sourceDocument": {"path": f"C:/CAD/{pn}.SLDPRT"},
    }), encoding="utf-8")

    # part.json -- the wizard MUST be able to JSON-decode this.
    (pkg_part_dir / "part.json").write_text(json.dumps({
        "partNumber":         pn,
        "activeConfiguration": "Default",
        "featureCount":       3,
        "featureTree":        [],
    }), encoding="utf-8")

    # Synthetic colored GLB so semantic-regions builder has input.
    if include_colored_glb:
        _sr_tests._write_synthetic_glb(
            pkg_part_dir / f"{pn}_colored.glb",
            _sr_tests._aircraft_fixture(),
        )
    # feature_colors so the auto-draft intent map step has input.
    if include_feature_colors:
        (pkg_part_dir / f"{pn}_feature_colors.json").write_text(json.dumps({
            "partNumber": pn,
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
    return pkg_dir


def _capture_handoff_payload(client: TestClient, pn: str, rev: str,
                              phrase: str = "top wing",
                              instruction: str = "make the top wing 2 inches thicker") -> dict:
    r = client.post(
        f"/api/part-semantic-regions/{pn}/cad-edit-handoff",
        json={"revision": rev, "phrase": phrase, "userInstruction": instruction},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _create_session_at_applied(client: TestClient, pn: str, rev: str, pkg_id: str) -> str:
    """Build a session and PATCH it to applied_in_solidworks so it's
    ready for refresh-from-solidworks. Returns sessionId."""
    handoff = _capture_handoff_payload(client, pn, rev)
    r = client.post("/api/edit-sessions", json={"handoffPayload": handoff})
    assert r.status_code == 200, r.text
    sid = r.json()["session"]["sessionId"]
    pr = client.patch(f"/api/edit-sessions/{sid}", json={
        "status":  "applied_in_solidworks",
        "applied": {"appliedAtUtc": "2026-05-25T10:00:00.000Z", "appliedByUser": "smoke"},
    })
    assert pr.status_code == 200, pr.text
    return sid


@pytest.fixture
def refresh_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Library with the source revision populated + bridge sidecar
    package planted + (no target revision so promote can succeed)."""
    library = tmp_path / "lib"
    # Source rev needs GLB + feature_colors so the handoff endpoint
    # can resolve semantic regions for the embedded payload.
    src_dir = library / "parts" / PN / SOURCE_REV
    src_dir.mkdir(parents=True)
    _sr_tests._write_synthetic_glb(src_dir / f"{PN}_colored.glb",
                                   _sr_tests._aircraft_fixture())
    (src_dir / f"{PN}_feature_colors.json").write_text(json.dumps({
        "partNumber": PN,
        "features": [
            {
                "cad_feature_id": n, "glb_node_name": n,
                "sw_name": n.replace("_", " ").title(),
                "type":    n.split("_", 1)[0],
                "display_label": n.replace("_", " ").title(),
            }
            for n, *_ in _sr_tests._aircraft_fixture()
        ],
    }), encoding="utf-8")
    # Pre-build semantic regions on source rev so the handoff endpoint
    # finds matching regions and emits a usable embedded payload.
    regions_doc = build_draft_regions(library, PN, SOURCE_REV)
    write_semantic_regions(library, PN, SOURCE_REV, regions_doc)

    # Plant the bridge sidecar package with all visuals.
    _write_sidecar_package(library, PN, PACKAGE_ID,
                           include_colored_glb=True,
                           include_feature_colors=True)

    monkeypatch.setattr(server, "LIBRARY_DIR", library)
    yield library


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_refresh_promotes_target_rev_and_drafts_regions_and_intent(
    refresh_library: Path,
):
    """Spec happy path: session in applied_in_solidworks + supplied
    partPackageId promotes targetRevision + drafts semantic regions +
    auto-drafts feature intent + advances session to promoted +
    response includes nextCompare."""
    client = TestClient(server.app)
    sid = _create_session_at_applied(client, PN, SOURCE_REV, PACKAGE_ID)

    r = client.post(
        f"/api/edit-sessions/{sid}/refresh-from-solidworks",
        json={"targetRevision": TARGET_REV, "partPackageId": PACKAGE_ID},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"]                      is True
    assert body["partNumber"]              == PN
    assert body["sourceRevision"]          == SOURCE_REV
    assert body["promotedRevision"]        == TARGET_REV
    assert body["partPackageId"]           == PACKAGE_ID
    assert body["semanticRegionsDrafted"]  is True
    assert body["featureIntentDrafted"]    is True
    assert body["sessionStatus"]           == "promoted"

    # nextCompare carries the rev pair sans 'rev' prefix + the
    # diff URL the UI can navigate to.
    nc = body["nextCompare"]
    assert nc["revA"] == "A"
    assert nc["revB"] == "B"
    assert nc["url"]  == f"/api/part-feature-diff/{PN}?revA=A&revB=B"

    # Files actually landed on disk.
    target_dir = refresh_library / "parts" / PN / TARGET_REV
    assert target_dir.exists()
    assert (target_dir / f"{PN}_semantic_regions.json").exists()
    assert (target_dir / f"{PN}_feature_intent_map.json").exists()


def test_refresh_session_advances_through_extracted_linked_promoted(
    refresh_library: Path,
):
    """Spec: session status advances atomically through the FSM. The
    extraction + promotion blocks are populated with the operator-
    supplied package + the resolved promote manifest path."""
    client = TestClient(server.app)
    sid = _create_session_at_applied(client, PN, SOURCE_REV, PACKAGE_ID)

    r = client.post(
        f"/api/edit-sessions/{sid}/refresh-from-solidworks",
        json={"targetRevision": TARGET_REV, "partPackageId": PACKAGE_ID},
    )
    assert r.status_code == 200, r.text

    # Read the session back to confirm the FSM walk landed.
    g = client.get(f"/api/edit-sessions/{sid}")
    assert g.status_code == 200, g.text
    session = g.json()
    assert session["status"] == "promoted"
    assert session["extraction"]["resultingPartPackageId"] == PACKAGE_ID
    assert session["promotion"]["promotedRevision"]       == TARGET_REV
    assert session["promotion"]["promotedManifestPath"]   == \
        f"parts/{PN}/{TARGET_REV}/intake_manifest.json"
    # Audit note appended to the session log. The orchestrator's
    # phrasing differentiates between supplied-package and auto-
    # extracted paths -- both start with "Refresh From SolidWorks".
    notes = session.get("notes") or []
    assert any("Refresh From SolidWorks" in n.get("text", "") for n in notes), notes


def test_refresh_accepts_bare_revision_letter_in_targetRevision(
    refresh_library: Path,
):
    """The endpoint normalises 'B' -> 'revB' so the operator does not
    have to remember the canonical prefix."""
    client = TestClient(server.app)
    sid = _create_session_at_applied(client, PN, SOURCE_REV, PACKAGE_ID)

    r = client.post(
        f"/api/edit-sessions/{sid}/refresh-from-solidworks",
        json={"targetRevision": "B", "partPackageId": PACKAGE_ID},
    )
    assert r.status_code == 200, r.text
    assert r.json()["promotedRevision"] == TARGET_REV


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------

def test_refresh_rejects_existing_target_revision(refresh_library: Path):
    """Spec: existing targetRevision returns 409. MVP must NOT
    overwrite curated revisions."""
    # Pre-create the target rev dir to simulate a prior promote.
    (refresh_library / "parts" / PN / TARGET_REV).mkdir(parents=True)
    client = TestClient(server.app)
    sid = _create_session_at_applied(client, PN, SOURCE_REV, PACKAGE_ID)

    r = client.post(
        f"/api/edit-sessions/{sid}/refresh-from-solidworks",
        json={"targetRevision": TARGET_REV, "partPackageId": PACKAGE_ID},
    )
    assert r.status_code == 409, r.text
    assert "already exists" in r.text
    assert "will not overwrite" in r.text


def test_refresh_missing_packageid_triggers_bridge_auto_extract(
    refresh_library: Path, monkeypatch: pytest.MonkeyPatch,
):
    """Demo path: when neither body nor session carries a packageId,
    the orchestrator auto-extracts the active SolidWorks document via
    the bridge. Earlier MVP returned 409; the auto-extract upgrade
    makes that 409 a successful promote when the bridge is online."""
    client = TestClient(server.app)
    sid = _create_session_at_applied(client, PN, SOURCE_REV, PACKAGE_ID)

    bridge_doc = {"type": "Part", "title": f"{PN}.SLDPRT", "path": f"C:/CAD/{PN}.SLDPRT"}
    async def _fake_active_doc_check(safe_pn, session_id):
        return (bridge_doc, bridge_doc["path"])
    extract_calls: list = []
    async def _fake_auto_extract(safe_pn, expected_doc_path):
        extract_calls.append({"pn": safe_pn, "path": expected_doc_path})
        return {
            "success":             True,
            "kind":                "part",
            "packageId":           PACKAGE_ID,
            "importPath":          str(refresh_library / "_bridge_imports" / "part" / safe_pn / PACKAGE_ID),
            "latestPointerPath":   str(refresh_library / "_bridge_imports" / "part" / safe_pn / "_latest.txt"),
            "featureCount":        3,
            "activeConfiguration": "Default",
        }
    monkeypatch.setattr(server, "_refresh_active_doc_check", _fake_active_doc_check)
    monkeypatch.setattr(server, "_refresh_auto_extract",     _fake_auto_extract)

    r = client.post(
        f"/api/edit-sessions/{sid}/refresh-from-solidworks",
        json={"targetRevision": TARGET_REV},  # NO partPackageId -> auto-extract
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["promotedRevision"] == TARGET_REV
    assert body["partPackageId"]    == PACKAGE_ID
    assert body["autoExtracted"]    is True
    ext = body["extraction"]
    assert ext["ok"]              is True
    assert ext["partPackageId"]   == PACKAGE_ID
    assert ext["source"]          == "auto_extract"
    assert ext["autoExtracted"]   is True
    assert ext["bridgeActiveDoc"] == bridge_doc
    assert len(extract_calls) == 1
    assert extract_calls[0]["pn"]   == PN
    assert extract_calls[0]["path"] == bridge_doc["path"]


def test_refresh_explicit_packageid_skips_auto_extract(
    refresh_library: Path, monkeypatch: pytest.MonkeyPatch,
):
    """Regression: passing an explicit partPackageId in the body keeps
    the existing fast path -- the active-doc gate and auto-extract
    helpers must NOT run (cheaper + lets operators batch-promote a
    pre-extracted package without SolidWorks open)."""
    client = TestClient(server.app)
    sid = _create_session_at_applied(client, PN, SOURCE_REV, PACKAGE_ID)

    bridge_calls: list = []
    extract_calls: list = []
    async def _spy_active_doc(*a, **kw): bridge_calls.append((a, kw))
    async def _spy_extract(*a, **kw):    extract_calls.append((a, kw))
    monkeypatch.setattr(server, "_refresh_active_doc_check", _spy_active_doc)
    monkeypatch.setattr(server, "_refresh_auto_extract",     _spy_extract)

    r = client.post(
        f"/api/edit-sessions/{sid}/refresh-from-solidworks",
        json={"targetRevision": TARGET_REV, "partPackageId": PACKAGE_ID},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["autoExtracted"]              is False
    assert body["extraction"]["source"]       == "body"
    assert body["extraction"]["autoExtracted"] is False
    assert bridge_calls == [], "active-doc check must not run when packageId supplied"
    assert extract_calls == [], "auto-extract must not run when packageId supplied"


def test_refresh_uses_packageId_from_session_extraction_when_body_omits(
    refresh_library: Path,
):
    """When the session's extraction.resultingPartPackageId is
    already populated (e.g. operator PATCHed it manually after the
    bridge extracted), the endpoint can run without a body packageId."""
    client = TestClient(server.app)
    sid = _create_session_at_applied(client, PN, SOURCE_REV, PACKAGE_ID)
    # Pre-populate the extraction block so the body packageId can be omitted.
    pr = client.patch(f"/api/edit-sessions/{sid}", json={
        "status":     "extracted",
        "extraction": {"resultingPartPackageId": PACKAGE_ID,
                       "extractedAtUtc": "2026-05-25T11:00:00.000Z"},
    })
    assert pr.status_code == 200, pr.text

    r = client.post(
        f"/api/edit-sessions/{sid}/refresh-from-solidworks",
        json={"targetRevision": TARGET_REV},  # NO partPackageId
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["partPackageId"]    == PACKAGE_ID
    assert body["promotedRevision"] == TARGET_REV


def test_refresh_rejects_session_in_prepared_status(refresh_library: Path):
    """Session that has not been applied in SolidWorks yet AND was
    not flagged assumeApplied -> 409 with a hint pointing to either
    Mark Applied or the assumeApplied flag. Prevents the orchestrator
    from racing ahead of the human approval gate."""
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(client, PN, SOURCE_REV)
    r1 = client.post("/api/edit-sessions", json={"handoffPayload": handoff})
    sid = r1.json()["session"]["sessionId"]

    r = client.post(
        f"/api/edit-sessions/{sid}/refresh-from-solidworks",
        json={"targetRevision": TARGET_REV, "partPackageId": PACKAGE_ID},
    )
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert "Mark Applied in SolidWorks" in detail
    assert "assumeApplied=true" in detail


def test_refresh_rejects_terminal_session(refresh_library: Path):
    """A session that's already terminal (abandoned/failed/compared)
    cannot be refreshed."""
    client = TestClient(server.app)
    sid = _create_session_at_applied(client, PN, SOURCE_REV, PACKAGE_ID)
    # Walk to terminal via abandoned.
    pr = client.patch(f"/api/edit-sessions/{sid}", json={
        "status": "abandoned", "abandonReason": "test cleanup",
    })
    assert pr.status_code == 200, pr.text

    r = client.post(
        f"/api/edit-sessions/{sid}/refresh-from-solidworks",
        json={"targetRevision": TARGET_REV, "partPackageId": PACKAGE_ID},
    )
    assert r.status_code == 409, r.text
    assert "terminal" in r.text.lower()


def test_refresh_404_for_missing_session(refresh_library: Path):
    client = TestClient(server.app)
    r = client.post(
        "/api/edit-sessions/01HZZZZZZZZZZZZZZZZZZZZZZZ/refresh-from-solidworks",
        json={"targetRevision": TARGET_REV, "partPackageId": PACKAGE_ID},
    )
    assert r.status_code == 404, r.text


# ---------------------------------------------------------------------------
# Stages + soft-skip surface
# ---------------------------------------------------------------------------

def test_refresh_stages_block_records_each_step_outcome(refresh_library: Path):
    """The response carries a `stages` map so the operator can see
    which steps ran and what was skipped (promote, enrichVisuals,
    semanticRegions, featureIntent)."""
    client = TestClient(server.app)
    sid = _create_session_at_applied(client, PN, SOURCE_REV, PACKAGE_ID)

    r = client.post(
        f"/api/edit-sessions/{sid}/refresh-from-solidworks",
        json={"targetRevision": TARGET_REV, "partPackageId": PACKAGE_ID},
    )
    assert r.status_code == 200, r.text
    stages = r.json()["stages"]
    assert stages["promote"]["ok"]            is True
    # enrichVisuals is intentionally a soft skip in MVP -- the
    # response must document that fact + carry a nextAction so the
    # operator knows where to find the manual path.
    assert stages["enrichVisuals"]["ok"]      is False
    assert "nextAction" in stages["enrichVisuals"]
    assert "enrich-visuals" in stages["enrichVisuals"]["nextAction"]
    assert stages["semanticRegions"]["ok"]    is True
    assert stages["featureIntent"]["ok"]      is True


def test_refresh_skips_regions_when_draftSemanticRegions_false(refresh_library: Path):
    """When the operator opts out of region drafting, both the
    regions and the (downstream) intent map skip with a clear
    reason -- but promote + FSM advance still happen."""
    client = TestClient(server.app)
    sid = _create_session_at_applied(client, PN, SOURCE_REV, PACKAGE_ID)

    r = client.post(
        f"/api/edit-sessions/{sid}/refresh-from-solidworks",
        json={"targetRevision": TARGET_REV, "partPackageId": PACKAGE_ID,
              "draftSemanticRegions": False},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["promotedRevision"]        == TARGET_REV
    assert body["semanticRegionsDrafted"]  is False
    assert body["featureIntentDrafted"]    is False
    stages = body["stages"]
    assert "skipped" in stages["semanticRegions"]
    assert "skipped" in stages["featureIntent"]


def test_refresh_omitted_targetRevision_auto_picks_next_letter(refresh_library: Path):
    """Demo path: when targetRevision is omitted (or empty), the
    server picks the next free rev letter by scanning parts/{pn}/rev*.
    The existing source rev (revA) means the next free letter is B."""
    client = TestClient(server.app)
    sid = _create_session_at_applied(client, PN, SOURCE_REV, PACKAGE_ID)
    r = client.post(
        f"/api/edit-sessions/{sid}/refresh-from-solidworks",
        json={"partPackageId": PACKAGE_ID},  # NO targetRevision
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["promotedRevision"] == "revB"
    nc = body["nextCompare"]
    assert nc["revA"] == "A"
    assert nc["revB"] == "B"


def test_refresh_empty_string_targetRevision_also_auto_picks(refresh_library: Path):
    """Belt-and-suspenders: a JSON body that sends targetRevision=''
    (e.g. a UI that defaulted to an empty input) should NOT 400 --
    the server treats it the same as omitted and auto-picks. The
    earlier MVP returned 400; the demo upgrade relaxes that."""
    client = TestClient(server.app)
    sid = _create_session_at_applied(client, PN, SOURCE_REV, PACKAGE_ID)
    r = client.post(
        f"/api/edit-sessions/{sid}/refresh-from-solidworks",
        json={"targetRevision": "", "partPackageId": PACKAGE_ID},
    )
    assert r.status_code == 200, r.text
    assert r.json()["promotedRevision"] == "revB"


def test_refresh_bridge_unavailable_returns_409_with_open_part_message(
    refresh_library: Path, monkeypatch: pytest.MonkeyPatch,
):
    """Spec error UX: when the bridge is unreachable and we need to
    auto-extract, refuse with a clear "open the edited part" message
    -- never a raw stack trace."""
    client = TestClient(server.app)
    sid = _create_session_at_applied(client, PN, SOURCE_REV, PACKAGE_ID)

    from fastapi import HTTPException
    async def _fake_active_doc_check(safe_pn, session_id):
        raise HTTPException(
            status_code=409,
            detail=(
                f"SolidWorks bridge is unavailable. Open the edited SolidWorks part for session "
                f"{session_id}, then retry Refresh From SolidWorks."
            ),
        )
    monkeypatch.setattr(server, "_refresh_active_doc_check", _fake_active_doc_check)

    r = client.post(
        f"/api/edit-sessions/{sid}/refresh-from-solidworks",
        json={"targetRevision": TARGET_REV},  # NO partPackageId -> auto path -> active-doc check fires
    )
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert "bridge is unavailable" in detail
    assert "Open the edited SolidWorks part" in detail


def test_refresh_active_doc_wrong_type_returns_409(
    refresh_library: Path, monkeypatch: pytest.MonkeyPatch,
):
    """When the operator has a Drawing or Assembly open instead of the
    edited Part, the orchestrator must refuse before tying up the
    extraction lock."""
    client = TestClient(server.app)
    sid = _create_session_at_applied(client, PN, SOURCE_REV, PACKAGE_ID)

    from fastapi import HTTPException
    async def _fake_active_doc_check(safe_pn, session_id):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Active SolidWorks document is 'Drawing', not a Part. Open the edited "
                f"SolidWorks part for session {session_id}, then retry."
            ),
        )
    monkeypatch.setattr(server, "_refresh_active_doc_check", _fake_active_doc_check)

    r = client.post(
        f"/api/edit-sessions/{sid}/refresh-from-solidworks",
        json={"targetRevision": TARGET_REV},
    )
    assert r.status_code == 409, r.text
    assert "not a Part" in r.json()["detail"]


def test_refresh_prepared_session_without_assumeApplied_returns_409(refresh_library: Path):
    """Safety: a session still in 'prepared' must NOT promote unless
    the caller explicitly sets assumeApplied=true (the frontend does
    that only after the operator confirms 'this marks the edit as
    applied')."""
    client = TestClient(server.app)
    # Build a session and leave it at 'prepared' (no PATCH to applied).
    handoff = _capture_handoff_payload(client, PN, SOURCE_REV)
    r1 = client.post("/api/edit-sessions", json={"handoffPayload": handoff})
    sid = r1.json()["session"]["sessionId"]

    r = client.post(
        f"/api/edit-sessions/{sid}/refresh-from-solidworks",
        json={"targetRevision": TARGET_REV, "partPackageId": PACKAGE_ID},
    )
    assert r.status_code == 409, r.text
    assert "assumeApplied=true" in r.json()["detail"]


def test_refresh_prepared_session_with_assumeApplied_walks_to_promoted(refresh_library: Path):
    """assumeApplied=true lifts a 'prepared' session through
    applied_in_solidworks before the normal extracted -> linked ->
    promoted chain. End state must be 'promoted'."""
    client = TestClient(server.app)
    handoff = _capture_handoff_payload(client, PN, SOURCE_REV)
    r1 = client.post("/api/edit-sessions", json={"handoffPayload": handoff})
    sid = r1.json()["session"]["sessionId"]

    r = client.post(
        f"/api/edit-sessions/{sid}/refresh-from-solidworks",
        json={
            "targetRevision":  TARGET_REV,
            "partPackageId":   PACKAGE_ID,
            "assumeApplied":   True,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sessionStatus"]    == "promoted"
    assert body["promotedRevision"] == TARGET_REV
    # Re-load the session and confirm the applied block + audit note
    # were stamped during the assumeApplied lift.
    sess = client.get(f"/api/edit-sessions/{sid}").json()
    assert sess["applied"]["appliedAtUtc"]
    assert "auto-applied by refresh-from-solidworks" in (sess["applied"].get("appliedNotes") or "")
