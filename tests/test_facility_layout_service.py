import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_inspector.facility_layout.authority_repository import (
    FacilityShellRepository,
    PolicySetRepository,
    VehicleProfileRepository,
)
from ai_inspector.facility_layout.authorization import FacilityPrincipal
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.errors import (
    FacilityConflictError,
    FacilityLayoutError,
    FacilityNotFoundError,
    FacilityValidationError,
)
from ai_inspector.facility_layout.operations import (
    apply_facility_layout_operations,
    create_layout_document,
)
from ai_inspector.facility_layout.repository import FacilityLayoutRepository
from ai_inspector.facility_layout.routing import (
    persisted_route_fingerprint,
    routing_layout_fingerprint,
)
from ai_inspector.facility_layout.service import (
    FacilityLayoutService,
    coordinate_frame_fingerprint,
)


FIXTURES = Path(__file__).parent / "fixtures" / "facility_layout"
NOW = datetime(2026, 7, 28, tzinfo=timezone.utc)


def _resolved_asset(asset_id, revision):
    return {
        "revision": revision,
        "definition": {
            "assetId": asset_id,
            "assetDefinitionRevision": revision,
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
        },
    }


def _default_asset_resolver(_principal, _site_id, asset_id, revision):
    return _resolved_asset(asset_id, revision)


def _principal(
    *,
    tenant_id="tenant-a",
    sites=("site-a",),
    roles=("admin",),
):
    return FacilityPrincipal(
        principal_id="principal-a",
        tenant_id=tenant_id,
        allowed_site_ids=tuple(sites),
        roles=tuple(roles),
    )


def _authority_documents():
    documents = json.loads(
        (FIXTURES / "p0_authority_documents.json").read_text(encoding="ascii")
    )
    return {
        document["documentKind"]: deepcopy(document)
        for document in documents
        if document["documentKind"]
        in {"facility_shell", "policy_set", "vehicle_profile"}
    }


def _publish(repository, principal, document, id_field):
    candidate = deepcopy(document)
    candidate["status"] = "draft"
    created = repository.create(
        principal,
        site_id="site-a",
        document=candidate,
    )
    reviewed = repository.review(
        principal,
        site_id="site-a",
        authority_id=candidate[id_field],
        expected_revision=created.envelope.revision,
    )
    return repository.publish(
        principal,
        site_id="site-a",
        authority_id=candidate[id_field],
        expected_revision=reviewed.envelope.revision,
    ).envelope


def _service(
    tmp_path,
    *,
    asset_resolver=_default_asset_resolver,
    process_map_resolver=None,
    prototype_vehicle=False,
    vehicle_asset_ref=None,
    allow_prototype_motion=False,
):
    principal = _principal()
    documents = _authority_documents()
    authority_root = tmp_path / "authority"
    clock = lambda: NOW
    shell_repository = FacilityShellRepository(
        authority_root / "shells",
        clock=clock,
    )
    policy_repository = PolicySetRepository(
        authority_root / "policies",
        clock=clock,
    )
    vehicle_repository = VehicleProfileRepository(
        authority_root / "vehicles",
        clock=clock,
    )
    shell = _publish(
        shell_repository,
        principal,
        documents["facility_shell"],
        "shellId",
    )
    policy = _publish(
        policy_repository,
        principal,
        documents["policy_set"],
        "policySetId",
    )
    if prototype_vehicle:
        vehicle_document = deepcopy(documents["vehicle_profile"])
        vehicle_document.update({
            "status": "draft",
            "prototypeMode": True,
            "prototypeLabel": "Prototype motion test profile",
            "productionEligible": False,
        })
        if vehicle_asset_ref is not None:
            vehicle_document["assetDefinitionRef"] = deepcopy(vehicle_asset_ref)
        vehicle = vehicle_repository.create(
            principal,
            site_id="site-a",
            document=vehicle_document,
        ).envelope
    else:
        vehicle = _publish(
            vehicle_repository,
            principal,
            documents["vehicle_profile"],
            "vehicleProfileId",
        )
    service = FacilityLayoutService(
        layout_repository=FacilityLayoutRepository(
            tmp_path / "layouts",
            clock=clock,
        ),
        shell_repository=shell_repository,
        policy_repository=policy_repository,
        vehicle_repository=vehicle_repository,
        asset_definition_resolver=asset_resolver,
        process_map_resolver=process_map_resolver,
        allow_prototype_motion=allow_prototype_motion,
    )
    return service, principal, shell, policy, vehicle


def _layout(shell, policy, *, layout_id="fl-service-cell"):
    frame = deepcopy(shell.document["coordinateFrame"])
    return create_layout_document(
        layout_id=layout_id,
        display_name="Service Cell",
        association={"siteId": "site-a", "areaId": "cell-service"},
        coordinate_frame=frame,
        source_shell_ref={
            "shellId": shell.document["shellId"],
            "shellRevision": shell.revision,
            "coordinateFrameFingerprint": coordinate_frame_fingerprint(frame),
        },
        policy_set_ref={
            "policySetId": policy.document["policySetId"],
            "policySetRevision": policy.revision,
        },
        created_at="browser-owned-time-is-ignored",
    )


def _placement_operation():
    fixture = json.loads(
        (FIXTURES / "two_asset_cell.json").read_text(encoding="ascii")
    )
    placement = deepcopy(fixture["placements"][0])
    return {"op": "place_asset", "placement": placement}


def _generated_placement_operation():
    operation = _placement_operation()
    operation["placement"].pop("placementId", None)
    return operation


def _file_snapshot(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_circulation_obstacle_context_uses_revision_bound_authority(tmp_path):
    service, principal, shell, policy, vehicle = _service(tmp_path)
    layout = _layout(shell, policy, layout_id="fl-g22-context")
    placed = apply_facility_layout_operations(
        layout,
        [_placement_operation()],
        base_revision=None,
    )["document"]

    context = service.circulation_obstacle_context(
        principal,
        "site-a",
        placed,
        vehicle_profile_ref={
            "vehicleProfileId": vehicle.document["vehicleProfileId"],
            "vehicleProfileRevision": vehicle.revision,
        },
    )

    assert context["schemaVersion"] == 1
    assert any(
        obstacle["obstacleKind"] == "placement_footprint"
        and obstacle["sourceRef"]
        == placed["placements"][0]["placementId"]
        for obstacle in context["obstacles"]
    )
    assert context["sourceRevisions"]["shell"] == shell.revision
    assert context["sourceRevisions"]["policy"] == policy.revision
    assert context["sourceRevisions"][
        f"asset:{placed['placements'][0]['assetId']}"
    ] == placed["placements"][0]["assetDefinitionRevision"]
    assert context["vehicleProfile"] == {
        "document": vehicle.document,
        "revision": vehicle.revision,
        "status": "published",
    }


def test_service_creates_and_reads_revision_bound_layout(tmp_path):
    service, principal, shell, policy, _ = _service(tmp_path)
    result = service.create_layout(
        principal,
        "site-a",
        _layout(shell, policy),
        make_default=True,
    )

    assert result["changed"] is True
    assert result["layout"]["createdAt"].startswith("2026-07-28")
    assert result["dependencies"]["shellRevision"] == shell.revision
    listed = service.list_layouts(principal, "site-a")
    assert listed["defaultLayoutId"] == "fl-service-cell"
    reopened = service.get_layout(principal, "site-a", "fl-service-cell")
    assert reopened["revision"] == result["revision"]
    assert reopened["layout"] == result["layout"]


def test_service_applies_one_atomic_operation_batch(tmp_path):
    calls = []

    def resolve_asset(principal, site_id, asset_id, revision):
        calls.append((principal.tenant_id, site_id, asset_id, revision))
        return _resolved_asset(asset_id, revision)

    service, principal, shell, policy, _ = _service(
        tmp_path,
        asset_resolver=resolve_asset,
    )
    created = service.create_layout(
        principal,
        "site-a",
        _layout(shell, policy),
    )
    applied = service.apply_operations(
        principal,
        "site-a",
        "fl-service-cell",
        created["revision"],
        [_placement_operation()],
    )

    assert applied["changed"] is True
    assert applied["operationResult"]["changed"] is True
    assert len(applied["layout"]["placements"]) == 1
    assert calls[-1][2:] == (
        applied["layout"]["placements"][0]["assetId"],
        applied["layout"]["placements"][0]["assetDefinitionRevision"],
    )
    reopened = service.get_layout(principal, "site-a", "fl-service-cell")
    assert reopened["layout"] == applied["layout"]


def test_operation_preview_is_stable_read_only_and_matches_apply(tmp_path):
    service, principal, shell, policy, _ = _service(tmp_path)
    created = service.create_layout(
        principal,
        "site-a",
        _layout(shell, policy),
    )
    operations = [_generated_placement_operation()]
    before = _file_snapshot(tmp_path)

    preview = service.preview_operations(
        principal,
        "site-a",
        "fl-service-cell",
        created["revision"],
        operations,
    )
    repeated = service.preview_operations(
        principal,
        "site-a",
        "fl-service-cell",
        created["revision"],
        operations,
    )

    assert _file_snapshot(tmp_path) == before
    assert preview == repeated
    assert preview["baseRevision"] == created["revision"]
    assert preview["createdIds"] == repeated["createdIds"]
    assert preview["createdIds"][0].startswith("pl-")
    assert preview["affectedIds"] == preview["createdIds"]
    assert preview["findings"] == []
    assert preview["canonicalDiff"]["changed"] is True
    assert len(preview["diffHash"]) == 64
    assert preview["dependencies"]["shellRevision"] == shell.revision

    applied = service.apply_operations(
        principal,
        "site-a",
        "fl-service-cell",
        created["revision"],
        operations,
    )

    assert applied["operationResult"] == {
        key: value
        for key, value in preview.items()
        if key not in {"baseRevision", "dependencies", "revision"}
    }
    assert preview["revision"] == layout_revision(preview["document"])
    assert applied["dependencies"] == preview["dependencies"]


def test_operation_preview_rejects_stale_and_unauthorized_requests(tmp_path):
    service, principal, shell, policy, _ = _service(tmp_path)
    created = service.create_layout(
        principal,
        "site-a",
        _layout(shell, policy),
    )
    before = _file_snapshot(tmp_path)

    with pytest.raises(FacilityConflictError) as stale:
        service.preview_operations(
            principal,
            "site-a",
            "fl-service-cell",
            "f" * 64,
            [_generated_placement_operation()],
        )
    assert stale.value.code == "revision_conflict"
    assert stale.value.details["currentRevision"] == created["revision"]

    with pytest.raises(FacilityLayoutError) as viewer:
        service.preview_operations(
            _principal(roles=("viewer",)),
            "site-a",
            "fl-service-cell",
            created["revision"],
            [_generated_placement_operation()],
        )
    assert viewer.value.code == "role_not_authorized"

    with pytest.raises(FacilityLayoutError) as cross_site:
        service.preview_operations(
            principal,
            "site-b",
            "fl-service-cell",
            created["revision"],
            [_generated_placement_operation()],
        )
    assert cross_site.value.code == "not_found"

    with pytest.raises(FacilityLayoutError) as cross_tenant:
        service.preview_operations(
            _principal(tenant_id="tenant-b"),
            "site-a",
            "fl-service-cell",
            created["revision"],
            [_generated_placement_operation()],
        )
    assert cross_tenant.value.code == "not_found"
    assert _file_snapshot(tmp_path) == before


def test_stale_operation_batch_writes_nothing(tmp_path):
    service, principal, shell, policy, _ = _service(tmp_path)
    created = service.create_layout(
        principal,
        "site-a",
        _layout(shell, policy),
    )

    with pytest.raises(FacilityConflictError) as raised:
        service.apply_operations(
            principal,
            "site-a",
            "fl-service-cell",
            "f" * 64,
            [_placement_operation()],
        )

    assert raised.value.code == "revision_conflict"
    current = service.get_layout(principal, "site-a", "fl-service-cell")
    assert current["revision"] == created["revision"]
    assert current["layout"]["placements"] == []


def test_dependency_failure_prevents_layout_creation(tmp_path):
    service, principal, shell, policy, _ = _service(tmp_path)
    document = _layout(shell, policy)
    document["sourceShellRef"]["coordinateFrameFingerprint"] = "0" * 64

    with pytest.raises(FacilityConflictError) as raised:
        service.create_layout(principal, "site-a", document)

    assert raised.value.code == "stale_shell_revision"
    assert service.list_layouts(principal, "site-a")["layouts"] == []


def test_unavailable_asset_resolver_fails_closed_without_save(tmp_path):
    service, principal, shell, policy, _ = _service(
        tmp_path,
        asset_resolver=None,
    )
    created = service.create_layout(
        principal,
        "site-a",
        _layout(shell, policy),
    )
    before = deepcopy(created)

    with pytest.raises(FacilityValidationError) as raised:
        service.apply_operations(
            principal,
            "site-a",
            "fl-service-cell",
            created["revision"],
            [_placement_operation()],
        )

    assert raised.value.code == "dependency_resolver_unavailable"
    current = service.get_layout(principal, "site-a", "fl-service-cell")
    assert current["revision"] == before["revision"]
    assert current["layout"]["placements"] == []


def test_browser_scope_cannot_override_principal(tmp_path):
    service, principal, shell, policy, _ = _service(tmp_path)
    document = _layout(shell, policy)
    document["association"]["siteId"] = "site-b"

    with pytest.raises(FacilityLayoutError) as raised:
        service.create_layout(principal, "site-a", document)

    assert raised.value.code == "not_found"


def test_reviewed_authority_is_not_eligible_for_layout_reference(tmp_path):
    principal = _principal()
    documents = _authority_documents()
    root = tmp_path / "authority"
    shell_repository = FacilityShellRepository(root / "shells", clock=lambda: NOW)
    policy_repository = PolicySetRepository(root / "policies", clock=lambda: NOW)
    vehicle_repository = VehicleProfileRepository(root / "vehicles", clock=lambda: NOW)
    shell_doc = deepcopy(documents["facility_shell"])
    shell_doc["status"] = "draft"
    shell_created = shell_repository.create(
        principal,
        site_id="site-a",
        document=shell_doc,
    )
    shell = shell_repository.review(
        principal,
        site_id="site-a",
        authority_id=shell_doc["shellId"],
        expected_revision=shell_created.envelope.revision,
    ).envelope
    policy = _publish(
        policy_repository,
        principal,
        documents["policy_set"],
        "policySetId",
    )
    service = FacilityLayoutService(
        layout_repository=FacilityLayoutRepository(
            tmp_path / "layouts",
            clock=lambda: NOW,
        ),
        shell_repository=shell_repository,
        policy_repository=policy_repository,
        vehicle_repository=vehicle_repository,
    )

    with pytest.raises(FacilityLayoutError) as raised:
        service.create_layout(principal, "site-a", _layout(shell, policy))

    assert raised.value.code == "not_found"


def _routing_asset(asset_id, revision):
    value = _resolved_asset(asset_id, revision)
    value["definition"]["documentKind"] = "industrial_asset_definition"
    value["definition"]["connectors"] = [
        {
            "connectorId": "material-in",
            "connectorKind": "material",
            "position": {"x": -0.5, "y": 0.5, "z": 0.0},
            "facing": {"x": -1.0, "y": 0.0, "z": 0.0},
            "role": "input",
            "allowedRouteKinds": ["material"],
            "interface": {"carrier": "pallet"},
            "evidenceStatus": "authored",
            "evidence": ["ev-material-in"],
        }
    ]
    return value


def _material_route_operations(asset_revision, base_layout):
    operations = [
        {
            "op": "add_zone",
            "zone": {
                "zoneId": "zn-inbound-route",
                "zoneType": "staging",
                "label": "Inbound route",
                "boundary": [
                    {"x": 0.0, "z": 0.0},
                    {"x": 5.0, "z": 0.0},
                    {"x": 5.0, "z": 4.0},
                    {"x": 0.0, "z": 4.0},
                ],
                "floorElevation": 0.0,
                "anchors": [
                    {
                        "anchorId": "za-material-source",
                        "anchorKind": "material",
                        "position": {"x": 0.0, "y": 0.5, "z": 2.0},
                        "facing": {"x": 1.0, "y": 0.0, "z": 0.0},
                        "allowedRouteKinds": ["material"],
                        "evidence": ["ev-staging-anchor"],
                    }
                ],
                "evidence": [],
            },
        },
        {
            "op": "place_asset",
            "placement": {
                "placementId": "pl-route-machine",
                "assetId": "asset-route-machine",
                "assetDefinitionRevision": asset_revision,
                "transform": {
                    "position": {"x": 4.0, "y": 0.0, "z": 2.0},
                    "quaternion": {
                        "x": 0.0,
                        "y": 0.0,
                        "z": 0.0,
                        "w": 1.0,
                    },
                    "scale": 1,
                },
                "positionMode": "manual",
                "snapRelationship": None,
                "metadata": {},
            },
        },
        {
            "op": "add_route",
            "route": {
                "routeId": "rt-inbound-machine",
                "routeKind": "material",
                "sourceEndpoint": {
                    "kind": "zone_anchor",
                    "zoneId": "zn-inbound-route",
                    "anchorId": "za-material-source",
                },
                "targetEndpoint": {
                    "kind": "placement_connector",
                    "placementId": "pl-route-machine",
                    "connectorId": "material-in",
                },
                "routingMode": "polyline",
                "centerline": [
                    {"x": 0.0, "y": 0.5, "z": 2.0},
                    {"x": 3.5, "y": 0.5, "z": 2.0},
                ],
                "corridorWidth": 1.0,
                "routeFingerprint": "7" * 64,
                "sourceRevisions": {},
                "requirements": [],
                "evidence": [],
            },
        },
    ]
    staged = apply_facility_layout_operations(
        base_layout,
        operations[:2],
    )["document"]
    route = operations[-1]["route"]
    route["sourceRevisions"] = {
        "layout": routing_layout_fingerprint(staged),
        "shell": staged["sourceShellRef"]["shellRevision"],
        "policy": staged["policySetRef"]["policySetRevision"],
    }
    route["routeFingerprint"] = persisted_route_fingerprint(route)
    return operations


def test_route_transaction_connector_candidates_and_process_binding(tmp_path):
    process_state = {"revision": "6" * 64}

    def resolve_process(_principal, _site, _product, _map_id, _revision):
        return {
            "revision": process_state["revision"],
            "document": {
                "canvasNodes": [{"id": "node-op"}],
                "canvasEdges": [{"id": "edge-flow"}],
            },
        }

    service, principal, shell, policy, _ = _service(
        tmp_path,
        asset_resolver=(
            lambda _p, _s, asset_id, revision: _routing_asset(
                asset_id,
                revision,
            )
        ),
        process_map_resolver=resolve_process,
    )
    created = service.create_layout(
        principal,
        "site-a",
        _layout(shell, policy),
    )
    asset_revision = "e" * 64
    applied = service.apply_operations(
        principal,
        "site-a",
        "fl-service-cell",
        created["revision"],
        _material_route_operations(asset_revision, created["layout"]),
    )
    assert applied["routingDiagnostics"]["valid"] is True
    assert applied["routingDiagnostics"]["metrics"]["routeCount"] == 1

    candidates = service.connector_candidates(
        principal,
        "site-a",
        "fl-service-cell",
        applied["revision"],
        {
            "routeKind": "material",
            "sourceEndpoint": {
                "kind": "zone_anchor",
                "zoneId": "zn-inbound-route",
                "anchorId": "za-material-source",
            },
        },
    )
    assert [
        item["targetQualifiedEndpointId"]
        for item in candidates["candidates"]
    ] == ["placement:pl-route-machine:material-in"]

    bound = service.apply_operations(
        principal,
        "site-a",
        "fl-service-cell",
        applied["revision"],
        [
            {
                "op": "attach_process_binding",
                "processBinding": {
                    "processBindingId": "pb-route-machine",
                    "productId": "product-demo",
                    "processMapId": "pm-demo",
                    "processMapRevision": process_state["revision"],
                    "processNodeIds": ["node-op"],
                    "processEdgeIds": ["edge-flow"],
                    "placementIds": ["pl-route-machine"],
                    "routeIds": ["rt-inbound-machine"],
                    "bindingRole": "material_flow",
                },
            }
        ],
    )
    assert bound["routingDiagnostics"]["valid"] is True
    assert bound["dependencies"]["processMapRevisions"] == [
        {
            "productId": "product-demo",
            "processMapId": "pm-demo",
            "processMapRevision": "6" * 64,
        }
    ]

    process_state["revision"] = "9" * 64
    with pytest.raises(FacilityConflictError) as stale:
        service.preview_operations(
            principal,
            "site-a",
            "fl-service-cell",
            bound["revision"],
            [{"op": "rename_layout", "displayName": "Must not preview"}],
        )
    assert stale.value.code == "stale_process_map_revision"


def test_process_binding_missing_targets_and_route_geometry_fail_closed(tmp_path):
    def resolve_process(_principal, _site, _product, _map_id, revision):
        return {
            "revision": revision,
            "document": {
                "canvasNodes": [{"id": "node-existing"}],
                "canvasEdges": [],
            },
        }

    service, principal, shell, policy, _ = _service(
        tmp_path,
        asset_resolver=(
            lambda _p, _s, asset_id, revision: _routing_asset(
                asset_id,
                revision,
            )
        ),
        process_map_resolver=resolve_process,
    )
    created = service.create_layout(
        principal,
        "site-a",
        _layout(shell, policy),
    )
    operations = _material_route_operations(
        "e" * 64,
        created["layout"],
    )
    operations[-1]["route"]["centerline"][0]["x"] = 1.0
    operations[-1]["route"]["routeFingerprint"] = (
        persisted_route_fingerprint(operations[-1]["route"])
    )
    with pytest.raises(FacilityValidationError) as route_error:
        service.preview_operations(
            principal,
            "site-a",
            "fl-service-cell",
            created["revision"],
            operations,
        )
    assert route_error.value.code == "routing_validation_failed"
    assert {
        item["code"] for item in route_error.value.details["findings"]
    } == {"route_endpoint_geometry_mismatch"}

    applied = service.apply_operations(
        principal,
        "site-a",
        "fl-service-cell",
        created["revision"],
        _material_route_operations("e" * 64, created["layout"]),
    )
    with pytest.raises(FacilityValidationError) as binding_error:
        service.preview_operations(
            principal,
            "site-a",
            "fl-service-cell",
            applied["revision"],
            [
                {
                    "op": "attach_process_binding",
                    "processBinding": {
                        "processBindingId": "pb-bad-target",
                        "productId": "product-demo",
                        "processMapId": "pm-demo",
                        "processMapRevision": "6" * 64,
                        "processNodeIds": ["node-missing"],
                        "processEdgeIds": ["edge-missing"],
                        "placementIds": ["pl-route-machine"],
                        "routeIds": ["rt-inbound-machine"],
                        "bindingRole": "material_flow",
                    },
                }
            ],
        )
    assert binding_error.value.code == "routing_validation_failed"
    assert {
        item["code"] for item in binding_error.value.details["findings"]
    } == {
        "dangling_process_binding_node",
        "dangling_process_binding_edge",
    }


def test_service_plans_forklift_route_from_trusted_zone_anchors(tmp_path):
    service, principal, shell, policy, vehicle = _service(tmp_path)
    layout = _layout(shell, policy)
    aisle = {
        "zoneId": "zn-forklift-aisle",
        "zoneType": "aisle",
        "label": "Main forklift aisle",
        "boundary": [
            {"x": 0.0, "z": 0.0},
            {"x": 15.0, "z": 0.0},
            {"x": 15.0, "z": 6.0},
            {"x": 0.0, "z": 6.0},
        ],
        "floorElevation": 0.0,
        "anchors": [
            {
                "anchorId": "za-forklift-start",
                "anchorKind": "forklift",
                "position": {"x": 2.0, "y": 0.0, "z": 3.0},
                "facing": {"x": 1.0, "y": 0.0, "z": 0.0},
                "allowedRouteKinds": ["forklift"],
                "evidence": ["ev-aisle"],
            },
            {
                "anchorId": "za-forklift-end",
                "anchorKind": "forklift",
                "position": {"x": 12.0, "y": 0.0, "z": 3.0},
                "facing": {"x": -1.0, "y": 0.0, "z": 0.0},
                "allowedRouteKinds": ["forklift"],
                "evidence": ["ev-aisle"],
            },
        ],
        "evidence": ["ev-aisle"],
    }
    layout["zones"].append(aisle)
    created = service.create_layout(principal, "site-a", layout)

    result = service.plan_forklift_route(
        principal,
        "site-a",
        "fl-service-cell",
        created["revision"],
        {
            "sourceEndpoint": {
                "kind": "zone_anchor",
                "zoneId": "zn-forklift-aisle",
                "anchorId": "za-forklift-start",
            },
            "targetEndpoint": {
                "kind": "zone_anchor",
                "zoneId": "zn-forklift-aisle",
                "anchorId": "za-forklift-end",
            },
            "vehicleProfileRef": {
                "vehicleProfileId": vehicle.document["vehicleProfileId"],
                "vehicleProfileRevision": vehicle.revision,
            },
            "allowReverse": False,
        },
    )
    assert result["accepted"] is True
    assert result["sweptVolume"]["valid"] is True
    assert result["sourceEndpoint"]["anchorId"] == "za-forklift-start"
    assert result["sourceRevisions"]["layout"] == created["revision"]


def test_service_validates_manual_operator_path_without_mutating_layout(tmp_path):
    def actor_resolver(_principal_value, _site_id, asset_id, revision):
        resolved = _resolved_asset(asset_id, revision)
        if asset_id == "asset-operator":
            resolved["definition"]["category"] = "operators"
        return resolved

    service, principal, shell, policy, _vehicle = _service(
        tmp_path,
        asset_resolver=actor_resolver,
    )
    layout = _layout(shell, policy, layout_id="fl-manual-navigation")
    actor = deepcopy(_placement_operation()["placement"])
    actor.update({
        "placementId": "pl-operator-manual",
        "assetId": "asset-operator",
    })
    actor["transform"]["position"].update({"x": 2.0, "z": 2.0})
    layout["placements"].append(actor)
    created = service.create_layout(principal, "site-a", layout)

    result = service.validate_manual_navigation_path(
        principal,
        "site-a",
        "fl-manual-navigation",
        created["revision"],
        {
            "actorPlacementId": "pl-operator-manual",
            "actorClass": "pedestrian",
            "actorProfileRef": {
                "profileKind": "pedestrian",
                "profileId": "pedestrian-profile:asset-operator",
                "profileRevision": actor["assetDefinitionRevision"],
            },
            "constraintMode": "complete_override",
            "direction": "forward",
            "points": [{"x": 2, "z": 2}, {"x": 12, "z": 2}],
        },
    )
    after = service.get_layout(
        principal,
        "site-a",
        "fl-manual-navigation",
    )
    assert result["valid"] is True
    assert result["mutated"] is False
    assert after["revision"] == created["revision"]
    assert after["layout"] == created["layout"]

    with pytest.raises(FacilityValidationError) as mismatch:
        service.validate_manual_navigation_path(
            principal,
            "site-a",
            "fl-manual-navigation",
            created["revision"],
            {
                "actorPlacementId": "pl-operator-manual",
                "actorClass": "vehicle",
                "actorProfileRef": {
                    "profileKind": "vehicle",
                    "profileId": "vehicle-forklift-a",
                    "profileRevision": "a" * 64,
                },
                "constraintMode": "complete_override",
                "direction": "forward",
                "points": [{"x": 2, "z": 2}, {"x": 12, "z": 2}],
            },
        )
    assert mismatch.value.code == "facility_navigation_actor_class_mismatch"


def test_service_requires_explicit_mode_for_prototype_vehicle_path(tmp_path):
    def actor_resolver(_principal_value, _site_id, asset_id, revision):
        resolved = _resolved_asset(asset_id, revision)
        if asset_id == "asset-forklift-navigation":
            resolved["definition"]["category"] = "vehicle"
        return resolved

    placement_operation = _placement_operation()
    placement_operation["placement"].update({
        "placementId": "pl-forklift-navigation",
        "assetId": "asset-forklift-navigation",
    })
    placement_operation["placement"]["transform"]["position"].update({
        "x": 2.0,
        "z": 2.0,
    })
    vehicle_asset_ref = {
        "assetId": "asset-forklift-navigation",
        "assetDefinitionRevision": placement_operation["placement"][
            "assetDefinitionRevision"
        ],
    }
    service, principal, shell, policy, vehicle = _service(
        tmp_path,
        asset_resolver=actor_resolver,
        prototype_vehicle=True,
        vehicle_asset_ref=vehicle_asset_ref,
        allow_prototype_motion=True,
    )
    layout = _layout(shell, policy, layout_id="fl-prototype-navigation")
    layout = apply_facility_layout_operations(
        layout,
        [placement_operation],
        base_revision=None,
    )["document"]
    created = service.create_layout(principal, "site-a", layout)
    request = {
        "actorPlacementId": "pl-forklift-navigation",
        "actorClass": "vehicle",
        "actorProfileRef": {
            "profileKind": "vehicle",
            "profileId": vehicle.document["vehicleProfileId"],
            "profileRevision": vehicle.revision,
        },
        "constraintMode": "complete_override",
        "direction": "forward",
        "points": [{"x": 2, "z": 2}, {"x": 12, "z": 2}],
    }
    with pytest.raises(FacilityNotFoundError):
        service.validate_manual_navigation_path(
            principal,
            "site-a",
            "fl-prototype-navigation",
            created["revision"],
            request,
        )

    result = service.validate_manual_navigation_path(
        principal,
        "site-a",
        "fl-prototype-navigation",
        created["revision"],
        {**request, "prototypeMode": True},
    )
    assert result["prototypeMode"] is True
    assert result["productionEligible"] is False
    assert result["prototypeLabel"] == "Prototype motion test profile"
    assert "not production eligible" in result["qualification"]
    assert result["mutated"] is False


def test_service_builds_and_revision_gates_browser_motion_package(tmp_path):
    vehicle_placement_operation = _placement_operation()
    vehicle_placement_operation["placement"]["transform"]["position"].update(
        {"x": 24.0, "z": 10.0}
    )
    vehicle_asset_ref = {
        "assetId": vehicle_placement_operation["placement"]["assetId"],
        "assetDefinitionRevision": vehicle_placement_operation["placement"][
            "assetDefinitionRevision"
        ],
    }
    service, principal, shell, policy, vehicle = _service(
        tmp_path,
        prototype_vehicle=True,
        vehicle_asset_ref=vehicle_asset_ref,
        allow_prototype_motion=True,
    )
    layout = _layout(shell, policy, layout_id="fl-motion-service")
    layout["zones"].append(
        {
            "zoneId": "zn-motion-aisle",
            "zoneType": "aisle",
            "label": "Motion aisle",
            "boundary": [
                {"x": 0.0, "z": 0.0},
                {"x": 16.0, "z": 0.0},
                {"x": 16.0, "z": 6.0},
                {"x": 0.0, "z": 6.0},
            ],
            "floorElevation": 0.0,
            "anchors": [],
            "evidence": ["ev-motion-aisle"],
        }
    )
    layout = apply_facility_layout_operations(
        layout,
        [vehicle_placement_operation],
        base_revision=None,
    )["document"]
    created = service.create_layout(
        principal,
        "site-a",
        layout,
    )
    route = {
        "routeId": "rt-motion-main",
        "routeKind": "material",
        "sourceEndpoint": {
            "kind": "world_point",
            "position": {"x": 2.0, "y": 0.0, "z": 3.0},
        },
        "targetEndpoint": {
            "kind": "world_point",
            "position": {"x": 14.0, "y": 0.0, "z": 3.0},
        },
        "routingMode": "vehicle",
        "centerline": [
            {"x": 2.0, "y": 0.0, "z": 3.0},
            {"x": 14.0, "y": 0.0, "z": 3.0},
        ],
        "corridorWidth": 6.0,
        "routeFingerprint": "0" * 64,
        "sourceRevisions": {
            "layout": routing_layout_fingerprint(created["layout"]),
            "shell": shell.revision,
            "policy": policy.revision,
        },
        "requirements": [],
        "evidence": [],
    }
    route["routeFingerprint"] = persisted_route_fingerprint(route)
    routed = service.apply_operations(
        principal,
        "site-a",
        "fl-motion-service",
        created["revision"],
        [{"op": "add_route", "route": route}],
    )
    motion_request = {
        "routeId": "rt-motion-main",
        "vehicleProfileRef": {
            "vehicleProfileId": vehicle.document["vehicleProfileId"],
            "vehicleProfileRevision": vehicle.revision,
        },
    }
    service.allow_prototype_motion = False
    with pytest.raises(FacilityLayoutError) as denied:
        service.build_forklift_motion_package(
            principal,
            "site-a",
            "fl-motion-service",
            routed["revision"],
            motion_request,
        )
    assert denied.value.code == "not_found"
    service.allow_prototype_motion = True
    summary = service.build_forklift_motion_package(
        principal,
        "site-a",
        "fl-motion-service",
        routed["revision"],
        motion_request,
    )

    assert summary["summary"]["outcome"] == "accepted"
    assert "poses" not in summary["summary"]
    full = service.get_forklift_motion_package(
        principal,
        "site-a",
        "fl-motion-service",
        summary["packageId"],
        active_revision=summary["layoutRevision"],
    )
    assert full["package"]["movement"]["outcome"] == "accepted"
    assert full["vehicleProfile"]["vehicleProfileId"] == vehicle.document[
        "vehicleProfileId"
    ]
    assert full["vehicleProfile"]["vehicleProfileRevision"] == vehicle.revision
    assert full["prototypeMode"] is True
    assert full["prototypeLabel"] == "Prototype motion test profile"
    assert full["vehicleProfile"]["productionEligible"] is False

    placed = routed
    actual_request = deepcopy(motion_request)
    actual_request["vehiclePlacementId"] = vehicle_placement_operation[
        "placement"
    ]["placementId"]
    actual_summary = service.build_forklift_motion_package(
        principal,
        "site-a",
        "fl-motion-service",
        placed["revision"],
        actual_request,
    )
    actual_full = service.get_forklift_motion_package(
        principal,
        "site-a",
        "fl-motion-service",
        actual_summary["packageId"],
        active_revision=actual_summary["layoutRevision"],
    )
    assert actual_full["package"]["movement"]["vehiclePlacementId"] == (
        vehicle_placement_operation["placement"]["placementId"]
    )
    with pytest.raises(FacilityConflictError) as caught:
        service.get_forklift_motion_package(
            principal,
            "site-a",
            "fl-motion-service",
            summary["packageId"],
            active_revision="stale-revision",
        )
    assert caught.value.code == "facility_motion_package_stale"


def test_service_rejects_vehicle_placement_profile_asset_mismatch(tmp_path):
    service, principal, shell, policy, vehicle = _service(
        tmp_path,
        prototype_vehicle=True,
        vehicle_asset_ref={
            "assetId": "asset-other-vehicle",
            "assetDefinitionRevision": "f" * 64,
        },
        allow_prototype_motion=True,
    )
    layout = _layout(shell, policy, layout_id="fl-motion-binding")
    layout["zones"].append({
        "zoneId": "zn-motion-binding-aisle",
        "zoneType": "aisle",
        "label": "Motion binding aisle",
        "boundary": [
            {"x": 0.0, "z": 0.0},
            {"x": 16.0, "z": 0.0},
            {"x": 16.0, "z": 6.0},
            {"x": 0.0, "z": 6.0},
        ],
        "floorElevation": 0.0,
        "anchors": [],
        "evidence": [],
    })
    vehicle_operation = _placement_operation()
    vehicle_operation["placement"]["transform"]["position"].update(
        {"x": 24.0, "z": 10.0}
    )
    layout = apply_facility_layout_operations(
        layout,
        [vehicle_operation],
        base_revision=None,
    )["document"]
    created = service.create_layout(principal, "site-a", layout)
    route = {
        "routeId": "rt-motion-binding",
        "routeKind": "material",
        "sourceEndpoint": {
            "kind": "world_point",
            "position": {"x": 2.0, "y": 0.0, "z": 3.0},
        },
        "targetEndpoint": {
            "kind": "world_point",
            "position": {"x": 14.0, "y": 0.0, "z": 3.0},
        },
        "routingMode": "vehicle",
        "centerline": [
            {"x": 2.0, "y": 0.0, "z": 3.0},
            {"x": 14.0, "y": 0.0, "z": 3.0},
        ],
        "corridorWidth": 6.0,
        "routeFingerprint": "0" * 64,
        "sourceRevisions": {
            "layout": routing_layout_fingerprint(created["layout"]),
            "shell": shell.revision,
            "policy": policy.revision,
        },
        "requirements": [],
        "evidence": [],
    }
    route["routeFingerprint"] = persisted_route_fingerprint(route)
    routed = service.apply_operations(
        principal,
        "site-a",
        "fl-motion-binding",
        created["revision"],
        [{"op": "add_route", "route": route}],
    )
    with pytest.raises(FacilityValidationError) as caught:
        service.build_forklift_motion_package(
            principal,
            "site-a",
            "fl-motion-binding",
            routed["revision"],
            {
                "routeId": "rt-motion-binding",
                "vehicleProfileRef": {
                    "vehicleProfileId": vehicle.document["vehicleProfileId"],
                    "vehicleProfileRevision": vehicle.revision,
                },
                "vehiclePlacementId": vehicle_operation["placement"][
                    "placementId"
                ],
            },
        )
    assert caught.value.code == "facility_motion_vehicle_asset_binding_mismatch"


def test_routing_differential_keeps_distinct_subjects():
    baseline = {
        "findings": [
            {
                "code": "route_endpoint_geometry_mismatch",
                "severity": "error",
                "subjects": ["rt-existing", "source"],
            }
        ]
    }
    candidate = {
        "findings": [
            *baseline["findings"],
            {
                "code": "route_endpoint_geometry_mismatch",
                "severity": "error",
                "subjects": ["rt-new", "source"],
            },
        ]
    }
    with pytest.raises(FacilityValidationError) as caught:
        FacilityLayoutService._require_no_new_routing_errors(
            baseline,
            candidate,
        )
    assert caught.value.code == "routing_validation_failed"
    assert caught.value.details["findings"][0]["subjects"] == [
        "rt-new",
        "source",
    ]


def test_process_map_dependency_requires_reported_revision(tmp_path):
    service, principal, shell, policy, _ = _service(
        tmp_path,
        process_map_resolver=lambda *_args: True,
    )
    created = service.create_layout(
        principal,
        "site-a",
        _layout(shell, policy),
    )
    with pytest.raises(FacilityValidationError) as caught:
        service.preview_operations(
            principal,
            "site-a",
            "fl-service-cell",
            created["revision"],
            [
                {
                    "op": "attach_process_binding",
                    "processBinding": {
                        "processBindingId": "pb-unverified",
                        "productId": "product-demo",
                        "processMapId": "pm-demo",
                        "processMapRevision": "6" * 64,
                        "processNodeIds": ["node-op"],
                        "processEdgeIds": [],
                        "placementIds": [],
                        "routeIds": [],
                        "bindingRole": "resource",
                    },
                }
            ],
        )
    assert caught.value.code == "process_map_revision_unverified"


def test_process_binding_role_rejects_junction_as_assigned_work(tmp_path):
    revision = "6" * 64

    def resolve_process(_principal, _site, _product, _map_id, _revision):
        return {
            "revision": revision,
            "document": {
                "canvasNodes": [{"id": "node-junction", "type": "junction"}],
                "canvasEdges": [],
            },
        }

    service, principal, shell, policy, _ = _service(
        tmp_path,
        asset_resolver=(
            lambda _p, _s, asset_id, asset_revision: _routing_asset(
                asset_id,
                asset_revision,
            )
        ),
        process_map_resolver=resolve_process,
    )
    created = service.create_layout(
        principal,
        "site-a",
        _layout(shell, policy),
    )
    asset_revision = "e" * 64
    placed = service.apply_operations(
        principal,
        "site-a",
        "fl-service-cell",
        created["revision"],
        _material_route_operations(asset_revision, created["layout"])[:2],
    )
    with pytest.raises(FacilityValidationError) as caught:
        service.preview_operations(
            principal,
            "site-a",
            "fl-service-cell",
            placed["revision"],
            [
                {
                    "op": "attach_process_binding",
                    "processBinding": {
                        "processBindingId": "pb-junction-work",
                        "productId": "product-demo",
                        "processMapId": "pm-demo",
                        "processMapRevision": revision,
                        "processNodeIds": ["node-junction"],
                        "processEdgeIds": [],
                        "placementIds": ["pl-route-machine"],
                        "routeIds": [],
                        "bindingRole": "resource",
                    },
                }
            ],
        )
    assert caught.value.code == "routing_validation_failed"
    assert {
        item["code"] for item in caught.value.details["findings"]
    } == {"process_binding_semantics_invalid"}


def test_service_compiles_bounded_navigation_snapshot_and_isolates_package(
    tmp_path,
    monkeypatch,
):
    def actor_resolver(_principal, _site_id, asset_id, revision):
        resolved = _resolved_asset(asset_id, revision)
        if asset_id == "asset-operator":
            resolved["definition"]["category"] = "people"
        return resolved

    service, principal, shell, policy, _vehicle = _service(
        tmp_path,
        asset_resolver=actor_resolver,
    )
    layout = _layout(shell, policy, layout_id="fl-navigation-snapshot")
    layout["zones"] = [{
        "zoneId": "zn-navigation-cell",
        "zoneType": "workcell",
        "label": "Navigation cell",
        "boundary": [
            {"x": 0.0, "z": 0.0}, {"x": 12.0, "z": 0.0},
            {"x": 12.0, "z": 8.0}, {"x": 0.0, "z": 8.0},
        ],
        "floorElevation": 0.0,
        "anchors": [],
        "evidence": [],
    }]
    layout["placements"] = [
        {
            "placementId": "pl-nav-operator",
            "assetId": "asset-operator",
            "assetDefinitionRevision": "e" * 64,
            "transform": {
                "position": {"x": 2.0, "y": 0.0, "z": 2.0},
                "quaternion": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
                "scale": 1,
            },
            "positionMode": "manual",
            "snapRelationship": None,
            "metadata": {},
        },
        {
            "placementId": "pl-nav-station",
            "assetId": "asset-machine",
            "assetDefinitionRevision": "f" * 64,
            "transform": {
                "position": {"x": 8.0, "y": 0.0, "z": 4.0},
                "quaternion": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
                "scale": 1,
            },
            "positionMode": "manual",
            "snapRelationship": None,
            "metadata": {},
        },
    ]
    layout.setdefault("extensions", {})["facilityNavigation"] = {
        "schemaVersion": 1,
        "anchors": [
            {
                "navigationAnchorId": "na-nav-home",
                "anchorKind": "actor_home",
                "ownerRef": {"ownerKind": "placement", "ownerId": "pl-nav-operator"},
                "interactionKind": "none",
                "positionAuthority": "ui_authored",
                "localPosition": {"x": 2.0, "z": 2.0},
                "derivedPositionRef": None,
                "approachDirections": ["any"],
                "actorClasses": ["pedestrian"],
                "evidenceStatus": "authored",
                "evidence": ["ev-nav-pointer"],
                "reviewStatus": "pending",
            },
            {
                "navigationAnchorId": "na-nav-work",
                "anchorKind": "station_operate",
                "ownerRef": {"ownerKind": "placement", "ownerId": "pl-nav-station"},
                "interactionKind": "operate",
                "positionAuthority": "ui_authored",
                "localPosition": {"x": 6.5, "z": 4.0},
                "derivedPositionRef": None,
                "approachDirections": ["any"],
                "actorClasses": ["pedestrian"],
                "evidenceStatus": "authored",
                "evidence": ["ev-nav-pointer"],
                "reviewStatus": "pending",
            },
        ],
        "movementPrograms": [{
            "movementProgramId": "nmp-nav-cycle",
            "actorPlacementId": "pl-nav-operator",
            "actorClass": "pedestrian",
            "actorProfileRef": {
                "profileKind": "pedestrian",
                "profileId": "operator-profile:asset-operator",
                "profileRevision": "e" * 64,
            },
            "orderedStops": [
                {"stopId": "nst-nav-home", "navigationAnchorId": "na-nav-home", "interactionKind": "none", "required": True},
                {"stopId": "nst-nav-work", "navigationAnchorId": "na-nav-work", "interactionKind": "operate", "required": True},
            ],
            "loopMode": "out_and_return",
            "requiredRouteIds": [],
            "requiredAnchorIds": ["na-nav-home", "na-nav-work"],
            "forbiddenZoneIds": [],
            "forbiddenRouteIds": [],
            "manualPathConstraintIds": [],
            "handoffProgramIds": [],
            "sourceRevisions": {"layout": "0" * 64},
            "evidenceStatus": "authored",
            "evidence": ["ev-nav-pointer"],
            "reviewStatus": "pending",
        }],
        "manualPathConstraints": [],
        "handoffPrograms": [],
    }
    created = service.create_layout(principal, "site-a", layout)

    result = service.compile_navigation_snapshot(
        principal, "site-a", "fl-navigation-snapshot", created["revision"],
        {"movementProgramId": "nmp-nav-cycle"},
    )
    assert result["mutated"] is False
    assert result["actorPlacementId"] == "pl-nav-operator"
    assert result["summary"]["canonicalBytes"] <= 8192
    assert "freeSpacePolygons" not in result["summary"]
    package_id = result["summary"]["navigationPackageId"]
    package = service.get_navigation_snapshot_package(
        principal, "site-a", "fl-navigation-snapshot", package_id,
    )
    assert package["navigationPackageId"] == package_id
    assert package["canonicalBytes"] == len(json.dumps(
        package, allow_nan=False, ensure_ascii=True,
        separators=(",", ":"), sort_keys=True,
    ).encode("ascii"))

    planned = service.plan_actor_journey(
        principal,
        "site-a",
        "fl-navigation-snapshot",
        created["revision"],
        {
            "navigationPackageId": package_id,
            "movementProgramId": "nmp-nav-cycle",
        },
    )
    assert planned["mutated"] is False
    assert planned["summary"]["outcome"] == "accepted"
    assert "centerline" not in planned["summary"]
    journey_id = planned["summary"]["journeySolutionId"]
    full_journey = service.get_actor_journey(
        principal, "site-a", "fl-navigation-snapshot", journey_id,
    )
    assert full_journey["journeySolutionId"] == journey_id
    assert full_journey["actorPlacementId"] == "pl-nav-operator"

    from ai_inspector.facility_layout import service as service_module
    monkeypatch.setattr(
        service_module,
        "activity_visual_alignment",
        lambda _ref: {
            "forwardAxis": "+Z",
            "authority": "curated_revision_bound_visual_review",
            "evidenceArtifact": "tests/fixtures/operator-forward-axis-v1.json",
        },
    )
    activity = service.build_navigation_activity_scenario(
        principal,
        "site-a",
        "fl-navigation-snapshot",
        created["revision"],
        {
            "journeySolutionIds": [journey_id],
            "handoffResultIds": [],
            "scenarioLabel": "Navigation service proof",
            "prototypeMode": True,
        },
    )
    assert activity["mutated"] is False
    assert activity["summary"]["actorCount"] == 1
    assert activity["summary"]["navigationDiagnostics"] == {
        "pathBindingCount": 1,
        "pathIntersectionCount": 0,
        "sampledPairCount": 0,
        "handoffResultCount": 0,
        "generatedCollisionAvoidanceOffsets": False,
    }
    full_activity = service.get_prototype_activity_scenario(
        principal,
        "site-a",
        "fl-navigation-snapshot",
        activity["scenarioId"],
        active_revision=created["revision"],
    )
    assert full_activity["scenario"]["schemaVersion"] == (
        "facility-activity-scenario-v7"
    )
    motion_payload = next(iter(full_activity["actorPayloads"].values()))
    assert motion_payload["package"]["schemaVersion"] == (
        "facility-motion-package-v3"
    )
    assert motion_payload["actorProfile"]["geometryAuthority"] == (
        "catalog_revision_bound"
    )

    with pytest.raises(FacilityValidationError) as journey_geometry_error:
        service.plan_actor_journey(
            principal,
            "site-a",
            "fl-navigation-snapshot",
            created["revision"],
            {
                "navigationPackageId": package_id,
                "movementProgramId": "nmp-nav-cycle",
                "waypoints": [{"x": 1, "z": 1}],
            },
        )
    assert journey_geometry_error.value.code == (
        "facility_navigation_journey_unknown_field"
    )

    with pytest.raises(FacilityValidationError) as geometry_error:
        service.compile_navigation_snapshot(
            principal, "site-a", "fl-navigation-snapshot", created["revision"],
            {"movementProgramId": "nmp-nav-cycle", "points": [{"x": 1, "z": 1}]},
        )
    assert geometry_error.value.code == "facility_navigation_snapshot_unknown_field"

    with pytest.raises(FacilityConflictError) as stale:
        service.compile_navigation_snapshot(
            principal, "site-a", "fl-navigation-snapshot", "1" * 64,
            {"movementProgramId": "nmp-nav-cycle"},
        )
    assert stale.value.code == "revision_conflict"

    with pytest.raises(FacilityNotFoundError) as wrong_owner:
        service.get_navigation_snapshot_package(
            principal, "site-a", "fl-other-layout", package_id,
        )
    assert wrong_owner.value.code == "facility_navigation_package_unavailable"
