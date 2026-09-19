"""Isolated live server support for parts-manual browser proofs."""

from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen


class IsolatedPartsManualServer:
    """Run the real app with a temporary parts-manual repository."""

    def __init__(self, root: Path, output_dir: Path, assembly_number: str) -> None:
        self.root = root.resolve()
        self.output_dir = output_dir.resolve()
        self.assembly_number = assembly_number
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._log_handle = None
        self.app_url = ""
        self.store_root: Path | None = None

    @property
    def plan_path(self) -> Path:
        if self.store_root is None:
            raise RuntimeError("isolated server has not been started")
        return self.store_root / self.assembly_number / "manual-plan.json"

    def start(self) -> "IsolatedPartsManualServer":
        if self._process is not None:
            return self
        runtime_root = self.root / ".runtime"
        runtime_root.mkdir(parents=True, exist_ok=True)
        self._temporary = tempfile.TemporaryDirectory(
            prefix="parts-manual-browser-proof-",
            dir=str(runtime_root),
            ignore_cleanup_errors=True,
        )
        self.store_root = Path(self._temporary.name) / "store"
        self.store_root.mkdir(parents=True, exist_ok=True)

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = int(probe.getsockname()[1])
        self.app_url = f"http://127.0.0.1:{port}"

        self.output_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.output_dir / "isolated_server.log"
        self._log_handle = log_path.open("wb")
        environment = os.environ.copy()
        environment["INSPECTORPRO_PARTS_MANUAL_ROOT"] = str(self.store_root)
        environment["PYTHONUNBUFFERED"] = "1"
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        self._process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "server:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=self.root,
            env=environment,
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            creationflags=creation_flags,
        )
        deadline = time.monotonic() + 90
        status_url = f"{self.app_url}/api/parts-manual/{self.assembly_number}"
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                self.stop()
                detail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
                raise RuntimeError(f"isolated parts-manual server exited during startup: {detail}")
            try:
                with urlopen(status_url, timeout=2) as response:  # noqa: S310 - loopback only
                    if response.status == 200:
                        return self
            except OSError:
                time.sleep(0.25)
        self.stop()
        raise RuntimeError("isolated parts-manual server did not become ready")

    def stop(self) -> None:
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None

    def __enter__(self) -> "IsolatedPartsManualServer":
        return self.start()

    def __exit__(self, _type, _value, _traceback) -> None:
        self.stop()


def seed_internal_legacy_section(request, app_url: str, assembly_number: str) -> dict:
    """Create the historical malformed draft only inside an isolated store."""

    initial_response = request.get(f"{app_url}/api/parts-manual/{assembly_number}")
    initial = initial_response.json()
    occurrences = [
        row["occurrenceId"]
        for row in initial.get("occurrences", [])
        if row.get("kind") == "part" and not row.get("suppressed")
    ]
    if not initial_response.ok or len(occurrences) < 5:
        raise RuntimeError("isolated manual fixture could not resolve five serviceable occurrences")
    created = request.post(
        f"{app_url}/api/parts-manual/{assembly_number}/sections",
        data={
            "baseRevision": initial["revision"],
            "sourceRevision": initial["sourceRevision"],
            "name": "body",
            "occurrenceIds": occurrences[:5],
        },
    )
    if not created.ok:
        raise RuntimeError(f"isolated legacy fixture could not be seeded: {created.text()}")
    return request.get(f"{app_url}/api/parts-manual/{assembly_number}").json()

