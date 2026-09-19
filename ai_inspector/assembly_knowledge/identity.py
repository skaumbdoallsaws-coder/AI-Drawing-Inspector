"""Stable CAD occurrence, item, mate, evidence, and finding identities."""

from __future__ import annotations

import posixpath
import re
from typing import Any, Iterable, Mapping, Optional

from .manifest import stable_id


def normalize_configuration(value: Optional[str]) -> str:
    cleaned = str(value or "").strip()
    return cleaned or "Default"


def normalize_occurrence_path(
    name: str,
    *,
    parent_path: Optional[str] = None,
) -> str:
    cleaned = str(name or "").strip().replace("\\", "/")
    cleaned = re.sub(r"/+", "/", cleaned).strip("/")
    if not cleaned:
        raise ValueError("component occurrence name is required")
    parent = str(parent_path or "").strip().replace("\\", "/").strip("/")
    if parent and not cleaned.lower().startswith(parent.lower() + "/"):
        cleaned = posixpath.join(parent, cleaned)
    return cleaned


def occurrence_id(
    *,
    root_source_revision: str,
    configuration: str,
    occurrence_path: str,
) -> str:
    return stable_id(
        "occ",
        {
            "configuration": normalize_configuration(configuration),
            "occurrencePath": normalize_occurrence_path(occurrence_path),
            "rootSourceRevision": root_source_revision,
        },
        digest_length=24,
    )


def item_id(*, source_hash: str, configuration: str) -> str:
    return stable_id(
        "item",
        {
            "configuration": normalize_configuration(configuration),
            "sourceHash": source_hash,
        },
        digest_length=24,
    )


def mate_id(normalized_mate: Mapping[str, Any], *, collision_ordinal: int = 0) -> str:
    return stable_id(
        "mate",
        {
            "mate": dict(normalized_mate),
            "ordinal": int(collision_ordinal),
        },
        digest_length=24,
    )


def evidence_id(
    *,
    source_type: str,
    subject_refs: Iterable[str],
    source_refs: Iterable[str],
    details: Mapping[str, Any],
) -> str:
    return stable_id(
        "evidence",
        {
            "details": dict(details),
            "sourceRefs": sorted(str(item) for item in source_refs),
            "sourceType": source_type,
            "subjectRefs": sorted(str(item) for item in subject_refs),
        },
        digest_length=24,
    )


def claim_id(
    *,
    subject_ref: str,
    predicate: str,
    object_refs: Iterable[str],
    evidence_fingerprint: str,
    policy_version: str,
) -> str:
    return stable_id(
        "claim",
        {
            "evidenceFingerprint": evidence_fingerprint,
            "objectRefs": sorted(str(item) for item in object_refs),
            "policyVersion": policy_version,
            "predicate": predicate,
            "subjectRef": subject_ref,
        },
        digest_length=24,
    )


def finding_id(
    code: str,
    *,
    subject_refs: Iterable[str] = (),
    evidence_refs: Iterable[str] = (),
    details: Optional[Mapping[str, Any]] = None,
) -> str:
    return stable_id(
        "finding",
        {
            "code": code,
            "details": dict(details or {}),
            "evidenceRefs": sorted(str(item) for item in evidence_refs),
            "subjectRefs": sorted(str(item) for item in subject_refs),
        },
        digest_length=20,
    )
