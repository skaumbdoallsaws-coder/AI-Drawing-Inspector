"""Floor-plan import, HTTP routes (docs/facility-floor-plan-import-plan.md, section 10).

    POST .../floor-plan-imports                      the DXF as the raw body (X-Floor-Plan-Name: the file name,
                                                     percent-encoded); reads it in the limited worker, stores it
    GET  .../floor-plan-imports/{importId}           the import record and its manifest (units, layers, warnings)
    GET  .../floor-plan-imports/{importId}/geometry  the normalized drawing (floor_plan_reader's geometry)
    GET  .../floor-plan-imports/{importId}/source    the original file, as a download
    POST .../floor-plan-imports/{importId}/alignment an alignment from control points or one distance, not saved
    POST .../floor-plan-imports/{importId}/conversion {baseRevision, settings, stage}: the walls, rooms and outline
                                                     the underlay's layers convert to; stage "proposal" also stages
                                                     them as a change to review (floor_plan_proposals)

under /api/facility-layouts/{site_id}/{layout_id}. Each request checks the person may read (or, to upload or download
the original, or to convert, edit) that layout before touching the store; an import id alone grants nothing. Nothing
here changes a layout: an underlay is saved with the upsert_floor_plan_reference operation, and a conversion is applied
only through the proposal approval routes, after review.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Body, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from .authorization import require_facility_action
from .errors import FacilityLayoutError, FacilityValidationError
from .floor_plan_store import (MAX_UPLOAD_BYTES, STORE_FOLDER, Upload, _too_large, artifact_file, check_not_busy,
                               clean_source_name, compute_alignment, import_drawing, load_import, scope_folder)

PREFIX = "/api/facility-layouts/{site_id}/{layout_id}/floor-plan-imports"
_FILE_HEADERS = {"Cache-Control": "private, no-cache", "X-Content-Type-Options": "nosniff"}


def create_floor_plan_import_router(*, service, principal_resolver, feature_gate=None):
    router = APIRouter()
    root = service.layout_repository.root / STORE_FOLDER

    def error_response(error):
        return JSONResponse(status_code=error.status_code, content={"error": error.to_dict()})

    async def authorize(request, site_id, layout_id, action):
        principal = principal_resolver(request)
        require_facility_action(principal, tenant_id=principal.tenant_id, site_id=site_id, action=action)
        await run_in_threadpool(service.get_layout, principal, site_id, layout_id)
        return principal

    @router.post(PREFIX)
    async def import_floor_plan(site_id: str, layout_id: str, request: Request):
        upload = None
        try:
            if feature_gate:
                feature_gate("manual_edit")
            principal = await authorize(request, site_id, layout_id, "layout.edit")
            check_not_busy(principal)
            declared = request.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
                raise _too_large()
            name = clean_source_name(unquote(request.headers.get("x-floor-plan-name", "")))
            upload = await run_in_threadpool(Upload, scope_folder(root, principal, site_id))
            async for chunk in request.stream():
                upload.write(chunk)
            if not upload.size:
                raise FacilityValidationError("floor_plan_empty", "The file is empty.")
            digest = await run_in_threadpool(upload.finish)
            path, size, upload = upload.path, upload.size, None  # import_drawing consumes the file
            result = await run_in_threadpool(import_drawing, root, principal, site_id, path, digest, size, name)
            return result
        except FacilityLayoutError as exc:
            return error_response(exc)
        finally:
            if upload is not None:
                upload.discard()

    @router.get(PREFIX + "/{import_id}")
    async def get_import(site_id: str, layout_id: str, import_id: str, request: Request):
        try:
            principal = await authorize(request, site_id, layout_id, "layout.read")
            return await run_in_threadpool(load_import, root, principal, site_id, import_id)
        except FacilityLayoutError as exc:
            return error_response(exc)

    @router.get(PREFIX + "/{import_id}/geometry")
    async def get_geometry(site_id: str, layout_id: str, import_id: str, request: Request):
        try:
            principal = await authorize(request, site_id, layout_id, "layout.read")
            path, _record = await run_in_threadpool(artifact_file, root, principal, site_id, import_id, "geometry")
            return FileResponse(path, media_type="application/json", headers=_FILE_HEADERS)
        except FacilityLayoutError as exc:
            return error_response(exc)

    @router.get(PREFIX + "/{import_id}/source")
    async def get_source(site_id: str, layout_id: str, import_id: str, request: Request):
        try:
            principal = await authorize(request, site_id, layout_id, "layout.edit")
            path, record = await run_in_threadpool(artifact_file, root, principal, site_id, import_id, "source")
            return FileResponse(path, media_type="application/octet-stream", headers=_FILE_HEADERS,
                                filename=record.get("sourceName") or "drawing.dxf",
                                content_disposition_type="attachment")
        except FacilityLayoutError as exc:
            return error_response(exc)

    @router.post(PREFIX + "/{import_id}/alignment")
    async def align(site_id: str, layout_id: str, import_id: str, request: Request, body: Any = Body(...)):
        try:
            principal = await authorize(request, site_id, layout_id, "layout.read")
            loaded = await run_in_threadpool(load_import, root, principal, site_id, import_id)
            return compute_alignment(loaded["manifest"], body)
        except FacilityLayoutError as exc:
            return error_response(exc)

    @router.post(PREFIX + "/{import_id}/conversion")
    async def convert_drawing(site_id: str, layout_id: str, import_id: str, request: Request, body: Any = Body(...)):
        from .floor_plan_proposals import stage_conversion
        try:
            if feature_gate:
                feature_gate("manual_edit")
                if isinstance(body, dict) and body.get("stage") == "proposal":
                    feature_gate("agent_preview")  # the review is a proposal preview
            principal = await authorize(request, site_id, layout_id, "layout.edit")
            return await run_in_threadpool(stage_conversion, service, principal, site_id, layout_id, import_id, body)
        except FacilityLayoutError as exc:
            return error_response(exc)

    return router
