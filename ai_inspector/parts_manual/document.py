"""Publication document model for illustrated parts manual rendering."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .catalog import build_scoped_bom
from .documentation import DEFAULT_DOCUMENT_THEME, DEFAULT_PAGE_MASTERS
from .layout import page_layout, publication_layout
from .quality import require_publishable_manual_plan
from .schema import default_section_visualization
from .version import (
    PARTS_MANUAL_DEFAULT_END_CONDITION,
    PARTS_MANUAL_RENDER_PIPELINE_VERSION,
)


PARTS_MANUAL_DOCUMENT_SCHEMA_VERSION = 4
MANUAL_SECTION_BOM_ROWS_PER_PAGE = 20
# The PDF draws index rows 22 pt apart from y 106 inside the index content area (y 66-564).
PARTS_INDEX_ROWS_PER_PAGE = 20
MANUAL_ILLUSTRATION_STYLE_SHADED_COLOR = "SHADED_COLOR"
MANUAL_ILLUSTRATION_STYLE_HIDDEN_LINES_REMOVED = "HIDDEN_LINES_REMOVED"
DEFAULT_MANUAL_ILLUSTRATION_STYLE = MANUAL_ILLUSTRATION_STYLE_HIDDEN_LINES_REMOVED
# HLR images contain edge pixels rather than filled faces. A 0.4% image-area
# floor rejects blank and single-stroke captures (a 1 px stroke across the
# frame is about 0.25%) while retaining legitimate sparse sections - a tube
# handle with two small brackets is about 0.6% - whose framing is
# independently enforced by bbox area.
MANUAL_HLR_MINIMUM_FOREGROUND_PIXEL_PERCENT = 0.4
MANUAL_HLR_FOREGROUND_PIXEL_POLICY = "hlr_linework_antiblank_floor"


def _stable_revision(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def figure_revision(
    assembly_number: str,
    source_revision: str,
    render_request: Mapping[str, Any],
) -> str:
    """Revision of one figure: everything its capture depends on (the CAD, the
    renderer and the page's render request with its composition). A capture is
    kept while its figure revision is unchanged, so a change to one section
    recaptures only the figures it touches."""
    request = {
        key: value
        for key, value in render_request.items()
        if key != "figureRevision"
    }
    return _stable_revision(
        {
            "assemblyNumber": str(assembly_number or "").lower(),
            "sourceRevision": str(source_revision or ""),
            "renderPipelineVersion": PARTS_MANUAL_RENDER_PIPELINE_VERSION,
            "renderRequest": request,
        }
    )


def _included_sections(plan: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    sections = [
        section
        for section in plan.get("sections") or []
        if isinstance(section, Mapping) and section.get("includeInManual", True)
    ]
    return sorted(
        sections,
        key=lambda section: (
            int(section.get("pageOrder") or 10**9),
            str(section.get("name") or "").casefold(),
            str(section.get("sectionId") or ""),
        ),
    )


def _section_depth(section: Mapping[str, Any], by_id: Mapping[str, Mapping[str, Any]]) -> int:
    depth = 0
    seen = {str(section.get("sectionId") or "")}
    parent_id = section.get("parentSectionId")
    while parent_id:
        parent_key = str(parent_id)
        if parent_key in seen or parent_key not in by_id:
            break
        seen.add(parent_key)
        depth += 1
        parent_id = by_id[parent_key].get("parentSectionId")
    return depth


def _visualization(section: Mapping[str, Any]) -> Dict[str, Any]:
    result = default_section_visualization()
    candidate = section.get("visualization")
    if isinstance(candidate, Mapping):
        result.update(copy.deepcopy(dict(candidate)))
    if section.get("processOperationIds") or section.get("occurrenceOrder"):
        result["explodeStrategy"] = "process_sequence"
    return result


def _display_revision(value: Any) -> Optional[str]:
    revision = str(value or "").strip()
    if not revision:
        return None
    lowered = revision.lower()
    if len(lowered) == 64 and all(character in "0123456789abcdef" for character in lowered):
        return None
    return revision


def _date_only(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).date().isoformat()
    except ValueError:
        return None


# A part's number and description are edited in a parts list (on the page or by Sage) once for the whole manual. The
# edit is kept on the part number index page, never on a figure's page, so no figure's revision changes (nothing is
# recaptured); its text replaces the CAD value in every parts list and in the index. An empty edit goes back to the
# CAD value. ITEM and QTY are the balloon's number and the model's count, so they are not edited.
PART_TEXT_PAGE_ID = "page-parts-index"
PART_TEXT_FIELDS = {"partNumber": "displayPartNumber", "description": "description"}


def part_text_target_id(definition_id: str, field: str) -> str:
    return f"part.{definition_id}.{field}"


def part_text_edits(scene_pages: Any) -> Dict[str, Dict[str, str]]:
    """The edited part numbers and descriptions in a documentation scene's pages, by definition id."""
    page = scene_pages.get(PART_TEXT_PAGE_ID) if isinstance(scene_pages, Mapping) else None
    overrides = page.get("pageElementOverrides") if isinstance(page, Mapping) else None
    edits: Dict[str, Dict[str, str]] = {}
    for target_id, override in overrides.items() if isinstance(overrides, Mapping) else ():
        prefix, _, rest = str(target_id).partition(".")
        definition_id, _, field = rest.rpartition(".")
        text = " ".join(str(override.get("text") or "").split()) if isinstance(override, Mapping) else ""
        if prefix == "part" and definition_id and field in PART_TEXT_FIELDS and text:
            edits.setdefault(definition_id, {})[PART_TEXT_FIELDS[field]] = text
    return edits


def with_part_text(
    rows: Iterable[Mapping[str, Any]],
    edits: Mapping[str, Mapping[str, str]],
) -> List[Dict[str, Any]]:
    """Parts-list rows with the manual's edited part numbers and descriptions."""
    result = []
    for source in rows:
        row = copy.deepcopy(dict(source))
        for field, text in (edits.get(str(row.get("definitionId") or "")) or {}).items():
            row[field] = text
            row["partNumberSource" if field == "displayPartNumber" else "descriptionSource"] = "documentation_edit"
        result.append(row)
    return result


def _natural_key(value: str) -> List[Any]:
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value)]


def _shown_copy(
    catalog_rows: Iterable[Mapping[str, Any]],
    occurrence_ids: List[str],
) -> tuple[List[str], int]:
    """A section made only of copies of one subassembly (the two fixed casters) is drawn as one copy: the
    occurrences of its first copy, and the number of copies. The parts list and the balloons' "2X" still count every
    copy. Any other section is drawn whole (one copy)."""
    rows = {str(row.get("occurrenceId")): row for row in catalog_rows if row.get("occurrenceId")}

    def ancestry(occurrence_id: str) -> List[str]:
        path = [occurrence_id]
        while rows.get(path[-1], {}).get("parentOccurrenceId") and len(path) < 64:
            path.append(str(rows[path[-1]]["parentOccurrenceId"]))
        return path[::-1]

    paths = [ancestry(value) for value in occurrence_ids if value in rows]
    if len(paths) < 2 or len(paths) != len(occurrence_ids):
        return occurrence_ids, 1
    # The copies hang just below the deepest assembly every occurrence of the section shares.
    depth = 0
    while all(len(path) > depth + 1 for path in paths) and len({path[depth] for path in paths}) == 1:
        depth += 1
    copies: Dict[str, List[str]] = {}
    for path in paths:
        copies.setdefault(path[depth], []).append(path[-1])
    if (
        len(copies) < 2
        or any(rows[key].get("kind") != "subassembly" for key in copies)
        or len({str(rows[key].get("definitionId") or "") for key in copies}) != 1
        or len({
            tuple(sorted(str(rows[value].get("definitionId") or "") for value in members))
            for members in copies.values()
        }) != 1
    ):
        return occurrence_ids, 1
    first = min(copies, key=lambda key: (_natural_key(str(rows[key].get("name") or "")), key))
    return copies[first], len(copies)


def _callout_items(bom: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "itemNumber": int(row["item"]),
            "calloutId": str(
                row.get("calloutId") or f"callout-item-{int(row['item'])}"
            ),
            "definitionId": str(row.get("definitionId") or ""),
            "description": str(row.get("description") or ""),
            "quantity": int(row.get("quantity") or 0),
            "occurrenceIds": [str(value) for value in row.get("occurrenceIds") or []],
            "anchorScope": str(row.get("anchorScope") or "component_instance"),
            "anchorPreference": str(
                row.get("anchorPreference") or "visible_edge"
            ),
            "endCondition": str(
                row.get("endCondition") or PARTS_MANUAL_DEFAULT_END_CONDITION
            ),
        }
        for row in bom
    ]


_CATALOG_BOUND_CALLOUT_FIELDS = (
    "partNumber",
    "engineeringPartNumber",
    "displayPartNumber",
    "partNumberSource",
    "description",
    "descriptionSource",
    "configuration",
    "quantity",
    "occurrenceIds",
)


def _rehydrate_manual_callout_items(
    manual_items: Iterable[Mapping[str, Any]],
    generated_bom: Iterable[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Keep manual callout composition while refreshing catalog-owned BOM data."""
    current_by_definition = {
        str(row.get("definitionId") or ""): row
        for row in generated_bom
        if isinstance(row, Mapping) and row.get("definitionId")
    }
    result: List[Dict[str, Any]] = []
    for source in manual_items:
        if not isinstance(source, Mapping):
            continue
        row = copy.deepcopy(dict(source))
        current = current_by_definition.get(str(row.get("definitionId") or ""))
        if current is not None:
            for field in _CATALOG_BOUND_CALLOUT_FIELDS:
                if field in current:
                    row[field] = copy.deepcopy(current[field])
        item_number = int(row.get("itemNumber") or row.get("item") or 0)
        if item_number > 0:
            row["itemNumber"] = item_number
            row["item"] = item_number
        result.append(row)
    return result


def _render_request(
    *,
    scope_kind: str,
    occurrence_ids: Iterable[str],
    pose: str,
    visualization: Mapping[str, Any],
    callout_items: Iterable[Mapping[str, Any]] = (),
    occurrence_order: Iterable[str] = (),
    process_operation_ids: Iterable[str] = (),
    illustration_style: str = DEFAULT_MANUAL_ILLUSTRATION_STYLE,
    target_foreground_occupancy: float = 0.70,
    minimum_foreground_occupancy: float = 0.60,
    maximum_foreground_occupancy: float = 0.80,
) -> Dict[str, Any]:
    normalized_callouts = [copy.deepcopy(dict(row)) for row in callout_items]
    normalized_style = str(illustration_style or DEFAULT_MANUAL_ILLUSTRATION_STYLE).upper()
    if normalized_style not in {
        MANUAL_ILLUSTRATION_STYLE_SHADED_COLOR,
        MANUAL_ILLUSTRATION_STYLE_HIDDEN_LINES_REMOVED,
    }:
        raise ValueError(f"unsupported manual illustration style: {illustration_style}")
    return {
        "scopeKind": scope_kind,
        "occurrenceIds": list(dict.fromkeys(str(value) for value in occurrence_ids if value)),
        "occurrenceOrder": list(dict.fromkeys(str(value) for value in occurrence_order if value)),
        "processOperationIds": list(
            dict.fromkeys(str(value) for value in process_operation_ids if value)
        ),
        "pose": pose,
        "cameraPreset": str(visualization.get("cameraPreset") or "isometric"),
        "explodeStrategy": str(visualization.get("explodeStrategy") or "radial"),
        "explodeFactor": float(visualization.get("explodeFactor") or 1.0),
        "illustrationStyle": normalized_style,
        "showItemCallouts": bool(normalized_callouts),
        "calloutItems": normalized_callouts,
        "calloutContract": {
            "anchorMethod": "frontmost_camera_raycast",
            "leaderStyle": "auto_straight_first",
            "allowedLeaderStyles": ["straight", "orthogonal"],
            "maximumAutomaticElbows": 1,
            "balloonAttachment": "circumference",
            "requireVisibleAnchor": True,
            "maximumLeaderCrossings": 0,
            "maximumGeometryIntersections": 0,
            "requireLeader": True,
            "repeatedPartStrategies": [
                "branched",
                "representative_with_count",
            ],
            # Automatic generation always emits one balloon, one leader and one
            # representative anchor for a repeated part. "branched" stays a
            # supported strategy but is only reachable through an explicit
            # user-authored leader override.
            "defaultRepeatedPartStrategy": "representative_with_count",
            "groupAnchorScope": "manual_group",
        },
        "image": {
            "status": "pending",
            "mimeType": "image/png",
            "minimumWidthPx": 2400,
            "minimumHeightPx": 1800,
            "transparentBackground": False,
            "background": "technical_white",
            "illustrationStyle": normalized_style,
            "foregroundOccupancyMetric": "bounding_box_area",
            "targetForegroundOccupancy": float(target_foreground_occupancy),
            "minimumForegroundOccupancy": float(minimum_foreground_occupancy),
            "maximumForegroundOccupancy": float(maximum_foreground_occupancy),
            "maximumForegroundAxisOccupancy": 0.96,
            "axisConstrainedOccupancyPolicy": "allow_when_uniform_scale_exceeds_axis_limit",
            "axisConstrainedFillTolerance": 0.02,
            "minimumForegroundPixelPercent": MANUAL_HLR_MINIMUM_FOREGROUND_PIXEL_PERCENT,
            "foregroundPixelPolicy": MANUAL_HLR_FOREGROUND_PIXEL_POLICY,
            # Documentation is WYSIWYG by default. Capture may refine distance
            # and centering, but it must not silently select another view.
            "allowAutomaticCameraSelection": False,
        },
    }


def _layout_mode(row_count: int) -> str:
    if row_count <= 8:
        return "small_bom"
    if row_count <= MANUAL_SECTION_BOM_ROWS_PER_PAGE:
        return "medium_bom"
    return "illustration_with_parts_list"


def build_manual_document(
    plan: Mapping[str, Any],
    catalog: Iterable[Mapping[str, Any]],
    assembly_data: Mapping[str, Any],
    *,
    plan_revision: str,
    documentation_scene: Optional[Mapping[str, Any]] = None,
    documentation_scene_revision: Optional[str] = None,
) -> Dict[str, Any]:
    """Compile a deterministic, publication-ready document model."""
    catalog_rows = [copy.deepcopy(dict(row)) for row in catalog if isinstance(row, Mapping)]
    publication_audit = require_publishable_manual_plan(plan, catalog_rows)
    composition_pages = (
        documentation_scene.get("pages")
        if isinstance(documentation_scene, Mapping)
        and isinstance(documentation_scene.get("pages"), Mapping)
        else {}
    )
    document_theme = copy.deepcopy(
        documentation_scene.get("theme")
        if isinstance(documentation_scene, Mapping)
        and isinstance(documentation_scene.get("theme"), Mapping)
        else DEFAULT_DOCUMENT_THEME
    )
    page_masters = copy.deepcopy(
        documentation_scene.get("pageMasters")
        if isinstance(documentation_scene, Mapping)
        and isinstance(documentation_scene.get("pageMasters"), Mapping)
        else DEFAULT_PAGE_MASTERS
    )
    part_text = part_text_edits(composition_pages)
    occurrence_ids = [
        str(row.get("occurrenceId"))
        for row in catalog_rows
        if row.get("occurrenceId")
        and row.get("kind") == "part"
        and not row.get("suppressed")
    ]
    sections = _included_sections(plan)
    section_by_id = {
        str(section.get("sectionId")): section
        for section in sections
        if section.get("sectionId")
    }
    identity = assembly_data.get("identity")
    identity = identity if isinstance(identity, Mapping) else {}
    document_control = plan.get("documentControl")
    document_control = document_control if isinstance(document_control, Mapping) else {}
    assembly_number = str(plan.get("assemblyNumber") or "")
    product_name = str(identity.get("description") or identity.get("name") or assembly_number)
    complete_product_name = product_name.strip()
    if complete_product_name.casefold().endswith(" assembly"):
        complete_product_name = complete_product_name[:-9].rstrip()
    complete_assembly_title = f"Complete {complete_product_name or product_name} Assembly"
    authored_title = str(plan.get("title") or "Illustrated Parts Manual").strip()
    default_title = f"{assembly_number} Illustrated Parts Manual"
    document_title = (
        f"{complete_product_name or product_name} Illustrated Parts Manual"
        if authored_title.casefold() == default_title.casefold()
        else authored_title
    )
    document_number = str(
        document_control.get("documentNumber") or f"IPM-{assembly_number.upper()}-001"
    )
    # Assembly profiles can carry InspectorPro library revisions that are not
    # controlled OEM document revisions.  Only explicitly authored document
    # control may populate this publication field.
    revision = _display_revision(document_control.get("revision")) or None
    release_date = (
        _date_only(document_control.get("releaseDate"))
        or _date_only(plan.get("updatedAt"))
        or _date_only(plan.get("createdAt"))
    )

    # Fixed front matter: cover, document information, contents, and group index.
    next_page_number = 5
    section_records: List[Dict[str, Any]] = []
    for section_index, section in enumerate(sections, start=2):
        section_id = str(section.get("sectionId"))
        section_occurrence_ids = [str(value) for value in section.get("occurrenceIds") or []]
        generated_bom = build_scoped_bom(
            catalog_rows,
            section_occurrence_ids,
            item_assignments=section.get("itemAssignments") or [],
        )
        bom = copy.deepcopy(generated_bom)
        section_page_override = composition_pages.get(f"page-{section_id}")
        manual_callout_mode = False
        if isinstance(section_page_override, Mapping) and "manualCalloutItems" in section_page_override:
            manual_items = section_page_override.get("manualCalloutItems")
            if manual_items is not None:
                manual_callout_mode = True
                bom = _rehydrate_manual_callout_items(manual_items, generated_bom)
        chunks = [
            bom[index : index + MANUAL_SECTION_BOM_ROWS_PER_PAGE]
            for index in range(0, len(bom), MANUAL_SECTION_BOM_ROWS_PER_PAGE)
        ] or [[]]
        figure_number = f"{section_index}-1"
        section_records.append(
            {
                "section": section,
                "occurrenceIds": section_occurrence_ids,
                "bom": bom,
                "generatedBom": generated_bom,
                "manualCalloutMode": manual_callout_mode,
                "bomChunks": chunks,
                "pageNumber": next_page_number,
                "figureNumber": figure_number,
                "sectionNumber": section_index,
            }
        )
        next_page_number += len(chunks)
    parts_index_page_number = next_page_number

    generated_overview_items = [
        {
            "itemNumber": index,
            "calloutId": f"callout-item-{index}",
            "sectionId": str(record["section"].get("sectionId") or ""),
            "name": str(record["section"].get("name") or "Manual Section"),
            "quantity": 1,
            "occurrenceIds": list(record["occurrenceIds"]),
            "pageNumber": int(record["pageNumber"]),
            "figureNumber": str(record["figureNumber"]),
            "anchorScope": "manual_group",
            "anchorPreference": "visible_edge",
            "endCondition": PARTS_MANUAL_DEFAULT_END_CONDITION,
        }
        for index, record in enumerate(section_records, start=1)
        if record["section"].get("parentSectionId") is None
    ]
    overview_items = copy.deepcopy(generated_overview_items)
    overview_override = composition_pages.get("page-assembly-overview")
    if isinstance(overview_override, Mapping) and "manualCalloutItems" in overview_override:
        manual_overview_items = overview_override.get("manualCalloutItems")
        if manual_overview_items is not None:
            overview_items = [
                copy.deepcopy(dict(row)) for row in manual_overview_items
            ]

    callout_page_audits: List[Dict[str, Any]] = []
    expected_overview_sections = {
        str(row.get("sectionId") or "") for row in generated_overview_items
    }
    active_overview_sections = {
        str(row.get("sectionId") or "") for row in overview_items
    }
    callout_page_audits.append(
        {
            "pageId": "page-assembly-overview",
            "mode": (
                "manual"
                if isinstance(overview_override, Mapping)
                and overview_override.get("manualCalloutItems") is not None
                else "generated"
            ),
            "requiredItemCount": len(expected_overview_sections),
            "activeItemCount": len(active_overview_sections),
            "missingSemanticIds": sorted(
                expected_overview_sections - active_overview_sections
            ),
            "unexpectedSemanticIds": sorted(
                active_overview_sections - expected_overview_sections
            ),
        }
    )
    for record in section_records:
        required = {
            str(row.get("definitionId") or "")
            for row in record["generatedBom"]
            if row.get("definitionId")
        }
        active = {
            str(row.get("definitionId") or "")
            for row in record["bom"]
            if row.get("definitionId")
        }
        callout_page_audits.append(
            {
                "pageId": f"page-{record['section'].get('sectionId')}",
                "mode": "manual" if record["manualCalloutMode"] else "generated",
                "requiredItemCount": len(required),
                "activeItemCount": len(active),
                "missingSemanticIds": sorted(required - active),
                "unexpectedSemanticIds": sorted(active - required),
            }
        )
    callout_audit_passed = all(
        not row["missingSemanticIds"] and not row["unexpectedSemanticIds"]
        for row in callout_page_audits
    )
    callout_audit = {
        "status": "PASS" if callout_audit_passed else "FAIL",
        "pages": callout_page_audits,
    }

    contents: List[Dict[str, Any]] = [
        {
            "sectionNumber": 1,
            "figureNumber": "1-1",
            "title": complete_assembly_title,
            "pageNumber": 4,
            "pageId": "page-assembly-overview",
            "depth": 0,
        }
    ]
    for record in section_records:
        section = record["section"]
        section_id = str(section.get("sectionId"))
        contents.append(
            {
                "sectionNumber": int(record["sectionNumber"]),
                "figureNumber": str(record["figureNumber"]),
                "title": str(section.get("name") or "Manual Section"),
                "pageNumber": int(record["pageNumber"]),
                "pageId": f"page-{section_id}",
                "sectionId": section_id,
                "depth": _section_depth(section, section_by_id),
            }
        )
    contents.append(
        {
            "sectionNumber": len(section_records) + 2,
            "figureNumber": None,
            "title": "Part Number Index",
            "pageNumber": parts_index_page_number,
            "pageId": "page-parts-index",
            "depth": 0,
        }
    )

    pages: List[Dict[str, Any]] = [
        {
            "pageId": "page-cover",
            "pageNumber": 1,
            "pageType": "cover",
            "title": document_title,
            "product": {
                "name": product_name,
                "assemblyNumber": assembly_number,
                "model": str(identity.get("model") or "").strip() or None,
            },
            "documentControl": {
                "documentNumber": document_number,
                "revision": revision,
                "releaseDate": release_date,
            },
            "renderRequest": _render_request(
                scope_kind="assembly",
                occurrence_ids=occurrence_ids,
                pose="assembled",
                visualization={"cameraPreset": "isometric"},
                target_foreground_occupancy=0.48,
                minimum_foreground_occupancy=0.38,
                maximum_foreground_occupancy=0.72,
            ),
        },
        {
            "pageId": "page-document-information",
            "pageNumber": 2,
            "pageType": "document_information",
            "title": "Document Information and Revision",
            "documentControl": {
                "documentTitle": document_title,
                "product": product_name,
                "model": str(identity.get("model") or "").strip() or None,
                "assemblyNumber": assembly_number,
                "documentNumber": document_number,
                "revision": revision,
                "releaseDate": release_date,
            },
            "revisionHistory": (
                [
                    {
                        "revision": revision,
                        "date": release_date,
                        "description": "Initial illustrated parts manual release",
                    }
                ]
                if revision
                else []
            ),
        },
        {
            "pageId": "page-contents",
            "pageNumber": 3,
            "pageType": "table_of_contents",
            "title": "Table of Contents",
            "entries": contents,
        },
        {
            "pageId": "page-assembly-overview",
            "pageNumber": 4,
            "pageType": "assembly_overview",
            "figureNumber": "1-1",
            "sectionNumber": 1,
            "title": complete_assembly_title,
            "manualGroupItems": overview_items,
            "availableManualGroupItems": generated_overview_items,
            "renderRequest": _render_request(
                scope_kind="assembly_groups",
                occurrence_ids=occurrence_ids,
                pose="group_exploded",
                visualization={
                    "cameraPreset": "isometric",
                    "explodeStrategy": "process_sequence",
                    "explodeFactor": 1.0,
                },
                callout_items=overview_items,
            ),
        },
    ]

    parts_index: Dict[str, Dict[str, Any]] = {}
    for record in section_records:
        section = record["section"]
        section_id = str(section.get("sectionId"))
        visualization = _visualization(section)
        first_bom_chunk = record["bomChunks"][0]
        shown_ids, copy_count = _shown_copy(catalog_rows, record["occurrenceIds"])
        occurrence_order = section.get("occurrenceOrder") or record["occurrenceIds"]
        if copy_count > 1:
            occurrence_order = [value for value in occurrence_order if str(value) in set(shown_ids)]
        render_request = _render_request(
            scope_kind="manual_section",
            occurrence_ids=shown_ids,
            occurrence_order=occurrence_order,
            process_operation_ids=section.get("processOperationIds") or [],
            pose="exploded",
            visualization=visualization,
            callout_items=_callout_items(record["bom"]),
        )
        if copy_count > 1:
            # The figure draws one copy; each balloon still names every copy's occurrences (its "2X").
            render_request["shownCopyCount"] = copy_count
        pages.append(
            {
                "pageId": f"page-{section_id}",
                "pageNumber": int(record["pageNumber"]),
                "pageType": "manual_section",
                "sectionId": section_id,
                "parentSectionId": section.get("parentSectionId"),
                "sectionNumber": int(record["sectionNumber"]),
                "figureNumber": str(record["figureNumber"]),
                "title": str(section.get("name") or "Manual Section"),
                "source": section.get("source"),
                "confidence": section.get("confidence"),
                "evidence": list(section.get("evidence") or []),
                "occurrenceIds": list(record["occurrenceIds"]),
                "bom": with_part_text(first_bom_chunk, part_text),
                "bomItemCount": len(record["bom"]),
                "bomContinuationCount": len(record["bomChunks"]) - 1,
                "pageLayout": _layout_mode(len(record["bom"])),
                "visualization": visualization,
                "renderRequest": render_request,
            }
        )
        for continuation_index, bom_rows in enumerate(record["bomChunks"][1:], start=1):
            pages.append(
                {
                    "pageId": f"page-{section_id}-parts-{continuation_index + 1}",
                    "pageNumber": int(record["pageNumber"]) + continuation_index,
                    "pageType": "manual_section_parts_list",
                    "sectionId": section_id,
                    "sectionNumber": int(record["sectionNumber"]),
                    "figureNumber": str(record["figureNumber"]),
                    "title": f"{section.get('name') or 'Manual Section'} - Parts List",
                    "bom": with_part_text(bom_rows, part_text),
                    "bomItemCount": len(record["bom"]),
                    "continuationIndex": continuation_index,
                }
            )
        for row in with_part_text(record["bom"], part_text):
            display_part_number = str(row.get("displayPartNumber") or "Not specified")
            key = (
                display_part_number
                if display_part_number != "Not specified"
                else f"{display_part_number}|{row.get('definitionId') or row.get('description')}"
            )
            index_row = parts_index.setdefault(
                key,
                {
                    "partNumber": display_part_number,
                    "description": str(row.get("description") or ""),
                    "references": [],
                },
            )
            index_row["references"].append(
                {
                    "figureNumber": str(record["figureNumber"]),
                    "itemNumber": int(row["item"]),
                    "pageNumber": int(record["pageNumber"]),
                    "sectionId": section_id,
                }
            )

    index_entries = sorted(
        parts_index.values(),
        key=lambda row: (
            str(row["partNumber"]).casefold(),
            str(row["description"]).casefold(),
        ),
    )
    # The index continues on further pages, as a section's parts list does; one page holds
    # PARTS_INDEX_ROWS_PER_PAGE rows.
    index_chunks = [
        index_entries[start:start + PARTS_INDEX_ROWS_PER_PAGE]
        for start in range(0, len(index_entries), PARTS_INDEX_ROWS_PER_PAGE)
    ] or [[]]
    for chunk_index, chunk in enumerate(index_chunks):
        pages.append(
            {
                "pageId": "page-parts-index" if chunk_index == 0 else f"page-parts-index-{chunk_index + 1}",
                "pageNumber": parts_index_page_number + chunk_index,
                "pageType": "parts_index",
                "title": "Part Number Index" if chunk_index == 0 else "Part Number Index (continued)",
                "entries": chunk,
                **({"continuedFrom": "page-parts-index"} if chunk_index else {}),
            }
        )
    pages.sort(key=lambda row: int(row["pageNumber"]))

    layout_contract = publication_layout()
    for page in pages:
        render_request = page.get("renderRequest")
        if not isinstance(render_request, dict):
            continue
        regions = page_layout(
            str(page.get("pageType") or ""),
            layout_mode=str(page.get("pageLayout") or ""),
            layout=layout_contract,
        )
        illustration = regions.get("illustration")
        image = render_request.get("image")
        if not isinstance(illustration, Mapping) or not isinstance(image, dict):
            continue
        inset_width = max(1.0, float(illustration["width"]) - 8.0)
        inset_height = max(1.0, float(illustration["height"]) - 8.0)
        image["targetAspectRatio"] = inset_width / inset_height
        image["publicationRect"] = copy.deepcopy(dict(illustration))

    for page in pages:
        page_override = composition_pages.get(str(page.get("pageId") or ""))
        composition = copy.deepcopy(
            page_override if isinstance(page_override, Mapping) else {}
        )
        page["documentationComposition"] = composition
        page["documentationObjects"] = copy.deepcopy(
            composition.get("documentObjects")
            if isinstance(composition.get("documentObjects"), Mapping)
            else {}
        )
        page_type = str(page.get("pageType") or "")
        page["pageMasterId"] = next(
            (
                str(master_id)
                for master_id, master in page_masters.items()
                if isinstance(master, Mapping)
                and page_type in {str(value) for value in master.get("pageTypes") or []}
            ),
            "technical",
        )
        render_request = page.get("renderRequest")
        if isinstance(render_request, dict):
            render_request["composition"] = copy.deepcopy(composition)
            render_request["figureRevision"] = figure_revision(
                assembly_number,
                str(plan.get("sourceRevision") or ""),
                render_request,
            )

    document: Dict[str, Any] = {
        "schemaVersion": PARTS_MANUAL_DOCUMENT_SCHEMA_VERSION,
        "documentType": "illustrated_parts_manual",
        "renderPipelineVersion": PARTS_MANUAL_RENDER_PIPELINE_VERSION,
        "status": "publication_ready" if callout_audit_passed else "draft_callouts",
        "manualPlanRevision": str(plan_revision),
        "documentationSceneRevision": (
            str(documentation_scene_revision)
            if documentation_scene_revision is not None
            else None
        ),
        "sourceRevision": str(plan.get("sourceRevision") or ""),
        "title": document_title,
        "documentNumber": document_number,
        "revision": revision,
        "releaseDate": release_date,
        "product": {
            "name": product_name,
            "assemblyNumber": assembly_number,
            "model": str(identity.get("model") or "").strip() or None,
        },
        "theme": document_theme,
        "pageMasters": page_masters,
        "publicationLayout": layout_contract,
        "publicationAudit": publication_audit,
        "calloutAudit": callout_audit,
        "pageCount": len(pages),
        "pages": pages,
    }
    document["documentRevision"] = _stable_revision(document)
    return document
