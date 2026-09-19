"""Principal-bound construction previews; never writes a layout document."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import re
import time
from typing import Any, Mapping

from shapely.geometry import Point, Polygon

from .authorization import require_facility_action
from .canonical import layout_revision
from .construction_compiler import (CONSTRUCTION_COMMANDS, canonical_bytes,
                                    compile_construction_command, construction_compiler_revision)
from .design_repository import FacilityDesignRepositoryNotFoundError, FacilityDesignRepositoryIntegrityError
from .errors import FacilityConflictError, FacilityNotFoundError, FacilityValidationError

MAX_CHAIN_COMMANDS = 8
MAX_OPERATIONS = 500
MAX_RESPONSE_BYTES = 16384
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
PREVIEW_TTL_SECONDS = 1800


def _hash(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _closed(value, fields):
    if not isinstance(value, Mapping) or set(value) != set(fields):
        raise FacilityValidationError("facility_construction_input_invalid", "Construction request fields do not match the closed contract. Geometry was not evaluated; correct the request before making a fit claim.")


def _text(value, field, *, digest=False):
    pattern = r"[0-9a-f]{64}" if digest else r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}"
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise FacilityValidationError("facility_construction_input_invalid", f"Invalid {field}.")
    return value


def _index(document):
    return {item[field]: item for collection, field in (
        ("placements", "placementId"), ("zones", "zoneId"), ("floorMarkings", "markingId"),
        ("routes", "routeId")) for item in document.get(collection, [])}


class FacilityConstructionService:
    def __init__(self, *, service, agent_runtime, repository, capability_gate, now=time.time):
        self.service = service
        self.agent_runtime = agent_runtime
        self.repository = repository
        self.require_capability = capability_gate
        self.now = now

    def _authorize(self, principal, site_id, action="proposal.create"):
        self.require_capability("construction_sage")
        require_facility_action(principal, tenant_id=principal.tenant_id, site_id=site_id, action=action)

    def _load(self, principal, site_id, layout_id, proposal_id):
        if not isinstance(proposal_id, str) or not re.fullmatch(r"fcp-[0-9a-f]{64}", proposal_id):
            raise FacilityNotFoundError("facility_construction_proposal_not_found", "Construction preview was not found.")
        try:
            record = self.repository.get_artifact(principal.tenant_id, site_id, "construction-preview",
                                                  proposal_id, proposal_id[4:])["artifact"]
        except FacilityDesignRepositoryNotFoundError as exc:
            raise FacilityNotFoundError("facility_construction_proposal_not_found", "Construction preview was not found.") from exc
        if record["layoutId"] != layout_id or record["principalId"] != principal.principal_id:
            raise FacilityNotFoundError("facility_construction_proposal_not_found", "Construction preview was not found.")
        if record["expiresAt"] <= self.now():
            raise FacilityConflictError("facility_construction_expired", "Construction preview expired; request a new preview.")
        return record

    def _bundle(self, principal, site_id, layout_id, base_revision, live_facts=None):
        if live_facts and (live_facts.get("dirty") or live_facts.get("conflict") or live_facts.get("pendingOperations")):
            raise FacilityConflictError("facility_construction_clean_base_required", "This construction pilot requires a clean editor base. Existing edits were not changed.")
        bundle = self.agent_runtime.resolve_context(principal, site_id=site_id, layout_id=layout_id,
                                                    expected_revision=base_revision)
        if bundle.base_layout_revision != base_revision or bundle.generation_run_id is not None:
            raise FacilityConflictError("facility_construction_base_changed", "The construction base changed or has an active generation draft.")
        source_hash = _hash({"layoutRevision": base_revision, "shell": bundle.shell_document,
                             "policy": bundle.policy_document, "catalog": bundle.asset_documents,
                             "evidence": bundle.evidence_authority,
                             "compilerRevision": construction_compiler_revision()})
        return bundle, source_hash

    def _current(self, principal, site_id, layout_id, record):
        bundle, source_hash = self._bundle(principal, site_id, layout_id, record["baseRevision"])
        if source_hash != record["sourceHash"]:
            raise FacilityConflictError("facility_construction_source_changed", "Construction source geometry, catalog, or compiler changed; rebuild the preview.")
        return bundle

    def _summary(self, record):
        result = deepcopy(record["summary"])
        if len(canonical_bytes(result)) > MAX_RESPONSE_BYTES:
            raise FacilityValidationError("facility_construction_response_too_large", "Construction result exceeds the bounded tool response.")
        return result

    def preview(self, principal, *, site_id, layout_id, base_revision, command_id, request, live_facts=None, request_scope=""):
        self._authorize(principal, site_id)
        _closed(request, ("requestId", "parentProposalId", "expectedDraftRevision", "arguments"))
        request_id = _text(request["requestId"], "requestId")
        _text(request["expectedDraftRevision"], "expectedDraftRevision", digest=True)
        _text(base_revision, "baseRevision", digest=True)
        if command_id not in CONSTRUCTION_COMMANDS or not isinstance(request["arguments"], Mapping):
            raise FacilityValidationError("facility_construction_input_invalid", "A supported command and an arguments OBJECT (not a JSON string) are required. Geometry was not evaluated. Retry the same requested envelope with correctly typed arguments; this does not prove the envelope is infeasible.")
        bundle, source_hash = self._bundle(principal, site_id, layout_id, base_revision, live_facts)
        if not isinstance(request_scope, str) or len(request_scope) > 128:
            raise FacilityValidationError("facility_construction_input_invalid", "Invalid trusted retry scope.")
        identity = {"principalId": principal.principal_id, "tenantId": principal.tenant_id, "requestScope": request_scope,
                    "siteId": site_id, "layoutId": layout_id, "requestId": request_id}
        proposal_id = "fcp-" + _hash(identity)
        request_hash = _hash({"commandId": command_id, "request": request, "baseRevision": base_revision})
        try:
            prior = self._load(principal, site_id, layout_id, proposal_id)
        except FacilityNotFoundError:
            prior = None
        if prior:
            if prior["requestHash"] != request_hash:
                raise FacilityConflictError("facility_command_idempotency_conflict", "Construction retry key was reused with different input.")
            self._current(principal, site_id, layout_id, prior)
            return self._summary(prior)
        parent_id = request["parentProposalId"]
        if not isinstance(parent_id, str):
            raise FacilityValidationError("facility_construction_input_invalid", "parentProposalId must be a string, empty for the initial command.")
        if parent_id:
            parent = self._load(principal, site_id, layout_id, parent_id)
            self._current(principal, site_id, layout_id, parent)
            if parent["baseRevision"] != base_revision:
                raise FacilityConflictError("facility_construction_base_changed", "Parent preview belongs to a different base revision.")
            before = parent["candidateLayout"]
            previous_operations = parent["operations"]
            commands = parent["commands"]
        else:
            before, previous_operations, commands = bundle.layout_document, [], []
        if request["expectedDraftRevision"] != layout_revision(before):
            raise FacilityConflictError("facility_command_stale", "Construction draft revision changed.")
        if command_id == "linear-pattern" and parent_id and commands and commands[-1]["commandId"] == "create-cell-group":
            seeds = request["arguments"].get("seedIds")
            if isinstance(seeds, list) and all(isinstance(item, str) for item in seeds):
                for cell in parent["summary"]["cells"]:
                    if set(seeds) == set(cell["memberIds"]):
                        raise FacilityValidationError("facility_construction_cell_seed_required",
                            "This repeats the new cell's members but omits its boundary. To repeat the complete cell, "
                            f"use seedIds=[{cell['cellId']!r}] from the Create Cell receipt, then retry with a new requestId. "
                            "No geometry was changed and no facility-boundary failure was established.",
                            details={"cellId": cell["cellId"], "memberIds": cell["memberIds"]})
        if len(commands) >= MAX_CHAIN_COMMANDS:
            raise FacilityValidationError("facility_construction_chain_limit", "Construction preview chain reached its command limit.")
        operations = compile_construction_command(layout=before, catalog=bundle.asset_documents,
                    command_id=command_id, arguments=request["arguments"], request_id=request_id,
                    namespace=_hash({"proposalId": proposal_id, "requestHash": request_hash})[:40])
        cumulative = previous_operations + operations
        if len(cumulative) > MAX_OPERATIONS:
            raise FacilityValidationError("facility_construction_operation_limit", "Construction operation budget exceeded.")
        validated = self.service.preview_operations(principal, site_id, layout_id, base_revision, cumulative)
        candidate = validated["document"]
        before_entities, after_entities = _index(before), _index(candidate)
        created = sorted(set(after_entities) - set(before_entities))
        changed = sorted(key for key in set(before_entities) & set(after_entities) if before_entities[key] != after_entities[key])
        affected = created + changed
        if len(affected) > 120:
            raise FacilityValidationError("facility_construction_entity_limit", "The construction pilot supports at most 120 affected entities per command.")
        cells = []
        for zone in candidate["zones"]:
            if zone["zoneId"] in created and zone.get("extensions", {}).get("cellGroup"):
                polygon = Polygon([(p["x"], p["z"]) for p in zone["boundary"]])
                members = [p["placementId"] for p in candidate["placements"]
                           if polygon.covers(Point(p["transform"]["position"]["x"], p["transform"]["position"]["z"]))]
                cells.append({"cellId": zone["zoneId"], "label": zone["label"], "memberIds": sorted(members)})
        command_record = {"commandId": command_id, "requestId": request_id, "arguments": deepcopy(request["arguments"])}
        summary = {"proposalId": proposal_id, "baseRevision": base_revision, "candidateRevision": layout_revision(candidate),
                   "commandId": command_id, "commandCount": len(commands) + 1, "createdIds": created, "changedIds": changed,
                   "completedCommandIds": [item["commandId"] for item in commands + [command_record]],
                   "candidateCounts": {"placements": len(candidate["placements"]), "zones": len(candidate["zones"]),
                       "cells": sum(bool(zone.get("extensions", {}).get("cellGroup")) for zone in candidate["zones"])},
                   "cells": cells, "entities": [{key: deepcopy(value) for key, value in after_entities[identifier].items()
                                if key in {"placementId", "assetId", "assetDefinitionRevision", "snapRelationship", "zoneId", "label", "metadata"}}
                                for identifier in affected],
                   "findings": deepcopy(validated.get("findings", []))[:12], "saved": False, "editorChanged": False,
                   "validationScope": "Existing authoritative spatial and routing checks; unverified engineering claims remain unverified.",
                   "qualifications": ["Cell Layout gap is a preferred input, not achieved edge clearance. Do not describe its requested value as measured spacing."]
                       if any(item["commandId"] == "cell-layout" for item in commands + [command_record]) else [],
                   "approvalRequired": True}
        record = {**identity, "proposalId": proposal_id, "requestHash": request_hash, "sourceHash": source_hash,
                  "baseRevision": base_revision, "candidateLayout": candidate, "operations": cumulative,
                  "commands": commands + [command_record], "expiresAt": int(self.now()) + PREVIEW_TTL_SECONDS,
                  "summary": summary}
        self._summary(record)
        if len(canonical_bytes(record)) > MAX_ARTIFACT_BYTES:
            raise FacilityValidationError("facility_construction_artifact_limit", "Construction preview exceeds its artifact byte limit.")
        try:
            self.repository.store_artifact(tenant_id=principal.tenant_id, site_id=site_id,
                artifact_kind="construction-preview", artifact_id=proposal_id, artifact_revision=proposal_id[4:], artifact=record)
        except FacilityDesignRepositoryIntegrityError:
            winner = self._load(principal, site_id, layout_id, proposal_id)
            if winner["requestHash"] != request_hash or winner["sourceHash"] != source_hash:
                raise FacilityConflictError("facility_command_idempotency_conflict", "Concurrent construction request conflicts with the durable retry record.")
            return self._summary(winner)
        return self._summary(record)

    def get_preview(self, principal, *, site_id, layout_id, proposal_id):
        self._authorize(principal, site_id, "proposal.read")
        record = self._load(principal, site_id, layout_id, proposal_id)
        self._current(principal, site_id, layout_id, record)
        return {**self._summary(record), "candidateLayout": deepcopy(record["candidateLayout"])}

    def approve_unsaved(self, principal, *, site_id, layout_id, proposal_id, request):
        self.require_capability("agent_write")
        self._authorize(principal, site_id, "proposal.approve")
        require_facility_action(principal, tenant_id=principal.tenant_id, site_id=site_id, action="proposal.apply")
        _closed(request, ("requestId", "sessionId", "expectedDraftRevision", "editorGenerationId", "candidateRevision"))
        for field in ("requestId", "sessionId", "editorGenerationId"):
            _text(request[field], field)
        record = self._load(principal, site_id, layout_id, proposal_id)
        self._current(principal, site_id, layout_id, record)
        if request["expectedDraftRevision"] != record["baseRevision"] or request["candidateRevision"] != record["summary"]["candidateRevision"]:
            raise FacilityConflictError("facility_command_stale", "Approval does not bind the exact construction preview and editor base.")
        validated = self.service.preview_operations(principal, site_id, layout_id, record["baseRevision"], record["operations"])
        if layout_revision(validated["document"]) != request["candidateRevision"]:
            raise FacilityConflictError("facility_construction_source_changed", "Construction preview no longer reproduces exactly.")
        approval_id = "fca-" + _hash({"principalId": principal.principal_id, "sessionId": request["sessionId"], "requestId": request["requestId"]})
        approval = {"approvalId": approval_id, "proposalId": proposal_id, "principalId": principal.principal_id,
                    "layoutId": layout_id, "binding": deepcopy(dict(request)), "sourceHash": record["sourceHash"]}
        try:
            self.repository.store_artifact(tenant_id=principal.tenant_id, site_id=site_id, artifact_kind="construction-approval",
                                           artifact_id=approval_id, artifact_revision=approval_id[4:], artifact=approval)
        except FacilityDesignRepositoryIntegrityError as exc:
            raise FacilityConflictError("facility_command_idempotency_conflict", "Approval retry key was reused for another editor frame or proposal.") from exc
        return {**approval, "baseRevision": record["baseRevision"], "candidateRevision": request["candidateRevision"],
                "operations": deepcopy(record["operations"]), "candidateLayout": deepcopy(record["candidateLayout"]), "saved": False}
