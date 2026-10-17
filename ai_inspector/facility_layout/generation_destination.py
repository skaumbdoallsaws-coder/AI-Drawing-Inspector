"""Explicit creation of an isolated conceptual destination, never a layout replacement."""
from copy import deepcopy

from .authorization import require_facility_action
from .service import coordinate_frame_fingerprint
from .design_brief import design_revision
from .design_repository import FacilityDesignRepositoryNotFoundError
from .errors import FacilityConflictError, FacilityNotFoundError, FacilityValidationError
from .generation_admission import _closed
from .generation_requirements import identifier, revision
from .operations import create_layout_document
from .plan_settings import default_plan_settings, PLAN_SETTINGS_EXTENSION_KEY


def create_generation_destination(host, principal, site_id, layout_id, request, shell_template, timestamp):
    host.generation_draft_adapter.authorize(principal, site_id)
    require_facility_action(principal, tenant_id=principal.tenant_id, site_id=site_id, action="layout.create")
    require_facility_action(principal, tenant_id=principal.tenant_id, site_id=site_id, action="authority.review")
    _closed(request, {"requestKey", "expectedBaseRevision", "displayName", "widthMeters", "depthMeters", "confirmConceptualFloor"}, "new conceptual destination")
    identifier(request["requestKey"], "requestKey")
    revision(request["expectedBaseRevision"], "expectedBaseRevision")
    if request["confirmConceptualFloor"] is not True:
        raise FacilityValidationError("generation_conceptual_floor_approval_required", "Confirm that these are conceptual dimensions, not surveyed site data.")
    name = request["displayName"]
    if not isinstance(name, str) or not name.strip() or len(name) > 160:
        raise FacilityValidationError("generation_destination_name_invalid", "Use a name containing 1-160 characters.")
    try:
        settings = default_plan_settings(width_meters=request["widthMeters"], depth_meters=request["depthMeters"])
    except ValueError as exc:
        raise FacilityValidationError("generation_destination_dimensions_invalid", str(exc)) from exc
    key = design_revision({"principalId": principal.principal_id, "siteId": site_id, "sourceLayoutId": layout_id,
                           "requestKey": request["requestKey"]})
    kind = "generation-destination-request"
    intent = {"request": deepcopy(request), "principalId": principal.principal_id,
              "siteId": site_id, "sourceLayoutId": layout_id, "layoutId": "fl-concept-" + key[:32]}
    repository = host.generation_requirement_repository
    try:
        prior = repository.get_artifact(principal.tenant_id, site_id, kind, key, key)["artifact"]
        if prior != intent:
            raise FacilityConflictError("generation_destination_retry_conflict", "Destination request key was already used for different dimensions or identity.")
    except FacilityDesignRepositoryNotFoundError:
        current = host.service.get_layout(principal, site_id, layout_id)
        if current["revision"] != request["expectedBaseRevision"]:
            raise FacilityConflictError("generation_destination_base_changed", "The selected source layout changed.")
        repository.store_artifact(tenant_id=principal.tenant_id, site_id=site_id, artifact_kind=kind,
                                 artifact_id=key, artifact_revision=key, artifact=intent)
    try:
        existing = host.service.get_layout(principal, site_id, intent["layoutId"])
        return {"layoutId": intent["layoutId"], "revision": existing["revision"], "created": False,
                "qualification": "Conceptual destination; not surveyed site geometry."}
    except FacilityNotFoundError:
        pass
    current = host.service.get_layout(principal, site_id, layout_id)
    if current["revision"] != request["expectedBaseRevision"]:
        raise FacilityConflictError("generation_destination_base_changed", "The source layout changed before destination creation.")
    shell = deepcopy(shell_template)
    shell.update(shellId="shell-concept-" + key[:32], tenantId=principal.tenant_id, siteId=site_id)
    width, depth = settings["widthMeters"], settings["depthMeters"]
    shell["features"][0]["geometry"]["boundary"] = [
        {"x": 0, "z": 0}, {"x": width, "z": 0}, {"x": width, "z": depth}, {"x": 0, "z": depth}]
    shell["unresolvedItems"] = [{"findingId": "conceptual-floor", "code": "conceptual_floor_requires_site_review",
        "message": "User-authorized conceptual dimensions only. Not measured or reviewed site geometry; no installation or safety approval."}]
    authority = host.shell_repository
    try:
        envelope = authority.get_current(principal, site_id=site_id, authority_id=shell["shellId"])
    except FacilityNotFoundError:
        envelope = authority.create(principal, site_id=site_id, document=shell).envelope
    if envelope.status == "draft":
        envelope = authority.review(principal, site_id=site_id, authority_id=shell["shellId"], expected_revision=envelope.revision).envelope
    if envelope.status == "reviewed":
        envelope = authority.publish(principal, site_id=site_id, authority_id=shell["shellId"], expected_revision=envelope.revision).envelope
    frame = shell["coordinateFrame"]
    document = create_layout_document(layout_id=intent["layoutId"], display_name=name.strip(),
        association=deepcopy(current["layout"]["association"]), coordinate_frame=frame,
        source_shell_ref={"shellId": shell["shellId"], "shellRevision": envelope.revision,
                          "coordinateFrameFingerprint": coordinate_frame_fingerprint(frame)},
        policy_set_ref=deepcopy(current["layout"]["policySetRef"]), created_at=timestamp)
    document.setdefault("extensions", {})[PLAN_SETTINGS_EXTENSION_KEY] = settings
    created = host.service.create_layout(principal, site_id, document, make_default=False)
    repository.pin_artifacts(tenant_id=principal.tenant_id, site_id=site_id,
        owner_kind="generation_destination", owner_id=key,
        artifact_refs=[{"artifactKind": kind, "artifactId": key, "artifactRevision": key}])
    return {"layoutId": intent["layoutId"], "revision": created["revision"], "created": True,
            "qualification": "Conceptual destination; not surveyed site geometry."}
