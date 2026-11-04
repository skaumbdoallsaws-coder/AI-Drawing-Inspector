"""Bounded stdio transport, not an agent reasoning or tool-selection loop."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import subprocess
import time

from anyio import CancelScope

from .policy import PilotError, PilotSettings, READONLY_PROFILE, REASONING_EFFORTS, RUNTIME_VERSION, reasoning_effort

class CatalogUnavailable(PilotError):
    """The pinned catalog could not be read, or has no entry for the model that parse_catalog accepts."""

    def __init__(self, message="The pinned model catalog could not be verified."):
        super().__init__("codex_catalog_invalid", message)


# For each (binary, pinned version, model): the model's entry in the pinned runtime's bundled catalog and the reasoning
# levels it supports, as parse_catalog returns them. Read by the first turn of this process that starts that runtime
# for the model, then kept; nothing is kept from a read that failed or that parse_catalog refused.
CATALOGS = {}


def parse_catalog(raw, model):
    """MODEL's entry in RAW (the output of `codex debug models --bundled`) and the reasoning levels it supports.
    CatalogUnavailable for anything malformed: not a JSON object, "models" not a list, an entry not an object, not
    exactly one entry for MODEL, its levels not a non-empty list of levels with a string effort, or none of them one
    Sage offers (policy.REASONING_EFFORTS). Other models' entries are not checked further."""
    try:
        catalog = json.loads(raw)
    except (ValueError, RecursionError):
        raise CatalogUnavailable() from None
    models = catalog.get("models") if isinstance(catalog, dict) else None
    if not isinstance(models, list) or not all(isinstance(item, dict) for item in models):
        raise CatalogUnavailable()
    entries = [item for item in models if item.get("slug") == model]
    if len(entries) != 1:
        raise CatalogUnavailable("The selected model is missing from the pinned catalog.")
    levels = entries[0].get("supported_reasoning_levels")
    if (not isinstance(levels, list) or not levels
            or not all(isinstance(level, dict) and isinstance(level.get("effort"), str) for level in levels)):
        raise CatalogUnavailable("The pinned model catalog lists no reasoning levels for the selected model.")
    efforts = tuple(level["effort"] for level in levels)
    if not set(efforts) & set(REASONING_EFFORTS):
        raise CatalogUnavailable("The pinned model catalog lists no reasoning level Sage offers for the selected "
                                 "model.")
    return entries[0], efforts


def pinned_efforts(binary, model):
    """The reasoning levels MODEL's kept catalog entry (CATALOGS) supports; None until a turn of this process has read
    one parse_catalog accepts from BINARY."""
    kept = CATALOGS.get((str(binary), RUNTIME_VERSION, model))
    return kept[1] if kept else None


def unsupported_effort(effort, model):
    return PilotError("codex_effort_unsupported", f'The pinned model catalog has no reasoning level "{effort}" for '
                      f"{model}. Nothing was sent to Codex.", 422)


def check_effort(requested, settings=None):
    """The reasoning level a turn will run at, checked before its stream starts, so a refusal is an HTTP 422: one Sage
    offers (policy.reasoning_effort) and, once a turn of this process has read the pinned catalog, one it supports
    for the model. Until then the turn checks the catalog itself (AppServer.inspect)."""
    effort = reasoning_effort(requested)
    try:
        settings = settings or PilotSettings.from_environment()
    except PilotError:
        return effort   # the turn says what is not configured, as before
    supported = pinned_efforts(settings.binary, settings.model)
    if supported is not None and effort not in supported:
        raise unsupported_effort(effort, settings.model)
    return effort


def toml_value(value):
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k) + "=" + toml_value(v) for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ",".join(toml_value(v) for v in value) + "]"
    return json.dumps(value)


def without_nulls(value):
    if isinstance(value, dict):
        return {key: without_nulls(item) for key, item in value.items() if item is not None}
    return value


def failure_diagnostic(error, environment):
    """Keep bounded provider diagnostics backend-only, without runtime credentials."""
    message = str(error.get("message", ""))
    for name in ("INSPECTORPRO_CODEX_API_KEY", "INSPECTORPRO_CODEX_MCP_TOKEN", "INSPECTORPRO_CHATGPT_ACCESS_TOKEN"):
        if environment.get(name):
            message = message.replace(environment[name], "[REDACTED]")
    message = re.sub(r"sk-[A-Za-z0-9_-]+|(?i:Bearer)\s+[^\s\"']+", "[REDACTED]", message)
    return {"message": message[:1200]}


def turn_failure(error, environment):
    code, message = "codex_turn_incomplete", "Codex did not complete this inspection. No engineering changes were made."
    if environment.get("INSPECTORPRO_CHATGPT_ACCESS_TOKEN"):
        message = "The ChatGPT plan request could not complete. No paid API fallback was attempted."
        try:
            provider = json.loads(error.get("message", ""))
            provider_code = provider.get("error", {}).get("code")
        except (ValueError, TypeError, AttributeError):
            provider_code = None
        if provider_code in {"subscription_sharing_usage_limit_exceeded", "subscription_sharing_usage_unavailable", "rate_limit_exceeded"}:
            code = "codex_subscription_usage_limit"
            message = "ChatGPT plan usage is currently limited. Check plan usage or try again later. No paid API fallback was attempted."
        elif provider_code in {"invalid_token", "token_expired", "invalid_grant"}:
            code = "chatgpt_sign_in_required"
            message = "Reconnect your account using Sage > ChatGPT account. No paid API fallback was attempted."
    failure = PilotError(code, message)
    failure.diagnostic = failure_diagnostic(error, environment)
    return failure


class AppServer:
    def __init__(self, binary: Path, root: Path, environment: dict, config: dict):
        self.binary, self.root, self.environment, self.config = binary, root, environment, config
        self.process = None
        self.pending, self.sequence = {}, 0
        self.events = asyncio.Queue(maxsize=256)
        self.write_lock = asyncio.Lock()
        self.tasks = []
        self.started_at = time.monotonic()
        self.timeline = []
        self._closing = None
        self.efforts = ()   # the reasoning levels the pinned catalog supports for the model (read on start)

    def mark(self, phase):
        if len(self.timeline) < 64:
            self.timeline.append({"phase": phase, "elapsedMs": round((time.monotonic() - self.started_at) * 1000)})

    async def __aenter__(self):
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.mark("version_spawn")
        probe = await asyncio.create_subprocess_exec(str(self.binary), "--version", env=self.environment,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, creationflags=flags)
        try:
            self.mark("version_wait")
            output, _ = await asyncio.wait_for(probe.communicate(), 15)
        except BaseException:
            if probe.returncode is None:
                probe.kill()
            await probe.wait()
            raise
        if probe.returncode != 0 or output.decode().strip() != "codex-cli " + RUNTIME_VERSION:
            raise PilotError("codex_version_mismatch", "The pilot requires its pinned Codex runtime.")
        await self._pinned_catalog(flags)
        args = [str(self.binary)]
        for key, value in self.config.items():
            args.extend(["-c", key + "=" + toml_value(value)])
        args.extend(["app-server", "--listen", "stdio://"])
        self.mark("runtime_spawn")
        self.process = await asyncio.create_subprocess_exec(*args, cwd=str(self.root / "workspace"),
            env=self.environment, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, limit=1048576, creationflags=flags)
        self.mark("runtime_spawned")
        self.tasks = [asyncio.create_task(self._read()), asyncio.create_task(self._drain_stderr())]
        try:
            await self.request("initialize", {"clientInfo": {"name": "InspectorPro" if self.environment.get("INSPECTORPRO_CHATGPT_ACCESS_TOKEN") else "inspectorpro_sage_pilot",
                "title": "InspectorPro", "version": "0.1.0"}, "capabilities": {"experimentalApi": True}})
            await self.send({"method": "initialized"})
            effective = (await self.request("config/read", {"includeLayers": False}))["config"]
            for key in ("default_permissions", "permissions", "web_search", "model_catalog_json"):
                if without_nulls(effective.get(key)) != self.config.get(key):
                    raise PilotError("codex_policy_mismatch", "The runtime did not apply the pilot restrictions.")
            if effective.get("model_provider") != self.config["model_provider"] or any(
                    effective.get("model_providers", {}).get(name, {}).get(key) != value
                    for name, provider in self.config["model_providers"].items() for key, value in provider.items()):
                raise PilotError("codex_policy_mismatch", "The runtime did not apply the selected inference credential and endpoint.")
            if any(effective.get("features", {}).get(key) is not value for key, value in self.config["features"].items()):
                raise PilotError("codex_policy_mismatch", "The runtime did not disable the requested native tools.")
            servers = effective.get("mcp_servers", {})
            if set(servers) != set(self.config["mcp_servers"]) or any(
                servers[name].get(key) != value for name, settings in self.config["mcp_servers"].items()
                for key, value in settings.items()
            ):
                raise PilotError("codex_policy_mismatch", "The runtime did not apply the authorized MCP configuration.")
            return self
        except BaseException:
            await self.close()
            raise

    async def _pinned_catalog(self, flags):
        """The pinned catalog's entry for the model: the reasoning levels it supports (self.efforts), and for
        gpt-6.1-sol a catalog of that model alone with its tool settings off. gpt-6.1-sol needs it; for another model
        a catalog that cannot be read or used leaves Sage's own levels (policy.REASONING_EFFORTS) and the turn goes on,
        as before the levels were read."""
        restricted = self.config["model"] == "gpt-6.1-sol"
        try:
            entry, self.efforts = await self._catalog_entry(flags)
        except Exception:
            if restricted:
                raise
            self.efforts = REASONING_EFFORTS
            self.mark("catalog_unavailable")
            return
        if not restricted:
            return
        # Bundled model metadata can force tools on after feature flags are read.
        # Preserve model identity/capabilities, but let our explicit tool policy win.
        model = dict(entry, tool_mode=None, multi_agent_version=None,
                     node_repl_disabled=True, use_responses_lite=False, experimental_supported_tools=[],
                     supports_search_tool=False)
        target = self.root / "home" / "inspectorpro-models.json"
        target.write_text(json.dumps({"models": [model]}), encoding="utf-8")
        self.config["model_catalog_json"] = str(target)

    async def _catalog_entry(self, flags):
        """The model's pinned catalog entry and the levels it supports (parse_catalog): read from `codex debug models
        --bundled` by the first turn of this process that starts this binary for the model, then kept (CATALOGS).
        Nothing is kept from a read that failed or that parse_catalog refused."""
        key = (str(self.binary), RUNTIME_VERSION, self.config["model"])
        if key in CATALOGS:
            return CATALOGS[key]
        probe = await asyncio.create_subprocess_exec(str(self.binary), "debug", "models", "--bundled",
            env=self.environment, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            creationflags=flags)
        try:
            raw, _ = await asyncio.wait_for(probe.communicate(), 15)
        except BaseException:
            if probe.returncode is None:
                probe.kill()
            await probe.wait()
            raise
        if probe.returncode or len(raw) > 2000000:
            raise CatalogUnavailable()
        CATALOGS[key] = parse_catalog(raw, self.config["model"])
        return CATALOGS[key]

    async def __aexit__(self, *_args):
        await self.close()

    async def send(self, message):
        if not self.process or self.process.returncode is not None:
            raise PilotError("codex_runtime_stopped", "The Codex runtime stopped before completing the request.")
        raw = json.dumps(message, allow_nan=False).encode() + b"\n"
        if len(raw) > 1048576:
            raise PilotError("codex_request_too_large", "The runtime request exceeds the pilot limit.", 422)
        async with self.write_lock:
            self.process.stdin.write(raw)
            await self.process.stdin.drain()

    async def request(self, method, params, timeout=20):
        self.sequence += 1
        key = self.sequence
        future = asyncio.get_running_loop().create_future()
        self.pending[key] = future
        try:
            # Include backpressure on stdin in the same protocol deadline.
            async with asyncio.timeout(timeout):
                self.mark(method + ":send")
                await self.send({"id": key, "method": method, "params": params})
                self.mark(method + ":wait")
                result = await future
            self.mark(method + ":done")
            return result
        except TimeoutError:
            error = PilotError("codex_protocol_timeout", "The Codex runtime did not respond in time. No engineering changes were made.")
            error.diagnostic = {"phase": method, "timeoutSeconds": timeout}
            raise error from None
        finally:
            self.pending.pop(key, None)
            if not future.done():
                future.cancel()

    async def _read(self):
        try:
            while raw := await self.process.stdout.readline():
                message = json.loads(raw)
                if not isinstance(message, dict):
                    raise ValueError("Invalid protocol message")
                if "method" in message and "id" in message:
                    # No approval, dynamic tool, login, or permission request is authorized by this pilot.
                    await self.send({"id": message["id"], "error": {"code": -32601,
                        "message": "InspectorPro read-only pilot does not authorize this request."}})
                elif "id" in message:
                    future = self.pending.get(message["id"])
                    if future and not future.done():
                        if "error" in message:
                            future.set_exception(PilotError("codex_protocol_rejected", "Codex rejected the runtime request. No engineering changes were made."))
                        else:
                            future.set_result(message.get("result"))
                else:
                    self.events.put_nowait(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        finally:
            error = PilotError("codex_runtime_stopped", "The Codex runtime connection ended.")
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(error)
            if self.events.full():
                self.events.get_nowait()
            self.events.put_nowait({"method": "inspectorpro/runtimeStopped"})

    async def _drain_stderr(self):
        # Never relay raw runtime logs: they can contain credentials, prompts, or document data.
        while await self.process.stderr.read(8192):
            pass

    async def close(self):
        if self._closing is None:
            self._closing = asyncio.create_task(self._close_owned_resources())
        cancelled = False
        # Avoid level-cancellation spin while still joining after repeated direct Task.cancel().
        with CancelScope(shield=True):
            while not self._closing.done():
                try:
                    await asyncio.shield(self._closing)
                except asyncio.CancelledError:
                    cancelled = True
            await self._closing
        if cancelled:
            raise asyncio.CancelledError

    async def _close_owned_resources(self):
        self.mark("closing")
        try:
            if self.process and self.process.returncode is None:
                try:
                    self.process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(self.process.wait(), 3)
                except TimeoutError:
                    try:
                        self.process.kill()
                    except ProcessLookupError:
                        pass
                    await self.process.wait()
        finally:
            if self.process and getattr(self.process, "stdin", None):
                self.process.stdin.close()
            for task in self.tasks:
                task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
            self.mark("closed")

    async def inspect(self, *, message, thread_id, instructions, on_thread, text_sink, status_sink, check, effort=None):
        """One turn. EFFORT, when given, is this turn's reasoning level (TurnStartParams.effort), one the pinned
        catalog supports for the model."""
        if effort is not None and effort not in self.efforts:
            raise unsupported_effort(effort, self.config["model"])
        options = {"model": self.config["model"], "modelProvider": "inspectorpro",
            "cwd": str(self.root / "workspace"), "approvalPolicy": "never", "permissions": READONLY_PROFILE,
            "runtimeWorkspaceRoots": [str(self.root / "workspace")],
            "baseInstructions": instructions}
        if thread_id:
            started = await self.request("thread/resume", {**options, "threadId": thread_id, "excludeTurns": True})
        else:
            started = await self.request("thread/start", options)
        if started.get("activePermissionProfile", {}).get("id") != READONLY_PROFILE:
            raise PilotError("codex_policy_mismatch", "The thread did not apply the pilot permissions.")
        thread_id = started["thread"]["id"]
        inventory = await self.request("mcpServerStatus/list", {"threadId": thread_id, "serverName": "inspectorpro"}, timeout=40)
        servers = inventory.get("data", [])
        expected = set(self.config["mcp_servers"]["inspectorpro"]["enabled_tools"])
        if (len(servers) != 1 or servers[0].get("name") != "inspectorpro" or servers[0].get("toolsError")
                or {tool["name"] for tool in servers[0].get("tools", {}).values()} != expected):
            raise PilotError("codex_tools_unavailable", "The authorized engineering tools are not ready.")
        on_thread(thread_id)
        check()
        turn_id = None
        try:
            started = await self.request("turn/start", {"threadId": thread_id,
                "input": [{"type": "text", "text": message}], "approvalPolicy": "never",
                "permissions": READONLY_PROFILE, **({"effort": effort} if effort is not None else {})})
            turn_id = started["turn"]["id"]
            answer = []
            while True:
                event = await self.events.get()
                method, params = event.get("method"), event.get("params", {})
                if method == "inspectorpro/runtimeStopped":
                    raise PilotError("codex_runtime_stopped", "Codex stopped during the inspection.")
                if params.get("threadId") != thread_id:
                    continue
                if params.get("turnId", turn_id) != turn_id:
                    continue
                if method == "item/agentMessage/delta":
                    delta = params.get("delta", "")
                    if not isinstance(delta, str) or sum(map(len, answer)) + len(delta) > 50000:
                        raise PilotError("codex_response_limit", "The inspection response exceeded its limit.")
                    answer.append(delta)
                    if text_sink:
                        await text_sink(delta)
                elif method == "item/started" and params.get("item", {}).get("type") == "mcpToolCall":
                    check()
                    if status_sink:
                        await status_sink("codex_inspecting")
                elif method == "turn/completed":
                    turn = params.get("turn", {})
                    if turn.get("id") != turn_id:
                        continue
                    if turn.get("status") != "completed":
                        raise turn_failure(turn.get("error") or {}, self.environment)
                    check()
                    if not "".join(answer).strip():
                        raise PilotError("codex_empty_response", "Codex completed without an inspection response.")
                    return "".join(answer)
        except BaseException:
            if turn_id:
                try:
                    await self.request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id}, timeout=2)
                except BaseException:
                    pass
            raise
