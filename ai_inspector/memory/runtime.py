"""Runtime configuration and ownership for the Phase 1 memory repository."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Optional

from .continuity import ContinuityConfig, ContinuityService
from .repository import MemoryValidationError
from .sqlite_repository import SqliteMemoryRepository, default_memory_db_path
from .summary_provider import (
    ConfiguredContinuitySummaryProvider,
    ContinuitySummaryProvider,
    SummaryProviderConfig,
)
from .turn_lifecycle import TurnLifecycleService


MEMORY_MODES = frozenset({"off", "shadow", "compare", "enforce"})


def memory_mode_from_environment(
    environ: Optional[Mapping[str, str]] = None,
) -> str:
    values = os.environ if environ is None else environ
    mode = str(values.get("INSPECTORPRO_MEMORY_V1_MODE") or "off").strip().lower()
    if mode not in MEMORY_MODES:
        raise MemoryValidationError(
            "INSPECTORPRO_MEMORY_V1_MODE must be off, shadow, compare, or enforce"
        )
    return mode


@dataclass(frozen=True)
class MemoryRuntimeConfig:
    mode: str
    database_path: Path
    stale_pending_seconds: float
    conversation_retention_days: int
    workflow_ttl_seconds: float
    referent_ttl_seconds: float
    retention_cleanup_batch_size: int
    continuity: ContinuityConfig
    summary_provider: SummaryProviderConfig

    @classmethod
    def from_environment(
        cls, environ: Optional[Mapping[str, str]] = None
    ) -> "MemoryRuntimeConfig":
        values = os.environ if environ is None else environ
        mode = memory_mode_from_environment(values)
        raw_stale = str(
            values.get("INSPECTORPRO_MEMORY_PENDING_TURN_STALE_SECONDS") or "900"
        ).strip()
        try:
            stale_seconds = float(raw_stale)
        except ValueError as exc:
            raise MemoryValidationError(
                "INSPECTORPRO_MEMORY_PENDING_TURN_STALE_SECONDS must be numeric"
            ) from exc
        if not 1.0 <= stale_seconds <= 86400.0:
            raise MemoryValidationError(
                "INSPECTORPRO_MEMORY_PENDING_TURN_STALE_SECONDS must be 1-86400"
            )
        conversation_retention_days = _bounded_int(
            values,
            "INSPECTORPRO_MEMORY_CONVERSATION_RETENTION_DAYS",
            30,
            minimum=1,
            maximum=3650,
        )
        workflow_ttl_seconds = _bounded_float(
            values,
            "INSPECTORPRO_MEMORY_WORKFLOW_TTL_SECONDS",
            86400.0,
            minimum=60.0,
            maximum=2592000.0,
        )
        referent_ttl_seconds = _bounded_float(
            values,
            "INSPECTORPRO_MEMORY_REFERENT_TTL_SECONDS",
            1800.0,
            minimum=60.0,
            maximum=86400.0,
        )
        retention_cleanup_batch_size = _bounded_int(
            values,
            "INSPECTORPRO_MEMORY_RETENTION_CLEANUP_BATCH_SIZE",
            100,
            minimum=1,
            maximum=5000,
        )
        continuity = ContinuityConfig.from_environment(values)
        return cls(
            mode=mode,
            database_path=default_memory_db_path(values),
            stale_pending_seconds=stale_seconds,
            conversation_retention_days=conversation_retention_days,
            workflow_ttl_seconds=workflow_ttl_seconds,
            referent_ttl_seconds=referent_ttl_seconds,
            retention_cleanup_batch_size=retention_cleanup_batch_size,
            continuity=continuity,
            summary_provider=SummaryProviderConfig.from_environment(
                values,
                maximum_output_tokens=continuity.summary_max_tokens,
                request_timeout_seconds=(
                    continuity.sync_refresh_timeout_seconds
                ),
            ),
        )

    @property
    def cache_key(self) -> tuple[object, ...]:
        return (
            self.mode,
            str(self.database_path.resolve()),
            self.stale_pending_seconds,
            self.conversation_retention_days,
            self.workflow_ttl_seconds,
            self.referent_ttl_seconds,
            self.retention_cleanup_batch_size,
            self.continuity,
            self.summary_provider,
        )


class MemoryRuntime:
    def __init__(
        self,
        config: MemoryRuntimeConfig,
        *,
        summary_provider: Optional[ContinuitySummaryProvider] = None,
    ) -> None:
        self.config = config
        self.repository = SqliteMemoryRepository(config.database_path)
        self.lifecycle = (
            TurnLifecycleService(
                self.repository,
                mode=config.mode,
                stale_pending_seconds=config.stale_pending_seconds,
                conversation_retention_seconds=(
                    config.conversation_retention_days * 86400.0
                ),
                workflow_ttl_seconds=config.workflow_ttl_seconds,
            )
            if config.mode != "off"
            else None
        )
        self.continuity = (
            ContinuityService(
                self.repository,
                summary_provider
                or ConfiguredContinuitySummaryProvider(config.summary_provider),
                config=config.continuity,
                telemetry_mode=config.mode,
            )
            if config.mode != "off"
            else None
        )

    @property
    def mode(self) -> str:
        return self.config.mode

    def conversation_retention_until(self) -> datetime:
        return datetime.now(timezone.utc) + timedelta(
            days=self.config.conversation_retention_days
        )

    def close(self) -> None:
        if self.continuity is not None:
            self.continuity.cancel_pending_tasks()
        self.repository.close()


def _bounded_int(
    values: Mapping[str, str],
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw = str(values.get(name) or str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise MemoryValidationError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise MemoryValidationError(
            f"{name} must be {minimum}-{maximum}"
        )
    return value


def _bounded_float(
    values: Mapping[str, str],
    name: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    raw = str(values.get(name) or str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise MemoryValidationError(f"{name} must be numeric") from exc
    if not minimum <= value <= maximum:
        raise MemoryValidationError(
            f"{name} must be {minimum:g}-{maximum:g}"
        )
    return value


__all__ = [
    "MEMORY_MODES",
    "MemoryRuntime",
    "MemoryRuntimeConfig",
    "memory_mode_from_environment",
]
