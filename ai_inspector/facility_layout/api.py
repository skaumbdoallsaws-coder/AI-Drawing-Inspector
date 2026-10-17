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
FeatureGate = Callable[[str], None]


def _body_mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FacilityValidationError(
            "invalid_request_body",
            "Request body must be a JSON object.",
        )
    return value


def _session_id(request: Request) -> str:
    value = request.headers.get("X-InspectorPro-Session", "").strip()
    if not value or len(value) > 128:
        raise FacilityValidationError(
            "invalid_session_id",
            "X-InspectorPro-Session is required for proposal authority.",
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


def _feature_block(
    feature_gate: FeatureGate | None,
    capability: str,
) -> JSONResponse | None:
    if feature_gate is None:
        return None
    try:
        feature_gate(capability)
    except FacilityLayoutError as exc:
        return _error_response(exc)
    return None


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
    feature_gate: FeatureGate | None = None,
) -> APIRouter:
    """Build an isolated router; the host app decides when to mount it."""

    router = APIRouter()
    from .decal_images import create_decal_image_router
    router.include_router(create_decal_image_router(
        service=service, principal_resolver=principal_resolver, feature_gate=feature_gate))

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
        blocked = _feature_block(feature_gate, "manual_edit")
        if blocked is not None:
            return blocked
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
        blocked = _feature_block(feature_gate, "manual_edit")
        if blocked is not None:
            return blocked
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
        blocked = _feature_block(feature_gate, "manual_edit")
        if blocked is not None:
            return blocked
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
        "/api/facility-layouts/{site_id}/{layout_id}/proposals"
    )
    async def create_layout_proposals(
        site_id: str,
        layout_id: str,
        request: Request,
        body: Any = Body(...),
    ):
        blocked = _feature_block(feature_gate, "agent_preview")
        if blocked is not None:
            return blocked
        try:
            payload = _body_mapping(body)
            planner_request = _body_mapping(payload.get("request"))
        except FacilityLayoutError as exc:
            return _error_response(exc)
        return await _thread_result(
            lambda: service.create_layout_proposals(
                principal_resolver(request),
                site_id,
                layout_id,
                str(payload.get("baseRevision") or ""),
                planner_request,
            )
        )

    @router.post("/api/facility-layouts/{site_id}/{layout_id}/operation-undo-preview")
    async def preview_approved_operation_undo(site_id: str, layout_id: str, request: Request, body: Any = Body(...)):
        blocked = _feature_block(feature_gate, "agent_preview")
        if blocked is not None:
            return blocked
        try:
            payload = _body_mapping(body)
            if (not {"baseRevision", "receiptId"}.issubset(payload)
                    or set(payload) - {"baseRevision", "receiptId", "editMode"}
                    or not all(isinstance(payload[key], str) and 1 <= len(payload[key]) <= 128 for key in payload)):
                raise FacilityValidationError("invalid_request_body", "An exact saved revision and receipt ID are required.")
        except FacilityLayoutError as exc:
            return _error_response(exc)
        from .operation_proposals import create
        return await _thread_result(lambda: create(service, principal_resolver(request), site_id, layout_id,
            payload["baseRevision"], undo_receipt_id=payload["receiptId"], edit_mode=payload.get("editMode", "preview")))

    @router.get(
        "/api/facility-layouts/{site_id}/{layout_id}"
        "/proposals/{proposal_id}/preview"
    )
    async def get_layout_proposal_preview(
        site_id: str,
        layout_id: str,
        proposal_id: str,
        request: Request,
    ):
        blocked = _feature_block(feature_gate, "agent_preview")
        if blocked is not None:
            return blocked
        return await _thread_result(
            lambda: service.get_layout_proposal_preview(
                principal_resolver(request),
                site_id,
                layout_id,
                proposal_id,
            )
        )

    @router.delete(
        "/api/facility-layouts/{site_id}/{layout_id}"
        "/proposals/{proposal_id}"
    )
    async def cancel_layout_proposal(
        site_id: str,
        layout_id: str,
        proposal_id: str,
        request: Request,
    ):
        blocked = _feature_block(feature_gate, "agent_preview")
        if blocked is not None:
            return blocked
        try:
            session_id = _session_id(request)
        except FacilityLayoutError as exc:
            return _error_response(exc)
        return _result(
            lambda: service.cancel_layout_proposal(
                principal_resolver(request),
                site_id,
                layout_id,
                proposal_id,
                session_id,
            )
        )

    @router.post(
        "/api/facility-layouts/{site_id}/{layout_id}/approvals"
    )
    async def approve_layout_proposal(
        site_id: str,
        layout_id: str,
        request: Request,
        body: Any = Body(...),
    ):
        blocked = _feature_block(feature_gate, "agent_write")
        if blocked is not None:
            return blocked
        try:
            payload = _body_mapping(body)
            binding = _body_mapping(payload.get("binding"))
            session_id = _session_id(request)
        except FacilityLayoutError as exc:
            return _error_response(exc)
        return _result(
            lambda: service.approve_layout_proposal(
                principal_resolver(request),
                site_id,
                layout_id,
                str(payload.get("proposalId") or ""),
                binding,
                session_id=session_id,
                idempotency_key=str(
                    payload.get("idempotencyKey") or ""
                ),
                explicit_approval=(
                    payload.get("explicitApproval") is True
                ),
                authorization_mode=payload.get("authorizationMode", "explicit"),
                direct_consent=payload.get("directConsent") is True,
            )
        )

    @router.post(
        "/api/facility-layouts/{site_id}/{layout_id}/apply"
    )
    async def apply_layout_proposal(
        site_id: str,
        layout_id: str,
        request: Request,
        body: Any = Body(...),
    ):
        blocked = _feature_block(feature_gate, "agent_write")
        if blocked is not None:
            return blocked
        try:
            payload = _body_mapping(body)
            binding = _body_mapping(payload.get("binding"))
            session_id = _session_id(request)
        except FacilityLayoutError as exc:
            return _error_response(exc)
        return await _thread_result(
            lambda: service.apply_layout_proposal(
                principal_resolver(request),
                site_id,
                layout_id,
                str(payload.get("approvalToken") or ""),
                binding,
                session_id=session_id,
                idempotency_key=str(
                    payload.get("idempotencyKey") or ""
                ),
            )
        )

    @router.get(
        "/api/facility-layouts/{site_id}/{layout_id}"
        "/receipts/{receipt_id}"
    )
    async def get_layout_receipt(
        site_id: str,
        layout_id: str,
        receipt_id: str,
        request: Request,
    ):
        return _result(
            lambda: service.get_layout_receipt(
                principal_resolver(request),
                site_id,
                layout_id,
                receipt_id,
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
        blocked = _feature_block(feature_gate, "constraints")
        if blocked is not None:
            return blocked
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
        blocked = _feature_block(feature_gate, "constraints")
        if blocked is not None:
            return blocked
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
        blocked = _feature_block(feature_gate, "constraints")
        if blocked is not None:
            return blocked
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

    @router.post(
        "/api/facility-layouts/{site_id}/{layout_id}/routing/diagnostics"
    )
    async def routing_diagnostics(
        site_id: str,
        layout_id: str,
        request: Request,
        body: Any = Body(...),
    ):
        blocked = _feature_block(feature_gate, "routing")
        if blocked is not None:
            return blocked
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
            lambda: service.diagnose_routing(
                principal_resolver(request),
                site_id,
                layout_id,
                str(payload.get("baseRevision") or ""),
                operations=operations,
            )
        )

    @router.post(
        "/api/facility-layouts/{site_id}/{layout_id}/routing/connectors"
    )
    async def routing_connector_candidates(
        site_id: str,
        layout_id: str,
        request: Request,
        body: Any = Body(...),
    ):
        blocked = _feature_block(feature_gate, "routing")
        if blocked is not None:
            return blocked
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
            lambda: service.connector_candidates(
                principal_resolver(request),
                site_id,
                layout_id,
                str(payload.get("baseRevision") or ""),
                candidate_request,
                operations=operations,
            )
        )

    @router.post(
        "/api/facility-layouts/{site_id}/{layout_id}/routing/forklift-plan"
    )
    async def routing_forklift_plan(
        site_id: str,
        layout_id: str,
        request: Request,
        body: Any = Body(...),
    ):
        blocked = _feature_block(feature_gate, "routing")
        if blocked is not None:
            return blocked
        try:
            payload = _body_mapping(body)
            route_request = _body_mapping(payload.get("request"))
            operations = payload.get("operations", [])
            if not isinstance(operations, list):
                raise FacilityValidationError(
                    "invalid_request_body",
                    "operations must be an array.",
                )
        except FacilityLayoutError as exc:
            return _error_response(exc)
        return await _thread_result(
            lambda: service.plan_forklift_route(
                principal_resolver(request),
                site_id,
                layout_id,
                str(payload.get("baseRevision") or ""),
                route_request,
                operations=operations,
            )
        )

    @router.post(
        "/api/facility-layouts/{site_id}/{layout_id}/"
        "navigation/manual-path/validate"
    )
    async def validate_manual_navigation_path(
        site_id: str,
        layout_id: str,
        request: Request,
        body: Any = Body(...),
    ):
        blocked = _feature_block(feature_gate, "navigation_manual")
        if blocked is not None:
            return blocked
        try:
            payload = _body_mapping(body)
            navigation_request = _body_mapping(payload.get("request"))
            operations = payload.get("operations", [])
            if not isinstance(operations, list):
                raise FacilityValidationError(
                    "invalid_request_body",
                    "operations must be an array.",
                )
        except FacilityLayoutError as exc:
            return _error_response(exc)
        return await _thread_result(
            lambda: service.validate_manual_navigation_path(
                principal_resolver(request),
                site_id,
                layout_id,
                str(payload.get("baseRevision") or ""),
                navigation_request,
                operations=operations,
            )
        )

    @router.post(
        "/api/facility-layouts/{site_id}/{layout_id}/"
        "navigation/snapshots/compile"
    )
    async def compile_navigation_snapshot(
        site_id: str,
        layout_id: str,
        request: Request,
        body: Any = Body(...),
    ):
        blocked = _feature_block(feature_gate, "navigation_snapshot")
        if blocked is not None:
            return blocked
        try:
            payload = _body_mapping(body)
            navigation_request = _body_mapping(payload.get("request"))
            operations = payload.get("operations", [])
            if not isinstance(operations, list):
                raise FacilityValidationError(
                    "invalid_request_body",
                    "operations must be an array.",
                )
        except FacilityLayoutError as exc:
            return _error_response(exc)
        return await _thread_result(
            lambda: service.compile_navigation_snapshot(
                principal_resolver(request),
                site_id,
                layout_id,
                str(payload.get("baseRevision") or ""),
                navigation_request,
                operations=operations,
            )
        )

    @router.get(
        "/api/facility-layouts/{site_id}/{layout_id}/"
        "navigation/packages/{package_id}"
    )
    async def get_navigation_snapshot_package(
        site_id: str,
        layout_id: str,
        package_id: str,
        request: Request,
    ):
        blocked = _feature_block(feature_gate, "navigation_snapshot")
        if blocked is not None:
            return blocked
        return await _thread_result(
            lambda: service.get_navigation_snapshot_package(
                principal_resolver(request),
                site_id,
                layout_id,
                package_id,
            )
        )

    @router.post(
        "/api/facility-layouts/{site_id}/{layout_id}/"
        "navigation/journeys/plan"
    )
    async def plan_actor_journey(
        site_id: str,
        layout_id: str,
        request: Request,
        body: Any = Body(...),
    ):
        blocked = _feature_block(feature_gate, "navigation_pedestrian")
        if blocked is not None:
            return blocked
        try:
            payload = _body_mapping(body)
            journey_request = _body_mapping(payload.get("request"))
            operations = payload.get("operations", [])
            if not isinstance(operations, list):
                raise FacilityValidationError(
                    "invalid_request_body",
                    "operations must be an array.",
                )
        except FacilityLayoutError as exc:
            return _error_response(exc)
        return await _thread_result(
            lambda: service.plan_actor_journey(
                principal_resolver(request),
                site_id,
                layout_id,
                str(payload.get("baseRevision") or ""),
                journey_request,
                operations=operations,
            )
        )

    @router.get(
        "/api/facility-layouts/{site_id}/{layout_id}/"
        "navigation/journeys/{journey_solution_id}"
    )
    async def get_actor_journey(
        site_id: str,
        layout_id: str,
        journey_solution_id: str,
        request: Request,
    ):
        blocked = _feature_block(feature_gate, "navigation_pedestrian")
        if blocked is not None:
            return blocked
        return await _thread_result(
            lambda: service.get_actor_journey(
                principal_resolver(request),
                site_id,
                layout_id,
                journey_solution_id,
            )
        )

    @router.post(
        "/api/facility-layouts/{site_id}/{layout_id}/"
        "navigation/handoffs/compile"
    )
    async def compile_navigation_handoff(
        site_id: str,
        layout_id: str,
        request: Request,
        body: Any = Body(...),
    ):
        blocked = _feature_block(feature_gate, "navigation_handoff")
        if blocked is not None:
            return blocked
        try:
            payload = _body_mapping(body)
            handoff_request = _body_mapping(payload.get("request"))
            operations = payload.get("operations", [])
            if not isinstance(operations, list):
                raise FacilityValidationError(
                    "invalid_request_body",
                    "operations must be an array.",
                )
        except FacilityLayoutError as exc:
            return _error_response(exc)
        return await _thread_result(
            lambda: service.compile_navigation_handoff(
                principal_resolver(request),
                site_id,
                layout_id,
                str(payload.get("baseRevision") or ""),
                handoff_request,
                operations=operations,
            )
        )

    @router.get(
        "/api/facility-layouts/{site_id}/{layout_id}/"
        "navigation/handoffs/{handoff_result_id}"
    )
    async def get_navigation_handoff(
        site_id: str,
        layout_id: str,
        handoff_result_id: str,
        request: Request,
    ):
        blocked = _feature_block(feature_gate, "navigation_handoff")
        if blocked is not None:
            return blocked
        return await _thread_result(
            lambda: service.get_navigation_handoff(
                principal_resolver(request),
                site_id,
                layout_id,
                handoff_result_id,
            )
        )

    @router.post(
        "/api/facility-layouts/{site_id}/{layout_id}/"
        "navigation/activity-scenarios"
    )
    async def build_navigation_activity_scenario(
        site_id: str,
        layout_id: str,
        request: Request,
        body: Any = Body(...),
    ):
        blocked = _feature_block(feature_gate, "navigation_multi_actor")
        if blocked is not None:
            return blocked
        try:
            payload = _body_mapping(body)
            activity_request = _body_mapping(payload.get("request"))
            operations = payload.get("operations", [])
            if not isinstance(operations, list):
                raise FacilityValidationError(
                    "invalid_request_body",
                    "operations must be an array.",
                )
        except FacilityLayoutError as exc:
            return _error_response(exc)
        return await _thread_result(
            lambda: service.build_navigation_activity_scenario(
                principal_resolver(request),
                site_id,
                layout_id,
                str(payload.get("baseRevision") or ""),
                activity_request,
                operations=operations,
            )
        )

    @router.post(
        "/api/facility-layouts/{site_id}/{layout_id}/motion-packages"
    )
    async def create_forklift_motion_package(
        site_id: str,
        layout_id: str,
        request: Request,
        body: Any = Body(...),
    ):
        blocked = _feature_block(feature_gate, "routing")
        if blocked is not None:
            return blocked
        try:
            payload = _body_mapping(body)
            motion_request = _body_mapping(payload.get("request"))
            operations = payload.get("operations", [])
            if not isinstance(operations, list):
                raise FacilityValidationError(
                    "invalid_request_body",
                    "operations must be an array.",
                )
        except FacilityLayoutError as exc:
            return _error_response(exc)
        return await _thread_result(
            lambda: service.build_forklift_motion_package(
                principal_resolver(request),
                site_id,
                layout_id,
                str(payload.get("baseRevision") or ""),
                motion_request,
                operations=operations,
            )
        )

    @router.get(
        "/api/facility-layouts/{site_id}/{layout_id}/motion-packages/{package_id}"
    )
    async def get_forklift_motion_package(
        site_id: str,
        layout_id: str,
        package_id: str,
        request: Request,
        active_revision: str | None = Query(None, alias="activeRevision"),
    ):
        blocked = _feature_block(feature_gate, "routing")
        if blocked is not None:
            return blocked
        return _result(
            lambda: service.get_forklift_motion_package(
                principal_resolver(request),
                site_id,
                layout_id,
                package_id,
                active_revision=active_revision,
            )
        )

    @router.post(
        "/api/facility-layouts/{site_id}/{layout_id}/activity-scenarios"
    )
    async def create_prototype_activity_scenario(
        site_id: str,
        layout_id: str,
        request: Request,
        body: Any = Body(...),
    ):
        blocked = _feature_block(feature_gate, "routing")
        if blocked is not None:
            return blocked
        try:
            payload = _body_mapping(body)
            scenario_request = _body_mapping(payload.get("request"))
            operations = payload.get("operations", [])
            if not isinstance(operations, list):
                raise FacilityValidationError(
                    "invalid_request_body",
                    "operations must be an array.",
                )
        except FacilityLayoutError as exc:
            return _error_response(exc)
        return await _thread_result(
            lambda: service.build_prototype_activity_scenario(
                principal_resolver(request),
                site_id,
                layout_id,
                str(payload.get("baseRevision") or ""),
                scenario_request,
                operations=operations,
            )
        )

    @router.get(
        "/api/facility-layouts/{site_id}/{layout_id}/"
        "activity-scenarios/{scenario_id}"
    )
    async def get_prototype_activity_scenario(
        site_id: str,
        layout_id: str,
        scenario_id: str,
        request: Request,
        active_revision: str | None = Query(None, alias="activeRevision"),
    ):
        blocked = _feature_block(feature_gate, "routing")
        if blocked is not None:
            return blocked
        return _result(
            lambda: service.get_prototype_activity_scenario(
                principal_resolver(request),
                site_id,
                layout_id,
                scenario_id,
                active_revision=active_revision,
            )
        )

    @router.post("/api/facility-layouts/{site_id}/{layout_id}/archive")
    async def archive_layout(
        site_id: str,
        layout_id: str,
        request: Request,
        body: Any = Body(...),
    ):
        blocked = _feature_block(feature_gate, "manual_edit")
        if blocked is not None:
            return blocked
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
        blocked = _feature_block(feature_gate, "manual_edit")
        if blocked is not None:
            return blocked
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
