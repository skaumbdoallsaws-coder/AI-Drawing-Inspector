"""Bounded cancellable execution for authoritative Facility Layout geometry."""

from __future__ import annotations

from concurrent.futures import (
    Future,
    ThreadPoolExecutor,
    TimeoutError as FuturesTimeoutError,
)
from dataclasses import dataclass
from threading import BoundedSemaphore, Event, Lock
from typing import Any, Callable, Mapping

from .errors import FacilityValidationError
from .spatial import diagnose_layout, generate_placement_candidates


class SpatialExecutionCancelled(FacilityValidationError):
    """Raised when an authoritative spatial job is cancelled."""

    def __init__(self) -> None:
        super().__init__(
            "spatial_execution_cancelled",
            "Facility Layout spatial execution was cancelled.",
        )


class SpatialCancellationToken:
    """Thread-safe cooperative cancellation token."""

    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self.cancelled:
            raise SpatialExecutionCancelled()


@dataclass(frozen=True)
class SpatialJob:
    """One cancellable submitted spatial job."""

    job_id: str
    token: SpatialCancellationToken
    future: Future[dict[str, Any]]

    def cancel(self) -> bool:
        self.token.cancel()
        self.future.cancel()
        return True

    def result(self, timeout: float | None = None) -> dict[str, Any]:
        try:
            return self.future.result(timeout=timeout)
        except FuturesTimeoutError as exc:
            self.cancel()
            raise FacilityValidationError(
                "spatial_execution_timeout",
                "Facility Layout spatial execution exceeded its time limit.",
                details={"jobId": self.job_id},
            ) from exc
        except SpatialExecutionCancelled:
            raise
        except Exception:
            if self.token.cancelled:
                raise SpatialExecutionCancelled()
            raise


class FacilitySpatialExecutor:
    """Run exact diagnostics and candidate generation off the request thread."""

    def __init__(
        self,
        *,
        maximum_workers: int = 2,
        maximum_pending_jobs: int = 16,
        timeout_seconds: float = 5.0,
        diagnose: Callable[..., dict[str, Any]] = diagnose_layout,
        generate: Callable[..., dict[str, Any]] = generate_placement_candidates,
    ) -> None:
        if (
            isinstance(maximum_workers, bool)
            or not isinstance(maximum_workers, int)
            or maximum_workers < 1
            or maximum_workers > 8
        ):
            raise ValueError("maximum_workers must be between 1 and 8")
        if (
            isinstance(maximum_pending_jobs, bool)
            or not isinstance(maximum_pending_jobs, int)
            or maximum_pending_jobs < maximum_workers
            or maximum_pending_jobs > 256
        ):
            raise ValueError(
                "maximum_pending_jobs must be between maximum_workers and 256"
            )
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or timeout_seconds <= 0
            or timeout_seconds > 300
        ):
            raise ValueError("timeout_seconds must be between 0 and 300")
        self._pool = ThreadPoolExecutor(
            max_workers=maximum_workers,
            thread_name_prefix="facility-spatial",
        )
        self._diagnose = diagnose
        self._generate = generate
        self._pending = BoundedSemaphore(maximum_pending_jobs)
        self._timeout_seconds = float(timeout_seconds)
        self._lock = Lock()
        self._counter = 0
        self._closed = False

    def _next_id(self) -> str:
        with self._lock:
            if self._closed:
                raise RuntimeError("FacilitySpatialExecutor is closed")
            self._counter += 1
            return f"spatial-job-{self._counter:08d}"

    def _submit(
        self,
        operation: Callable[..., dict[str, Any]],
        args: tuple[Any, ...],
        kwargs: Mapping[str, Any],
    ) -> SpatialJob:
        job_id = self._next_id()
        if not self._pending.acquire(blocking=False):
            raise FacilityValidationError(
                "spatial_execution_overloaded",
                "Facility Layout spatial execution capacity is exhausted.",
                details={"maximumPendingJobsReached": True},
            )
        token = SpatialCancellationToken()

        def execute() -> dict[str, Any]:
            token.check()
            result = operation(
                *args,
                **dict(kwargs),
                cancel_check=token.check,
            )
            token.check()
            return result

        try:
            future = self._pool.submit(execute)
        except Exception:
            self._pending.release()
            raise
        future.add_done_callback(lambda _: self._pending.release())
        return SpatialJob(job_id=job_id, token=token, future=future)

    def submit_diagnostics(
        self,
        layout: Mapping[str, Any],
        asset_definitions: Mapping[str, Any],
        **kwargs: Any,
    ) -> SpatialJob:
        return self._submit(
            self._diagnose,
            (layout, asset_definitions),
            kwargs,
        )

    def submit_candidates(
        self,
        layout: Mapping[str, Any],
        asset_definition: Mapping[str, Any],
        requested_position: Mapping[str, Any],
        asset_definitions: Mapping[str, Any],
        **kwargs: Any,
    ) -> SpatialJob:
        return self._submit(
            self._generate,
            (
                layout,
                asset_definition,
                requested_position,
                asset_definitions,
            ),
            kwargs,
        )

    def run_diagnostics(
        self,
        layout: Mapping[str, Any],
        asset_definitions: Mapping[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self.submit_diagnostics(
            layout,
            asset_definitions,
            **kwargs,
        ).result(timeout=self._timeout_seconds)

    def run_candidates(
        self,
        layout: Mapping[str, Any],
        asset_definition: Mapping[str, Any],
        requested_position: Mapping[str, Any],
        asset_definitions: Mapping[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self.submit_candidates(
            layout,
            asset_definition,
            requested_position,
            asset_definitions,
            **kwargs,
        ).result(timeout=self._timeout_seconds)

    def close(self, *, wait: bool = True) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._pool.shutdown(wait=wait, cancel_futures=True)


__all__ = [
    "FacilitySpatialExecutor",
    "SpatialCancellationToken",
    "SpatialExecutionCancelled",
    "SpatialJob",
]
