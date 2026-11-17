"""Scoped model intake and immutable drafts; no model parsing runs in the host.

All capacity/admission decisions and publication transitions use an OS-held root
coordinator. Durable operation leases identify PID plus process start time.
Sources are shared only within a tenant/site and referenced by import records.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from functools import wraps
import errno
import math
import os
from pathlib import Path
import re
import shutil
import threading
import time
import uuid

from .authorization import FacilityPrincipal, require_facility_action
from .errors import FacilityLayoutError, FacilityNotFoundError
from . import model_import_files as disk
from ..industrial_assets.model_import.errors import ModelImportError
from ..industrial_assets.model_import.inspection import INSPECTION_BYTES, inspection_page, validate_inspection
from ..industrial_assets.model_import.job_io import file_digest
from ..industrial_assets.model_import.limits import CACHE_BYTES, CACHE_METADATA_BYTES, PREVIEW_BYTES, SUMMARY_BYTES
from ..industrial_assets.model_import.pictures import validate_picture
from ..industrial_assets.model_import.prepare_protocol import (DRAFT_BYTES, DRAFT_FILES, PUBLIC_FIELDS,
                                                               read_draft_output, validate_draft, validate_part)
from ..industrial_assets.model_import.protocol import read_summary
from ..industrial_assets.model_import.recipe import normalize_recipe
from ..industrial_assets.model_import.runner import _result, prepare_draft, run_inspect
from ..industrial_assets.model_import.validation import clean_text
from ..industrial_assets.model_builder.errors import ModelBuildError
from ..industrial_assets.model_builder.imports import module as builder_import

STORE_FOLDER = "model-imports"
MIB = 1024 * 1024
MAX_UPLOAD_BYTES = 128 * MIB
SITE_BYTES = 4 * 1024 * MIB
MARGIN = 1024 * 1024  # Atomic record replacements, request/manifests and lock metadata.
INSPECT_OUTPUT_BYTES = CACHE_BYTES + CACHE_METADATA_BYTES + INSPECTION_BYTES + PREVIEW_BYTES + SUMMARY_BYTES + MARGIN
PREPARE_OUTPUT_BYTES = INSPECT_OUTPUT_BYTES + sum(DRAFT_FILES.values()) + MARGIN
IMPORT_ID = re.compile(r"mi-[0-9a-f]{24}")
DRAFT_ID = re.compile(r"md-[0-9a-f]{24}")
BUILD_JOB_ID = re.compile(r"mbj-[0-9a-f]{24}")
HASH = re.compile(r"[0-9a-f]{64}")
# Folder names are kept short: Windows refuses paths over 259 characters unless long paths are turned on, and a
# prepare job nests scope/jobs/<token>/.model-prepare-*/output/<file> below the app's data folder (2026-11-09: the
# desktop's OneDrive data folder plus 64 + 32 character names reached 261 and every prepare failed).
SCOPE_KEY = re.compile(r"[0-9a-f]{24}")
TOKEN = re.compile(r"[0-9a-f]{16}")
# The deepest path below the store folder: scope (24) / jobs / token (16) / .model-prepare-XXXXXXXX / output / a file
# name of up to 32 characters (".atomic-" temporaries included), with the separators.
DEEPEST_BELOW_STORE = 1 + 24 + 1 + 4 + 1 + 16 + 1 + 23 + 1 + 6 + 1 + 32
WINDOWS_MAX_PATH = 259
STALE_SECONDS = 210
DAY = 86400
_OPERATIONS: dict[tuple[str, str], "_Lease"] = {}
_OPERATIONS_LOCK = threading.RLock()
_STORES_LOCK = threading.Lock()


def _long_paths_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            return winreg.QueryValueEx(key, "LongPathsEnabled")[0] == 1
    except (ImportError, OSError):
        return False


def require_path_budget(root: Path) -> None:
    """Refuse clearly, before any worker starts, when Windows could not open the deepest job path."""
    if os.name == "nt" and len(str(root)) + DEEPEST_BELOW_STORE > WINDOWS_MAX_PATH and not _long_paths_enabled():
        raise FacilityLayoutError(
            "model_store_path_too_long",
            "This app's data folder path is too long for Windows to prepare models. Move the app's data to a "
            "shorter folder, or turn on Windows long paths.", status_code=507)


def missing() -> FacilityNotFoundError:
    return FacilityNotFoundError("model_import_missing", "That model import or draft was not found for this site.")


def busy() -> FacilityLayoutError:
    return FacilityLayoutError("model_import_busy", "Model imports are busy. Retry shortly.", status_code=429)


def quota() -> FacilityLayoutError:
    return FacilityLayoutError("model_import_quota", "This site's model imports have reached the 4 GiB storage budget.",
                               status_code=507)


def translate(error: ModelImportError) -> FacilityLayoutError:
    return FacilityLayoutError(error.code, error.message, status_code=error.status_code, details=error.details)


def build_failure(error):
    if isinstance(error, ModelBuildError):
        return FacilityLayoutError(error.code, error.message, details=error.to_dict()["details"])
    if isinstance(error, builder_import("errors").ModelImportError):
        return translate(error)
    return job_failure(error)


def lease_key(value):
    return value["objectId"] if value.get("kind", "import") == "build" else value["importId"]


def host_errors(method):
    @wraps(method)
    def call(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except ModelBuildError as error:
            raise build_failure(error) from None
        except ModelImportError as error:
            raise translate(error) from None
        except OSError as error:
            if error.errno == errno.ENOSPC:
                raise quota() from None
            raise FacilityLayoutError("model_store_unavailable", "Model storage is unavailable. Retry shortly.",
                                      status_code=503) from None
    return call


def job_failure(error: BaseException) -> FacilityLayoutError:
    """Keep storage refusals intact while recording failures before worker handoff."""
    if isinstance(error, ModelImportError):
        return translate(error)
    if isinstance(error, FacilityLayoutError):
        return error
    if isinstance(error, OSError):
        return (quota() if error.errno == errno.ENOSPC else FacilityLayoutError(
            "model_store_unavailable", "Model storage is unavailable. Retry shortly.", status_code=503))
    return translate(ModelImportError("model_worker_failed"))


def clean_source_name(raw: str) -> str:
    return clean_text(str(raw or "").replace("\\", "/").rsplit("/", 1)[-1], 80) or "model.glb"


@dataclass(frozen=True)
class ModelImportScope:
    principal: FacilityPrincipal
    site_id: str
    layout_id: str

    @property
    def key(self) -> str:
        return sha256((self.principal.tenant_id + "\0" + self.site_id).encode()).hexdigest()[:24]


class _Lease:
    def __init__(self, store, scope, import_id, amount, cancel=None, *, kind="import"):
        self.store, self.scope, self.import_id = store, scope, import_id
        self.kind = kind
        self.token = uuid.uuid4().hex[:16]
        self.cancel = cancel if cancel is not None else threading.Event()
        self.done = threading.Event()
        self.ending = False
        self.cancel_upload = None
        self.data = {**disk.owner(), "token": self.token, "scope": scope.key, "importId": import_id,
                     "user": sha256((scope.principal.tenant_id + "\0" + scope.principal.principal_id).encode()).hexdigest(),
                     "reserved": amount}
        if kind == "build":
            self.data.pop("importId")
            self.data.update(kind="build", objectId=import_id)
        self.job = store.root / scope.key / "jobs" / self.token

    def check(self):
        if self.cancel.is_set():
            raise translate(ModelImportError("model_cancelled"))

    def release(self):
        if self.done.is_set():
            return
        self.ending = True
        with disk.coordinator(self.store.root):
            disk.remove(self.job)
            if self.kind == "import":
                disk.remove(self.store.root / self.scope.key / "uploads" / (self.import_id + ".part"))
            lock = self.store.root / self.scope.key / "locks" / (self.import_id + ".json")
            if (disk.read_json(lock) or {}).get("token") == self.token:
                lock.unlink(missing_ok=True)
            (self.store.root / "active" / (self.token + ".json")).unlink(missing_ok=True)
        with _OPERATIONS_LOCK:
            _OPERATIONS.pop((str(self.store.root), self.token), None)
        self.done.set()


class Upload:
    """Admission and storage have already been reserved before the first body chunk."""
    def __init__(self, store, scope, lease, name, declared):
        self.store, self.scope, self.lease = store, scope, lease
        self.name, self.declared, self.size = name, declared, 0
        self.path = disk.safe(store.root / scope.key / "uploads" / (lease.import_id + ".part"))
        disk.mkdir(self.path.parent)
        self.digest, self.prefix = sha256(), b""
        self.lock = threading.RLock()
        self.finished = False
        self.stream = self.path.open("xb")
        lease.cancel_upload = self.abort

    def write(self, chunk: bytes) -> None:
        with self.lock:
            self.lease.check()
            if self.finished:
                raise translate(ModelImportError("model_cancelled"))
            new_size = self.size + len(chunk)
            if new_size > MAX_UPLOAD_BYTES:
                raise translate(ModelImportError("model_too_large"))
            # A dishonest or absent Content-Length cannot under-reserve a streamed body.
            with disk.coordinator(self.store.root):
                self.store._resize(self.lease, max(self.lease.data["reserved"], new_size + MARGIN))
            self.stream.write(chunk)
            self.digest.update(chunk)
            self.prefix = (self.prefix + chunk[:4])[:4]
            self.size = new_size

    def finish(self) -> dict:
        with self.lock:
            try:
                self.lease.check()
                if self.finished:
                    raise translate(ModelImportError("model_cancelled"))
                if not self.size:
                    raise FacilityLayoutError("model_empty", "The uploaded file is empty.")
                self.stream.flush()
                os.fsync(self.stream.fileno())
                self.stream.close()
                with disk.coordinator(self.store.root):
                    self.lease.check()
                    record = self.store._record(self.scope, self.lease.import_id)
                    digest = self.digest.hexdigest()
                    kind = "zip" if self.prefix[:2] == b"PK" else "glb"
                    target = disk.safe(self.store.root / self.scope.key / "sources" / (digest + "." + kind))
                    disk.mkdir(target.parent)
                    if target.exists():
                        if target.stat().st_size != self.size or file_digest(target) != digest:
                            raise FacilityLayoutError("model_store_invalid", "Stored source failed its integrity check.")
                        self.path.unlink()
                    else:
                        os.replace(self.path, target)
                    record.update(sha256=digest, bytes=self.size, format=kind, sourceFormat=kind,
                                  state="queued", updated=time.time())
                    self.store._save(self.scope, record)
                    self.store._resize(self.lease, MARGIN)
                    result = deepcopy(record)
                self.store._start_inspect(self.lease)
                self.finished = True
                self.lease.cancel_upload = None
                return result
            except BaseException as error:
                self.abort(job_failure(error))
                if isinstance(error, Exception):
                    raise job_failure(error) from None
                raise

    def abort(self, error=None):
        with self.lock:
            if self.finished:
                return
            self.lease.cancel.set()
            self.finished = True
            try:
                try:
                    self.stream.close()
                finally:
                    with disk.coordinator(self.store.root):
                        record = self.store._record(self.scope, self.lease.import_id)
                        self.store._fail(self.scope, record, error or FacilityLayoutError(
                            "interrupted", "The upload was interrupted. Retry or upload it again."),
                            "refused" if error and error.code in {"model_too_large", "model_empty"} else "failed")
            except (OSError, FacilityLayoutError):
                pass  # Reconciliation retries the terminal transition; preserve the HTTP refusal.
            finally:
                self.lease.release()


class ModelImportStore:
    """One app root, injectable workers for tests; all public lookups recheck scope."""
    def __init__(self, layout_root, *, layout_reader, runtime=None, inspect_worker=None, prepare_worker=None,
                 build_worker=None, site_bytes=SITE_BYTES):
        self.root = disk.safe(Path(layout_root).absolute() / STORE_FOLDER)
        self.layout_reader = layout_reader
        self.runtime = runtime
        self.inspect_worker = inspect_worker or run_inspect
        self.prepare_worker = prepare_worker or prepare_draft
        self.build_worker = build_worker
        self.site_bytes = site_bytes

    def _authorize(self, scope: ModelImportScope, write=False) -> None:
        require_facility_action(scope.principal, tenant_id=scope.principal.tenant_id, site_id=scope.site_id,
                                action="layout.edit" if write else "layout.read")
        self.layout_reader(scope.principal, scope.site_id, scope.layout_id)
        disk.mkdir(self.root / "active")

    def _folder(self, scope) -> Path:
        return disk.safe(self.root / scope.key)

    def _record(self, scope, import_id) -> dict:
        if not isinstance(import_id, str) or not IMPORT_ID.fullmatch(import_id):
            raise missing()
        record = disk.read_json(self._folder(scope) / "imports" / (import_id + ".json"))
        if not isinstance(record, dict) or record.get("id") != import_id or record.get("scope") != scope.key:
            raise missing()
        return record

    def _save(self, scope, record):
        length = len(disk.encode(record))
        if length > 256 * 1024:
            raise quota()
        if not any(v["scope"] == scope.key and v.get("importId") == record["id"] for v in self._active()):
            # Housekeeping also reserves the temporary copy while the coordinator is held.
            self._capacity(scope, length)
        disk.atomic(self._folder(scope) / "imports" / (record["id"] + ".json"), record)

    def _fail(self, scope, record, error, state):
        record.update(state=state, refusal=error.to_dict(), updated=time.time())
        self._save(scope, record)

    def _active(self) -> list[dict]:
        values = []
        for file in (self.root / "active").glob("*.json"):
            value = disk.read_json(file)
            if not isinstance(value, dict) or not TOKEN.fullmatch(str(value.get("token", ""))):
                raise FacilityLayoutError("model_store_invalid", "An import reservation is invalid.", status_code=503)
            kind = value.get("kind", "import")
            valid_id = (kind == "import" and IMPORT_ID.fullmatch(str(value.get("importId", "")))) or (
                kind == "build" and "importId" not in value and
                (BUILD_JOB_ID.fullmatch(str(value.get("objectId", ""))) or DRAFT_ID.fullmatch(str(value.get("objectId", "")))))
            if (file.stem != value["token"] or not SCOPE_KEY.fullmatch(str(value.get("scope", "")))
                    or not valid_id
                    or not HASH.fullmatch(str(value.get("user", "")))
                    or type(value.get("reserved")) is not int or not 0 <= value["reserved"] <= SITE_BYTES
                    or type(value.get("created")) not in (int, float) or not math.isfinite(value["created"])
                    or type(value.get("pid")) is not int or value["pid"] <= 0
                    or not isinstance(value.get("processStart"), str)):
                raise FacilityLayoutError("model_store_invalid", "An import reservation is invalid.", status_code=503)
            values.append(value)
        return values

    def _owned_paths(self, value):
        folder = self.root / value["scope"]
        paths = [folder / "jobs" / value["token"], folder / "locks" / (lease_key(value) + ".json")]
        if value.get("kind", "import") == "import":
            paths.extend([folder / "uploads" / (value["importId"] + ".part"),
                          folder / "imports" / (value["importId"] + ".json")])
        return paths

    def _owned_size(self, value):
        return sum(disk.size(p) for p in self._owned_paths(value))

    def _capacity(self, scope, amount, token=None):
        # Count owned trees by their reservation, never by a racy pair of size scans:
        # workers write outside the coordinator, so total-size minus owned-size can
        # undercount a file that grows between those two measurements.
        active = [v for v in self._active() if v["scope"] == scope.key]
        excluded = set()
        reserved = amount if token is None else 0
        for value in active:
            excluded.update(self._owned_paths(value))
            reserved += amount if value["token"] == token else value["reserved"]
        def committed(path):
            path = disk.safe(path)
            if path in excluded or not path.exists():
                return 0
            if path.is_file():
                return path.stat().st_size
            return sum(committed(child) for child in path.iterdir())
        if committed(self._folder(scope)) + reserved > self.site_bytes:
            raise quota()

    def _resize(self, lease, amount):
        amount = max(amount, self._owned_size(lease.data))
        self._capacity(lease.scope, amount, lease.token)
        lease.data["reserved"] = amount
        disk.atomic(self.root / "active" / (lease.token + ".json"), lease.data)

    def _claim(self, scope, import_id, amount, cancel=None, *, kind="import") -> _Lease:
        # Caller holds coordinator. Reconciliation occurs before admission, not while a live worker owns files.
        require_path_budget(self.root)
        lease = _Lease(self, scope, import_id, amount, cancel, kind=kind)
        active = self._active()
        if (self.root / "active" / (lease.token + ".json")).exists():
            raise busy()
        if len(active) >= 8 or sum(v["user"] == lease.data["user"] for v in active) >= 2:
            raise busy()
        lock = self._folder(scope) / "locks" / (import_id + ".json")
        if lock.exists():
            raise busy()
        self._capacity(scope, amount)
        try:
            disk.atomic(self.root / "active" / (lease.token + ".json"), lease.data)
            disk.atomic(lock, lease.data)
            disk.mkdir(lease.job)
            with _OPERATIONS_LOCK:
                _OPERATIONS[(str(self.root), lease.token)] = lease
        except BaseException:
            # The caller cannot release a claim that never returned. Roll back
            # here without reacquiring the coordinator; failed cleanup is marked
            # ending so reconciliation retries it immediately, never waits on it.
            lease.ending = True
            with _OPERATIONS_LOCK:
                _OPERATIONS[(str(self.root), lease.token)] = lease
            try:
                disk.remove(lease.job)
                lock.unlink(missing_ok=True)
                (self.root / "active" / (lease.token + ".json")).unlink(missing_ok=True)
            except (OSError, FacilityLayoutError):
                pass
            else:
                with _OPERATIONS_LOCK:
                    _OPERATIONS.pop((str(self.root), lease.token), None)
                lease.done.set()
            raise
        return lease

    @host_errors
    def begin_upload(self, scope, name, content_length=None) -> Upload:
        self._authorize(scope, True)
        if content_length is not None and (type(content_length) is not int or content_length < 0):
            raise FacilityLayoutError("model_upload_length", "Content-Length must be a non-negative integer.", status_code=400)
        if content_length is not None and content_length > MAX_UPLOAD_BYTES:
            raise translate(ModelImportError("model_too_large"))
        self.reconcile()
        lease = None
        try:
            with disk.coordinator(self.root):
                import_id = "mi-" + uuid.uuid4().hex[:24]
                if (self._folder(scope) / "imports" / (import_id + ".json")).exists():
                    raise busy()  # Even a nonce collision must never overwrite an older import.
                lease = self._claim(scope, import_id, (MAX_UPLOAD_BYTES if content_length is None else content_length) + MARGIN)
                record = {"schemaVersion": 1, "id": import_id, "importId": import_id, "scope": scope.key,
                          "name": clean_source_name(name), "sha256": None, "bytes": 0, "format": None,
                          "sourceFormat": None, "created": time.time(), "updated": time.time(),
                          "createdBy": scope.principal.principal_id, "state": "queued", "refusal": None,
                          "summary": None, "licence": None, "warnings": [], "drafts": []}
                self._save(scope, record)
                return Upload(self, scope, lease, record["name"], content_length)
        except BaseException as error:
            if lease is not None:
                self._fail_start(lease, job_failure(error))
            if isinstance(error, Exception):
                raise job_failure(error) from None
            raise

    def _source(self, scope, record) -> Path:
        digest, kind = record.get("sha256"), record.get("sourceFormat")
        if not isinstance(digest, str) or not HASH.fullmatch(digest) or kind not in ("glb", "zip"):
            raise missing()
        path = disk.safe(self._folder(scope) / "sources" / (digest + "." + kind))
        if not path.is_file():
            raise missing()
        if path.stat().st_size != record["bytes"] or file_digest(path) != digest:
            raise ModelImportError("model_cache_invalid")
        return path

    def _dependencies(self):
        # Explicit test/native runtime wins; otherwise discover only host-installed packages.
        if self.runtime is not None:
            from ..industrial_assets.model_import.job_io import local_directory
            return local_directory(self.runtime().dependency_root)
        from .model_import_runtime import model_import_runtime
        return model_import_runtime().dependency_root

    def _fail_start(self, lease, error):
        """Caller has left the coordinator; state-write failure must not bypass release."""
        try:
            with disk.coordinator(self.root):
                self._fail(lease.scope, self._record(lease.scope, lease.import_id), error, "failed")
        except (OSError, FacilityLayoutError):
            pass  # A persistently unwritable record is reconciled once storage recovers.
        finally:
            lease.release()

    def _start_inspect(self, lease):
        # Until start succeeds, the upload/retry caller owns cleanup, including
        # exceptions while constructing the thread or recording its failure.
        thread = threading.Thread(target=self._check_job, args=(lease,), name="model-import-check", daemon=True)
        thread.start()

    def _check_job(self, lease):
        scope = lease.scope
        try:
            with disk.coordinator(self.root):
                record = self._record(scope, lease.import_id)
                source = self._source(scope, record)
                self._resize(lease, record["bytes"] + INSPECT_OUTPUT_BYTES)
                record.update(state="checking", refusal=None, updated=time.time())
                self._save(scope, record)
            lease.check()
            shutil.copyfile(source, disk.safe(lease.job / "source.bin"))
            disk.atomic(lease.job / "request.json", {"name": record["name"], "storeMetadata": True})
            self.inspect_worker(lease.job, self._dependencies(), cancel_event=lease.cancel)
            summary = _result(lease.job, require_preview=True)
            if summary["sourceSha256"] != record["sha256"]:
                raise ModelImportError("model_worker_failed")
            metadata = validate_inspection(disk.read_json(lease.job / "inspection.json", INSPECTION_BYTES), summary)
            lease.check()
            published = disk.mkdir(lease.job / "inspection")
            for name in ("summary.json", "inspection.json", "preview.png"):
                os.replace(disk.safe(lease.job / name), published / name)
            with disk.coordinator(self.root):
                lease.check()
                target = self._folder(scope) / "inspections" / lease.import_id
                disk.mkdir(target.parent)
                disk.remove(target)
                os.replace(published, target)
                record.update(state="ready", refusal=None, summary=summary, licence=metadata["licence"],
                              format=summary["format"], warnings=summary["warnings"], updated=time.time())
                self._save(scope, record)
        except Exception as error:
            if isinstance(error, ModelImportError):
                error = translate(error)
            if not isinstance(error, FacilityLayoutError):
                error = translate(ModelImportError("model_worker_failed"))
            state = ("failed" if error.code in {"model_worker_failed", "model_timeout", "model_cancelled",
                                                "model_runtime_unavailable", "model_limits_unavailable",
                                                "model_import_quota", "model_store_unavailable", "model_cache_invalid"} else "refused")
            with disk.coordinator(self.root):
                self._fail(scope, self._record(scope, lease.import_id), error, state)
        finally:
            lease.release()

    @host_errors
    def retry(self, scope, import_id):
        self._authorize(scope, True)
        self.reconcile()
        lease = None
        try:
            with disk.coordinator(self.root):
                record = self._record(scope, import_id)
                self._source(scope, record)
                if record["state"] != "failed":
                    raise FacilityLayoutError("model_import_not_retryable", "Only a failed import can be retried.", status_code=409)
                lease = self._claim(scope, import_id, record["bytes"] + INSPECT_OUTPUT_BYTES)
                record.update(state="queued", refusal=None, updated=time.time())
                self._save(scope, record)
                result = deepcopy(record)
            self._start_inspect(lease)
            return result
        except BaseException as error:
            if lease is not None:
                self._fail_start(lease, job_failure(error))
            if isinstance(error, Exception):
                raise job_failure(error) from None
            raise

    @host_errors
    def get(self, scope, import_id):
        self._authorize(scope)
        self.reconcile()
        with disk.coordinator(self.root):
            record = deepcopy(self._record(scope, import_id))
            record["registrations"] = [receipt for d in record["drafts"]
                                       if (receipt := self._receipt(scope, d["id"])) is not None]
            return record

    @host_errors
    def list(self, scope):
        self._authorize(scope)
        self.reconcile()
        with disk.coordinator(self.root):
            parent = self._folder(scope) / "imports"
            records = [self._record(scope, p.stem) for p in parent.glob("mi-*.json")
                       if IMPORT_ID.fullmatch(p.stem)]
            records.sort(key=lambda r: (r["created"], r["id"]), reverse=True)
            return [{k: r[k] for k in ("id", "importId", "name", "bytes", "format", "state", "created", "refusal")}
                    for r in records[:20]]

    @host_errors
    def describe_model_attachment(self, scope, import_id):
        """Read attachment metadata only; do not reconcile or transition its record."""
        self._authorize(scope)
        with disk.coordinator(self.root):
            try:
                record = self._record(scope, import_id)
            except FacilityNotFoundError:
                return None
            refusal = record.get("refusal")
            if isinstance(refusal, dict):
                refusal = {"code": clean_text(refusal.get("code"), 80),
                           "message": clean_text(refusal.get("message"), 1000)}
            else:
                refusal = None
            return {"importId": record["id"], "name": clean_source_name(record["name"]),
                    "format": clean_text(record["format"], 32), "megabytes": record["bytes"] / MIB,
                    "state": record["state"], "refusal": refusal}

    @host_errors
    def registrations_since(self, scope, started_at):
        """Receipt times, not import state or a duplicated registration index, are authoritative."""
        self._authorize(scope)
        if type(started_at) not in (int, float) or not 0 <= started_at < 1e12:
            raise FacilityLayoutError("model_registration_time_invalid", "Supply a finite registration start time.")
        with disk.coordinator(self.root):
            rows = []
            for path in (self._folder(scope) / "registrations").glob("md-*.json"):
                if not DRAFT_ID.fullmatch(path.stem):
                    continue
                receipt = self._receipt(scope, path.stem)
                if receipt is not None and receipt["at"] >= started_at:
                    self._draft(scope, path.stem)  # Recheck tenant/site/source ownership.
                    rows.append((receipt["at"], path.stem, receipt["assetId"]))
            # Turn notifications are bounded information; catalogVersion drives refresh.
            return list(dict.fromkeys(row[2] for row in sorted(rows, reverse=True)))[:256]

    @host_errors
    def inspect(self, scope, import_id=None, offset=0, limit=64):
        if import_id is None:
            return {"imports": [{k: record[k] for k in ("id", "importId", "name", "state", "created")}
                                for record in self.list(scope)]}
        self._authorize(scope)
        with disk.coordinator(self.root):
            record = self._record(scope, import_id)
            if record["state"] != "ready":
                return {k: record[k] for k in ("name", "format", "state", "refusal")}
            directory = self._folder(scope) / "inspections" / import_id
            try:
                from ..industrial_assets.model_import.job_io import bounded_read
                summary = read_summary(bounded_read(disk.safe(directory), "summary.json", SUMMARY_BYTES))
                metadata = validate_inspection(disk.read_json(directory / "inspection.json", INSPECTION_BYTES), summary)
                if (type(offset) is not int or not 0 <= offset <= summary["partsTotal"]
                        or type(limit) is not int or not 1 <= limit <= 64):
                    raise FacilityLayoutError("model_parts_page_invalid", "Use a valid parts offset and a limit of 1-64.")
                return inspection_page(summary, metadata, offset, limit)
            except ModelImportError as error:
                raise translate(error) from None

    @host_errors
    def preview(self, scope, object_id, *, draft=False) -> bytes:
        self._authorize(scope)
        with disk.coordinator(self.root):
            if draft:
                self._draft(scope, object_id)
                directory = self._folder(scope) / "drafts" / object_id
            else:
                record = self._record(scope, object_id)
                if record["state"] != "ready":
                    raise missing()
                directory = self._folder(scope) / "inspections" / object_id
            file = disk.safe(directory / "preview.png")
            if not file.is_file():
                raise missing()
            with file.open("rb") as stream:
                content = stream.read(PREVIEW_BYTES + 1)
            try:
                validate_picture(content, "preview")
            except ModelImportError as error:
                raise translate(error) from None
            return content

    def _draft(self, scope, draft_id):
        if not isinstance(draft_id, str) or not DRAFT_ID.fullmatch(draft_id):
            raise missing()
        directory = disk.safe(self._folder(scope) / "drafts" / draft_id)
        from ..industrial_assets.model_builder.drafts import DRAFT_BYTES as BUILD_DRAFT_BYTES
        value = disk.read_json(directory / "draft.json", max(DRAFT_BYTES, BUILD_DRAFT_BYTES))
        if not isinstance(value, dict):
            raise missing()
        if value.get("kind", "import") == "build":
            from .model_build_store import read
            return read(self, scope, draft_id)
        if value.get("kind", "import") != "import":
            raise FacilityLayoutError("model_store_invalid", "Unknown model draft kind.", status_code=503)
        # Preserve the import protocol's original bound and validator.
        value = disk.read_json(directory / "draft.json", DRAFT_BYTES)
        try:
            value = validate_draft(value)
            record = self._record(scope, value["recipe"]["importId"])
            if value["sourceSha256"] != record["sha256"] or value["draftId"] != draft_id:
                raise missing()
            receipt = self._receipt(scope, draft_id)
            if receipt is not None and not receipt["assetId"].startswith("asset-import-"):
                raise FacilityLayoutError("model_store_invalid", "The import receipt has the wrong kind.", status_code=503)
            if receipt is None:
                return read_draft_output(directory)
            manifest = disk.read_json(directory / "manifest.json", 4096)
            if not isinstance(manifest, dict):
                raise ModelImportError("model_worker_failed")
            # These remain even after registration compacts the frozen draft.
            for name in ("draft.json", "parts.jsonl", "preview.png"):
                file = disk.safe(directory / name)
                entry = manifest["files"][name]
                if (not file.is_file() or file.stat().st_size > DRAFT_FILES[name]
                        or file.stat().st_size != entry["bytes"] or file_digest(file) != entry["sha256"]):
                    raise ModelImportError("model_worker_failed")
            return value
        except ModelImportError as error:
            raise translate(error) from None
        except (KeyError, TypeError, OSError):
            raise translate(ModelImportError("model_worker_failed")) from None

    @host_errors
    def draft(self, scope, draft_id):
        self._authorize(scope)
        with disk.coordinator(self.root):
            return deepcopy(self._draft(scope, draft_id))

    @host_errors
    def draft_parts(self, scope, draft_id, offset=0, limit=64):
        self._authorize(scope)
        with disk.coordinator(self.root):
            value = self._draft(scope, draft_id)
            if value.get("kind") == "build":
                from ..industrial_assets.model_builder.drafts import public_result
                try:
                    return public_result(self._folder(scope) / "drafts" / draft_id, value, offset=offset, limit=limit)
                except ValueError:
                    raise FacilityLayoutError("model_parts_page_invalid", "Use a valid parts offset and a limit of 1-64.") from None
            if type(offset) is not int or not 0 <= offset <= value["partsTotal"] or type(limit) is not int or not 1 <= limit <= 64:
                raise FacilityLayoutError("model_parts_page_invalid", "Use a valid parts offset and a limit of 1-64.")
            parts = []
            with disk.safe(self._folder(scope) / "drafts" / draft_id / "parts.jsonl").open("rb") as stream:
                for index in range(value["partsTotal"]):
                    line = stream.readline(2049)
                    if len(line) > 2048 or not line.endswith(b"\n"):
                        raise translate(ModelImportError("model_worker_failed"))
                    if offset <= index < offset + limit:
                        from ..industrial_assets.model_import.validation import parse_json
                        part = parse_json(line, 2048)
                        validate_part(part, index)
                        parts.append(part)
                    if index + 1 >= offset + limit:
                        break
            result = {"draftId": draft_id, "partsTotal": value["partsTotal"], "partsOffset": offset, "parts": parts}
            while True:
                end = offset + len(parts)
                result["nextPartsOffset"] = end if end < value["partsTotal"] else None
                if len(disk.encode(result)) <= SUMMARY_BYTES:
                    return result
                parts.pop()

    @host_errors
    def build(self, scope, recipe, cancel=None, **options):
        from .model_build_store import build
        return build(self, scope, recipe, cancel, **options)

    @host_errors
    def list_build_drafts(self, scope):
        from .model_build_store import list_drafts
        return list_drafts(self, scope)

    @host_errors
    def focus_build_view(self, scope, draft_id, focus, private_asset_root, cancel=None):
        from .model_build_views import focus_view
        return focus_view(self, scope, draft_id, focus, private_asset_root, cancel)

    @host_errors
    def prepare(self, scope, recipe, cancel=None):
        self._authorize(scope, True)
        try:
            normalized = normalize_recipe(recipe)
        except ModelImportError as error:
            raise translate(error) from None
        if cancel is not None and cancel.is_set():
            raise translate(ModelImportError("model_cancelled"))
        self.reconcile()
        lease = None
        published = None
        committed = False
        worker_started = False
        try:
            with disk.coordinator(self.root):
                record = self._record(scope, normalized["importId"])
                if record["state"] != "ready":
                    raise FacilityLayoutError("model_import_not_ready", "Wait for this model to finish checking.", status_code=409)
                for item in record["drafts"]:
                    existing = self._draft(scope, item["id"])
                    if existing["recipe"] == normalized:
                        if cancel is not None and cancel.is_set():
                            raise translate(ModelImportError("model_cancelled"))
                        return {key: existing[key] for key in PUBLIC_FIELDS}
                source = self._source(scope, record)
                lease = self._claim(scope, record["id"], record["bytes"] + PREPARE_OUTPUT_BYTES, cancel)
                record.update(state="checking", updated=time.time())
                self._save(scope, record)
            lease.check()
            destination = lease.job / "prepared"
            dependencies = self._dependencies()
            worker_started = True
            result = self.prepare_worker(source, normalized, destination, lease.cancel,
                                         dependency_root=dependencies)
            value = read_draft_output(destination)
            if value["recipe"] != normalized or value["sourceSha256"] != record["sha256"]:
                raise ModelImportError("model_worker_failed")
            # The entire worker job, including its copied input, was reserved before it wrote.
            if disk.size(lease.job) > lease.data["reserved"]:
                raise quota()
            lease.check()
            with disk.coordinator(self.root):
                lease.check()
                target = self._folder(scope) / "drafts" / value["draftId"]
                disk.mkdir(target.parent)
                if target.exists():
                    existing = self._draft(scope, value["draftId"])
                    if existing != value:
                        raise FacilityLayoutError("asset_identity_conflict", "A different draft has the same identity.")
                else:
                    os.replace(destination, target)
                    published = target
                lease.check()
                if not any(d["id"] == value["draftId"] for d in record["drafts"]):
                    record["drafts"].append({"id": value["draftId"], "created": time.time()})
                self._trim(scope, record, maximum=20)
                record.update(state="ready", refusal=None, updated=time.time())
                record.pop("lastPrepareError", None)
                self._save(scope, record)
                committed = True
            return {key: value[key] for key in PUBLIC_FIELDS}
        except BaseException as error:
            if lease is None or (worker_started and not isinstance(error, Exception)):
                # Preserve completed orphan output on simulated/process interruption;
                # reconciliation recovers it. The lease still releases in finally.
                raise
            failure = job_failure(error)
            try:
                with disk.coordinator(self.root):
                    if published is not None and not committed:
                        disk.remove(published)
                    # A bad adaptation does not invalidate a checked source.
                    record = self._record(scope, normalized["importId"])
                    record.update(state="ready", updated=time.time(), lastPrepareError=failure.to_dict())
                    self._save(scope, record)
            except (OSError, FacilityLayoutError):
                pass  # Cleanup still runs; reconciliation repairs an unwritable record later.
            if isinstance(error, Exception):
                raise failure from None
            raise
        finally:
            if lease is not None:
                lease.release()
            if committed and lease.cancel.is_set():
                if published is not None:
                    with disk.coordinator(self.root):
                        disk.remove(published)
                        current = self._record(scope, normalized["importId"])
                        current["drafts"] = [d for d in current["drafts"] if d["id"] != published.name]
                        self._save(scope, current)
                raise translate(ModelImportError("model_cancelled"))

    def _receipt(self, scope, draft_id):
        value = disk.read_json(self._folder(scope) / "registrations" / (draft_id + ".json"), 4096)
        if value is None:
            return None
        if (not isinstance(value, dict) or set(value) != {"assetId", "revision", "at"}
                or not isinstance(value["assetId"], str)
                or not re.fullmatch(r"asset-(?:import|built)-[a-z0-9-]{1,40}-[a-f0-9]{24}", value["assetId"])
                or not isinstance(value["revision"], str) or not 1 <= len(value["revision"]) <= 128
                or clean_text(value["revision"], 128) != value["revision"]
                or type(value["at"]) not in (int, float) or not 0 < value["at"] < 1e12):
            raise FacilityLayoutError("model_store_invalid", "The stored registration receipt is invalid.", status_code=503)
        return value

    @host_errors
    def receipt(self, scope, draft_id):
        self._authorize(scope)
        with disk.coordinator(self.root):
            self._draft(scope, draft_id)
            return self._receipt(scope, draft_id)

    @contextmanager
    def hold_draft(self, scope, draft_id, cancel=None):
        """MI2 holds this lease across bundle publication/live binding/receipt creation."""
        self._authorize(scope, True)
        self.reconcile()
        lease = None
        try:
            with disk.coordinator(self.root):
                value = self._draft(scope, draft_id)
                if value.get("kind") == "build":
                    lease = self._claim(scope, draft_id, 16*1024, cancel, kind="build")
                else:
                    import_id = value["recipe"]["importId"]
                    metadata_bytes = disk.size(self._folder(scope) / "imports" / (import_id + ".json")) + 16 * 1024
                    lease = self._claim(scope, import_id, metadata_bytes, cancel)
                directory = self._folder(scope) / "drafts" / draft_id
            lease.check()
            yield value, directory, lease
        finally:
            if lease is not None:
                lease.release()

    @host_errors
    def record_receipt(self, scope, draft_id, asset_id, revision, *, _lease=None):
        self._authorize(scope, True)
        with disk.coordinator(self.root):
            value = self._draft(scope, draft_id)
            is_build = value.get("kind") == "build"
            import_id = draft_id if is_build else value["recipe"]["importId"]
            lock = disk.read_json(self._folder(scope) / "locks" / (import_id + ".json"))
            if lock is not None and (_lease is None or lock.get("token") != _lease.token):
                raise busy()
            valid_asset = (asset_id == value["assetId"] if is_build else isinstance(asset_id, str) and
                           re.fullmatch(r"asset-import-[a-z0-9-]{1,40}-[a-f0-9]{24}", asset_id))
            if (not valid_asset
                    or not isinstance(revision, str) or not 1 <= len(revision) <= 128
                    or clean_text(revision, 128) != revision):
                raise FacilityLayoutError("model_receipt_invalid", "Supply a valid asset identity and revision.")
            existing = self._receipt(scope, draft_id)
            if existing is not None:
                if existing["assetId"] != asset_id or existing["revision"] != revision:
                    raise FacilityLayoutError("asset_identity_conflict", "This draft already has a different registration.")
                self._compact(scope, draft_id)
                return existing
            if _lease is None:
                self._capacity(scope, 4096)
            else:
                # hold_draft already reserved the receipt and its atomic copy.
                # Do not charge another 4 KiB on top of that peak reservation.
                needed = self._owned_size(_lease.data) + 4096
                if needed > _lease.data["reserved"]:
                    self._resize(_lease, needed)
            result = {"assetId": asset_id, "revision": revision, "at": time.time()}
            disk.atomic(self._folder(scope) / "registrations" / (draft_id + ".json"), result)
            self._compact(scope, draft_id)
            return result

    def _compact(self, scope, draft_id):
        directory = self._folder(scope) / "drafts" / draft_id
        for name in ("model.glb", "thumbnail.webp", "CREDITS.txt"):
            disk.remove(directory / name)

    def _trim(self, scope, record, maximum=20, cutoff=None):
        unregistered = sorted((d for d in record["drafts"] if self._receipt(scope, d["id"]) is None),
                              key=lambda d: (d["created"], d["id"]))
        remove = unregistered[:max(0, len(unregistered) - maximum)]
        if cutoff is not None:
            remove += [d for d in unregistered if d["created"] < cutoff and d not in remove]
        for item in remove:
            disk.remove(self._folder(scope) / "drafts" / item["id"])
            record["drafts"].remove(item)

    def _scope_stub(self, key):
        # Internal reconciliation uses only the prevalidated hash, never authorization bypass for public calls.
        class StoredScope:
            pass
        scope = StoredScope()
        scope.key = key
        return scope

    def reconcile(self):
        """Dead identities can be reclaimed; old live work must first be cancelled and joined."""
        if not self.root.exists():
            return
        with _OPERATIONS_LOCK:
            overdue = [v for (root, _), v in _OPERATIONS.items()
                       if root == str(self.root) and (v.ending or time.time() - v.data["created"] > STALE_SECONDS)]
        for operation in overdue:
            if operation.ending:
                operation.release()
                continue
            operation.cancel.set()
            callback = operation.cancel_upload
            if callback is not None:
                callback()
        deadline = time.monotonic() + 71
        for operation in overdue:
            operation.done.wait(max(0, deadline - time.monotonic()))  # Killed and joined before done.
        with disk.coordinator(self.root):
            active = self._active()
            for lease in active:
                if disk.live(lease):
                    continue
                folder = self.root / lease["scope"]
                disk.remove(folder / "jobs" / lease["token"])
                if lease.get("kind", "import") == "import":
                    disk.remove(folder / "uploads" / (lease["importId"] + ".part"))
                lock = folder / "locks" / (lease_key(lease) + ".json")
                if (disk.read_json(lock) or {}).get("token") == lease["token"]:
                    disk.remove(lock)
                disk.remove(self.root / "active" / (lease["token"] + ".json"))
            active = self._active()
            for folder in self.root.iterdir():
                if not folder.is_dir() or not SCOPE_KEY.fullmatch(folder.name):
                    continue
                disk.safe(folder)
                scope = self._scope_stub(folder.name)
                locks = {}
                for lock in (folder / "locks").glob("*.json"):
                    if not (IMPORT_ID.fullmatch(lock.stem) or DRAFT_ID.fullmatch(lock.stem) or BUILD_JOB_ID.fullmatch(lock.stem)):
                        continue
                    value = disk.read_json(lock)
                    if disk.live(value):
                        locks[lock.stem] = value
                    else:
                        disk.remove(lock)
                for file in (folder / "imports").glob("mi-*.json"):
                    if not IMPORT_ID.fullmatch(file.stem):
                        continue
                    record = self._record(scope, file.stem)
                    if record["id"] in locks:
                        continue
                    if record["state"] in ("queued", "checking"):
                        self._fail(scope, record, FacilityLayoutError(
                            "interrupted", "The check was interrupted. Retry or upload it again."), "failed")
                    # Recover a fully published folder if the process died before updating its import record.
                    old_drafts = record["drafts"]
                    record["drafts"] = [d for d in old_drafts if
                        (folder / "drafts" / d["id"]).is_dir() or self._receipt(scope, d["id"]) is not None]
                    known = {d["id"] for d in record["drafts"]}
                    changed = record["drafts"] != old_drafts
                    for draft_dir in (folder / "drafts").glob("md-*"):
                        if not DRAFT_ID.fullmatch(draft_dir.name) or draft_dir.name in known:
                            continue
                        draft = disk.read_json(draft_dir / "draft.json", DRAFT_BYTES)
                        if (isinstance(draft, dict) and draft.get("kind", "import") == "import"
                                and draft.get("recipe", {}).get("importId") == record["id"]):
                            try:
                                read_draft_output(disk.safe(draft_dir))
                            except ModelImportError:
                                continue
                            record["drafts"].append({"id": draft_dir.name, "created": draft_dir.stat().st_mtime})
                            changed = True
                    if changed:
                        self._trim(scope, record)
                        self._save(scope, record)
                unknown_lock = any(not isinstance(v, dict) or not TOKEN.fullmatch(str(v.get("token", "")))
                                   for v in locks.values())
                live_tokens = {v["token"] for v in active if v["scope"] == folder.name}
                live_tokens.update(v.get("token") for v in locks.values() if isinstance(v, dict))
                for job in (folder / "jobs").iterdir() if (folder / "jobs").is_dir() else ():
                    if not unknown_lock and TOKEN.fullmatch(job.name) and job.name not in live_tokens:
                        disk.remove(job)
                for upload in (folder / "uploads").glob("mi-*.part"):
                    if upload.stem not in locks:
                        disk.remove(upload)
                for directory in (folder / "imports", folder / "locks", folder / "registrations"):
                    for partial in directory.glob(".atomic-*"):
                        disk.remove(partial)
                if not unknown_lock:
                    self._source_gc(scope)
            for partial in (self.root / "active").glob(".atomic-*"):
                disk.remove(partial)

    def _source_gc(self, scope):
        references = set()
        for file in (self._folder(scope) / "imports").glob("mi-*.json"):
            record = disk.read_json(file)
            if (not isinstance(record, dict) or record.get("schemaVersion") != 1
                    or record.get("scope") != scope.key or record.get("id") != file.stem):
                return  # An unreadable record cannot authorize deleting a shared source.
            if record.get("sha256") and record.get("sourceFormat"):
                references.add(record["sha256"] + "." + record["sourceFormat"])
        for source in (self._folder(scope) / "sources").glob("*"):
            if re.fullmatch(r"[a-f0-9]{64}\.(glb|zip)", source.name) and source.name not in references:
                disk.remove(source)

    def sweep(self, *, now=None):
        if not self.root.exists():
            return
        self.reconcile()
        now = time.time() if now is None else now
        with disk.coordinator(self.root):
            for folder in self.root.iterdir():
                if not folder.is_dir() or not SCOPE_KEY.fullmatch(folder.name):
                    continue
                scope = self._scope_stub(folder.name)
                for file in (folder / "imports").glob("mi-*.json"):
                    if not IMPORT_ID.fullmatch(file.stem):
                        continue
                    record = self._record(scope, file.stem)
                    if (folder / "locks" / (record["id"] + ".json")).exists():
                        continue
                    self._trim(scope, record, cutoff=now - 7 * DAY)
                    receipts = [d for d in record["drafts"] if self._receipt(scope, d["id"]) is not None]
                    for item in receipts:
                        self._compact(scope, item["id"])
                    if record["state"] in ("refused", "failed") and record["updated"] < now - DAY and not receipts:
                        for item in record["drafts"]:
                            disk.remove(folder / "drafts" / item["id"])
                        disk.remove(folder / "inspections" / record["id"])
                        disk.remove(file)
                    else:
                        self._save(scope, record)
                self._source_gc(scope)

                from .model_build_store import trim
                trim(self, scope, now=now)

    def close(self):
        """Application shutdown: cancel owned work and wait for worker termination."""
        with _OPERATIONS_LOCK:
            operations = [v for (root, _), v in _OPERATIONS.items() if root == str(self.root)]
        for operation in operations:
            operation.cancel.set()
            callback = operation.cancel_upload
            if callback is not None:
                callback()
        for operation in operations:
            operation.done.wait(71)


def get_model_import_store(service) -> ModelImportStore:
    """The HTTP router and MI2/MI3 host hooks share this instance and trusted binding."""
    with _STORES_LOCK:
        value = getattr(service, "_model_import_store", None)
        if value is None:
            value = ModelImportStore(service.layout_repository.root, layout_reader=service.get_layout)
            service._model_import_store = value
        return value
