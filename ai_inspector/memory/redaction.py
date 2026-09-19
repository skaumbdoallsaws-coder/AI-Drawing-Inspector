"""Deterministic secret redaction for durable Sage-memory records."""

from __future__ import annotations

import hashlib
import json
import os
import re
from functools import lru_cache
from typing import Any, Mapping, Optional, Sequence

from .models import canonical_json
from .repository import MemoryValidationError


SECRET_PATTERNS_ENV = "INSPECTORPRO_MEMORY_SECRET_PATTERNS_JSON"

_SENSITIVE_KEY = re.compile(
    r"(?:^|[_-])(?:api[_-]?key|authorization|cookie|password|secret|"
    r"access[_-]?token|refresh[_-]?token)(?:$|[_-])",
    re.IGNORECASE,
)
_HEADER_SECRET = re.compile(
    r"(?im)(?P<prefix>\b(?:authorization|proxy-authorization|cookie|"
    r"set-cookie)\s*:\s*)(?P<value>[^\r\n]+)"
)
_ASSIGNED_SECRET = re.compile(
    r"(?i)(?P<prefix>\b(?:api[_-]?key|password|secret|access[_-]?token|"
    r"refresh[_-]?token)\b\s*[:=]\s*)"
    r"(?P<value>\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;]+)"
)
_STANDALONE_SECRET = re.compile(
    r"(?<![A-Za-z0-9_-])(?:sk-(?:ant-|proj-)?[A-Za-z0-9_-]{16,}|"
    r"gh[pousr]_[A-Za-z0-9]{20,})(?![A-Za-z0-9_-])"
)


def redact_text(
    value: str,
    *,
    configured_patterns: Optional[Sequence[re.Pattern[str]]] = None,
) -> str:
    """Redact known credentials while preserving deterministic retry identity."""

    text = str(value)
    text = _HEADER_SECRET.sub(_redact_named_match, text)
    text = _ASSIGNED_SECRET.sub(_redact_named_match, text)
    text = _STANDALONE_SECRET.sub(lambda match: _marker(match.group(0)), text)
    patterns = (
        tuple(configured_patterns)
        if configured_patterns is not None
        else configured_secret_patterns()
    )
    for pattern in patterns:
        text = pattern.sub(lambda match: _marker(match.group(0)), text)
    return text


def redact_for_persistence(
    value: Any,
    *,
    configured_patterns: Optional[Sequence[re.Pattern[str]]] = None,
) -> Any:
    """Return an ASCII-serializable clone with sensitive values removed."""

    patterns = (
        tuple(configured_patterns)
        if configured_patterns is not None
        else configured_secret_patterns()
    )
    if isinstance(value, Mapping):
        redacted = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            if _SENSITIVE_KEY.search(key):
                redacted[key] = _marker(_stable_secret_text(item))
            else:
                redacted[key] = redact_for_persistence(
                    item,
                    configured_patterns=patterns,
                )
        return redacted
    if isinstance(value, list):
        return [
            redact_for_persistence(item, configured_patterns=patterns)
            for item in value
        ]
    if isinstance(value, tuple):
        return [
            redact_for_persistence(item, configured_patterns=patterns)
            for item in value
        ]
    if isinstance(value, str):
        return redact_text(value, configured_patterns=patterns)
    return value


def configured_secret_patterns(
    environ: Optional[Mapping[str, str]] = None,
) -> tuple[re.Pattern[str], ...]:
    values = os.environ if environ is None else environ
    raw = str(values.get(SECRET_PATTERNS_ENV) or "").strip()
    return _compile_configured_patterns(raw)


@lru_cache(maxsize=16)
def _compile_configured_patterns(raw: str) -> tuple[re.Pattern[str], ...]:
    if not raw:
        return ()
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MemoryValidationError(
            f"{SECRET_PATTERNS_ENV} must be a JSON array of regular expressions"
        ) from exc
    if not isinstance(values, list) or len(values) > 20:
        raise MemoryValidationError(
            f"{SECRET_PATTERNS_ENV} must contain at most 20 patterns"
        )
    compiled = []
    for value in values:
        if not isinstance(value, str) or not value or len(value) > 500:
            raise MemoryValidationError(
                f"{SECRET_PATTERNS_ENV} contains an invalid pattern"
            )
        try:
            compiled.append(re.compile(value))
        except re.error as exc:
            raise MemoryValidationError(
                f"{SECRET_PATTERNS_ENV} contains an invalid regular expression"
            ) from exc
    return tuple(compiled)


def _redact_named_match(match: re.Match[str]) -> str:
    return match.group("prefix") + _marker(match.group("value"))


def _marker(value: str) -> str:
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()
    return f"<redacted:sha256:{digest}>"


def _stable_secret_text(value: Any) -> str:
    try:
        return canonical_json(value)
    except (TypeError, ValueError):
        return str(value)


__all__ = [
    "SECRET_PATTERNS_ENV",
    "configured_secret_patterns",
    "redact_for_persistence",
    "redact_text",
]
