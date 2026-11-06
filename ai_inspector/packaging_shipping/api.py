"""Local pilot router; identity comes from the host, never from request bodies."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool

from .geometry import digest
from .admission import PackagingAdmission
from .models import Design, Edit, PackingRequest, QuoteRequest, RevisionCommand, DensityRequest, AlternativeSave
from .catalog import catalog
from .packing import propose
from .rating import EasyPostRating
from .service import PackagingError, PackagingService
from .sources import MAX_BYTES, import_glb_isolated
from .step_import import StepRuntime, StepImportError, import_step


async def bounded_body(request, limit):
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > limit:
            raise PackagingError("upload_too_large", "Request exceeds the permitted byte limit.", 413)
    return bytes(data)


class PackagingRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            try:
                binary_paths = {"/api/packaging/sources", "/api/packaging/sources/step", "/api/packaging/images"}
                editor_path = request.url.path == "/api/packaging/editor" or request.url.path.startswith("/api/packaging/editor/")
                if request.method not in {"GET", "HEAD"} and request.url.path not in binary_paths and not editor_path:
                    request._body = await bounded_body(request, 1024 * 1024)
                response = await handler(request)
                response.headers["Cache-Control"] = "no-store"
                return response
            except PackagingError as exc:
                return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status,
                                    headers={"Cache-Control": "no-store"})
            except RecursionError:
                return JSONResponse({"error": {"code": "json_nesting_limit", "message": "Request nesting exceeds the supported limit."}},
                                    status_code=400, headers={"Cache-Control": "no-store"})
        return guarded


def create_router(service: PackagingService, *, principal_resolver, static_root: Path, rating=None,
                  admission: PackagingAdmission | None = None, sage_enabled: Callable[[], bool] | None = None,
                  credential_factory=None, step_runtime=None):
    if admission is not None and (not isinstance(admission, PackagingAdmission) or admission.service is not service):
        raise ValueError("Packaging admission must use this router's service instance.")
    if sage_enabled is not None and not callable(sage_enabled):
        raise ValueError("sage_enabled must be a host callback.")
    router = APIRouter(route_class=PackagingRoute)
    provider = rating or EasyPostRating()
    job_lock = asyncio.Lock()
    quote_lock = asyncio.Lock()

    def geometry_runtime():
        return step_runtime or StepRuntime.from_environment()

    def account(resolved):
        if credential_factory is None:
            raise PackagingError("carrier_secure_store_disabled", "This host has not enabled local carrier account storage.", 403)
        return credential_factory(resolved)

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
        async def editor_body(request):
            # Authenticate first; even malformed transitions must reach the
            # registry's invalidation path before returning a validation error.
            try:
                return json.loads(await bounded_body(request, 65536))
            except (ValueError, UnicodeError, RecursionError, PackagingError):
                return None

        @router.post("/api/packaging/editor")
        async def publish_editor(request: Request, resolved=Depends(principal)):
            return await run_in_threadpool(admission.publish, resolved, await editor_body(request))

        @router.post("/api/packaging/editor/{admission_id}/heartbeat")
        async def heartbeat_editor(admission_id: str, request: Request, resolved=Depends(principal)):
            return await run_in_threadpool(admission.heartbeat, resolved, admission_id, await editor_body(request))

        @router.post("/api/packaging/editor/{admission_id}/revoke")
        async def revoke_editor(admission_id: str, request: Request, resolved=Depends(principal)):
            return await run_in_threadpool(admission.revoke, resolved, admission_id, await editor_body(request))

    @router.get("/packaging")
    def page(_=Depends(scope)):
        return FileResponse(static_root / "packaging.html")

    @router.get("/api/packaging/status")
    def status(_=Depends(scope), resolved=Depends(principal)):
        try:
            sage = admission is not None and sage_enabled is not None and sage_enabled() is True
        except Exception:
            sage = False
        try:
            geometry_runtime()
            step = True
        except StepImportError:
            step = False
        return {"workflow": "packaging_shipping", "pilot": True,
                "rating": account(resolved).status() if credential_factory else provider.status(),
                "capabilities": ["glb_import", "manual_dimensions", "mass_provenance", "cartons", "solid_pads", "top_open_pockets", "surface_graphics", "material_catalog", "saved_alternatives", "orthogonal_arrangements", "undo", "redo", "quote_only", "pdf_report"] + (["step_import", "cad_volume_density_estimate"] if step else []) + (["sage_chat_execution"] if sage else []),
                "unsupported": ["verified_cad_material_mass", "arbitrary_contour_cutouts", "transport_certification", "freight", "future_ship_dates"] + ([] if step else ["step_runtime_not_configured"]) + ([] if sage else ["sage_chat_execution"])}

    @router.get("/api/packaging/catalog")
    def get_catalog(_=Depends(scope)):
        return catalog()

    @router.get("/api/packaging/account")
    def get_account(_=Depends(scope), resolved=Depends(principal)):
        return account(resolved).status()

    @router.put("/api/packaging/account")
    async def replace_account(request: Request, _=Depends(scope), resolved=Depends(principal)):
        try:
            raw = await bounded_body(request, 8192)
            body = json.loads(raw)
            if not isinstance(body, dict) or set(body) != {"api_key", "account_alias"}:
                raise ValueError()
        except (ValueError, UnicodeError):
            raise PackagingError("carrier_account_invalid", "Enter a carrier key and account alias in the account form.", 422) from None
        return account(resolved).replace(body["api_key"], account_alias=body["account_alias"])

    @router.delete("/api/packaging/account")
    def remove_account(_=Depends(scope), resolved=Depends(principal)):
        return account(resolved).remove()

    @router.get("/api/packaging/documents")
    def documents(s=Depends(scope)):
        return {"documents": service.list(s)}

    @router.post("/api/packaging/documents")
    def create(design: Design, request: Request, s=Depends(scope)):
        return service.create(s, design, request_id=request.headers.get("idempotency-key"))

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

    @router.get("/api/packaging/documents/{doc_id}/alternatives")
    def alternatives(doc_id: str, s=Depends(scope)):
        return {"alternatives": service.alternatives(s, doc_id)}

    @router.post("/api/packaging/documents/{doc_id}/alternatives")
    def save_alternative(doc_id: str, body: AlternativeSave, s=Depends(scope)):
        return service.save_alternative(s, doc_id, body)

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
        data = await bounded_body(request, MAX_BYTES)
        async with job_lock:
            metadata, glb = await import_glb_isolated(bytes(data), request.query_params.get("name", "Imported product"), unit, service.root)
        return service.store_source(s, metadata, glb)

    @router.post("/api/packaging/sources/step")
    async def step_upload(request: Request, s=Depends(scope)):
        if job_lock.locked():
            raise PackagingError("geometry_busy", "A packaging calculation is already running.", 429)
        try:
            runtime = geometry_runtime()
            data = await bounded_body(request, runtime.max_input_bytes)
            async with job_lock:
                result = await import_step(data, runtime=runtime)
            metadata = result.metadata
            metadata["name"] = request.query_params.get("name", "Imported STEP product").strip()[:160] or "Imported STEP product"
            metadata["geometry_evidence"] = "Closed-solid STEP BRep bounds and volume; mass requires material density and engineering review."
            return service.store_source(s, metadata, result.glb_bytes)
        except StepImportError as exc:
            raise PackagingError(exc.code, exc.message, exc.status_code) from None

    @router.get("/api/packaging/sources")
    def sources(s=Depends(scope)):
        return {"sources": service.sources(s)}

    @router.get("/api/packaging/sources/{source_id}.glb")
    def source_glb(source_id: str, s=Depends(scope)):
        _, glb = service.source(s, source_id)
        return Response(glb, media_type="model/gltf-binary")

    @router.get("/api/packaging/sources/{source_id}")
    def source_metadata(source_id: str, s=Depends(scope)):
        return service.source_metadata(s, source_id)

    @router.post("/api/packaging/sources/{source_id}/mass-estimate")
    def mass_estimate(source_id: str, body: DensityRequest, s=Depends(scope)):
        return {"product": service.estimate_mass(s, source_id, body)}

    @router.post("/api/packaging/images")
    async def image_upload(request: Request, s=Depends(scope)):
        data = await bounded_body(request, 10 * 1024 * 1024)
        return await asyncio.to_thread(service.store_image, s, data)

    @router.get("/api/packaging/images/{image_id}.png")
    def image_png(image_id: str, s=Depends(scope)):
        return Response(service.image(s, image_id)[1], media_type="image/png", headers={"X-Content-Type-Options": "nosniff"})

    @router.get("/api/packaging/images/{image_id}")
    def image_metadata(image_id: str, s=Depends(scope)):
        return service.image(s, image_id)[0]

    @router.get("/api/packaging/documents/{doc_id}/quotes")
    def quotes(doc_id: str, s=Depends(scope)):
        return {"quotes": service.quote_history(s, doc_id)}

    @router.post("/api/packaging/documents/{doc_id}/quotes")
    async def quote(doc_id: str, body: QuoteRequest, s=Depends(scope), resolved=Depends(principal)):
        if quote_lock.locked():
            raise PackagingError("quote_in_progress", "A quote request is already running. Wait before retrying.", 429)
        current = service.get(s, doc_id, body.expected_revision)
        async with quote_lock:
            credential = account(resolved).resolve() if credential_factory else None
            selected = EasyPostRating(key=credential.api_key.get_secret_value()) if credential else provider
            if credential:
                credential.check()
            result = await selected.quote(Design.model_validate(current["design"]), current["assessment"], body)
            if credential:
                credential.check()
            return service.save_quotes(s, doc_id, body.expected_revision, result)

    @router.get("/api/packaging/documents/{doc_id}/report.pdf")
    def report(doc_id: str, revision: int, s=Depends(scope)):
        from .report import render_report
        current = service.get(s, doc_id, revision)
        payload = render_report(current, service.quote_history(s, doc_id))
        return Response(payload, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="packaging-review.pdf"'})

    return router
