"""Sage's 3D shots (docs/sage-basic-shapes-plan.md, Part B: SV2 and SV3).

show_facility_views frames the views on the server (sage_views.py). When the turn came from an app window that has
the layout open, the gateway asks that window, through the turn's running step, to take the shots there (SV1,
workspace.captureSageViews), and waits here for them: the window posts the JPEGs to
POST /api/facility-layouts/{site}/{layout}/sage-shots/{requestId}, or posts no shots and why at once. The request id
is random and lives only while the tool waits, and only the principal the turn runs for can answer it.

Round 2 (Codex on 7279e45): the endpoint checks the request before it reads the form, and reads at most one 2 MB JPEG
per view; a shot's size is checked before it is decoded; a request the tool stopped waiting for while its shots were
being stored keeps none of them; the window gets the tool's wait (waitMs) and stops its capture after it.

The window's shots land in the host's store under sage-shots/.pending/{requestId}/. The tool keeps a set for the
chat's shots block, which links to it (SV2: the shots are saved with the conversation), with one rename to
sage-shots/{requestId}/, and only then gives Sage its contact sheet beside the tool's JSON (SV3) and the chat its row.
A set Sage and the chat were shown is never deleted: only .pending is swept, and a kept set is deleted only when its
tool gave up on it, so nobody saw it (final rounds 6 and 9). Every file access goes through _within: no link,
junction or other reparse point below the root is ever followed (final round 7). Final round 9: a keep's rename is
its commit point. Before it, closing the request (the tool, the app's shutdown) or the tool giving up wins, and
nothing is renamed; after it nothing takes the keep back, so what the tool shows is what is kept.
"""
from __future__ import annotations

import asyncio
from collections import deque
from copy import deepcopy
import io
import json
import logging
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import threading
import time
from typing import Any, Mapping, Sequence
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

SHOTS_MAX = 6                      # sage_views.MAX_VIEWS
SHOT_BYTES_MAX = 2_000_000
FORM_SPARE = 65536                 # the report and the form's own bytes, beside the JPEGs
SHOT_WIDTH, SHOT_HEIGHT = 1280, 720
WAIT_SECONDS = 60.0
SHEET_WIDTH = 1280                 # the contact sheet: every shot in one image, at most this wide
SHEET_LABEL = 26
SHEET_GAP = 4
SHEET_QUALITY = 80
REQUEST_ID = re.compile(r"[0-9a-f]{32}")
VIEW_KEYS = ("label", "from", "roofHidden", "camera")
REASONS = {  # why the window took no shots, or not all of them, in Sage's words
    "layout_not_open": "the app window shows another layout",
    "no_views": "the views had no camera the app could use",
    "busy": "the app window was taking other shots",
    "no_3d_view": "the app window could not open its 3D view",
    "no_canvas": "the app window's 3D view could not be copied",
    "interrupted": "the user pressed Back, left the 3D view or changed the layout while the shots were taken",
    "revision_differs": "the app window shows unsaved edits, a review or another revision of the layout",
    "timeout": "the app window did not send them in time",
    "no_app": "the chat is not in the app window that has the layout open",
    "failed": "the app window failed to take them",
    "invalid": "the app window sent pictures the server could not read",
    "closed": "the app was closing",
}


PENDING = ".pending"       # under the root: where shots land, and the only folder the sweep looks in
SWEEP_AFTER_SECONDS = 300  # a set in .pending this old, of no open request or read, is deleted by the next sweep
KEEP_TRIES = 5             # a keep's rename, tried again while Windows still holds a file of the set
KEEP_RETRY_SECONDS = 0.05


class ShotsRefused(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


def _resolve(answer: asyncio.Future, value: Any) -> None:
    if not answer.done():
        answer.set_result(value)


def _settle(loop: asyncio.AbstractEventLoop, future: asyncio.Future, value: Any) -> None:
    """Hand VALUE to FUTURE from another thread; nothing waits once its loop has closed."""
    try:
        loop.call_soon_threadsafe(_resolve, future, value)
    except RuntimeError:
        pass


def _plain(path: Path, folder: bool) -> bool:
    """PATH is a real folder (FOLDER) or a real file: not a symbolic link, a junction or another reparse point (lstat
    follows none of them)."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        return False
    return stat.S_ISDIR(info.st_mode) if folder else stat.S_ISREG(info.st_mode)


def _within(root: Path, folders: Sequence[str], file: str | None = None) -> Path | None:
    """ROOT/FOLDERS.../FILE, only when every level below ROOT is a real folder (FILE a real file) with no link,
    junction or other reparse point, and it resolves right where ROOT's own resolved path puts it. None otherwise,
    or when it does not exist. Every file access of the store goes through here (final round 7)."""
    path = Path(root)
    for name in folders:
        path = path / name
        if not _plain(path, True):
            return None
    if file is not None:
        path = path / file
        if not _plain(path, False):
            return None
    try:
        resolved = os.path.normcase(os.path.realpath(path))
        expected = os.path.normcase(os.path.join(os.path.realpath(root), *folders, *([file] if file else [])))
    except (OSError, ValueError):
        return None
    return path if resolved == expected else None


class SageShots:
    """The capture requests the gateway waits on, and the shots the app windows sent, under ROOT."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.pending_root = self.root / PENDING
        self._lock = threading.Lock()
        self._pending: dict[str, dict] = {}
        self._reading: dict[str, int] = {}   # request id -> reads still in images()
        self._abandoned: set[str] = set()    # shots to delete once their last read is done
        self._sweeping = False                # a backstop sweep is queued or running
        self._jobs: deque = deque()           # deletes and sweeps for the files thread, in order
        self._working = False                 # the files thread is running
        self._idle = threading.Event()        # set while the files thread has nothing to do
        self._idle.set()
        self._closed = False                  # the app is closing: no more shots are taken (shutdown)

    # -- the gateway's side

    def open(self, principal: Any, identity: Mapping, views: Sequence[Mapping],
             wait: float = WAIT_SECONDS) -> tuple[str, asyncio.Future]:
        """A new capture request for the views, and the future its answer lands in (in the running loop). The tool
        waits WAIT seconds for it; the window is told, and stops its capture after that."""
        self._sweep_soon()
        loop = asyncio.get_running_loop()
        answer = loop.create_future()
        request_id = secrets.token_hex(16)
        with self._lock:
            self._pending[request_id] = {
                "tenantId": principal.tenant_id, "principalId": principal.principal_id,
                "siteId": identity["siteId"], "layoutId": identity["layoutId"], "revision": identity["revision"],
                "views": [{key: deepcopy(view[key]) for key in VIEW_KEYS if key in view} for view in views[:SHOTS_MAX]],
                "waitMs": max(0, int(wait * 1000)), "loop": loop, "answer": answer,
                "answering": False, "stored": False, "closed": False}
            closing = self._closed
        if closing:   # the app is closing: nothing will answer it (final round 7)
            _resolve(answer, {"complete": False, "reason": "closed", "shots": []})
        return request_id, answer

    def close(self, request_id: str) -> None:
        """The tool stopped waiting: a window that answers later is refused, and what is left of the set in .pending
        is deleted (shots it did not keep: it timed out, was cancelled, even while they were being stored, or its
        keep failed). A kept set has left .pending already (keep), so nothing here can touch it (final round 6).
        Whatever still waits on the request is answered: closed (final round 7). A keep that has not come to its
        rename never starts it; one already renaming finishes, and its result stands (final round 9)."""
        with self._lock:
            pending = self._pending.pop(request_id, None)
            if pending is None:
                return
            pending["closed"] = True
            stored = pending["stored"]
        _settle(pending["loop"], pending["answer"], {"complete": False, "reason": "closed", "shots": []})
        if stored:
            self._drop(request_id)

    def shutdown(self, timeout: float = 2.0) -> bool:
        """The app is closing (final round 7): every open request is closed first, so whatever waits on it is
        answered and a window that answers later is refused (410); then the queued file jobs get at most TIMEOUT
        seconds. What is left in .pending is swept on a later start. True if the files thread is idle. From its first
        moment no keep starts its rename and none is taken; one already renaming finishes in that wait (round 9)."""
        with self._lock:
            self._closed = True
            open_ids = list(self._pending)
        for request_id in open_ids:
            self.close(request_id)
        return self.wait_idle(timeout)

    @property
    def closed(self) -> bool:
        return self._closed

    async def keep(self, request_id: str, timeout: float | None = None, *, deadline: float | None = None) -> str:
        """Keep the stored set of REQUEST_ID for the chat: one rename, .pending/ID to ID, in the files thread, waited
        for until DEADLINE: the tool call's one cutoff on time.monotonic() (the asyncio loop's clock), or TIMEOUT
        seconds from now, taken before the keep is queued. Only "kept" may show Sage and the chat the set. Final
        round 9: the rename is the keep's commit point (_move), and every answer is final: "kept"; or "failed", the
        rename failed and the set is deleted; "closed", the request was closed (say by the app closing) before the
        rename, so nothing was renamed; or "late", the tool gave up and shows nothing, and a set its rename kept
        meanwhile is deleted (_give_up). Final round 10: past the deadline the answer is "late", however the wait
        ended: another ready callback can hold the loop after the rename has answered in time and before this keep
        goes on."""
        if deadline is None:
            deadline = time.monotonic() + timeout
        with self._lock:
            pending = self._pending.get(request_id)
            if pending is None or pending["closed"] or self._closed:
                return "closed"
            if not pending["stored"]:
                return "failed"
            if time.monotonic() >= deadline:
                return "late"
            ticket = pending["keep"] = {"state": "queued"}   # queued, voided, committing, kept or failed (lock)
        loop = asyncio.get_running_loop()
        done = loop.create_future()
        self._background(lambda: self._move(request_id, ticket, loop, done))
        outcome = None
        try:
            outcome = await asyncio.wait_for(done, max(0.0, deadline - time.monotonic()))
            if time.monotonic() >= deadline:   # final round 10: wait_for does not look at the clock once it is done
                outcome = "late"
        except TimeoutError:
            outcome = "late"
        finally:
            if outcome in (None, "late"):   # too late, or cancelled: the tool shows nothing
                self._give_up(request_id, ticket)
        return outcome

    def _give_up(self, request_id: str, ticket: dict) -> None:
        """The tool stopped waiting for its keep, and shows nothing (final round 9). A keep that has not come to its
        rename never starts it: the set stays in .pending, and close() deletes it there. One that has finishes, and
        then one job in the files thread deletes the set wherever the rename left it (_discard)."""
        with self._lock:
            state = ticket["state"]
            if state == "queued":
                ticket["state"] = "voided"
        if state in ("committing", "kept"):
            self._background(lambda: self._discard(request_id, ticket))

    # -- deleting shots: only ever in the files thread

    def _drop(self, request_id: str) -> None:
        """Delete the shots of REQUEST_ID from .pending, in the files thread: the caller (the tool on the event loop
        with its cutoff running, the endpoint, a read) never waits for it. A delete asked for while images() still
        reads waits for that read (on Windows an open file cannot be deleted, and a read the tool stopped waiting
        for runs on). A set that is not deleted (a file another program holds, a delete still queued when the app
        stopped) stays in .pending, and a later sweep deletes it (final rounds 2 to 6)."""
        with self._lock:
            if self._reading.get(request_id):
                self._abandoned.add(request_id)
                return
            self._abandoned.discard(request_id)
        self._background(lambda: self._remove(request_id))

    def _remove(self, request_id: str) -> None:
        """The files thread's delete from .pending: a plain folder right inside it only, never a link or a junction,
        never a kept set (final round 6). The only other delete is _discard's, of a set nobody saw (final round 9)."""
        with self._lock:
            if self._reading.get(request_id):
                self._abandoned.add(request_id)
                return
        folder = _within(self.root, [PENDING, request_id])
        if folder is not None:
            shutil.rmtree(folder, ignore_errors=True)

    def _move(self, request_id: str, ticket: dict, loop: asyncio.AbstractEventLoop, done: asyncio.Future) -> None:
        """The files thread's keep (final round 9). The rename is its commit point. Right before it, under the lock,
        the keep goes ahead only while its tool still waits for it, its request is open with this keep and the app
        is not closing; otherwise nothing is renamed ("closed"), and the set is deleted from .pending there (close(),
        or a later sweep). Once it goes ahead nothing takes it back: the rename's result stands, "kept", or "failed"
        and the set is deleted from .pending at once."""
        with self._lock:
            pending = self._pending.get(request_id)
            go = (ticket["state"] == "queued" and not self._closed and pending is not None and not pending["closed"]
                  and pending.get("keep") is ticket)
            ticket["state"] = "committing" if go else "voided"
        if not go:
            _settle(loop, done, "closed")
            return
        source = _within(self.root, [PENDING, request_id])
        kept = bool(source is not None and not os.path.lexists(self.root / request_id)
                    and self._rename(source, self.root / request_id))
        with self._lock:
            ticket["state"] = "kept" if kept else "failed"
        if not kept:
            self._remove(request_id)
        _settle(loop, done, "kept" if kept else "failed")

    def _discard(self, request_id: str, ticket: dict) -> None:
        """The files thread's delete of a set whose tool gave up once its keep had come to the rename (final round
        9). It runs after the rename and deletes the set if the rename kept it (a failed rename's set is gone
        already). Nobody was shown it. If it cannot be deleted (a file another program holds), it stays and is
        logged: a set nobody saw, which no sweep looks for."""
        with self._lock:
            kept = ticket["state"] == "kept"
        folder = _within(self.root, [request_id]) if kept else None
        if folder is None:
            return
        shutil.rmtree(folder, ignore_errors=True)
        if os.path.lexists(folder):
            logging.getLogger(__name__).warning("Sage shots: could not delete %s, kept after its tool gave up",
                                                request_id)

    @staticmethod
    def _rename(source: Path, target: Path) -> bool:
        """One atomic rename of a set's folder, tried again briefly while Windows still holds one of its files (a
        virus scan, an indexer)."""
        for attempt in range(KEEP_TRIES):
            try:
                os.rename(source, target)
                return True
            except PermissionError:
                if attempt + 1 < KEEP_TRIES:
                    time.sleep(KEEP_RETRY_SECONDS)
            except OSError:
                break
        logging.getLogger(__name__).warning("Sage shots: could not move %s from %s to %s", source.name,
                                            source.parent.name, target.parent.name)
        return False

    def _sweep_soon(self) -> None:
        """Queue the backstop sweep for the files thread, unless one is queued or running."""
        with self._lock:
            if self._sweeping:
                return
            self._sweeping = True

        def run() -> None:
            try:
                self._sweep()
            finally:
                with self._lock:
                    self._sweeping = False
        self._background(run)

    def _sweep(self) -> None:
        """A backstop, in the files thread: delete every set in .pending older than SWEEP_AFTER_SECONDS that belongs
        to no open request or read (a delete still queued when the app stopped, a file another program held). Only
        .pending is looked at, and nothing in it is followed: a kept set is never touched (final round 6)."""
        if _within(self.root, [PENDING]) is None:
            return
        cutoff = time.time() - SWEEP_AFTER_SECONDS
        try:
            with os.scandir(self.pending_root) as entries:
                names = [entry.name for entry in entries if REQUEST_ID.fullmatch(entry.name)]
        except OSError:
            return
        for name in names:
            with self._lock:
                busy = name in self._pending or name in self._reading
            try:
                stale = not busy and os.lstat(self.pending_root / name).st_mtime < cutoff
            except OSError:
                continue
            if stale:
                self._remove(name)

    def _background(self, job: Any) -> None:
        """Run JOB in the files thread, after the jobs already queued; start the thread if it is not running."""
        with self._lock:
            self._jobs.append(job)
            self._idle.clear()
            if self._working:
                return
            self._working = True
        threading.Thread(target=self._work, name="sage-shots-files", daemon=True).start()

    def _work(self) -> None:
        while True:
            with self._lock:
                if not self._jobs:
                    self._working = False
                    self._idle.set()
                    return
                job = self._jobs.popleft()
            try:
                job()
            except Exception:  # a set not deleted stays in .pending and is swept later; the thread goes on
                logging.getLogger(__name__).exception("Sage shots: a file job failed")

    def wait_idle(self, timeout: float = 5.0) -> bool:
        """Wait until the files thread has nothing left to do (tests, shutdown); True if it is idle. A shutdown
        waits a bounded time: what is left in .pending is swept on a later start."""
        return self._idle.wait(timeout)

    def capture_request(self, request_id: str) -> dict:
        """What the running step hands the app window: captureSageViews' request, and where to post the shots."""
        with self._lock:
            pending = self._pending[request_id]
            return {"requestId": request_id, "siteId": pending["siteId"], "layoutId": pending["layoutId"],
                    "revision": pending["revision"], "views": deepcopy(pending["views"]),
                    "url": shots_url(pending["siteId"], pending["layoutId"], request_id),
                    "waitMs": pending["waitMs"]}

    # -- the app window's side

    def _waiting(self, request_id: str, principal: Any, site_id: str, layout_id: str) -> dict | None:
        """The request, if it waits for this principal's answer for this site and layout (under the lock)."""
        pending = self._pending.get(request_id) if REQUEST_ID.fullmatch(request_id or "") else None
        if (pending is None or pending["answering"] or pending["closed"] or pending["answer"].done()
                or pending["tenantId"] != principal.tenant_id or pending["principalId"] != principal.principal_id
                or pending["siteId"] != site_id or pending["layoutId"] != layout_id):
            return None
        return pending

    def expects(self, request_id: str, principal: Any, site_id: str, layout_id: str) -> int | None:
        """How many shots the request waits for, before its form is read; None when nothing waits for it."""
        with self._lock:
            pending = self._waiting(request_id, principal, site_id, layout_id)
            return len(pending["views"]) if pending else None

    def refuse(self, request_id: str, principal: Any, site_id: str, layout_id: str) -> None:
        """The window's answer could not be read (too large, not a form): the tool stops waiting, without shots."""
        with self._lock:
            pending = self._waiting(request_id, principal, site_id, layout_id)
            if pending is None:
                return
            pending["answering"] = True
        _settle(pending["loop"], pending["answer"], {"complete": False, "reason": "invalid", "shots": []})

    def answer(self, request_id: str, principal: Any, site_id: str, layout_id: str, report: Any,
               images: Sequence[bytes]) -> dict:
        """The shots the app window took (or why it took none). Each request is answered once. The request stays
        open while its shots are checked and stored, so the tool that stops waiting meanwhile (close) gets none:
        they are deleted and the window is told. Once it has claimed the request, every way out of here answers the
        tool's wait and removes what it wrote unless it was stored whole: refused shots (invalid), an unexpected
        error such as a full disk (failed), or a tool that stopped waiting (nothing to answer)."""
        with self._lock:
            if self._closed:
                raise ShotsRefused(410, "sage_shots_closed", "The app is closing: it takes no more 3D shots.")
            pending = self._waiting(request_id, principal, site_id, layout_id)
            if pending is None:
                raise ShotsRefused(404, "sage_shots_not_requested", "No 3D shots are waiting for this request.")
            pending["answering"] = True
        writing = False

        def undo(reason: str | None) -> None:
            if writing and not pending["stored"]:
                self._drop(request_id)
            if reason:
                _settle(pending["loop"], pending["answer"], {"complete": False, "reason": reason, "shots": []})
        try:
            shots, complete, reason = self._check(pending, report, images)
            with self._lock:
                if pending["closed"]:
                    raise ShotsRefused(410, "sage_shots_expired", "Sage stopped waiting for these 3D shots.")
            writing = True
            self._write(request_id, pending, shots)   # kept later by one rename out of .pending (keep)
            with self._lock:
                expired = pending["closed"]
                pending["stored"] = not expired
            if expired:
                raise ShotsRefused(410, "sage_shots_expired", "Sage stopped waiting for these 3D shots.")
        except ShotsRefused as exc:
            undo(None if exc.code == "sage_shots_expired" else "invalid")
            raise
        except BaseException:
            undo("failed")
            raise
        result = {"complete": complete, "reason": None if complete else (reason or "failed"),
                  "shots": [{key: shot[key] for key in ("index", "width", "height")} for shot in shots]}
        _settle(pending["loop"], pending["answer"], result)
        return {"accepted": len(result["shots"]), "complete": result["complete"]}

    def _check(self, pending: Mapping, report: Any, images: Sequence[bytes]) -> tuple[list, bool, str | None]:
        """The shots, checked: one JPEG of at most 2 MB and 1280 x 720 per listed view, its size read from its
        header before anything is decoded (a small file can hold a huge picture)."""
        from PIL import Image, UnidentifiedImageError

        report = report if isinstance(report, Mapping) else {}
        count = len(pending["views"])
        listed = report.get("shots") if isinstance(report.get("shots"), list) else []
        if len(images) > count or len(listed) != len(images):
            raise ShotsRefused(422, "sage_shots_invalid", "Send one report entry per shot, at most one per view.")
        indexes = [item.get("index") if isinstance(item, Mapping) else None for item in listed]
        if any(not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < count for index in indexes) \
                or indexes != sorted(set(indexes)):
            raise ShotsRefused(422, "sage_shots_invalid", "Each shot names its view's index, in order, once.")
        shots = []
        for index, data in zip(indexes, images):
            if not isinstance(data, (bytes, bytearray)) or not 0 < len(data) <= SHOT_BYTES_MAX \
                    or not bytes(data[:3]) == b"\xff\xd8\xff":
                raise ShotsRefused(422, "sage_shots_invalid", "Each shot is a JPEG of at most 2 MB.")
            try:
                with Image.open(io.BytesIO(data)) as image:
                    width, height = image.size
                    if image.format != "JPEG":
                        raise ValueError("not a JPEG")
                    if not (0 < width <= SHOT_WIDTH and 0 < height <= SHOT_HEIGHT):
                        raise ShotsRefused(422, "sage_shots_invalid", "Each shot is at most 1280 x 720.")
                    image.verify()
                with Image.open(io.BytesIO(data)) as image:
                    if image.size != (width, height):
                        raise ValueError("the size changed")
                    image.load()
            except ShotsRefused:
                raise
            except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError) as exc:
                raise ShotsRefused(422, "sage_shots_invalid", "A shot is not a readable JPEG.") from exc
            shots.append({"index": index, "width": width, "height": height, "data": bytes(data)})
        reason = report.get("reason")
        reason = reason if isinstance(reason, str) and reason in REASONS else None
        # Complete when the window says so and sent every shot: it then ends on the main view, with Back.
        complete = len(shots) == count and report.get("complete") is True
        return shots, complete, reason

    def _write(self, request_id: str, pending: Mapping, shots: Sequence[Mapping]) -> None:
        self.pending_root.mkdir(parents=True, exist_ok=True)
        if _within(self.root, [PENDING]) is None:
            raise OSError("The 3D shots folder is a link.")
        folder = self.pending_root / request_id
        folder.mkdir(exist_ok=False)
        if _within(self.root, [PENDING, request_id]) is None:
            raise OSError("The 3D shots folder is a link.")
        for shot in shots:
            (folder / f"{shot['index']}.jpg").write_bytes(shot["data"])
        record = {"tenantId": pending["tenantId"], "siteId": pending["siteId"], "layoutId": pending["layoutId"],
                  "revision": pending["revision"], "views": pending["views"],
                  "shots": [{key: shot[key] for key in ("index", "width", "height")} for shot in shots]}
        (folder / "set.json").write_bytes(json.dumps(record, indent=1).encode("utf-8"))

    # -- reading them back

    def shot_path(self, principal: Any, site_id: str, layout_id: str, request_id: str, index: int) -> Path | None:
        """The kept shot, if this principal's tenant took it of this site and layout. Only a kept set is read: the
        chat is shown a set only once it is kept (final round 6)."""
        if not REQUEST_ID.fullmatch(request_id or "") or not 0 <= index < SHOTS_MAX:
            return None
        found = _within(self.root, [request_id], "set.json")
        try:
            record = json.loads(found.read_bytes().decode("utf-8")) if found is not None else None
        except (OSError, ValueError):
            record = None
        if (not isinstance(record, dict) or record.get("tenantId") != principal.tenant_id
                or record.get("siteId") != site_id or record.get("layoutId") != layout_id):
            return None
        return _within(self.root, [request_id], f"{index}.jpg")

    def images(self, request_id: str, indexes: Sequence[int]) -> list[bytes]:
        """The stored shots, each read whole into memory (decoded later from bytes, so no file stays open). A delete
        asked for while this reads waits for it to finish, then runs (final round 2)."""
        with self._lock:
            self._reading[request_id] = self._reading.get(request_id, 0) + 1
        try:
            shots = []
            for index in indexes:
                path = _within(self.root, [PENDING, request_id], f"{index}.jpg")
                if path is None:
                    raise FileNotFoundError(f"No stored 3D shot {index}.")
                shots.append(path.read_bytes())
            return shots
        finally:
            with self._lock:
                left = self._reading.pop(request_id) - 1
                if left:
                    self._reading[request_id] = left
                late = not left and request_id in self._abandoned
            if late:
                self._drop(request_id)


def shots_url(site_id: str, layout_id: str, request_id: str) -> str:
    return f"/api/facility-layouts/{quote(site_id, safe='')}/{quote(layout_id, safe='')}/sage-shots/{request_id}"


def chat_block(request_id: str, identity: Mapping, views: Sequence[Mapping], shots: Sequence[Mapping]) -> dict:
    """The chat's row of shots (SV2): each links to its saved JPEG and carries its view, so a click moves the 3D
    view there."""
    base = shots_url(identity["siteId"], identity["layoutId"], request_id)
    return {"type": "shots", "siteId": identity["siteId"], "layoutId": identity["layoutId"],
            "revision": identity["revision"], "folded": False,
            "shots": [{"label": str(views[shot["index"]].get("label") or ""), "from": views[shot["index"]].get("from"),
                       "roofHidden": views[shot["index"]].get("roofHidden") is True,
                       "camera": deepcopy(views[shot["index"]].get("camera")),
                       "url": f"{base}/{shot['index']}.jpg", "width": shot["width"], "height": shot["height"]}
                      for shot in shots]}


def contact_sheet(images: Sequence[bytes], labels: Sequence[str]) -> bytes:
    """Every shot in one JPEG at most SHEET_WIDTH wide, each under its number and label: what Sage looks at, one
    picture to keep its tokens down."""
    from PIL import Image, ImageDraw, ImageFont

    columns = 1 if len(images) == 1 else 2
    width = SHEET_WIDTH // columns
    tiles = []
    for data in images:
        with Image.open(io.BytesIO(data)) as image:
            picture = image.convert("RGB")
        scale = min(1.0, width / picture.width)
        if scale < 1.0:
            picture = picture.resize((max(1, round(picture.width * scale)), max(1, round(picture.height * scale))),
                                     Image.Resampling.LANCZOS)
        tiles.append(picture)
    cell_width = max(tile.width for tile in tiles)
    cell_height = max(tile.height for tile in tiles) + SHEET_LABEL
    rows = math.ceil(len(tiles) / columns)
    sheet = Image.new("RGB", (columns * cell_width + (columns - 1) * SHEET_GAP,
                              rows * cell_height + (rows - 1) * SHEET_GAP), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default(size=16)
    except TypeError:  # an older Pillow: the bitmap font
        font = ImageFont.load_default()
    for number, (tile, label) in enumerate(zip(tiles, labels)):
        x = (number % columns) * (cell_width + SHEET_GAP)
        y = (number // columns) * (cell_height + SHEET_GAP)
        draw.text((x + 6, y + 4), str(label)[:90], fill=(20, 20, 20), font=font)
        sheet.paste(tile, (x, y + SHEET_LABEL))
    out = io.BytesIO()
    sheet.save(out, "JPEG", quality=SHEET_QUALITY)
    return out.getvalue()


def create_sage_shots_router(*, shots: SageShots, principal_resolver):
    from .authorization import require_facility_action
    from .errors import FacilityLayoutError

    router = APIRouter()

    @router.post("/api/facility-layouts/{site_id}/{layout_id}/sage-shots/{request_id}")
    async def post_shots(site_id: str, layout_id: str, request_id: str, request: Request):
        try:
            principal = principal_resolver(request)
        except FacilityLayoutError as exc:
            return JSONResponse(status_code=exc.status_code, content={"error": exc.to_dict()})
        # Nothing is read before the request is known to wait for this principal's shots of this layout, and then
        # at most one 2 MB JPEG per view (round 2: a form's file parts have no size limit of their own).
        if shots.closed:
            return JSONResponse(status_code=410, content={"error": {
                "code": "sage_shots_closed", "message": "The app is closing: it takes no more 3D shots."}})
        count = shots.expects(request_id, principal, site_id, layout_id)
        if count is None:
            return JSONResponse(status_code=404, content={"error": {
                "code": "sage_shots_not_requested", "message": "No 3D shots are waiting for this request."}})
        # Round 3: from here every way out answers the request once. answer() does it for the shots it takes or
        # refuses; any other exit (too large, not a form, a shot that is not a file, an error) refuses it in the
        # finally, which does nothing once the request was answered. The tool never waits on a request that failed.
        form = None
        try:
            limit = count * SHOT_BYTES_MAX + FORM_SPARE
            declared = request.headers.get("content-length")
            if declared is not None and (not declared.isdigit() or int(declared) > limit):
                raise ShotsRefused(413, "sage_shots_too_large", "Send at most one JPEG of 2 MB per view.")
            body = bytearray()
            async for chunk in request.stream():
                body += chunk
                if len(body) > limit:
                    raise ShotsRefused(413, "sage_shots_too_large", "Send at most one JPEG of 2 MB per view.")

            async def replay():
                return {"type": "http.request", "body": bytes(body), "more_body": False}

            try:
                form = await Request(request.scope, replay).form(max_files=SHOTS_MAX, max_fields=4,
                                                               max_part_size=FORM_SPARE)
            except Exception as exc:  # noqa: BLE001 -- a malformed form
                raise ShotsRefused(422, "sage_shots_invalid", "Send the shots as a form: report, then each shot.") \
                    from exc
            raw = form.get("report")
            try:
                report = json.loads(raw) if isinstance(raw, str) and len(raw) <= 20000 else None
            except ValueError:
                report = None
            images = []
            for item in form.getlist("shot"):
                if isinstance(item, str):
                    raise ShotsRefused(422, "sage_shots_invalid", "Each shot is a file.")
                data = await item.read(SHOT_BYTES_MAX + 1)
                images.append(data)
            result = await run_in_threadpool(shots.answer, request_id, principal, site_id, layout_id, report,
                                             images)
        except ShotsRefused as exc:
            return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": str(exc)}})
        finally:
            try:
                if form is not None:
                    await form.close()
            finally:
                await run_in_threadpool(shots.refuse, request_id, principal, site_id, layout_id)
        return JSONResponse(content=result, headers={"Cache-Control": "no-store"})

    @router.get("/api/facility-layouts/{site_id}/{layout_id}/sage-shots/{request_id}/{index}.jpg")
    async def get_shot(site_id: str, layout_id: str, request_id: str, index: int, request: Request):
        try:
            principal = principal_resolver(request)
            require_facility_action(principal, tenant_id=principal.tenant_id, site_id=site_id, action="layout.read")
        except FacilityLayoutError as exc:
            return JSONResponse(status_code=exc.status_code, content={"error": exc.to_dict()})
        path = await run_in_threadpool(shots.shot_path, principal, site_id, layout_id, request_id, index)
        if path is None:
            return JSONResponse(status_code=404, content={"error": {
                "code": "sage_shot_not_found", "message": "No such 3D shot."}})
        # A saved shot never changes: its request id is new for every set.
        return FileResponse(path, media_type="image/jpeg", headers={
            "Cache-Control": "private, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"})

    return router
