"""Durable, idempotent conversation-turn orchestration for Sage memory."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import threading
from concurrent.futures import Future
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional, Sequence

from .invalidation import normalize_revision_vector, revision_vector_sha256
from .envelope import finalize_context_manifest
from .ids import is_memory_id
from .models import (
    AgentSessionRecord,
    MemoryPrincipal,
    TurnRecord,
    canonical_sha256,
)
from .policy import (
    MEMORY_SCHEMA_VERSION,
    REQUEST_HASH_VERSION,
    SEMANTIC_TARGET_FIELDS,
    request_identity_sha256_v1,
)
from .repository import MemoryRepository


TURN_CLASSIFICATIONS = frozenset({"read_only", "preview", "action_write"})
CAS_SUCCESS_OUTCOMES = frozenset({"applied", "committed", "success", "succeeded"})
CAS_NO_EFFECT_OUTCOMES = frozenset({"not_applicable", "not_attempted"})
_ACTIVE_MEMORY_TURN: ContextVar[Optional[TurnRecord]] = ContextVar(
    "active_memory_turn", default=None
)


def active_memory_turn() -> Optional[TurnRecord]:
    """Return the server-owned pending turn in the current execution context."""

    return _ACTIVE_MEMORY_TURN.get()


@dataclass(frozen=True)
class TrustedTurnContext:
    """Current server-resolved scope and revision facts for one request."""

    asset_scope: Dict[str, Any]
    scope_fingerprint: Optional[str]
    revision_vector: Dict[str, str]
    workflow_mode: str


@dataclass(frozen=True)
class TurnExecutionResult:
    result: Dict[str, Any]
    turn: TurnRecord
    replayed: bool


class TurnLifecycleError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = int(status_code)
        self.details = copy.deepcopy(dict(details or {}))


def classify_turn(
    message: str,
    action_parameters: Optional[Mapping[str, Any]] = None,
) -> str:
    """Conservatively classify a turn before any tool can be authorized."""

    parameters = dict(action_parameters or {})
    explicit = str(
        parameters.get("turnClassification")
        or parameters.get("turn_classification")
        or ""
    ).strip().lower()
    preview_only = parameters.get("previewOnly") is True
    if preview_only or explicit == "preview":
        return "preview"

    normalized = " ".join(str(message or "").strip().lower().split())
    preview_terms = (
        "ghost preview",
        "show a preview",
        "preview for my approval",
        "do not commit",
        "don't commit",
        "without committing",
    )
    action_terms = (
        " add ",
        " apply ",
        " approve ",
        " arrange ",
        " build ",
        " clear ",
        " commit ",
        " connect ",
        " create ",
        " delete ",
        " duplicate ",
        " fill ",
        " generate ",
        " highlight ",
        " insert ",
        " move ",
        " populate ",
        " remove ",
        " route ",
        " save ",
        " set ",
        " update ",
    )
    padded = f" {normalized} "
    if any(term in normalized for term in preview_terms):
        return "preview"
    if explicit == "action_write" or parameters:
        return "action_write"
    if any(term in padded for term in action_terms):
        return "action_write"
    return "read_only"


def image_sha256_values(image: Optional[str]) -> list[str]:
    """Hash current image input without persisting its raw bytes in memory."""

    if not isinstance(image, str) or not image:
        return []
    value = image
    if value.startswith("data:") and "," in value:
        value = value.split(",", 1)[1]
    return [hashlib.sha256(value.encode("utf-8")).hexdigest()]


def build_request_identity_v1(
    *,
    message: str,
    agent_type: str,
    trusted_context: TrustedTurnContext,
    request_context: Optional[Mapping[str, Any]],
    action_parameters: Optional[Mapping[str, Any]],
    image_sha256: Sequence[str],
    cross_agent_context: Optional[str],
    memory_schema_version: str = MEMORY_SCHEMA_VERSION,
    request_hash_version: int = REQUEST_HASH_VERSION,
    require_client_context: bool = True,
) -> tuple[Dict[str, Any], str]:
    """Build and validate the frozen v1 identity against trusted scope facts."""

    supplied = dict(request_context or {})
    unknown = set(supplied) - {"asset_scope", "semantic_targets"}
    if unknown:
        raise TurnLifecycleError(
            "invalid_request_context",
            f"request_context contains unsupported fields: {sorted(unknown)}",
            status_code=422,
        )
    if require_client_context and not request_context:
        raise TurnLifecycleError(
            "memory_identity_required",
            "request_context is required while memory enforcement is enabled",
            status_code=422,
        )

    client_scope = supplied.get("asset_scope")
    if client_scope is None:
        client_scope = copy.deepcopy(trusted_context.asset_scope)
    semantic_targets = supplied.get("semantic_targets")
    if semantic_targets is None:
        semantic_targets = {field: [] for field in SEMANTIC_TARGET_FIELDS}

    raw = {
        "requestHashVersion": request_hash_version,
        "message": message,
        "agentType": agent_type,
        "workflowMode": trusted_context.workflow_mode,
        "assetScope": client_scope,
        "semanticTargets": semantic_targets,
        "imageSha256": list(image_sha256),
        "actionParameters": dict(action_parameters or {}),
        "crossAgentProjectionSha256": (
            hashlib.sha256(cross_agent_context.encode("utf-8")).hexdigest()
            if isinstance(cross_agent_context, str) and cross_agent_context
            else None
        ),
        "memorySchemaVersion": memory_schema_version,
    }
    try:
        identity, request_sha256 = request_identity_sha256_v1(raw)
    except (TypeError, ValueError) as exc:
        raise TurnLifecycleError(
            "invalid_request_identity",
            str(exc),
            status_code=422,
        ) from exc
    _validate_client_scope(identity["assetScope"], trusted_context.asset_scope)
    return identity, request_sha256


def evaluate_revision_barrier(
    *,
    classification: str,
    source_revision_vector: Mapping[str, Any],
    pre_effect_revision_vector: Mapping[str, Any],
    current_revision_vector: Mapping[str, Any],
    receipts: Sequence[Any] = (),
    cas_outcome: str = "not_applicable",
) -> Dict[str, Any]:
    """Evaluate the frozen pending-turn barrier without performing an effect."""

    if classification not in TURN_CLASSIFICATIONS:
        raise ValueError("unsupported turn classification")
    source = normalize_revision_vector(source_revision_vector)
    pre_effect = normalize_revision_vector(pre_effect_revision_vector)
    current = normalize_revision_vector(current_revision_vector)
    normalized_receipts = [copy.deepcopy(item) for item in receipts if isinstance(item, dict)]
    effect_count = sum(
        1
        for receipt in normalized_receipts
        if str(
            receipt.get("casOutcome") or receipt.get("cas_outcome") or ""
        ).strip().lower()
        in CAS_SUCCESS_OUTCOMES
        or isinstance(receipt.get("resultingRevisionVector"), dict)
    )
    if cas_outcome == "not_applicable" and normalized_receipts:
        cas_outcome = str(
            normalized_receipts[-1].get("casOutcome")
            or normalized_receipts[-1].get("cas_outcome")
            or ("applied" if effect_count else "not_attempted")
        )
    cas_outcome = str(cas_outcome or "not_applicable").strip().lower()

    pre_drift = source != pre_effect
    current_drift = source != current
    error_code: Optional[str] = None
    terminal_status = "committed"
    post_effect_drift = False
    resulting = current

    if classification in {"preview", "action_write"} and pre_drift:
        terminal_status = "failed"
        error_code = "revision_advanced_during_turn"
        effect_count = 0
    elif (
        classification == "action_write"
        and cas_outcome not in CAS_NO_EFFECT_OUTCOMES
        and cas_outcome not in CAS_SUCCESS_OUTCOMES
    ):
        terminal_status = "failed"
        error_code = "cas_conflict"
        effect_count = 0
    elif classification in {"preview", "action_write"} and current_drift:
        successful_receipt = normalized_receipts[-1] if effect_count else None
        if successful_receipt is None:
            terminal_status = "failed"
            error_code = "revision_advanced_during_turn"
        else:
            receipt_result = successful_receipt.get("resultingRevisionVector")
            if isinstance(receipt_result, dict):
                resulting = normalize_revision_vector(receipt_result)
            else:
                resulting = source
            post_effect_drift = current != resulting

    return {
        "classification": classification,
        "sourceRevisionVector": source,
        "preEffectRevisionVector": pre_effect,
        "currentRevisionVector": current,
        "resultingRevisionVector": resulting,
        "casOutcome": cas_outcome,
        "terminalStatus": terminal_status,
        "errorCode": error_code,
        "effectCount": effect_count,
        "revisionAdvancedDuringTurn": current_drift or pre_drift,
        "postEffectRevisionDrift": post_effect_drift,
    }


class TurnLifecycleService:
    """Coordinate pending, terminal, retry, cancellation, and revision barriers."""

    def __init__(
        self,
        repository: MemoryRepository,
        *,
        mode: str,
        stale_pending_seconds: float = 300.0,
        conversation_retention_seconds: Optional[float] = None,
        workflow_ttl_seconds: float = 86400.0,
    ) -> None:
        if mode not in {"shadow", "compare", "enforce"}:
            raise ValueError("active memory mode must be shadow, compare, or enforce")
        if stale_pending_seconds <= 0:
            raise ValueError("stale_pending_seconds must be positive")
        if (
            conversation_retention_seconds is not None
            and conversation_retention_seconds <= 0
        ):
            raise ValueError("conversation retention must be positive")
        if workflow_ttl_seconds <= 0:
            raise ValueError("workflow-state TTL must be positive")
        self.repository = repository
        self.mode = mode
        self.stale_pending_seconds = float(stale_pending_seconds)
        self.conversation_retention_seconds = (
            float(conversation_retention_seconds)
            if conversation_retention_seconds is not None
            else None
        )
        self.workflow_ttl_seconds = float(workflow_ttl_seconds)
        self._inflight: Dict[str, Future[TurnRecord]] = {}
        self._inflight_lock = threading.RLock()

    async def execute(
        self,
        *,
        principal: MemoryPrincipal,
        conversation_id: str,
        agent_session_id: str,
        client_turn_id: str,
        request_identity: Mapping[str, Any],
        user_message: Mapping[str, Any],
        trusted_context: TrustedTurnContext,
        classification: str,
        execute: Callable[[], Awaitable[Mapping[str, Any]]],
        resolve_current_context: Callable[[], TrustedTurnContext],
        route_metadata: Optional[Mapping[str, Any]] = None,
        model_metadata: Optional[Mapping[str, Any]] = None,
    ) -> TurnExecutionResult:
        if classification not in TURN_CLASSIFICATIONS:
            raise TurnLifecycleError(
                "invalid_turn_classification",
                "turn classification is invalid",
                status_code=422,
            )
        started = self.repository.start_turn(
            principal,
            conversation_id,
            agent_session_id,
            client_turn_id=client_turn_id,
            request_identity=request_identity,
            user_message=user_message,
            scope_fingerprint=trusted_context.scope_fingerprint,
            source_revision_vector=trusted_context.revision_vector,
            route_metadata=route_metadata,
            model_metadata=model_metadata,
        )
        if started.disposition == "created":
            self._refresh_conversation_retention(
                principal, conversation_id
            )
        if started.disposition == "existing_committed":
            return self._committed_result(principal, started.turn, replayed=True)
        if started.disposition == "existing_pending":
            return await self._join_or_recover_pending(principal, started.turn)
        if started.disposition.startswith("existing_"):
            raise TurnLifecycleError(
                "turn_already_terminal",
                f"turn is already {started.turn.status}",
                details={"turnId": started.turn.turn_id, "status": started.turn.status},
            )

        turn = started.turn
        future: Future[TurnRecord] = Future()
        with self._inflight_lock:
            self._inflight[turn.turn_id] = future
        try:
            pre_effect_context = trusted_context
            if classification in {"preview", "action_write"}:
                pre_effect_context = resolve_current_context()
                pre_barrier = evaluate_revision_barrier(
                    classification=classification,
                    source_revision_vector=trusted_context.revision_vector,
                    pre_effect_revision_vector=pre_effect_context.revision_vector,
                    current_revision_vector=pre_effect_context.revision_vector,
                    cas_outcome="not_attempted",
                )
                if pre_barrier["terminalStatus"] == "failed":
                    raise TurnLifecycleError(
                        str(pre_barrier["errorCode"]),
                        "trusted source revisions advanced before execution",
                        details=pre_barrier,
                    )

            active_turn_token = _ACTIVE_MEMORY_TURN.set(turn)
            try:
                raw_result = await execute()
            finally:
                _ACTIVE_MEMORY_TURN.reset(active_turn_token)
            result = copy.deepcopy(dict(raw_result))
            result.pop("memory", None)
            continuity_metadata = result.pop("_memory_continuity", None)
            reconciliation_metadata = result.pop(
                "_memory_reconciliation", None
            )
            prepared_envelope = result.pop("_memory_envelope", None)
            receipts = _result_receipts(result)
            current_context = resolve_current_context()
            cas_outcome = _result_cas_outcome(result, receipts)
            barrier = evaluate_revision_barrier(
                classification=classification,
                source_revision_vector=trusted_context.revision_vector,
                pre_effect_revision_vector=pre_effect_context.revision_vector,
                current_revision_vector=current_context.revision_vector,
                receipts=receipts,
                cas_outcome=cas_outcome,
            )
            if barrier["terminalStatus"] == "failed":
                raise TurnLifecycleError(
                    str(barrier["errorCode"]),
                    "trusted source revisions advanced during the turn",
                    details=barrier,
                )

            self._persist_session_state(
                principal,
                turn.agent_session_id,
                result,
                current_context,
            )

            final_route_metadata = _result_route_metadata(result, route_metadata)
            if isinstance(continuity_metadata, dict):
                final_route_metadata["continuity"] = copy.deepcopy(
                    continuity_metadata
                )
            if isinstance(reconciliation_metadata, dict):
                final_route_metadata["reconciliation"] = copy.deepcopy(
                    reconciliation_metadata
                )
            if isinstance(prepared_envelope, dict) and isinstance(
                prepared_envelope.get("responseMetadata"), dict
            ):
                final_route_metadata["memoryEnvelope"] = copy.deepcopy(
                    prepared_envelope["responseMetadata"]
                )
            final_model_metadata = copy.deepcopy(dict(model_metadata or {}))
            if isinstance(prepared_envelope, dict):
                envelope_hash = str(
                    prepared_envelope.get("memoryEnvelopeSha256") or ""
                ).strip()
                context_manifest_id = str(
                    prepared_envelope.get("contextManifestId") or ""
                ).strip()
                prepared_manifest = prepared_envelope.get("manifest")
                if (
                    len(envelope_hash) != 64
                    or not is_memory_id(context_manifest_id, "context_manifest")
                    or not isinstance(prepared_manifest, dict)
                    or prepared_manifest.get("memoryEnvelopeSha256")
                    != envelope_hash
                    or prepared_manifest.get("turnId") != turn.turn_id
                ):
                    raise TurnLifecycleError(
                        "invalid_memory_envelope",
                        "prepared memory envelope metadata is invalid",
                        status_code=500,
                    )
                finalized_manifest = finalize_context_manifest(
                    prepared_manifest,
                    barrier,
                )
                manifest = self.repository.update_context_manifest(
                    principal,
                    context_manifest_id,
                    manifest=finalized_manifest,
                    expected_memory_envelope_sha256=envelope_hash,
                )
            else:
                envelope_hash = canonical_sha256({
                    "phase": "p1.3-compatibility",
                    "requestSha256": turn.request_sha256,
                    "sourceRevisionVector": trusted_context.revision_vector,
                })
                manifest = self.repository.create_context_manifest(
                    principal,
                    turn.conversation_id,
                    turn.agent_session_id,
                    turn.turn_id,
                    schema_version=1,
                    scope_fingerprint=trusted_context.scope_fingerprint,
                    revision_vector_sha256=revision_vector_sha256(
                        barrier["resultingRevisionVector"]
                    ),
                    memory_envelope_sha256=envelope_hash,
                    manifest={
                        "schemaVersion": "sage-memory-lifecycle-manifest-1.0",
                        "requestSha256": turn.request_sha256,
                        "classification": classification,
                        "revisionBarrier": barrier,
                        "routeMetadata": final_route_metadata,
                        "modelMetadata": final_model_metadata,
                    },
                )
            committed = self.repository.commit_turn(
                principal,
                turn.turn_id,
                assistant_result=result,
                tool_receipts=receipts,
                resulting_revision_vector=barrier["resultingRevisionVector"],
                revision_barrier=barrier,
                memory_envelope_sha256=envelope_hash,
                context_manifest_id=manifest.context_manifest_id,
                route_metadata=final_route_metadata,
                model_metadata=final_model_metadata,
            )
            self._refresh_conversation_retention(
                principal, committed.conversation_id
            )
            future.set_result(committed)
            return self._committed_result(principal, committed, replayed=False)
        except asyncio.CancelledError:
            terminal = self.repository.cancel_turn(principal, turn.turn_id)
            if not future.done():
                future.set_result(terminal)
            raise
        except TurnLifecycleError as exc:
            terminal = self.repository.fail_turn(
                principal,
                turn.turn_id,
                error_code=exc.code,
                revision_barrier=exc.details,
            )
            if not future.done():
                future.set_result(terminal)
            raise
        except Exception as exc:
            terminal = self.repository.fail_turn(
                principal,
                turn.turn_id,
                error_code=_stable_execution_error_code(exc),
            )
            if not future.done():
                future.set_result(terminal)
            raise
        finally:
            with self._inflight_lock:
                self._inflight.pop(turn.turn_id, None)

    def _persist_session_state(
        self,
        principal: MemoryPrincipal,
        agent_session_id: str,
        result: Mapping[str, Any],
        current_context: TrustedTurnContext,
    ) -> None:
        session = self.repository.get_agent_session(principal, agent_session_id)
        returned_state = result.get("workflow_state")
        if isinstance(returned_state, dict):
            workflow_state: Optional[Mapping[str, Any]] = returned_state
        elif session.scope_fingerprint == current_context.scope_fingerprint:
            workflow_state = session.workflow_state
        else:
            workflow_state = None
        if (
            workflow_state == session.workflow_state
            and session.scope_fingerprint == current_context.scope_fingerprint
            and session.revision_vector == current_context.revision_vector
        ):
            return
        self.repository.update_agent_session_state(
            principal,
            agent_session_id,
            workflow_state=workflow_state,
            scope_fingerprint=current_context.scope_fingerprint,
            revision_vector=current_context.revision_vector,
            expected_workflow_state_revision=session.workflow_state_revision,
            expires_at=(
                datetime.now(timezone.utc)
                + timedelta(seconds=self.workflow_ttl_seconds)
            ),
        )

    def _refresh_conversation_retention(
        self,
        principal: MemoryPrincipal,
        conversation_id: str,
    ) -> None:
        if self.conversation_retention_seconds is None:
            return
        self.repository.set_conversation_retention(
            principal,
            conversation_id,
            retention_until=(
                datetime.now(timezone.utc)
                + timedelta(seconds=self.conversation_retention_seconds)
            ),
        )

    async def _join_or_recover_pending(
        self,
        principal: MemoryPrincipal,
        turn: TurnRecord,
    ) -> TurnExecutionResult:
        with self._inflight_lock:
            future = self._inflight.get(turn.turn_id)
        if future is not None:
            terminal = await asyncio.wrap_future(future)
            if terminal.status == "committed":
                return self._committed_result(principal, terminal, replayed=True)
            raise TurnLifecycleError(
                terminal.error_code or "turn_not_committed",
                f"in-flight turn ended as {terminal.status}",
                details={"turnId": terminal.turn_id, "status": terminal.status},
            )

        age_seconds = _turn_age_seconds(turn)
        if age_seconds >= self.stale_pending_seconds:
            terminal = self.repository.fail_turn(
                principal,
                turn.turn_id,
                error_code="stale_pending_recovered",
            )
            raise TurnLifecycleError(
                "stale_pending_recovered",
                "an interrupted pending turn was recovered without replaying effects",
                details={"turnId": terminal.turn_id, "ageSeconds": age_seconds},
            )
        raise TurnLifecycleError(
            "turn_in_progress",
            "the matching turn is already in progress",
            status_code=409,
            details={"turnId": turn.turn_id},
        )

    def _committed_result(
        self,
        principal: MemoryPrincipal,
        turn: TurnRecord,
        *,
        replayed: bool,
    ) -> TurnExecutionResult:
        if turn.status != "committed" or turn.assistant_result is None:
            raise TurnLifecycleError(
                "turn_not_committed",
                "turn has no canonical assistant result",
            )
        session = self.repository.get_agent_session(principal, turn.agent_session_id)
        result = copy.deepcopy(turn.assistant_result)
        result["memory"] = _memory_response(self.mode, turn, session, replayed=replayed)
        return TurnExecutionResult(result=result, turn=turn, replayed=replayed)


def _validate_client_scope(
    client_scope: Mapping[str, Any],
    trusted_scope: Mapping[str, Any],
) -> None:
    client_kind = str(client_scope.get("kind") or "")
    trusted_kind = str(trusted_scope.get("kind") or "")
    client_ids = dict(client_scope.get("ids") or {})
    trusted_ids = dict(trusted_scope.get("ids") or {})
    client_revisions = dict(client_scope.get("expectedRevisionVector") or {})
    trusted_revisions = dict(trusted_scope.get("expectedRevisionVector") or {})
    if client_kind != trusted_kind or client_ids != trusted_ids:
        raise TurnLifecycleError(
            "asset_scope_mismatch",
            "request asset scope does not match current trusted context",
            status_code=409,
            details={"trustedAssetScope": copy.deepcopy(dict(trusted_scope))},
        )
    mismatches = {
        key: {"expected": value, "current": trusted_revisions.get(key)}
        for key, value in client_revisions.items()
        if trusted_revisions.get(key) != value
    }
    if mismatches:
        raise TurnLifecycleError(
            "source_revision_conflict",
            "request revisions do not match current trusted context",
            status_code=409,
            details={"revisionMismatches": mismatches},
        )


def _result_receipts(result: Mapping[str, Any]) -> list[Dict[str, Any]]:
    raw = result.get("tool_receipts")
    if not isinstance(raw, list):
        raw = result.get("receipts")
    if not isinstance(raw, list):
        workflow_state = result.get("workflow_state")
        if isinstance(workflow_state, dict):
            raw = workflow_state.get("execution_receipts")
    if not isinstance(raw, list):
        return []
    return [copy.deepcopy(item) for item in raw if isinstance(item, dict)]


def _result_cas_outcome(
    result: Mapping[str, Any], receipts: Sequence[Mapping[str, Any]]
) -> str:
    explicit = str(result.get("cas_outcome") or result.get("casOutcome") or "").strip()
    if explicit:
        return explicit
    if receipts:
        last = receipts[-1]
        receipt_value = str(last.get("casOutcome") or last.get("cas_outcome") or "").strip()
        if receipt_value:
            return receipt_value
        if isinstance(last.get("resultingRevisionVector"), dict):
            return "applied"
    return "not_applicable"


def _result_route_metadata(
    result: Mapping[str, Any], supplied: Optional[Mapping[str, Any]]
) -> Dict[str, Any]:
    metadata = copy.deepcopy(dict(supplied or {}))
    for source_key, target_key in (
        ("tool_source", "toolSource"),
        ("tool_call_count", "toolCallCount"),
        ("workflow_state_event", "workflowStateEvent"),
    ):
        value = result.get(source_key)
        if value is not None:
            metadata[target_key] = copy.deepcopy(value)
    return metadata


def _memory_response(
    mode: str,
    turn: TurnRecord,
    session: AgentSessionRecord,
    *,
    replayed: bool,
) -> Dict[str, Any]:
    continuity = turn.route_metadata.get("continuity")
    if not isinstance(continuity, dict):
        continuity = {}
    envelope = turn.route_metadata.get("memoryEnvelope")
    if not isinstance(envelope, dict):
        envelope = {}
    reconciliation = turn.route_metadata.get("reconciliation")
    if not isinstance(reconciliation, dict):
        reconciliation = {}
    return {
        "mode": mode,
        "conversationId": turn.conversation_id,
        "agentSessionId": turn.agent_session_id,
        "turnId": turn.turn_id,
        "turnSequence": turn.sequence,
        "workflowStateRevision": session.workflow_state_revision,
        "summaryRevision": session.summary_revision,
        "scopeEvent": _scope_event(turn.revision_barrier),
        "contextManifestId": turn.context_manifest_id,
        "memoryEnvelopeSha256": turn.memory_envelope_sha256,
        "memoryEnvelopeSchemaVersion": envelope.get("schemaVersion"),
        "contextProviderCount": int(envelope.get("providerCount", 0) or 0),
        "memoryEstimatedTokens": int(
            envelope.get("estimatedTokens", 0) or 0
        ),
        "legacyEstimatedTokens": int(
            envelope.get("legacyEstimatedTokens", 0) or 0
        ),
        "appliedToPrompt": bool(envelope.get("appliedToPrompt", False)),
        "contextOmissions": list(envelope.get("omissions") or []),
        "reconciliation": copy.deepcopy(reconciliation),
        "reconciliationOutcome": reconciliation.get(
            "outcome", "same_scope_same_revisions"
        ),
        "continuityMode": continuity.get("status", "healthy"),
        "continuityStaleness": continuity.get("staleness", "fresh"),
        "unsummarizedTurnCount": int(
            continuity.get("unsummarizedTurnCount", 0) or 0
        ),
        "replayed": bool(replayed),
        "warnings": list(continuity.get("warnings") or []),
    }


def _scope_event(barrier: Mapping[str, Any]) -> str:
    if barrier.get("revisionAdvancedDuringTurn"):
        return "same_scope_revision_advanced"
    return "same_scope_same_revisions"


def _turn_age_seconds(turn: TurnRecord) -> float:
    created = datetime.fromisoformat(turn.created_at_utc.replace("Z", "+00:00"))
    return max(0.0, (datetime.now(timezone.utc) - created).total_seconds())


def _stable_execution_error_code(exc: Exception) -> str:
    status = int(getattr(exc, "status_code", 0) or 0)
    if status == 409:
        return "execution_conflict"
    if status == 422:
        return "execution_invalid"
    if status == 429:
        return "provider_rate_limited"
    if status == 504:
        return "provider_timeout"
    return "execution_failed"


__all__ = [
    "TURN_CLASSIFICATIONS",
    "TrustedTurnContext",
    "TurnExecutionResult",
    "TurnLifecycleError",
    "TurnLifecycleService",
    "active_memory_turn",
    "build_request_identity_v1",
    "classify_turn",
    "evaluate_revision_barrier",
    "image_sha256_values",
]
