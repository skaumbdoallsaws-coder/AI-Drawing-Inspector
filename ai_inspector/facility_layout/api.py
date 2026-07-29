"""FastAPI router factory for principal-bound Facility Layout APIs."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .authority_repository import RevisionedAuthorityRepository
from .authorization import FacilityPrincipal
from .errors import FacilityLayoutError, FacilityValidationError
from .service import FacilityLayoutService


PrincipalResolver = Callable[[Request], FacilityPrincipal]


def _body_mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FacilityValidationError(
            "invalid_request_body",
            "Request body must be a JSON object.",
        )
    return value


def _error_response(error: FacilityLayoutError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={"error": error.to_dict()},
    )


def _result(call: Callable[[], Any]) -> Any:
    try:
        return call()
    except FacilityLayoutError as exc:
        return _error_response(exc)


async def _thread_result(call: Callable[[], Any]) -> Any:
    try:
        return await run_in_threadpool(call)
    except FacilityLayoutError as exc:
        return _error_response(exc)


def _authority_routes(
    router: APIRouter,
    *,
    prefix: str,
    repository: RevisionedAuthorityRepository,
    principal_resolver: PrincipalResolver,
) -> None:
    @router.get(prefix + "/{site_id}")
    async def list_authority(site_id: str, request: Request):
        return _result(
            lambda: repository.list_documents(
                principal_resolver(request),
                site_id=site_id,
            )
        )

    @router.post(prefix + "/{site_id}")
    async def create_authority(
        site_id: str,
        request: Request,
        body: Any = Body(...),
    ):
        try:
            payload = _body_mapping(body)
            document = _body_mapping(payload.get("document", payload))
        except FacilityLayoutError as exc:
            return _error_response(exc)
        return _result(
            lambda: repository.create(
                principal_resolver(request),
                site_id=site_id,
                document=document,
            ).to_dict()
        )

    @router.get(prefix + "/{site_id}/{authority_id}")
    async def get_authority(
        site_id: str,
        authority_id: str,
        request: Request,
    ):
        return _result(
            lambda: repository.get_current(
                principal_resolver(request),
                site_id=site_id,
                authority_id=authority_id,
            ).to_dict()
        )

    @router.get(
        prefix + "/{site_id}/{authority_id}/revisions/{revision}"
    )
    async def get_authority_revision(
        site_id: str,
        authority_id: str,
        revision: str,
        request: Request,
    ):
        return _result(
            lambda: repository.get_revision(
                principal_resolver(request),
                site_id=site_id,
                authority_id=authority_id,
                revision=revision,
            ).to_dict()
        )

    @router.put(prefix + "/{site_id}/{authority_id}")
    async def update_authority(
        site_id: str,
        authority_id: str,
        request: Request,
        body: Any = Body(...),
    ):
        try:
            payload = _body_mapping(body)
            document = _body_mapping(payload.get("document"))
        except FacilityLayoutError as exc:
            return _error_response(exc)
        if document.get(repository.id_field) != authority_id:
            return _error_response(
                FacilityValidationError(
                    "request_identity_mismatch",
                    "Authority path and document identities differ.",
                )
            )
        return _result(
            lambda: repository.save_draft(
                principal_resolver(request),
                site_id=site_id,
                document=document,
                expected_revision=str(payload.get("baseRevision") or ""),
            ).to_dict()
        )

    def transition_handler(action: str):
        method = getattr(repository, action)

        async def transition(
            site_id: str,
            authority_id: str,
            request: Request,
            body: Any = Body(...),
        ):
            try:
                payload = _body_mapping(body)
            except FacilityLayoutError as exc:
                return _error_response(exc)
            return _result(
                lambda: method(
                    principal_resolver(request),
                    site_id=site_id,
                    authority_id=authority_id,
                    expected_revision=str(
                        payload.get("baseRevision") or ""
                    ),
                ).to_dict()
            )

        return transition

    for action in ("review", "publish", "deprecate", "archive"):
        router.add_api_route(
            prefix + "/{site_id}/{authority_id}/" + action,
            transition_handler(action),
            methods=["POST"],
            name=f"{repository.document_kind}_{action}",
        )


def create_facility_layout_router(
    *,
    service: FacilityLayoutService,
    principal_resolver: PrincipalResolver,
) -> APIRouter:
    """Build an isolated router; the host app decides when to mount it."""

    router = APIRouter()

    @router.get("/api/facility-layouts/{site_id}")
    async def list_layouts(
        site_id: str,
        request: Request,
        include_archived: bool = Query(False, alias="includeArchived"),
    ):
        return _result(
            lambda: service.list_layouts(
                principal_resolver(request),
                site_id,
                include_archived=include_archived,
            )
        )

    @router.post("/api/facility-layouts/{site_id}")
    async def create_layout(
        site_id: str,
        request: Request,
        body: Any = Body(...),
    ):
        try:
            payload = _body_mapping(body)
            document = _body_mapping(payload.get("layout", payload))
        except FacilityLayoutError as exc:
            return _error_response(exc)
        return _result(
            lambda: service.create_layout(
                principal_resolver(request),
                site_id,
                document,
                make_default=bool(payload.get("makeDefault", False)),
            )
        )

    @router.get("/api/facility-layouts/{site_id}/{layout_id}")
    async def get_layout(
        site_id: str,
        layout_id: str,
        request: Request,
    ):
        return _result(
            lambda: service.get_layout(
                principal_resolver(request),
                site_id,
                layout_id,
            )
        )

    @router.get(
        "/api/facility-layouts/{site_id}/{layout_id}/revisions/{revision}"
    )
    async def get_layout_revision(
        site_id: str,
        layout_id: str,
        revision: str,
        request: Request,
    ):
        return _result(
            lambda: service.get_layout_revision(
                principal_resolver(request),
                site_id,
                layout_id,
                revision,
            )
        )

    @router.put("/api/facility-layouts/{site_id}/{layout_id}")
    async def update_layout(
        site_id: str,
        layout_id: str,
        request: Request,
        body: Any = Body(...),
    ):
        try:
            payload = _body_mapping(body)
        except FacilityLayoutError as exc:
            return _error_response(exc)
        base_revision = str(payload.get("baseRevision") or "")
        if "operations" in payload:
            operations = payload["operations"]
            if not isinstance(operations, list):
                return _error_response(
                    FacilityValidationError(
                        "invalid_request_body",
                        "operations must be an array.",
                    )
                )
            return _result(
                lambda: service.apply_operations(
                    principal_resolver(request),
                    site_id,
                    layout_id,
                    base_revision,
                    operations,
                )
            )
        try:
            document = _body_mapping(payload.get("layout"))
        except FacilityLayoutError as exc:
            return _error_response(exc)
        if document.get("layoutId") != layout_id:
            return _error_response(
                FacilityValidationError(
                    "request_identity_mismatch",
                    "Layout path and document identities differ.",
                )
            )
        return _result(
            lambda: service.save_layout(
                principal_resolver(request),
                site_id,
                layout_id,
                document,
                base_revision,
            )
        )

    @router.post(
        "/api/facility-layouts/{site_id}/{layout_id}/preview"
    )
    async def preview_layout_operations(
        site_id: str,
        layout_id: str,
        request: Request,
        body: Any = Body(...),
    ):
        try:
            payload = _body_mapping(body)
        except FacilityLayoutError as exc:
            return _error_response(exc)
        operations = payload.get("operations")
        if not isinstance(operations, list):
            return _error_response(
                FacilityValidationError(
                    "invalid_request_body",
                    "operations must be an array.",
                )
            )
        return _result(
            lambda: service.preview_operations(
                principal_resolver(request),
                site_id,
                layout_id,
                str(payload.get("baseRevision") or ""),
                operations,
            )
        )

    @router.post(
        "/api/facility-layouts/{site_id}/{layout_id}/spatial/diagnostics"
    )
    async def spatial_diagnostics(
        site_id: str,
        layout_id: str,
        request: Request,
        body: Any = Body(...),
    ):
        try:
            payload = _body_mapping(body)
            operations = payload.get("operations", [])
            if not isinstance(operations, list):
                raise FacilityValidationError(
                    "invalid_request_body",
                    "operations must be an array.",
                )
        except FacilityLayoutError as exc:
            return _error_response(exc)
        return await _thread_result(
            lambda: service.diagnose_spatial(
                principal_resolver(request),
                site_id,
                layout_id,
                str(payload.get("baseRevision") or ""),
                operations=operations,
            )
        )

    @router.post(
        "/api/facility-layouts/{site_id}/{layout_id}/spatial/candidates"
    )
    async def spatial_candidates(
        site_id: str,
        layout_id: str,
        request: Request,
        body: Any = Body(...),
    ):
        try:
            payload = _body_mapping(body)
            candidate_request = _body_mapping(payload.get("request"))
            operations = payload.get("operations", [])
            if not isinstance(operations, list):
                raise FacilityValidationError(
                    "invalid_request_body",
                    "operations must be an array.",
                )
        except FacilityLayoutError as exc:
            return _error_response(exc)
        return await _thread_result(
            lambda: service.generate_spatial_candidates(
                principal_resolver(request),
                site_id,
                layout_id,
                str(payload.get("baseRevision") or ""),
                candidate_request,
                operations=operations,
            )
        )

    @router.post(
        "/api/facility-layouts/{site_id}/{layout_id}/spatial/candidates/preview"
    )
    async def preview_spatial_candidate(
        site_id: str,
        layout_id: str,
        request: Request,
        body: Any = Body(...),
    ):
        try:
            payload = _body_mapping(body)
            candidate_request = _body_mapping(payload.get("request"))
            candidate_id = payload.get("candidateId")
            operations = payload.get("operations", [])
            if not isinstance(candidate_id, str) or not candidate_id:
                raise FacilityValidationError(
                    "invalid_request_body",
                    "candidateId is required.",
                )
            if not isinstance(operations, list):
                raise FacilityValidationError(
                    "invalid_request_body",
                    "operations must be an array.",
                )
        except FacilityLayoutError as exc:
            return _error_response(exc)
        return await _thread_result(
            lambda: service.preview_spatial_candidate(
                principal_resolver(request),
                site_id,
                layout_id,
                str(payload.get("baseRevision") or ""),
                candidate_request,
                candidate_id,
                operations=operations,
            )
        )

    @router.post("/api/facility-layouts/{site_id}/{layout_id}/archive")
    async def archive_layout(
        site_id: str,
        layout_id: str,
        request: Request,
        body: Any = Body(...),
    ):
        try:
            payload = _body_mapping(body)
        except FacilityLayoutError as exc:
            return _error_response(exc)
        return _result(
            lambda: service.archive_layout(
                principal_resolver(request),
                site_id,
                layout_id,
                str(payload.get("baseRevision") or ""),
            )
        )

    @router.post("/api/facility-layouts/{site_id}/{layout_id}/default")
    async def set_default_layout(
        site_id: str,
        layout_id: str,
        request: Request,
    ):
        return _result(
            lambda: service.set_default_layout(
                principal_resolver(request),
                site_id,
                layout_id,
            )
        )

    @router.post("/api/facility-layouts/{site_id}/{layout_id}/validate")
    async def validate_saved_layout(
        site_id: str,
        layout_id: str,
        request: Request,
        body: Any = Body(None),
    ):
        try:
            payload = _body_mapping(body or {})
        except FacilityLayoutError as exc:
            return _error_response(exc)
        document = payload.get("layout")
        if document is None:
            loaded = service.get_layout(
                principal_resolver(request),
                site_id,
                layout_id,
            )
            document = loaded["layout"]
        try:
            document = _body_mapping(document)
        except FacilityLayoutError as exc:
            return _error_response(exc)
        if document.get("layoutId") != layout_id:
            return _error_response(
                FacilityValidationError(
                    "request_identity_mismatch",
                    "Layout path and document identities differ.",
                )
            )
        return _result(
            lambda: service.validate_layout(
                principal_resolver(request),
                site_id,
                document,
            )
        )

    _authority_routes(
        router,
        prefix="/api/facility-shells",
        repository=service.shell_repository,
        principal_resolver=principal_resolver,
    )
    _authority_routes(
        router,
        prefix="/api/facility-policy-sets",
        repository=service.policy_repository,
        principal_resolver=principal_resolver,
    )
    _authority_routes(
        router,
        prefix="/api/facility-vehicle-profiles",
        repository=service.vehicle_repository,
        principal_resolver=principal_resolver,
    )
    return router
