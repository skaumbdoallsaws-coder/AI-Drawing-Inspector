"""Proposal, approval, and CAS-apply runtime for process-map Builder edits."""

from __future__ import annotations

import os
import secrets
import threading
import time
from collections import OrderedDict
from copy import deepcopy
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .asset_write_policy import authorize_process_map_asset_write
from .operations import (
    ProcessMapOperationError,
    apply_process_map_operations,
    build_process_map_diff,
    diff_hash,
    find_process_map_records,
)
from .repository import (
    ProcessMapConflictError,
    ProcessMapNotFoundError,
    ProcessMapValidationError,
    list_named_process_map_revisions,
    list_process_maps,
    load_named_process_map,
    load_named_process_map_revision,
    process_map_revision,
    save_named_process_map,
)
from .schema_v3 import validate_placement_map
from .validate import has_structural_errors


class ProcessMapBuilderError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ProcessMapAuthorizationError(ProcessMapBuilderError):
    pass


class ProcessMapProposalNotFoundError(ProcessMapBuilderError):
    pass


class ProcessMapApprovalReplayError(ProcessMapBuilderError):
    pass


_LOCK = threading.RLock()
_PROPOSALS: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_APPROVALS: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_USED_IDEMPOTENCY: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()


def _store_ttl_seconds() -> int:
    raw = (os.getenv("INSPECTORPRO_BUILDER_APPROVAL_TTL_SECONDS") or "1800").strip()
    try:
        return max(60, min(86400, int(raw)))
    except ValueError:
        return 1800


def _store_limit() -> int:
    raw = (os.getenv("INSPECTORPRO_BUILDER_APPROVAL_LIMIT") or "512").strip()
    try:
        return max(32, min(4096, int(raw)))
    except ValueError:
        return 512


def _cleanup_locked(now: Optional[float] = None) -> None:
    current = time.monotonic() if now is None else now
    cutoff = current - _store_ttl_seconds()
    for store in (_PROPOSALS, _APPROVALS, _USED_IDEMPOTENCY):
        for key in list(store):
            if float(store[key].get("createdMonotonic", 0)) >= cutoff:
                continue
            del store[key]
        while len(store) > _store_limit():
            store.popitem(last=False)


def reset_process_map_builder_state_for_tests() -> None:
    with _LOCK:
        _PROPOSALS.clear()
        _APPROVALS.clear()
        _USED_IDEMPOTENCY.clear()


def _new_token(prefix: str) -> str:
    return f"{prefix}-{secrets.token_urlsafe(24)}"


def _assert_revision(base_revision: str, current_revision: str) -> str:
    supplied = base_revision.strip() if isinstance(base_revision, str) else ""
    if supplied != current_revision:
        raise ProcessMapConflictError(current_revision)
    return supplied


def _occurrence_ids(product_structure: Mapping[str, Any]) -> set[str]:
    return {
        str(item["occurrenceId"])
        for item in product_structure.get("occurrences", [])
        if isinstance(item, dict) and isinstance(item.get("occurrenceId"), str)
    }


def _proposal_response(record: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "proposalId": record.get("proposalId"),
        "productId": record["productId"],
        "mapId": record["mapId"],
        "baseRevision": record["baseRevision"],
        "action": record["action"],
        "diff": deepcopy(record["diff"]),
        "diffHash": record["diffHash"],
        "findings": deepcopy(record["findings"]),
        "operationResults": deepcopy(record.get("operationResults", [])),
        "wouldSave": bool(record["wouldSave"]),
        "targetRevision": record.get("targetRevision"),
    }


def _store_proposal(record: Dict[str, Any]) -> Dict[str, Any]:
    if not record["wouldSave"]:
        record["proposalId"] = None
        return _proposal_response(record)
    with _LOCK:
        _cleanup_locked()
        proposal_id = _new_token("pmp")
        record["proposalId"] = proposal_id
        record["createdMonotonic"] = time.monotonic()
        _PROPOSALS[proposal_id] = deepcopy(record)
        _cleanup_locked()
    return _proposal_response(record)


def propose_process_map_operations(
    training_root,
    product_id: str,
    map_id: str,
    base_revision: str,
    operations: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Dry-run an operation batch. This function never writes."""
    loaded = load_named_process_map(training_root, product_id, map_id)
    base = _assert_revision(base_revision, loaded["revision"])
    applied = apply_process_map_operations(
        loaded["map"],
        loaded["productStructure"],
        operations,
    )
    structural_error = has_structural_errors(applied["findings"])
    would_save = bool(applied["changed"] and not structural_error)
    calculated_hash = diff_hash(
        map_id=map_id,
        base_revision=base,
        operations=operations,
        after=applied["map"],
        diff=applied["diff"],
    )
    return _store_proposal(
        {
            "productId": product_id,
            "mapId": map_id,
            "baseRevision": base,
            "action": "apply_operations",
            "operations": deepcopy(list(operations)),
            "after": deepcopy(applied["map"]),
            "diff": deepcopy(applied["diff"]),
            "diffHash": calculated_hash,
            "findings": deepcopy(applied["findings"]),
            "operationResults": deepcopy(applied["operationResults"]),
            "wouldSave": would_save,
        }
    )


def propose_process_map_revert(
    training_root,
    product_id: str,
    map_id: str,
    base_revision: str,
    target_revision: str,
) -> Dict[str, Any]:
    """Dry-run a revert to one retained named revision."""
    loaded = load_named_process_map(training_root, product_id, map_id)
    base = _assert_revision(base_revision, loaded["revision"])
    target = load_named_process_map_revision(
        training_root,
        product_id,
        map_id,
        target_revision,
    )
    after = deepcopy(target["map"])
    after["mapId"] = map_id
    after["productId"] = product_id
    after["sourceStructureRevision"] = loaded["structureRevision"]
    findings = validate_placement_map(after, _occurrence_ids(loaded["productStructure"]))
    diff = build_process_map_diff(loaded["map"], after)
    operations = [{"op": "revert_to_revision", "targetRevision": target_revision}]
    changed = process_map_revision(after) != process_map_revision(loaded["map"])
    would_save = bool(changed and not has_structural_errors(findings))
    calculated_hash = diff_hash(
        map_id=map_id,
        base_revision=base,
        operations=operations,
        after=after,
        diff=diff,
    )
    return _store_proposal(
        {
            "productId": product_id,
            "mapId": map_id,
            "baseRevision": base,
            "action": "revert_to_revision",
            "targetRevision": target_revision,
            "operations": operations,
            "after": after,
            "diff": diff,
            "diffHash": calculated_hash,
            "findings": findings,
            "operationResults": [],
            "wouldSave": would_save,
        }
    )


def show_process_map_proposal(proposal_id: str) -> Dict[str, Any]:
    with _LOCK:
        _cleanup_locked()
        record = _PROPOSALS.get(proposal_id)
        if record is None:
            raise ProcessMapProposalNotFoundError(
                "proposal_not_found", "The process-map proposal is missing or expired."
            )
        return _proposal_response(record)


def approve_process_map_proposal(
    training_root,
    proposal_id: str,
    *,
    product_id: str,
    map_id: str,
    base_revision: str,
    diff_hash_value: str,
    user_id: str,
    session_id: str,
    idempotency_key: str,
    explicit_approval: bool,
) -> Dict[str, Any]:
    """Issue an opaque token only after an exact diff is explicitly approved."""
    with _LOCK:
        _cleanup_locked()
        proposal = deepcopy(_PROPOSALS.get(proposal_id))
    if proposal is None:
        raise ProcessMapProposalNotFoundError(
            "proposal_not_found", "The process-map proposal is missing or expired."
        )
    supplied_binding = {
        "productId": product_id,
        "mapId": map_id,
        "baseRevision": base_revision,
        "diffHash": diff_hash_value,
    }
    expected_binding = {
        "productId": proposal["productId"],
        "mapId": proposal["mapId"],
        "baseRevision": proposal["baseRevision"],
        "diffHash": proposal["diffHash"],
    }
    if supplied_binding != expected_binding:
        raise ProcessMapAuthorizationError(
            "approval_binding_mismatch",
            "Approval does not match the exact proposed map, revision, and diff.",
        )
    loaded = load_named_process_map(training_root, product_id, map_id)
    _assert_revision(base_revision, loaded["revision"])
    gate_request = {
        "action": proposal["action"],
        "explicitApproval": explicit_approval,
        "productId": product_id,
        "mapId": map_id,
        "baseRevision": base_revision,
        "diffHash": diff_hash_value,
        "userId": user_id,
        "sessionId": session_id,
        "idempotencyKey": idempotency_key,
    }
    authorization = authorize_process_map_asset_write(gate_request)
    if not authorization["authorized"]:
        raise ProcessMapAuthorizationError(
            "asset_write_not_authorized",
            f"Process-map asset write denied: {authorization['reason']}.",
        )
    with _LOCK:
        _cleanup_locked()
        if idempotency_key in _USED_IDEMPOTENCY or any(
            item.get("idempotencyKey") == idempotency_key for item in _APPROVALS.values()
        ):
            raise ProcessMapApprovalReplayError(
                "idempotency_replay", "The idempotency key was already used."
            )
        approval_token = _new_token("pma")
        _APPROVALS[approval_token] = {
            **proposal,
            "approvalToken": approval_token,
            "proposalId": proposal_id,
            "userId": user_id.strip(),
            "sessionId": session_id.strip(),
            "idempotencyKey": idempotency_key,
            "authorization": authorization,
            "createdMonotonic": time.monotonic(),
        }
        _cleanup_locked()
    return {
        "approvalToken": approval_token,
        "proposalId": proposal_id,
        "productId": product_id,
        "mapId": map_id,
        "baseRevision": base_revision,
        "diffHash": diff_hash_value,
        "expiresInSeconds": _store_ttl_seconds(),
        "authorization": authorization,
    }


def apply_approved_process_map_operations(
    training_root,
    approval_token: str,
    *,
    product_id: str,
    map_id: str,
    base_revision: str,
    diff_hash_value: str,
    user_id: str,
    session_id: str,
    idempotency_key: str,
) -> Dict[str, Any]:
    """Revalidate and CAS-save the exact approved result once."""
    with _LOCK:
        _cleanup_locked()
        if idempotency_key in _USED_IDEMPOTENCY:
            raise ProcessMapApprovalReplayError(
                "idempotency_replay", "The approved write was already applied."
            )
        approval = deepcopy(_APPROVALS.get(approval_token))
    if approval is None:
        raise ProcessMapProposalNotFoundError(
            "approval_not_found", "The process-map approval is missing or expired."
        )
    supplied = {
        "productId": product_id,
        "mapId": map_id,
        "baseRevision": base_revision,
        "diffHash": diff_hash_value,
        "userId": user_id.strip(),
        "sessionId": session_id.strip(),
        "idempotencyKey": idempotency_key,
    }
    expected = {key: approval[key] for key in supplied}
    if supplied != expected:
        raise ProcessMapAuthorizationError(
            "approval_binding_mismatch", "Apply request does not match the approved write."
        )
    loaded = load_named_process_map(training_root, product_id, map_id)
    _assert_revision(base_revision, loaded["revision"])

    if approval["action"] == "apply_operations":
        applied = apply_process_map_operations(
            loaded["map"], loaded["productStructure"], approval["operations"]
        )
        after = applied["map"]
        findings = applied["findings"]
        diff = applied["diff"]
    else:
        after = deepcopy(approval["after"])
        after["sourceStructureRevision"] = loaded["structureRevision"]
        findings = validate_placement_map(after, _occurrence_ids(loaded["productStructure"]))
        diff = build_process_map_diff(loaded["map"], after)
    if has_structural_errors(findings):
        raise ProcessMapValidationError(findings)
    recalculated_hash = diff_hash(
        map_id=map_id,
        base_revision=base_revision,
        operations=approval["operations"],
        after=after,
        diff=diff,
    )
    if recalculated_hash != approval["diffHash"]:
        raise ProcessMapAuthorizationError(
            "approved_diff_changed", "The approved process-map diff no longer matches."
        )

    saved = save_named_process_map(
        training_root,
        product_id,
        map_id,
        after,
        base_revision,
    )
    receipt = {
        "receiptId": _new_token("pmr"),
        "proposalId": approval["proposalId"],
        "action": approval["action"],
        "productId": product_id,
        "mapId": map_id,
        "baseRevision": base_revision,
        "revision": saved["revision"],
        "diffHash": diff_hash_value,
        "userId": user_id.strip(),
        "sessionId": session_id.strip(),
        "idempotencyKey": idempotency_key,
    }
    with _LOCK:
        _APPROVALS.pop(approval_token, None)
        _PROPOSALS.pop(approval["proposalId"], None)
        _USED_IDEMPOTENCY[idempotency_key] = {
            "createdMonotonic": time.monotonic(),
            "receipt": deepcopy(receipt),
        }
        _cleanup_locked()
    return {**saved, "receipt": receipt}


def builder_list_process_maps(training_root, product_id: str) -> Dict[str, Any]:
    return list_process_maps(training_root, product_id, include_archived=True)


def builder_read_process_map(training_root, product_id: str, map_id: str) -> Dict[str, Any]:
    return load_named_process_map(training_root, product_id, map_id)


def builder_find_process_map_records(
    training_root,
    product_id: str,
    map_id: str,
    query: str,
    *,
    limit: int = 50,
) -> Dict[str, Any]:
    loaded = load_named_process_map(training_root, product_id, map_id)
    return {
        "productId": product_id,
        "mapId": map_id,
        "revision": loaded["revision"],
        "matches": find_process_map_records(
            loaded["map"], loaded["productStructure"], query, limit=limit
        ),
    }


def builder_validate_process_map(training_root, product_id: str, map_id: str) -> Dict[str, Any]:
    loaded = load_named_process_map(training_root, product_id, map_id)
    return {
        "productId": product_id,
        "mapId": map_id,
        "revision": loaded["revision"],
        "findings": loaded["findings"],
        "valid": not has_structural_errors(loaded["findings"]),
    }


def builder_list_process_map_revisions(training_root, product_id: str, map_id: str) -> Dict[str, Any]:
    return {
        "productId": product_id,
        "mapId": map_id,
        "revisions": list_named_process_map_revisions(training_root, product_id, map_id),
    }
