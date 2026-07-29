"""Normalized source identities for pre-extraction industrial-asset intake."""

from __future__ import annotations

from typing import Any, Mapping

from .schema_v1 import (
    DependencyGraphResult,
    DiscoveryResult,
    IntakeFinding,
    NormalizedSourceIdentity,
    canonical_json_sha256,
    canonical_path_key,
    sort_findings,
    source_revision,
    validate_json_value,
)


_PROTECTED_INPUT_KEYS = {
    "licenseDocumentPath",
    "localPath",
    "sourcePath",
    "storageKey",
}


def _reject_protected_input_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) in _PROTECTED_INPUT_KEYS:
                raise ValueError(
                    "extraction inputs may not contain protected path fields"
                )
            _reject_protected_input_keys(item)
    elif isinstance(value, list):
        for item in value:
            _reject_protected_input_keys(item)


def build_normalized_source_identity(
    discovery: DiscoveryResult,
    dependency_graph: DependencyGraphResult,
    *,
    configuration: str | None,
    extraction_inputs: Mapping[str, Any],
) -> NormalizedSourceIdentity:
    """Build a protected, deterministic source identity candidate.

    A complete source revision is emitted only when the caller supplies a
    selected configuration and a dependency graph explicitly marked complete.
    Quarantined or ambiguous inputs never receive a source revision.
    """

    inputs = validate_json_value(extraction_inputs)
    _reject_protected_input_keys(inputs)
    records_by_path = {
        record.relative_path: record for record in discovery.records
    }
    selected_records = [
        records_by_path[path]
        for path in dependency_graph.source_paths
        if path in records_by_path
    ]
    selected_root = (
        records_by_path.get(dependency_graph.selected_root)
        if dependency_graph.selected_root is not None
        else None
    )
    findings = list(dependency_graph.findings)
    revision: str | None = None
    if configuration is None or not str(configuration).strip():
        findings.append(
            IntakeFinding(
                "warning",
                "source_configuration_unresolved",
                "A selected CAD configuration is required before source revisioning.",
                relative_path=(
                    selected_root.relative_path if selected_root is not None else None
                ),
            )
        )
    elif (
        dependency_graph.status == "resolved"
        and dependency_graph.reference_graph_complete
        and not discovery.quarantined
        and selected_root is not None
        and selected_records
    ):
        revision = source_revision(
            selected_records,
            configuration=str(configuration),
            extraction_inputs=inputs,
        )

    lifecycle = (
        "quarantined"
        if dependency_graph.status == "quarantined" or discovery.quarantined
        else "draft"
    )
    candidate_identity = {
        "rootPathKey": (
            canonical_path_key(selected_root.relative_path)
            if selected_root is not None
            else None
        ),
        "sourceFingerprint": discovery.source_fingerprint,
    }
    candidate_id = "iac-" + canonical_json_sha256(candidate_identity)[:24]
    record: dict[str, Any] = {
        "schemaVersion": 1,
        "recordKind": "industrial_asset_source_identity",
        "candidateId": candidate_id,
        "assetId": None,
        "status": lifecycle,
        "safeLabel": (
            selected_root.safe_label if selected_root is not None else None
        ),
        "sourceFingerprint": discovery.source_fingerprint,
        "sourceRevision": revision,
        "configuration": (
            str(configuration) if configuration is not None else None
        ),
        "extractionInputs": inputs,
        "requestedRoot": (
            {
                "relativePath": selected_root.relative_path,
                "safeLabel": selected_root.safe_label,
                "sourceKind": selected_root.source_kind,
                "byteLength": selected_root.byte_length,
                "sha256": selected_root.sha256,
            }
            if selected_root is not None
            else None
        ),
        "sourceFiles": [item.to_dict() for item in selected_records],
        "dependencyGraph": dependency_graph.to_dict(),
        "findings": [
            item.to_dict() for item in sort_findings(findings)
        ],
        "readiness": {
            "visualReady": {
                "value": False,
                "blockers": ["web_geometry_missing", "thumbnail_missing"],
            },
            "placementReady": {
                "value": False,
                "blockers": [
                    "canonical_frame_unverified",
                    "floor_anchor_unverified",
                    "footprint_unverified",
                    "collision_proxy_unverified",
                ],
            },
            "planningReady": {
                "value": False,
                "blockers": [
                    "connectors_unreviewed",
                    "clearances_unreviewed",
                    "loading_unreviewed",
                ],
            },
            "publicReady": {
                "value": False,
                "blockers": [
                    "redistribution_permission_unverified",
                    "attribution_unverified",
                ],
            },
        },
    }
    record["identityFingerprint"] = canonical_json_sha256(record)
    return NormalizedSourceIdentity(record)
