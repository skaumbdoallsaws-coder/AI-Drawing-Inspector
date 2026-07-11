"""Typed UI-action policy and browser-receipt sanitization for Phase 4."""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping


CONTRACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "static"
    / "contracts"
    / "ui-action-contract-v1.json"
)
RECEIPT_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "execution-receipt.schema.json"
_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")
_RECEIPT_STATUSES = frozenset({"succeeded", "failed", "rejected"})


class ToolPolicyError(ValueError):
    pass


@lru_cache(maxsize=1)
def load_ui_action_contract() -> dict[str, Any]:
    raw = CONTRACT_PATH.read_bytes()
    if any(byte > 127 for byte in raw):
        raise ToolPolicyError("UI action contract must be ASCII-only")
    value = json.loads(raw.decode("ascii"))
    required = {"contract_version", "max_actions", "workspaces", "actions", "conflicts"}
    if not isinstance(value, dict) or set(value) != required:
        raise ToolPolicyError("UI action contract has invalid top-level keys")
    if value.get("contract_version") != 1:
        raise ToolPolicyError("Unsupported UI action contract version")
    if not isinstance(value.get("actions"), dict) or not value["actions"]:
        raise ToolPolicyError("UI action contract has no actions")
    if not isinstance(value.get("workspaces"), list) or not value["workspaces"]:
        raise ToolPolicyError("UI action contract has no workspaces")
    return value


def _clean_field(value: Any, rule: Mapping[str, Any]) -> tuple[Any, str | None]:
    kind = rule.get("type")
    if kind == "string":
        if not isinstance(value, str) or not value.strip():
            return None, "must_be_nonempty_string"
        return value.strip()[: int(rule.get("max_length", 240))], None
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            return None, "must_be_finite_number"
        number = float(value)
        if number < float(rule.get("minimum", -math.inf)) or number > float(rule.get("maximum", math.inf)):
            return None, "number_out_of_range"
        return number, None
    if kind == "boolean":
        if type(value) is not bool:
            return None, "must_be_boolean"
        return value, None
    if kind == "enum":
        if value not in (rule.get("values") or []):
            return None, "invalid_enum"
        return value, None
    if kind == "string_array":
        if not isinstance(value, list):
            return None, "must_be_string_array"
        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                return None, "must_be_string_array"
            token = item.strip()[:200]
            if token not in cleaned:
                cleaned.append(token)
        if len(cleaned) > int(rule.get("max_items", 30)):
            return None, "too_many_items"
        return cleaned, None
    if kind == "object":
        if not isinstance(value, dict):
            return None, "must_be_object"
        return _clean_json(value), None
    return None, "unknown_field_type"


def _clean_json(value: Any, *, depth: int = 0) -> Any:
    if depth > 3:
        return None
    if value is None or type(value) is bool:
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, str):
        return value[:300]
    if isinstance(value, list):
        return [_clean_json(item, depth=depth + 1) for item in value[:40]]
    if isinstance(value, dict):
        return {
            str(key)[:80]: _clean_json(item, depth=depth + 1)
            for key, item in list(value.items())[:30]
        }
    return str(value)[:300]


def validate_ui_action_bundle(args: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate and normalize one ui_actions payload against the shared contract."""
    contract = load_ui_action_contract()
    errors: list[str] = []
    if not isinstance(args, dict) or set(args) - {"workspace", "actions"}:
        return None, ["bundle_invalid_keys"]
    workspace = str(args.get("workspace") or "assembly").strip()
    if workspace not in set(contract["workspaces"]):
        return None, ["workspace_not_allowed"]
    raw_actions = args.get("actions")
    if not isinstance(raw_actions, list) or not raw_actions:
        return None, ["actions_required"]
    if len(raw_actions) > int(contract["max_actions"]):
        return None, ["too_many_actions"]

    normalized: list[dict[str, Any]] = []
    seen_action_ids: set[str] = set()
    for index, raw_action in enumerate(raw_actions):
        prefix = f"action[{index}]"
        if not isinstance(raw_action, dict):
            errors.append(f"{prefix}:must_be_object")
            continue
        action_type = str(raw_action.get("type") or "").strip()
        spec = contract["actions"].get(action_type)
        if spec is None:
            errors.append(f"{prefix}:unknown_type")
            continue
        allowed_keys = {"type", "action_id"} | set(spec.get("fields") or {})
        if set(raw_action) - allowed_keys:
            errors.append(f"{prefix}:unknown_fields")
            continue
        action_id = str(raw_action.get("action_id") or f"a{index + 1}").strip()
        if not _ID_RE.fullmatch(action_id) or action_id in seen_action_ids:
            errors.append(f"{prefix}:invalid_action_id")
            continue
        seen_action_ids.add(action_id)
        missing = [field for field in spec.get("required", []) if field not in raw_action]
        if missing:
            errors.append(f"{prefix}:missing_{missing[0]}")
            continue
        required_any = spec.get("require_any") or []
        if required_any and not any(field in raw_action for field in required_any):
            errors.append(f"{prefix}:missing_target")
            continue
        effect_any = spec.get("require_effect_any") or []
        if effect_any and not any(field in raw_action for field in effect_any):
            errors.append(f"{prefix}:missing_effect")
            continue

        action = {"type": action_type, "action_id": action_id}
        field_error = None
        for field, value in raw_action.items():
            if field in {"type", "action_id"}:
                continue
            cleaned, field_error = _clean_field(value, spec["fields"][field])
            if field_error:
                errors.append(f"{prefix}:{field}:{field_error}")
                break
            action[field] = cleaned
        if field_error is None:
            normalized.append(action)

    if errors:
        return None, errors
    action_types = {action["type"] for action in normalized}
    for conflict in contract.get("conflicts") or []:
        types = set(conflict.get("types") or [])
        if types and types <= action_types:
            errors.append(f"conflict:{conflict.get('reason') or 'conflicting_actions'}")
    if errors:
        return None, errors
    return {"workspace": workspace, "actions": normalized}, []


def sanitize_execution_receipts(value: Any, *, limit: int = 12) -> list[dict[str, Any]]:
    """Accept only compact, contract-shaped browser receipts from attachments."""
    if not isinstance(value, list):
        return []
    allowed_tools = set(load_ui_action_contract()["actions"])
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value[: max(1, min(int(limit), 20))]:
        if not isinstance(raw, dict) or raw.get("contract_version") != 1:
            continue
        receipt_id = str(raw.get("receipt_id") or "").strip()
        tool_call_id = str(raw.get("tool_call_id") or "").strip()
        action_id = str(raw.get("action_id") or "").strip()
        tool_id = str(raw.get("tool_id") or "").strip()
        status = str(raw.get("status") or "").strip()
        if (
            not _ID_RE.fullmatch(receipt_id)
            or not _ID_RE.fullmatch(tool_call_id)
            or not _ID_RE.fullmatch(action_id)
            or tool_id not in allowed_tools
            or status not in _RECEIPT_STATUSES
            or receipt_id in seen
        ):
            continue
        requested = raw.get("requested_args")
        applied = raw.get("applied_args")
        before = raw.get("before")
        after = raw.get("after")
        if not all(isinstance(item, dict) for item in (requested, applied, before, after)):
            continue
        error = raw.get("error")
        if error is not None:
            error = str(error)[:240]
        if status == "succeeded":
            error = None
        elif not error:
            error = "execution_failed"
        evidence = raw.get("evidence") if isinstance(raw.get("evidence"), list) else []
        try:
            duration_ms = max(0.0, min(float(raw.get("duration_ms") or 0.0), 600000.0))
        except (TypeError, ValueError):
            duration_ms = 0.0
        timestamp = str(raw.get("timestamp") or "")[:60]
        if not timestamp:
            continue
        cleaned.append(
            {
                "contract_version": 1,
                "receipt_id": receipt_id,
                "tool_call_id": tool_call_id,
                "action_id": action_id,
                "tool_id": tool_id,
                "status": status,
                "requested_args": _clean_json(requested),
                "applied_args": _clean_json(applied),
                "before": _clean_json(before),
                "after": _clean_json(after),
                "evidence": [str(item)[:200] for item in evidence[:12]],
                "error": error,
                "duration_ms": duration_ms,
                "timestamp": timestamp,
            }
        )
        seen.add(receipt_id)
    return cleaned


def reset_tool_policy_cache_for_tests() -> None:
    load_ui_action_contract.cache_clear()


def tool_policy_metadata() -> dict[str, Any]:
    contract = load_ui_action_contract()
    return {
        "contract_version": contract["contract_version"],
        "action_count": len(contract["actions"]),
        "max_actions": contract["max_actions"],
        "receipt_schema": RECEIPT_SCHEMA_PATH.name,
    }
