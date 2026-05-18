"""Tests for Library Intake Wizard Step 1 — stub-profile awareness gate.

Validates the contract in docs/library-intake-wizard-plan.md sections
5.7, 9.5, and 9.6:

- `_is_intake_stub_profile` predicate detects `source == "library_intake_stub"`
- `/api/profile-details/{pn}` returns the stub-aware shape for stubs
- `/api/profile-details/{pn}` preserves the existing shape for real profiles
- `/api/inspect` returns HTTP 422 + the prescribed body shape for stubs
- The 422 path does NOT call `inspector.inspect` (no LLM call leak)
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

# Ensure the repo root is on sys.path so `import server` works when pytest
# is invoked from a sub-directory or another worktree.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import server  # noqa: E402


# ── Fixtures ──────────────────────────────────────────────────────────


def _write_stub_profile(library: Path, pn: str = "1099999") -> None:
    """Per §5.7 schema."""
    (library / f"{pn}_inspection_profile.json").write_text(
        json.dumps({
            "$schemaVersion":  "intake-stub-1.0.0",
            "source":          "library_intake_stub",
            "status":          "incomplete",
            "inspectionReady": False,
            "part_number":     pn,
            "revision":        "revA",
            "name":            f"Stub test part {pn}",
            "description":     "Intake stub test fixture",
            "links": {
                "intakeManifest":  f"parts/{pn}/revA/intake_manifest.json",
                "drawingMap":      f"{pn}_drawing_map.json",
                "partMetadata":    f"parts/{pn}/revA/{pn}.json",
            },
        }),
        encoding="utf-8",
    )


def _write_real_profile(library: Path, pn: str = "1099998") -> None:
    """Typical existing-fleet shape — no `source`, no `status`, no `inspectionReady`."""
    (library / f"{pn}_inspection_profile.json").write_text(
        json.dumps({
            "part_number":      pn,
            "part_name":        f"Real test part {pn}",
            "part_description": "A normal part with real inspection criteria.",
            "features": [
                {"name": "Hole A", "type": "hole", "count": 1, "spatial_description": "top-left"},
                {"name": "Slot B", "type": "slot", "count": 2, "spatial_description": "bottom"},
            ],
            "view_expectations": {"front": True, "top": True},
        }),
        encoding="utf-8",
    )


@pytest.fixture
def intake_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Spin up a temporary library with one stub + one real profile and
    point server.LIBRARY_DIR at it. The helpers and the endpoint handlers
    all read through `library_path()` which composes off LIBRARY_DIR, so
    the monkeypatch is sufficient — no need to restart the FastAPI app."""
    library = tmp_path / "stub_library"
    library.mkdir()
    _write_stub_profile(library, "1099999")
    _write_real_profile(library, "1099998")
    monkeypatch.setattr(server, "LIBRARY_DIR", library)
    # Belt-and-suspenders: clear the assembly_profiles dict so the stub
    # path in get_profile_details never falls back to an assembly entry
    # named the same as our test part.
    monkeypatch.setattr(server, "assembly_profiles", {}, raising=False)
    yield library


# ── Predicate ──────────────────────────────────────────────────────────


def test_is_intake_stub_profile_recognises_marker():
    assert server._is_intake_stub_profile({"source": "library_intake_stub"}) is True
    # With surrounding noise
    assert server._is_intake_stub_profile({
        "source": "library_intake_stub", "part_number": "X", "features": []
    }) is True


def test_is_intake_stub_profile_rejects_non_stubs():
    # Real profile — no source
    assert server._is_intake_stub_profile({"part_number": "1099998", "features": []}) is False
    # Wrong source value
    assert server._is_intake_stub_profile({"source": "manual_authoring"}) is False
    # Defensive non-dict inputs
    assert server._is_intake_stub_profile(None) is False
    assert server._is_intake_stub_profile([]) is False
    assert server._is_intake_stub_profile("library_intake_stub") is False


# ── _load_profile_if_present ───────────────────────────────────────────


def test_load_profile_if_present_returns_stub_data(intake_library: Path):
    data = server._load_profile_if_present("1099999")
    assert data is not None
    assert server._is_intake_stub_profile(data) is True
    assert data["status"] == "incomplete"
    assert data["inspectionReady"] is False


def test_load_profile_if_present_returns_real_profile(intake_library: Path):
    data = server._load_profile_if_present("1099998")
    assert data is not None
    assert server._is_intake_stub_profile(data) is False
    assert data["part_name"] == "Real test part 1099998"


def test_load_profile_if_present_missing_returns_none(intake_library: Path):
    assert server._load_profile_if_present("0000000") is None
    # Empty / invalid PN inputs do not raise
    assert server._load_profile_if_present("") is None
    assert server._load_profile_if_present(None) is None
    # Path-traversal-style input also returns None (sanitiser strips chars)
    assert server._load_profile_if_present("../../etc/passwd") is None


# ── /api/profile-details/{pn} response shape (§9.5) ────────────────────


def test_profile_details_stub_exposes_source_status_inspection_ready(intake_library: Path):
    """§9.5: stub responses MUST include source / status / inspectionReady
    + a links object so the frontend can gate behaviour."""
    client = TestClient(server.app)
    r = client.get("/api/profile-details/1099999")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "library_intake_stub"
    assert body["status"] == "incomplete"
    assert body["inspectionReady"] is False
    assert body["part_number"] == "1099999"
    # links object passed through
    assert body["links"]["drawingMap"] == "1099999_drawing_map.json"
    assert body["links"]["intakeManifest"] == "parts/1099999/revA/intake_manifest.json"
    # Stubs have no usable features list — explicitly empty per §9.5
    assert body["features"] == []


def test_profile_details_real_profile_preserves_legacy_shape(intake_library: Path):
    """§9.5 backward compat: real profiles MUST NOT gain the
    source/status/inspectionReady fields if the underlying file does not
    declare them. Existing consumers stay byte-equivalent."""
    client = TestClient(server.app)
    r = client.get("/api/profile-details/1099998")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "source" not in body
    assert "status" not in body
    assert "inspectionReady" not in body
    assert "links" not in body
    # Existing fields still present
    assert body["part_number"] == "1099998"
    assert body["part_name"] == "Real test part 1099998"
    assert len(body["features"]) == 2
    assert body["features"][0]["name"] == "Hole A"
    assert body["view_expectations"] == {"front": True, "top": True}


# ── /api/inspect fail-fast gate (§9.6) ─────────────────────────────────


def test_inspect_returns_422_for_stub(intake_library: Path, monkeypatch: pytest.MonkeyPatch):
    """§9.6: posting to /api/inspect with a stub part must 422 with
    error/message/part_number body — and must NOT invoke inspector.inspect."""
    # Sentinel that fails the test if the LLM path is ever reached.
    sentinel = MagicMock(
        side_effect=AssertionError("inspector.inspect MUST NOT be called on the stub fail-fast path")
    )
    mock_inspector = MagicMock(inspect=sentinel)
    monkeypatch.setattr(server, "inspector", mock_inspector)

    client = TestClient(server.app)
    r = client.post(
        "/api/inspect",
        data={"part_number": "1099999"},
        files={"file": ("ignored.png", io.BytesIO(b"\x89PNG\r\n\x1a\n"), "image/png")},
    )
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["error"] == "profile_incomplete"
    assert "inspection profile has been authored" in body["message"]
    assert body["part_number"] == "1099999"
    # Confirm the LLM path was untouched.
    assert sentinel.call_count == 0


def test_inspect_fail_fast_does_not_read_uploaded_file(intake_library: Path,
                                                       monkeypatch: pytest.MonkeyPatch):
    """§9.6: 'The gate runs early — before any uploaded bytes are
    processed.' A large uploaded payload should not change latency
    meaningfully because the body should not be consumed. We verify by
    posting a moderately-sized file and confirming the 422 fires; if the
    gate did NOT run early, the request would proceed and crash on
    inspector access (sentinel above)."""
    mock_inspector = MagicMock(inspect=MagicMock(side_effect=AssertionError("must not be called")))
    monkeypatch.setattr(server, "inspector", mock_inspector)
    # 256 KB payload — large enough that reading it would dominate the
    # request, small enough not to slow the test suite noticeably.
    payload = b"X" * (256 * 1024)
    client = TestClient(server.app)
    r = client.post(
        "/api/inspect",
        data={"part_number": "1099999"},
        files={"file": ("big.png", io.BytesIO(payload), "image/png")},
    )
    assert r.status_code == 422
    assert r.json()["error"] == "profile_incomplete"


# ── /api/profiles picker payload (§8.7-A enablement) ───────────────────


def test_list_profiles_exposes_source_for_stubs(intake_library: Path,
                                                monkeypatch: pytest.MonkeyPatch):
    """§8.7-A enablement: /api/profiles must surface `source` for stub
    entries so the picker can render the [INTAKE] badge without making
    a /api/profile-details call per row. Real profiles MUST NOT gain
    the field (backward compat — keeps payload byte-equivalent for the
    existing fleet)."""
    # Repoint the inspector at the test library so list_profiles() walks
    # the stub + real fixtures we wrote.
    from ai_inspector.spatial import SpatialInspector
    test_inspector = SpatialInspector(library_dir=str(intake_library))
    monkeypatch.setattr(server, "inspector", test_inspector)

    client = TestClient(server.app)
    r = client.get("/api/profiles")
    assert r.status_code == 200, r.text
    profiles = r.json()
    by_pn = {p["part_number"]: p for p in profiles}

    assert "1099999" in by_pn, f"stub not picked up by list_profiles: {profiles}"
    assert by_pn["1099999"].get("source") == "library_intake_stub"

    assert "1099998" in by_pn
    # Real profile must NOT have `source` (otherwise we drift the existing-
    # fleet payload).
    assert "source" not in by_pn["1099998"]
