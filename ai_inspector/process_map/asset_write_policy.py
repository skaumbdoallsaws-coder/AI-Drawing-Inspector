"""Permanent authorization gate for Builder process-map asset writes."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Mapping


_CONTRACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "static"
    / "contracts"
    / "process-map-asset-write-authorization-v1.json"
)


@lru_cache(maxsize=1)
def load_asset_write_authorization_contract() -> Dict[str, Any]:
    contract = json.loads(_CONTRACT_PATH.read_text(encoding="ascii"))
    if contract.get("contractVersion") != 1:
        raise RuntimeError("unsupported process-map asset-write contract")
    return contract


def reset_asset_write_authorization_contract_for_tests() -> None:
    load_asset_write_authorization_contract.cache_clear()


def authorize_process_map_asset_write(request: Mapping[str, Any]) -> Dict[str, Any]:
    """Evaluate the shared, deterministic write-authorization contract."""
    contract = load_asset_write_authorization_contract()
    constraints = contract["constraints"]
    action = request.get("action")
    if action not in contract["allowedActions"]:
        return {"authorized": False, "reason": "action_not_allowed"}
    if constraints.get("requireExplicitApproval") and request.get("explicitApproval") is not True:
        return {"authorized": False, "reason": "explicit_approval_required"}

    maximum = int(constraints.get("identityMaxLength", 128))
    for field in ("productId", "mapId", "userId", "sessionId"):
        value = request.get(field)
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
            return {"authorized": False, "reason": f"invalid_{field}"}
    revision = request.get("baseRevision")
    if not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{64}", revision) is None:
        return {"authorized": False, "reason": "invalid_base_revision"}
    diff_hash = request.get("diffHash")
    if not isinstance(diff_hash, str) or re.fullmatch(constraints["diffHashPattern"], diff_hash) is None:
        return {"authorized": False, "reason": "invalid_diff_hash"}
    idempotency_key = request.get("idempotencyKey")
    if (
        not isinstance(idempotency_key, str)
        or re.fullmatch(constraints["idempotencyKeyPattern"], idempotency_key) is None
    ):
        return {"authorized": False, "reason": "invalid_idempotency_key"}
    return {
        "authorized": True,
        "reason": "authorized",
        "contractVersion": contract["contractVersion"],
        "action": action,
    }


def asset_write_policy_metadata() -> Dict[str, Any]:
    contract = load_asset_write_authorization_contract()
    return {
        "contractVersion": contract["contractVersion"],
        "allowedActions": list(contract["allowedActions"]),
    }
