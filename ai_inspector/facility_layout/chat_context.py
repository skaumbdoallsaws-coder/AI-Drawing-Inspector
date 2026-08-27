"""Bounded trusted context projections for Facility Layout chat reviews."""

from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any, Dict, List

from .semantic_model import build_facility_semantic_map


FACILITY_ANALYSIS_DIGEST_MAXIMUM_BYTES = 32_768


def _metric_summary(zone: Dict[str, Any]) -> Dict[str, Any]:
    metrics = zone.get("spatialMetrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    physical = metrics.get("physicalFloorContact")
    physical = physical if isinstance(physical, dict) else {}
    geometric = metrics.get("geometricFreeArea")
    geometric = geometric if isinstance(geometric, dict) else {}
    planning = metrics.get("knownPlanningFreeArea")
    planning = planning if isinstance(planning, dict) else {}
    operational = metrics.get("operationallyUsableFreeArea")
    operational = operational if isinstance(operational, dict) else {}
    completeness = metrics.get("completeness")
    completeness = completeness if isinstance(completeness, dict) else {}
    gross_area = metrics.get("grossAreaSquareMeters")
    planning_free = planning.get("areaSquareMeters")
    operational_free = operational.get("areaSquareMeters")
    known_planning_utilization = (
        round(
            (float(gross_area) - float(planning_free))
            / float(gross_area)
            * 100.0,
            6,
        )
        if isinstance(gross_area, (int, float))
        and float(gross_area) > 1e-9
        and isinstance(planning_free, (int, float))
        else None
    )
    operational_utilization = (
        round(
            (float(gross_area) - float(operational_free))
            / float(gross_area)
            * 100.0,
            6,
        )
        if isinstance(gross_area, (int, float))
        and float(gross_area) > 1e-9
        and isinstance(operational_free, (int, float))
        and operational.get("evidenceStatus") == "derived"
        else None
    )
    return {
        "grossAreaSquareMeters": metrics.get("grossAreaSquareMeters"),
        "netPhysicalFootprintSquareMeters": physical.get(
            "netUnionAreaSquareMeters"
        ),
        "physicalCoveragePercent": physical.get("coveragePercent"),
        "geometricFreeAreaSquareMeters": geometric.get("areaSquareMeters"),
        "geometricFreePercent": geometric.get("percent"),
        "knownPlanningFreeAreaSquareMeters": planning.get("areaSquareMeters"),
        "knownPlanningUtilizationPercent": known_planning_utilization,
        "operationallyUsableFreeAreaSquareMeters": operational.get(
            "areaSquareMeters"
        ),
        "operationalUtilizationPercent": operational_utilization,
        "operationalEvidenceStatus": operational.get("evidenceStatus"),
        "operationalBlockerCodes": [
            str(item.get("code"))
            for item in completeness.get("blockers", [])
            if isinstance(item, dict) and item.get("code")
        ],
    }


def _compact_semantic_zone(zone: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "zoneId": zone.get("zoneId"),
        "label": zone.get("label"),
        "zoneType": zone.get("zoneType"),
        "semanticType": zone.get("semanticType"),
        "purpose": zone.get("purpose"),
        "purposeEvidenceStatus": zone.get("purposeEvidenceStatus"),
        "scopeKind": zone.get("scopeKind"),
        "parentZoneId": zone.get("parentZoneId"),
        "hierarchyDepth": zone.get("hierarchyDepth"),
        "childZoneCount": zone.get("childZoneCount"),
        "areaSquareMeters": zone.get("areaSquareMeters"),
        "areaSquareFeet": zone.get("areaSquareFeet"),
        "cardinalLocation": zone.get("cardinalLocation"),
        "placementCount": zone.get("placementCount"),
        "componentPlacementCount": zone.get("componentPlacementCount"),
        "cellModuleCount": zone.get("cellModuleCount"),
        "ungroupedOperationalPlacementCount": zone.get(
            "ungroupedOperationalPlacementCount"
        ),
        "operationalUnitCount": zone.get("operationalUnitCount"),
        "assetCategories": deepcopy(zone.get("assetCategories") or {}),
        "assetOperationalRoles": deepcopy(
            zone.get("assetOperationalRoles") or {}
        ),
        "connectedRouteIds": deepcopy(zone.get("connectedRouteIds") or []),
        "metrics": _metric_summary(zone),
    }


def _refresh_projection_size(value: Dict[str, Any]) -> None:
    value["canonicalUtf8Bytes"] = 0
    value["estimatedTokens"] = 0
    for _attempt in range(8):
        byte_count = len(json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii"))
        token_count = (byte_count + 3) // 4
        if (
            value["canonicalUtf8Bytes"] == byte_count
            and value["estimatedTokens"] == token_count
        ):
            return
        value["canonicalUtf8Bytes"] = byte_count
        value["estimatedTokens"] = token_count


def _zone_bounds(zone: Dict[str, Any]) -> tuple[float, float, float, float] | None:
    points = zone.get("boundary")
    if not isinstance(points, list) or len(points) < 3:
        return None
    coordinates = []
    for point in points:
        if not isinstance(point, dict):
            return None
        try:
            coordinates.append((float(point["x"]), float(point["z"])))
        except (KeyError, TypeError, ValueError):
            return None
    xs = [item[0] for item in coordinates]
    zs = [item[1] for item in coordinates]
    return min(xs), min(zs), max(xs), max(zs)


def _zone_hierarchy(
    zones: List[Dict[str, Any]],
) -> tuple[Dict[str, str | None], Dict[str, int], Dict[str, int]]:
    """Derive authored department/subzone containment from zone boundaries."""

    records = {}
    for zone in zones:
        zone_id = str(zone.get("zoneId") or "")
        bounds = _zone_bounds(zone)
        if not zone_id or bounds is None:
            continue
        area = max(0.0, bounds[2] - bounds[0]) * max(
            0.0, bounds[3] - bounds[1]
        )
        records[zone_id] = (bounds, area)

    parents: Dict[str, str | None] = {}
    epsilon = 1e-8
    for zone_id, (bounds, area) in records.items():
        candidates = []
        for candidate_id, (candidate, candidate_area) in records.items():
            if candidate_id == zone_id or candidate_area <= area + epsilon:
                continue
            contains = (
                candidate[0] <= bounds[0] + epsilon
                and candidate[1] <= bounds[1] + epsilon
                and candidate[2] >= bounds[2] - epsilon
                and candidate[3] >= bounds[3] - epsilon
            )
            if contains:
                candidates.append((candidate_area, candidate_id))
        parents[zone_id] = min(candidates)[1] if candidates else None

    depths: Dict[str, int] = {}
    for zone_id in records:
        depth = 0
        cursor = parents.get(zone_id)
        visited = {zone_id}
        while cursor and cursor not in visited:
            visited.add(cursor)
            depth += 1
            cursor = parents.get(cursor)
        depths[zone_id] = depth
    child_counts = {zone_id: 0 for zone_id in records}
    for parent_id in parents.values():
        if parent_id:
            child_counts[parent_id] = child_counts.get(parent_id, 0) + 1
    return parents, depths, child_counts


def is_zone_inventory_request(message: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not normalized:
        return False
    broad_review = re.search(
        r"\b(review|analy[sz]e|inspect|audit|summari[sz]e|list|"
        r"each|every|all|complete)\b",
        normalized,
    )
    zone_scope = re.search(
        r"\b(zones?|departments?|areas?|facility\s+layout|"
        r"factory\s+layout|plant\s+layout)\b",
        normalized,
    )
    return bool(broad_review and zone_scope)


def is_complete_zone_table_request(message: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not is_zone_inventory_request(normalized):
        return False
    if not re.search(r"\btable\b", normalized):
        return False

    # This direct renderer emits every authored zone. Require the quantifier
    # to govern zones explicitly; words such as "each" in "each cell's area"
    # or "all six departments" must remain on the semantic tool path.
    explicit_all_zone_scope = re.search(
        r"\b(?:each|every|all)(?:\s+\d+)?\s+(?:authored\s+)?zones?\b",
        normalized,
    )
    explicit_zone_inventory = re.search(
        r"\b(?:complete|full)\s+(?:authored\s+)?zone\s+"
        r"(?:inventory|list|table)\b",
        normalized,
    )
    explicit_list_of_zones = re.search(
        r"\b(?:complete|full)\s+(?:inventory|list|table)\s+of\s+"
        r"(?:the\s+)?(?:authored\s+)?zones?\b",
        normalized,
    )
    return bool(
        explicit_all_zone_scope
        or explicit_zone_inventory
        or explicit_list_of_zones
    )


def build_zone_inventory_digest(digest: Any, state: Any) -> Any:
    """Return a compact digest projection containing every authored zone."""

    if not isinstance(digest, dict) or not isinstance(state, dict):
        return digest
    zones = [
        item
        for item in state.get("zones", [])
        if isinstance(item, dict) and item.get("zoneId")
    ]
    if not zones:
        return digest

    placement_counts: Dict[str, int] = {}
    category_counts: Dict[str, Dict[str, int]] = {}
    for placement in state.get("placements", []):
        if not isinstance(placement, dict):
            continue
        category = str(placement.get("category") or "Uncategorized")
        for zone_id in placement.get("zoneIds", []) or []:
            zone_key = str(zone_id or "")
            if not zone_key:
                continue
            placement_counts[zone_key] = placement_counts.get(zone_key, 0) + 1
            category_map = category_counts.setdefault(zone_key, {})
            category_map[category] = category_map.get(category, 0) + 1

    parents, depths, child_counts = _zone_hierarchy(zones)
    labels_by_id = {
        str(zone.get("zoneId")): str(
            zone.get("label") or zone.get("zoneId")
        )
        for zone in zones
        if zone.get("zoneId")
    }

    zone_summaries = []
    for zone in sorted(
        zones,
        key=lambda item: (
            str(item.get("label") or "").casefold(),
            str(item.get("zoneId") or ""),
        ),
    ):
        zone_id = str(zone["zoneId"])
        extensions = (
            zone.get("extensions")
            if isinstance(zone.get("extensions"), dict)
            else {}
        )
        authored_purpose = zone.get("purpose") or extensions.get("purpose")
        parent_zone_id = parents.get(zone_id)
        zone_summaries.append({
            "zoneId": zone_id,
            "label": str(zone.get("label") or zone_id),
            "zoneType": str(zone.get("zoneType") or "unknown"),
            "placementCount": placement_counts.get(zone_id, 0),
            "assetCategories": dict(sorted(
                category_counts.get(zone_id, {}).items(),
                key=lambda item: item[0].casefold(),
            )),
            "authoredPurpose": (
                str(authored_purpose) if authored_purpose else None
            ),
            "purposeAuthority": (
                "authored"
                if authored_purpose
                else "infer_only_from_authored_label_and_contents"
            ),
            "parentZoneId": parent_zone_id,
            "parentZoneLabel": labels_by_id.get(parent_zone_id or ""),
            "hierarchyDepth": depths.get(zone_id, 0),
            "scopeKind": (
                "department"
                if depths.get(zone_id, 0) == 0
                else "subzone"
            ),
            "childZoneCount": child_counts.get(zone_id, 0),
        })

    summaries_by_id = {
        str(item["zoneId"]): item for item in zone_summaries
    }
    department_summaries = [
        deepcopy(summaries_by_id[str(zone["zoneId"])])
        for zone in zones
        if zone.get("zoneId")
        and depths.get(str(zone["zoneId"]), 0) == 0
        and str(zone["zoneId"]) in summaries_by_id
    ]

    projected = {
        key: deepcopy(digest[key])
        for key in (
            "digestContractVersion",
            "tokenizerId",
            "tokenizerRevision",
            "identity",
            "savedStateCurrent",
            "counts",
            "positionModes",
            "routeKinds",
            "utilityKinds",
            "findingSummary",
            "findingDetails",
            "unresolvedAuthorityGaps",
            "staleDependencies",
            "coordinateContract",
        )
        if key in digest
    }
    projected["requestProjection"] = "complete_zone_inventory"
    projected["zoneSummaries"] = zone_summaries
    projected["departmentSummaries"] = department_summaries
    projected["counts"] = deepcopy(projected.get("counts") or {})
    projected["counts"]["departments"] = len(department_summaries)
    projected["truncation"] = {
        "zoneSummaries": {
            "returnedCount": len(zone_summaries),
            "omittedCount": 0,
        },
        "assetUsage": {
            "returnedCount": 0,
            "omittedCount": len(digest.get("assetUsage", []) or []),
            "reason": "not_required_for_zone_inventory",
        },
    }
    projected["reviewInstructions"] = {
        "purpose": (
            "Use authoredPurpose when present. Otherwise describe purpose as "
            "an inference from the authored label and contained asset categories."
        ),
        "authority": (
            "Do not present unverified clearance, safety, capacity, or flow "
            "claims as validated facts."
        ),
        "hierarchy": (
            "Department summaries are hierarchyDepth 0. Nested manufacturing "
            "cells, stations, and other contained zones are subzones and must "
            "not be mixed into a department-only comparison."
        ),
    }
    return projected


def build_facility_analysis_digest(digest: Any, state: Any) -> Any:
    """Return a bounded default projection for Facility analysis.

    The default projection contains complete department metrics and a compact
    identity index for every zone. Full child-zone records remain available
    through the bounded semantic read tool, while explicit complete-zone table
    requests use ``build_zone_inventory_digest`` directly. Raw placements and
    the complete 45-zone metric payload must not enter every provider turn.
    """

    if not isinstance(digest, dict):
        return digest
    projected = deepcopy(digest)
    semantic_map = (
        build_facility_semantic_map(state)
        if isinstance(state, dict)
        else None
    )
    projected.pop("zoneSummaries", None)
    projected.pop("assetUsage", None)
    projected.pop("findingDetails", None)
    # Tool schemas already describe the read tools for the provider. Keeping
    # their verbose digest descriptors here duplicates that contract and costs
    # several thousand bytes on every analytical turn.
    projected.pop("readDescriptors", None)
    if isinstance(semantic_map, dict):
        semantic_zones = [
            item
            for item in semantic_map.get("zones", [])
            if isinstance(item, dict) and item.get("zoneId")
        ]
        projected["departmentSummaries"] = [
            _compact_semantic_zone(item)
            for item in semantic_map.get("departments", [])
            if isinstance(item, dict) and item.get("zoneId")
        ]
        projected["zoneIndex"] = [
            {
                "zoneId": item.get("zoneId"),
                "label": item.get("label"),
                "semanticType": item.get("semanticType"),
                "scopeKind": item.get("scopeKind"),
                "parentZoneId": item.get("parentZoneId"),
            }
            for item in semantic_zones
        ]
        projected["facilitySemanticSummary"] = deepcopy(
            semantic_map.get("facilitySummary")
        )
        facility_summary = projected["facilitySemanticSummary"]
        if isinstance(facility_summary, dict):
            detailed_metrics = facility_summary.pop("spatialMetrics", None)
            if isinstance(detailed_metrics, dict):
                facility_summary["metrics"] = _metric_summary({
                    "spatialMetrics": detailed_metrics,
                })
        projected["assetRoleSummary"] = deepcopy(
            semantic_map.get("assetRoleSummary")
        )
        projected["routeRoleSummary"] = deepcopy(
            semantic_map.get("routeRoleSummary")
        )
        projected["routeNetworkSummary"] = deepcopy(
            semantic_map.get("routeNetworkSummary")
        )
        projected["floorMarkingRoleSummary"] = deepcopy(
            semantic_map.get("floorMarkingRoleSummary")
        )
        projected["processRelationshipSummary"] = deepcopy(
            semantic_map.get("processRelationshipSummary")
        )
        projected["derivedMetricDefinitions"] = deepcopy(
            semantic_map.get("derivedMetricDefinitions")
        )
        projected["analysisCapabilities"] = deepcopy(
            semantic_map.get("analysisCapabilities")
        )
        projected["counts"] = deepcopy(projected.get("counts") or {})
        projected["counts"]["departments"] = len(
            projected["departmentSummaries"]
        )
        truncation = (
            deepcopy(projected.get("truncation"))
            if isinstance(projected.get("truncation"), dict)
            else {}
        )
        truncation["zoneSummaries"] = {
            "returnedCount": 0,
            "omittedCount": len(semantic_zones),
            "reason": (
                "retrieve targeted child-zone metrics through "
                "inspect_facility_semantics"
            ),
        }
        prior_asset_truncation = truncation.get("assetUsage")
        prior_asset_truncation = (
            prior_asset_truncation
            if isinstance(prior_asset_truncation, dict)
            else {}
        )
        truncation["assetUsage"] = {
            "returnedCount": 0,
            "omittedCount": int(
                prior_asset_truncation.get("returnedCount") or 0
            ) + int(prior_asset_truncation.get("omittedCount") or 0),
            "reason": "retrieve assets through bounded read tools",
        }
        truncation["zoneIndex"] = {
            "returnedCount": len(projected["zoneIndex"]),
            "omittedCount": 0,
        }
        projected["truncation"] = truncation
    projected["requestProjection"] = "facility_layout_analysis"
    projected["analysisInstructions"] = {
        "authority": (
            "Use authored values and exact derived metrics before declaring "
            "information unavailable. Keep inferred manufacturing priors "
            "separate from validated findings."
        ),
        "zones": (
            "Area is derived from exact authored polygons. Net physical "
            "footprint removes overlaps and ignores stacked objects above the "
            "floor. Keep geometric, planning, operational, and production "
            "capacity distinct."
        ),
        "hierarchy": (
            "Use departmentSummaries for department-level requests. Use "
            "zoneIndex to resolve child-zone IDs, then request exact child "
            "records with inspect_facility_semantics. Explicit complete-zone "
            "tables use the complete_zone_inventory projection. Do not mix "
            "nested subzones into a department comparison."
        ),
        "visualization": (
            "Charts must use exact numeric values from this projection and "
            "stable zone or asset IDs when available. Never substitute a "
            "different metric without the user's agreement."
        ),
        "response": (
            "Present finding, operational consequence, and recommendation. "
            "Keep evidence status in the data; mention it when it materially "
            "changes the answer rather than narrating database uncertainty."
        ),
    }
    _refresh_projection_size(projected)
    if projected["canonicalUtf8Bytes"] > (
        FACILITY_ANALYSIS_DIGEST_MAXIMUM_BYTES
    ):
        raise ValueError(
            "Facility analysis projection exceeded its 32768-byte bound."
        )
    return projected


def _markdown_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def _inferred_zone_purpose(zone: Dict[str, Any]) -> str:
    label = str(zone.get("label") or "").strip()
    normalized = label.casefold()
    patterns = (
        (("receiving", "raw material"), "Inbound receiving and raw-material staging or storage"),
        (("machining",), "Machining operations and local production support"),
        (("automation", "robot"), "Automated production and robot-cell operations"),
        (("manufacturing cell",), "Contained manufacturing-cell operations"),
        (("assembly + kitting",), "Assembly and kit preparation"),
        (("assembly cell",), "Local assembly workcell"),
        (("assembly line",), "Sequential assembly-line work"),
        (("knitting",), "Knitting workcell operations"),
        (("inspection + packing",), "Final inspection, packing, and finished-goods handling"),
        (("inspection station", "inpection station"), "Local inspection work"),
        (("packaging station",), "Local packaging work"),
        (("packaging",), "Packaging operations"),
        (("finished goods rack",), "Finished-goods storage"),
        (("equipment parking",), "Material-handling equipment parking or staging"),
        (("maintenance shop",), "Equipment maintenance and support"),
        (("material handling", "maintenance"), "Material-handling and maintenance support"),
        (("tooling", "utilities"), "Tooling storage and utility support"),
    )
    for terms, purpose in patterns:
        if any(term in normalized for term in terms):
            return f"{purpose} (inferred from authored label and contents)"
    categories = zone.get("assetCategories")
    if isinstance(categories, dict) and categories:
        category_text = ", ".join(
            f"{name}: {count}" for name, count in categories.items()
        )
        return (
            "Purpose not authored; inferred only from contained categories "
            f"({category_text})"
        )
    return "Purpose not authored; engineering review required"


def build_zone_inventory_markdown(
    digest: Any,
    state: Any,
    evidence: Any = None,
) -> str:
    """Render a complete authority-labelled zone review without model prose."""

    projected = build_zone_inventory_digest(digest, state)
    if not isinstance(projected, dict):
        return ""
    zones = projected.get("zoneSummaries")
    if not isinstance(zones, list) or not zones:
        return ""

    lines: List[str] = [
        "# Facility Layout Review",
        "",
        "| Zone | Purpose |",
        "|---|---|",
    ]
    for zone in zones:
        if not isinstance(zone, dict):
            continue
        purpose = zone.get("authoredPurpose") or _inferred_zone_purpose(zone)
        lines.append(
            f"| {_markdown_cell(zone.get('label'))} | "
            f"{_markdown_cell(purpose)} |"
        )

    unresolved = projected.get("unresolvedAuthorityGaps")
    unresolved = unresolved if isinstance(unresolved, list) else []
    default_checks = [
        (
            "Configure site policy",
            "Site-specific clearance, egress, and safety requirements must be "
            "configured before spatial safety claims can be validated.",
        ),
        (
            "Verify the facility shell",
            "Replace or confirm the starter floor boundary with reviewed site "
            "geometry before installation decisions.",
        ),
    ]
    checks = []
    for index in range(2):
        if index < len(unresolved) and isinstance(unresolved[index], dict):
            message = str(unresolved[index].get("message") or "").strip()
            code = str(unresolved[index].get("code") or "authority_gap")
            title = code.replace("_", " ").strip().capitalize()
            checks.append((title, message or default_checks[index][1]))
        else:
            checks.append(default_checks[index])

    counts = projected.get("counts") if isinstance(projected.get("counts"), dict) else {}
    evidence_records = (
        evidence.get("records")
        if isinstance(evidence, dict) and isinstance(evidence.get("records"), list)
        else []
    )
    coverage = (
        f"Review boundaries, overlaps, clearances, access routes, and material "
        f"flow across {int(counts.get('placements') or 0)} placements, "
        f"{len(zones)} zones, {int(counts.get('floorMarkings') or 0)} floor "
        f"markings, and {int(counts.get('routes') or 0)} routes. The current "
        f"trusted evidence bundle contains {len(evidence_records)} validation "
        "records; unverified conditions must not be presented as approved."
    )
    checks.append(("Complete authoritative spatial validation", coverage))

    lines.extend(["", "## Three Highest-Priority Layout Checks", ""])
    for index, (title, detail) in enumerate(checks[:3], start=1):
        lines.append(
            f"{index}. **{_markdown_cell(title)}:** {_markdown_cell(detail)}"
        )
    return "\n".join(lines)
