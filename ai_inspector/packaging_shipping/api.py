"""Local pilot router; identity comes from the host, never from request bodies."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool

from .geometry import assess, digest
from .admission import PackagingAdmission
from .models import Design, Edit, PackingRequest, QuoteRequest, RevisionCommand, DensityRequest, AlternativeSave, BaselineSelect, ScenarioAuthorization
from .quoting import QuoteDesk
from .comparison import compare as compare_designs, scenarios as quoted_scenarios
from .catalog import catalog
from .permissions import ACCOUNT, EDIT, QUOTE, READ, granted, permits
from .packing import propose
from .destinations import RULES as DESTINATION_RULES
from .rating import FEES_NOTICE, PRICE_BASES, SHIP_DATE_BASIS
from .service import PackagingError, PackagingService
from .sources import MAX_BYTES, GlbRuntime, glb_runtime, import_glb_isolated
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
                  credential_factory=None, step_runtime=None, source_runtime=None, quotes: QuoteDesk | None = None):
    if admission is not None and (not isinstance(admission, PackagingAdmission) or admission.service is not service):
        raise ValueError("Packaging admission must use this router's service instance.")
    if quotes is not None and (not isinstance(quotes, QuoteDesk) or quotes.service is not service
                               or rating is not None or credential_factory is not None):
        raise ValueError("Give the rating provider and credential store to the QuoteDesk, which must use this router's service.")
    if sage_enabled is not None and not callable(sage_enabled):
        raise ValueError("sage_enabled must be a host callback.")
    source_runtime = glb_runtime() if source_runtime is None else source_runtime
    if not isinstance(source_runtime, GlbRuntime):
        raise TypeError('A host-configured GlbRuntime is required')
    router = APIRouter(route_class=PackagingRoute)
    # One provider path, lock and audit for the Rates panel and Sage (the host passes the same desk to both).
    desk = quotes or QuoteDesk(service, rating=rating, credential_factory=credential_factory)
    job_lock = asyncio.Lock()

    def geometry_runtime():
        return step_runtime or StepRuntime.from_environment()

    account, current_account = desk.account, desk.current_account

    def principal(request: Request):
        if request.url.hostname not in {"127.0.0.1", "localhost", "::1", "testserver"}:
            raise HTTPException(403, "Packaging pilot is restricted to the local application.")
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Cross-origin packaging requests are not permitted.")
        if request.method not in {"GET", "HEAD"} and request.headers.get("x-inspectorpro-request") != "packaging":
            raise HTTPException(403, "Use the InspectorPro packaging client.")
        resolved = principal_resolver(request)
        if not permits(resolved, READ):
            raise HTTPException(403, "Your application role does not permit this operation.")
        return resolved

    def scoped(action=None):
        """Reads need packaging.read and other methods packaging.edit, unless the route names its action."""
        def dependency(request: Request, resolved=Depends(principal)):
            if not permits(resolved, action or (READ if request.method in {"GET", "HEAD"} else EDIT)):
                raise HTTPException(403, "Your application role does not permit this operation.")
            return digest({"tenant": resolved.tenant_id, "sites": sorted(resolved.allowed_site_ids), "workflow": "packaging_shipping"})
        return dependency

    scope, quote_scope, account_scope = scoped(), scoped(QUOTE), scoped(ACCOUNT)

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
                "rating": desk.status(resolved),
                "permissions": granted(resolved),
                "capabilities": ["glb_import", "manual_dimensions", "mass_provenance", "cartons", "solid_pads", "top_open_pockets", "surface_graphics", "material_catalog", "saved_alternatives", "orthogonal_arrangements", "undo", "redo", "quote_only", "pdf_report", "proposal_protection", "quote_reuse", "quote_attempt_audit", "carrier_account_discovery", "cost_comparison", "sage_quote_scenarios"] + (["step_import", "cad_volume_density_estimate"] if step else []) + (["sage_chat_execution"] if sage else []),
                "quote_rules": {"destinations": DESTINATION_RULES, "ship_date": SHIP_DATE_BASIS, "fees": FEES_NOTICE,
                                "price_bases": PRICE_BASES},
                "unsupported": ["verified_cad_material_mass", "arbitrary_contour_cutouts", "transport_certification", "freight", "future_ship_dates"] + ([] if step else ["step_runtime_not_configured"]) + ([] if sage else ["sage_chat_execution"])}

    @router.get("/api/packaging/catalog")
    def get_catalog(_=Depends(scope)):
        return catalog()

    @router.get("/api/packaging/account")
    def get_account(_=Depends(scope), resolved=Depends(principal)):
        return account(resolved).status()

    @router.put("/api/packaging/account")
    async def replace_account(request: Request, _=Depends(account_scope), resolved=Depends(principal)):
        try:
            raw = await bounded_body(request, 8192)
            body = json.loads(raw)
            if not isinstance(body, dict) or set(body) != {"api_key", "account_alias"}:
                raise ValueError()
        except (ValueError, UnicodeError):
            raise PackagingError("carrier_account_invalid", "Enter a carrier key and account alias in the account form.", 422) from None
        return account(resolved).replace(body["api_key"], account_alias=body["account_alias"])

    @router.delete("/api/packaging/account")
    def remove_account(_=Depends(account_scope), resolved=Depends(principal)):
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
            metadata, glb = await import_glb_isolated(bytes(data), request.query_params.get("name", "Imported product"), unit, service.root,
                                                      runtime=source_runtime)
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
    def quotes(doc_id: str, s=Depends(scope), resolved=Depends(principal)):
        account_ref, known = current_account(resolved)
        return {"quotes": service.quote_history(s, doc_id, account_ref=account_ref, account_known=known)}

    @router.get("/api/packaging/documents/{doc_id}/quote-attempts")
    def quote_attempts(doc_id: str, s=Depends(scope)):
        return service.quote_attempts(s, doc_id) | {"fees_notice": FEES_NOTICE}

    @router.post("/api/packaging/documents/{doc_id}/quotes")
    async def quote(doc_id: str, body: QuoteRequest, s=Depends(quote_scope), resolved=Depends(principal)):
        desk.busy()
        current = service.get(s, doc_id, body.expected_revision)
        revision = body.expected_revision
        return await desk.price(s, doc_id, revision, Design.model_validate(current["design"]), current["assessment"], body, resolved,
                                lambda fingerprint: service.find_quote(s, doc_id, revision, fingerprint),
                                lambda result: service.save_quotes(s, doc_id, revision, result))

    @router.post("/api/packaging/documents/{doc_id}/alternatives/{alt_id}/quotes")
    async def quote_alternative(doc_id: str, alt_id: str, body: QuoteRequest, s=Depends(quote_scope), resolved=Depends(principal)):
        desk.busy()
        service.get(s, doc_id, body.expected_revision)
        design = service.alternative_design(s, doc_id, alt_id)
        revision = body.expected_revision
        return await desk.price(s, doc_id, revision, design, await asyncio.to_thread(assess, design), body, resolved,
                                lambda fingerprint: service.find_alternative_quote(s, doc_id, alt_id, fingerprint),
                                lambda result: service.save_alternative_quote(s, doc_id, alt_id, revision, result))

    @router.post("/api/packaging/documents/{doc_id}/scenarios")
    def authorize_scenario(doc_id: str, body: ScenarioAuthorization, s=Depends(quote_scope), resolved=Depends(principal)):
        """Lets Sage quote these session addresses by ID. Held in memory only; nothing is sent until Sage quotes."""
        service.get(s, doc_id)
        return desk.scenarios.create(s, doc_id, resolved.principal_id, body)

    @router.get("/api/packaging/documents/{doc_id}/scenarios")
    def authorized_scenarios(doc_id: str, s=Depends(scope), resolved=Depends(principal)):
        service.get(s, doc_id)
        return {"scenarios": desk.scenarios.list(s, doc_id, resolved.principal_id)}

    @router.delete("/api/packaging/documents/{doc_id}/scenarios/{scenario_id}")
    def revoke_scenario(doc_id: str, scenario_id: str, s=Depends(quote_scope), resolved=Depends(principal)):
        return desk.scenarios.revoke(s, doc_id, resolved.principal_id, scenario_id)

    @router.put("/api/packaging/documents/{doc_id}/comparison/baseline")
    def comparison_baseline(doc_id: str, body: BaselineSelect, s=Depends(scope)):
        return service.set_baseline(s, doc_id, body.baseline)

    @router.get("/api/packaging/documents/{doc_id}/comparison")
    def comparison(doc_id: str, s=Depends(scope), resolved=Depends(principal),
                   scenario_hash: str | None = Query(None, pattern=r"^[a-f0-9]{64}$"),
                   carrier: str | None = Query(None, max_length=100),
                   service_name: str | None = Query(None, alias="service", max_length=100),
                   account_id: str = Query("", max_length=100),
                   currency: str | None = Query(None, pattern=r"^[A-Z]{3}$")):
        """Reads saved quotes only; no provider request is made."""
        chosen = (carrier, service_name, currency)
        if any(v is not None for v in chosen) and not all(v is not None for v in chosen):
            raise PackagingError("comparison_service_incomplete", "Name the carrier, service and currency together.", 422)
        account_ref, known = current_account(resolved)
        if not known:
            raise PackagingError("carrier_credentials_unavailable", "The carrier account could not be read, so saved quotes cannot be matched.", 503)
        candidates, quotes, baseline = service.comparison_inputs(s, doc_id)
        selection = None if carrier is None else (carrier, service_name, account_id, currency)
        return {"baseline": {**service.baseline(s, doc_id), "baseline": baseline}, "account_ref": account_ref,
                "scenarios": quoted_scenarios(quotes, account_ref),
                "comparison": None if scenario_hash is None else compare_designs(baseline, candidates, quotes, scenario_hash, account_ref, selection)}

    @router.post("/api/packaging/account/carrier-accounts")
    async def carrier_accounts(_=Depends(account_scope), resolved=Depends(principal)):
        # POST: this contacts the provider, so it needs the packaging client header and account rights.
        return await desk.carrier_accounts(resolved)

    @router.get("/api/packaging/documents/{doc_id}/report.pdf")
    def report(doc_id: str, revision: int, s=Depends(scope)):
        from .report import render_report
        current = service.get(s, doc_id, revision)
        payload = render_report(current, service.quote_history(s, doc_id))
        return Response(payload, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="packaging-review.pdf"'})

    return router
