from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from ai_inspector.facility_layout.authorization import (
    FacilityNotFoundError,
    FacilityPrincipal,
    FacilityRoleNotAuthorizedError,
)
from ai_inspector.facility_layout.authority_repository import (
    AuthorityConflictError,
    AuthorityIntegrityError,
    AuthorityValidationError,
    AuthorityWriteError,
    FacilityShellRepository,
    PolicySetRepository,
    RevisionedAuthorityRepository,
    VehicleProfileRepository,
    authority_revision,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "p0_authority_documents.json"
)


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 29, 1, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        result = self.value
        self.value += timedelta(seconds=1)
        return result


def _fixture(kind: str, *, tenant: str = "tenant-a", site: str = "site-a") -> dict:
    documents = json.loads(FIXTURE_PATH.read_text(encoding="ascii"))
    value = next(item for item in documents if item["documentKind"] == kind)
    value["tenantId"] = tenant
    value["siteId"] = site
    value["status"] = "draft"
    value["futureCompatibleField"] = {
        "owner": "test",
        "nested": {"kept": True},
    }
    return value


def _principal(
    *,
    tenant: str = "tenant-a",
    sites: tuple[str, ...] = ("site-a",),
    roles: tuple[str, ...] = ("authority_curator",),
) -> FacilityPrincipal:
    return FacilityPrincipal(
        principal_id=f"principal-{tenant}",
        tenant_id=tenant,
        allowed_site_ids=sites,
        roles=roles,
    )


@pytest.mark.parametrize(
    ("repository_type", "document_kind", "id_field"),
    (
        (FacilityShellRepository, "facility_shell", "shellId"),
        (PolicySetRepository, "policy_set", "policySetId"),
        (VehicleProfileRepository, "vehicle_profile", "vehicleProfileId"),
    ),
)
def test_wrappers_create_exact_immutable_revisions_and_preserve_unknown_fields(
    tmp_path,
    repository_type,
    document_kind,
    id_field,
):
    repository = repository_type(tmp_path / "authority", clock=_Clock())
    principal = _principal()
    document = _fixture(document_kind)

    result = repository.create(
        principal,
        site_id="site-a",
        document=document,
    )

    assert result.changed is True
    assert result.envelope.revision == authority_revision(document)
    assert result.envelope.current_revision == result.envelope.revision
    assert result.envelope.published_revision is None
    assert result.envelope.document["futureCompatibleField"] == document[
        "futureCompatibleField"
    ]
    assert all(
        field not in result.envelope.document
        for field in (
            "shellRevision",
            "policySetRevision",
            "vehicleProfileRevision",
        )
    )
    assert repository.list_documents(principal, site_id="site-a") == [
        {
            id_field: document[id_field],
            "status": "draft",
            "currentRevision": result.envelope.revision,
            "publishedRevision": None,
            "createdAt": "2026-07-29T01:00:00Z",
            "updatedAt": "2026-07-29T01:00:00Z",
        }
    ]

    revision_path = repository._revision_path(
        "tenant-a",
        "site-a",
        document[id_field],
        result.envelope.revision,
    )
    raw = repository._read_bytes(
        revision_path,
        maximum=100 * 1024 * 1024,
    )
    raw.decode("ascii")
    assert not raw.endswith(b"\n")
    assert json.loads(raw.decode("ascii")) == document


def test_draft_edit_is_cas_bound_and_noop_is_byte_stable(tmp_path):
    repository = FacilityShellRepository(tmp_path / "authority", clock=_Clock())
    principal = _principal()
    document = _fixture("facility_shell")
    created = repository.create(principal, site_id="site-a", document=document)
    registry_path = repository._registry_path("tenant-a", "site-a")

    before = registry_path.read_bytes()
    noop = repository.save_draft(
        principal,
        site_id="site-a",
        document=deepcopy(document),
        expected_revision=created.envelope.revision,
    )
    assert noop.changed is False
    assert registry_path.read_bytes() == before

    updated_document = deepcopy(document)
    updated_document["futureCompatibleField"]["nested"]["newValue"] = 7
    updated = repository.save_draft(
        principal,
        site_id="site-a",
        document=updated_document,
        expected_revision=created.envelope.revision,
    )
    assert updated.changed is True
    assert updated.envelope.revision != created.envelope.revision
    assert updated.envelope.document["futureCompatibleField"] == updated_document[
        "futureCompatibleField"
    ]

    with pytest.raises(AuthorityConflictError) as captured:
        repository.save_draft(
            principal,
            site_id="site-a",
            document=updated_document,
            expected_revision=created.envelope.revision,
        )
    assert captured.value.code == "revision_conflict"
    assert captured.value.current_revision == updated.envelope.revision


def test_conservative_lifecycle_and_revision_addressability(tmp_path):
    repository = PolicySetRepository(tmp_path / "authority", clock=_Clock())
    principal = _principal()
    document = _fixture("policy_set")
    created = repository.create(principal, site_id="site-a", document=document)

    with pytest.raises(FacilityNotFoundError):
        repository.get_published(
            principal,
            site_id="site-a",
            authority_id=document["policySetId"],
        )
    with pytest.raises(AuthorityValidationError) as captured:
        repository.publish(
            principal,
            site_id="site-a",
            authority_id=document["policySetId"],
            expected_revision=created.envelope.revision,
        )
    assert captured.value.code == "invalid_lifecycle_transition"

    reviewed = repository.review(
        principal,
        site_id="site-a",
        authority_id=document["policySetId"],
        expected_revision=created.envelope.revision,
    )
    published = repository.publish(
        principal,
        site_id="site-a",
        authority_id=document["policySetId"],
        expected_revision=reviewed.envelope.revision,
    )
    resolved = repository.get_published(
        principal,
        site_id="site-a",
        authority_id=document["policySetId"],
        revision=published.envelope.revision,
    )
    assert resolved.status == "published"
    assert resolved.revision == published.envelope.revision

    draft = repository.get_revision(
        principal,
        site_id="site-a",
        authority_id=document["policySetId"],
        revision=created.envelope.revision,
    )
    old_review = repository.get_revision(
        principal,
        site_id="site-a",
        authority_id=document["policySetId"],
        revision=reviewed.envelope.revision,
    )
    assert draft.status == "draft"
    assert old_review.status == "reviewed"

    archived = repository.archive(
        principal,
        site_id="site-a",
        authority_id=document["policySetId"],
        expected_revision=published.envelope.revision,
    )
    assert archived.envelope.status == "archived"
    assert archived.envelope.published_revision == published.envelope.revision
    with pytest.raises(FacilityNotFoundError):
        repository.get_published(
            principal,
            site_id="site-a",
            authority_id=document["policySetId"],
        )
    assert repository.get_revision(
        principal,
        site_id="site-a",
        authority_id=document["policySetId"],
        revision=published.envelope.revision,
    ).status == "published"
    assert not hasattr(repository, "delete")


def test_deprecated_authority_is_not_eligible_for_new_references(tmp_path):
    repository = VehicleProfileRepository(tmp_path / "authority", clock=_Clock())
    principal = _principal()
    document = _fixture("vehicle_profile")
    created = repository.create(principal, site_id="site-a", document=document)
    reviewed = repository.review(
        principal,
        site_id="site-a",
        authority_id=document["vehicleProfileId"],
        expected_revision=created.envelope.revision,
    )
    published = repository.publish(
        principal,
        site_id="site-a",
        authority_id=document["vehicleProfileId"],
        expected_revision=reviewed.envelope.revision,
    )
    deprecated = repository.deprecate(
        principal,
        site_id="site-a",
        authority_id=document["vehicleProfileId"],
        expected_revision=published.envelope.revision,
    )
    assert deprecated.envelope.status == "deprecated"
    with pytest.raises(FacilityNotFoundError):
        repository.get_published(
            principal,
            site_id="site-a",
            authority_id=document["vehicleProfileId"],
        )
    archived = repository.archive(
        principal,
        site_id="site-a",
        authority_id=document["vehicleProfileId"],
        expected_revision=deprecated.envelope.revision,
    )
    assert archived.envelope.status == "archived"


def test_content_cannot_be_edited_after_review(tmp_path):
    repository = FacilityShellRepository(tmp_path / "authority", clock=_Clock())
    principal = _principal()
    document = _fixture("facility_shell")
    created = repository.create(principal, site_id="site-a", document=document)
    reviewed = repository.review(
        principal,
        site_id="site-a",
        authority_id=document["shellId"],
        expected_revision=created.envelope.revision,
    )
    changed = deepcopy(reviewed.envelope.document)
    changed["status"] = "draft"
    changed["futureCompatibleField"]["attemptedRewrite"] = True
    with pytest.raises(AuthorityValidationError) as captured:
        repository.save_draft(
            principal,
            site_id="site-a",
            document=changed,
            expected_revision=reviewed.envelope.revision,
        )
    assert captured.value.code == "invalid_lifecycle_transition"


def test_cross_scope_and_absent_object_reads_are_indistinguishable(tmp_path):
    repository = FacilityShellRepository(tmp_path / "authority", clock=_Clock())
    owner = _principal()
    document = _fixture("facility_shell")
    repository.create(owner, site_id="site-a", document=document)

    probes = (
        (
            _principal(
                tenant="tenant-b",
                sites=("site-a",),
                roles=("viewer",),
            ),
            "site-a",
            document["shellId"],
        ),
        (
            _principal(
                tenant="tenant-a",
                sites=("site-b",),
                roles=("viewer",),
            ),
            "site-b",
            document["shellId"],
        ),
        (owner, "site-a", "shell-does-not-exist"),
        (owner, "site-a", "../shell-site-a"),
    )
    messages = set()
    for principal, site_id, authority_id in probes:
        with pytest.raises(FacilityNotFoundError) as captured:
            repository.get_current(
                principal,
                site_id=site_id,
                authority_id=authority_id,
            )
        assert captured.value.code == "not_found"
        messages.add(str(captured.value))
    assert messages == {"Facility resource was not found."}


def test_document_scope_cannot_be_supplied_by_browser_payload(tmp_path):
    repository = FacilityShellRepository(tmp_path / "authority", clock=_Clock())
    principal = _principal()
    for mutation in (
        {"tenantId": "tenant-b"},
        {"siteId": "site-b"},
        {"shellId": "../shell-site-a"},
    ):
        document = _fixture("facility_shell")
        document.update(mutation)
        expected = FacilityNotFoundError if "shellId" not in mutation else AuthorityValidationError
        with pytest.raises(expected):
            repository.create(
                principal,
                site_id="site-a",
                document=document,
            )


def test_role_matrix_applies_before_repository_mutation(tmp_path):
    repository = FacilityShellRepository(tmp_path / "authority", clock=_Clock())
    document = _fixture("facility_shell")
    viewer = _principal(roles=("viewer",))
    cross_scope = deepcopy(document)
    cross_scope["tenantId"] = "tenant-b"
    with pytest.raises(FacilityNotFoundError) as hidden:
        repository.create(viewer, site_id="site-a", document=cross_scope)
    assert hidden.value.code == "not_found"

    with pytest.raises(FacilityRoleNotAuthorizedError) as captured:
        repository.create(viewer, site_id="site-a", document=document)
    assert captured.value.code == "role_not_authorized"
    assert repository._load_registry("tenant-a", "site-a")["entries"] == []

    alias = _principal(roles=("facility_authority_admin",))
    created = repository.create(alias, site_id="site-a", document=document)
    assert created.envelope.status == "draft"


@pytest.mark.parametrize("failure_stage", ("before_registry_write", "after_registry_write"))
def test_registry_failure_leaves_pointer_unchanged_and_retry_is_safe(
    tmp_path,
    failure_stage,
):
    state = {"enabled": True}

    def fail(stage: str, _path: Path) -> None:
        if state["enabled"] and stage == failure_stage:
            raise OSError("injected registry failure")

    repository = FacilityShellRepository(
        tmp_path / "authority",
        clock=_Clock(),
        failure_injector=fail,
    )
    principal = _principal()
    document = _fixture("facility_shell")

    with pytest.raises(AuthorityWriteError) as captured:
        repository.create(principal, site_id="site-a", document=document)
    assert captured.value.code == "authority_registry_write_failed"
    assert repository._load_registry("tenant-a", "site-a")["entries"] == []
    with pytest.raises(FacilityNotFoundError):
        repository.get_revision(
            principal,
            site_id="site-a",
            authority_id=document["shellId"],
            revision=authority_revision(document),
        )

    state["enabled"] = False
    retried = repository.create(
        principal,
        site_id="site-a",
        document=document,
    )
    assert retried.envelope.revision == authority_revision(document)


def test_failed_draft_update_restores_exact_registry_pointer(tmp_path):
    state = {"fail": False}

    def fail(stage: str, _path: Path) -> None:
        if state["fail"] and stage == "after_registry_write":
            raise OSError("injected post-replace failure")

    repository = FacilityShellRepository(
        tmp_path / "authority",
        clock=_Clock(),
        failure_injector=fail,
    )
    principal = _principal()
    document = _fixture("facility_shell")
    created = repository.create(principal, site_id="site-a", document=document)
    registry_path = repository._registry_path("tenant-a", "site-a")
    before = registry_path.read_bytes()

    updated = deepcopy(document)
    updated["futureCompatibleField"]["newValue"] = "not-visible"
    state["fail"] = True
    with pytest.raises(AuthorityWriteError):
        repository.save_draft(
            principal,
            site_id="site-a",
            document=updated,
            expected_revision=created.envelope.revision,
        )
    assert registry_path.read_bytes() == before
    current = repository.get_current(
        principal,
        site_id="site-a",
        authority_id=document["shellId"],
    )
    assert current.revision == created.envelope.revision
    assert "newValue" not in current.document["futureCompatibleField"]


def test_corrupt_immutable_revision_is_detected(tmp_path):
    repository = FacilityShellRepository(tmp_path / "authority", clock=_Clock())
    principal = _principal()
    document = _fixture("facility_shell")
    created = repository.create(principal, site_id="site-a", document=document)
    path = repository._revision_path(
        "tenant-a",
        "site-a",
        document["shellId"],
        created.envelope.revision,
    )
    repository._atomic_write(path, b"{}")
    with pytest.raises(AuthorityIntegrityError) as captured:
        repository.get_current(
            principal,
            site_id="site-a",
            authority_id=document["shellId"],
        )
    assert captured.value.code == "authority_revision_mismatch"


def test_generic_repository_rejects_unsupported_kind(tmp_path):
    repository = RevisionedAuthorityRepository(
        tmp_path / "authority",
        document_kind="unsupported_kind",
        id_field="unsupportedId",
        clock=_Clock(),
    )
    principal = _principal()
    with pytest.raises(AuthorityValidationError) as captured:
        repository.create(
            principal,
            site_id="site-a",
            document={
                "schemaVersion": 1,
                "documentKind": "unsupported_kind",
                "unsupportedId": "unsupported-a",
                "tenantId": "tenant-a",
                "siteId": "site-a",
                "status": "draft",
                "sourceDocuments": [],
                "evidence": [],
                "unresolvedItems": [],
            },
        )
    assert captured.value.code == "unsupported_authority_kind"
