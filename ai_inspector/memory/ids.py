"""Server-owned identifiers for Sage memory records."""

from __future__ import annotations

import re
import secrets
from typing import Callable


_PREFIXES = {
    "conversation": "conv",
    "agent_session": "agent-session",
    "turn": "turn",
    "summary": "summary",
    "summary_job": "summary-job",
    "context_manifest": "context",
}
_ID_RE = re.compile(r"^[a-z][a-z-]*-[0-9a-f]{32}$")


def new_memory_id(kind: str, token_factory: Callable[[int], str] = secrets.token_hex) -> str:
    try:
        prefix = _PREFIXES[kind]
    except KeyError as exc:
        raise ValueError(f"unknown memory ID kind: {kind}") from exc
    token = token_factory(16)
    value = f"{prefix}-{token}"
    if not _ID_RE.fullmatch(value):
        raise ValueError("memory ID token factory returned an invalid token")
    return value


def is_memory_id(value: str, kind: str | None = None) -> bool:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        return False
    if kind is None:
        return True
    prefix = _PREFIXES.get(kind)
    return prefix is not None and value.startswith(f"{prefix}-")
