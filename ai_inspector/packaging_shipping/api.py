"""Local pilot router; identity comes from the host, never from request bodies."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.routing import APIRoute

from .geometry import digest
from .admission import EditorHeartbeat, EditorRevoke, EditorState, PackagingAdmission
from .models import Design, Edit, PackingRequest, QuoteRequest, RevisionCommand
from .packing import propose
from .rating import EasyPostRating
from .service import PackagingError, PackagingService
from .sources import MAX_BYTES, import_glb_isolated


class PackagingRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            try:
                response = await handler(request)
                response.headers["Cache-Control"] = "no-store"
                return response
            except PackagingError as exc:
                return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status,
                                    headers={"Cache-Control": "no-store"})
        return guarded


def create_router(service: PackagingService, *, principal_resolver, static_root: Path, rating=None,
                  admission: PackagingAdmission | None = None, sage_enabled: Callable[[], bool] | None = None):
    if admission is not None and (not isinstance(admission, PackagingAdmission) or admission.service is not service):
        raise ValueError("Packaging admission must use this router's service instance.")
    if sage_enabled is not None and not callable(sage_enabled):
        raise ValueError("sage_enabled must be a host callback.")
    router = APIRouter(route_class=PackagingRoute)
    provider = rating or EasyPostRating()
    job_lock = asyncio.Lock()

    def principal(request: Request):
        if request.url.hostname not in {"127.0.0.1", "localhost", "::1", "testserver"}:
            raise HTTPException(403, "Packaging pilot is restricted to the local application.")
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Cross-origin packaging requests are not permitted.")
        if request.method not in {"GET", "HEAD"} and request.headers.get("x-inspectorpro-request") != "packaging":
            raise HTTPException(403, "Use the InspectorPro packaging client.")
        resolved = principal_resolver(request)
        if not resolved.permits("layout.read"):
            raise HTTPException(403, "Your application role does not permit this operation.")
        return resolved

    def scope(request: Request, resolved=Depends(principal)):
        if request.method not in {"GET", "HEAD"} and not resolved.permits("layout.edit"):
            raise HTTPException(403, "Your application role does not permit this operation.")
        return digest({"tenant": resolved.tenant_id, "sites": sorted(resolved.allowed_site_ids), "workflow": "packaging_shipping"})

    if admission is not None:
        @router.post("/api/packaging/editor")
        def publish_editor(body: EditorState, resolved=Depends(principal)):
            return admission.publish(resolved, body)

        @router.post("/api/packaging/editor/{admission_id}/heartbeat")
        def heartbeat_editor(admission_id: str, body: EditorHeartbeat, resolved=Depends(principal)):
            return admission.heartbeat(resolved, admission_id, body)

        @router.post("/api/packaging/editor/{admission_id}/revoke")
        def revoke_editor(admission_id: str, body: EditorRevoke, resolved=Depends(principal)):
            return admission.revoke(resolved, admission_id, body)

    @router.get("/packaging")
    def page(_=Depends(scope)):
        return FileResponse(static_root / "packaging.html")

    @router.get("/api/packaging/status")
    def status(_=Depends(scope)):
        try:
            sage = admission is not None and sage_enabled is not None and sage_enabled() is True
        except Exception:
            sage = False
        return {"workflow": "packaging_shipping", "pilot": True, "rating": provider.status(),
                "capabilities": ["glb_import", "manual_dimensions", "mass_provenance", "cartons", "solid_pads", "orthogonal_arrangements", "undo", "redo", "quote_only", "pdf_report"] + (["sage_chat_execution"] if sage else []),
                "unsupported": ["solid_cutouts", "verified_cad_mass_import", "transport_certification", "freight", "future_ship_dates"] + ([] if sage else ["sage_chat_execution"])}

    @router.get("/api/packaging/documents")
    def documents(s=Depends(scope)):
        return {"documents": service.list(s)}

    @router.post("/api/packaging/documents")
    def create(design: Design, s=Depends(scope)):
        return service.create(s, design)

    @router.get("/api/packaging/documents/{doc_id}")
    def get(doc_id: str, s=Depends(scope)):
        return service.get(s, doc_id)

    @router.put("/api/packaging/documents/{doc_id}")
    def edit(doc_id: str, body: Edit, s=Depends(scope)):
        return service.change(s, doc_id, body)

    @router.post("/api/packaging/documents/{doc_id}/undo")
    def undo(doc_id: str, body: RevisionCommand, s=Depends(scope)):
        return service.change(s, doc_id, body, "undo")

    @router.post("/api/packaging/documents/{doc_id}/redo")
    def redo(doc_id: str, body: RevisionCommand, s=Depends(scope)):
        return service.change(s, doc_id, body, "redo")

    @router.post("/api/packaging/documents/{doc_id}/arrangements")
    async def arrangements(doc_id: str, body: PackingRequest, s=Depends(scope)):
        if job_lock.locked():
            raise PackagingError("geometry_busy", "A packaging calculation is already running.", 429)
        current = service.get(s, doc_id, body.expected_revision)
        async with job_lock:
            result = await asyncio.to_thread(propose, Design.model_validate(current["design"]), body.cartons, body.max_packages)
        service.get(s, doc_id, body.expected_revision)
        return result

    @router.post("/api/packaging/sources")
    async def source_upload(request: Request, s=Depends(scope)):
        if job_lock.locked():
            raise PackagingError("geometry_busy", "A packaging calculation is already running.", 429)
        try:
            unit = float(request.query_params.get("meters_per_unit", "1"))
        except ValueError:
            raise PackagingError("units_required", "Choose a supported source unit.", 400)
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_BYTES:
                raise PackagingError("source_too_large", "GLB import is limited to 24 MiB.", 413)
        async with job_lock:
            metadata, glb = await import_glb_isolated(bytes(data), request.query_params.get("name", "Imported product"), unit, service.root)
        return service.store_source(s, metadata, glb)

    @router.get("/api/packaging/sources/{source_id}.glb")
    def source_glb(source_id: str, s=Depends(scope)):
        _, glb = service.source(s, source_id)
        return Response(glb, media_type="model/gltf-binary")

    @router.get("/api/packaging/documents/{doc_id}/quotes")
    def quotes(doc_id: str, s=Depends(scope)):
        return {"quotes": service.quote_history(s, doc_id)}

    @router.post("/api/packaging/documents/{doc_id}/quotes")
    async def quote(doc_id: str, body: QuoteRequest, s=Depends(scope)):
        current = service.get(s, doc_id, body.expected_revision)
        result = await provider.quote(Design.model_validate(current["design"]), current["assessment"], body)
        return service.save_quotes(s, doc_id, body.expected_revision, result)

    @router.get("/api/packaging/documents/{doc_id}/report.pdf")
    def report(doc_id: str, revision: int, s=Depends(scope)):
        from .report import render_report
        current = service.get(s, doc_id, revision)
        payload = render_report(current, service.quote_history(s, doc_id))
        return Response(payload, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="packaging-review.pdf"'})

    return router
