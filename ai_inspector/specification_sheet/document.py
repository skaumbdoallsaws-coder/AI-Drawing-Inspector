"""Compile one-page, evidence-bound product specification sheets."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from ai_inspector.operations_manual.evidence import OperationsManualEvidenceRepository
from ai_inspector.parts_manual.documentation import (
    DEFAULT_DOCUMENT_THEME,
    DEFAULT_PAGE_MASTERS,
)


SPECIFICATION_SHEET_DOCUMENT_SCHEMA_VERSION = 1
SPECIFICATION_SHEET_RENDER_PIPELINE_VERSION = 1
SPECIFICATION_SHEET_PAGE_WIDTH_PT = 612.0
SPECIFICATION_SHEET_PAGE_HEIGHT_PT = 792.0
_APPROVED_PROFILE_STATUSES = {
    "approved_for_prototype",
    "approved_for_prototype_description",
}


class SpecificationSheetError(RuntimeError):
    pass


def _stable_revision(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _read_profile(profile_root: str | Path, assembly_number: str) -> Dict[str, Any]:
    root = Path(profile_root).resolve()
    safe_name = str(assembly_number or "").strip().lower()
    if not safe_name or any(value not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for value in safe_name):
        raise SpecificationSheetError("invalid specification-sheet assembly number")
    path = (root / "profiles" / f"{safe_name}.json").resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise SpecificationSheetError("invalid specification-sheet profile path") from exc
    try:
        profile = json.loads(path.read_text("utf-8"))
    except FileNotFoundError as exc:
        raise SpecificationSheetError(
            f"no reviewed specification-sheet profile is registered for {assembly_number}"
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SpecificationSheetError("the specification-sheet profile is unreadable") from exc
    if not isinstance(profile, dict):
        raise SpecificationSheetError("the specification-sheet profile must be an object")
    if str(profile.get("assemblyNumber") or "").casefold() != safe_name.casefold():
        raise SpecificationSheetError("the specification-sheet profile assembly binding is invalid")
    return profile


def _claim(snapshot: Mapping[str, Any], claim_id: str) -> Dict[str, Any]:
    claim = (snapshot.get("claims") or {}).get(str(claim_id))
    if not isinstance(claim, Mapping):
        raise SpecificationSheetError(f"required specification claim is missing: {claim_id}")
    status = str(claim.get("status") or "")
    if status not in _APPROVED_PROFILE_STATUSES:
        raise SpecificationSheetError(
            f"specification claim {claim_id} is not approved for the review sheet"
        )
    return copy.deepcopy(dict(claim))


def _format_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SpecificationSheetError("a specification value is not numeric") from exc
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def _format_claim_value(claim: Mapping[str, Any]) -> str:
    value = claim.get("value")
    unit = str(claim.get("unit") or "").strip()
    if isinstance(value, Mapping):
        ordered = [value.get(key) for key in ("width", "length", "height") if value.get(key) is not None]
        if not ordered:
            raise SpecificationSheetError("a structured specification value is empty")
        formatted = " x ".join(_format_number(item) for item in ordered)
    elif value is not None:
        formatted = _format_number(value)
    else:
        raise SpecificationSheetError("an approved specification value is missing")
    return f"{formatted} {unit}".strip()


def _citation_receipt(
    snapshot: Mapping[str, Any],
    claim_ids: Iterable[str],
) -> list[Dict[str, Any]]:
    source_claims: Dict[str, set[str]] = {}
    source_anchors: Dict[str, Dict[str, set[str]]] = {}
    source_pages: Dict[str, Dict[str, set[int]]] = {}
    for claim_id in sorted({str(value) for value in claim_ids if str(value).strip()}):
        claim = (snapshot.get("claims") or {}).get(claim_id) or {}
        for source_id in claim.get("sourceIds") or []:
            source_key = str(source_id)
            source_claims.setdefault(source_key, set()).add(claim_id)
            for location in claim.get("sourceLocations") or []:
                if not isinstance(location, Mapping) or str(location.get("sourceId") or "") != source_key:
                    continue
                anchor = str(location.get("anchor") or "").strip()
                if anchor:
                    source_anchors.setdefault(source_key, {}).setdefault(claim_id, set()).add(anchor)
                try:
                    page_number = int(location.get("page") or 0)
                except (TypeError, ValueError):
                    page_number = 0
                if page_number > 0:
                    source_pages.setdefault(source_key, {}).setdefault(claim_id, set()).add(page_number)

    sources = snapshot.get("sources") or {}
    authority_order = {
        "OEM_CURRENT": 0,
        "CAD_AUTHORED": 1,
        "USER_AUTHORED": 2,
    }
    ordered = sorted(
        source_claims,
        key=lambda source_id: (
            authority_order.get(str((sources.get(source_id) or {}).get("authority") or ""), 99),
            str((sources.get(source_id) or {}).get("title") or source_id).casefold(),
        ),
    )
    rows: list[Dict[str, Any]] = []
    for index, source_id in enumerate(ordered, start=1):
        source = sources.get(source_id) or {}
        claim_ids_for_source = sorted(source_claims[source_id])
        references = [
            {
                "claimId": claim_id,
                "sourcePageNumbers": sorted(source_pages.get(source_id, {}).get(claim_id, set())),
                "anchors": sorted(source_anchors.get(source_id, {}).get(claim_id, set())),
            }
            for claim_id in claim_ids_for_source
        ]
        rows.append(
            {
                "citationNumber": index,
                "sourceId": source_id,
                "title": str(source.get("title") or source_id),
                "kind": str(source.get("kind") or "registered_evidence"),
                "authority": str(source.get("authority") or "UNKNOWN"),
                "url": str(source.get("url") or "").strip() or None,
                "registeredLocation": str(
                    source.get("canonicalLocation")
                    or source.get("cachedLocation")
                    or ""
                ).strip() or None,
                "claimCount": len(claim_ids_for_source),
                "claimIds": claim_ids_for_source,
                "claimSourcePageReferences": references,
                "sourcePageNumbers": sorted(
                    {
                        page_number
                        for reference in references
                        for page_number in reference["sourcePageNumbers"]
                    }
                ),
            }
        )
    return rows


def specification_sheet_layout() -> Dict[str, Any]:
    return {
        "page": {
            "width": SPECIFICATION_SHEET_PAGE_WIDTH_PT,
            "height": SPECIFICATION_SHEET_PAGE_HEIGHT_PT,
            "aspectRatio": SPECIFICATION_SHEET_PAGE_WIDTH_PT / SPECIFICATION_SHEET_PAGE_HEIGHT_PT,
            "orientation": "portrait",
            "logicalUnit": "pt",
        },
        "shared": {
            "header": {"x": 0, "y": 0, "width": 612, "height": 64},
            "footer": {"x": 24, "y": 754, "width": 564, "height": 26},
            "content": {"x": 36, "y": 82, "width": 540, "height": 654},
        },
        "pageTypes": {
            "product_specification": {
                "illustration": {"x": 36, "y": 176, "width": 318, "height": 346},
                "specifications": {"x": 374, "y": 198, "width": 202, "height": 324},
            }
        },
    }


def _apply_scene(
    page: Dict[str, Any],
    documentation_scene: Optional[Mapping[str, Any]],
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    scene = documentation_scene if isinstance(documentation_scene, Mapping) else {}
    composition_pages = scene.get("pages") if isinstance(scene.get("pages"), Mapping) else {}
    composition = copy.deepcopy(
        composition_pages.get(page["pageId"])
        if isinstance(composition_pages.get(page["pageId"]), Mapping)
        else {}
    )
    page["documentationComposition"] = composition
    page["documentationObjects"] = copy.deepcopy(
        composition.get("documentObjects")
        if isinstance(composition.get("documentObjects"), Mapping)
        else {}
    )
    page["pageMasterId"] = "reference"
    page["renderRequest"]["composition"] = copy.deepcopy(composition)
    theme = copy.deepcopy(
        scene.get("theme") if isinstance(scene.get("theme"), Mapping) else DEFAULT_DOCUMENT_THEME
    )
    page_masters = copy.deepcopy(
        scene.get("pageMasters")
        if isinstance(scene.get("pageMasters"), Mapping)
        else DEFAULT_PAGE_MASTERS
    )
    return theme, page_masters


def build_specification_sheet_document(
    assembly_data: Mapping[str, Any],
    catalog: Mapping[str, Any],
    *,
    evidence_root: str | Path,
    profile_root: str | Path,
    documentation_scene: Optional[Mapping[str, Any]] = None,
    documentation_scene_revision: Optional[str] = None,
) -> Dict[str, Any]:
    assembly_number = str(catalog.get("assemblyNumber") or "").strip()
    profile = _read_profile(profile_root, assembly_number)
    snapshot = OperationsManualEvidenceRepository(evidence_root).snapshot()
    identity = _claim(snapshot, str(profile.get("identityClaimId") or ""))
    product_name = str(identity.get("statement") or "").strip()
    product_name = product_name.removeprefix("The target product is the ").rstrip(".")
    if not product_name:
        product_name = str(
            (assembly_data.get("identity") or {}).get("description")
            or (assembly_data.get("identity") or {}).get("name")
            or assembly_number
        )

    specifications: list[Dict[str, Any]] = []
    used_claim_ids = {str(profile.get("identityClaimId") or "")}
    for row in profile.get("specifications") or []:
        if not isinstance(row, Mapping):
            continue
        claim_id = str(row.get("claimId") or "")
        claim = _claim(snapshot, claim_id)
        used_claim_ids.add(claim_id)
        specifications.append(
            {
                "label": str(row.get("label") or claim.get("category") or "Specification"),
                "value": _format_claim_value(claim),
                "claimId": claim_id,
                "sourceIds": [str(value) for value in claim.get("sourceIds") or []],
            }
        )
    if not specifications:
        raise SpecificationSheetError("the specification-sheet profile has no approved values")

    tagline = profile.get("tagline") if isinstance(profile.get("tagline"), Mapping) else {}
    tagline_claim_ids = [str(value) for value in tagline.get("claimIds") or []]
    for claim_id in tagline_claim_ids:
        _claim(snapshot, claim_id)
        used_claim_ids.add(claim_id)

    features: list[Dict[str, Any]] = []
    for row in profile.get("features") or []:
        if not isinstance(row, Mapping):
            continue
        claim_ids = [str(value) for value in row.get("claimIds") or []]
        for claim_id in claim_ids:
            _claim(snapshot, claim_id)
            used_claim_ids.add(claim_id)
        features.append(
            {
                "title": str(row.get("title") or "Feature"),
                "text": str(row.get("text") or ""),
                "claimIds": claim_ids,
            }
        )
    if len(features) != 3:
        raise SpecificationSheetError("the one-page specification profile requires three features")

    occurrence_ids = [
        str(row.get("occurrenceId"))
        for row in catalog.get("occurrences") or []
        if isinstance(row, Mapping)
        and row.get("occurrenceId")
        and row.get("kind") == "part"
        and not row.get("suppressed")
    ]
    if not occurrence_ids:
        raise SpecificationSheetError("the assembly has no visible part occurrences")

    figure = profile.get("figure") if isinstance(profile.get("figure"), Mapping) else {}
    layout = specification_sheet_layout()
    illustration_frame = layout["pageTypes"]["product_specification"]["illustration"]
    table_frame = layout["pageTypes"]["product_specification"]["specifications"]
    feature_width = 168.0
    page: Dict[str, Any] = {
        "pageId": "page-product-specification",
        "pageNumber": 1,
        "pageCount": 1,
        "pageType": "product_specification",
        "title": product_name,
        "productCategory": str(profile.get("productCategory") or "PRODUCT SPECIFICATION"),
        "specifications": copy.deepcopy(specifications),
        "features": copy.deepcopy(features),
        "evidenceClaimIds": sorted(used_claim_ids),
        "layoutBlocks": [
            {
                "blockId": "spec-kicker",
                "blockType": "spec_kicker",
                "text": "PRODUCT SPECIFICATION",
                "frame": {"x": 36, "y": 84, "width": 540, "height": 16},
                "style": {"fontSize": 8.5, "lineHeight": 12, "fontWeight": 700, "color": "#148FD0"},
                "evidenceClaimIds": [],
            },
            {
                "blockId": "spec-title",
                "blockType": "spec_title",
                "text": product_name,
                "frame": {"x": 36, "y": 102, "width": 540, "height": 39},
                "style": {"fontSize": 22, "lineHeight": 28, "fontWeight": 700, "color": "#071B2A"},
                "evidenceClaimIds": [str(profile.get("identityClaimId") or "")],
            },
            {
                "blockId": "spec-tagline",
                "blockType": "paragraph",
                "text": str(tagline.get("text") or ""),
                "frame": {"x": 36, "y": 144, "width": 540, "height": 20},
                "style": {"fontSize": 9, "lineHeight": 12, "color": "#596A76"},
                "evidenceClaimIds": tagline_claim_ids,
            },
            {
                "blockId": "spec-figure",
                "blockType": "cad_figure",
                "figureId": "SPEC-FIG-001",
                "caption": str(figure.get("caption") or "Assembled product visualization."),
                "frame": copy.deepcopy(illustration_frame),
                "evidenceClaimIds": [],
            },
            {
                "blockId": "specifications-heading",
                "blockType": "heading",
                "text": "Specifications",
                "lines": ["Specifications"],
                "frame": {"x": 374, "y": 170, "width": 202, "height": 28},
                "style": {"fontSize": 15, "lineHeight": 19, "fontWeight": 700, "color": "#071B2A"},
                "evidenceClaimIds": [],
            },
            {
                "blockId": "specifications-table",
                "blockType": "key_value_table",
                "columns": [],
                "columnWidths": [0.58, 0.42],
                "rows": [
                    {
                        "cells": [row["label"], row["value"]],
                        "claimIds": [row["claimId"]],
                    }
                    for row in specifications
                ],
                "rowHeights": [54 for _row in specifications],
                "frame": copy.deepcopy(table_frame),
                "evidenceClaimIds": [row["claimId"] for row in specifications],
            },
            {
                "blockId": "features-heading",
                "blockType": "heading",
                "text": "Designed for productive material handling",
                "lines": ["Designed for productive material handling"],
                "frame": {"x": 36, "y": 550, "width": 540, "height": 22},
                "style": {"fontSize": 13, "lineHeight": 17, "fontWeight": 700, "color": "#071B2A"},
                "evidenceClaimIds": [],
            },
            *[
                {
                    "blockId": f"spec-feature-{index + 1}",
                    "blockType": "spec_feature",
                    "title": row["title"],
                    "text": row["text"],
                    "frame": {
                        "x": 36 + index * 186,
                        "y": 582,
                        "width": feature_width,
                        "height": 132,
                    },
                    "evidenceClaimIds": row["claimIds"],
                }
                for index, row in enumerate(features)
            ],
        ],
        "renderRequest": {
            "figureId": "SPEC-FIG-001",
            "scopeKind": "assembly",
            "manualGroupNames": [],
            "occurrenceIds": occurrence_ids,
            "occurrenceOrder": occurrence_ids,
            "pose": str(figure.get("pose") or "assembled"),
            "cameraPreset": str(figure.get("cameraPreset") or "isometric"),
            "explodeStrategy": "radial",
            "explodeFactor": 0.0,
            "displayStyle": "shaded",
            "illustrationStyle": str(figure.get("illustrationStyle") or "SHADED_COLOR"),
            "showItemCallouts": False,
            "calloutItems": [],
            "image": {
                "status": "required",
                "minimumWidthPx": 2200,
                "minimumHeightPx": 2200,
                "targetAspectRatio": 1.0,
                "targetForegroundOccupancy": 0.70,
                "minimumForegroundOccupancy": 0.60,
                "maximumForegroundOccupancy": 0.80,
                "maximumForegroundAxisOccupancy": 0.94,
                "background": "technical_white",
                "illustrationStyle": str(figure.get("illustrationStyle") or "SHADED_COLOR"),
                "allowAutomaticCameraSelection": True,
            },
        },
    }
    theme, page_masters = _apply_scene(page, documentation_scene)
    profile_revision = _stable_revision(profile)
    manual_plan_revision = _stable_revision(
        {
            "assemblyNumber": assembly_number,
            "sourceRevision": catalog.get("sourceRevision"),
            "evidenceRevision": snapshot["revision"],
            "profileRevision": profile_revision,
        }
    )
    citations = _citation_receipt(snapshot, used_claim_ids)
    document: Dict[str, Any] = {
        "schemaVersion": SPECIFICATION_SHEET_DOCUMENT_SCHEMA_VERSION,
        "renderPipelineVersion": SPECIFICATION_SHEET_RENDER_PIPELINE_VERSION,
        "documentType": "product_specification_sheet",
        "status": "review_ready",
        "sourceRevision": str(catalog.get("sourceRevision") or ""),
        "evidenceRevision": str(snapshot["revision"]),
        "profileRevision": profile_revision,
        "manualPlanRevision": manual_plan_revision,
        "documentationSceneRevision": documentation_scene_revision,
        "title": f"{product_name} Specification Sheet",
        "documentNumber": str(profile.get("documentNumber") or f"SS-{assembly_number}-001"),
        "revision": None,
        "product": {
            "name": product_name,
            "assemblyNumber": assembly_number,
            "model": str(profile.get("assemblyNumber") or assembly_number),
            "category": str(profile.get("productCategory") or "PRODUCT SPECIFICATION"),
        },
        "theme": theme,
        "pageMasters": page_masters,
        "publicationLayout": layout,
        "pageCount": 1,
        "pages": [page],
        "evidenceCitations": citations,
        "evidenceSummary": {
            "approvedClaimCount": len(used_claim_ids),
            "citedClaimCount": len(used_claim_ids),
            "citedSourceCount": len(citations),
            "registeredClaimCount": len(snapshot.get("claims") or {}),
            "registeredSourceCount": len(snapshot.get("sources") or {}),
        },
        "releaseGate": {
            "status": "REVIEW_READY",
            "reviewPdfAllowed": True,
            "controlledPdfAllowed": False,
            "message": "Review export only; controlled release requires recorded approval.",
        },
    }
    document["documentRevision"] = _stable_revision(document)
    return document
