"""Deterministic FAI request targeting from live table state.

The model reasons about engineering consequences. It does not decide which
row phrases such as "the failed dimension" or "the one I just added" refer
to; the application resolves that referent before prompt compilation.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping


_WORD_RE = re.compile(r"[a-z0-9]+")
_STOP_WORDS = frozenset({
    "a", "an", "and", "at", "dimension", "feature", "for", "from", "how",
    "is", "it", "of", "on", "the", "this", "to", "what", "with",
})
_RECENT_RE = re.compile(
    r"\b(?:new|newest|latest|most recent|just (?:added|changed|entered|failed)|"
    r"one i just|recently (?:added|changed|entered|failed))\b",
    re.IGNORECASE,
)
_OTHER_RE = re.compile(r"\b(?:other|another|next)\b", re.IGNORECASE)
_ALL_RE = re.compile(
    r"\b(?:all|each|every|both|results|failures|failed dimensions|failed characteristics|"
    r"out[- ]of[- ]spec dimensions|out[- ]of[- ]tolerance dimensions)\b",
    re.IGNORECASE,
)
_FAILURE_RE = re.compile(
    r"\b(?:fail|failed|failure|out[- ]of[- ]spec|out[- ]of[- ]tolerance|deviation)\b",
    re.IGNORECASE,
)


def _row_id(row: Mapping[str, Any], index: int) -> str:
    for key in ("char_number", "characteristic_number", "number", "id", "balloon"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return str(index + 1)


def _status(row: Mapping[str, Any]) -> str:
    return str(row.get("computed_status") or row.get("status") or "").strip().upper()


def _tokens(value: Any) -> set[str]:
    return {
        token for token in _WORD_RE.findall(str(value or "").lower())
        if len(token) >= 3 and token not in _STOP_WORDS
    }


def _explicit_ids(message: str) -> list[str]:
    found: list[str] = []
    patterns = (
        r"#\s*(\d+)\b",
        r"\b(?:characteristic|char(?:acteristic)?\.?|balloon)\s*(?:number|no\.?|#)?\s*(\d+)\b",
        r"\bdimension\s*#\s*(\d+)\b",
    )
    for pattern in patterns:
        for value in re.findall(pattern, message or "", flags=re.IGNORECASE):
            normalized = str(int(value))
            if normalized not in found:
                found.append(normalized)
    return found


def _description_matches(message: str, indexed: Mapping[str, Mapping[str, Any]]) -> list[str]:
    query_tokens = _tokens(message)
    if not query_tokens:
        return []
    scored: list[tuple[int, int, str]] = []
    for characteristic_id, row in indexed.items():
        row_tokens = _tokens(
            row.get("description") or row.get("name") or row.get("feature") or ""
        )
        overlap = query_tokens & row_tokens
        if len(overlap) < 2:
            continue
        score = len(overlap) * 10
        if {"outside", "diameter"} <= overlap or {"pin", "bore"} <= overlap:
            score += 8
        scored.append((score, -len(row_tokens), characteristic_id))
    if not scored:
        return []
    scored.sort(reverse=True)
    best = scored[0][0]
    return [item[2] for item in scored if item[0] == best]


def _snapshot_ids(snapshot: Mapping[str, Any], key: str) -> list[str]:
    values = snapshot.get(key)
    if not isinstance(values, list):
        return []
    result = []
    for value in values:
        normalized = str(value).strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def resolve_fai_request_target(
    message: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve one user turn to exact FAI characteristic IDs.

    Precedence is explicit ID/name, explicit recency, selected row, a single
    failure, then all current failures. The selected row is intentionally
    bypassed for "new/other" wording so a stale selection cannot defeat an
    explicit temporal referent.
    """

    safe_rows = [row for row in rows if isinstance(row, Mapping)]
    indexed = {_row_id(row, index): row for index, row in enumerate(safe_rows)}
    snapshot = snapshot if isinstance(snapshot, Mapping) else {}
    query = str(message or "").strip()
    explicit = _explicit_ids(query)
    missing_explicit = [item for item in explicit if item not in indexed]
    if explicit:
        targets = [item for item in explicit if item in indexed]
        return {
            "schema_version": 1,
            "request_scope": "specific_characteristic" if len(targets) == 1 else "specific_characteristics",
            "target_characteristic_ids": targets,
            "resolution": "explicit_characteristic_number",
            "mentions_characteristic_number": True,
            "needs_clarification": bool(missing_explicit or not targets),
            "missing_characteristic_ids": missing_explicit,
            "table_revision": int(snapshot.get("table_revision") or 0),
        }

    name_matches = _description_matches(query, indexed)
    if len(name_matches) == 1:
        return {
            "schema_version": 1,
            "request_scope": "specific_characteristic",
            "target_characteristic_ids": name_matches,
            "resolution": "explicit_characteristic_name",
            "mentions_characteristic_number": False,
            "needs_clarification": False,
            "missing_characteristic_ids": [],
            "table_revision": int(snapshot.get("table_revision") or 0),
        }

    failed_ids = [
        characteristic_id for characteristic_id, row in indexed.items()
        if _status(row) in {"FAIL", "FAILED", "REJECT"}
    ]
    recency_requested = bool(_RECENT_RE.search(query) or _OTHER_RE.search(query))
    if recency_requested:
        newly_failed = [
            item for item in _snapshot_ids(snapshot, "newly_failed_characteristic_ids")
            if item in indexed
        ]
        changed_rows = snapshot.get("changed_since_last_response")
        changed_rows = changed_rows if isinstance(changed_rows, list) else []
        changed = sorted(
            (
                item for item in changed_rows
                if isinstance(item, Mapping)
                and str(item.get("id") or "") in indexed
                and str(item.get("current_status") or "").upper() in {"FAIL", "FAILED"}
            ),
            key=lambda item: (
                int(item.get("revision") or 0),
                int(item.get("row_revision") or 0),
            ),
            reverse=True,
        )
        changed_ids = [str(item.get("id")) for item in changed]
        if newly_failed:
            recent_ids = [item for item in changed_ids if item in set(newly_failed)]
            recent_ids.extend(item for item in newly_failed if item not in recent_ids)
        else:
            recent_ids = changed_ids
        previous_targets = set(_snapshot_ids(snapshot, "previous_target_characteristic_ids"))
        if _OTHER_RE.search(query):
            without_previous = [item for item in recent_ids if item not in previous_targets]
            if without_previous:
                recent_ids = without_previous
        if recent_ids:
            return {
                "schema_version": 1,
                "request_scope": "specific_characteristic",
                "target_characteristic_ids": [recent_ids[0]],
                "resolution": "changed_since_last_response",
                "mentions_characteristic_number": False,
                "needs_clarification": False,
                "missing_characteristic_ids": [],
                "table_revision": int(snapshot.get("table_revision") or 0),
            }

    asks_all = bool(_ALL_RE.search(query))
    selected = str(snapshot.get("selected_characteristic_id") or "").strip()
    if selected and selected in indexed and not asks_all and not recency_requested:
        selected_row = indexed[selected]
        if not _FAILURE_RE.search(query) or _status(selected_row) in {"FAIL", "FAILED", "REJECT"}:
            return {
                "schema_version": 1,
                "request_scope": "specific_characteristic",
                "target_characteristic_ids": [selected],
                "resolution": "selected_characteristic",
                "mentions_characteristic_number": False,
                "needs_clarification": False,
                "missing_characteristic_ids": [],
                "table_revision": int(snapshot.get("table_revision") or 0),
            }

    if len(failed_ids) == 1 and not asks_all:
        return {
            "schema_version": 1,
            "request_scope": "specific_characteristic",
            "target_characteristic_ids": failed_ids,
            "resolution": "single_current_failure",
            "mentions_characteristic_number": False,
            "needs_clarification": False,
            "missing_characteristic_ids": [],
            "table_revision": int(snapshot.get("table_revision") or 0),
        }

    if failed_ids:
        return {
            "schema_version": 1,
            "request_scope": "all_failed_characteristics",
            "target_characteristic_ids": failed_ids,
            "resolution": "all_current_failures",
            "mentions_characteristic_number": False,
            "needs_clarification": False,
            "missing_characteristic_ids": [],
            "table_revision": int(snapshot.get("table_revision") or 0),
        }

    return {
        "schema_version": 1,
        "request_scope": "no_failed_characteristic",
        "target_characteristic_ids": [],
        "resolution": "no_current_failure",
        "mentions_characteristic_number": False,
        "needs_clarification": False,
        "missing_characteristic_ids": [],
        "table_revision": int(snapshot.get("table_revision") or 0),
    }
