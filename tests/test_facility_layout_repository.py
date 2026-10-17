from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import pytest

from ai_inspector.facility_layout.authorization import FacilityPrincipal
from ai_inspector.facility_layout.canonical import (
    canonical_layout_bytes,
    canonicalize_layout,
)
from ai_inspector.facility_layout.repository import (
    FacilityLayoutAuthorizationError,
    FacilityLayoutConflictError,
    FacilityLayoutIntegrityError,
    FacilityLayoutNotFoundError,
    FacilityLayoutReadOnlyError,
    FacilityLayoutRepository,
    FacilityLayoutValidationError,
    FacilityLayoutWriteError,
    _read_bytes,
)


FIXTURES = Path(__file__).parent / "fixtures" / "facility_layout"


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="ascii"))


def _principal(
    *,
    tenant_id: str = "tenant-a",
    site_ids: tuple[str, ...] = ("site-a",),
    roles: tuple[str, ...] = ("editor",),
) -> FacilityPrincipal:
    return FacilityPrincipal(
        principal_id="user-a",
        tenant_id=tenant_id,
        allowed_site_ids=site_ids,
        roles=roles,
    )


class _Clock:
    def __init__(self) -> None:
        self.tick = 0

    def __call__(self) -> str:
        self.tick += 1
        return f"2026-07-29T00:00:{self.tick:02d}.000000Z"


def _repo(tmp_path: Path) -> FacilityLayoutRepository:
    return FacilityLayoutRepository(tmp_path / "facility", clock=_Clock())


def _document(
    layout_id: str = "fl-empty-cell",
    *,
    display_name: str = "Empty Cell",
    site_id: str = "site-a",
) -> dict[str, Any]:
    value = _fixture("empty_cell.json")
    value["layoutId"] = layout_id
    value["displayName"] = display_name
    value["association"]["siteId"] = site_id
    return value


def _all_files(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): _read_bytes(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _replace_with_noncanonical_current(
    repository: FacilityLayoutRepository,
    created: Mapping[str, Any],
) -> tuple[bytes, str]:
    scope = repository.root / "tenant-a" / "site-a" / "layouts"
    asset = scope / "fl-empty-cell.json"
    registry_path = scope / "registry.json"
    noncanonical = deepcopy(created["layout"])
    noncanonical["coordinateFrame"]["floorElevation"] = -0.0
    payload = json.dumps(
        noncanonical,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    assert payload != canonical_layout_bytes(noncanonical)
    revision = hashlib.sha256(payload).hexdigest()
    registry = json.loads(registry_path.read_text(encoding="ascii"))
    registry["layouts"][0]["currentRevision"] = revision
    repository._atomic_write(asset, payload)
    repository._atomic_write(
        registry_path,
        json.dumps(
            registry,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii"),
    )
    return payload, revision


def test_create_stamps_server_time_and_establishes_default(tmp_path: Path) -> None:
    repository = _repo(tmp_path)
    source = _document()
    source["createdAt"] = "browser-created"
    source["updatedAt"] = "browser-updated"

    result = repository.create_layout(_principal(), "site-a", source)
    listing = repository.list_layouts(_principal(), "site-a")

    assert result["changed"] is True
    assert result["isDefault"] is True
    assert result["layout"]["createdAt"] == "2026-07-29T00:00:01.000000Z"
    assert result["layout"]["updatedAt"] == result["layout"]["createdAt"]
    assert listing["defaultLayoutId"] == "fl-empty-cell"
    assert listing["layouts"][0]["currentRevision"] == result["revision"]
    assert source["createdAt"] == "browser-created"


def test_current_validation_cache_reuses_only_successful_exact_bytes(tmp_path, monkeypatch):
    import ai_inspector.facility_layout.repository as module
    repository = _repo(tmp_path)
    created = repository.create_layout(_principal(), "site-a", _document())
    original = module.canonical_layout_bytes
    calls = []
    def counted(document):
        calls.append(document["layoutId"])
        return original(document)
    monkeypatch.setattr(module, "canonical_layout_bytes", counted)
    first = repository.get_layout(_principal(), "site-a", "fl-empty-cell")
    first["layout"]["displayName"] = "Changed outside the repository"
    second = repository.get_layout(_principal(), "site-a", "fl-empty-cell")
    assert calls == ["fl-empty-cell"]
    assert second["layout"] == created["layout"]
    assert second["layout"] is not first["layout"]


def test_current_validation_cache_still_checks_bytes_registry_and_authority(tmp_path):
    repository = _repo(tmp_path)
    repository.create_layout(_principal(), "site-a", _document())
    repository.get_layout(_principal(), "site-a", "fl-empty-cell")
    with pytest.raises(FacilityLayoutAuthorizationError):
        repository.get_layout(_principal(roles=("catalog_curator",)), "site-a", "fl-empty-cell")
    asset = repository.root / "tenant-a/site-a/layouts/fl-empty-cell.json"
    original = asset.read_bytes()
    # Same length: a stat/size-based shortcut must not permit a stale read.
    asset.write_bytes(original.replace(b"Empty Cell", b"Other Cell"))
    with pytest.raises(FacilityLayoutIntegrityError, match="authoritative registry"):
        repository.get_layout(_principal(), "site-a", "fl-empty-cell")
    asset.write_bytes(original)
    registry_path = asset.parent / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="ascii"))
    registry["layouts"][0]["currentRevision"] = "0" * 64
    repository._atomic_write(registry_path, json.dumps(
        registry, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii"))
    with pytest.raises(FacilityLayoutIntegrityError, match="authoritative registry"):
        repository.get_layout(_principal(), "site-a", "fl-empty-cell")


def test_current_validation_cache_rejects_new_noncanonical_bytes_repeatedly(tmp_path):
    repository = _repo(tmp_path)
    created = repository.create_layout(_principal(), "site-a", _document())
    repository.get_layout(_principal(), "site-a", "fl-empty-cell")
    _, invalid_revision = _replace_with_noncanonical_current(repository, created)
    for _ in range(2):
        with pytest.raises(FacilityLayoutIntegrityError, match="not canonical"):
            repository.get_layout(_principal(), "site-a", "fl-empty-cell")
    assert invalid_revision not in repository._validated_current_revisions


def test_current_validation_cache_is_bounded_and_evicts(tmp_path, monkeypatch):
    import ai_inspector.facility_layout.repository as module
    monkeypatch.setattr(module, "_VALIDATED_CURRENT_CACHE_SIZE", 2)
    repository = _repo(tmp_path)
    for name in ("fl-a", "fl-b", "fl-c"):
        repository.create_layout(_principal(), "site-a", _document(name))
    original = module.canonical_layout_bytes
    calls = []
    def counted(document):
        calls.append(document["layoutId"])
        return original(document)
    monkeypatch.setattr(module, "canonical_layout_bytes", counted)
    for name in ("fl-a", "fl-b", "fl-c", "fl-c", "fl-a"):
        repository.get_layout(_principal(), "site-a", name)
        assert len(repository._validated_current_revisions) <= 2
    assert calls == ["fl-a", "fl-b", "fl-c", "fl-a"]


def test_registry_is_sorted_and_default_pointer_can_change(tmp_path: Path) -> None:
    repository = _repo(tmp_path)
    principal = _principal()
    second = repository.create_layout(
        principal,
        "site-a",
        _document("fl-z-cell", display_name="Z Cell"),
    )
    first = repository.create_layout(
        principal,
        "site-a",
        _document("fl-a-cell", display_name="A Cell"),
    )

    listing = repository.list_layouts(principal, "site-a")
    assert [item["layoutId"] for item in listing["layouts"]] == [
        "fl-a-cell",
        "fl-z-cell",
    ]
    assert listing["defaultLayoutId"] == second["layout"]["layoutId"]

    changed = repository.set_default_layout(principal, "site-a", "fl-a-cell")
    repeated = repository.set_default_layout(principal, "site-a", "fl-a-cell")
    assert changed["changed"] is True
    assert repeated["changed"] is False
    assert repository.get_layout(
        principal,
        "site-a",
        first["layout"]["layoutId"],
    )["isDefault"] is True


def test_save_reopen_is_exact_and_backup_is_revision_addressable(
    tmp_path: Path,
) -> None:
    repository = _repo(tmp_path)
    principal = _principal()
    created = repository.create_layout(
        principal,
        "site-a",
        _document(),
    )
    candidate = deepcopy(created["layout"])
    candidate["displayName"] = "Renamed Cell"

    saved = repository.save_layout(
        principal,
        "site-a",
        "fl-empty-cell",
        candidate,
        created["revision"],
    )
    reopened = FacilityLayoutRepository(
        repository.root,
        clock=_Clock(),
    ).get_layout(principal, "site-a", "fl-empty-cell")
    historical = repository.get_layout_revision(
        principal,
        "site-a",
        "fl-empty-cell",
        created["revision"],
    )

    assert reopened["layout"] == saved["layout"]
    assert canonical_layout_bytes(reopened["layout"]) == canonical_layout_bytes(
        saved["layout"]
    )
    assert reopened["revision"] == saved["revision"]
    assert historical["layout"] == created["layout"]
    assert historical["revision"] == created["revision"]


def test_no_op_save_is_byte_and_registry_stable(tmp_path: Path) -> None:
    repository = _repo(tmp_path)
    principal = _principal()
    created = repository.create_layout(principal, "site-a", _document())
    scope = repository.root / "tenant-a" / "site-a" / "layouts"
    before = _all_files(scope)
    candidate = deepcopy(created["layout"])
    candidate["updatedAt"] = "browser-must-not-dirty"

    result = repository.save_layout(
        principal,
        "site-a",
        "fl-empty-cell",
        candidate,
        created["revision"],
    )

    assert result["changed"] is False
    assert result["revision"] == created["revision"]
    assert _all_files(scope) == before


def test_stale_save_reports_current_revision_without_writing(
    tmp_path: Path,
) -> None:
    repository = _repo(tmp_path)
    principal = _principal()
    created = repository.create_layout(principal, "site-a", _document())
    candidate = deepcopy(created["layout"])
    candidate["displayName"] = "Current"
    current = repository.save_layout(
        principal,
        "site-a",
        "fl-empty-cell",
        candidate,
        created["revision"],
    )
    before = _all_files(repository.root)
    stale = deepcopy(created["layout"])
    stale["displayName"] = "Stale"

    with pytest.raises(FacilityLayoutConflictError) as caught:
        repository.save_layout(
            principal,
            "site-a",
            "fl-empty-cell",
            stale,
            created["revision"],
        )

    assert caught.value.code == "revision_conflict"
    assert caught.value.current_revision == current["revision"]
    assert caught.value.status_code == 409
    assert _all_files(repository.root) == before


def test_unknown_compatible_fields_round_trip(tmp_path: Path) -> None:
    repository = _repo(tmp_path)
    principal = _principal()
    source = _fixture("repeated_assets.json")
    source["futureCompatible"] = {"vendorMode": "retained", "rank": 7}
    source["placements"][0]["futurePlacementField"] = {
        "reviewedBy": "operator-a"
    }

    created = repository.create_layout(principal, "site-a", source)
    reopened = repository.get_layout(
        principal,
        "site-a",
        source["layoutId"],
    )

    assert reopened["layout"]["futureCompatible"] == source["futureCompatible"]
    assert reopened["layout"]["placements"][0][
        "futurePlacementField"
    ] == source["placements"][0]["futurePlacementField"]
    assert reopened["revision"] == created["revision"]


def test_repeated_asset_placements_remain_independent(tmp_path: Path) -> None:
    repository = _repo(tmp_path)
    principal = _principal()
    source = _fixture("repeated_assets.json")
    created = repository.create_layout(principal, "site-a", source)
    candidate = deepcopy(created["layout"])
    original_second = deepcopy(candidate["placements"][1])
    candidate["placements"][0]["transform"]["position"]["x"] += 3.0

    saved = repository.save_layout(
        principal,
        "site-a",
        source["layoutId"],
        candidate,
        created["revision"],
    )

    assert saved["layout"]["placements"][0]["placementId"] != saved["layout"][
        "placements"
    ][1]["placementId"]
    assert saved["layout"]["placements"][1] == original_second


def test_archive_is_revisioned_hidden_and_read_only(tmp_path: Path) -> None:
    repository = _repo(tmp_path)
    principal = _principal()
    default = repository.create_layout(
        principal,
        "site-a",
        _document("fl-default"),
    )
    candidate = repository.create_layout(
        principal,
        "site-a",
        _document("fl-archive-me"),
    )

    archived = repository.archive_layout(
        principal,
        "site-a",
        "fl-archive-me",
        candidate["revision"],
    )

    assert archived["layout"]["status"] == "archived"
    assert archived["readOnly"] is True
    visible = repository.list_layouts(principal, "site-a")["layouts"]
    assert [item["layoutId"] for item in visible] == ["fl-default"]
    all_layouts = repository.list_layouts(
        principal,
        "site-a",
        include_archived=True,
    )
    assert [item["status"] for item in all_layouts["layouts"]] == [
        "archived",
        "draft",
    ]
    with pytest.raises(FacilityLayoutReadOnlyError) as caught:
        repository.save_layout(
            principal,
            "site-a",
            "fl-archive-me",
            archived["layout"],
            archived["revision"],
        )
    assert caught.value.code == "archived_layout_read_only"
    assert default["isDefault"] is True


def test_default_layout_cannot_be_archived(tmp_path: Path) -> None:
    repository = _repo(tmp_path)
    principal = _principal()
    created = repository.create_layout(
        principal,
        "site-a",
        _document("fl-default"),
    )

    with pytest.raises(FacilityLayoutValidationError) as caught:
        repository.archive_layout(
            principal,
            "site-a",
            "fl-default",
            created["revision"],
        )

    assert caught.value.code == "default_layout_cannot_be_archived"
    assert repository.get_layout(
        principal,
        "site-a",
        "fl-default",
    )["layout"]["status"] == "draft"


def test_cross_scope_and_object_substitution_are_hidden(tmp_path: Path) -> None:
    repository = _repo(tmp_path)
    owner = _principal()
    created = repository.create_layout(owner, "site-a", _document())
    other_tenant = _principal(tenant_id="tenant-b")
    other_site = _principal(site_ids=("site-b",))

    for principal, site_id in (
        (other_tenant, "site-a"),
        (other_site, "site-a"),
    ):
        with pytest.raises(FacilityLayoutNotFoundError) as caught:
            repository.get_layout(
                principal,
                site_id,
                "fl-empty-cell",
            )
        assert caught.value.code == "not_found"
        assert caught.value.status_code == 404

    substituted = deepcopy(created["layout"])
    substituted["layoutId"] = "fl-other"
    with pytest.raises(FacilityLayoutNotFoundError):
        repository.save_layout(
            owner,
            "site-a",
            "fl-empty-cell",
            substituted,
            created["revision"],
        )


def test_role_denial_is_distinct_from_hidden_scope(tmp_path: Path) -> None:
    repository = _repo(tmp_path)
    viewer = _principal(roles=("viewer",))

    with pytest.raises(FacilityLayoutAuthorizationError) as caught:
        repository.create_layout(viewer, "site-a", _document())

    assert caught.value.code == "role_not_authorized"
    assert caught.value.status_code == 403


def test_untrusted_principal_mapping_is_not_accepted(tmp_path: Path) -> None:
    repository = _repo(tmp_path)
    forged = {
        "principalId": "browser-user",
        "tenantId": "tenant-a",
        "allowedSiteIds": ["site-a"],
        "roles": ["admin"],
    }

    with pytest.raises(FacilityLayoutNotFoundError):
        repository.create_layout(forged, "site-a", _document())


@pytest.mark.parametrize(
    "layout_id",
    ("../escape", "fl-../../escape", "fl-invalid/child", "not-a-layout"),
)
def test_path_traversal_and_invalid_ids_are_hidden(
    tmp_path: Path,
    layout_id: str,
) -> None:
    repository = _repo(tmp_path)
    with pytest.raises(FacilityLayoutNotFoundError):
        repository.get_layout(_principal(), "site-a", layout_id)


class _FailingRepository(FacilityLayoutRepository):
    def __init__(self, root: Path) -> None:
        super().__init__(root, clock=_Clock())
        self.fail_registry = False
        self.fail_layout_id: str | None = None
        self.write_order: list[str] = []

    def _atomic_write(self, path: Path, payload: bytes) -> None:
        self.write_order.append(path.name)
        if self.fail_layout_id and path.name == f"{self.fail_layout_id}.json":
            raise FacilityLayoutWriteError(
                "injected_layout_failure",
                "Injected layout failure.",
            )
        super()._atomic_write(path, payload)

    def _write_registry(
        self,
        tenant_id: str,
        site_id: str,
        registry: Mapping[str, Any],
    ) -> None:
        if self.fail_registry:
            raise FacilityLayoutWriteError(
                "injected_registry_failure",
                "Injected registry failure.",
            )
        super()._write_registry(tenant_id, site_id, registry)


class _AfterRegistryWriteRepository(FacilityLayoutRepository):
    def __init__(self, root: Path) -> None:
        super().__init__(root, clock=_Clock())
        self.fail_after_registry_write = False

    def _after_registry_write(self, path: Path) -> None:
        if self.fail_after_registry_write:
            raise FacilityLayoutWriteError(
                "injected_after_registry_failure",
                "Injected failure after replacing the registry.",
            )


def test_failed_create_registry_write_leaves_no_asset(tmp_path: Path) -> None:
    repository = _FailingRepository(tmp_path / "facility")
    repository.fail_registry = True

    with pytest.raises(FacilityLayoutWriteError) as caught:
        repository.create_layout(_principal(), "site-a", _document())

    assert caught.value.code == "injected_registry_failure"
    assert _all_files(repository.root) == {}


def test_failed_save_registry_write_restores_exact_state(tmp_path: Path) -> None:
    repository = _FailingRepository(tmp_path / "facility")
    principal = _principal()
    created = repository.create_layout(principal, "site-a", _document())
    before = _all_files(repository.root)
    candidate = deepcopy(created["layout"])
    candidate["displayName"] = "Must Roll Back"
    repository.fail_registry = True

    with pytest.raises(FacilityLayoutWriteError):
        repository.save_layout(
            principal,
            "site-a",
            "fl-empty-cell",
            candidate,
            created["revision"],
        )

    assert _all_files(repository.root) == before
    assert repository.get_layout(
        principal,
        "site-a",
        "fl-empty-cell",
    )["revision"] == created["revision"]


def test_failure_after_registry_replace_restores_layout_and_registry(
    tmp_path: Path,
) -> None:
    repository = _AfterRegistryWriteRepository(tmp_path / "facility")
    principal = _principal()
    created = repository.create_layout(principal, "site-a", _document())
    before = _all_files(repository.root)
    candidate = deepcopy(created["layout"])
    candidate["displayName"] = "Must Roll Back After Registry Replace"
    repository.fail_after_registry_write = True

    with pytest.raises(FacilityLayoutWriteError) as caught:
        repository.save_layout(
            principal,
            "site-a",
            "fl-empty-cell",
            candidate,
            created["revision"],
        )

    assert caught.value.code == "injected_after_registry_failure"
    assert _all_files(repository.root) == before
    reopened = repository.get_layout(
        principal,
        "site-a",
        "fl-empty-cell",
    )
    assert reopened["revision"] == created["revision"]
    assert reopened["layout"] == created["layout"]


def test_failed_layout_write_removes_new_backup_and_changes_nothing(
    tmp_path: Path,
) -> None:
    repository = _FailingRepository(tmp_path / "facility")
    principal = _principal()
    created = repository.create_layout(principal, "site-a", _document())
    before = _all_files(repository.root)
    candidate = deepcopy(created["layout"])
    candidate["displayName"] = "Must Not Land"
    repository.fail_layout_id = "fl-empty-cell"

    with pytest.raises(FacilityLayoutWriteError):
        repository.save_layout(
            principal,
            "site-a",
            "fl-empty-cell",
            candidate,
            created["revision"],
        )

    assert _all_files(repository.root) == before


def test_registry_is_written_after_backup_and_layout(tmp_path: Path) -> None:
    repository = _FailingRepository(tmp_path / "facility")
    principal = _principal()
    created = repository.create_layout(principal, "site-a", _document())
    repository.write_order.clear()
    candidate = deepcopy(created["layout"])
    candidate["displayName"] = "Ordered Save"

    repository.save_layout(
        principal,
        "site-a",
        "fl-empty-cell",
        candidate,
        created["revision"],
    )

    assert repository.write_order[-1] == "registry.json"
    assert repository.write_order[-2] == "fl-empty-cell.json"
    assert f"{created['revision']}.json" in repository.write_order


def test_tampered_layout_is_rejected_even_if_file_exists(tmp_path: Path) -> None:
    repository = _repo(tmp_path)
    principal = _principal()
    repository.create_layout(principal, "site-a", _document())
    asset = (
        repository.root
        / "tenant-a"
        / "site-a"
        / "layouts"
        / "fl-empty-cell.json"
    )
    asset.write_bytes(asset.read_bytes() + b" ")

    with pytest.raises(FacilityLayoutIntegrityError) as caught:
        repository.get_layout(principal, "site-a", "fl-empty-cell")

    assert caught.value.code == "layout_registry_revision_mismatch"


def test_missing_registry_with_layout_assets_fails_closed(tmp_path: Path) -> None:
    repository = _repo(tmp_path)
    principal = _principal()
    repository.create_layout(principal, "site-a", _document())
    registry = (
        repository.root / "tenant-a" / "site-a" / "layouts" / "registry.json"
    )
    registry.unlink()

    with pytest.raises(FacilityLayoutIntegrityError) as caught:
        repository.list_layouts(principal, "site-a")

    assert caught.value.code == "layout_registry_missing"


def test_future_schema_is_readable_without_rewrite_but_not_writable(
    tmp_path: Path,
) -> None:
    repository = _repo(tmp_path)
    principal = _principal()
    created = repository.create_layout(principal, "site-a", _document())
    scope = repository.root / "tenant-a" / "site-a" / "layouts"
    asset = scope / "fl-empty-cell.json"
    future = deepcopy(created["layout"])
    future["schemaVersion"] = 2
    future["futureOnly"] = {"exact": [3, 2, 1]}
    future_payload = json.dumps(
        future,
        ensure_ascii=True,
        sort_keys=False,
        indent=1,
    ).encode("ascii")
    future_revision = __import__("hashlib").sha256(future_payload).hexdigest()
    registry = json.loads((scope / "registry.json").read_text(encoding="ascii"))
    registry["layouts"][0]["currentRevision"] = future_revision
    repository._atomic_write(asset, future_payload)
    repository._atomic_write(
        scope / "registry.json",
        json.dumps(
            registry,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii"),
    )

    read = repository.get_layout(principal, "site-a", "fl-empty-cell")

    assert read["readOnly"] is True
    assert read["revision"] == future_revision
    assert asset.read_bytes() == future_payload
    with pytest.raises(FacilityLayoutReadOnlyError) as caught:
        repository.save_layout(
            principal,
            "site-a",
            "fl-empty-cell",
            read["layout"],
            future_revision,
        )
    assert caught.value.code == "unsupported_schema_version_read_only"
    assert asset.read_bytes() == future_payload


def test_explicit_validator_runs_before_create_and_save(tmp_path: Path) -> None:
    calls: list[str] = []

    def validator(document: Mapping[str, Any]) -> Mapping[str, Any]:
        calls.append(str(document["displayName"]))
        return document

    repository = FacilityLayoutRepository(
        tmp_path / "facility",
        validator=validator,
        clock=_Clock(),
    )
    principal = _principal()
    created = repository.create_layout(principal, "site-a", _document())
    candidate = deepcopy(created["layout"])
    candidate["displayName"] = "Validated Save"
    repository.save_layout(
        principal,
        "site-a",
        "fl-empty-cell",
        candidate,
        created["revision"],
    )

    assert calls == ["Empty Cell", "Validated Save", "Validated Save"]


def test_long_windows_paths_round_trip(tmp_path: Path) -> None:
    tenant_id = "t" * 120
    site_id = "s" * 120
    layout_id = "fl-" + ("l" * 120)
    principal = _principal(
        tenant_id=tenant_id,
        site_ids=(site_id,),
    )
    repository = FacilityLayoutRepository(
        tmp_path / ("root-" + ("r" * 80)),
        clock=_Clock(),
    )
    source = _document(layout_id, site_id=site_id)

    created = repository.create_layout(principal, site_id, source)
    reopened = repository.get_layout(principal, site_id, layout_id)

    assert reopened["layout"]["layoutId"] == layout_id
    assert reopened["revision"] == created["revision"]


def test_returned_documents_are_detached_from_storage(tmp_path: Path) -> None:
    repository = _repo(tmp_path)
    principal = _principal()
    repository.create_layout(principal, "site-a", _document())
    first = repository.get_layout(principal, "site-a", "fl-empty-cell")
    first["layout"]["displayName"] = "Local Mutation"

    second = repository.get_layout(principal, "site-a", "fl-empty-cell")

    assert second["layout"]["displayName"] == "Empty Cell"


def test_noncanonical_input_is_normalized_before_persistence(
    tmp_path: Path,
) -> None:
    repository = _repo(tmp_path)
    source = _document()
    source["coordinateFrame"]["floorElevation"] = -0.0

    created = repository.create_layout(_principal(), "site-a", source)

    assert created["layout"] == canonicalize_layout(created["layout"])
    assert created["layout"]["coordinateFrame"]["floorElevation"] == 0


def test_explicit_storage_normalization_preserves_exact_prior_revision(
    tmp_path: Path,
) -> None:
    repository = _repo(tmp_path)
    principal = _principal()
    created = repository.create_layout(principal, "site-a", _document())
    prior_payload, prior_revision = _replace_with_noncanonical_current(
        repository,
        created,
    )

    with pytest.raises(FacilityLayoutIntegrityError) as caught:
        repository.get_layout(principal, "site-a", "fl-empty-cell")
    assert caught.value.code == "layout_asset_not_canonical"

    normalized = repository.normalize_current_layout_storage(
        principal,
        "site-a",
        "fl-empty-cell",
    )
    scope = repository.root / "tenant-a" / "site-a" / "layouts"
    backup = scope / "backups" / "fl-empty-cell" / f"{prior_revision}.json"

    assert normalized["changed"] is True
    assert normalized["revision"] == created["revision"]
    assert normalized["layout"] == created["layout"]
    assert (scope / "fl-empty-cell.json").read_bytes() == (
        canonical_layout_bytes(created["layout"])
    )
    assert _read_bytes(backup) == prior_payload
    assert repository.get_layout_revision(
        principal,
        "site-a",
        "fl-empty-cell",
        prior_revision,
    )["revision"] == prior_revision

    before_repeat = _all_files(repository.root)
    repeated = repository.normalize_current_layout_storage(
        principal,
        "site-a",
        "fl-empty-cell",
    )
    assert repeated["changed"] is False
    assert _all_files(repository.root) == before_repeat


def test_storage_normalization_rolls_back_exactly_after_registry_failure(
    tmp_path: Path,
) -> None:
    repository = _AfterRegistryWriteRepository(tmp_path / "facility")
    principal = _principal()
    created = repository.create_layout(principal, "site-a", _document())
    _replace_with_noncanonical_current(repository, created)
    before = _all_files(repository.root)
    repository.fail_after_registry_write = True

    with pytest.raises(FacilityLayoutWriteError) as caught:
        repository.normalize_current_layout_storage(
            principal,
            "site-a",
            "fl-empty-cell",
        )

    assert caught.value.code == "injected_after_registry_failure"
    assert _all_files(repository.root) == before
