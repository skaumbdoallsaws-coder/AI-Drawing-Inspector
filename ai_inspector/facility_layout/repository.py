"""Authoritative, revision-aware Facility Layout persistence."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

from .authorization import (
    FacilityNotFoundError as PrincipalScopeNotFoundError,
    FacilityPrincipal,
    FacilityRoleNotAuthorizedError,
    require_facility_action,
)
from .canonical import (
    canonical_layout_bytes,
    canonicalize_layout,
    layout_revision,
)
from .errors import (
    FacilityAuthorizationError,
    FacilityCompatibilityError,
    FacilityConflictError,
    FacilityIntegrityError,
    FacilityLayoutError,
    FacilityNotFoundError,
    FacilityValidationError,
)


FACILITY_LAYOUT_REGISTRY_VERSION = 1
FACILITY_LAYOUT_SCHEMA_VERSION = 1

_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_LAYOUT_ID_RE = re.compile(r"^fl-[A-Za-z0-9][A-Za-z0-9._:-]{0,124}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{64}$")
_STATUSES = frozenset({"draft", "active", "template", "archived"})
_REQUIRED_COLLECTIONS = (
    "zones",
    "placements",
    "routes",
    "utilityNetworks",
    "processBindings",
    "dismissedSuggestions",
)
_FORBIDDEN_LIVE_FIELDS = frozenset(
    {"camera", "viewport", "selection", "activeProposal"}
)
_WRITE_LOCK = threading.RLock()


FacilityLayoutRepositoryError = FacilityLayoutError


class FacilityLayoutNotFoundError(FacilityNotFoundError):
    def __init__(self) -> None:
        super().__init__("not_found", "Facility Layout was not found.")


class FacilityLayoutAuthorizationError(FacilityAuthorizationError):
    def __init__(self) -> None:
        super().__init__(
            "role_not_authorized",
            "Principal is not authorized for this Facility Layout action.",
        )


class FacilityLayoutConflictError(FacilityConflictError):
    def __init__(self, current_revision: str) -> None:
        super().__init__(
            "revision_conflict",
            "Facility Layout revision conflict.",
            details={"currentRevision": current_revision},
        )
        self.current_revision = current_revision


class FacilityLayoutValidationError(FacilityValidationError):
    def __init__(
        self,
        findings: Iterable[Mapping[str, Any]] | None = None,
        *,
        code: str = "layout_validation_failed",
        message: str = "Facility Layout failed validation.",
    ) -> None:
        self.findings = [deepcopy(dict(item)) for item in (findings or ())]
        super().__init__(
            code,
            message,
            details={"findings": deepcopy(self.findings)} if self.findings else None,
        )


class FacilityLayoutReadOnlyError(FacilityCompatibilityError):
    pass


class FacilityLayoutIntegrityError(FacilityIntegrityError):
    pass


class FacilityLayoutWriteError(FacilityIntegrityError):
    pass


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, UnicodeError) as exc:
        raise FacilityLayoutIntegrityError(
            "registry_not_serializable",
            "Facility Layout registry cannot be serialized as canonical JSON.",
        ) from exc
    return text.encode("ascii")


def facility_layout_revision(value: Any) -> str:
    return layout_revision(value)


def _native_fs_path(path: Path) -> str:
    absolute = os.path.abspath(os.fspath(path))
    if os.name != "nt" or absolute.startswith("\\\\?\\"):
        return absolute
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


def _utc_timestamp(value: datetime | str | None = None) -> str:
    current = value if value is not None else datetime.now(timezone.utc)
    if isinstance(current, str):
        if not current.strip():
            raise FacilityLayoutWriteError(
                "invalid_server_timestamp",
                "Server clock returned an empty timestamp.",
            )
        return current
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return (
        current.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _authorize(
    principal: Any,
    site_id: str,
    action: str,
) -> tuple[str, str]:
    if not isinstance(principal, FacilityPrincipal):
        raise FacilityLayoutNotFoundError()
    try:
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action=action,
        )
    except PrincipalScopeNotFoundError as exc:
        raise FacilityLayoutNotFoundError() from exc
    except FacilityRoleNotAuthorizedError as exc:
        raise FacilityLayoutAuthorizationError() from exc
    if not isinstance(site_id, str) or not _STABLE_ID_RE.fullmatch(site_id):
        raise FacilityLayoutNotFoundError()
    return principal.tenant_id, site_id


def _validate_layout_id(layout_id: str) -> str:
    if not isinstance(layout_id, str) or not _LAYOUT_ID_RE.fullmatch(layout_id):
        raise FacilityLayoutNotFoundError()
    return layout_id


def _is_file(path: Path) -> bool:
    return os.path.isfile(_native_fs_path(path))


def _read_bytes(path: Path) -> bytes:
    try:
        with open(_native_fs_path(path), "rb") as stream:
            return stream.read()
    except FileNotFoundError as exc:
        raise FacilityLayoutNotFoundError() from exc
    except OSError as exc:
        raise FacilityLayoutIntegrityError(
            "layout_asset_unreadable",
            "Facility Layout storage is unreadable.",
        ) from exc


def _read_json_object(path: Path) -> tuple[dict[str, Any], bytes]:
    payload = _read_bytes(path)
    try:
        value = json.loads(payload.decode("ascii"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FacilityLayoutIntegrityError(
            "layout_asset_invalid",
            "Facility Layout storage contains invalid canonical JSON.",
        ) from exc
    if not isinstance(value, dict):
        raise FacilityLayoutIntegrityError(
            "layout_asset_invalid",
            "Facility Layout storage must contain a JSON object.",
        )
    return value, payload


def _hash_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _core_findings(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def error(code: str, message: str) -> None:
        findings.append({"severity": "error", "code": code, "message": message})

    if document.get("schemaVersion") != FACILITY_LAYOUT_SCHEMA_VERSION:
        error(
            "unsupported_schema_version",
            "Only Facility Layout schema version 1 can be written.",
        )
    if not _LAYOUT_ID_RE.fullmatch(str(document.get("layoutId") or "")):
        error("invalid_id", "layoutId is invalid.")
    display_name = document.get("displayName")
    if (
        not isinstance(display_name, str)
        or not display_name.strip()
        or len(display_name) > 120
    ):
        error("invalid_display_name", "displayName is invalid.")
    if document.get("status") not in _STATUSES:
        error("invalid_status", "status is invalid.")
    association = document.get("association")
    if not isinstance(association, Mapping) or not _STABLE_ID_RE.fullmatch(
        str(association.get("siteId") or "")
    ):
        error("invalid_association", "association.siteId is invalid.")
    for key in _REQUIRED_COLLECTIONS:
        if not isinstance(document.get(key), list):
            error("invalid_collection", f"{key} must be an array.")
    for key in _FORBIDDEN_LIVE_FIELDS:
        if key in document:
            error("forbidden_live_state", f"{key} must not be persisted.")
    for key in ("createdAt", "updatedAt"):
        value = document.get(key)
        if not isinstance(value, str) or not value or len(value) > 64:
            error("invalid_server_timestamp", f"{key} is invalid.")

    def inspect_numbers(value: Any, path: str = "$") -> None:
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, (int, float)):
            if not math.isfinite(value):
                error("non_finite_transform", f"{path} must be finite.")
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                inspect_numbers(item, f"{path}[{index}]")
        elif isinstance(value, Mapping):
            for key, item in value.items():
                inspect_numbers(item, f"{path}.{key}")

    inspect_numbers(document)
    return findings


def _load_default_validator() -> Optional[Callable[[Mapping[str, Any]], Any]]:
    try:
        from .validate import validate_layout
    except (ImportError, AttributeError):
        return None
    return validate_layout


def _validation_findings(result: Any) -> list[dict[str, Any]]:
    if result is None or result is True:
        return []
    if result is False:
        return [
            {
                "severity": "error",
                "code": "layout_validation_failed",
                "message": "Facility Layout validator rejected the document.",
            }
        ]
    if isinstance(result, Mapping):
        nested = result.get("findings")
        if isinstance(nested, list):
            return [
                deepcopy(dict(item)) for item in nested if isinstance(item, Mapping)
            ]
        if result.get("valid") is False:
            return [
                {
                    "severity": "error",
                    "code": "layout_validation_failed",
                    "message": "Facility Layout validator rejected the document.",
                }
            ]
        return []
    if isinstance(result, Iterable) and not isinstance(result, (str, bytes)):
        return [
            deepcopy(dict(item)) for item in result if isinstance(item, Mapping)
        ]
    nested = getattr(result, "findings", None)
    if isinstance(nested, Iterable):
        return [
            deepcopy(dict(item)) for item in nested if isinstance(item, Mapping)
        ]
    return []


class FacilityLayoutRepository:
    """Principal-scoped Facility Layout registry and immutable revision store."""

    def __init__(
        self,
        root: str | Path,
        *,
        validator: Optional[Callable[[Mapping[str, Any]], Any]] = None,
        clock: Optional[Callable[[], datetime | str]] = None,
    ) -> None:
        self.root = Path(root).resolve()
        self._validator = validator
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        try:
            os.makedirs(_native_fs_path(self.root), exist_ok=True)
        except OSError as exc:
            raise FacilityLayoutWriteError(
                "layout_root_unavailable",
                "Facility Layout storage root is unavailable.",
            ) from exc

    def _timestamp(self) -> str:
        return _utc_timestamp(self._clock())

    def _scope_root(self, tenant_id: str, site_id: str) -> Path:
        if not _STABLE_ID_RE.fullmatch(tenant_id) or not _STABLE_ID_RE.fullmatch(
            site_id
        ):
            raise FacilityLayoutNotFoundError()
        candidate = self.root / tenant_id / site_id / "layouts"
        root_text = os.path.normcase(os.path.realpath(os.fspath(self.root)))
        candidate_text = os.path.normcase(os.path.realpath(os.fspath(candidate)))
        try:
            contained = os.path.commonpath((root_text, candidate_text)) == root_text
        except ValueError:
            contained = False
        if not contained:
            raise FacilityLayoutNotFoundError()
        return candidate

    def _registry_path(self, tenant_id: str, site_id: str) -> Path:
        return self._scope_root(tenant_id, site_id) / "registry.json"

    def _layout_path(
        self,
        tenant_id: str,
        site_id: str,
        layout_id: str,
    ) -> Path:
        return self._scope_root(tenant_id, site_id) / f"{layout_id}.json"

    def _backup_path(
        self,
        tenant_id: str,
        site_id: str,
        layout_id: str,
        revision: str,
    ) -> Path:
        if not _REVISION_RE.fullmatch(revision):
            raise FacilityLayoutNotFoundError()
        return (
            self._scope_root(tenant_id, site_id)
            / "backups"
            / layout_id
            / f"{revision}.json"
        )

    @staticmethod
    def _empty_registry(tenant_id: str, site_id: str) -> dict[str, Any]:
        return {
            "schemaVersion": FACILITY_LAYOUT_REGISTRY_VERSION,
            "recordKind": "facility_layout_registry",
            "tenantId": tenant_id,
            "siteId": site_id,
            "defaultLayoutId": None,
            "layouts": [],
        }

    def _unregistered_assets_exist(self, scope_root: Path) -> bool:
        native = _native_fs_path(scope_root)
        if not os.path.isdir(native):
            return False
        try:
            with os.scandir(native) as entries:
                return any(
                    item.is_file(follow_symlinks=False)
                    and _LAYOUT_ID_RE.fullmatch(
                        item.name[:-5] if item.name.endswith(".json") else ""
                    )
                    for item in entries
                )
        except OSError as exc:
            raise FacilityLayoutIntegrityError(
                "layout_registry_unreadable",
                "Facility Layout registry directory is unreadable.",
            ) from exc

    def _load_registry(self, tenant_id: str, site_id: str) -> dict[str, Any]:
        path = self._registry_path(tenant_id, site_id)
        if not _is_file(path):
            if self._unregistered_assets_exist(path.parent):
                raise FacilityLayoutIntegrityError(
                    "layout_registry_missing",
                    "Facility Layout registry is missing.",
                )
            return self._empty_registry(tenant_id, site_id)
        value, payload = _read_json_object(path)
        if payload != _canonical_json_bytes(value):
            raise FacilityLayoutIntegrityError(
                "layout_registry_not_canonical",
                "Facility Layout registry is not canonical.",
            )
        if (
            value.get("schemaVersion") != FACILITY_LAYOUT_REGISTRY_VERSION
            or value.get("recordKind") != "facility_layout_registry"
            or value.get("tenantId") != tenant_id
            or value.get("siteId") != site_id
            or not isinstance(value.get("layouts"), list)
        ):
            raise FacilityLayoutIntegrityError(
                "layout_registry_invalid",
                "Facility Layout registry is invalid.",
            )
        summaries = value["layouts"]
        ids = [
            item.get("layoutId") if isinstance(item, Mapping) else None
            for item in summaries
        ]
        if (
            any(not isinstance(item, Mapping) for item in summaries)
            or ids != sorted(ids)
            or len(ids) != len(set(ids))
            or any(not _LAYOUT_ID_RE.fullmatch(str(item or "")) for item in ids)
        ):
            raise FacilityLayoutIntegrityError(
                "layout_registry_invalid",
                "Facility Layout registry entries are invalid.",
            )
        default_layout_id = value.get("defaultLayoutId")
        if summaries:
            if default_layout_id not in ids:
                raise FacilityLayoutIntegrityError(
                    "layout_registry_invalid",
                    "Facility Layout default pointer is invalid.",
                )
        elif default_layout_id is not None:
            raise FacilityLayoutIntegrityError(
                "layout_registry_invalid",
                "Empty Facility Layout registry has a default pointer.",
            )
        for item in summaries:
            if not _REVISION_RE.fullmatch(str(item.get("currentRevision") or "")):
                raise FacilityLayoutIntegrityError(
                    "layout_registry_invalid",
                    "Facility Layout registry revision is invalid.",
                )
            if item.get("status") not in _STATUSES:
                raise FacilityLayoutIntegrityError(
                    "layout_registry_invalid",
                    "Facility Layout registry status is invalid.",
                )
        return value

    @staticmethod
    def _summary(document: Mapping[str, Any], revision: str) -> dict[str, Any]:
        return {
            "layoutId": document["layoutId"],
            "displayName": document["displayName"],
            "status": document["status"],
            "association": deepcopy(dict(document["association"])),
            "createdAt": document["createdAt"],
            "updatedAt": document["updatedAt"],
            "currentRevision": revision,
        }

    @staticmethod
    def _summary_for(
        registry: Mapping[str, Any],
        layout_id: str,
    ) -> Mapping[str, Any]:
        for item in registry["layouts"]:
            if item["layoutId"] == layout_id:
                return item
        raise FacilityLayoutNotFoundError()

    @staticmethod
    def _with_summary(
        registry: Mapping[str, Any],
        summary: Mapping[str, Any],
        *,
        make_default: bool = False,
    ) -> dict[str, Any]:
        result = deepcopy(dict(registry))
        result["layouts"] = sorted(
            [
                deepcopy(dict(item))
                for item in result["layouts"]
                if item["layoutId"] != summary["layoutId"]
            ]
            + [deepcopy(dict(summary))],
            key=lambda item: item["layoutId"],
        )
        if result["defaultLayoutId"] is None or make_default:
            result["defaultLayoutId"] = summary["layoutId"]
        return result

    @staticmethod
    def _replace_file(source: str, destination: str) -> None:
        for attempt in range(6):
            try:
                os.replace(source, destination)
                return
            except (FileNotFoundError, PermissionError):
                if attempt == 5:
                    raise
                time.sleep(0.02 * (attempt + 1))

    def _atomic_write(self, path: Path, payload: bytes) -> None:
        native_parent = _native_fs_path(path.parent)
        native_path = _native_fs_path(path)
        temporary_name: Optional[str] = None
        try:
            os.makedirs(native_parent, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".fl-",
                suffix=".tmp",
                dir=native_parent,
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            self._replace_file(temporary_name, native_path)
            temporary_name = None
        except OSError as exc:
            raise FacilityLayoutWriteError(
                "layout_write_failed",
                "Failed to write Facility Layout storage.",
            ) from exc
        finally:
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name)
                except OSError:
                    pass

    @staticmethod
    def _remove_file(path: Path) -> None:
        try:
            os.unlink(_native_fs_path(path))
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise FacilityLayoutWriteError(
                "layout_rollback_failed",
                "Failed to restore Facility Layout storage.",
            ) from exc

    def _write_registry(
        self,
        tenant_id: str,
        site_id: str,
        registry: Mapping[str, Any],
    ) -> None:
        path = self._registry_path(tenant_id, site_id)
        native_path = _native_fs_path(path)
        previous: Optional[bytes] = None
        if os.path.exists(native_path):
            previous = _read_bytes(path)
        try:
            self._atomic_write(path, _canonical_json_bytes(registry))
            self._after_registry_write(path)
        except FacilityLayoutRepositoryError:
            try:
                if previous is None:
                    self._remove_file(path)
                else:
                    self._atomic_write(path, previous)
            except FacilityLayoutRepositoryError as rollback_exc:
                raise FacilityLayoutIntegrityError(
                    "layout_registry_rollback_failed",
                    "Facility Layout registry failed and could not be restored.",
                ) from rollback_exc
            raise

    def _after_registry_write(self, path: Path) -> None:
        """Fault-injection seam used to verify registry-last rollback."""

    def _validate(
        self,
        document: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        findings = _core_findings(document)
        validator = self._validator
        if validator is None:
            validator = _load_default_validator()
        if validator is not None:
            findings.extend(_validation_findings(validator(deepcopy(document))))
        errors = [
            item for item in findings if str(item.get("severity")).lower() == "error"
        ]
        if errors:
            raise FacilityLayoutValidationError(findings)
        return findings

    @staticmethod
    def _assert_document_scope(
        document: Mapping[str, Any],
        *,
        site_id: str,
        layout_id: Optional[str] = None,
    ) -> None:
        association = document.get("association")
        if (
            not isinstance(association, Mapping)
            or association.get("siteId") != site_id
        ):
            raise FacilityLayoutNotFoundError()
        if layout_id is not None and document.get("layoutId") != layout_id:
            raise FacilityLayoutNotFoundError()

    def _load_current(
        self,
        tenant_id: str,
        site_id: str,
        layout_id: str,
        registry: Mapping[str, Any],
    ) -> tuple[dict[str, Any], bytes, str, Mapping[str, Any]]:
        summary = self._summary_for(registry, layout_id)
        document, payload = _read_json_object(
            self._layout_path(tenant_id, site_id, layout_id)
        )
        revision = _hash_bytes(payload)
        if revision != summary["currentRevision"]:
            raise FacilityLayoutIntegrityError(
                "layout_registry_revision_mismatch",
                "Facility Layout bytes do not match the authoritative registry.",
            )
        if document.get("layoutId") != layout_id:
            raise FacilityLayoutIntegrityError(
                "layout_identity_mismatch",
                "Facility Layout identity does not match its registry entry.",
            )
        association = document.get("association")
        if (
            not isinstance(association, Mapping)
            or association.get("siteId") != site_id
        ):
            raise FacilityLayoutIntegrityError(
                "layout_scope_mismatch",
                "Facility Layout scope does not match its registry.",
            )
        if document.get("schemaVersion") == FACILITY_LAYOUT_SCHEMA_VERSION:
            try:
                canonical_payload = canonical_layout_bytes(document)
            except FacilityLayoutError as exc:
                raise FacilityLayoutIntegrityError(
                    "layout_asset_invalid",
                    "Stored Facility Layout failed validation.",
                ) from exc
            if canonical_payload != payload:
                raise FacilityLayoutIntegrityError(
                    "layout_asset_not_canonical",
                    "Facility Layout bytes are not canonical.",
                )
        return document, payload, revision, summary

    def _record(
        self,
        document: Mapping[str, Any],
        revision: str,
        default_layout_id: Optional[str],
        findings: Iterable[Mapping[str, Any]] = (),
        *,
        changed: bool,
    ) -> dict[str, Any]:
        schema_version = document.get("schemaVersion")
        return {
            "layout": deepcopy(dict(document)),
            "revision": revision,
            "isDefault": document.get("layoutId") == default_layout_id,
            "readOnly": schema_version != FACILITY_LAYOUT_SCHEMA_VERSION
            or document.get("status") == "archived",
            "changed": changed,
            "findings": [deepcopy(dict(item)) for item in findings],
        }

    def registry_revision(self, principal: Any, site_id: str) -> str:
        tenant_id, safe_site_id = _authorize(principal, site_id, "layout.read")
        registry = self._load_registry(tenant_id, safe_site_id)
        return _hash_bytes(_canonical_json_bytes(registry))

    def list_layouts(
        self,
        principal: Any,
        site_id: str,
        *,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        tenant_id, safe_site_id = _authorize(principal, site_id, "layout.read")
        with _WRITE_LOCK:
            registry = self._load_registry(tenant_id, safe_site_id)
            summaries = []
            for item in registry["layouts"]:
                self._load_current(
                    tenant_id,
                    safe_site_id,
                    item["layoutId"],
                    registry,
                )
                if include_archived or item["status"] != "archived":
                    summary = deepcopy(dict(item))
                    summary["isDefault"] = (
                        item["layoutId"] == registry["defaultLayoutId"]
                    )
                    summaries.append(summary)
            return {
                "defaultLayoutId": registry["defaultLayoutId"],
                "layouts": summaries,
                "registryRevision": _hash_bytes(_canonical_json_bytes(registry)),
            }

    def create_layout(
        self,
        principal: Any,
        site_id: str,
        document: Mapping[str, Any],
        *,
        make_default: bool = False,
    ) -> dict[str, Any]:
        tenant_id, safe_site_id = _authorize(principal, site_id, "layout.create")
        candidate = deepcopy(dict(document))
        layout_id = _validate_layout_id(str(candidate.get("layoutId") or ""))
        self._assert_document_scope(candidate, site_id=safe_site_id)
        if candidate.get("schemaVersion") != FACILITY_LAYOUT_SCHEMA_VERSION:
            raise FacilityLayoutReadOnlyError(
                "unsupported_schema_version_read_only",
                "Future Facility Layout schemas are read-only.",
            )
        if candidate.get("status") == "archived":
            raise FacilityLayoutValidationError(
                code="archived_layout_creation_forbidden",
                message="A new Facility Layout cannot start archived.",
            )
        timestamp = self._timestamp()
        candidate["createdAt"] = timestamp
        candidate["updatedAt"] = timestamp
        candidate = canonicalize_layout(candidate)
        findings = self._validate(candidate)
        payload = canonical_layout_bytes(candidate)
        revision = _hash_bytes(payload)

        with _WRITE_LOCK:
            registry = self._load_registry(tenant_id, safe_site_id)
            if any(item["layoutId"] == layout_id for item in registry["layouts"]):
                raise FacilityLayoutConflictError(
                    self._summary_for(registry, layout_id)["currentRevision"]
                )
            asset = self._layout_path(
                tenant_id,
                safe_site_id,
                layout_id,
            )
            if _is_file(asset):
                raise FacilityLayoutIntegrityError(
                    "unregistered_layout_asset",
                    "An unregistered Facility Layout asset already exists.",
                )
            next_registry = self._with_summary(
                registry,
                self._summary(candidate, revision),
                make_default=make_default,
            )
            try:
                self._atomic_write(asset, payload)
                try:
                    self._write_registry(
                        tenant_id,
                        safe_site_id,
                        next_registry,
                    )
                except FacilityLayoutRepositoryError:
                    self._remove_file(asset)
                    raise
            except FacilityLayoutRepositoryError:
                raise
            except OSError as exc:
                self._remove_file(asset)
                raise FacilityLayoutWriteError(
                    "layout_write_failed",
                    "Failed to create Facility Layout.",
                ) from exc
            return self._record(
                candidate,
                revision,
                next_registry["defaultLayoutId"],
                findings,
                changed=True,
            )

    def get_layout(
        self,
        principal: Any,
        site_id: str,
        layout_id: str,
    ) -> dict[str, Any]:
        tenant_id, safe_site_id = _authorize(principal, site_id, "layout.read")
        safe_layout_id = _validate_layout_id(layout_id)
        with _WRITE_LOCK:
            registry = self._load_registry(tenant_id, safe_site_id)
            document, _, revision, _ = self._load_current(
                tenant_id,
                safe_site_id,
                safe_layout_id,
                registry,
            )
            return self._record(
                document,
                revision,
                registry["defaultLayoutId"],
                changed=False,
            )

    def get_layout_revision(
        self,
        principal: Any,
        site_id: str,
        layout_id: str,
        revision: str,
    ) -> dict[str, Any]:
        tenant_id, safe_site_id = _authorize(principal, site_id, "layout.read")
        safe_layout_id = _validate_layout_id(layout_id)
        if not isinstance(revision, str) or not _REVISION_RE.fullmatch(revision):
            raise FacilityLayoutNotFoundError()
        with _WRITE_LOCK:
            registry = self._load_registry(tenant_id, safe_site_id)
            current, current_payload, current_revision, _ = self._load_current(
                tenant_id,
                safe_site_id,
                safe_layout_id,
                registry,
            )
            if revision == current_revision:
                document = current
                payload = current_payload
            else:
                backup_path = self._backup_path(
                    tenant_id,
                    safe_site_id,
                    safe_layout_id,
                    revision,
                )
                document, payload = _read_json_object(backup_path)
                if _hash_bytes(payload) != revision:
                    raise FacilityLayoutIntegrityError(
                        "layout_backup_revision_mismatch",
                        "Facility Layout backup bytes do not match their revision.",
                    )
            if (
                document.get("layoutId") != safe_layout_id
                or not isinstance(document.get("association"), Mapping)
                or document["association"].get("siteId") != safe_site_id
            ):
                raise FacilityLayoutIntegrityError(
                    "layout_backup_identity_mismatch",
                    "Facility Layout backup identity is invalid.",
                )
            return self._record(
                document,
                revision,
                registry["defaultLayoutId"],
                changed=False,
            )

    def _write_backup(
        self,
        path: Path,
        payload: bytes,
    ) -> bool:
        if _is_file(path):
            if _read_bytes(path) != payload:
                raise FacilityLayoutIntegrityError(
                    "layout_backup_conflict",
                    "Immutable Facility Layout backup content differs.",
                )
            return False
        self._atomic_write(path, payload)
        return True

    def save_layout(
        self,
        principal: Any,
        site_id: str,
        layout_id: str,
        document: Mapping[str, Any],
        base_revision: str,
    ) -> dict[str, Any]:
        tenant_id, safe_site_id = _authorize(principal, site_id, "layout.edit")
        safe_layout_id = _validate_layout_id(layout_id)
        candidate = deepcopy(dict(document))
        self._assert_document_scope(
            candidate,
            site_id=safe_site_id,
            layout_id=safe_layout_id,
        )

        with _WRITE_LOCK:
            registry = self._load_registry(tenant_id, safe_site_id)
            stored, stored_payload, current_revision, _ = self._load_current(
                tenant_id,
                safe_site_id,
                safe_layout_id,
                registry,
            )
            if base_revision != current_revision:
                raise FacilityLayoutConflictError(current_revision)
            if stored.get("schemaVersion") != FACILITY_LAYOUT_SCHEMA_VERSION:
                raise FacilityLayoutReadOnlyError(
                    "unsupported_schema_version_read_only",
                    "Future Facility Layout schemas are read-only.",
                )
            if stored.get("status") == "archived":
                raise FacilityLayoutReadOnlyError(
                    "archived_layout_read_only",
                    "Archived Facility Layouts are read-only.",
                )
            if candidate.get("schemaVersion") != FACILITY_LAYOUT_SCHEMA_VERSION:
                raise FacilityLayoutReadOnlyError(
                    "unsupported_schema_version_read_only",
                    "Future Facility Layout schemas are read-only.",
                )

            candidate["layoutId"] = safe_layout_id
            candidate["createdAt"] = stored["createdAt"]
            candidate["updatedAt"] = stored["updatedAt"]
            candidate = canonicalize_layout(candidate)
            findings = self._validate(candidate)
            comparison_payload = canonical_layout_bytes(candidate)
            if comparison_payload == stored_payload:
                return self._record(
                    stored,
                    current_revision,
                    registry["defaultLayoutId"],
                    findings,
                    changed=False,
                )

            if (
                candidate.get("status") == "archived"
                and registry["defaultLayoutId"] == safe_layout_id
            ):
                raise FacilityLayoutValidationError(
                    code="default_layout_cannot_be_archived",
                    message="The default Facility Layout cannot be archived.",
                )
            candidate["updatedAt"] = self._timestamp()
            candidate = canonicalize_layout(candidate)
            findings = self._validate(candidate)
            next_payload = canonical_layout_bytes(candidate)
            next_revision = _hash_bytes(next_payload)
            next_registry = self._with_summary(
                registry,
                self._summary(candidate, next_revision),
            )
            asset = self._layout_path(
                tenant_id,
                safe_site_id,
                safe_layout_id,
            )
            backup = self._backup_path(
                tenant_id,
                safe_site_id,
                safe_layout_id,
                current_revision,
            )
            backup_created = False
            layout_replaced = False
            try:
                backup_created = self._write_backup(backup, stored_payload)
                self._atomic_write(asset, next_payload)
                layout_replaced = True
                self._write_registry(
                    tenant_id,
                    safe_site_id,
                    next_registry,
                )
            except FacilityLayoutRepositoryError:
                rollback_error: Optional[BaseException] = None
                if layout_replaced:
                    try:
                        self._atomic_write(asset, stored_payload)
                    except BaseException as exc:
                        rollback_error = exc
                if backup_created:
                    try:
                        self._remove_file(backup)
                    except FacilityLayoutRepositoryError as exc:
                        rollback_error = rollback_error or exc
                if rollback_error is not None:
                    raise FacilityLayoutIntegrityError(
                        "layout_rollback_failed",
                        "Facility Layout rollback failed.",
                    ) from rollback_error
                raise
            return self._record(
                candidate,
                next_revision,
                next_registry["defaultLayoutId"],
                findings,
                changed=True,
            )

    def archive_layout(
        self,
        principal: Any,
        site_id: str,
        layout_id: str,
        base_revision: str,
    ) -> dict[str, Any]:
        tenant_id, safe_site_id = _authorize(principal, site_id, "layout.archive")
        safe_layout_id = _validate_layout_id(layout_id)
        with _WRITE_LOCK:
            registry = self._load_registry(tenant_id, safe_site_id)
            document, _, current_revision, _ = self._load_current(
                tenant_id,
                safe_site_id,
                safe_layout_id,
                registry,
            )
            if base_revision != current_revision:
                raise FacilityLayoutConflictError(current_revision)
            if document.get("status") == "archived":
                return self._record(
                    document,
                    current_revision,
                    registry["defaultLayoutId"],
                    changed=False,
                )
            if registry["defaultLayoutId"] == safe_layout_id:
                raise FacilityLayoutValidationError(
                    code="default_layout_cannot_be_archived",
                    message="The default Facility Layout cannot be archived.",
                )
        candidate = deepcopy(document)
        candidate["status"] = "archived"
        return self.save_layout(
            principal,
            safe_site_id,
            safe_layout_id,
            candidate,
            current_revision,
        )

    def set_default_layout(
        self,
        principal: Any,
        site_id: str,
        layout_id: str,
    ) -> dict[str, Any]:
        tenant_id, safe_site_id = _authorize(principal, site_id, "layout.edit")
        safe_layout_id = _validate_layout_id(layout_id)
        with _WRITE_LOCK:
            registry = self._load_registry(tenant_id, safe_site_id)
            summary = self._summary_for(registry, safe_layout_id)
            self._load_current(
                tenant_id,
                safe_site_id,
                safe_layout_id,
                registry,
            )
            if summary["status"] == "archived":
                raise FacilityLayoutReadOnlyError(
                    "archived_layout_read_only",
                    "Archived Facility Layouts cannot become the default.",
                )
            if registry["defaultLayoutId"] == safe_layout_id:
                return {
                    "defaultLayoutId": safe_layout_id,
                "registryRevision": _hash_bytes(_canonical_json_bytes(registry)),
                    "changed": False,
                }
            next_registry = deepcopy(registry)
            next_registry["defaultLayoutId"] = safe_layout_id
            self._write_registry(tenant_id, safe_site_id, next_registry)
            return {
                "defaultLayoutId": safe_layout_id,
                "registryRevision": _hash_bytes(
                    _canonical_json_bytes(next_registry)
                ),
                "changed": True,
            }


__all__ = [
    "FACILITY_LAYOUT_REGISTRY_VERSION",
    "FacilityLayoutAuthorizationError",
    "FacilityLayoutConflictError",
    "FacilityLayoutIntegrityError",
    "FacilityLayoutNotFoundError",
    "FacilityLayoutReadOnlyError",
    "FacilityLayoutRepository",
    "FacilityLayoutRepositoryError",
    "FacilityLayoutValidationError",
    "FacilityLayoutWriteError",
    "canonical_layout_bytes",
    "facility_layout_revision",
]
