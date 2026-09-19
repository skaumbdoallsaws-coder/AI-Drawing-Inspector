"""Closed normalization and hashing policies for Sage memory."""

from __future__ import annotations

import copy
import unicodedata
from typing import Any, Dict, Mapping, Optional, Tuple

from .models import canonical_json, canonical_sha256


REQUEST_HASH_VERSION = 1
MEMORY_SCHEMA_VERSION = "1.0"
SEMANTIC_TARGET_FIELDS = (
    "partOccurrenceIds",
    "processMapNodeIds",
    "processMapEdgeIds",
    "facilityPlacementIds",
    "faiCharacteristicIds",
)
_SCOPE_FIELDS = {
    "process_map": (
        ("productId", "mapId"),
        (
            "processMapRevision",
            "productStructureRevision",
            "assemblyKnowledgeRevision",
        ),
    ),
    "facility_layout": (
        ("siteId", "layoutId"),
        (
            "facilityLayoutRevision",
            "facilityShellRevision",
            "facilityPolicyRevision",
        ),
    ),
    "cad_fai": (
        (
            "productId",
            "partNumber",
            "assemblyNumber",
            "configuration",
            "inspectionProfileId",
        ),
        (
            "partRevision",
            "drawingRevision",
            "faiRevision",
            "assemblyKnowledgeRevision",
            "motionAssetPin",
        ),
    ),
    "none": ((), ()),
}


def normalize_request_identity_v1(raw: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError("request identity must be an object")
    version = raw.get("requestHashVersion", REQUEST_HASH_VERSION)
    if version != REQUEST_HASH_VERSION:
        raise ValueError("unsupported request hash version")

    message = _required_string(raw, "message").replace("\r\n", "\n").replace("\r", "\n")
    message = unicodedata.normalize("NFC", message)
    agent_type = _required_string(raw, "agentType").strip().lower()
    workflow_mode = _required_string(raw, "workflowMode").strip().lower()
    if not agent_type or not workflow_mode:
        raise ValueError("agentType and workflowMode must not be blank")

    memory_schema_version = _required_string(raw, "memorySchemaVersion")
    if memory_schema_version != MEMORY_SCHEMA_VERSION:
        raise ValueError("unsupported memory schema version")

    return {
        "requestHashVersion": REQUEST_HASH_VERSION,
        "message": message,
        "agentType": agent_type,
        "workflowMode": workflow_mode,
        "assetScope": _normalize_asset_scope(raw.get("assetScope")),
        "semanticTargets": _normalize_semantic_targets(raw.get("semanticTargets")),
        "imageSha256": _normalize_ordered_strings(raw.get("imageSha256"), "imageSha256"),
        "actionParameters": _normalize_json_object(
            raw.get("actionParameters"), "actionParameters"
        ),
        "crossAgentProjectionSha256": _optional_string(
            raw.get("crossAgentProjectionSha256"), "crossAgentProjectionSha256"
        ),
        "memorySchemaVersion": memory_schema_version,
    }


def request_identity_sha256_v1(raw: Mapping[str, Any]) -> Tuple[Dict[str, Any], str]:
    identity = normalize_request_identity_v1(raw)
    return identity, canonical_sha256(identity)


def _normalize_asset_scope(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("assetScope must be an object")
    extra = set(value) - {"kind", "ids", "expectedRevisionVector"}
    if extra:
        raise ValueError(f"assetScope contains unsupported fields: {sorted(extra)}")
    kind = _required_string(value, "kind").strip().lower()
    if kind not in _SCOPE_FIELDS:
        raise ValueError("assetScope.kind is unsupported")
    id_fields, revision_fields = _SCOPE_FIELDS[kind]
    ids = value.get("ids")
    revisions = value.get("expectedRevisionVector")
    if not isinstance(ids, Mapping) or not isinstance(revisions, Mapping):
        raise ValueError("assetScope IDs and revisions must be objects")
    unknown_ids = set(ids) - set(id_fields)
    unknown_revisions = set(revisions) - set(revision_fields)
    if unknown_ids or unknown_revisions:
        raise ValueError("assetScope contains fields not allowed for its kind")

    normalized_ids: Dict[str, str] = {}
    for field in id_fields:
        raw = ids.get(field)
        if raw is None or raw == "":
            continue
        normalized_ids[field] = _string_value(raw, f"assetScope.ids.{field}")
    if kind in {"process_map", "facility_layout"} and set(normalized_ids) != set(id_fields):
        raise ValueError(f"assetScope kind {kind} requires IDs {list(id_fields)}")
    if kind == "none" and (ids or revisions):
        raise ValueError("assetScope kind none must be empty")

    normalized_revisions: Dict[str, str] = {}
    for field in revision_fields:
        raw = revisions.get(field)
        if raw is None or raw == "":
            continue
        normalized_revisions[field] = _string_value(
            raw, f"assetScope.expectedRevisionVector.{field}"
        )
    return {
        "kind": kind,
        "ids": normalized_ids,
        "expectedRevisionVector": normalized_revisions,
    }


def _normalize_semantic_targets(value: Any) -> Dict[str, list[str]]:
    if not isinstance(value, Mapping):
        raise ValueError("semanticTargets must be an object")
    unknown = set(value) - set(SEMANTIC_TARGET_FIELDS)
    if unknown:
        raise ValueError(f"semanticTargets contains unsupported fields: {sorted(unknown)}")
    normalized: Dict[str, list[str]] = {}
    for field in SEMANTIC_TARGET_FIELDS:
        values = value.get(field, [])
        if not isinstance(values, list):
            raise ValueError(f"semanticTargets.{field} must be an array")
        normalized[field] = sorted({_string_value(item, field) for item in values})
    return normalized


def _normalize_ordered_strings(value: Any, name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    return [_string_value(item, name) for item in value]


def _normalize_json_object(value: Any, name: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    cloned = copy.deepcopy(value)
    canonical_json(cloned)
    return cloned


def _required_string(value: Mapping[str, Any], name: str) -> str:
    if name not in value:
        raise ValueError(f"{name} is required")
    return _string_value(value[name], name, allow_empty=True)


def _optional_string(value: Any, name: str) -> Optional[str]:
    if value is None:
        return None
    return _string_value(value, name)


def _string_value(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    if not allow_empty and not value:
        raise ValueError(f"{name} must not be empty")
    return value

