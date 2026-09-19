"""Immutable saved and unsaved base artifacts for Facility design runs."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping

from .canonical import canonicalize_layout, layout_revision
from .design_brief import canonical_design_bytes, design_revision


FACILITY_DESIGN_BASE_SCHEMA_VERSION = "facility-design-base-v1"
FACILITY_DESIGN_BASE_KINDS = frozenset(
    {"saved_layout", "receipt_bound_draft", "editor_draft"}
)


class FacilityDesignBaseError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = deepcopy(dict(details or {}))


def _fail(code: str, message: str, **details: Any) -> None:
    raise FacilityDesignBaseError(code, message, details=details)


def _stable_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        _fail("facility_design_base_invalid", f"{field} must be a stable identifier.", field=field)
    candidate = value.strip()
    if not candidate[0].isalnum() or any(
        not (character.isalnum() or character in "._:-") for character in candidate
    ):
        _fail("facility_design_base_invalid", f"{field} must be a stable identifier.", field=field)
    return candidate


def _revision(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        _fail("facility_design_base_invalid", f"{field} must be a lowercase SHA-256 revision.", field=field)
    return value


def _timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str):
        _fail("facility_design_base_invalid", f"{field} must be a UTC timestamp.", field=field)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FacilityDesignBaseError(
            "facility_design_base_invalid",
            f"{field} must be a UTC timestamp.",
            details={"field": field},
        ) from exc
    if parsed.tzinfo is None:
        _fail("facility_design_base_invalid", f"{field} must be a UTC timestamp.", field=field)
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _source_ref(base_kind: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("facility_design_base_invalid", "sourceRef must be an object.")
    result = deepcopy(dict(value))
    fields_by_kind = {
        "saved_layout": {
            "repositoryRecordRevision",
            "savedLayoutRevision",
        },
        "receipt_bound_draft": {
            "generationRunId",
            "receiptId",
            "receiptRevision",
            "resultDraftRevision",
            "savedBaseRevision",
        },
        "editor_draft": {
            "editorSessionId",
            "editorGenerationId",
            "commandJournalHash",
            "savedBaseRevision",
            "capturedDraftRevision",
        },
    }
    expected = fields_by_kind[base_kind]
    if set(result) != expected:
        _fail(
            "facility_design_base_invalid",
            "sourceRef fields do not match baseKind.",
            baseKind=base_kind,
            expectedFields=sorted(expected),
        )
    for field in sorted(expected):
        if field.endswith("Revision") or field.endswith("Hash"):
            result[field] = _revision(result[field], f"sourceRef.{field}")
        else:
            result[field] = _stable_text(result[field], f"sourceRef.{field}")
    return result


def _without_revision(value: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(value))
    result.pop("baseRevision", None)
    return result


def validate_facility_design_base(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("facility_design_base_invalid", "FacilityDesignBase must be an object.")
    result = deepcopy(dict(value))
    required = {
        "schemaVersion",
        "baseId",
        "baseRevision",
        "baseKind",
        "tenantId",
        "siteId",
        "workspaceId",
        "layoutId",
        "layoutRevision",
        "savedLayoutRevision",
        "sourceRef",
        "document",
        "capturedAt",
    }
    if set(result) != required:
        _fail(
            "facility_design_base_invalid",
            "FacilityDesignBase fields are invalid.",
            expectedFields=sorted(required),
        )
    if result["schemaVersion"] != FACILITY_DESIGN_BASE_SCHEMA_VERSION:
        _fail("facility_design_base_version_unsupported", "FacilityDesignBase version is unsupported.")
    for field in ("baseId", "tenantId", "siteId", "workspaceId", "layoutId"):
        result[field] = _stable_text(result[field], field)
    result["baseRevision"] = _revision(result["baseRevision"], "baseRevision")
    result["layoutRevision"] = _revision(result["layoutRevision"], "layoutRevision")
    result["savedLayoutRevision"] = _revision(result["savedLayoutRevision"], "savedLayoutRevision")
    if result["baseKind"] not in FACILITY_DESIGN_BASE_KINDS:
        _fail("facility_design_base_kind_unsupported", "FacilityDesignBase kind is unsupported.", baseKind=result["baseKind"])
    result["sourceRef"] = _source_ref(result["baseKind"], result["sourceRef"])
    try:
        document = canonicalize_layout(result["document"])
        document_revision = layout_revision(document)
    except (TypeError, ValueError) as exc:
        raise FacilityDesignBaseError(
            "facility_design_base_layout_invalid",
            "FacilityDesignBase document is not a valid canonical layout.",
        ) from exc
    if document.get("layoutId") != result["layoutId"]:
        _fail("facility_design_base_layout_mismatch", "Base document layoutId does not match the base scope.")
    if document_revision != result["layoutRevision"]:
        _fail(
            "facility_design_base_revision_mismatch",
            "Base document does not match layoutRevision.",
            expected=result["layoutRevision"],
            actual=document_revision,
        )
    if result["baseKind"] == "saved_layout":
        if result["layoutRevision"] != result["savedLayoutRevision"]:
            _fail("facility_design_base_lineage_invalid", "Saved-layout base must equal its saved revision.")
        if result["sourceRef"]["savedLayoutRevision"] != result["savedLayoutRevision"]:
            _fail("facility_design_base_lineage_invalid", "Saved-layout source revision does not match.")
    elif result["baseKind"] == "receipt_bound_draft":
        if result["sourceRef"]["resultDraftRevision"] != result["layoutRevision"]:
            _fail("facility_design_base_lineage_invalid", "Receipt result does not match the draft document.")
        if result["sourceRef"]["savedBaseRevision"] != result["savedLayoutRevision"]:
            _fail("facility_design_base_lineage_invalid", "Receipt saved base does not match.")
    else:
        if result["sourceRef"]["capturedDraftRevision"] != result["layoutRevision"]:
            _fail("facility_design_base_lineage_invalid", "Editor capture does not match the draft document.")
        if result["sourceRef"]["savedBaseRevision"] != result["savedLayoutRevision"]:
            _fail("facility_design_base_lineage_invalid", "Editor saved base does not match.")
    result["document"] = document
    result["capturedAt"] = _timestamp(result["capturedAt"], "capturedAt")
    expected_base_revision = design_revision(_without_revision(result))
    if result["baseRevision"] != expected_base_revision:
        _fail(
            "facility_design_base_integrity_mismatch",
            "FacilityDesignBase revision does not match its immutable bytes.",
            expected=expected_base_revision,
            actual=result["baseRevision"],
        )
    return result


def capture_facility_design_base(
    *,
    base_id: str,
    base_kind: str,
    tenant_id: str,
    site_id: str,
    workspace_id: str,
    document: Mapping[str, Any],
    saved_layout_revision: str,
    source_ref: Mapping[str, Any],
    captured_at: str,
) -> dict[str, Any]:
    try:
        canonical_document = canonicalize_layout(document)
        current_revision = layout_revision(canonical_document)
    except (TypeError, ValueError) as exc:
        raise FacilityDesignBaseError(
            "facility_design_base_layout_invalid",
            "Cannot capture an invalid Facility Layout draft.",
        ) from exc
    record = {
        "schemaVersion": FACILITY_DESIGN_BASE_SCHEMA_VERSION,
        "baseId": base_id,
        "baseRevision": "",
        "baseKind": base_kind,
        "tenantId": tenant_id,
        "siteId": site_id,
        "workspaceId": workspace_id,
        "layoutId": canonical_document.get("layoutId"),
        "layoutRevision": current_revision,
        "savedLayoutRevision": saved_layout_revision,
        "sourceRef": deepcopy(dict(source_ref)),
        "document": canonical_document,
        "capturedAt": _timestamp(captured_at, "capturedAt"),
    }
    record["baseRevision"] = design_revision(_without_revision(record))
    return validate_facility_design_base(record)


def facility_design_base_ref(value: Mapping[str, Any]) -> dict[str, Any]:
    record = validate_facility_design_base(value)
    return {
        "baseId": record["baseId"],
        "baseRevision": record["baseRevision"],
        "baseKind": record["baseKind"],
        "layoutId": record["layoutId"],
        "layoutRevision": record["layoutRevision"],
    }


def canonical_facility_design_base_bytes(value: Mapping[str, Any]) -> bytes:
    return canonical_design_bytes(validate_facility_design_base(value))


__all__ = [
    "FACILITY_DESIGN_BASE_KINDS",
    "FACILITY_DESIGN_BASE_SCHEMA_VERSION",
    "FacilityDesignBaseError",
    "canonical_facility_design_base_bytes",
    "capture_facility_design_base",
    "facility_design_base_ref",
    "validate_facility_design_base",
]
