"""Adapt an exact generation preview to the shared editor transaction protocol.

The compatibility field briefRevision carries the generation ledger revision;
it does not create a travel-optimization brief or claim an objective improvement.
"""
from copy import deepcopy

from .authorization import require_facility_action
from .design_brief import design_revision
from .errors import FacilityConflictError, FacilityValidationError
from .generation_admission import PREVIEW_KIND, ADMISSION_KIND, _closed


class GenerationDraftAdapter:
    def __init__(self, admission, design_repository):
        self.admission = admission
        self.repository = design_repository

    def authorize(self, principal, site_id):
        self.admission.require_capability("agent_write")
        self.admission.require_capability("design_loop_apply")
        self.admission._authorize(principal, site_id, "proposal.apply")
        require_facility_action(principal, tenant_id=principal.tenant_id, site_id=site_id, action="proposal.apply")

    def publish(self, principal, *, site_id, layout_id, workspace_id, request, editor_context):
        self.authorize(principal, site_id)
        _closed(request, {"previewId", "previewRevision"}, "selected generation preview")
        preview = self.admission.get_preview(principal, site_id=site_id, layout_id=layout_id,
            workspace_id=workspace_id, preview_id=request["previewId"], preview_revision=request["previewRevision"],
            editor_context=editor_context)
        record = self.admission._load(principal, site_id, layout_id, workspace_id, PREVIEW_KIND, request["previewId"])
        admission = self.admission._load(principal, site_id, layout_id, workspace_id, ADMISSION_KIND,
                                         record["admissionRef"]["artifactId"])
        if admission["contentRevision"] != record["admissionRevision"]:
            raise FacilityConflictError("generation_admission_revision_mismatch", "The selected preview admission changed.")
        key = "generation-" + design_revision({"principalId": principal.principal_id, "siteId": site_id,
            "layoutId": layout_id, "workspaceId": workspace_id, **request})
        operation_batches = [{"label": stage["stageId"], "operations": deepcopy(batch["operations"])}
                             for stage in record["operationPlan"]["stages"]
                             for batch in stage["batches"] if batch["operations"]]

        def store(kind, value):
            digest = design_revision(value)
            self.repository.store_artifact(tenant_id=principal.tenant_id, site_id=site_id,
                artifact_kind=kind, artifact_id=key, artifact_revision=digest, artifact=value)
            return {"artifactKind": kind, "artifactId": key, "artifactRevision": digest}

        candidate = {"candidateLayout": preview["candidateLayout"], "operationBatches": operation_batches,
            "resultLayoutRevision": preview["candidateRevision"], "origin": "generation_preview"}
        candidate_ref = store("generation_editor_candidate", candidate)
        evaluation_ref = store("generation_editor_evaluation", {"origin": "generation_preview",
            "requirements": admission["requirements"], "validation": preview["validation"],
            "optimizationAvailable": False, "productionEligible": False})
        base_ref = store("generation_editor_base", {"layoutId": layout_id, "baseRevision": preview["baseRevision"]})
        proposal = {"origin": "generation_preview", "proposalId": key, "layoutId": layout_id,
            "runId": key, "briefRevision": record["ledgerRevision"], "baseRef": base_ref,
            "resultLayoutRevision": preview["candidateRevision"], "diffHash": design_revision(record["cumulativeDiff"]),
            "operationPlanRevision": record["operationPlan"]["planRevision"],
            "candidateRef": candidate_ref, "evaluationRef": evaluation_ref, "stageReceiptRefs": [],
            "generationRef": {"principalId": principal.principal_id, "workspaceId": workspace_id,
                **deepcopy(request), "editorContext": deepcopy(editor_context)},
            "optimizationAvailable": False, "productionEligible": False}
        proposal_ref = store("design_proposal", proposal)
        self.repository.pin_artifacts(tenant_id=principal.tenant_id, site_id=site_id,
            owner_kind="generation_editor_proposal", owner_id=key,
            artifact_refs=[proposal_ref, candidate_ref, evaluation_ref, base_ref])
        self.admission.repository.pin_artifacts(tenant_id=principal.tenant_id, site_id=site_id,
            owner_kind="generation_editor_proposal", owner_id=key,
            artifact_refs=[self.admission._record_ref(PREVIEW_KIND, request["previewId"]),
                           record["admissionRef"], record["sourceContextRef"]])
        return {"proposalId": key, "proposalRevision": proposal_ref["artifactRevision"],
                "candidateRevision": preview["candidateRevision"], "saved": False, "editorChanged": False}

    def validate(self, principal, site_id, layout_id, proposal, *, adopted=False):
        if proposal.get("origin") != "generation_preview":
            return
        self.authorize(principal, site_id)
        ref = proposal["generationRef"]
        if ref["principalId"] != principal.principal_id or proposal["layoutId"] != layout_id:
            raise FacilityValidationError("generation_draft_scope_mismatch", "Generation selection belongs to another principal or layout.")
        record = self.admission._load(principal, site_id, layout_id, ref["workspaceId"], PREVIEW_KIND, ref["previewId"])
        if (record["contentRevision"] != ref["previewRevision"]
                or record["candidateRevision"] != proposal["resultLayoutRevision"]):
            raise FacilityConflictError("generation_preview_revision_mismatch", "Generation selection differs from its validated preview.")
        self.admission._current(principal, site_id, layout_id, ref["workspaceId"], record, ref["editorContext"],
                                allowed_design_owner=proposal["runId"] if adopted else None)
