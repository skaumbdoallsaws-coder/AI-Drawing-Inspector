"""Version-one records for deterministic industrial-asset source intake.

This module deliberately models only the pre-extraction sidecar. It does not
publish catalog assets, claim CAD dependency completeness, or expose protected
filesystem roots.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import PurePosixPath
import re
import unicodedata
from typing import Any, Iterable, Mapping, Sequence


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize identity-bearing data as deterministic ASCII JSON."""

    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("ascii")


def canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def canonical_relative_path(value: str) -> str:
    """Return a portable, case-preserving relative path.

    The returned path is safe to include in protected intake records. Absolute
    paths, traversal, drive-qualified paths, and empty segments fail closed.
    """

    if not isinstance(value, str):
        raise ValueError("relative path must be a string")
    raw = unicodedata.normalize("NFC", value.strip()).replace("\\", "/")
    if not raw or raw.startswith("/") or raw.startswith("//"):
        raise ValueError("relative path must be non-empty and relative")
    if re.match(r"^[A-Za-z]:", raw):
        raise ValueError("drive-qualified paths are not allowed")
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("relative path traversal is not allowed")
    normalized = str(PurePosixPath(*parts))
    if not normalized or normalized == ".":
        raise ValueError("relative path must identify a file")
    return normalized


def canonical_path_key(value: str) -> str:
    """Return a platform-neutral comparison key for a relative path."""

    return canonical_relative_path(value).casefold()


def stable_finding_id(
    code: str,
    *,
    relative_path: str | None = None,
    reference: str | None = None,
    candidates: Sequence[str] = (),
) -> str:
    digest = canonical_json_sha256(
        {
            "candidates": sorted(candidates, key=lambda item: (item.casefold(), item)),
            "code": code,
            "reference": reference,
            "relativePath": relative_path,
        }
    )
    return f"iaf-{digest[:24]}"


@dataclass(frozen=True)
class IntakeFinding:
    severity: str
    code: str
    message: str
    relative_path: str | None = None
    reference: str | None = None
    candidates: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.severity not in {"error", "warning", "info"}:
            raise ValueError("finding severity must be error, warning, or info")
        if not self.code or not self.code.isascii():
            raise ValueError("finding code must be non-empty ASCII")
        if self.relative_path is not None:
            object.__setattr__(
                self,
                "relative_path",
                canonical_relative_path(self.relative_path),
            )
        object.__setattr__(
            self,
            "candidates",
            tuple(
                sorted(
                    (canonical_relative_path(item) for item in self.candidates),
                    key=lambda item: (item.casefold(), item),
                )
            ),
        )

    @property
    def finding_id(self) -> str:
        return stable_finding_id(
            self.code,
            relative_path=self.relative_path,
            reference=self.reference,
            candidates=self.candidates,
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "findingId": self.finding_id,
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }
        if self.relative_path is not None:
            result["relativePath"] = self.relative_path
        if self.reference is not None:
            result["reference"] = self.reference
        if self.candidates:
            result["candidates"] = list(self.candidates)
        return result


def sort_findings(findings: Iterable[IntakeFinding]) -> tuple[IntakeFinding, ...]:
    unique: dict[str, IntakeFinding] = {}
    for finding in findings:
        unique[finding.finding_id] = finding
    return tuple(
        sorted(
            unique.values(),
            key=lambda item: (
                {"error": 0, "warning": 1, "info": 2}[item.severity],
                item.code,
                (item.relative_path or "").casefold(),
                item.relative_path or "",
                item.reference or "",
                item.candidates,
                item.finding_id,
            ),
        )
    )


@dataclass(frozen=True)
class SourceFileRecord:
    relative_path: str
    path_key: str
    safe_label: str
    extension: str
    source_kind: str
    byte_length: int
    sha256: str

    def __post_init__(self) -> None:
        normalized = canonical_relative_path(self.relative_path)
        if self.relative_path != normalized:
            raise ValueError("source relative_path must already be canonical")
        if self.path_key != canonical_path_key(normalized):
            raise ValueError("source path_key does not match relative_path")
        if not self.safe_label or "/" in self.safe_label or "\\" in self.safe_label:
            raise ValueError("safe_label must be a basename")
        if self.extension != self.extension.lower() or not self.extension.startswith("."):
            raise ValueError("extension must be lowercase and start with a dot")
        if self.byte_length < 0:
            raise ValueError("byte_length must be non-negative")
        if not _SHA256_RE.fullmatch(self.sha256):
            raise ValueError("sha256 must be a lowercase SHA-256 digest")

    @property
    def basename_key(self) -> str:
        return self.safe_label.casefold()

    def to_dict(self) -> dict[str, Any]:
        return {
            "relativePath": self.relative_path,
            "pathKey": self.path_key,
            "safeLabel": self.safe_label,
            "extension": self.extension,
            "sourceKind": self.source_kind,
            "byteLength": self.byte_length,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class DiscoveryResult:
    schema_version: int
    records: tuple[SourceFileRecord, ...]
    source_fingerprint: str
    findings: tuple[IntakeFinding, ...] = ()
    scanned_entry_count: int = 0
    ignored_file_count: int = 0

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("only discovery schema version 1 is supported")
        if not _SHA256_RE.fullmatch(self.source_fingerprint):
            raise ValueError("source_fingerprint must be a SHA-256 digest")
        keys = [record.path_key for record in self.records]
        if keys != sorted(keys):
            raise ValueError("discovery records must be sorted by path_key")
        if len(keys) != len(set(keys)):
            raise ValueError("discovery records must have unique path keys")

    @property
    def quarantined(self) -> bool:
        return any(item.severity == "error" for item in self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "recordKind": "industrial_asset_source_discovery",
            "sourceFingerprint": self.source_fingerprint,
            "quarantined": self.quarantined,
            "scannedEntryCount": self.scanned_entry_count,
            "ignoredFileCount": self.ignored_file_count,
            "files": [record.to_dict() for record in self.records],
            "findings": [finding.to_dict() for finding in self.findings],
        }


@dataclass(frozen=True)
class DependencyReference:
    owner_path: str
    reference: str
    reference_kind: str = "cad_external_reference"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "owner_path",
            canonical_relative_path(self.owner_path),
        )
        if not isinstance(self.reference, str) or not self.reference.strip():
            raise ValueError("dependency reference must be non-empty")
        if (
            not isinstance(self.reference_kind, str)
            or not self.reference_kind
            or not self.reference_kind.isascii()
        ):
            raise ValueError("reference_kind must be non-empty ASCII")


@dataclass(frozen=True)
class DependencyEdge:
    owner_path: str
    target_path: str
    reference: str
    reference_kind: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ownerPath": self.owner_path,
            "targetPath": self.target_path,
            "reference": self.reference,
            "referenceKind": self.reference_kind,
        }


@dataclass(frozen=True)
class DependencyGraphResult:
    schema_version: int
    status: str
    reference_graph_complete: bool
    root_candidates: tuple[str, ...]
    selected_root: str | None
    source_paths: tuple[str, ...]
    edges: tuple[DependencyEdge, ...]
    findings: tuple[IntakeFinding, ...]

    def __post_init__(self) -> None:
        allowed = {
            "resolved",
            "candidate_only",
            "selection_required",
            "quarantined",
        }
        if self.schema_version != 1 or self.status not in allowed:
            raise ValueError("invalid dependency graph result")

    @property
    def quarantined(self) -> bool:
        return self.status == "quarantined"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "status": self.status,
            "referenceGraphComplete": self.reference_graph_complete,
            "rootCandidates": list(self.root_candidates),
            "selectedRoot": self.selected_root,
            "sourcePaths": list(self.source_paths),
            "edges": [edge.to_dict() for edge in self.edges],
            "findings": [finding.to_dict() for finding in self.findings],
        }


def validate_json_value(value: Any, *, maximum_bytes: int = 65_536) -> Any:
    """Return a detached JSON-compatible value or raise deterministically."""

    try:
        payload = canonical_json_bytes(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("value must be finite JSON-compatible data") from exc
    if len(payload) > maximum_bytes:
        raise ValueError("canonical JSON value exceeds the configured limit")
    return json.loads(payload.decode("ascii"))


def source_revision(
    records: Sequence[SourceFileRecord],
    *,
    configuration: str,
    extraction_inputs: Mapping[str, Any],
) -> str:
    if not isinstance(configuration, str) or not configuration.strip():
        raise ValueError("configuration must be a non-empty string")
    if len(configuration) > 256:
        raise ValueError("configuration exceeds 256 characters")
    inputs = validate_json_value(extraction_inputs)
    return canonical_json_sha256(
        {
            "configuration": configuration,
            "extractionInputs": inputs,
            "sourceFileHashes": [
                {
                    "pathKey": record.path_key,
                    "sha256": record.sha256,
                }
                for record in sorted(records, key=lambda item: item.path_key)
            ],
        }
    )


@dataclass(frozen=True)
class NormalizedSourceIdentity:
    document: Mapping[str, Any] = field(repr=False)

    def __post_init__(self) -> None:
        detached = validate_json_value(self.document, maximum_bytes=1_048_576)
        object.__setattr__(self, "document", detached)

    def to_dict(self) -> dict[str, Any]:
        return json.loads(canonical_json_bytes(self.document).decode("ascii"))
