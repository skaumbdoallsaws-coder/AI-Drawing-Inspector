"""Principal-bound package admission and read-only, deterministic generation previews."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
from typing import Any, Mapping

from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from .authorization import require_facility_action
from .canonical import layout_revision
from .circulation import FacilityCirculationError
from .design_brief import canonical_design_bytes, design_revision
from .design_repository import FacilityDesignRepositoryNotFoundError
from .design_source import _process_map_document
from .errors import FacilityConflictError, FacilityNotFoundError, FacilityValidationError
from .facility_planning import (
    _canonical_evidence_register, _canonical_process_steps,
    canonicalize_facility_planning_package, compile_facility_planning_package,
)
from .facility_program import FacilityProgramError
from .floor_communication import FacilityFloorCommunicationError
from .industrial_patterns import FacilityIndustrialPatternError
from .knowledge_foundation import FacilityKnowledgeContractError
from .generation_requirements import (
    evaluate_generation_requirements, guard_empty_generation_base,
    guard_generation_operations, identifier, revision, require_generation_planning_coverage,
)
from .generation_flow import require_process_coverage, FLOW_SCOPE
from .generation_composition import (MAX_GENERATION_PLACEMENTS, COMPOSITION_FIELDS,
    composition_inventory, require_composition_coverage, validate_composed_inventory)
from .program_execution import (
    FacilityProgramExecutionError, compile_facility_program_operation_plan,
    execute_facility_program_operation_plan,
)


MAX_REQUEST_BYTES = 262_144
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 16_384
MAX_PREVIEW_PLACEMENTS = MAX_GENERATION_PLACEMENTS
SOURCE_KIND = "generation-source-context"
PROVISIONAL_SOURCE_KIND = "generation-provisional-context"
ADMISSION_KIND = "generation-package-admission"
PREVIEW_KIND = "generation-isolated-preview"
SOURCE_SCHEMA = "facility-generation-source-context-v1"
PROVISIONAL_SOURCE_SCHEMA = "facility-generation-provisional-context-v1"
_MODEL_FIELDS = {
    "packageId", "displayName", "facilityEnvelope", "departments", "areaGroups",
    "equipmentRequirements", "routes", "cellRecipes", "moduleFamilies", "floorCommunication",
    "presentationIntent",
}
_SERVER_FIELDS = {"authority", "reviewStatus", "reviewReceiptId", "productionEligible",
                  "reviewedBy", "evidenceRegister", "sourcePackageRefs", "productRef", "processSteps"}


def _fail(code, message, **details):
    raise FacilityValidationError(code, message, details=details)


def _closed(value, fields, name):
    if not isinstance(value, Mapping) or set(value) != set(fields):
        _fail("generation_admission_fields_invalid", f"{name} does not match its closed contract.")


def _bounded(value, maximum, name):
    if len(canonical_design_bytes(value)) > maximum:
        _fail("generation_admission_budget_exceeded", f"{name} exceeds its byte limit.")


def matching_equipment_mappings(context, identity, process_step_refs):
    return [mapping for mapping in context["equipmentMappings"]
            if identity.get("assetId") == mapping["assetId"]
            and identity.get("assetDefinitionRevision") == mapping["assetDefinitionRevision"]
            and set(process_step_refs) == set(mapping["processStepRefs"])]


def _reject_model_authority(value):
    if isinstance(value, Mapping):
        if set(value) & _SERVER_FIELDS:
            _fail("generation_model_authority_forbidden", "Review, evidence and authority are resolved by the server.")
        for child in value.values():
            _reject_model_authority(child)
    elif isinstance(value, list):
        for child in value:
            _reject_model_authority(child)


def generation_compiler_revision():
    """Changes to compilers, requirements or validation invalidate retained previews."""
    root = Path(__file__).parent
    paths = sorted(root.glob("*.py"))
    paths += sorted((root.parents[1] / "static" / "contracts").glob("*.json"))
    return design_revision({str(path.relative_to(root.parents[1])): hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in paths})


class FacilityGenerationAdmissionService:
    def __init__(self, *, service, agent_runtime, repository, capability_gate,
                 lease_repository, process_map_resolver, catalog_provider):
        self.service = service
        self.agent_runtime = agent_runtime
        self.repository = repository
        self.require_capability = capability_gate
        self.leases = lease_repository
        self.resolve_process_map = process_map_resolver
        self.catalog_provider = catalog_provider
        from ai_inspector.research.equipment_documents import EquipmentDocumentLibrary
        self.equipment_documents = EquipmentDocumentLibrary()

    def _authorize(self, principal, site_id, action="proposal.create"):
        self.require_capability("generation_planning_preview")
        self.require_capability("agent_preview")
        require_facility_action(principal, tenant_id=principal.tenant_id, site_id=site_id, action=action)

    def _map(self, principal, site_id, context):
        ref = context["processMapRef"]
        _closed(ref, {"processMapId", "processMapRevision"}, "processMapRef")
        identifier(ref["processMapId"], "processMapId")
        revision(ref["processMapRevision"], "processMapRevision")
        product = context["productRef"]
        _closed(product, {"productId", "productRevision", "displayName"}, "productRef")
        identifier(product["productId"], "productId")
        revision(product["productRevision"], "productRevision")
        resolved = self.resolve_process_map(principal, site_id, product["productId"],
                                            ref["processMapId"], ref["processMapRevision"])
        graph = _process_map_document(resolved, product_id=product["productId"],
                                      process_map_id=ref["processMapId"], process_map_revision=ref["processMapRevision"])
        return graph, resolved

    def _ground_context(self, principal, site_id, context):
        provisional = isinstance(context, Mapping) and context.get("schemaVersion") == PROVISIONAL_SOURCE_SCHEMA
        fields = {"schemaVersion", "contextId", "productRef", "processMapRef", "processSteps",
                  "equipmentMappings", "evidenceRegister", "sourcePackageRefs"}
        _closed(context, fields | ({"assumptions", "unknowns"} if provisional else set()), "source context")
        _bounded(context, MAX_REQUEST_BYTES, "source context")
        if context["schemaVersion"] not in {SOURCE_SCHEMA, PROVISIONAL_SOURCE_SCHEMA}:
            _fail("generation_source_schema_invalid", "Unsupported source-context schema.")
        identifier(context["contextId"], "contextId")
        steps, mappings = context["processSteps"], context["equipmentMappings"]
        if not isinstance(steps, list) or not 1 <= len(steps) <= 32 or not isinstance(mappings, list) or not 1 <= len(mappings) <= 32:
            _fail("generation_source_budget_exceeded", "The prototype supports 1-32 process steps and equipment mappings.")
        evidence = _canonical_evidence_register(context["evidenceRegister"])
        evidence_ids = {item["evidenceId"] for item in evidence}
        _canonical_process_steps(steps, evidence_ids)
        if provisional:
            if context["processMapRef"] is not None:
                _fail("generation_provisional_map_forbidden", "An inferred process cannot impersonate a published Process Map.")
            graph = {"nodes": [{"nodeId": step["processStepId"]} for step in steps],
                     "edges": [{"fromNodeId": prior, "toNodeId": step["processStepId"], "edgeKind": "precedence"}
                               for step in steps for prior in step["predecessorProcessStepIds"]]}
            resolved = {"provenance": "inferred_process_proposal", "reviewStatus": "pending", "graph": graph}
        else:
            graph, resolved = self._map(principal, site_id, context)
        node_ids = {node["nodeId"] for node in graph["nodes"]}
        if (len(node_ids) != len(graph["nodes"])
                or any(edge["fromNodeId"] not in node_ids or edge["toNodeId"] not in node_ids for edge in graph["edges"])):
            _fail("generation_source_process_mismatch", "Process Map contains duplicate or unresolved graph identities.")
        edges = {(edge["fromNodeId"], edge["toNodeId"]) for edge in graph["edges"] if edge["edgeKind"] == "precedence"}
        step_ids = set()
        for step in steps:
            _closed(step, {"processStepId", "label", "predecessorProcessStepIds", "departmentId",
                           "stationRef", "materialAndWipClasses", "evidenceRefs"}, "process step")
            key = identifier(step["processStepId"], "processStepId")
            if key in step_ids or key not in node_ids:
                _fail("generation_source_process_mismatch", "Process step is missing, duplicated or not in the exact Process Map.")
            step_ids.add(key)
        for step in steps:
            expected = {source for source, target in edges if target == step["processStepId"] and source in step_ids}
            predecessors = step["predecessorProcessStepIds"]
            if (not isinstance(predecessors, list) or any(not isinstance(ref, str) for ref in predecessors)
                    or set(predecessors) != expected or len(predecessors) != len(expected)):
                _fail("generation_source_process_mismatch", "Process sequence differs from the authoritative map.")
        catalog = self.catalog_provider(principal, site_id)
        available = {(item["assetId"], item["assetDefinitionRevision"]): item for item in catalog}
        seen = set()
        for mapping in mappings:
            _closed(mapping, {"assetId", "assetDefinitionRevision", "processStepRefs", "evidenceRefs"}, "equipment mapping")
            key = (identifier(mapping["assetId"], "assetId"), revision(mapping["assetDefinitionRevision"], "assetDefinitionRevision"))
            refs = mapping["processStepRefs"]
            if key not in available:
                _fail("generation_source_catalog_stale", "The approved equipment revision is not current in the catalog.")
            if available[key].get("previewPlanningEligible") is not True:
                _fail("generation_source_catalog_ineligible", "Equipment is not eligible for prototype planning previews.")
            if (not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or ref not in step_ids for ref in refs)
                    or len(set(refs)) != len(refs)):
                _fail("generation_source_mapping_invalid", "Equipment mapping needs exact selected process-step IDs.")
            evidence_refs = mapping["evidenceRefs"]
            if (not isinstance(evidence_refs, list) or not evidence_refs
                    or any(not isinstance(ref, str) or ref not in evidence_ids for ref in evidence_refs)):
                _fail("generation_source_mapping_invalid", "Equipment mapping needs evidence present in the source context.")
            binding = (key, tuple(sorted(refs)))
            if binding in seen:
                _fail("generation_source_mapping_invalid",
                      "Duplicate asset/revision/process assignment. Include this mapping once; equipment quantity belongs "
                      "in the resource batch, not repeated mappings. The same asset may have different process assignments.",
                      assetId=key[0], assetDefinitionRevision=key[1], processStepRefs=sorted(refs))
            seen.add(binding)
        return catalog, resolved

    def publish_source_context(self, principal, *, site_id, context):
        """Explicit curator review of a prototype mapping; never exposed as a Sage tool.

        This records the curator's assertion, not automatic engineering approval.
        Evidence editions/variants and real installation capability need human review.
        """
        self._authorize(principal, site_id, "authority.review")
        self._ground_context(principal, site_id, context)
        record = {"context": deepcopy(context), "tenantId": principal.tenant_id, "siteId": site_id,
                  "reviewedBy": principal.principal_id, "reviewScope": "prototype_process_equipment_mapping",
                  "productionEligible": False}
        digest = design_revision(record)
        # Logical IDs may contain colons or Windows device names. They are data,
        # never filesystem path components.
        ref = {"artifactKind": SOURCE_KIND, "artifactId": design_revision({"contextId": context["contextId"]}),
               "artifactRevision": digest}
        self.repository.store_artifact(tenant_id=principal.tenant_id, site_id=site_id, artifact_kind=SOURCE_KIND,
                                        artifact_id=ref["artifactId"], artifact_revision=digest, artifact=record)
        self.repository.pin_artifacts(tenant_id=principal.tenant_id, site_id=site_id,
                                      owner_kind="generation_source_review", owner_id=digest, artifact_refs=[ref])
        return ref

    def _source(self, principal, site_id, source_ref):
        _closed(source_ref, {"artifactKind", "artifactId", "artifactRevision"}, "sourceContextRef")
        kind = source_ref["artifactKind"]
        provisional = kind == PROVISIONAL_SOURCE_KIND
        if kind not in {SOURCE_KIND, PROVISIONAL_SOURCE_KIND}:
            _fail("generation_source_kind_invalid", "A reviewed source-context reference is required.")
        revision(source_ref["artifactId"], "sourceContextRef.artifactId")
        revision(source_ref["artifactRevision"], "sourceContextRef.artifactRevision")
        record = self.repository.get_artifact(principal.tenant_id, site_id, kind,
                                              source_ref["artifactId"], source_ref["artifactRevision"])["artifact"]
        if (design_revision(record) != source_ref["artifactRevision"]
                or record.get("tenantId") != principal.tenant_id or record.get("siteId") != site_id
                or record.get("productionEligible") is not False
                or design_revision({"contextId": record.get("context", {}).get("contextId")}) != source_ref["artifactId"]
                or record.get("reviewScope") != ("unreviewed_process_proposal" if provisional else "prototype_process_equipment_mapping")
                or (provisional and (record.get("principalId") != principal.principal_id or record.get("reviewedBy") is not None
                                     or record.get("context", {}).get("schemaVersion") != PROVISIONAL_SOURCE_SCHEMA))
                or (not provisional and record.get("context", {}).get("schemaVersion") != SOURCE_SCHEMA)):
            _fail("generation_source_integrity_mismatch", "Source context identity, scope or digest is invalid.")
        if not self.repository.artifact_pin_count(principal.tenant_id, site_id, source_ref["artifactRevision"]):
            _fail("generation_source_unpublished", "Source context publication is incomplete.")
        catalog, resolved_map = self._ground_context(principal, site_id, record["context"])
        if record.get("localDocumentRefs"):
            from .generation_exploration import GenerationExploration
            GenerationExploration(self).planning_documents(principal, record, record["localDocumentRefs"])
        return record, catalog, resolved_map

    @staticmethod
    def ledger_source_refs(source_ref, context):
        refs = [{"sourceKind": "evidence", "sourceId": source_ref["artifactId"], "sourceRevision": source_ref["artifactRevision"]},
                {"sourceKind": "product", "sourceId": context["productRef"]["productId"], "sourceRevision": context["productRef"]["productRevision"]}]
        if context["processMapRef"] is not None:
            refs.append({"sourceKind": "process_map", "sourceId": context["processMapRef"]["processMapId"],
                         "sourceRevision": context["processMapRef"]["processMapRevision"]})
        return refs

    def _bundle(self, principal, site_id, layout_id, ledger, editor_context, *, allowed_design_owner=None):
        self.repository.require_current_ledger(principal.tenant_id, site_id, ledger["ledgerId"], ledger["ledgerRevision"])
        if ledger["layoutId"] != layout_id or ledger["tenantId"] != principal.tenant_id or ledger["siteId"] != site_id:
            _fail("generation_ledger_scope_mismatch", "Ledger belongs to a different layout or principal scope.")
        ownership = self.leases.inspect(principal.tenant_id, site_id, layout_id)
        lease = ownership["lease"] or {}
        owned = (allowed_design_owner is not None and lease.get("ownerKind") == "design_run"
                 and lease.get("ownerRunId") == allowed_design_owner)
        if ownership["active"] and not owned:
            raise FacilityConflictError("generation_active_writer", "An active draft owner blocks new-empty-layout planning.")
        bundle = self.agent_runtime.resolve_context(principal, site_id=site_id, layout_id=layout_id,
                                                    expected_revision=ledger["baseRevision"])
        if bundle.generation_run_id is not None:
            raise FacilityConflictError("generation_active_writer", "An active generation draft is not an empty base.")
        guard_empty_generation_base(bundle.layout_document, expected_revision=ledger["baseRevision"],
                                    editor_context=editor_context, mode=ledger["authoringMode"])
        return bundle

    def _identity(self, principal, site_id, layout_id, workspace_id, request_key, kind):
        identifier(request_key, "requestKey")
        identifier(workspace_id, "workspaceId")
        return design_revision({"tenantId": principal.tenant_id, "principalId": principal.principal_id,
                                "siteId": site_id, "layoutId": layout_id, "workspaceId": workspace_id,
                                "requestKey": request_key, "kind": kind})

    def _load(self, principal, site_id, layout_id, workspace_id, kind, artifact_id, *, allow_unpublished=False):
        revision(artifact_id, "artifactId")
        address = design_revision({"artifactKind": kind, "artifactId": artifact_id})
        envelope = self.repository.get_artifact(principal.tenant_id, site_id, kind, artifact_id, address)
        record = envelope["artifact"]
        if (record.get("principalId"), record.get("siteId"), record.get("layoutId"), record.get("workspaceId")) != (
                principal.principal_id, site_id, layout_id, workspace_id):
            raise FacilityNotFoundError("generation_artifact_not_found", "Planning artifact was not found.")
        if record.get("contentRevision") != design_revision({key: value for key, value in record.items() if key != "contentRevision"}):
            _fail("generation_artifact_integrity_mismatch", "Planning artifact content revision is invalid.")
        if not allow_unpublished:
            self.repository.require_published_artifact(principal.tenant_id, site_id, kind, artifact_id, record)
        return record

    @staticmethod
    def _record_ref(kind, artifact_id):
        return {"artifactKind": kind, "artifactId": artifact_id,
                "artifactRevision": design_revision({"artifactKind": kind, "artifactId": artifact_id})}

    def prior_package(self, principal, binding, *, preview_ref=None):
        """Historical proposal observation only; never restores its old eligibility."""
        self._authorize(principal, binding["siteId"], "proposal.read")
        index = (self.repository.latest_preview_reference(principal.tenant_id, binding["siteId"], binding["ledgerId"])
                 if preview_ref is None else {"artifactRef": {"artifactId": revision(preview_ref["previewId"], "previewId")},
                    "contentRevision": revision(preview_ref["previewRevision"], "previewRevision")})
        if index is None:
            return None
        preview = self._load(principal, binding["siteId"], binding["layoutId"], binding["workspaceId"],
                             PREVIEW_KIND, index["artifactRef"]["artifactId"])
        if (preview["ledgerId"] != binding["ledgerId"] or preview["baseRevision"] != binding["baseRevision"]
                or ("ledgerRevision" in index and preview["ledgerRevision"] != index["ledgerRevision"])
                or preview["contentRevision"] != index["contentRevision"]):
            _fail("generation_prior_proposal_mismatch", "Prior proposal does not belong to this brief/base.")
        admission = self._load(principal, binding["siteId"], binding["layoutId"], binding["workspaceId"],
                               ADMISSION_KIND, preview["admissionRef"]["artifactId"])
        if admission["contentRevision"] != preview["admissionRevision"]:
            _fail("generation_prior_proposal_mismatch", "Prior proposal admission revision differs.")
        return {"previewId": index["artifactRef"]["artifactId"], "previewRevision": preview["contentRevision"],
                "ledgerRevision": preview["ledgerRevision"], "packageRevision": admission["packageRevision"],
                "package": deepcopy(admission["modelProposal"]),
                "qualification": "Historical evaluated package. Preserve unchanged fields during correction; the new package must pass current admission and geometry checks."}

    @staticmethod
    def _fingerprint(bundle, catalog, resolved_map, source_record):
        return design_revision({"layout": bundle.layout_document, "shell": bundle.shell_document,
                                "policy": bundle.policy_document, "catalog": catalog, "processMap": resolved_map,
                                "source": source_record, "compilerRevision": generation_compiler_revision()})

    def _current(self, principal, site_id, layout_id, workspace_id, record, editor_context, *, allowed_design_owner=None):
        ledger = self.repository.require_current_ledger(principal.tenant_id, site_id, record["ledgerId"], record["ledgerRevision"])["ledger"]
        if ledger["workspaceId"] != workspace_id:
            _fail("generation_ledger_scope_mismatch", "Ledger belongs to another workspace.")
        bundle = self._bundle(principal, site_id, layout_id, ledger, editor_context, allowed_design_owner=allowed_design_owner)
        source, catalog, resolved = self._source(principal, site_id, record["sourceContextRef"])
        if self._fingerprint(bundle, catalog, resolved, source) != record["sourceFingerprint"]:
            raise FacilityConflictError("generation_sources_changed", "Base, source, policy, catalog or compiler changed; request a new admission.")
        return ledger, bundle, catalog

    def _guard_preserved_proposal(self, principal, site_id, layout_id, workspace_id, ledger, proposal):
        turn = ledger["turns"][-1]["turnId"]
        current = [item for item in ledger["requirements"] if item["source"]["turnId"] == turn
                   and item["disposition"] == "represented" and item["kind"] == "hard_constraint"]
        if not any(item["predicate"]["kind"] == "preserve_prior_requirements" for item in current):
            return
        prior = self.prior_package(principal, {"siteId": site_id, "layoutId": layout_id,
            "workspaceId": workspace_id, "ledgerId": ledger["ledgerId"], "baseRevision": ledger["baseRevision"]})
        if prior is None:
            _fail("generation_preservation_base_missing", "Preservation requires an existing evaluated proposal.")
        # Permission to change a requirement does not authorize rebuilding all
        # unbound design choices. Preserve those too, except explicit new fields.
        bindings = {
            "resource_quantity": ("equipmentRequirements", "requirementId", {"quantity"}),
            "resource_spacing": ("equipmentRequirements", "requirementId", {"authoredSpacing"}),
            "resource_pattern": ("equipmentRequirements", "requirementId", {"placementPattern", "semanticOrientation"}),
            "resource_mapping": ("equipmentRequirements", "requirementId", {"selectedCatalogIdentity", "processStepRefs", "targetArea"}),
            "department_allocation": ("departments", "departmentId", {"label", "zoneType", "areaShare", "row"}),
            **COMPOSITION_FIELDS,
        }
        allowed = set()
        for item in current:
            predicate = item["predicate"]
            if predicate["kind"] == "envelope_dimensions":
                allowed.update(("facilityEnvelope", key) for key in ("width", "depth", "sourceUnit"))
            elif predicate["kind"] in bindings:
                collection, identity, fields = bindings[predicate["kind"]]
                for index, entity in enumerate(prior["package"][collection]):
                    if entity[identity] == predicate["subjectId"]:
                        allowed.update((collection, index, key) for key in fields)

        changed = []
        def compare(before, after, path=()):
            if path in allowed or before == after:
                return
            if isinstance(before, dict) and isinstance(after, dict) and before.keys() == after.keys():
                for key in before:
                    compare(before[key], after[key], (*path, key))
            elif isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
                for index, (left, right) in enumerate(zip(before, after)):
                    compare(left, right, (*path, index))
            else:
                changed.append(".".join(map(str, path)))
        compare(prior["package"], proposal)
        if changed:
            _fail("generation_unrequested_package_change",
                  "This correction must preserve unrequested package fields. Patch the exact prior proposal; do not rebuild it.",
                  changedFields=changed[:16], nextTool="revise_generation_package",
                  previewId=prior["previewId"], previewRevision=prior["previewRevision"])

    def admit(self, principal, *, site_id, layout_id, workspace_id, request, editor_context):
        self._authorize(principal, site_id)
        _bounded(request, MAX_REQUEST_BYTES, "admission request")
        _closed(request, {"requestKey", "ledgerId", "ledgerRevision", "sourceContextRef", "proposal"}, "admission request")
        ledger = self.repository.require_current_ledger(principal.tenant_id, site_id, request["ledgerId"], request["ledgerRevision"])["ledger"]
        if ledger["workspaceId"] != workspace_id:
            _fail("generation_ledger_scope_mismatch", "Ledger belongs to another workspace.")
        bundle = self._bundle(principal, site_id, layout_id, ledger, editor_context)
        proposal = request["proposal"]
        _reject_model_authority(proposal)
        _closed(proposal, _MODEL_FIELDS, "model package proposal")
        self._guard_preserved_proposal(principal, site_id, layout_id, workspace_id, ledger, proposal)
        source, catalog, resolved_map = self._source(principal, site_id, request["sourceContextRef"])
        context = source["context"]
        if source.get("reviewScope") == "unreviewed_process_proposal" and any(source.get(key) != value for key, value in
                (("workspaceId", workspace_id), ("layoutId", layout_id), ("baseRevision", ledger["baseRevision"]))):
            _fail("generation_provisional_scope_mismatch", "Provisional context belongs to another editor/base.")
        needed_refs = {(ref["sourceKind"], ref["sourceId"], ref["sourceRevision"])
                       for ref in self.ledger_source_refs(request["sourceContextRef"], context)}
        actual_refs = {(ref["sourceKind"], ref["sourceId"], ref["sourceRevision"]) for ref in ledger["sourceRefs"]}
        if not needed_refs <= actual_refs:
            _fail("generation_ledger_sources_unbound", "The ledger must bind the exact reviewed context, product and Process Map.")
        if actual_refs != needed_refs:
            _fail("generation_ledger_source_unsupported", "Extra ledger sources need a supported resolver before admission.")
        package = canonicalize_facility_planning_package({
            **deepcopy(proposal), "schemaVersion": "facility-planning-package-v1",
            **{key: deepcopy(context[key]) for key in ("productRef", "sourcePackageRefs", "evidenceRegister", "processSteps")},
            "planningInputs": [], "unresolvedFindings": [],
            "authority": {"knowledgeStatus": "inferred", "authority": "illustrative", "reviewStatus": "pending",
                          "productionEligible": False, "planningClaim": "illustrative_prototype", "reviewReceiptId": None},
        })
        if len(package["departments"]) > 8 or len(package["equipmentRequirements"]) > 24:
            _fail("generation_admission_budget_exceeded", "First-slice planning supports at most eight departments and 24 resource batches.")
        inventory = composition_inventory(package)
        require_composition_coverage(ledger, package, inventory)
        for item in package["equipmentRequirements"]:
            spacing = item.get("authoredSpacing")
            if spacing and any(entry["evidenceId"] == spacing["evidenceRef"] and entry["sourceType"] in {"public_research_result", "local_equipment_document"}
                               for entry in context["evidenceRegister"]):
                _fail("generation_spacing_evidence_not_applicable",
                      "A document-read receipt is not an applicable dimensional fact. Do not attribute a numeric gap to background research. "
                      "Use brief-interpretation only for an authorized, disclosed prototype assumption; if a documented limit is required, retain that requirement as unresolved.",
                      requirementId=item["requirementId"], evidenceRef=spacing["evidenceRef"])
            identity = item["selectedCatalogIdentity"] or {}
            if not any(set(mapping["evidenceRefs"]) <= set(item["evidenceRefs"])
                       for mapping in matching_equipment_mappings(context, identity, item["processStepRefs"])):
                candidates = [mapping for mapping in context["equipmentMappings"] if mapping["assetId"] == identity.get("assetId")]
                _fail("generation_equipment_mapping_unapproved",
                      f"Resource {item['requirementId']} does not match a bound equipment/process assignment and its evidence refs.",
                      requirementId=item["requirementId"], expectedMappings=candidates[:8])
        notes, consulted = self._planning_notes(principal, source, ledger)
        require_process_coverage(ledger, context)
        from .generation_research_policy import GenerationResearchPolicy
        policy = GenerationResearchPolicy(self.repository).overview(principal.tenant_id,
            {"siteId": site_id, "ledgerId": ledger["ledgerId"]})
        if policy["mode"] == "clarify":
            _fail("generation_research_requirement_mismatch", "Clarify the research restriction before previewing.")
        checks = evaluate_generation_requirements(ledger, package, execution_context={
            "catalogIdentities": [{key: item[key] for key in ("assetId", "assetDefinitionRevision")}
                                  for item in catalog if item.get("previewPlanningEligible") is True],
            "consultedSources": consulted, "consultedLocalDocuments": notes["localDocuments"], "assumptionsDisclosed": True,
            "publicWebAllowed": policy["mode"] == "allow" if policy["policyRevision"] else None,
            "compositionInventory": inventory})
        if not checks["requirementsSatisfied"]:
            failed_ids = {item["requirementId"] for item in checks["checks"] if not item["passed"]}
            turn_text = {item["turnId"]: item["text"] for item in ledger["turns"]}
            violations = [{"requirementId": item["requirementId"], "kind": item["kind"],
                "predicate": deepcopy(item["predicate"]), "sourceText": turn_text[item["source"]["turnId"]][
                    item["source"]["start"]:item["source"]["end"]][:1024]}
                for item in ledger["requirements"] if item["requirementId"] in failed_ids]
            _fail("generation_requirements_not_satisfied", "Package does not satisfy all active requirements.",
                  checks=checks["checks"], violations=violations[:8], violationsTruncated=len(violations) > 8)
        require_generation_planning_coverage(ledger, (item["requirementId"] for item in package["equipmentRequirements"]))
        compiled = compile_facility_planning_package(package, catalog)
        if compiled["blockingFindingCount"]:
            _fail("generation_program_not_ready", "Planning package has unresolved compilation requirements.", findings=compiled.get("findings", []))
        artifact_id = self._identity(principal, site_id, layout_id, workspace_id, request["requestKey"], ADMISSION_KIND)
        record = {"principalId": principal.principal_id, "siteId": site_id, "layoutId": layout_id, "workspaceId": workspace_id,
                  "requestHash": design_revision(request), "ledgerId": ledger["ledgerId"], "ledgerRevision": ledger["ledgerRevision"],
                  "baseRevision": ledger["baseRevision"], "sourceContextRef": deepcopy(request["sourceContextRef"]),
                  "sourceFingerprint": self._fingerprint(bundle, catalog, resolved_map, source),
                  "package": package, "modelProposal": deepcopy(proposal), "packageRevision": design_revision(package), "compiled": compiled,
                  "requirements": checks, "compositionInventory": inventory, "saved": False, "editorChanged": False,
                  "processValidation": {"scope": FLOW_SCOPE,
                      "checks": [item for item in checks["checks"] if "processFlow" in item]},
                  "planningNotes": notes,
                  "eligibility": "isolated_prototype_preview_only", "productionEligible": False}
        record["contentRevision"] = design_revision(record)
        _bounded(record, MAX_ARTIFACT_BYTES, "admission artifact")
        self._current(principal, site_id, layout_id, workspace_id, record, editor_context)
        self.repository.publish_current_artifact(tenant_id=principal.tenant_id, site_id=site_id,
            ledger_id=ledger["ledgerId"], ledger_revision=ledger["ledgerRevision"], artifact_kind=ADMISSION_KIND,
            artifact_id=artifact_id, artifact=record, dependency_refs=[request["sourceContextRef"]])
        return {"admissionId": artifact_id, "admissionRevision": record["contentRevision"],
                "packageId": package["packageId"], "packageRevision": record["packageRevision"],
                "ledgerRevision": ledger["ledgerRevision"], "eligibility": record["eligibility"],
                "productionEligible": False, "saved": False, "editorChanged": False}

    def _planning_notes(self, principal, source, ledger):
        context = source["context"]
        context_current = source.get("userTurn", {}).get("turnId") == ledger["turns"][-1]["turnId"]
        context_assumptions = list(context.get("assumptions", []))
        assumptions = context_assumptions if context_current else []
        # Free-text reasons are retained as provenance; the current values come
        # from the executable predicate, not an earlier narrative about it.
        for item in ledger["requirements"]:
            if item["kind"] != "assumption" or item["disposition"] != "represented":
                continue
            predicate = item["predicate"]
            parameters, kind = predicate["parameters"], predicate["kind"]
            if kind == "resource_spacing":
                detail = f"{parameters['value']:g} {parameters['unit']} geometric gap, not approved operating clearance"
            elif kind == "resource_quantity":
                detail = f"{parameters['quantity']} resources (provisional quantity)"
            elif kind == "resource_mapping":
                detail = f"{parameters['assetId']} in {parameters['targetArea']} (provisional process assignment)"
            else:
                values = [f"{key}: {', '.join(map(str, value)) if isinstance(value, list) else value}"
                          for key, value in parameters.items() if key not in {"assetDefinitionRevision", "evidenceRef"}]
                detail = kind.replace("_", " ") + "; " + "; ".join(values)
            assumptions.append(predicate["subjectId"] + ": " + detail)
        assumptions = list(dict.fromkeys(assumptions))
        consulted = []
        if source.get("researchRefs"):
            from .generation_exploration import GenerationExploration
            reader = GenerationExploration(self)
            for index, ref in enumerate(source["researchRefs"]):
                result = reader.planning_research(principal, source, [ref])[0]
                consulted.extend({"evidenceRef": "research-" + str(index), "url": entry["url"], "title": entry["title"]}
                                 for entry in result["sources"] if entry.get("retrieval") == "fetched_document"
                                 and entry["url"] == result["requestedUrl"])
        sources = []
        for entry in consulted:
            if len(entry["url"]) <= 1000 and not any(prior["url"] == entry["url"] for prior in sources):
                sources.append({**entry, "title": entry["title"][:160]})
        local_documents = []
        if source.get("localDocumentRefs"):
            from .generation_exploration import GenerationExploration, local_document_consultations
            local_documents = local_document_consultations(
                GenerationExploration(self).planning_documents(principal, source, source["localDocumentRefs"]))
        notes = {"provisional": context["schemaVersion"] == PROVISIONAL_SOURCE_SCHEMA,
                 "assumptions": assumptions, "unknowns": context.get("unknowns", []),
                 "historicalAssumptions": [] if context_current else context_assumptions,
                 "contextNotesStatus": "current_turn" if context_current else "historical_not_revalidated",
                 "sources": sources[:4], "sourcesTruncated": len(sources) > 4 or any(len(entry["url"]) > 1000 for entry in consulted),
                 "localDocuments": local_documents,
                 "sourceQualification": "Bounded document reads; applicability and engineering limits are not approved."}
        _bounded(notes, MAX_RESPONSE_BYTES - 2500, "visible planning notes")
        return notes, consulted

    @staticmethod
    def _check_floor(bundle, package):
        envelope = package["facilityEnvelope"]
        factor = {"m": 1, "mm": 0.001, "ft": 0.3048, "in": 0.0254}[envelope["sourceUnit"]]
        requested = box(0, 0, envelope["width"] * factor, envelope["depth"] * factor)
        floors = []
        for feature in bundle.shell_document.get("features", []):
            if feature.get("featureKind") not in {"floor", "floor_surface"}:
                continue
            boundary = feature.get("geometry", {}).get("boundary", [])
            if len(boundary) >= 3:
                polygon = Polygon([(point["x"], point["z"]) for point in boundary])
                if polygon.is_valid:
                    floors.append(polygon)
        if not floors or not unary_union(floors).covers(requested):
            _fail("generation_envelope_outside_authored_floor", "The proposed envelope exceeds the bound floor; no floor geometry was invented.")

    def preview(self, principal, *, site_id, layout_id, workspace_id, request, editor_context):
        self._authorize(principal, site_id)
        _bounded(request, MAX_REQUEST_BYTES, "preview request")
        _closed(request, {"requestKey", "admissionId", "admissionRevision"}, "preview request")
        revision(request["admissionRevision"], "admissionRevision")
        admission = self._load(principal, site_id, layout_id, workspace_id, ADMISSION_KIND, request["admissionId"])
        if request["admissionRevision"] != admission["contentRevision"]:
            raise FacilityConflictError("generation_admission_revision_mismatch", "Preview must name the exact admitted revision.")
        ledger, bundle, catalog = self._current(principal, site_id, layout_id, workspace_id, admission, editor_context)
        artifact_id = self._identity(principal, site_id, layout_id, workspace_id, request["requestKey"], PREVIEW_KIND)
        try:
            prior = self._load(principal, site_id, layout_id, workspace_id, PREVIEW_KIND, artifact_id, allow_unpublished=True)
        except FacilityDesignRepositoryNotFoundError:
            prior = None
        if prior is not None:
            if prior["requestHash"] != design_revision(request):
                raise FacilityConflictError("generation_preview_retry_conflict", "Preview retry key identifies another admission.")
            self._current(principal, site_id, layout_id, workspace_id, prior, editor_context)
            self._publish_preview(principal, site_id, artifact_id, prior)
            return self._summary(artifact_id, prior)
        self._check_floor(bundle, admission["package"])
        program = admission["compiled"]["facilityProgram"]
        try:
            plan = compile_facility_program_operation_plan(program, bundle.layout_document, catalog)
        except (FacilityCirculationError, FacilityKnowledgeContractError, FacilityProgramError,
                FacilityIndustrialPatternError, FacilityFloorCommunicationError,
                FacilityProgramExecutionError) as exc:
            # Known compiler refusals are actionable findings, not unexpected read failures.
            raise FacilityValidationError(exc.code, str(exc), details=exc.details) from exc
        operation_batches = []
        for stage in plan["stages"]:
            for batch in stage["batches"]:
                if batch["operations"]:
                    guard_generation_operations(batch["operations"])
                    operation_batches.append(batch["operations"])
        if (sum(map(len, operation_batches)) <= 500
                and not any(admission["package"][k] for k in ("areaGroups", "cellRecipes", "moduleFamilies"))):
            operations = [op for batch in operation_batches for op in batch]
            executed = execute_facility_program_operation_plan(bundle.layout_document, plan)
            validated = self.service.preview_operations(principal, site_id, layout_id, ledger["baseRevision"], operations)
        else:
            validated = self.service.preview_program(principal, site_id, layout_id, ledger["baseRevision"], plan)
            executed = validated["execution"]
        candidate = validated["document"]
        if layout_revision(candidate) != executed["draftLayoutRevision"]:
            _fail("generation_preview_execution_drift", "Authoritative replay differs from the compiled candidate.")
        validate_composed_inventory(candidate, admission["compositionInventory"])
        for name in ("spatialDiagnostics", "routingDiagnostics"):
            diagnostic = validated.get(name)
            if (not isinstance(diagnostic, Mapping) or diagnostic.get("valid") is not True
                    or not isinstance(diagnostic.get("findings"), list)):
                _fail("generation_preview_validation_incomplete", "Required geometry validation did not report a passing result.", diagnostic=name)
            findings = diagnostic["findings"]
            if any(not isinstance(item, Mapping) or item.get("severity") in {"error", "blocked"} for item in findings):
                _fail("generation_preview_validation_failed", "Candidate contains a blocking authoritative finding.", diagnostic=name)
        manifest = {collection: [item[key] for item in candidate.get(collection, [])]
                    for collection, key in (("zones", "zoneId"), ("placements", "placementId"),
                                             ("routes", "routeId"), ("floorMarkings", "markingId"))}
        record = {key: deepcopy(admission[key]) for key in ("principalId", "siteId", "layoutId", "workspaceId",
                  "ledgerId", "ledgerRevision", "baseRevision", "sourceContextRef", "sourceFingerprint", "planningNotes", "processValidation")}
        record.update({"requestHash": design_revision(request), "admissionRef": self._record_ref(ADMISSION_KIND, request["admissionId"]),
                       "admissionRevision": admission["contentRevision"], "candidateLayout": candidate,
                       "candidateRevision": layout_revision(candidate), "operationPlan": plan,
                       "receiptChain": executed["receiptChain"], "cumulativeDiff": executed["cumulativeDiff"],
                       "manifest": manifest, "compositionInventory": deepcopy(admission["compositionInventory"]),
                       "validation": {key: deepcopy(validated[key]) for key in
                           ("findings", "spatialDiagnostics", "routingDiagnostics") if key in validated},
                       "optimizationAvailable": False, "productionEligible": False, "saved": False, "editorChanged": False})
        record["contentRevision"] = design_revision(record)
        _bounded(record, MAX_ARTIFACT_BYTES, "preview artifact")
        self._current(principal, site_id, layout_id, workspace_id, record, editor_context)
        self._publish_preview(principal, site_id, artifact_id, record)
        return self._summary(artifact_id, record)

    def _publish_preview(self, principal, site_id, artifact_id, record):
        return self.repository.publish_current_artifact(tenant_id=principal.tenant_id, site_id=site_id,
            ledger_id=record["ledgerId"], ledger_revision=record["ledgerRevision"], artifact_kind=PREVIEW_KIND,
            artifact_id=artifact_id, artifact=record, dependency_refs=[record["sourceContextRef"], record["admissionRef"]])

    @staticmethod
    def _summary(artifact_id, record):
        findings = [item for name in ("spatialDiagnostics", "routingDiagnostics")
                    for item in record["validation"][name]["findings"]]
        summary = {"previewId": artifact_id, "previewRevision": record["contentRevision"],
                   "planningNotes": deepcopy(record.get("planningNotes", {})),
                   "baseRevision": record["baseRevision"],
                   "candidateRevision": record["candidateRevision"], "ledgerRevision": record["ledgerRevision"],
                   "counts": {key: len(value) for key, value in record["manifest"].items()},
                   "compositionInventory": deepcopy(record.get("compositionInventory", {})),
                   "execution": {"stages": len(record["operationPlan"]["stages"]),
                       "batches": len(record["receiptChain"]),
                       "operations": sum(r["operationCount"] for r in record["receiptChain"])},
                   "zoneKinds": {"operational": sum(zone.get("zoneType") != "aisle" for zone in record["candidateLayout"]["zones"]),
                                 "circulation": sum(zone.get("zoneType") == "aisle" for zone in record["candidateLayout"]["zones"])},
                   "saved": False, "editorChanged": False, "optimizationAvailable": False, "productionEligible": False,
                   "validationStatus": "prototype_geometry_valid",
                   "processValidation": {"scope": record["processValidation"]["scope"],
                       "checkedSequenceCount": len(record["processValidation"]["checks"]),
                       "stationTransfersValidated": False},
                   "warningCount": sum(item.get("severity") == "warning" for item in findings),
                   "unverifiedFindingCount": sum(item.get("severity") == "unverified" for item in findings),
                   "qualification": "Isolated prototype geometry; process bindings, production and safety qualification are not provided."}
        _bounded(summary, MAX_RESPONSE_BYTES, "tool response")
        return summary

    def get_preview(self, principal, *, site_id, layout_id, workspace_id, preview_id, preview_revision, editor_context):
        self._authorize(principal, site_id, "proposal.read")
        record = self._load(principal, site_id, layout_id, workspace_id, PREVIEW_KIND, preview_id)
        if record["contentRevision"] != preview_revision:
            raise FacilityConflictError("generation_preview_revision_mismatch", "Inspection must name the exact preview revision.")
        self._current(principal, site_id, layout_id, workspace_id, record, editor_context)
        return {**self._summary(preview_id, record), "candidateLayout": deepcopy(record["candidateLayout"]),
                "manifest": deepcopy(record["manifest"]), "receiptChain": deepcopy(record["receiptChain"]),
                "validation": deepcopy(record["validation"])}
