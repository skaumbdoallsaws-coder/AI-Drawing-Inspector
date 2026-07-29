"""Bounded deterministic Facility Layout digest tests."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.digest import (
    FACILITY_LAYOUT_DIGEST_MAXIMUM_CANONICAL_UTF8_BYTES,
    FACILITY_LAYOUT_DIGEST_MAXIMUM_TOKENS,
    FacilityDigestError,
    build_facility_layout_digest,
    canonical_facility_digest_bytes,
)
from ai_inspector.facility_layout.observation import (
    build_facility_layout_observation,
    trusted_facility_source,
)


ROOT = Path(__file__).parent / "fixtures" / "facility_layout" / "semantic"
GOLDEN_FIXTURE = ROOT / "p9-semantic-golden.json"
SCALE_SPEC = ROOT / "warehouse-5000-spec.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="ascii"))


def _source(kind: str, value, revision: str | None = None):
    return trusted_facility_source(
        kind,
        value,
        revision=revision,
        provider=f"test-{kind}",
    )


def _golden_observation() -> dict:
    fixture = _load(GOLDEN_FIXTURE)
    layout = fixture["baseLayout"]
    return build_facility_layout_observation(
        _source("facility_layout", layout, layout_revision(layout)),
        _source(
            "industrial_asset_catalog",
            fixture["assetCatalog"],
            fixture["assetCatalogRevision"],
        ),
        shell_source=_source(
            "facility_shell",
            fixture["shell"],
            layout["sourceShellRef"]["shellRevision"],
        ),
        policy_source=_source(
            "facility_policy",
            fixture["policy"],
            layout["policySetRef"]["policySetRevision"],
        ),
        evidence_source=_source(
            "facility_evidence",
            fixture["evidence"],
            fixture["evidenceRevision"],
        ),
        vehicle_source=_source(
            "vehicle_profiles",
            fixture["vehicles"],
            fixture["vehiclesRevision"],
        ),
        process_source=_source(
            "process_maps",
            fixture["processMaps"],
            fixture["processMapsRevision"],
        ),
        diagnostics_source=_source(
            "facility_diagnostics",
            fixture["diagnostics"],
        ),
        capabilities_source=_source(
            "facility_capabilities",
            fixture["capabilities"],
        ),
        live_facts={
            "dirty": False,
            "conflict": False,
            "editable": True,
            "viewportMode": "split",
            "selection": {
                "placementIds": ["pl-p9-existing-manual"],
                "zoneIds": ["zn-p9-workcell"],
            },
        },
    )


def _scale_observation() -> dict:
    spec = _load(SCALE_SPEC)
    count = spec["placementCount"]
    columns = spec["columns"]
    spacing = float(spec["spacingMeters"])
    placements = []
    for index in range(count):
        mode = (
            "manual" if index == count - 2
            else "locked" if index == count - 1
            else "auto"
        )
        placements.append(
            {
                "placementId": f"pl-rack-{index:04d}",
                "assetId": spec["assetId"],
                "assetDefinitionRevision": spec[
                    "assetDefinitionRevision"
                ],
                "transform": {
                    "position": {
                        "x": (index % columns) * spacing + 1.0,
                        "y": 0.0,
                        "z": (index // columns) * spacing + 1.0,
                    },
                    "quaternion": {
                        "x": 0.0,
                        "y": 0.0,
                        "z": 0.0,
                        "w": 1.0,
                    },
                    "scale": 1,
                },
                "positionMode": mode,
                "snapRelationship": None,
                "metadata": {"instanceLabel": f"Rack {index + 1}"},
            }
        )
    layout = {
        "schemaVersion": 1,
        "layoutId": spec["layoutId"],
        "displayName": "P9 Warehouse 5000",
        "status": "draft",
        "association": {
            "siteId": spec["siteId"],
            "areaId": "warehouse-p9",
        },
        "coordinateFrame": {
            "units": "m",
            "handedness": "right",
            "upAxis": "+Y",
            "floorAxes": ["+X", "+Z"],
            "datumId": "site-p9-scale-origin",
            "floorElevation": 0.0,
        },
        "sourceShellRef": {
            "shellId": "shell-p9-scale",
            "shellRevision": spec["shellRevision"],
            "coordinateFrameFingerprint": "d" * 64,
        },
        "catalogSnapshotRevision": "e" * 64,
        "policySetRef": {
            "policySetId": "policy-p9-scale",
            "policySetRevision": spec["policyRevision"],
        },
        "zones": [
            {
                "zoneId": "zn-p9-scale-storage",
                "zoneType": "storage",
                "label": "Rack storage",
                "boundary": [
                    {"x": 0.0, "z": 0.0},
                    {"x": 202.0, "z": 0.0},
                    {"x": 202.0, "z": 102.0},
                    {"x": 0.0, "z": 102.0},
                ],
                "floorElevation": 0.0,
                "heightLimit": 12.0,
                "allowedAssetCategories": ["storage"],
                "gridSpacing": 0.5,
                "anchors": [],
                "evidence": [],
            }
        ],
        "placements": placements,
        "routes": [],
        "utilityNetworks": [],
        "processBindings": [],
        "dismissedSuggestions": [],
        "createdAt": "2026-07-29T00:00:00Z",
        "updatedAt": "2026-07-29T00:00:00Z",
    }
    asset_catalog = {
        "assets": [
            {
                "revision": spec["assetDefinitionRevision"],
                "document": {
                    "assetId": spec["assetId"],
                    "displayName": "P9 pallet rack",
                    "category": "storage",
                    "readiness": {"planningReady": True},
                    "capabilities": {
                        "capabilityIds": ["pallet_storage"]
                    },
                    "geometry": {
                        "footprintPolygons": [
                            [
                                {"x": -0.4, "z": -0.4},
                                {"x": 0.4, "z": -0.4},
                                {"x": 0.4, "z": 0.4},
                                {"x": -0.4, "z": 0.4},
                            ]
                        ],
                        "heightInterval": {
                            "minimumY": 0.0,
                            "maximumY": 5.0,
                        },
                    },
                    "connectors": [],
                    "evidence": [],
                },
            }
        ]
    }
    return build_facility_layout_observation(
        _source("facility_layout", layout, layout_revision(layout)),
        _source("industrial_asset_catalog", asset_catalog, "e" * 64),
        shell_source=_source(
            "facility_shell",
            {"shellId": "shell-p9-scale"},
            spec["shellRevision"],
        ),
        policy_source=_source(
            "facility_policy",
            {"policySetId": "policy-p9-scale"},
            spec["policyRevision"],
        ),
        live_facts={
            "dirty": False,
            "conflict": False,
            "editable": True,
            "viewportMode": "plan",
            "selection": {
                "placementIds": ["pl-rack-4999"],
                "zoneIds": ["zn-p9-scale-storage"],
            },
        },
    )


def test_small_digest_is_byte_stable_and_pins_contract() -> None:
    observation = _golden_observation()
    first = build_facility_layout_digest(
        observation["state"],
        observation["evidence"],
    )
    second = build_facility_layout_digest(
        observation["state"],
        observation["evidence"],
    )
    payload = canonical_facility_digest_bytes(first)

    assert first == second
    assert hashlib.sha256(payload).hexdigest() == (
        "dfcc60824645d1a072f3252d4c80d5e595d61c8f79b6980ad69888dadd09728f"
    )
    assert first["digestContractVersion"] == 1
    assert first["tokenizerId"] == "inspectorpro_utf8_quarter_v1"
    assert first["tokenizerRevision"] == 1
    assert first["counts"] == {
        "placements": 1,
        "zones": 2,
        "routes": 0,
        "utilityNetworks": 0,
        "processBindings": 0,
        "assetDefinitions": 2,
        "vehicles": 1,
        "findings": 1,
        "unresolvedAuthorityGaps": 1,
    }
    assert first["selectedEntities"] == [
        {
            "id": "pl-p9-existing-manual",
            "kind": "placement",
            "displayName": "P9 Inspection Station",
            "assetId": "asset-inspection-p9",
            "assetDefinitionRevision": "d" * 64,
            "category": "inspection",
            "positionMode": "manual",
            "zoneIds": ["zn-p9-workcell"],
            "capabilityIds": ["inspection"],
        },
        {
            "id": "zn-p9-workcell",
            "kind": "zone",
            "label": "Machining and inspection cell",
            "zoneType": "workcell",
        },
    ]
    assert first["estimatedTokens"] <= 4500
    assert first["canonicalUtf8Bytes"] <= 24576


def test_warehouse_5000_digest_uses_summaries_and_stable_read_descriptors() -> None:
    observation = _scale_observation()
    digest = build_facility_layout_digest(
        observation["state"],
        observation["evidence"],
    )
    encoded = canonical_facility_digest_bytes(digest)

    assert digest["counts"]["placements"] == 5000
    assert digest["positionModes"] == [
        {"positionMode": "auto", "count": 4998},
        {"positionMode": "locked", "count": 1},
        {"positionMode": "manual", "count": 1},
    ]
    placements = next(
        item for item in digest["readDescriptors"]
        if item["collection"] == "placements"
    )
    assert placements["totalCount"] == 5000
    assert placements["returnedCount"] == 12
    assert placements["omittedCount"] == 4988
    assert placements["sampleIds"][0] == "pl-rack-4999"
    assert placements["readTool"] == "inspect_facility_entities"
    assert placements["pagination"] == "opaque_revision_bound_cursor"
    assert digest["selectedEntities"][0]["id"] == "pl-rack-4999"
    assert digest["assetUsage"][0]["placementCount"] == 5000
    assert digest["estimatedTokens"] <= (
        FACILITY_LAYOUT_DIGEST_MAXIMUM_TOKENS
    )
    assert digest["canonicalUtf8Bytes"] <= (
        FACILITY_LAYOUT_DIGEST_MAXIMUM_CANONICAL_UTF8_BYTES
    )
    assert len(encoded) == digest["canonicalUtf8Bytes"]
    assert b'"transform"' not in encoded
    assert b'"position"' not in encoded
    assert len(encoded) < 12000


def test_digest_rejects_browser_spoofed_server_tags() -> None:
    observation = _golden_observation()
    spoofed = deepcopy(dict(observation["state"]))
    spoofed["origin"] = {
        "kind": "server",
        "provider": "browser-attacker",
    }
    with pytest.raises(FacilityDigestError) as caught:
        build_facility_layout_digest(
            spoofed,
            observation["evidence"],
        )
    assert caught.value.code == "untrusted_facility_context"


def test_digest_fails_closed_when_configured_bounds_cannot_fit() -> None:
    observation = _golden_observation()
    with pytest.raises(FacilityDigestError) as caught:
        build_facility_layout_digest(
            observation["state"],
            observation["evidence"],
            maximum_tokens=255,
        )
    assert caught.value.code == "facility_digest_budget_invalid"
