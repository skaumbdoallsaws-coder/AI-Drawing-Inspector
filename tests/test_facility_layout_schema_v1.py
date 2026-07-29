from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

import pytest

from ai_inspector.facility_layout.canonical import (
    canonical_layout_bytes,
    canonicalize_layout,
    layout_revision,
)
from ai_inspector.facility_layout.errors import (
    FacilityAuthorizationError,
    FacilityCompatibilityError,
    FacilityConflictError,
    FacilityIntegrityError,
    FacilityLayoutError,
    FacilityNotFoundError,
    FacilityValidationError,
)
from ai_inspector.facility_layout.schema_v1 import detect_layout_compatibility
from ai_inspector.facility_layout.validate import validate_layout


FIXTURES = Path(__file__).parent / "fixtures" / "facility_layout"
LAYOUT_FIXTURES = (
    "empty_cell.json",
    "two_asset_cell.json",
    "overlapping_zones.json",
    "repeated_assets.json",
    "utility_cell.json",
)


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="ascii"))


def _error_code(document: dict) -> str:
    with pytest.raises(FacilityLayoutError) as captured:
        validate_layout(document)
    return captured.value.code


def test_error_hierarchy_has_stable_status_and_payloads():
    cases = (
        (FacilityValidationError("invalid", "bad"), 422),
        (FacilityConflictError("conflict", "bad"), 409),
        (FacilityAuthorizationError("forbidden", "bad"), 403),
        (FacilityNotFoundError("not_found", "bad"), 404),
        (FacilityCompatibilityError("future", "bad"), 409),
        (FacilityIntegrityError("integrity", "bad"), 422),
    )
    for error, status in cases:
        assert isinstance(error, FacilityLayoutError)
        assert error.status_code == status
        assert error.to_dict() == {"code": error.code, "message": "bad"}


def test_all_frozen_v1_layouts_validate_and_canonicalize_deterministically():
    for name in LAYOUT_FIXTURES:
        document = _load(name)
        assert validate_layout(document) is document
        first = canonical_layout_bytes(document)
        second = canonical_layout_bytes(deepcopy(document))
        assert first == second
        assert first.decode("ascii")
        assert not first.endswith(b"\n")
        assert json.loads(first) == canonicalize_layout(document)
        assert layout_revision(document) == hashlib.sha256(first).hexdigest()


def test_canonical_numeric_forms_use_half_even_and_remove_negative_zero():
    document = _load("empty_cell.json")
    document["coordinateFrame"]["floorElevation"] = -0.0
    document["zones"] = [
        {
            "zoneId": "zn-rounding",
            "zoneType": "workcell",
            "label": "Rounding",
            "boundary": [
                {"x": 0.0000005, "z": 0},
                {"x": 2.0000005, "z": 0},
                {"x": 2, "z": 2.0000015},
                {"x": 0, "z": 2},
            ],
            "floorElevation": -0.0,
            "anchors": [],
            "evidence": [],
        }
    ]
    canonical = canonicalize_layout(document)
    assert canonical["coordinateFrame"]["floorElevation"] == 0
    assert canonical["zones"][0]["boundary"] == [
        {"x": 0, "z": 0},
        {"x": 2, "z": 0},
        {"x": 2, "z": 2.000002},
        {"x": 0, "z": 2},
    ]


def test_quaternion_sign_is_canonicalized_but_invalid_norm_is_rejected():
    document = _load("repeated_assets.json")
    document["placements"][0]["transform"]["quaternion"] = {
        "x": 0,
        "y": 0,
        "z": 0,
        "w": -1,
    }
    canonical = canonicalize_layout(document)
    assert canonical["placements"][0]["transform"]["quaternion"] == {
        "x": 0,
        "y": 0,
        "z": 0,
        "w": 1,
    }
    validate_layout(canonical, require_canonical=True)

    invalid = _load("repeated_assets.json")
    invalid["placements"][0]["transform"]["quaternion"]["w"] = 0.5
    assert _error_code(invalid) == "invalid_quaternion"


def test_clockwise_polygon_is_canonicalized_and_raw_validation_rejects_it():
    document = _load("two_asset_cell.json")
    document["zones"][0]["boundary"] = [
        document["zones"][0]["boundary"][0],
        *reversed(document["zones"][0]["boundary"][1:]),
    ]
    assert _error_code(document) == "invalid_polygon"
    canonical = canonicalize_layout(document)
    validate_layout(canonical, require_canonical=True)


def test_self_intersecting_and_repeated_polygons_fail_closed():
    document = _load("two_asset_cell.json")
    document["zones"][0]["boundary"] = [
        {"x": 0, "z": 0},
        {"x": 2, "z": 2},
        {"x": 0, "z": 2},
        {"x": 2, "z": 0},
    ]
    assert _error_code(document) == "invalid_polygon"

    repeated = _load("two_asset_cell.json")
    repeated["zones"][0]["boundary"][3] = repeated["zones"][0]["boundary"][0]
    assert _error_code(repeated) == "invalid_polygon"


@pytest.mark.parametrize("field", ("camera", "viewport", "selection", "activeProposal"))
def test_live_editor_fields_are_never_persisted(field: str):
    document = _load("empty_cell.json")
    document[field] = {}
    assert _error_code(document) == "forbidden_live_state"


def test_compatible_unknown_fields_round_trip_without_reconstruction():
    document = _load("two_asset_cell.json")
    document["futureTopLevel"] = {"nested": [True, 7, "value"]}
    document["zones"][0]["futureZoneField"] = {"preserve": 1.25}
    document["placements"][0]["futurePlacementField"] = ["x", None]
    canonical = canonicalize_layout(document)
    reopened = json.loads(canonical_layout_bytes(canonical))
    assert reopened["futureTopLevel"] == document["futureTopLevel"]
    assert reopened["zones"][0]["futureZoneField"] == {
        "preserve": 1.25,
    }
    assert reopened["placements"][0]["futurePlacementField"] == ["x", None]


def test_closed_geometry_objects_reject_unknown_fields():
    document = _load("empty_cell.json")
    document["coordinateFrame"]["future"] = True
    assert _error_code(document) == "invalid_layout_shape"

    document = _load("repeated_assets.json")
    document["placements"][0]["transform"]["position"]["future"] = True
    assert _error_code(document) == "invalid_layout_shape"


def test_extension_field_and_byte_budgets_are_enforced():
    fields = _load("empty_cell.json")
    for index in range(33):
        fields[f"future{index:02d}"] = index
    assert _error_code(fields) == "extension_limit_exceeded"

    byte_budget = _load("empty_cell.json")
    byte_budget["futurePayload"] = "x" * 5_242_881
    assert _error_code(byte_budget) == "extension_limit_exceeded"

    combined = _load("empty_cell.json")
    combined["extensions"] = {"inside": True}
    for index in range(32):
        combined[f"outside{index:02d}"] = index
    assert _error_code(combined) == "extension_limit_exceeded"


def test_schema_defined_free_form_map_keys_remain_compatible():
    document = _load("two_asset_cell.json")
    document["zones"][0]["edgeSetbacks"] = {"operator side": 0.5}
    document["routes"][0]["sourceRevisions"]["asset definition"] = "9" * 64
    validate_layout(document)


def test_json_depth_and_nonfinite_numbers_are_rejected():
    document = _load("empty_cell.json")
    nested: dict = {}
    cursor = nested
    for index in range(35):
        cursor["next"] = {}
        cursor = cursor["next"]
    document["futureNested"] = nested
    assert _error_code(document) == "document_limit_exceeded"

    nonfinite = _load("empty_cell.json")
    nonfinite["coordinateFrame"]["floorElevation"] = math.inf
    assert _error_code(nonfinite) == "non_finite_transform"

    out_of_bounds = _load("empty_cell.json")
    out_of_bounds["coordinateFrame"]["floorElevation"] = 1_000_001
    assert _error_code(out_of_bounds) == "non_finite_transform"


def test_placement_membership_and_binding_dual_writes_are_forbidden():
    document = _load("repeated_assets.json")
    document["placements"][0]["zoneId"] = "zn-runtime"
    assert _error_code(document) == "persisted_zone_membership_forbidden"

    document = _load("repeated_assets.json")
    document["placements"][0]["processBindings"] = []
    assert _error_code(document) == "placement_binding_dual_write_forbidden"


def test_route_endpoints_are_revision_and_reference_bound():
    dangling = _load("two_asset_cell.json")
    dangling["routes"][0]["targetEndpoint"]["placementId"] = "pl-missing"
    assert _error_code(dangling) == "dangling_placement_endpoint"

    shell = _load("utility_cell.json")
    shell["routes"][0]["sourceEndpoint"]["shellRevision"] = "9" * 64
    assert _error_code(shell) == "shell_endpoint_mismatch"

    anchor = _load("two_asset_cell.json")
    anchor["routes"][0]["sourceEndpoint"]["anchorId"] = "za-missing"
    assert _error_code(anchor) == "dangling_zone_anchor"


def test_utility_and_process_binding_references_fail_closed():
    network = _load("utility_cell.json")
    network["utilityNetworks"][0]["segments"][0][
        "sourceNetworkNodeId"
    ] = "nn-missing"
    assert _error_code(network) == "dangling_network_node"

    placement = _load("utility_cell.json")
    placement["processBindings"][0]["placementIds"] = ["pl-missing"]
    assert _error_code(placement) == "dangling_process_binding_placement"

    route = _load("utility_cell.json")
    route["processBindings"][0]["routeIds"] = ["rt-missing"]
    assert _error_code(route) == "dangling_process_binding_route"


def test_repeated_asset_definitions_remain_independent_placements():
    document = _load("repeated_assets.json")
    validate_layout(document)
    first, second = document["placements"]
    assert first["assetId"] == second["assetId"]
    assert first["assetDefinitionRevision"] == second["assetDefinitionRevision"]
    assert first["placementId"] != second["placementId"]
    assert first["transform"] != second["transform"]


def test_future_schema_is_read_only_and_original_bytes_are_preserved():
    path = FIXTURES / "migration" / "newer-schema-v2.input.json"
    source = path.read_bytes()
    compatibility = detect_layout_compatibility(source)
    assert compatibility.mode == "read_only"
    assert compatibility.read_allowed is True
    assert compatibility.write_allowed is False
    assert compatibility.original_bytes == source
    assert compatibility.canonical_rewrite_allowed is False
    assert compatibility.to_dict()["originalBytesMustRemainUnchanged"] is True
    with pytest.raises(FacilityCompatibilityError) as captured:
        canonicalize_layout(json.loads(source))
    assert captured.value.code == "unsupported_schema_version_read_only"


def test_native_and_legacy_compatibility_modes_are_explicit():
    native = detect_layout_compatibility(_load("empty_cell.json"))
    assert (native.mode, native.read_allowed, native.write_allowed) == (
        "native",
        True,
        True,
    )
    legacy_path = FIXTURES / "migration" / "legacy-semantic-v0.2.input.json"
    legacy = detect_layout_compatibility(legacy_path.read_bytes())
    assert legacy.mode == "legacy_migration"
    assert legacy.migration_allowed is True
    assert legacy.write_allowed is False
