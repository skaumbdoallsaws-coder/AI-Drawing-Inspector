"""Shared in-place transaction contracts; persistence stays in each existing store."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Mapping
import uuid

RECEIPT_LIMIT = 1000
MAX_REQUEST_BYTES = 256 * 1024
NAMESPACE = uuid.UUID("5a4e6955-0b80-52ca-b473-f8bc4cc15008")


class DocumentEditError(ValueError):
    def __init__(self, code: str, message: str, **details: Any):
        self.code, self.details = code, details
        super().__init__(message)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def document_id(document_type: str, assembly_number: str) -> str:
    return str(uuid.uuid5(NAMESPACE, document_type + ":" + assembly_number.strip().casefold()))


def binding(state: Mapping[str, Any]) -> dict:
    return {key: state[key] for key in ("documentId", "revision", "sourceRevision", "manualPlanRevision")}


def content_hash(state: Mapping[str, Any], target_id: str, value: Any) -> str:
    key = value.get("versionKey", target_id) if isinstance(value, Mapping) else target_id
    page = value.get("versionPage", "") if isinstance(value, Mapping) else ""
    return digest({"hashVersion": 1, "targetId": target_id, "value": value,
                   "fieldVersion": state.get("fieldVersions", {}).get(key, 0),
                   "pageVersion": state.get("fieldVersions", {}).get("@page:" + page, 0),
                   "epoch": state.get("editEpoch", 0)})


def scene_field_key(page_id: str, target_type: str, alias: str) -> str:
    return alias if alias.startswith("part.") else page_id + "/" + target_type + "/" + alias


def transaction_defaults(state: dict) -> dict:
    state.setdefault("editRevision", 0)
    state.setdefault("editEpoch", 0)
    state.setdefault("fieldVersions", {})
    state.setdefault("fieldMeta", {})
    state.setdefault("receipts", {})
    state.setdefault("receiptOrder", [])
    return state


def validate_transaction_metadata(state: dict) -> None:
    for field in ("editRevision", "editEpoch"):
        if type(state.get(field)) is not int or state[field] < 0:
            raise DocumentEditError("unsupported_document_schema", "Invalid edit revision.")
    if not isinstance(state.get("fieldMeta", {}), dict):
        raise DocumentEditError("unsupported_document_schema", "Invalid field provenance.")
    versions = state.get("fieldVersions")
    if not isinstance(versions, dict) or any(type(v) is not int or v < 0 for v in versions.values()):
        raise DocumentEditError("unsupported_document_schema", "Invalid field versions.")
    receipts, order = state.get("receipts"), state.get("receiptOrder")
    if (not isinstance(receipts, dict) or not isinstance(order, list) or len(order) != len(set(order))
            or set(order) != set(receipts) or len(order) > RECEIPT_LIMIT):
        raise DocumentEditError("unsupported_document_schema", "Invalid receipt history.")


def request_hash(request_id: str, payload: Any) -> str:
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
        raise DocumentEditError("invalid_document_operation", "A request ID of 1-128 characters is required.")
    if len(canonical_bytes(payload)) > MAX_REQUEST_BYTES:
        raise DocumentEditError("invalid_document_operation", "The edit request is too large.")
    return digest(payload)


def prior_receipt(state: dict, request_id: str, payload_hash: str) -> dict | None:
    previous = state["receipts"].get(request_id)
    if previous is None:
        return None
    if previous["payloadHash"] != payload_hash:
        raise DocumentEditError("request_id_reused", "This request ID was used for a different payload.")
    return deepcopy(previous["receipt"])


def check_preconditions(state: dict, expected_revision: int, expected: dict, current: dict) -> None:
    if type(expected_revision) is not int or expected_revision < 0 or expected_revision > state["editRevision"]:
        raise DocumentEditError("stale_revision", "The observed edit revision is invalid or in the future.")
    if not expected:
        raise DocumentEditError("document_read_required", "Read the complete targets before editing.")
    conflicts = state.get("conflicts") or {}
    conflicts = list(conflicts.values()) if isinstance(conflicts, dict) else conflicts
    for index, (target, value) in enumerate(expected.items()):
        details = {"operationIndex": index, "targetId": target}
        if target not in current:
            raise DocumentEditError("stale_revision", "A target was removed or rebound; read it again.", **details)
        if any(c.get("targetId") == target and c.get("status", "open") == "open" for c in conflicts):
            raise DocumentEditError("manual_edit_conflict", "Resolve this target's open conflict first.", **details)
        if not value or value != current[target]:
            raise DocumentEditError("content_hash_mismatch", "The target changed; read it again and preserve the newer text.", **details)


def make_receipt(state: dict, *, request_id: str, payload_hash: str, document: str,
                 expected_revision: int, changed: list[str], undoable: bool) -> dict:
    return {"requestId": request_id, "changeId": uuid.uuid4().hex if changed else None,
            "documentId": document, "expectedRevision": expected_revision,
            "beforeRevision": state["editRevision"], "revision": state["editRevision"] + bool(changed),
            "changedIds": changed, "undoable": undoable and bool(changed), "validation": [],
            "payloadHash": payload_hash}


def retain_receipt(state: dict, receipt: dict) -> None:
    request_id = receipt["requestId"]
    state["receipts"][request_id] = {"payloadHash": receipt["payloadHash"], "receipt": deepcopy(receipt)}
    state["receiptOrder"].append(request_id)
    while len(state["receiptOrder"]) > RECEIPT_LIMIT:
        state["receipts"].pop(state["receiptOrder"].pop(0))


def operation_store(operations: list[dict]) -> str:
    if not isinstance(operations, list) or not 1 <= len(operations) <= 12 or any(not isinstance(o, dict) for o in operations):
        raise DocumentEditError("invalid_document_operation", "Submit 1-12 edit operations.")
    kinds = {o.get("operation") for o in operations}
    if kinds == {"replace_text", "set_slot_value"}:
        raise DocumentEditError("invalid_document_operation", "send text and value edits as separate requests")
    if kinds not in ({"replace_text"}, {"set_slot_value"}):
        raise DocumentEditError("invalid_document_operation", "Unsupported edit operation.")
    if len({o.get("targetId") for o in operations}) != len(operations):
        raise DocumentEditError("invalid_document_operation", "Each target may occur only once in a batch.")
    return "scene" if kinds == {"replace_text"} else "slots"
