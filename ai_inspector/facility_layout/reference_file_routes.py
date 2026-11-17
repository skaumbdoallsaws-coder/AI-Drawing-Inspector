"""Streamed, scoped reference intake and read-only page routes."""
import asyncio
import contextlib
import logging
from urllib.parse import unquote

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .errors import FacilityLayoutError
from .model_import_store import ModelImportScope, STALE_SECONDS
from .reference_files import get_reference_store

BASE = "/api/facility-layouts/{site_id}/{layout_id}/reference-files"
HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}
LOGGER = logging.getLogger(__name__)


def create_reference_file_router(*, service, principal_resolver, feature_gate=None, store=None):
    router = APIRouter()
    store = store or get_reference_store(service)
    maintenance = None

    def scope(request, site_id, layout_id):
        return ModelImportScope(principal_resolver(request), site_id, layout_id)

    def error(error):
        return JSONResponse({"error": error.to_dict()}, status_code=error.status_code, headers=HEADERS)

    async def sweep_periodically():
        while True:
            try:
                await run_in_threadpool(store.sweep)
            except (FacilityLayoutError, OSError):
                LOGGER.warning("Reference sweep deferred; storage is busy or unavailable.")
            await asyncio.sleep(3600)

    @router.on_event("startup")
    async def start():
        nonlocal maintenance
        maintenance = asyncio.create_task(sweep_periodically())

    @router.on_event("shutdown")
    async def stop():
        if maintenance:
            maintenance.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await maintenance
        await run_in_threadpool(store.close)

    @router.post(BASE)
    async def upload(site_id: str, layout_id: str, request: Request):
        upload = None
        try:
            if feature_gate:
                feature_gate("manual_edit")
            raw_length = request.headers.get("content-length")
            if raw_length is not None and (not raw_length.isascii() or not raw_length.isdigit() or len(raw_length) > 12):
                raise FacilityLayoutError("reference_upload_length", "Content-Length must be a non-negative integer.", status_code=400)
            upload = await run_in_threadpool(store.begin_upload, scope(request, site_id, layout_id),
                                             unquote(request.headers.get("x-reference-name", "")),
                                             int(raw_length) if raw_length is not None else None)
            async with asyncio.timeout(STALE_SECONDS):
                async for chunk in request.stream():
                    await run_in_threadpool(upload.write, chunk)
            result = await run_in_threadpool(upload.finish)
            return JSONResponse(result, status_code=202, headers=HEADERS)
        except TimeoutError:
            return error(FacilityLayoutError("reference_timeout", "The reference upload timed out.", status_code=422))
        except FacilityLayoutError as exc:
            return error(exc)
        finally:
            if upload is not None:
                task = asyncio.create_task(run_in_threadpool(upload.abort))
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        continue
                task.result()

    @router.get(BASE + "/{reference_id}")
    async def record(site_id: str, layout_id: str, reference_id: str, request: Request):
        try:
            value = await run_in_threadpool(store.get, scope(request, site_id, layout_id), reference_id)
            return JSONResponse(value, headers=HEADERS)
        except FacilityLayoutError as exc:
            return error(exc)

    @router.get(BASE + "/{reference_id}/pages/{page}")
    async def page(site_id: str, layout_id: str, reference_id: str, page: int, request: Request):
        try:
            data, _ = await run_in_threadpool(store.page, scope(request, site_id, layout_id), reference_id, page)
            return Response(data, media_type="image/png", headers=HEADERS)
        except FacilityLayoutError as exc:
            return error(exc)

    return router
