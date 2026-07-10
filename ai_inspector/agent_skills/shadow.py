"""Shadow-only semantic route model call with exact-match caching."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, Mapping, Sequence

from ai_inspector.telemetry import (
    classify_exception_status,
    record_anthropic_call,
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


def classify_shadow_route(
    message: str,
    *,
    catalog: CandidateCatalog,
    context_facts: Mapping[str, Any],
    recent_turns: Sequence[Mapping[str, str]],
    workflow_state: Mapping[str, Any] | None,
    cache: ExactRouteCache,
    model: str,
    timeout_seconds: float,
    max_tokens: int,
    api_key: str | None = None,
    agent_type: str = "deviation-analyst",
    authorize: Callable[[str, Mapping[str, bool]], Mapping[str, bool]] | None = None,
    complete: Callable[[str, str], str] | None = None,
    failure: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return a validated route for telemetry only; never execute it.

    When ``failure`` is a dict and the result is None, it receives a
    ``reason`` key (and ``error_type`` when known) so callers such as the
    route evaluation harness can distinguish timeout, schema-invalid, and
    runtime failures without changing the soft-fail return contract.
    """
    started = time.perf_counter()
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
    cached = cache.get(key)
    if cached is not None:
        requested = cached["requested_side_effects"]
        cached["_shadow"] = _shadow_metadata(
            cached,
            catalog,
            cache_hit=True,
            authorized=(dict(authorize(message, requested)) if authorize else _deny_all()),
        )
        _record_route_stage(cached, "cache_hit", started, agent_type)
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
            import anthropic

            key_value = api_key or os.getenv("ANTHROPIC_API_KEY")
            if not key_value:
                _record_empty_stage("api_key_missing", started, agent_type)
                _note_failure(failure, "api_key_missing")
                return None
            client = anthropic.Anthropic(
                api_key=key_value,
                max_retries=0,
                timeout=float(timeout_seconds),
            )
            with time_block() as elapsed_ms:
                try:
                    response = client.messages.create(
                        model=model,
                        max_tokens=int(max_tokens),
                        system=SKILL_ROUTE_SYSTEM,
                        messages=[{"role": "user", "content": user_text}],
                    )
                except Exception as exc:  # noqa: BLE001
                    status, error_type = classify_exception_status(exc)
                    record_anthropic_call(
                        model=model,
                        response=None,
                        latency_ms=elapsed_ms(),
                        status=status,
                        errorType=error_type,
                        route="/api/agent/chat",
                        workflow="skill_route_shadow",
                        agentType=agent_type,
                    )
                    _record_empty_stage("model_error", started, agent_type, error_type)
                    _note_failure(failure, "model_error", error_type)
                    return None
            record_anthropic_call(
                model=model,
                response=response,
                latency_ms=elapsed_ms(),
                route="/api/agent/chat",
                workflow="skill_route_shadow",
                agentType=agent_type,
            )
            raw = "".join(block.text for block in response.content if hasattr(block, "text"))

        parsed = extract_json_object(raw)
        route = validate_route_response(parsed, catalog)
        if route is None:
            _record_empty_stage("invalid_route", started, agent_type)
            _note_failure(failure, "schema_invalid")
            return None
        cache.put(key, route)
        requested = route["requested_side_effects"]
        route["_shadow"] = _shadow_metadata(
            route,
            catalog,
            cache_hit=False,
            authorized=(dict(authorize(message, requested)) if authorize else _deny_all()),
        )
        _record_route_stage(route, "valid", started, agent_type)
        return route
    except Exception as exc:  # noqa: BLE001 -- shadow routing is soft-fail by contract
        logger.warning("Skill shadow route failed: %s", exc)
        _record_empty_stage("runtime_error", started, agent_type, type(exc).__name__)
        _note_failure(failure, "runtime_error", type(exc).__name__)
        return None


def _note_failure(failure: dict[str, Any] | None, reason: str, error_type: str | None = None) -> None:
    if failure is None:
        return
    failure["reason"] = reason
    if error_type:
        failure["error_type"] = error_type


def _deny_all() -> dict[str, bool]:
    return {"viewport_write": False, "asset_write": False, "system_write": False}


def _shadow_metadata(
    route: Mapping[str, Any],
    catalog: CandidateCatalog,
    *,
    cache_hit: bool,
    authorized: Mapping[str, bool],
) -> dict[str, Any]:
    return {
        "mode": "shadow",
        "used_for_prompt": False,
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


def _record_route_stage(route: Mapping[str, Any], stage: str, started: float, agent_type: str) -> None:
    record_workflow_stage(
        workflow="skill_route_shadow",
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
) -> None:
    record_workflow_stage(
        workflow="skill_route_shadow",
        stage=stage,
        latency_ms=(time.perf_counter() - started) * 1000.0,
        status="error" if error_type else "success",
        errorType=error_type,
        route="none",
        agentType=agent_type,
    )
