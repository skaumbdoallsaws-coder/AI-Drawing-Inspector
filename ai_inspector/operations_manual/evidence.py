"""Read-only source and claim repository for operations-manual generation."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping


class OperationsManualEvidenceError(RuntimeError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


class OperationsManualEvidenceRepository:
    """Loads the reviewed pre-coding package as immutable generation evidence."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def _read(self, filename: str) -> Dict[str, Any]:
        path = (self.root / filename).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise OperationsManualEvidenceError("invalid evidence path") from exc
        try:
            value = json.loads(path.read_text("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise OperationsManualEvidenceError(
                f"could not load {filename}: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise OperationsManualEvidenceError(f"{filename} must contain an object")
        return value

    def snapshot(self) -> Dict[str, Any]:
        sources = self._read("source-register.json")
        evidence = self._read("evidence-register.json")
        plan = self._read("mmle-50d-prototype-plan.example.json")
        revision = hashlib.sha256(
            _canonical_bytes(
                {
                    "sources": sources,
                    "evidence": evidence,
                    "prototypePlan": plan,
                }
            )
        ).hexdigest()
        claims = {
            str(row.get("claimId")): copy.deepcopy(row)
            for row in evidence.get("claims") or []
            if isinstance(row, Mapping) and row.get("claimId")
        }
        source_rows = {
            str(row.get("sourceId")): copy.deepcopy(row)
            for row in sources.get("sources") or []
            if isinstance(row, Mapping) and row.get("sourceId")
        }
        return {
            "revision": revision,
            "sources": source_rows,
            "claims": claims,
            "conflicts": copy.deepcopy(evidence.get("conflicts") or []),
            "gaps": copy.deepcopy(evidence.get("gaps") or []),
            "plan": plan,
            "asOf": evidence.get("asOf"),
            "configurationStatus": evidence.get("configurationStatus"),
        }


def release_findings(snapshot: Mapping[str, Any]) -> list[Dict[str, Any]]:
    findings: list[Dict[str, Any]] = []
    for conflict in snapshot.get("conflicts") or []:
        if not isinstance(conflict, Mapping) or not conflict.get("releaseBlocking"):
            continue
        findings.append(
            {
                "findingId": str(conflict.get("conflictId") or ""),
                "code": "EVIDENCE_CONFLICT",
                "findingType": "evidence_conflict",
                "topic": str(conflict.get("topic") or ""),
                "severity": "P1",
                "message": str(conflict.get("resolution") or conflict.get("topic") or ""),
                "blocking": True,
                "sourceIds": [str(value) for value in conflict.get("sourceIds") or []],
            }
        )
    for gap in snapshot.get("gaps") or []:
        if not isinstance(gap, Mapping) or not gap.get("releaseBlocking"):
            continue
        findings.append(
            {
                "findingId": str(gap.get("gapId") or ""),
                "code": "EVIDENCE_GAP",
                "findingType": "evidence_gap",
                "topic": str(gap.get("topic") or ""),
                "severity": "P1",
                "message": str(gap.get("resolutionRequired") or gap.get("description") or ""),
                "blocking": True,
                "sourceIds": [],
            }
        )
    findings.extend(
        [
            {
                "findingId": "LICENSE-PYMUPDF",
                "code": "PDF_LIBRARY_LICENSE_DECISION_REQUIRED",
                "findingType": "governance_prerequisite",
                "topic": "pdf_renderer_license_disposition",
                "severity": "P1",
                "message": (
                    "Controlled PDF publication is disabled until an Artifex "
                    "commercial license or approved replacement is recorded."
                ),
                "blocking": True,
                "sourceIds": [],
            },
            {
                "findingId": "APPROVAL-ROLES",
                "code": "NAMED_REVIEWERS_REQUIRED",
                "findingType": "governance_prerequisite",
                "topic": "named_release_reviewers",
                "severity": "P1",
                "message": (
                    "Named product, safety, technical-publications, and quality "
                    "reviewers are required for controlled release."
                ),
                "blocking": True,
                "sourceIds": [],
            },
            {
                "findingId": "STANDARDS-REVIEW",
                "code": "STANDARDS_EDITION_REVIEW_REQUIRED",
                "findingType": "governance_prerequisite",
                "topic": "standards_and_symbol_review",
                "severity": "P1",
                "message": (
                    "Applicable standards editions and licensed symbol assets "
                    "must be confirmed by the assigned reviewer."
                ),
                "blocking": True,
                "sourceIds": [],
            },
        ]
    )
    return findings
