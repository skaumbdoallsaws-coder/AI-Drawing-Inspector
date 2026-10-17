"""Real chat/kernel with synthetic transport, plus explicitly opted-in live calls."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_inspector.model_gateway import CONFIG_ENV, GatewayError, load_config, request_scope
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.generation_agent import CONTEXT_TOOL, REQUIREMENTS_TOOL, PREVIEW_TOOL
from ai_inspector.facility_layout.generation_research_policy import POLICY_TOOL
from tests.test_facility_generation_admission import case
from tests.test_facility_generation_agent import chat, execute


def configure(chat, monkeypatch, tmp_path, *, deployment="astra-candidate"):
    import server
    source = Path(__file__).resolve().parents[1] / "config/sage-gateway.json"
    config = json.loads(source.read_text())
    config["roles"]["facility-planner"] = deployment
    path = tmp_path / "gateway.json"
    path.write_text(json.dumps(config))
    monkeypatch.setenv(CONFIG_ENV, str(path))
    monkeypatch.setenv("INSPECTORPRO_SKILLS_ENABLED", "1")
    monkeypatch.setenv("INSPECTORPRO_MEMORY_V1_MODE", "off")
    monkeypatch.setattr(server, "_FACILITY_LAYOUT_HOST", chat["host"])
    monkeypatch.setattr(server, "_run_skill_route_production", lambda *a, **k: pytest.fail("Explicit planning called the router"))
    server._reset_agent_skill_runtime_cache_for_tests()
    return config, path


def request_body(chat):
    return {"message": chat["message"], "history": [], "agent_type": "deviation-analyst",
            "session_id": "gateway-chat-test", "client_turn_id": chat["turn"],
            "inspection_context": {"attachments": {"session": {"active_mode": "facility_layout"}, "facility_layout": {
                "siteId": chat["options"]["site_id"], "layoutId": chat["options"]["layout_id"],
                "revision": chat["ledger"]["baseRevision"], "generationPlanning": chat["reference"]}}}}


def assert_saved_unchanged(chat):
    saved = chat["host"].service.get_layout(chat["principal"], **{
        key: chat["options"][key] for key in ("site_id", "layout_id")})["layout"]
    assert layout_revision(saved) == chat["ledger"]["baseRevision"]


def test_live_requirement_schema_lowering_preserves_validation(chat):
    import jsonschema
    from ai_inspector.model_gateway import explicit_named_properties
    from ai_inspector.facility_layout.generation_agent import generation_tool_specs, _bind_requirement_segments
    schema = next(spec["input_schema"] for spec in generation_tool_specs() if spec["name"] == REQUIREMENTS_TOOL)
    _bind_requirement_segments(schema, [{"id": "s0"}], has_prior_requirements=False)
    lowered = explicit_named_properties(schema)
    values = [{key: value for key, value in item.items() if key not in {"start", "end"}}
              for item in chat["record"]["requirements"]]
    valid = {"expectedLedgerRevision": None, "requirementsBySegment": {"s0": values}}
    left, right = jsonschema.Draft202012Validator(schema), jsonschema.Draft202012Validator(lowered)
    left.validate(valid)
    right.validate(valid)
    for change in ("unknown_predicate", "missing_segment", "extra_segment", "negative_quantity"):
        changed = deepcopy(valid)
        segments = changed["requirementsBySegment"]
        if change == "unknown_predicate":
            segments["s0"][0]["predicate"]["kind"] = "invented_geometry_rule"
        elif change == "missing_segment":
            del segments["s0"]
        elif change == "extra_segment":
            segments["s1"] = deepcopy(values)
        else:
            quantity = next(item for item in segments["s0"] if item["predicate"]["kind"] == "resource_quantity")
            quantity["predicate"]["parameters"]["quantity"] = -1
        assert not left.is_valid(changed) and not right.is_valid(changed)


@pytest.mark.parametrize("deployment", ["astra-candidate", "claude-baseline"])
def test_actual_chat_gateway_to_kernel_preview_and_binding(chat, monkeypatch, tmp_path, deployment):
    import server
    import ai_inspector.model_gateway as gateway
    from fastapi.testclient import TestClient
    config, path = configure(chat, monkeypatch, tmp_path, deployment=deployment)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-no-network")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-no-network")
    outputs, requests, failures = [], [], []
    original = chat["agent"].execute
    def observe(*args, **kwargs):
        try:
            result = original(*args, **kwargs)
        except Exception as exc:
            failures.append(exc.code)
            raise
        if kwargs["tool_name"] != POLICY_TOOL:
            outputs.append(result)
        return result
    monkeypatch.setattr(chat["agent"], "execute", observe)
    async def respond(**kwargs):
        requests.append(kwargs)
        assert kwargs["store"] is False and kwargs["max_retries"] == 0
        if kwargs.get("tool_choice", {}).get("name") == POLICY_TOOL:
            name, arguments = POLICY_TOOL, {"expectedPolicyRevision": None, "decision": "inherit", "sourceText": None}
        elif len(outputs) == 1:
            name, arguments = REQUIREMENTS_TOOL, chat["record"]
        else:
            name, arguments = PREVIEW_TOOL, {"requestKey": "gateway-preview", "expectedLedgerRevision": outputs[-1]["ledgerRevision"],
                "proposal": deepcopy(chat["request"]["proposal"])}
            if not failures:
                arguments["proposal"]["equipmentRequirements"][0]["quantity"] = 3
        return {"status": "completed", "model": kwargs["model"].split("/", 1)[1], "id": "receipt-" + str(len(requests)),
                "output": [{"type": "function_call", "call_id": "call-" + str(len(requests)),
                            "name": name, "arguments": json.dumps(arguments)}], "usage": {"input_tokens": 10, "output_tokens": 20}}
    monkeypatch.setattr(gateway, "_sdk", lambda: SimpleNamespace(aresponses=respond))
    with TestClient(server.app) as client:
        response = client.post("/api/agent/chat", json=request_body(chat))
    assert response.status_code == 200, response.text
    payload = response.json()["facility_generation_planning"]
    assert payload["status"] == "preview_ready" and payload["saved"] is False
    assert payload["preview"]["counts"]["placements"] == 2
    assert failures == ["generation_requirements_not_satisfied"]
    assert all(call["gateway"]["deployment"] == deployment for call in payload["timings"]["providerCalls"])
    assert_saved_unchanged(chat)
    config["deployments"][deployment]["timeoutSeconds"] += 1
    path.write_text(json.dumps(config))
    with pytest.raises(Exception) as failure:
        execute(chat, CONTEXT_TOOL, {})
    assert failure.value.code == "model_gateway_run_changed"
    monkeypatch.delenv(CONFIG_ENV)
    with pytest.raises(Exception) as failure:
        execute(chat, CONTEXT_TOOL, {})
    assert failure.value.code == "model_gateway_run_changed"
    assert_saved_unchanged(chat)


def test_server_scope_and_named_gateway_failure(monkeypatch):
    import server
    config = load_config({CONFIG_ENV: "config/sage-gateway.json"})
    async def body(request, http_request):
        assert server.current_gateway_config() is config
        raise GatewayError("model_gateway_provider_failed", "Safe provider failure")
    monkeypatch.setattr(server, "load_gateway_config", lambda: config)
    monkeypatch.setattr(server, "_agent_chat_impl", body)
    request = server.AgentChatRequest(message="inspect", agent_type="deviation-analyst", inspection_context={
        "attachments": {"session": {"active_mode": "facility_layout"}}})
    with pytest.raises(server.HTTPException) as failure:
        asyncio.run(server.agent_chat(request, None))
    assert failure.value.status_code == 503
    assert failure.value.detail["error"]["code"] == "model_gateway_provider_failed"
    assert server._stream_provider_error_payload(failure.value) == {
        "code": "model_gateway_provider_failed", "message": "Safe provider failure", "retryable": False}


def test_non_facility_request_does_not_activate_gateway(monkeypatch):
    import server
    from ai_inspector.model_gateway import current_config
    monkeypatch.setattr(server, "load_gateway_config", lambda: pytest.fail("Other workflow loaded Facility gateway"))
    async def body(*args):
        assert current_config() is None
        return {"unrelated": True}
    monkeypatch.setattr(server, "_agent_chat_impl", body)
    request = server.AgentChatRequest(message="inspect", agent_type="inspector", inspection_context={})
    assert asyncio.run(server.agent_chat(request, None)) == {"unrelated": True}


@pytest.mark.parametrize("message", [
    "Generate a facility layout preview for manual assembly with two workbenches.",
    "Build a manual inspection cell in this layout and keep the aisle fixed.",
])
def test_facility_manual_work_does_not_dispatch_hidden_documentation(message):
    import server
    context = {"attachments": {"session": {"active_mode": "facility_layout"},
        "documentation": {"document_type": "illustrated_parts_manual"}}}
    request = server.AgentChatRequest(message=message, agent_type="deviation-analyst", inspection_context=context)
    assert server._documentation_effective_chat_message(request) == message
    assert server._deterministic_documentation_chat_result(request) is None
    explicit = server.AgentChatRequest(message="Build an illustrated parts manual.",
        agent_type="deviation-analyst", inspection_context=context)
    assert server._deterministic_documentation_chat_result(explicit)["tool_calls"][0]["name"] == "generate_parts_manual_draft"


@pytest.mark.skipif(os.environ.get("INSPECTORPRO_LIVE_GATEWAY") != "1", reason="Paid provider calls require explicit opt-in.")
def test_live_gateway_chat_to_layout(chat, monkeypatch, tmp_path):
    import server
    from ai_inspector.model_gateway import GatewayClient
    from fastapi.testclient import TestClient
    from dotenv import load_dotenv
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root.parent / ".env", override=False)
    configure(chat, monkeypatch, tmp_path, deployment=os.environ.get("INSPECTORPRO_LIVE_GATEWAY_DEPLOYMENT", "astra-candidate"))
    chat["message"] = "Generate a facility layout preview from these reviewed requirements. " + chat["message"]
    for department in chat["request"]["proposal"]["departments"]:
        chat["message"] = chat["message"].replace(f"Use the specified allocation for {department['label']}.",
            f"Allocate {department['areaShare'] * 100:g} percent to {department['label']} in row {department['row']}.")
    report = {"scope": "Actual HTTP chat, gateway provider and deterministic kernel over isolated reviewed fixture; no desktop rendering.",
              "prompt": chat["message"], "passed": False, "providerResponses": []}
    invoke = GatewayClient.invoke
    async def observe(self, **kwargs):
        response = await invoke(self, **kwargs)
        report["providerResponses"].append({"content": [vars(block) for block in response.content],
                                            "stopReason": response.stop_reason, "gateway": response.gateway_metadata})
        return response
    monkeypatch.setattr(GatewayClient, "invoke", observe)
    try:
        with TestClient(server.app) as client:
            response = client.post("/api/agent/chat", json=request_body(chat))
        report["httpStatus"] = response.status_code
        report["response"] = response.json()
        assert response.status_code == 200, response.text
        result = response.json()["facility_generation_planning"]
        assert result["status"] == "preview_ready", result
        assert result["preview"]["counts"]["placements"] == 2
        assert result["saved"] is False
        assert_saved_unchanged(chat)
        report["passed"] = True
    finally:
        import time
        output = root / f".runtime/sage-gateway-20261001/live-chat-{time.time_ns()}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
