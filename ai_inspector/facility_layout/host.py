"""Local InspectorPro host integration for the Facility Layout domain.

The domain repositories and authorization layer remain authoritative. This
module only supplies the explicit single-user local principal and a small,
revisioned starter catalog so the production UI can mount without a separate
tenant provisioning service.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request

from .api import create_facility_layout_router
from .asset_orientation import attach_registered_semantics
from .model_axes import mirror_catalog_record
from .authority_repository import (
    FacilityShellRepository,
    PolicySetRepository,
    VehicleProfileRepository,
)
from .authorization import (
    FacilityPrincipal,
    local_facility_principal,
    require_facility_action,
)
from .canonical import canonicalize_layout, layout_revision
from .agent_runtime import (
    FacilityLayoutAgentRuntime,
    FacilityLayoutAgentRuntimeError,
)
from .construction_service import FacilityConstructionService
from .generation_admission import FacilityGenerationAdmissionService
from .generation_agent import FacilityGenerationAgentService
from .generation_requirement_repository import GenerationRequirementRepository
from .generation_requirements import GenerationRequirementError
from .generation_draft import GenerationDraftAdapter
from .generation_destination import create_generation_destination
from .program_execution import FacilityProgramExecutionError
from .errors import FacilityLayoutError, FacilityNotFoundError
from .design_base import (
    FacilityDesignBaseError,
    capture_facility_design_base,
    validate_facility_design_base,
)
from .design_brief import FacilityDesignBriefError
from .design_candidates import FacilityDesignCandidateError, OperationBuilder
from .design_evaluator import FacilityDesignEvaluationError
from .design_repository import (
    FacilityDesignRepository,
    FacilityDesignRepositoryError,
)
from .design_runtime import (
    CandidateRecipeProvider,
    FacilityDesignRuntime,
    FacilityDesignRuntimeError,
)
from .design_service import (
    FacilityDesignLoopService,
    FacilityDesignServiceError,
    validate_facility_design_editor_frame,
)
from .design_source import build_facility_design_source_bundle
from .design_intent import (
    FacilityDesignIntentError,
    compile_facility_design_brief_body,
    compile_facility_design_brief_patch,
)
from .facility_draft_lease import FacilityDraftLeaseError
from .feature_flags import FacilityLayoutFeatureFlags
from .facility_planning import (
    FacilityPlanningPackageError,
    compile_facility_planning_package,
)
from .generation_run_repository import FacilityGenerationRunRepository
from .generation_coordinator import (
    FacilityGenerationCoordinator,
    FacilityGenerationCoordinatorError,
)
from .generation_run_repository import FacilityGenerationRunRepositoryError
from .identity import FacilityPrincipalResolver
from .operations import apply_facility_layout_operations, create_layout_document
from .plan_settings import (
    default_plan_settings,
    plan_settings_from_layout,
    plan_world_bounds,
)
from .repository import (
    FacilityLayoutIntegrityError,
    FacilityLayoutRepository,
)
from .service import FacilityLayoutService, coordinate_frame_fingerprint
from .knowledge_foundation import FacilityKnowledgeContractError
from .manufacturing_snapshot import FacilityManufacturingSnapshotError
from .provider_config import (
    FacilityProviderConfigurationError,
    resolve_facility_provider_config,
)
from .transaction_adapter import FacilityLayoutTransactionRuntime


LOCAL_SITE_ID = "site-local"
LOCAL_LAYOUT_ID = "fl-main"
LOCAL_SHELL_ID = "shell-local"
LOCAL_POLICY_ID = "policy-local"
PRIVATE_ASSET_ENV = "INSPECTORPRO_FACILITY_PRIVATE_ASSETS"
MOTION_PROTOTYPE_ENV = "INSPECTORPRO_FACILITY_MOTION_PROTOTYPE"
PRIVATE_ASSET_MANIFEST = Path(
    "generated/industrial_assets/local_library/catalog.json"
)

_DESIGN_ERRORS = (
    GenerationRequirementError,
    FacilityDesignBaseError,
    FacilityDesignBriefError,
    FacilityDesignCandidateError,
    FacilityDesignEvaluationError,
    FacilityDesignIntentError,
    FacilityDesignRepositoryError,
    FacilityDesignRuntimeError,
    FacilityDesignServiceError,
    FacilityDraftLeaseError,
    FacilityManufacturingSnapshotError,
    FacilityLayoutError,
    FacilityProviderConfigurationError,
)


def _timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _revision(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _asset(
    *,
    asset_id: str,
    display_name: str,
    category: str,
    width: float,
    depth: float,
    height: float,
    description: str,
    connectors: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    definition = {
        "schemaVersion": 1,
        "documentKind": "industrial_asset_definition",
        "assetId": asset_id,
        "displayName": display_name,
        "category": category,
        "description": description,
        "geometry": {
            "aabb": {
                "minimum": {
                    "x": -width / 2,
                    "y": 0,
                    "z": -depth / 2,
                },
                "maximum": {
                    "x": width / 2,
                    "y": height,
                    "z": depth / 2,
                },
            },
            "footprintPolygons": [[
                {"x": -width / 2, "z": -depth / 2},
                {"x": width / 2, "z": -depth / 2},
                {"x": width / 2, "z": depth / 2},
                {"x": -width / 2, "z": depth / 2},
            ]],
            "heightInterval": {
                "minimumY": 0,
                "maximumY": height,
            },
        },
        "clearances": [],
        "connectors": deepcopy(connectors or []),
        "readiness": {
            "visualReady": {"value": True, "blockers": []},
            "placementReady": {"value": True, "blockers": []},
            "planningReady": {
                "value": False,
                "blockers": ["clearance_evidence_missing"],
            },
        },
    }
    return {
        "assetId": asset_id,
        "assetDefinitionRevision": _revision(definition),
        "previewPlanningEligible": True,
        "displayName": display_name,
        "category": category,
        "description": description,
        "definition": definition,
    }


LOCAL_ASSET_CATALOG: tuple[dict[str, Any], ...] = (
    _asset(
        asset_id="asset-cnc-mill",
        display_name="CNC Milling Machine",
        category="Machines",
        width=3.0,
        depth=3.7,
        height=2.7,
        description="Generic placement-ready CNC milling machine envelope.",
    ),
    _asset(
        asset_id="asset-pallet-rack",
        display_name="Pallet Rack",
        category="Storage",
        width=2.7,
        depth=1.1,
        height=3.6,
        description="Generic selective pallet-rack bay.",
    ),
    _asset(
        asset_id="asset-workbench",
        display_name="Assembly Workbench",
        category="Workstations",
        width=1.8,
        depth=0.8,
        height=1.0,
        description="General-purpose manual assembly workstation.",
    ),
    _asset(
        asset_id="asset-material-transfer-buffer",
        display_name="Material Transfer Buffer",
        category="Material Handling",
        width=2.0,
        depth=2.0,
        height=0.3,
        description="Prototype FIFO buffer with revision-bound material connectors.",
        connectors=[
            {
                "connectorId": "material-output",
                "connectorKind": "material",
                "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                "facing": {"x": 1.0, "y": 0.0, "z": 0.0},
                "role": "output",
                "allowedRouteKinds": ["material"],
                "interface": {},
                "capacity": {},
                "evidenceStatus": "authored",
                "evidence": ["local-prototype-material-output"],
            },
            {
                "connectorId": "material-input",
                "connectorKind": "material",
                "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                "facing": {"x": -1.0, "y": 0.0, "z": 0.0},
                "role": "input",
                "allowedRouteKinds": ["material"],
                "interface": {},
                "capacity": {},
                "evidenceStatus": "authored",
                "evidence": ["local-prototype-material-input"],
            },
        ],
    ),
    _asset(
        asset_id="asset-forklift",
        display_name="Electric Forklift",
        category="Material Handling",
        width=1.2,
        depth=3.5,
        height=2.2,
        description="Generic electric counterbalance forklift envelope.",
    ),
)


_PRIVATE_LOCAL_ASSET_SPECS: tuple[dict[str, Any], ...] = (
    {
        "asset_id": "asset-cnc-mill",
        "display_name": "CNC Milling Machine",
        "category": "Machines",
        "width": 3.0,
        "depth": 3.718252,
        "height": 2.7,
        "description": "Private local CNC vertical machining center model.",
        "artifact": (
            "generated/industrial_assets/p0_spike/cnc_vmc/"
            "User Library-CNC Milling machine_colored.glb"
        ),
        "source_to_canonical": (
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 1.159126, 1.0,
        ),
    },
    {
        "asset_id": "asset-pallet-rack",
        "display_name": "Pallet Rack",
        "category": "Storage",
        "width": 1.227199912,
        "depth": 2.528399944,
        "height": 4.87680006,
        "description": "Private local selective pallet-rack model.",
        "artifact": (
            "generated/industrial_assets/p0_spike/rack_prototypes/"
            "Pallet Racking_colored.glb"
        ),
        "source_to_canonical": (
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ),
    },
    {
        "asset_id": "asset-workbench",
        "display_name": "Assembly Workbench",
        "category": "Workstations",
        "width": 1.2192002062,
        "depth": 1.0541,
        "height": 0.8636001031,
        "description": "Private local WA01 assembly workstation model.",
        "artifact": (
            "generated/industrial_assets/p0_spike/wa01_workstation/"
            "RF--WA01-W48-D36-H34-T0_375-UF-F0-P5002_colored.glb"
        ),
        "source_to_canonical": (
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.8540751031, 0.0, 1.0,
        ),
    },
    {
        "asset_id": "asset-forklift",
        "display_name": "Electric Forklift",
        "category": "Material Handling",
        "width": 1.130300046,
        "depth": 1.962149978,
        "height": 2.501774646,
        "description": "Private local Toyota electric forklift model.",
        "artifact": (
            "generated/industrial_assets/p0_spike/toyota_forklift/"
            "User Library-Toyota Forklift_colored.glb"
        ),
        "source_to_canonical": (
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.076074697, -0.981074989, 1.0,
        ),
    },
)


def _private_manifest_specs(root: Path) -> tuple[dict[str, Any], ...]:
    """Load bounded local-only catalog records generated from private CAD."""

    manifest_path = root / PRIVATE_ASSET_MANIFEST
    if not manifest_path.is_file():
        return ()
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Private asset manifest is unreadable: {manifest_path}"
        ) from exc
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise ValueError("Private asset manifest schemaVersion must be 1")
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise ValueError("Private asset manifest assets must be an array")

    specs: list[dict[str, Any]] = []
    seen: set[str] = set()
    reserved = {
        str(item["asset_id"])
        for item in _PRIVATE_LOCAL_ASSET_SPECS
    }
    for index, raw in enumerate(assets):
        if not isinstance(raw, dict):
            raise ValueError(f"Private asset manifest entry {index} is invalid")
        asset_id = str(raw.get("assetId", "")).strip()
        if (
            not asset_id.startswith("asset-")
            or asset_id in seen
            or asset_id in reserved
        ):
            raise ValueError(
                f"Private asset manifest assetId is invalid: {asset_id!r}"
            )
        seen.add(asset_id)
        display_name = str(raw.get("displayName", "")).strip()
        category = str(raw.get("category", "")).strip()
        description = str(raw.get("description", "")).strip()
        if not display_name or not category or not description:
            raise ValueError(
                f"Private asset manifest metadata is incomplete: {asset_id}"
            )
        dimensions = raw.get("dimensions")
        if not isinstance(dimensions, dict):
            raise ValueError(
                f"Private asset manifest dimensions are missing: {asset_id}"
            )
        measured = []
        for field in ("width", "depth", "height"):
            value = dimensions.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(
                    f"Private asset manifest {field} is invalid: {asset_id}"
                )
            number = float(value)
            if not math.isfinite(number) or number <= 0:
                raise ValueError(
                    f"Private asset manifest {field} is invalid: {asset_id}"
                )
            measured.append(number)

        artifact = Path(str(raw.get("artifact", "")))
        if (
            artifact.is_absolute()
            or ".." in artifact.parts
            or artifact.suffix.lower() != ".glb"
        ):
            raise ValueError(
                f"Private asset manifest artifact is invalid: {asset_id}"
            )
        matrix = raw.get("sourceToCanonical")
        if (
            not isinstance(matrix, list)
            or len(matrix) != 16
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                for value in matrix
            )
        ):
            raise ValueError(
                f"Private asset manifest transform is invalid: {asset_id}"
            )
        tags = raw.get("tags", [])
        if not isinstance(tags, list) or any(
            not isinstance(value, str) or not value.strip()
            for value in tags
        ):
            raise ValueError(
                f"Private asset manifest tags are invalid: {asset_id}"
            )
        footprint_polygons = None
        if "footprintPolygons" in raw:
            from .spatial import _convex_hull, _polygon, _polygon_is_convex, polygon_area

            polygons = raw["footprintPolygons"]
            if not isinstance(polygons, list) or not 1 <= len(polygons) <= 64:
                raise ValueError(f"Private asset footprint polygons are invalid: {asset_id}")
            footprint_polygons = []
            for polygon in polygons:
                if (
                    not isinstance(polygon, list) or not 3 <= len(polygon) <= 32
                    or any(not isinstance(p, dict) or set(p) != {"x", "z"} for p in polygon)
                ):
                    raise ValueError(f"Private asset footprint polygon is invalid: {asset_id}")
                points = _polygon(polygon, "private asset footprint")
                if (
                    len(set(points)) != len(points)
                    or not _polygon_is_convex(points)
                    or abs(abs(polygon_area(points)) - abs(polygon_area(_convex_hull(points)))) > 1e-8
                    or any(abs(x) > measured[0] / 2 + 1e-8 or abs(z) > measured[1] / 2 + 1e-8 for x, z in points)
                ):
                    raise ValueError(f"Private asset footprint must be convex and inside its bounds: {asset_id}")
                footprint_polygons.append([{"x": x, "z": z} for x, z in points])
        raw_surfaces = raw.get("supportSurfaces", [])
        if not isinstance(raw_surfaces, list):
            raise ValueError(
                f"Private asset support surfaces are invalid: {asset_id}"
            )
        support_surfaces: list[dict[str, Any]] = []
        surface_ids: set[str] = set()
        for surface_index, raw_surface in enumerate(raw_surfaces):
            if not isinstance(raw_surface, dict):
                raise ValueError(
                    f"Private asset support surface is invalid: {asset_id}"
                )
            fields = {
                "surfaceId",
                "label",
                "localFrame",
                "bounds",
                "allowedSides",
                "evidenceStatus",
            }
            if set(raw_surface) != fields:
                raise ValueError(
                    f"Private asset support surface fields are invalid: {asset_id}"
                )
            surface_id = str(raw_surface.get("surfaceId", "") or "").strip()
            label = str(raw_surface.get("label", "") or "").strip()
            if not surface_id or surface_id in surface_ids or not label:
                raise ValueError(
                    f"Private asset support surface identity is invalid: {asset_id}"
                )
            surface_ids.add(surface_id)
            frame = raw_surface.get("localFrame")
            bounds = raw_surface.get("bounds")
            if not isinstance(frame, dict) or set(frame) != {
                "origin", "xAxis", "zAxis", "normal"
            }:
                raise ValueError(
                    f"Private asset support surface frame is invalid: {asset_id}"
                )
            normalized_frame: dict[str, dict[str, float]] = {}
            for vector_name in ("origin", "xAxis", "zAxis", "normal"):
                vector = frame.get(vector_name)
                if not isinstance(vector, dict) or set(vector) != {"x", "y", "z"}:
                    raise ValueError(
                        f"Private asset support surface vector is invalid: {asset_id}"
                    )
                normalized_vector = {}
                for axis in ("x", "y", "z"):
                    value = vector.get(axis)
                    if isinstance(value, bool) or not isinstance(value, (int, float)):
                        raise ValueError(
                            f"Private asset support surface vector is invalid: {asset_id}"
                        )
                    number = float(value)
                    if not math.isfinite(number):
                        raise ValueError(
                            f"Private asset support surface vector is invalid: {asset_id}"
                        )
                    normalized_vector[axis] = number
                normalized_frame[vector_name] = normalized_vector
            bound_fields = {"minimumX", "maximumX", "minimumZ", "maximumZ"}
            if not isinstance(bounds, dict) or set(bounds) != bound_fields:
                raise ValueError(
                    f"Private asset support surface bounds are invalid: {asset_id}"
                )
            normalized_bounds = {}
            for field in sorted(bound_fields):
                value = bounds.get(field)
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(
                        f"Private asset support surface bounds are invalid: {asset_id}"
                    )
                number = float(value)
                if not math.isfinite(number):
                    raise ValueError(
                        f"Private asset support surface bounds are invalid: {asset_id}"
                    )
                normalized_bounds[field] = number
            if (
                normalized_bounds["minimumX"] >= normalized_bounds["maximumX"]
                or normalized_bounds["minimumZ"] >= normalized_bounds["maximumZ"]
            ):
                raise ValueError(
                    f"Private asset support surface bounds are empty: {asset_id}"
                )
            allowed_sides = raw_surface.get("allowedSides")
            if (
                not isinstance(allowed_sides, list)
                or not allowed_sides
                or len(allowed_sides) != len(set(allowed_sides))
                or any(side not in {"above", "below"} for side in allowed_sides)
            ):
                raise ValueError(
                    f"Private asset support surface sides are invalid: {asset_id}"
                )
            evidence_status = str(
                raw_surface.get("evidenceStatus", "") or ""
            ).strip()
            if evidence_status not in {
                "authored", "derived", "inferred", "unverified", "unknown"
            }:
                raise ValueError(
                    f"Private asset support surface evidence is invalid: {asset_id}"
                )
            support_surfaces.append({
                "surfaceId": surface_id,
                "label": label,
                "localFrame": normalized_frame,
                "bounds": normalized_bounds,
                "allowedSides": list(allowed_sides),
                "evidenceStatus": evidence_status,
            })
        specs.append({
            "asset_id": asset_id,
            "display_name": display_name,
            "category": category,
            "width": measured[0],
            "depth": measured[1],
            "height": measured[2],
            "description": description,
            "artifact": artifact.as_posix(),
            "source_to_canonical": tuple(float(value) for value in matrix),
            "tags": tuple(value.strip() for value in tags),
            "support_surfaces": tuple(support_surfaces),
            "footprint_polygons": footprint_polygons,
        })
    return tuple(specs)


def _environment_enabled(name: str) -> bool:
    return str(os.getenv(name, "") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def build_private_local_asset_catalog(
    project_root: str | Path | None = None,
) -> tuple[dict[str, Any], ...]:
    """Bind private local GLBs without exposing protected source paths."""

    root = (
        Path(project_root).resolve()
        if project_root is not None
        else Path(__file__).resolve().parents[2]
    )
    catalog: list[dict[str, Any]] = []
    specs = (*_PRIVATE_LOCAL_ASSET_SPECS, *_private_manifest_specs(root))
    for spec in specs:
        entry = _asset(
            asset_id=str(spec["asset_id"]),
            display_name=str(spec["display_name"]),
            category=str(spec["category"]),
            width=float(spec["width"]),
            depth=float(spec["depth"]),
            height=float(spec["height"]),
            description=str(spec["description"]),
        )
        matrix = [float(value) for value in spec["source_to_canonical"]]
        entry["definition"]["coordinateFrame"] = {
            "units": "m",
            "handedness": "right",
            "upAxis": "+Y",
            "sourceToCanonical": matrix,
        }
        support_surfaces = [
            deepcopy(surface)
            for surface in spec.get("support_surfaces", ())
        ]
        if spec.get("footprint_polygons") is not None:
            entry["definition"]["geometry"]["footprintPolygons"] = deepcopy(spec["footprint_polygons"])
        if support_surfaces:
            entry["supportSurfaces"] = support_surfaces
            entry["definition"]["supportSurfaces"] = support_surfaces
        entry["assetDefinitionRevision"] = _revision(entry["definition"])
        tags = [str(value) for value in spec.get("tags", ())]
        if tags:
            entry["tags"] = tags
            entry["definition"]["tags"] = tags
            entry["assetDefinitionRevision"] = _revision(entry["definition"])

        relative = Path(str(spec["artifact"]))
        artifact_path = root / relative
        available = artifact_path.is_file()
        entry["privateLocalVisual"] = {
            "enabled": True,
            "available": available,
        }
        if available:
            # A lighter copy beside the model (<name>.overview.glb: the same parts and materials at a
            # fraction of the triangles) is what busy layouts draw; the full model stays as the detail.
            light = artifact_path.with_name(artifact_path.stem + ".overview.glb")
            shown = relative.with_name(light.name) if light.is_file() else relative
            entry["overview"] = {
                "path": "/" + quote(shown.as_posix(), safe="/"),
                "byteSize": (root / shown).stat().st_size,
                "sourceToCanonical": matrix,
                "instancingEligible": True,
            }
            if shown != relative:
                entry["detail"] = {
                    "path": "/" + quote(relative.as_posix(), safe="/"),
                    "byteSize": artifact_path.stat().st_size,
                    "sourceToCanonical": matrix,
                    "instancingEligible": True,
                }
        thumbnail_relative = relative.parent / "thumbnail.webp"
        if (root / thumbnail_relative).is_file():
            entry["thumbnail"] = {
                "path": "/" + quote(
                    thumbnail_relative.as_posix(), safe="/"
                ),
                "mediaType": "image/webp",
            }
        catalog.append(entry)
    return tuple(catalog)


def _shell_document() -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "documentKind": "facility_shell",
        "shellId": LOCAL_SHELL_ID,
        "tenantId": "local",
        "siteId": LOCAL_SITE_ID,
        "status": "draft",
        "coordinateFrame": {
            "units": "m",
            "handedness": "right",
            "upAxis": "+Y",
            "floorAxes": ["+X", "+Z"],
            "datumId": "local-origin",
            "floorElevation": 0,
        },
        "features": [{
            "featureId": "floor-main",
            "featureKind": "floor_surface",
            "geometry": {
                "boundary": [
                    {"x": 0, "z": 0},
                    {"x": 40, "z": 0},
                    {"x": 40, "z": 30},
                    {"x": 0, "z": 30},
                ],
                "elevation": 0,
            },
            "evidence": [],
        }],
        "shellConnectors": [],
        "sourceDocuments": [],
        "evidence": [],
        "unresolvedItems": [{
            "findingId": "finding-local-shell-review",
            "code": "local_shell_requires_site_review",
            "message": (
                "Replace the starter floor boundary with reviewed site data "
                "before safety or installation decisions."
            ),
        }],
    }


def _policy_document() -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "documentKind": "policy_set",
        "policySetId": LOCAL_POLICY_ID,
        "tenantId": "local",
        "siteId": LOCAL_SITE_ID,
        "status": "draft",
        "applicability": {"areaIds": ["main"]},
        "deterministicRules": [],
        "sourceDocuments": [],
        "evidence": [],
        "unresolvedItems": [{
            "findingId": "finding-local-policy-review",
            "code": "facility_policy_not_configured",
            "message": (
                "Site-specific clearance, egress, and safety policy has not "
                "been configured."
            ),
        }],
    }


class LocalFacilityLayoutHost:
    """Own the local-mode repositories, bootstrap, and product router."""

    def __init__(
        self,
        root: str | Path,
        *,
        process_map_root: str | Path | None = None,
        feature_flags: FacilityLayoutFeatureFlags | None = None,
        private_assets: bool | None = None,
        private_asset_root: str | Path | None = None,
        facility_planning_root: str | Path | None = None,
        require_distinct_approver: bool = False,
        principal_resolver: (
            Callable[[Request], FacilityPrincipal] | None
        ) = None,
        design_source_provider: (
            Callable[
                [
                    FacilityPrincipal,
                    str,
                    str,
                    Mapping[str, Any],
                    Mapping[str, Any],
                ],
                Mapping[str, Any],
            ]
            | None
        ) = None,
        design_candidate_recipe_provider: CandidateRecipeProvider | None = None,
        design_operation_builder: OperationBuilder | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.process_map_root = (
            Path(process_map_root).resolve()
            if process_map_root is not None
            else None
        )
        self.facility_planning_root = (
            Path(facility_planning_root).resolve()
            if facility_planning_root is not None
            else None
        )
        self.feature_flags = (
            feature_flags
            if feature_flags is not None
            else FacilityLayoutFeatureFlags.all_enabled()
        )
        self.require_distinct_approver = bool(
            require_distinct_approver
        )
        if self.require_distinct_approver and (
            not isinstance(
                principal_resolver,
                FacilityPrincipalResolver,
            )
            or not principal_resolver.authenticated
        ):
            raise ValueError(
                "Maker-checker mode requires the authenticated Facility "
                "pilot principal resolver."
            )
        self._principal_resolver = principal_resolver
        self.principal_mode = (
            str(getattr(principal_resolver, "mode", "custom"))
            if principal_resolver is not None
            else "local"
        )
        authority_root = self.root / "authorities"
        self.layout_repository = FacilityLayoutRepository(self.root / "layouts")
        self.generation_run_repository = FacilityGenerationRunRepository(
            self.root
        )
        self.generation_coordinator = FacilityGenerationCoordinator(
            self.generation_run_repository,
            feature_flags=self.feature_flags,
        )
        self.design_repository = FacilityDesignRepository(self.root)
        self.design_runtime = FacilityDesignRuntime(
            self.design_repository,
            candidate_recipe_provider=design_candidate_recipe_provider,
            operation_builder=design_operation_builder,
        )
        self.design_loop_service = FacilityDesignLoopService(
            repository=self.design_repository,
            runtime=self.design_runtime,
            lease_repository=(
                self.generation_run_repository.draft_lease_repository
            ),
            feature_flags=self.feature_flags,
        )
        self._design_source_provider = design_source_provider
        self.shell_repository = FacilityShellRepository(
            authority_root / "shells"
        )
        self.policy_repository = PolicySetRepository(
            authority_root / "policies"
        )
        self.vehicle_repository = VehicleProfileRepository(
            authority_root / "vehicles"
        )
        use_private_assets = (
            _environment_enabled(PRIVATE_ASSET_ENV)
            if private_assets is None
            else bool(private_assets)
        )
        self._component_visual_root = (Path(private_asset_root).resolve()
            if private_asset_root is not None else Path(__file__).resolve().parents[2])
        catalog_source = (
            build_private_local_asset_catalog(private_asset_root)
            if use_private_assets
            else LOCAL_ASSET_CATALOG
        )
        # Model-space data (footprints, support surfaces, reviewed sides and
        # seats) is authored in each model file's own axes; the catalog carries
        # it in the layout's model space, mirrored once across x = 0 (model_axes).
        self._catalog = {
            item["assetId"]: mirror_catalog_record(attach_registered_semantics(item))
            for item in catalog_source
        }
        # Private visual definitions are new immutable revisions, not
        # replacements for revisions already referenced by saved layouts.
        # Keep both so existing placements remain verifiable while the asset
        # browser offers the current private definition for new placements.
        self._asset_versions = {
            (item["assetId"], item["assetDefinitionRevision"]): mirror_catalog_record(item)
            for item in (*LOCAL_ASSET_CATALOG, *catalog_source)
        }
        self.transaction_runtime = FacilityLayoutTransactionRuntime(
            receipt_root=self.root / "transactions",
            require_distinct_approver=self.require_distinct_approver,
        )
        self.service = FacilityLayoutService(
            layout_repository=self.layout_repository,
            shell_repository=self.shell_repository,
            policy_repository=self.policy_repository,
            vehicle_repository=self.vehicle_repository,
            asset_definition_resolver=self._resolve_asset_definition,
            current_asset_definition_resolver=(
                self._resolve_current_asset_definition
            ),
            component_inventory_resolver=self._resolve_component_inventory,
            process_map_resolver=(
                self._resolve_process_map
                if self.process_map_root is not None
                else None
            ),
            transaction_runtime=self.transaction_runtime,
            capability_gate=self.feature_flags.require,
            allow_prototype_motion=_environment_enabled(
                MOTION_PROTOTYPE_ENV
            ),
        )
        self.agent_runtime = FacilityLayoutAgentRuntime(
            service=self.service,
            shell_repository=self.shell_repository,
            policy_repository=self.policy_repository,
            vehicle_repository=self.vehicle_repository,
            asset_catalog_provider=self._agent_asset_catalog,
            process_catalog_provider=self._agent_process_catalog,
            capabilities_provider=self._agent_capabilities,
            generation_layout_provider=self._agent_generation_layout,
        )
        # Sage's 3D shots (docs/sage-basic-shapes-plan.md, SV2 and SV3): show_facility_views waits here for the
        # shots the app window takes, and the chat links to them.
        from .sage_shots import SageShots
        self.sage_shots = SageShots(self.root / "sage-shots")
        self.agent_runtime.sage_shots = self.sage_shots
        self.construction_service = FacilityConstructionService(
            service=self.service, agent_runtime=self.agent_runtime,
            repository=self.design_repository, capability_gate=self.feature_flags.require,
        )
        self.generation_requirement_repository = GenerationRequirementRepository(self.root)
        self.generation_admission_service = FacilityGenerationAdmissionService(
            service=self.service, agent_runtime=self.agent_runtime,
            repository=self.generation_requirement_repository, capability_gate=self.feature_flags.require,
            lease_repository=self.generation_run_repository.draft_lease_repository,
            process_map_resolver=self._resolve_process_map, catalog_provider=self._agent_asset_catalog,
        )
        self._lock = threading.RLock()
        self.generation_agent_service = FacilityGenerationAgentService(self.generation_admission_service)
        self.generation_draft_adapter = GenerationDraftAdapter(self.generation_admission_service, self.design_repository)
        self._bootstrapped = False

    @staticmethod
    def principal() -> FacilityPrincipal:
        return local_facility_principal(site_id=LOCAL_SITE_ID)

    def _resolve_component_inventory(self, principal, reference, placement_id, representation, *, asset=None):
        from ai_inspector.codex_runtime.component_inventory import resolve_component_inventory
        return resolve_component_inventory(self.agent_runtime, principal, reference,
            placement_id, representation, project_root=self._component_visual_root, asset=asset)

    def _load_facility_planning_package(
        self,
        package_id: str,
    ) -> dict[str, Any]:
        if self.facility_planning_root is None:
            raise FacilityPlanningPackageError(
                "facility_planning_package_unavailable",
                "Facility Planning packages are not configured for this host.",
            )
        matches: list[dict[str, Any]] = []
        for path in sorted(self.facility_planning_root.rglob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if (
                isinstance(value, Mapping)
                and str(value.get("packageId") or "") == package_id
            ):
                matches.append(deepcopy(dict(value)))
        if len(matches) != 1:
            raise FacilityPlanningPackageError(
                "facility_planning_package_unavailable",
                "The requested Facility Planning package did not resolve uniquely.",
                details={"planningPackageId": package_id, "matchCount": len(matches)},
            )
        return matches[0]

    def close(self) -> None:
        """Close every open Sage shots request first (whatever waits on one is answered, and a late upload is
        refused), give queued shot deletes up to 2 s (what is left is swept on a later start), then release the
        bounded background spatial workers."""

        self.sage_shots.shutdown(2.0)
        self.service.spatial_executor.close(wait=True)

    def _agent_generation_layout(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        saved_revision: str,
        live_facts: Mapping[str, Any] | None,
    ) -> Mapping[str, Any] | None:
        """Resolve a browser pointer to one owned, revision-bound draft."""

        pointer = (
            live_facts.get("generationDraft")
            if isinstance(live_facts, Mapping)
            and isinstance(live_facts.get("generationDraft"), Mapping)
            else None
        )
        if not isinstance(pointer, Mapping) or pointer.get("active") is not True:
            return None
        run_id = str(pointer.get("runId") or "").strip()
        if not run_id:
            raise FacilityLayoutAgentRuntimeError(
                "facility_generation_context_run_missing",
                "The active Facility generation draft has no run identity.",
                status_code=409,
            )
        try:
            artifacts = self.generation_run_repository.get_execution_artifacts(
                principal.tenant_id,
                site_id,
                run_id,
            )
        except FacilityGenerationRunRepositoryError as exc:
            raise FacilityLayoutAgentRuntimeError(
                "facility_generation_context_unavailable",
                "The active Facility generation draft is unavailable.",
                status_code=409,
                details={"runId": run_id, "reason": exc.code},
            ) from exc
        run = artifacts["run"]["run"]
        draft = artifacts["draft"]
        pointer_base = str(pointer.get("baseLayoutRevision") or "")
        pointer_draft = str(pointer.get("draftLayoutRevision") or "")
        mismatch = (
            run.get("tenantId") != principal.tenant_id
            or run.get("siteId") != site_id
            or run.get("layoutId") != layout_id
            or run.get("userId") != principal.principal_id
            or run.get("baseLayoutRevision") != saved_revision
            or (pointer_base and pointer_base != saved_revision)
            or draft.get("document", {}).get("layoutId") != layout_id
            or (
                pointer_draft
                and pointer_draft != draft.get("draftLayoutRevision")
            )
            or run.get("writable") is not True
            or run.get("status")
            not in {"active", "pending", "running", "complete"}
        )
        if mismatch:
            raise FacilityLayoutAgentRuntimeError(
                "facility_generation_context_conflict",
                "The active Facility generation pointer is stale or not owned by this session.",
                status_code=409,
                details={"runId": run_id},
            )
        return {
            "layout": deepcopy(draft["document"]),
            "revision": draft["draftLayoutRevision"],
            "baseRevision": saved_revision,
            "runId": run_id,
            "provider": "facility-generation-run-repository",
        }

    def _resolve_asset_definition(
        self,
        _principal: FacilityPrincipal,
        _site_id: str,
        asset_id: str,
        revision: str,
    ) -> Mapping[str, Any] | None:
        entry = self._asset_versions.get((asset_id, revision))
        if entry is None:
            entry = self._catalog.get(asset_id)
        if entry is None:
            return None
        return {
            "revision": entry["assetDefinitionRevision"],
            "definition": deepcopy(entry["definition"]),
        }

    def _resolve_current_asset_definition(
        self,
        _principal: FacilityPrincipal,
        _site_id: str,
        asset_id: str,
    ) -> Mapping[str, Any] | None:
        entry = self._catalog.get(asset_id)
        if entry is None:
            return None
        return {
            "revision": entry["assetDefinitionRevision"],
            "definition": deepcopy(entry["definition"]),
        }

    def _resolve_process_map(
        self,
        _principal: FacilityPrincipal,
        _site_id: str,
        product_id: str,
        map_id: str,
        revision: str,
    ) -> Mapping[str, Any] | None:
        if self.process_map_root is None:
            return None
        from ai_inspector.process_map.repository import (
            ProcessMapAssetError,
            load_named_process_map_revision,
        )

        try:
            result = load_named_process_map_revision(
                self.process_map_root,
                product_id,
                map_id,
                revision,
            )
        except ProcessMapAssetError:
            return None
        return {
            "revision": result["revision"],
            "document": deepcopy(result["map"]),
        }

    def _agent_asset_catalog(
        self,
        _principal: FacilityPrincipal,
        site_id: str,
    ) -> list[dict[str, Any]]:
        if site_id != LOCAL_SITE_ID:
            raise FacilityNotFoundError(
                "not_found",
                "Facility resource was not found.",
            )
        return deepcopy(list(self._catalog.values()))

    def authoritative_asset_catalog(self) -> list[dict[str, Any]]:
        """Return revision-bound asset definitions for server-side analysis."""

        return deepcopy(list(self._asset_versions.values()))

    def _agent_process_catalog(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        if site_id != LOCAL_SITE_ID:
            raise FacilityNotFoundError(
                "not_found",
                "Facility resource was not found.",
            )
        result = []
        seen = set()
        for binding in layout.get("processBindings", []):
            if not isinstance(binding, Mapping):
                continue
            key = (
                str(binding.get("productId") or ""),
                str(binding.get("processMapId") or ""),
                str(binding.get("processMapRevision") or ""),
            )
            if not all(key) or key in seen:
                continue
            seen.add(key)
            resolved = self._resolve_process_map(
                principal,
                site_id,
                key[0],
                key[1],
                key[2],
            )
            if (
                not isinstance(resolved, Mapping)
                or resolved.get("revision") != key[2]
                or not isinstance(resolved.get("document"), Mapping)
            ):
                continue
            document = resolved["document"]
            precedence_edges = []
            for edge in document.get("canvasEdges", []):
                if not isinstance(edge, Mapping):
                    continue
                from_ref = edge.get("from")
                from_ref = from_ref if isinstance(from_ref, Mapping) else {}
                to_ref = edge.get("to")
                to_ref = to_ref if isinstance(to_ref, Mapping) else {}
                from_node_id = str(
                    edge.get("fromNodeId")
                    or from_ref.get("nodeId")
                    or ""
                )
                to_node_id = str(
                    edge.get("toNodeId")
                    or to_ref.get("nodeId")
                    or ""
                )
                edge_id = str(edge.get("edgeId") or edge.get("id") or "")
                if not edge_id or not from_node_id or not to_node_id:
                    continue
                precedence_edges.append({
                    "edgeId": edge_id,
                    "fromNodeId": from_node_id,
                    "toNodeId": to_node_id,
                    "edgeKind": str(edge.get("kind") or "precedence"),
                    "evidenceStatus": "authored",
                })
            result.append(
                {
                    "productId": key[0],
                    "processMapId": key[1],
                    "processMapRevision": key[2],
                    "displayName": str(
                        document.get("displayName") or key[1]
                    ),
                    "nodeIds": sorted(
                        {
                            str(item.get("nodeId") or item.get("id"))
                            for item in document.get("canvasNodes", [])
                            if isinstance(item, Mapping)
                            and (item.get("nodeId") or item.get("id"))
                        }
                    ),
                    "edgeIds": sorted(
                        {
                            str(item.get("edgeId") or item.get("id"))
                            for item in document.get("canvasEdges", [])
                            if isinstance(item, Mapping)
                            and (item.get("edgeId") or item.get("id"))
                        }
                    ),
                    "graphTopologyLoaded": True,
                    "precedenceEdges": sorted(
                        precedence_edges,
                        key=lambda item: item["edgeId"],
                    ),
                }
            )
        return sorted(
            result,
            key=lambda item: (
                item["processMapId"],
                item["processMapRevision"],
            ),
        )

    def _resolve_design_source_bundle(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        design_base: Mapping[str, Any],
        design_brief: Mapping[str, Any],
    ) -> dict[str, Any]:
        if self._design_source_provider is not None:
            source = self._design_source_provider(
                principal,
                site_id,
                layout_id,
                design_base,
                design_brief,
            )
        else:
            source = build_facility_design_source_bundle(
                design_base=design_base,
                design_brief=design_brief,
                asset_definitions=self.authoritative_asset_catalog(),
                process_map_resolver=lambda product_id, map_id, revision: (
                    self._resolve_process_map(
                        principal,
                        site_id,
                        product_id,
                        map_id,
                        revision,
                    )
                ),
            )
        if not isinstance(source, Mapping):
            raise FacilityDesignServiceError(
                "facility_design_source_bundle_invalid",
                "The authoritative design source provider returned no evidence object.",
            )
        return deepcopy(dict(source))

    def _design_brief_and_base(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        brief_id: str,
        *,
        brief_revision: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        envelope = self.design_repository.get_brief(
            principal.tenant_id,
            site_id,
            brief_id,
            brief_revision=brief_revision,
        )
        brief = envelope["brief"]
        body = brief["semanticBody"]
        if (
            body["tenantId"] != principal.tenant_id
            or body["siteId"] != site_id
            or body["layoutId"] != layout_id
        ):
            raise FacilityDesignServiceError(
                "facility_design_scope_mismatch",
                "Facility design brief is outside the requested layout scope.",
            )
        base_state = body["baseStateRef"]
        base = self.design_repository.get_artifact(
            principal.tenant_id,
            site_id,
            "design_base",
            base_state["baseId"],
            base_state["baseRevision"],
        )["artifact"]
        return envelope, validate_facility_design_base(base)

    @staticmethod
    def _design_source_turn(request: Request, body: Mapping[str, Any]) -> str:
        raw = str(
            body.get("sourceTurnRef")
            or request.headers.get("X-InspectorPro-Agent-Turn")
            or request.headers.get("X-InspectorPro-Session")
            or "facility-design-turn"
        ).strip()
        normalized = re.sub(r"[^A-Za-z0-9._:-]+", "-", raw).strip("-.")
        if normalized and normalized[0].isalnum():
            return normalized[:160]
        return "turn-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _capture_design_base_from_editor(
        self,
        *,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        request: Request,
        body: Mapping[str, Any],
        current: Mapping[str, Any],
    ) -> dict[str, Any]:
        frame = validate_facility_design_editor_frame(
            self._authoritative_design_editor_frame(
                body.get("editorFrame"),
                current=current,
                tenant_id=principal.tenant_id,
                site_id=site_id,
                layout_id=layout_id,
            )
        )
        if (
            frame["baseRevision"] != current["revision"]
            or frame["baseLayout"].get("layoutId") != layout_id
            or frame["draftLayout"].get("layoutId") != layout_id
        ):
            raise FacilityDesignServiceError(
                "facility_design_base_scope_mismatch",
                "The editor frame is not based on the current authorized layout.",
            )
        is_saved = bool(
            frame["draftRevision"] == frame["baseRevision"]
            and not frame["batches"]
            and frame["cursor"] == 0
            and frame["generatedDraft"] is None
            and frame["activeProposal"] is None
        )
        base_kind = "saved_layout" if is_saved else "editor_draft"
        session_value = str(
            request.headers.get("X-InspectorPro-Session")
            or "facility-design-editor"
        )
        editor_session_id = "editor-" + hashlib.sha256(
            session_value.encode("utf-8")
        ).hexdigest()[:24]
        if is_saved:
            source_ref = {
                "repositoryRecordRevision": current["revision"],
                "savedLayoutRevision": current["revision"],
            }
        else:
            source_ref = {
                "editorSessionId": editor_session_id,
                "editorGenerationId": frame["editorGenerationId"],
                "commandJournalHash": frame["commandJournalHash"],
                "savedBaseRevision": frame["baseRevision"],
                "capturedDraftRevision": frame["draftRevision"],
            }
        base_seed = {
            "layoutId": layout_id,
            "draftRevision": frame["draftRevision"],
            "editorGenerationId": frame["editorGenerationId"],
            "commandJournalHash": frame["commandJournalHash"],
        }
        base_id = "fdb-" + _revision(base_seed)[:24]
        return capture_facility_design_base(
            base_id=base_id,
            base_kind=base_kind,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            workspace_id=str(body.get("workspaceId") or "workspace-local"),
            document=frame["draftLayout"],
            saved_layout_revision=current["revision"],
            source_ref=source_ref,
            captured_at=_timestamp(),
        )

    def _authoritative_design_editor_frame(
        self,
        raw_frame: Any,
        *,
        current: Mapping[str, Any],
        tenant_id: str,
        site_id: str,
        layout_id: str,
    ) -> Any:
        """Restore JSON number lexemes from authoritative editor inputs.

        Browsers cannot preserve the difference between JSON ``30.0`` and
        ``30``. Facility revisions can, so the server reconstructs ordinary
        edits from the active command journal and proposal drafts from their
        immutable candidate artifact before validating the frame. No geometry
        or revision is trusted unless the semantic document, transaction, and
        supplied revision all agree.
        """

        if not isinstance(raw_frame, Mapping):
            return raw_frame
        frame = deepcopy(dict(raw_frame))
        if frame.get("baseRevision") != current.get("revision"):
            return frame
        try:
            authoritative_base = canonicalize_layout(current["layout"])
            submitted_base = canonicalize_layout(frame.get("baseLayout"))
        except (KeyError, TypeError, ValueError, FacilityLayoutError):
            return frame
        if submitted_base != authoritative_base:
            return frame
        frame["baseLayout"] = authoritative_base

        if frame.get("generatedDraft") is not None:
            return frame
        active_proposal = frame.get("activeProposal")
        if active_proposal is not None:
            if not isinstance(active_proposal, Mapping):
                return frame
            try:
                transaction = self.design_repository.get_transaction(
                    tenant_id,
                    site_id,
                    str(active_proposal["transactionId"]),
                )
                transaction_body = transaction["transaction"]
                proposal_binding = transaction_body["proposalBinding"]
                candidate_ref = transaction_body["selectedCandidateRef"]
                candidate = self.design_repository.get_artifact(
                    tenant_id,
                    site_id,
                    candidate_ref["artifactKind"],
                    candidate_ref["artifactId"],
                    candidate_ref["artifactRevision"],
                )["artifact"]
                authoritative_draft = canonicalize_layout(
                    candidate["candidateLayout"]
                )
                submitted_draft = canonicalize_layout(
                    frame.get("draftLayout")
                )
            except (
                KeyError,
                TypeError,
                ValueError,
                FacilityDesignRepositoryError,
                FacilityLayoutError,
            ):
                return frame
            result_revision = proposal_binding.get("resultLayoutRevision")
            active_matches = bool(
                transaction_body.get("layoutId") == layout_id
                and transaction_body.get("status")
                in {"installation_pending", "active"}
                and active_proposal.get("proposalId")
                == proposal_binding.get("proposalId")
                and active_proposal.get("proposalRevision")
                == proposal_binding.get("proposalRevision")
                and active_proposal.get("transactionRevision")
                == transaction.get("transactionRevision")
                and active_proposal.get("transactionBindingRevision")
                == transaction_body.get(
                    "installationBindingTransactionRevision"
                )
                and frame.get("draftRevision") == result_revision
                and candidate.get("resultLayoutRevision") == result_revision
                and layout_revision(authoritative_draft) == result_revision
                and submitted_draft == authoritative_draft
            )
            if active_matches:
                frame["draftLayout"] = authoritative_draft
            return frame
        batches = frame.get("batches")
        cursor = frame.get("cursor")
        if (
            not isinstance(batches, list)
            or isinstance(cursor, bool)
            or not isinstance(cursor, int)
            or cursor < 0
            or cursor > len(batches)
        ):
            return frame
        operations: list[dict[str, Any]] = []
        for batch in batches[:cursor]:
            if not isinstance(batch, Mapping) or not isinstance(
                batch.get("operations"), list
            ):
                return frame
            if not all(isinstance(item, Mapping) for item in batch["operations"]):
                return frame
            operations.extend(deepcopy(batch["operations"]))
        try:
            submitted_draft = canonicalize_layout(frame.get("draftLayout"))
            updated_at = submitted_draft.get("updatedAt") if operations else None
            reconstructed = apply_facility_layout_operations(
                authoritative_base,
                operations,
                base_revision=str(current["revision"]),
                updated_at=(str(updated_at) if updated_at is not None else None),
            )["document"]
        except (KeyError, TypeError, ValueError, FacilityLayoutError):
            return frame
        if (
            reconstructed == submitted_draft
            and layout_revision(reconstructed) == frame.get("draftRevision")
        ):
            frame["draftLayout"] = reconstructed
        return frame

    def _require_design_transaction_scope(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        transaction_id: str,
    ) -> dict[str, Any]:
        envelope = self.design_repository.get_transaction(
            principal.tenant_id, site_id, transaction_id
        )
        if envelope["transaction"]["layoutId"] != layout_id:
            raise FacilityDesignServiceError(
                "facility_design_scope_mismatch",
                "Facility design transaction is outside the requested layout scope.",
            )
        return envelope

    def _validate_generation_transaction(self, principal, site_id, layout_id, transaction_id):
        envelope = self._require_design_transaction_scope(principal, site_id, layout_id, transaction_id)
        ref = envelope["transaction"]["selectedProposalRef"]
        proposal = self.design_repository.get_artifact(principal.tenant_id, site_id,
            ref["artifactKind"], ref["artifactId"], ref["artifactRevision"])["artifact"]
        self.generation_draft_adapter.validate(principal, site_id, layout_id, proposal, adopted=True)

    def _agent_capabilities(
        self,
        principal: FacilityPrincipal,
        _site_id: str,
    ) -> dict[str, bool]:
        actions = principal.action_set
        allowed = lambda action: "*" in actions or action in actions
        return {
            "read": allowed("layout.read"),
            "semanticPlanning": (
                allowed("layout.read")
                and self.feature_flags.enabled("viewer_v2")
            ),
            "semanticPreview": (
                allowed("proposal.create")
                and self.feature_flags.enabled("agent_preview")
            ),
            "generationPlanning": allowed("proposal.create") and self.feature_flags.enabled("generation_planning_sage"),
            "constructionPreview": (
                allowed("proposal.create")
                and self.feature_flags.enabled("construction_sage")
            ),
            "constructionApply": (
                allowed("proposal.approve") and allowed("proposal.apply")
                and self.feature_flags.enabled("construction_sage")
                and self.feature_flags.enabled("agent_write")
            ),
            "approval": (
                allowed("proposal.approve")
                and self.feature_flags.enabled("agent_write")
            ),
            "apply": (
                allowed("proposal.apply")
                and self.feature_flags.enabled("agent_write")
            ),
            "manualAuthoring": (
                allowed("layout.edit")
                and self.feature_flags.enabled("manual_edit")
            ),
            "automaticRouting": self.feature_flags.enabled("routing"),
            "navigationSnapshot": self.feature_flags.enabled("routing"),
            "navigationContract": self.feature_flags.enabled(
                "navigation_contract"
            ),
            "navigationManual": self.feature_flags.enabled(
                "navigation_manual"
            ),
            "navigationPedestrian": self.feature_flags.enabled(
                "navigation_pedestrian"
            ),
            "navigationVehicle": self.feature_flags.enabled(
                "navigation_vehicle"
            ),
            "navigationHandoff": self.feature_flags.enabled(
                "navigation_handoff"
            ),
            "navigationMultiActor": self.feature_flags.enabled(
                "navigation_multi_actor"
            ),
            "navigationSageWrite": self.feature_flags.enabled(
                "navigation_sage_write"
            ),
            "designBrief": self.feature_flags.enabled("design_brief"),
            "designLoopPreview": (
                allowed("proposal.create")
                and self.feature_flags.enabled("design_loop_preview")
            ),
            "designLoopApply": (
                allowed("proposal.apply")
                and self.feature_flags.enabled("agent_write")
                and self.feature_flags.enabled("design_loop_apply")
            ),
            "prototypeMotion": self.service.allow_prototype_motion,
            "spatialValidation": self.feature_flags.enabled("constraints"),
        }

    def _require_feature(self, capability: str) -> None:
        try:
            self.feature_flags.require(capability)
        except FacilityLayoutError as error:
            raise HTTPException(
                status_code=error.status_code,
                detail={"error": error.to_dict()},
            ) from error

    @staticmethod
    def _agent_error(error: FacilityLayoutAgentRuntimeError) -> HTTPException:
        return HTTPException(
            status_code=error.status_code,
            detail={
                "error": {
                    "code": error.code,
                    "message": str(error),
                    "details": deepcopy(error.details),
                }
            },
        )

    @staticmethod
    def _generation_error(error: Exception) -> HTTPException:
        code = str(getattr(error, "code", "facility_generation_failed"))
        details = deepcopy(dict(getattr(error, "details", {}) or {}))
        status_code = 409 if any(
            token in code
            for token in (
                "conflict",
                "stale",
                "changed",
                "blocked",
                "expired",
                "mismatch",
                "not_save_eligible",
            )
        ) else 422
        return HTTPException(
            status_code=status_code,
            detail={
                "error": {
                    "code": code,
                    "message": str(error),
                    "details": details,
                }
            },
        )

    @staticmethod
    def _design_error(error: Exception) -> HTTPException:
        code = str(getattr(error, "code", "facility_design_failed"))
        details = deepcopy(dict(getattr(error, "details", {}) or {}))
        if "not_found" in code:
            status_code = 404
        elif any(
            token in code
            for token in (
                "conflict",
                "stale",
                "changed",
                "expired",
                "mismatch",
                "lease",
            )
        ):
            status_code = 409
        else:
            status_code = 422
        return HTTPException(
            status_code=status_code,
            detail={
                "error": {
                    "code": code,
                    "message": str(error),
                    "details": details,
                }
            },
        )

    @staticmethod
    def _generation_session_id(request: Request) -> str:
        value = str(
            request.headers.get("X-InspectorPro-Session") or ""
        ).strip()
        if not value or len(value) > 128:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": {
                        "code": "invalid_session_id",
                        "message": (
                            "X-InspectorPro-Session is required for Facility "
                            "generation runs."
                        ),
                        "details": {},
                    }
                },
            )
        return value

    def _ensure_published(
        self,
        repository: Any,
        document: Mapping[str, Any],
        id_field: str,
    ) -> Any:
        principal = self.principal()
        authority_id = str(document[id_field])
        try:
            return repository.get_published(
                principal,
                site_id=LOCAL_SITE_ID,
                authority_id=authority_id,
            )
        except FacilityNotFoundError:
            pass
        try:
            current = repository.get_current(
                principal,
                site_id=LOCAL_SITE_ID,
                authority_id=authority_id,
            )
        except FacilityNotFoundError:
            created = repository.create(
                principal,
                site_id=LOCAL_SITE_ID,
                document=document,
            )
            current = created.envelope
        if current.status == "draft":
            reviewed = repository.review(
                principal,
                site_id=LOCAL_SITE_ID,
                authority_id=authority_id,
                expected_revision=current.revision,
            )
            current = reviewed.envelope
        if current.status == "reviewed":
            published = repository.publish(
                principal,
                site_id=LOCAL_SITE_ID,
                authority_id=authority_id,
                expected_revision=current.revision,
            )
            current = published.envelope
        return repository.get_published(
            principal,
            site_id=LOCAL_SITE_ID,
            authority_id=authority_id,
        )

    def ensure_bootstrap(self) -> dict[str, Any]:
        with self._lock:
            principal = self.principal()
            shell = self._ensure_published(
                self.shell_repository,
                _shell_document(),
                "shellId",
            )
            policy = self._ensure_published(
                self.policy_repository,
                _policy_document(),
                "policySetId",
            )
            try:
                layout_receipt = self.service.get_layout(
                    principal,
                    LOCAL_SITE_ID,
                    LOCAL_LAYOUT_ID,
                )
            except FacilityLayoutIntegrityError as error:
                if error.code != "layout_asset_not_canonical":
                    raise
                self.layout_repository.normalize_current_layout_storage(
                    principal,
                    LOCAL_SITE_ID,
                    LOCAL_LAYOUT_ID,
                )
                layout_receipt = self.service.get_layout(
                    principal,
                    LOCAL_SITE_ID,
                    LOCAL_LAYOUT_ID,
                )
            except FacilityNotFoundError:
                frame = deepcopy(shell.document["coordinateFrame"])
                layout = create_layout_document(
                    layout_id=LOCAL_LAYOUT_ID,
                    display_name="Main Facility Layout",
                    association={"siteId": LOCAL_SITE_ID, "areaId": "main"},
                    coordinate_frame=frame,
                    source_shell_ref={
                        "shellId": LOCAL_SHELL_ID,
                        "shellRevision": shell.revision,
                        "coordinateFrameFingerprint": (
                            coordinate_frame_fingerprint(frame)
                        ),
                    },
                    policy_set_ref={
                        "policySetId": LOCAL_POLICY_ID,
                        "policySetRevision": policy.revision,
                    },
                    created_at=_timestamp(),
                )
                layout_receipt = self.service.create_layout(
                    principal,
                    LOCAL_SITE_ID,
                    layout,
                    make_default=True,
                )
            self._bootstrapped = True
            saved_layout = layout_receipt.get("layout", {})
            saved_plan_settings = plan_settings_from_layout(saved_layout)
            plan_settings = saved_plan_settings
            if plan_settings is None:
                plan_settings = default_plan_settings()
            world_bounds = plan_world_bounds(
                plan_settings,
                floor_y=float(
                    shell.document["coordinateFrame"].get("floorElevation", 0)
                ),
            )
            return {
                "schemaVersion": 1,
                "siteId": LOCAL_SITE_ID,
                "layoutId": LOCAL_LAYOUT_ID,
                "layout": layout_receipt,
                "assetCatalog": (
                    deepcopy(list(self._catalog.values()))
                    if self.feature_flags.enabled("asset_library")
                    else []
                ),
                "worldBounds": world_bounds,
                "grid": {
                    "units": "m",
                    "originMode": "corner",
                    "snapSpacing": (
                        plan_settings["gridSpacingMeters"]
                        if saved_plan_settings is not None
                        else 0.5
                    ),
                    "minorSpacing": plan_settings["gridSpacingMeters"],
                    "majorSpacing": plan_settings["majorGridSpacingMeters"],
                },
                "capabilities": {
                    "constructionPreview": self._agent_capabilities(principal, LOCAL_SITE_ID)["constructionPreview"],
                    "generationPlanning": self._agent_capabilities(principal, LOCAL_SITE_ID)["generationPlanning"],
                    "constructionApply": self._agent_capabilities(principal, LOCAL_SITE_ID)["constructionApply"],
                    "viewerV2": self.feature_flags.enabled("viewer_v2"),
                    "assetLibrary": self.feature_flags.enabled(
                        "asset_library"
                    ),
                    "manualAuthoring": self.feature_flags.enabled(
                        "manual_edit"
                    ),
                    "authoritativePreview": self.feature_flags.enabled(
                        "constraints"
                    ),
                    "casSave": self.feature_flags.enabled("manual_edit"),
                    "collisionValidation": self.feature_flags.enabled(
                        "constraints"
                    ),
                    "candidateSnapping": self.feature_flags.enabled(
                        "constraints"
                    ),
                    # Manual drag/drop is direct and undoable. Candidate
                    # previews remain available to planners and agents.
                    "manualPlacementApproval": False,
                    "coarseAdvisoryWorker": self.feature_flags.enabled(
                        "constraints"
                    ),
                    "automaticRouting": self.feature_flags.enabled("routing"),
                    "navigationSnapshot": self.feature_flags.enabled("routing"),
                    "navigationContract": self.feature_flags.enabled(
                        "navigation_contract"
                    ),
                    "navigationManual": self.feature_flags.enabled(
                        "navigation_manual"
                    ),
                    "navigationPedestrian": self.feature_flags.enabled(
                        "navigation_pedestrian"
                    ),
                    "navigationVehicle": self.feature_flags.enabled(
                        "navigation_vehicle"
                    ),
                    "navigationHandoff": self.feature_flags.enabled(
                        "navigation_handoff"
                    ),
                    "navigationMultiActor": self.feature_flags.enabled(
                        "navigation_multi_actor"
                    ),
                    "navigationSageWrite": self.feature_flags.enabled(
                        "navigation_sage_write"
                    ),
                    "prototypeMotion": self.service.allow_prototype_motion,
                    "fullLayoutProposals": self.feature_flags.enabled(
                        "agent_preview"
                    ),
                    "atomicProposalApply": self.feature_flags.enabled(
                        "agent_write"
                    ),
                    "makerCheckerRequired": (
                        self.require_distinct_approver
                    ),
                    "principalAuthentication": self.principal_mode,
                },
                "featureFlags": self.feature_flags.to_dict(),
            }

    def resolve_principal(self, request: Request) -> FacilityPrincipal:
        if self._principal_resolver is not None:
            principal = self._principal_resolver(request)
        else:
            principal = self.principal()
        self.ensure_bootstrap()
        return principal

    def _lighting_coverage(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        body: Mapping[str, Any],
    ) -> dict[str, Any]:
        from .appearance_library import load_library
        from .light_coverage import check_lighting_coverage, view_payload
        operations = body.get("operations", [])
        area = body.get("area")
        try:
            if not isinstance(operations, list) or not isinstance(area, Mapping):
                raise ValueError("Send baseRevision, operations (a list) and area (an object).")
            document = self.service.layout_with_operations(
                principal,
                site_id,
                layout_id,
                str(body.get("baseRevision") or ""),
                operations,
            )
            catalog = self._agent_asset_catalog(principal, site_id)
            shell = self.service.effective_shell(principal, site_id, document)
            summary, result = check_lighting_coverage(document, catalog, load_library(), dict(area), shell=shell)
        except FacilityLayoutError as error:
            raise HTTPException(
                status_code=error.status_code,
                detail={"error": error.to_dict()},
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail={"error": {"code": "lighting_coverage_unavailable", "message": str(error)}},
            ) from error
        return view_payload(summary, result)

    def _require_request_action(
        self,
        request: Request,
        action: str,
    ) -> FacilityPrincipal:
        principal = self.resolve_principal(request)
        try:
            require_facility_action(
                principal,
                tenant_id="local",
                site_id=LOCAL_SITE_ID,
                action=action,
            )
        except FacilityLayoutError as error:
            raise HTTPException(
                status_code=error.status_code,
                detail={"error": error.to_dict()},
            ) from error
        return principal

    def create_router(self) -> APIRouter:
        router = APIRouter()
        router.add_event_handler("shutdown", self.close)

        @router.get("/api/facility-layout-bootstrap")
        async def bootstrap(request: Request):
            principal = self._require_request_action(
                request,
                "layout.read",
            )
            try:
                require_facility_action(
                    principal,
                    tenant_id="local",
                    site_id=LOCAL_SITE_ID,
                    action="catalog.read",
                )
            except FacilityLayoutError as error:
                raise HTTPException(
                    status_code=error.status_code,
                    detail={"error": error.to_dict()},
                ) from error
            result = self.ensure_bootstrap()
            result["principal"] = {
                "principalId": principal.principal_id,
                "tenantId": principal.tenant_id,
                "allowedSiteIds": list(principal.allowed_site_ids),
                "roles": list(principal.roles),
            }
            result["principalCapabilities"] = self._agent_capabilities(
                principal,
                LOCAL_SITE_ID,
            )
            return result

        @router.get("/api/industrial-assets")
        async def list_assets(
            request: Request,
            site_id: str = Query(LOCAL_SITE_ID, alias="siteId"),
        ):
            self._require_feature("asset_library")
            self._require_request_action(request, "catalog.read")
            if site_id != LOCAL_SITE_ID:
                raise HTTPException(
                    status_code=404,
                    detail="Facility resource was not found.",
                )
            self.ensure_bootstrap()
            return {
                "siteId": LOCAL_SITE_ID,
                "assets": deepcopy(list(self._catalog.values())),
            }

        @router.post(
            "/api/facility-layout-agent/{site_id}/{layout_id}/read/{tool_name}"
        )
        async def facility_agent_read(
            request: Request,
            site_id: str,
            layout_id: str,
            tool_name: str,
            body: dict[str, Any],
        ):
            self._require_feature("viewer_v2")
            principal = self.resolve_principal(request)
            turn_id = (
                request.headers.get("X-InspectorPro-Agent-Turn")
                or request.headers.get("X-InspectorPro-Session")
                or "facility-agent-turn"
            )
            try:
                return self.agent_runtime.execute_read_tool(
                    principal,
                    site_id=site_id,
                    layout_id=layout_id,
                    expected_revision=str(
                        body.get("expectedRevision") or ""
                    ),
                    tool_name=tool_name,
                    arguments=(
                        body.get("arguments")
                        if isinstance(body.get("arguments"), Mapping)
                        else {}
                    ),
                    turn_id=turn_id,
                    live_facts=(
                        body.get("liveState")
                        if isinstance(body.get("liveState"), Mapping)
                        else None
                    ),
                    proposal_id=(
                        str(body["proposalId"])
                        if body.get("proposalId") else None
                    ),
                    receipt_ids=(
                        body.get("receiptIds")
                        if isinstance(body.get("receiptIds"), list)
                        else None
                    ),
                )
            except FacilityLayoutAgentRuntimeError as error:
                raise self._agent_error(error) from error

        @router.post(
            "/api/facility-layout-agent/{site_id}/{layout_id}/preview"
        )
        async def facility_agent_preview(
            request: Request,
            site_id: str,
            layout_id: str,
            body: dict[str, Any],
        ):
            self._require_feature("agent_preview")
            principal = self.resolve_principal(request)
            semantic_plan = body.get("semanticPlan")
            if not isinstance(semantic_plan, Mapping):
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": {
                            "code": "semantic_facility_plan_missing",
                            "message": (
                                "semanticPlan must be a Semantic Facility "
                                "Layout Plan v1 object."
                            ),
                            "details": {},
                        }
                    },
                )
            try:
                return self.agent_runtime.build_preview(
                    principal,
                    site_id=site_id,
                    layout_id=layout_id,
                    expected_revision=str(
                        body.get("expectedRevision") or ""
                    ),
                    semantic_plan=semantic_plan,
                    live_facts=(
                        body.get("liveState")
                        if isinstance(body.get("liveState"), Mapping)
                        else None
                    ),
                    proposal_id=(
                        str(body["proposalId"])
                        if body.get("proposalId") else None
                    ),
                    receipt_ids=(
                        body.get("receiptIds")
                        if isinstance(body.get("receiptIds"), list)
                        else None
                    ),
                )
            except FacilityLayoutAgentRuntimeError as error:
                raise self._agent_error(error) from error

        @router.get(
            "/api/facility-layout-agent/{site_id}/{layout_id}/runs/{run_id}"
        )
        async def facility_agent_workflow_run(
            request: Request,
            site_id: str,
            layout_id: str,
            run_id: str,
        ):
            self._require_feature("agent_preview")
            principal = self.resolve_principal(request)
            try:
                return self.agent_runtime.get_workflow_run(
                    principal,
                    site_id=site_id,
                    layout_id=layout_id,
                    run_id=run_id,
                )
            except FacilityLayoutAgentRuntimeError as error:
                raise self._agent_error(error) from error

        @router.get("/api/facility-layout-planning/{site_id}/{layout_id}/sources")
        def generation_planning_sources(request: Request, site_id: str, layout_id: str):
            principal = self.resolve_principal(request)
            try:
                self._require_feature("generation_planning_sage")
                self.service.get_layout(principal, site_id, layout_id)
                return self.generation_agent_service.list_sources(principal, site_id=site_id)
            except FacilityLayoutError as error:
                raise HTTPException(status_code=error.status_code, detail={"error": error.to_dict()}) from error

        @router.post("/api/facility-layout-planning/{site_id}/{layout_id}/{action}")
        def isolated_generation_planning(request: Request, site_id: str, layout_id: str,
                                         action: str, body: dict[str, Any]):
            if action not in {"admit", "preview", "inspect", "select", "destination"}:
                raise HTTPException(status_code=404, detail="Planning action not found.")
            self._require_feature("generation_planning_preview")
            if set(body) != {"workspaceId", "request", "editorContext"}:
                raise HTTPException(status_code=422, detail={"error": {"code": "generation_admission_fields_invalid"}})
            principal = self.resolve_principal(request)
            options = dict(site_id=site_id, layout_id=layout_id, workspace_id=body["workspaceId"],
                           editor_context=body["editorContext"])
            try:
                if action == "destination":
                    with self._lock:
                        return create_generation_destination(self, principal, site_id, layout_id,
                            body["request"], _shell_document(), _timestamp())
                if action == "select":
                    return self.generation_draft_adapter.publish(principal, **options, request=body["request"])
                if action == "inspect":
                    reference = body["request"]
                    if not isinstance(reference, Mapping) or set(reference) != {"previewId", "previewRevision"}:
                        raise HTTPException(status_code=422, detail={"error": {"code": "generation_admission_fields_invalid"}})
                    return self.generation_admission_service.get_preview(principal, **options,
                        preview_id=reference["previewId"], preview_revision=reference["previewRevision"])
                method = (self.generation_admission_service.admit if action == "admit"
                          else self.generation_admission_service.preview)
                return method(principal, **options, request=body["request"])
            except FacilityLayoutError as error:
                raise HTTPException(status_code=error.status_code, detail={"error": error.to_dict()}) from error
            except (GenerationRequirementError, FacilityDesignRepositoryError, FacilityPlanningPackageError,
                    FacilityProgramExecutionError, FacilityDesignServiceError, FacilityKnowledgeContractError,
                    FacilityLayoutAgentRuntimeError) as error:
                raise self._generation_error(error) from error

        @router.get("/api/facility-layout-agent/{site_id}/{layout_id}/construction/{proposal_id}")
        async def get_construction_preview(request: Request, site_id: str, layout_id: str, proposal_id: str):
            try:
                return self.construction_service.get_preview(self.resolve_principal(request),
                    site_id=site_id, layout_id=layout_id, proposal_id=proposal_id)
            except FacilityLayoutError as error:
                raise HTTPException(status_code=error.status_code, detail={"error": error.to_dict()}) from error

        @router.post("/api/facility-layout-agent/{site_id}/{layout_id}/construction/{proposal_id}/approve-unsaved")
        async def approve_construction_unsaved(request: Request, site_id: str, layout_id: str,
                                               proposal_id: str, body: dict[str, Any]):
            try:
                return self.construction_service.approve_unsaved(self.resolve_principal(request),
                    site_id=site_id, layout_id=layout_id, proposal_id=proposal_id, request=body)
            except FacilityLayoutError as error:
                raise HTTPException(status_code=error.status_code, detail={"error": error.to_dict()}) from error

        @router.post(
            "/api/facility-layout-design/{site_id}/{layout_id}/briefs"
        )
        async def create_facility_design_brief_endpoint(
            request: Request,
            site_id: str,
            layout_id: str,
            body: dict[str, Any],
        ):
            principal = self._require_request_action(
                request, "proposal.create"
            )
            try:
                raw_base = body.get("designBase")
                semantic_body = body.get("semanticBody")
                current = self.service.get_layout(
                    principal, site_id, layout_id
                )
                semantic_intent = body.get("semanticIntent")
                if isinstance(semantic_intent, Mapping):
                    base = self._capture_design_base_from_editor(
                        principal=principal,
                        site_id=site_id,
                        layout_id=layout_id,
                        request=request,
                        body=body,
                        current=current,
                    )
                    source_turn_ref = self._design_source_turn(
                        request, body
                    )
                    semantic_body = compile_facility_design_brief_body(
                        intent=semantic_intent,
                        design_base=base,
                        source_turn_ref=source_turn_ref,
                    )
                else:
                    if not isinstance(raw_base, Mapping) or not isinstance(
                        semantic_body, Mapping
                    ):
                        raise FacilityDesignServiceError(
                            "facility_design_request_invalid",
                            "Provide semanticIntent with editorFrame, or designBase with semanticBody.",
                        )
                    base = validate_facility_design_base(raw_base)
                    source_turn_ref = self._design_source_turn(
                        request, body
                    )
                if (
                    base["tenantId"] != principal.tenant_id
                    or base["siteId"] != site_id
                    or base["layoutId"] != layout_id
                    or base["savedLayoutRevision"] != current["revision"]
                ):
                    raise FacilityDesignServiceError(
                        "facility_design_base_scope_mismatch",
                        "The immutable design base does not match the current authorized layout.",
                    )
                brief_id = str(body.get("briefId") or "").strip()
                if not brief_id:
                    brief_id = "fdbf-" + hashlib.sha256(
                        json.dumps(
                            {
                                "baseRevision": base["baseRevision"],
                                "sourceTurnRef": source_turn_ref,
                                "objective": semantic_body.get("objective"),
                            },
                            ensure_ascii=True,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("ascii")
                    ).hexdigest()[:24]
                return self.design_loop_service.create_brief(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    principal_id=principal.principal_id,
                    brief_id=brief_id,
                    semantic_body=semantic_body,
                    source_turn_ref=source_turn_ref,
                    design_base=base,
                )
            except _DESIGN_ERRORS as error:
                raise self._design_error(error) from error

        @router.get(
            "/api/facility-layout-design/{site_id}/{layout_id}/briefs/{brief_id}"
        )
        async def inspect_facility_design_brief_endpoint(
            request: Request,
            site_id: str,
            layout_id: str,
            brief_id: str,
            brief_revision: str | None = Query(
                None, alias="briefRevision"
            ),
        ):
            principal = self._require_request_action(
                request, "proposal.read"
            )
            try:
                self._design_brief_and_base(
                    principal,
                    site_id,
                    layout_id,
                    brief_id,
                    brief_revision=brief_revision,
                )
                return self.design_loop_service.inspect_brief(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    brief_id=brief_id,
                    brief_revision=brief_revision,
                )
            except _DESIGN_ERRORS as error:
                raise self._design_error(error) from error

        @router.post(
            "/api/facility-layout-design/{site_id}/{layout_id}/briefs/{brief_id}/revisions"
        )
        async def update_facility_design_brief_endpoint(
            request: Request,
            site_id: str,
            layout_id: str,
            brief_id: str,
            body: dict[str, Any],
        ):
            principal = self._require_request_action(
                request, "proposal.create"
            )
            try:
                brief_envelope, base = self._design_brief_and_base(
                    principal, site_id, layout_id, brief_id
                )
                patch = body.get("patch")
                semantic_intent = body.get("semanticIntent")
                source_turn_ref = self._design_source_turn(request, body)
                if isinstance(semantic_intent, Mapping):
                    patch = compile_facility_design_brief_patch(
                        intent=semantic_intent,
                        current_brief=brief_envelope["brief"],
                        design_base=base,
                        source_turn_ref=source_turn_ref,
                    )
                elif not isinstance(patch, Mapping):
                    raise FacilityDesignServiceError(
                        "facility_design_request_invalid",
                        "patch or semanticIntent must be a Facility design brief update object.",
                    )
                return self.design_loop_service.update_brief(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    principal_id=principal.principal_id,
                    brief_id=brief_id,
                    patch=patch,
                    source_turn_ref=source_turn_ref,
                )
            except _DESIGN_ERRORS as error:
                raise self._design_error(error) from error

        @router.post(
            "/api/facility-layout-design/{site_id}/{layout_id}/briefs/{brief_id}/preview"
        )
        async def start_facility_design_preview_endpoint(
            request: Request,
            site_id: str,
            layout_id: str,
            brief_id: str,
            body: dict[str, Any],
        ):
            principal = self._require_request_action(
                request, "proposal.create"
            )
            try:
                brief_envelope, base = self._design_brief_and_base(
                    principal,
                    site_id,
                    layout_id,
                    brief_id,
                    brief_revision=(
                        str(body["briefRevision"])
                        if body.get("briefRevision")
                        else None
                    ),
                )
                source = self._resolve_design_source_bundle(
                    principal,
                    site_id,
                    layout_id,
                    base,
                    brief_envelope["brief"],
                )
                provider = resolve_facility_provider_config(os.environ)
                return self.design_loop_service.start_preview(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    workspace_id=str(
                        body.get("workspaceId")
                        or base["workspaceId"]
                    ),
                    design_base=base,
                    design_brief=brief_envelope["brief"],
                    source_bundle=source,
                    provider=provider.provider,
                    model=provider.model,
                    reasoning_effort=provider.reasoning_effort,
                    client_generation_id=str(
                        body.get("clientGenerationId")
                        or self._generation_session_id(request)
                    ),
                    mode=str(body.get("mode") or "production_sage"),
                    run_id=(
                        str(body["runId"])
                        if body.get("runId")
                        else None
                    ),
                )
            except _DESIGN_ERRORS as error:
                raise self._design_error(error) from error

        @router.post(
            "/api/facility-layout-design/{site_id}/{layout_id}/runs/{run_id}/continue"
        )
        async def continue_facility_design_preview_endpoint(
            request: Request,
            site_id: str,
            layout_id: str,
            run_id: str,
            body: dict[str, Any],
        ):
            principal = self._require_request_action(
                request, "proposal.create"
            )
            try:
                run = self.design_repository.get_run(
                    principal.tenant_id, site_id, run_id
                )
                if run["run"]["layoutId"] != layout_id:
                    raise FacilityDesignServiceError(
                        "facility_design_scope_mismatch",
                        "Facility design run is outside the requested layout scope.",
                    )
                return self.design_loop_service.continue_preview(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    run_id=run_id,
                    maximum_tool_calls=int(
                        body.get("maximumToolCalls") or 10
                    ),
                )
            except _DESIGN_ERRORS as error:
                raise self._design_error(error) from error

        @router.post(
            "/api/facility-layout-design/{site_id}/{layout_id}/runs/{run_id}/cancel"
        )
        async def cancel_facility_design_preview_endpoint(
            request: Request,
            site_id: str,
            layout_id: str,
            run_id: str,
        ):
            principal = self._require_request_action(
                request, "proposal.create"
            )
            try:
                run = self.design_repository.get_run(
                    principal.tenant_id, site_id, run_id
                )
                if run["run"]["layoutId"] != layout_id:
                    raise FacilityDesignServiceError(
                        "facility_design_scope_mismatch",
                        "Facility design run is outside the requested layout scope.",
                    )
                return self.design_loop_service.cancel_preview(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    run_id=run_id,
                )
            except _DESIGN_ERRORS as error:
                raise self._design_error(error) from error

        @router.get(
            "/api/facility-layout-design/{site_id}/{layout_id}/proposals/{proposal_id}"
        )
        async def inspect_facility_design_proposal_endpoint(
            request: Request,
            site_id: str,
            layout_id: str,
            proposal_id: str,
            proposal_revision: str = Query(..., alias="proposalRevision"),
            include_candidate_layout: bool = Query(
                False, alias="includeCandidateLayout"
            ),
        ):
            principal = self._require_request_action(
                request, "proposal.read"
            )
            try:
                result = self.design_loop_service.inspect_proposal(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    proposal_id=proposal_id,
                    proposal_revision=proposal_revision,
                    include_candidate_layout=include_candidate_layout,
                )
                if result["proposal"]["layoutId"] != layout_id:
                    raise FacilityDesignServiceError(
                        "facility_design_scope_mismatch",
                        "Facility design proposal is outside the requested layout scope.",
                    )
                return result
            except _DESIGN_ERRORS as error:
                raise self._design_error(error) from error

        @router.post(
            "/api/facility-layout-design/{site_id}/{layout_id}/proposals/{proposal_id}/apply/prepare"
        )
        async def prepare_facility_design_apply_endpoint(
            request: Request,
            site_id: str,
            layout_id: str,
            proposal_id: str,
            body: dict[str, Any],
        ):
            principal = self._require_request_action(
                request, "proposal.apply"
            )
            try:
                current = self.service.get_layout(
                    principal, site_id, layout_id
                )
                inspected = self.design_loop_service.inspect_proposal(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    proposal_id=proposal_id,
                    proposal_revision=str(
                        body.get("proposalRevision") or ""
                    ),
                )
                if inspected["proposal"]["layoutId"] != layout_id:
                    raise FacilityDesignServiceError(
                        "facility_design_scope_mismatch",
                        "Facility design proposal is outside the requested layout scope.",
                    )
                self.generation_draft_adapter.validate(principal, site_id, layout_id, inspected["proposal"])
                result = self.design_loop_service.prepare_proposal_apply(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    proposal_id=proposal_id,
                    proposal_revision=str(
                        body.get("proposalRevision") or ""
                    ),
                    root_undo_frame=self._authoritative_design_editor_frame(
                        body.get("rootUndoFrame") or {},
                        current=current,
                        tenant_id=principal.tenant_id,
                        site_id=site_id,
                        layout_id=layout_id,
                    ),
                    previous_installation_state=(
                        self._authoritative_design_editor_frame(
                            body.get("previousInstallationState") or {},
                            current=current,
                            tenant_id=principal.tenant_id,
                            site_id=site_id,
                            layout_id=layout_id,
                        )
                    ),
                    expected_result_editor_generation_id=str(
                        body.get("expectedResultEditorGenerationId") or ""
                    ),
                    expected_result_command_journal_hash=str(
                        body.get("expectedResultCommandJournalHash") or ""
                    ),
                    expected_source_owner=(
                        body.get("expectedSourceOwner")
                        if isinstance(
                            body.get("expectedSourceOwner"), Mapping
                        )
                        else None
                    ),
                    transaction_id=(
                        str(body["transactionId"])
                        if body.get("transactionId")
                        else None
                    ),
                    expected_transaction_revision=(
                        str(body["expectedTransactionRevision"])
                        if body.get("expectedTransactionRevision")
                        else None
                    ),
                )
                if result["transaction"]["transaction"]["layoutId"] != layout_id:
                    raise FacilityDesignServiceError(
                        "facility_design_scope_mismatch",
                        "Facility design transaction is outside the requested layout scope.",
                    )
                return result
            except _DESIGN_ERRORS as error:
                raise self._design_error(error) from error

        @router.post(
            "/api/facility-layout-design/{site_id}/{layout_id}/transactions/{transaction_id}/apply/commit"
        )
        async def commit_facility_design_apply_endpoint(
            request: Request,
            site_id: str,
            layout_id: str,
            transaction_id: str,
            body: dict[str, Any],
        ):
            principal = self._require_request_action(
                request, "proposal.apply"
            )
            try:
                self._require_design_transaction_scope(
                    principal, site_id, layout_id, transaction_id
                )
                self._validate_generation_transaction(principal, site_id, layout_id, transaction_id)
                result = self.design_loop_service.commit_proposal_apply(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    transaction_id=transaction_id,
                    expected_transaction_revision=str(
                        body.get("expectedTransactionRevision") or ""
                    ),
                    adoption_token=str(body.get("adoptionToken") or ""),
                )
                if result["transaction"]["transaction"]["layoutId"] != layout_id:
                    raise FacilityDesignServiceError(
                        "facility_design_scope_mismatch",
                        "Facility design transaction is outside the requested layout scope.",
                    )
                return result
            except _DESIGN_ERRORS as error:
                raise self._design_error(error) from error

        @router.post(
            "/api/facility-layout-design/{site_id}/{layout_id}/transactions/{transaction_id}/apply/acknowledge"
        )
        async def acknowledge_facility_design_apply_endpoint(
            request: Request,
            site_id: str,
            layout_id: str,
            transaction_id: str,
            body: dict[str, Any],
        ):
            principal = self._require_request_action(
                request, "proposal.apply"
            )
            try:
                self._require_design_transaction_scope(
                    principal, site_id, layout_id, transaction_id
                )
                return self.design_loop_service.acknowledge_proposal_apply(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    transaction_id=transaction_id,
                    expected_transaction_revision=str(
                        body.get("expectedTransactionRevision") or ""
                    ),
                    adoption_token=str(body.get("adoptionToken") or ""),
                    observed_installation_fingerprint=str(
                        body.get("observedInstallationFingerprint") or ""
                    ),
                )
            except _DESIGN_ERRORS as error:
                raise self._design_error(error) from error

        @router.post(
            "/api/facility-layout-design/{site_id}/{layout_id}/transactions/{transaction_id}/apply/recover"
        )
        async def recover_facility_design_apply_endpoint(
            request: Request,
            site_id: str,
            layout_id: str,
            transaction_id: str,
            body: dict[str, Any],
        ):
            principal = self._require_request_action(
                request, "proposal.apply"
            )
            try:
                self._require_design_transaction_scope(
                    principal, site_id, layout_id, transaction_id
                )
                return self.design_loop_service.recover_proposal_apply(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    transaction_id=transaction_id,
                    expected_transaction_revision=str(
                        body.get("expectedTransactionRevision") or ""
                    ),
                    observed_installation_fingerprint=str(
                        body.get("observedInstallationFingerprint") or ""
                    ),
                )
            except _DESIGN_ERRORS as error:
                raise self._design_error(error) from error

        @router.post(
            "/api/facility-layout-design/{site_id}/{layout_id}/transactions/{transaction_id}/save"
        )
        async def save_facility_design_proposal_endpoint(
            request: Request,
            site_id: str,
            layout_id: str,
            transaction_id: str,
            body: dict[str, Any],
        ):
            principal = self._require_request_action(
                request, "proposal.apply"
            )
            try:
                self._require_design_transaction_scope(
                    principal, site_id, layout_id, transaction_id
                )
                self._validate_generation_transaction(principal, site_id, layout_id, transaction_id)
                return self.design_loop_service.save_proposal(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    transaction_id=transaction_id,
                    expected_transaction_revision=str(
                        body.get("expectedTransactionRevision") or ""
                    ),
                    observed_draft_revision=str(
                        body.get("observedDraftRevision") or ""
                    ),
                    observed_command_journal_hash=str(
                        body.get("observedCommandJournalHash") or ""
                    ),
                    explicit_approval=body.get("explicitApproval") is True,
                    layout_saver=lambda document, base_revision: (
                        self.service.save_layout(
                            principal,
                            site_id,
                            layout_id,
                            document,
                            base_revision,
                        )
                    ),
                )
            except _DESIGN_ERRORS as error:
                raise self._design_error(error) from error

        @router.get(
            "/api/facility-layout-design/{site_id}/{layout_id}/transactions/{transaction_id}/undo"
        )
        async def inspect_facility_design_undo_endpoint(
            request: Request,
            site_id: str,
            layout_id: str,
            transaction_id: str,
        ):
            principal = self._require_request_action(
                request, "proposal.read"
            )
            try:
                self._require_design_transaction_scope(
                    principal, site_id, layout_id, transaction_id
                )
                return self.design_loop_service.undo_eligibility(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    transaction_id=transaction_id,
                )
            except _DESIGN_ERRORS as error:
                raise self._design_error(error) from error

        @router.post(
            "/api/facility-layout-design/{site_id}/{layout_id}/transactions/{transaction_id}/undo/prepare"
        )
        async def prepare_facility_design_undo_endpoint(
            request: Request,
            site_id: str,
            layout_id: str,
            transaction_id: str,
            body: dict[str, Any],
        ):
            principal = self._require_request_action(
                request, "proposal.apply"
            )
            try:
                self._require_design_transaction_scope(
                    principal, site_id, layout_id, transaction_id
                )
                return self.design_loop_service.prepare_undo(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    transaction_id=transaction_id,
                    expected_transaction_revision=str(
                        body.get("expectedTransactionRevision") or ""
                    ),
                )
            except _DESIGN_ERRORS as error:
                raise self._design_error(error) from error

        @router.post(
            "/api/facility-layout-design/{site_id}/{layout_id}/transactions/{transaction_id}/undo/acknowledge"
        )
        async def acknowledge_facility_design_undo_endpoint(
            request: Request,
            site_id: str,
            layout_id: str,
            transaction_id: str,
            body: dict[str, Any],
        ):
            principal = self._require_request_action(
                request, "proposal.apply"
            )
            try:
                self._require_design_transaction_scope(
                    principal, site_id, layout_id, transaction_id
                )
                return self.design_loop_service.acknowledge_undo(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    transaction_id=transaction_id,
                    expected_transaction_revision=str(
                        body.get("expectedTransactionRevision") or ""
                    ),
                    observed_draft_revision=str(
                        body.get("observedDraftRevision") or ""
                    ),
                    observed_command_journal_hash=str(
                        body.get("observedCommandJournalHash") or ""
                    ),
                )
            except _DESIGN_ERRORS as error:
                raise self._design_error(error) from error

        @router.post(
            "/api/facility-layout-generation/{site_id}/{layout_id}/g1"
        )
        async def start_facility_generation_g1(
            request: Request,
            site_id: str,
            layout_id: str,
            body: dict[str, Any],
        ):
            execution_mode = str(
                body.get("executionMode") or "authorized_draft_run"
            )
            action = (
                "proposal.create"
                if execution_mode == "preview_only"
                else "proposal.apply"
            )
            principal = self._require_request_action(request, action)
            session_id = self._generation_session_id(request)
            if body.get("prototypeMode") is not True:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": {
                            "code": "explicit_prototype_mode_required",
                            "message": (
                                "Gate G1 generation requires prototypeMode=true."
                            ),
                            "details": {},
                        }
                    },
                )
            envelope = body.get("facilityEnvelope")
            departments = body.get("departments")
            if not isinstance(envelope, Mapping) or not isinstance(
                departments, Mapping
            ):
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": {
                            "code": "g1_intent_incomplete",
                            "message": (
                                "facilityEnvelope and departments must be objects."
                            ),
                            "details": {},
                        }
                    },
                )
            current = self.service.get_layout(principal, site_id, layout_id)

            def start_run() -> dict[str, Any]:
                return self.generation_coordinator.start_g1_run(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    workspace_id=str(
                        body.get("workspaceId") or "workspace-facility-layout"
                    ),
                    layout_id=layout_id,
                    user_id=principal.principal_id,
                    session_id=session_id,
                    base_layout=current["layout"],
                    base_layout_revision=current["revision"],
                    envelope_request=envelope,
                    department_request=departments,
                    execution_mode=execution_mode,
                    prototype_mode=True,
                )

            try:
                try:
                    return start_run()
                except FacilityGenerationRunRepositoryError as error:
                    can_supersede = (
                        body.get("supersedeActiveDraft") is True
                        and error.code
                        in {
                            "generation_session_already_bound",
                            "generation_writable_lease_conflict",
                        }
                    )
                    prior_run_id = str(error.details.get("runId") or "").strip()
                    if not can_supersede or not prior_run_id:
                        raise
                    prior_envelope = self.generation_run_repository.get_run(
                        principal.tenant_id,
                        site_id,
                        prior_run_id,
                    )
                    prior_run = prior_envelope["run"]
                    same_owned_draft = (
                        prior_run["layoutId"] == layout_id
                        and prior_run["userId"] == principal.principal_id
                        and prior_run["writable"] is True
                        and prior_run["status"]
                        not in {"cancelled", "expired", "saved", "stale"}
                    )
                    if not same_owned_draft:
                        raise
                    superseded = self.generation_coordinator.undo_to_base(
                        tenant_id=principal.tenant_id,
                        site_id=site_id,
                        run_id=prior_run_id,
                    )
                    replacement = start_run()
                    replacement["supersededRunId"] = prior_run_id
                    replacement["supersededReceiptIds"] = list(
                        superseded.get("supersededReceiptIds") or []
                    )
                    return replacement
            except (
                FacilityGenerationCoordinatorError,
                FacilityGenerationRunRepositoryError,
                FacilityProviderConfigurationError,
                FacilityKnowledgeContractError,
                FacilityLayoutError,
            ) as error:
                raise self._generation_error(error) from error

        @router.post(
            "/api/facility-layout-generation/{site_id}/{layout_id}/full-factory"
        )
        async def start_facility_generation_full_factory(
            request: Request,
            site_id: str,
            layout_id: str,
            body: dict[str, Any],
        ):
            principal = self._require_request_action(
                request, "proposal.apply"
            )
            session_id = self._generation_session_id(request)
            if body.get("prototypeMode") is not True:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": {
                            "code": "explicit_prototype_mode_required",
                            "message": (
                                "Full-factory generation requires "
                                "prototypeMode=true."
                            ),
                            "details": {},
                        }
                    },
                )
            full_factory = body.get("fullFactory")
            if not isinstance(full_factory, Mapping):
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": {
                            "code": "full_factory_intent_incomplete",
                            "message": "fullFactory must be an object.",
                            "details": {},
                        }
                    },
                )
            current = self.service.get_layout(principal, site_id, layout_id)

            def start_run() -> dict[str, Any]:
                return self.generation_coordinator.start_full_factory_run(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    workspace_id=str(
                        body.get("workspaceId")
                        or "workspace-facility-layout"
                    ),
                    layout_id=layout_id,
                    user_id=principal.principal_id,
                    session_id=session_id,
                    base_layout=current["layout"],
                    base_layout_revision=current["revision"],
                    full_factory_request=full_factory,
                    asset_catalog=deepcopy(list(self._catalog.values())),
                    prototype_mode=True,
                )

            try:
                try:
                    return start_run()
                except FacilityGenerationRunRepositoryError as error:
                    can_supersede = (
                        body.get("supersedeActiveDraft") is True
                        and error.code
                        in {
                            "generation_session_already_bound",
                            "generation_writable_lease_conflict",
                        }
                    )
                    prior_run_id = str(
                        error.details.get("runId") or ""
                    ).strip()
                    if not can_supersede or not prior_run_id:
                        raise
                    prior_envelope = self.generation_run_repository.get_run(
                        principal.tenant_id,
                        site_id,
                        prior_run_id,
                    )
                    prior_run = prior_envelope["run"]
                    same_owned_draft = (
                        prior_run["layoutId"] == layout_id
                        and prior_run["userId"] == principal.principal_id
                        and prior_run["writable"] is True
                        and prior_run["status"]
                        not in {
                            "cancelled",
                            "expired",
                            "saved",
                            "stale",
                        }
                    )
                    if not same_owned_draft:
                        raise
                    superseded = self.generation_coordinator.undo_to_base(
                        tenant_id=principal.tenant_id,
                        site_id=site_id,
                        run_id=prior_run_id,
                    )
                    replacement = start_run()
                    replacement["supersededRunId"] = prior_run_id
                    replacement["supersededReceiptIds"] = list(
                        superseded.get("supersededReceiptIds") or []
                    )
                    return replacement
            except (
                FacilityGenerationCoordinatorError,
                FacilityGenerationRunRepositoryError,
                FacilityProviderConfigurationError,
                FacilityKnowledgeContractError,
                FacilityLayoutError,
            ) as error:
                raise self._generation_error(error) from error

        @router.post(
            "/api/facility-layout-generation/{site_id}/{layout_id}/facility-program"
        )
        async def start_facility_program_generation(
            request: Request,
            site_id: str,
            layout_id: str,
            body: dict[str, Any],
        ):
            principal = self._require_request_action(request, "proposal.apply")
            session_id = self._generation_session_id(request)
            if body.get("prototypeMode") is not True:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": {
                            "code": "explicit_prototype_mode_required",
                            "message": (
                                "FacilityProgram generation requires prototypeMode=true."
                            ),
                            "details": {},
                        }
                    },
                )
            facility_program = body.get("facilityProgram")
            if not isinstance(facility_program, Mapping):
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": {
                            "code": "facility_program_intent_incomplete",
                            "message": "facilityProgram must be an object.",
                            "details": {},
                        }
                    },
                )
            current = self.service.get_layout(principal, site_id, layout_id)

            def start_run() -> dict[str, Any]:
                return self.generation_coordinator.start_facility_program_run(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    workspace_id=str(
                        body.get("workspaceId") or "workspace-facility-layout"
                    ),
                    layout_id=layout_id,
                    user_id=principal.principal_id,
                    session_id=session_id,
                    base_layout=current["layout"],
                    base_layout_revision=current["revision"],
                    facility_program=facility_program,
                    asset_catalog=deepcopy(list(self._catalog.values())),
                    prototype_mode=True,
                )

            try:
                try:
                    return start_run()
                except FacilityGenerationRunRepositoryError as error:
                    can_supersede = (
                        body.get("supersedeActiveDraft") is True
                        and error.code
                        in {
                            "generation_session_already_bound",
                            "generation_writable_lease_conflict",
                        }
                    )
                    prior_run_id = str(error.details.get("runId") or "").strip()
                    if not can_supersede or not prior_run_id:
                        raise
                    prior_envelope = self.generation_run_repository.get_run(
                        principal.tenant_id, site_id, prior_run_id
                    )
                    prior_run = prior_envelope["run"]
                    same_owned_draft = (
                        prior_run["layoutId"] == layout_id
                        and prior_run["userId"] == principal.principal_id
                        and prior_run["writable"] is True
                        and prior_run["status"]
                        not in {"cancelled", "expired", "saved", "stale"}
                    )
                    if not same_owned_draft:
                        raise
                    superseded = self.generation_coordinator.undo_to_base(
                        tenant_id=principal.tenant_id,
                        site_id=site_id,
                        run_id=prior_run_id,
                    )
                    replacement = start_run()
                    replacement["supersededRunId"] = prior_run_id
                    replacement["supersededReceiptIds"] = list(
                        superseded.get("supersededReceiptIds") or []
                    )
                    return replacement
            except (
                FacilityGenerationCoordinatorError,
                FacilityGenerationRunRepositoryError,
                FacilityProviderConfigurationError,
                FacilityKnowledgeContractError,
                FacilityLayoutError,
            ) as error:
                raise self._generation_error(error) from error

        @router.post(
            "/api/facility-layout-generation/{site_id}/{layout_id}/planning-package"
        )
        async def start_facility_planning_package_generation(
            request: Request,
            site_id: str,
            layout_id: str,
            body: dict[str, Any],
        ):
            principal = self._require_request_action(request, "proposal.apply")
            session_id = self._generation_session_id(request)
            if body.get("prototypeMode") is not True:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": {
                            "code": "explicit_prototype_mode_required",
                            "message": (
                                "Facility Planning generation requires "
                                "prototypeMode=true."
                            ),
                            "details": {},
                        }
                    },
                )
            package_id = str(body.get("planningPackageId") or "").strip()
            current = self.service.get_layout(principal, site_id, layout_id)

            def start_run() -> dict[str, Any]:
                package = self._load_facility_planning_package(package_id)
                compiled = compile_facility_planning_package(
                    package,
                    deepcopy(list(self._catalog.values())),
                )
                return self.generation_coordinator.start_facility_program_run(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    workspace_id=str(
                        body.get("workspaceId")
                        or "workspace-facility-layout"
                    ),
                    layout_id=layout_id,
                    user_id=principal.principal_id,
                    session_id=session_id,
                    base_layout=current["layout"],
                    base_layout_revision=current["revision"],
                    facility_program=compiled["facilityProgram"],
                    asset_catalog=deepcopy(list(self._catalog.values())),
                    prototype_mode=True,
                )

            try:
                try:
                    result = start_run()
                except FacilityGenerationRunRepositoryError as error:
                    can_supersede = (
                        body.get("supersedeActiveDraft") is True
                        and error.code
                        in {
                            "generation_session_already_bound",
                            "generation_writable_lease_conflict",
                        }
                    )
                    prior_run_id = str(error.details.get("runId") or "").strip()
                    if not can_supersede or not prior_run_id:
                        raise
                    prior_envelope = self.generation_run_repository.get_run(
                        principal.tenant_id, site_id, prior_run_id
                    )
                    prior_run = prior_envelope["run"]
                    same_owned_draft = (
                        prior_run["layoutId"] == layout_id
                        and prior_run["userId"] == principal.principal_id
                        and prior_run["writable"] is True
                        and prior_run["status"]
                        not in {"cancelled", "expired", "saved", "stale"}
                    )
                    if not same_owned_draft:
                        raise
                    superseded = self.generation_coordinator.undo_to_base(
                        tenant_id=principal.tenant_id,
                        site_id=site_id,
                        run_id=prior_run_id,
                    )
                    result = start_run()
                    result["supersededRunId"] = prior_run_id
                    result["supersededReceiptIds"] = list(
                        superseded.get("supersededReceiptIds") or []
                    )
                result["planningPackageId"] = package_id
                result["planningAuthority"] = "illustrative_prototype"
                return result
            except (
                FacilityPlanningPackageError,
                FacilityGenerationCoordinatorError,
                FacilityGenerationRunRepositoryError,
                FacilityProviderConfigurationError,
                FacilityKnowledgeContractError,
                FacilityLayoutError,
            ) as error:
                raise self._generation_error(error) from error

        @router.post(
            "/api/facility-layout-generation/{site_id}/{layout_id}/runs/"
            "{run_id}/continue"
        )
        async def continue_facility_generation(
            request: Request,
            site_id: str,
            layout_id: str,
            run_id: str,
            body: dict[str, Any],
        ):
            try:
                principal = self._require_request_action(
                    request, "proposal.create"
                )
                run_view = self.generation_coordinator.get_run(
                    principal.tenant_id, site_id, run_id
                )
                if run_view["draftLayout"]["layoutId"] != layout_id:
                    raise HTTPException(status_code=404, detail="Not found")
                if run_view["writable"]:
                    principal = self._require_request_action(
                        request, "proposal.apply"
                    )
                current = self.service.get_layout(
                    principal, site_id, layout_id
                )
                return self.generation_coordinator.continue_run(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    run_id=run_id,
                    current_base_layout=current["layout"],
                    current_base_revision=current["revision"],
                    explicit_stage_acceptance=(
                        body.get("explicitStageAcceptance") is True
                    ),
                )
            except (
                FacilityGenerationCoordinatorError,
                FacilityGenerationRunRepositoryError,
                FacilityProviderConfigurationError,
                FacilityKnowledgeContractError,
                FacilityLayoutError,
            ) as error:
                raise self._generation_error(error) from error

        @router.get(
            "/api/facility-layout-generation/{site_id}/{layout_id}/runs/"
            "{run_id}"
        )
        async def get_facility_generation_run(
            request: Request,
            site_id: str,
            layout_id: str,
            run_id: str,
        ):
            principal = self._require_request_action(request, "layout.read")
            try:
                result = self.generation_coordinator.get_run(
                    principal.tenant_id, site_id, run_id
                )
            except (
                FacilityGenerationCoordinatorError,
                FacilityGenerationRunRepositoryError,
                FacilityKnowledgeContractError,
                FacilityLayoutError,
            ) as error:
                raise self._generation_error(error) from error
            if result["draftLayout"]["layoutId"] != layout_id:
                raise HTTPException(status_code=404, detail="Not found")
            return result

        @router.post(
            "/api/facility-layout-generation/{site_id}/{layout_id}/runs/"
            "{run_id}/circulation"
        )
        async def amend_facility_generation_circulation(
            request: Request,
            site_id: str,
            layout_id: str,
            run_id: str,
            body: dict[str, Any],
        ):
            principal = self._require_request_action(
                request, "proposal.apply"
            )
            if body.get("prototypeMode") is not True:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": {
                            "code": "explicit_prototype_mode_required",
                            "message": (
                                "Circulation generation requires "
                                "prototypeMode=true."
                            ),
                            "details": {},
                        }
                    },
                )
            circulation = body.get("circulation")
            if not isinstance(circulation, Mapping):
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": {
                            "code": "facility_circulation_intent_incomplete",
                            "message": "circulation must be an object.",
                            "details": {},
                        }
                    },
                )
            try:
                run_envelope = self.generation_run_repository.get_run(
                    principal.tenant_id, site_id, run_id
                )
                run = run_envelope["run"]
                if (
                    run.get("layoutId") != layout_id
                    or run.get("userId") != principal.principal_id
                ):
                    raise HTTPException(status_code=404, detail="Not found")
                if run.get("prototypeMode") is not True:
                    raise FacilityGenerationCoordinatorError(
                        "facility_circulation_prototype_run_required",
                        "Circulation generation is enabled only for prototype runs.",
                    )
                current = self.service.get_layout(
                    principal, site_id, layout_id
                )
                obstacle_context = None
                if circulation.get("action") == "avoid_obstacles":
                    execution = (
                        self.generation_run_repository.get_execution_artifacts(
                            principal.tenant_id,
                            site_id,
                            run_id,
                        )
                    )
                    vehicle_ref = None
                    if circulation.get("vehicle_profile_id") is not None:
                        vehicle_ref = {
                            "vehicleProfileId": circulation.get(
                                "vehicle_profile_id"
                            ),
                            "vehicleProfileRevision": circulation.get(
                                "vehicle_profile_revision"
                            ),
                        }
                    obstacle_context = self.service.circulation_obstacle_context(
                        principal,
                        site_id,
                        execution["draft"]["document"],
                        vehicle_profile_ref=vehicle_ref,
                    )
                return self.generation_coordinator.amend_primary_circulation(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    run_id=run_id,
                    current_base_layout=current["layout"],
                    current_base_revision=current["revision"],
                    expected_draft_revision=str(
                        body.get("expectedDraftRevision") or ""
                    ),
                    circulation_request=circulation,
                    obstacle_context=obstacle_context,
                )
            except HTTPException:
                raise
            except (
                FacilityGenerationCoordinatorError,
                FacilityGenerationRunRepositoryError,
                FacilityProviderConfigurationError,
                FacilityKnowledgeContractError,
                FacilityLayoutError,
            ) as error:
                raise self._generation_error(error) from error

        @router.post(
            "/api/facility-layout-generation/{site_id}/{layout_id}/runs/"
            "{run_id}/subdivisions"
        )
        async def amend_facility_generation_subdivisions(
            request: Request,
            site_id: str,
            layout_id: str,
            run_id: str,
            body: dict[str, Any],
        ):
            principal = self._require_request_action(
                request, "proposal.apply"
            )
            if body.get("prototypeMode") is not True:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": {
                            "code": "explicit_prototype_mode_required",
                            "message": (
                                "Department subdivision requires "
                                "prototypeMode=true."
                            ),
                            "details": {},
                        }
                    },
                )
            subdivision = body.get("subdivision")
            if not isinstance(subdivision, Mapping):
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": {
                            "code": "facility_subdivision_intent_incomplete",
                            "message": "subdivision must be an object.",
                            "details": {},
                        }
                    },
                )
            try:
                run_envelope = self.generation_run_repository.get_run(
                    principal.tenant_id, site_id, run_id
                )
                run = run_envelope["run"]
                if (
                    run.get("layoutId") != layout_id
                    or run.get("userId") != principal.principal_id
                ):
                    raise HTTPException(status_code=404, detail="Not found")
                if run.get("prototypeMode") is not True:
                    raise FacilityGenerationCoordinatorError(
                        "facility_subdivision_prototype_run_required",
                        "Subdivision is enabled only for prototype runs.",
                    )
                current = self.service.get_layout(
                    principal, site_id, layout_id
                )
                return self.generation_coordinator.amend_department_subdivisions(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    run_id=run_id,
                    current_base_layout=current["layout"],
                    current_base_revision=current["revision"],
                    expected_draft_revision=str(
                        body.get("expectedDraftRevision") or ""
                    ),
                    subdivision_request=subdivision,
                )
            except HTTPException:
                raise
            except (
                FacilityGenerationCoordinatorError,
                FacilityGenerationRunRepositoryError,
                FacilityProviderConfigurationError,
                FacilityKnowledgeContractError,
                FacilityLayoutError,
            ) as error:
                raise self._generation_error(error) from error

        @router.post(
            "/api/facility-layout-generation/{site_id}/{layout_id}/runs/"
            "{run_id}/assets"
        )
        async def amend_facility_generation_assets(
            request: Request,
            site_id: str,
            layout_id: str,
            run_id: str,
            body: dict[str, Any],
        ):
            principal = self._require_request_action(
                request, "proposal.apply"
            )
            if body.get("prototypeMode") is not True:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": {
                            "code": "explicit_prototype_mode_required",
                            "message": (
                                "Asset placement requires prototypeMode=true."
                            ),
                            "details": {},
                        }
                    },
                )
            asset_placement = body.get("assetPlacement")
            if not isinstance(asset_placement, Mapping):
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": {
                            "code": "facility_asset_intent_incomplete",
                            "message": "assetPlacement must be an object.",
                            "details": {},
                        }
                    },
                )
            try:
                run_envelope = self.generation_run_repository.get_run(
                    principal.tenant_id, site_id, run_id
                )
                run = run_envelope["run"]
                if (
                    run.get("layoutId") != layout_id
                    or run.get("userId") != principal.principal_id
                ):
                    raise HTTPException(status_code=404, detail="Not found")
                if run.get("prototypeMode") is not True:
                    raise FacilityGenerationCoordinatorError(
                        "facility_asset_prototype_run_required",
                        "Asset placement is enabled only for prototype runs.",
                    )
                current = self.service.get_layout(
                    principal, site_id, layout_id
                )
                return self.generation_coordinator.amend_asset_placements(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    run_id=run_id,
                    current_base_layout=current["layout"],
                    current_base_revision=current["revision"],
                    expected_draft_revision=str(
                        body.get("expectedDraftRevision") or ""
                    ),
                    asset_request=asset_placement,
                    asset_catalog=deepcopy(list(self._catalog.values())),
                )
            except HTTPException:
                raise
            except (
                FacilityGenerationCoordinatorError,
                FacilityGenerationRunRepositoryError,
                FacilityProviderConfigurationError,
                FacilityKnowledgeContractError,
                FacilityLayoutError,
            ) as error:
                raise self._generation_error(error) from error

        @router.post(
            "/api/facility-layout-generation/{site_id}/{layout_id}/runs/"
            "{run_id}/facility-program/resource-batch"
        )
        async def amend_facility_program_resource_batch(
            request: Request,
            site_id: str,
            layout_id: str,
            run_id: str,
            body: dict[str, Any],
        ):
            principal = self._require_request_action(
                request, "proposal.apply"
            )
            if body.get("prototypeMode") is not True:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": {
                            "code": "explicit_prototype_mode_required",
                            "message": (
                                "FacilityProgram amendment requires "
                                "prototypeMode=true."
                            ),
                            "details": {},
                        }
                    },
                )
            resource_batch_id = str(
                body.get("resourceBatchId") or ""
            ).strip()
            patch = body.get("patch")
            if not resource_batch_id or not isinstance(patch, Mapping):
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": {
                            "code": (
                                "facility_program_local_amendment_invalid"
                            ),
                            "message": (
                                "resourceBatchId and patch are required."
                            ),
                            "details": {},
                        }
                    },
                )
            try:
                run_envelope = self.generation_run_repository.get_run(
                    principal.tenant_id, site_id, run_id
                )
                run = run_envelope["run"]
                if (
                    run.get("layoutId") != layout_id
                    or run.get("userId") != principal.principal_id
                ):
                    raise HTTPException(status_code=404, detail="Not found")
                if run.get("prototypeMode") is not True:
                    raise FacilityGenerationCoordinatorError(
                        "facility_program_amendment_prototype_run_required",
                        "FacilityProgram amendments are enabled only for prototype runs.",
                    )
                current = self.service.get_layout(
                    principal, site_id, layout_id
                )
                return self.generation_coordinator.amend_facility_program_resource_batch(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    run_id=run_id,
                    current_base_layout=current["layout"],
                    current_base_revision=current["revision"],
                    expected_draft_revision=str(
                        body.get("expectedDraftRevision") or ""
                    ),
                    resource_batch_id=resource_batch_id,
                    patch=patch,
                    asset_catalog=deepcopy(
                        list(self._catalog.values())
                    ),
                )
            except HTTPException:
                raise
            except (
                FacilityGenerationCoordinatorError,
                FacilityGenerationRunRepositoryError,
                FacilityProviderConfigurationError,
                FacilityKnowledgeContractError,
                FacilityLayoutError,
            ) as error:
                raise self._generation_error(error) from error

        @router.post(
            "/api/facility-layout-generation/{site_id}/{layout_id}/runs/"
            "{run_id}/cells"
        )
        async def amend_facility_generation_cells(
            request: Request,
            site_id: str,
            layout_id: str,
            run_id: str,
            body: dict[str, Any],
        ):
            principal = self._require_request_action(
                request, "proposal.apply"
            )
            if body.get("prototypeMode") is not True:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": {
                            "code": "explicit_prototype_mode_required",
                            "message": (
                                "Cell composition requires prototypeMode=true."
                            ),
                            "details": {},
                        }
                    },
                )
            cell_composition = body.get("cellComposition")
            if not isinstance(cell_composition, Mapping):
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": {
                            "code": "facility_cell_intent_incomplete",
                            "message": "cellComposition must be an object.",
                            "details": {},
                        }
                    },
                )
            try:
                run_envelope = self.generation_run_repository.get_run(
                    principal.tenant_id, site_id, run_id
                )
                run = run_envelope["run"]
                if (
                    run.get("layoutId") != layout_id
                    or run.get("userId") != principal.principal_id
                ):
                    raise HTTPException(status_code=404, detail="Not found")
                if run.get("prototypeMode") is not True:
                    raise FacilityGenerationCoordinatorError(
                        "facility_cell_prototype_run_required",
                        "Cell composition is enabled only for prototype runs.",
                    )
                current = self.service.get_layout(
                    principal, site_id, layout_id
                )
                return self.generation_coordinator.amend_cell_composition(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    run_id=run_id,
                    current_base_layout=current["layout"],
                    current_base_revision=current["revision"],
                    expected_draft_revision=str(
                        body.get("expectedDraftRevision") or ""
                    ),
                    cell_request=cell_composition,
                    asset_catalog=deepcopy(list(self._catalog.values())),
                )
            except HTTPException:
                raise
            except (
                FacilityGenerationCoordinatorError,
                FacilityGenerationRunRepositoryError,
                FacilityProviderConfigurationError,
                FacilityKnowledgeContractError,
                FacilityLayoutError,
            ) as error:
                raise self._generation_error(error) from error

        @router.post(
            "/api/facility-layout-generation/{site_id}/{layout_id}/runs/"
            "{run_id}/cell-replication"
        )
        async def amend_facility_generation_cell_replication(
            request: Request,
            site_id: str,
            layout_id: str,
            run_id: str,
            body: dict[str, Any],
        ):
            principal = self._require_request_action(
                request, "proposal.apply"
            )
            if body.get("prototypeMode") is not True:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": {
                            "code": "explicit_prototype_mode_required",
                            "message": (
                                "Cell replication requires prototypeMode=true."
                            ),
                            "details": {},
                        }
                    },
                )
            replication = body.get("cellReplication")
            if not isinstance(replication, Mapping):
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": {
                            "code": "facility_cell_module_intent_incomplete",
                            "message": "cellReplication must be an object.",
                            "details": {},
                        }
                    },
                )
            try:
                run_envelope = self.generation_run_repository.get_run(
                    principal.tenant_id, site_id, run_id
                )
                run = run_envelope["run"]
                if (
                    run.get("layoutId") != layout_id
                    or run.get("userId") != principal.principal_id
                ):
                    raise HTTPException(status_code=404, detail="Not found")
                if run.get("prototypeMode") is not True:
                    raise FacilityGenerationCoordinatorError(
                        "facility_cell_module_prototype_run_required",
                        "Cell replication is enabled only for prototype runs.",
                    )
                current = self.service.get_layout(
                    principal, site_id, layout_id
                )
                return self.generation_coordinator.amend_cell_replication(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    run_id=run_id,
                    current_base_layout=current["layout"],
                    current_base_revision=current["revision"],
                    expected_draft_revision=str(
                        body.get("expectedDraftRevision") or ""
                    ),
                    replication_request=replication,
                    asset_catalog=deepcopy(list(self._catalog.values())),
                )
            except HTTPException:
                raise
            except (
                FacilityGenerationCoordinatorError,
                FacilityGenerationRunRepositoryError,
                FacilityProviderConfigurationError,
                FacilityKnowledgeContractError,
                FacilityLayoutError,
            ) as error:
                raise self._generation_error(error) from error

        @router.post(
            "/api/facility-layout-generation/{site_id}/{layout_id}/runs/"
            "{run_id}/invalidate"
        )
        async def invalidate_facility_generation(
            request: Request,
            site_id: str,
            layout_id: str,
            run_id: str,
            body: dict[str, Any],
        ):
            principal = self._require_request_action(request, "proposal.apply")
            try:
                return self.generation_coordinator.invalidate_from_stage(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    run_id=run_id,
                    upstream_stage_id=str(body.get("upstreamStageId") or ""),
                    reason=str(
                        body.get("reason") or "upstream_dependency_changed"
                    ),
                    dependency_fingerprint_after=str(
                        body.get("dependencyFingerprintAfter") or ""
                    ),
                )
            except (
                FacilityGenerationCoordinatorError,
                FacilityGenerationRunRepositoryError,
                FacilityKnowledgeContractError,
                FacilityLayoutError,
            ) as error:
                raise self._generation_error(error) from error

        @router.post(
            "/api/facility-layout-generation/{site_id}/{layout_id}/runs/"
            "{run_id}/undo"
        )
        async def undo_facility_generation(
            request: Request,
            site_id: str,
            layout_id: str,
            run_id: str,
        ):
            principal = self._require_request_action(request, "proposal.apply")
            try:
                return self.generation_coordinator.undo_to_base(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    run_id=run_id,
                )
            except (
                FacilityGenerationCoordinatorError,
                FacilityGenerationRunRepositoryError,
                FacilityKnowledgeContractError,
                FacilityLayoutError,
            ) as error:
                raise self._generation_error(error) from error

        @router.post(
            "/api/facility-layout-generation/{site_id}/{layout_id}/runs/"
            "{run_id}/save"
        )
        async def save_facility_generation(
            request: Request,
            site_id: str,
            layout_id: str,
            run_id: str,
            body: dict[str, Any],
        ):
            principal = self._require_request_action(request, "layout.edit")
            current = self.service.get_layout(principal, site_id, layout_id)
            try:
                return self.generation_coordinator.save_run(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    run_id=run_id,
                    current_base_layout=current["layout"],
                    current_base_revision=current["revision"],
                    expected_cumulative_diff_hash=str(
                        body.get("cumulativeDiffHash") or ""
                    ),
                    explicit_approval=body.get("explicitApproval") is True,
                    approved_by=principal.principal_id,
                    persist=lambda document, base_revision: (
                        self.service.save_layout(
                            principal,
                            site_id,
                            layout_id,
                            document,
                            base_revision,
                        )
                    ),
                )
            except (
                FacilityGenerationCoordinatorError,
                FacilityGenerationRunRepositoryError,
                FacilityProviderConfigurationError,
                FacilityKnowledgeContractError,
                FacilityLayoutError,
            ) as error:
                raise self._generation_error(error) from error

        # The lighting coverage estimate (docs/facility-lighting-plan.md, CC3): read only, for the layout as the
        # view holds it (the saved revision and the view's unsaved operations); nothing is saved.
        @router.post("/api/facility-layouts/{site_id}/{layout_id}/lighting/coverage")
        async def lighting_coverage(
            request: Request,
            site_id: str,
            layout_id: str,
            body: dict[str, Any],
        ):
            principal = self._require_request_action(request, "layout.read")
            import asyncio
            return await asyncio.to_thread(self._lighting_coverage, principal, site_id, layout_id, body)

        router.include_router(
            create_facility_layout_router(
                service=self.service,
                principal_resolver=self.resolve_principal,
                feature_gate=self.feature_flags.require,
            )
        )
        from .sage_shots import create_sage_shots_router
        router.include_router(
            create_sage_shots_router(shots=self.sage_shots, principal_resolver=self.resolve_principal)
        )
        return router


def create_local_facility_layout_router(
    root: str | Path,
    *,
    process_map_root: str | Path | None = None,
) -> APIRouter:
    """Create the local-mode product router for the host FastAPI app."""

    effective_process_map_root = (
        Path(process_map_root)
        if process_map_root is not None
        else Path(__file__).resolve().parents[2] / "generated" / "training"
    )
    return LocalFacilityLayoutHost(
        root,
        process_map_root=effective_process_map_root,
        feature_flags=FacilityLayoutFeatureFlags.from_environment(),
    ).create_router()


__all__ = [
    "LOCAL_ASSET_CATALOG",
    "LOCAL_LAYOUT_ID",
    "LOCAL_SITE_ID",
    "PRIVATE_ASSET_ENV",
    "LocalFacilityLayoutHost",
    "build_private_local_asset_catalog",
    "create_local_facility_layout_router",
]
