import hashlib
import json
import math
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "static" / "contracts"
FIXTURES = ROOT / "tests" / "fixtures" / "facility_layout"

LAYOUT_SCHEMA_PATH = CONTRACTS / "facility-layout-schema-v1.json"
AUTHORITY_SCHEMA_PATH = CONTRACTS / "facility-authority-schema-v1.json"
SPATIAL_CONTRACT_PATH = CONTRACTS / "facility-layout-spatial-contract-v1.json"
AUTHORIZATION_CONTRACT_PATH = CONTRACTS / "facility-layout-authorization-v1.json"
OBSERVATION_CONTRACT_PATH = CONTRACTS / "facility-layout-observation-contract-v1.json"
ASSET_SCHEMA_PATH = CONTRACTS / "industrial-asset-definition-schema-v1.json"
CATALOG_CONTRACT_PATH = CONTRACTS / "industrial-asset-catalog-contract-v1.json"

CANONICAL_LAYOUT_FIXTURES = (
    "empty_cell.json",
    "two_asset_cell.json",
    "overlapping_zones.json",
    "repeated_assets.json",
    "utility_cell.json",
)

REVISION_RE = re.compile(r"^[0-9a-f]{64}$")
PREFIXES = {
    "layoutId": "fl-",
    "zoneId": "zn-",
    "anchorId": "za-",
    "placementId": "pl-",
    "routeId": "rt-",
    "utilityNetworkId": "un-",
    "networkNodeId": "nn-",
    "networkSegmentId": "ns-",
    "processBindingId": "pb-",
}


def _load(path):
    return json.loads(path.read_text(encoding="ascii"))


def _canonical_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _fingerprint(value):
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _transform_point_column_major(matrix, point):
    return {
        "x": (
            matrix[0] * point["x"]
            + matrix[4] * point["y"]
            + matrix[8] * point["z"]
            + matrix[12]
        ),
        "y": (
            matrix[1] * point["x"]
            + matrix[5] * point["y"]
            + matrix[9] * point["z"]
            + matrix[13]
        ),
        "z": (
            matrix[2] * point["x"]
            + matrix[6] * point["y"]
            + matrix[10] * point["z"]
            + matrix[14]
        ),
    }


def _canonical_meter(value):
    rounded = round(value, 6)
    return 0.0 if rounded == 0 else rounded


def _derived_id(prefix, *identity_parts):
    digest = _fingerprint(list(identity_parts))
    return f"{prefix}{digest[:24]}"


def _assert_revision(value):
    assert isinstance(value, str)
    assert REVISION_RE.fullmatch(value)


def _assert_finite_numbers(value, path="$"):
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        assert math.isfinite(value), f"{path} must be finite"
        assert abs(value) <= 1_000_000, f"{path} exceeds world bounds"
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_finite_numbers(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _assert_finite_numbers(item, f"{path}.{key}")


def _orientation(a, b, c):
    return (
        (b["x"] - a["x"]) * (c["z"] - a["z"])
        - (b["z"] - a["z"]) * (c["x"] - a["x"])
    )


def _segments_intersect(a, b, c, d):
    epsilon = 1e-12
    ab_c = _orientation(a, b, c)
    ab_d = _orientation(a, b, d)
    cd_a = _orientation(c, d, a)
    cd_b = _orientation(c, d, b)
    return (
        (ab_c > epsilon and ab_d < -epsilon)
        or (ab_c < -epsilon and ab_d > epsilon)
    ) and (
        (cd_a > epsilon and cd_b < -epsilon)
        or (cd_a < -epsilon and cd_b > epsilon)
    )


def _assert_canonical_polygon(points, path):
    assert len(points) >= 3, f"{path} needs at least three vertices"
    vertices = [(point["x"], point["z"]) for point in points]
    assert len(vertices) == len(set(vertices)), f"{path} repeats a vertex"
    assert vertices[0] != vertices[-1], f"{path} must use implicit closure"

    signed_area_twice = 0.0
    for index, point in enumerate(points):
        following = points[(index + 1) % len(points)]
        signed_area_twice += (
            point["x"] * following["z"] - following["x"] * point["z"]
        )
    assert signed_area_twice > 0, f"{path} must be counter-clockwise in X/Z"

    edge_count = len(points)
    for first_index in range(edge_count):
        first_next = (first_index + 1) % edge_count
        for second_index in range(first_index + 1, edge_count):
            second_next = (second_index + 1) % edge_count
            if first_index in (second_index, second_next):
                continue
            if first_next in (second_index, second_next):
                continue
            assert not _segments_intersect(
                points[first_index],
                points[first_next],
                points[second_index],
                points[second_next],
            ), f"{path} self-intersects"


def _collect_unique(items, key):
    values = [item[key] for item in items]
    assert len(values) == len(set(values)), f"duplicate {key}"
    assert all(value.startswith(PREFIXES[key]) for value in values)
    return set(values)


def _validate_endpoint(endpoint, *, layout, zone_anchors, placement_ids):
    kind = endpoint.get("kind")
    if kind == "placement_connector":
        assert set(endpoint) == {"kind", "placementId", "connectorId"}
        assert endpoint["placementId"] in placement_ids
        assert endpoint["connectorId"]
        return
    if kind == "shell_connector":
        assert set(endpoint) == {
            "kind",
            "shellId",
            "shellRevision",
            "connectorId",
        }
        source_shell = layout["sourceShellRef"]
        assert endpoint["shellId"] == source_shell["shellId"]
        assert endpoint["shellRevision"] == source_shell["shellRevision"]
        assert endpoint["connectorId"]
        return
    if kind == "zone_anchor":
        assert set(endpoint) == {"kind", "zoneId", "anchorId"}
        assert (endpoint["zoneId"], endpoint["anchorId"]) in zone_anchors
        return
    raise AssertionError(f"unsupported endpoint kind: {kind!r}")


def _validate_layout(layout, schema, spatial):
    missing = set(schema["required"]) - set(layout)
    assert not missing, f"missing fields: {sorted(missing)}"
    assert layout["schemaVersion"] == spatial["schemaVersion"] == 1
    assert layout["layoutId"].startswith(PREFIXES["layoutId"])
    assert layout["status"] in {"draft", "active", "template", "archived"}

    for forbidden in ("camera", "viewport", "selection", "activeProposal"):
        assert forbidden not in layout

    expected_frame = {
        "units": "m",
        "handedness": "right",
        "upAxis": "+Y",
        "floorAxes": ["+X", "+Z"],
    }
    for key, expected in expected_frame.items():
        assert layout["coordinateFrame"][key] == expected
    assert layout["coordinateFrame"]["datumId"]
    assert isinstance(layout["coordinateFrame"]["floorElevation"], (int, float))

    source_shell = layout["sourceShellRef"]
    _assert_revision(source_shell["shellRevision"])
    _assert_revision(source_shell["coordinateFrameFingerprint"])
    _assert_revision(layout["policySetRef"]["policySetRevision"])
    if "catalogSnapshotRevision" in layout:
        _assert_revision(layout["catalogSnapshotRevision"])

    limits = spatial["limits"]
    assert len(layout["placements"]) <= limits["maximumPlacements"]
    assert len(layout["zones"]) <= limits["maximumZones"]
    assert len(layout["routes"]) <= limits["maximumRoutes"]
    assert len(layout["utilityNetworks"]) <= limits["maximumUtilityNetworks"]
    assert len(layout["processBindings"]) <= limits["maximumProcessBindings"]
    assert len(_canonical_bytes(layout)) <= limits["maximumCanonicalDocumentBytes"]

    zone_ids = _collect_unique(layout["zones"], "zoneId")
    placement_ids = _collect_unique(layout["placements"], "placementId")
    route_ids = _collect_unique(layout["routes"], "routeId")
    network_ids = _collect_unique(layout["utilityNetworks"], "utilityNetworkId")
    binding_ids = _collect_unique(layout["processBindings"], "processBindingId")
    assert len(zone_ids | placement_ids | route_ids | network_ids | binding_ids) == (
        len(zone_ids)
        + len(placement_ids)
        + len(route_ids)
        + len(network_ids)
        + len(binding_ids)
    )

    zone_anchors = set()
    for zone in layout["zones"]:
        assert len(zone["boundary"]) >= 3
        assert len(zone["boundary"]) <= limits["maximumVerticesPerZone"]
        _assert_canonical_polygon(zone["boundary"], f"zone {zone['zoneId']}")
        anchor_ids = _collect_unique(zone["anchors"], "anchorId")
        for anchor_id in anchor_ids:
            qualified = (zone["zoneId"], anchor_id)
            assert qualified not in zone_anchors
            zone_anchors.add(qualified)

    for placement in layout["placements"]:
        assert "zoneId" not in placement
        assert "processBindings" not in placement
        assert placement["positionMode"] in {"auto", "manual", "locked"}
        assert placement["transform"]["scale"] == 1
        quaternion = placement["transform"]["quaternion"]
        norm = math.sqrt(sum(quaternion[key] ** 2 for key in ("x", "y", "z", "w")))
        assert math.isclose(norm, 1.0, abs_tol=1e-9)
        _assert_revision(placement["assetDefinitionRevision"])

    for route in layout["routes"]:
        _validate_endpoint(
            route["sourceEndpoint"],
            layout=layout,
            zone_anchors=zone_anchors,
            placement_ids=placement_ids,
        )
        _validate_endpoint(
            route["targetEndpoint"],
            layout=layout,
            zone_anchors=zone_anchors,
            placement_ids=placement_ids,
        )
        assert 2 <= len(route["centerline"]) <= limits["maximumPointsPerRoute"]
        _assert_revision(route["routeFingerprint"])
        for revision in route["sourceRevisions"].values():
            _assert_revision(revision)

    for network in layout["utilityNetworks"]:
        network_node_ids = _collect_unique(network["nodes"], "networkNodeId")
        _collect_unique(network["segments"], "networkSegmentId")
        for node in network["nodes"]:
            if node["nodeKind"] == "endpoint":
                assert "position" not in node
                assert node["networkRole"] in {"supply", "sink"}
                _validate_endpoint(
                    node["endpointRef"],
                    layout=layout,
                    zone_anchors=zone_anchors,
                    placement_ids=placement_ids,
                )
            elif node["nodeKind"] == "junction":
                assert "endpointRef" not in node
                assert node["networkRole"] == "junction"
                assert set(node["position"]) == {"x", "y", "z"}
            else:
                raise AssertionError("utility nodes must be endpoints or junctions")
        for segment in network["segments"]:
            assert segment["sourceNetworkNodeId"] in network_node_ids
            assert segment["targetNetworkNodeId"] in network_node_ids
            assert (
                2
                <= len(segment["centerline"])
                <= limits["maximumPointsPerUtilitySegment"]
            )
        for revision in network["sourceRevisionRefs"].values():
            _assert_revision(revision)

    for binding in layout["processBindings"]:
        assert set(binding["placementIds"]) <= placement_ids
        assert set(binding["routeIds"]) <= route_ids
        _assert_revision(binding["processMapRevision"])

    _assert_finite_numbers(layout)


def _evaluate_authorization(contract, case):
    principal = case["principal"]
    request = case["request"]
    if request["tenantId"] != principal["tenantId"]:
        return False, "not_found"
    if request["siteId"] not in principal["siteIds"]:
        return False, "not_found"

    actions = set()
    for role in principal["roles"]:
        actions.update(contract["roles"][role])
    if "*" not in actions and request["action"] not in actions:
        return False, "role_not_authorized"

    if request["action"] == "proposal.apply":
        if not request.get("explicitApproval"):
            return False, "explicit_approval_required"
        for required in ("dependencyFingerprint", "diffHash", "idempotencyKey"):
            if not request.get(required):
                return False, f"{required}_required"
    return True, "authorized"


def _evaluate_observation(contract, case):
    digest = contract["digest"]
    read_tools = contract["readTools"]
    if "canonicalUtf8Bytes" in case:
        if case["canonicalUtf8Bytes"] > digest["maximumCanonicalUtf8Bytes"]:
            return False, "digest_byte_budget_exceeded"
        if case["estimatedTokens"] > digest["maximumTokens"]:
            return False, "digest_token_budget_exceeded"
        return True, "within_bounds"
    if case.get("pageSize", 0) > read_tools["maximumPageSize"]:
        return False, "page_size_exceeded"
    if "query" in case and any(key in case["query"] for key in ("x", "y", "z")):
        return False, "model_authored_coordinates_forbidden"
    if case.get("cursorLayoutRevision") != case.get(
        "currentLayoutRevision", case.get("cursorLayoutRevision")
    ):
        return False, "stale_cursor_revision"
    return True, "within_bounds"


def _evaluate_catalog_visibility(contract, case):
    if case["siteId"] not in case["principalSiteIds"]:
        return False
    visibility = case["visibility"]
    if visibility == "common":
        return bool(case.get("publicReady"))
    if case["principalTenantId"] != case["ownerTenantId"]:
        return False
    if visibility in {"private", "tenant_shared"}:
        return True
    if visibility == "site_shared":
        return case["siteId"] in case["allowedSiteIds"]
    raise AssertionError(f"unknown catalog visibility: {visibility}")


def _schema_compatibility_mode(document):
    version = document.get("schemaVersion")
    if version == "facility-layout-semantic-v0.2":
        return {
            "mode": "legacy_migration",
            "readAllowed": True,
            "writeAllowed": False,
        }
    if isinstance(version, int) and not isinstance(version, bool):
        if version == 1:
            return {"mode": "native", "readAllowed": True, "writeAllowed": True}
        if version > 1:
            return {
                "mode": "read_only",
                "readAllowed": True,
                "writeAllowed": False,
            }
    return {"mode": "unsupported", "readAllowed": False, "writeAllowed": False}


def test_p0_contract_files_are_ascii_and_well_formed():
    paths = (
        LAYOUT_SCHEMA_PATH,
        AUTHORITY_SCHEMA_PATH,
        SPATIAL_CONTRACT_PATH,
        AUTHORIZATION_CONTRACT_PATH,
        OBSERVATION_CONTRACT_PATH,
        ASSET_SCHEMA_PATH,
        CATALOG_CONTRACT_PATH,
    )
    for path in paths:
        raw = path.read_bytes()
        raw.decode("ascii")
        assert json.loads(raw)

    layout_schema = _load(LAYOUT_SCHEMA_PATH)
    authority_schema = _load(AUTHORITY_SCHEMA_PATH)
    spatial = _load(SPATIAL_CONTRACT_PATH)
    authorization = _load(AUTHORIZATION_CONTRACT_PATH)
    observation = _load(OBSERVATION_CONTRACT_PATH)
    asset_schema = _load(ASSET_SCHEMA_PATH)
    catalog = _load(CATALOG_CONTRACT_PATH)
    assert layout_schema["$schema"].endswith("2020-12/schema")
    assert authority_schema["$schema"].endswith("2020-12/schema")
    assert asset_schema["$schema"].endswith("2020-12/schema")
    assert spatial["contractId"] == "facility-layout-spatial-contract-v1"
    assert authorization["contractId"] == "facility-layout-authorization-v1"
    assert observation["contractId"] == "facility-layout-observation-contract-v1"
    assert catalog["contractId"] == "industrial-asset-catalog-contract-v1"


def test_schema_and_spatial_limits_do_not_drift():
    schema = _load(LAYOUT_SCHEMA_PATH)
    asset_schema = _load(ASSET_SCHEMA_PATH)
    spatial = _load(SPATIAL_CONTRACT_PATH)
    limits = spatial["limits"]
    assert schema["properties"]["placements"]["maxItems"] == limits["maximumPlacements"]
    assert schema["properties"]["zones"]["maxItems"] == limits["maximumZones"]
    assert schema["properties"]["routes"]["maxItems"] == limits["maximumRoutes"]
    assert (
        schema["properties"]["utilityNetworks"]["maxItems"]
        == limits["maximumUtilityNetworks"]
    )
    assert (
        schema["properties"]["processBindings"]["maxItems"]
        == limits["maximumProcessBindings"]
    )
    assert (
        schema["$defs"]["zone"]["properties"]["boundary"]["maxItems"]
        == limits["maximumVerticesPerZone"]
    )
    assert (
        schema["$defs"]["route"]["properties"]["centerline"]["maxItems"]
        == limits["maximumPointsPerRoute"]
    )
    assert (
        schema["$defs"]["utilityNetwork"]["properties"]["nodes"]["maxItems"]
        == limits["maximumNodesPerUtilityNetwork"]
    )
    assert (
        schema["$defs"]["utilityNetwork"]["properties"]["segments"]["maxItems"]
        == limits["maximumSegmentsPerUtilityNetwork"]
    )
    assert (
        asset_schema["properties"]["connectors"]["maxItems"]
        == limits["maximumConnectorsPerAssetDefinition"]
    )
    assert (
        asset_schema["properties"]["clearances"]["maxItems"]
        == limits["maximumClearancesPerAssetDefinition"]
    )


def test_camera_and_live_editor_state_are_not_persisted():
    schema = _load(LAYOUT_SCHEMA_PATH)
    spatial = _load(SPATIAL_CONTRACT_PATH)
    for field in ("camera", "viewport", "selection", "activeProposal"):
        assert schema["properties"][field] is False
    assert spatial["coordinateFrame"]["screenPixelsPersisted"] is False
    assert spatial["coordinateFrame"]["cameraPersisted"] is False
    assert spatial["coordinateFrame"]["layoutFrameMustEqualShellFrame"] is True
    assert spatial["coordinateFrame"]["matrixStorage"] == "column_major"
    assert spatial["coordinateFrame"]["matrixVectorConvention"] == "column_vectors"
    assert spatial["coordinateFrame"]["assetSourceTransformInputUnits"] == "m"


def test_canonical_layout_fixtures_satisfy_executable_contract():
    schema = _load(LAYOUT_SCHEMA_PATH)
    spatial = _load(SPATIAL_CONTRACT_PATH)
    for name in CANONICAL_LAYOUT_FIXTURES:
        fixture = _load(FIXTURES / name)
        _validate_layout(fixture, schema, spatial)


def test_repeated_assets_remain_distinct_occurrences():
    fixture = _load(FIXTURES / "repeated_assets.json")
    placements = fixture["placements"]
    assert placements[0]["assetId"] == placements[1]["assetId"]
    assert (
        placements[0]["assetDefinitionRevision"]
        == placements[1]["assetDefinitionRevision"]
    )
    assert placements[0]["placementId"] != placements[1]["placementId"]
    assert placements[0]["transform"] != placements[1]["transform"]


def test_overlapping_zones_do_not_create_singular_persisted_membership():
    fixture = _load(FIXTURES / "overlapping_zones.json")
    assert len(fixture["zones"]) == 2
    placement = fixture["placements"][0]
    assert "zoneId" not in placement
    assert placement["metadata"]["membershipResolvedAtRuntime"] is True


def test_utility_topology_uses_discriminated_nodes_and_qualified_endpoints():
    fixture = _load(FIXTURES / "utility_cell.json")
    network = fixture["utilityNetworks"][0]
    endpoint_nodes = [node for node in network["nodes"] if node["nodeKind"] == "endpoint"]
    junction_nodes = [node for node in network["nodes"] if node["nodeKind"] == "junction"]
    assert len(endpoint_nodes) == 2
    assert len(junction_nodes) == 1
    assert all("position" not in node for node in endpoint_nodes)
    assert all("endpointRef" not in node for node in junction_nodes)


def test_identity_derivation_is_stable_and_dependency_bound():
    spatial = _load(SPATIAL_CONTRACT_PATH)
    prefixes = spatial["identity"]["prefixes"]
    dependency_inputs = {
        "layoutRevision": "1" * 64,
        "referencedAssetDefinitionRevisions": ["2" * 64],
        "shellRevision": "3" * 64,
        "policySetRevision": "4" * 64,
        "vehicleProfileRevisions": ["5" * 64],
        "processMapRevision": "6" * 64,
        "spatialEngineVersion": spatial["spatialEngineVersion"],
        "routerVersion": "facility-router-v1",
        "obstacleFingerprint": "7" * 64,
    }
    assert set(dependency_inputs) == set(
        spatial["identity"]["dependencyFingerprintInputs"]
    )
    dependency_fingerprint = _fingerprint(dependency_inputs)
    proposal_a = _derived_id(
        prefixes["proposal"],
        "fl-two-asset-cell",
        "8" * 64,
        "add_asset",
        "9" * 64,
        dependency_fingerprint,
    )
    proposal_b = _derived_id(
        prefixes["proposal"],
        "fl-two-asset-cell",
        "8" * 64,
        "add_asset",
        "9" * 64,
        dependency_fingerprint,
    )
    assert proposal_a == proposal_b
    assert len(proposal_a) <= spatial["identity"]["maximumIdLength"]

    changed = dict(dependency_inputs, policySetRevision="a" * 64)
    changed_fingerprint = _fingerprint(changed)
    proposal_changed = _derived_id(
        prefixes["proposal"],
        "fl-two-asset-cell",
        "8" * 64,
        "add_asset",
        "9" * 64,
        changed_fingerprint,
    )
    assert proposal_changed != proposal_a
    placement_a = _derived_id(prefixes["placement"], proposal_a, "machine-1")
    placement_b = _derived_id(prefixes["placement"], proposal_a, "machine-1")
    assert placement_a == placement_b


def test_legacy_migration_bundle_is_lossless_and_revision_bound():
    migration = FIXTURES / "migration"
    source_path = migration / "legacy-semantic-v0.2.input.json"
    source_bytes = source_path.read_bytes()
    source = json.loads(source_bytes.decode("ascii"))
    context = _load(
        migration / "legacy-semantic-v0.2.migration-context.json"
    )
    layout = _load(migration / "legacy-semantic-v0.2.expected-layout-v1.json")
    shell = _load(migration / "legacy-semantic-v0.2.expected-shell-v1.json")
    policy = _load(migration / "legacy-semantic-v0.2.expected-policy-v1.json")
    evidence = _load(
        migration / "legacy-semantic-v0.2.expected-evidence-v1.json"
    )

    assert _schema_compatibility_mode(source)["mode"] == "legacy_migration"
    assert len(source_bytes) == context["source"]["byteLength"]
    assert hashlib.sha256(source_bytes).hexdigest() == context["source"]["sha256"]
    retained = layout["extensions"]["inspectorproLegacySemanticV0_2"]
    assert retained["payload"] == source
    assert retained["sourceByteLength"] == len(source_bytes)
    assert retained["sourceSha256"] == hashlib.sha256(source_bytes).hexdigest()
    assert retained["mode"] == "read_only"

    assert layout["layoutId"] == context["layoutId"]
    assert layout["coordinateFrame"] == context["coordinateFrame"]
    assert shell["coordinateFrame"] == layout["coordinateFrame"]
    assert _fingerprint(layout["coordinateFrame"]) == context[
        "coordinateFrameFingerprint"
    ]
    assert layout["sourceShellRef"] == context["sourceShellRef"]
    assert layout["policySetRef"] == context["policySetRef"]
    assert context["sourceShellRef"]["shellRevision"] == _fingerprint(shell)
    assert context["policySetRef"]["policySetRevision"] == _fingerprint(policy)

    promoted = layout["placements"][0]
    binding = context["assetBindings"][0]
    legacy_rack = source["rackRows"][0]["rackInstances"][0]
    assert promoted["metadata"]["legacyComponentName"] == binding[
        "legacyComponentName"
    ]
    assert promoted["transform"]["position"] == legacy_rack["positionMeters"]
    assert promoted["transform"]["quaternion"] == binding[
        "canonicalQuaternion"
    ]
    assert promoted["positionMode"] == "locked"
    assert promoted["metadata"]["readOnly"] is True
    assert evidence["status"] == "inferred"
    assert layout["status"] == shell["status"] == policy["status"] == "draft"

    schema = _load(LAYOUT_SCHEMA_PATH)
    spatial = _load(SPATIAL_CONTRACT_PATH)
    _validate_layout(layout, schema, spatial)


def test_newer_schema_is_preserved_read_only_without_rewrite():
    migration = FIXTURES / "migration"
    source_path = migration / "newer-schema-v2.input.json"
    source_bytes = source_path.read_bytes()
    source = json.loads(source_bytes.decode("ascii"))
    expected = _load(migration / "newer-schema-v2.expected-read-only.json")
    compatibility = _schema_compatibility_mode(source)
    assert compatibility == {
        "mode": "read_only",
        "readAllowed": True,
        "writeAllowed": False,
    }
    assert len(source_bytes) == expected["source"]["byteLength"]
    assert hashlib.sha256(source_bytes).hexdigest() == expected["source"]["sha256"]
    assert expected["compatibility"]["migrationAllowed"] is False
    assert expected["compatibility"]["canonicalRewriteAllowed"] is False
    assert expected["compatibility"]["originalBytesMustRemainUnchanged"] is True
    assert expected["writeFailure"] == {
        "status": 409,
        "code": "unsupported_schema_version_read_only",
    }


def test_authority_documents_are_revision_external_and_provenance_closed():
    schema = _load(AUTHORITY_SCHEMA_PATH)
    documents = _load(FIXTURES / "p0_authority_documents.json")
    by_kind = {}
    evidence_ids = set()
    for document in documents:
        by_kind.setdefault(document["documentKind"], []).append(document)
        if document["documentKind"] == "evidence_record":
            evidence_ids.add(document["evidenceId"])

    assert set(by_kind) == {
        "facility_shell",
        "policy_set",
        "vehicle_profile",
        "trusted_source_registry",
        "evidence_record",
    }
    assert len(schema["oneOf"]) == 5

    shell = by_kind["facility_shell"][0]
    policy = by_kind["policy_set"][0]
    vehicle = by_kind["vehicle_profile"][0]
    assert "shellRevision" not in shell
    assert "policySetRevision" not in policy
    assert "vehicleProfileRevision" not in vehicle

    registry = by_kind["trusted_source_registry"][0]
    trusted_sources = {source["trustedSourceId"]: source for source in registry["sources"]}
    for document in (shell, policy, vehicle):
        assert set(document["evidence"]) <= evidence_ids
        for source_ref in document["sourceDocuments"]:
            source = trusted_sources[source_ref["trustedSourceId"]]
            assert document["siteId"] in source["allowedSiteIds"]
            _assert_revision(source_ref["sourceRevision"])

    for evidence in by_kind["evidence_record"]:
        source = trusted_sources[evidence["sourceRef"]["trustedSourceId"]]
        assert source["status"] == "active"
        assert evidence["tenantId"] == source["ownerTenantId"]
        _assert_revision(evidence["valueFingerprint"])
        _assert_revision(evidence["sourceRef"]["sourceRevision"])
        if evidence["status"] == "derived":
            assert evidence["derivation"]["methodId"]


def test_synthetic_asset_definition_exercises_normalization_contract():
    schema = _load(ASSET_SCHEMA_PATH)
    asset = _load(FIXTURES / "assets" / "synthetic-normalized-machine.json")
    assert not (set(schema["required"]) - set(asset))
    assert asset["schemaVersion"] == 1
    assert asset["documentKind"] == "industrial_asset_definition"
    assert "assetDefinitionRevision" not in asset
    assert "renderBundleRevision" not in asset
    assert "sourcePath" not in asset["provenance"]
    assert "localPath" not in asset["provenance"]
    assert "storageKey" not in asset["provenance"]
    _assert_revision(asset["sourceRevision"])
    _assert_revision(asset["renderingCompatibility"]["geometryInterfaceRevision"])
    coordinate = asset["coordinateFrame"]
    assert coordinate["nativeSourceUnits"] == "mm"
    assert len(coordinate["sourceToCanonical"]) == 16
    assert coordinate["alignmentResidualMeters"] <= 0.001
    assert coordinate["floorAnchor"] == {"x": 0.0, "y": 0.0, "z": 0.0}
    assert asset["geometry"]["footprintPolygons"]
    assert asset["collision"]["model"] == "footprint_2_5d"
    assert asset["readiness"]["placementReady"] == {
        "value": True,
        "blockers": [],
    }
    assert asset["readiness"]["planningReady"]["value"] is False
    assert asset["readiness"]["publicReady"]["value"] is False
    _assert_finite_numbers(asset)


def test_real_asset_intake_candidates_fail_closed_without_cad_geometry():
    names = (
        "cnc-vmc-milling-machine.asset-definition-candidate.json",
        "wa01-w48-d36-machine-table.asset-definition-candidate.json",
    )
    for name in names:
        candidate = _load(FIXTURES / "assets" / name)
        assert (
            candidate["schemaVersion"]
            == "facility-layout-p0-asset-definition-candidate-v1"
        )
        assert candidate["identity"]["assetDefinitionRevision"] is None
        assert candidate["identity"]["sourceRevision"] is None
        assert candidate["coordinateFrame"]["sourceToCanonical"] is None
        assert candidate["coordinateFrame"]["floorAnchor"] is None
        assert candidate["geometry"]["footprintPolygons"] is None
        assert candidate["collision"]["footprint2_5d"] is None
        assert candidate["clearances"]["items"] == []
        assert candidate["connectors"]["items"] == []
        assert all(
            gate["value"] is False for gate in candidate["readiness"].values()
        )
        source = candidate["sourceBinding"]["requestedRoot"]
        package = candidate["sourceBinding"]["acquisitionPackage"]
        _assert_revision(source["primaryDataSha256"])
        _assert_revision(package["primaryDataSha256"])
        assert source["visibility"] == package["visibility"] == "server_only"
        assert source["protectedPath"].startswith("protected://machine-library/")
        assert package["protectedPath"].startswith(
            "protected://acquisition-cache/"
        )
        assert ":\\" not in source["protectedPath"]
        assert ":\\" not in package["protectedPath"]


def test_two_real_assets_have_reviewed_placement_geometry_after_extraction():
    assets_root = FIXTURES / "assets"
    evidence = _load(assets_root / "p0-normalization-evidence.json")
    schema = _load(ASSET_SCHEMA_PATH)
    spatial = _load(SPATIAL_CONTRACT_PATH)
    geometry_revision = hashlib.sha256(
        b"industrial-asset-geometry-interface-v1|meters|right|+Y|X/Z|column-major"
    ).hexdigest()

    assert evidence["authorityBoundary"] == {
        "placementGeometry": "derived_and_reviewed",
        "safetyClearances": "unknown",
        "contactLoads": "unknown",
        "utilities": "unknown",
        "publicRedistribution": "blocked",
    }
    assert len(evidence["assets"]) == 2
    for record in evidence["assets"]:
        asset = _load(assets_root / record["normalizedFixture"])
        assert not (set(schema["required"]) - set(asset))
        assert asset["assetId"] == record["assetId"]
        assert asset["status"] == "reviewed"
        assert asset["coordinateFrame"]["nativeSourceUnits"] == record[
            "nativeSourceUnits"
        ]
        assert asset["coordinateFrame"]["sourceCoordinateValueUnits"] == "m"
        assert asset["coordinateFrame"]["sourceUpAxis"] == "+Y"
        assert asset["coordinateFrame"]["floorAnchor"] == {
            "x": 0.0,
            "y": 0.0,
            "z": 0.0,
        }
        assert asset["coordinateFrame"]["alignmentResidualMeters"] <= 0.001
        assert asset["renderingCompatibility"][
            "geometryInterfaceRevision"
        ] == geometry_revision

        source_inputs = {
            "activeConfiguration": record["activeConfiguration"],
            "extractionInputs": evidence["extractor"]["extractionInputs"],
            "extractorExecutableSha256": evidence["extractor"][
                "executableSha256"
            ],
            "sourceFileSha256": record["sourceFileSha256"],
        }
        assert asset["sourceRevision"] == _fingerprint(source_inputs)

        matrix = asset["coordinateFrame"]["sourceToCanonical"]
        source_aabb = record["sourceAabbMeters"]
        transformed_minimum = _transform_point_column_major(
            matrix, source_aabb["minimum"]
        )
        transformed_maximum = _transform_point_column_major(
            matrix, source_aabb["maximum"]
        )
        expected_minimum = {
            axis: _canonical_meter(transformed_minimum[axis])
            for axis in ("x", "y", "z")
        }
        expected_maximum = {
            axis: _canonical_meter(transformed_maximum[axis])
            for axis in ("x", "y", "z")
        }
        assert asset["geometry"]["aabb"]["minimum"] == expected_minimum
        assert asset["geometry"]["aabb"]["maximum"] == expected_maximum
        assert expected_minimum["y"] == 0.0

        footprint = asset["geometry"]["footprintPolygons"][0]
        _assert_canonical_polygon(footprint, asset["assetId"])
        assert asset["collision"]["model"] == "footprint_2_5d"
        assert asset["collision"]["geometry"]["conservative"] is True
        assert asset["readiness"]["visualReady"] == {
            "value": True,
            "blockers": [],
        }
        assert asset["readiness"]["placementReady"] == {
            "value": True,
            "blockers": [],
        }
        assert asset["readiness"]["planningReady"]["value"] is False
        assert asset["readiness"]["publicReady"]["value"] is False
        assert asset["clearances"] == []
        assert asset["connectors"] == []
        assert asset["loading"]["contactLoads"] == []

        evidence_ids = {
            item["evidenceId"] for item in asset["evidenceRecords"]
        }
        assert set(asset["evidence"]) == evidence_ids
        artifact_by_hash = {
            item["sha256"]: item for item in record["artifacts"]
        }
        for artifact in asset["renderingCompatibility"]["artifacts"]:
            source_artifact = artifact_by_hash[artifact["sha256"]]
            assert artifact["byteLength"] == source_artifact["byteLength"]
        _assert_revision(record["extractedJson"]["sha256"])
        for spatial_section in (
            "coordinateFrame",
            "geometry",
            "collision",
            "loading",
        ):
            _assert_finite_numbers(
                asset[spatial_section],
                f"$.{spatial_section}",
            )


def test_catalog_visibility_and_authority_cases_are_executable():
    contract = _load(CATALOG_CONTRACT_PATH)
    for case in contract["visibilityCases"]:
        assert _evaluate_catalog_visibility(contract, case) is case["visible"]
    assert contract["registryAuthority"]["directoryScanIsAuthoritative"] is False
    assert (
        contract["revisionSeparation"]["renderOnlyUpdateInvalidatesLayout"] is False
    )
    assert (
        contract["revisionSeparation"][
            "semanticDefinitionUpdateInvalidatesBoundProposal"
        ]
        is True
    )
    protected = set(contract["clientProjections"]["protected"])
    assert {"sourcePath", "localPath", "storageKey", "licenseDocumentPath"} <= protected
    for case in contract["floorLoadDecisionTable"]:
        authoritative = (
            case["floorCapacityStatus"] in {"authored", "derived"}
            and case["contactLoadStatus"] in {"authored", "derived"}
        )
        if not authoritative:
            assert case["finding"] == "floor_load_unverified"
            assert case["safeVerdictAllowed"] is False


def test_authorization_cases_are_executable_and_fail_closed():
    contract = _load(AUTHORIZATION_CONTRACT_PATH)
    for case in contract["cases"]:
        authorized, reason = _evaluate_authorization(contract, case)
        assert authorized is case["authorized"], case["caseId"]
        assert reason == case["reason"], case["caseId"]
    assert contract["identity"]["trustBrowserTenantOrSite"] is False
    assert contract["writeRules"]["approvalBindsExactDiff"] is True
    assert contract["writeRules"]["approvalBindsDependencyFingerprint"] is True


def test_observation_cases_are_executable_and_bounded():
    contract = _load(OBSERVATION_CONTRACT_PATH)
    digest = contract["digest"]
    assert digest["tokenCountAlgorithm"] == "ceil(canonical_utf8_bytes/4)"
    assert math.ceil(12_001 / 4) == 3_001
    assert contract["readTools"]["allowModelAuthoredWorldCoordinates"] is False
    assert contract["readTools"]["allowScreenRectangles"] is False
    assert contract["previewTool"]["lowLevelMutationsExposedToModel"] is False
    assert contract["previewTool"]["writesFacilityLayout"] is False
    for case in contract["cases"]:
        allowed, reason = _evaluate_observation(contract, case)
        assert allowed is case["allowed"], case["caseId"]
        assert reason == case["reason"], case["caseId"]
