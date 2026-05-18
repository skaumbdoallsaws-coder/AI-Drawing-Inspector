"""
Async bridge client for the InspectorPro SOLIDWORKS add-in.

Wraps the four bridge HTTP endpoints (10A-10C, extended in bridge
Phase 5a to carry per-kind dispatch):
  GET  /status                — discover SW running + active doc
  POST /jobs/extract          — request an extraction; body may
                                include "kind": "drawing"|"part"|"assembly".
                                Bridge defaults missing kind to "drawing"
                                (BridgeKindNormaliser.Normalise).
  GET  /jobs/{id}             — poll job state; response carries the
                                canonical `kind` plus per-kind nullable
                                count fields (sheets/views for drawing,
                                features/activeConfiguration for part,
                                components/mates/activeConfiguration for
                                assembly).
  GET  /jobs/{id}/package     — download the .inspectorpkg.zip

Discovery: reads %LOCALAPPDATA%\\InspectorPro\\Bridge\\bridge.json,
verifies the recorded pid is still a live process, then connects to
the recorded port. The bridge listens on 127.0.0.1 only — there is no
remote / network access path.

This module is the API surface the FastAPI server uses; the
endpoint-level orchestration (POST /api/request-extraction and the
per-kind variants planned for Phase B) lives in server.py.
"""

from __future__ import annotations

import asyncio
import ctypes
import json
import os
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("inspectorpro.bridge")


# ── Job-state constants ────────────────────────────────────────────
# Wire form mirrors the BridgeServer JSON exactly (see
# InspectorPro.SolidWorksAddin.Bridge.Jobs.JobStateNames.ToWire).
JOB_STATE_AWAITING_APPROVAL = "awaiting-approval"
JOB_STATE_APPROVED          = "approved"
JOB_STATE_RUNNING           = "running"
JOB_STATE_DONE              = "done"
JOB_STATE_FAILED            = "failed"
JOB_STATE_DENIED            = "denied"

TERMINAL_STATES = frozenset({JOB_STATE_DONE, JOB_STATE_FAILED, JOB_STATE_DENIED})


# ── Kind constants (bridge Phase 5a) ───────────────────────────────
# Wire form mirrors BridgeKindNormaliser.SupportedKinds in the bridge
# repo. The bridge canonicalises (trim + lowercase + default to
# "drawing"); the client always sends already-canonical values, so
# there is no client-side normaliser. Validation of unsupported kinds
# is the bridge's responsibility — clients trust the bridge to 400 a
# bad value and surface the bridge's `error` + `supportedKinds` body
# unchanged so future bridge upgrades that add a new kind do not
# require an app release.
KIND_DRAWING  = "drawing"
KIND_PART     = "part"
KIND_ASSEMBLY = "assembly"
SUPPORTED_KINDS = (KIND_DRAWING, KIND_PART, KIND_ASSEMBLY)
DEFAULT_KIND    = KIND_DRAWING


# ── Errors ─────────────────────────────────────────────────────────

class BridgeUnavailableError(RuntimeError):
    """Bridge port file is missing, pid is dead, or /status is unreachable."""


class BridgeUnauthorizedError(RuntimeError):
    """Bridge rejected our token (HTTP 401) or no token file present.

    Raised when the add-in has Week-11 auth enabled and our request did
    not carry a valid bearer. The client maps this to a distinct UI
    state so the operator can fix the token rather than restart SW.
    """

    def __init__(self, message: str = "SOLIDWORKS bridge token is missing or invalid."):
        super().__init__(message)


class BridgeJobConflictError(RuntimeError):
    """Bridge returned 409 — another job is already in progress.

    Bridge Phase 5a.7 added the in-flight job's `kind` to the 409
    response body; this client surfaces it as a structured attribute
    so the orchestrator can render kind-aware messaging without
    re-parsing the bridge body. `kind` is empty string when the
    bridge omits it (e.g. a pre-Phase-5a bridge); never None.
    """

    def __init__(self, active_job_id: str, state: str, kind: str = ""):
        suffix = f", kind={kind}" if kind else ""
        super().__init__(f"another job in progress (jobId={active_job_id}{suffix}, state={state})")
        self.active_job_id = active_job_id
        self.state         = state
        self.kind          = kind


class BridgeBadResponseError(RuntimeError):
    """Bridge returned an unexpected status code or unparseable body."""

    def __init__(self, message: str, status_code: Optional[int] = None, body: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


# ── DTOs ───────────────────────────────────────────────────────────

@dataclass
class BridgeInfo:
    version: int
    port: int
    pid: int
    started_at: str  # ISO-8601 from bridge.json


@dataclass
class BridgeActiveDoc:
    type: str    # "Drawing" | "Part" | "Assembly" | "Unknown"
    title: str
    path: str

    @classmethod
    def from_json(cls, j: dict) -> Optional["BridgeActiveDoc"]:
        if not j:
            return None
        return cls(type=j.get("type", ""), title=j.get("title", ""), path=j.get("path", ""))


@dataclass
class BridgeStatus:
    bridge_version: int
    sw_process_id: int
    sw_running: bool
    active_doc: Optional[BridgeActiveDoc] = None
    # Week 11 auth surface (added by the bridge in the dual-mode /status
    # response). Older bridge versions omit these — we default to
    # auth_required=False so legacy bridges keep working unchanged.
    auth_required: bool = False
    authenticated: bool = True

    @classmethod
    def from_json(cls, j: dict) -> "BridgeStatus":
        auth_required = bool(j.get("authRequired", False))
        # When the Week-11 bridge returns its minimal (unauthenticated)
        # body, it includes authRequired=true but OMITS `authenticated`.
        # Treat the missing field as "not authenticated" in that case so
        # the orchestration takes the 401 fast-fail path instead of
        # falling through to "no active doc" (which is misleading — the
        # active doc IS open in SW, the bridge just refused to surface
        # it without a valid token).
        if auth_required:
            authenticated = bool(j.get("authenticated", False))
        else:
            # Legacy bridge with no auth — implicitly authenticated.
            authenticated = bool(j.get("authenticated", True))
        return cls(
            bridge_version=int(j.get("bridgeVersion", 0)),
            sw_process_id=int(j.get("swProcessId", 0)),
            sw_running=bool(j.get("swRunning", False)),
            active_doc=BridgeActiveDoc.from_json(j.get("activeDoc")),
            auth_required=auth_required,
            authenticated=authenticated,
        )


@dataclass
class JobCreateResult:
    job_id: str
    state: str
    # Bridge Phase 5a.2 added `kind` to the POST /jobs/extract 200 OK
    # body. Defensive `j.get("kind", DEFAULT_KIND)` keeps this client
    # parsing a pre-Phase-5a bridge without crashing.
    kind: str = DEFAULT_KIND

    @classmethod
    def from_json(cls, j: dict) -> "JobCreateResult":
        return cls(
            job_id=str(j["jobId"]),
            state=str(j["state"]),
            kind=str(j.get("kind", DEFAULT_KIND)),
        )


@dataclass
class JobSnapshot:
    """GET /jobs/{id} response — superset of all fields the bridge may
    populate. None for any field the bridge omitted.

    Bridge Phase 5a.2 added `kind` plus per-kind nullable count fields:
      drawing  → sheet_count, view_count
      part     → feature_count, active_configuration
      assembly → component_count, mate_count, active_configuration
    Fields are None when not applicable (e.g. feature_count is None on
    a drawing snapshot). A pre-Phase-5a bridge omits `kind` entirely;
    `j.get("kind", DEFAULT_KIND)` keeps this client compatible.
    """

    job_id: str
    state: str
    kind: str = DEFAULT_KIND
    package_id: Optional[str] = None
    package_folder: Optional[str] = None
    sheet_count:           Optional[int] = None  # drawing
    view_count:            Optional[int] = None  # drawing
    feature_count:         Optional[int] = None  # part
    component_count:       Optional[int] = None  # assembly
    mate_count:            Optional[int] = None  # assembly
    active_configuration:  Optional[str] = None  # part / assembly
    error: Optional[str] = None
    package_available: bool = False
    package_url: Optional[str] = None

    @classmethod
    def from_json(cls, j: dict) -> "JobSnapshot":
        return cls(
            job_id=str(j["jobId"]),
            state=str(j["state"]),
            kind=str(j.get("kind", DEFAULT_KIND)),
            package_id=j.get("packageId"),
            package_folder=j.get("packageFolder"),
            sheet_count=j.get("sheetCount"),
            view_count=j.get("viewCount"),
            feature_count=j.get("featureCount"),
            component_count=j.get("componentCount"),
            mate_count=j.get("mateCount"),
            active_configuration=j.get("activeConfiguration"),
            error=j.get("error"),
            package_available=bool(j.get("packageAvailable", False)),
            package_url=j.get("packageUrl"),
        )

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES


# ── Discovery ──────────────────────────────────────────────────────

def _bridge_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        # Non-Windows or missing env. Bridge is Windows-only by design.
        return Path("/dev/null")
    return Path(base) / "InspectorPro" / "Bridge"


def _bridge_port_file() -> Path:
    return _bridge_dir() / "bridge.json"


def _bridge_token_file() -> Path:
    return _bridge_dir() / "bridge_token"


def _read_bridge_token() -> Optional[str]:
    """Read the local bearer token written by the add-in on bridge
    start. Returns None when the file is missing or unreadable; the
    caller decides whether to attempt auth or surface "auth missing"
    to the UI. Never logs the token contents."""
    path = _bridge_token_file()
    try:
        if not path.exists():
            return None
        raw = path.read_text(encoding="utf-8-sig").strip()
        return raw or None
    except Exception as ex:
        logger.debug("bridge token unreadable: %s", ex)
        return None


def _is_pid_alive_windows(pid: int) -> bool:
    """Best-effort liveness check for a Windows pid via OpenProcess +
    GetExitCodeProcess. Defense-in-depth on top of the HTTP probe so we
    do not connect to a *different* process that grabbed the port after
    SOLIDWORKS crashed without removing bridge.json."""
    if pid <= 0:
        return False
    if os.name != "nt":
        return False
    try:
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong(0)
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            STILL_ACTIVE = 259
            return bool(ok) and exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    except Exception as ex:
        logger.debug("pid liveness check failed for pid=%s: %s", pid, ex)
        return False


# ── Client ─────────────────────────────────────────────────────────

class BridgeClient:
    """Async client over the localhost bridge. Construct freely (no
    persistent state); the client uses an ephemeral httpx.AsyncClient
    per request to keep things simple — bridge calls are infrequent."""

    DEFAULT_STATUS_TIMEOUT_S = 5.0
    DEFAULT_POST_TIMEOUT_S   = 10.0
    DEFAULT_GET_TIMEOUT_S    = 5.0
    DEFAULT_DOWNLOAD_TIMEOUT_S = 60.0
    DEFAULT_POLL_INTERVAL_S  = 1.0

    def __init__(self, port_file: Optional[Path] = None) -> None:
        self._port_file = port_file or _bridge_port_file()

    # ── Auth ───────────────────────────────────────────────────────
    def _auth_headers(self) -> Dict[str, str]:
        """Return a headers dict with the bearer token (if any) ready
        to merge into httpx calls. Empty dict if no token on disk."""
        token = _read_bridge_token()
        return {"Authorization": f"Bearer {token}"} if token else {}

    # ── Discovery ──────────────────────────────────────────────────
    def discover(self) -> Optional[BridgeInfo]:
        """Read bridge.json + verify pid liveness. Returns None on any
        failure (file missing, malformed, dead pid). Never raises."""
        try:
            if not self._port_file.exists():
                return None
            raw = self._port_file.read_text(encoding="utf-8-sig")
            data = json.loads(raw)
        except Exception as ex:
            logger.debug("bridge port file unreadable: %s", ex)
            return None

        try:
            version = int(data.get("version", 0))
            port    = int(data.get("port", 0))
            pid     = int(data.get("pid", 0))
            started = str(data.get("startedAt", ""))
        except Exception:
            return None
        if port <= 0 or pid <= 0:
            return None
        if not _is_pid_alive_windows(pid):
            logger.debug("bridge pid %d is not alive (stale port file)", pid)
            return None
        return BridgeInfo(version=version, port=port, pid=pid, started_at=started)

    # ── /status ────────────────────────────────────────────────────
    async def status(self) -> Optional[BridgeStatus]:
        """Returns the bridge status, or None when bridge is unavailable.

        Sends the bearer token if we have one so the bridge returns the
        full body. If the bridge is in Week-11 auth mode and we have no
        token (or a wrong one), the bridge still returns 200 with the
        minimal body — the result's `auth_required` / `authenticated`
        flags let the caller distinguish "bridge up, need token" from
        "bridge up and authenticated".
        """
        info = self.discover()
        if info is None:
            return None
        url = f"http://127.0.0.1:{info.port}/status"
        try:
            async with httpx.AsyncClient(timeout=self.DEFAULT_STATUS_TIMEOUT_S) as http:
                resp = await http.get(url, headers=self._auth_headers())
                resp.raise_for_status()
                return BridgeStatus.from_json(resp.json())
        except Exception as ex:
            logger.debug("bridge /status failed: %s", ex)
            return None

    # ── POST /jobs/extract ─────────────────────────────────────────
    async def request_extraction(
        self,
        part_number: Optional[str] = None,
        expected_doc_path: Optional[str] = None,
        *,
        kind: Optional[str] = None,
    ) -> JobCreateResult:
        """Create an extraction job. Raises BridgeUnavailableError,
        BridgeJobConflictError, or BridgeBadResponseError.

        `kind` is bridge Phase 5a's per-kind dispatch selector: one of
        KIND_DRAWING / KIND_PART / KIND_ASSEMBLY (or None to let the
        bridge default to drawing). Keyword-only so the existing
        positional callers (request_extraction(pn, expected_path))
        keep working byte-equivalent — only new code that wants
        non-drawing kinds needs to opt in.

        The client does NOT validate `kind` against SUPPORTED_KINDS;
        the bridge owns the canonical accepted set and 400s an
        unsupported value with a structured `supportedKinds` body the
        caller can surface verbatim. This keeps the client compatible
        with future bridge upgrades that add new kinds without an app
        release.
        """
        info = self.discover()
        if info is None:
            raise BridgeUnavailableError("bridge port file missing or stale")

        body: dict = {}
        if kind is not None:
            body["kind"] = kind
        if part_number:
            body["partNumber"] = part_number
        if expected_doc_path:
            body["expectedDocPath"] = expected_doc_path

        url = f"http://127.0.0.1:{info.port}/jobs/extract"
        try:
            async with httpx.AsyncClient(timeout=self.DEFAULT_POST_TIMEOUT_S) as http:
                resp = await http.post(url, json=body, headers=self._auth_headers())
        except Exception as ex:
            raise BridgeUnavailableError(f"POST /jobs/extract failed: {ex}") from ex

        if resp.status_code == 401:
            raise BridgeUnauthorizedError()
        if resp.status_code == 200:
            try:
                return JobCreateResult.from_json(resp.json())
            except Exception as ex:
                raise BridgeBadResponseError(
                    f"bridge returned 200 with unparseable body: {ex}",
                    status_code=200, body=resp.text)

        if resp.status_code == 409:
            try:
                j = resp.json()
                raise BridgeJobConflictError(
                    active_job_id=str(j.get("activeJobId", "")),
                    state=str(j.get("state", "")),
                    kind=str(j.get("kind", "")))    # bridge Phase 5a.7
            except BridgeJobConflictError:
                raise
            except Exception as ex:
                raise BridgeBadResponseError(
                    f"bridge returned 409 with unparseable body: {ex}",
                    status_code=409, body=resp.text)

        # 400 (precondition: kind-mismatch / no active doc / unsupported
        # kind), 500, others. The body carries the bridge's tightened
        # wording (see bridge plan §6); orchestrator surfaces it raw.
        raise BridgeBadResponseError(
            f"bridge POST /jobs/extract returned HTTP {resp.status_code}",
            status_code=resp.status_code, body=resp.text)

    # ── GET /jobs/{id} ─────────────────────────────────────────────
    async def get_job(self, job_id: str) -> Optional[JobSnapshot]:
        """Returns the current job snapshot, or None if 404 / bridge gone.

        Raises BridgeUnauthorizedError on 401 so the orchestrator can
        stop polling immediately instead of looping until timeout."""
        info = self.discover()
        if info is None:
            return None
        url = f"http://127.0.0.1:{info.port}/jobs/{job_id}"
        try:
            async with httpx.AsyncClient(timeout=self.DEFAULT_GET_TIMEOUT_S) as http:
                resp = await http.get(url, headers=self._auth_headers())
        except Exception as ex:
            logger.debug("bridge GET /jobs/%s failed: %s", job_id, ex)
            return None
        if resp.status_code == 401:
            raise BridgeUnauthorizedError()
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise BridgeBadResponseError(
                f"bridge GET /jobs/{job_id} returned HTTP {resp.status_code}",
                status_code=resp.status_code, body=resp.text)
        try:
            return JobSnapshot.from_json(resp.json())
        except Exception as ex:
            raise BridgeBadResponseError(
                f"bridge GET /jobs/{job_id} unparseable body: {ex}",
                status_code=200, body=resp.text)

    # ── Poll until terminal ────────────────────────────────────────
    async def wait_for_terminal(
        self,
        job_id: str,
        *,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        timeout_s: float = 600.0,
        on_state_change=None,
    ) -> JobSnapshot:
        """Poll GET /jobs/{id} at poll_interval_s until state is terminal
        or timeout_s elapses. Raises asyncio.TimeoutError on hard timeout
        (so the caller can map it to HTTP 504).

        `on_state_change` (optional) is a callable(old_state, new_state)
        invoked whenever the polled state changes. Used by the Phase 3
        telemetry instrumentation in server.py to split bridge-extraction
        time into approval-wait (state transition out of
        "awaiting-approval") vs extract-wait (transition into terminal).
        Callback exceptions are caught + logged so a callback bug never
        breaks the poll loop."""

        async def _poll():
            last_state = None
            while True:
                snap = await self.get_job(job_id)
                if snap is None:
                    raise BridgeUnavailableError(
                        f"job {job_id} vanished from bridge mid-flight (404)")
                if snap.state != last_state:
                    if on_state_change is not None:
                        try:
                            on_state_change(last_state, snap.state)
                        except Exception as cb_ex:  # noqa: BLE001
                            logger.debug(
                                "bridge on_state_change callback raised "
                                "(swallowed): %s", cb_ex)
                    last_state = snap.state
                if snap.is_terminal:
                    return snap
                await asyncio.sleep(poll_interval_s)

        return await asyncio.wait_for(_poll(), timeout=timeout_s)

    # ── GET /jobs/{id}/package ─────────────────────────────────────
    async def download_package(self, job_id: str, dest_zip_path: Path) -> int:
        """Streams the package zip to dest_zip_path. Returns bytes
        written. Raises BridgeBadResponseError on non-200, or
        BridgeUnavailableError on transport failure."""
        info = self.discover()
        if info is None:
            raise BridgeUnavailableError("bridge port file missing or stale")

        url = f"http://127.0.0.1:{info.port}/jobs/{job_id}/package"
        dest_zip_path.parent.mkdir(parents=True, exist_ok=True)
        # Write to .partial then rename so a partial write never leaves
        # a half-truncated zip at the final path.
        partial = dest_zip_path.with_suffix(dest_zip_path.suffix + ".partial")
        bytes_written = 0
        try:
            async with httpx.AsyncClient(timeout=self.DEFAULT_DOWNLOAD_TIMEOUT_S) as http:
                async with http.stream("GET", url, headers=self._auth_headers()) as resp:
                    if resp.status_code == 401:
                        raise BridgeUnauthorizedError()
                    if resp.status_code != 200:
                        body = await resp.aread()
                        raise BridgeBadResponseError(
                            f"bridge GET /jobs/{job_id}/package returned HTTP {resp.status_code}",
                            status_code=resp.status_code, body=body.decode("utf-8", errors="replace"))
                    with partial.open("wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                            f.write(chunk)
                            bytes_written += len(chunk)
        except BridgeUnauthorizedError:
            try: partial.unlink(missing_ok=True)
            except Exception: pass
            raise
        except BridgeBadResponseError:
            try: partial.unlink(missing_ok=True)
            except Exception: pass
            raise
        except Exception as ex:
            try: partial.unlink(missing_ok=True)
            except Exception: pass
            raise BridgeUnavailableError(
                f"bridge download failed: {ex}") from ex

        os.replace(partial, dest_zip_path)
        return bytes_written
