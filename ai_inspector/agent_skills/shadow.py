"""Shadow-only semantic route model call with exact-match caching."""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Callable, Mapping, Sequence

from ai_inspector.telemetry import (
    classify_exception_status,
    record_anthropic_call,
    record_openai_call,
    record_workflow_stage,
    time_block,
)

from .routing import (
    CandidateCatalog,
    ExactRouteCache,
    SKILL_ROUTE_SYSTEM,
    build_route_user_text,
    extract_json_object,
    route_cache_key,
    validate_route_response,
)


logger = logging.getLogger("inspectorpro.skill-shadow")
_SECRET_RE = re.compile(
    r"(?i)(?:sk-(?:ant-)?[a-z0-9_-]{8,}|"
    r"(?:authorization|api[-_ ]?key)\s*[:=]?\s*(?:bearer\s+)?[a-z0-9_-]{8,})"
)


def classify_shadow_route(
    message: str,
    *,
    catalog: CandidateCatalog,
    context_facts: Mapping[str, Any],
    recent_turns: Sequence[Mapping[str, str]],
    workflow_state: Mapping[str, Any] | None,
    cache: ExactRouteCache,
    model: str,
    provider: str = "anthropic",
    timeout_seconds: float,
    max_tokens: int,
    api_key: str | None = None,
    agent_type: str = "deviation-analyst",
    authorize: Callable[[str, Mapping[str, bool]], Mapping[str, bool]] | None = None,
    complete: Callable[[str, str], str] | None = None,
    failure: dict[str, Any] | None = None,
    runtime_mode: str = "shadow",
    telemetry_workflow: str = "skill_route_shadow",
    cache_namespace: str = "",
) -> dict[str, Any] | None:
    """Return a validated route; side effects remain independently gated.

    When ``failure`` is a dict and the result is None, it receives a
    ``reason`` key (and ``error_type`` when known) so callers such as the
    route evaluation harness can distinguish timeout, schema-invalid, and
    runtime failures without changing the soft-fail return contract.
    """
    started = time.perf_counter()
    if runtime_mode not in {"shadow", "production"}:
        raise ValueError("runtime_mode must be shadow or production")
    message = str(message or "").strip()
    if not message:
        _note_failure(failure, "empty_message")
        return None
    key = route_cache_key(
        message,
        workflow_state=workflow_state,
        recent_turns=recent_turns,
        context_fingerprint=catalog.context_fingerprint,
    )
    if cache_namespace:
        key = (key[0], key[1], cache_namespace + ":" + key[2])
    cached = cache.get(key)
    if cached is not None:
        requested = cached["requested_side_effects"]
        metadata_key = "_shadow" if runtime_mode == "shadow" else "_runtime"
        cached[metadata_key] = _route_metadata(
            cached,
            catalog,
            cache_hit=True,
            authorized=(dict(authorize(message, requested)) if authorize else _deny_all()),
            runtime_mode=runtime_mode,
        )
        _record_route_stage(cached, "cache_hit", started, agent_type, telemetry_workflow)
        return cached

    user_text = build_route_user_text(
        message,
        catalog,
        context_facts=context_facts,
        recent_turns=recent_turns,
        workflow_state=workflow_state,
    )
    try:
        if complete is not None:
            raw = complete(SKILL_ROUTE_SYSTEM, user_text)
        else:
            provider = str(provider or "anthropic").strip().lower()
            if provider not in {"anthropic", "openai"}:
                _note_failure(failure, "invalid_provider")
                return None
            key_name = (
                "OPENAI_API_KEY" if provider == "openai" else "ANTHROPIC_API_KEY"
            )
            key_value = api_key or os.getenv(key_name)
            if not key_value:
                _record_empty_stage("api_key_missing", started, agent_type, workflow=telemetry_workflow)
                _note_failure(failure, "api_key_missing")
                return None
            if provider == "openai":
                import openai

                client = openai.OpenAI(
                    api_key=key_value,
                    max_retries=0,
                    timeout=float(timeout_seconds),
                )
            else:
                import anthropic

                client = anthropic.Anthropic(
                    api_key=key_value,
                    max_retries=0,
                    timeout=float(timeout_seconds),
                )
            with time_block() as elapsed_ms:
                try:
                    if provider == "openai":
                        response = client.responses.create(
                            model=model,
                            instructions=SKILL_ROUTE_SYSTEM,
                            input=user_text,
                            max_output_tokens=int(max_tokens),
                            store=False,
                        )
                    else:
                        response = client.messages.create(
                            model=model,
                            max_tokens=int(max_tokens),
                            system=SKILL_ROUTE_SYSTEM,
                            messages=[{"role": "user", "content": user_text}],
                        )
                except Exception as exc:  # noqa: BLE001
                    status, error_type = classify_exception_status(exc)
                    error_message = _sanitize_provider_error(exc, secrets=(key_value,))
                    logger.warning(
                        "Skill route model call failed (%s): %s",
                        error_type,
                        error_message,
                    )
                    recorder = (
                        record_openai_call
                        if provider == "openai"
                        else record_anthropic_call
                    )
                    recorder(
                        model=model,
                        response=None,
                        latency_ms=elapsed_ms(),
                        status=status,
                        errorType=error_type,
                        route="/api/agent/chat",
                        workflow=telemetry_workflow,
                        agentType=agent_type,
                    )
                    _record_empty_stage(
                        "model_error", started, agent_type, error_type, workflow=telemetry_workflow
                    )
                    _note_failure(
                        failure,
                        "model_error",
                        error_type,
                        error_message=error_message,
                    )
                    return None
            recorder = (
                record_openai_call
                if provider == "openai"
                else record_anthropic_call
            )
            recorder(
                model=model,
                response=response,
                latency_ms=elapsed_ms(),
                route="/api/agent/chat",
                workflow=telemetry_workflow,
                agentType=agent_type,
            )
            raw = (
                str(getattr(response, "output_text", "") or "")
                if provider == "openai"
                else "".join(
                    block.text
                    for block in response.content
                    if hasattr(block, "text")
                )
            )

        parsed = extract_json_object(raw)
        route = validate_route_response(parsed, catalog)
        if route is None:
            _record_empty_stage("invalid_route", started, agent_type, workflow=telemetry_workflow)
            _note_failure(failure, "schema_invalid")
            if failure is not None:
                failure["route_shape"] = _safe_route_shape(parsed)
            return None
        cache.put(key, route)
        requested = route["requested_side_effects"]
        metadata_key = "_shadow" if runtime_mode == "shadow" else "_runtime"
        route[metadata_key] = _route_metadata(
            route,
            catalog,
            cache_hit=False,
            authorized=(dict(authorize(message, requested)) if authorize else _deny_all()),
            runtime_mode=runtime_mode,
        )
        _record_route_stage(route, "valid", started, agent_type, telemetry_workflow)
        return route
    except Exception as exc:  # noqa: BLE001 -- shadow routing is soft-fail by contract
        logger.warning("Skill shadow route failed: %s", exc)
        _record_empty_stage(
            "runtime_error", started, agent_type, type(exc).__name__, workflow=telemetry_workflow
        )
        _note_failure(failure, "runtime_error", type(exc).__name__)
        return None


def _note_failure(
    failure: dict[str, Any] | None,
    reason: str,
    error_type: str | None = None,
    *,
    error_message: str | None = None,
) -> None:
    if failure is None:
        return
    failure["reason"] = reason
    if error_type:
        failure["error_type"] = error_type
    if error_message:
        failure["error_message"] = error_message


def _sanitize_provider_error(
    exc: BaseException,
    *,
    secrets: Sequence[str] = (),
    max_length: int = 240,
) -> str:
    """Keep an actionable provider reason without retaining request content."""
    body = getattr(exc, "body", None)
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    text = str(message or exc or type(exc).__name__)
    for secret in secrets:
        if secret:
            text = text.replace(str(secret), "[redacted]")
    text = _SECRET_RE.sub("[redacted]", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.encode("ascii", errors="replace").decode("ascii")
    return text[:max(1, int(max_length))] or type(exc).__name__


def _safe_route_shape(value: Any) -> dict[str, Any]:
    """Summarize invalid route structure without retaining model prose."""
    if not isinstance(value, dict):
        return {"type": type(value).__name__}
    intents = value.get("intents") if isinstance(value.get("intents"), list) else []
    skills = value.get("skill_candidates") if isinstance(value.get("skill_candidates"), list) else []
    return {
        "keys": sorted(str(key) for key in value),
        "speech_act": value.get("speech_act"),
        "primary_workflow": value.get("primary_workflow"),
        "workflow_confidence": value.get("workflow_confidence"),
        "workflow_confidence_type": type(value.get("workflow_confidence")).__name__,
        "continue_existing_workflow": value.get("continue_existing_workflow"),
        "continue_existing_workflow_type": type(value.get("continue_existing_workflow")).__name__,
        "intent_kinds": [item.get("kind") for item in intents if isinstance(item, dict)],
        "requested_effects": [
            effect
            for item in intents if isinstance(item, dict)
            for effect in (item.get("requested_effects") or [])
        ],
        "target_kinds": [
            target.get("kind")
            for item in intents if isinstance(item, dict)
            for target in (item.get("targets") or []) if isinstance(target, dict)
        ],
        "target_ids": [
            str(target.get("id"))
            for item in intents if isinstance(item, dict)
            for target in (item.get("targets") or [])
            if isinstance(target, dict) and target.get("id") is not None
        ],
        "skill_ids": [item.get("id") for item in skills if isinstance(item, dict)],
        "skill_roles": [item.get("role") for item in skills if isinstance(item, dict)],
        "context_requirements": value.get("context_requirements"),
        "requested_side_effects": value.get("requested_side_effects"),
        "needs_clarification": value.get("needs_clarification"),
        "clarification_question_type": type(value.get("clarification_question")).__name__,
        "clarification_question_length": len(value.get("clarification_question") or ""),
    }


def _deny_all() -> dict[str, bool]:
    return {"viewport_write": False, "asset_write": False, "system_write": False}


def classify_production_route(*args, **kwargs) -> dict[str, Any] | None:
    """Classify one production turn while preserving deterministic authorization."""
    kwargs["runtime_mode"] = "production"
    kwargs["telemetry_workflow"] = "skill_route_production"
    return classify_shadow_route(*args, **kwargs)


def _route_metadata(
    route: Mapping[str, Any],
    catalog: CandidateCatalog,
    *,
    cache_hit: bool,
    authorized: Mapping[str, bool],
    runtime_mode: str,
) -> dict[str, Any]:
    return {
        "mode": runtime_mode,
        "used_for_prompt": runtime_mode == "production",
        "used_for_execution": False,
        "cache_hit": bool(cache_hit),
        "context_fingerprint": catalog.context_fingerprint,
        "authorized_side_effects": {
            "viewport_write": bool(authorized.get("viewport_write")),
            "asset_write": bool(authorized.get("asset_write")),
            "system_write": bool(authorized.get("system_write")),
        },
        "candidate_counts": {
            "workflows": len(catalog.workflows),
            "skills": len(catalog.skills),
            "eligible_skills": len(catalog.eligible_skill_ids),
        },
    }


def _route_label(route: Mapping[str, Any]) -> str:
    workflow = route.get("primary_workflow") or "none"
    speech = route.get("speech_act") or "unknown"
    skills = "+".join(item.get("id", "") for item in route.get("skill_candidates") or []) or "none"
    requested = route.get("requested_side_effects") or {}
    effect = "v" if requested.get("viewport_write") else "a" if requested.get("asset_write") else "r"
    return f"{workflow}|{speech}|{skills}|{effect}"[:240]


def _record_route_stage(
    route: Mapping[str, Any],
    stage: str,
    started: float,
    agent_type: str,
    workflow: str,
) -> None:
    record_workflow_stage(
        workflow=workflow,
        stage=stage,
        latency_ms=(time.perf_counter() - started) * 1000.0,
        route=_route_label(route),
        agentType=agent_type,
    )


def _record_empty_stage(
    stage: str,
    started: float,
    agent_type: str,
    error_type: str | None = None,
    *,
    workflow: str = "skill_route_shadow",
) -> None:
    record_workflow_stage(
        workflow=workflow,
        stage=stage,
        latency_ms=(time.perf_counter() - started) * 1000.0,
        status="error" if error_type else "success",
        errorType=error_type,
        route="none",
        agentType=agent_type,
    )
