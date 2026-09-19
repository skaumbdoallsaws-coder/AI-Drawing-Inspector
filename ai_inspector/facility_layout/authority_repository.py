"""Revisioned Facility Layout authority repositories.

Authority documents are immutable content-addressed JSON revisions. A
tenant/site-scoped registry is the only authority for current and published
pointers, and it is replaced only after a new revision has been installed.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from typing import Any, Callable, Mapping

from .authorization import (
    FacilityNotFoundError,
    FacilityPrincipal,
    FacilityRoleNotAuthorizedError,
    require_facility_action,
)
from .errors import (
    FacilityConflictError,
    FacilityIntegrityError,
    FacilityLayoutError,
    FacilityValidationError,
)


_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{64}$")
_STATUSES = frozenset(
    {"draft", "reviewed", "published", "deprecated", "archived"}
)
_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "draft": frozenset({"reviewed"}),
    "reviewed": frozenset({"published"}),
    "published": frozenset({"deprecated", "archived"}),
    "deprecated": frozenset({"archived"}),
    "archived": frozenset(),
}
_MAX_DOCUMENT_BYTES = 100 * 1024 * 1024
_MAX_REGISTRY_BYTES = 16 * 1024 * 1024

_ROOT_LOCK_GUARD = threading.Lock()
_ROOT_LOCKS: dict[str, threading.RLock] = {}


FacilityAuthorityError = FacilityLayoutError


class AuthorityValidationError(FacilityValidationError):
    pass


class AuthorityConflictError(FacilityConflictError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        current_revision: str | None = None,
    ) -> None:
        super().__init__(
            code,
            message,
            details=(
                {"currentRevision": current_revision}
                if current_revision is not None
                else None
            ),
        )
        self.current_revision = current_revision


class AuthorityIntegrityError(FacilityIntegrityError):
    pass


class AuthorityWriteError(FacilityIntegrityError):
    pass


AuthorityNotFoundError = FacilityNotFoundError
AuthorityAuthorizationError = FacilityRoleNotAuthorizedError


def _shared_lock(root: Path) -> threading.RLock:
    key = os.path.normcase(str(root.resolve()))
    with _ROOT_LOCK_GUARD:
        return _ROOT_LOCKS.setdefault(key, threading.RLock())


def _native_fs_path(path: Path) -> str:
    value = str(path)
    if os.name != "nt" or value.startswith("\\\\?\\"):
        return value
    absolute = str(path.resolve())
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise AuthorityValidationError(
            "invalid_authority_document",
            f"Authority content is not canonical JSON: {exc}",
        ) from exc
    if len(encoded) > _MAX_DOCUMENT_BYTES:
        raise AuthorityValidationError(
            "document_limit_exceeded",
            "Authority document exceeds the canonical byte limit.",
        )
    return encoded


def authority_revision(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json_bytes(document)).hexdigest()


def _validate_stable_id(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _STABLE_ID_RE.fullmatch(value):
        raise AuthorityValidationError(
            "invalid_id",
            f"{field_name} must be a stable ID.",
        )
    return value


def _validate_revision(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _REVISION_RE.fullmatch(value):
        raise AuthorityValidationError(
            "invalid_revision",
            f"{field_name} must be a lowercase SHA-256 revision.",
        )
    return value


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise AuthorityValidationError(
            "invalid_server_time",
            "Authority repository clock must return a timezone-aware datetime.",
        )
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _validate_finite_numbers(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)) or abs(float(value)) > 1_000_000:
            raise AuthorityValidationError(
                "non_finite_transform",
                f"{path} must be finite and within facility bounds.",
            )
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_finite_numbers(item, f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _validate_finite_numbers(item, f"{path}.{key}")


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AuthorityValidationError(
            "invalid_authority_document",
            f"{field_name} must be an object.",
        )
    return value


def _require_list(value: Any, field_name: str, *, maximum: int) -> list[Any]:
    if not isinstance(value, list) or len(value) > maximum:
        raise AuthorityValidationError(
            "invalid_authority_document",
            f"{field_name} must be a bounded list.",
        )
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    field_name: str,
) -> None:
    if set(value) != expected:
        raise AuthorityValidationError(
            "invalid_authority_document",
            f"{field_name} has unsupported fields.",
        )


def _validate_coordinate_frame(value: Any) -> None:
    frame = _require_mapping(value, "coordinateFrame")
    _require_exact_keys(
        frame,
        {
            "units",
            "handedness",
            "upAxis",
            "floorAxes",
            "datumId",
            "floorElevation",
        },
        "coordinateFrame",
    )
    if (
        frame.get("units") != "m"
        or frame.get("handedness") != "right"
        or frame.get("upAxis") != "+Y"
        or frame.get("floorAxes") != ["+X", "+Z"]
    ):
        raise AuthorityValidationError(
            "invalid_coordinate_frame",
            "Facility shell coordinate frame is not canonical.",
        )
    _validate_stable_id(frame.get("datumId"), "coordinateFrame.datumId")
    _validate_finite_numbers(
        frame.get("floorElevation"),
        "$.coordinateFrame.floorElevation",
    )


def _validate_source_documents(value: Any) -> None:
    documents = _require_list(value, "sourceDocuments", maximum=64)
    for index, raw in enumerate(documents):
        item = _require_mapping(raw, f"sourceDocuments[{index}]")
        _require_exact_keys(
            item,
            {"trustedSourceId", "sourceRevision", "locator"},
            f"sourceDocuments[{index}]",
        )
        _validate_stable_id(
            item.get("trustedSourceId"),
            f"sourceDocuments[{index}].trustedSourceId",
        )
        _validate_revision(
            item.get("sourceRevision"),
            f"sourceDocuments[{index}].sourceRevision",
        )
        locator = item.get("locator")
        if not isinstance(locator, str) or len(locator) > 512:
            raise AuthorityValidationError(
                "invalid_authority_document",
                f"sourceDocuments[{index}].locator is invalid.",
            )


def _validate_evidence_refs(value: Any) -> None:
    values = _require_list(value, "evidence", maximum=64)
    normalized = [_validate_stable_id(item, "evidence") for item in values]
    if len(normalized) != len(set(normalized)):
        raise AuthorityValidationError(
            "duplicate_id",
            "Evidence references must be unique.",
        )


def _validate_unresolved_items(value: Any) -> None:
    values = _require_list(value, "unresolvedItems", maximum=10_000)
    for index, raw in enumerate(values):
        item = _require_mapping(raw, f"unresolvedItems[{index}]")
        for field_name in ("findingId", "code", "message"):
            if field_name not in item:
                raise AuthorityValidationError(
                    "invalid_authority_document",
                    f"unresolvedItems[{index}] is missing {field_name}.",
                )
        _validate_stable_id(
            item["findingId"],
            f"unresolvedItems[{index}].findingId",
        )
        _validate_stable_id(item["code"], f"unresolvedItems[{index}].code")
        if not isinstance(item["message"], str) or len(item["message"]) > 2000:
            raise AuthorityValidationError(
                "invalid_authority_document",
                f"unresolvedItems[{index}].message is invalid.",
            )


def _validate_common_document(
    document: Mapping[str, Any],
    *,
    document_kind: str,
    id_field: str,
) -> None:
    required = {
        "schemaVersion",
        "documentKind",
        id_field,
        "tenantId",
        "siteId",
        "status",
        "sourceDocuments",
        "evidence",
        "unresolvedItems",
    }
    missing = sorted(required - set(document))
    if missing:
        raise AuthorityValidationError(
            "invalid_authority_document",
            f"Authority document is missing required fields: {missing}.",
        )
    if (
        document.get("schemaVersion") != 1
        or document.get("documentKind") != document_kind
    ):
        raise AuthorityValidationError(
            "unsupported_schema_version",
            "Authority document kind or schema version is unsupported.",
        )
    _validate_stable_id(document.get(id_field), id_field)
    _validate_stable_id(document.get("tenantId"), "tenantId")
    _validate_stable_id(document.get("siteId"), "siteId")
    if document.get("status") not in _STATUSES:
        raise AuthorityValidationError(
            "invalid_lifecycle_status",
            "Authority lifecycle status is unsupported.",
        )
    for forbidden in (
        "shellRevision",
        "policySetRevision",
        "vehicleProfileRevision",
    ):
        if forbidden in document:
            raise AuthorityValidationError(
                "persisted_revision_forbidden",
                "Authority content revisions are repository envelopes.",
            )
    _validate_source_documents(document["sourceDocuments"])
    _validate_evidence_refs(document["evidence"])
    _validate_unresolved_items(document["unresolvedItems"])


def _validate_document_shape(
    document: Mapping[str, Any],
    *,
    document_kind: str,
    id_field: str,
) -> dict[str, Any]:
    normalized = deepcopy(dict(_require_mapping(document, "document")))
    _validate_common_document(
        normalized,
        document_kind=document_kind,
        id_field=id_field,
    )
    if document_kind == "facility_shell":
        for field_name in ("coordinateFrame", "features", "shellConnectors"):
            if field_name not in normalized:
                raise AuthorityValidationError(
                    "invalid_authority_document",
                    f"Facility shell is missing {field_name}.",
                )
        _validate_coordinate_frame(normalized["coordinateFrame"])
        features = _require_list(
            normalized["features"],
            "features",
            maximum=100_000,
        )
        feature_ids = []
        for index, raw in enumerate(features):
            item = _require_mapping(raw, f"features[{index}]")
            feature_ids.append(
                _validate_stable_id(
                    item.get("featureId"),
                    f"features[{index}].featureId",
                )
            )
            if not isinstance(item.get("geometry"), Mapping):
                raise AuthorityValidationError(
                    "invalid_authority_document",
                    f"features[{index}].geometry must be an object.",
                )
            _validate_evidence_refs(item.get("evidence"))
        connectors = _require_list(
            normalized["shellConnectors"],
            "shellConnectors",
            maximum=4096,
        )
        connector_ids = []
        for index, raw in enumerate(connectors):
            item = _require_mapping(raw, f"shellConnectors[{index}]")
            connector_ids.append(
                _validate_stable_id(
                    item.get("connectorId"),
                    f"shellConnectors[{index}].connectorId",
                )
            )
            for vector_name in ("position", "facing"):
                vector = _require_mapping(
                    item.get(vector_name),
                    f"shellConnectors[{index}].{vector_name}",
                )
                _require_exact_keys(
                    vector,
                    {"x", "y", "z"},
                    f"shellConnectors[{index}].{vector_name}",
                )
            _validate_evidence_refs(item.get("evidence"))
        if len(feature_ids) != len(set(feature_ids)) or len(connector_ids) != len(
            set(connector_ids)
        ):
            raise AuthorityValidationError(
                "duplicate_id",
                "Facility shell feature and connector IDs must be unique.",
            )
    elif document_kind == "policy_set":
        if not isinstance(normalized.get("applicability"), Mapping):
            raise AuthorityValidationError(
                "invalid_authority_document",
                "Policy set applicability must be an object.",
            )
        rules = _require_list(
            normalized.get("deterministicRules"),
            "deterministicRules",
            maximum=5000,
        )
        rule_ids = []
        for index, raw in enumerate(rules):
            item = _require_mapping(raw, f"deterministicRules[{index}]")
            rule_ids.append(
                _validate_stable_id(
                    item.get("ruleId"),
                    f"deterministicRules[{index}].ruleId",
                )
            )
            if not isinstance(item.get("applicability"), Mapping) or not isinstance(
                item.get("parameters"), Mapping
            ):
                raise AuthorityValidationError(
                    "invalid_authority_document",
                    f"deterministicRules[{index}] is invalid.",
                )
            _validate_evidence_refs(item.get("evidence"))
        if len(rule_ids) != len(set(rule_ids)):
            raise AuthorityValidationError(
                "duplicate_id",
                "Policy rule IDs must be unique.",
            )
    elif document_kind == "vehicle_profile":
        required = {
            "displayName",
            "overallDimensions",
            "footprint",
            "wheelbase",
            "steeringLimits",
            "speedLimits",
            "loadLimits",
            "gradeLimits",
            "reversePolicy",
        }
        missing = sorted(required - set(normalized))
        if missing:
            raise AuthorityValidationError(
                "invalid_authority_document",
                f"Vehicle profile is missing required fields: {missing}.",
            )
        name = normalized["displayName"]
        if not isinstance(name, str) or not name or len(name) > 120:
            raise AuthorityValidationError(
                "invalid_authority_document",
                "Vehicle displayName is invalid.",
            )
        dimensions = _require_mapping(
            normalized["overallDimensions"],
            "overallDimensions",
        )
        _require_exact_keys(
            dimensions,
            {"length", "width", "height"},
            "overallDimensions",
        )
        if any(
            isinstance(dimensions[key], bool)
            or not isinstance(dimensions[key], (int, float))
            or dimensions[key] < 0
            for key in dimensions
        ):
            raise AuthorityValidationError(
                "invalid_authority_document",
                "Vehicle dimensions must be non-negative numbers.",
            )
        footprint = _require_list(
            normalized["footprint"],
            "footprint",
            maximum=2048,
        )
        if len(footprint) < 3:
            raise AuthorityValidationError(
                "invalid_authority_document",
                "Vehicle footprint requires at least three points.",
            )
        vertices = []
        for index, raw in enumerate(footprint):
            point = _require_mapping(raw, f"footprint[{index}]")
            _require_exact_keys(point, {"x", "z"}, f"footprint[{index}]")
            vertices.append((point.get("x"), point.get("z")))
        if len(vertices) != len(set(vertices)):
            raise AuthorityValidationError(
                "invalid_authority_document",
                "Vehicle footprint vertices must be unique.",
            )
        asset_ref = normalized.get("assetDefinitionRef")
        if asset_ref is not None:
            asset_ref = _require_mapping(
                asset_ref,
                "assetDefinitionRef",
            )
            _require_exact_keys(
                asset_ref,
                {"assetId", "assetDefinitionRevision"},
                "assetDefinitionRef",
            )
            _validate_stable_id(
                asset_ref.get("assetId"),
                "assetDefinitionRef.assetId",
            )
            _validate_revision(
                asset_ref.get("assetDefinitionRevision"),
                "assetDefinitionRef.assetDefinitionRevision",
            )
    else:
        raise AuthorityValidationError(
            "unsupported_authority_kind",
            "Authority document kind is unsupported.",
        )
    _validate_finite_numbers(normalized)
    _canonical_json_bytes(normalized)
    return normalized


@dataclass(frozen=True)
class AuthorityDocumentEnvelope:
    document: Mapping[str, Any]
    revision: str
    current_revision: str
    published_revision: str | None
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "document": deepcopy(dict(self.document)),
            "revision": self.revision,
            "currentRevision": self.current_revision,
            "publishedRevision": self.published_revision,
            "status": self.status,
        }


@dataclass(frozen=True)
class AuthorityMutationResult:
    envelope: AuthorityDocumentEnvelope
    changed: bool
    registry_revision: str

    def to_dict(self) -> dict[str, Any]:
        result = self.envelope.to_dict()
        result.update(
            {
                "changed": self.changed,
                "registryRevision": self.registry_revision,
            }
        )
        return result


class RevisionedAuthorityRepository:
    """Generic immutable authority store with registry-last publication."""

    def __init__(
        self,
        root: str | Path,
        *,
        document_kind: str,
        id_field: str,
        clock: Callable[[], datetime] | None = None,
        failure_injector: Callable[[str, Path], None] | None = None,
    ) -> None:
        resolved = Path(root).resolve()
        if resolved == Path(resolved.anchor):
            raise AuthorityValidationError(
                "invalid_repository_root",
                "Authority repository root cannot be a filesystem root.",
            )
        if resolved.exists() and not resolved.is_dir():
            raise AuthorityValidationError(
                "invalid_repository_root",
                "Authority repository root must be a directory.",
            )
        self.root = resolved
        self.document_kind = document_kind
        self.id_field = id_field
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._failure_injector = failure_injector
        self._lock = _shared_lock(resolved)
        self.root.mkdir(parents=True, exist_ok=True)

    def _inject(self, stage: str, path: Path) -> None:
        if self._failure_injector is not None:
            self._failure_injector(stage, path)

    @staticmethod
    def _lookup_id(value: Any) -> str:
        if not isinstance(value, str) or not _STABLE_ID_RE.fullmatch(value):
            raise AuthorityNotFoundError(
                "not_found",
                "Facility resource was not found.",
            )
        return value

    @staticmethod
    def _lookup_revision(value: Any) -> str:
        if not isinstance(value, str) or not _REVISION_RE.fullmatch(value):
            raise AuthorityNotFoundError(
                "not_found",
                "Facility resource was not found.",
            )
        return value

    def _scope_root(self, tenant_id: str, site_id: str) -> Path:
        tenant = _validate_stable_id(tenant_id, "tenantId")
        site = _validate_stable_id(site_id, "siteId")
        candidate = (
            self.root
            / tenant
            / site
            / "authority"
            / self.document_kind
        )
        try:
            candidate.resolve().relative_to(self.root)
        except ValueError as exc:
            raise AuthorityValidationError(
                "invalid_repository_path",
                "Authority repository path escaped its configured root.",
            ) from exc
        return candidate

    def _registry_path(self, tenant_id: str, site_id: str) -> Path:
        return self._scope_root(tenant_id, site_id) / "registry.json"

    def _revision_path(
        self,
        tenant_id: str,
        site_id: str,
        authority_id: str,
        revision: str,
    ) -> Path:
        authority_id = _validate_stable_id(authority_id, self.id_field)
        revision = _validate_revision(revision, "revision")
        return (
            self._scope_root(tenant_id, site_id)
            / authority_id
            / "revisions"
            / f"{revision}.json"
        )

    def _empty_registry(self, tenant_id: str, site_id: str) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "recordKind": "facility_authority_registry",
            "documentKind": self.document_kind,
            "tenantId": tenant_id,
            "siteId": site_id,
            "entries": [],
        }

    def _read_bytes(self, path: Path, *, maximum: int) -> bytes:
        try:
            size = os.stat(_native_fs_path(path)).st_size
            if size < 1 or size > maximum:
                raise AuthorityIntegrityError(
                    "authority_record_size_invalid",
                    "Authority record size is invalid.",
                )
            with open(_native_fs_path(path), "rb") as stream:
                raw = stream.read()
        except FileNotFoundError:
            raise
        except AuthorityIntegrityError:
            raise
        except OSError as exc:
            raise AuthorityIntegrityError(
                "authority_record_unreadable",
                "Authority record could not be read.",
            ) from exc
        if any(byte > 0x7F for byte in raw):
            raise AuthorityIntegrityError(
                "authority_record_not_ascii",
                "Authority record is not ASCII.",
            )
        return raw

    def _load_registry(self, tenant_id: str, site_id: str) -> dict[str, Any]:
        path = self._registry_path(tenant_id, site_id)
        try:
            raw = self._read_bytes(path, maximum=_MAX_REGISTRY_BYTES)
        except FileNotFoundError:
            return self._empty_registry(tenant_id, site_id)
        try:
            parsed = json.loads(raw.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AuthorityIntegrityError(
                "authority_registry_unreadable",
                "Authority registry is unreadable.",
            ) from exc
        if raw != _canonical_json_bytes(parsed):
            raise AuthorityIntegrityError(
                "authority_registry_not_canonical",
                "Authority registry bytes are not canonical.",
            )
        expected = {
            "schemaVersion": 1,
            "recordKind": "facility_authority_registry",
            "documentKind": self.document_kind,
            "tenantId": tenant_id,
            "siteId": site_id,
        }
        if not isinstance(parsed, dict) or any(
            parsed.get(key) != value for key, value in expected.items()
        ):
            raise AuthorityIntegrityError(
                "authority_registry_scope_mismatch",
                "Authority registry scope is invalid.",
            )
        entries = parsed.get("entries")
        if not isinstance(entries, list):
            raise AuthorityIntegrityError(
                "authority_registry_invalid",
                "Authority registry entries are invalid.",
            )
        identifiers = []
        for raw_entry in entries:
            if not isinstance(raw_entry, Mapping):
                raise AuthorityIntegrityError(
                    "authority_registry_invalid",
                    "Authority registry entry is invalid.",
                )
            authority_id = raw_entry.get("authorityId")
            try:
                authority_id = _validate_stable_id(
                    authority_id,
                    "authorityId",
                )
                current = _validate_revision(
                    raw_entry.get("currentRevision"),
                    "currentRevision",
                )
                status = raw_entry.get("status")
                history = raw_entry.get("revisionHistory")
                published = raw_entry.get("publishedRevision")
                if status not in _STATUSES:
                    raise AuthorityValidationError(
                        "invalid_lifecycle_status",
                        "Registry lifecycle status is invalid.",
                    )
                if (
                    not isinstance(history, list)
                    or not history
                    or len(history) != len(set(history))
                ):
                    raise AuthorityValidationError(
                        "invalid_revision_history",
                        "Registry revision history is invalid.",
                    )
                normalized_history = [
                    _validate_revision(item, "revisionHistory") for item in history
                ]
                if current not in normalized_history:
                    raise AuthorityValidationError(
                        "invalid_revision_history",
                        "Current revision is absent from revision history.",
                    )
                if published is not None:
                    published = _validate_revision(
                        published,
                        "publishedRevision",
                    )
                    if published not in normalized_history:
                        raise AuthorityValidationError(
                            "invalid_revision_history",
                            "Published revision is absent from revision history.",
                        )
                for field_name in ("createdAt", "updatedAt"):
                    if not isinstance(raw_entry.get(field_name), str):
                        raise AuthorityValidationError(
                            "invalid_registry_timestamp",
                            "Authority registry timestamp is invalid.",
                        )
            except AuthorityValidationError as exc:
                raise AuthorityIntegrityError(
                    "authority_registry_invalid",
                    "Authority registry entry is invalid.",
                ) from exc
            identifiers.append(authority_id)
        if identifiers != sorted(identifiers) or len(identifiers) != len(
            set(identifiers)
        ):
            raise AuthorityIntegrityError(
                "authority_registry_invalid",
                "Authority registry entries must be unique and sorted.",
            )
        return parsed

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        for attempt in range(6):
            temporary_name: str | None = None
            try:
                os.makedirs(_native_fs_path(path.parent), exist_ok=True)
                descriptor, temporary_name = tempfile.mkstemp(
                    prefix=".fa-",
                    suffix=".tmp",
                    dir=_native_fs_path(path.parent),
                )
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary_name, _native_fs_path(path))
                temporary_name = None
                return
            except (FileNotFoundError, PermissionError):
                if attempt == 5:
                    raise
                time.sleep(0.02 * (attempt + 1))
            finally:
                if temporary_name is not None:
                    try:
                        os.unlink(temporary_name)
                    except OSError:
                        pass

    def _write_immutable(
        self,
        path: Path,
        document: Mapping[str, Any],
    ) -> None:
        payload = _canonical_json_bytes(document)
        native_path = _native_fs_path(path)
        if os.path.exists(native_path):
            try:
                current = self._read_bytes(path, maximum=_MAX_DOCUMENT_BYTES)
            except FileNotFoundError:
                current = b""
            if current != payload:
                raise AuthorityConflictError(
                    "immutable_authority_revision_conflict",
                    "Immutable authority revision content differs.",
                )
            return
        try:
            self._inject("before_revision_write", path)
            self._atomic_write(path, payload)
            self._inject("after_revision_write", path)
        except FacilityAuthorityError:
            raise
        except OSError as exc:
            raise AuthorityWriteError(
                "authority_revision_write_failed",
                "Authority revision could not be written.",
            ) from exc

    def _write_registry(
        self,
        tenant_id: str,
        site_id: str,
        registry: Mapping[str, Any],
    ) -> None:
        path = self._registry_path(tenant_id, site_id)
        native_path = _native_fs_path(path)
        previous: bytes | None = None
        if os.path.exists(native_path):
            try:
                previous = self._read_bytes(
                    path,
                    maximum=_MAX_REGISTRY_BYTES,
                )
            except FileNotFoundError:
                previous = None
        try:
            self._inject("before_registry_write", path)
            self._atomic_write(path, _canonical_json_bytes(registry))
            self._inject("after_registry_write", path)
        except (FacilityAuthorityError, OSError) as exc:
            try:
                if previous is None:
                    try:
                        os.unlink(native_path)
                    except FileNotFoundError:
                        pass
                else:
                    self._atomic_write(path, previous)
            except OSError as rollback_exc:
                raise AuthorityWriteError(
                    "authority_registry_rollback_failed",
                    "Authority registry failed and could not be restored.",
                ) from rollback_exc
            if isinstance(exc, FacilityAuthorityError):
                raise
            raise AuthorityWriteError(
                "authority_registry_write_failed",
                "Authority registry could not be written.",
            ) from exc

    def registry_revision(
        self,
        principal: FacilityPrincipal,
        *,
        site_id: str,
    ) -> str:
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="authority.read",
        )
        with self._lock:
            registry = self._load_registry(principal.tenant_id, site_id)
            return hashlib.sha256(_canonical_json_bytes(registry)).hexdigest()

    @staticmethod
    def _find_entry(
        registry: Mapping[str, Any],
        authority_id: str,
    ) -> dict[str, Any] | None:
        for raw in registry["entries"]:
            if raw.get("authorityId") == authority_id:
                return deepcopy(dict(raw))
        return None

    @staticmethod
    def _replace_entry(
        registry: Mapping[str, Any],
        entry: Mapping[str, Any],
    ) -> dict[str, Any]:
        updated = deepcopy(dict(registry))
        entries = [
            deepcopy(dict(item))
            for item in updated["entries"]
            if item.get("authorityId") != entry.get("authorityId")
        ]
        entries.append(deepcopy(dict(entry)))
        updated["entries"] = sorted(
            entries,
            key=lambda item: item["authorityId"],
        )
        return updated

    def _authorize(
        self,
        principal: FacilityPrincipal,
        *,
        site_id: str,
        action: str,
    ) -> None:
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action=action,
        )

    def _validate_scoped_document(
        self,
        principal: FacilityPrincipal,
        *,
        site_id: str,
        document: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(document, Mapping):
            raise AuthorityValidationError(
                "invalid_authority_document",
                "Authority document must be an object.",
            )
        if (
            document.get("tenantId") != principal.tenant_id
            or document.get("siteId") != site_id
        ):
            raise AuthorityNotFoundError(
                "not_found",
                "Facility resource was not found.",
            )
        return _validate_document_shape(
            document,
            document_kind=self.document_kind,
            id_field=self.id_field,
        )

    @staticmethod
    def _hide_cross_scope_payload(
        principal: FacilityPrincipal,
        *,
        site_id: str,
        document: Any,
    ) -> None:
        if isinstance(document, Mapping) and (
            document.get("tenantId") != principal.tenant_id
            or document.get("siteId") != site_id
        ):
            raise AuthorityNotFoundError(
                "not_found",
                "Facility resource was not found.",
            )

    def _load_revision_document(
        self,
        *,
        tenant_id: str,
        site_id: str,
        authority_id: str,
        revision: str,
    ) -> dict[str, Any]:
        path = self._revision_path(
            tenant_id,
            site_id,
            authority_id,
            revision,
        )
        try:
            raw = self._read_bytes(path, maximum=_MAX_DOCUMENT_BYTES)
        except FileNotFoundError as exc:
            raise AuthorityNotFoundError(
                "not_found",
                "Facility resource was not found.",
            ) from exc
        if hashlib.sha256(raw).hexdigest() != revision:
            raise AuthorityIntegrityError(
                "authority_revision_mismatch",
                "Authority revision bytes do not match their identity.",
            )
        try:
            parsed = json.loads(raw.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AuthorityIntegrityError(
                "authority_revision_unreadable",
                "Authority revision is unreadable.",
            ) from exc
        try:
            normalized = _validate_document_shape(
                parsed,
                document_kind=self.document_kind,
                id_field=self.id_field,
            )
        except AuthorityValidationError as exc:
            raise AuthorityIntegrityError(
                "authority_revision_invalid",
                "Authority revision content is invalid.",
            ) from exc
        if raw != _canonical_json_bytes(normalized):
            raise AuthorityIntegrityError(
                "authority_revision_not_canonical",
                "Authority revision bytes are not canonical.",
            )
        if (
            normalized[self.id_field] != authority_id
            or normalized["tenantId"] != tenant_id
            or normalized["siteId"] != site_id
        ):
            raise AuthorityIntegrityError(
                "authority_revision_scope_mismatch",
                "Authority revision content does not match registry scope.",
            )
        return normalized

    def _envelope(
        self,
        *,
        tenant_id: str,
        site_id: str,
        entry: Mapping[str, Any],
        revision: str,
    ) -> AuthorityDocumentEnvelope:
        document = self._load_revision_document(
            tenant_id=tenant_id,
            site_id=site_id,
            authority_id=entry["authorityId"],
            revision=revision,
        )
        return AuthorityDocumentEnvelope(
            document=document,
            revision=revision,
            current_revision=entry["currentRevision"],
            published_revision=entry.get("publishedRevision"),
            status=document["status"],
        )

    def create(
        self,
        principal: FacilityPrincipal,
        *,
        site_id: str,
        document: Mapping[str, Any],
    ) -> AuthorityMutationResult:
        self._hide_cross_scope_payload(
            principal,
            site_id=site_id,
            document=document,
        )
        self._authorize(principal, site_id=site_id, action="authority.create")
        normalized = self._validate_scoped_document(
            principal,
            site_id=site_id,
            document=document,
        )
        if normalized["status"] != "draft":
            raise AuthorityValidationError(
                "invalid_lifecycle_transition",
                "New authority documents must begin in draft.",
            )
        authority_id = normalized[self.id_field]
        revision = authority_revision(normalized)
        now = _timestamp(self._clock())
        with self._lock:
            registry = self._load_registry(principal.tenant_id, site_id)
            if self._find_entry(registry, authority_id) is not None:
                raise AuthorityConflictError(
                    "authority_already_exists",
                    "Authority document already exists.",
                )
            entry = {
                "authorityId": authority_id,
                "status": "draft",
                "currentRevision": revision,
                "publishedRevision": None,
                "revisionHistory": [revision],
                "createdAt": now,
                "updatedAt": now,
            }
            self._write_immutable(
                self._revision_path(
                    principal.tenant_id,
                    site_id,
                    authority_id,
                    revision,
                ),
                normalized,
            )
            updated = self._replace_entry(registry, entry)
            self._write_registry(principal.tenant_id, site_id, updated)
            envelope = self._envelope(
                tenant_id=principal.tenant_id,
                site_id=site_id,
                entry=entry,
                revision=revision,
            )
            return AuthorityMutationResult(
                envelope=envelope,
                changed=True,
                registry_revision=hashlib.sha256(
                    _canonical_json_bytes(updated)
                ).hexdigest(),
            )

    def list_documents(
        self,
        principal: FacilityPrincipal,
        *,
        site_id: str,
    ) -> list[dict[str, Any]]:
        self._authorize(principal, site_id=site_id, action="authority.read")
        with self._lock:
            registry = self._load_registry(principal.tenant_id, site_id)
            return [
                {
                    self.id_field: entry["authorityId"],
                    "status": entry["status"],
                    "currentRevision": entry["currentRevision"],
                    "publishedRevision": entry.get("publishedRevision"),
                    "createdAt": entry["createdAt"],
                    "updatedAt": entry["updatedAt"],
                }
                for entry in registry["entries"]
            ]

    def get_current(
        self,
        principal: FacilityPrincipal,
        *,
        site_id: str,
        authority_id: str,
    ) -> AuthorityDocumentEnvelope:
        self._authorize(principal, site_id=site_id, action="authority.read")
        authority_id = self._lookup_id(authority_id)
        with self._lock:
            registry = self._load_registry(principal.tenant_id, site_id)
            entry = self._find_entry(registry, authority_id)
            if entry is None:
                raise AuthorityNotFoundError(
                    "not_found",
                    "Facility resource was not found.",
                )
            return self._envelope(
                tenant_id=principal.tenant_id,
                site_id=site_id,
                entry=entry,
                revision=entry["currentRevision"],
            )

    def get_revision(
        self,
        principal: FacilityPrincipal,
        *,
        site_id: str,
        authority_id: str,
        revision: str,
    ) -> AuthorityDocumentEnvelope:
        self._authorize(principal, site_id=site_id, action="authority.read")
        authority_id = self._lookup_id(authority_id)
        revision = self._lookup_revision(revision)
        with self._lock:
            registry = self._load_registry(principal.tenant_id, site_id)
            entry = self._find_entry(registry, authority_id)
            if entry is None or revision not in entry["revisionHistory"]:
                raise AuthorityNotFoundError(
                    "not_found",
                    "Facility resource was not found.",
                )
            return self._envelope(
                tenant_id=principal.tenant_id,
                site_id=site_id,
                entry=entry,
                revision=revision,
            )

    def get_published(
        self,
        principal: FacilityPrincipal,
        *,
        site_id: str,
        authority_id: str,
        revision: str | None = None,
    ) -> AuthorityDocumentEnvelope:
        self._authorize(principal, site_id=site_id, action="authority.read")
        authority_id = self._lookup_id(authority_id)
        with self._lock:
            registry = self._load_registry(principal.tenant_id, site_id)
            entry = self._find_entry(registry, authority_id)
            if (
                entry is None
                or entry["status"] != "published"
                or entry.get("publishedRevision") is None
            ):
                raise AuthorityNotFoundError(
                    "not_found",
                    "Facility resource was not found.",
                )
            published = entry["publishedRevision"]
            if revision is not None and self._lookup_revision(revision) != published:
                raise AuthorityNotFoundError(
                    "not_found",
                    "Facility resource was not found.",
                )
            return self._envelope(
                tenant_id=principal.tenant_id,
                site_id=site_id,
                entry=entry,
                revision=published,
            )

    def save_draft(
        self,
        principal: FacilityPrincipal,
        *,
        site_id: str,
        document: Mapping[str, Any],
        expected_revision: str,
    ) -> AuthorityMutationResult:
        self._hide_cross_scope_payload(
            principal,
            site_id=site_id,
            document=document,
        )
        self._authorize(principal, site_id=site_id, action="authority.edit")
        normalized = self._validate_scoped_document(
            principal,
            site_id=site_id,
            document=document,
        )
        if normalized["status"] != "draft":
            raise AuthorityValidationError(
                "invalid_lifecycle_transition",
                "Content edits are permitted only while an authority is draft.",
            )
        authority_id = normalized[self.id_field]
        expected_revision = _validate_revision(
            expected_revision,
            "expectedRevision",
        )
        with self._lock:
            registry = self._load_registry(principal.tenant_id, site_id)
            entry = self._find_entry(registry, authority_id)
            if entry is None:
                raise AuthorityNotFoundError(
                    "not_found",
                    "Facility resource was not found.",
                )
            current_revision = entry["currentRevision"]
            if expected_revision != current_revision:
                raise AuthorityConflictError(
                    "revision_conflict",
                    "Authority document changed since it was read.",
                    current_revision=current_revision,
                )
            current = self._load_revision_document(
                tenant_id=principal.tenant_id,
                site_id=site_id,
                authority_id=authority_id,
                revision=current_revision,
            )
            if entry["status"] != "draft" or current["status"] != "draft":
                raise AuthorityValidationError(
                    "invalid_lifecycle_transition",
                    "Only draft authority content may be edited.",
                )
            revision = authority_revision(normalized)
            if revision == current_revision:
                return AuthorityMutationResult(
                    envelope=self._envelope(
                        tenant_id=principal.tenant_id,
                        site_id=site_id,
                        entry=entry,
                        revision=current_revision,
                    ),
                    changed=False,
                    registry_revision=hashlib.sha256(
                        _canonical_json_bytes(registry)
                    ).hexdigest(),
                )
            self._write_immutable(
                self._revision_path(
                    principal.tenant_id,
                    site_id,
                    authority_id,
                    revision,
                ),
                normalized,
            )
            updated_entry = deepcopy(entry)
            updated_entry["currentRevision"] = revision
            updated_entry["revisionHistory"].append(revision)
            updated_entry["updatedAt"] = _timestamp(self._clock())
            updated = self._replace_entry(registry, updated_entry)
            self._write_registry(principal.tenant_id, site_id, updated)
            return AuthorityMutationResult(
                envelope=self._envelope(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    entry=updated_entry,
                    revision=revision,
                ),
                changed=True,
                registry_revision=hashlib.sha256(
                    _canonical_json_bytes(updated)
                ).hexdigest(),
            )

    def _transition(
        self,
        principal: FacilityPrincipal,
        *,
        site_id: str,
        authority_id: str,
        expected_revision: str,
        target_status: str,
        action: str,
    ) -> AuthorityMutationResult:
        self._authorize(principal, site_id=site_id, action=action)
        authority_id = self._lookup_id(authority_id)
        expected_revision = _validate_revision(
            expected_revision,
            "expectedRevision",
        )
        if target_status not in _STATUSES:
            raise AuthorityValidationError(
                "invalid_lifecycle_status",
                "Authority lifecycle status is unsupported.",
            )
        with self._lock:
            registry = self._load_registry(principal.tenant_id, site_id)
            entry = self._find_entry(registry, authority_id)
            if entry is None:
                raise AuthorityNotFoundError(
                    "not_found",
                    "Facility resource was not found.",
                )
            current_revision = entry["currentRevision"]
            if expected_revision != current_revision:
                raise AuthorityConflictError(
                    "revision_conflict",
                    "Authority document changed since it was read.",
                    current_revision=current_revision,
                )
            current = self._load_revision_document(
                tenant_id=principal.tenant_id,
                site_id=site_id,
                authority_id=authority_id,
                revision=current_revision,
            )
            source_status = current["status"]
            if target_status not in _TRANSITIONS[source_status]:
                raise AuthorityValidationError(
                    "invalid_lifecycle_transition",
                    f"Cannot move authority from {source_status} to {target_status}.",
                )
            transitioned = deepcopy(current)
            transitioned["status"] = target_status
            normalized = _validate_document_shape(
                transitioned,
                document_kind=self.document_kind,
                id_field=self.id_field,
            )
            revision = authority_revision(normalized)
            self._write_immutable(
                self._revision_path(
                    principal.tenant_id,
                    site_id,
                    authority_id,
                    revision,
                ),
                normalized,
            )
            updated_entry = deepcopy(entry)
            updated_entry["status"] = target_status
            updated_entry["currentRevision"] = revision
            updated_entry["revisionHistory"].append(revision)
            if target_status == "published":
                updated_entry["publishedRevision"] = revision
            updated_entry["updatedAt"] = _timestamp(self._clock())
            updated = self._replace_entry(registry, updated_entry)
            self._write_registry(principal.tenant_id, site_id, updated)
            return AuthorityMutationResult(
                envelope=self._envelope(
                    tenant_id=principal.tenant_id,
                    site_id=site_id,
                    entry=updated_entry,
                    revision=revision,
                ),
                changed=True,
                registry_revision=hashlib.sha256(
                    _canonical_json_bytes(updated)
                ).hexdigest(),
            )

    def review(
        self,
        principal: FacilityPrincipal,
        *,
        site_id: str,
        authority_id: str,
        expected_revision: str,
    ) -> AuthorityMutationResult:
        return self._transition(
            principal,
            site_id=site_id,
            authority_id=authority_id,
            expected_revision=expected_revision,
            target_status="reviewed",
            action="authority.review",
        )

    def publish(
        self,
        principal: FacilityPrincipal,
        *,
        site_id: str,
        authority_id: str,
        expected_revision: str,
    ) -> AuthorityMutationResult:
        return self._transition(
            principal,
            site_id=site_id,
            authority_id=authority_id,
            expected_revision=expected_revision,
            target_status="published",
            action="authority.publish",
        )

    def deprecate(
        self,
        principal: FacilityPrincipal,
        *,
        site_id: str,
        authority_id: str,
        expected_revision: str,
    ) -> AuthorityMutationResult:
        return self._transition(
            principal,
            site_id=site_id,
            authority_id=authority_id,
            expected_revision=expected_revision,
            target_status="deprecated",
            action="authority.deprecate",
        )

    def archive(
        self,
        principal: FacilityPrincipal,
        *,
        site_id: str,
        authority_id: str,
        expected_revision: str,
    ) -> AuthorityMutationResult:
        return self._transition(
            principal,
            site_id=site_id,
            authority_id=authority_id,
            expected_revision=expected_revision,
            target_status="archived",
            action="authority.archive",
        )

    # Concise compatibility aliases for service adapters.
    get = get_current
    list = list_documents
    update = save_draft


class FacilityShellRepository(RevisionedAuthorityRepository):
    def __init__(
        self,
        root: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
        failure_injector: Callable[[str, Path], None] | None = None,
    ) -> None:
        super().__init__(
            root,
            document_kind="facility_shell",
            id_field="shellId",
            clock=clock,
            failure_injector=failure_injector,
        )


class PolicySetRepository(RevisionedAuthorityRepository):
    def __init__(
        self,
        root: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
        failure_injector: Callable[[str, Path], None] | None = None,
    ) -> None:
        super().__init__(
            root,
            document_kind="policy_set",
            id_field="policySetId",
            clock=clock,
            failure_injector=failure_injector,
        )


class VehicleProfileRepository(RevisionedAuthorityRepository):
    def __init__(
        self,
        root: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
        failure_injector: Callable[[str, Path], None] | None = None,
    ) -> None:
        super().__init__(
            root,
            document_kind="vehicle_profile",
            id_field="vehicleProfileId",
            clock=clock,
            failure_injector=failure_injector,
        )
