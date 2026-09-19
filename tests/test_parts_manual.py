from __future__ import annotations

from pathlib import Path
import hashlib
import json
import io

import pytest
import fitz
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient

import server
from ai_inspector.parts_manual import (
    DocumentationSceneConflictError,
    DocumentationSceneRepository,
    PARTS_MANUAL_RENDER_PIPELINE_VERSION,
    PartsManualConflictError,
    PartsManualRepository,
    PartsManualValidationError,
    audit_manual_plan,
    build_occurrence_catalog,
    build_manual_document,
    build_scoped_bom,
    compile_manual_structure_proposal,
)
from ai_inspector.parts_manual.version import (  # noqa: E402
    PARTS_MANUAL_DEFAULT_END_CONDITION,
)
from ai_inspector.parts_manual.artifacts import (
    PartsManualRenderArtifactError,
    _native_atomic_path,
    _render_quality,
    _validate_balloons,
)
from ai_inspector.parts_manual.layout import page_layout, publication_layout
from ai_inspector.parts_manual.pdf import (
    _draw_bom_table,
    _draw_documentation_objects,
    _draw_wordmark,
    _page_element_rect,
    _validate_document,
)


def test_pdf_publication_allows_an_unspecified_controlled_revision() -> None:
    _validate_document(
        {
            "status": "publication_ready",
            "publicationAudit": {"status": "PASS"},
            "calloutAudit": {"status": "PASS"},
            "documentNumber": "IPM-FIXTURE-001",
            "revision": None,
            "pageCount": 2,
            "pages": [
                {
                    "pageId": "page-cover",
                    "pageNumber": 1,
                    "pageType": "cover",
                    "title": "Fixture Illustrated Parts Manual",
                },
                {
                    "pageId": "page-contents",
                    "pageNumber": 2,
                    "pageType": "table_of_contents",
                    "title": "Table of Contents",
                    "entries": [],
                },
            ],
        }
    )


def _png(width: int = 2400, height: int = 1800) -> bytes:
    buffer = io.BytesIO()
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle(
        (int(width * 0.09), int(height * 0.09), int(width * 0.91), int(height * 0.91)),
        outline=(48, 48, 48),
        width=max(2, width // 240),
    )
    for fraction in (0.28, 0.50, 0.72):
        x = int(width * fraction)
        draw.line(
            (x, int(height * 0.09), x, int(height * 0.91)),
            fill=(48, 48, 48),
            width=max(2, width // 300),
        )
    draw.line(
        (int(width * 0.09), int(height * 0.09), int(width * 0.91), int(height * 0.91)),
        fill=(48, 48, 48),
        width=max(2, width // 300),
    )
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _balloons_for_page(
    page: dict, *, repeated_strategy: str = "representative_with_count"
) -> str:
    rows = page.get("renderRequest", {}).get("calloutItems", [])
    count = max(1, len(rows))
    return json.dumps(
        [
            _valid_balloon(row, index, count, repeated_strategy=repeated_strategy)
            for index, row in enumerate(rows)
        ]
    )


def _valid_balloon(
    row: dict,
    index: int,
    count: int,
    *,
    repeated_strategy: str = "representative_with_count",
) -> dict:
    """A publishable balloon manifest row.

    Repeated parts default to representative_with_count because that is what
    automatic generation now emits: one balloon, one leader, one representative
    anchor and an nX badge. Pass repeated_strategy="branched" to model a page
    where a user explicitly authored a branched leader.
    """
    y = 0.20 + index * 0.60 / max(1, count - 1) if count > 1 else 0.50
    occurrence_ids = [str(value) for value in row["occurrenceIds"]]
    occurrence_id = occurrence_ids[0]
    bounds = {"left": 0.38, "top": y - 0.02, "right": 0.42, "bottom": y + 0.02}
    anchor_scope = str(row.get("anchorScope") or ("manual_group" if row.get("sectionId") else "component_instance"))
    callout_type = "group" if anchor_scope == "manual_group" else (
        repeated_strategy if len(occurrence_ids) > 1 else "single"
    )
    anchors = [{
        "occurrenceId": occurrence_id,
        "target": {"x": 0.40, "y": y},
        "targetBounds": bounds,
        "anchorMethod": "frontmost_camera_raycast",
        "anchorRaycastDistance": 1.0,
        "visibleSampleCount": 12,
        "anchorValidated": True,
        "primary": True,
    }]
    branches = []
    projected_regions = [{"occurrenceId": occurrence_id, "bounds": bounds}]
    if callout_type == "branched":
        for occurrence_index, repeated_occurrence_id in enumerate(occurrence_ids[1:], start=1):
            branch_y = min(0.94, y + occurrence_index * 0.025)
            branch_bounds = {
                "left": 0.40,
                "top": branch_y - 0.015,
                "right": 0.44,
                "bottom": branch_y + 0.015,
            }
            branch_target = {"x": 0.42, "y": branch_y}
            anchor = {
                "occurrenceId": repeated_occurrence_id,
                "target": branch_target,
                "targetBounds": branch_bounds,
                "anchorMethod": "frontmost_camera_raycast",
                "anchorRaycastDistance": 1.1,
                "visibleSampleCount": 8,
                "anchorValidated": True,
                "primary": False,
            }
            anchors.append(anchor)
            projected_regions.append({
                "occurrenceId": repeated_occurrence_id,
                "bounds": branch_bounds,
            })
            branches.append({
                **anchor,
                "leaderPath": [{"x": 0.48, "y": branch_y}, {"x": 0.48, "y": y}],
                "routeValidationMethod": "frontmost_raycast_sampling",
                "routeRaycastSampleCount": 12,
                "routeObstructingItemNumbers": [],
                "geometryIntersectionCount": 0,
                "leaderCrossingCount": 0,
                "routingValidated": True,
            })
    return {
        "itemNumber": row["itemNumber"],
        "occurrenceIds": occurrence_ids,
        "target": {"x": 0.40, "y": y},
        "balloon": {"x": 0.68, "y": y},
        "leaderPath": [{"x": 0.48, "y": y}, {"x": 0.58, "y": y}],
        "targetBounds": bounds,
        "projectedRegions": projected_regions,
        "anchorMethod": "frontmost_camera_raycast",
        "anchorOccurrenceId": occurrence_id,
        "anchorRaycastDistance": 1.0,
        "visibleSampleCount": 12,
        "anchorValidated": True,
        "anchorScope": anchor_scope,
        "manualGroupId": str(row.get("sectionId") or ""),
        "calloutType": callout_type,
        "anchors": anchors,
        "branches": branches,
        "representativeCount": len(occurrence_ids),
        "quantityLabel": (
            f"{len(occurrence_ids)}X"
            if callout_type == "representative_with_count"
            else ""
        ),
        "repeatedStrategyValidated": True,
        "repeatedPartStrategySource": (
            "user_override" if callout_type == "branched" else "contract_default"
        ),
        "routeSide": "right",
        "leaderStyle": "orthogonal",
        "endCondition": str(
            row.get("endCondition") or PARTS_MANUAL_DEFAULT_END_CONDITION
        ),
        "geometryIntersectionCount": 0,
        "leaderCrossingCount": 0,
        "routeValidationMethod": "frontmost_raycast_sampling",
        "routeRaycastSampleCount": 24,
        "branchRouteRaycastSampleCount": sum(
            branch["routeRaycastSampleCount"] for branch in branches
        ),
        "routeObstructingItemNumbers": [],
        "routingValidated": True,
    }


def test_pdf_bom_preserves_long_unbroken_part_numbers() -> None:
    with fitz.open() as pdf:
        page = pdf.new_page(width=792, height=612)
        _draw_bom_table(
            fitz,
            page,
            fitz.Rect(28, 62, 326, 564),
            [
                {
                    "item": 1,
                    "partNumber": "SWPR-Tricycle_Wheel Spacer",
                    "displayPartNumber": "SWPR-Tricycle_Wheel Spacer",
                    "description": "Wheel Spacer",
                    "quantity": 2,
                }
            ],
        )
        assert "SWPR-Tricycle_Wheel Spacer" in page.get_text()


def test_pdf_bom_compact_rows_keep_short_engineering_values_visible() -> None:
    with fitz.open() as pdf:
        page = pdf.new_page(width=792, height=612)
        _draw_bom_table(
            fitz,
            page,
            fitz.Rect(558, 70, 764, 564),
            [
                {
                    "item": 1,
                    "displayPartNumber": "Not specified",
                    "description": "Bell",
                    "quantity": 1,
                }
            ],
        )
        text = page.get_text()
        assert "Not specified" in text
        assert "Bell" in text


def test_pdf_wordmark_renders_pro_in_brand_blue() -> None:
    with fitz.open() as pdf:
        page = pdf.new_page(width=300, height=100)
        page.draw_rect(page.rect, color=None, fill=(0.035, 0.075, 0.12))
        _draw_wordmark(fitz, page, fitz.Point(20, 40), fontsize=18)
        spans = [
            span
            for block in page.get_text("dict").get("blocks", [])
            for line in block.get("lines", [])
            for span in line.get("spans", [])
        ]
        inspector = next(span for span in spans if span["text"] == "Inspector")
        pro = next(span for span in spans if span["text"] == "Pro")
        assert inspector["color"] != pro["color"]


def test_documentation_scene_v2_replays_objects_theme_and_history(tmp_path: Path) -> None:
    repository = DocumentationSceneRepository(tmp_path)
    page_id = "page-cover"
    targets = {
        page_id: {
            "figure": [],
            "manual_group": [],
            "occurrence": [],
            "balloon": [],
            "leader": [],
            "page_element": ["header_title", "cover_subtitle"],
            "document_object": [],
            "document_theme": ["company-theme"],
        }
    }
    loaded = repository.read("tricycle", "source-a", "plan-a")
    assert loaded["scene"]["schemaVersion"] == 2
    object_id = "document-object-release-note"
    created = repository.apply_command(
        "tricycle",
        "source-a",
        "plan-a",
        base_revision=loaded["revision"],
        command={
            "operation": "add_object",
            "targetType": "document_object",
            "targetId": object_id,
            "pageId": page_id,
            "documentObject": {
                "objectId": object_id,
                "type": "text",
                "name": "Release Note",
                "content": "Service parts manual",
                "frame": {
                    "x": 0.2,
                    "y": 0.2,
                    "width": 0.4,
                    "height": 0.1,
                    "rotation": 0,
                },
                "styleRef": "heading",
                "styleOverrides": {},
                "locked": False,
                "source": "user",
            },
            "actor": "user",
        },
        page_targets=targets,
    )
    targets[page_id]["document_object"] = [object_id]
    updated = repository.apply_command(
        "tricycle",
        "source-a",
        "plan-a",
        base_revision=created["revision"],
        command={
            "operation": "update_text",
            "targetType": "document_object",
            "targetId": object_id,
            "pageId": page_id,
            "text": "Released service parts manual",
            "actor": "user",
        },
        page_targets=targets,
    )
    styled = repository.apply_command(
        "tricycle",
        "source-a",
        "plan-a",
        base_revision=updated["revision"],
        command={
            "operation": "update_style",
            "targetType": "document_object",
            "targetId": object_id,
            "pageId": page_id,
            "style": {"fontSize": 22, "color": "#125D87", "fontWeight": 700},
            "actor": "user",
        },
        page_targets=targets,
    )
    themed = repository.apply_command(
        "tricycle",
        "source-a",
        "plan-a",
        base_revision=styled["revision"],
        command={
            "operation": "set_theme",
            "targetType": "document_theme",
            "targetId": "company-theme",
            "pageId": page_id,
            "theme": {
                "name": "Acme Technical",
                "companyName": "Acme Manufacturing",
                "colors": {"primary": "#102B3A", "accent": "#E63946"},
            },
            "actor": "user",
        },
        page_targets=targets,
    )
    scene = themed["scene"]
    value = scene["pages"][page_id]["documentObjects"][object_id]
    assert value["content"] == "Released service parts manual"
    assert value["styleOverrides"]["fontSize"] == 22
    assert scene["theme"]["companyName"] == "Acme Manufacturing"
    assert scene["theme"]["colors"]["accent"] == "#E63946"

    undone = repository.move_history(
        "tricycle",
        "source-a",
        "plan-a",
        base_revision=themed["revision"],
        direction="undo",
    )
    assert undone["scene"]["theme"]["companyName"] == "InspectorPro"
    assert undone["scene"]["pages"][page_id]["documentObjects"][object_id][
        "content"
    ] == "Released service parts manual"
    redone = repository.move_history(
        "tricycle",
        "source-a",
        "plan-a",
        base_revision=undone["revision"],
        direction="redo",
    )
    assert redone["scene"]["theme"]["companyName"] == "Acme Manufacturing"


def test_pdf_renders_document_text_shape_and_managed_image(tmp_path: Path) -> None:
    image_payload = _png(80, 48)
    asset_id = hashlib.sha256(image_payload).hexdigest()
    asset_directory = tmp_path / "tricycle" / "documentation-assets"
    asset_directory.mkdir(parents=True)
    (asset_directory / f"{asset_id}.png").write_bytes(image_payload)
    descriptor = {
        "documentationObjects": {
            "document-object-note": {
                "objectId": "document-object-note",
                "type": "text",
                "name": "Customer Note",
                "content": "ACME SERVICE PARTS",
                "frame": {
                    "x": 0.10,
                    "y": 0.12,
                    "width": 0.36,
                    "height": 0.10,
                    "rotation": 0,
                },
                "styleRef": "heading",
                "styleOverrides": {"color": "#125D87", "fontSize": 18},
            },
            "document-object-box": {
                "objectId": "document-object-box",
                "type": "shape",
                "name": "Detail Box",
                "shapeType": "detail_box",
                "frame": {
                    "x": 0.08,
                    "y": 0.30,
                    "width": 0.26,
                    "height": 0.18,
                    "rotation": 0,
                },
                "styleRef": "body",
                "styleOverrides": {
                    "fill": "#FFFFFF",
                    "outlineColor": "#E63946",
                    "lineWidth": 2,
                },
            },
            "document-object-logo": {
                "objectId": "document-object-logo",
                "type": "image",
                "name": "Customer Logo",
                "asset": {
                    "assetId": asset_id,
                    "mimeType": "image/png",
                    "filename": "acme.png",
                    "url": f"/api/parts-manual/tricycle/documentation-assets/{asset_id}",
                },
                "contentMode": "contain",
                "frame": {
                    "x": 0.55,
                    "y": 0.12,
                    "width": 0.24,
                    "height": 0.12,
                    "rotation": 0,
                },
                "styleRef": "body",
                "styleOverrides": {},
            },
        }
    }
    with fitz.open() as pdf:
        page = pdf.new_page(width=792, height=612)
        _draw_documentation_objects(
            fitz,
            page,
            descriptor,
            {"theme": {"typography": {"headingFont": "Arial"}}},
            tmp_path,
            "tricycle",
        )
        assert "ACME SERVICE PARTS" in page.get_text()
        assert page.get_images(full=True)
        assert page.get_drawings()


def test_catalog_does_not_publish_a_cad_identity_as_an_engineering_part_number() -> None:
    profile = {
        "components": [
            {
                "name": "SWPR-Tricycle_Wheel Spacer-1",
                "type": "Part",
                "partDataKey": "SWPR-Tricycle_Wheel Spacer.sldprt",
                "referencedFileName": "SWPR-Tricycle_Wheel Spacer.SLDPRT",
            }
        ],
        "partDataCache": {
            "SWPR-Tricycle_Wheel Spacer.sldprt": {
                "identity": {
                    "customProperties": {"PartNo": "SWPR-Tricycle_Wheel Spacer"},
                }
            }
        },
    }
    catalog = build_occurrence_catalog("cad-identity-fixture", profile)
    part = next(row for row in catalog["occurrences"] if row["kind"] == "part")
    assert part["partNumber"] == "SWPR-Tricycle_Wheel Spacer"
    assert part["partNumberSource"] == "cad_identity_fallback"
    assert part["engineeringPartNumber"] is None
    assert part["displayPartNumber"] == "Not specified"
    assert part["description"] == "Wheel Spacer"


def test_catalog_normalizes_numeric_cad_copy_suffixes_in_public_descriptions() -> None:
    profile = {
        "components": [
            {
                "name": "SWPR-Tricycle_Grip2-1",
                "type": "Part",
                "partDataKey": "SWPR-Tricycle_Grip2.sldprt",
            },
            {
                "name": "SWPR-Tricycle_Fork2-1",
                "type": "Part",
                "partDataKey": "SWPR-Tricycle_Fork2.sldprt",
            },
        ],
        "partDataCache": {
            "SWPR-Tricycle_Grip2.sldprt": {
                "identity": {
                    "customProperties": {
                        "PartNo": "SWPR-Tricycle_Grip2",
                        "DESCRIPTION": "Grip2",
                    }
                }
            },
            "SWPR-Tricycle_Fork2.sldprt": {
                "identity": {
                    "customProperties": {
                        "PartNo": "SWPR-Tricycle_Fork2",
                        "DESCRIPTION": "Fork2",
                    }
                }
            },
        },
    }

    rows = build_occurrence_catalog("cad-description-fixture", profile)["occurrences"]

    assert [row["description"] for row in rows] == ["Grip", "Fork"]
    assert [row["internalComponentName"] for row in rows] == [
        "SWPR-Tricycle_Grip2-1",
        "SWPR-Tricycle_Fork2-1",
    ]
    assert all(
        row["descriptionSource"] == "cad_custom_property_normalized"
        for row in rows
    )


def test_render_quality_uses_bounding_box_area_not_longest_axis() -> None:
    narrow = Image.new("RGB", (512, 384), "white")
    draw = ImageDraw.Draw(narrow)
    draw.rectangle((242, 38, 269, 345), fill=(40, 90, 130))
    expected = {
        "background": "technical_white",
        "minimumForegroundOccupancy": 0.65,
        "maximumForegroundOccupancy": 0.85,
    }

    with pytest.raises(PartsManualRenderArtifactError, match="framing is too small"):
        _render_quality(narrow, expected)

    well_framed = Image.new("RGB", (512, 384), "white")
    draw = ImageDraw.Draw(well_framed)
    draw.rectangle((46, 35, 465, 348), fill=(40, 90, 130))
    quality = _render_quality(well_framed, expected)

    assert quality["foregroundOccupancyMetric"] == "bounding_box_area"
    assert 0.65 <= quality["foregroundOccupancy"] <= 0.85
    assert quality["foregroundWidthFraction"] > 0.8
    assert quality["foregroundHeightFraction"] > 0.8


def test_render_quality_requires_minimum_visible_ink_independently_of_framing() -> None:
    sparse = Image.new("RGB", (512, 384), "white")
    draw = ImageDraw.Draw(sparse)
    draw.line((30, 30, 480, 350), fill=(40, 40, 40), width=1)
    expected = {
        "background": "technical_white",
        "minimumForegroundOccupancy": 0.60,
        "maximumForegroundOccupancy": 0.90,
        "minimumForegroundPixelPercent": 1.0,
    }

    with pytest.raises(PartsManualRenderArtifactError, match="too little visible geometry"):
        _render_quality(sparse, expected)


def test_render_quality_accepts_legitimate_sparse_hlr_above_antiblank_floor() -> None:
    line_art = Image.new("RGB", (512, 384), "white")
    draw = ImageDraw.Draw(line_art)
    draw.rectangle((50, 40, 460, 340), outline=(40, 40, 40), width=2)
    for offset in (80, 140, 200, 260):
        draw.line((70, offset, 440, offset + 20), fill=(70, 70, 70), width=2)
    expected = {
        "background": "technical_white",
        "illustrationStyle": "HIDDEN_LINES_REMOVED",
        "minimumForegroundOccupancy": 0.60,
        "maximumForegroundOccupancy": 0.80,
        "minimumForegroundPixelPercent": 1.0,
        "foregroundPixelPolicy": "hlr_linework_antiblank_floor",
    }

    quality = _render_quality(line_art, expected)

    assert quality["status"] == "PASS"
    assert quality["foregroundPixelPercent"] > 1.0
    assert quality["foregroundPixelPolicy"] == "hlr_linework_antiblank_floor"
    assert 0.60 <= quality["foregroundOccupancy"] <= 0.80


def test_render_quality_accepts_axis_constrained_hlr_without_weakening_ink_gate() -> None:
    wide_line_art = Image.new("RGB", (512, 384), "white")
    draw = ImageDraw.Draw(wide_line_art)
    draw.rectangle((10, 72, 501, 305), outline=(35, 35, 35), width=4)
    for offset in (115, 165, 215, 265):
        draw.line((20, offset, 490, offset + 8), fill=(65, 65, 65), width=3)
    expected = {
        "background": "technical_white",
        "illustrationStyle": "HIDDEN_LINES_REMOVED",
        "minimumForegroundOccupancy": 0.60,
        "maximumForegroundOccupancy": 0.80,
        "maximumForegroundAxisOccupancy": 0.96,
        "axisConstrainedOccupancyPolicy": "allow_when_uniform_scale_exceeds_axis_limit",
        "axisConstrainedFillTolerance": 0.02,
        "minimumForegroundPixelPercent": 1.0,
    }

    quality = _render_quality(wide_line_art, expected)

    assert quality["status"] == "PASS"
    assert quality["foregroundOccupancy"] < 0.60
    assert quality["axisConstrainedOccupancyAccepted"] is True
    assert quality["axisLimitedMaximumOccupancy"] < 0.60


def test_callout_manifest_requires_visible_geometry_anchor_and_orthogonal_route() -> None:
    request = {"calloutItems": [{"itemNumber": 1, "occurrenceIds": ["occ-1"]}]}
    valid = _valid_balloon(request["calloutItems"][0], 0, 1)
    assert _validate_balloons(request, [valid])[0]["routingValidated"] is True

    floating = json.loads(json.dumps(valid))
    floating["target"] = {"x": 0.50, "y": 0.50}
    with pytest.raises(PartsManualRenderArtifactError, match="floats outside"):
        _validate_balloons(request, [floating])

    diagonal = json.loads(json.dumps(valid))
    diagonal["leaderPath"][0]["y"] = 0.55
    with pytest.raises(PartsManualRenderArtifactError, match="diagonal"):
        _validate_balloons(request, [diagonal])

    hidden_by_balloon = json.loads(json.dumps(valid))
    hidden_by_balloon["leaderPath"] = [
        {"x": 0.415, "y": hidden_by_balloon["target"]["y"]},
        {"x": 0.43, "y": hidden_by_balloon["target"]["y"]},
    ]
    hidden_by_balloon["balloon"] = {
        "x": 0.45,
        "y": hidden_by_balloon["target"]["y"],
    }
    with pytest.raises(PartsManualRenderArtifactError, match="too short to remain visible"):
        _validate_balloons(request, [hidden_by_balloon])


def test_straight_leader_terminates_on_balloon_circumference() -> None:
    request = {"calloutItems": [{"itemNumber": 1, "occurrenceIds": ["occ-1"]}]}
    straight = _valid_balloon(request["calloutItems"][0], 0, 1)
    straight["leaderStyle"] = "straight"
    straight["leaderPath"] = []

    validated = _validate_balloons(request, [straight])[0]
    attachment = validated["balloonAttachment"]
    balloon = validated["balloon"]
    assert validated["leaderStyle"] == "straight"
    assert attachment != balloon
    normalized_radius = (
        ((attachment["x"] - balloon["x"]) / 0.022) ** 2
        + ((attachment["y"] - balloon["y"]) / 0.027) ** 2
    )
    assert normalized_radius == pytest.approx(1.0, abs=0.02)

    forged = json.loads(json.dumps(straight))
    forged["balloonAttachment"] = forged["balloon"]
    with pytest.raises(PartsManualRenderArtifactError, match="terminate on its circumference"):
        _validate_balloons(request, [forged])


def test_callout_manifest_rejects_crossing_leaders() -> None:
    request = {
        "calloutItems": [
            {"itemNumber": 1, "occurrenceIds": ["occ-1"]},
            {"itemNumber": 2, "occurrenceIds": ["occ-2"]},
        ]
    }
    rows = [
        {
            **_valid_balloon(request["calloutItems"][0], 0, 2),
            "target": {"x": 0.40, "y": 0.30},
            "targetBounds": {"left": 0.38, "top": 0.28, "right": 0.42, "bottom": 0.32},
            "projectedRegions": [{
                "occurrenceId": "occ-1",
                "bounds": {"left": 0.38, "top": 0.28, "right": 0.42, "bottom": 0.32},
            }],
            "leaderPath": [],
            "leaderStyle": "straight",
            "balloon": {"x": 0.75, "y": 0.50},
        },
        {
            **_valid_balloon(request["calloutItems"][1], 1, 2),
            "target": {"x": 0.40, "y": 0.50},
            "targetBounds": {"left": 0.38, "top": 0.48, "right": 0.42, "bottom": 0.52},
            "projectedRegions": [{
                "occurrenceId": "occ-2",
                "bounds": {"left": 0.38, "top": 0.48, "right": 0.42, "bottom": 0.52},
            }],
            "leaderPath": [],
            "leaderStyle": "straight",
            "balloon": {"x": 0.75, "y": 0.30},
            "routeSide": "right",
        },
    ]
    for row in rows:
        row["anchors"][0]["target"] = row["target"]
        row["anchors"][0]["targetBounds"] = row["targetBounds"]
    with pytest.raises(PartsManualRenderArtifactError, match="leaders 1 and 2 cross"):
        _validate_balloons(request, rows)


def test_callout_manifest_rejects_excessive_leader_detours() -> None:
    request = {
        "calloutItems": [{"itemNumber": 1, "occurrenceIds": ["occ-1"]}],
        "composition": {
            "leaderOverrides": {
                "callout-item-1": {"corridorTranslation": [0.1, 0.0, 0.0]}
            }
        },
    }
    detoured = _valid_balloon(request["calloutItems"][0], 0, 1)
    detoured["target"] = {"x": 0.40, "y": 0.50}
    detoured["anchors"][0]["target"] = detoured["target"]
    detoured["balloon"] = {"x": 0.95, "y": 0.50}
    detoured["leaderPath"] = [
        {"x": 0.40, "y": 0.05},
        {"x": 0.95, "y": 0.05},
    ]

    with pytest.raises(PartsManualRenderArtifactError, match="too long for a readable"):
        _validate_balloons(request, [detoured])


def test_callout_manifest_rejects_leader_through_another_balloon() -> None:
    request = {
        "calloutItems": [
            {"itemNumber": 1, "occurrenceIds": ["occ-1"]},
            {"itemNumber": 2, "occurrenceIds": ["occ-2"]},
        ]
    }
    first = _valid_balloon(request["calloutItems"][0], 0, 2)
    first.update(
        target={"x": 0.40, "y": 0.30},
        targetBounds={"left": 0.38, "top": 0.28, "right": 0.42, "bottom": 0.304},
        projectedRegions=[{
            "occurrenceId": "occ-1",
            "bounds": {"left": 0.38, "top": 0.28, "right": 0.42, "bottom": 0.304},
        }],
        leaderPath=[{"x": 0.40, "y": 0.55}, {"x": 0.55, "y": 0.55}],
        balloon={"x": 0.70, "y": 0.55},
    )
    second = _valid_balloon(request["calloutItems"][1], 1, 2)
    second.update(
        target={"x": 0.60, "y": 0.45},
        targetBounds={"left": 0.58, "top": 0.43, "right": 0.62, "bottom": 0.47},
        projectedRegions=[{
            "occurrenceId": "occ-2",
            "bounds": {"left": 0.58, "top": 0.43, "right": 0.62, "bottom": 0.47},
        }],
        leaderPath=[],
        leaderStyle="straight",
        balloon={"x": 0.40, "y": 0.45},
        routeSide="left",
    )
    for row in (first, second):
        row["anchors"][0]["target"] = row["target"]
        row["anchors"][0]["targetBounds"] = row["targetBounds"]
    request["composition"] = {
        "leaderOverrides": {
            "callout-item-1": {"corridorTranslation": [0.1, 0.0, 0.0]}
        }
    }

    with pytest.raises(PartsManualRenderArtifactError, match="intersect another balloon"):
        _validate_balloons(request, [first, second])


def test_callout_manifest_rejects_parallel_route_congestion() -> None:
    request = {
        "calloutItems": [
            {"itemNumber": 1, "occurrenceIds": ["occ-1"]},
            {"itemNumber": 2, "occurrenceIds": ["occ-2"]},
        ]
    }
    first = _valid_balloon(request["calloutItems"][0], 0, 2)
    first.update(
        target={"x": 0.40, "y": 0.30},
        targetBounds={"left": 0.38, "top": 0.28, "right": 0.42, "bottom": 0.32},
        projectedRegions=[{
            "occurrenceId": "occ-1",
            "bounds": {"left": 0.38, "top": 0.28, "right": 0.42, "bottom": 0.32},
        }],
        leaderPath=[],
        leaderStyle="straight",
        balloon={"x": 0.90, "y": 0.30},
    )
    second = _valid_balloon(request["calloutItems"][1], 1, 2)
    second.update(
        target={"x": 0.80, "y": 0.31},
        targetBounds={"left": 0.78, "top": 0.306, "right": 0.82, "bottom": 0.326},
        projectedRegions=[{
            "occurrenceId": "occ-2",
            "bounds": {"left": 0.78, "top": 0.306, "right": 0.82, "bottom": 0.326},
        }],
        leaderPath=[],
        leaderStyle="straight",
        balloon={"x": 0.30, "y": 0.31},
        routeSide="left",
    )
    for row in (first, second):
        row["anchors"][0]["target"] = row["target"]
        row["anchors"][0]["targetBounds"] = row["targetBounds"]

    with pytest.raises(PartsManualRenderArtifactError, match="too closely in parallel"):
        _validate_balloons(request, [first, second])


def test_callout_manifest_defaults_repeated_parts_to_a_single_counted_leader() -> None:
    """Automatic generation gives a qty>1 item one balloon, one leader, one nX badge."""
    request = {
        "calloutItems": [
            {
                "itemNumber": 4,
                "calloutId": "callout-item-4",
                "occurrenceIds": ["left-wheel", "right-wheel"],
                "anchorScope": "component_instance",
            }
        ],
        "calloutContract": {
            "defaultRepeatedPartStrategy": "representative_with_count"
        },
    }
    generated = _valid_balloon(request["calloutItems"][0], 0, 1)
    validated = _validate_balloons(request, [generated])[0]
    assert validated["calloutType"] == "representative_with_count"
    assert validated["representativeCount"] == 2
    assert validated["quantityLabel"] == "2X"
    assert len(validated["anchors"]) == 1
    assert validated["branches"] == []
    assert validated["anchors"][0]["occurrenceId"] == "left-wheel"

    # A branched layout nobody asked for is refused rather than trusted.
    unauthorised = json.loads(json.dumps(generated))
    unauthorised["calloutType"] = "branched"
    with pytest.raises(
        PartsManualRenderArtifactError, match="no documentation override requested"
    ):
        _validate_balloons(request, [unauthorised])


def test_callout_manifest_keeps_arrow_endpoints_available_by_override_only() -> None:
    """Generated leaders end on a dot; an arrowhead needs an authored override."""
    base_item = {
        "itemNumber": 1,
        "calloutId": "callout-item-1",
        "occurrenceIds": ["only-one"],
        "anchorScope": "component_instance",
    }

    # Default contract: the manifest must carry the generated dot.
    default_request = {"calloutItems": [dict(base_item)]}
    generated = _valid_balloon(default_request["calloutItems"][0], 0, 1)
    assert generated["endCondition"] == "dot"
    assert _validate_balloons(default_request, [generated])[0]["endCondition"] == "dot"

    # An arrowhead the user never asked for is refused.
    unauthorised = json.loads(json.dumps(generated))
    unauthorised["endCondition"] = "arrow"
    with pytest.raises(
        PartsManualRenderArtifactError, match="authored leader end condition"
    ):
        _validate_balloons(default_request, [unauthorised])

    # With the arrow authored on the row, the same manifest validates - and the
    # dot is now the mismatch, so neither endpoint is silently interchangeable.
    authored_request = {"calloutItems": [dict(base_item, endCondition="arrow")]}
    authored = _valid_balloon(authored_request["calloutItems"][0], 0, 1)
    assert authored["endCondition"] == "arrow"
    assert _validate_balloons(authored_request, [authored])[0]["endCondition"] == "arrow"
    with pytest.raises(
        PartsManualRenderArtifactError, match="authored leader end condition"
    ):
        _validate_balloons(authored_request, [generated])


def test_callout_manifest_validates_repeated_branches_and_group_scope() -> None:
    repeated_request = {
        "calloutItems": [
            {
                "itemNumber": 4,
                "calloutId": "callout-item-4",
                "occurrenceIds": ["left-wheel", "right-wheel"],
                "anchorScope": "component_instance",
            }
        ],
        # A branched leader is only reachable through an explicit user override.
        "composition": {
            "leaderOverrides": {
                "callout-item-4": {"repeatedPartStrategy": "branched"}
            }
        },
    }
    repeated = _valid_balloon(
        repeated_request["calloutItems"][0], 0, 1, repeated_strategy="branched"
    )
    validated = _validate_balloons(repeated_request, [repeated])[0]
    assert validated["calloutType"] == "branched"
    assert len(validated["branches"]) == 1
    assert sorted(row["occurrenceId"] for row in validated["anchors"]) == [
        "left-wheel",
        "right-wheel",
    ]

    detoured = json.loads(json.dumps(repeated))
    branch = detoured["branches"][0]
    branch_y = branch["target"]["y"]
    trunk_y = detoured["target"]["y"]
    branch["leaderPath"] = [
        {"x": 0.46, "y": branch_y},
        {"x": 0.46, "y": branch_y + 0.01},
        {"x": 0.50, "y": branch_y + 0.01},
        {"x": 0.50, "y": trunk_y},
        {"x": 0.55, "y": trunk_y},
    ]
    assert _validate_balloons(repeated_request, [detoured])[0]["branches"][0][
        "routingValidated"
    ] is True

    missing_branch = json.loads(json.dumps(repeated))
    missing_branch["branches"] = []
    with pytest.raises(PartsManualRenderArtifactError, match="do not account"):
        _validate_balloons(repeated_request, [missing_branch])

    unlabelled_representative = json.loads(json.dumps(repeated))
    unlabelled_representative["calloutType"] = "representative"
    unlabelled_representative["anchors"] = unlabelled_representative["anchors"][:1]
    unlabelled_representative["branches"] = []
    with pytest.raises(PartsManualRenderArtifactError, match="no validated repeated-part strategy"):
        _validate_balloons(repeated_request, [unlabelled_representative])

    group_request = {
        "calloutItems": [
            {
                "itemNumber": 1,
                "sectionId": "front-group",
                "occurrenceIds": ["fork", "wheel"],
                "anchorScope": "manual_group",
            }
        ]
    }
    group = _valid_balloon(group_request["calloutItems"][0], 0, 1)
    validated_group = _validate_balloons(group_request, [group])[0]
    assert validated_group["calloutType"] == "group"
    assert validated_group["manualGroupId"] == "front-group"


def _assembly_profile() -> dict:
    return {
        "identity": {
            "assemblyNumber": "manual-fixture",
            "description": "Manual Fixture Assembly",
            "revision": "A",
        },
        "statistics": {
            "totalComponents": 3,
            "uniquePartCount": 2,
            "totalMates": 0,
        },
        "components": [
            {
                "name": "Workbench-1",
                "type": "Part",
                "level": 1,
                "activeConfiguration": "Default",
                "partDataKey": "workbench.sldprt",
                "referencedFileName": "workbench.SLDPRT",
                "transform": {"translation": [0.0, 0.0, 0.0]},
            },
            {
                "name": "Workbench-2",
                "type": "Part",
                "level": 1,
                "activeConfiguration": "Default",
                "partDataKey": "workbench.sldprt",
                "referencedFileName": "workbench.SLDPRT",
                "transform": {"translation": [1.0, 0.0, 0.0]},
            },
            {
                "name": "Fixture-1",
                "type": "Part",
                "level": 1,
                "activeConfiguration": "Default",
                "partDataKey": "fixture.sldprt",
                "referencedFileName": "fixture.SLDPRT",
                "transform": {"translation": [0.5, 0.0, 0.5]},
            },
        ],
        "partDataCache": {
            "workbench.sldprt": {
                "identity": {
                    "partNumber": "WB-100",
                    "description": "Assembly Workbench",
                    "customProperties": {"PartNo": "WB-100"},
                }
            },
            "fixture.sldprt": {
                "identity": {
                    "partNumber": "FX-200",
                    "description": "Locating Fixture",
                    "customProperties": {"PartNo": "FX-200"},
                }
            },
        },
        "partColorMapping": {
            "workbench.sldprt": "#112233",
            "fixture.sldprt": "#445566",
        },
        "mates": [],
        "mateRelationships": [],
        "explodeSteps": [],
    }


def _process_evidence_for_rows(rows: list[dict]) -> dict:
    workbenches = [row for row in rows if row["partNumber"] == "WB-100"]
    operation_id = "process-workbench-assembly"
    nodes = [
        {
            "nodeId": f"node-{index}",
            "nodeKind": "product_occurrence",
            "sourceOccurrenceId": row["occurrenceId"],
        }
        for index, row in enumerate(workbenches)
    ]
    nodes.append(
        {
            "nodeId": operation_id,
            "nodeKind": "process_step",
            "name": "Assemble workbench station",
            "semantic": {
                "stageIndex": 1,
                "knowledgeStatus": "derived",
                "semanticRef": "operation-workbench-station",
            },
        }
    )
    edges = [
        {
            "from": {"nodeId": f"node-{index}"},
            "to": {"nodeId": operation_id},
        }
        for index in range(len(workbenches))
    ]
    return {
        "revision": "c" * 64,
        "map": {
            "mapId": "manual-planner-fixture",
            "canvasNodes": nodes,
            "canvasEdges": edges,
        },
    }


def test_documentation_scene_commands_are_persistent_replayable_and_isolated(
    tmp_path: Path,
) -> None:
    repository = DocumentationSceneRepository(tmp_path)
    targets = {
        "page-overview": {
            "figure": ["page-overview"],
            "manual_group": ["section-front", "section-rear"],
            "occurrence": [],
        },
        "page-section-front": {
            "figure": ["page-section-front"],
            "manual_group": [],
            "occurrence": ["pedal-left", "pedal-right"],
            "balloon": ["callout-item-9"],
            "leader": ["callout-item-9"],
        },
    }
    initial = repository.read("tricycle", "source-a", "plan-a")
    assert initial["scene"]["pages"] == {}
    assert not initial["persisted"]

    moved_group = repository.apply_command(
        "tricycle",
        "source-a",
        "plan-a",
        base_revision=initial["revision"],
        command={
            "operation": "translate",
            "targetType": "manual_group",
            "targetId": "section-front",
            "pageId": "page-overview",
            "translation": [0.0, -0.25, 0.0],
            "actor": "user",
        },
        page_targets=targets,
    )
    moved_pedal = repository.apply_command(
        "tricycle",
        "source-a",
        "plan-a",
        base_revision=moved_group["revision"],
        command={
            "operation": "translate",
            "targetType": "occurrence",
            "targetId": "pedal-left",
            "pageId": "page-section-front",
            "translation": [-0.18, 0.0, 0.0],
            "actor": "sage",
        },
        page_targets=targets,
    )
    scene = moved_pedal["scene"]
    assert scene["pages"]["page-overview"]["manualGroupOverrides"]["section-front"] == {
        "translation": [0.0, -0.25, 0.0]
    }
    assert scene["pages"]["page-section-front"]["occurrenceOverrides"]["pedal-left"] == {
        "translation": [-0.18, 0.0, 0.0]
    }
    assert (tmp_path / "tricycle" / "documentation-scene.json").is_file()
    assert not (tmp_path / "tricycle" / "manual-plan.json").exists()

    undone = repository.move_history(
        "tricycle",
        "source-a",
        "plan-a",
        base_revision=moved_pedal["revision"],
        direction="undo",
    )
    assert "page-section-front" not in undone["scene"]["pages"]
    assert undone["canRedo"]
    redone = repository.move_history(
        "tricycle",
        "source-a",
        "plan-a",
        base_revision=undone["revision"],
        direction="redo",
    )
    assert redone["scene"]["pages"] == scene["pages"]

    with pytest.raises(DocumentationSceneConflictError):
        repository.apply_command(
            "tricycle",
            "source-a",
            "plan-a",
            base_revision=initial["revision"],
            command={
                "operation": "reset",
                "targetType": "manual_group",
                "targetId": "section-front",
                "pageId": "page-overview",
                "actor": "user",
            },
            page_targets=targets,
        )


def test_documentation_callout_commands_persist_balloon_anchor_and_corridor(
    tmp_path: Path,
) -> None:
    repository = DocumentationSceneRepository(tmp_path)
    targets = {
        "page-section-front": {
            "figure": ["page-section-front"],
            "manual_group": [],
            "occurrence": [],
            "balloon": ["callout-item-9"],
            "leader": ["callout-item-9"],
        }
    }
    initial = repository.read("tricycle", "source-a", "plan-a")
    balloon = repository.apply_command(
        "tricycle",
        "source-a",
        "plan-a",
        base_revision=initial["revision"],
        command={
            "operation": "translate",
            "targetType": "balloon",
            "targetId": "callout-item-9",
            "pageId": "page-section-front",
            "translation": [0.08, -0.04, 0.0],
            "actor": "user",
        },
        page_targets=targets,
    )
    anchored = repository.apply_command(
        "tricycle",
        "source-a",
        "plan-a",
        base_revision=balloon["revision"],
        command={
            "operation": "set_anchor",
            "targetType": "leader",
            "targetId": "callout-item-9",
            "pageId": "page-section-front",
            "anchorSide": "right",
            "actor": "user",
        },
        page_targets=targets,
    )
    routed = repository.apply_command(
        "tricycle",
        "source-a",
        "plan-a",
        base_revision=anchored["revision"],
        command={
            "operation": "translate",
            "targetType": "leader",
            "targetId": "callout-item-9",
            "pageId": "page-section-front",
            "translation": [0.05, 0.0, 0.0],
            "actor": "sage",
        },
        page_targets=targets,
    )
    page = routed["scene"]["pages"]["page-section-front"]
    assert page["balloonOverrides"]["callout-item-9"] == {
        "translation": [0.08, -0.04, 0.0]
    }
    assert page["leaderOverrides"]["callout-item-9"] == {
        "anchorSide": "right",
        "corridorTranslation": [0.05, 0.0, 0.0],
    }

    reset_leader = repository.apply_command(
        "tricycle",
        "source-a",
        "plan-a",
        base_revision=routed["revision"],
        command={
            "operation": "reset",
            "targetType": "leader",
            "targetId": "callout-item-9",
            "pageId": "page-section-front",
            "actor": "user",
        },
        page_targets=targets,
    )
    reset_page = reset_leader["scene"]["pages"]["page-section-front"]
    assert reset_page["leaderOverrides"] == {}
    assert "callout-item-9" in reset_page["balloonOverrides"]

    with pytest.raises(Exception, match="normalized two-dimensional"):
        repository.apply_command(
            "tricycle",
            "source-a",
            "plan-a",
            base_revision=reset_leader["revision"],
            command={
                "operation": "translate",
                "targetType": "balloon",
                "targetId": "callout-item-9",
                "pageId": "page-section-front",
                "translation": [0.0, 0.0, 0.1],
                "actor": "user",
            },
            page_targets=targets,
        )


def test_documentation_leader_route_and_visible_anchor_overrides_round_trip(
    tmp_path: Path,
) -> None:
    repository = DocumentationSceneRepository(tmp_path)
    targets = {
        "page-section-front": {
            "figure": ["page-section-front"],
            "manual_group": [],
            "occurrence": [],
            "balloon": ["callout-item-9"],
            "leader": ["callout-item-9"],
        }
    }
    current = repository.read("tricycle", "source-a", "plan-a")
    for command in (
        {
            "operation": "set_anchor",
            "anchorPoint": [0.42, 0.61],
        },
        {
            "operation": "set_leader_style",
            "leaderStyle": "orthogonal",
        },
        {
            "operation": "translate",
            "translation": [0.04, 0.0, 0.0],
        },
    ):
        current = repository.apply_command(
            "tricycle",
            "source-a",
            "plan-a",
            base_revision=current["revision"],
            command={
                **command,
                "targetType": "leader",
                "targetId": "callout-item-9",
                "pageId": "page-section-front",
                "actor": "user",
            },
            page_targets=targets,
        )
    override = current["scene"]["pages"]["page-section-front"]["leaderOverrides"][
        "callout-item-9"
    ]
    assert override == {
        "anchorPoint": [0.42, 0.61],
        "leaderStyle": "orthogonal",
        "corridorTranslation": [0.04, 0.0, 0.0],
    }

    automatic = repository.apply_command(
        "tricycle",
        "source-a",
        "plan-a",
        base_revision=current["revision"],
        command={
            "operation": "auto_route",
            "targetType": "leader",
            "targetId": "callout-item-9",
            "pageId": "page-section-front",
            "actor": "user",
        },
        page_targets=targets,
    )
    automatic_page = automatic["scene"]["pages"].get("page-section-front", {})
    assert "callout-item-9" not in automatic_page.get("leaderOverrides", {})


def test_manual_callout_authoring_drives_bom_quantity_numbering_and_publication_gate(
    tmp_path: Path,
) -> None:
    profile = _assembly_profile()
    catalog = build_occurrence_catalog("manual-fixture", profile)
    rows = catalog["occurrences"]
    plan_repository = PartsManualRepository(tmp_path / "plans")
    initial_plan = plan_repository.read(
        "manual-fixture",
        catalog["sourceRevision"],
        known_occurrence_ids=[row["occurrenceId"] for row in rows],
    )
    created = plan_repository.create_section(
        "manual-fixture",
        catalog["sourceRevision"],
        base_revision=initial_plan["revision"],
        name="Workholding Station",
        occurrence_ids=[row["occurrenceId"] for row in rows],
        catalog=rows,
    )
    section_id = created["section"]["sectionId"]
    page_id = f"page-{section_id}"
    scene_repository = DocumentationSceneRepository(tmp_path / "scenes")
    loaded_scene = scene_repository.read(
        "manual-fixture", catalog["sourceRevision"], created["revision"]
    )
    baseline = build_manual_document(
        created["plan"], rows, profile, plan_revision=created["revision"]
    )

    clear_command = server._parts_manual_prepare_callout_command(
        {
            "operation": "clear_callouts",
            "targetType": "figure",
            "targetId": page_id,
            "pageId": page_id,
            "actor": "user",
        },
        document=baseline,
        catalog_rows=rows,
    )
    cleared_scene = scene_repository.apply_command(
        "manual-fixture",
        catalog["sourceRevision"],
        created["revision"],
        base_revision=loaded_scene["revision"],
        command=clear_command,
        page_targets=server._parts_manual_editable_page_targets(baseline),
    )
    cleared = build_manual_document(
        created["plan"],
        rows,
        profile,
        plan_revision=created["revision"],
        documentation_scene=cleared_scene["scene"],
        documentation_scene_revision=cleared_scene["revision"],
    )
    cleared_page = next(page for page in cleared["pages"] if page.get("pageId") == page_id)
    assert cleared_page["bom"] == []
    assert cleared_page["renderRequest"]["calloutItems"] == []
    assert cleared["status"] == "draft_callouts"
    assert cleared["calloutAudit"]["status"] == "FAIL"

    workbench_ids = [
        row["occurrenceId"] for row in rows if row["partNumber"] == "WB-100"
    ]
    add_workbench = server._parts_manual_prepare_callout_command(
        {
            "operation": "add_callout",
            "targetType": "occurrence",
            "targetId": workbench_ids[0],
            "pageId": page_id,
            "actor": "user",
        },
        document=cleared,
        catalog_rows=rows,
    )
    assert add_workbench["calloutItems"][0]["itemNumber"] == 1
    assert add_workbench["calloutItems"][0]["quantity"] == 2
    assert sorted(add_workbench["calloutItems"][0]["occurrenceIds"]) == sorted(
        workbench_ids
    )
    assert add_workbench["calloutItems"][0]["anchorPreference"] == "bounding_box_center"
    # A newly authored callout inherits the generated default, not an arrowhead.
    assert (
        add_workbench["calloutItems"][0]["endCondition"]
        == PARTS_MANUAL_DEFAULT_END_CONDITION
        == "dot"
    )
    workbench_scene = scene_repository.apply_command(
        "manual-fixture",
        catalog["sourceRevision"],
        created["revision"],
        base_revision=cleared_scene["revision"],
        command=add_workbench,
        page_targets=server._parts_manual_editable_page_targets(cleared),
    )
    one_item = build_manual_document(
        created["plan"],
        rows,
        profile,
        plan_revision=created["revision"],
        documentation_scene=workbench_scene["scene"],
        documentation_scene_revision=workbench_scene["revision"],
    )
    one_item_page = next(page for page in one_item["pages"] if page.get("pageId") == page_id)
    assert [(row["item"], row["description"], row["quantity"]) for row in one_item_page["bom"]] == [
        (1, "Assembly Workbench", 2)
    ]

    fixture_id = next(row["occurrenceId"] for row in rows if row["partNumber"] == "FX-200")
    add_fixture = server._parts_manual_prepare_callout_command(
        {
            "operation": "add_callout",
            "targetType": "occurrence",
            "targetId": fixture_id,
            "pageId": page_id,
            "actor": "user",
        },
        document=one_item,
        catalog_rows=rows,
    )
    complete_scene = scene_repository.apply_command(
        "manual-fixture",
        catalog["sourceRevision"],
        created["revision"],
        base_revision=workbench_scene["revision"],
        command=add_fixture,
        page_targets=server._parts_manual_editable_page_targets(one_item),
    )
    complete = build_manual_document(
        created["plan"],
        rows,
        profile,
        plan_revision=created["revision"],
        documentation_scene=complete_scene["scene"],
        documentation_scene_revision=complete_scene["revision"],
    )
    complete_page = next(page for page in complete["pages"] if page.get("pageId") == page_id)
    assert [row["item"] for row in complete_page["bom"]] == [1, 2]
    assert add_fixture["calloutItems"][1]["itemNumber"] == 2
    assert complete["calloutAudit"]["status"] == "PASS"
    assert complete["status"] == "publication_ready"

    first_callout_id = complete_page["renderRequest"]["calloutItems"][0]["calloutId"]
    remove_first = server._parts_manual_prepare_callout_command(
        {
            "operation": "remove_callout",
            "targetType": "balloon",
            "targetId": first_callout_id,
            "pageId": page_id,
            "actor": "user",
        },
        document=complete,
        catalog_rows=rows,
    )
    assert len(remove_first["calloutItems"]) == 1
    assert remove_first["calloutItems"][0]["itemNumber"] == 1
    assert remove_first["calloutItems"][0]["description"] == "Locating Fixture"

    dotted_scene = scene_repository.apply_command(
        "manual-fixture",
        catalog["sourceRevision"],
        created["revision"],
        base_revision=complete_scene["revision"],
        command={
            "operation": "set_end_condition",
            "targetType": "leader",
            "targetId": first_callout_id,
            "pageId": page_id,
            "endCondition": "dot",
            "actor": "user",
        },
        page_targets=server._parts_manual_editable_page_targets(complete),
    )
    dotted = build_manual_document(
        created["plan"],
        rows,
        profile,
        plan_revision=created["revision"],
        documentation_scene=dotted_scene["scene"],
        documentation_scene_revision=dotted_scene["revision"],
    )
    dotted_page = next(page for page in dotted["pages"] if page.get("pageId") == page_id)
    assert dotted_page["renderRequest"]["composition"]["leaderOverrides"][first_callout_id] == {
        "endCondition": "dot"
    }

    undone = scene_repository.move_history(
        "manual-fixture",
        catalog["sourceRevision"],
        created["revision"],
        base_revision=dotted_scene["revision"],
        direction="undo",
    )
    assert first_callout_id not in undone["scene"]["pages"][page_id]["leaderOverrides"]


def test_manual_callout_composition_rehydrates_current_catalog_identity(
    tmp_path: Path,
) -> None:
    profile = _assembly_profile()
    catalog = build_occurrence_catalog("manual-fixture", profile)
    rows = catalog["occurrences"]
    repository = PartsManualRepository(tmp_path / "plans")
    initial = repository.read(
        "manual-fixture",
        catalog["sourceRevision"],
        known_occurrence_ids=[row["occurrenceId"] for row in rows],
    )
    created = repository.create_section(
        "manual-fixture",
        catalog["sourceRevision"],
        base_revision=initial["revision"],
        name="Workholding Station",
        occurrence_ids=[row["occurrenceId"] for row in rows],
        catalog=rows,
    )
    section_id = created["section"]["sectionId"]
    page_id = f"page-{section_id}"
    generated = build_scoped_bom(rows, created["section"]["occurrenceIds"])
    authored = []
    for item_number, current in enumerate(reversed(generated), start=1):
        authored.append(
            {
                **current,
                "item": item_number,
                "itemNumber": item_number,
                "calloutId": f"authored-callout-{item_number}",
                "partNumber": "SWPR-Stale CAD Filename",
                "engineeringPartNumber": None,
                "displayPartNumber": "Not specified",
                "partNumberSource": "cad_identity_fallback",
                "description": "Stale description",
                "descriptionSource": "cad_filename",
                "quantity": 99,
                "occurrenceIds": ["stale-occurrence"],
                "anchorPreference": "bounding_box_center",
                "endCondition": "dot",
            }
        )
    document = build_manual_document(
        created["plan"],
        rows,
        profile,
        plan_revision=created["revision"],
        documentation_scene={
            "pages": {page_id: {"manualCalloutItems": authored}},
        },
        documentation_scene_revision="scene-current",
    )
    page = next(row for row in document["pages"] if row.get("pageId") == page_id)

    assert [row["calloutId"] for row in page["bom"]] == [
        "authored-callout-1",
        "authored-callout-2",
    ]
    assert [row["item"] for row in page["bom"]] == [1, 2]
    assert [row["displayPartNumber"] for row in page["bom"]] == ["WB-100", "FX-200"]
    assert [row["description"] for row in page["bom"]] == [
        "Assembly Workbench",
        "Locating Fixture",
    ]
    assert [row["quantity"] for row in page["bom"]] == [2, 1]
    assert all("stale-occurrence" not in row["occurrenceIds"] for row in page["bom"])
    assert page["renderRequest"]["calloutItems"][0]["calloutId"] == "authored-callout-1"
    assert page["renderRequest"]["calloutItems"][0]["endCondition"] == "dot"
    assert page["renderRequest"]["image"]["allowAutomaticCameraSelection"] is False


def test_documentation_page_elements_share_normalized_offsets_with_pdf(
    tmp_path: Path,
) -> None:
    repository = DocumentationSceneRepository(tmp_path)
    targets = {
        "page-section-front": {
            "figure": ["page-section-front"],
            "manual_group": [],
            "occurrence": [],
            "balloon": [],
            "leader": [],
            "page_element": ["illustration", "bom"],
        }
    }
    initial = repository.read("tricycle", "source-a", "plan-a")
    moved = repository.apply_command(
        "tricycle",
        "source-a",
        "plan-a",
        base_revision=initial["revision"],
        command={
            "operation": "translate",
            "targetType": "page_element",
            "targetId": "bom",
            "pageId": "page-section-front",
            "translation": [0.025, -0.05, 0.0],
            "actor": "user",
        },
        page_targets=targets,
    )
    override = moved["scene"]["pages"]["page-section-front"]["pageElementOverrides"]["bom"]
    assert override == {"translation": [0.025, -0.05, 0.0]}

    layout = publication_layout()
    bom_rect = page_layout(
        "manual_section",
        layout_mode="small_bom",
        layout=layout,
    )["bom"]
    pdf = fitz.open()
    page = pdf.new_page(width=layout["page"]["width"], height=layout["page"]["height"])
    shifted = _page_element_rect(
        fitz,
        page,
        {
            "renderRequest": {
                "composition": {
                    "pageElementOverrides": {"bom": override},
                }
            }
        },
        bom_rect,
        "bom",
    )
    assert shifted.x0 == pytest.approx(bom_rect["x"] + 0.025 * 792)
    assert shifted.y0 == pytest.approx(bom_rect["y"] - 0.05 * 612)
    assert shifted.width == pytest.approx(bom_rect["width"])
    assert shifted.height == pytest.approx(bom_rect["height"])
    pdf.close()


def test_documentation_rotation_arrangement_and_resize_are_atomic_overrides(
    tmp_path: Path,
) -> None:
    repository = DocumentationSceneRepository(tmp_path)
    page_id = "page-section-front"
    targets = {
        page_id: {
            "figure": [page_id],
            "manual_group": [],
            "occurrence": ["pedal-left", "pedal-right", "wheel"],
            "balloon": [],
            "leader": [],
            "page_element": ["illustration", "bom"],
        }
    }
    initial = repository.read("tricycle", "source-a", "plan-a")
    rotated = repository.apply_command(
        "tricycle",
        "source-a",
        "plan-a",
        base_revision=initial["revision"],
        command={
            "operation": "rotate",
            "targetType": "occurrence",
            "targetId": "wheel",
            "pageId": page_id,
            "rotation": [0.0, 15.0, 0.0],
            "actor": "user",
        },
        page_targets=targets,
    )
    resized = repository.apply_command(
        "tricycle",
        "source-a",
        "plan-a",
        base_revision=rotated["revision"],
        command={
            "operation": "resize",
            "targetType": "page_element",
            "targetId": "bom",
            "pageId": page_id,
            "sizeDelta": [0.04, -0.02, 0.0],
            "actor": "user",
        },
        page_targets=targets,
    )
    arranged = repository.apply_command(
        "tricycle",
        "source-a",
        "plan-a",
        base_revision=resized["revision"],
        command={
            "operation": "arrange",
            "targetType": "selection",
            "targetId": "",
            "pageId": page_id,
            "arrangement": "align_top",
            "transforms": [
                {
                    "targetType": "occurrence",
                    "targetId": "pedal-left",
                    "translation": [0.0, 0.12, 0.0],
                },
                {
                    "targetType": "occurrence",
                    "targetId": "pedal-right",
                    "translation": [0.0, -0.08, 0.0],
                },
            ],
            "actor": "sage",
        },
        page_targets=targets,
    )
    page = arranged["scene"]["pages"][page_id]
    assert page["occurrenceOverrides"]["wheel"]["rotation"] == [0.0, 15.0, 0.0]
    assert page["pageElementOverrides"]["bom"]["sizeDelta"] == [0.04, -0.02, 0.0]
    assert page["occurrenceOverrides"]["pedal-left"]["translation"] == [0.0, 0.12, 0.0]
    assert page["occurrenceOverrides"]["pedal-right"]["translation"] == [0.0, -0.08, 0.0]
    assert arranged["scene"]["commands"][-1]["arrangement"] == "align_top"

    undone = repository.move_history(
        "tricycle",
        "source-a",
        "plan-a",
        base_revision=arranged["revision"],
        direction="undo",
    )
    undone_page = undone["scene"]["pages"][page_id]
    assert "pedal-left" not in undone_page["occurrenceOverrides"]
    assert "pedal-right" not in undone_page["occurrenceOverrides"]
    assert undone_page["occurrenceOverrides"]["wheel"]["rotation"] == [0.0, 15.0, 0.0]

    with pytest.raises(Exception, match="only CAD presentation targets"):
        repository.apply_command(
            "tricycle",
            "source-a",
            "plan-a",
            base_revision=undone["revision"],
            command={
                "operation": "rotate",
                "targetType": "page_element",
                "targetId": "bom",
                "pageId": page_id,
                "rotation": [0.0, 15.0, 0.0],
                "actor": "user",
            },
            page_targets=targets,
        )


def test_documentation_camera_and_page_reset_are_persistent_and_undoable(
    tmp_path: Path,
) -> None:
    repository = DocumentationSceneRepository(tmp_path)
    page_id = "page-section-front"
    targets = {
        page_id: {
            "figure": [page_id],
            "manual_group": [],
            "occurrence": ["wheel"],
            "balloon": [],
            "leader": [],
            "page_element": ["illustration", "bom"],
        }
    }
    initial = repository.read("tricycle", "source-a", "plan-a")
    moved = repository.apply_command(
        "tricycle",
        "source-a",
        "plan-a",
        base_revision=initial["revision"],
        command={
            "operation": "translate",
            "targetType": "occurrence",
            "targetId": "wheel",
            "pageId": page_id,
            "translation": [0.1, 0.0, 0.0],
            "actor": "user",
        },
        page_targets=targets,
    )
    viewed = repository.apply_command(
        "tricycle",
        "source-a",
        "plan-a",
        base_revision=moved["revision"],
        command={
            "operation": "set_view",
            "targetType": "figure",
            "targetId": page_id,
            "pageId": page_id,
            "cameraPreset": "front",
            "actor": "sage",
        },
        page_targets=targets,
    )
    assert viewed["scene"]["pages"][page_id]["figureOverride"] == {
        "cameraPreset": "front"
    }
    spaced = repository.apply_command(
        "tricycle",
        "source-a",
        "plan-a",
        base_revision=viewed["revision"],
        command={
            "operation": "adjust_explode",
            "targetType": "figure",
            "targetId": page_id,
            "pageId": page_id,
            "explodeDelta": 0.25,
            "actor": "user",
        },
        page_targets=targets,
    )
    assert spaced["scene"]["pages"][page_id]["figureOverride"] == {
        "cameraPreset": "front",
        "explodeScale": 1.25,
    }
    reset = repository.apply_command(
        "tricycle",
        "source-a",
        "plan-a",
        base_revision=spaced["revision"],
        command={
            "operation": "reset_page",
            "targetType": "figure",
            "targetId": page_id,
            "pageId": page_id,
            "actor": "user",
        },
        page_targets=targets,
    )
    assert page_id not in reset["scene"]["pages"]
    assert reset["scene"]["commands"][-1]["operation"] == "reset_page"

    undone = repository.move_history(
        "tricycle",
        "source-a",
        "plan-a",
        base_revision=reset["revision"],
        direction="undo",
    )
    page = undone["scene"]["pages"][page_id]
    assert page["figureOverride"] == {
        "cameraPreset": "front",
        "explodeScale": 1.25,
    }
    assert page["occurrenceOverrides"]["wheel"]["translation"] == [0.1, 0.0, 0.0]


def test_documentation_override_changes_render_revision_not_bom_semantics(
    tmp_path: Path,
) -> None:
    profile = _assembly_profile()
    catalog = build_occurrence_catalog("manual-fixture", profile)
    rows = catalog["occurrences"]
    manual_repository = PartsManualRepository(tmp_path)
    initial = manual_repository.read(
        "manual-fixture",
        catalog["sourceRevision"],
        known_occurrence_ids=[row["occurrenceId"] for row in rows],
    )
    created = manual_repository.create_section(
        "manual-fixture",
        catalog["sourceRevision"],
        base_revision=initial["revision"],
        name="Workholding Station",
        occurrence_ids=[row["occurrenceId"] for row in rows],
        catalog=rows,
    )
    baseline_scene = DocumentationSceneRepository(tmp_path).read(
        "manual-fixture",
        catalog["sourceRevision"],
        created["revision"],
    )
    baseline_document = build_manual_document(
        created["plan"],
        rows,
        profile,
        plan_revision=created["revision"],
        documentation_scene=baseline_scene["scene"],
        documentation_scene_revision=baseline_scene["revision"],
    )
    section_id = created["section"]["sectionId"]
    section_page_id = f"page-{section_id}"
    workbench_ids = [
        row["occurrenceId"] for row in rows if row["partNumber"] == "WB-100"
    ]
    moved = DocumentationSceneRepository(tmp_path).apply_command(
        "manual-fixture",
        catalog["sourceRevision"],
        created["revision"],
        base_revision=baseline_scene["revision"],
        command={
            "operation": "translate",
            "targetType": "occurrence",
            "targetId": workbench_ids[0],
            "pageId": section_page_id,
            "translation": [-0.2, 0.0, 0.0],
            "actor": "user",
        },
        page_targets={
            section_page_id: {
                "figure": [section_page_id],
                "manual_group": [],
                "occurrence": [row["occurrenceId"] for row in rows],
            }
        },
    )
    composed_document = build_manual_document(
        created["plan"],
        rows,
        profile,
        plan_revision=created["revision"],
        documentation_scene=moved["scene"],
        documentation_scene_revision=moved["revision"],
    )
    baseline_page = next(
        page for page in baseline_document["pages"] if page.get("sectionId") == section_id
    )
    composed_page = next(
        page for page in composed_document["pages"] if page.get("sectionId") == section_id
    )
    assert composed_document["documentRevision"] != baseline_document["documentRevision"]
    assert composed_page["renderRequest"]["composition"]["occurrenceOverrides"][workbench_ids[0]] == {
        "translation": [-0.2, 0.0, 0.0]
    }
    assert baseline_page["bom"] == composed_page["bom"]
    assert next(row for row in composed_page["bom"] if row["partNumber"] == "WB-100")["quantity"] == 2


def test_occurrence_catalog_separates_occurrences_from_part_definitions() -> None:
    catalog = build_occurrence_catalog("manual-fixture", _assembly_profile())
    rows = catalog["occurrences"]

    assert len(rows) == 3
    assert len({row["occurrenceId"] for row in rows}) == 3
    workbenches = [row for row in rows if row["partNumber"] == "WB-100"]
    assert len(workbenches) == 2
    assert workbenches[0]["definitionId"] == workbenches[1]["definitionId"]
    assert workbenches[0]["occurrenceId"] != workbenches[1]["occurrenceId"]
    assert workbenches[0]["referencedFileName"] == "workbench.SLDPRT"
    assert len(catalog["sourceRevision"]) == 64


def test_scoped_bom_aggregates_definitions_and_preserves_occurrence_refs() -> None:
    catalog = build_occurrence_catalog("manual-fixture", _assembly_profile())
    ids = [row["occurrenceId"] for row in catalog["occurrences"]]

    bom = build_scoped_bom(catalog["occurrences"], ids)

    assert [row["partNumber"] for row in bom] == ["FX-200", "WB-100"]
    workbench = next(row for row in bom if row["partNumber"] == "WB-100")
    assert workbench["quantity"] == 2
    assert len(workbench["occurrenceIds"]) == 2


def test_manual_document_compiles_stable_page_scopes_and_bom_items(tmp_path: Path) -> None:
    profile = _assembly_profile()
    catalog = build_occurrence_catalog("manual-fixture", profile)
    rows = catalog["occurrences"]
    repository = PartsManualRepository(tmp_path)
    initial = repository.read(
        "manual-fixture",
        catalog["sourceRevision"],
        known_occurrence_ids=[row["occurrenceId"] for row in rows],
    )
    created = repository.create_section(
        "manual-fixture",
        catalog["sourceRevision"],
        base_revision=initial["revision"],
        name="Workholding Station",
        occurrence_ids=[row["occurrenceId"] for row in rows],
        catalog=rows,
    )

    document = build_manual_document(
        created["plan"],
        rows,
        profile,
        plan_revision=created["revision"],
    )

    assert document["pageCount"] == 6
    assert [page["pageType"] for page in document["pages"]] == [
        "cover",
        "document_information",
        "table_of_contents",
        "assembly_overview",
        "manual_section",
        "parts_index",
    ]
    assert document["status"] == "publication_ready"
    assert document["publicationAudit"]["status"] == "PASS"
    cover_image_contract = document["pages"][0]["renderRequest"]["image"]
    assert cover_image_contract["targetForegroundOccupancy"] == 0.48
    assert cover_image_contract["minimumForegroundOccupancy"] == 0.38
    section_page = document["pages"][4]
    assert section_page["occurrenceIds"] == [row["occurrenceId"] for row in rows]
    assert section_page["renderRequest"]["pose"] == "exploded"
    assert section_page["renderRequest"]["image"]["minimumWidthPx"] == 2400
    assert document["publicationLayout"]["page"] == {"width": 792.0, "height": 612.0}
    cover_layout = document["publicationLayout"]["pageTypes"]["cover"]
    assert cover_layout["coverStyleVersion"] == 2
    assert cover_layout["illustrationFramed"] is False
    assert cover_layout["topAccent"] == {
        "x": 10.0, "y": 4.0, "width": 772.0, "height": 13.0,
    }
    assert cover_layout["leftAccent"]["height"] == 523.0
    assert cover_layout["bottomBand"] == {
        "x": 10.0, "y": 545.0, "width": 772.0, "height": 55.0,
    }
    assert cover_layout["illustration"]["y"] + cover_layout["illustration"]["height"] \
        < cover_layout["bottomBand"]["y"]
    section_rect = document["publicationLayout"]["pageTypes"]["manual_section"][
        "small_bom"
    ]["illustration"]
    assert section_page["renderRequest"]["image"]["publicationRect"] == section_rect
    assert section_page["renderRequest"]["image"]["targetAspectRatio"] == pytest.approx(
        (section_rect["width"] - 8) / (section_rect["height"] - 8)
    )
    assert section_page["renderRequest"]["image"]["background"] == "technical_white"
    assert section_page["renderRequest"]["image"]["minimumForegroundOccupancy"] == 0.60
    assert section_page["renderRequest"]["image"]["axisConstrainedOccupancyPolicy"] == (
        "allow_when_uniform_scale_exceeds_axis_limit"
    )
    assert section_page["renderRequest"]["image"]["axisConstrainedFillTolerance"] == 0.02
    assert section_page["renderRequest"]["illustrationStyle"] == "HIDDEN_LINES_REMOVED"
    assert section_page["renderRequest"]["image"]["illustrationStyle"] == "HIDDEN_LINES_REMOVED"
    overview_page = document["pages"][3]
    assert all(
        row["anchorScope"] == "manual_group"
        for row in overview_page["renderRequest"]["calloutItems"]
    )
    assert section_page["figureNumber"] == "2-1"
    workbench = next(row for row in section_page["bom"] if row["partNumber"] == "WB-100")
    assert workbench["quantity"] == 2
    assert [row["item"] for row in section_page["bom"]] == [1, 2]
    repeated = build_manual_document(
        created["plan"],
        rows,
        profile,
        plan_revision=created["revision"],
    )
    assert document["documentType"] == "illustrated_parts_manual"
    assert repeated["documentRevision"] == document["documentRevision"]

    profile_with_internal_revision = _assembly_profile()
    profile_with_internal_revision["identity"]["revision"] = catalog["sourceRevision"]
    hidden_internal_revision = build_manual_document(
        created["plan"],
        rows,
        profile_with_internal_revision,
        plan_revision=created["revision"],
    )
    assert hidden_internal_revision["revision"] == "A"
    assert hidden_internal_revision["pages"][0]["documentControl"]["revision"] == "A"


def test_manual_document_paginates_long_section_boms() -> None:
    occurrences = [
        {
            "occurrenceId": f"occ-{index:024x}",
            "definitionId": f"item-{index:024x}",
            "kind": "part",
            "suppressed": False,
            "partNumber": f"PN-{index:03d}",
            "description": f"Part {index:03d}",
            "configuration": "Default",
        }
        for index in range(21)
    ]
    section_id = "section-12345678"
    plan = {
        "assemblyNumber": "manual-fixture",
        "sourceRevision": "a" * 64,
        "title": "Fixture Manual",
        "sections": [
            {
                "sectionId": section_id,
                "name": "Large Group",
                "parentSectionId": None,
                "occurrenceIds": [row["occurrenceId"] for row in occurrences],
                "source": "manual",
                "confidence": None,
                "evidence": [],
                "includeInManual": True,
                "pageOrder": 1,
                "itemAssignments": [
                    {"definitionId": row["definitionId"], "itemNumber": index + 1}
                    for index, row in enumerate(occurrences)
                ],
            }
        ],
    }
    document = build_manual_document(
        plan,
        occurrences,
        _assembly_profile(),
        plan_revision="b" * 64,
    )

    assert document["pageCount"] == 7
    assert document["pages"][4]["pageType"] == "manual_section"
    assert len(document["pages"][4]["bom"]) == 20
    assert document["pages"][5]["pageType"] == "manual_section_parts_list"
    assert len(document["pages"][5]["bom"]) == 1
    assert document["pages"][2]["entries"][1]["pageNumber"] == 5


def test_repository_persists_sections_and_stable_item_assignments(tmp_path: Path) -> None:
    catalog = build_occurrence_catalog("manual-fixture", _assembly_profile())
    rows = catalog["occurrences"]
    repository = PartsManualRepository(tmp_path)
    initial = repository.read(
        "manual-fixture",
        catalog["sourceRevision"],
        known_occurrence_ids=[row["occurrenceId"] for row in rows],
    )

    created = repository.create_section(
        "manual-fixture",
        catalog["sourceRevision"],
        base_revision=initial["revision"],
        name="Workholding Station",
        occurrence_ids=[row["occurrenceId"] for row in rows],
        catalog=rows,
    )
    section = created["section"]
    assert section["visualization"] == {
        "explodeStrategy": "radial",
        "explodeFactor": 1.0,
        "cameraPreset": "isometric",
        "showItemCallouts": True,
    }
    original_assignments = {
        row["definitionId"]: row["itemNumber"]
        for row in section["itemAssignments"]
    }
    fixture_id = next(row["occurrenceId"] for row in rows if row["partNumber"] == "FX-200")
    one_workbench_id = next(row["occurrenceId"] for row in rows if row["partNumber"] == "WB-100")
    updated = repository.update_section(
        "manual-fixture",
        section["sectionId"],
        catalog["sourceRevision"],
        base_revision=created["revision"],
        catalog=rows,
        patch={"occurrenceIds": [fixture_id, one_workbench_id]},
    )

    assert {
        row["definitionId"]: row["itemNumber"]
        for row in updated["section"]["itemAssignments"]
    } == original_assignments
    reloaded = repository.read(
        "manual-fixture",
        catalog["sourceRevision"],
        known_occurrence_ids=[row["occurrenceId"] for row in rows],
    )
    assert reloaded["persisted"] is True
    assert reloaded["plan"]["sections"][0]["name"] == "Workholding Station"

    visualized = repository.update_section(
        "manual-fixture",
        section["sectionId"],
        catalog["sourceRevision"],
        base_revision=updated["revision"],
        catalog=rows,
        patch={
            "visualization": {
                "explodeStrategy": "radial",
                "explodeFactor": 1.4,
                "cameraPreset": "front",
                "showItemCallouts": False,
            }
        },
    )
    assert visualized["section"]["visualization"]["explodeFactor"] == 1.4

    with pytest.raises(PartsManualConflictError):
        repository.create_section(
            "manual-fixture",
            catalog["sourceRevision"],
            base_revision=initial["revision"],
            name="Stale Write",
            occurrence_ids=[fixture_id],
            catalog=rows,
        )


def test_repository_rejects_sibling_occurrence_overlap(tmp_path: Path) -> None:
    catalog = build_occurrence_catalog("manual-fixture", _assembly_profile())
    rows = catalog["occurrences"]
    repository = PartsManualRepository(tmp_path)
    initial = repository.read(
        "manual-fixture",
        catalog["sourceRevision"],
        known_occurrence_ids=[row["occurrenceId"] for row in rows],
    )
    occurrence_id = rows[0]["occurrenceId"]
    first = repository.create_section(
        "manual-fixture",
        catalog["sourceRevision"],
        base_revision=initial["revision"],
        name="First",
        occurrence_ids=[occurrence_id],
        catalog=rows,
    )

    with pytest.raises(PartsManualValidationError):
        repository.create_section(
            "manual-fixture",
            catalog["sourceRevision"],
            base_revision=first["revision"],
            name="Second",
            occurrence_ids=[occurrence_id],
            catalog=rows,
        )


def test_manual_planner_uses_process_branch_evidence_and_flags_authored_overlap(
    tmp_path: Path,
) -> None:
    catalog = build_occurrence_catalog("manual-fixture", _assembly_profile())
    rows = catalog["occurrences"]
    repository = PartsManualRepository(tmp_path)
    initial = repository.read(
        "manual-fixture",
        catalog["sourceRevision"],
        known_occurrence_ids=[row["occurrenceId"] for row in rows],
    )
    process_evidence = _process_evidence_for_rows(rows)

    proposal = compile_manual_structure_proposal(
        catalog=catalog,
        plan=initial["plan"],
        plan_revision=initial["revision"],
        process_evidence=process_evidence,
    )

    assert proposal["strategy"] == "process_map"
    assert proposal["summary"]["readyCount"] == 1
    candidate = proposal["candidates"][0]
    assert candidate["name"] == "Workbench Station Assembly"
    assert candidate["source"] == "process_map"
    assert candidate["status"] == "ready"
    assert len(candidate["occurrenceIds"]) == 2
    assert candidate["evidence"][0]["sourceType"] == "process_map"

    authored = repository.create_section(
        "manual-fixture",
        catalog["sourceRevision"],
        base_revision=initial["revision"],
        name="Authored Workbench",
        occurrence_ids=[candidate["occurrenceIds"][0]],
        catalog=rows,
    )
    conflicted = compile_manual_structure_proposal(
        catalog=catalog,
        plan=authored["plan"],
        plan_revision=authored["revision"],
        process_evidence=process_evidence,
    )
    process_candidate = next(
        row for row in conflicted["candidates"] if row["source"] == "process_map"
    )
    assert process_candidate["status"] == "conflict"
    assert process_candidate["conflicts"][0]["name"] == "Authored Workbench"


def test_manual_proposal_http_approval_is_revision_bound_and_atomic(
    tmp_path: Path,
    monkeypatch,
) -> None:
    profile = _assembly_profile()
    catalog = build_occurrence_catalog("manual-fixture", profile)
    process_evidence = _process_evidence_for_rows(catalog["occurrences"])
    monkeypatch.setattr(server, "assembly_profiles", {"manual-fixture": profile})
    monkeypatch.setattr(server, "assembly_part_lookup", {})
    monkeypatch.setattr(server, "PARTS_MANUAL_ROOT", tmp_path)
    monkeypatch.setattr(
        server,
        "_parts_manual_process_map_evidence",
        lambda _assembly_number: process_evidence,
    )
    client = TestClient(server.app)

    initial = client.get("/api/parts-manual/manual-fixture").json()
    proposal_response = client.get(
        "/api/parts-manual/manual-fixture/proposal"
    )
    assert proposal_response.status_code == 200, proposal_response.text
    proposal = proposal_response.json()["proposal"]
    ready = [row for row in proposal["candidates"] if row["status"] == "ready"]
    assert len(ready) == 1

    approval = client.post(
        "/api/parts-manual/manual-fixture/proposals/"
        f"{proposal['proposalRevision']}/approve",
        json={
            "baseRevision": initial["revision"],
            "sourceRevision": initial["sourceRevision"],
            "candidateIds": [ready[0]["candidateId"]],
        },
    )
    assert approval.status_code == 200, approval.text
    approved = approval.json()
    assert len(approved["sections"]) == 1
    assert approved["sections"][0]["source"] == "process_map"
    assert approved["sections"][0]["occurrenceIds"] == ready[0]["occurrenceIds"]
    assert (tmp_path / "manual-fixture" / "manual-plan.json").is_file()

    replay = client.post(
        "/api/parts-manual/manual-fixture/proposals/"
        f"{proposal['proposalRevision']}/approve",
        json={
            "baseRevision": initial["revision"],
            "sourceRevision": initial["sourceRevision"],
            "candidateIds": [ready[0]["candidateId"]],
        },
    )
    assert replay.status_code == 409


def test_sage_parts_manual_tool_is_narrow_and_read_only() -> None:
    for agent in ("inspector", "deviation-analyst"):
        spec = next(
            value
            for value in server.AGENT_TOOL_SPECS[agent]
            if value["name"] == "propose_parts_manual_structure"
        )
        assert "read-only" in spec["description"]
        assert "never approves" in spec["description"]
        assert spec["input_schema"]["additionalProperties"] is False
    assert "propose_parts_manual_structure" not in server.get_allowed_tool_names(
        "parts-finder"
    )
    calls, warnings, added = server.ensure_parts_manual_proposal_tool_call(
        [],
        "Suggest an illustrated parts manual structure for this assembly.",
        "deviation-analyst",
    )
    assert added is True
    assert calls == [{"name": "propose_parts_manual_structure", "args": {}}]
    assert warnings == ["parts_manual_proposal_backstop_added"]

    gated, gated_warnings, _ = server.ensure_parts_manual_proposal_tool_call(
        [
            {"name": "highlight_parts", "args": {"part_numbers": ["WB-100"]}},
            {"name": "propose_parts_manual_structure", "args": {}},
        ],
        "Build a parts manual structure for this assembly.",
        "deviation-analyst",
    )
    assert gated == [{"name": "propose_parts_manual_structure", "args": {}}]
    assert gated_warnings == ["parts_manual_proposal_dropped_unrelated_tools"]

    informational, _, informational_added = (
        server.ensure_parts_manual_proposal_tool_call(
            [],
            "What is an illustrated parts manual?",
            "deviation-analyst",
        )
    )
    assert informational == []
    assert informational_added is False


def test_sage_parts_manual_publication_requires_explicit_end_to_end_authority() -> None:
    for agent in ("inspector", "deviation-analyst"):
        spec = next(
            value
            for value in server.AGENT_TOOL_SPECS[agent]
            if value["name"] == "generate_and_publish_parts_manual"
        )
        assert "explicitly requests PDF publication" in spec["description"]
        assert "never changes source CAD geometry" in spec["description"]
        schema = spec["input_schema"]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == {
            "approval_mode",
            "layout_mode",
            "open_pdf",
        }
    assert "generate_and_publish_parts_manual" not in server.get_allowed_tool_names(
        "parts-finder"
    )

    prompt = (
        "Generate the complete illustrated parts manual, publish it, "
        "and show me the PDF."
    )
    calls, warnings, added = server.ensure_parts_manual_publication_tool_call(
        [], prompt, "deviation-analyst"
    )
    assert added is True
    assert warnings == ["parts_manual_publication_backstop_added"]
    assert calls == [{
        "name": "generate_and_publish_parts_manual",
        "args": {
            "approval_mode": "approve_trusted_ready_candidates",
            "layout_mode": "generate_baseline_if_missing",
            "open_pdf": True,
        },
    }]

    publish_current, _, _ = server.ensure_parts_manual_publication_tool_call(
        [],
        "Publish the current approved parts manual as-is, but do not open the PDF.",
        "deviation-analyst",
    )
    assert publish_current[0]["args"] == {
        "approval_mode": "use_approved_structure",
        "layout_mode": "preserve_current",
        "open_pdf": False,
    }

    plain_generation, warnings, added = (
        server.ensure_parts_manual_publication_tool_call(
            [],
            "Generate a parts manual structure for this assembly.",
            "deviation-analyst",
        )
    )
    assert plain_generation == []
    assert warnings == []
    assert added is False


def test_sage_parts_manual_generation_opens_review_workflow_without_publishing() -> None:
    calls, warnings, added = server.ensure_parts_manual_generation_tool_call(
        [],
        "Generate a parts manual for this assembly.",
        "deviation-analyst",
    )
    assert calls == [{"name": "generate_parts_manual_draft", "args": {}}]
    assert warnings == ["parts_manual_generation_backstop_added"]
    assert added is True

    source = (
        Path(__file__).resolve().parents[1] / "static" / "index.html"
    ).read_text(encoding="utf-8")
    assert "function _partsManualSemanticToolStatusLine" in source
    assert "**Your illustrated Parts Manual has been published.**" in source
    assert "[Published PDF]" in source
    assert server._safe_parts_manual_route(
        "Generate a parts manual for this assembly."
    )["intents"][0]["kind"] == "generate_parts_manual"

    proposal, _, _ = server.ensure_parts_manual_proposal_tool_call(
        [],
        "Suggest a parts manual structure for this assembly.",
        "deviation-analyst",
    )
    assert proposal == [{"name": "propose_parts_manual_structure", "args": {}}]

    no_proposal, _, _ = server.ensure_parts_manual_proposal_tool_call(
        [],
        "Generate a parts manual for this assembly.",
        "deviation-analyst",
    )
    assert no_proposal == []

    blocked, warnings, added = server.ensure_parts_manual_publication_tool_call(
        [{
            "name": "generate_and_publish_parts_manual",
            "args": {
                "approval_mode": "approve_trusted_ready_candidates",
                "layout_mode": "generate_baseline_if_missing",
                "open_pdf": True,
            },
        }],
        "What does publishing a parts manual do?",
        "deviation-analyst",
    )
    assert blocked == []
    assert warnings == [
        "parts_manual_publication_dropped_without_explicit_request"
    ]
    assert added is False


def test_documentation_skill_prompt_exposes_the_four_workflow_tools() -> None:
    route = server._safe_parts_manual_route(
        "Generate the complete illustrated parts manual, publish it, and show the PDF."
    )
    plan, reason = server._compose_production_skill_prompt(
        route,
        mode="training",
    )
    assert reason == ""
    assert plan is not None
    assert plan["workflow"]["id"] == "documentation-publication"
    assert plan["selection"][0]["id"] == "publish-parts-manual"
    assert set(plan["allowed_tools"]) == {
        "propose_parts_manual_structure",
        "generate_parts_manual_draft",
        "edit_parts_manual_composition",
        "generate_and_publish_parts_manual",
    }
    assert "Only `ok=true`, `stage=published`" in plan["prompt"]

    filtered, warnings = server.apply_compiled_skill_tool_policy(
        [
            {"name": "highlight_parts", "args": {"part_numbers": ["P1"]}},
            {
                "name": "generate_and_publish_parts_manual",
                "args": {
                    "approval_mode": "approve_trusted_ready_candidates",
                    "layout_mode": "generate_baseline_if_missing",
                    "open_pdf": True,
                },
            },
        ],
        plan,
    )
    assert filtered == [{
        "name": "generate_and_publish_parts_manual",
        "args": {
            "approval_mode": "approve_trusted_ready_candidates",
            "layout_mode": "generate_baseline_if_missing",
            "open_pdf": True,
        },
    }]
    assert warnings == ["skill_policy_dropped:highlight_parts"]


def test_sage_documentation_tool_uses_explicit_presentation_only_contract() -> None:
    for agent in ("inspector", "deviation-analyst"):
        spec = next(
            value
            for value in server.AGENT_TOOL_SPECS[agent]
            if value["name"] == "edit_parts_manual_composition"
        )
        assert "explicitly asks" in spec["description"]
        assert "documentation overrides only" in spec["description"]
        assert "never changes CAD geometry" in spec["description"]
        assert spec["input_schema"]["additionalProperties"] is False
        assert set(spec["input_schema"]["properties"]["operation"]["enum"]) == {
            "translate",
            "rotate",
            "align",
            "distribute",
            "resize",
            "adjust_explode",
                "set_view",
                "set_anchor",
                "set_leader_style",
                "auto_route",
                "set_end_condition",
                "set_repeated_strategy",
                "clear_callouts",
                "add_callout",
                "remove_callout",
                "restore_callouts",
                "reset",
            "reset_page",
            "undo",
            "redo",
        }
        assert {"balloon", "leader", "page_element"}.issubset(
            set(spec["input_schema"]["properties"]["target_type"]["enum"])
        )
        assert set(spec["input_schema"]["properties"]["anchor_side"]["enum"]) == {
            "center",
            "left",
            "right",
            "top",
            "bottom",
        }
    assert "edit_parts_manual_composition" not in server.get_allowed_tool_names(
        "parts-finder"
    )
    candidate = [{
        "name": "edit_parts_manual_composition",
        "args": {
            "operation": "translate",
            "page": "Figure 1-1",
            "target_type": "manual_group",
            "target": "Frame and Seat Assembly",
            "direction": "down",
        },
    }]
    allowed, warnings = server.enforce_parts_manual_documentation_action_gate(
        candidate,
        "Move Frame and Seat Assembly down on Figure 1-1 in the parts manual.",
        "deviation-analyst",
    )
    assert allowed == candidate
    assert warnings == []
    arrangement_call = [{
        "name": "edit_parts_manual_composition",
        "args": {
            "operation": "align",
            "page": "Figure 2-1",
            "target_type": "occurrence",
            "targets": ["Pedal 1", "Pedal 2"],
            "alignment": "middle",
        },
    }]
    allowed_arrangement, warnings = server.enforce_parts_manual_documentation_action_gate(
        arrangement_call,
        "Align both pedals through the middle on Figure 2-1 in the parts manual.",
        "deviation-analyst",
    )
    assert allowed_arrangement == arrangement_call
    assert warnings == []
    leader_call = [{
        "name": "edit_parts_manual_composition",
        "args": {
            "operation": "set_anchor",
            "page": "Figure 2-1",
            "target_type": "leader",
            "target": "Item 9 leader",
            "anchor_side": "right",
        },
    }]
    allowed_leader, warnings = server.enforce_parts_manual_documentation_action_gate(
        leader_call,
        "Snap the item 9 leader anchor right on Figure 2-1 in the parts manual.",
        "deviation-analyst",
    )
    assert allowed_leader == leader_call
    assert warnings == []
    blocked, warnings = server.enforce_parts_manual_documentation_action_gate(
        candidate,
        "Analyze the current assembly without changing anything.",
        "deviation-analyst",
    )
    assert blocked == []
    assert warnings == [
        "parts_manual_documentation_edit_dropped_without_explicit_request"
    ]
    for generic_message in (
        "Show Figure 1-1 in the parts manual.",
        "Use Figure 1-1 in the parts manual.",
        "Set the parts manual for this assembly.",
        "Make a parts manual for this assembly.",
    ):
        generic_blocked, warnings = server.enforce_parts_manual_documentation_action_gate(
            candidate,
            generic_message,
            "deviation-analyst",
        )
        assert generic_blocked == []
        assert warnings == [
            "parts_manual_documentation_edit_dropped_without_explicit_request"
        ]

    view_call = [{
        "name": "edit_parts_manual_composition",
        "args": {
            "operation": "set_view",
            "page": "Figure 2-1",
            "target_type": "figure",
            "camera_preset": "front",
        },
    }]
    allowed_view, warnings = server.enforce_parts_manual_documentation_action_gate(
        view_call,
        "Set Figure 2-1 to the front view in the parts manual.",
        "deviation-analyst",
    )
    assert allowed_view == view_call
    assert warnings == []
    interrogative = [{
        "name": "edit_parts_manual_composition",
        "args": {
            "operation": "translate",
            "page": "Figure 2-1",
            "target_type": "occurrence",
            "target": "Pedal 1",
            "direction": "left",
        },
    }]
    blocked_interrogative, warnings = server.enforce_parts_manual_documentation_action_gate(
        interrogative,
        "In the parts manual, what is on the left of the wheel?",
        "deviation-analyst",
    )
    assert blocked_interrogative == []
    assert warnings == [
        "parts_manual_documentation_edit_dropped_without_explicit_request"
    ]


def test_repository_normalizes_legacy_and_partial_visualization_settings(tmp_path: Path) -> None:
    catalog = build_occurrence_catalog("manual-fixture", _assembly_profile())
    rows = catalog["occurrences"]
    repository = PartsManualRepository(tmp_path)
    initial = repository.read(
        "manual-fixture",
        catalog["sourceRevision"],
        known_occurrence_ids=[row["occurrenceId"] for row in rows],
    )
    created = repository.create_section(
        "manual-fixture",
        catalog["sourceRevision"],
        base_revision=initial["revision"],
        name="Legacy Section",
        occurrence_ids=[rows[0]["occurrenceId"]],
        catalog=rows,
    )
    plan_path = tmp_path / "manual-fixture" / "manual-plan.json"
    legacy_plan = json.loads(plan_path.read_text("ascii"))
    legacy_plan["sections"][0].pop("visualization")
    plan_path.write_text(json.dumps(legacy_plan), encoding="ascii")

    normalized = repository.read(
        "manual-fixture",
        catalog["sourceRevision"],
        known_occurrence_ids=[row["occurrenceId"] for row in rows],
    )
    assert normalized["plan"]["sections"][0]["visualization"] == {
        "explodeStrategy": "radial",
        "explodeFactor": 1.0,
        "cameraPreset": "isometric",
        "showItemCallouts": True,
    }

    updated = repository.update_section(
        "manual-fixture",
        created["section"]["sectionId"],
        catalog["sourceRevision"],
        base_revision=normalized["revision"],
        catalog=rows,
        patch={"visualization": {"explodeFactor": 1.75}},
    )
    assert updated["section"]["visualization"] == {
        "explodeStrategy": "radial",
        "explodeFactor": 1.75,
        "cameraPreset": "isometric",
        "showItemCallouts": True,
    }


def test_publication_gate_blocks_internal_names_and_incomplete_coverage(tmp_path: Path) -> None:
    profile = _assembly_profile()
    catalog = build_occurrence_catalog("manual-fixture", profile)
    rows = catalog["occurrences"]
    repository = PartsManualRepository(tmp_path)
    initial = repository.read(
        "manual-fixture",
        catalog["sourceRevision"],
        known_occurrence_ids=[row["occurrenceId"] for row in rows],
    )
    created = repository.create_section(
        "manual-fixture",
        catalog["sourceRevision"],
        base_revision=initial["revision"],
        name="__Parts Manual Smoke",
        occurrence_ids=[row["occurrenceId"] for row in rows[:2]],
        catalog=rows,
    )

    audit = audit_manual_plan(created["plan"], rows)
    assert audit["status"] == "FAIL"
    assert audit["coveragePercent"] < 100
    assert {
        finding["code"] for finding in audit["findings"]
    } >= {
        "manual_publication_section_name",
        "manual_publication_incomplete_coverage",
    }
    with pytest.raises(PartsManualValidationError) as caught:
        build_manual_document(
            created["plan"],
            rows,
            profile,
            plan_revision=created["revision"],
        )
    assert {
        finding["code"] for finding in caught.value.findings
    } >= {
        "manual_publication_section_name",
        "manual_publication_incomplete_coverage",
    }


def test_parts_manual_http_vertical_slice(tmp_path: Path, monkeypatch) -> None:
    profile = _assembly_profile()
    monkeypatch.setattr(server, "assembly_profiles", {"manual-fixture": profile})
    monkeypatch.setattr(server, "assembly_part_lookup", {})
    monkeypatch.setattr(server, "PARTS_MANUAL_ROOT", tmp_path)
    client = TestClient(server.app)

    context = client.get("/api/assembly-context/manual-fixture")
    assert context.status_code == 200
    assert len(context.json()["assembly_source_revision"]) == 64
    assert all(row.get("occurrenceId") for row in context.json()["components"])

    initial_response = client.get("/api/parts-manual/manual-fixture")
    assert initial_response.status_code == 200
    initial = initial_response.json()
    assert initial["plan"]["sections"] == []
    selected_ids = [row["occurrenceId"] for row in initial["occurrences"]]

    created_response = client.post(
        "/api/parts-manual/manual-fixture/sections",
        json={
            "baseRevision": initial["revision"],
            "sourceRevision": initial["sourceRevision"],
            "name": "Workholding Station",
            "occurrenceIds": selected_ids,
        },
    )
    assert created_response.status_code == 200, created_response.text
    created = created_response.json()
    section_id = created["section"]["sectionId"]

    bom_response = client.get(
        f"/api/parts-manual/manual-fixture/sections/{section_id}/bom"
    )
    assert bom_response.status_code == 200, bom_response.text
    bom = bom_response.json()
    assert bom["occurrenceCount"] == 3
    assert bom["uniqueItemCount"] == 2
    assert next(row for row in bom["bom"] if row["partNumber"] == "WB-100")["quantity"] == 2

    document_response = client.get("/api/parts-manual/manual-fixture/document")
    assert document_response.status_code == 200, document_response.text
    document = document_response.json()["document"]
    assert document["pageCount"] == 6
    assert document["renderPipelineVersion"] == PARTS_MANUAL_RENDER_PIPELINE_VERSION
    section_page = next(page for page in document["pages"] if page.get("sectionId") == section_id)
    assert section_page["pageNumber"] == 5

    scene_response = client.get(
        "/api/parts-manual/manual-fixture/documentation-scene"
    )
    assert scene_response.status_code == 200, scene_response.text
    scene_payload = scene_response.json()
    assert scene_payload["scene"]["pages"] == {}
    moved_occurrence_id = selected_ids[0]
    command_response = client.post(
        "/api/parts-manual/manual-fixture/documentation-scene/commands",
        json={
            "baseRevision": scene_payload["revision"],
            "sourceRevision": initial["sourceRevision"],
            "manualPlanRevision": created["revision"],
            "operation": "translate",
            "pageId": f"page-{section_id}",
            "targetType": "occurrence",
            "targetId": moved_occurrence_id,
            "translation": [-0.2, 0.0, 0.0],
            "actor": "user",
        },
    )
    assert command_response.status_code == 200, command_response.text
    composed = command_response.json()
    assert composed["canUndo"]
    assert composed["document"]["documentRevision"] != document["documentRevision"]
    section_page = next(
        page
        for page in composed["document"]["pages"]
        if page.get("sectionId") == section_id
    )
    assert section_page["renderRequest"]["composition"]["occurrenceOverrides"][moved_occurrence_id] == {
        "translation": [-0.2, 0.0, 0.0]
    }
    assert next(row for row in section_page["bom"] if row["partNumber"] == "WB-100")["quantity"] == 2

    undo_response = client.post(
        "/api/parts-manual/manual-fixture/documentation-scene/undo",
        json={
            "baseRevision": composed["revision"],
            "sourceRevision": initial["sourceRevision"],
            "manualPlanRevision": created["revision"],
        },
    )
    assert undo_response.status_code == 200, undo_response.text
    undone = undo_response.json()
    assert undone["canRedo"]
    redo_response = client.post(
        "/api/parts-manual/manual-fixture/documentation-scene/redo",
        json={
            "baseRevision": undone["revision"],
            "sourceRevision": initial["sourceRevision"],
            "manualPlanRevision": created["revision"],
        },
    )
    assert redo_response.status_code == 200, redo_response.text
    document = redo_response.json()["document"]
    section_page = next(
        page for page in document["pages"] if page.get("sectionId") == section_id
    )

    stale_renderer_response = client.post(
        f"/api/parts-manual/manual-fixture/document/page-{section_id}/render",
        data={
            "documentRevision": document["documentRevision"],
            "manualPlanRevision": document["manualPlanRevision"],
            "sourceRevision": document["sourceRevision"],
            "balloons": _balloons_for_page(section_page),
        },
        files={"file": ("stale-section.png", _png(), "image/png")},
    )
    assert stale_renderer_response.status_code == 422
    assert "technical renderer is stale" in stale_renderer_response.json()["message"]

    render_response = client.post(
        f"/api/parts-manual/manual-fixture/document/page-{section_id}/render",
        data={
            "documentRevision": document["documentRevision"],
            "manualPlanRevision": document["manualPlanRevision"],
            "sourceRevision": document["sourceRevision"],
            "renderPipelineVersion": PARTS_MANUAL_RENDER_PIPELINE_VERSION,
            "balloons": _balloons_for_page(section_page),
        },
        files={"file": ("section.png", _png(), "image/png")},
    )
    assert render_response.status_code == 200, render_response.text
    artifact = render_response.json()["artifact"]
    assert artifact["renderPipelineVersion"] == PARTS_MANUAL_RENDER_PIPELINE_VERSION
    assert artifact["widthPx"] == 2400
    assert artifact["heightPx"] == 1800

    metadata_path = (
        tmp_path
        / "manual-fixture"
        / "renders"
        / document["documentRevision"]
        / f"page-{section_id}.json"
    )
    with open(_native_atomic_path(metadata_path), "r", encoding="ascii") as handle:
        stored_descriptor = json.load(handle)
    stored_descriptor.pop("renderPipelineVersion")
    with open(_native_atomic_path(metadata_path), "w", encoding="ascii") as handle:
        handle.write(
            json.dumps(stored_descriptor, ensure_ascii=True, sort_keys=True, indent=2)
            + "\n"
        )
    stale_document = client.get("/api/parts-manual/manual-fixture/document").json()["document"]
    stale_page = next(page for page in stale_document["pages"] if page.get("sectionId") == section_id)
    assert stale_page["renderRequest"]["image"].get("status") != "ready"
    stored_descriptor["renderPipelineVersion"] = PARTS_MANUAL_RENDER_PIPELINE_VERSION
    with open(_native_atomic_path(metadata_path), "w", encoding="ascii") as handle:
        handle.write(
            json.dumps(stored_descriptor, ensure_ascii=True, sort_keys=True, indent=2)
            + "\n"
        )

    rendered_document = client.get("/api/parts-manual/manual-fixture/document").json()["document"]
    rendered_page = next(page for page in rendered_document["pages"] if page.get("sectionId") == section_id)
    rendered_image = rendered_page["renderRequest"]["image"]
    assert rendered_image["status"] == "ready"
    assert rendered_image["minimumWidthPx"] == 2400
    assert rendered_image["minimumHeightPx"] == 1800
    assert (
        rendered_image["axisConstrainedOccupancyPolicy"]
        == "allow_when_uniform_scale_exceeds_axis_limit"
    )
    assert rendered_image["axisConstrainedFillTolerance"] == 0.02
    artifact_response = client.get(rendered_page["renderRequest"]["image"]["url"])
    assert artifact_response.status_code == 200
    assert artifact_response.headers["content-type"] == "image/png"

    undersized_response = client.post(
        f"/api/parts-manual/manual-fixture/document/page-{section_id}/render",
        data={
            "documentRevision": document["documentRevision"],
            "manualPlanRevision": document["manualPlanRevision"],
            "sourceRevision": document["sourceRevision"],
            "renderPipelineVersion": PARTS_MANUAL_RENDER_PIPELINE_VERSION,
            "balloons": _balloons_for_page(section_page),
        },
        files={"file": ("small.png", _png(64, 64), "image/png")},
    )
    assert undersized_response.status_code == 422
    assert "at least 2400 x 1800" in undersized_response.json()["message"]

    for page in rendered_document["pages"]:
        render_request = page.get("renderRequest")
        if not render_request or render_request["image"]["status"] == "ready":
            continue
        response = client.post(
            f"/api/parts-manual/manual-fixture/document/{page['pageId']}/render",
            data={
                "documentRevision": document["documentRevision"],
                "manualPlanRevision": document["manualPlanRevision"],
                "sourceRevision": document["sourceRevision"],
                "renderPipelineVersion": PARTS_MANUAL_RENDER_PIPELINE_VERSION,
                "balloons": _balloons_for_page(page),
            },
            files={"file": (f"{page['pageId']}.png", _png(), "image/png")},
        )
        assert response.status_code == 200, response.text

    complete_document = client.get("/api/parts-manual/manual-fixture/document").json()["document"]
    assert all(
        page.get("renderRequest", {}).get("image", {}).get("status") == "ready"
        for page in complete_document["pages"]
        if page.get("renderRequest")
    )
    pdf_response = client.post(
        "/api/parts-manual/manual-fixture/pdf",
        json={
            "documentRevision": complete_document["documentRevision"],
            "manualPlanRevision": complete_document["manualPlanRevision"],
            "sourceRevision": complete_document["sourceRevision"],
        },
    )
    assert pdf_response.status_code == 200, pdf_response.text
    pdf_artifact = pdf_response.json()["artifact"]
    assert pdf_artifact["pageCount"] == 6
    assert pdf_artifact["qualityStatus"] == "PASS"
    pdf_file_response = client.get(pdf_artifact["url"])
    assert pdf_file_response.status_code == 200
    assert pdf_file_response.content.startswith(b"%PDF")
    with fitz.open(stream=pdf_file_response.content, filetype="pdf") as pdf:
        assert pdf.page_count == 6
        text = "\n".join(page.get_text() for page in pdf)
        assert "ILLUSTRATED PARTS MANUAL" in text
        assert "Workholding Station" in text
        assert "WB-100" in text
        assert "Figure 2-1" in text
        assert "PART NUMBER INDEX" in text
        assert len(pdf.get_toc()) >= 3

    delete_response = client.post(
        f"/api/parts-manual/manual-fixture/sections/{section_id}/delete",
        json={
            "baseRevision": created["revision"],
            "sourceRevision": initial["sourceRevision"],
        },
    )
    assert delete_response.status_code == 200, delete_response.text
    assert delete_response.json()["plan"]["sections"] == []
