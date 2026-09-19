from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw

from ai_inspector.assembly_knowledge.provider import FixtureMultimodalProvider
from ai_inspector.process_map.card_previews import (
    render_process_map_card_previews,
    resolve_process_map_card_preview_artifact,
)
from ai_inspector.process_map.visual_validation import (
    ProcessMapVisualValidationError,
    apply_process_map_visual_corrections,
    build_process_map_visual_review_context,
    public_process_map_visual_validation_report,
    render_process_map_visual_review,
    review_semantic_process_plan_visuals,
    validate_process_map_visual_review,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _plan() -> dict:
    return {
        "schemaVersion": 1,
        "planId": "plan-visual-fixture",
        "scope": {
            "assemblyOccurrenceId": "module",
            "label": "Fixture Module",
        },
        "requiredOccurrences": [
            {"occurrenceId": "part-a"},
            {"occurrenceId": "part-b"},
        ],
        "operations": [
            {
                "id": "op-prepare",
                "label": "Prepare both parts",
                "stageIndex": 1,
                "inputs": [
                    {"ref": "part-a", "type": "occurrence"},
                    {"ref": "part-b", "type": "occurrence"},
                ],
                "output": {
                    "ref": "state-prepared",
                    "type": "intermediateResult",
                    "label": "Prepared part",
                },
            },
            {
                "id": "op-join",
                "label": "Join module",
                "stageIndex": 2,
                "inputs": [
                    {"ref": "state-prepared", "type": "intermediateResult"},
                ],
                "output": {"ref": "module", "type": "occurrence"},
            },
        ],
        "intermediateResults": [
            {
                "id": "state-prepared",
                "label": "Prepared part",
                "producedBy": "op-prepare",
            }
        ],
    }


def _assembly_knowledge(tmp_path: Path) -> tuple[dict, Path]:
    package_dir = tmp_path / "package"
    presentation_dir = package_dir / "visuals" / "presentation"
    mask_dir = package_dir / "visuals" / "identity_masks"
    presentation_dir.mkdir(parents=True)
    mask_dir.mkdir(parents=True)

    presentation_path = presentation_dir / "front.png"
    presentation = Image.new("RGB", (180, 90), (238, 242, 246))
    draw = ImageDraw.Draw(presentation)
    draw.rectangle((18, 20, 68, 70), fill=(120, 130, 145))
    draw.rectangle((112, 20, 162, 70), fill=(170, 180, 190))
    presentation.save(presentation_path)

    mask_path = mask_dir / "front.png"
    mask = Image.new("RGB", (180, 90), (0, 0, 0))
    draw = ImageDraw.Draw(mask)
    draw.rectangle((18, 20, 68, 70), fill=(32, 123, 97))
    draw.rectangle((112, 20, 162, 70), fill=(214, 123, 58))
    mask.save(mask_path)

    presentation_relative = "visuals/presentation/front.png"
    mask_relative = "visuals/identity_masks/front.png"
    presentation_hash = _sha256(presentation_path)
    mask_hash = _sha256(mask_path)
    documents = {
        "package.json": {
            "assetHashes": {
                presentation_relative: presentation_hash,
                mask_relative: mask_hash,
            }
        },
        "product_structure.json": {
            "rootOccurrenceId": "root",
            "occurrences": [
                {
                    "occurrenceId": "root",
                    "parentOccurrenceId": None,
                    "name": "Root",
                    "kind": "assembly",
                },
                {
                    "occurrenceId": "module",
                    "parentOccurrenceId": "root",
                    "name": "Fixture Module",
                    "kind": "subassembly",
                },
                {
                    "occurrenceId": "part-a",
                    "parentOccurrenceId": "module",
                    "name": "Part A",
                    "kind": "part",
                },
                {
                    "occurrenceId": "part-b",
                    "parentOccurrenceId": "module",
                    "name": "Part B",
                    "kind": "part",
                },
            ],
        },
        "visual_manifest.json": {
            "views": [
                {
                    "viewId": "assembly-front-001",
                    "kind": "presentation",
                    "assetPath": presentation_relative,
                    "assetHash": presentation_hash,
                    "maskAssetPath": mask_relative,
                    "maskAssetHash": mask_hash,
                    "width": 180,
                    "height": 90,
                    "camera": {"namedView": "front"},
                    "colorLegend": {
                        "#207B61": "part-a",
                        "#D67B3A": "part-b",
                    },
                }
            ]
        },
    }
    return (
        {
            "documents": documents,
            "binding": {
                "packageId": "akp-fixture1234",
                "packageRevision": "1" * 64,
                "sourceRevision": "2" * 64,
                "evidenceFingerprint": "3" * 64,
                "contextFingerprint": "4" * 64,
            },
        },
        package_dir,
    )


def _review_response(*, confidence: float = 0.97) -> dict:
    return {
        "schemaVersion": 1,
        "overallVerdict": "corrected",
        "operationReviews": [
            {
                "operationId": "op-prepare",
                "verdict": "needs_correction",
                "confidence": confidence,
                "findings": [
                    {
                        "code": "part_group_mismatch",
                        "message": "Part B belongs with the joining operation.",
                        "occurrenceIds": ["part-b"],
                    }
                ],
                "proposedLabel": "Prepare part A",
                "moveOccurrences": [
                    {
                        "occurrenceId": "part-b",
                        "toOperationId": "op-join",
                        "reason": "The fixed views place Part B at the joining interface.",
                    }
                ],
            },
            {
                "operationId": "op-join",
                "verdict": "coherent",
                "confidence": 0.98,
                "findings": [],
                "proposedLabel": None,
                "moveOccurrences": [],
            },
        ],
        "unresolvedItems": [],
    }


def test_context_derives_direct_and_cumulative_occurrence_groups(
    tmp_path: Path,
) -> None:
    knowledge, _ = _assembly_knowledge(tmp_path)
    context = build_process_map_visual_review_context(_plan(), knowledge)
    operations = {
        item["operationId"]: item for item in context["operations"]
    }
    assert [
        item["occurrenceId"]
        for item in operations["op-prepare"]["directOccurrences"]
    ] == ["part-a", "part-b"]
    assert operations["op-prepare"]["inheritedOccurrences"] == []
    assert operations["op-join"]["directOccurrences"] == []
    assert [
        item["occurrenceId"]
        for item in operations["op-join"]["inheritedOccurrences"]
    ] == ["part-a", "part-b"]


def test_renderer_creates_hash_bound_occurrence_contact_sheet(
    tmp_path: Path,
) -> None:
    knowledge, package_dir = _assembly_knowledge(tmp_path)
    rendered = render_process_map_visual_review(
        _plan(),
        knowledge,
        package_dir=package_dir,
        artifact_root=tmp_path / "artifacts",
        provider_name="fixture",
        model="fixture-model-v1",
    )
    artifact = rendered["artifact"]
    path = Path(artifact["absolutePath"])
    assert path.is_file()
    assert _sha256(path) == artifact["assetHash"]
    assert artifact["width"] > 300
    assert artifact["height"] > 200
    assert rendered["context"]["views"][0]["colorLegend"]["#207B61"] == "part-a"


def test_card_previews_isolate_occurrences_and_color_stage_state(
    tmp_path: Path,
) -> None:
    knowledge, package_dir = _assembly_knowledge(tmp_path)
    descriptors = [
        {
            "previewId": "card-part-a",
            "kind": "occurrence",
            "occurrenceIds": ["part-a"],
            "directOccurrenceIds": [],
        },
        {
            "previewId": "card-stage",
            "kind": "stage",
            "occurrenceIds": ["part-a", "part-b"],
            "directOccurrenceIds": ["part-b"],
        },
    ]
    first = render_process_map_card_previews(
        knowledge,
        descriptors,
        package_dir=package_dir,
        artifact_root=tmp_path / "card-previews",
    )
    second = render_process_map_card_previews(
        knowledge,
        descriptors,
        package_dir=package_dir,
        artifact_root=tmp_path / "card-previews",
    )
    assert first == second
    assert first["warnings"] == []
    assert [item["previewId"] for item in first["previews"]] == [
        "card-part-a",
        "card-stage",
    ]

    part_path = resolve_process_map_card_preview_artifact(
        tmp_path / "card-previews",
        first["previews"][0]["artifactId"],
    )
    stage_path = resolve_process_map_card_preview_artifact(
        tmp_path / "card-previews",
        first["previews"][1]["artifactId"],
    )
    with Image.open(part_path).convert("RGBA") as part_image:
        assert part_image.getchannel("A").getbbox() is not None
    with Image.open(stage_path).convert("RGBA") as stage_image:
        opaque_colors = {
            pixel[:3]
            for pixel in stage_image.getdata()
            if pixel[3] == 255
        }
    assert (42, 185, 214) in opaque_colors
    assert (245, 153, 45) in opaque_colors


def test_card_preview_rejects_unknown_occurrence(
    tmp_path: Path,
) -> None:
    knowledge, package_dir = _assembly_knowledge(tmp_path)
    try:
        render_process_map_card_previews(
            knowledge,
            [
                {
                    "previewId": "unknown-card",
                    "kind": "occurrence",
                    "occurrenceIds": ["missing-occurrence"],
                    "directOccurrenceIds": [],
                }
            ],
            package_dir=package_dir,
            artifact_root=tmp_path / "card-previews",
        )
    except ProcessMapVisualValidationError as exc:
        assert exc.code == "card_preview_occurrence_unknown"
    else:
        raise AssertionError("Unknown card-preview occurrence should be rejected")


def test_one_bounded_review_applies_only_high_confidence_safe_corrections(
    tmp_path: Path,
) -> None:
    knowledge, package_dir = _assembly_knowledge(tmp_path)
    provider = FixtureMultimodalProvider([_review_response()])
    result = review_semantic_process_plan_visuals(
        _plan(),
        knowledge,
        package_dir=package_dir,
        artifact_root=tmp_path / "artifacts",
        provider=provider,
    )
    assert len(provider.calls) == 1
    corrected = {
        item["id"]: item for item in result["plan"]["operations"]
    }
    assert corrected["op-prepare"]["label"] == "Prepare part A"
    assert corrected["op-prepare"]["inputs"] == [
        {"ref": "part-a", "type": "occurrence"}
    ]
    assert {"ref": "part-b", "type": "occurrence"} in corrected["op-join"]["inputs"]
    report = result["report"]
    assert report["status"] == "corrected"
    assert len(report["appliedCorrections"]) == 2
    assert Path(report["artifact"]["absolutePath"]).is_file()
    assert Path(report["originalArtifact"]["absolutePath"]).is_file()
    assert report["artifact"]["artifactId"] != report["originalArtifact"]["artifactId"]
    assert report["artifact"]["assetHash"] != report["originalArtifact"]["assetHash"]


def test_low_confidence_correction_is_deferred_without_mutating_plan(
    tmp_path: Path,
) -> None:
    knowledge, package_dir = _assembly_knowledge(tmp_path)
    provider = FixtureMultimodalProvider([_review_response(confidence=0.72)])
    result = review_semantic_process_plan_visuals(
        _plan(),
        knowledge,
        package_dir=package_dir,
        artifact_root=tmp_path / "artifacts",
        provider=provider,
    )
    assert result["plan"] == _plan()
    assert result["report"]["status"] == "needs_review"
    assert result["report"]["appliedCorrections"] == []
    assert result["report"]["unresolvedItems"]


def test_identical_review_uses_cache_without_a_second_provider_call(
    tmp_path: Path,
) -> None:
    knowledge, package_dir = _assembly_knowledge(tmp_path)
    first_provider = FixtureMultimodalProvider([_review_response()])
    first = review_semantic_process_plan_visuals(
        _plan(),
        knowledge,
        package_dir=package_dir,
        artifact_root=tmp_path / "artifacts",
        provider=first_provider,
    )
    second_provider = FixtureMultimodalProvider([])
    second = review_semantic_process_plan_visuals(
        _plan(),
        knowledge,
        package_dir=package_dir,
        artifact_root=tmp_path / "artifacts",
        provider=second_provider,
    )
    assert first["plan"] == second["plan"]
    assert second["report"]["fromCache"] is True
    assert second_provider.calls == []


def test_visual_review_rejects_unknown_or_reused_occurrence_ids(
    tmp_path: Path,
) -> None:
    knowledge, _ = _assembly_knowledge(tmp_path)
    context = build_process_map_visual_review_context(_plan(), knowledge)
    invalid = _review_response()
    invalid["operationReviews"][0]["moveOccurrences"][0][
        "occurrenceId"
    ] = "unknown-part"
    try:
        validate_process_map_visual_review(invalid, context)
    except ProcessMapVisualValidationError as exc:
        assert exc.code == "visual_review_occurrence_unknown" or exc.code == (
            "visual_review_move_invalid"
        )
    else:
        raise AssertionError("Unknown occurrence move should be rejected")


def test_public_report_never_exposes_server_local_artifact_path(
    tmp_path: Path,
) -> None:
    report = {
        "schemaVersion": 1,
        "status": "corrected",
        "fingerprint": "a" * 64,
        "promptVersion": "v1",
        "provider": "fixture",
        "model": "fixture",
        "fromCache": False,
        "overallVerdict": "corrected",
        "originalPlanHash": "b" * 64,
        "reviewedPlanHash": "c" * 64,
        "operationReviews": [],
        "appliedCorrections": [
            {
                "kind": "rename_operation",
                "operationId": "op-prepare",
            }
        ],
        "unresolvedItems": [],
        "artifact": {
            "artifactId": "d" * 64,
            "absolutePath": str(tmp_path / "private.png"),
            "assetHash": "e" * 64,
            "width": 100,
            "height": 100,
        },
    }
    public = public_process_map_visual_validation_report(
        report,
        artifact_url="/safe/image",
    )
    assert "absolutePath" not in public["artifact"]
    assert public["artifact"]["url"] == "/safe/image"
    assert public["correctionCount"] == 1


def test_correction_function_never_moves_low_confidence_occurrences() -> None:
    result = apply_process_map_visual_corrections(
        _plan(),
        {
            "operationReviews": _review_response(
                confidence=0.5
            )["operationReviews"]
        },
    )
    assert result["plan"] == _plan()
    assert result["appliedCorrections"] == []
    assert result["deferredReviews"]
