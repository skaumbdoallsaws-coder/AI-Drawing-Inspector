"""SQLite-backed telemetry storage.

Per docs/usage-cost-dashboard-plan.md §6:
- Local and simple.
- Safer than scattered JSON logs.
- Queryable for charts.
- No new external service required for pilot.

Path: `runtime_metrics/inspectorpro_metrics.sqlite` by default. Override
with the INSPECTORPRO_METRICS_DB env var.

This module's `write()` MAY raise on failure — soft-fail wrapping happens
in `instrumentation.record_event()` so test code can still observe the
exception when explicitly looking for it.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import List, Optional

from .models import TelemetryEvent

# Bump SCHEMA_VERSION when SCHEMA_SQL changes in a non-additive way.
# Additive column-only changes can keep the previous version — `_apply_migrations`
# below catches up databases created at an older version by ALTERing missing
# columns onto an existing table (CREATE TABLE IF NOT EXISTS does not).
#
# v2 (Phase 3) — added httpStatus + stage columns (additive).
SCHEMA_VERSION = 3

# SCHEMA_SQL handles the fresh-DB case (CREATE TABLE IF NOT EXISTS) and
# indexes that reference columns present since the original Phase 1
# schema. Indexes that reference columns added later live in
# _POST_MIGRATION_INDEXES so they fire AFTER _apply_migrations has
# ALTERed the missing columns onto legacy tables.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS telemetry_events (
    eventId TEXT PRIMARY KEY,
    timestampUtc TEXT NOT NULL,
    environment TEXT,
    sessionId TEXT,
    requestId TEXT,
    route TEXT,
    workflow TEXT,
    agentType TEXT,
    provider TEXT,
    model TEXT,
    status TEXT,
    errorType TEXT,
    inputTokens INTEGER NOT NULL DEFAULT 0,
    outputTokens INTEGER NOT NULL DEFAULT 0,
    cacheReadTokens INTEGER NOT NULL DEFAULT 0,
    cacheWriteTokens INTEGER NOT NULL DEFAULT 0,
    totalTokens INTEGER NOT NULL DEFAULT 0,
    estimatedCostUsd REAL NOT NULL DEFAULT 0.0,
    pricingConfidence TEXT,
    latencyMs REAL NOT NULL DEFAULT 0.0,
    firstTokenLatencyMs REAL,
    firstCleanSentenceMs REAL,
    streamDurationMs REAL,
    pipelineLatencyMs REAL,
    finalizeDeltaChars INTEGER,
    retryCount INTEGER NOT NULL DEFAULT 0,
    toolCallCount INTEGER NOT NULL DEFAULT 0,
    partNumber TEXT,
    documentKind TEXT,
    httpStatus INTEGER,
    stage TEXT
);

CREATE INDEX IF NOT EXISTS idx_telemetry_timestamp ON telemetry_events (timestampUtc);
CREATE INDEX IF NOT EXISTS idx_telemetry_workflow  ON telemetry_events (workflow);
CREATE INDEX IF NOT EXISTS idx_telemetry_model     ON telemetry_events (model);
CREATE INDEX IF NOT EXISTS idx_telemetry_route     ON telemetry_events (route);

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Indexes that reference columns added in a later schema version. Each
# entry is (sql_create_statement, column_required) — the migration
# runner skips entries whose column is still missing post-ALTER (defensive
# — should not happen since _ADDITIVE_COLUMNS would have just added it).
_POST_MIGRATION_INDEXES = [
    ("CREATE INDEX IF NOT EXISTS idx_telemetry_stage ON telemetry_events (stage)",
     "stage"),  # depends on v2 column
]

# Columns added by additive migrations. Each entry is (column_name, sql_type).
# Order is "added in version N" — the migration runner ALTERs the table to
# add anything that's missing, regardless of which old version produced the
# pre-existing DB.
_ADDITIVE_COLUMNS = [
    ("httpStatus", "INTEGER"),  # added v2
    ("stage",      "TEXT"),     # added v2
    ("firstTokenLatencyMs",  "REAL"),     # added v3
    ("firstCleanSentenceMs", "REAL"),     # added v3
    ("streamDurationMs",     "REAL"),     # added v3
    ("pipelineLatencyMs",    "REAL"),     # added v3
    ("finalizeDeltaChars",   "INTEGER"),  # added v3
]

# Path convention (§6 of the plan). Override at runtime with the env var.
DEFAULT_DB_PATH = Path("runtime_metrics") / "inspectorpro_metrics.sqlite"
ENV_VAR = "INSPECTORPRO_METRICS_DB"


def default_db_path() -> Path:
    """Resolve the SQLite path the default store will use.

    Honors the INSPECTORPRO_METRICS_DB env var when set. Returns a
    Path object — relative paths are resolved against the process's
    current working directory at write time (not at import time), so
    a test fixture can chdir before the first write and still hit
    the right file.
    """
    override = os.environ.get(ENV_VAR)
    if override:
        return Path(override)
    return DEFAULT_DB_PATH


class TelemetryStore:
    """SQLite store for telemetry events.

    One Connection per write() call — simple, robust against the
    process being multi-threaded, no shared cursor state to corrupt.
    A module-level lock serializes writes to a single store instance
    so two threads cannot race the schema-init step.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path: Path = Path(db_path) if db_path else default_db_path()
        self._lock = threading.Lock()
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Lazy schema init. Runs on first write/query; deferred so
        the default store can be constructed without touching the
        filesystem (and so import order does not matter)."""
        if self._initialized:
            return
        # Create parent dir BEFORE attempting to connect — sqlite3
        # otherwise raises an OperationalError for missing dirs.
        parent = self.db_path.parent
        if str(parent) and parent != Path("."):
            parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
            # CREATE TABLE IF NOT EXISTS no-ops against an existing table,
            # so additive columns added in later versions must be ALTERed
            # in via _apply_migrations. Idempotent — uses PRAGMA table_info
            # to skip columns that already exist.
            self._apply_migrations(conn)
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            conn.commit()
        self._initialized = True

    @staticmethod
    def _apply_migrations(conn: sqlite3.Connection) -> None:
        """Add additive columns + post-migration indexes missing from
        older schema versions. Safe to run on a fresh DB — the columns
        added by SCHEMA_SQL already exist, so each ADD COLUMN is
        skipped; post-migration indexes use IF NOT EXISTS."""
        cursor = conn.execute("PRAGMA table_info(telemetry_events)")
        existing = {row[1] for row in cursor.fetchall()}
        for col_name, col_type in _ADDITIVE_COLUMNS:
            if col_name not in existing:
                conn.execute(
                    f"ALTER TABLE telemetry_events ADD COLUMN {col_name} {col_type}"
                )
                existing.add(col_name)
        for create_sql, required_col in _POST_MIGRATION_INDEXES:
            if required_col in existing:
                conn.execute(create_sql)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        # WAL mode lets a dashboard read concurrently with writes.
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            # Some filesystems (e.g. network mounts) reject WAL. Fall
            # back silently to the default rollback journal — telemetry
            # still works, just without the concurrent-reader benefit.
            pass
        return conn

    def write(self, event: TelemetryEvent) -> None:
        """Insert a single event. Raises on failure — soft-fail wrapping
        belongs to instrumentation.record_event() so unit tests that
        explicitly want to verify the failure path can still see the
        exception by calling write() directly."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                d = event.to_dict()
                cols = list(d.keys())
                placeholders = ",".join("?" * len(cols))
                sql = (
                    f"INSERT OR IGNORE INTO telemetry_events ({','.join(cols)}) "
                    f"VALUES ({placeholders})"
                )
                conn.execute(sql, [d[c] for c in cols])
                conn.commit()

    def query_recent(self, limit: int = 100) -> List[TelemetryEvent]:
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT * FROM telemetry_events ORDER BY timestampUtc DESC LIMIT ?",
                    (int(limit),),
                )
                return [TelemetryEvent.from_dict(dict(row)) for row in cursor.fetchall()]

    def count(self) -> int:
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM telemetry_events")
                return int(cursor.fetchone()[0])

    def schema_version(self) -> Optional[int]:
        """Return the stored schema_meta version, or None if uninitialized."""
        with self._lock:
            if not self._initialized:
                # Don't trigger init just to read the version.
                if not self.db_path.exists():
                    return None
            self._ensure_initialized()
            with self._connect() as conn:
                cursor = conn.execute(
                    "SELECT value FROM schema_meta WHERE key = ?",
                    ("schema_version",),
                )
                row = cursor.fetchone()
                return int(row[0]) if row else None

    def close(self) -> None:
        """Truncate WAL/SHM sibling files so the DB file can be cleanly
        deleted by external code (e.g. pytest tmp_path teardown on
        Windows, where lingering -wal/-shm handles can cause
        PermissionError during rmtree). Safe to call multiple times."""
        if not self._initialized or not self.db_path.exists():
            return
        try:
            with self._connect() as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            # Best-effort — if the checkpoint fails, the tests will
            # still observe the lock error and we'll learn about it.
            pass
