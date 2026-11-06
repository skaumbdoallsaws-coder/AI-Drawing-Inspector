"""Bounded byte-upload admission for an explicitly configured local STEP worker.

The application never imports OCP. Geometry executes in a disposable process;
neither filenames nor geometry-runtime paths may come from model tool arguments.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import tempfile
import threading
import time


_SLOTS = threading.BoundedSemaphore(2)
_WORKER = Path(__file__).with_name("step_worker.py")
_WARNINGS = ["material_density_unknown", "assembly_constraints_not_imported",
             "solid_volume_sum_not_boolean_union"]
_PHYSICAL = {"volume_basis": "closed_solid_brep", "material": None,
             "density_kg_m3": None, "mass_kg": None, "mass_basis": "unknown"}
_UNIT_NAMES = {"millimetre", "centimetre", "metre", "inch", "foot", "micrometre"}
_EXTERNAL = {b"EXTERNAL_SOURCE", b"EXTERNALLY_DEFINED_ITEM", b"DOCUMENT_FILE",
             b"PRODUCT_DEFINITION_WITH_ASSOCIATED_DOCUMENTS", b"APPLIED_DOCUMENT_REFERENCE",
             b"APPLIED_EXTERNAL_IDENTIFICATION_ASSIGNMENT", b"EXTERNAL_IDENTIFICATION_ASSIGNMENT",
             b"EXTERNALLY_DEFINED_REPRESENTATION", b"REFERENCE", b"ANCHOR"}
_TOKENS = re.compile(rb"/\*.*?\*/|'(?:''|[^'])*'|[A-Za-z_][A-Za-z_0-9]*|#[0-9]+", re.DOTALL)
_WORKER_ERRORS = {"step_invalid", "step_open_geometry", "step_units_unknown", "step_geometry_limit",
                  "step_mesh_failed", "step_export_failed", "step_external_reference",
                  "step_runtime_unavailable", "step_resource_limits_unavailable", "step_worker_failed"}


class StepImportError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 422):
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code


@dataclass(frozen=True)
class StepRuntime:
    python_executable: Path
    work_root: Path | None = None
    timeout_seconds: float = 60
    max_input_bytes: int = 32 * 1024 * 1024
    max_glb_bytes: int = 24 * 1024 * 1024
    max_metadata_bytes: int = 16384
    max_log_bytes: int = 65536
    memory_limit_bytes: int = 1536 * 1024 * 1024
    cpu_seconds: int = 45
    max_solids: int = 4096
    max_faces: int = 50000
    max_triangles: int = 300000
    max_nodes: int = 2000
    max_depth: int = 64
    max_dimension_m: float = 5

    def __post_init__(self):
        python = Path(self.python_executable)
        if not python.is_absolute() or not python.is_file():
            raise StepImportError("step_runtime_unavailable", "Configure an absolute local geometry Python executable.", 503)
        object.__setattr__(self, "python_executable", python.resolve())
        if self.work_root is not None:
            root = Path(self.work_root)
            if not root.is_absolute():
                raise ValueError("Geometry work_root must be an absolute host-configured directory")
            object.__setattr__(self, "work_root", root.resolve())
        for key, maximum in {
            "max_input_bytes": 128 * 1024 * 1024, "max_glb_bytes": 256 * 1024 * 1024,
            "max_metadata_bytes": 65536, "max_log_bytes": 1024 * 1024,
            "memory_limit_bytes": 4 * 1024**3, "cpu_seconds": 180,
            "max_solids": 10000, "max_faces": 100000, "max_triangles": 2000000,
            "max_nodes": 50000, "max_depth": 128,
        }.items():
            value = getattr(self, key)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"Invalid bounded STEP runtime setting: {key}")
        if not _number(self.timeout_seconds, 0.05, 240) or not _number(self.max_dimension_m, 1e-9, 5):
            raise ValueError("Invalid STEP timeout or dimensional bound")
        if self.memory_limit_bytes < 128 * 1024 * 1024:
            raise ValueError("Geometry memory limit must be at least 128 MiB")

    @classmethod
    def from_environment(cls, environ=None):
        values = os.environ if environ is None else environ
        python = values.get("INSPECTORPRO_PACKAGING_GEOMETRY_PYTHON", "")
        if not python:
            raise StepImportError("step_runtime_unavailable", "STEP import requires a configured local geometry runtime.", 503)
        root = values.get("INSPECTORPRO_PACKAGING_GEOMETRY_TMP")
        return cls(Path(python), Path(root) if root else None)

    def worker_limits(self):
        return {key: getattr(self, key) for key in (
            "max_input_bytes", "max_glb_bytes", "max_metadata_bytes", "memory_limit_bytes",
            "cpu_seconds", "max_solids", "max_faces", "max_triangles", "max_nodes",
            "max_depth", "max_dimension_m")}


@dataclass(frozen=True)
class StepImportResult:
    _metadata_json: bytes
    glb_bytes: bytes

    @property
    def metadata(self) -> dict:
        """Return a detached view; caller edits cannot alter the import evidence."""
        return json.loads(self._metadata_json)


def _number(value, minimum, maximum):
    return type(value) in (int, float) and math.isfinite(value) and minimum <= value <= maximum


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = value
        return result

    def nonfinite(_value):
        raise ValueError("Nonfinite JSON")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


def _preflight(data, runtime):
    if type(data) is not bytes or not data or len(data) > runtime.max_input_bytes:
        raise StepImportError("step_upload_limit", "STEP upload is empty or exceeds its byte limit.", 413)
    stripped = data.strip()
    if (not stripped.startswith(b"ISO-10303-21;") or not stripped.endswith(b"END-ISO-10303-21;")
            or b"\x00" in data):
        raise StepImportError("step_invalid", "Upload a complete STEP Part 21 file.")
    # Ignore quoted names/comments. External STEP references are deliberately unsupported.
    for match in _TOKENS.finditer(data):
        token = match.group()
        if token[:1] in (b"'", b"/"):
            continue
        if token.upper() in _EXTERNAL:
            raise StepImportError("step_external_reference", "External-file STEP references are not supported.")


def _environment(runtime, directory):
    system = os.environ.get("SystemRoot", os.environ.get("SYSTEMROOT", "C:/Windows"))
    env = {"HOME": str(directory), "USERPROFILE": str(directory), "TMP": str(directory),
           "TEMP": str(directory), "TMPDIR": str(directory), "LANG": "C.UTF-8",
           "PATH": str(runtime.python_executable.parent), "OMP_NUM_THREADS": "1",
           "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    if os.name == "nt":
        env.update(SYSTEMROOT=system, WINDIR=system, APPDATA=str(directory), LOCALAPPDATA=str(directory))
        env["PATH"] += os.pathsep + str(Path(system) / "System32")
    return env


def _metadata(raw, revision, runtime):
    try:
        value = _json(raw)
        keys = {"format", "dimensions_m", "bounds_m", "volume_m3", "solid_count", "root_count",
                "face_count", "triangle_count", "source_revision", "physical_evidence", "warnings", "units"}
        if not isinstance(value, dict) or set(value) != keys:
            raise ValueError("Invalid metadata fields")
        if value["format"] != "step" or value["source_revision"] != revision:
            raise ValueError("Invalid source identity")
        if value["physical_evidence"] != _PHYSICAL or value["warnings"] != _WARNINGS:
            raise ValueError("Untrusted physical evidence")
        dims, bounds = value["dimensions_m"], value["bounds_m"]
        if not isinstance(dims, list) or len(dims) != 3 or not all(
                _number(v, 1e-9, runtime.max_dimension_m) for v in dims):
            raise ValueError("Invalid dimensions")
        if not isinstance(bounds, list) or len(bounds) != 2 or not all(
                isinstance(row, list) and len(row) == 3 and all(_number(v, -10000, 10000) for v in row)
                for row in bounds):
            raise ValueError("Invalid bounds")
        if any(not math.isclose(bounds[1][i] - bounds[0][i], dims[i], rel_tol=1e-9, abs_tol=1e-10)
               for i in range(3)):
            raise ValueError("Inconsistent bounds")
        for key, cap in (("solid_count", runtime.max_solids), ("root_count", runtime.max_nodes),
                         ("face_count", runtime.max_faces), ("triangle_count", runtime.max_triangles)):
            if type(value[key]) is not int or not 1 <= value[key] <= cap:
                raise ValueError("Invalid geometry count")
        if not _number(value["volume_m3"], 1e-27, math.prod(dims) * value["solid_count"] * 1.00001):
            raise ValueError("Invalid volume")
        units = value["units"]
        if not isinstance(units, dict) or set(units) != {
                "authority", "source_length_units", "kernel_length_unit", "kernel_meters_per_unit",
                "output_length_unit", "output_meters_per_unit", "coordinate_system"}:
            raise ValueError("Invalid unit evidence")
        sources = units["source_length_units"]
        if (not isinstance(sources, list) or not 1 <= len(sources) <= 8
                or any(type(item) is not str or item not in _UNIT_NAMES for item in sources)):
            raise ValueError("Unknown source units")
        if units != {"authority": "STEP_declared_units_via_OCCT", "source_length_units": sources,
                "kernel_length_unit": "mm", "kernel_meters_per_unit": 0.001,
                "output_length_unit": "m", "output_meters_per_unit": 1.0, "coordinate_system": "Y-up"}:
            raise ValueError("Untrusted unit conversion")
        if (not _number(units["kernel_meters_per_unit"], .001, .001)
                or not _number(units["output_meters_per_unit"], 1, 1)):
            raise ValueError("Invalid numeric unit conversion")
        return value
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        raise StepImportError("step_result_invalid", "Geometry runtime returned invalid bounded evidence.", 502) from exc


def _glb(data, runtime):
    try:
        if not 20 <= len(data) <= runtime.max_glb_bytes:
            raise ValueError("GLB size")
        magic, version, total = struct.unpack_from("<4sII", data)
        if magic != b"glTF" or version != 2 or total != len(data):
            raise ValueError("GLB header")
        length, kind = struct.unpack_from("<II", data, 12)
        if kind != 0x4E4F534A or length % 4 or not 0 < length <= min(8 * 1024 * 1024, len(data) - 28):
            raise ValueError("GLB JSON")
        model = _json(data[20:20 + length])
        offset = 20 + length
        binary_length, binary_kind = struct.unpack_from("<II", data, offset)
        if binary_kind != 0x004E4942 or binary_length % 4 or offset + 8 + binary_length != len(data):
            raise ValueError("GLB binary")
        if not isinstance(model, dict) or model.get("asset", {}).get("version") != "2.0":
            raise ValueError("GLB model")
        if any(model.get(key) for key in ("animations", "skins", "extensionsRequired")):
            raise ValueError("GLB must be static")
        if not model.get("meshes") or not 1 <= len(model.get("nodes", [])) <= runtime.max_nodes:
            raise ValueError("GLB geometry")
        pending = [model]
        count = 0
        while pending:
            item = pending.pop()
            count += 1
            if count > 1000000:
                raise ValueError("GLB structure limit")
            if isinstance(item, dict):
                if "uri" in item:
                    raise ValueError("GLB external resources are forbidden")
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
            elif isinstance(item, float) and not math.isfinite(item):
                raise ValueError("GLB number")
    except (ValueError, TypeError, KeyError, AttributeError, struct.error, OverflowError, RecursionError) as exc:
        raise StepImportError("step_result_invalid", "Geometry runtime returned an invalid static GLB.", 502) from exc


async def _stop(process, readers):
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    for task in readers:
        if not task.done():
            task.cancel()
    if readers:
        await asyncio.gather(*readers, return_exceptions=True)

    async def discard(stream):
        while await stream.read(8192):
            pass

    # wait() can remain pending after kill while a piped transport is paused.
    # Discard the finite remainder without retaining potentially hostile logs.
    await asyncio.gather(discard(process.stdout), discard(process.stderr), process.wait())


async def _run(runtime, directory, cancel_event):
    process = None
    readers = []
    waiting = None
    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        starting = asyncio.create_task(asyncio.create_subprocess_exec(
            str(runtime.python_executable), "-I", "-B", str(_WORKER),
            json.dumps(runtime.worker_limits(), separators=(",", ":")),
            cwd=str(directory), env=_environment(runtime, directory),
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, creationflags=flags, limit=16384))
        try:
            process = await asyncio.shield(starting)
        except asyncio.CancelledError:
            # Process creation itself is asynchronous; recover its handle before cleanup.
            while not starting.done():
                try:
                    await asyncio.shield(starting)
                except asyncio.CancelledError:
                    continue
            process = starting.result()
            raise
        consumed = 0

        async def drain(stream):
            nonlocal consumed
            while chunk := await stream.read(8192):
                consumed += len(chunk)
                if consumed > runtime.max_log_bytes:
                    raise StepImportError("step_output_limit", "Geometry runtime exceeded its output limit.", 422)

        readers = [asyncio.create_task(drain(process.stdout)), asyncio.create_task(drain(process.stderr))]
        waiting = asyncio.create_task(process.wait())
        start = time.monotonic()
        while not waiting.done():
            if cancel_event is not None and cancel_event.is_set():
                raise asyncio.CancelledError("STEP import cancelled")
            if time.monotonic() - start >= runtime.timeout_seconds:
                raise StepImportError("step_timeout", "STEP import exceeded its time limit.", 504)
            for reader in readers:
                if reader.done():
                    reader.result()
            total, count = 0, 0
            for path in directory.iterdir():
                count += 1
                limit = runtime.max_input_bytes if path.name == "input.step" else runtime.max_glb_bytes
                if path.name == "result.json":
                    limit = runtime.max_metadata_bytes
                try:
                    info = path.lstat()
                except FileNotFoundError:
                    # RWGltf removes its temporary binary during GLB assembly.
                    continue
                size = info.st_size
                total += size
                if (not stat.S_ISREG(info.st_mode) or size > limit or count > 8
                        or total > runtime.max_input_bytes + 2 * runtime.max_glb_bytes + runtime.max_metadata_bytes):
                    raise StepImportError("step_output_limit", "Geometry runtime exceeded its file limit.")
            await asyncio.wait([waiting, *readers], timeout=0.05, return_when=asyncio.FIRST_EXCEPTION)
        await asyncio.gather(*readers)
        if cancel_event is not None and cancel_event.is_set():
            raise asyncio.CancelledError("STEP import cancelled")
        return process.returncode
    except OSError as exc:
        raise StepImportError("step_runtime_unavailable", "The configured geometry worker could not start.", 503) from exc
    finally:
        cancelled_during_cleanup = False
        if process is not None:
            # Finish termination even if the request task is cancelled again during cleanup.
            cleanup = asyncio.create_task(_stop(process, readers))
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    cancelled_during_cleanup = True
                    continue
            cleanup.result()
        if waiting is not None:
            await waiting
        if cancelled_during_cleanup:
            raise asyncio.CancelledError("STEP import cancelled during cleanup")


async def import_step(data: bytes, *, runtime: StepRuntime, cancel_event=None) -> StepImportResult:
    """Import uploaded bytes, not paths. Cancellation never leaves a worker running.

    ``cancel_event`` may be a threading.Event or asyncio.Event. Runtime configuration
    is host-owned, never renderer/model supplied. No caller source file is opened.
    """
    if not isinstance(runtime, StepRuntime):
        raise TypeError("A host-configured StepRuntime is required")
    if cancel_event is not None and cancel_event.is_set():
        raise asyncio.CancelledError("STEP import cancelled")
    _preflight(data, runtime)
    if not _SLOTS.acquire(blocking=False):
        raise StepImportError("step_busy", "The geometry import capacity is currently occupied.", 429)
    try:
        if runtime.work_root is not None:
            runtime.work_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="step-", dir=runtime.work_root) as temporary:
            directory = Path(temporary)
            with (directory / "input.step").open("xb") as stream:
                stream.write(data)
            revision = hashlib.sha256(data).hexdigest()
            exit_code = await _run(runtime, directory, cancel_event)
            result = directory / "result.json"
            if not result.is_file() or result.is_symlink() or not 0 < result.stat().st_size <= runtime.max_metadata_bytes:
                raise StepImportError("step_worker_failed", "Geometry runtime did not return bounded evidence.", 422)
            raw = result.read_bytes()
            if exit_code:
                try:
                    error = _json(raw)
                    code = error.get("error") if isinstance(error, dict) and set(error) == {"error"} else None
                except (ValueError, RecursionError):
                    code = None
                if type(code) is not str or code not in _WORKER_ERRORS:
                    code = "step_worker_failed"
                status = 503 if code in {"step_runtime_unavailable", "step_resource_limits_unavailable"} else 422
                raise StepImportError(code, "STEP geometry could not be imported safely (" + code + ").", status)
            metadata = _metadata(raw, revision, runtime)
            output = directory / "model.glb"
            if not output.is_file() or output.is_symlink() or output.stat().st_size > runtime.max_glb_bytes:
                raise StepImportError("step_output_limit", "Geometry runtime did not return a bounded GLB.")
            glb = output.read_bytes()
            _glb(glb, runtime)
            staged = directory / "input.step"
            if staged.is_symlink() or not staged.is_file() or staged.stat().st_size != len(data):
                raise StepImportError("step_result_invalid", "The staged STEP source changed during import.", 502)
            with staged.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != revision:
                    raise StepImportError("step_result_invalid", "The staged STEP source changed during import.", 502)
            if cancel_event is not None and cancel_event.is_set():
                raise asyncio.CancelledError("STEP import cancelled")
            return StepImportResult(json.dumps(metadata, allow_nan=False, sort_keys=True).encode("utf-8"), glb)
    finally:
        _SLOTS.release()
