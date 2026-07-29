"""Deterministic, exact diffs for Facility Layout documents.

The diff is an approval artifact, not a mutation language. Every changed path
contains the exact before and after value so a caller can render or audit the
proposal without re-reading mutable state.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Dict, List, Mapping, Sequence

from .canonical import canonical_layout_bytes, canonicalize_layout, layout_revision


FACILITY_LAYOUT_DIFF_SCHEMA_VERSION = 1


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _path(parent: str, child: str) -> str:
    token = _pointer_token(child)
    return f"{parent}/{token}" if parent else f"/{token}"


def _canonical_payload_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def _walk(before: Any, after: Any, path: str, entries: List[Dict[str, Any]]) -> None:
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        before_keys = set(before)
        after_keys = set(after)
        for key in sorted(before_keys - after_keys, key=str):
            entries.append(
                {
                    "op": "remove",
                    "path": _path(path, str(key)),
                    "before": deepcopy(before[key]),
                }
            )
        for key in sorted(after_keys - before_keys, key=str):
            entries.append(
                {
                    "op": "add",
                    "path": _path(path, str(key)),
                    "after": deepcopy(after[key]),
                }
            )
        for key in sorted(before_keys & after_keys, key=str):
            _walk(before[key], after[key], _path(path, str(key)), entries)
        return

    # Array order is meaningful in the v1 contract. Treating one changed array
    # as one exact replacement avoids ambiguous index-shift edit scripts.
    if isinstance(before, list) and isinstance(after, list):
        if before != after:
            entries.append(
                {
                    "op": "replace",
                    "path": path or "/",
                    "before": deepcopy(before),
                    "after": deepcopy(after),
                }
            )
        return

    if before != after:
        entries.append(
            {
                "op": "replace",
                "path": path or "/",
                "before": deepcopy(before),
                "after": deepcopy(after),
            }
        )


def build_exact_layout_diff(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return a stable, lossless before/after diff for two layout documents."""

    normalized_before = canonicalize_layout(deepcopy(dict(before)))
    normalized_after = canonicalize_layout(deepcopy(dict(after)))
    entries: List[Dict[str, Any]] = []
    _walk(normalized_before, normalized_after, "", entries)
    entries.sort(key=lambda item: (str(item["path"]), str(item["op"])))
    return {
        "schemaVersion": FACILITY_LAYOUT_DIFF_SCHEMA_VERSION,
        "beforeRevision": layout_revision(normalized_before),
        "afterRevision": layout_revision(normalized_after),
        "changed": bool(entries),
        "entries": entries,
    }


def facility_layout_diff_hash(
    *,
    layout_id: str,
    base_revision: str,
    operations: Sequence[Mapping[str, Any]],
    after: Mapping[str, Any],
    canonical_diff: Mapping[str, Any],
) -> str:
    """Bind one exact operation proposal to its base and resulting content."""

    payload = {
        "layoutId": layout_id,
        "baseRevision": base_revision,
        "operations": deepcopy([dict(operation) for operation in operations]),
        "afterContentHash": hashlib.sha256(canonical_layout_bytes(after)).hexdigest(),
        "canonicalDiff": deepcopy(dict(canonical_diff)),
    }
    return hashlib.sha256(_canonical_payload_bytes(payload)).hexdigest()


# Short aliases make the API convenient without weakening the explicit names.
build_facility_layout_diff = build_exact_layout_diff
diff_hash = facility_layout_diff_hash

