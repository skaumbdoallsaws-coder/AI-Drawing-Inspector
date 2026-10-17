"""Gateway protocol and policy tests; no provider calls or layout writes."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_inspector.model_gateway import (
    CONFIG_ENV, GatewayClient, GatewayError, current_config, load_config,
    normalize_response, parse_config, request_scope, responses_input,
    explicit_named_properties,
)
from ai_inspector.facility_layout.provider_config import (
    FacilityProviderConfigurationError, resolve_facility_provider_config,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config_data():
    value = json.loads((ROOT / "config/sage-gateway.json").read_text())
    # Provider-specific assertions must not depend on the user's selected default.
    value["roles"]["facility-planner"] = "claude-baseline"
    return value


@pytest.fixture
def route(config_data, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    config_data["roles"]["facility-planner"] = "astra-candidate"
    return parse_config(config_data).route("facility-planner")


def receipt(route, *, status="completed", output=None):
    return {"id": "receipt-1", "model": route.model, "status": status,
            "output": output or [{"type": "message", "content": [{"type": "output_text", "text": "Ready."}]}],
            "usage": {"input_tokens": 12, "output_tokens": 4, "input_tokens_details": {"cached_tokens": 3}}}


def call(arguments='{"count":3}', call_id="call-1"):
    return {"type": "function_call", "call_id": call_id, "name": "inspect", "arguments": arguments}


def test_canonical_configuration_and_secret_free_metadata(config_data):
    a = parse_config(config_data)
    b = parse_config(dict(reversed(list(config_data.items()))))
    assert a == b
    assert a.route("facility-planner").provider == "anthropic"
    assert "apiKey" not in json.dumps(a.metadata())
    changed = deepcopy(config_data)
    changed["deployments"]["claude-baseline"]["timeoutSeconds"] += 1
    assert parse_config(changed).revision != a.revision


@pytest.mark.parametrize("field,value", [
    ("provider", "unqualified"), ("provider", []), ("apiKeyEnv", "secret-value"),
    ("endpoint", "chat"), ("endpoint", {}), ("model", "https://untrusted.test"),
    ("reasoningEffort", "none"), ("reasoningEffort", []),
    ("capabilities", ["text", {}]), ("capabilities", ["text", "text"]),
    ("timeoutSeconds", True), ("timeoutSeconds", 181), ("maxOutputTokens", 0),
])
def test_invalid_config_fails_closed(config_data, field, value):
    config_data["deployments"]["astra-candidate"][field] = value
    with pytest.raises(GatewayError):
        parse_config(config_data)


def test_roles_require_real_capabilities(config_data):
    config_data["roles"]["research-reader"] = "astra-candidate"
    with pytest.raises(GatewayError):
        parse_config(config_data)


def test_duplicate_config_keys_rejected(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text('{"roles":{},"roles":{}}')
    with pytest.raises(GatewayError):
        load_config({CONFIG_ENV: str(path)})


def test_disabled_and_enabled_request_snapshots_do_not_reload(config_data, monkeypatch):
    monkeypatch.setenv(CONFIG_ENV, "missing.json")
    with request_scope(None):
        assert current_config() is None
    config = parse_config(config_data)
    with request_scope(config):
        assert current_config() is config
    with pytest.raises(GatewayError):
        current_config()


def test_facility_opt_in_and_legacy_rollback(config_data):
    config_data["roles"]["facility-planner"] = "astra-candidate"
    with request_scope(parse_config(config_data)):
        effective = resolve_facility_provider_config({})
        assert effective.provider == "openai" and effective.model == "gpt-6-astra"
        assert effective.public_metadata()["gateway"]["automaticFallback"] is False
        with pytest.raises(FacilityProviderConfigurationError):
            resolve_facility_provider_config({}, compatible_models=("claude-sonnet",))
    with request_scope(None):
        assert resolve_facility_provider_config({}).gateway_route is None
        with pytest.raises(FacilityProviderConfigurationError):
            resolve_facility_provider_config({"INSPECTORPRO_SAGE_PROVIDER": "openai"})


def test_history_roles_tool_identity_images_and_errors_survive():
    messages = [
        {"role": "user", "content": "inspect"},
        {"role": "assistant", "content": [{"type": "text", "text": "Checking."},
            {"type": "tool_use", "id": "call-1", "name": "inspect", "input": {"a": 2}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call-1", "content": "stale", "is_error": True},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AA=="}}]},
    ]
    result = responses_input(messages)
    assert result[1]["role"] == "assistant"
    assert result[2]["call_id"] == result[3]["call_id"] == "call-1"
    assert json.loads(result[3]["output"])["is_error"] is True
    assert result[4]["content"][0]["image_url"] == "data:image/png;base64,AA=="
    with pytest.raises(GatewayError):
        responses_input([{"role": "user", "content": [{"type": "document"}]}])


def test_responses_arguments_no_sampling_or_fallback(route):
    kwargs = GatewayClient(route).kwargs(system="system", messages=[{"role": "user", "content": "hi"}],
        tools=[{"name": "inspect", "input_schema": {"type": "object"}}], required_tool_name="inspect", max_tokens=2000)
    assert kwargs["model"] == "openai/gpt-6-astra"
    assert kwargs["store"] is False and kwargs["max_retries"] == 0
    assert kwargs["parallel_tool_calls"] is False
    assert kwargs["reasoning"] == {"effort": "medium"}
    assert "temperature" not in kwargs and "fallbacks" not in kwargs
    assert kwargs["tool_choice"] == {"type": "function", "name": "inspect"}


def test_required_tool_and_key_fail_before_dispatch(route, monkeypatch):
    with pytest.raises(GatewayError):
        GatewayClient(route).kwargs(system="s", messages=[], tools=[], required_tool_name="save", max_tokens=500)
    monkeypatch.delenv("OPENAI_API_KEY")
    with pytest.raises(GatewayError) as failure:
        route.key()
    assert failure.value.code == "model_gateway_key_missing"


def test_normalized_usage_and_native_tool_ids(route):
    response = normalize_response(receipt(route, output=[call()]), route)
    assert response.stop_reason == "tool_use"
    assert response.content[0].input == {"count": 3}
    assert response.content[0].id == "call-1"
    assert response.usage.cache_read_input_tokens == 3
    assert response.gateway_metadata["configRevision"] == route.config_revision


def test_anthropic_usage_does_not_double_count_cached_input(config_data):
    route = parse_config(config_data).route("facility-planner")
    raw = receipt(route)
    raw["usage"]["input_tokens_details"]["cache_write_tokens"] = 2
    usage = normalize_response(raw, route).usage
    assert (usage.input_tokens, usage.cache_read_input_tokens, usage.cache_creation_input_tokens) == (7, 3, 2)


def test_routing_cache_is_configuration_scoped():
    import server
    from tests.test_agent_skill_routing import _facts, _route
    from ai_inspector.agent_skills.routing import ExactRouteCache, build_candidate_catalog
    from ai_inspector.agent_skills.shadow import classify_shadow_route
    workflows, skills = server._get_agent_skill_runtime()
    catalog = build_candidate_catalog(workflows, skills, agent="sage", mode="report_fai",
        available_assets={"fai_table", "drawing", "part_model", "parent_assembly", "motion_package"},
        available_context={"fai.characteristics", "drawing.dimensions", "part.feature_map"}, context_facts=_facts())
    calls, cache = [], ExactRouteCache()
    def complete(*args):
        calls.append(args)
        return json.dumps(_route())
    def route(namespace):
        return classify_shadow_route("inspect", catalog=catalog, context_facts=_facts(),
            recent_turns=[], workflow_state={}, cache=cache, model="test-model",
            timeout_seconds=5, max_tokens=700, complete=complete, cache_namespace=namespace)
    assert route("config-a")["_shadow"]["cache_hit"] is False
    assert route("config-a")["_shadow"]["cache_hit"] is True
    assert route("config-b")["_shadow"]["cache_hit"] is False
    assert len(calls) == 2


def test_generation_binding_survives_reopening_artifact_store(config_data, tmp_path):
    from ai_inspector.facility_layout.generation_requirement_repository import GenerationRequirementRepository
    from ai_inspector.facility_layout.errors import FacilityConflictError
    from ai_inspector.model_gateway import require_generation_binding
    principal = SimpleNamespace(tenant_id="t", principal_id="u")
    binding = dict(siteId="s", layoutId="l", workspaceId="w", baseRevision="0" * 64, ledgerId="1" * 64)
    config = parse_config(config_data)
    require_generation_binding(GenerationRequirementRepository(tmp_path), principal, binding, config)
    require_generation_binding(GenerationRequirementRepository(tmp_path), principal, binding, config)
    for changed in (None, replace(config, revision="2" * 64)):
        with pytest.raises(FacilityConflictError) as failure:
            require_generation_binding(GenerationRequirementRepository(tmp_path), principal, binding, changed)
        assert failure.value.code == "model_gateway_run_changed"


@pytest.mark.parametrize("output", [[call("[]")], [call("bad")], [call(), call()], [call(call_id="")],
    [call('{"count":1,"count":2}')], [call('{"count":NaN}')]])
def test_malformed_tool_calls_rejected(route, output):
    with pytest.raises(GatewayError):
        normalize_response(receipt(route, output=output), route)


def test_incomplete_or_refused_response_cannot_execute_tools(route):
    response = normalize_response(receipt(route, status="incomplete", output=[call()]), route)
    assert response.stop_reason == "max_tokens" and not response.content
    response = normalize_response(receipt(route, output=[call(), {"type": "message", "content": [{"type": "refusal"}]}]), route)
    assert response.stop_reason == "refusal" and not response.content
    with pytest.raises(GatewayError):
        normalize_response({**receipt(route), "model": "other"}, route)


def test_stream_requires_terminal_receipt_and_closes(route):
    class Stream:
        closed = False
        def __aiter__(self):
            return self.events()
        async def events(self):
            yield {"type": "response.output_text.delta", "delta": "Hello"}
        async def aclose(self):
            self.closed = True
    stream, received = Stream(), []
    async def respond(**kwargs):
        assert kwargs["stream"] is True
        return stream
    client = GatewayClient(route, transport=SimpleNamespace(aresponses=respond))
    with pytest.raises(GatewayError) as failure:
        asyncio.run(client.invoke(system="s", messages=[], stream_sink=received.append))
    assert failure.value.code == "model_gateway_response_incomplete"
    assert received == ["Hello"] and stream.closed


def test_cancellation_does_not_retry_or_finish(route):
    calls = []
    async def respond(**kwargs):
        calls.append(kwargs)
        await asyncio.sleep(60)
    async def exercise():
        task = asyncio.create_task(GatewayClient(route, transport=SimpleNamespace(aresponses=respond)).invoke(system="s", messages=[]))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(exercise())
    assert len(calls) == 1


def test_provider_error_never_leaks_request_or_key(route):
    async def fail(**kwargs):
        raise RuntimeError("not-a-real-key private request contents")
    with pytest.raises(GatewayError) as failure:
        asyncio.run(GatewayClient(route, transport=SimpleNamespace(aresponses=fail)).invoke(system="s", messages=[]))
    assert "private" not in str(failure.value) and "not-a-real-key" not in str(failure.value)
    assert failure.value.__suppress_context__


def test_native_research_does_not_flatten_provenance(config_data, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    route = parse_config(config_data).route("research-reader")
    raw = {"content": [{"type": "web_search_tool_result", "content": []}]}
    async def create(**kwargs):
        assert kwargs["model"] == "anthropic/" + route.model
        assert kwargs["max_retries"] == 0
        return raw
    sdk = SimpleNamespace(anthropic=SimpleNamespace(messages=SimpleNamespace(acreate=create)))
    assert GatewayClient(route, transport=sdk).research(max_tokens=2500, tools=[]) is raw


def test_finite_pattern_lowering_is_equivalent_and_preserves_original():
    import jsonschema
    schema = {"type": "object", "properties": {"s0": {"description": "first"}, "s1": {}},
              "propertyNames": {"enum": ["s0", "s1"]}, "required": ["s0", "s1"], "additionalProperties": False,
              "patternProperties": {"^s[0-9]+$": {"type": "array", "minItems": 1,
                  "items": {"type": "object", "properties": {"kind": {"enum": ["resource_mapping"]}},
                            "required": ["kind"], "additionalProperties": False}}}}
    original = deepcopy(schema)
    lowered = explicit_named_properties(schema)
    assert schema == original and "patternProperties" not in lowered
    assert len(lowered["$defs"]) == 1
    valid = {"s0": [{"kind": "resource_mapping"}], "s1": [{"kind": "resource_mapping"}]}
    for instance in (valid, {}, {**valid, "s2": []}, {**valid, "s0": []},
                     {**valid, "s0": [{"kind": "invented"}]}, {**valid, "s1": [{"kind": "resource_mapping", "extra": 3}]}):
        assert jsonschema.Draft202012Validator(schema).is_valid(instance) == jsonschema.Draft202012Validator(lowered).is_valid(instance)
    del schema["propertyNames"]
    assert explicit_named_properties(schema) == schema


def test_cli_changes_only_configuration_and_preserves_file_on_failed_replace(config_data, tmp_path, monkeypatch):
    from tools.sage_gateway import select_deployment
    path = tmp_path / "gateway.json"
    path.write_text(json.dumps(config_data))
    selected = select_deployment(path, "facility-planner", "astra-candidate")
    assert next(r for r in selected["routes"] if r["role"] == "facility-planner")["model"] == "gpt-6-astra"
    before = path.read_bytes()
    with pytest.raises(GatewayError):
        select_deployment(path, "research-reader", "astra-candidate")
    assert path.read_bytes() == before
    def locked(*args):
        raise PermissionError("Controlled replacement lock")
    monkeypatch.setattr("tools.sage_gateway.os.replace", locked)
    with pytest.raises(PermissionError):
        select_deployment(path, "facility-planner", "claude-baseline")
    assert path.read_bytes() == before and list(tmp_path.iterdir()) == [path]


def test_generation_run_pins_gateway_and_rejects_revision_changes(config_data, tmp_path):
    from ai_inspector.facility_layout.generation_run_repository import FacilityGenerationRunRepository
    from ai_inspector.facility_layout.generation_coordinator import FacilityGenerationCoordinator
    config_data["roles"]["facility-planner"] = "astra-candidate"
    with request_scope(parse_config(config_data)):
        config = resolve_facility_provider_config({})
    repository = FacilityGenerationRunRepository(tmp_path)
    created = repository.create_run(tenant_id="t", site_id="s", workspace_id="w", layout_id="l", user_id="u", session_id="session",
        base_layout_revision="0" * 64, effective_provider=config.provider, effective_model=config.model,
        reasoning_effort=config.reasoning_effort, gateway_route=config.gateway_route, intent_hash="1" * 64,
        dependency_fingerprint="2" * 64, prototype_mode=True, writable=False)
    run = FacilityGenerationRunRepository(tmp_path).get_run("t", "s", created["run"]["runId"])["run"]
    assert run["gatewayRevision"] == config.gateway_route.config_revision
    FacilityGenerationCoordinator._assert_provider_binding(run, config)
    changed = replace(config, gateway_route=replace(config.gateway_route, config_revision="a" * 64))
    with pytest.raises(Exception) as failure:
        FacilityGenerationCoordinator._assert_provider_binding(run, changed)
    assert failure.value.code == "facility_generation_provider_changed"


def test_native_report_reader_uses_utf8_and_requires_complete_cleanup(tmp_path):
    from tools.verify_sage_gateway_desktop import summarize_native_reports
    (tmp_path / "generation-check.json").write_text(json.dumps({
        "status": "passed", "saveCalls": 0, "text": "\u200d"}, ensure_ascii=False), encoding="utf-8")
    cleanup = {"terminationConfirmed": True, "stdioClosed": True, "resourcesClosed": True,
               "shutdown": {"cleanupErrors": []}}
    runtime = {"network": {"saveCalls": 0}, "backends": [{"cleanup": cleanup}]}
    path = tmp_path / "last-application-run.json"
    path.write_text(json.dumps(runtime), encoding="utf-8")
    result = summarize_native_reports(tmp_path)
    assert result == {"status": "passed", "saveCalls": 0, "networkSaveCalls": 0, "cleanupConfirmed": True}
    cleanup["resourcesClosed"] = False
    path.write_text(json.dumps(runtime), encoding="utf-8")
    assert summarize_native_reports(tmp_path)["cleanupConfirmed"] is False
