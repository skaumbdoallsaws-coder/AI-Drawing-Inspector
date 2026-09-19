"""Reviewed local fixture boundary for the first Facility design-loop slice.

This module deliberately does not generalize reviewed candidate geometry to an
arbitrary layout.  The source provider releases the synthetic manufacturing
evidence only when the complete base document matches the accepted fixture.
"""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
from typing import Any, Mapping

from .authority_repository import authority_revision
from .canonical import canonicalize_layout, layout_revision
from .design_service import FacilityDesignServiceError
from .service import coordinate_frame_fingerprint


REVIEWED_MATERIAL_TRAVEL_LAYOUT_ID = "fl-fdl-material-travel-v1"
REVIEWED_REFERENCE_MATERIAL_TRAVEL_LAYOUT_ID = (
    "fl-reference-fdl-material-travel-v1"
)
REVIEWED_MATERIAL_TRAVEL_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "design_loop"
    / "fdl-material-travel-v1.json"
)
REVIEWED_REFERENCE_MATERIAL_TRAVEL_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "design_loop"
    / "fdl-reference-material-travel-v1.json"
)
REFERENCE_MANUAL_LAYOUT_PATH = (
    Path(__file__).resolve().parents[2]
    / ".runtime"
    / "facility-layout"
    / "layouts"
    / "local"
    / "site-local"
    / "layouts"
    / "fl-reference-manual-20260812.json"
)


@lru_cache(maxsize=1)
def _fixture() -> dict[str, Any]:
    try:
        value = json.loads(
            REVIEWED_MATERIAL_TRAVEL_FIXTURE_PATH.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise FacilityDesignServiceError(
            "facility_design_reviewed_fixture_unavailable",
            "The reviewed material-travel fixture is unavailable.",
        ) from exc
    if (
        not isinstance(value, dict)
        or value.get("schemaVersion") != "facility-design-fixture-v1"
        or value.get("fixtureId") != "fdl-material-travel-v1"
    ):
        raise FacilityDesignServiceError(
            "facility_design_reviewed_fixture_invalid",
            "The reviewed material-travel fixture identity is invalid.",
        )
    return value


@lru_cache(maxsize=1)
def _reference_fixture() -> dict[str, Any]:
    try:
        value = json.loads(
            REVIEWED_REFERENCE_MATERIAL_TRAVEL_FIXTURE_PATH.read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise FacilityDesignServiceError(
            "facility_design_reference_objective_unavailable",
            "The reviewed reference-factory objective package is unavailable.",
        ) from exc
    if (
        not isinstance(value, dict)
        or value.get("schemaVersion")
        != "facility-design-reference-objective-v1"
        or value.get("fixtureId") != "fdl-reference-material-travel-v1"
    ):
        raise FacilityDesignServiceError(
            "facility_design_reference_objective_invalid",
            "The reviewed reference-factory objective identity is invalid.",
        )
    return value


@lru_cache(maxsize=1)
def reference_manual_layout() -> dict[str, Any]:
    """Load and verify the immutable manual factory used by FDL9."""

    fixture = _reference_fixture()
    try:
        document = json.loads(
            REFERENCE_MANUAL_LAYOUT_PATH.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise FacilityDesignServiceError(
            "facility_design_reference_layout_unavailable",
            "The archived manual reference layout is unavailable.",
        ) from exc
    canonical = canonicalize_layout(document)
    if (
        canonical.get("layoutId") != fixture["sourceLayoutId"]
        or layout_revision(canonical) != fixture["sourceLayoutRevision"]
    ):
        raise FacilityDesignServiceError(
            "facility_design_reference_layout_mismatch",
            "The archived manual reference layout does not match its reviewed revision.",
        )
    return canonical


def reviewed_reference_material_travel_layout(
    *, site_id: str
) -> dict[str, Any]:
    """Create the FDL9 review copy without changing reference geometry."""

    fixture = _reference_fixture()
    document = deepcopy(reference_manual_layout())
    document["layoutId"] = fixture["reviewLayoutId"]
    document["displayName"] = "Reference Factory - FDL Material Travel Review"
    document["association"]["siteId"] = str(site_id)
    document["processBindings"] = deepcopy(fixture["processBindings"])
    document["updatedAt"] = fixture["authority"]["reviewedAt"]
    return canonicalize_layout(document)


def _reference_comparison_document(
    document: Mapping[str, Any],
    *,
    canonical_site_id: str,
) -> dict[str, Any]:
    """Ignore repository timestamps, never reference geometry or bindings."""

    result = deepcopy(canonicalize_layout(document))
    source = reference_manual_layout()
    fixture = _reference_fixture()
    result.setdefault("association", {})["siteId"] = canonical_site_id
    result["createdAt"] = source["createdAt"]
    result["updatedAt"] = fixture["authority"]["reviewedAt"]
    return canonicalize_layout(result)


def _comparison_document(
    document: Mapping[str, Any],
    *,
    canonical_site_id: str,
) -> dict[str, Any]:
    result = canonicalize_layout(document)
    result = deepcopy(result)
    result.setdefault("association", {})["siteId"] = canonical_site_id
    fixture_document = _fixture()["facilityLayout"]
    result["createdAt"] = fixture_document["createdAt"]
    result["updatedAt"] = fixture_document["updatedAt"]
    return canonicalize_layout(result)


def _endpoint_geometry(
    document: Mapping[str, Any],
    route_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Bind fixture connector locations to authored route endpoints."""

    placements = {
        str(item.get("placementId")): item
        for item in document.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    }
    routes = {
        str(item.get("routeId")): item
        for item in document.get("routes", [])
        if isinstance(item, Mapping) and item.get("routeId")
    }
    result: dict[str, dict[str, Any]] = {}
    for route_id in route_ids:
        route = routes.get(str(route_id))
        if not isinstance(route, Mapping):
            continue
        centerline = route.get("centerline")
        if not isinstance(centerline, list) or len(centerline) < 2:
            continue
        for field, point in (
            ("sourceEndpoint", centerline[0]),
            ("targetEndpoint", centerline[-1]),
        ):
            endpoint = route.get(field)
            if (
                not isinstance(endpoint, Mapping)
                or endpoint.get("kind") != "placement_connector"
                or not isinstance(point, Mapping)
            ):
                continue
            placement_id = str(endpoint.get("placementId") or "")
            connector_id = str(endpoint.get("connectorId") or "")
            placement = placements.get(placement_id)
            if not isinstance(placement, Mapping) or not connector_id:
                continue
            result[f"{placement_id}:{connector_id}"] = {
                "assetDefinitionRevision": placement[
                    "assetDefinitionRevision"
                ],
                "basePlacementPosition": deepcopy(
                    placement["transform"]["position"]
                ),
                "baseEndpointPosition": deepcopy(point),
                "evidenceStatus": "derived",
                "sourceRouteId": route_id,
            }
    return result


def reviewed_material_travel_authority_documents(
    *,
    site_id: str,
) -> dict[str, Any]:
    """Return the published, test-only authorities for the reviewed fixture."""

    fixture = _fixture()
    layout = fixture["facilityLayout"]
    frame = deepcopy(layout["coordinateFrame"])
    plan = layout["extensions"]["facilityPlan"]
    width = plan["widthMeters"]
    depth = plan["depthMeters"]
    qualification = (
        "Synthetic authority for the reviewed FDL test fixture only. It is "
        "not site, safety, compliance, installation, or production evidence."
    )
    shell = {
        "schemaVersion": 1,
        "documentKind": "facility_shell",
        "shellId": "shell-fdl",
        "tenantId": "local",
        "siteId": str(site_id),
        "status": "published",
        "coordinateFrame": frame,
        "features": [{
            "featureId": "floor-fdl-material-travel",
            "featureKind": "floor_surface",
            "geometry": {
                "boundary": [
                    {"x": 0, "z": 0},
                    {"x": width, "z": 0},
                    {"x": width, "z": depth},
                    {"x": 0, "z": depth},
                ],
                "elevation": frame["floorElevation"],
            },
            "evidence": [],
        }],
        "shellConnectors": [],
        "sourceDocuments": [],
        "evidence": [],
        "unresolvedItems": [{
            "findingId": "finding-fdl-shell-test-only",
            "code": "fdl_synthetic_shell_not_production_authority",
            "message": qualification,
        }],
    }
    policy = {
        "schemaVersion": 1,
        "documentKind": "policy_set",
        "policySetId": "policy-fdl-prototype",
        "tenantId": "local",
        "siteId": str(site_id),
        "status": "published",
        "applicability": {
            "areaIds": [layout["association"]["areaId"]],
        },
        "deterministicRules": [],
        "sourceDocuments": [],
        "evidence": [],
        "unresolvedItems": [{
            "findingId": "finding-fdl-policy-test-only",
            "code": "fdl_synthetic_policy_not_production_authority",
            "message": qualification,
        }],
    }
    return {
        "facilityShell": shell,
        "facilityShellRevision": authority_revision(shell),
        "policySet": policy,
        "policySetRevision": authority_revision(policy),
    }


def reviewed_material_travel_layout(*, site_id: str) -> dict[str, Any]:
    """Return the reviewed synthetic layout re-scoped for local display."""

    document = deepcopy(_fixture()["facilityLayout"])
    document["association"]["siteId"] = str(site_id)
    authorities = reviewed_material_travel_authority_documents(site_id=site_id)
    shell = authorities["facilityShell"]
    document["sourceShellRef"] = {
        "shellId": shell["shellId"],
        "shellRevision": authorities["facilityShellRevision"],
        "coordinateFrameFingerprint": coordinate_frame_fingerprint(
            shell["coordinateFrame"]
        ),
    }
    policy = authorities["policySet"]
    document["policySetRef"] = {
        "policySetId": policy["policySetId"],
        "policySetRevision": authorities["policySetRevision"],
    }
    return canonicalize_layout(document)


def _reviewed_fixture_asset_definitions(fixture: Mapping[str, Any]) -> list[dict[str, Any]]:
    records = []
    for raw in fixture.get("catalogAssets", []):
        if not isinstance(raw, Mapping):
            continue
        connectors = []
        if raw.get("assetId") == "asset-fifo-buffer":
            connectors = [
                {
                    "connectorId": "material-output",
                    "connectorKind": "material",
                    "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                    "facing": {"x": 1.0, "y": 0.0, "z": 0.0},
                    "role": "output",
                    "allowedRouteKinds": ["material"],
                    "evidenceStatus": "authored",
                },
                {
                    "connectorId": "material-input",
                    "connectorKind": "material",
                    "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                    "facing": {"x": -1.0, "y": 0.0, "z": 0.0},
                    "role": "input",
                    "allowedRouteKinds": ["material"],
                    "evidenceStatus": "authored",
                },
            ]
        records.append(
            {
                "assetId": str(raw.get("assetId") or ""),
                "assetDefinitionRevision": str(
                    raw.get("assetDefinitionRevision") or ""
                ),
                "definition": {
                    "documentKind": "industrial_asset_definition",
                    "assetId": str(raw.get("assetId") or ""),
                    "geometry": deepcopy(raw.get("geometry") or {}),
                    "connectors": connectors,
                },
            }
        )
    return records


def reviewed_material_travel_source_provider(
    _principal: Any,
    site_id: str,
    layout_id: str,
    design_base: Mapping[str, Any],
    _design_brief: Mapping[str, Any],
) -> dict[str, Any]:
    """Release test-gold evidence only for the exact reviewed fixture bytes."""

    if layout_id == REVIEWED_REFERENCE_MATERIAL_TRAVEL_LAYOUT_ID:
        fixture = _reference_fixture()
        document = design_base.get("document")
        if not isinstance(document, Mapping):
            raise FacilityDesignServiceError(
                "facility_design_source_bundle_invalid",
                "The design base has no canonical Facility Layout document.",
            )
        expected = _reference_comparison_document(
            reviewed_reference_material_travel_layout(site_id=site_id),
            canonical_site_id=site_id,
        )
        observed = _reference_comparison_document(
            document,
            canonical_site_id=site_id,
        )
        if layout_revision(observed) != layout_revision(expected):
            raise FacilityDesignServiceError(
                "facility_design_reviewed_fixture_mismatch",
                "The active layout does not match the reviewed reference-factory copy.",
                details={
                    "layoutId": layout_id,
                    "expectedFixtureRevision": layout_revision(expected),
                    "observedFixtureRevision": layout_revision(observed),
                    "siteId": site_id,
                },
            )
        return {
            "processMap": deepcopy(fixture["processMap"]),
            "transfer": deepcopy(fixture["transferEvidence"]),
            "validationContextRevision": layout_revision(expected),
            "candidateUpdatedAt": fixture["authority"]["reviewedAt"],
            "reviewedCandidateRecipes": deepcopy(
                fixture["candidateRecipes"]
            ),
            "candidateAuthority": "reviewed_reference_test_gold",
            "fixtureAuthority": deepcopy(fixture["authority"]),
            "referenceSource": {
                "layoutId": fixture["sourceLayoutId"],
                "layoutRevision": fixture["sourceLayoutRevision"],
            },
            "assetDefinitions": [],
            "endpointGeometry": _endpoint_geometry(
                document,
                list(fixture["transferEvidence"]["routeIds"]),
            ),
        }
    fixture = _fixture()
    if layout_id != REVIEWED_MATERIAL_TRAVEL_LAYOUT_ID:
        raise FacilityDesignServiceError(
            "facility_design_source_bundle_unavailable",
            "This layout has no reviewed material-travel design source bundle.",
            details={"layoutId": layout_id},
        )
    document = design_base.get("document")
    if not isinstance(document, Mapping):
        raise FacilityDesignServiceError(
            "facility_design_source_bundle_invalid",
            "The design base has no canonical Facility Layout document.",
        )
    expected = _comparison_document(
        reviewed_material_travel_layout(site_id=site_id),
        canonical_site_id=site_id,
    )
    observed = _comparison_document(
        document,
        canonical_site_id=site_id,
    )
    expected_revision = layout_revision(expected)
    observed_revision = layout_revision(observed)
    if observed_revision != expected_revision:
        raise FacilityDesignServiceError(
            "facility_design_reviewed_fixture_mismatch",
            "The active layout does not match the reviewed material-travel fixture.",
            details={
                "layoutId": layout_id,
                "expectedFixtureRevision": expected_revision,
                "observedFixtureRevision": observed_revision,
                "siteId": site_id,
            },
        )
    return {
        "processMap": deepcopy(fixture["processMap"]),
        "transfer": deepcopy(fixture["transferEvidence"]),
        "validationContextRevision": fixture["expected"][
            "validationContextRevision"
        ],
        "candidateUpdatedAt": fixture["authority"]["reviewedAt"],
        "reviewedCandidateRecipes": deepcopy(fixture["candidateRecipes"]),
        "candidateAuthority": "reviewed_test_gold",
        "fixtureAuthority": deepcopy(fixture["authority"]),
        "assetDefinitions": _reviewed_fixture_asset_definitions(fixture),
    }


__all__ = [
    "REFERENCE_MANUAL_LAYOUT_PATH",
    "REVIEWED_MATERIAL_TRAVEL_FIXTURE_PATH",
    "REVIEWED_MATERIAL_TRAVEL_LAYOUT_ID",
    "REVIEWED_REFERENCE_MATERIAL_TRAVEL_FIXTURE_PATH",
    "REVIEWED_REFERENCE_MATERIAL_TRAVEL_LAYOUT_ID",
    "reference_manual_layout",
    "reviewed_material_travel_authority_documents",
    "reviewed_material_travel_layout",
    "reviewed_material_travel_source_provider",
    "reviewed_reference_material_travel_layout",
]
