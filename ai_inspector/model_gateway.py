"""Backend-owned, configuration-only model routing for the Facility workflow.

The gateway transports model requests. It never executes application tools or
receives browser cookies, and never retries with a different deployment.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import inspect
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import time
from types import SimpleNamespace
from typing import Mapping

CONFIG_ENV = "INSPECTORPRO_LLM_GATEWAY_CONFIG"
TRANSPORT_VERSION = "1.103.1"
ROLES = {
    "facility-planner": {"text", "tools", "vision"},
    "facility-router": {"text"},
    "research-reader": {"text", "web_search", "web_fetch"},
}
_UNSET = object()
_ACTIVE = ContextVar("inspectorpro_model_gateway", default=_UNSET)


class GatewayError(RuntimeError):
    def __init__(self, code, message, *, details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _fail(message):
    raise GatewayError("model_gateway_config_invalid", message)


def _closed(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        _fail(f"{label} has missing or unsupported fields.")


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class GatewayRoute:
    role: str
    deployment: str
    provider: str
    model: str
    endpoint: str
    api_key_env: str
    reasoning_effort: str | None
    capabilities: tuple[str, ...]
    timeout_seconds: int
    max_output_tokens: int
    config_revision: str

    def metadata(self):
        return {"role": self.role, "deployment": self.deployment, "provider": self.provider,
                "model": self.model, "endpoint": self.endpoint,
                "reasoningEffort": self.reasoning_effort, "configRevision": self.config_revision,
                "transport": "litellm", "transportVersion": TRANSPORT_VERSION, "automaticFallback": False}

    def require(self, *capabilities):
        if not set(capabilities).issubset(self.capabilities):
            raise GatewayError("model_gateway_capability_missing", "Configured model lacks a required capability.",
                               details={"role": self.role, "required": list(capabilities)})

    def key(self):
        value = str(os.environ.get(self.api_key_env) or "").strip()
        if not value:
            raise GatewayError("model_gateway_key_missing", f"Configure {self.api_key_env} outside the renderer.")
        return value


@dataclass(frozen=True)
class GatewayConfig:
    revision: str
    routes: tuple[GatewayRoute, ...]

    def route(self, role):
        return next(route for route in self.routes if route.role == role)

    def metadata(self):
        return {"configRevision": self.revision, "routes": [route.metadata() for route in self.routes]}


def parse_config(value):
    _closed(value, {"schemaVersion", "roles", "deployments"}, "Gateway configuration")
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
        _fail("Unsupported gateway configuration version.")
    _closed(value["roles"], ROLES, "Gateway roles")
    profiles = value["deployments"]
    if not isinstance(profiles, dict) or not 1 <= len(profiles) <= 32:
        _fail("Use 1-32 deployments.")
    fields = {"provider", "model", "endpoint", "apiKeyEnv", "reasoningEffort", "capabilities",
              "timeoutSeconds", "maxOutputTokens"}
    for name, item in profiles.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name):
            _fail("Invalid deployment identifier.")
        _closed(item, fields, "Deployment")
        if not isinstance(item["provider"], str) or item["provider"] not in {"openai", "anthropic"}:
            _fail("This gateway slice supports OpenAI and Anthropic deployments.")
        if not isinstance(item["model"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", item["model"]):
            _fail("Invalid model identifier.")
        if item["apiKeyEnv"] != {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}[item["provider"]]:
            _fail("Use the provider's API-key environment variable, not an inline credential.")
        if not isinstance(item["endpoint"], str) or item["endpoint"] not in {"responses", "anthropic_messages"}:
            _fail("Unsupported gateway endpoint.")
        if item["endpoint"] == "anthropic_messages" and item["provider"] != "anthropic":
            _fail("Native research currently requires an Anthropic Messages deployment.")
        if item["provider"] == "anthropic" and item["reasoningEffort"] is not None:
            _fail("Anthropic reasoning settings are not qualified in this gateway slice.")
        if item["provider"] == "openai" and (not isinstance(item["reasoningEffort"], str) or item["reasoningEffort"] not in {"low", "medium", "high", "xhigh", "max"}):
            _fail("Specify a supported OpenAI reasoning effort.")
        caps = item["capabilities"]
        if not isinstance(caps, list) or not caps or any(not isinstance(cap, str) or cap not in {"text", "tools", "vision", "web_search", "web_fetch"} for cap in caps) or len(set(caps)) != len(caps):
            _fail("Invalid or repeated deployment capabilities.")
        if type(item["timeoutSeconds"]) is not int or not 5 <= item["timeoutSeconds"] <= 180:
            _fail("Timeout must be 5-180 seconds.")
        if type(item["maxOutputTokens"]) is not int or not 256 <= item["maxOutputTokens"] <= 32768:
            _fail("Output limit must be 256-32768 tokens.")
    routes = []
    revision = _digest(value)
    for role, required in ROLES.items():
        name = value["roles"][role]
        if not isinstance(name, str) or name not in profiles:
            _fail("Every gateway role must resolve to a deployment.")
        item = profiles[name]
        if not required.issubset(item["capabilities"]):
            _fail(f"Deployment for {role} lacks required capabilities.")
        if (role == "research-reader") != (item["endpoint"] == "anthropic_messages"):
            _fail("Use Responses for planning/routing and native Messages for provenance-preserving research.")
        routes.append(GatewayRoute(role, name, item["provider"], item["model"], item["endpoint"],
            item["apiKeyEnv"], item["reasoningEffort"], tuple(item["capabilities"]), item["timeoutSeconds"],
            item["maxOutputTokens"], revision))
    return GatewayConfig(revision, tuple(routes))


def load_config(environ=None):
    source = os.environ if environ is None else environ
    filename = str(source.get(CONFIG_ENV) or "").strip()
    if not filename:
        return None
    path = Path(filename)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    try:
        if path.stat().st_size > 65536:
            _fail("Gateway configuration exceeds 64 KiB.")
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    _fail("Duplicate gateway configuration key.")
                result[key] = value
            return result
        return parse_config(json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=pairs))
    except GatewayError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise GatewayError("model_gateway_config_unavailable", "Gateway configuration could not be read or validated.") from exc


def current_config(environ=None):
    active = _ACTIVE.get()
    return load_config(environ) if active is _UNSET else active


@contextmanager
def request_scope(config):
    token = _ACTIVE.set(config)
    try:
        yield config
    finally:
        _ACTIVE.reset(token)


def _sdk():
    # Avoid the optional remote cost-map fetch and telemetry during lazy import.
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    try:
        import litellm
    except ImportError as exc:
        raise GatewayError("model_gateway_dependency_missing", "Install requirements-gateway.txt in the backend environment.") from exc
    litellm.telemetry = False
    litellm.suppress_debug_info = True
    if version("litellm") != TRANSPORT_VERSION:
        raise GatewayError("model_gateway_dependency_mismatch", "Install the tested transport version from requirements-gateway.txt.")
    return litellm


def responses_input(messages):
    """Keep roles, images, and native call/result identity rather than flattening history."""
    result = []
    for message in messages:
        role = message.get("role")
        if role not in {"user", "assistant"}:
            raise GatewayError("model_gateway_input_invalid", "Unsupported conversation role.")
        content = message.get("content", "")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content
        if not isinstance(blocks, list):
            raise GatewayError("model_gateway_input_invalid", "Invalid conversation content.")
        parts = []
        def flush():
            if parts:
                result.append({"role": role, "content": list(parts)})
                parts.clear()
        for block in blocks:
            kind = block.get("type")
            if kind == "text":
                parts.append({"type": "output_text" if role == "assistant" else "input_text", "text": str(block.get("text") or "")})
            elif kind == "image" and role == "user":
                source = block.get("source") or {}
                if source.get("type") != "base64" or source.get("media_type") not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
                    raise GatewayError("model_gateway_input_invalid", "Only explicit inline image inputs are supported.")
                parts.append({"type": "input_image", "image_url": f"data:{source['media_type']};base64,{source['data']}"})
            elif kind == "tool_use" and role == "assistant":
                flush()
                result.append({"type": "function_call", "call_id": block["id"], "name": block["name"],
                               "arguments": json.dumps(block["input"], separators=(",", ":"))})
            elif kind == "tool_result" and role == "user":
                flush()
                output = block.get("content", "")
                if block.get("is_error"):
                    output = {"is_error": True, "content": output}
                result.append({"type": "function_call_output", "call_id": block["tool_use_id"],
                               "output": output if isinstance(output, str) else json.dumps(output)})
            else:
                raise GatewayError("model_gateway_input_invalid", "Unsupported conversation block; it was not silently dropped.")
        flush()
    return result


def _raw(response):
    return response.model_dump() if hasattr(response, "model_dump") else response


def _require_reported_model(raw, route):
    reported = raw.get("model")
    if reported and str(reported).removeprefix(route.provider + "/") != route.model:
        raise GatewayError("model_gateway_model_changed", "Gateway returned a different model than the pinned deployment.")
    return reported


def explicit_named_properties(schema):
    """Lower a closed finite pattern map to explicit properties without weakening it.

    Some providers attend to named properties but overlook the shared pattern
    constraints. Only rewrite when propertyNames proves that no other key is
    legal. Reuse definitions instead of multiplying the schema by clause count.
    """
    result = deepcopy(schema)
    definitions = result.setdefault("$defs", {})
    def visit(node):
        if isinstance(node, list):
            for child in node:
                visit(child)
        elif isinstance(node, dict):
            for key, child in list(node.items()):
                if key != "$defs":
                    visit(child)
            properties, patterns = node.get("properties"), node.get("patternProperties")
            names = node.get("propertyNames", {}).get("enum")
            if (node.get("additionalProperties") is not False or not isinstance(properties, dict)
                    or not isinstance(patterns, dict) or not isinstance(names, list)
                    or set(names) != set(properties)):
                return
            refs = []
            for pattern, constraint in patterns.items():
                name = "gateway_named_map_" + str(len(definitions))
                while name in definitions:
                    name += "_"
                definitions[name] = constraint
                refs.append((re.compile(pattern), {"$ref": "#/$defs/" + name}))
            for name, constraint in list(properties.items()):
                matches = [reference for pattern, reference in refs if pattern.search(name)]
                if matches:
                    properties[name] = {"allOf": [constraint, *matches]}
            del node["patternProperties"]
    visit(result)
    if not definitions:
        result.pop("$defs")
    return result


def normalize_response(response, route):
    raw = _raw(response)
    if not isinstance(raw, dict):
        raise GatewayError("model_gateway_response_invalid", "Gateway returned no structured response.")
    reported = _require_reported_model(raw, route)
    status = raw.get("status")
    if status not in {"completed", "incomplete"}:
        raise GatewayError("model_gateway_response_incomplete", "Provider response did not reach a supported terminal state.")
    blocks, ids = [], set()
    stop = "max_tokens" if status == "incomplete" else "end_turn"
    for item in raw.get("output", []):
        if item.get("type") == "function_call":
            call_id = item.get("call_id")
            if not isinstance(call_id, str) or not call_id or call_id in ids:
                raise GatewayError("model_gateway_tool_invalid", "Missing or repeated tool-call identity.")
            ids.add(call_id)
            try:
                def pairs(items):
                    values = {}
                    for key, value in items:
                        if key in values:
                            raise ValueError("Repeated tool argument")
                        values[key] = value
                    return values
                def invalid_constant(_):
                    raise ValueError("Non-finite JSON constant")
                arguments = json.loads(item.get("arguments", ""), object_pairs_hook=pairs, parse_constant=invalid_constant)
            except (ValueError, TypeError) as exc:
                raise GatewayError("model_gateway_tool_invalid", "Provider returned invalid tool arguments.") from exc
            if not isinstance(arguments, dict) or not item.get("name"):
                raise GatewayError("model_gateway_tool_invalid", "Provider returned an invalid tool call.")
            blocks.append(SimpleNamespace(type="tool_use", id=call_id, name=item["name"], input=arguments))
        elif item.get("type") == "message":
            for part in item.get("content", []):
                if part.get("type") == "refusal":
                    stop = "refusal"
                elif part.get("type") == "output_text" and part.get("text"):
                    blocks.append(SimpleNamespace(type="text", text=part["text"]))
        elif item.get("type") != "reasoning":
            raise GatewayError("model_gateway_response_invalid", "Unexpected provider action was not accepted.")
    # An incomplete response must not execute even an apparently complete tool call.
    if stop in {"max_tokens", "refusal"}:
        blocks = [block for block in blocks if block.type == "text"]
    elif ids:
        stop = "tool_use"
    elif not blocks:
        raise GatewayError("model_gateway_response_incomplete", "Provider returned no usable text or tool call.")
    usage = raw.get("usage") or {}
    details = usage.get("input_tokens_details") or {}
    cached = int(details.get("cached_tokens") or 0)
    written = int(details.get("cache_write_tokens") or 0)
    total_input = int(usage.get("input_tokens") or 0)
    # Responses includes cached input in its total. Anthropic telemetry expects
    # uncached input plus separate read/write counts; OpenAI expects the total.
    input_tokens = max(0, total_input - cached - written) if route.provider == "anthropic" else total_input
    normalized_usage = SimpleNamespace(input_tokens=input_tokens,
        output_tokens=int(usage.get("output_tokens") or 0),
        cache_read_input_tokens=cached, cache_creation_input_tokens=written)
    return SimpleNamespace(content=blocks, usage=normalized_usage, stop_reason=stop,
        gateway_metadata={**route.metadata(), "reportedModel": reported, "responseId": raw.get("id")},
        raw_provider_response=response)


class GatewayClient:
    def __init__(self, route, *, transport=None):
        self.route = route
        self.transport = transport

    def kwargs(self, *, system, messages, tools, required_tool_name, max_tokens):
        route = self.route
        route.require("text")
        if tools:
            route.require("tools")
        inputs = responses_input(messages)
        if any(part.get("type") == "input_image" for message in inputs for part in message.get("content", [])):
            route.require("vision")
        kwargs = {"model": route.provider + "/" + route.model, "instructions": system, "input": inputs,
                  "max_output_tokens": min(max_tokens, route.max_output_tokens), "store": False,
                  "api_key": route.key(), "timeout": route.timeout_seconds, "max_retries": 0,
                  "drop_params": False}
        if route.reasoning_effort:
            kwargs["reasoning"] = {"effort": route.reasoning_effort}
        if tools:
            kwargs["tools"] = [{"type": "function", "name": spec["name"], "description": spec.get("description", ""),
                                "parameters": explicit_named_properties(spec["input_schema"]) if route.provider == "openai" else spec["input_schema"], "strict": False,
                                **({"cache_control": spec["cache_control"]} if route.provider == "anthropic" and "cache_control" in spec else {})}
                               for spec in tools]
            kwargs["parallel_tool_calls"] = False
        if required_tool_name:
            if required_tool_name not in {spec["name"] for spec in tools or []}:
                raise GatewayError("model_gateway_tool_invalid", "Required tool is not authorized for this call.")
            kwargs["tool_choice"] = {"type": "function", "name": required_tool_name}
        return kwargs

    async def invoke(self, *, system, messages, tools=None, required_tool_name=None, max_tokens=4096, stream_sink=None):
        kwargs = self.kwargs(system=system, messages=messages, tools=tools,
                             required_tool_name=required_tool_name, max_tokens=max_tokens)
        sdk = self.transport or _sdk()
        try:
            async with asyncio.timeout(self.route.timeout_seconds):
                if stream_sink is None:
                    raw = await sdk.aresponses(**kwargs)
                else:
                    stream = await sdk.aresponses(**kwargs, stream=True)
                    raw = None
                    try:
                        async for event in stream:
                            event = _raw(event)
                            if event.get("type") == "response.output_text.delta":
                                pending = stream_sink(str(event.get("delta") or ""))
                                if inspect.isawaitable(pending):
                                    await pending
                            elif event.get("type") in {"response.completed", "response.incomplete"}:
                                raw = event.get("response")
                            elif event.get("type") in {"error", "response.failed"}:
                                raise GatewayError("model_gateway_provider_failed", "Gateway stream failed; no tool result was accepted.")
                    finally:
                        if hasattr(stream, "aclose"):
                            await stream.aclose()
                    if raw is None:
                        raise GatewayError("model_gateway_response_incomplete", "Gateway stream ended before its terminal receipt.")
                return normalize_response(raw, self.route)
        except (GatewayError, asyncio.CancelledError):
            raise
        except Exception as exc:
            # No raw provider exception or request body reaches chat/log receipts.
            status = getattr(exc, "status_code", None)
            raise GatewayError("model_gateway_provider_failed", "Configured model request failed; no model fallback was attempted.",
                               details={"role": self.route.role, "status": status if isinstance(status, int) else None,
                                        "errorType": type(exc).__name__}) from None

    def research(self, **kwargs):
        """Retain native search/fetch provenance; do not flatten it to plain text."""
        self.route.require("web_search", "web_fetch")
        if self.route.endpoint != "anthropic_messages":
            raise GatewayError("model_gateway_capability_missing", "Research requires native server-tool provenance.")
        async def complete():
            sdk = self.transport or _sdk()
            # LiteLLM exposes create(), but this transport implements Messages
            # only asynchronously. The research service runs in a worker thread.
            async with asyncio.timeout(self.route.timeout_seconds):
                return await sdk.anthropic.messages.acreate(**{
                    **kwargs, "model": self.route.provider + "/" + self.route.model,
                    "api_key": self.route.key(), "max_retries": 0,
                    "timeout": self.route.timeout_seconds,
                    "max_tokens": min(kwargs["max_tokens"], self.route.max_output_tokens),
                })
        try:
            response = asyncio.run(complete())
            _require_reported_model(_raw(response), self.route)
            return response
        except GatewayError:
            raise
        except Exception as exc:
            raise GatewayError("model_gateway_provider_failed", "Configured research request failed; no fallback was attempted.",
                               details={"errorType": type(exc).__name__}) from None

    def text(self, system, text):
        started = time.monotonic()
        response = None
        try:
            kwargs = self.kwargs(system=system, messages=[{"role": "user", "content": text}],
                                 tools=None, required_tool_name=None, max_tokens=self.route.max_output_tokens)
            response = normalize_response((self.transport or _sdk()).responses(**kwargs), self.route)
        except GatewayError:
            raise
        except Exception as exc:
            raise GatewayError("model_gateway_provider_failed", "Configured routing request failed; no fallback was attempted.",
                               details={"errorType": type(exc).__name__}) from None
        finally:
            from ai_inspector.telemetry import record_anthropic_call, record_openai_call
            recorder = record_openai_call if self.route.provider == "openai" else record_anthropic_call
            recorder(model=self.route.model, response=response, latency_ms=(time.monotonic() - started) * 1000,
                     status="success" if response else "error", route="facility_gateway_router", workflow="facility_layout", agentType="sage")
        if response.stop_reason != "end_turn":
            raise GatewayError("model_gateway_response_incomplete", "Router did not return a complete text response.")
        return "".join(block.text for block in response.content if block.type == "text")


def require_generation_binding(repository, principal, binding, config):
    """Immutable first-writer binding in the existing artifact store, not a new DB."""
    from ai_inspector.facility_layout.design_repository import FacilityDesignRepositoryNotFoundError
    from ai_inspector.facility_layout.errors import FacilityConflictError
    kind, key = "generation-model-binding", binding["ledgerId"]
    expected = {"scope": {"tenantId": principal.tenant_id, "principalId": principal.principal_id,
                           **{name: binding[name] for name in ("siteId", "layoutId", "workspaceId", "baseRevision", "ledgerId")}},
                "gateway": config.metadata() if config else None}
    try:
        record = repository.get_artifact(principal.tenant_id, binding["siteId"], kind, key, key)["artifact"]
    except FacilityDesignRepositoryNotFoundError:
        if config is None:
            return
        try:
            repository.get_ledger(principal.tenant_id, binding["siteId"], key)
        except FacilityDesignRepositoryNotFoundError:
            pass
        else:
            raise FacilityConflictError("model_gateway_existing_run_unbound", "Start a new planning session before changing an existing unbound run to the gateway.")
        repository.store_artifact(tenant_id=principal.tenant_id, site_id=binding["siteId"], artifact_kind=kind,
                                  artifact_id=key, artifact_revision=key, artifact=expected)
        repository.pin_artifacts(tenant_id=principal.tenant_id, site_id=binding["siteId"], owner_kind=kind,
                                 owner_id=key, artifact_refs=[{"artifactKind": kind, "artifactId": key, "artifactRevision": key}])
        return
    if record != expected:
        raise FacilityConflictError("model_gateway_run_changed", "This planning run is pinned to a different gateway configuration. Restore it or start a new planning session.")
