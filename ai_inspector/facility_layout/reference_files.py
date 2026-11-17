"""Site-scoped reference intake, pins, and comparison views.

No untrusted image or PDF is decoded here. A contained worker writes checked,
metadata-free PNG pages; only those pages enter the persistent blob directory.
"""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
import os
import re
import threading
import time
import uuid

from . import model_import_files as disk
from .errors import FacilityLayoutError
from .model_import_store import ModelImportScope, get_model_import_store
from ..industrial_assets.model_builder.errors import ModelBuildError
from ..industrial_assets.model_builder.imports import module
from ..industrial_assets.model_reference_runner import run_reference

ID = re.compile(r"rf-[0-9a-f]{24}")
HASH = re.compile(r"[0-9a-f]{64}")
MAX_UPLOAD = 25 * 1024 * 1024
SITE_BYTES = 200 * 1024 * 1024
RESERVATION = 70 * 1024 * 1024
DAY = 86400
# One picture in a Sage tool result (codex_runtime.model_import_tools.PICTURE_BYTES; a test pins them equal).
SAGE_PICTURE_BYTES = 1536 * 1024


def _fail(code, message, status=422):
    raise FacilityLayoutError(code, message, status_code=status)


def _kind(head):
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image"
    if head.startswith(b"\xff\xd8\xff"):
        return "image"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image"
    _fail("reference_invalid", "Choose a PNG, JPEG or WebP image, or an enabled PDF.")


class ReferenceUpload:
    def __init__(self, store, scope, identifier, name, job, declared):
        self.store, self.scope, self.identifier, self.name = store, scope, identifier, name
        self.job, self.declared = job, declared
        self.length = 0
        self.closed = False
        self.finished = False
        self.stream = disk.safe(job / "source.bin").open("xb")

    def write(self, chunk):
        if self.closed or not isinstance(chunk, bytes):
            _fail("reference_upload_invalid", "The reference upload is no longer active.")
        self.length += len(chunk)
        if self.length > MAX_UPLOAD:
            _fail("reference_limit", "Reference files must be at most 25 MB.", 413)
        self.stream.write(chunk)

    def finish(self):
        if self.closed:
            _fail("reference_upload_invalid", "The reference upload is no longer active.")
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.stream.close()
        self.closed = True
        if not self.length or self.declared is not None and self.length != self.declared:
            _fail("reference_upload_invalid", "The reference upload length differs from its body.")
        with (self.job / "source.bin").open("rb") as source:
            kind = _kind(source.read(16))
        if kind == "pdf" and not self.store.reference_pdf:
            _fail("reference_pdf_disabled", "PDF reading is not enabled; attach a screenshot of the page.")
        request = disk.encode({"pdf": kind == "pdf"})
        with disk.safe(self.job / "request.json").open("xb") as output:
            output.write(request)
        self.store._set_state(self.scope, self.identifier, "processing")
        self.store._submit(self.scope, self.identifier, self.job, kind)
        self.finished = True
        return self.store.get(self.scope, self.identifier)

    def abort(self):
        if self.finished:
            return
        if not self.closed:
            self.stream.close()
            self.closed = True
        self.store._discard(self.scope, self.identifier, self.job)


class ReferenceStore:
    def __init__(self, service, *, reference_pdf=False, runner=run_reference, dependency_root=None):
        self.service = service
        self.imports = get_model_import_store(service)
        self.root = disk.safe(Path(service.layout_repository.root).absolute() / "reference-files")
        self.reference_pdf = bool(reference_pdf)
        self.runner = runner
        self.dependency_root = dependency_root
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="reference-intake")
        self._active = {}
        self._lock = threading.Lock()

    def _authorize(self, scope, write=False):
        self.imports._authorize(scope, write)
        disk.mkdir(self.root)

    def _folder(self, scope):
        return disk.safe(self.root / scope.key)

    def _path(self, scope, identifier):
        if not isinstance(identifier, str) or not ID.fullmatch(identifier):
            _fail("reference_missing", "Reference file not found for this site.", 404)
        return disk.safe(self._folder(scope) / "records" / (identifier + ".json"))

    def _record(self, scope, identifier):
        value = disk.read_json(self._path(scope, identifier), 512*1024)
        if not isinstance(value, dict) or value.get("referenceId") != identifier or value.get("scope") != scope.key:
            _fail("reference_missing", "Reference file not found for this site.", 404)
        return value

    def _space(self, scope):
        folder = self._folder(scope)
        used = disk.size(folder)
        for path in (folder / "reservations").glob("*.json"):
            row = disk.read_json(path, 1024)
            if not isinstance(row, dict) or row.get("reserved") != RESERVATION:
                _fail("reference_store_invalid", "Reference reservations need repair.", 503)
            used += max(0, RESERVATION - disk.size(folder / "jobs" / path.stem))
        return used

    def begin_upload(self, scope, name, content_length=None):
        self._authorize(scope, True)
        if content_length is not None and (type(content_length) is not int or not 0 <= content_length <= MAX_UPLOAD):
            _fail("reference_limit", "Reference files must be at most 25 MB.", 413)
        clean = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
        clean = "".join(ch for ch in clean if 32 <= ord(ch) < 127)[:80] or "reference"
        with disk.coordinator(self.root):
            folder = self._folder(scope)
            count = len(list((folder / "records").glob("rf-*.json")))
            if count >= 100 or self._space(scope) + RESERVATION > SITE_BYTES:
                _fail("reference_quota", "This site's reference files reached the 100-file or 200 MB limit.", 507)
            identifier = "rf-" + uuid.uuid4().hex[:24]
            job = disk.mkdir(folder / "jobs" / identifier)
            disk.atomic(folder / "reservations" / (identifier + ".json"),
                        {"reserved": RESERVATION, **disk.owner()})
            now = time.time()
            disk.atomic(self._path(scope, identifier), {"referenceId": identifier, "scope": scope.key,
                "name": clean, "kind": None, "state": "uploading", "pages": 0, "renderedPages": [],
                "sourceSha256": None, "created": now, "updated": now, "pins": []})
        return ReferenceUpload(self, scope, identifier, clean, job, content_length)

    def _set_state(self, scope, identifier, state, **changes):
        with disk.coordinator(self.root):
            row = self._record(scope, identifier)
            row.update(state=state, updated=time.time(), **changes)
            disk.atomic(self._path(scope, identifier), row)

    def _discard(self, scope, identifier, job):
        with disk.coordinator(self.root):
            disk.remove(job)
            disk.remove(self._folder(scope) / "reservations" / (identifier + ".json"))
            disk.remove(self._path(scope, identifier))

    def _submit(self, scope, identifier, job, kind):
        cancel = threading.Event()
        with self._lock:
            self._active[identifier] = cancel
        self.executor.submit(self._process, scope, identifier, job, kind, cancel)

    def _process(self, scope, identifier, job, kind, cancel):
        try:
            dependencies = self.dependency_root or self.imports._dependencies()
            result = self.runner(job, dependencies, pdf=kind == "pdf", cancel_event=cancel)
            if cancel.is_set():
                _fail("reference_cancelled", "The reference intake was cancelled.")
            with disk.coordinator(self.root):
                row = self._record(scope, identifier)
                folder = self._folder(scope)
                for page in result["renderedPages"]:
                    source = disk.safe(job / "pages" / (str(page["page"]) + ".png"))
                    target = disk.safe(folder / "blobs" / (page["sha256"] + ".png"))
                    disk.mkdir(target.parent)
                    if target.exists():
                        if sha256(target.read_bytes()).hexdigest() != page["sha256"]:
                            _fail("reference_store_invalid", "A reference blob differs from its digest.", 503)
                    else:
                        os.replace(source, target)
                row.update(kind=result["kind"], pages=result["pages"], renderedPages=result["renderedPages"],
                           sourceSha256=result["sourceSha256"], state="ready", updated=time.time())
                disk.atomic(self._path(scope, identifier), row)
        except Exception as error:
            code = getattr(error, "code", "reference_failed")
            message = (error.message if isinstance(error, (FacilityLayoutError, ModelBuildError)) else
                       "The reference file could not be prepared.")
            try:
                self._set_state(scope, identifier, "failed", refusal={"code": code, "message": message})
            except (FacilityLayoutError, OSError):
                pass
        finally:
            with disk.coordinator(self.root):
                disk.remove(job)
                disk.remove(self._folder(scope) / "reservations" / (identifier + ".json"))
            with self._lock:
                self._active.pop(identifier, None)

    def get(self, scope, identifier):
        self._authorize(scope)
        with disk.coordinator(self.root):
            row = self._record(scope, identifier)
            if row["created"] < time.time()-7*DAY and not row["pins"]:
                _fail("reference_missing", "Reference file not found for this site.", 404)
            value = {key: row[key] for key in ("referenceId", "name", "kind", "pages", "state", "created", "updated")}
            if row.get("refusal"):
                value["refusal"] = row["refusal"]
            return value

    def page(self, scope, identifier, number=0):
        self._authorize(scope)
        with disk.coordinator(self.root):
            row = self._record(scope, identifier)
            if row["created"] < time.time()-7*DAY and not row["pins"]:
                _fail("reference_missing", "Reference file not found for this site.", 404)
            if row["state"] != "ready" or type(number) is not int or not 0 <= number < len(row["renderedPages"]):
                _fail("reference_page_missing", "That reference page is unavailable.", 404)
            entry = row["renderedPages"][number]
            source = disk.safe(self._folder(scope) / "blobs" / (entry["sha256"] + ".png"))
            payload = source.read_bytes()
            if len(payload) != entry["bytes"] or sha256(payload).hexdigest() != entry["sha256"]:
                _fail("reference_store_invalid", "Reference page bytes changed.", 503)
            return payload, {"referenceId": identifier, "name": row["name"], "kind": row["kind"],
                             "pages": row["pages"], "page": number, "text": entry["text"],
                             "sha256": entry["sha256"], "state": row["state"]}

    def sage_page(self, scope, identifier, number=0):
        """The page as Sage sees it: the stored page when it fits one tool picture, else a smaller RGB copy.

        Stored pages are this store's own digest-checked worker output, never the uploaded bytes. The stored
        page and the browser route keep full size; vision models scale large pictures down anyway.
        """
        payload, details = self.page(scope, identifier, number)
        if len(payload) <= SAGE_PICTURE_BYTES:
            return payload, details
        from io import BytesIO
        from PIL import Image
        with Image.open(BytesIO(payload)) as stored:
            image = stored.convert("RGB")
        scale = min(1.0, 1600 / max(image.size))
        while True:
            size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
            output = BytesIO()
            image.resize(size, Image.Resampling.LANCZOS).save(output, format="PNG")
            if len(output.getvalue()) <= SAGE_PICTURE_BYTES or max(size) <= 256:
                break
            scale *= 0.85
        if len(output.getvalue()) > SAGE_PICTURE_BYTES:
            _fail("reference_limit", "That reference page is too detailed to show.")
        return output.getvalue(), {**details, "shownWidth": size[0], "shownHeight": size[1]}

    def list(self, scope):
        self._authorize(scope)
        with disk.coordinator(self.root):
            rows = []
            for path in (self._folder(scope) / "records").glob("rf-*.json"):
                row = disk.read_json(path, 512*1024)
                if (isinstance(row, dict) and row.get("scope") == scope.key and row.get("state") == "ready"
                        and (row.get("created", 0) >= time.time()-7*DAY or row.get("pins"))):
                    rows.append({key: row[key] for key in ("referenceId", "name", "kind", "pages", "state", "created")})
            return sorted(rows, key=lambda row: (row["created"], row["referenceId"]), reverse=True)[:20]

    def compare(self, scope, draft_id, reference_id, page=0):
        """Cache one bounded side-by-side picture outside the frozen model draft."""
        from io import BytesIO
        from PIL import Image, ImageDraw, ImageOps
        self._authorize(scope)
        photo, info = self.page(scope, reference_id, page)
        source = self.imports.preview(scope, draft_id, draft=True)
        digest = sha256(source + info["sha256"].encode() + str(page).encode() + b"compare-1").hexdigest()[:24]
        target = disk.safe(self._folder(scope) / "views" / draft_id / (digest + ".png"))
        with disk.coordinator(self.root):
            if target.exists():
                data = target.read_bytes()
                if len(data) <= 1536*1024:
                    return data
        with Image.open(BytesIO(photo)) as original, Image.open(BytesIO(source)) as sheet:
            canvas = Image.new("RGB", (1536, 768), "#f8fafc")
            left = ImageOps.contain(original.convert("RGB"), (744, 744), Image.Resampling.LANCZOS)
            canvas.paste(left, ((768-left.width)//2, (768-left.height)//2))
            front = sheet.crop((0, 0, 384, 384))
            quarter = sheet.crop((384, 384, 768, 768))
            canvas.paste(front, (768, 192))
            canvas.paste(quarter, (1152, 192))
            draw = ImageDraw.Draw(canvas)
            draw.text((774, 176), "Front", fill="#263238")
            draw.text((1158, 176), "Three-quarter", fill="#263238")
            reduced = canvas.quantize(colors=256, method=Image.Quantize.FASTOCTREE)
            output = BytesIO()
            reduced.save(output, format="PNG", optimize=True)
            picture = output.getvalue()
        if len(picture) > 1536*1024:
            _fail("reference_limit", "The comparison picture exceeds 1.5 MB.")
        with disk.coordinator(self.root):
            if self._space(scope) + len(picture) + 4096 > SITE_BYTES:
                _fail("reference_quota", "This site's reference files reached the 200 MB limit.", 507)
            disk.mkdir(target.parent)
            if not target.exists():
                with disk.safe(target.parent / (".comparison-" + uuid.uuid4().hex)).open("xb") as stream:
                    temporary = Path(stream.name)
                    stream.write(picture)
                os.replace(temporary, target)
            views = sorted(target.parent.glob("*.png"), key=lambda p: (p.stat().st_mtime_ns, p.name))
            for stale in views[:-8]:
                disk.remove(stale)
            selection = self._folder(scope) / "draft-pages" / (draft_id + ".json")
            selected = disk.read_json(selection, 4096) or {}
            selected[reference_id] = page
            disk.atomic(selection, selected)
        return picture

    def pin(self, scope, identifiers, pin):
        self._authorize(scope, True)
        with disk.coordinator(self.root):
            rows = [self._record(scope, identifier) for identifier in identifiers]
            if any(row["state"] != "ready" or row["created"] < time.time()-7*DAY and not row["pins"]
                   for row in rows):
                _fail("reference_not_ready", "Wait for each reference to be ready before building.")
            for row in rows:
                if pin not in row["pins"]:
                    row["pins"].append(pin)
                    row["updated"] = time.time()
                    disk.atomic(self._path(scope, row["referenceId"]), row)

    def unpin(self, scope, identifiers, pin):
        with disk.coordinator(self.root):
            for identifier in identifiers:
                row = self._record(scope, identifier)
                if pin in row["pins"]:
                    row["pins"].remove(pin)
                    disk.atomic(self._path(scope, identifier), row)

    def draft_references(self, scope, draft_id, fallback=()):
        self._authorize(scope)
        with disk.coordinator(self.root):
            value = disk.read_json(self._folder(scope) / "draft-refs" / (draft_id + ".json"), 4096)
            return value if isinstance(value, list) else list(fallback)

    def pin_draft(self, scope, draft_id, identifiers):
        self._authorize(scope, True)
        with disk.coordinator(self.root):
            target = self._folder(scope) / "draft-refs" / (draft_id + ".json")
            previous = disk.read_json(target, 4096) or []
            combined = list(dict.fromkeys([*previous, *identifiers]))
            registered = disk.read_json(self._folder(scope) / "provenance" / (draft_id + ".json"), 4096) or []
            if len({*[row["referenceId"] for row in registered], *combined}) > 3:
                _fail("reference_limit", "A built draft can retain at most three reference files.")
            rows = [self._record(scope, identifier) for identifier in combined]
            if any(row["state"] != "ready" for row in rows):
                _fail("reference_not_ready", "Wait for each reference to be ready before building.")
            for row in rows:
                if draft_id not in row["pins"]:
                    row["pins"].append(draft_id)
                    disk.atomic(self._path(scope, row["referenceId"]), row)
            disk.atomic(target, combined)
            return combined

    def registered(self, scope, draft_id, identifiers, page_map=None):
        self._authorize(scope, True)
        with disk.coordinator(self.root):
            target = self._folder(scope) / "provenance" / (draft_id + ".json")
            pending = disk.read_json(self._folder(scope) / "draft-refs" / (draft_id + ".json"), 4096)
            if target.exists() and not pending:
                return disk.read_json(target, 4096)
            identifiers = pending or identifiers
            page_map = page_map or disk.read_json(self._folder(scope) / "draft-pages" / (draft_id + ".json"), 4096) or {}
            rows = [self._record(scope, identifier) for identifier in identifiers]
            record = disk.read_json(target, 4096) if target.exists() else []
            seen = {item["referenceId"] for item in record}
            for row in rows:
                if row["referenceId"] not in seen:
                    record.append({"referenceId": row["referenceId"], "kind": row["kind"],
                                   "sha256": row["sourceSha256"], "page": page_map.get(row["referenceId"], 0)})
            disk.atomic(target, record)
            for row in rows:
                if draft_id in row["pins"]:
                    row["pins"].remove(draft_id)
                    disk.atomic(self._path(scope, row["referenceId"]), row)
            disk.remove(self._folder(scope) / "draft-pages" / (draft_id + ".json"))
            disk.remove(self._folder(scope) / "draft-refs" / (draft_id + ".json"))

    def sweep(self, now=None):
        if not self.root.exists():
            return
        now = time.time() if now is None else now
        with disk.coordinator(self.root):
            for folder in self.root.iterdir():
                if not folder.is_dir() or not re.fullmatch(r"[0-9a-f]{24}", folder.name):
                    continue
                for reservation in (folder / "reservations").glob("rf-*.json"):
                    owner = disk.read_json(reservation, 1024)
                    if isinstance(owner, dict) and not disk.live(owner):
                        record_path = folder / "records" / reservation.name
                        row = disk.read_json(record_path, 512*1024)
                        if isinstance(row, dict) and row.get("state") in {"uploading", "processing"}:
                            row.update(state="failed", updated=now,
                                       refusal={"code": "reference_failed", "message": "The intake was interrupted."})
                            disk.atomic(record_path, row)
                        disk.remove(folder / "jobs" / reservation.stem)
                        disk.remove(reservation)
                references = set()
                for path in (folder / "records").glob("rf-*.json"):
                    row = disk.read_json(path, 512*1024)
                    if not isinstance(row, dict) or row.get("referenceId") != path.stem:
                        continue  # Corruption never authorizes deleting a blob.
                    retained = []
                    for pin in row["pins"]:
                        if pin.startswith("job-"):
                            if row["updated"] >= now-DAY:
                                retained.append(pin)
                        elif re.fullmatch(r"md-[0-9a-f]{24}", pin):
                            draft = disk.read_json(self.imports.root / folder.name / "drafts" / pin / "draft.json", 1024*1024)
                            if (isinstance(draft, dict) and draft.get("expires", 0) > now and
                                    not (folder / "provenance" / (pin + ".json")).exists()):
                                retained.append(pin)
                    if retained != row["pins"]:
                        row["pins"] = retained
                        disk.atomic(path, row)
                    if row["created"] < now-7*DAY and not row["pins"]:
                        disk.remove(path)
                        disk.remove(folder / "views" / row["referenceId"])
                        continue
                    references.update(page["sha256"] for page in row["renderedPages"])
                for path in [*(folder / "draft-refs").glob("md-*.json"), *(folder / "draft-pages").glob("md-*.json")]:
                    draft = disk.read_json(self.imports.root / folder.name / "drafts" / path.stem / "draft.json", 1024*1024)
                    if not isinstance(draft, dict) or draft.get("expires", 0) <= now:
                        disk.remove(path)
                for view in (folder / "views").glob("md-*"):
                    draft = disk.read_json(self.imports.root / folder.name / "drafts" / view.name / "draft.json", 1024*1024)
                    if not isinstance(draft, dict) or draft.get("expires", 0) <= now:
                        disk.remove(view)
                for path in (folder / "blobs").glob("*.png"):
                    if HASH.fullmatch(path.stem) and path.stem not in references:
                        disk.remove(path)

    def close(self):
        with self._lock:
            events = list(self._active.values())
        for event in events:
            event.set()
        self.executor.shutdown(wait=True, cancel_futures=True)


_LOCK = threading.Lock()


def get_reference_store(service):
    with _LOCK:
        value = getattr(service, "_reference_store", None)
        if value is None:
            value = ReferenceStore(service)
            service._reference_store = value
        return value
