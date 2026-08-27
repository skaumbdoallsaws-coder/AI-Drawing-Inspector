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
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request

from .api import create_facility_layout_router
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
from .agent_runtime import (
    FacilityLayoutAgentRuntime,
    FacilityLayoutAgentRuntimeError,
)
from .errors import FacilityLayoutError, FacilityNotFoundError
from .feature_flags import FacilityLayoutFeatureFlags
from .generation_run_repository import FacilityGenerationRunRepository
from .generation_coordinator import (
    FacilityGenerationCoordinator,
    FacilityGenerationCoordinatorError,
)
from .generation_run_repository import FacilityGenerationRunRepositoryError
from .identity import FacilityPrincipalResolver
from .operations import create_layout_document
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
from .provider_config import FacilityProviderConfigurationError
from .transaction_adapter import FacilityLayoutTransactionRuntime


LOCAL_SITE_ID = "site-local"
LOCAL_LAYOUT_ID = "fl-main"
LOCAL_SHELL_ID = "shell-local"
LOCAL_POLICY_ID = "policy-local"
PRIVATE_ASSET_ENV = "INSPECTORPRO_FACILITY_PRIVATE_ASSETS"
PRIVATE_ASSET_MANIFEST = Path(
    "generated/industrial_assets/local_library/catalog.json"
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
        "connectors": [],
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
            entry["overview"] = {
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
        require_distinct_approver: bool = False,
        principal_resolver: (
            Callable[[Request], FacilityPrincipal] | None
        ) = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.process_map_root = (
            Path(process_map_root).resolve()
            if process_map_root is not None
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
        catalog_source = (
            build_private_local_asset_catalog(private_asset_root)
            if use_private_assets
            else LOCAL_ASSET_CATALOG
        )
        self._catalog = {
            item["assetId"]: deepcopy(item)
            for item in catalog_source
        }
        # Private visual definitions are new immutable revisions, not
        # replacements for revisions already referenced by saved layouts.
        # Keep both so existing placements remain verifiable while the asset
        # browser offers the current private definition for new placements.
        self._asset_versions = {
            (item["assetId"], item["assetDefinitionRevision"]): deepcopy(item)
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
            process_map_resolver=(
                self._resolve_process_map
                if self.process_map_root is not None
                else None
            ),
            transaction_runtime=self.transaction_runtime,
        )
        self.agent_runtime = FacilityLayoutAgentRuntime(
            service=self.service,
            shell_repository=self.shell_repository,
            policy_repository=self.policy_repository,
            vehicle_repository=self.vehicle_repository,
            asset_catalog_provider=self._agent_asset_catalog,
            process_catalog_provider=self._agent_process_catalog,
            capabilities_provider=self._agent_capabilities,
        )
        self._lock = threading.RLock()
        self._bootstrapped = False

    @staticmethod
    def principal() -> FacilityPrincipal:
        return local_facility_principal(site_id=LOCAL_SITE_ID)

    def close(self) -> None:
        """Release bounded background spatial workers."""

        self.service.spatial_executor.close(wait=True)

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
        _revision: str,
    ) -> Mapping[str, Any] | None:
        if self.process_map_root is None:
            return None
        from ai_inspector.process_map.repository import (
            ProcessMapAssetError,
            load_named_process_map,
        )

        try:
            result = load_named_process_map(
                self.process_map_root,
                product_id,
                map_id,
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
            try:
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

        router.include_router(
            create_facility_layout_router(
                service=self.service,
                principal_resolver=self.resolve_principal,
                feature_gate=self.feature_flags.require,
            )
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
