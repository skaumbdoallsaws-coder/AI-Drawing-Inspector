"""Load and apply engineer-approved FAI disposition policies."""

from __future__ import annotations

import copy
import json
import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


_SCHEMA_VERSION = "1.0"
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
_DISPOSITIONS = frozenset(
    {"accept_as_is", "rework", "reject_replace", "scrap_replace"}
)
_DIRECTIONS = frozenset({"above_upper", "below_lower"})


class DispositionPolicyError(ValueError):
    """Raised when a policy asset is malformed or cannot be loaded."""


@dataclass(frozen=True)
class DispositionDecision:
    policy_id: str
    policy_version: str
    rule_id: str
    characteristic_id: str
    characteristic_label: str
    part_number: str
    subject: str
    disposition: str
    measured: float
    limit: float
    deviation: float
    direction: str
    unit: str
    use_as_is_allowed: bool
    rework_allowed: bool
    rationale: str
    approval_ref: str

    def as_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.__dict__)


def _required_string(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise DispositionPolicyError(f"{field} must be a non-empty string")
    return text


def _identifier(value: Any, field: str) -> str:
    text = _required_string(value, field)
    if not _ID_RE.fullmatch(text):
        raise DispositionPolicyError(f"{field} is not a valid identifier")
    return text


def _finite_number(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DispositionPolicyError(f"{field} must be numeric") from exc
    if not math.isfinite(number) or number < 0:
        raise DispositionPolicyError(f"{field} must be a non-negative finite number")
    return number


def _required_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise DispositionPolicyError(f"{field} must be a boolean")
    return value


def validate_disposition_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a detached canonical policy dictionary."""
    if not isinstance(policy, Mapping):
        raise DispositionPolicyError("policy must be an object")
    allowed_top = {
        "schema_version",
        "policy_id",
        "version",
        "assembly_number",
        "authority",
        "rules",
    }
    unknown = set(policy) - allowed_top
    if unknown:
        raise DispositionPolicyError(f"unknown policy fields: {sorted(unknown)}")
    if str(policy.get("schema_version")) != _SCHEMA_VERSION:
        raise DispositionPolicyError("unsupported disposition policy schema_version")
    canonical = {
        "schema_version": _SCHEMA_VERSION,
        "policy_id": _identifier(policy.get("policy_id"), "policy_id"),
        "version": _required_string(policy.get("version"), "version"),
        "assembly_number": _identifier(
            policy.get("assembly_number"), "assembly_number"
        ),
    }

    authority = policy.get("authority")
    if not isinstance(authority, Mapping):
        raise DispositionPolicyError("authority must be an object")
    authority_allowed = {
        "status",
        "owner_role",
        "delegated_agent",
        "decision_scope",
        "approval_ref",
    }
    authority_unknown = set(authority) - authority_allowed
    if authority_unknown:
        raise DispositionPolicyError(
            f"unknown authority fields: {sorted(authority_unknown)}"
        )
    canonical["authority"] = {
        "status": _required_string(authority.get("status"), "authority.status"),
        "owner_role": _required_string(
            authority.get("owner_role"), "authority.owner_role"
        ),
        "delegated_agent": _required_string(
            authority.get("delegated_agent"), "authority.delegated_agent"
        ),
        "decision_scope": _required_string(
            authority.get("decision_scope"), "authority.decision_scope"
        ),
        "approval_ref": _required_string(
            authority.get("approval_ref"), "authority.approval_ref"
        ),
    }

    rules = policy.get("rules")
    if not isinstance(rules, list) or not rules:
        raise DispositionPolicyError("rules must be a non-empty array")
    canonical_rules = []
    seen_rule_ids: set[str] = set()
    for index, raw_rule in enumerate(rules):
        if not isinstance(raw_rule, Mapping):
            raise DispositionPolicyError(f"rules[{index}] must be an object")
        allowed_rule = {
            "rule_id",
            "priority",
            "part_number",
            "characteristic_label",
            "characteristic_aliases",
            "interface_pattern_ids",
            "condition",
            "decision",
        }
        rule_unknown = set(raw_rule) - allowed_rule
        if rule_unknown:
            raise DispositionPolicyError(
                f"unknown fields in rules[{index}]: {sorted(rule_unknown)}"
            )
        rule_id = _identifier(raw_rule.get("rule_id"), f"rules[{index}].rule_id")
        if rule_id in seen_rule_ids:
            raise DispositionPolicyError(f"duplicate rule_id: {rule_id}")
        seen_rule_ids.add(rule_id)
        aliases = raw_rule.get("characteristic_aliases")
        if not isinstance(aliases, list) or not aliases:
            raise DispositionPolicyError(
                f"rules[{index}].characteristic_aliases must be non-empty"
            )
        patterns = raw_rule.get("interface_pattern_ids") or []
        if not isinstance(patterns, list):
            raise DispositionPolicyError(
                f"rules[{index}].interface_pattern_ids must be an array"
            )
        condition = raw_rule.get("condition")
        decision = raw_rule.get("decision")
        if not isinstance(condition, Mapping) or not isinstance(decision, Mapping):
            raise DispositionPolicyError(
                f"rules[{index}] condition and decision must be objects"
            )
        direction = _required_string(
            condition.get("direction"), f"rules[{index}].condition.direction"
        )
        if direction not in _DIRECTIONS:
            raise DispositionPolicyError(f"unsupported direction: {direction}")
        disposition = _required_string(
            decision.get("disposition"), f"rules[{index}].decision.disposition"
        )
        if disposition not in _DISPOSITIONS:
            raise DispositionPolicyError(f"unsupported disposition: {disposition}")
        canonical_rules.append(
            {
                "rule_id": rule_id,
                "priority": int(raw_rule.get("priority") or 0),
                "part_number": _identifier(
                    raw_rule.get("part_number"), f"rules[{index}].part_number"
                ),
                "characteristic_label": _required_string(
                    raw_rule.get("characteristic_label"),
                    f"rules[{index}].characteristic_label",
                ),
                "characteristic_aliases": [
                    _required_string(value, f"rules[{index}].characteristic_aliases")
                    for value in aliases
                ],
                "interface_pattern_ids": [
                    _identifier(value, f"rules[{index}].interface_pattern_ids")
                    for value in patterns
                ],
                "condition": {
                    "status": _required_string(
                        condition.get("status"),
                        f"rules[{index}].condition.status",
                    ).upper(),
                    "direction": direction,
                    "minimum_out_of_tolerance": _finite_number(
                        condition.get("minimum_out_of_tolerance", 0),
                        f"rules[{index}].condition.minimum_out_of_tolerance",
                    ),
                    "unit": _required_string(
                        condition.get("unit"), f"rules[{index}].condition.unit"
                    ),
                },
                "decision": {
                    "disposition": disposition,
                    "subject": _required_string(
                        decision.get("subject"), f"rules[{index}].decision.subject"
                    ),
                    "use_as_is_allowed": _required_bool(
                        decision.get("use_as_is_allowed"),
                        f"rules[{index}].decision.use_as_is_allowed",
                    ),
                    "rework_allowed": _required_bool(
                        decision.get("rework_allowed"),
                        f"rules[{index}].decision.rework_allowed",
                    ),
                    "rationale": _required_string(
                        decision.get("rationale"),
                        f"rules[{index}].decision.rationale",
                    ).rstrip(". "),
                },
            }
        )
    canonical_rules.sort(key=lambda item: (-item["priority"], item["rule_id"]))
    canonical["rules"] = canonical_rules
    return canonical


def _normalize_words(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def _characteristic_id(row: Mapping[str, Any], index: int) -> str:
    value = row.get("char_number")
    if value in (None, ""):
        value = row.get("characteristic_id")
    return str(value if value not in (None, "") else index + 1)


def _affected_patterns(
    affected_interfaces: Iterable[Mapping[str, Any]], characteristic_id: str
) -> set[str]:
    result: set[str] = set()
    for item in affected_interfaces:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("characteristic_id") or "") != characteristic_id:
            continue
        interface = item.get("interface")
        if isinstance(interface, Mapping) and interface.get("pattern_id"):
            result.add(str(interface["pattern_id"]))
    return result


def evaluate_disposition_policy(
    policy: Mapping[str, Any],
    *,
    part_number: str,
    fai_rows: Iterable[Mapping[str, Any]],
    target_characteristic_ids: Iterable[str],
    affected_interfaces: Iterable[Mapping[str, Any]] = (),
) -> DispositionDecision | None:
    """Return an authorized decision only when exactly one failed row matches."""
    canonical = validate_disposition_policy(policy)
    authority = canonical["authority"]
    if (
        authority["status"].lower() != "approved"
        or authority["delegated_agent"].lower() != "sage"
        or authority["decision_scope"].lower() != "final_material_disposition"
    ):
        return None
    targets = {str(value) for value in target_characteristic_ids if str(value)}
    rows = [row for row in fai_rows if isinstance(row, Mapping)]
    selected = [
        (index, row)
        for index, row in enumerate(rows)
        if _characteristic_id(row, index) in targets
        and str(row.get("status") or row.get("computed_status") or "").upper()
        in {"FAIL", "FAILED", "REJECT"}
    ]
    if len(selected) != 1:
        return None
    index, row = selected[0]
    characteristic_id = _characteristic_id(row, index)
    try:
        measured = float(row.get("measured"))
        lower = float(row.get("lower_limit"))
        upper = float(row.get("upper_limit"))
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (measured, lower, upper)):
        return None
    if measured > upper:
        direction = "above_upper"
        limit = upper
        deviation = measured - upper
    elif measured < lower:
        direction = "below_lower"
        limit = lower
        deviation = lower - measured
    else:
        return None

    description = _normalize_words(
        row.get("description") or row.get("name") or row.get("feature")
    )
    patterns = _affected_patterns(affected_interfaces, characteristic_id)
    for rule in canonical["rules"]:
        condition = rule["condition"]
        if rule["part_number"] != str(part_number):
            continue
        if condition["status"] not in {"FAIL", "FAILED", "REJECT"}:
            continue
        if condition["direction"] != direction:
            continue
        if deviation + 1e-12 < condition["minimum_out_of_tolerance"]:
            continue
        aliases = [_normalize_words(value) for value in rule["characteristic_aliases"]]
        alias_match = any(alias and alias in description for alias in aliases)
        pattern_match = bool(
            set(rule["interface_pattern_ids"]) & patterns
        )
        if not alias_match and not pattern_match:
            continue
        decision = rule["decision"]
        return DispositionDecision(
            policy_id=canonical["policy_id"],
            policy_version=canonical["version"],
            rule_id=rule["rule_id"],
            characteristic_id=characteristic_id,
            characteristic_label=rule["characteristic_label"],
            part_number=str(part_number),
            subject=decision["subject"],
            disposition=decision["disposition"],
            measured=measured,
            limit=limit,
            deviation=deviation,
            direction=direction,
            unit=condition["unit"],
            use_as_is_allowed=decision["use_as_is_allowed"],
            rework_allowed=decision["rework_allowed"],
            rationale=decision["rationale"],
            approval_ref=authority["approval_ref"],
        )
    return None


class DispositionPolicyRegistry:
    """Thread-safe loader for assembly-scoped approved policy assets."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(__file__).resolve().parent / "disposition_policies"
        self._lock = threading.RLock()
        self._cache: dict[str, tuple[int, dict[str, Any]]] = {}

    def load(self, assembly_number: str) -> dict[str, Any] | None:
        safe = str(assembly_number or "").strip()
        if not _ID_RE.fullmatch(safe):
            return None
        path = self.root / f"{safe}.json"
        if not path.is_file():
            return None
        stamp = path.stat().st_mtime_ns
        with self._lock:
            cached = self._cache.get(safe)
            if cached and cached[0] == stamp:
                return copy.deepcopy(cached[1])
            try:
                raw = json.loads(path.read_text(encoding="ascii"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise DispositionPolicyError(f"cannot load policy {safe}: {exc}") from exc
            canonical = validate_disposition_policy(raw)
            if canonical["assembly_number"] != safe:
                raise DispositionPolicyError(
                    f"policy assembly_number {canonical['assembly_number']} does not match {safe}"
                )
            self._cache[safe] = (stamp, canonical)
            return copy.deepcopy(canonical)
