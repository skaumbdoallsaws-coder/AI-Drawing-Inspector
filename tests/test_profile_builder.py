"""Tests for the Profile Builder MVP.

The builder upgrades Library Intake Wizard stubs into real inspection
profiles through a generate-review-apply flow. These tests avoid real AI
calls by monkeypatching the model helper; they focus on data plumbing,
safe apply semantics, and profile-index refresh behavior.
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


def _draft_profile(pn: str = "1099999") -> dict:
    return {
        "part_number": pn,
        "part_name": f"Builder draft {pn}",
        "part_description": "Draft generated from promoted part and drawing context.",
        "features": [
            {
                "name": "Main body",
                "type": "Extrude",
                "count": 1,
                "spatial_description": "Primary envelope visible in front and side views.",
                "inspection_reason": "Defines the main part envelope.",
                "evidence": ["front view: main body outline"],
                "uncertainty": "low",
            },
            {
                "name": "Mounting holes",
                "type": "Hole",
                "count": 4,
                "spatial_description": "Repeated circular holes called out by drawing dimensions.",
                "inspection_reason": "Controls bolted assembly fit.",
                "evidence": ["front view: repeated hole callout"],
                "uncertainty": "medium",
                "review_notes": "Confirm whether holes are clearance or locating features.",
            },
        ],
        "view_expectations": {
            "front_or_plan": "Show the main body and hole pattern.",
            "side_or_right": "Show the part thickness.",
            "top": "Confirm the hole layout.",
        },
        "review_notes": ["Confirm generated profile before applying."],
    }


def _seed_profile_builder_library(library: Path, pn: str = "1099999") -> None:
    rev = library / "parts" / pn / "revA"
    rev.mkdir(parents=True)
    (rev / f"{pn}.json").write_text(json.dumps({
        "schemaVersion": "1.0",
        "documentType": "part",
        "activeConfiguration": "Default",
        "units": "mm",
        "featureTree": [
            {"name": "Material <not specified>", "type": "MaterialFolder", "suppressedInActive": False},
            {"name": "Boss-Extrude1", "type": "Extrusion", "suppressedInActive": False},
            {"name": "Cut-Extrude1", "type": "ICE", "suppressedInActive": False},
            {"name": "Hole Wizard1", "type": "HoleWzd", "suppressedInActive": False},
        ],
    }), encoding="utf-8")
    (rev / f"{pn}_drawing_map.json").write_text(json.dumps({
        "fileName": f"{pn}.SLDDRW",
        "referencedModelPath": f"C:\\dev\\{pn}.SLDPRT",
        "sheets": [{
            "sheetName": "Sheet1",
            "projectionType": "third-angle",
            "views": [{
                "viewName": "Front",
                "annotations": [
                    {"annotationType": "dimension", "dimensionText": "<MOD-DIAM>10.00"},
                    {"annotationType": "note", "noteText": "BREAK EDGES"},
                ],
            }],
        }],
    }), encoding="utf-8")
    (rev / "intake_manifest.json").write_text(json.dumps({
        "schemaVersion": "1.0.0",
        "partNumber": pn,
        "revision": "revA",
        "sourceDrawing": {"packageId": "drawpkg", "sheetCount": 1, "viewCount": 1},
        "sourcePart": {"packageId": "partpkg", "featureCount": 3, "activeConfiguration": "Default"},
    }), encoding="utf-8")
    (library / f"{pn}_inspection_profile.json").write_text(json.dumps({
        "$schemaVersion": "intake-stub-1.0.0",
        "source": "library_intake_stub",
        "status": "incomplete",
        "inspectionReady": False,
        "part_number": pn,
        "revision": "revA",
        "name": f"Stub {pn}",
        "description": "Stub pending profile builder.",
    }), encoding="utf-8")


@pytest.fixture
def profile_builder_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    library = tmp_path / "profile_builder_library"
    library.mkdir()
    _seed_profile_builder_library(library)
    monkeypatch.setattr(server, "LIBRARY_DIR", library)
    monkeypatch.setattr(server, "assembly_profiles", {}, raising=False)
    monkeypatch.setattr(server, "inspector", None)
    yield library


def test_profile_builder_context_reports_ready_with_revision_sources(profile_builder_library: Path):
    client = TestClient(server.app)
    r = client.get("/api/profile-builder/context/1099999?revision=revA")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ready"] is True
    assert body["revision"] == "revA"
    assert body["existingProfile"]["kind"] == "stub"
    assert body["partSummary"]["featureCount"] == 3
    assert body["partSummary"]["material"]["status"] == "not_specified"
    assert body["partSummary"]["material"]["raw"] == "<not specified>"
    assert body["drawingSummary"]["sheetCount"] == 1
    assert body["drawingSummary"]["viewCount"] == 1
    assert body["drawingSummary"]["dimensions"][0]["text"] == "<MOD-DIAM>10.00"


def test_profile_builder_generate_uses_context_and_returns_validated_draft(
    profile_builder_library: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    seen = {}

    def fake_generate(context, instructions, model):
        seen["context"] = context
        seen["instructions"] = instructions
        seen["model"] = model
        return _draft_profile("1099999"), "fake-model"

    monkeypatch.setattr(server, "_generate_profile_builder_draft", fake_generate)
    client = TestClient(server.app)
    r = client.post("/api/profile-builder/generate", json={
        "partNumber": "1099999",
        "revision": "revA",
        "instructions": "Focus on holes.",
        "model": "fake-model",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["model"] == "fake-model"
    assert body["draftProfile"]["part_number"] == "1099999"
    assert len(body["draftProfile"]["features"]) == 2
    assert body["draftProfile"]["features"][0]["inspection_reason"] == "Defines the main part envelope."
    assert body["draftProfile"]["features"][1]["evidence"] == ["front view: repeated hole callout"]
    assert body["draftProfile"]["features"][1]["uncertainty"] == "medium"
    assert body["draftProfile"]["features"][1]["review_notes"] == "Confirm whether holes are clearance or locating features."
    assert body["draftProfile"]["review_notes"] == ["Confirm generated profile before applying."]
    assert body["validationIssues"] == []
    assert seen["context"]["partSummary"]["featureCount"] == 3
    assert seen["instructions"] == "Focus on holes."


def test_profile_builder_prompt_contains_few_shot_dimension_grouping_guidance(profile_builder_library: Path):
    context = server._profile_builder_context(profile_builder_library, "1099999", "revA")
    prompt = server._profile_builder_prompt(context, "Focus on holes.")
    for marker in [
        "Do not turn every dimension into its own feature row.",
        "count = physical instance count",
        "Count must not contradict the supplied context.",
        "Do not create feature rows for envelope/thickness/position dimensions by themselves.",
        "prefer a profile-level review_notes item instead of a new inspectable feature",
        "If partSummary.material.status is not \"specified\"",
        "do not infer material when supplied context says material is not specified",
        "EXAMPLE 1: Revolved mounting flange",
        "EXAMPLE 2: Machined bracket with slots, holes, and GD&T",
        '"Outer Diameter", "type": "dimension"',
        '"Mounting flange body"',
        '"inspection_reason"',
        '"evidence"',
        '"uncertainty"',
        "Focus on holes.",
    ]:
        assert marker in prompt


def test_profile_builder_generate_flags_unsupported_material_claim(
    profile_builder_library: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    def fake_generate(context, instructions, model):
        draft = _draft_profile("1099999")
        draft["part_description"] = "Aluminum mounting bracket generated from promoted context."
        return draft, "fake-model"

    monkeypatch.setattr(server, "_generate_profile_builder_draft", fake_generate)
    client = TestClient(server.app)
    r = client.post("/api/profile-builder/generate", json={
        "partNumber": "1099999",
        "revision": "revA",
        "model": "fake-model",
    })
    assert r.status_code == 200, r.text
    issues = r.json()["validationIssues"]
    assert any(i["severity"] == "error" and "unsupported material" in i["issue"] for i in issues)


def test_profile_builder_apply_blocks_unsupported_material_claim(profile_builder_library: Path):
    profile = _draft_profile("1099999")
    profile["part_description"] = "Steel mounting bracket generated from promoted context."
    client = TestClient(server.app)
    r = client.post("/api/profile-builder/apply", json={
        "partNumber": "1099999",
        "revision": "revA",
        "profile": profile,
    })
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["error"] == "profile_validation_failed"
    assert any("unsupported material" in i["issue"] for i in body["validationIssues"])


def test_profile_builder_generate_blocks_when_sources_missing(profile_builder_library: Path):
    (profile_builder_library / "parts" / "1099999" / "revA" / "1099999_drawing_map.json").unlink()
    client = TestClient(server.app)
    r = client.post("/api/profile-builder/generate", json={
        "partNumber": "1099999",
        "revision": "revA",
    })
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["error"] == "profile_builder_context_incomplete"
    assert "drawing_map" in body["missing"]


def test_profile_builder_generate_blocks_missing_explicit_revision(profile_builder_library: Path):
    client = TestClient(server.app)
    r = client.post("/api/profile-builder/generate", json={
        "partNumber": "1099999",
        "revision": "revZ",
    })
    assert r.status_code == 409, r.text
    body = r.json()
    assert "revision" in body["missing"]


def test_profile_builder_apply_replaces_stub_and_writes_revision_copy(profile_builder_library: Path):
    client = TestClient(server.app)
    r = client.post("/api/profile-builder/apply", json={
        "partNumber": "1099999",
        "revision": "revA",
        "profile": _draft_profile("1099999"),
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["replacedProfileKind"] == "stub"
    assert "1099999_inspection_profile.json" in body["written"][0]
    root_profile = json.loads((profile_builder_library / "1099999_inspection_profile.json").read_text())
    rev_profile = json.loads((profile_builder_library / "parts" / "1099999" / "revA" / "1099999_inspection_profile.json").read_text())
    assert root_profile["part_name"] == "Builder draft 1099999"
    assert rev_profile["features"][1]["count"] == 4
    assert rev_profile["features"][1]["inspection_reason"] == "Controls bolted assembly fit."
    assert rev_profile["features"][1]["uncertainty"] == "medium"
    assert rev_profile["review_notes"] == ["Confirm generated profile before applying."]
    assert "source" not in root_profile
    assert root_profile["features"]


def test_profile_builder_apply_requires_confirmation_for_real_profile(profile_builder_library: Path):
    (profile_builder_library / "1099999_inspection_profile.json").write_text(
        json.dumps(_draft_profile("1099999")),
        encoding="utf-8",
    )
    client = TestClient(server.app)
    r = client.post("/api/profile-builder/apply", json={
        "partNumber": "1099999",
        "revision": "revA",
        "profile": _draft_profile("1099999"),
    })
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["requiresOverwriteConfirmation"] is True
    assert body["confirmationText"] == "1099999"

    r2 = client.post("/api/profile-builder/apply", json={
        "partNumber": "1099999",
        "revision": "revA",
        "profile": _draft_profile("1099999"),
        "overwriteConfirmed": "1099999",
    })
    assert r2.status_code == 200, r2.text
    assert r2.json()["replacedProfileKind"] == "real"


def test_served_html_contains_profile_builder_surface():
    client = TestClient(server.app)
    html = client.get("/").text
    for marker in [
        'id="openProfileBuilderBtn"',
        'Build Inspection Profile',
        'id="profileBuilderPanel"',
        'id="profileBuilderBody"',
        'id="profileBuilderFooter"',
        'function initProfileBuilder()',
        "document.addEventListener('DOMContentLoaded', initProfileBuilder",
        '/api/profile-builder/context/',
        '/api/profile-builder/generate',
        '/api/profile-builder/apply',
        'window._openProfileBuilder',
    ]:
        assert marker in html, f"missing Profile Builder marker: {marker!r}"
