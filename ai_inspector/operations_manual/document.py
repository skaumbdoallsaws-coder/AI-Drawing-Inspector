"""Evidence-backed operations-manual draft compiler."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Dict, Iterable, Mapping, Optional

from ai_inspector.parts_manual.documentation import (
    DEFAULT_DOCUMENT_THEME,
    DEFAULT_PAGE_MASTERS,
)
from ai_inspector.parts_manual.catalog import build_scoped_bom
from ai_inspector.parts_manual.version import PARTS_MANUAL_DEFAULT_END_CONDITION

from .evidence import OperationsManualEvidenceRepository, release_findings
from .flow import (
    FlowLayoutEngine,
    assert_no_orphan_continuation_pages,
    assert_pages_within_bounds,
    publication_layout,
)
from .content import FIGURE_SPECS, prototype_sections
from .nomenclature import (
    load_publication_aliases,
    resolve_publication_description,
    validate_figure_nomenclature,
)


OPERATIONS_MANUAL_DOCUMENT_SCHEMA_VERSION = 1
OPERATIONS_MANUAL_RENDER_PIPELINE_VERSION = 4

_APPROVED_FACT_STATUSES = {
    "approved_for_prototype",
    "approved_for_prototype_description",
}
_PUBLICATION_POLICY_STATUSES = {
    "approved_for_figure_planning",
    "publication_rule",
}
_CRITICAL_REVIEW_STATUS_PREFIXES = (
    "blocked_",
    "not_publishable_",
    "rejected_",
)


def _load_safety_symbol_policy(evidence_root: str | Path) -> Dict[str, Any]:
    path = Path(evidence_root) / "safety-symbol-register.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("safety symbol register is missing or unreadable") from exc
    symbols = [
        copy.deepcopy(dict(row))
        for row in payload.get("symbols") or []
        if isinstance(row, Mapping)
    ]
    missing = [
        copy.deepcopy(dict(row))
        for row in payload.get("missingRequirements") or []
        if isinstance(row, Mapping) and bool(row.get("blocking", True))
    ]
    approved = str(payload.get("status") or "").casefold() == "approved" and not missing
    return {
        "register": path.name,
        "registerStatus": str(payload.get("status") or "missing"),
        "approvedAssetCount": len(symbols),
        "missingRequirements": missing,
        "controlledPublicationAllowed": approved,
        "draftRenderMode": (
            "approved_assets" if approved else "draft_geometric_fallback"
        ),
        "draftFallbackAllowed": True,
    }


def _technical_capture_dimensions(target_aspect_ratio: float) -> tuple[int, int]:
    """Return a high-resolution request that is feasible inside the GPU cap.

    A fixed 2400 x 1800 minimum is impossible for wide, shallow publication
    frames: preserving a 3:1 frame would require a 5400 px texture.  Keep the
    same 4.32 MP baseline instead, while retaining a 1200 px short-edge floor
    and a 2400 px long-edge floor.  The resulting dimensions remain below the
    browser capture ceiling (4096 x 3072) for supported page layouts.
    """

    ratio = float(target_aspect_ratio)
    if not math.isfinite(ratio) or ratio <= 0:
        raise ValueError("technical illustration aspect ratio must be positive")
    baseline_pixels = 2400 * 1800
    if ratio >= 1:
        height = max(
            1200,
            math.ceil(math.sqrt(baseline_pixels / ratio)),
            math.ceil(2400 / ratio),
        )
        width = math.ceil(height * ratio)
    else:
        width = max(
            1200,
            math.ceil(math.sqrt(baseline_pixels * ratio)),
            math.ceil(2400 * ratio),
        )
        height = math.ceil(width / ratio)
    if width > 4096 or height > 3072:
        raise ValueError(
            "technical illustration aspect ratio exceeds the supported capture envelope"
        )
    return width, height


def _technical_image_request(*, target_aspect_ratio: float, target_occupancy: float) -> Dict[str, Any]:
    minimum_width, minimum_height = _technical_capture_dimensions(target_aspect_ratio)
    return {
        "status": "pending",
        "minimumWidthPx": minimum_width,
        "minimumHeightPx": minimum_height,
        "background": "technical_white",
        "illustrationStyle": "HIDDEN_LINES_REMOVED",
        "targetAspectRatio": target_aspect_ratio,
        "targetForegroundOccupancy": target_occupancy,
        "minimumForegroundOccupancy": 0.32,
        "maximumForegroundOccupancy": 0.82,
        "maximumForegroundAxisOccupancy": 0.96,
        "axisConstrainedOccupancyPolicy": (
            "allow_when_uniform_scale_exceeds_axis_limit"
        ),
        "axisConstrainedFillTolerance": 0.025,
    }


def _stable_revision(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _manual_group_scopes(
    evidence_root: str | Path,
    assembly_number: str,
    catalog: Mapping[str, Any],
) -> Dict[str, list[str]]:
    """Load current semantic parts-plan scopes for operations-manual figures."""

    repository_root = Path(evidence_root).resolve().parents[1]
    plan_path = (
        repository_root
        / "generated"
        / "parts_manual"
        / assembly_number.lower()
        / "manual-plan.json"
    )
    eligible = {
        str(row.get("occurrenceId"))
        for row in catalog.get("occurrences") or []
        if isinstance(row, Mapping)
        and row.get("occurrenceId")
        and row.get("kind") == "part"
        and not row.get("suppressed")
    }
    if plan_path.is_file():
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            plan = {}
        if str(plan.get("sourceRevision") or "") == str(catalog.get("sourceRevision") or ""):
            scopes: Dict[str, list[str]] = {}
            for section in plan.get("sections") or []:
                if not isinstance(section, Mapping):
                    continue
                name = str(section.get("name") or "").strip()
                occurrence_ids = [
                    str(value)
                    for value in section.get("occurrenceIds") or []
                    if str(value) in eligible
                ]
                if name and occurrence_ids:
                    scopes[name] = list(dict.fromkeys(occurrence_ids))
            if scopes:
                return scopes

    def normalized_reference(value: Any) -> str:
        text = str(value or "").replace("\\", "/").rsplit("/", 1)[-1]
        text = re.sub(r"\.(?:sldasm|sldprt)$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"-\d+$", "", text)
        return re.sub(r"\s+", " ", text).strip().casefold()

    rows = [
        row
        for row in catalog.get("occurrences") or []
        if isinstance(row, Mapping)
        and str(row.get("occurrenceId") or "") in eligible
    ]
    remaining = {str(row.get("occurrenceId")) for row in rows}
    scopes = {}
    groups = (catalog.get("manualPlanning") or {}).get("groups") or []
    deferred_remaining: list[Mapping[str, Any]] = []
    for group in groups:
        if not isinstance(group, Mapping):
            continue
        if group.get("includeRemaining"):
            deferred_remaining.append(group)
            continue
        subassemblies = {
            normalized_reference(value)
            for value in group.get("subassemblyReferences") or []
        }
        direct_parts = {
            normalized_reference(value)
            for value in group.get("directPartReferences") or []
        }
        matched: list[str] = []
        for row in rows:
            occurrence_id = str(row.get("occurrenceId") or "")
            if occurrence_id not in remaining:
                continue
            path_segments = [
                normalized_reference(segment)
                for segment in str(row.get("name") or "").split("/")
            ]
            if any(segment in subassemblies for segment in path_segments[:-1]) \
                    or (path_segments and path_segments[-1] in direct_parts):
                matched.append(occurrence_id)
        if matched:
            scopes[str(group.get("name") or "")] = matched
            remaining.difference_update(matched)
    for group in deferred_remaining:
        scopes[str(group.get("name") or "")] = [
            str(row.get("occurrenceId"))
            for row in rows
            if str(row.get("occurrenceId")) in remaining
        ]
    return scopes


def _manual_group_records(
    evidence_root: str | Path,
    assembly_number: str,
    catalog: Mapping[str, Any],
) -> list[Dict[str, Any]]:
    scopes = _manual_group_scopes(evidence_root, assembly_number, catalog)
    repository_root = Path(evidence_root).resolve().parents[1]
    plan_path = (
        repository_root
        / "generated"
        / "parts_manual"
        / assembly_number.lower()
        / "manual-plan.json"
    )
    source_sections: Dict[str, Mapping[str, Any]] = {}
    if plan_path.is_file():
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            plan = {}
        if str(plan.get("sourceRevision") or "") == str(catalog.get("sourceRevision") or ""):
            source_sections = {
                str(row.get("name") or ""): row
                for row in plan.get("sections") or []
                if isinstance(row, Mapping) and row.get("name")
            }
    records: list[Dict[str, Any]] = []
    for index, (name, occurrence_ids) in enumerate(scopes.items(), start=1):
        source = source_sections.get(name) or {}
        records.append(
            {
                "sectionId": str(
                    source.get("sectionId")
                    or f"operations-group-{hashlib.sha256(name.encode('utf-8')).hexdigest()[:12]}"
                ),
                "name": name,
                "occurrenceIds": list(occurrence_ids),
                "occurrenceOrder": [
                    str(value) for value in source.get("occurrenceOrder") or occurrence_ids
                ],
                "itemAssignments": [
                    copy.deepcopy(dict(value))
                    for value in source.get("itemAssignments") or []
                    if isinstance(value, Mapping)
                ],
                "pageOrder": int(source.get("pageOrder") or index),
            }
        )
    return sorted(records, key=lambda row: (row["pageOrder"], row["name"].casefold()))


_SYSTEM_FUNCTIONS = {
    "Lift Platform Assembly": "Supports the material and provides the working load surface.",
    "Lift Mechanism Assembly": "Guides the vertical movement of the platform through the scissor structure.",
    "Hydraulic Cylinder Assembly": "Converts hydraulic pressure into lifting and lowering motion.",
    "Hydraulic Power Pack Assembly": "Supplies controlled hydraulic flow to the lift cylinder.",
    "Right Swivel Caster and Brake Assembly": "Supports steering at the right rear corner. The model includes brake hardware; verify the installed brake configuration and approved parking method.",
    "Left Swivel Caster and Brake Assembly": "Supports steering at the left rear corner. The model includes brake hardware; verify the installed brake configuration and approved parking method.",
    "Rigid Caster Assembly": "Supports the front of the lift and establishes its primary direction of travel.",
    "Caster Support Structure": "Transfers wheel loads into the base frame and maintains caster alignment.",
    "Battery and Control Assembly": "Supplies electrical power and houses the operator controls and charging components.",
    "Base Frame and Covers Assembly": "Carries the lift systems and protects the lower machine components.",
}


def _component_callout_items(
    catalog: Mapping[str, Any],
    occurrence_ids: Iterable[str],
    *,
    item_assignments: Iterable[Mapping[str, Any]] = (),
    figure_id: str,
    publication_aliases: Mapping[str, Mapping[str, Any]],
) -> list[Dict[str, Any]]:
    bom = build_scoped_bom(
        catalog.get("occurrences") or [],
        occurrence_ids,
        item_assignments=item_assignments,
    )
    items: list[Dict[str, Any]] = []
    for row in bom:
        nomenclature = resolve_publication_description(row, publication_aliases)
        items.append(
            {
            "itemNumber": int(row["item"]),
            "calloutId": f"operations-{figure_id.lower()}-item-{int(row['item'])}",
            "definitionId": str(row.get("definitionId") or ""),
            "partNumber": str(row.get("displayPartNumber") or "Not specified"),
            "description": nomenclature["displayDescription"],
            "internalDescription": str(row.get("description") or ""),
            "configuration": str(row.get("configuration") or ""),
            "nomenclatureSource": nomenclature["nomenclatureSource"],
            "quantity": int(row.get("quantity") or 1),
            "occurrenceIds": [str(value) for value in row.get("occurrenceIds") or []],
            "anchorScope": "component_instance",
            "anchorPreference": "visible_edge",
            "endCondition": PARTS_MANUAL_DEFAULT_END_CONDITION,
            }
        )
    return items


def _filter_figure_callout_items(
    items: Iterable[Mapping[str, Any]],
    spec: Mapping[str, Any],
    *,
    figure_id: str,
) -> list[Dict[str, Any]]:
    include = [
        str(value).casefold()
        for value in spec.get("descriptionIncludesAny") or []
        if str(value).strip()
    ]
    exclude = [
        str(value).casefold()
        for value in spec.get("descriptionExcludesAny") or []
        if str(value).strip()
    ]
    selected: list[Dict[str, Any]] = []
    for source in items:
        description = str(
            source.get("internalDescription") or source.get("description") or ""
        ).casefold()
        if include and not any(token in description for token in include):
            continue
        if exclude and any(token in description for token in exclude):
            continue
        selected.append(copy.deepcopy(dict(source)))
    for item_number, row in enumerate(selected, start=1):
        row["itemNumber"] = item_number
        row["calloutId"] = f"operations-{figure_id.lower()}-item-{item_number}"
    return selected


def _group_callout_items(
    group_records: Iterable[Mapping[str, Any]],
    *,
    figure_id: str,
) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
    callouts: list[Dict[str, Any]] = []
    groups: list[Dict[str, Any]] = []
    for item_number, source in enumerate(group_records, start=1):
        section_id = str(source.get("sectionId") or "")
        name = str(source.get("name") or f"System {item_number}")
        occurrence_ids = [str(value) for value in source.get("occurrenceIds") or []]
        callout_prefix = (
            "operations-overview"
            if figure_id == "OM-FIG-001"
            else f"operations-{figure_id.lower()}"
        )
        callouts.append(
            {
                "itemNumber": item_number,
                "calloutId": f"{callout_prefix}-group-{item_number}",
                "sectionId": section_id,
                "manualGroupId": section_id,
                "name": name,
                "quantity": 1,
                "occurrenceIds": occurrence_ids,
                "anchorScope": "manual_group",
                "anchorPreference": "visible_edge",
                "endCondition": PARTS_MANUAL_DEFAULT_END_CONDITION,
            }
        )
        groups.append(
            {
                "sectionId": section_id,
                "name": name,
                "occurrenceIds": occurrence_ids,
            }
        )
    return callouts, groups


def _figure_legend_items(items: Iterable[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    return [
        {
            "itemNumber": int(row.get("itemNumber") or 0),
            "label": str(row.get("description") or row.get("name") or "Component"),
            "text": str(row.get("function") or ""),
            "quantity": int(row.get("quantity") or 1),
        }
        for row in items
        if int(row.get("itemNumber") or 0) > 0
    ]


def _component_callout_coverage(
    figure_id: str,
    occurrence_ids: Iterable[str],
    items: Iterable[Mapping[str, Any]],
) -> Dict[str, Any]:
    expected = [str(value) for value in occurrence_ids if str(value)]
    expected_set = set(expected)
    item_rows = list(items)
    seen: set[str] = set()
    duplicates: list[str] = []
    for item in item_rows:
        item_occurrences = [
            str(value) for value in item.get("occurrenceIds") or [] if str(value)
        ]
        if int(item.get("quantity") or 0) != len(item_occurrences):
            raise ValueError(
                f"{figure_id} item {item.get('itemNumber')} quantity does not match "
                "its occurrence count"
            )
        for occurrence_id in item_occurrences:
            if occurrence_id in seen:
                duplicates.append(occurrence_id)
            seen.add(occurrence_id)
    missing = sorted(expected_set - seen)
    unexpected = sorted(seen - expected_set)
    if duplicates or missing or unexpected or len(expected) != len(expected_set):
        raise ValueError(
            f"{figure_id} callout coverage failed: missing={missing}, "
            f"unexpected={unexpected}, duplicates={sorted(set(duplicates))}"
        )
    return {
        "status": "PASS",
        "scopeOccurrenceCount": len(expected_set),
        "representedOccurrenceCount": len(seen),
        "itemCount": len(item_rows),
        "missingOccurrenceIds": [],
        "unexpectedOccurrenceIds": [],
        "duplicateOccurrenceIds": [],
    }


def _callout_contract() -> Dict[str, Any]:
    return {
        "anchorMethod": "frontmost_camera_raycast",
        "leaderStyle": "straight_with_orthogonal_fallback",
        "requireVisibleAnchor": True,
        "requireLeader": True,
        "maximumLeaderCrossings": 0,
        "maximumGeometryIntersections": 0,
        "defaultRepeatedPartStrategy": "representative_with_count",
        "groupAnchorScope": "manual_group",
        "defaultEndCondition": PARTS_MANUAL_DEFAULT_END_CONDITION,
    }


def _claim(snapshot: Mapping[str, Any], claim_id: str) -> Dict[str, Any]:
    row = (snapshot.get("claims") or {}).get(claim_id)
    if not isinstance(row, Mapping):
        raise ValueError(f"required evidence claim is missing: {claim_id}")
    return copy.deepcopy(dict(row))


def _evidence_citation_receipt(
    snapshot: Mapping[str, Any],
    pages: Iterable[Mapping[str, Any]],
) -> list[Dict[str, Any]]:
    """Return only registered sources cited by claims used in the document."""

    source_claims: Dict[str, set[str]] = {}
    source_pages: Dict[str, set[int]] = {}
    source_claim_page_references: Dict[str, Dict[str, set[int]]] = {}
    source_claim_anchors: Dict[str, Dict[str, set[str]]] = {}
    for page in pages:
        page_number = int(page.get("pageNumber") or 0)
        for claim_id in {
            str(value)
            for value in page.get("evidenceClaimIds") or []
            if str(value).strip()
        }:
            claim = (snapshot.get("claims") or {}).get(claim_id) or {}
            for source_id in claim.get("sourceIds") or []:
                key = str(source_id).strip()
                if not key:
                    continue
                source_claims.setdefault(key, set()).add(claim_id)
                if page_number > 0:
                    source_pages.setdefault(key, set()).add(page_number)
                claim_pages = source_claim_page_references.setdefault(
                    key, {}
                ).setdefault(claim_id, set())
                claim_anchors = source_claim_anchors.setdefault(
                    key, {}
                ).setdefault(claim_id, set())
                for location in claim.get("sourceLocations") or []:
                    if not isinstance(location, Mapping):
                        continue
                    if str(location.get("sourceId") or "").strip() != key:
                        continue
                    try:
                        source_page = int(location.get("page") or 0)
                    except (TypeError, ValueError):
                        source_page = 0
                    if source_page > 0:
                        claim_pages.add(source_page)
                    anchor = str(location.get("anchor") or "").strip()
                    if anchor:
                        claim_anchors.add(anchor)

    authority_order = {
        "OEM_CURRENT": 0,
        "OEM_LEGACY": 1,
        "INDUSTRY_GUIDANCE": 2,
        "CAD_AUTHORED": 3,
        "USER_AUTHORED": 4,
    }
    sources = snapshot.get("sources") or {}
    ordered_ids = sorted(
        source_claims,
        key=lambda source_id: (
            authority_order.get(
                str((sources.get(source_id) or {}).get("authority") or ""), 99
            ),
            str((sources.get(source_id) or {}).get("title") or source_id).casefold(),
            source_id,
        ),
    )
    receipt: list[Dict[str, Any]] = []
    for index, source_id in enumerate(ordered_ids, start=1):
        source = sources.get(source_id) or {}
        url = str(source.get("url") or "").strip() or None
        registered_location = str(
            source.get("canonicalLocation")
            or source.get("cachedLocation")
            or source.get("externalLocalLocation")
            or ""
        ).strip() or None
        claim_ids = sorted(source_claims[source_id])
        page_numbers = sorted(source_pages.get(source_id) or set())
        source_page_references = [
            {
                "claimId": claim_id,
                "sourcePageNumbers": sorted(
                    source_claim_page_references.get(source_id, {}).get(
                        claim_id, set()
                    )
                ),
                "anchors": sorted(
                    source_claim_anchors.get(source_id, {}).get(
                        claim_id, set()
                    )
                ),
            }
            for claim_id in claim_ids
        ]
        source_page_numbers = sorted(
            {
                page_number
                for reference in source_page_references
                for page_number in reference["sourcePageNumbers"]
            }
        )
        missing_source_page_claim_ids = [
            reference["claimId"]
            for reference in source_page_references
            if not reference["sourcePageNumbers"]
        ]
        source_locations = [
            source.get("url"),
            source.get("canonicalLocation"),
            source.get("cachedLocation"),
            source.get("externalLocalLocation"),
        ]
        is_pdf = any(
            str(value or "").split("?", 1)[0].lower().endswith(".pdf")
            for value in source_locations
        )
        blocking_conflicts = [
            row
            for row in snapshot.get("conflicts") or []
            if isinstance(row, Mapping)
            and bool(row.get("releaseBlocking"))
            and source_id in {str(value) for value in row.get("sourceIds") or []}
        ]
        receipt.append(
            {
                "citationNumber": index,
                "sourceId": source_id,
                "title": str(source.get("title") or source_id),
                "kind": str(source.get("kind") or "registered_evidence"),
                "authority": str(source.get("authority") or "UNKNOWN"),
                "url": url,
                "registeredLocation": registered_location,
                "accessedAt": source.get("accessedAt"),
                "sha256": source.get("sha256"),
                "claimCount": len(claim_ids),
                "pageCount": len(page_numbers),
                "claimIds": claim_ids,
                "pageNumbers": page_numbers,
                "manualPageNumbers": page_numbers,
                "isPdf": is_pdf,
                "sourcePageCount": len(source_page_numbers),
                "sourcePageNumbers": source_page_numbers,
                "sourcePageLocatorComplete": (
                    not missing_source_page_claim_ids if is_pdf else None
                ),
                "missingSourcePageClaimIds": (
                    missing_source_page_claim_ids if is_pdf else []
                ),
                "claimSourcePageReferences": source_page_references,
                "blockingConflictCount": len(blocking_conflicts),
                "blockingConflictIds": [
                    str(row.get("conflictId") or "")
                    for row in blocking_conflicts
                ],
                "blockingConflictTopics": [
                    str(row.get("topic") or "evidence_conflict")
                    for row in blocking_conflicts
                ],
            }
        )
    return receipt


def _claim_disposition_summary(
    snapshot: Mapping[str, Any],
    cited_claim_ids: set[str],
) -> Dict[str, Any]:
    claims = snapshot.get("claims") or {}
    disposition_counts: Dict[str, int] = {}
    for claim_id in sorted(cited_claim_ids):
        status = str((claims.get(claim_id) or {}).get("status") or "unknown")
        disposition_counts[status] = disposition_counts.get(status, 0) + 1
    approved_cited_ids = [
        claim_id
        for claim_id in sorted(cited_claim_ids)
        if str((claims.get(claim_id) or {}).get("status") or "")
        in _APPROVED_FACT_STATUSES
    ]
    policy_cited_ids = [
        claim_id
        for claim_id in sorted(cited_claim_ids)
        if str((claims.get(claim_id) or {}).get("status") or "")
        in _PUBLICATION_POLICY_STATUSES
    ]
    approved_registered_ids = [
        str(claim_id)
        for claim_id, claim in claims.items()
        if str((claim or {}).get("status") or "") in _APPROVED_FACT_STATUSES
    ]
    review_required_ids = sorted(
        cited_claim_ids - set(approved_cited_ids) - set(policy_cited_ids)
    )
    return {
        "claimDispositionCounts": dict(sorted(disposition_counts.items())),
        "approvedRegisteredClaimCount": len(approved_registered_ids),
        "approvedCitedClaimCount": len(approved_cited_ids),
        "approvedCitedClaimCategories": sorted(
            {
                str((claims.get(claim_id) or {}).get("category") or "")
                for claim_id in approved_cited_ids
                if str((claims.get(claim_id) or {}).get("category") or "").strip()
            }
        ),
        "policyCitedClaimCount": len(policy_cited_ids),
        "reviewRequiredCitedClaimCount": len(review_required_ids),
        "unusedRegisteredClaimCount": max(0, len(claims) - len(cited_claim_ids)),
    }


def _release_finding_summary(
    snapshot: Mapping[str, Any],
    findings: Iterable[Mapping[str, Any]],
) -> Dict[str, int]:
    finding_rows = [row for row in findings if isinstance(row, Mapping)]
    blocking_conflicts = [
        row for row in finding_rows
        if bool(row.get("blocking", True))
        and str(row.get("findingType") or row.get("code") or "")
        in {"evidence_conflict", "EVIDENCE_CONFLICT"}
    ]
    blocking_gaps = [
        row for row in finding_rows
        if bool(row.get("blocking", True))
        and str(row.get("findingType") or row.get("code") or "")
        in {"evidence_gap", "EVIDENCE_GAP"}
    ]
    governance = [
        row for row in finding_rows
        if bool(row.get("blocking", True))
        and row not in blocking_conflicts
        and row not in blocking_gaps
    ]
    conflicts = [row for row in snapshot.get("conflicts") or [] if isinstance(row, Mapping)]
    gaps = [row for row in snapshot.get("gaps") or [] if isinstance(row, Mapping)]
    return {
        "conflictCount": len(conflicts),
        "blockingConflictCount": len(blocking_conflicts),
        "nonBlockingConflictCount": max(0, len(conflicts) - len(blocking_conflicts)),
        "gapCount": len(gaps),
        "blockingGapCount": len(blocking_gaps),
        "blockingEvidenceFindingCount": len(blocking_conflicts) + len(blocking_gaps),
        "governancePrerequisiteCount": len(governance),
    }


def _review_priority_sections(
    snapshot: Mapping[str, Any],
    pages: Iterable[Mapping[str, Any]],
) -> list[Dict[str, Any]]:
    claims = snapshot.get("claims") or {}
    sections: Dict[str, Dict[str, Any]] = {}
    for page in pages:
        section_id = str(page.get("sectionId") or "").strip()
        if not section_id:
            continue
        row = sections.setdefault(
            section_id,
            {
                "sectionId": section_id,
                "title": str(page.get("title") or section_id).replace(" (continued)", ""),
                "pageNumber": int(page.get("pageNumber") or 0),
                "criticalClaimIds": set(),
            },
        )
        row["pageNumber"] = min(row["pageNumber"], int(page.get("pageNumber") or 0))
        for claim_id in page.get("evidenceClaimIds") or []:
            key = str(claim_id)
            status = str((claims.get(key) or {}).get("status") or "")
            if status.startswith(_CRITICAL_REVIEW_STATUS_PREFIXES):
                row["criticalClaimIds"].add(key)
    candidates = [
        {
            "sectionId": row["sectionId"],
            "title": row["title"],
            "pageNumber": row["pageNumber"],
            "criticalClaimCount": len(row["criticalClaimIds"]),
        }
        for row in sections.values()
        if row["criticalClaimIds"]
    ]
    selected = sorted(
        candidates,
        key=lambda row: (-row["criticalClaimCount"], row["pageNumber"], row["sectionId"]),
    )[:2]
    return sorted(selected, key=lambda row: (row["pageNumber"], row["sectionId"]))


def evaluate_release_gate(
    findings: Iterable[Mapping[str, Any]],
) -> Dict[str, Any]:
    finding_rows = [copy.deepcopy(dict(row)) for row in findings]
    blocking = [row for row in finding_rows if bool(row.get("blocking", True))]
    for row in blocking:
        row.setdefault("blockingScope", "controlled_release")
    controlled_release_allowed = not blocking
    return {
        "status": "READY" if controlled_release_allowed else "REVIEW_READY",
        "findings": finding_rows,
        "blockingFindingCount": len(blocking),
        "controlledReleasePrerequisiteCount": len(blocking),
        "draftPreviewAllowed": True,
        "reviewPdfAllowed": True,
        "reviewDocxAllowed": True,
        "controlledReleaseStatus": (
            "READY" if controlled_release_allowed else "PENDING_APPROVAL"
        ),
        "controlledPdfAllowed": controlled_release_allowed,
        "controlledDocxAllowed": controlled_release_allowed,
        "evaluation": "computed_from_controlled_release_prerequisites",
    }


def _specification_rows(snapshot: Mapping[str, Any]) -> list[Dict[str, Any]]:
    labels = [
        ("CLM-SPEC-001", "Rated capacity"),
        ("CLM-SPEC-002", "Vertical travel"),
        ("CLM-SPEC-003", "Lowered height"),
        ("CLM-SPEC-004", "Raised height"),
        ("CLM-SPEC-005", "Platform size"),
        ("CLM-SPEC-006", "Shipping weight"),
        ("CLM-ELECTRICAL-001", "Battery"),
        ("CLM-ELECTRICAL-002", "Charger"),
    ]
    rows: list[Dict[str, Any]] = []
    for claim_id, label in labels:
        claim = _claim(snapshot, claim_id)
        value = claim.get("value")
        unit = str(claim.get("unit") or "")
        if isinstance(value, Mapping):
            value_text = " x ".join(str(value[key]) for key in ("width", "length") if key in value)
            value_text = f"{value_text} {unit}".strip()
        elif value is not None:
            value_text = f"{value} {unit}".strip()
        else:
            statement = str(claim.get("statement") or "")
            value_text = statement.split("uses ", 1)[-1].rstrip(".") if "uses " in statement else statement
        rows.append(
            {
                "cells": [
                    label,
                    value_text,
                    "Review required" if "review_required" in str(claim.get("status")) else "OEM current",
                ],
                "claimIds": [claim_id],
                "sourceIds": list(claim.get("sourceIds") or []),
            }
        )
    return rows


def _source_rows(snapshot: Mapping[str, Any], claim_ids: Iterable[str]) -> list[Dict[str, Any]]:
    source_ids: set[str] = set()
    for claim_id in claim_ids:
        source_ids.update(_claim(snapshot, claim_id).get("sourceIds") or [])
    rows: list[Dict[str, Any]] = []
    for source_id in sorted(source_ids):
        source = (snapshot.get("sources") or {}).get(source_id) or {}
        rows.append(
            {
                "cells": [
                    source_id,
                    str(source.get("title") or source.get("name") or "Registered source"),
                    str(source.get("sourceType") or source.get("type") or "Evidence"),
                ],
                "sourceIds": [source_id],
            }
        )
    return rows


def _draft_sections(snapshot: Mapping[str, Any]) -> list[Dict[str, Any]]:
    identity = _claim(snapshot, "CLM-IDENTITY-001")
    use = _claim(snapshot, "CLM-USE-001")
    cad = _claim(snapshot, "CLM-CAD-001")
    overview_text = (
        f"{identity['statement']} {use['statement']} "
        "These published examples do not establish complete application authorization."
    )
    claim_ids = [
        "CLM-IDENTITY-001",
        "CLM-USE-001",
        "CLM-CAD-001",
        "CLM-SPEC-001",
        "CLM-SPEC-002",
        "CLM-SPEC-003",
        "CLM-SPEC-004",
        "CLM-SPEC-005",
        "CLM-SPEC-006",
        "CLM-ELECTRICAL-001",
        "CLM-ELECTRICAL-002",
    ]
    return [
        {
            "sectionId": "product-overview",
            "title": "Product Overview",
            "blocks": [
                {
                    "blockId": "overview-heading",
                    "blockType": "heading",
                    "readingOrder": 0,
                    "evidenceClaimIds": [],
                    "payload": {"level": 1, "text": "Product Overview"},
                },
                {
                    "blockId": "overview-purpose",
                    "blockType": "paragraph",
                    "readingOrder": 1,
                    "evidenceClaimIds": ["CLM-IDENTITY-001", "CLM-USE-001"],
                    "payload": {"text": overview_text},
                },
                {
                    "blockId": "overview-figure",
                    "blockType": "cad_figure",
                    "readingOrder": 2,
                    "evidenceClaimIds": ["CLM-CAD-001"],
                    "payload": {
                        "figureId": "OM-FIG-001",
                        "height": 330,
                        "caption": "MMLE-50D complete assembly - technical identification view",
                    },
                },
                {
                    "blockId": "overview-cad-scope",
                    "blockType": "note",
                    "readingOrder": 3,
                    "evidenceClaimIds": ["CLM-CAD-001"],
                    "payload": {
                        "tone": "information",
                        "text": cad["statement"],
                    },
                },
            ],
        },
        {
            "sectionId": "specifications",
            "title": "Specifications",
            "blocks": [
                {
                    "blockId": "specifications-heading",
                    "blockType": "heading",
                    "readingOrder": 0,
                    "evidenceClaimIds": [],
                    "payload": {"level": 1, "text": "Specifications"},
                },
                {
                    "blockId": "specifications-intro",
                    "blockType": "paragraph",
                    "readingOrder": 1,
                    "evidenceClaimIds": [],
                    "payload": {
                        "text": (
                            "Published values are retained with their source meaning. "
                            "Shipping weight is not relabeled as operating weight, and "
                            "electrical configuration remains subject to review."
                        )
                    },
                },
                {
                    "blockId": "specifications-table",
                    "blockType": "specification_table",
                    "readingOrder": 2,
                    "evidenceClaimIds": claim_ids[3:],
                    "payload": {
                        "columns": ["Characteristic", "Value", "Evidence status"],
                        "rows": _specification_rows(snapshot),
                    },
                },
                {
                    "blockId": "specifications-limit",
                    "blockType": "note",
                    "readingOrder": 3,
                    "evidenceClaimIds": [],
                    "payload": {
                        "tone": "warning",
                        "text": (
                            "Operating limits for load distribution, duty cycle, "
                            "environment, floor condition, and slope are not approved. "
                            "This draft must not be used to operate the machine."
                        ),
                    },
                },
            ],
        },
        {
            "sectionId": "evidence-and-review",
            "title": "Evidence and Review Status",
            "blocks": [
                {
                    "blockId": "evidence-heading",
                    "blockType": "heading",
                    "readingOrder": 0,
                    "evidenceClaimIds": [],
                    "payload": {"level": 1, "text": "Evidence and Review Status"},
                },
                {
                    "blockId": "evidence-note",
                    "blockType": "note",
                    "readingOrder": 1,
                    "evidenceClaimIds": [],
                    "payload": {
                        "tone": "draft",
                        "text": (
                            "DRAFT - NOT FOR OPERATION. Safety procedures, maintenance "
                            "instructions, charging, parking, compliance statements, and "
                            "controlled release are intentionally excluded until their "
                            "blocking evidence and approvals are resolved."
                        ),
                    },
                },
                {
                    "blockId": "evidence-sources",
                    "blockType": "source_table",
                    "readingOrder": 2,
                    "evidenceClaimIds": claim_ids,
                    "payload": {
                        "columns": ["Source ID", "Registered source", "Class"],
                        "rows": _source_rows(snapshot, claim_ids),
                    },
                },
            ],
        },
    ]


def _front_matter_pages(product_name: str, document_number: str, findings: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    layout = publication_layout()
    page_types = layout["pageTypes"]
    cover_layout = page_types["operations_cover"]
    control_layout = page_types["operations_document_control"]
    return [
        {
            "pageId": "page-operations-cover",
            "pageNumber": 1,
            "pageType": "operations_cover",
            "title": f"{product_name} Operations and Maintenance Manual",
            "layoutBlocks": [
                {
                    "blockId": "cover-kicker",
                    "blockType": "cover_kicker",
                    "text": "OPERATIONS AND MAINTENANCE MANUAL",
                    "lines": ["OPERATIONS AND MAINTENANCE MANUAL"],
                    "style": {
                        "fontSize": 16,
                        "lineHeight": 22,
                        "fontWeight": 700,
                        "color": "#43B5EE",
                    },
                    "frame": copy.deepcopy(cover_layout["kicker"]),
                    "evidenceClaimIds": ["CLM-IDENTITY-001"],
                },
                {
                    "blockId": "cover-product",
                    "blockType": "cover_title",
                    "text": product_name,
                    "lines": [product_name],
                    "style": {
                        "fontSize": 30,
                        "lineHeight": 36,
                        "fontWeight": 700,
                        "color": "#071B2A",
                    },
                    "frame": copy.deepcopy(cover_layout["title"]),
                    "evidenceClaimIds": ["CLM-IDENTITY-001"],
                },
            ],
            "renderRequest": {
                "scopeKind": "assembly",
                "occurrenceIds": [],
                "pose": "assembled",
                "cameraPreset": "isometric",
                "displayStyle": "hidden_lines_removed",
                "showItemCallouts": False,
                "frame": copy.deepcopy(cover_layout["illustration"]),
                "image": _technical_image_request(
                    target_aspect_ratio=(
                        cover_layout["illustration"]["width"]
                        / cover_layout["illustration"]["height"]
                    ),
                    target_occupancy=0.54,
                ),
            },
        },
        {
            "pageId": "page-operations-document-control",
            "pageNumber": 2,
            "pageType": "operations_document_control",
            "title": "Document Control",
            "layoutBlocks": [
                {
                    "blockId": "control-heading",
                    "blockType": "heading",
                    "text": "Document Control",
                    "lines": ["Document Control"],
                    "style": {"fontSize": 20, "lineHeight": 25, "fontWeight": 700, "color": "#071B2A"},
                    "frame": copy.deepcopy(control_layout["heading"]),
                    "evidenceClaimIds": [],
                },
                {
                    "blockId": "control-table",
                    "blockType": "key_value_table",
                    "columns": ["Field", "Value"],
                    "rows": [
                        {"cells": ["Document title", f"{product_name} Operations and Maintenance Manual"]},
                        {"cells": ["Document number", document_number]},
                        {"cells": ["Product document revision", "Not specified"]},
                        {"cells": ["Configuration effectivity", "Not specified"]},
                        {"cells": ["Status", "DRAFT"]},
                        {"cells": ["PDF / DOCX", "Available for document review"]},
                        {"cells": ["Approval", "Final approval pending"]},
                        {"cells": ["Revision history", "Initial review issue; product document revision not specified"]},
                    ],
                    "frame": copy.deepcopy(control_layout["table"]),
                    "evidenceClaimIds": ["CLM-REVISION-001"],
                },
                {
                    "blockId": "control-status",
                    "blockType": "note",
                    "text": (
                        "Confirm configuration effectivity, current manufacturer information, "
                        "and required approvals before final release."
                    ),
                    "lines": [
                        "Confirm configuration effectivity, current manufacturer information, and required approvals before final release."
                    ],
                    "tone": "notice",
                    "frame": copy.deepcopy(control_layout["status"]),
                    "evidenceClaimIds": [],
                },
            ],
        },
        {
            "pageId": "page-operations-contents",
            "pageNumber": 3,
            "pageType": "operations_contents",
            "title": "Table of Contents",
            "layoutBlocks": [],
        },
    ]


def _apply_scene(
    pages: list[Dict[str, Any]],
    documentation_scene: Optional[Mapping[str, Any]],
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    scene = documentation_scene if isinstance(documentation_scene, Mapping) else {}
    composition_pages = scene.get("pages") if isinstance(scene.get("pages"), Mapping) else {}
    theme = copy.deepcopy(scene.get("theme") if isinstance(scene.get("theme"), Mapping) else DEFAULT_DOCUMENT_THEME)
    page_masters = copy.deepcopy(
        scene.get("pageMasters") if isinstance(scene.get("pageMasters"), Mapping) else DEFAULT_PAGE_MASTERS
    )
    for page in pages:
        page_id = str(page.get("pageId") or "")
        composition = copy.deepcopy(
            composition_pages.get(page_id)
            if isinstance(composition_pages.get(page_id), Mapping)
            else {}
        )
        # The cover is an assembled product identity view. Component-level
        # presentation transforms would turn it into an unlabelled exploded
        # view, so only whole-figure and page-object overrides apply there.
        if page.get("pageType") == "operations_cover":
            composition.pop("manualGroupOverrides", None)
            composition.pop("occurrenceOverrides", None)
        page["documentationComposition"] = composition
        page["documentationObjects"] = copy.deepcopy(
            composition.get("documentObjects")
            if isinstance(composition.get("documentObjects"), Mapping)
            else {}
        )
        page["pageMasterId"] = "cover" if page.get("pageType") == "operations_cover" else "reference"
        if isinstance(page.get("renderRequest"), dict):
            page["renderRequest"]["composition"] = copy.deepcopy(composition)
    return theme, page_masters


def build_operations_manual_document(
    assembly_data: Mapping[str, Any],
    catalog: Mapping[str, Any],
    *,
    evidence_root: str | Path,
    documentation_scene: Optional[Mapping[str, Any]] = None,
    documentation_scene_revision: Optional[str] = None,
) -> Dict[str, Any]:
    repository = OperationsManualEvidenceRepository(evidence_root)
    snapshot = repository.snapshot()
    assembly_number = str(catalog.get("assemblyNumber") or "")
    identity_statement = str(
        _claim(snapshot, "CLM-IDENTITY-001").get("statement") or ""
    ).strip()
    evidence_product_name = identity_statement.removeprefix(
        "The target product is the "
    ).rstrip(".")
    product_name = str(
        evidence_product_name
        or (assembly_data.get("identity") or {}).get("description")
        or (assembly_data.get("identity") or {}).get("name")
        or assembly_number
        or "Product"
    )
    document_number = f"OM-{assembly_number.upper()}-001"
    findings = release_findings(snapshot)
    safety_symbol_policy = _load_safety_symbol_policy(evidence_root)
    if (
        not safety_symbol_policy["controlledPublicationAllowed"]
        and not any(
            str(row.get("code") or "") == "STANDARDS_EDITION_REVIEW_REQUIRED"
            for row in findings
        )
    ):
        findings.append(
            {
                "findingId": "SAFETY-SYMBOL-ASSETS",
                "code": "SAFETY_SYMBOL_ASSETS_REQUIRED",
                "severity": "P1",
                "message": (
                    "Approved safety-symbol assets are required for controlled release."
                ),
                "blocking": True,
                "sourceIds": [],
            }
        )
    occurrence_ids = [
        str(row.get("occurrenceId"))
        for row in catalog.get("occurrences") or []
        if isinstance(row, Mapping)
        and row.get("occurrenceId")
        and row.get("kind") == "part"
        and not row.get("suppressed")
    ]
    group_records = _manual_group_records(evidence_root, assembly_number, catalog)
    publication_aliases = load_publication_aliases(evidence_root, assembly_number)
    group_scopes = {
        str(row["name"]): list(row["occurrenceIds"])
        for row in group_records
    }
    group_by_name = {str(row["name"]): row for row in group_records}
    overview_callouts, overview_groups = _group_callout_items(
        group_records,
        figure_id="OM-FIG-001",
    )
    for row in overview_callouts:
        row["function"] = _SYSTEM_FUNCTIONS.get(
            str(row.get("name") or ""),
            "Identifies a functional system in the complete machine.",
        )
    figure_callouts: Dict[str, list[Dict[str, Any]]] = {
        "OM-FIG-001": overview_callouts,
    }
    figure_group_items: Dict[str, list[Dict[str, Any]]] = {
        "OM-FIG-001": overview_groups,
    }
    for figure_id, spec in FIGURE_SPECS.items():
        if figure_id == "OM-FIG-001":
            continue
        names = [str(value) for value in spec.get("groupNames") or []]
        if str(spec.get("calloutScope") or "") == "manual_group":
            selected_groups = [
                group_by_name[name]
                for name in names
                if name in group_by_name
            ]
            group_callouts, group_items = _group_callout_items(
                selected_groups,
                figure_id=figure_id,
            )
            for row in group_callouts:
                row["function"] = _SYSTEM_FUNCTIONS.get(
                    str(row.get("name") or ""),
                    "Identifies a functional system in the machine.",
                )
            figure_callouts[figure_id] = group_callouts
            figure_group_items[figure_id] = group_items
            continue
        if str(spec.get("pose") or "") != "exploded":
            continue
        scoped_ids = list(
            dict.fromkeys(
                occurrence_id
                for name in names
                for occurrence_id in group_scopes.get(name, [])
            )
        )
        assignments = [
            assignment
            for name in names
            for assignment in (group_by_name.get(name) or {}).get("itemAssignments") or []
        ]
        if scoped_ids:
            all_items = _component_callout_items(
                catalog,
                scoped_ids,
                item_assignments=assignments,
                figure_id=figure_id,
                publication_aliases=publication_aliases,
            )
            figure_callouts[figure_id] = _filter_figure_callout_items(
                all_items,
                spec,
                figure_id=figure_id,
            )
            validate_figure_nomenclature(
                figure_id,
                figure_callouts[figure_id],
            )
    figure_legends = {
        figure_id: _figure_legend_items(items)
        for figure_id, items in figure_callouts.items()
    }
    sections = prototype_sections(
        snapshot,
        figure_legends=figure_legends,
        overview_systems=figure_legends.get("OM-FIG-001", []),
    )
    flow_pages = FlowLayoutEngine(start_page_number=4).layout(sections)
    assert_pages_within_bounds(flow_pages)
    assert_no_orphan_continuation_pages(flow_pages)
    pages = _front_matter_pages(product_name, document_number, findings) + flow_pages
    for figure_page in pages:
        figure_block = next(
            (
                block
                for block in figure_page.get("layoutBlocks") or []
                if str(block.get("figureId") or "") in FIGURE_SPECS
            ),
            None,
        )
        if not isinstance(figure_block, Mapping):
            continue
        figure_id = str(figure_block.get("figureId") or "")
        spec = FIGURE_SPECS[figure_id]
        scoped_ids: list[str] = []
        for group_name in spec.get("groupNames") or []:
            scoped_ids.extend(group_scopes.get(str(group_name), []))
        scoped_ids = list(dict.fromkeys(scoped_ids))
        if spec.get("scopeKind") == "assembly":
            scoped_ids = occurrence_ids
        elif figure_callouts.get(figure_id):
            scoped_ids = list(
                dict.fromkeys(
                    occurrence_id
                    for row in figure_callouts[figure_id]
                    for occurrence_id in row.get("occurrenceIds") or []
                )
            )
        if not scoped_ids:
            # A visible assembly fallback is safer than an empty stale figure.
            scoped_ids = occurrence_ids
        figure_frame = figure_block.get("frame") or {}
        figure_width = max(180.0, float(figure_frame.get("width") or 848.0))
        figure_height = max(
            180.0,
            float(figure_frame.get("height") or 320) - 18.0,
        )
        component_callouts = [
            row
            for row in figure_callouts.get(figure_id) or []
            if row.get("anchorScope") == "component_instance"
        ]
        callout_coverage = (
            _component_callout_coverage(figure_id, scoped_ids, component_callouts)
            if component_callouts
            else None
        )
        figure_page["renderRequest"] = {
            "figureId": figure_id,
            "scopeKind": str(spec.get("scopeKind") or "manual_group"),
            "manualGroupNames": list(spec.get("groupNames") or []),
            "occurrenceIds": scoped_ids,
            "occurrenceOrder": scoped_ids,
            "pose": str(spec.get("pose") or "assembled"),
            "cameraPreset": str(spec.get("cameraPreset") or "isometric"),
            "explodeStrategy": "radial",
            "explodeFactor": float(spec.get("explodeFactor") or 0.0),
            "displayStyle": "hidden_lines_removed",
            "showItemCallouts": bool(figure_callouts.get(figure_id)),
            "calloutItems": copy.deepcopy(figure_callouts.get(figure_id) or []),
            "calloutContract": _callout_contract(),
            "image": _technical_image_request(
                target_aspect_ratio=figure_width / figure_height,
                target_occupancy=0.66,
            ),
        }
        if callout_coverage is not None:
            figure_page["renderRequest"]["calloutCoverage"] = callout_coverage
        group_items = figure_group_items.get(figure_id) or []
        if group_items:
            figure_page["availableManualGroupItems"] = copy.deepcopy(group_items)
            figure_page["manualGroupItems"] = copy.deepcopy(group_items)
            figure_page["renderRequest"]["manualGroupItems"] = copy.deepcopy(
                group_items
            )
    pages[0]["renderRequest"]["occurrenceIds"] = occurrence_ids
    section_first_pages: Dict[str, int] = {}
    for page in flow_pages:
        section_first_pages.setdefault(str(page.get("sectionId") or ""), int(page["pageNumber"]))
    contents = [
        {"title": "Document Control", "pageNumber": 2},
        {"title": "Table of Contents", "pageNumber": 3},
        *[
            {"title": str(section.get("title") or ""), "pageNumber": section_first_pages[str(section.get("sectionId") or "")]}
            for section in sections
        ],
    ]
    contents_layout = publication_layout()["pageTypes"]["operations_contents"]
    pages[2]["entries"] = contents
    pages[2]["layoutBlocks"] = [
        {
            "blockId": "contents-heading",
            "blockType": "heading",
            "text": "Table of Contents",
            "lines": ["Table of Contents"],
            "style": {"fontSize": 20, "lineHeight": 25, "fontWeight": 700, "color": "#071B2A"},
            "frame": copy.deepcopy(contents_layout["heading"]),
            "evidenceClaimIds": [],
        },
        {
            "blockId": "contents-list",
            "blockType": "contents_list",
            "entries": [
                {
                    "title": row["title"],
                    "pageNumber": int(row["pageNumber"]),
                    "level": 0,
                }
                for row in contents
            ],
            "frame": copy.deepcopy(contents_layout["list"]),
            "evidenceClaimIds": [],
        },
    ]
    for page in pages:
        page["pageCount"] = len(pages)
    theme, page_masters = _apply_scene(pages, documentation_scene)
    evidence_citations = _evidence_citation_receipt(snapshot, pages)
    cited_claim_ids = {
        claim_id
        for citation in evidence_citations
        for claim_id in citation.get("claimIds") or []
    }
    claim_disposition_summary = _claim_disposition_summary(
        snapshot,
        cited_claim_ids,
    )
    release_finding_summary = _release_finding_summary(snapshot, findings)
    review_priority_sections = _review_priority_sections(snapshot, pages)
    release_gate = evaluate_release_gate(findings)
    plan_revision = _stable_revision(
        {
            "assemblyNumber": assembly_number,
            "sourceRevision": catalog.get("sourceRevision"),
            "evidenceRevision": snapshot["revision"],
            "sections": sections,
        }
    )
    document: Dict[str, Any] = {
        "schemaVersion": OPERATIONS_MANUAL_DOCUMENT_SCHEMA_VERSION,
        "renderPipelineVersion": OPERATIONS_MANUAL_RENDER_PIPELINE_VERSION,
        "documentType": "operations_and_maintenance_manual",
        "status": "draft_review",
        "sourceRevision": str(catalog.get("sourceRevision") or ""),
        "evidenceRevision": str(snapshot["revision"]),
        "manualPlanRevision": plan_revision,
        "documentationSceneRevision": documentation_scene_revision,
        "title": f"{product_name} Operations and Maintenance Manual",
        "documentNumber": document_number,
        "revision": None,
        "product": {
            "name": product_name,
            "assemblyNumber": assembly_number,
            "model": assembly_number,
        },
        "theme": theme,
        "pageMasters": page_masters,
        "publicationLayout": publication_layout(),
        "safetySymbolPolicy": safety_symbol_policy,
        "pageCount": len(pages),
        "pages": pages,
        "evidenceCitations": evidence_citations,
        "evidenceSummary": {
            "asOf": snapshot.get("asOf"),
            "claimCount": len(snapshot.get("claims") or {}),
            "sourceCount": len(snapshot.get("sources") or {}),
            "registeredClaimCount": len(snapshot.get("claims") or {}),
            "registeredSourceCount": len(snapshot.get("sources") or {}),
            "citedClaimCount": len(cited_claim_ids),
            "citedSourceCount": len(evidence_citations),
            "claimContributingSourceCount": len(evidence_citations),
            "blockingFindingCount": len(findings),
            "controlledReleasePrerequisiteCount": len(findings),
            "reviewPrioritySections": review_priority_sections,
            **claim_disposition_summary,
            **release_finding_summary,
        },
        "releaseGate": release_gate,
    }
    document["documentRevision"] = _stable_revision(document)
    return document
