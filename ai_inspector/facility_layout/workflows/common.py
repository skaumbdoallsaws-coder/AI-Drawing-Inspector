"""Shared deterministic contracts for Facility Layout workflow packages.

P10 packages describe operational intent. They never own coordinates, route
geometry, transactions, approvals, or persistence. Their two outputs are:

* one coordinate-free P8 planner request for manual authoring; and
* one Semantic Facility Layout Plan v1 for Sage review and preview.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Sequence

from ..planner import (
    FACILITY_LAYOUT_REQUEST_SCHEMA_VERSION,
    validate_layout_request,
)


WORKFLOW_PACKAGE_SCHEMA_VERSION = 1
WORKFLOW_PACKAGE_COMPILER_VERSION = "1.0.0"
EVIDENCE_STATUSES = frozenset(
    {"authored", "derived", "inferred", "unknown"}
)
LAYOUT_STRATEGIES = frozenset(
    {"compact_rows", "balanced_grid", "flow_lanes"}
)
DENSITY_SPACING_METERS = {
    "compact": 0.75,
    "balanced": 1.0,
    "spacious": 1.5,
}
ZONE_PADDING_METERS = {
    "compact": 0.5,
    "standard": 0.75,
    "generous": 1.25,
}
MAXIMUM_WORKFLOW_ASSET_INSTANCES = 500

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_GEOMETRY_KEYS = frozenset(
    {
        "camera",
        "centerline",
        "clientx",
        "clienty",
        "coordinate",
        "coordinates",
        "matrix",
        "offsetx",
        "offsety",
        "pagex",
        "pagey",
        "pixel",
        "pixels",
        "position",
        "positions",
        "quaternion",
        "rotation",
        "routepoint",
        "routepoints",
        "screen",
        "transform",
        "transforms",
        "translation",
        "viewport",
        "waypoint",
        "waypoints",
        "worldcoordinate",
        "worldcoordinates",
        "x",
        "y",
        "yaw",
        "z",
        "zoom",
    }
)


class FacilityWorkflowPackageError(ValueError):
    """Typed deterministic workflow-package rejection."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        path: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.path = path
        self.details = deepcopy(dict(details or {}))

    def finding(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "severity": "error",
            "code": self.code,
            "message": str(self),
        }
        if self.path:
            result["path"] = self.path
        if self.details:
            result["details"] = deepcopy(self.details)
        return result


def fail(
    code: str,
    message: str,
    *,
    path: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> None:
    raise FacilityWorkflowPackageError(
        code,
        message,
        path=path,
        details=details,
    )


def canonical_workflow_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise FacilityWorkflowPackageError(
            "invalid_workflow_package",
            "Workflow packages must contain finite JSON values.",
        ) from exc


def workflow_fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_workflow_bytes(value)).hexdigest()


def stable_workflow_id(prefix: str, seed: Any, *, length: int = 20) -> str:
    return f"{prefix}{workflow_fingerprint(seed)[:length]}"


def detached(value: Any) -> Any:
    return json.loads(canonical_workflow_bytes(value).decode("ascii"))


def identifier(value: Any, field: str) -> str:
    if not isinstance(value, str):
        fail(
            "invalid_workflow_identifier",
            f"{field} must be a stable ID.",
            path=field,
        )
    result = value.strip()
    if not _ID_RE.fullmatch(result):
        fail(
            "invalid_workflow_identifier",
            f"{field} must be a stable ID.",
            path=field,
        )
    return result


def text(value: Any, field: str, *, maximum: int = 240) -> str:
    if not isinstance(value, str):
        fail(
            "invalid_workflow_text",
            f"{field} must be text.",
            path=field,
        )
    result = " ".join(value.split())
    if not result or len(result) > maximum:
        fail(
            "invalid_workflow_text",
            f"{field} must contain 1 to {maximum} characters.",
            path=field,
        )
    return result


def revision(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _REVISION_RE.fullmatch(value):
        fail(
            "invalid_workflow_revision",
            f"{field} must be a lowercase SHA-256 revision.",
            path=field,
        )
    return value


def positive_integer(
    value: Any,
    field: str,
    *,
    minimum: int = 1,
    maximum: int = MAXIMUM_WORKFLOW_ASSET_INSTANCES,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        fail(
            "invalid_workflow_quantity",
            f"{field} must be an integer from {minimum} through {maximum}.",
            path=field,
        )
    return value


def percentage(value: Any, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0.0 <= float(value) <= 100.0
    ):
        fail(
            "invalid_workflow_percentage",
            f"{field} must be from 0 through 100.",
            path=field,
        )
    return float(value)


def mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        fail(
            "invalid_workflow_object",
            f"{field} must be an object.",
            path=field,
        )
    return deepcopy(dict(value))


def records(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(
        isinstance(item, Mapping) for item in value
    ):
        fail(
            "invalid_workflow_collection",
            f"{field} must be an array of objects.",
            path=field,
        )
    return [deepcopy(dict(item)) for item in value]


def reject_raw_geometry(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = re.sub(r"[^a-z0-9]", "", str(raw_key).lower())
            if key in _FORBIDDEN_GEOMETRY_KEYS:
                fail(
                    "workflow_raw_geometry_forbidden",
                    (
                        "Workflow packages describe facility intent; the "
                        "deterministic planner owns coordinates and routes."
                    ),
                    path=f"{path}.{raw_key}",
                )
            reject_raw_geometry(child, f"{path}.{raw_key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_raw_geometry(child, f"{path}[{index}]")


def normalize_source_revisions(
    raw: Any,
    *,
    require_catalog: bool = True,
) -> dict[str, str]:
    source = mapping(raw, "sourceRevisions")
    required = {"layout", "shell", "policy"}
    if require_catalog:
        required.add("catalog")
    missing = sorted(required - set(source))
    if missing:
        fail(
            "workflow_source_revisions_missing",
            "Missing source revisions: " + ", ".join(missing) + ".",
            path="sourceRevisions",
        )
    return {
        str(key): revision(value, f"sourceRevisions.{key}")
        for key, value in sorted(source.items())
    }


def normalize_scope(raw: Any) -> dict[str, str]:
    scope = mapping(raw, "scope")
    return {
        "siteId": identifier(scope.get("siteId"), "scope.siteId"),
        "layoutId": identifier(scope.get("layoutId"), "scope.layoutId"),
        "label": text(scope.get("label"), "scope.label", maximum=120),
    }


def normalize_basis(
    raw: Mapping[str, Any],
    *,
    field: str,
    known_evidence_ids: set[str],
    known_assumption_ids: set[str],
    unresolved_subjects: set[str],
) -> dict[str, Any]:
    status = raw.get("knowledgeStatus")
    if status not in EVIDENCE_STATUSES:
        fail(
            "invalid_workflow_evidence_status",
            f"{field}.knowledgeStatus is invalid.",
            path=f"{field}.knowledgeStatus",
        )
    raw_evidence_ids = raw.get("evidenceIds", [])
    raw_assumption_ids = raw.get("assumptionIds", [])
    if not isinstance(raw_evidence_ids, list):
        fail(
            "invalid_workflow_evidence_refs",
            f"{field}.evidenceIds must be an array.",
            path=f"{field}.evidenceIds",
        )
    if not isinstance(raw_assumption_ids, list):
        fail(
            "invalid_workflow_assumption_refs",
            f"{field}.assumptionIds must be an array.",
            path=f"{field}.assumptionIds",
        )
    evidence_ids = sorted(
        {
            identifier(value, f"{field}.evidenceIds")
            for value in raw_evidence_ids
        }
    )
    assumption_ids = sorted(
        {
            identifier(value, f"{field}.assumptionIds")
            for value in raw_assumption_ids
        }
    )
    missing_evidence = sorted(set(evidence_ids) - known_evidence_ids)
    missing_assumptions = sorted(set(assumption_ids) - known_assumption_ids)
    if missing_evidence:
        fail(
            "workflow_evidence_unknown",
            f"{field} references unknown evidence.",
            path=f"{field}.evidenceIds",
            details={"evidenceIds": missing_evidence},
        )
    if missing_assumptions:
        fail(
            "workflow_assumption_unknown",
            f"{field} references unknown assumptions.",
            path=f"{field}.assumptionIds",
            details={"assumptionIds": missing_assumptions},
        )
    subject_id = identifier(
        raw.get("itemId")
        or raw.get("flowId")
        or raw.get("zoneRequestId")
        or raw.get("requirementId")
        or raw.get("bindingIntentId")
        or raw.get("claimId")
        or raw.get("relationshipId"),
        field,
    )
    if status in {"authored", "derived"} and not evidence_ids:
        fail(
            "workflow_authoritative_evidence_required",
            f"{field} requires cited evidence.",
            path=f"{field}.evidenceIds",
        )
    if status == "inferred" and not evidence_ids and not assumption_ids:
        fail(
            "workflow_inference_basis_required",
            f"{field} requires evidence or an explicit assumption.",
            path=field,
        )
    if status == "unknown" and subject_id not in unresolved_subjects:
        fail(
            "workflow_unknown_must_remain_unresolved",
            f"{field} must remain represented as unresolved.",
            path=field,
        )
    return {
        "knowledgeStatus": status,
        "evidenceIds": evidence_ids,
        "assumptionIds": assumption_ids,
    }


def normalize_provenance(
    spec: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(spec.get("trustedEvidenceIds", []), list):
        fail(
            "invalid_workflow_evidence_refs",
            "trustedEvidenceIds must be an array.",
            path="trustedEvidenceIds",
        )
    trusted_evidence_ids = {
        identifier(value, "trustedEvidenceIds")
        for value in spec.get("trustedEvidenceIds", [])
    }
    assumptions = records(spec.get("assumptions", []), "assumptions")
    assumption_ids: set[str] = set()
    normalized_assumptions = []
    for index, raw in enumerate(assumptions):
        assumption_id = identifier(
            raw.get("assumptionId"),
            f"assumptions[{index}].assumptionId",
        )
        if assumption_id in assumption_ids:
            fail(
                "duplicate_workflow_identifier",
                f"Duplicate assumption '{assumption_id}'.",
            )
        assumption_ids.add(assumption_id)
        normalized_assumptions.append(
            {
                "assumptionId": assumption_id,
                "text": text(
                    raw.get("text"),
                    f"assumptions[{index}].text",
                    maximum=500,
                ),
                "subjectRefs": sorted(
                    {
                        identifier(
                            value,
                            f"assumptions[{index}].subjectRefs",
                        )
                        for value in raw.get("subjectRefs", [])
                    }
                ),
            }
        )

    unresolved = records(
        spec.get("unresolvedItems", []),
        "unresolvedItems",
    )
    unresolved_ids: set[str] = set()
    unresolved_subjects: set[str] = set()
    normalized_unresolved = []
    for index, raw in enumerate(unresolved):
        unresolved_id = identifier(
            raw.get("unresolvedId"),
            f"unresolvedItems[{index}].unresolvedId",
        )
        if unresolved_id in unresolved_ids:
            fail(
                "duplicate_workflow_identifier",
                f"Duplicate unresolved item '{unresolved_id}'.",
            )
        unresolved_ids.add(unresolved_id)
        subjects = sorted(
            {
                identifier(
                    value,
                    f"unresolvedItems[{index}].subjectRefs",
                )
                for value in raw.get("subjectRefs", [])
            }
        )
        unresolved_subjects.update(subjects)
        normalized_unresolved.append(
            {
                "unresolvedId": unresolved_id,
                "code": identifier(
                    raw.get("code"),
                    f"unresolvedItems[{index}].code",
                ),
                "message": text(
                    raw.get("message"),
                    f"unresolvedItems[{index}].message",
                    maximum=500,
                ),
                "subjectRefs": subjects,
            }
        )

    evidence = records(spec.get("evidence", []), "evidence")
    claim_ids: set[str] = set()
    normalized_evidence = []
    for index, raw in enumerate(evidence):
        claim_id = identifier(
            raw.get("claimId"),
            f"evidence[{index}].claimId",
        )
        if claim_id in claim_ids:
            fail(
                "duplicate_workflow_identifier",
                f"Duplicate evidence claim '{claim_id}'.",
            )
        claim_ids.add(claim_id)
        trusted_evidence_ids.update(
            identifier(value, f"evidence[{index}].evidenceIds")
            for value in raw.get("evidenceIds", [])
        )
        normalized_evidence.append(deepcopy(raw))
        normalized_evidence[-1]["claimId"] = claim_id

    return {
        "assumptions": sorted(
            normalized_assumptions,
            key=lambda item: item["assumptionId"],
        ),
        "assumptionIds": assumption_ids,
        "unresolvedItems": sorted(
            normalized_unresolved,
            key=lambda item: item["unresolvedId"],
        ),
        "unresolvedSubjects": unresolved_subjects,
        "evidence": sorted(
            normalized_evidence,
            key=lambda item: item["claimId"],
        ),
        "claimIds": claim_ids,
        "evidenceIds": trusted_evidence_ids,
    }


def normalize_strategies(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        fail(
            "invalid_workflow_strategies",
            "alternatives must be an array.",
            path="alternatives",
        )
    result = []
    for index, value in enumerate(raw):
        if isinstance(value, Mapping):
            strategy = value.get("strategy")
        else:
            strategy = value
        if strategy not in LAYOUT_STRATEGIES:
            fail(
                "invalid_workflow_strategy",
                f"alternatives[{index}] has an unsupported strategy.",
                path=f"alternatives[{index}]",
            )
        if strategy not in result:
            result.append(str(strategy))
    if not result:
        fail(
            "workflow_strategy_required",
            "At least one deterministic strategy is required.",
        )
    return result[:4]


def semantic_alternatives(strategies: Sequence[str]) -> list[dict[str, Any]]:
    return [
        {
            "alternativeId": f"alternative-{strategy.replace('_', '-')}",
            "strategy": strategy,
            "label": strategy.replace("_", " ").title(),
        }
        for strategy in strategies
    ]


def planner_asset_set(
    selected_assets: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result = []
    for item in sorted(selected_assets, key=lambda value: str(value["itemId"])):
        record = {
            "itemId": item["itemId"],
            "assetId": item["assetId"],
            "assetDefinitionRevision": item["assetDefinitionRevision"],
            "quantity": item["quantity"],
            "stage": item["stage"],
        }
        if item.get("existingPlacementId"):
            record["existingPlacementId"] = item["existingPlacementId"]
        if item.get("targetZoneId"):
            record["targetZoneId"] = item["targetZoneId"]
        result.append(record)
    return result


def planner_zone_sizing(
    zones: Sequence[Mapping[str, Any]],
    *,
    package_id: str,
) -> list[dict[str, Any]]:
    result = []
    for item in sorted(zones, key=lambda value: str(value["zoneRequestId"])):
        record: dict[str, Any] = {
            "memberItemIds": sorted(item["memberItemIds"]),
            "paddingMeters": ZONE_PADDING_METERS[
                item.get("paddingClass", "standard")
            ],
        }
        if item.get("existingZoneId"):
            record["zoneId"] = item["existingZoneId"]
        else:
            record["newZone"] = {
                "zoneId": stable_workflow_id(
                    "zn-p10-",
                    {
                        "packageId": package_id,
                        "zoneRequestId": item["zoneRequestId"],
                    },
                ),
                "zoneType": item["zoneType"],
                "label": item["label"],
                "allowedAssetCategories": sorted(
                    set(item.get("allowedAssetCategories", []))
                ),
                "evidence": sorted(set(item.get("evidenceIds", []))),
            }
        result.append(record)
    return result


def planner_routes(
    flows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result = []
    for item in sorted(flows, key=lambda value: str(value["flowId"])):
        if item["flowKind"] == "utility":
            continue
        route = {
            "routeRequestId": item["flowId"],
            "routeKind": item["flowKind"],
            "sourceEndpoint": deepcopy(item["sourceEndpoint"]),
            "targetEndpoint": deepcopy(item["targetEndpoint"]),
            "requirements": [],
            "evidence": sorted(set(item.get("evidenceIds", []))),
        }
        if item["flowKind"] == "forklift":
            route.update(
                {
                    "vehicleProfileId": item["vehicleProfileId"],
                    "vehicleProfileRevision": item[
                        "vehicleProfileRevision"
                    ],
                    "allowReverse": False,
                }
            )
        result.append(route)
    return result


def build_manual_planner_request(
    *,
    package_id: str,
    objective: str,
    selected_assets: Sequence[Mapping[str, Any]],
    zones: Sequence[Mapping[str, Any]],
    flows: Sequence[Mapping[str, Any]],
    strategies: Sequence[str],
    density: str,
    source_revisions: Mapping[str, str],
    process_bindings: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    if density not in DENSITY_SPACING_METERS:
        fail(
            "invalid_workflow_density",
            "layoutHints.density is invalid.",
        )
    planner_sources = {
        "shell": source_revisions["shell"],
        "policy": source_revisions["policy"],
    }
    for binding in process_bindings:
        planner_sources[
            f"process.{binding['processMapId']}"
        ] = binding["processMapRevision"]
    request = {
        "schemaVersion": FACILITY_LAYOUT_REQUEST_SCHEMA_VERSION,
        "requestId": stable_workflow_id(
            "request-p10-",
            {
                "packageId": package_id,
                "objective": objective,
                "assets": selected_assets,
                "zones": zones,
                "flows": flows,
                "strategies": list(strategies),
                "density": density,
                "sourceRevisions": source_revisions,
            },
            length=24,
        ),
        "objective": objective,
        "assetSet": planner_asset_set(selected_assets),
        "strategies": list(strategies),
        "maximumAlternatives": min(4, len(strategies)),
        "spacingMeters": DENSITY_SPACING_METERS[density],
        "cleanup": {
            "enabled": objective in {"cleanup_layout", "place_and_cleanup"},
            "moveAuto": True,
            "movableManualPlacementIds": [],
        },
        "zoneSizing": planner_zone_sizing(
            zones,
            package_id=package_id,
        ),
        "routes": planner_routes(flows),
        "sourceRevisions": planner_sources,
    }
    return validate_layout_request(request)


def base_compilation(
    *,
    package_type: str,
    package_id: str,
    spec: Mapping[str, Any],
    source_revisions: Mapping[str, str],
    semantic_plan: Mapping[str, Any],
    manual_request: Mapping[str, Any],
    domain_model: Mapping[str, Any],
    estimates: Mapping[str, Any],
    deferred: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    normalized_spec = detached(spec)
    spec_hash = workflow_fingerprint(normalized_spec)
    return {
        "schemaVersion": WORKFLOW_PACKAGE_SCHEMA_VERSION,
        "compilerVersion": WORKFLOW_PACKAGE_COMPILER_VERSION,
        "packageType": package_type,
        "packageId": package_id,
        "sourceRevisions": deepcopy(dict(source_revisions)),
        "specFingerprint": spec_hash,
        "semanticPlan": deepcopy(dict(semantic_plan)),
        "manualPlannerRequest": deepcopy(dict(manual_request)),
        "domainModel": deepcopy(dict(domain_model)),
        "estimates": deepcopy(dict(estimates)),
        "deferredItems": sorted(
            [deepcopy(dict(item)) for item in deferred],
            key=lambda item: (
                str(item.get("code") or ""),
                str(item.get("id") or ""),
            ),
        ),
        "reviewRequired": True,
        "previewOnly": True,
    }


__all__ = [
    "DENSITY_SPACING_METERS",
    "EVIDENCE_STATUSES",
    "FacilityWorkflowPackageError",
    "LAYOUT_STRATEGIES",
    "MAXIMUM_WORKFLOW_ASSET_INSTANCES",
    "WORKFLOW_PACKAGE_COMPILER_VERSION",
    "WORKFLOW_PACKAGE_SCHEMA_VERSION",
    "base_compilation",
    "build_manual_planner_request",
    "canonical_workflow_bytes",
    "detached",
    "fail",
    "identifier",
    "mapping",
    "normalize_basis",
    "normalize_provenance",
    "normalize_scope",
    "normalize_source_revisions",
    "normalize_strategies",
    "percentage",
    "positive_integer",
    "records",
    "reject_raw_geometry",
    "revision",
    "semantic_alternatives",
    "stable_workflow_id",
    "text",
    "workflow_fingerprint",
]
