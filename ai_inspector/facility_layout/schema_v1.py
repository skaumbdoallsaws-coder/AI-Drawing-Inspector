"""Facility Layout v1 compatibility and frozen schema constants."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Mapping

from .errors import FacilityValidationError


SCHEMA_VERSION = 1
LEGACY_SCHEMA_VERSION = "facility-layout-semantic-v0.2"

MAXIMUM_CANONICAL_DOCUMENT_BYTES = 104_857_600
MAXIMUM_JSON_DEPTH = 32
MAXIMUM_EXTENSION_FIELDS_PER_OBJECT = 32
MAXIMUM_TOTAL_EXTENSION_BYTES = 5_242_880
MAXIMUM_ABSOLUTE_WORLD_COORDINATE_METERS = 1_000_000

LIMITS = {
    "zones": 500,
    "placements": 5000,
    "routes": 2000,
    "utilityNetworks": 100,
    "processBindings": 5000,
    "dismissedSuggestions": 5000,
    "verticesPerZone": 256,
    "totalZoneVertices": 50_000,
    "anchorsPerZone": 128,
    "totalZoneAnchors": 10_000,
    "pointsPerRoute": 2048,
    "totalRoutePoints": 250_000,
    "nodesPerUtilityNetwork": 2000,
    "totalUtilityNodes": 20_000,
    "segmentsPerUtilityNetwork": 4000,
    "totalUtilitySegments": 40_000,
    "pointsPerUtilitySegment": 2048,
    "totalUtilityPoints": 250_000,
    "requirementsPerTarget": 64,
    "evidencePerTarget": 64,
}

STABLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
REVISION_RE = re.compile(r"^[0-9a-f]{64}$")

ID_PREFIXES = {
    "layoutId": "fl-",
    "zoneId": "zn-",
    "anchorId": "za-",
    "placementId": "pl-",
    "routeId": "rt-",
    "utilityNetworkId": "un-",
    "networkNodeId": "nn-",
    "networkSegmentId": "ns-",
    "processBindingId": "pb-",
}

REQUIRED_LAYOUT_FIELDS = frozenset(
    {
        "schemaVersion",
        "layoutId",
        "displayName",
        "status",
        "association",
        "coordinateFrame",
        "sourceShellRef",
        "policySetRef",
        "zones",
        "placements",
        "routes",
        "utilityNetworks",
        "processBindings",
        "dismissedSuggestions",
        "createdAt",
        "updatedAt",
    }
)

FORBIDDEN_LIVE_STATE_FIELDS = frozenset(
    {"camera", "viewport", "selection", "activeProposal"}
)


@dataclass(frozen=True)
class LayoutCompatibility:
    mode: str
    read_allowed: bool
    write_allowed: bool
    detected_schema_version: Any
    reason: str
    original_bytes: bytes | None = None
    migration_allowed: bool = False
    canonical_rewrite_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "reason": self.reason,
            "detectedSchemaVersion": self.detected_schema_version,
            "maximumReadableSchemaVersion": SCHEMA_VERSION,
            "maximumWritableSchemaVersion": SCHEMA_VERSION,
            "readAllowed": self.read_allowed,
            "writeAllowed": self.write_allowed,
            "migrationAllowed": self.migration_allowed,
            "canonicalRewriteAllowed": self.canonical_rewrite_allowed,
            "originalBytesMustRemainUnchanged": self.mode == "read_only",
        }


def _parse_document(
    source: Mapping[str, Any] | bytes | bytearray | str,
) -> tuple[Mapping[str, Any], bytes | None]:
    if isinstance(source, Mapping):
        return source, None
    if isinstance(source, str):
        raw = source.encode("utf-8")
    elif isinstance(source, (bytes, bytearray)):
        raw = bytes(source)
    else:
        raise FacilityValidationError(
            "invalid_layout_shape",
            "Facility Layout source must be an object or JSON bytes.",
        )
    if len(raw) > MAXIMUM_CANONICAL_DOCUMENT_BYTES:
        raise FacilityValidationError(
            "document_limit_exceeded",
            "Facility Layout exceeds the maximum document size.",
            details={
                "maximumBytes": MAXIMUM_CANONICAL_DOCUMENT_BYTES,
                "actualBytes": len(raw),
            },
        )
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FacilityValidationError(
            "invalid_json",
            "Facility Layout source is not valid UTF-8 JSON.",
        ) from exc
    if not isinstance(parsed, Mapping):
        raise FacilityValidationError(
            "invalid_layout_shape",
            "Facility Layout source must contain a JSON object.",
        )
    return parsed, raw


def detect_layout_compatibility(
    source: Mapping[str, Any] | bytes | bytearray | str,
) -> LayoutCompatibility:
    """Classify a layout without rewriting source bytes."""

    document, original_bytes = _parse_document(source)
    version = document.get("schemaVersion")
    if version == LEGACY_SCHEMA_VERSION:
        return LayoutCompatibility(
            mode="legacy_migration",
            read_allowed=True,
            write_allowed=False,
            detected_schema_version=version,
            reason="supported_legacy_schema",
            original_bytes=original_bytes,
            migration_allowed=True,
            canonical_rewrite_allowed=False,
        )
    if isinstance(version, bool) or not isinstance(version, int):
        return LayoutCompatibility(
            mode="unsupported",
            read_allowed=False,
            write_allowed=False,
            detected_schema_version=version,
            reason="unsupported_schema_version",
            original_bytes=original_bytes,
        )
    if version == SCHEMA_VERSION:
        return LayoutCompatibility(
            mode="native",
            read_allowed=True,
            write_allowed=True,
            detected_schema_version=version,
            reason="native_schema",
            original_bytes=original_bytes,
            canonical_rewrite_allowed=True,
        )
    if version > SCHEMA_VERSION:
        return LayoutCompatibility(
            mode="read_only",
            read_allowed=True,
            write_allowed=False,
            detected_schema_version=version,
            reason="unsupported_newer_schema",
            original_bytes=original_bytes,
            migration_allowed=False,
            canonical_rewrite_allowed=False,
        )
    return LayoutCompatibility(
        mode="unsupported",
        read_allowed=False,
        write_allowed=False,
        detected_schema_version=version,
        reason="unsupported_schema_version",
        original_bytes=original_bytes,
    )
