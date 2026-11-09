"""Scoped raw-body model uploads and polling; worker work never delays the upload response."""
import asyncio
import contextlib
import logging
from urllib.parse import unquote

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .errors import FacilityLayoutError
from .model_import_store import ModelImportScope, STALE_SECONDS, get_model_import_store

BASE = "/api/facility-layouts/{site_id}/{layout_id}"
PREFIX = BASE + "/model-imports"
LOGGER = logging.getLogger(__name__)
HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


def create_model_import_router(*, service, principal_resolver, feature_gate=None, store=None):
    router = APIRouter()
    store = store or get_model_import_store(service)
    maintenance = None

    def scope(request, site_id, layout_id):
        return ModelImportScope(principal_resolver(request), site_id, layout_id)

    def error_response(error):
        return JSONResponse({"error": error.to_dict()}, status_code=error.status_code, headers=HEADERS)

    async def sweep_periodically():
        while True:
            delay = 3600
            try:
                await run_in_threadpool(store.sweep)
            except (FacilityLayoutError, OSError):
                LOGGER.warning("Model import sweep deferred; storage is busy or unavailable.")
                delay = 60
            await asyncio.sleep(delay)

    @router.on_event("startup")
    async def start():
        nonlocal maintenance
        maintenance = asyncio.create_task(sweep_periodically())

    @router.on_event("shutdown")
    async def stop():
        try:
            if maintenance:
                maintenance.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await maintenance
        finally:
            await run_in_threadpool(store.close)

    @router.post(PREFIX)
    async def upload_model(site_id: str, layout_id: str, request: Request):
        upload = None
        try:
            if feature_gate:
                feature_gate("manual_edit")
            bound = scope(request, site_id, layout_id)
            raw_length = request.headers.get("content-length")
            if raw_length is not None and (not raw_length.isascii() or not raw_length.isdigit() or len(raw_length) > 12):
                raise FacilityLayoutError("model_upload_length", "Content-Length must be a non-negative integer.", status_code=400)
            length = int(raw_length) if raw_length is not None else None
            upload = await run_in_threadpool(store.begin_upload, bound,
                                            unquote(request.headers.get("x-model-name", "")), length)
            # Admission + reservation precede the first receive. An idle body cannot hold a lease forever.
            async with asyncio.timeout(STALE_SECONDS):
                async for chunk in request.stream():
                    await run_in_threadpool(upload.write, chunk)
            record = await run_in_threadpool(upload.finish)
            return JSONResponse(record, status_code=202, headers=HEADERS)
        except TimeoutError:
            error = FacilityLayoutError("model_timeout", "The model upload timed out.", status_code=422)
            if upload is not None:
                await run_in_threadpool(upload.abort, error)
            return error_response(error)
        except FacilityLayoutError as error:
            if upload is not None:
                await run_in_threadpool(upload.abort, error)
            return error_response(error)
        finally:
            if upload is not None:
                # Shield cleanup so a disconnected HTTP request cannot retain its admission slot.
                task = asyncio.create_task(run_in_threadpool(upload.abort))
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        continue
                try:
                    task.result()
                except (FacilityLayoutError, OSError):
                    LOGGER.warning("Model upload cleanup deferred; the original response is preserved.")

    @router.get(PREFIX)
    async def imports(site_id: str, layout_id: str, request: Request):
        try:
            value = {"imports": await run_in_threadpool(store.list, scope(request, site_id, layout_id))}
            return JSONResponse(value, headers=HEADERS)
        except FacilityLayoutError as error:
            return error_response(error)

    @router.get(PREFIX + "/{import_id}")
    async def get_import(site_id: str, layout_id: str, import_id: str, request: Request):
        try:
            value = await run_in_threadpool(store.get, scope(request, site_id, layout_id), import_id)
            return JSONResponse(value, headers=HEADERS)
        except FacilityLayoutError as error:
            return error_response(error)

    @router.post(PREFIX + "/{import_id}/retry")
    async def retry(site_id: str, layout_id: str, import_id: str, request: Request):
        try:
            if feature_gate:
                feature_gate("manual_edit")
            record = await run_in_threadpool(store.retry, scope(request, site_id, layout_id), import_id)
            return JSONResponse(record, status_code=202, headers=HEADERS)
        except FacilityLayoutError as error:
            return error_response(error)

    @router.get(PREFIX + "/{import_id}/preview")
    async def source_preview(site_id: str, layout_id: str, import_id: str, request: Request):
        try:
            data = await run_in_threadpool(store.preview, scope(request, site_id, layout_id), import_id)
            return Response(data, media_type="image/png", headers=HEADERS)
        except FacilityLayoutError as error:
            return error_response(error)

    @router.get(BASE + "/model-drafts/{draft_id}/preview")
    async def draft_preview(site_id: str, layout_id: str, draft_id: str, request: Request):
        try:
            data = await run_in_threadpool(store.preview, scope(request, site_id, layout_id), draft_id, draft=True)
            return Response(data, media_type="image/png", headers=HEADERS)
        except FacilityLayoutError as error:
            return error_response(error)

    return router
