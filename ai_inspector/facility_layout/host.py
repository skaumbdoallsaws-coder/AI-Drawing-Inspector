"""Local InspectorPro host integration for the Facility Layout domain.

The domain repositories and authorization layer remain authoritative. This
module only supplies the explicit single-user local principal and a small,
revisioned starter catalog so the production UI can mount without a separate
tenant provisioning service.
"""

from __future__ import annotations

import hashlib
import json
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from fastapi import APIRouter, HTTPException, Query, Request

from .api import create_facility_layout_router
from .authority_repository import (
    FacilityShellRepository,
    PolicySetRepository,
    VehicleProfileRepository,
)
from .authorization import FacilityPrincipal, local_facility_principal
from .errors import FacilityNotFoundError
from .operations import create_layout_document
from .repository import FacilityLayoutRepository
from .service import FacilityLayoutService, coordinate_frame_fingerprint


LOCAL_SITE_ID = "site-local"
LOCAL_LAYOUT_ID = "fl-main"
LOCAL_SHELL_ID = "shell-local"
LOCAL_POLICY_ID = "policy-local"


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
    ) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.process_map_root = (
            Path(process_map_root).resolve()
            if process_map_root is not None
            else None
        )
        authority_root = self.root / "authorities"
        self.layout_repository = FacilityLayoutRepository(self.root / "layouts")
        self.shell_repository = FacilityShellRepository(
            authority_root / "shells"
        )
        self.policy_repository = PolicySetRepository(
            authority_root / "policies"
        )
        self.vehicle_repository = VehicleProfileRepository(
            authority_root / "vehicles"
        )
        self._catalog = {
            item["assetId"]: deepcopy(item)
            for item in LOCAL_ASSET_CATALOG
        }
        self.service = FacilityLayoutService(
            layout_repository=self.layout_repository,
            shell_repository=self.shell_repository,
            policy_repository=self.policy_repository,
            vehicle_repository=self.vehicle_repository,
            asset_definition_resolver=self._resolve_asset_definition,
            process_map_resolver=(
                self._resolve_process_map
                if self.process_map_root is not None
                else None
            ),
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
            return {
                "schemaVersion": 1,
                "siteId": LOCAL_SITE_ID,
                "layoutId": LOCAL_LAYOUT_ID,
                "layout": layout_receipt,
                "assetCatalog": deepcopy(list(self._catalog.values())),
                "worldBounds": {
                    "minX": 0,
                    "minZ": 0,
                    "maxX": 40,
                    "maxZ": 30,
                    "floorY": float(
                        shell.document["coordinateFrame"].get(
                            "floorElevation",
                            0,
                        )
                    ),
                },
                "capabilities": {
                    "manualAuthoring": True,
                    "authoritativePreview": True,
                    "casSave": True,
                    "collisionValidation": True,
                    "candidateSnapping": True,
                    "coarseAdvisoryWorker": True,
                },
            }

    def resolve_principal(self, _request: Request) -> FacilityPrincipal:
        self.ensure_bootstrap()
        return self.principal()

    def create_router(self) -> APIRouter:
        router = APIRouter()
        router.add_event_handler("shutdown", self.close)

        @router.get("/api/facility-layout-bootstrap")
        async def bootstrap():
            return self.ensure_bootstrap()

        @router.get("/api/industrial-assets")
        async def list_assets(
            site_id: str = Query(LOCAL_SITE_ID, alias="siteId"),
        ):
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

        router.include_router(
            create_facility_layout_router(
                service=self.service,
                principal_resolver=self.resolve_principal,
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
    ).create_router()


__all__ = [
    "LOCAL_ASSET_CATALOG",
    "LOCAL_LAYOUT_ID",
    "LOCAL_SITE_ID",
    "LocalFacilityLayoutHost",
    "create_local_facility_layout_router",
]
