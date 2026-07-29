"""Lossless migration from the frozen Facility Layout semantic v0.2 fixture."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping

from .canonical import (
    _canonical_value_bytes,
    canonicalize_layout,
    canonicalize_polygon,
)
from .errors import (
    FacilityCompatibilityError,
    FacilityIntegrityError,
    FacilityValidationError,
)
from .schema_v1 import (
    LEGACY_SCHEMA_VERSION,
    detect_layout_compatibility,
)
from .validate import validate_layout


MIGRATION_CONTRACT_VERSION = 1
MIGRATION_ASSERTED_BY = "facility-layout-migration-v1"


@dataclass(frozen=True)
class MigrationBundle:
    layout: Mapping[str, Any]
    shell: Mapping[str, Any]
    policy_set: Mapping[str, Any]
    evidence_records: tuple[Mapping[str, Any], ...]
    source_bytes: bytes
    source_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "layout": deepcopy(dict(self.layout)),
            "shell": deepcopy(dict(self.shell)),
            "policySet": deepcopy(dict(self.policy_set)),
            "evidenceRecords": [
                deepcopy(dict(record)) for record in self.evidence_records
            ],
            "source": {
                "byteLength": len(self.source_bytes),
                "sha256": self.source_sha256,
            },
        }


def _fail(code: str, message: str, path: str = "$") -> None:
    raise FacilityValidationError(code, message, details={"path": path})


def _object(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("invalid_migration_context", "Expected an object.", path)
    return value


def _array(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        _fail("invalid_migration_context", "Expected an array.", path)
    return value


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_value_bytes(value)).hexdigest()


def _legacy_id(prefix: str, identity: Mapping[str, Any]) -> str:
    return f"{prefix}-legacy-{_fingerprint(identity)[:20]}"


def _source_bytes(
    source: bytes | bytearray | str,
) -> tuple[bytes, Mapping[str, Any]]:
    if isinstance(source, str):
        raw = source.encode("utf-8")
    elif isinstance(source, (bytes, bytearray)):
        raw = bytes(source)
    else:
        raise FacilityIntegrityError(
            "legacy_source_bytes_required",
            "Legacy migration requires original source bytes.",
        )
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FacilityValidationError(
            "invalid_json",
            "Legacy Facility Layout source is not valid UTF-8 JSON.",
        ) from exc
    if not isinstance(document, Mapping):
        _fail("invalid_layout_shape", "Legacy source must contain an object.")
    return raw, document


def _assert_equal(actual: Any, expected: Any, *, code: str, path: str) -> None:
    if actual != expected:
        raise FacilityIntegrityError(
            code,
            "Legacy migration input does not match its pinned context.",
            details={"path": path, "expected": expected, "actual": actual},
        )


def _find_floor_zone(
    source: Mapping[str, Any],
    legacy_zone_id: str,
) -> tuple[Mapping[str, Any], int]:
    layout_map = _object(source.get("layoutMap"), "$.layoutMap")
    zones = _array(layout_map.get("floorZones"), "$.layoutMap.floorZones")
    matches = [
        (zone, index)
        for index, zone in enumerate(zones)
        if isinstance(zone, Mapping) and zone.get("id") == legacy_zone_id
    ]
    if len(matches) != 1:
        raise FacilityIntegrityError(
            "legacy_zone_binding_mismatch",
            "Legacy zone promotion must resolve exactly one source zone.",
            details={"legacyZoneId": legacy_zone_id, "matches": len(matches)},
        )
    return matches[0]


def _find_component(
    source: Mapping[str, Any],
    component_name: str,
) -> tuple[Mapping[str, Any], str, str]:
    matches: list[tuple[Mapping[str, Any], str, str]] = []
    for row_index, raw_row in enumerate(source.get("rackRows", [])):
        row = _object(raw_row, f"$.rackRows[{row_index}]")
        for instance_index, raw_instance in enumerate(row.get("rackInstances", [])):
            instance = _object(
                raw_instance,
                f"$.rackRows[{row_index}].rackInstances[{instance_index}]",
            )
            if instance.get("componentName") == component_name:
                matches.append(
                    (
                        instance,
                        f"rackRows[{row_index}].rackInstances[{instance_index}]",
                        str(row.get("id", "")),
                    )
                )
    for asset_index, raw_asset in enumerate(source.get("materialHandlingAssets", [])):
        asset = _object(
            raw_asset,
            f"$.materialHandlingAssets[{asset_index}]",
        )
        if asset.get("componentName") == component_name:
            matches.append(
                (
                    asset,
                    f"materialHandlingAssets[{asset_index}]",
                    str(asset.get("id", "")),
                )
            )
    if len(matches) != 1:
        raise FacilityIntegrityError(
            "legacy_asset_binding_mismatch",
            "Legacy asset binding must resolve exactly one component.",
            details={"legacyComponentName": component_name, "matches": len(matches)},
        )
    return matches[0]


def _zone_type(legacy_kind: Any) -> str:
    mapping = {
        "rack_storage_zone": "storage",
        "workcell": "workcell",
        "staging": "staging",
        "inspection": "inspection",
        "aisle": "aisle",
    }
    return mapping.get(str(legacy_kind), "storage")


def _zone_label(legacy_zone_id: str) -> str:
    value = legacy_zone_id
    if value.startswith("Zone_"):
        value = value[5:]
    value = value.replace("_", " ").strip()
    if not value:
        return "Legacy zone"
    return value[0].upper() + value[1:].lower()


def _evidence_id(
    promotion: Mapping[str, Any],
    *,
    promotion_count: int,
) -> str:
    status = str(promotion.get("evidenceStatus", "inferred"))
    if promotion_count == 1:
        return f"ev-legacy-zone-{status}"
    return _legacy_id(
        "ev",
        {
            "kind": "zone-evidence",
            "legacyId": promotion.get("legacyZoneId"),
            "status": status,
        },
    )


def _build_shell(
    *,
    shell_id: str,
    context: Mapping[str, Any],
    coordinate_frame: Mapping[str, Any],
    coordinate_frame_fingerprint: str,
    source: Mapping[str, Any],
) -> dict[str, Any]:
    validation = _object(
        _object(source.get("layoutMap"), "$.layoutMap")
        .get("coordinateFrame"),
        "$.layoutMap.coordinateFrame",
    ).get("validation", {})
    residual = _object(
        validation,
        "$.layoutMap.coordinateFrame.validation",
    ).get("maxResidualMeters")
    residual_text = str(residual)
    return {
        "schemaVersion": 1,
        "documentKind": "facility_shell",
        "shellId": shell_id,
        "tenantId": context["serverContext"]["tenantId"],
        "siteId": context["serverContext"]["siteId"],
        "status": "draft",
        "coordinateFrame": deepcopy(dict(coordinate_frame)),
        "features": [],
        "shellConnectors": [],
        "sourceDocuments": [],
        "evidence": [],
        "unresolvedItems": [
            {
                "findingId": "finding-legacy-frame-demo-only",
                "code": "legacy_coordinate_alignment_demo_only",
                "message": (
                    f"The {residual_text} m legacy alignment residual exceeds "
                    "the 0.001 m placement-readiness target."
                ),
            },
            {
                "findingId": "finding-legacy-floor-inferred",
                "code": "legacy_floor_elevation_inferred",
                "message": (
                    "The compatibility floor elevation is inferred from the "
                    "minimum rack occurrence Y value."
                ),
            },
            {
                "findingId": "finding-legacy-shell-missing",
                "code": "legacy_shell_geometry_unavailable",
                "message": (
                    "No reviewed floor surface, boundary, wall, door, dock, "
                    "or fixed-obstacle geometry is available."
                ),
            },
        ],
        "extensions": {
            "inspectorproLegacyMigration": {
                "compatibilityOnly": True,
                "coordinateFrameFingerprint": coordinate_frame_fingerprint,
                "evidenceStatus": "inferred",
                "readOnly": True,
            }
        },
    }


def _build_policy(
    *,
    policy_id: str,
    layout_id: str,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "documentKind": "policy_set",
        "policySetId": policy_id,
        "tenantId": context["serverContext"]["tenantId"],
        "siteId": context["serverContext"]["siteId"],
        "status": "draft",
        "applicability": {
            "layoutId": layout_id,
            "compatibilityOnly": True,
        },
        "deterministicRules": [],
        "sourceDocuments": [],
        "evidence": [],
        "unresolvedItems": [
            {
                "findingId": "finding-legacy-policy-missing",
                "code": "legacy_policy_unavailable",
                "message": (
                    "The legacy semantic document contains no authoritative "
                    "deterministic facility policy."
                ),
            }
        ],
        "extensions": {
            "inspectorproLegacyMigration": {
                "readOnly": True,
            }
        },
    }


def migrate_legacy_semantic_v02(
    source: bytes | bytearray | str,
    context: Mapping[str, Any],
) -> MigrationBundle:
    """Migrate a pinned v0.2 source into a read-only v1 compatibility bundle."""

    raw, legacy = _source_bytes(source)
    compatibility = detect_layout_compatibility(raw)
    if compatibility.mode != "legacy_migration":
        raise FacilityCompatibilityError(
            "unsupported_legacy_schema",
            "Only facility-layout-semantic-v0.2 can use this migration.",
            details={"detectedSchemaVersion": legacy.get("schemaVersion")},
        )
    context = _object(context, "$.migrationContext")
    _assert_equal(
        context.get("migrationContractVersion"),
        MIGRATION_CONTRACT_VERSION,
        code="migration_contract_mismatch",
        path="$.migrationContext.migrationContractVersion",
    )
    canonicalization = _object(
        context.get("canonicalization"),
        "$.migrationContext.canonicalization",
    )
    _assert_equal(
        dict(canonicalization),
        {
            "encoding": "ascii",
            "jsonKeys": "sorted",
            "jsonSeparators": [",", ":"],
            "trailingLf": False,
            "hashAlgorithm": "sha256",
        },
        code="migration_contract_mismatch",
        path="$.migrationContext.canonicalization",
    )
    compatibility_context = _object(
        context.get("compatibility"),
        "$.migrationContext.compatibility",
    )
    if (
        compatibility_context.get("mode") != "read_only"
        or compatibility_context.get("writeAllowed") is not False
        or compatibility_context.get("promotionRequiresReviewedAuthority") is not True
    ):
        raise FacilityIntegrityError(
            "migration_contract_mismatch",
            "Legacy migration context must remain read-only.",
            details={"path": "$.migrationContext.compatibility"},
        )
    source_context = _object(context.get("source"), "$.migrationContext.source")
    source_sha256 = hashlib.sha256(raw).hexdigest()
    _assert_equal(
        len(raw),
        source_context.get("byteLength"),
        code="legacy_source_length_mismatch",
        path="$.migrationContext.source.byteLength",
    )
    _assert_equal(
        source_sha256,
        source_context.get("sha256"),
        code="legacy_source_hash_mismatch",
        path="$.migrationContext.source.sha256",
    )
    _assert_equal(
        legacy.get("schemaVersion"),
        source_context.get("schemaVersion"),
        code="legacy_source_schema_mismatch",
        path="$.schemaVersion",
    )

    facility = _object(legacy.get("facility"), "$.facility")
    facility_id = facility.get("id")
    if not isinstance(facility_id, str) or not facility_id:
        _fail("invalid_legacy_source", "Legacy facility ID is required.", "$.facility.id")
    site_id = _object(
        context.get("serverContext"),
        "$.migrationContext.serverContext",
    ).get("siteId")
    source_schema = legacy["schemaVersion"]

    derived_layout_id = _legacy_id(
        "fl",
        {
            "facilityId": facility_id,
            "kind": "layout",
            "sourceSchemaVersion": source_schema,
        },
    )
    _assert_equal(
        derived_layout_id,
        context.get("layoutId"),
        code="legacy_identity_mismatch",
        path="$.migrationContext.layoutId",
    )
    derived_shell_id = _legacy_id(
        "shell",
        {
            "facilityId": facility_id,
            "kind": "shell",
            "sourceSchemaVersion": source_schema,
        },
    )
    derived_policy_id = _legacy_id(
        "policy",
        {
            "facilityId": facility_id,
            "kind": "empty-policy",
            "siteId": site_id,
        },
    )

    coordinate_frame = deepcopy(
        dict(_object(context.get("coordinateFrame"), "$.migrationContext.coordinateFrame"))
    )
    coordinate_frame_fingerprint = _fingerprint(coordinate_frame)
    _assert_equal(
        coordinate_frame_fingerprint,
        context.get("coordinateFrameFingerprint"),
        code="coordinate_frame_fingerprint_mismatch",
        path="$.migrationContext.coordinateFrameFingerprint",
    )

    shell = _build_shell(
        shell_id=derived_shell_id,
        context=context,
        coordinate_frame=coordinate_frame,
        coordinate_frame_fingerprint=coordinate_frame_fingerprint,
        source=legacy,
    )
    policy = _build_policy(
        policy_id=derived_policy_id,
        layout_id=derived_layout_id,
        context=context,
    )
    shell_revision = _fingerprint(shell)
    policy_revision = _fingerprint(policy)

    source_shell_ref = _object(
        context.get("sourceShellRef"),
        "$.migrationContext.sourceShellRef",
    )
    policy_set_ref = _object(
        context.get("policySetRef"),
        "$.migrationContext.policySetRef",
    )
    expected_shell_ref = {
        "shellId": derived_shell_id,
        "shellRevision": shell_revision,
        "coordinateFrameFingerprint": coordinate_frame_fingerprint,
    }
    expected_policy_ref = {
        "policySetId": derived_policy_id,
        "policySetRevision": policy_revision,
    }
    _assert_equal(
        dict(source_shell_ref),
        expected_shell_ref,
        code="stale_shell_revision",
        path="$.migrationContext.sourceShellRef",
    )
    _assert_equal(
        dict(policy_set_ref),
        expected_policy_ref,
        code="stale_policy_revision",
        path="$.migrationContext.policySetRef",
    )

    promotions = _array(
        context.get("zonePromotions"),
        "$.migrationContext.zonePromotions",
    )
    zones: list[dict[str, Any]] = []
    evidence_records: list[dict[str, Any]] = []
    for promotion_index, raw_promotion in enumerate(promotions):
        promotion_path = f"$.migrationContext.zonePromotions[{promotion_index}]"
        promotion = _object(raw_promotion, promotion_path)
        legacy_zone_id = promotion.get("legacyZoneId")
        if not isinstance(legacy_zone_id, str) or not legacy_zone_id:
            _fail(
                "invalid_migration_context",
                "Zone promotion needs legacyZoneId.",
                f"{promotion_path}.legacyZoneId",
            )
        legacy_zone, source_index = _find_floor_zone(legacy, legacy_zone_id)
        derived_zone_id = _legacy_id(
            "zn",
            {
                "facilityId": facility_id,
                "kind": "zone",
                "legacyId": legacy_zone_id,
            },
        )
        _assert_equal(
            derived_zone_id,
            promotion.get("zoneId"),
            code="legacy_identity_mismatch",
            path=f"{promotion_path}.zoneId",
        )
        boundary = canonicalize_polygon(
            legacy_zone.get("approxFloorPolygonMeters"),
            f"$.layoutMap.floorZones[{source_index}].approxFloorPolygonMeters",
        )
        evidence_id = _evidence_id(promotion, promotion_count=len(promotions))
        zone = {
            "zoneId": derived_zone_id,
            "zoneType": _zone_type(legacy_zone.get("kind")),
            "label": _zone_label(legacy_zone_id),
            "boundary": boundary,
            "floorElevation": coordinate_frame["floorElevation"],
            "anchors": [],
            "evidence": [evidence_id],
            "extensions": {
                "inspectorproLegacyMigration": {
                    "demoOnly": bool(promotion.get("demoOnly")),
                    "evidenceStatus": promotion.get("evidenceStatus"),
                    "legacyPath": f"layoutMap.floorZones[{source_index}]",
                    "legacyRowIds": deepcopy(legacy_zone.get("rowIds", [])),
                }
            },
        }
        zones.append(zone)
        evidence_records.append(
            {
                "schemaVersion": 1,
                "documentKind": "evidence_record",
                "evidenceId": evidence_id,
                "tenantId": context["serverContext"]["tenantId"],
                "subjectRef": {
                    "zoneId": derived_zone_id,
                },
                "claimKey": "facility.zone.boundary",
                "valueFingerprint": _fingerprint(boundary),
                "status": promotion.get("evidenceStatus"),
                "sourceRef": {
                    "trustedSourceId": "legacy-unregistered-source",
                    "sourceRevision": source_sha256,
                    "locator": (
                        f"layoutMap.floorZones[{source_index}]"
                        ".approxFloorPolygonMeters"
                    ),
                },
                "assertedBy": MIGRATION_ASSERTED_BY,
                "assertedAt": context["serverContext"]["updatedAt"],
            }
        )

    placements: list[dict[str, Any]] = []
    bindings = _array(
        context.get("assetBindings"),
        "$.migrationContext.assetBindings",
    )
    for binding_index, raw_binding in enumerate(bindings):
        binding_path = f"$.migrationContext.assetBindings[{binding_index}]"
        binding = _object(raw_binding, binding_path)
        component_name = binding.get("legacyComponentName")
        if not isinstance(component_name, str) or not component_name:
            _fail(
                "invalid_migration_context",
                "Asset binding needs legacyComponentName.",
                f"{binding_path}.legacyComponentName",
            )
        component, source_path, semantic_group = _find_component(
            legacy,
            component_name,
        )
        if binding.get("sourceOriginMatchesPlacementOrigin") is not True:
            raise FacilityIntegrityError(
                "legacy_asset_origin_unresolved",
                "Legacy placement needs a pinned source-origin mapping.",
                details={"legacyComponentName": component_name},
            )
        if binding.get("quaternionSource") != "pinned_companion_extractor":
            raise FacilityIntegrityError(
                "legacy_orientation_unresolved",
                "Legacy placement needs a pinned companion quaternion.",
                details={"legacyComponentName": component_name},
            )
        if binding.get("sourceQuaternionOrder") != "WXYZ":
            raise FacilityIntegrityError(
                "legacy_orientation_unresolved",
                "Legacy companion quaternion order must be pinned as WXYZ.",
                details={"legacyComponentName": component_name},
            )
        placement_id = _legacy_id(
            "pl",
            {
                "componentName": component_name,
                "facilityId": facility_id,
                "kind": "placement",
            },
        )
        placements.append(
            {
                "placementId": placement_id,
                "assetId": binding["assetId"],
                "assetDefinitionRevision": binding["assetDefinitionRevision"],
                "transform": {
                    "position": deepcopy(component["positionMeters"]),
                    "quaternion": deepcopy(binding["canonicalQuaternion"]),
                    "scale": 1,
                },
                "positionMode": "locked",
                "snapRelationship": None,
                "metadata": {
                    "legacyComponentName": component_name,
                    "legacySemanticGroup": semantic_group,
                    "legacySourcePath": source_path,
                    "orientationSource": binding["quaternionSource"],
                    "readOnly": True,
                    "sourceOriginMatchesPlacementOrigin": True,
                },
            }
        )

    server_context = context["serverContext"]
    association: dict[str, Any] = {"siteId": server_context["siteId"]}
    if server_context.get("areaId"):
        association["areaId"] = server_context["areaId"]
    layout = {
        "schemaVersion": 1,
        "layoutId": derived_layout_id,
        "displayName": facility.get("displayName") or facility_id,
        "status": "draft",
        "association": association,
        "coordinateFrame": coordinate_frame,
        "sourceShellRef": expected_shell_ref,
        "policySetRef": expected_policy_ref,
        "zones": zones,
        "placements": placements,
        "routes": [],
        "utilityNetworks": [],
        "processBindings": [],
        "dismissedSuggestions": [],
        "createdAt": server_context["createdAt"],
        "updatedAt": server_context["updatedAt"],
        "extensions": {
            "inspectorproLegacySemanticV0_2": {
                "migrationContractVersion": MIGRATION_CONTRACT_VERSION,
                "mode": "read_only",
                "sourceByteLength": len(raw),
                "sourceSha256": source_sha256,
                "payload": deepcopy(dict(legacy)),
            }
        },
    }
    layout = canonicalize_layout(layout)
    validate_layout(layout, require_canonical=True)
    return MigrationBundle(
        layout=layout,
        shell=shell,
        policy_set=policy,
        evidence_records=tuple(evidence_records),
        source_bytes=raw,
        source_sha256=source_sha256,
    )
