"""Pilot maintenance operations for durable Sage memory."""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .models import MemoryPrincipal, RetentionResult
from .repository import MemoryRepository, MemoryValidationError


def run_retention_cleanup(
    repository: MemoryRepository,
    principal: MemoryPrincipal,
    *,
    before: Optional[datetime] = None,
    batch_size: int = 100,
    maximum_batches: int = 100,
) -> Dict[str, Any]:
    """Delete expired conversation graphs in bounded, repeatable batches."""

    if not 1 <= int(batch_size) <= 5000:
        raise MemoryValidationError("retention batch size must be 1-5000")
    if not 1 <= int(maximum_batches) <= 10000:
        raise MemoryValidationError("retention maximum batches must be 1-10000")
    cutoff = before or datetime.now(timezone.utc)
    if cutoff.tzinfo is None:
        raise MemoryValidationError("retention cutoff must be timezone-aware")

    totals = RetentionResult(0, 0, 0, 0, 0)
    batches = 0
    while batches < int(maximum_batches):
        result = repository.purge_expired(
            principal,
            before=cutoff,
            limit=int(batch_size),
        )
        batches += 1
        totals = RetentionResult(
            totals.conversation_count + result.conversation_count,
            totals.agent_session_count + result.agent_session_count,
            totals.turn_count + result.turn_count,
            totals.summary_count + result.summary_count,
            totals.context_manifest_count + result.context_manifest_count,
        )
        if result.conversation_count < int(batch_size):
            break

    return {
        "cutoffUtc": cutoff.astimezone(timezone.utc).isoformat(),
        "batches": batches,
        "batchSize": int(batch_size),
        "maximumBatchesReached": (
            batches >= int(maximum_batches)
            and totals.conversation_count >= int(batch_size)
        ),
        "deleted": {
            _camel_case(key): value for key, value in asdict(totals).items()
        },
    }


def backup_sqlite_database(
    source: Path,
    destination: Path,
) -> Dict[str, Any]:
    """Create and integrity-check an online SQLite backup atomically."""

    source_path = Path(source).resolve()
    destination_path = Path(destination).resolve()
    if source_path == destination_path:
        raise MemoryValidationError("backup destination must differ from source")
    if not source_path.is_file():
        raise MemoryValidationError("memory database does not exist")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination_path.with_name(
        destination_path.name + ".tmp-" + os.urandom(6).hex()
    )
    try:
        with closing(sqlite3.connect(source_path)) as source_connection:
            with closing(sqlite3.connect(temporary)) as destination_connection:
                source_connection.backup(destination_connection)
                destination_connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                destination_connection.commit()
        quick_check = sqlite_quick_check(temporary)
        if quick_check != "ok":
            raise MemoryValidationError(
                f"memory backup integrity check failed: {quick_check}"
            )
        os.replace(temporary, destination_path)
    finally:
        if temporary.exists():
            temporary.unlink()

    payload = destination_path.read_bytes()
    return {
        "source": str(source_path),
        "destination": str(destination_path),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "quickCheck": quick_check,
        "createdAtUtc": datetime.now(timezone.utc).isoformat(),
    }


def sqlite_quick_check(path: Path) -> str:
    database_path = Path(path)
    if not database_path.is_file():
        raise MemoryValidationError("SQLite database does not exist")
    try:
        with closing(sqlite3.connect(database_path)) as connection:
            row = connection.execute("PRAGMA quick_check").fetchone()
    except sqlite3.DatabaseError as exc:
        raise MemoryValidationError(
            f"SQLite integrity check failed: {exc}"
        ) from exc
    return str(row[0] if row else "missing_result")


def _remove_sqlite_sidecars(database: Path) -> None:
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(database) + suffix)
        try:
            sidecar.unlink()
        except FileNotFoundError:
            pass


def restore_sqlite_database(
    backup: Path,
    destination: Path,
    *,
    pre_restore_backup: Optional[Path] = None,
) -> Dict[str, Any]:
    """Restore a stopped pilot database with integrity checks and rollback copy."""

    backup_path = Path(backup).resolve()
    destination_path = Path(destination).resolve()
    if backup_path == destination_path:
        raise MemoryValidationError("restore source must differ from destination")
    source_check = sqlite_quick_check(backup_path)
    if source_check != "ok":
        raise MemoryValidationError(
            f"memory restore source integrity check failed: {source_check}"
        )

    rollback_path = None
    if destination_path.exists():
        rollback_path = Path(pre_restore_backup).resolve() if pre_restore_backup else (
            destination_path.with_name(
                destination_path.stem
                + ".pre-restore-"
                + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                + destination_path.suffix
            )
        )
        backup_sqlite_database(destination_path, rollback_path)

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination_path.with_name(
        destination_path.name + ".restore-" + os.urandom(6).hex()
    )
    replaced = False
    try:
        shutil.copyfile(backup_path, temporary)
        with temporary.open("rb+") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        copied_check = sqlite_quick_check(temporary)
        if copied_check != "ok":
            raise MemoryValidationError(
                f"copied restore database failed integrity check: {copied_check}"
            )
        _remove_sqlite_sidecars(destination_path)
        os.replace(temporary, destination_path)
        replaced = True
        restored_check = sqlite_quick_check(destination_path)
        if restored_check != "ok":
            raise MemoryValidationError(
                f"restored memory database failed integrity check: {restored_check}"
            )
    except Exception:
        if replaced and rollback_path is not None and rollback_path.exists():
            _remove_sqlite_sidecars(destination_path)
            shutil.copyfile(rollback_path, destination_path)
        raise
    finally:
        if temporary.exists():
            temporary.unlink()

    payload = destination_path.read_bytes()
    return {
        "source": str(backup_path),
        "destination": str(destination_path),
        "preRestoreBackup": str(rollback_path) if rollback_path else None,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "quickCheck": restored_check,
        "restoredAtUtc": datetime.now(timezone.utc).isoformat(),
    }


def _camel_case(value: str) -> str:
    head, *tail = str(value).split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


__all__ = [
    "backup_sqlite_database",
    "restore_sqlite_database",
    "run_retention_cleanup",
    "sqlite_quick_check",
]
