"""One bounded AppServer/MCP invocation for an already admitted gateway.

Callers own admission, replay begin/finish, progress, and result/error policy.
There is no provider fallback or additional reasoning loop here.
"""
from __future__ import annotations

import asyncio
import os

from .app_server import AppServer
from .mcp_bridge import serve_gateway
from .policy import PilotError, PilotSettings, child_environment, live_allowed, runtime_config


async def prepare_credentials(settings: PilotSettings) -> tuple[str, object | None]:
    """Check live approval before reading either supported inference credential."""
    if not live_allowed():
        raise PilotError("codex_paid_testing_disabled", "Codex live inference is disabled pending approval.")
    subscription = None
    if settings.auth_mode == "chatgpt_plan":
        from .chatgpt_accounts import subscription_credential
        subscription = await asyncio.to_thread(subscription_credential, settings.model)
    key = "" if subscription else os.environ.get("INSPECTORPRO_CODEX_API_KEY", "").strip()
    if not key and not subscription:
        raise PilotError("codex_api_key_required", "Configure a dedicated API credential outside the renderer.")
    return key, subscription


async def run_gateway_turn(*, settings, gateway, journal, binding, message, instructions, effort,
                           api_key="", subscription=None, text_sink=None, status_sink=None,
                           transport_factory=AppServer, on_phase=None):
    """Return (answer, runtime), closing the transport and gateway on every exit.

    ``on_phase(phase, runtime)`` is a synchronous diagnostic callback. Runtime is
    None until construction, then the actual transport, including during startup
    failures. Exceptions also carry ``gateway_phase`` and ``gateway_runtime``;
    their type and cancellation semantics are preserved. No journal turn status
    is written here. The caller must prepare credentials and admit the gateway.
    """
    return await _run_gateway_turn(
        settings=settings, gateway=gateway, journal=journal, binding=binding,
        message=message, instructions=instructions, effort=effort, api_key=api_key,
        subscription=subscription, text_sink=text_sink, status_sink=status_sink,
        transport_factory=transport_factory, on_phase=on_phase,
        bridge_factory=serve_gateway)


async def _run_gateway_turn(*, settings, gateway, journal, binding, message, instructions, effort,
                            api_key="", subscription=None, text_sink=None, status_sink=None,
                            transport_factory=AppServer, on_phase=None, bridge_factory,
                            finish_answer=None):
    """Shared core; private hooks retain documentation's existing lifecycle/tests.

    Documentation finalizes streamed progress before its final context check,
    within the same timeout and while its gateway and transport are still open.
    """
    runtime = None
    phase = "connecting"

    def mark(value):
        nonlocal phase
        phase = value
        if on_phase:
            on_phase(phase, runtime)

    try:
        async with asyncio.timeout(settings.timeout_seconds):
            mark("mcp_listener_start")
            async with bridge_factory(gateway) as (url, token):
                mark("child_environment")
                child_root = settings.root / "sessions" / binding
                env = child_environment(child_root, token, api_key=api_key or None,
                                        access_token=subscription.access_token if subscription else None)
                config = runtime_config(url, settings.model, auth_mode=settings.auth_mode)
                config["mcp_servers"]["inspectorpro"]["enabled_tools"] = [spec["name"] for spec in gateway.specs]
                runtime = transport_factory(settings.binary, child_root, env, config)
                mark("runtime_startup")
                async with runtime:
                    try:
                        mark("inspection")
                        answer = await runtime.inspect(
                            message=message, thread_id=journal.thread(binding), instructions=instructions,
                            on_thread=lambda value: journal.bind_thread(binding, value),
                            text_sink=text_sink, status_sink=status_sink, check=gateway.check, effort=effort)
                        if finish_answer:
                            answer = await finish_answer(answer)
                        gateway.check()
                    finally:
                        # MCP remains reachable while the child runtime drains.
                        gateway.closed = True
        return answer, runtime
    except BaseException as exc:
        exc.gateway_phase = phase
        exc.gateway_runtime = runtime
        raise
    finally:
        gateway.closed = True
