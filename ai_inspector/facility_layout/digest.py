"""Deterministic bounded Facility Layout digest for Sage.

Exact geometry remains in ``facility_layout.state`` for deterministic tools.
The model receives aggregate facts, selected/active entities, high-priority
findings, and stable-ID descriptors for bounded follow-up reads.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import json
from typing import Any, Mapping, Sequence

from .observation import (
    FacilityObservationError,
    TrustedFacilityContext,
    assert_trusted_facility_context,
)


FACILITY_LAYOUT_DIGEST_CONTRACT_VERSION = 1
FACILITY_LAYOUT_DIGEST_TOKENIZER_ID = "inspectorpro_utf8_quarter_v1"
FACILITY_LAYOUT_DIGEST_TOKENIZER_REVISION = 1
FACILITY_LAYOUT_DIGEST_MAXIMUM_TOKENS = 4500
FACILITY_LAYOUT_DIGEST_MAXIMUM_CANONICAL_UTF8_BYTES = 24_576
FACILITY_LAYOUT_READ_PAGE_SIZE = 50

_SEVERITY_PRIORITY = {
    "blocked": 0,
    "error": 1,
    "unverified": 2,
    "warning": 3,
    "info": 4,
}
_DESCRIPTOR_CONFIG = (
    ("placements", "placementId", "placement", "inspect_facility_entities"),
    ("zones", "zoneId", "zone", "inspect_facility_entities"),
    ("routes", "routeId", "route", "inspect_facility_entities"),
    (
        "utilityNetworks",
        "utilityNetworkId",
        "utility_network",
        "inspect_facility_entities",
    ),
    (
        "processBindings",
        "processBindingId",
        "process_binding",
        "inspect_process_bindings",
    ),
)


class FacilityDigestError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def canonical_facility_digest_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FacilityDigestError(
            "invalid_facility_digest",
            "Facility Layout digest must contain finite JSON values.",
        ) from exc


def estimate_facility_digest_tokens(value: Mapping[str, Any]) -> int:
    return (len(canonical_facility_digest_bytes(value)) + 3) // 4


def _text(value: Any, maximum: int = 240) -> str:
    return " ".join(str(value or "").split())[:maximum]


def _counter_records(
    values: Sequence[str],
    *,
    key: str,
    limit: int = 40,
) -> tuple[list[dict[str, Any]], int]:
    counter = Counter(values)
    records = [
        {key: name, "count": count}
        for name, count in sorted(
            counter.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]
    return records[:limit], max(0, len(records) - limit)


def _entity_ids(
    state: Mapping[str, Any],
    collection: str,
    id_field: str,
) -> list[str]:
    return sorted(
        {
            str(item[id_field])
            for item in state.get(collection, [])
            if isinstance(item, Mapping) and item.get(id_field)
        }
    )


def _selection_ids(state: Mapping[str, Any]) -> set[str]:
    selection = state.get("selection")
    if not isinstance(selection, Mapping):
        return set()
    return {
        str(item)
        for values in selection.values()
        if isinstance(values, list)
        for item in values
        if isinstance(item, str)
    }


def _active_entity_ids(state: Mapping[str, Any]) -> set[str]:
    proposal = state.get("activeProposal")
    if not isinstance(proposal, Mapping):
        return set()
    return {
        str(item)
        for item in proposal.get("entityIds", [])
        if isinstance(item, str)
    }


def _read_descriptors(
    state: Mapping[str, Any],
    *,
    priority_ids: set[str],
    sample_limit: int = 12,
) -> list[dict[str, Any]]:
    result = []
    for collection, id_field, entity_kind, tool in _DESCRIPTOR_CONFIG:
        identifiers = _entity_ids(state, collection, id_field)
        prioritized = [
            item for item in identifiers if item in priority_ids
        ]
        remainder = [
            item for item in identifiers if item not in priority_ids
        ]
        samples = (prioritized + remainder)[:sample_limit]
        result.append(
            {
                "collection": collection,
                "entityKind": entity_kind,
                "stableIdField": id_field,
                "totalCount": len(identifiers),
                "returnedCount": len(samples),
                "omittedCount": max(0, len(identifiers) - len(samples)),
                "sampleIds": samples,
                "readTool": tool,
                "stableSortKey": id_field,
                "maximumPageSize": FACILITY_LAYOUT_READ_PAGE_SIZE,
                "pagination": "opaque_revision_bound_cursor",
            }
        )
    assets = sorted(
        {
            (
                str(item.get("assetId") or ""),
                str(item.get("assetDefinitionRevision") or ""),
            )
            for item in state.get("assets", [])
            if isinstance(item, Mapping) and item.get("assetId")
        }
    )
    asset_samples = [
        {
            "assetId": asset_id,
            "assetDefinitionRevision": revision,
        }
        for asset_id, revision in assets[:sample_limit]
    ]
    result.append(
        {
            "collection": "assets",
            "entityKind": "industrial_asset",
            "stableIdField": "assetId+assetDefinitionRevision",
            "totalCount": len(assets),
            "returnedCount": len(asset_samples),
            "omittedCount": max(0, len(assets) - len(asset_samples)),
            "sampleIds": asset_samples,
            "readTool": "search_industrial_assets",
            "stableSortKey": "assetId,assetDefinitionRevision",
            "maximumPageSize": FACILITY_LAYOUT_READ_PAGE_SIZE,
            "pagination": "opaque_revision_bound_cursor",
        }
    )
    findings = sorted(
        {
            str(item.get("findingId"))
            for item in (
                state.get("diagnostics", {}).get("findings", [])
                if isinstance(state.get("diagnostics"), Mapping)
                else []
            )
            if isinstance(item, Mapping) and item.get("findingId")
        }
    )
    finding_samples = findings[:sample_limit]
    result.append(
        {
            "collection": "findings",
            "entityKind": "finding",
            "stableIdField": "findingId",
            "totalCount": len(findings),
            "returnedCount": len(finding_samples),
            "omittedCount": max(0, len(findings) - len(finding_samples)),
            "sampleIds": finding_samples,
            "readTool": "inspect_facility_findings",
            "stableSortKey": "severity,code,findingId",
            "maximumPageSize": FACILITY_LAYOUT_READ_PAGE_SIZE,
            "pagination": "opaque_revision_bound_cursor",
        }
    )
    return result


def _entity_summary(
    state: Mapping[str, Any],
    entity_id: str,
) -> dict[str, Any] | None:
    for collection, id_field, entity_kind, _tool in _DESCRIPTOR_CONFIG:
        for item in state.get(collection, []):
            if not isinstance(item, Mapping) or item.get(id_field) != entity_id:
                continue
            record: dict[str, Any] = {
                "id": entity_id,
                "kind": entity_kind,
            }
            for key in (
                "displayName",
                "label",
                "assetId",
                "assetDefinitionRevision",
                "category",
                "positionMode",
                "zoneType",
                "routeKind",
                "networkKind",
                "bindingRole",
            ):
                if item.get(key) not in (None, ""):
                    record[key] = deepcopy(item[key])
            if entity_kind == "placement":
                record["zoneIds"] = sorted(item.get("zoneIds", []))
                record["capabilityIds"] = sorted(
                    item.get("capabilityIds", [])
                )
            return record
    return None


def _finding_summary(
    state: Mapping[str, Any],
    priority_ids: set[str],
) -> tuple[list[dict[str, Any]], dict[str, int], int]:
    diagnostics = state.get("diagnostics")
    raw_findings = (
        diagnostics.get("findings", [])
        if isinstance(diagnostics, Mapping)
        else []
    )
    findings = [
        item for item in raw_findings if isinstance(item, Mapping)
    ]
    by_severity = Counter(
        str(item.get("severity") or "unknown") for item in findings
    )
    by_code = Counter(str(item.get("code") or "unknown") for item in findings)

    def touches_priority(item: Mapping[str, Any]) -> bool:
        return any(
            str(item.get(key) or "") in priority_ids
            for key in (
                "placementId",
                "zoneId",
                "routeId",
                "utilityNetworkId",
                "processBindingId",
            )
        )

    ordered = sorted(
        findings,
        key=lambda item: (
            0 if touches_priority(item) else 1,
            _SEVERITY_PRIORITY.get(
                str(item.get("severity") or ""),
                99,
            ),
            str(item.get("code") or ""),
            str(item.get("findingId") or ""),
        ),
    )
    records = []
    for item in ordered[:40]:
        record = {
            "findingId": str(item.get("findingId") or ""),
            "severity": str(item.get("severity") or "unknown"),
            "code": str(item.get("code") or "unknown"),
            "message": _text(item.get("message"), 320),
        }
        for key in (
            "placementId",
            "zoneId",
            "routeId",
            "utilityNetworkId",
            "processBindingId",
        ):
            if item.get(key):
                record[key] = str(item[key])
        records.append(record)
    code_counts = {
        key: by_code[key]
        for key in sorted(
            by_code,
            key=lambda value: (-by_code[value], value),
        )[:40]
    }
    severity_counts = {
        key: by_severity[key]
        for key in sorted(
            by_severity,
            key=lambda value: (
                _SEVERITY_PRIORITY.get(value, 99),
                value,
            ),
        )
    }
    return records, {
        **{f"severity:{key}": value for key, value in severity_counts.items()},
        **{f"code:{key}": value for key, value in code_counts.items()},
    }, max(0, len(ordered) - len(records))


def _zone_summaries(
    state: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    occupancy: dict[str, Counter[str]] = defaultdict(Counter)
    for placement in state.get("placements", []):
        if not isinstance(placement, Mapping):
            continue
        category = str(placement.get("category") or "unknown")
        for zone_id in placement.get("zoneIds", []):
            occupancy[str(zone_id)][category] += 1
    values = []
    for zone in state.get("zones", []):
        if not isinstance(zone, Mapping) or not zone.get("zoneId"):
            continue
        zone_id = str(zone["zoneId"])
        counts = occupancy.get(zone_id, Counter())
        values.append(
            {
                "zoneId": zone_id,
                "label": _text(zone.get("label"), 160),
                "zoneType": str(zone.get("zoneType") or "unknown"),
                "placementCount": sum(counts.values()),
                "assetCategories": {
                    key: counts[key] for key in sorted(counts)
                },
                "anchorCount": len(zone.get("anchors", [])),
                "userNamed": bool(_text(zone.get("label"))),
            }
        )
    values.sort(
        key=lambda item: (
            0 if item["userNamed"] else 1,
            item["zoneId"],
        )
    )
    return values[:40], max(0, len(values) - 40)


def _asset_usage(
    state: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    assets = {
        (
            str(item.get("assetId") or ""),
            str(item.get("assetDefinitionRevision") or ""),
        ): item
        for item in state.get("assets", [])
        if isinstance(item, Mapping) and item.get("assetId")
    }
    counts = Counter(
        (
            str(item.get("assetId") or ""),
            str(item.get("assetDefinitionRevision") or ""),
        )
        for item in state.get("placements", [])
        if isinstance(item, Mapping) and item.get("assetId")
    )
    records = []
    for key in sorted(counts, key=lambda item: (-counts[item], item)):
        asset = assets.get(key, {})
        records.append(
            {
                "assetId": key[0],
                "assetDefinitionRevision": key[1],
                "displayName": _text(
                    asset.get("displayName") or key[0],
                    160,
                ),
                "category": str(asset.get("category") or "unknown"),
                "placementCount": counts[key],
                "capabilityIds": sorted(
                    asset.get("capabilityIds", [])
                )[:16],
                "planningReady": asset.get("planningReady") is True,
            }
        )
    return records[:40], max(0, len(records) - 40)


def _bounded_unresolved(
    evidence: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    values = sorted(
        [
            {
                "findingId": str(item.get("findingId") or ""),
                "code": str(item.get("code") or "unresolved_fact"),
                "message": _text(item.get("message"), 320),
                "subjectRefs": sorted(
                    str(value)
                    for value in item.get("subjectRefs", [])
                    if isinstance(value, str)
                )[:20],
            }
            for item in evidence.get("unresolvedFacts", [])
            if isinstance(item, Mapping)
        ],
        key=lambda item: (
            item["code"],
            item["findingId"],
            item["message"],
        ),
    )
    return values[:40], max(0, len(values) - 40)


def _set_size_fields(digest: dict[str, Any]) -> None:
    digest["canonicalUtf8Bytes"] = 0
    digest["estimatedTokens"] = 0
    for _attempt in range(8):
        byte_count = len(canonical_facility_digest_bytes(digest))
        token_count = (byte_count + 3) // 4
        if (
            digest["canonicalUtf8Bytes"] == byte_count
            and digest["estimatedTokens"] == token_count
        ):
            return
        digest["canonicalUtf8Bytes"] = byte_count
        digest["estimatedTokens"] = token_count


def _fit_bounds(
    digest: dict[str, Any],
    *,
    maximum_tokens: int,
    maximum_bytes: int,
) -> dict[str, Any]:
    result = deepcopy(digest)
    truncation = result.setdefault("truncation", {})
    paths = [
        (0, result, "selectedEntities", "selectedEntities"),
        (1, result, "findingDetails", "findingDetails"),
        (2, result, "zoneSummaries", "zoneSummaries"),
        (2, result, "assetUsage", "assetUsage"),
        (1, result, "unresolvedAuthorityGaps", "unresolvedAuthorityGaps"),
        (3, result, "readDescriptors", "readDescriptors"),
    ]
    while True:
        _set_size_fields(result)
        if (
            result["estimatedTokens"] <= maximum_tokens
            and result["canonicalUtf8Bytes"] <= maximum_bytes
        ):
            break
        candidate = max(
            (
                (
                    priority,
                    len(container.get(key, [])),
                    path,
                    container,
                    key,
                )
                for priority, container, key, path in paths
                if isinstance(container.get(key), list)
                and container[key]
            ),
            default=None,
            key=lambda item: (item[0], item[1], item[2]),
        )
        if candidate is None:
            raise FacilityDigestError(
                "facility_digest_budget_exceeded",
                "Facility Layout digest cannot fit its configured bounds.",
            )
        _priority, _length, path, container, key = candidate
        container[key].pop()
        record = truncation.setdefault(
            path,
            {"returnedCount": 0, "omittedCount": 0},
        )
        record["omittedCount"] += 1
        record["returnedCount"] = len(container[key])
    if not truncation:
        result.pop("truncation", None)
    _set_size_fields(result)
    if (
        result["estimatedTokens"] > maximum_tokens
        or result["canonicalUtf8Bytes"] > maximum_bytes
    ):
        raise FacilityDigestError(
            "facility_digest_budget_exceeded",
            "Facility Layout digest exceeds its configured bounds.",
        )
    return result


def build_facility_layout_digest(
    state: TrustedFacilityContext,
    evidence: TrustedFacilityContext,
    *,
    maximum_tokens: int = FACILITY_LAYOUT_DIGEST_MAXIMUM_TOKENS,
    maximum_canonical_utf8_bytes: int = (
        FACILITY_LAYOUT_DIGEST_MAXIMUM_CANONICAL_UTF8_BYTES
    ),
) -> dict[str, Any]:
    """Compile one stable model digest from trusted Facility Layout context."""

    try:
        state = assert_trusted_facility_context(
            state,
            "facility_layout.state",
        )
        evidence = assert_trusted_facility_context(
            evidence,
            "facility_layout.evidence",
        )
    except FacilityObservationError as exc:
        raise FacilityDigestError(exc.code, str(exc)) from exc
    if maximum_tokens < 256 or maximum_canonical_utf8_bytes < 1024:
        raise FacilityDigestError(
            "facility_digest_budget_invalid",
            "Facility Layout digest bounds are too small.",
        )

    selected_ids = _selection_ids(state)
    active_ids = _active_entity_ids(state)
    priority_ids = selected_ids | active_ids
    selected_entities = [
        summary
        for entity_id in sorted(priority_ids)
        for summary in [_entity_summary(state, entity_id)]
        if summary is not None
    ][:50]
    finding_details, finding_counts, omitted_findings = _finding_summary(
        state,
        priority_ids,
    )
    zones, omitted_zones = _zone_summaries(state)
    asset_usage, omitted_assets = _asset_usage(state)
    unresolved, omitted_unresolved = _bounded_unresolved(evidence)
    position_modes, _ = _counter_records(
        [
            str(item.get("positionMode") or "unknown")
            for item in state.get("placements", [])
            if isinstance(item, Mapping)
        ],
        key="positionMode",
        limit=8,
    )
    route_kinds, _ = _counter_records(
        [
            str(item.get("routeKind") or "unknown")
            for item in state.get("routes", [])
            if isinstance(item, Mapping)
        ],
        key="routeKind",
        limit=8,
    )
    network_kinds, _ = _counter_records(
        [
            str(item.get("networkKind") or "unknown")
            for item in state.get("utilityNetworks", [])
            if isinstance(item, Mapping)
        ],
        key="networkKind",
        limit=16,
    )
    binding_roles, _ = _counter_records(
        [
            str(item.get("bindingRole") or "unknown")
            for item in state.get("processBindings", [])
            if isinstance(item, Mapping)
        ],
        key="bindingRole",
        limit=16,
    )
    capability_counts = Counter(
        capability
        for item in state.get("placements", [])
        if isinstance(item, Mapping)
        for capability in item.get("capabilityIds", [])
        if isinstance(capability, str)
    )
    read_descriptors = _read_descriptors(
        state,
        priority_ids=priority_ids,
    )
    digest: dict[str, Any] = {
        "digestContractVersion": FACILITY_LAYOUT_DIGEST_CONTRACT_VERSION,
        "tokenizerId": FACILITY_LAYOUT_DIGEST_TOKENIZER_ID,
        "tokenizerRevision": FACILITY_LAYOUT_DIGEST_TOKENIZER_REVISION,
        "identity": {
            **deepcopy(state.get("identity", {})),
            "shellId": state.get("dependencyRevisions", {}).get("shellId"),
            "shellRevision": state.get("dependencyRevisions", {}).get(
                "shellRevision"
            ),
            "policySetId": state.get("dependencyRevisions", {}).get(
                "policySetId"
            ),
            "policySetRevision": state.get("dependencyRevisions", {}).get(
                "policySetRevision"
            ),
            "processMapRevisions": [
                {
                    "processMapId": str(item.get("processMapId") or ""),
                    "processMapRevision": str(
                        item.get("processMapRevision") or ""
                    ),
                }
                for item in state.get("processMaps", [])
                if isinstance(item, Mapping)
            ],
        },
        "savedStateCurrent": bool(state.get("savedStateCurrent")),
        "counts": {
            "placements": len(state.get("placements", [])),
            "zones": len(state.get("zones", [])),
            "routes": len(state.get("routes", [])),
            "utilityNetworks": len(state.get("utilityNetworks", [])),
            "processBindings": len(state.get("processBindings", [])),
            "assetDefinitions": len(state.get("assets", [])),
            "vehicles": len(state.get("vehicles", [])),
            "findings": sum(
                value
                for key, value in finding_counts.items()
                if key.startswith("severity:")
            ),
            "unresolvedAuthorityGaps": len(
                evidence.get("unresolvedFacts", [])
            ),
        },
        "positionModes": position_modes,
        "routeKinds": route_kinds,
        "utilityKinds": network_kinds,
        "processBindingRoles": binding_roles,
        "capabilities": [
            {"capabilityId": key, "placementCount": capability_counts[key]}
            for key in sorted(
                capability_counts,
                key=lambda value: (-capability_counts[value], value),
            )[:40]
        ],
        "assetUsage": asset_usage,
        "zoneSummaries": zones,
        "findingSummary": finding_counts,
        "findingDetails": finding_details,
        "selection": deepcopy(state.get("selection", {})),
        "selectedEntities": selected_entities,
        "activeProposal": deepcopy(state.get("activeProposal")),
        "unresolvedAuthorityGaps": unresolved,
        "staleDependencies": deepcopy(
            state.get("staleDependencies", [])
        ),
        "capabilitiesAvailable": deepcopy(
            state.get("capabilities", {})
        ),
        "coordinateContract": {
            "persisted": "facility_world",
            "modelSuppliesCoordinates": False,
            "cameraIsGeometry": False,
            "positionModes": ["auto", "manual", "locked"],
        },
        "readDescriptors": read_descriptors,
        "canonicalUtf8Bytes": 0,
        "estimatedTokens": 0,
    }
    truncation = {}
    if omitted_findings:
        truncation["findingDetails"] = {
            "returnedCount": len(finding_details),
            "omittedCount": omitted_findings,
        }
    if omitted_zones:
        truncation["zoneSummaries"] = {
            "returnedCount": len(zones),
            "omittedCount": omitted_zones,
        }
    if omitted_assets:
        truncation["assetUsage"] = {
            "returnedCount": len(asset_usage),
            "omittedCount": omitted_assets,
        }
    if omitted_unresolved:
        truncation["unresolvedAuthorityGaps"] = {
            "returnedCount": len(unresolved),
            "omittedCount": omitted_unresolved,
        }
    if truncation:
        digest["truncation"] = truncation
    return _fit_bounds(
        digest,
        maximum_tokens=maximum_tokens,
        maximum_bytes=maximum_canonical_utf8_bytes,
    )


__all__ = [
    "FACILITY_LAYOUT_DIGEST_CONTRACT_VERSION",
    "FACILITY_LAYOUT_DIGEST_MAXIMUM_CANONICAL_UTF8_BYTES",
    "FACILITY_LAYOUT_DIGEST_MAXIMUM_TOKENS",
    "FACILITY_LAYOUT_DIGEST_TOKENIZER_ID",
    "FACILITY_LAYOUT_DIGEST_TOKENIZER_REVISION",
    "FacilityDigestError",
    "build_facility_layout_digest",
    "canonical_facility_digest_bytes",
    "estimate_facility_digest_tokens",
]
