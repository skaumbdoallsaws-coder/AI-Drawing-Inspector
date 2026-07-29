"""Deterministic, no-CAD source discovery for industrial assets."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
from typing import Iterable

from .schema_v1 import (
    DiscoveryResult,
    IntakeFinding,
    SourceFileRecord,
    canonical_json_sha256,
    canonical_path_key,
    canonical_relative_path,
    sort_findings,
)


DEFAULT_SOURCE_KINDS = {
    ".sldasm": "assembly",
    ".sldprt": "part",
    ".step": "interchange",
    ".stp": "interchange",
    ".iges": "interchange",
    ".igs": "interchange",
    ".x_t": "interchange",
    ".x_b": "interchange",
}


class SourcePathRejected(ValueError):
    """Raised when an untrusted source root violates the configured boundary."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DiscoveryPolicy:
    source_kinds: dict[str, str] | None = None
    maximum_entries: int = 50_000
    maximum_source_files: int = 10_000
    maximum_total_source_bytes: int = 20 * 1024 * 1024 * 1024
    maximum_single_file_bytes: int = 4 * 1024 * 1024 * 1024
    maximum_depth: int = 64
    hash_chunk_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        numeric = (
            self.maximum_entries,
            self.maximum_source_files,
            self.maximum_total_source_bytes,
            self.maximum_single_file_bytes,
            self.maximum_depth,
            self.hash_chunk_bytes,
        )
        if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in numeric):
            raise ValueError("discovery limits must be positive integers")
        source_kinds = self.source_kinds or DEFAULT_SOURCE_KINDS
        normalized: dict[str, str] = {}
        for extension, kind in source_kinds.items():
            extension_value = str(extension).lower()
            if not extension_value.startswith(".") or not kind:
                raise ValueError("source kind extensions must start with a dot")
            normalized[extension_value] = str(kind)
        object.__setattr__(self, "source_kinds", normalized)


@dataclass(frozen=True)
class TrustedSourceRoots:
    """Resolved server configuration used to authorize untrusted source roots."""

    roots: tuple[Path, ...]

    @classmethod
    def from_paths(cls, roots: Iterable[str | Path]) -> "TrustedSourceRoots":
        resolved: list[Path] = []
        for value in roots:
            path = Path(value)
            if not path.is_absolute():
                raise SourcePathRejected(
                    "configured_root_not_absolute",
                    "Configured source roots must be absolute.",
                )
            try:
                canonical = path.resolve(strict=True)
            except OSError as exc:
                raise SourcePathRejected(
                    "configured_root_unavailable",
                    "A configured source root is unavailable.",
                ) from exc
            if not canonical.is_dir():
                raise SourcePathRejected(
                    "configured_root_not_directory",
                    "Configured source roots must be directories.",
                )
            if canonical not in resolved:
                resolved.append(canonical)
        if not resolved:
            raise SourcePathRejected(
                "configured_roots_empty",
                "At least one configured source root is required.",
            )
        return cls(tuple(sorted(resolved, key=lambda item: os.path.normcase(str(item)))))

    def resolve_directory(self, requested: str | Path) -> Path:
        candidate = Path(requested)
        if not candidate.is_absolute():
            raise SourcePathRejected(
                "source_root_not_absolute",
                "The requested source root must be absolute.",
            )
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise SourcePathRejected(
                "source_root_unavailable",
                "The requested source root is unavailable.",
            ) from exc
        if not resolved.is_dir():
            raise SourcePathRejected(
                "source_root_not_directory",
                "The requested source root must be a directory.",
            )
        for configured in self.roots:
            try:
                resolved.relative_to(configured)
                return resolved
            except ValueError:
                continue
        raise SourcePathRejected(
            "source_root_outside_configured_roots",
            "The requested source root is outside configured roots.",
        )


def _is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def _sha256_stable_file(path: Path, *, chunk_size: int) -> tuple[str, int]:
    descriptor: int | None = None
    before = path.lstat()
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise OSError("source file is not a stable regular file")
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (before.st_dev, before.st_ino)
            != (opened.st_dev, opened.st_ino)
        ):
            raise OSError("source file changed before hashing")
        digest = hashlib.sha256()
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = None
            while True:
                chunk = stream.read(chunk_size)
                if not chunk:
                    break
                digest.update(chunk)
        after = path.lstat()
    finally:
        if descriptor is not None:
            os.close(descriptor)
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if before_identity != after_identity:
        raise OSError("source file changed during hashing")
    return digest.hexdigest(), after.st_size


def discover_source_tree(
    requested_root: str | Path,
    *,
    allowed_roots: TrustedSourceRoots | Iterable[str | Path],
    policy: DiscoveryPolicy | None = None,
) -> DiscoveryResult:
    """Recursively inventory supported CAD sources without opening CAD.

    Directory links and junctions are not followed. Returned records contain
    only safe relative paths; the authorized absolute root never leaves this
    function.
    """

    active_policy = policy or DiscoveryPolicy()
    roots = (
        allowed_roots
        if isinstance(allowed_roots, TrustedSourceRoots)
        else TrustedSourceRoots.from_paths(allowed_roots)
    )
    root = roots.resolve_directory(requested_root)
    records: list[SourceFileRecord] = []
    findings: list[IntakeFinding] = []
    seen_path_keys: dict[str, str] = {}
    scanned_entries = 0
    ignored_files = 0
    total_source_bytes = 0
    stopped = False

    def add_limit_finding(code: str, message: str, relative_path: str | None = None) -> None:
        nonlocal stopped
        findings.append(
            IntakeFinding(
                "error",
                code,
                message,
                relative_path=relative_path,
            )
        )
        stopped = True

    def walk(directory: Path, relative_parts: tuple[str, ...], depth: int) -> None:
        nonlocal scanned_entries, ignored_files, total_source_bytes, stopped
        if stopped:
            return
        if depth > active_policy.maximum_depth:
            add_limit_finding(
                "source_depth_limit_exceeded",
                "Source discovery exceeded its configured recursion depth.",
                "/".join(relative_parts) if relative_parts else None,
            )
            return
        try:
            entries = sorted(
                os.scandir(directory),
                key=lambda item: (item.name.casefold(), item.name),
            )
        except OSError:
            findings.append(
                IntakeFinding(
                    "error",
                    "source_directory_unreadable",
                    "A source directory could not be read.",
                    relative_path="/".join(relative_parts) if relative_parts else None,
                )
            )
            return
        for entry in entries:
            if stopped:
                return
            scanned_entries += 1
            relative = canonical_relative_path("/".join((*relative_parts, entry.name)))
            if scanned_entries > active_policy.maximum_entries:
                add_limit_finding(
                    "source_entry_limit_exceeded",
                    "Source discovery exceeded its configured entry limit.",
                    relative,
                )
                return
            path = Path(entry.path)
            if _is_link_like(path):
                findings.append(
                    IntakeFinding(
                        "error",
                        "source_link_rejected",
                        "Symbolic links and junctions are not followed during intake.",
                        relative_path=relative,
                    )
                )
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    resolved_directory = path.resolve(strict=True)
                    try:
                        resolved_directory.relative_to(root)
                    except ValueError:
                        findings.append(
                            IntakeFinding(
                                "error",
                                "source_path_escape",
                                "A discovered directory escapes the authorized source root.",
                                relative_path=relative,
                            )
                        )
                        continue
                    walk(
                        resolved_directory,
                        (*relative_parts, entry.name),
                        depth + 1,
                    )
                    continue
                if not entry.is_file(follow_symlinks=False):
                    findings.append(
                        IntakeFinding(
                            "warning",
                            "source_entry_unsupported",
                            "A non-file source entry was ignored.",
                            relative_path=relative,
                        )
                    )
                    continue
            except OSError:
                findings.append(
                    IntakeFinding(
                        "error",
                        "source_entry_unreadable",
                        "A source entry could not be inspected.",
                        relative_path=relative,
                    )
                )
                continue

            extension = path.suffix.lower()
            source_kind = active_policy.source_kinds.get(extension)
            if source_kind is None:
                ignored_files += 1
                continue
            if len(records) >= active_policy.maximum_source_files:
                add_limit_finding(
                    "source_file_limit_exceeded",
                    "Source discovery exceeded its configured CAD-file limit.",
                    relative,
                )
                return
            try:
                size = path.stat().st_size
                if size > active_policy.maximum_single_file_bytes:
                    findings.append(
                        IntakeFinding(
                            "error",
                            "source_file_size_limit_exceeded",
                            "A CAD source exceeds the configured per-file size limit.",
                            relative_path=relative,
                        )
                    )
                    continue
                if total_source_bytes + size > active_policy.maximum_total_source_bytes:
                    add_limit_finding(
                        "source_total_size_limit_exceeded",
                        "CAD sources exceed the configured total size limit.",
                        relative,
                    )
                    return
                digest, stable_size = _sha256_stable_file(
                    path,
                    chunk_size=active_policy.hash_chunk_bytes,
                )
            except OSError:
                findings.append(
                    IntakeFinding(
                        "error",
                        "source_file_unstable_or_unreadable",
                        "A CAD source could not be read consistently.",
                        relative_path=relative,
                    )
                )
                continue
            key = canonical_path_key(relative)
            previous = seen_path_keys.get(key)
            if previous is not None:
                findings.append(
                    IntakeFinding(
                        "error",
                        "duplicate_normalized_source_path",
                        "Two sources normalize to the same portable path.",
                        relative_path=relative,
                        candidates=(previous, relative),
                    )
                )
                continue
            seen_path_keys[key] = relative
            total_source_bytes += stable_size
            records.append(
                SourceFileRecord(
                    relative_path=relative,
                    path_key=key,
                    safe_label=path.name,
                    extension=extension,
                    source_kind=source_kind,
                    byte_length=stable_size,
                    sha256=digest,
                )
            )

    walk(root, (), 0)
    records.sort(key=lambda item: item.path_key)
    if not records:
        findings.append(
            IntakeFinding(
                "error",
                "source_files_not_found",
                "No supported CAD source files were discovered.",
            )
        )
    source_fingerprint = canonical_json_sha256(
        {
            "files": [
                {
                    "byteLength": record.byte_length,
                    "pathKey": record.path_key,
                    "sha256": record.sha256,
                    "sourceKind": record.source_kind,
                }
                for record in records
            ],
            "schemaVersion": 1,
        }
    )
    return DiscoveryResult(
        schema_version=1,
        records=tuple(records),
        source_fingerprint=source_fingerprint,
        findings=sort_findings(findings),
        scanned_entry_count=scanned_entries,
        ignored_file_count=ignored_files,
    )
