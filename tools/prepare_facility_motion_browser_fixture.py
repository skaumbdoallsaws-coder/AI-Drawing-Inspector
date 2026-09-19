"""Prepare an isolated fl-main identity clone of the archived manual layout."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.facility_layout.canonical import (  # noqa: E402
    canonical_layout_bytes,
    canonicalize_layout,
    layout_revision,
)
from ai_inspector.facility_layout.authority_repository import (  # noqa: E402
    VehicleProfileRepository,
)
from ai_inspector.facility_layout.authorization import (  # noqa: E402
    FacilityPrincipal,
)
from ai_inspector.facility_layout.errors import (  # noqa: E402
    FacilityNotFoundError,
)


DEFAULT_SOURCE = (
    ROOT
    / ".runtime"
    / "facility-layout"
    / "layouts"
    / "local"
    / "site-local"
    / "layouts"
    / "fl-reference-manual-20260812.json"
)
DEFAULT_ROOT = ROOT / ".runtime" / "facility-motion" / "acceptance-root"
DEFAULT_PROFILE_FIXTURE = (
    ROOT / "tests" / "fixtures" / "facility_layout" / "p0_authority_documents.json"
)
PROTOTYPE_PROFILE_ID = "prototype-reference-forklift-v1"
PROTOTYPE_PROFILE_LABEL = (
    "Prototype fixture profile on archived manual factory"
)
DETAILED_PROFILE_ID = "prototype-red-telescopic-forklift-v1"
DETAILED_PROFILE_LABEL = (
    "Prototype profile bound to the Red Telescopic Forklift CAD asset; "
    "operating limits are synthetic and not production eligible"
)
DETAILED_ASSET_ID = "asset-forklift-telescopic-red"
DETAILED_ASSET_REVISION = (
    "ab73c19258c171d1c3cab496cd317b1d896293249ddd62c57cba81a61829f214"
)
DETAILED_PLACEMENT_ID = "pl-043ba93c06287a1189f76121"
DETAILED_CATALOG_ENTRY = (
    ROOT
    / "generated"
    / "industrial_assets"
    / "local_library"
    / "forklift-telescopic-red"
    / "catalog-entry.json"
)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def _base_vehicle_profile() -> dict[str, Any]:
    values = json.loads(DEFAULT_PROFILE_FIXTURE.read_text(encoding="ascii"))
    return deepcopy(next(
        item for item in values if item.get("documentKind") == "vehicle_profile"
    ))


def _store_prototype_profile(
    root: Path,
    *,
    profile_id: str,
    profile_label: str,
    profile: dict[str, Any],
) -> dict[str, Any]:
    profile.update({
        "vehicleProfileId": profile_id,
        "tenantId": "local",
        "siteId": "site-local",
        "status": "draft",
        "prototypeMode": True,
        "prototypeLabel": profile_label,
        "productionEligible": False,
        "evidenceAuthority": "prototype_fixture",
    })
    repository = VehicleProfileRepository(root / "authorities" / "vehicles")
    principal = FacilityPrincipal(
        principal_id="motion-fixture-builder",
        tenant_id="local",
        allowed_site_ids=("site-local",),
        roles=("admin",),
    )
    try:
        envelope = repository.get_current(
            principal,
            site_id="site-local",
            authority_id=profile_id,
        )
        if envelope.document != profile or envelope.status != "draft":
            raise RuntimeError(
                "The existing prototype vehicle fixture does not match the "
                "expected non-production draft."
            )
    except FacilityNotFoundError:
        envelope = repository.create(
            principal,
            site_id="site-local",
            document=profile,
        ).envelope
    return {
        "vehicleProfileId": profile_id,
        "vehicleProfileRevision": envelope.revision,
        "status": envelope.status,
        "prototypeMode": True,
        "productionEligible": False,
        "prototypeLabel": profile_label,
    }


def _prepare_prototype_profiles(
    root: Path,
    layout: dict[str, Any],
) -> list[dict[str, Any]]:
    generic = _base_vehicle_profile()
    generic["displayName"] = "Prototype Reference Forklift"
    stored = [_store_prototype_profile(
        root,
        profile_id=PROTOTYPE_PROFILE_ID,
        profile_label=PROTOTYPE_PROFILE_LABEL,
        profile=generic,
    )]

    placement = next(
        (
            item
            for item in layout.get("placements", [])
            if item.get("placementId") == DETAILED_PLACEMENT_ID
        ),
        None,
    )
    if placement is None or {
        "assetId": placement.get("assetId"),
        "assetDefinitionRevision": placement.get("assetDefinitionRevision"),
    } != {
        "assetId": DETAILED_ASSET_ID,
        "assetDefinitionRevision": DETAILED_ASSET_REVISION,
    }:
        raise RuntimeError(
            "The archived detailed forklift placement no longer matches its "
            "frozen asset identity."
        )
    catalog = json.loads(DETAILED_CATALOG_ENTRY.read_text(encoding="utf-8"))
    dimensions = catalog["dimensions"]
    length = float(dimensions["width"])
    width = float(dimensions["depth"])
    detailed = _base_vehicle_profile()
    detailed.update({
        "displayName": "Red Telescopic Forklift - Prototype Motion Fixture",
        "overallDimensions": {
            "length": length,
            "width": width,
            "height": float(dimensions["height"]),
        },
        "footprint": [
            {"x": -length / 2.0, "z": -width / 2.0},
            {"x": length / 2.0, "z": -width / 2.0},
            {"x": length / 2.0, "z": width / 2.0},
            {"x": -length / 2.0, "z": width / 2.0},
        ],
        # Geometry is catalog-derived. All behavior below remains synthetic.
        "wheelbase": 2.0,
        "steeringLimits": {"minimumTurningRadiusMeters": 2.3},
        "speedLimits": {"maximumMetersPerSecond": 1.0},
        "loadLimits": {"maximumKilograms": 0},
        "gradeLimits": {"maximumPercent": 0},
        "reversePolicy": "prohibited",
        "assetDefinitionRef": {
            "assetId": DETAILED_ASSET_ID,
            "assetDefinitionRevision": DETAILED_ASSET_REVISION,
        },
        "fieldAuthority": {
            "overallDimensions": "catalog_derived",
            "footprint": "catalog_derived_bounding_envelope",
            "wheelbase": "synthetic_demo",
            "steeringLimits": "synthetic_demo",
            "speedLimits": "synthetic_demo",
            "loadLimits": "synthetic_demo",
            "gradeLimits": "synthetic_demo",
            "reversePolicy": "synthetic_demo",
        },
        "sourceDocuments": [],
        "evidence": [],
        "unresolvedItems": [{
            "findingId": "motion-fixture-operating-limits",
            "code": "prototype-vehicle-limits-unverified",
            "message": (
                "Wheelbase, steering, speed, load, grade, and reverse-policy "
                "values are synthetic fixture inputs and are not approved "
                "vehicle specifications."
            ),
        }],
    })
    stored.append(_store_prototype_profile(
        root,
        profile_id=DETAILED_PROFILE_ID,
        profile_label=DETAILED_PROFILE_LABEL,
        profile=detailed,
    ))
    return stored


def prepare(source: Path, root: Path) -> dict[str, Any]:
    source = source.resolve()
    root = root.resolve()
    source_before = _hash(source)
    archived = json.loads(source.read_text(encoding="utf-8"))
    clone = deepcopy(archived)
    clone["layoutId"] = "fl-main"
    clone = canonicalize_layout(clone)
    clone_revision = layout_revision(clone)
    destination = (
        root / "layouts" / "local" / "site-local" / "layouts" / "fl-main.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(canonical_layout_bytes(clone))
    summary = {
        "association": deepcopy(clone["association"]),
        "createdAt": "2026-08-30T00:00:00Z",
        "currentRevision": clone_revision,
        "displayName": "Reference Factory - Manual Build (Motion Acceptance)",
        "layoutId": "fl-main",
        "status": "draft",
        "updatedAt": "2026-08-30T00:00:00Z",
    }
    registry = {
        "schemaVersion": 1,
        "recordKind": "facility_layout_registry",
        "tenantId": "local",
        "siteId": "site-local",
        "defaultLayoutId": "fl-main",
        "layouts": [summary],
    }
    registry_path = destination.parent / "registry.json"
    registry_path.write_bytes(_canonical_json(registry))
    prototype_profiles = _prepare_prototype_profiles(root, archived)
    source_after = _hash(source)
    receipt = {
        "schemaVersion": 1,
        "source": {
            "path": source.relative_to(ROOT).as_posix(),
            "sha256Before": source_before,
            "sha256After": source_after,
            "byteIdentical": source_before == source_after,
            "layoutId": archived["layoutId"],
        },
        "browserClone": {
            "path": destination.relative_to(ROOT).as_posix(),
            "layoutId": clone["layoutId"],
            "revision": clone_revision,
            "zoneCount": len(clone.get("zones", [])),
            "routeCount": len(clone.get("routes", [])),
            "placementCount": len(clone.get("placements", [])),
            "markingCount": len(clone.get("floorMarkings", [])),
        },
        "prototypeVehicleProfile": prototype_profiles[0],
        "prototypeVehicleProfiles": prototype_profiles,
    }
    (root.parent / "browser-fixture-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    args = parser.parse_args()
    receipt = prepare(Path(args.source), Path(args.root))
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["source"]["byteIdentical"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
