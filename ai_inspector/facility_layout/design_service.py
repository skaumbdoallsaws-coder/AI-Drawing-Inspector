"""Service boundary for persistent Facility design briefs and proposals."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from .canonical import canonicalize_layout, layout_revision
from .design_base import (
    facility_design_base_ref,
    validate_facility_design_base,
)
from .design_brief import (
    apply_facility_design_brief_patch,
    canonical_design_bytes,
    create_facility_design_brief,
    design_revision,
)
from .design_repository import (
    FacilityDesignRepository,
    FacilityDesignRepositoryError,
)
from .design_runtime import FacilityDesignRuntime
from .facility_draft_lease import FacilityDraftLeaseRepository
from .feature_flags import FacilityLayoutFeatureFlags


FACILITY_DESIGN_EDITOR_FRAME_VERSION = "facility-design-editor-frame-v1"
FACILITY_DESIGN_TRANSACTION_VERSION = "facility-design-transaction-v1"
FACILITY_DESIGN_EDITOR_FRAME_MAXIMUM_BYTES = 16 * 1024 * 1024


class FacilityDesignServiceError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = deepcopy(dict(details or {}))


def _fail(code: str, message: str, **details: Any) -> None:
    raise FacilityDesignServiceError(code, message, details=details)


def _timestamp(value: datetime) -> str:
    current = value
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


def _identifier(value: Any, field: str) -> str:
    text = str(value or "")
    if (
        not text
        or len(text) > 160
        or not text[0].isalnum()
        or any(
            not (character.isalnum() or character in "._:@+-")
            for character in text
        )
    ):
        _fail("facility_design_request_invalid", f"{field} must be a stable ID.")
    return text


def _revision(value: Any, field: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        _fail(
            "facility_design_request_invalid",
            f"{field} must be a lowercase SHA-256 revision.",
        )
    return text


def _artifact_ref(envelope: Mapping[str, Any]) -> dict[str, str]:
    return {
        "artifactKind": str(envelope["artifactKind"]),
        "artifactId": str(envelope["artifactId"]),
        "artifactRevision": str(envelope["artifactRevision"]),
    }


def validate_facility_design_editor_frame(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    expected = {
        "schemaVersion",
        "baseLayout",
        "baseRevision",
        "draftLayout",
        "draftRevision",
        "batches",
        "cursor",
        "selectedIds",
        "generatedDraft",
        "recentReceiptIds",
        "activeProposal",
        "editorGenerationId",
        "commandJournalHash",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        _fail(
            "facility_design_editor_frame_invalid",
            "Editor frame fields do not match the closed transaction contract.",
        )
    frame = deepcopy(dict(value))
    if frame["schemaVersion"] != FACILITY_DESIGN_EDITOR_FRAME_VERSION:
        _fail(
            "facility_design_editor_frame_invalid",
            "Editor frame version is unsupported.",
        )
    try:
        frame["baseLayout"] = canonicalize_layout(frame["baseLayout"])
        frame["draftLayout"] = canonicalize_layout(frame["draftLayout"])
    except (TypeError, ValueError) as exc:
        raise FacilityDesignServiceError(
            "facility_design_editor_frame_invalid",
            "Editor frame contains invalid Facility geometry.",
        ) from exc
    base_revision = layout_revision(frame["baseLayout"])
    draft_revision = layout_revision(frame["draftLayout"])
    if frame["baseRevision"] != base_revision:
        _fail(
            "facility_design_editor_frame_revision_mismatch",
            "Editor base bytes do not match baseRevision.",
        )
    if frame["draftRevision"] != draft_revision:
        _fail(
            "facility_design_editor_frame_revision_mismatch",
            "Editor draft bytes do not match draftRevision.",
        )
    if not isinstance(frame["batches"], list):
        _fail("facility_design_editor_frame_invalid", "batches must be an array.")
    if (
        isinstance(frame["cursor"], bool)
        or not isinstance(frame["cursor"], int)
        or frame["cursor"] < 0
        or frame["cursor"] > len(frame["batches"])
    ):
        _fail("facility_design_editor_frame_invalid", "cursor is invalid.")
    if not isinstance(frame["selectedIds"], list) or not isinstance(
        frame["recentReceiptIds"], list
    ):
        _fail(
            "facility_design_editor_frame_invalid",
            "Editor selection and receipt IDs must be arrays.",
        )
    frame["editorGenerationId"] = _identifier(
        frame["editorGenerationId"], "editorGenerationId"
    )
    frame["commandJournalHash"] = _revision(
        frame["commandJournalHash"], "commandJournalHash"
    )
    if len(canonical_design_bytes(frame)) > FACILITY_DESIGN_EDITOR_FRAME_MAXIMUM_BYTES:
        _fail(
            "facility_design_editor_frame_limit_exceeded",
            "Editor frame exceeds its canonical byte ceiling.",
            maximumBytes=FACILITY_DESIGN_EDITOR_FRAME_MAXIMUM_BYTES,
        )
    return frame


def facility_design_installation_fingerprint(
    *,
    draft_revision: str,
    proposal_id: str | None,
    proposal_revision: str | None,
    transaction_binding_revision: str | None,
    editor_generation_id: str,
    command_journal_hash: str,
) -> str:
    return design_revision(
        {
            "draftRevision": _revision(draft_revision, "draftRevision"),
            "proposalId": (
                _identifier(proposal_id, "proposalId")
                if proposal_id is not None
                else None
            ),
            "proposalRevision": (
                _revision(proposal_revision, "proposalRevision")
                if proposal_revision is not None
                else None
            ),
            "transactionBindingRevision": (
                _revision(
                    transaction_binding_revision,
                    "transactionBindingRevision",
                )
                if transaction_binding_revision is not None
                else None
            ),
            "editorGenerationId": _identifier(
                editor_generation_id, "editorGenerationId"
            ),
            "commandJournalHash": _revision(
                command_journal_hash, "commandJournalHash"
            ),
        }
    )


class FacilityDesignLoopService:
    """Coordinates FDL artifacts without adding a layout Save path."""

    def __init__(
        self,
        *,
        repository: FacilityDesignRepository,
        runtime: FacilityDesignRuntime,
        lease_repository: FacilityDraftLeaseRepository,
        feature_flags: FacilityLayoutFeatureFlags,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.runtime = runtime
        self.lease_repository = lease_repository
        self.feature_flags = feature_flags
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> str:
        return _timestamp(self._clock())

    def create_brief(
        self,
        *,
        tenant_id: str,
        site_id: str,
        principal_id: str,
        brief_id: str,
        semantic_body: Mapping[str, Any],
        source_turn_ref: str,
        design_base: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.feature_flags.require("design_brief")
        artifact_refs: list[dict[str, str]] = []
        if design_base is not None:
            base = validate_facility_design_base(design_base)
            if (
                base["tenantId"] != tenant_id
                or base["siteId"] != site_id
                or semantic_body.get("layoutId") != base["layoutId"]
                or semantic_body.get("baseStateRef")
                != facility_design_base_ref(base)
            ):
                _fail(
                    "facility_design_base_scope_mismatch",
                    "Design brief and immutable base do not share one exact scope.",
                )
            envelope = self.repository.store_artifact(
                tenant_id=tenant_id,
                site_id=site_id,
                artifact_kind="design_base",
                artifact_id=base["baseId"],
                artifact_revision=base["baseRevision"],
                artifact=base,
            )
            artifact_refs.append(_artifact_ref(envelope))
        brief = create_facility_design_brief(
            brief_id=brief_id,
            semantic_body=semantic_body,
            source_turn_refs=[source_turn_ref],
            principal_id=principal_id,
            created_at=self._now(),
        )
        return self.repository.create_brief(
            tenant_id=tenant_id,
            site_id=site_id,
            brief=brief,
            artifact_refs=artifact_refs,
        )

    def inspect_brief(
        self,
        *,
        tenant_id: str,
        site_id: str,
        brief_id: str,
        brief_revision: str | None = None,
    ) -> dict[str, Any]:
        self.feature_flags.require("design_loop_preview")
        envelope = self.repository.get_brief(
            tenant_id,
            site_id,
            brief_id,
            brief_revision=brief_revision,
        )
        return {
            "head": deepcopy(envelope["head"]),
            # Browser/editor state needs the complete active records so lock,
            # permission, provenance, and correction history remain visible.
            # Sage receives its separately bounded projection at the trusted
            # provider-read boundary.
            "brief": deepcopy(envelope["brief"]),
        }

    def update_brief(
        self,
        *,
        tenant_id: str,
        site_id: str,
        principal_id: str,
        brief_id: str,
        patch: Mapping[str, Any],
        source_turn_ref: str,
    ) -> dict[str, Any]:
        self.feature_flags.require("design_loop_preview")
        current = self.repository.get_brief(tenant_id, site_id, brief_id)
        revised = apply_facility_design_brief_patch(
            current["brief"],
            patch,
            source_turn_ref=source_turn_ref,
            principal_id=principal_id,
            created_at=self._now(),
        )
        envelope = self.repository.advance_brief(
            tenant_id=tenant_id,
            site_id=site_id,
            brief=revised,
            expected_brief_revision=current["brief"]["briefRevision"],
            artifact_refs=[
                {
                    "artifactKind": "design_base",
                    "artifactId": revised["semanticBody"]["baseStateRef"][
                        "baseId"
                    ],
                    "artifactRevision": revised["semanticBody"][
                        "baseStateRef"
                    ]["baseRevision"],
                }
            ],
        )
        return {
            "head": deepcopy(envelope["head"]),
            "brief": deepcopy(envelope["brief"]),
            "receipt": {
                "recordKind": "facility_design_brief_revision_receipt",
                "briefId": brief_id,
                "beforeBriefRevision": current["brief"]["briefRevision"],
                "afterBriefRevision": revised["briefRevision"],
                "briefSemanticFingerprint": revised[
                    "briefSemanticFingerprint"
                ],
                "sourceTurnRef": source_turn_ref,
            },
        }

    def start_preview(self, **arguments: Any) -> dict[str, Any]:
        self.feature_flags.require("design_loop_preview")
        mode = str(arguments.get("mode") or "production_sage")
        self.feature_flags.require(
            "design_loop_lab" if mode == "lab" else "design_loop_sage"
        )
        envelope = self.runtime.start_preview(**arguments)
        return self.runtime.summary(envelope)

    def continue_preview(
        self,
        *,
        tenant_id: str,
        site_id: str,
        run_id: str,
        maximum_tool_calls: int = 10,
    ) -> dict[str, Any]:
        self.feature_flags.require("design_loop_preview")
        envelope = self.runtime.continue_preview(
            tenant_id=tenant_id,
            site_id=site_id,
            run_id=run_id,
            maximum_tool_calls=maximum_tool_calls,
        )
        return self.runtime.summary(envelope)

    def cancel_preview(
        self,
        *,
        tenant_id: str,
        site_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        self.feature_flags.require("design_loop_preview")
        envelope = self.runtime.cancel(
            tenant_id=tenant_id,
            site_id=site_id,
            run_id=run_id,
        )
        return self.runtime.summary(envelope)

    def inspect_proposal(
        self,
        *,
        tenant_id: str,
        site_id: str,
        proposal_id: str,
        proposal_revision: str,
        include_candidate_layout: bool = False,
    ) -> dict[str, Any]:
        self.feature_flags.require("design_loop_preview")
        proposal_envelope = self.repository.get_artifact(
            tenant_id,
            site_id,
            "design_proposal",
            proposal_id,
            proposal_revision,
        )
        proposal = proposal_envelope["artifact"]
        evaluation_ref = proposal["evaluationRef"]
        evaluation = self.repository.get_artifact(
            tenant_id,
            site_id,
            evaluation_ref["artifactKind"],
            evaluation_ref["artifactId"],
            evaluation_ref["artifactRevision"],
        )["artifact"]
        result = {
            "proposal": deepcopy(proposal),
            "evaluation": deepcopy(evaluation),
        }
        if include_candidate_layout:
            candidate_ref = proposal["candidateRef"]
            result["candidate"] = self.repository.get_artifact(
                tenant_id,
                site_id,
                candidate_ref["artifactKind"],
                candidate_ref["artifactId"],
                candidate_ref["artifactRevision"],
            )["artifact"]
        return result

    def prepare_proposal_apply(
        self,
        *,
        tenant_id: str,
        site_id: str,
        proposal_id: str,
        proposal_revision: str,
        root_undo_frame: Mapping[str, Any],
        previous_installation_state: Mapping[str, Any],
        expected_result_editor_generation_id: str,
        expected_result_command_journal_hash: str,
        expected_source_owner: Mapping[str, Any] | None = None,
        transaction_id: str | None = None,
        expected_transaction_revision: str | None = None,
    ) -> dict[str, Any]:
        # These checks intentionally precede all repository and lease access.
        self.feature_flags.require("agent_write")
        self.feature_flags.require("design_loop_apply")
        root = validate_facility_design_editor_frame(root_undo_frame)
        previous = validate_facility_design_editor_frame(
            previous_installation_state
        )
        inspected = self.inspect_proposal(
            tenant_id=tenant_id,
            site_id=site_id,
            proposal_id=proposal_id,
            proposal_revision=proposal_revision,
            include_candidate_layout=True,
        )
        proposal = inspected["proposal"]
        candidate = inspected["candidate"]
        if candidate["resultLayoutRevision"] != proposal["resultLayoutRevision"]:
            _fail(
                "facility_design_proposal_integrity_mismatch",
                "Proposal and candidate result revisions differ.",
            )
        replacement = transaction_id is not None
        existing_transaction = None
        if replacement:
            existing_transaction = self.repository.get_transaction(
                tenant_id,
                site_id,
                _identifier(transaction_id, "transactionId"),
            )
            if existing_transaction["transactionRevision"] != _revision(
                expected_transaction_revision, "expectedTransactionRevision"
            ):
                _fail(
                    "facility_design_transaction_revision_conflict",
                    "Design transaction changed before replacement.",
                )
            if existing_transaction["transaction"]["rootUndoFrameRevision"] != design_revision(root):
                _fail(
                    "facility_design_root_undo_frame_changed",
                    "Replacement must preserve the original root Undo frame.",
                )
            identifier = str(existing_transaction["transaction"]["transactionId"])
            lease_design_run_id = str(
                existing_transaction["transaction"]["designRunId"]
            )
        else:
            identifier = f"fdlt-{uuid4().hex}"
            lease_design_run_id = str(proposal["runId"])
        root_envelope = self.repository.store_artifact(
            tenant_id=tenant_id,
            site_id=site_id,
            artifact_kind="editor_undo_frame",
            artifact_id=f"{identifier}-root",
            artifact_revision=design_revision(root),
            artifact=root,
        )
        previous_envelope = self.repository.store_artifact(
            tenant_id=tenant_id,
            site_id=site_id,
            artifact_kind="editor_installation_state",
            artifact_id=f"{identifier}-{proposal_id}-previous",
            artifact_revision=design_revision(previous),
            artifact=previous,
        )
        root_ref = _artifact_ref(root_envelope)
        previous_ref = _artifact_ref(previous_envelope)
        prior_proposal = previous.get("activeProposal")
        previous_fingerprint = facility_design_installation_fingerprint(
            draft_revision=previous["draftRevision"],
            proposal_id=(
                str(prior_proposal.get("proposalId"))
                if isinstance(prior_proposal, Mapping)
                and prior_proposal.get("proposalId")
                else None
            ),
            proposal_revision=(
                str(prior_proposal.get("proposalRevision"))
                if isinstance(prior_proposal, Mapping)
                and prior_proposal.get("proposalRevision")
                else None
            ),
            transaction_binding_revision=(
                str(prior_proposal.get("transactionBindingRevision"))
                if isinstance(prior_proposal, Mapping)
                and prior_proposal.get("transactionBindingRevision")
                else None
            ),
            editor_generation_id=previous["editorGenerationId"],
            command_journal_hash=previous["commandJournalHash"],
        )
        root_fingerprint = facility_design_installation_fingerprint(
            draft_revision=root["draftRevision"],
            proposal_id=None,
            proposal_revision=None,
            transaction_binding_revision=None,
            editor_generation_id=root["editorGenerationId"],
            command_journal_hash=root["commandJournalHash"],
        )
        proposal_binding = {
            "proposalId": proposal_id,
            "proposalRevision": proposal_revision,
            "briefRevision": proposal["briefRevision"],
            "baseRevision": proposal["baseRef"]["artifactRevision"],
            "resultLayoutRevision": proposal["resultLayoutRevision"],
            "diffHash": proposal["diffHash"],
            "operationPlanRevision": proposal["operationPlanRevision"],
        }
        prepared_shell = {
            "schemaVersion": FACILITY_DESIGN_TRANSACTION_VERSION,
            "transactionId": identifier,
            "designRunId": lease_design_run_id,
            "selectedDesignRunId": proposal["runId"],
            "layoutId": proposal["layoutId"],
            "status": "preparing",
            "rootUndoFrameRef": root_ref,
            "rootUndoFrameRevision": root_ref["artifactRevision"],
            "previousInstallationStateRef": previous_ref,
            "previousInstallationFingerprint": previous_fingerprint,
            "selectedProposalRef": {
                "artifactKind": "design_proposal",
                "artifactId": proposal_id,
                "artifactRevision": proposal_revision,
            },
            "selectedCandidateRef": deepcopy(proposal["candidateRef"]),
            "selectedEvaluationRef": deepcopy(proposal["evaluationRef"]),
            "selectedStageReceiptRefs": deepcopy(
                proposal["stageReceiptRefs"]
            ),
            "previousTransactionRevision": (
                existing_transaction["transactionRevision"]
                if existing_transaction is not None
                else None
            ),
            "proposalBinding": proposal_binding,
            "adoptionId": None,
            "adoptionRevision": None,
            "rootAdoptionId": (
                existing_transaction["transaction"]["rootAdoptionId"]
                if existing_transaction is not None
                else None
            ),
            "rootAdoptionRevision": (
                existing_transaction["transaction"]["rootAdoptionRevision"]
                if existing_transaction is not None
                else None
            ),
            "expectedInstallationFingerprint": None,
            "installationBindingTransactionRevision": None,
            "installedEditorGenerationId": expected_result_editor_generation_id,
            "leaseRevision": None,
            "leaseOwnerToken": None,
            "reviewReason": None,
            "createdAt": (
                existing_transaction["transaction"]["createdAt"]
                if existing_transaction is not None
                else self._now()
            ),
            "updatedAt": self._now(),
        }
        if existing_transaction is None:
            prepared_envelope = self.repository.create_transaction(
                tenant_id=tenant_id,
                site_id=site_id,
                transaction=prepared_shell,
                artifact_refs=self._transaction_artifact_refs(
                    prepared_shell
                ),
            )
        else:
            prepared_envelope = self.repository.advance_transaction(
                tenant_id=tenant_id,
                site_id=site_id,
                transaction=prepared_shell,
                expected_transaction_revision=existing_transaction[
                    "transactionRevision"
                ],
                artifact_refs=self._transaction_artifact_refs(
                    prepared_shell
                ),
            )
        binding_revision = prepared_envelope["transactionRevision"]
        expected_fingerprint = facility_design_installation_fingerprint(
            draft_revision=proposal["resultLayoutRevision"],
            proposal_id=proposal_id,
            proposal_revision=proposal_revision,
            transaction_binding_revision=binding_revision,
            editor_generation_id=expected_result_editor_generation_id,
            command_journal_hash=expected_result_command_journal_hash,
        )
        adoption = self.lease_repository.prepare_adoption(
            tenant_id=tenant_id,
            site_id=site_id,
            layout_id=proposal["layoutId"],
            design_run_id=lease_design_run_id,
            base_saved_layout_revision=root["baseRevision"],
            current_draft_revision=previous["draftRevision"],
            editor_generation_id=previous["editorGenerationId"],
            proposal_binding=proposal_binding,
            expected_source_owner=expected_source_owner,
            root_installation_fingerprint=root_fingerprint,
            previous_installation_fingerprint=previous_fingerprint,
            expected_installation_fingerprint=expected_fingerprint,
        )
        prepared = deepcopy(prepared_envelope["transaction"])
        prepared.update(
            {
                "status": "adoption_prepared",
                "adoptionId": adoption["adoption"]["adoptionId"],
                "adoptionRevision": adoption["adoption"]["adoptionRevision"],
                "rootAdoptionId": prepared["rootAdoptionId"]
                or adoption["adoption"]["adoptionId"],
                "expectedInstallationFingerprint": expected_fingerprint,
                "installationBindingTransactionRevision": binding_revision,
                "leaseRevision": adoption["lease"]["leaseRevision"],
                "leaseOwnerToken": adoption["adoption"]["targetOwnerToken"],
                "updatedAt": self._now(),
            }
        )
        next_envelope = self.repository.advance_transaction(
            tenant_id=tenant_id,
            site_id=site_id,
            transaction=prepared,
            expected_transaction_revision=prepared_envelope[
                "transactionRevision"
            ],
            artifact_refs=self._transaction_artifact_refs(prepared),
        )
        return {
            "transaction": next_envelope,
            "adoption": adoption,
            "candidateLayout": deepcopy(candidate["candidateLayout"]),
            **({"candidateOperationBatches": deepcopy(candidate["operationBatches"])}
               if "operationBatches" in candidate else {"candidateOperations": deepcopy(candidate["operations"])}),
            "expectedInstallationFingerprint": expected_fingerprint,
            "transactionBindingRevision": binding_revision,
        }

    def commit_proposal_apply(
        self,
        *,
        tenant_id: str,
        site_id: str,
        transaction_id: str,
        expected_transaction_revision: str,
        adoption_token: str,
    ) -> dict[str, Any]:
        self.feature_flags.require("agent_write")
        self.feature_flags.require("design_loop_apply")
        envelope = self.repository.get_transaction(
            tenant_id, site_id, transaction_id
        )
        if envelope["transactionRevision"] != expected_transaction_revision:
            _fail(
                "facility_design_transaction_revision_conflict",
                "Design transaction changed before server commit.",
            )
        transaction = envelope["transaction"]
        result = self.lease_repository.commit_adoption(
            tenant_id=tenant_id,
            site_id=site_id,
            adoption_id=transaction["adoptionId"],
            adoption_token=adoption_token,
            expected_adoption_revision=transaction["adoptionRevision"],
            expected_prepared_lease_revision=transaction["leaseRevision"],
            result_draft_revision=transaction["proposalBinding"][
                "resultLayoutRevision"
            ],
        )
        candidate = deepcopy(transaction)
        candidate.update(
            {
                "status": "installation_pending",
                "adoptionRevision": result["adoption"]["adoptionRevision"],
                "leaseRevision": result["lease"]["leaseRevision"],
                "leaseOwnerToken": result["lease"]["ownerToken"],
                "reviewReason": "installation_unacknowledged",
                "updatedAt": self._now(),
            }
        )
        advanced = self.repository.advance_transaction(
            tenant_id=tenant_id,
            site_id=site_id,
            transaction=candidate,
            expected_transaction_revision=envelope["transactionRevision"],
            artifact_refs=self._transaction_artifact_refs(transaction),
        )
        return {"transaction": advanced, **result}

    def acknowledge_proposal_apply(
        self,
        *,
        tenant_id: str,
        site_id: str,
        transaction_id: str,
        expected_transaction_revision: str,
        adoption_token: str,
        observed_installation_fingerprint: str,
    ) -> dict[str, Any]:
        envelope = self.repository.get_transaction(
            tenant_id, site_id, transaction_id
        )
        if envelope["transactionRevision"] != expected_transaction_revision:
            _fail(
                "facility_design_transaction_revision_conflict",
                "Design transaction changed before browser acknowledgment.",
            )
        transaction = envelope["transaction"]
        result = self.lease_repository.acknowledge_adoption(
            tenant_id=tenant_id,
            site_id=site_id,
            adoption_id=transaction["adoptionId"],
            adoption_token=adoption_token,
            expected_adoption_revision=transaction["adoptionRevision"],
            observed_installation_fingerprint=observed_installation_fingerprint,
        )
        candidate = deepcopy(transaction)
        candidate.update(
            {
                "status": "active",
                "adoptionRevision": result["adoption"]["adoptionRevision"],
                "rootAdoptionRevision": (
                    result["adoption"]["adoptionRevision"]
                    if transaction["rootAdoptionId"]
                    == transaction["adoptionId"]
                    else transaction["rootAdoptionRevision"]
                ),
                "leaseRevision": result["lease"]["leaseRevision"],
                "reviewReason": None,
                "updatedAt": self._now(),
            }
        )
        advanced = self.repository.advance_transaction(
            tenant_id=tenant_id,
            site_id=site_id,
            transaction=candidate,
            expected_transaction_revision=envelope["transactionRevision"],
            artifact_refs=self._transaction_artifact_refs(transaction),
        )
        return {"transaction": advanced, **result}

    def save_proposal(
        self,
        *,
        tenant_id: str,
        site_id: str,
        transaction_id: str,
        expected_transaction_revision: str,
        observed_draft_revision: str,
        observed_command_journal_hash: str,
        explicit_approval: bool,
        layout_saver: Callable[[Mapping[str, Any], str], Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Persist the installed proposal and consume its design lease once."""

        self.feature_flags.require("agent_write")
        self.feature_flags.require("design_loop_apply")
        if explicit_approval is not True:
            _fail(
                "facility_design_save_approval_required",
                "Saving a Facility design proposal requires explicit approval.",
            )
        envelope = self.repository.get_transaction(
            tenant_id, site_id, transaction_id
        )
        if envelope["transactionRevision"] != expected_transaction_revision:
            _fail(
                "facility_design_transaction_revision_conflict",
                "Design transaction changed before Save.",
            )
        body = envelope["transaction"]
        if body.get("status") != "active":
            _fail(
                "facility_design_transaction_not_save_eligible",
                "Design transaction is not eligible for Save.",
                status=body.get("status"),
            )
        draft_revision = _revision(
            observed_draft_revision, "observedDraftRevision"
        )
        command_journal_hash = _revision(
            observed_command_journal_hash,
            "observedCommandJournalHash",
        )
        proposal_binding = body["proposalBinding"]
        if draft_revision != proposal_binding["resultLayoutRevision"]:
            _fail(
                "facility_design_save_installation_mismatch",
                "The visible draft is not the installed design proposal.",
            )
        observed_fingerprint = facility_design_installation_fingerprint(
            draft_revision=draft_revision,
            proposal_id=proposal_binding["proposalId"],
            proposal_revision=proposal_binding["proposalRevision"],
            transaction_binding_revision=body[
                "installationBindingTransactionRevision"
            ],
            editor_generation_id=_identifier(
                body.get("installedEditorGenerationId"),
                "installedEditorGenerationId",
            ),
            command_journal_hash=command_journal_hash,
        )
        if observed_fingerprint != body["expectedInstallationFingerprint"]:
            _fail(
                "facility_design_save_installation_mismatch",
                "The visible editor installation does not match the design transaction.",
            )
        candidate_ref = body["selectedCandidateRef"]
        candidate = self.repository.get_artifact(
            tenant_id,
            site_id,
            candidate_ref["artifactKind"],
            candidate_ref["artifactId"],
            candidate_ref["artifactRevision"],
        )["artifact"]
        root_ref = body["rootUndoFrameRef"]
        root_frame = self.repository.get_artifact(
            tenant_id,
            site_id,
            root_ref["artifactKind"],
            root_ref["artifactId"],
            root_ref["artifactRevision"],
        )["artifact"]
        saved = deepcopy(
            dict(
                layout_saver(
                    deepcopy(candidate["candidateLayout"]),
                    root_frame["baseRevision"],
                )
            )
        )
        saved_revision = _revision(
            saved.get("revision"), "savedLayoutRevision"
        )
        consumed = self.lease_repository.consume_after_save(
            tenant_id=tenant_id,
            site_id=site_id,
            adoption_id=body["adoptionId"],
            expected_adoption_revision=body["adoptionRevision"],
            expected_lease_revision=body["leaseRevision"],
            owner_run_id=body["designRunId"],
            owner_token=body["leaseOwnerToken"],
            saved_layout_revision=saved_revision,
        )
        save_receipt = {
            "recordKind": "facility_design_save_receipt",
            "transactionId": transaction_id,
            "proposalId": proposal_binding["proposalId"],
            "proposalRevision": proposal_binding["proposalRevision"],
            "priorSavedLayoutRevision": root_frame["baseRevision"],
            "savedLayoutRevision": saved_revision,
            "leaseConsumptionReceiptRevision": consumed["receipt"][
                "receiptRevision"
            ],
            "savedAt": self._now(),
        }
        save_receipt["receiptRevision"] = design_revision(save_receipt)
        completed = deepcopy(body)
        completed.update(
            {
                "status": "saved",
                "adoptionRevision": consumed["adoption"]["adoptionRevision"],
                "leaseRevision": consumed["lease"]["leaseRevision"],
                "savedLayoutRevision": saved_revision,
                "saveReceiptRevision": save_receipt["receiptRevision"],
                "reviewReason": None,
                "updatedAt": self._now(),
            }
        )
        advanced = self.repository.advance_transaction(
            tenant_id=tenant_id,
            site_id=site_id,
            transaction=completed,
            expected_transaction_revision=envelope["transactionRevision"],
            artifact_refs=self._transaction_artifact_refs(body),
        )
        self.repository.release_owner_pins(
            tenant_id=tenant_id,
            site_id=site_id,
            owner_kind="transaction",
            owner_id=transaction_id,
        )
        return {
            "transaction": advanced,
            "savedLayout": saved,
            "saveReceipt": save_receipt,
            "lease": consumed["lease"],
            "leaseReceipt": consumed["receipt"],
        }

    @staticmethod
    def _transaction_artifact_refs(
        transaction: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        refs = []
        for field in (
            "rootUndoFrameRef",
            "previousInstallationStateRef",
            "selectedProposalRef",
            "selectedCandidateRef",
            "selectedEvaluationRef",
        ):
            value = transaction.get(field)
            if isinstance(value, Mapping):
                refs.append(deepcopy(dict(value)))
        for value in transaction.get("selectedStageReceiptRefs", []):
            if isinstance(value, Mapping):
                refs.append(deepcopy(dict(value)))
        return refs

    def recover_proposal_apply(
        self,
        *,
        tenant_id: str,
        site_id: str,
        transaction_id: str,
        expected_transaction_revision: str,
        observed_installation_fingerprint: str,
    ) -> dict[str, Any]:
        envelope = self.repository.get_transaction(
            tenant_id, site_id, transaction_id
        )
        if envelope["transactionRevision"] != expected_transaction_revision:
            _fail(
                "facility_design_transaction_revision_conflict",
                "Design transaction changed before recovery.",
            )
        body = envelope["transaction"]
        recovered = self.lease_repository.recover_adoption(
            tenant_id=tenant_id,
            site_id=site_id,
            adoption_id=body["adoptionId"],
            expected_adoption_revision=body["adoptionRevision"],
            observed_installation_fingerprint=observed_installation_fingerprint,
        )
        prior_revision = body.get("previousTransactionRevision")
        if prior_revision is not None:
            prior = self.repository.get_transaction(
                tenant_id,
                site_id,
                transaction_id,
                transaction_revision=prior_revision,
            )
            restored = self.repository.restore_transaction_head(
                tenant_id=tenant_id,
                site_id=site_id,
                transaction_id=transaction_id,
                expected_transaction_revision=envelope[
                    "transactionRevision"
                ],
                restore_transaction_revision=prior_revision,
                artifact_refs=self._transaction_artifact_refs(
                    prior["transaction"]
                ),
            )
            return {
                "outcome": "previous_proposal_restored",
                "transaction": restored,
                **recovered,
            }
        failed = deepcopy(body)
        failed.update(
            {
                "status": "installation_failed",
                "adoptionRevision": recovered["adoption"][
                    "adoptionRevision"
                ],
                "leaseRevision": (
                    recovered["lease"]["leaseRevision"]
                    if recovered["lease"] is not None
                    else None
                ),
                "leaseOwnerToken": None,
                "reviewReason": None,
                "updatedAt": self._now(),
            }
        )
        advanced = self.repository.advance_transaction(
            tenant_id=tenant_id,
            site_id=site_id,
            transaction=failed,
            expected_transaction_revision=envelope[
                "transactionRevision"
            ],
            artifact_refs=[body["rootUndoFrameRef"]],
        )
        return {
            "outcome": "root_frame_restored",
            "transaction": advanced,
            **recovered,
        }

    def undo_eligibility(
        self,
        *,
        tenant_id: str,
        site_id: str,
        transaction_id: str,
    ) -> dict[str, Any]:
        transaction = self.repository.get_transaction(
            tenant_id, site_id, transaction_id
        )
        body = transaction["transaction"]
        ownership = self.lease_repository.inspect(
            tenant_id, site_id, body["layoutId"]
        )
        lease = ownership.get("lease")
        coordinated = bool(
            ownership["active"]
            and isinstance(lease, Mapping)
            and lease.get("ownerKind") == "design_run"
            and lease.get("ownerRunId") == body["designRunId"]
            and lease.get("ownerToken") == body["leaseOwnerToken"]
        )
        return {
            "transactionId": transaction_id,
            "transactionRevision": transaction["transactionRevision"],
            "mode": "coordinated" if coordinated else "local_only",
            "readiness": "ready" if coordinated else "stale_local_restore",
            "rootUndoFrameRef": deepcopy(body["rootUndoFrameRef"]),
            "leaseRevision": lease.get("leaseRevision") if coordinated else None,
        }

    def prepare_undo(
        self,
        *,
        tenant_id: str,
        site_id: str,
        transaction_id: str,
        expected_transaction_revision: str,
    ) -> dict[str, Any]:
        envelope = self.repository.get_transaction(
            tenant_id, site_id, transaction_id
        )
        body = envelope["transaction"]

        def expected_revision_is_retryable() -> bool:
            if envelope["transactionRevision"] == expected_transaction_revision:
                return True
            try:
                prior = self.repository.get_transaction(
                    tenant_id,
                    site_id,
                    transaction_id,
                    transaction_revision=expected_transaction_revision,
                )
            except FacilityDesignRepositoryError:
                return False
            return (
                prior["transaction"].get("status") in {"active", "undo_pending"}
                and prior["transaction"].get("rootUndoFrameRef")
                == body.get("rootUndoFrameRef")
            )

        if not expected_revision_is_retryable():
            _fail(
                "facility_design_transaction_revision_conflict",
                "Design transaction changed before Undo.",
            )
        if body.get("status") == "undone":
            frame_ref = body["rootUndoFrameRef"]
            frame = self.repository.get_artifact(
                tenant_id,
                site_id,
                frame_ref["artifactKind"],
                frame_ref["artifactId"],
                frame_ref["artifactRevision"],
            )["artifact"]
            return {
                "mode": "already_undone",
                "readiness": "ready",
                "transaction": envelope,
                "rootUndoFrame": frame,
            }
        eligibility = self.undo_eligibility(
            tenant_id=tenant_id,
            site_id=site_id,
            transaction_id=transaction_id,
        )
        if eligibility["mode"] != "coordinated":
            frame_ref = eligibility["rootUndoFrameRef"]
            frame = self.repository.get_artifact(
                tenant_id,
                site_id,
                frame_ref["artifactKind"],
                frame_ref["artifactId"],
                frame_ref["artifactRevision"],
            )["artifact"]
            return {**eligibility, "rootUndoFrame": frame}
        if body.get("status") == "undo_pending":
            frame_ref = body["rootUndoFrameRef"]
            frame = self.repository.get_artifact(
                tenant_id,
                site_id,
                frame_ref["artifactKind"],
                frame_ref["artifactId"],
                frame_ref["artifactRevision"],
            )["artifact"]
            return {
                "mode": "coordinated",
                "readiness": "undo_acknowledgment_pending",
                "transaction": envelope,
                "rootUndoFrame": frame,
            }
        if body.get("status") != "active":
            _fail(
                "facility_design_transaction_not_undo_eligible",
                "Design transaction is not eligible for Undo.",
                status=body.get("status"),
            )
        pending_lease = self.lease_repository.mark_undo_acknowledgment_pending(
            tenant_id=tenant_id,
            site_id=site_id,
            layout_id=body["layoutId"],
            owner_run_id=body["designRunId"],
            owner_token=body["leaseOwnerToken"],
            expected_lease_revision=body["leaseRevision"],
        )
        body = deepcopy(body)
        body["status"] = "undo_pending"
        body["leaseRevision"] = pending_lease["leaseRevision"]
        body["reviewReason"] = "undo_unacknowledged"
        body["updatedAt"] = self._now()
        advanced = self.repository.advance_transaction(
            tenant_id=tenant_id,
            site_id=site_id,
            transaction=body,
            expected_transaction_revision=envelope["transactionRevision"],
            artifact_refs=[body["rootUndoFrameRef"]],
        )
        frame_ref = body["rootUndoFrameRef"]
        frame = self.repository.get_artifact(
            tenant_id,
            site_id,
            frame_ref["artifactKind"],
            frame_ref["artifactId"],
            frame_ref["artifactRevision"],
        )["artifact"]
        return {
            "mode": "coordinated",
            "readiness": "undo_acknowledgment_pending",
            "transaction": advanced,
            "lease": pending_lease,
            "rootUndoFrame": frame,
        }

    def acknowledge_undo(
        self,
        *,
        tenant_id: str,
        site_id: str,
        transaction_id: str,
        expected_transaction_revision: str,
        observed_draft_revision: str,
        observed_command_journal_hash: str,
    ) -> dict[str, Any]:
        envelope = self.repository.get_transaction(
            tenant_id, site_id, transaction_id
        )
        body = deepcopy(envelope["transaction"])
        frame_ref = body["rootUndoFrameRef"]
        frame = self.repository.get_artifact(
            tenant_id,
            site_id,
            frame_ref["artifactKind"],
            frame_ref["artifactId"],
            frame_ref["artifactRevision"],
        )["artifact"]
        if (
            observed_draft_revision != frame["draftRevision"]
            or observed_command_journal_hash != frame["commandJournalHash"]
        ):
            _fail(
                "facility_design_undo_acknowledgment_mismatch",
                "Browser did not restore the captured root Undo frame.",
            )
        if body.get("status") == "undone":
            try:
                pending = self.repository.get_transaction(
                    tenant_id,
                    site_id,
                    transaction_id,
                    transaction_revision=expected_transaction_revision,
                )
            except FacilityDesignRepositoryError:
                pending = None
            if (
                pending is None
                or pending["transaction"].get("status") != "undo_pending"
                or pending["transaction"].get("rootUndoFrameRef") != frame_ref
            ):
                _fail(
                    "facility_design_transaction_revision_conflict",
                    "Design transaction changed before Undo acknowledgment.",
                )
            ownership = self.lease_repository.inspect(
                tenant_id, site_id, body["layoutId"]
            )
            return {
                "outcome": "already_undone",
                "transaction": envelope,
                "lease": ownership.get("lease"),
            }
        if envelope["transactionRevision"] != expected_transaction_revision:
            _fail(
                "facility_design_transaction_revision_conflict",
                "Design transaction changed before Undo acknowledgment.",
            )
        if body.get("status") != "undo_pending":
            _fail(
                "facility_design_transaction_not_undo_eligible",
                "Design transaction is not awaiting Undo acknowledgment.",
                status=body.get("status"),
            )
        returned = self.lease_repository.return_after_undo(
            tenant_id=tenant_id,
            site_id=site_id,
            adoption_id=body["rootAdoptionId"],
            expected_adoption_revision=body["rootAdoptionRevision"],
            expected_lease_revision=body["leaseRevision"],
            owner_token=body["leaseOwnerToken"],
        )
        body.update(
            {
                "status": "undone",
                "leaseRevision": returned["lease"]["leaseRevision"],
                "reviewReason": None,
                "updatedAt": self._now(),
            }
        )
        advanced = self.repository.advance_transaction(
            tenant_id=tenant_id,
            site_id=site_id,
            transaction=body,
            expected_transaction_revision=envelope["transactionRevision"],
            artifact_refs=[body["rootUndoFrameRef"]],
        )
        self.repository.release_owner_pins(
            tenant_id=tenant_id,
            site_id=site_id,
            owner_kind="transaction",
            owner_id=transaction_id,
        )
        return {"transaction": advanced, **returned}


__all__ = [
    "FACILITY_DESIGN_EDITOR_FRAME_MAXIMUM_BYTES",
    "FACILITY_DESIGN_EDITOR_FRAME_VERSION",
    "FACILITY_DESIGN_TRANSACTION_VERSION",
    "FacilityDesignLoopService",
    "FacilityDesignServiceError",
    "facility_design_installation_fingerprint",
    "validate_facility_design_editor_frame",
]
