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
from ai_inspector.facility_layout.errors import (
    FacilityConflictError,
    FacilityLayoutError,
    FacilityValidationError,
)
from ai_inspector.facility_layout.operations import create_layout_document
from ai_inspector.facility_layout.repository import FacilityLayoutRepository
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


def _service(tmp_path, *, asset_resolver=_default_asset_resolver):
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
        if key not in {"baseRevision", "dependencies"}
    }
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
