from __future__ import annotations

from copy import deepcopy
import json
import math
import os
from pathlib import Path
import random
import statistics
import time

import pytest

from ai_inspector.facility_layout.service import FacilityLayoutService
from ai_inspector.facility_layout.spatial import (
    GEOMETRY_EPSILON,
    SpatialRecord,
    UniformGridSpatialIndex,
    brute_force_query,
    canonical_spatial_bytes,
    diagnose_layout,
    generate_placement_candidates,
    height_intervals_intersect,
    oriented_box_polygon,
    placement_spatial_records,
    point_in_polygon,
    polygon_contains_polygon,
    polygons_intersect,
    sort_findings,
    stable_candidate_id,
    stable_finding_id,
)
from ai_inspector.facility_layout.validate import validate_layout
from ai_inspector.industrial_assets.authority import EvidenceRecord


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "facility_layout"
    / "spatial"
    / "golden_scenarios.json"
)
NATIVE_FIXTURE = FIXTURE.with_name("native_layout_v1.json")
PERFORMANCE_FIXTURE = FIXTURE.with_name("performance_500_spec.json")


@pytest.fixture()
def golden() -> dict:
    return json.loads(FIXTURE.read_text(encoding="ascii"))


@pytest.fixture()
def native_layout() -> dict:
    return json.loads(NATIVE_FIXTURE.read_text(encoding="ascii"))


@pytest.fixture()
def performance_spec() -> dict:
    return json.loads(PERFORMANCE_FIXTURE.read_text(encoding="ascii"))


def _identity_quaternion() -> dict:
    return {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}


def _yaw_quaternion(degrees: float) -> dict:
    half = math.radians(degrees) / 2.0
    return {
        "x": 0.0,
        "y": math.sin(half),
        "z": 0.0,
        "w": math.cos(half),
    }


def _placement(
    placement_id: str,
    asset_id: str,
    x: float,
    z: float,
    *,
    y: float = 0.0,
    quaternion: dict | None = None,
    metadata: dict | None = None,
    snap_relationship: dict | None = None,
) -> dict:
    return {
        "placementId": placement_id,
        "assetId": asset_id,
        "assetDefinitionRevision": "a" * 64,
        "transform": {
            "position": {"x": x, "y": y, "z": z},
            "quaternion": quaternion or _identity_quaternion(),
            "scale": 1,
        },
        "positionMode": "manual",
        "snapRelationship": snap_relationship,
        "metadata": metadata or {},
    }


def _asset(golden: dict, asset_id: str) -> dict:
    return next(
        deepcopy(item)
        for item in golden["assetDefinitions"]
        if item["assetId"] == asset_id
    )


def _box_asset(asset_id: str, width: float, depth: float, height: float) -> dict:
    half_width = width / 2.0
    half_depth = depth / 2.0
    footprint = [
        {"x": -half_width, "z": -half_depth},
        {"x": half_width, "z": -half_depth},
        {"x": half_width, "z": half_depth},
        {"x": -half_width, "z": half_depth},
    ]
    return {
        "assetId": asset_id,
        "category": "workstation",
        "coordinateFrame": {
            "allowedMountingSurfaces": ["floor"],
            "floorAnchor": {"x": 0, "y": 0, "z": 0},
        },
        "geometry": {
            "footprintPolygons": [footprint],
            "heightInterval": {"minimumY": 0, "maximumY": height},
        },
        "collision": {
            "geometry": {"footprintIndex": 0},
            "verticalInterval": {"minimumY": 0, "maximumY": height},
        },
        "clearances": [],
    }


def _layout_with_machine(
    golden: dict,
    x: float,
    z: float,
    *,
    y: float = 0.0,
    quaternion: dict | None = None,
) -> dict:
    layout = deepcopy(golden["baseLayout"])
    layout["placements"].append(
        _placement(
            "pl-machine",
            "asset-machine-golden",
            x,
            z,
            y=y,
            quaternion=quaternion,
        )
    )
    return layout


def _codes(result: dict, severity: str | None = None) -> list[str]:
    return [
        finding["code"]
        for finding in result["findings"]
        if severity is None or finding["severity"] == severity
    ]


def _evidence_record(
    evidence_id: str,
    *,
    valid_until: str | None = None,
    revoked_at: str | None = None,
) -> dict:
    return {
        "schemaVersion": 1,
        "documentKind": "evidence_record",
        "evidenceId": evidence_id,
        "tenantId": "tenant-p6",
        "subjectRef": {
            "documentKind": "industrial_asset_definition",
            "assetId": "asset-machine-golden",
        },
        "claimKey": "industrial_asset.loading.operating_mass",
        "valueFingerprint": "9" * 64,
        "status": "authored",
        "sourceRef": {
            "trustedSourceId": "source-p6-machine-spec",
            "sourceRevision": "8" * 64,
            "locator": "manufacturer/spec#operating-mass",
        },
        "assertedBy": "curator-p6",
        "assertedAt": "2026-07-01T00:00:00Z",
        "validFrom": "2026-07-01T00:00:00Z",
        "validUntil": valid_until,
        "revokedAt": revoked_at,
        "revocationReason": "Superseded" if revoked_at else None,
    }


def _contract_scale_layout(
    native_layout: dict,
    performance_spec: dict,
    asset: dict,
) -> dict:
    layout = deepcopy(native_layout)
    layout["layoutId"] = "fl-p6-performance-500"
    layout["displayName"] = "P6 500 Placement Performance Fixture"
    layout["zones"] = [
        {
            "zoneId": "zn-p6-performance",
            "zoneType": "workcell",
            "label": "Performance Workcell",
            "boundary": [
                {"x": -2.0, "z": -2.0},
                {"x": 104.0, "z": -2.0},
                {"x": 104.0, "z": 82.0},
                {"x": -2.0, "z": 82.0},
            ],
            "floorElevation": 0.0,
            "gridSpacing": 0.5,
            "allowedAssetCategories": [asset["category"]],
            "anchors": [],
            "evidence": [],
        }
    ]
    columns = performance_spec["grid"]["columns"]
    column_spacing = performance_spec["grid"]["columnSpacingMeters"]
    row_spacing = performance_spec["grid"]["rowSpacingMeters"]
    layout["placements"] = [
        _placement(
            f"pl-perf-{index:04d}",
            asset["assetId"],
            (index % columns) * column_spacing,
            (index // columns) * row_spacing,
        )
        for index in range(performance_spec["placementCount"])
    ]
    return layout


def _record(
    record_id: str,
    owner_id: str,
    minimum_x: float,
    minimum_z: float,
    maximum_x: float,
    maximum_z: float,
    *,
    minimum_y: float = 0.0,
    maximum_y: float = 1.0,
) -> SpatialRecord:
    return SpatialRecord(
        record_id=record_id,
        owner_id=owner_id,
        asset_id=f"asset-{owner_id}",
        polygon=(
            (minimum_x, minimum_z),
            (maximum_x, minimum_z),
            (maximum_x, maximum_z),
            (minimum_x, maximum_z),
        ),
        minimum_y=minimum_y,
        maximum_y=maximum_y,
    )


def test_stable_finding_id_is_order_independent() -> None:
    left = stable_finding_id(
        "placement_collision",
        subject_refs=("pl-b", "pl-a", "pl-b"),
        details={"z": 2, "a": {"y": 1}},
    )
    right = stable_finding_id(
        "placement_collision",
        subject_refs=("pl-a", "pl-b"),
        details={"a": {"y": 1}, "z": 2},
    )
    assert left == right
    assert left.startswith("fsf-")
    assert len(left) == 28


def test_p6_fixture_is_a_canonical_native_facility_layout(
    native_layout: dict,
) -> None:
    assert validate_layout(native_layout, require_canonical=True) is native_layout


def test_stable_candidate_id_is_canonical() -> None:
    arguments = {
        "layout_fingerprint": "a" * 64,
        "obstacle_fingerprint": "b" * 64,
        "asset_id": "asset-a",
        "asset_definition_revision": "c" * 64,
        "family": "grid",
        "transform": {
            "position": {"z": 2.0, "x": 1.0, "y": 0.0},
            "quaternion": _identity_quaternion(),
            "scale": 1,
        },
        "snap_relationship": {"gridSpacing": 0.5, "family": "grid"},
    }
    first = stable_candidate_id(**arguments)
    arguments["transform"] = {
        "scale": 1,
        "quaternion": {"w": 1.0, "z": 0.0, "y": 0.0, "x": 0.0},
        "position": {"x": 1, "y": 0, "z": 2},
    }
    assert stable_candidate_id(**arguments) == first
    assert first.startswith("fsc-")


def test_findings_sort_by_severity_code_and_identity() -> None:
    findings = [
        {
            "findingId": "fsf-warning",
            "severity": "warning",
            "code": "z",
            "subjectRefs": [],
        },
        {
            "findingId": "fsf-error-b",
            "severity": "error",
            "code": "b",
            "subjectRefs": [],
        },
        {
            "findingId": "fsf-unverified",
            "severity": "unverified",
            "code": "a",
            "subjectRefs": [],
        },
        {
            "findingId": "fsf-error-a",
            "severity": "error",
            "code": "a",
            "subjectRefs": [],
        },
    ]
    assert [item["findingId"] for item in sort_findings(reversed(findings))] == [
        "fsf-error-a",
        "fsf-error-b",
        "fsf-unverified",
        "fsf-warning",
    ]


def test_polygon_primitives_cover_boundary_concavity_and_separation() -> None:
    square = ((0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0))
    interior = ((1.0, 1.0), (2.0, 1.0), (2.0, 2.0), (1.0, 2.0))
    touching = ((4.0, 1.0), (5.0, 1.0), (5.0, 2.0), (4.0, 2.0))
    separate = ((5.1, 1.0), (6.0, 1.0), (6.0, 2.0), (5.1, 2.0))
    concave_u = (
        (0.0, 0.0),
        (4.0, 0.0),
        (4.0, 4.0),
        (3.0, 4.0),
        (3.0, 1.0),
        (1.0, 1.0),
        (1.0, 4.0),
        (0.0, 4.0),
    )
    bridges_concavity = (
        (0.5, 3.0),
        (3.5, 3.0),
        (3.5, 3.5),
        (0.5, 3.5),
    )
    assert point_in_polygon((0.0, 2.0), square)
    assert polygon_contains_polygon(square, interior)
    assert all(point_in_polygon(point, concave_u) for point in bridges_concavity)
    assert not polygon_contains_polygon(concave_u, bridges_concavity)
    assert polygons_intersect(square, touching)
    assert not polygons_intersect(square, separate)


def test_oriented_box_polygon_intersects_after_rotation() -> None:
    horizontal = oriented_box_polygon((0.0, 0.0), (2.0, 0.25), 0.0)
    vertical = oriented_box_polygon((0.0, 0.0), (2.0, 0.25), math.pi / 2.0)
    distant = oriented_box_polygon((5.0, 5.0), (1.0, 1.0), math.pi / 4.0)
    assert polygons_intersect(horizontal, vertical)
    assert not polygons_intersect(horizontal, distant)


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ((0.0, 1.0), (0.5, 2.0), True),
        ((0.0, 1.0), (1.0, 2.0), True),
        ((0.0, 0.9), (1.0, 2.0), False),
    ],
)
def test_height_interval_boundary_conditions(left, right, expected) -> None:
    assert height_intervals_intersect(left, right) is expected


def test_placement_geometry_applies_yaw_and_world_translation(golden: dict) -> None:
    asset = _asset(golden, "asset-machine-golden")
    placement = _placement(
        "pl-rotated",
        asset["assetId"],
        10.0,
        4.0,
        quaternion=_yaw_quaternion(90),
    )
    records = placement_spatial_records(placement, asset)
    assert len(records) == 1
    assert records[0].bounds == pytest.approx((9.0, 3.0, 11.0, 5.0))
    assert records[0].interval == pytest.approx((0.0, 2.0))


def test_tilted_placement_uses_conservative_projected_hull(golden: dict) -> None:
    asset = _asset(golden, "asset-machine-golden")
    half = math.radians(45) / 2.0
    placement = _placement(
        "pl-tilted",
        asset["assetId"],
        0.0,
        0.0,
        quaternion={"x": math.sin(half), "y": 0.0, "z": 0.0, "w": math.cos(half)},
    )
    record = placement_spatial_records(placement, asset)[0]
    assert record.maximum_y > 2.0
    assert record.bounds[3] > 1.0


def test_obb_only_asset_supplies_footprint_and_height_interval() -> None:
    asset = {
        "assetId": "asset-obb-only",
        "geometry": {
            "obb": {
                "center": {"x": 1.0, "y": 0.75, "z": -2.0},
                "halfExtents": {"x": 2.0, "y": 0.75, "z": 0.5},
                "yawRadians": 0.0,
            }
        },
    }
    placement = _placement(
        "pl-obb-only",
        asset["assetId"],
        10.0,
        20.0,
        y=2.0,
    )
    records = placement_spatial_records(placement, asset)
    assert len(records) == 1
    assert records[0].bounds == pytest.approx((9.0, 17.5, 13.0, 18.5))
    assert records[0].interval == pytest.approx((2.0, 3.5))


def test_same_asset_id_resolves_each_exact_definition_revision() -> None:
    small_revision = "1" * 64
    large_revision = "2" * 64
    small = {
        "assetId": "asset-revisioned",
        "assetDefinitionRevision": small_revision,
        "category": "machine",
        "geometry": {
            "footprintPolygons": [[
                {"x": -0.5, "z": -0.5},
                {"x": 0.5, "z": -0.5},
                {"x": 0.5, "z": 0.5},
                {"x": -0.5, "z": 0.5},
            ]],
            "heightInterval": {"minimumY": 0, "maximumY": 1},
        },
        "clearances": [],
    }
    large = deepcopy(small)
    large["assetDefinitionRevision"] = large_revision
    large["geometry"]["footprintPolygons"] = [[
        {"x": -2.5, "z": -2.5},
        {"x": 2.5, "z": -2.5},
        {"x": 2.5, "z": 2.5},
        {"x": -2.5, "z": 2.5},
    ]]
    first = _placement("pl-small", "asset-revisioned", 0, 0)
    first["assetDefinitionRevision"] = small_revision
    second = _placement("pl-large", "asset-revisioned", 3, 0)
    second["assetDefinitionRevision"] = large_revision
    layout = {"placements": [first, second], "zones": []}

    result = diagnose_layout(layout, [large, small])

    assert result["metrics"]["placementCollisions"] == 1
    assert "placement_collision" in _codes(result, "error")


def test_uniform_grid_matches_fixed_brute_force_oracle() -> None:
    records = (
        _record("r-a", "pl-a", -2, -1, 1, 1),
        _record("r-b", "pl-b", 5, 4, 7, 8),
        _record("r-c", "pl-c", -8, 6, -4, 9),
    )
    index = UniformGridSpatialIndex(records, cell_size=2.5)
    for bounds in ((-3, -2, 2, 2), (6, 6, 9, 9), (-20, -20, 20, 20)):
        assert index.query(bounds) == brute_force_query(records, bounds)


def test_uniform_grid_matches_seeded_randomized_brute_force_oracle() -> None:
    generator = random.Random(602024)
    for round_index in range(40):
        records = []
        for index in range(120):
            x = generator.uniform(-100.0, 100.0)
            z = generator.uniform(-100.0, 100.0)
            width = generator.uniform(0.05, 12.0)
            depth = generator.uniform(0.05, 12.0)
            records.append(
                _record(
                    f"r-{round_index:02d}-{index:03d}",
                    f"pl-{round_index:02d}-{index:03d}",
                    x,
                    z,
                    x + width,
                    z + depth,
                )
            )
        index = UniformGridSpatialIndex(
            records,
            cell_size=generator.uniform(0.5, 15.0),
        )
        for _ in range(30):
            x = generator.uniform(-120.0, 120.0)
            z = generator.uniform(-120.0, 120.0)
            bounds = (
                x,
                z,
                x + generator.uniform(0.01, 35.0),
                z + generator.uniform(0.01, 35.0),
            )
            assert index.query(bounds) == brute_force_query(records, bounds)


def test_uniform_grid_owner_ignore_matches_oracle() -> None:
    records = (
        _record("r-a-1", "pl-a", 0, 0, 1, 1),
        _record("r-a-2", "pl-a", 1, 0, 2, 1),
        _record("r-b", "pl-b", 0, 0, 1, 1),
    )
    index = UniformGridSpatialIndex(records, cell_size=1)
    bounds = (-1, -1, 3, 3)
    assert index.query(bounds, ignore_owner_ids=("pl-a",)) == brute_force_query(
        records,
        bounds,
        ignore_owner_ids=("pl-a",),
    ) == ("r-b",)


def test_physical_collision_is_an_error(golden: dict) -> None:
    result = diagnose_layout(
        _layout_with_machine(golden, 5.5, 5.0),
        golden["assetDefinitions"],
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
    )
    assert "placement_collision" in _codes(result, "error")
    assert result["metrics"]["placementCollisions"] == 1
    assert result["safe"] is False
    assert result["safetyStatus"] == "unsafe"


def test_same_plan_footprint_at_separate_heights_has_no_narrow_collision(
    golden: dict,
) -> None:
    asset = _asset(golden, "asset-machine-golden")
    lower = placement_spatial_records(
        _placement("pl-low", asset["assetId"], 0, 0),
        asset,
    )[0]
    upper = placement_spatial_records(
        _placement("pl-high", asset["assetId"], 0, 0, y=3.0),
        asset,
    )[0]
    assert polygons_intersect(lower.polygon, upper.polygon)
    assert not height_intervals_intersect(lower.interval, upper.interval)


def test_declared_vertical_stack_allows_support_contact_but_stays_unverified(
    golden: dict,
) -> None:
    layout = deepcopy(golden["baseLayout"])
    relationship = {
        "family": "vertical_stack",
        "stackId": "stack-machine-a",
        "count": 3,
        "gapMeters": 0,
        "itemHeightMeters": 2,
        "evidenceStatus": "unverified",
    }
    for level, y in enumerate((0.0, 2.0, 4.0)):
        layout["placements"].append(
            _placement(
                f"pl-stack-{level}",
                "asset-machine-golden",
                2.0,
                5.0,
                y=y,
                snap_relationship={**relationship, "level": level},
            )
        )
    assets = deepcopy(golden["assetDefinitions"])
    for asset in assets:
        if asset["assetId"] == "asset-machine-golden":
            asset["clearances"] = []
    result = diagnose_layout(
        layout,
        assets,
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
    )
    assert "placement_collision" not in _codes(result, "error")
    assert "invalid_vertical_stack" not in _codes(result, "error")
    assert "vertical_stack_safety_unverified" in _codes(result, "unverified")
    assert result["valid"] is True
    assert result["safe"] is False


def test_misaligned_vertical_stack_fails_closed(golden: dict) -> None:
    layout = deepcopy(golden["baseLayout"])
    relationship = {
        "family": "vertical_stack",
        "stackId": "stack-machine-b",
        "count": 2,
        "gapMeters": 0,
        "itemHeightMeters": 2,
        "evidenceStatus": "unverified",
    }
    layout["placements"].extend([
        _placement(
            "pl-stack-base", "asset-machine-golden", 2.0, 5.0,
            snap_relationship={**relationship, "level": 0},
        ),
        _placement(
            "pl-stack-bad", "asset-machine-golden", 2.1, 5.0, y=2.0,
            snap_relationship={**relationship, "level": 1},
        ),
    ])
    result = diagnose_layout(
        layout,
        golden["assetDefinitions"],
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
    )
    assert "invalid_vertical_stack" in _codes(result, "error")
    assert result["valid"] is False


def _surface_relationship(
    support_id: str,
    local_x: float,
    local_z: float,
    *,
    side: str = "above",
    surface_id: str = "derived-top",
    surface_source: str = "derived_aabb",
    local_rotation: float = 0,
) -> dict:
    return {
        "family": "surface_attachment",
        "attachmentId": "surface-table-worktop",
        "supportPlacementId": support_id,
        "surfaceId": surface_id,
        "side": side,
        "localPosition": {"x": local_x, "z": local_z},
        "localRotationDegrees": local_rotation,
        "normalOffsetMeters": 0,
        "surfaceSource": surface_source,
        "evidenceStatus": "unverified",
    }


def test_surface_support_holds_three_distinct_items_without_false_collision(
    golden: dict,
) -> None:
    layout = deepcopy(golden["baseLayout"])
    layout["zones"] = []
    layout["placements"] = [
        _placement("pl-table", "asset-table", 0, 0),
        _placement(
            "pl-computer",
            "asset-computer",
            -1,
            0,
            y=0.8,
            snap_relationship=_surface_relationship("pl-table", -1, 0),
        ),
        _placement(
            "pl-keyboard",
            "asset-keyboard",
            0,
            0,
            y=0.8,
            snap_relationship=_surface_relationship("pl-table", 0, 0),
        ),
        _placement(
            "pl-mouse",
            "asset-mouse",
            1,
            0,
            y=0.8,
            snap_relationship=_surface_relationship("pl-table", 1, 0),
        ),
    ]
    assets = [
        _box_asset("asset-table", 4, 3, 0.8),
        _box_asset("asset-computer", 0.5, 0.5, 0.5),
        _box_asset("asset-keyboard", 0.6, 0.25, 0.05),
        _box_asset("asset-mouse", 0.15, 0.1, 0.05),
    ]
    result = diagnose_layout(layout, assets)
    assert "invalid_surface_attachment" not in _codes(result, "error")
    assert "placement_collision" not in _codes(result, "error")
    assert _codes(result, "unverified").count(
        "surface_attachment_safety_unverified"
    ) == 3


def test_surface_attachment_outside_support_footprint_fails_closed(
    golden: dict,
) -> None:
    layout = deepcopy(golden["baseLayout"])
    layout["zones"] = []
    layout["placements"] = [
        _placement("pl-table", "asset-table", 0, 0),
        _placement(
            "pl-device",
            "asset-device",
            1.9,
            0,
            y=0.8,
            snap_relationship=_surface_relationship("pl-table", 1.9, 0),
        ),
    ]
    result = diagnose_layout(
        layout,
        [
            _box_asset("asset-table", 4, 3, 0.8),
            _box_asset("asset-device", 0.5, 0.5, 0.5),
        ],
    )
    assert "invalid_surface_attachment" in _codes(result, "error")
    assert result["valid"] is False


def _named_worktop_asset(*, allowed_sides: list[str] | None = None) -> dict:
    asset = _box_asset("asset-tall-workstation", 4, 3, 2)
    asset["supportSurfaces"] = [{
        "surfaceId": "worktop",
        "label": "Worktop",
        "localFrame": {
            "origin": {"x": 0, "y": 0.8, "z": 0},
            "xAxis": {"x": 1, "y": 0, "z": 0},
            "zAxis": {"x": 0, "y": 0, "z": 1},
            "normal": {"x": 0, "y": 1, "z": 0},
        },
        "bounds": {
            "minimumX": -1.5,
            "maximumX": 1.5,
            "minimumZ": -1,
            "maximumZ": 1,
        },
        "allowedSides": allowed_sides or ["above", "below"],
        "evidenceStatus": "derived",
    }]
    return asset


def test_named_surface_uses_authored_elevation_below_asset_top(
    golden: dict,
) -> None:
    layout = deepcopy(golden["baseLayout"])
    layout["zones"] = []
    layout["placements"] = [
        _placement("pl-support", "asset-tall-workstation", 0, 0),
        _placement(
            "pl-device",
            "asset-device",
            0,
            0,
            y=0.8,
            snap_relationship=_surface_relationship(
                "pl-support",
                0,
                0,
                surface_id="worktop",
                surface_source="asset_definition",
            ),
        ),
    ]
    result = diagnose_layout(
        layout,
        [
            _named_worktop_asset(),
            _box_asset("asset-device", 0.5, 0.5, 0.25),
        ],
    )
    assert "invalid_surface_attachment" not in _codes(result, "error")
    assert "surface_attachment_safety_unverified" in _codes(
        result,
        "unverified",
    )
    assert result["valid"] is True


def test_named_surface_accepts_a_rotated_horizontal_local_frame(
    golden: dict,
) -> None:
    support_asset = _named_worktop_asset()
    surface = support_asset["supportSurfaces"][0]
    surface["localFrame"] = {
        "origin": {"x": 0.5, "y": 0.8, "z": -0.25},
        "xAxis": {"x": 0, "y": 0, "z": -1},
        "zAxis": {"x": 1, "y": 0, "z": 0},
        "normal": {"x": 0, "y": 1, "z": 0},
    }
    surface["bounds"] = {
        "minimumX": -0.6,
        "maximumX": 0.6,
        "minimumZ": -0.3,
        "maximumZ": 0.3,
    }
    layout = deepcopy(golden["baseLayout"])
    layout["zones"] = []
    layout["placements"] = [
        _placement("pl-support", "asset-tall-workstation", 10, 8),
        _placement(
            "pl-device",
            "asset-device",
            10.35,
            8.1,
            y=0.8,
            quaternion=_yaw_quaternion(90),
            snap_relationship=_surface_relationship(
                "pl-support",
                0.35,
                0.1,
                surface_id="worktop",
                surface_source="asset_definition",
                local_rotation=90,
            ),
        ),
    ]
    result = diagnose_layout(
        layout,
        [support_asset, _box_asset("asset-device", 0.4, 0.2, 0.25)],
    )
    assert "invalid_surface_attachment" not in _codes(result, "error")
    assert result["valid"] is True


def test_named_surface_missing_from_bound_asset_revision_fails_closed(
    golden: dict,
) -> None:
    layout = deepcopy(golden["baseLayout"])
    layout["zones"] = []
    layout["placements"] = [
        _placement("pl-support", "asset-tall-workstation", 0, 0),
        _placement(
            "pl-device",
            "asset-device",
            0,
            0,
            y=0.8,
            snap_relationship=_surface_relationship(
                "pl-support",
                0,
                0,
                surface_id="missing-worktop",
                surface_source="asset_definition",
            ),
        ),
    ]
    result = diagnose_layout(
        layout,
        [
            _named_worktop_asset(),
            _box_asset("asset-device", 0.5, 0.5, 0.25),
        ],
    )
    assert "invalid_surface_attachment" in _codes(result, "error")
    assert result["valid"] is False


def test_named_surface_forbidden_side_fails_closed(golden: dict) -> None:
    layout = deepcopy(golden["baseLayout"])
    layout["zones"] = []
    layout["placements"] = [
        _placement("pl-support", "asset-tall-workstation", 0, 0),
        _placement(
            "pl-device",
            "asset-device",
            0,
            0,
            y=0.55,
            snap_relationship=_surface_relationship(
                "pl-support",
                0,
                0,
                side="below",
                surface_id="worktop",
                surface_source="asset_definition",
            ),
        ),
    ]
    result = diagnose_layout(
        layout,
        [
            _named_worktop_asset(allowed_sides=["above"]),
            _box_asset("asset-device", 0.5, 0.5, 0.25),
        ],
    )
    assert "invalid_surface_attachment" in _codes(result, "error")
    assert result["valid"] is False


def test_surface_attachment_cycle_fails_closed(golden: dict) -> None:
    layout = deepcopy(golden["baseLayout"])
    layout["zones"] = []
    layout["placements"] = [
        _placement(
            "pl-a",
            "asset-a",
            0,
            0,
            y=0.5,
            snap_relationship=_surface_relationship("pl-b", 0, 0),
        ),
        _placement(
            "pl-b",
            "asset-b",
            0,
            0,
            y=0.5,
            snap_relationship=_surface_relationship("pl-a", 0, 0),
        ),
    ]
    result = diagnose_layout(
        layout,
        [
            _box_asset("asset-a", 1, 1, 0.5),
            _box_asset("asset-b", 1, 1, 0.5),
        ],
    )
    assert "invalid_surface_attachment" in _codes(result, "error")
    assert result["valid"] is False


def test_touching_physical_boundaries_are_conservatively_collisions(
    golden: dict,
) -> None:
    result = diagnose_layout(
        _layout_with_machine(golden, 4.0, 5.0),
        golden["assetDefinitions"],
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
    )
    assert "placement_collision" in _codes(result, "error")


def test_golden_valid_layout_is_safe_with_authoritative_evidence(golden: dict) -> None:
    result = diagnose_layout(
        _layout_with_machine(golden, 2.0, 5.0),
        golden["assetDefinitions"],
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
    )
    assert result["valid"] is True
    assert result["safe"] is True
    assert result["safetyStatus"] == "safe"
    assert result["metrics"]["errorCount"] == 0
    assert result["metrics"]["unverifiedCount"] == 0


def test_zone_containment_violation_is_deterministic(golden: dict) -> None:
    result = diagnose_layout(
        _layout_with_machine(golden, 20.5, 5.0),
        golden["assetDefinitions"],
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
    )
    assert "zone_containment_violation" in _codes(result, "error")
    assert "placement_outside_floor" in _codes(result, "error")
    assert result == diagnose_layout(
        _layout_with_machine(golden, 20.5, 5.0),
        list(reversed(golden["assetDefinitions"])),
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=dict(reversed(list(golden["authority"].items()))),
    )


def test_zone_category_incompatibility_is_enforced(golden: dict) -> None:
    layout = _layout_with_machine(golden, 2.0, 5.0)
    layout["zones"][0]["allowedAssetCategories"] = ["rack"]
    result = diagnose_layout(
        layout,
        golden["assetDefinitions"],
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
    )
    assert "zone_kind_incompatible" in _codes(result, "error")


def test_exclusion_zone_rejects_contained_placement(golden: dict) -> None:
    layout = _layout_with_machine(golden, 2.0, 5.0)
    layout["zones"].append(
        {
            "zoneId": "zn-machine-exclusion",
            "zoneType": "exclusion",
            "label": "Machine keep-out",
            "boundary": [
                {"x": 0.5, "z": 3.5},
                {"x": 3.5, "z": 3.5},
                {"x": 3.5, "z": 6.5},
                {"x": 0.5, "z": 6.5},
            ],
            "floorElevation": 0.0,
            "anchors": [],
            "evidence": ["ev-exclusion-zone"],
        }
    )
    authority = dict(golden["authority"])
    authority["ev-exclusion-zone"] = {
        "authoritative": True,
        "blockers": [],
        "current": True,
        "status": "authored",
    }

    result = diagnose_layout(
        layout,
        golden["assetDefinitions"],
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=authority,
    )

    prohibited = [
        item
        for item in result["findings"]
        if item["code"] == "exclusion_zone_violation"
        and item.get("details", {}).get("reason") == "prohibited_zone"
    ]
    assert prohibited
    assert result["safe"] is False
    assert result["safetyStatus"] == "unsafe"


def test_shell_fixed_obstacle_rejects_overlap(golden: dict) -> None:
    shell = deepcopy(golden["shell"])
    shell["features"].append(
        {
            "featureId": "shell-fixed-column",
            "featureKind": "fixed_obstacle",
            "geometry": {
                "boundary": [
                    {"x": 1.25, "z": 4.25},
                    {"x": 2.75, "z": 4.25},
                    {"x": 2.75, "z": 5.75},
                    {"x": 1.25, "z": 5.75},
                ],
                "heightInterval": {
                    "minimumY": 0.0,
                    "maximumY": 4.0,
                },
            },
            "evidence": ["ev-shell-fixed-column"],
        }
    )
    authority = dict(golden["authority"])
    authority["ev-shell-fixed-column"] = {
        "authoritative": True,
        "blockers": [],
        "current": True,
        "status": "derived",
    }

    result = diagnose_layout(
        _layout_with_machine(golden, 2.0, 5.0),
        golden["assetDefinitions"],
        shell=shell,
        policy_set=golden["policySet"],
        evidence_authority=authority,
    )

    shell_collisions = [
        item
        for item in result["findings"]
        if item["code"] == "shell_obstacle_collision"
        and item.get("details", {}).get("shellFeatureId")
        == "shell-fixed-column"
    ]
    assert shell_collisions
    assert result["safe"] is False
    assert result["safetyStatus"] == "unsafe"


def test_zone_height_limit_uses_world_vertical_interval(golden: dict) -> None:
    layout = _layout_with_machine(golden, 2.0, 5.0)
    layout["zones"][0]["heightLimit"] = 1.0
    result = diagnose_layout(
        layout,
        golden["assetDefinitions"],
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
    )
    height_findings = [
        item
        for item in result["findings"]
        if item["code"] == "zone_containment_violation"
        and item["details"].get("reason") == "height_limit"
    ]
    assert height_findings


def test_asset_rejects_unsupported_mounting_surface(golden: dict) -> None:
    layout = deepcopy(golden["baseLayout"])
    layout["placements"][0]["metadata"] = {
        "mountingSurfaceRef": {
            "surfaceKind": "foundation",
            "featureId": "shell-foundation-golden",
        }
    }
    layout["placements"][0]["transform"]["position"] = {"x": 15, "y": 0, "z": 15}
    result = diagnose_layout(
        layout,
        golden["assetDefinitions"],
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
    )
    assert "unsupported_mounting_surface" in _codes(result, "error")


def test_missing_shell_mounting_geometry_is_unverified(golden: dict) -> None:
    result = diagnose_layout(
        _layout_with_machine(golden, 2.0, 5.0),
        golden["assetDefinitions"],
        shell=None,
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
    )
    assert "unsupported_mounting_surface" in _codes(result, "unverified")
    assert result["safe"] is False
    assert result["safetyStatus"] == "unverified"


def test_floor_load_exceeded_requires_authoritative_inputs(golden: dict) -> None:
    layout = _layout_with_machine(golden, 2.0, 5.0)
    layout["zones"][0]["loadLimit"]["maximumKgPerSquareMeter"] = 500.0
    result = diagnose_layout(
        layout,
        golden["assetDefinitions"],
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
    )
    assert "floor_load_exceeded" in _codes(result, "error")


def test_semantic_aisle_reports_obstruction_and_unverified_clearance(
    golden: dict,
) -> None:
    layout = _layout_with_machine(golden, 2.0, 5.0)
    layout["routes"] = [{
        "routeId": "rt-main-forklift",
        "label": "Main Forklift Boulevard",
        "routeKind": "forklift",
        "sourceEndpoint": {
            "kind": "world_point",
            "position": {"x": 0.0, "y": 0.0, "z": 5.0},
        },
        "targetEndpoint": {
            "kind": "world_point",
            "position": {"x": 6.0, "y": 0.0, "z": 5.0},
        },
        "routingMode": "vehicle",
        "centerline": [
            {"x": 0.0, "y": 0.0, "z": 5.0},
            {"x": 6.0, "y": 0.0, "z": 5.0},
        ],
        "corridorWidth": 2.0,
        "routeFingerprint": "7" * 64,
        "sourceRevisions": {"layoutBaseRevision": "8" * 64},
        "requirements": [],
        "evidence": [],
        "extensions": {
            "facilityAisle": {
                "schemaVersion": 1,
                "aisleKind": "forklift",
                "direction": "two_way",
                "color": "#d9a514",
                "clearanceEvidenceStatus": "unverified",
            },
        },
    }]

    result = diagnose_layout(layout, golden["assetDefinitions"])

    assert "aisle_obstructed" in _codes(result, "warning")
    assert "aisle_clearance_unverified" in _codes(result, "unverified")
    assert result["metrics"]["aisleCount"] == 1
    assert result["metrics"]["obstructedAisleCount"] == 1
    assert result["metrics"]["aisleClearanceUnverifiedCount"] == 1


_FLOOR_CHECK_CODES = {
    "aisle_obstructed",
    "exclusion_zone_violation",
    "floor_load_unverified",
    "placement_outside_floor",
    "unsupported_mounting_surface",
    "zone_containment_violation",
}


def _roof_beam_layout(golden: dict, beam_y: float) -> tuple[dict, list[dict]]:
    """A 30 m beam spanning past the cell and the floor, over a forklift aisle."""
    layout = deepcopy(golden["baseLayout"])
    layout["placements"].append(
        _placement("pl-beam", "asset-roof-beam", 10.0, 10.0, y=beam_y)
    )
    layout["routes"] = [{
        "routeId": "rt-under-beam",
        "label": "Under Beam Aisle",
        "routeKind": "forklift",
        "centerline": [
            {"x": 0.0, "y": 0.0, "z": 10.0},
            {"x": 20.0, "y": 0.0, "z": 10.0},
        ],
        "corridorWidth": 2.0,
        "evidence": [],
        "extensions": {"facilityAisle": {"aisleKind": "forklift"}},
    }]
    assets = [
        *golden["assetDefinitions"],
        _box_asset("asset-roof-beam", 30.0, 0.4, 0.5),
        _box_asset("asset-tall-rack", 1.0, 1.0, 7.0),
    ]
    return layout, assets


def _beam_codes(result: dict) -> set[str]:
    return {
        finding["code"]
        for finding in result["findings"]
        if "pl-beam" in finding["subjectRefs"]
    }


def test_overhead_placement_skips_floor_checks_but_keeps_collisions(
    golden: dict,
) -> None:
    layout, assets = _roof_beam_layout(golden, 6.0)
    result = diagnose_layout(
        layout,
        assets,
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
    )
    assert not _beam_codes(result) & _FLOOR_CHECK_CODES
    assert result["zoneMembership"]["pl-beam"] == []
    assert result["metrics"]["obstructedAisleCount"] == 0

    layout["placements"].append(
        _placement("pl-rack", "asset-tall-rack", 10.0, 10.0)
    )
    result = diagnose_layout(
        layout,
        assets,
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
    )
    assert "placement_collision" in _beam_codes(result)


def test_placement_below_overhead_clearance_keeps_floor_checks(
    golden: dict,
) -> None:
    layout, assets = _roof_beam_layout(golden, 3.0)
    result = diagnose_layout(
        layout,
        assets,
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
    )
    assert {"aisle_obstructed", "zone_containment_violation"} <= _beam_codes(result)


def _aisle_doorway_scene(
    minimum_x: float = 7.0,
    width: float = 3.0,
    *,
    yaw_degrees: float = 0.0,
    intrusion: float = 0.0,
) -> tuple[dict, dict]:
    angle = math.radians(yaw_degrees)

    def point(x: float, z: float) -> dict:
        return {
            "x": x * math.cos(angle) - z * math.sin(angle),
            "z": x * math.sin(angle) + z * math.cos(angle),
        }

    layout = {"placements": [], "routes": [{
        "routeId": "rt-doorway",
        "corridorWidth": width,
        "centerline": [point(minimum_x + width / 2, 0),
                       point(minimum_x + width / 2, 8.5)],
        "extensions": {"facilityAisle": {
            "clearanceEvidenceStatus": "unverified",
        }},
    }]}
    shell = {"features": [
        {
            "featureId": feature_id,
            "featureKind": "wall",
            "geometry": {"boundary": [
                point(low, -0.15), point(high, -0.15),
                point(high, 0.15), point(low, 0.15),
            ], "height": 3.0},
        }
        for feature_id, low, high in (
            ("wall-left", 0.0, minimum_x + intrusion),
            ("wall-right", minimum_x + width, 26.0),
        )
    ]}
    return layout, shell


@pytest.mark.parametrize(("minimum_x", "width"), [(7.0, 3.0), (22.0, 1.5)])
@pytest.mark.parametrize("yaw_degrees", [0.0, 33.0, 90.0])
@pytest.mark.parametrize("reverse", [False, True])
def test_aisle_exact_doorway_boundary_contact_is_not_obstructed(
    minimum_x: float, width: float, yaw_degrees: float, reverse: bool,
) -> None:
    layout, shell = _aisle_doorway_scene(minimum_x, width, yaw_degrees=yaw_degrees)
    if reverse:
        layout["routes"][0]["centerline"].reverse()
        for feature in shell["features"]:
            feature["geometry"]["boundary"].reverse()
    before = deepcopy((layout, shell))

    result = diagnose_layout(layout, [], shell=shell)

    assert "aisle_shell_obstructed" not in _codes(result)
    assert result["metrics"]["obstructedAisleCount"] == 0
    assert result["metrics"]["aisleCount"] == 1
    assert result["metrics"]["aisleClearanceUnverifiedCount"] == 1
    assert "aisle_clearance_unverified" in _codes(result, "unverified")
    assert result["safe"] is False
    assert (layout, shell) == before
    assert diagnose_layout(layout, [], shell=shell) == result


@pytest.mark.parametrize("yaw_degrees", [0.0, 33.0])
@pytest.mark.parametrize(("intrusion", "blocked"), [
    (-1.0e-6, False),
    (-GEOMETRY_EPSILON / 2, False),
    (0.0, False),
    (GEOMETRY_EPSILON / 2, False),
    (2 * GEOMETRY_EPSILON, True),
    (1.0e-6, True),
    (0.05, True),
])
def test_aisle_wall_contact_tolerance_preserves_positive_overlap(
    yaw_degrees: float, intrusion: float, blocked: bool,
) -> None:
    layout, shell = _aisle_doorway_scene(yaw_degrees=yaw_degrees, intrusion=intrusion)

    result = diagnose_layout(layout, [], shell=shell)

    hits = [item for item in result["findings"] if item["code"] == "aisle_shell_obstructed"]
    assert len(hits) == int(blocked)
    assert result["metrics"]["obstructedAisleCount"] == int(blocked)
    if blocked:
        assert hits[0]["severity"] == "warning"
        assert hits[0]["details"] == {
            "shellFeatureId": "wall-left", "segmentIndexes": [0], "corridorWidth": 3.0,
        }


@pytest.mark.parametrize(("boundary", "blocked"), [
    pytest.param([(5, 3), (7, 4), (5, 5)], False, id="corner-contact"),
    pytest.param([(9, 9.5), (11, 7.5), (12, 10.5)], False, id="diagonal-corner-contact"),
    pytest.param([(8, 2), (9, 2), (9, 3), (8, 3)], True, id="contained-wall"),
    pytest.param([(8, 1), (8 + GEOMETRY_EPSILON / 2, 1),
                  (8 + GEOMETRY_EPSILON / 2, 7), (8, 7)],
                 True, id="thin-contained-wall"),
    pytest.param([(7, 0), (10, 0), (10, 8.5), (7, 8.5)], True, id="coincident"),
    pytest.param([(5, 3), (12, 3), (12, 4), (5, 4)], True, id="crossing-edges"),
    pytest.param([(5, 1), (7.25, 1), (7.25, 2), (6, 2), (6, 7), (5, 7)],
                 True, id="concave-intrusion"),
])
def test_aisle_wall_contact_checks_polygon_interiors(
    boundary: list[tuple[float, float]], blocked: bool,
) -> None:
    layout, shell = _aisle_doorway_scene()
    shell["features"] = shell["features"][:1]
    shell["features"][0]["geometry"]["boundary"] = [
        {"x": x, "z": z} for x, z in boundary
    ]

    result = diagnose_layout(layout, [], shell=shell)

    assert ("aisle_shell_obstructed" in _codes(result)) is blocked
    assert result["metrics"]["obstructedAisleCount"] == int(blocked)


@pytest.mark.parametrize("feature_kind", ["column", "door", "fixed_obstacle"])
def test_aisle_non_wall_shell_contact_still_obstructs(feature_kind: str) -> None:
    layout, shell = _aisle_doorway_scene()
    shell["features"][0]["featureKind"] = feature_kind

    result = diagnose_layout(layout, [], shell=shell)

    hits = [item for item in result["findings"] if item["code"] == "aisle_shell_obstructed"]
    assert [item["details"]["shellFeatureId"] for item in hits] == ["wall-left"]
    assert result["metrics"]["obstructedAisleCount"] == 1


def test_aisle_wall_contact_exception_keeps_placement_wall_collisions() -> None:
    layout, shell = _aisle_doorway_scene()
    asset = _box_asset("asset-doorway", 3.0, 1.0, 1.0)
    layout["placements"] = [_placement("pl-doorway", asset["assetId"], 8.5, 0.0)]

    result = diagnose_layout(layout, [asset], shell=shell)

    assert "aisle_shell_obstructed" not in _codes(result)
    assert "aisle_obstructed" in _codes(result, "warning")
    assert "shell_obstacle_collision" in _codes(result, "error")
    assert result["metrics"]["shellObstacleCollisions"] == 2
    assert result["valid"] is False


def test_aisle_wall_contact_exception_keeps_placement_aisle_contact() -> None:
    layout, shell = _aisle_doorway_scene()
    asset = _box_asset("asset-touching", 1.0, 1.0, 1.0)
    layout["placements"] = [_placement("pl-touching", asset["assetId"], 10.5, 4.0)]

    result = diagnose_layout(layout, [asset], shell=shell)

    assert "aisle_shell_obstructed" not in _codes(result)
    assert "aisle_obstructed" in _codes(result, "warning")
    assert result["metrics"]["obstructedAisleCount"] == 1


def test_aisle_wall_contact_exception_keeps_hard_clearance_contact(golden: dict) -> None:
    layout, shell = _aisle_doorway_scene()
    asset = _asset(golden, "asset-machine-golden")
    obstacle = _box_asset("asset-clearance-contact", 1.0, 1.0, 1.0)
    layout["placements"] = [
        _placement("pl-machine", asset["assetId"], 8.5, 4.0),
        _placement("pl-clearance-contact", obstacle["assetId"], 10.5, 4.0),
    ]

    result = diagnose_layout(
        layout, [asset, obstacle], shell=shell, evidence_authority=golden["authority"],
    )

    assert "aisle_shell_obstructed" not in _codes(result)
    assert "placement_collision" not in _codes(result)
    assert "safety_clearance_violation" in _codes(result, "error")
    assert result["valid"] is False


def test_floor_load_without_evidence_is_unverified_not_exceeded(golden: dict) -> None:
    layout = _layout_with_machine(golden, 2.0, 5.0)
    layout["zones"][0]["loadLimit"]["maximumKgPerSquareMeter"] = 1.0
    result = diagnose_layout(
        layout,
        golden["assetDefinitions"],
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority={},
    )
    assert "floor_load_unverified" in _codes(result, "unverified")
    assert "floor_load_exceeded" not in _codes(result)
    assert result["safe"] is False


@pytest.mark.parametrize(
    ("missing_input", "expected_reason"),
    [
        ("authoritative_mass", "asset_contact_loading_missing"),
        ("support_geometry", "asset_support_geometry_missing"),
        ("contact_geometry", "asset_contact_distribution_missing"),
        ("contact_distribution", "asset_contact_distribution_missing"),
        ("dynamic_load_factor", "asset_dynamic_load_factor_missing"),
        ("floor_capacity", "floor_capacity_missing"),
        ("applicable_policy_binding", "floor_policy_missing"),
        ("published_policy_set", "policy_set_missing"),
    ],
)
def test_floor_safety_cannot_be_safe_when_one_authority_input_is_missing(
    golden: dict,
    missing_input: str,
    expected_reason: str,
) -> None:
    layout = _layout_with_machine(golden, 2.0, 5.0)
    assets = deepcopy(golden["assetDefinitions"])
    machine = next(
        item for item in assets if item["assetId"] == "asset-machine-golden"
    )
    loading = machine["loading"]
    if missing_input == "authoritative_mass":
        loading.pop("operatingMass", None)
        loading.pop("installedMass", None)
    elif missing_input == "support_geometry":
        loading.pop("supportPoints", None)
    elif missing_input == "contact_geometry":
        loading["contactLoads"][0].pop("areaSquareMeters", None)
    elif missing_input == "contact_distribution":
        loading["contactLoads"][0].pop("loadFraction", None)
    elif missing_input == "dynamic_load_factor":
        loading.pop("dynamicLoadFactors", None)
    elif missing_input == "floor_capacity":
        layout["zones"][0].pop("loadLimit", None)
    elif missing_input == "applicable_policy_binding":
        layout["zones"][0]["loadLimit"].pop("policyRuleRef", None)
        layout["zones"][0]["loadLimit"].pop("ruleType", None)
    elif missing_input != "published_policy_set":
        raise AssertionError(f"Unsupported safety case: {missing_input}")

    result = diagnose_layout(
        layout,
        assets,
        shell=golden["shell"],
        policy_set=(
            None
            if missing_input == "published_policy_set"
            else golden["policySet"]
        ),
        evidence_authority=golden["authority"],
    )

    matching = [
        item
        for item in result["findings"]
        if item["code"] in {"floor_load_unverified", "policy_rule_unavailable"}
        and item["severity"] == "unverified"
    ]
    assert matching, result
    assert any(
        item.get("details", {}).get("reason") == expected_reason
        for item in matching
    ), matching
    assert result["safe"] is False
    assert result["safetyStatus"] == "unverified"


@pytest.mark.parametrize(
    "evidence_state",
    ("missing", "revoked", "stale"),
)
def test_embedded_claims_cannot_self_authorize_noncurrent_evidence(
    golden: dict,
    evidence_state: str,
) -> None:
    asset = _asset(golden, "asset-machine-golden")
    evidence_id = "ev-machine-mass"
    records = []
    if evidence_state == "revoked":
        records.append(
            _evidence_record(
                evidence_id,
                revoked_at="2026-07-28T00:00:00Z",
            )
        )
    elif evidence_state == "stale":
        records.append(
            _evidence_record(
                evidence_id,
                valid_until="2026-07-28T00:00:00Z",
            )
        )
    for record in records:
        EvidenceRecord.from_mapping(record)
    asset["evidenceRecords"] = records

    authority = FacilityLayoutService._collect_evidence_authority([asset])

    assert authority.get(evidence_id) not in {"authored", "derived"}


def test_authoritative_hard_clearance_conflict_is_error(golden: dict) -> None:
    result = diagnose_layout(
        _layout_with_machine(golden, 3.6, 5.0),
        golden["assetDefinitions"],
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
    )
    assert "placement_collision" not in _codes(result)
    assert golden["expected"]["clearanceCollisionCodes"][0] in _codes(
        result,
        "error",
    )


def test_inferred_hard_clearance_cannot_become_authoritative(golden: dict) -> None:
    assets = deepcopy(golden["assetDefinitions"])
    machine = next(item for item in assets if item["assetId"] == "asset-machine-golden")
    machine["clearances"][0]["evidenceStatus"] = "inferred"
    result = diagnose_layout(
        _layout_with_machine(golden, 3.6, 5.0),
        assets,
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
    )
    assert "safety_clearance_violation" in _codes(result, "warning")
    assert "clearance_rule_unavailable" in _codes(result, "unverified")
    assert "safety_clearance_violation" not in _codes(result, "error")
    assert result["safe"] is False


def test_mixed_safety_evidence_cannot_yield_safe(golden: dict) -> None:
    assets = deepcopy(golden["assetDefinitions"])
    machine = next(item for item in assets if item["assetId"] == "asset-machine-golden")
    inferred = deepcopy(machine["clearances"][0])
    inferred["clearanceId"] = "clearance-machine-inferred"
    inferred["evidence"] = ["ev-machine-clearance-inferred"]
    inferred["evidenceStatus"] = "inferred"
    machine["clearances"].append(inferred)
    authority = dict(golden["authority"])
    authority["ev-machine-clearance-inferred"] = "inferred"

    result = diagnose_layout(
        _layout_with_machine(golden, 2.0, 5.0),
        assets,
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=authority,
    )

    assert "clearance_rule_unavailable" in _codes(result, "unverified")
    assert result["safe"] is False
    assert result["safetyStatus"] == "unverified"


def test_mirrored_clearance_conflicts_keep_distinct_directional_ids(
    golden: dict,
) -> None:
    layout = deepcopy(golden["baseLayout"])
    layout["placements"] = [
        _placement("pl-machine-a", "asset-machine-golden", 2.0, 5.0),
        _placement("pl-machine-b", "asset-machine-golden", 4.2, 5.0),
    ]
    result = diagnose_layout(
        layout,
        golden["assetDefinitions"],
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
    )
    conflicts = [
        finding
        for finding in result["findings"]
        if finding["code"] == "safety_clearance_violation"
    ]

    assert result["metrics"]["placementCollisions"] == 0
    assert result["metrics"]["clearanceConflicts"] == 2
    assert len(conflicts) == 2
    assert len({finding["findingId"] for finding in conflicts}) == 2
    assert {
        finding["details"]["clearanceOwnerId"] for finding in conflicts
    } == {"pl-machine-a", "pl-machine-b"}


def test_missing_safety_clearance_evidence_never_yields_safe(golden: dict) -> None:
    assets = deepcopy(golden["assetDefinitions"])
    for asset in assets:
        asset["clearances"] = []
    result = diagnose_layout(
        _layout_with_machine(golden, 2.0, 5.0),
        assets,
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
    )
    assert "clearance_rule_unavailable" in _codes(result, "unverified")
    assert result["valid"] is True
    assert result["safe"] is False
    assert result["safetyStatus"] == "unverified"


def test_spatial_diagnostics_do_not_overwrite_authored_clearances(golden: dict) -> None:
    layout = _layout_with_machine(golden, 3.6, 5.0)
    assets = deepcopy(golden["assetDefinitions"])
    layout_before = canonical_spatial_bytes(layout)
    assets_before = canonical_spatial_bytes(assets)
    diagnose_layout(
        layout,
        assets,
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
    )
    assert canonical_spatial_bytes(layout) == layout_before
    assert canonical_spatial_bytes(assets) == assets_before
    assert assets[0]["clearances"][0]["evidenceStatus"] == "authored"


def test_candidate_generation_exercises_every_p6_snap_family(golden: dict) -> None:
    result = generate_placement_candidates(
        golden["baseLayout"],
        _asset(golden, "asset-machine-golden"),
        {"x": 3.2, "y": 0.0, "z": 5.0},
        golden["assetDefinitions"],
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
        maximum_candidates=64,
    )
    families = {candidate["family"] for candidate in result["candidates"]}
    assert families == set(golden["expected"]["candidateFamilies"])
    assert all(candidate["metrics"]["physicalCollisions"] == 0 for candidate in result["candidates"])
    assert all(candidate["safe"] is True for candidate in result["candidates"])


def test_foundation_snap_uses_authoritative_surface_elevation(golden: dict) -> None:
    layout = deepcopy(golden["baseLayout"])
    foundation_anchor = next(
        anchor
        for anchor in layout["zones"][0]["anchors"]
        if anchor["anchorKind"] == "foundation"
    )
    foundation_anchor["position"]["y"] = 0.75
    shell = deepcopy(golden["shell"])
    foundation = next(
        feature
        for feature in shell["features"]
        if feature["featureKind"] == "foundation"
    )
    foundation["geometry"]["elevation"] = 0.75
    foundation["geometry"]["position"]["y"] = 0.75

    result = generate_placement_candidates(
        layout,
        _asset(golden, "asset-machine-golden"),
        {"x": 15.0, "y": 0.0, "z": 15.0},
        golden["assetDefinitions"],
        shell=shell,
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
        enabled_families=("foundation",),
    )

    assert result["candidates"]
    assert all(
        candidate["transform"]["position"]["y"] == pytest.approx(0.75)
        for candidate in result["candidates"]
    )
    assert all(candidate["safe"] is True for candidate in result["candidates"])


def test_candidate_ids_and_ranking_are_stable_across_input_order(golden: dict) -> None:
    arguments = {
        "layout": golden["baseLayout"],
        "asset_definition": _asset(golden, "asset-machine-golden"),
        "requested_position": {"x": 3.2, "y": 0.0, "z": 5.0},
        "asset_definitions": golden["assetDefinitions"],
        "shell": golden["shell"],
        "policy_set": golden["policySet"],
        "evidence_authority": golden["authority"],
    }
    first = generate_placement_candidates(**arguments)
    shuffled_layout = deepcopy(golden["baseLayout"])
    shuffled_layout["zones"][0]["anchors"].reverse()
    second = generate_placement_candidates(
        shuffled_layout,
        arguments["asset_definition"],
        arguments["requested_position"],
        list(reversed(golden["assetDefinitions"])),
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=dict(reversed(list(golden["authority"].items()))),
    )
    assert [item["candidateId"] for item in second["candidates"]] == [
        item["candidateId"] for item in first["candidates"]
    ]
    assert second == first


def test_locked_target_yields_no_movement_candidates(golden: dict) -> None:
    layout = deepcopy(golden["baseLayout"])
    target = layout["placements"][0]
    target["positionMode"] = "locked"
    asset = _asset(golden, target["assetId"])

    result = generate_placement_candidates(
        layout,
        asset,
        {"x": 10.0, "y": 0.0, "z": 10.0},
        golden["assetDefinitions"],
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
        target_placement_id=target["placementId"],
    )

    assert result["candidates"] == []
    assert result["rejectionCounts"]["locked_placement_movement"] >= 1


def test_candidate_obstacle_change_invalidates_stable_ids(golden: dict) -> None:
    first = generate_placement_candidates(
        golden["baseLayout"],
        _asset(golden, "asset-machine-golden"),
        {"x": 3.2, "y": 0.0, "z": 5.0},
        golden["assetDefinitions"],
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
    )
    changed = deepcopy(golden["baseLayout"])
    changed["placements"][0]["transform"]["position"]["z"] = 6.0
    second = generate_placement_candidates(
        changed,
        _asset(golden, "asset-machine-golden"),
        {"x": 3.2, "y": 0.0, "z": 5.0},
        golden["assetDefinitions"],
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
    )
    assert first["obstacleFingerprint"] != second["obstacleFingerprint"]
    assert {item["candidateId"] for item in first["candidates"]}.isdisjoint(
        item["candidateId"] for item in second["candidates"]
    )


def test_candidate_cache_is_isolated_and_policy_bound(golden: dict) -> None:
    arguments = {
        "layout": golden["baseLayout"],
        "asset_definition": _asset(golden, "asset-machine-golden"),
        "requested_position": {"x": 3.2, "y": 0.0, "z": 5.0},
        "asset_definitions": golden["assetDefinitions"],
        "shell": golden["shell"],
        "policy_set": golden["policySet"],
        "evidence_authority": golden["authority"],
    }
    first = generate_placement_candidates(**arguments)
    expected = deepcopy(first)
    first["candidates"][0]["findings"].clear()

    assert generate_placement_candidates(**arguments) == expected

    changed_policy = deepcopy(golden["policySet"])
    changed_policy.setdefault("unresolvedItems", []).append(
        {
            "findingId": "policy-cache-invalidation",
            "code": "policy_cache_invalidation",
            "message": "Policy evidence changed.",
        }
    )
    changed = generate_placement_candidates(
        **{**arguments, "policy_set": changed_policy}
    )
    assert changed != expected
    assert any(
        finding.get("details", {}).get("sourceCode")
        == "policy_cache_invalidation"
        for candidate in changed["candidates"]
        for finding in candidate["findings"]
    )


def test_candidate_generation_reports_rejections_without_mutation(golden: dict) -> None:
    layout = deepcopy(golden["baseLayout"])
    before = canonical_spatial_bytes(layout)
    result = generate_placement_candidates(
        layout,
        _asset(golden, "asset-machine-golden"),
        {"x": 6.0, "y": 0.0, "z": 5.0},
        golden["assetDefinitions"],
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
        enabled_families=("grid", "alignment"),
    )
    assert result["rejectionCounts"]["placement_collision"] >= 1
    assert canonical_spatial_bytes(layout) == before
    assert all(
        "candidateId" in candidate and "beforeAfterMetrics" in candidate
        for candidate in result["candidates"]
    )


def test_candidate_generation_with_missing_evidence_returns_unverified(golden: dict) -> None:
    result = generate_placement_candidates(
        golden["baseLayout"],
        _asset(golden, "asset-machine-golden"),
        {"x": 3.2, "y": 0.0, "z": 5.0},
        golden["assetDefinitions"],
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority={},
        enabled_families=("grid",),
    )
    assert result["candidates"]
    assert all(candidate["safe"] is False for candidate in result["candidates"])
    assert all(
        candidate["safetyStatus"] == "unverified"
        for candidate in result["candidates"]
    )


def test_golden_expected_code_contract(golden: dict) -> None:
    physical = diagnose_layout(
        _layout_with_machine(golden, 5.5, 5.0),
        golden["assetDefinitions"],
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
    )
    clearance = diagnose_layout(
        _layout_with_machine(golden, 3.6, 5.0),
        golden["assetDefinitions"],
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
    )
    unknown = diagnose_layout(
        _layout_with_machine(golden, 2.0, 5.0),
        golden["assetDefinitions"],
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority={},
    )
    assert set(golden["expected"]["physicalCollisionCodes"]) <= set(_codes(physical))
    assert set(golden["expected"]["clearanceCollisionCodes"]) <= set(_codes(clearance))
    assert set(golden["expected"]["unknownEvidenceCodes"]) <= set(_codes(unknown))


@pytest.mark.skipif(
    os.environ.get("RUN_FACILITY_LAYOUT_PERF") != "1",
    reason=(
        "Opt-in contractual wall-clock benchmark; set "
        "RUN_FACILITY_LAYOUT_PERF=1 on the pinned performance host."
    ),
)
def test_candidate_generation_p95_at_500_placements_is_within_contract(
    golden: dict,
    native_layout: dict,
    performance_spec: dict,
) -> None:
    asset = _asset(golden, "asset-machine-golden")
    asset["assetDefinitionRevision"] = "a" * 64
    layout = _contract_scale_layout(native_layout, performance_spec, asset)
    shell = deepcopy(golden["shell"])
    shell["features"][0]["geometry"]["boundary"] = [
        {"x": -2.0, "z": -2.0},
        {"x": 104.0, "z": -2.0},
        {"x": 104.0, "z": 82.0},
        {"x": -2.0, "z": 82.0},
    ]
    request = performance_spec["candidateRequest"]
    arguments = {
        "layout": layout,
        "asset_definition": asset,
        "requested_position": request["position"],
        "asset_definitions": [asset],
        "shell": shell,
        "policy_set": golden["policySet"],
        "evidence_authority": golden["authority"],
        "maximum_candidates": request["maximumCandidates"],
    }
    measurement = performance_spec["measurement"]

    for _ in range(measurement["warmupRuns"]):
        generate_placement_candidates(**arguments)

    durations = []
    candidate_ids = None
    for _ in range(measurement["sampleRuns"]):
        started = time.perf_counter()
        result = generate_placement_candidates(**arguments)
        durations.append((time.perf_counter() - started) * 1000.0)
        observed_ids = [
            item["candidateId"] for item in result["candidates"]
        ]
        if candidate_ids is None:
            candidate_ids = observed_ids
        else:
            assert observed_ids == candidate_ids

    p95 = statistics.quantiles(
        durations,
        n=100,
        method="inclusive",
    )[94]
    assert p95 <= measurement["maximumP95Milliseconds"], {
        "durationsMs": durations,
        "fixtureId": performance_spec["fixtureId"],
        "p95Ms": p95,
        "thresholdMs": measurement["maximumP95Milliseconds"],
    }
