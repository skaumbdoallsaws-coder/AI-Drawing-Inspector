"""Operational CLI for the Sage Memory Phase 1 single-host pilot."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_inspector.memory import (  # noqa: E402
    MemoryPrincipal,
    SqliteMemoryRepository,
    backup_sqlite_database,
    default_memory_db_path,
    restore_sqlite_database,
    run_retention_cleanup,
    sqlite_quick_check,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect and maintain the local Sage memory database."
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=default_memory_db_path(),
        help="Memory SQLite database path.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("health", help="Run repository and SQLite checks.")

    backup = commands.add_parser("backup", help="Create an online backup.")
    backup.add_argument("--destination", type=Path, required=True)

    verify = commands.add_parser("verify", help="Run SQLite quick_check.")
    verify.add_argument("--source", type=Path)

    restore = commands.add_parser(
        "restore",
        help="Restore a backup while the InspectorPro server is stopped.",
    )
    restore.add_argument("--source", type=Path, required=True)
    restore.add_argument("--pre-restore-backup", type=Path)
    restore.add_argument(
        "--confirm-replace",
        action="store_true",
        help="Required acknowledgement that the active database is replaced.",
    )

    retention = commands.add_parser(
        "retention", help="Delete expired conversation graphs in bounded batches."
    )
    retention.add_argument("--tenant", default="local")
    retention.add_argument("--user", default="local-user")
    retention.add_argument("--batch-size", type=int, default=100)
    retention.add_argument("--maximum-batches", type=int, default=100)
    retention.add_argument(
        "--before",
        help="UTC ISO-8601 cutoff; defaults to the current time.",
    )
    return parser


def _cutoff(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("--before must include a timezone")
    return parsed.astimezone(timezone.utc)


def _require_database(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"memory database does not exist: {resolved}")
    return resolved


def execute(args: argparse.Namespace) -> Dict[str, Any]:
    database = args.database.expanduser().resolve()
    if args.command == "verify":
        source = _require_database(args.source or database)
        return {"source": str(source), "quickCheck": sqlite_quick_check(source)}
    if args.command == "backup":
        return backup_sqlite_database(
            _require_database(database),
            args.destination,
        )
    if args.command == "restore":
        if not args.confirm_replace:
            raise ValueError("restore requires --confirm-replace")
        return restore_sqlite_database(
            _require_database(args.source),
            database,
            pre_restore_backup=args.pre_restore_backup,
        )

    database = _require_database(database)
    repository = SqliteMemoryRepository(database)
    try:
        if args.command == "health":
            health = repository.health()
            return {
                "healthy": health.healthy,
                "repository": asdict(health),
                "quickCheck": sqlite_quick_check(database),
            }
        if args.command == "retention":
            return run_retention_cleanup(
                repository,
                MemoryPrincipal(args.tenant, args.user),
                before=_cutoff(args.before),
                batch_size=args.batch_size,
                maximum_batches=args.maximum_batches,
            )
    finally:
        repository.close()
    raise ValueError(f"unsupported command: {args.command}")


def main() -> int:
    args = _parser().parse_args()
    try:
        result = execute(args)
    except Exception as exc:  # noqa: BLE001 -- CLI boundary
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": type(exc).__name__,
                    "message": str(exc),
                },
                ensure_ascii=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps({"status": "ok", **result}, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
