"""Offline coverage for Sage's opt-in OpenAI final-answer adapter."""

import asyncio
from types import SimpleNamespace

import pytest

import server


def _raw_openai_response():
    return SimpleNamespace(
        output=[
            SimpleNamespace(
                type="message",
                content=[SimpleNamespace(type="output_text", text="Grounded answer.")],
            ),
            SimpleNamespace(
                type="function_call",
                name="highlight_parts",
                arguments='{"part_numbers":["100006"]}',
            ),
        ],
        output_text="Grounded answer.",
        usage=SimpleNamespace(
            input_tokens=41,
            output_tokens=12,
            input_tokens_details=SimpleNamespace(cached_tokens=7),
        ),
    )


def test_sage_openai_provider_uses_latest_default(monkeypatch):
    monkeypatch.setenv("INSPECTORPRO_SAGE_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.delenv("INSPECTORPRO_SAGE_OPENAI_MODEL", raising=False)
    monkeypatch.delenv("INSPECTORPRO_SAGE_OPENAI_REASONING_EFFORT", raising=False)

    config = server._sage_answer_provider_config("deviation-analyst")

    assert config.provider == "openai"
    assert config.model == "gpt-5.6-sol"
    assert config.reasoning_effort == "medium"


def test_non_sage_agents_remain_on_anthropic(monkeypatch):
    monkeypatch.setenv("INSPECTORPRO_SAGE_PROVIDER", "openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")

    config = server._sage_answer_provider_config("inspector")

    assert config.provider == "anthropic"
    assert config.model == server.SAGE_ANTHROPIC_MODEL_DEFAULT


def test_facility_model_mismatch_fails_before_api_key_or_provider_client(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv(
        "INSPECTORPRO_FACILITY_LAYOUT_SAGE_ANTHROPIC_MODEL", raising=False
    )
    monkeypatch.setenv("INSPECTORPRO_SAGE_ANTHROPIC_MODEL", "claude-opus-5")

    with pytest.raises(server.HTTPException) as exc:
        server._sage_answer_provider_config(
            "deviation-analyst", active_mode="facility_layout"
        )

    assert exc.value.detail["error"]["code"] == "facility_model_mismatch"


def test_facility_scoped_model_isolated_from_shared_sage_override(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("INSPECTORPRO_SAGE_ANTHROPIC_MODEL", "claude-opus-5")
    monkeypatch.setenv(
        "INSPECTORPRO_FACILITY_LAYOUT_SAGE_ANTHROPIC_MODEL",
        server.SAGE_ANTHROPIC_MODEL_DEFAULT,
    )

    config = server._sage_answer_provider_config(
        "deviation-analyst", active_mode="facility_layout"
    )

    assert config.provider == "anthropic"
    assert config.model == server.SAGE_ANTHROPIC_MODEL_DEFAULT


def test_facility_skill_incompatibility_fails_before_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setattr(server, "_facility_skill_compatible_models", lambda: ("gpt",))

    with pytest.raises(server.HTTPException) as exc:
        server._sage_answer_provider_config(
            "deviation-analyst", active_mode="facility_layout"
        )

    assert exc.value.detail["error"]["code"] == "facility_model_mismatch"


def test_openai_input_preserves_history_text_and_images():
    payload = server._openai_responses_input([
        {"role": "user", "content": "Earlier question"},
        {"role": "assistant", "content": "Earlier answer"},
        {"role": "user", "content": [
            {"type": "text", "text": "<trusted_application_context>facts</trusted_application_context>"},
            {"type": "image", "source": {
                "type": "base64", "media_type": "image/png", "data": "aGVsbG8=",
            }},
            {"type": "text", "text": "<user_request>What is the impact?</user_request>"},
        ]},
    ])

    content = payload[0]["content"]
    assert payload[0]["role"] == "user"
    assert "[assistant]" in content[0]["text"]
    assert any(part["type"] == "input_image" for part in content)
    assert any("What is the impact?" in part.get("text", "") for part in content)


def test_openai_input_preserves_trusted_facility_tool_observations():
    messages = [{
        "role": "user",
        "content": [{
            "type": "text",
            "text": "What is the exact department area?",
        }],
    }]
    server._append_facility_tool_results_to_messages(
        messages,
        [{
            "tool": "inspect_facility_semantics",
            "arguments": {"view": "department_metrics"},
            "status": "succeeded",
            "result": {
                "authoritative": True,
                "evidenceClass": "derived",
                "grossAreaM2": 100.0,
            },
        }],
        round_index=1,
    )

    payload = server._openai_responses_input(messages)
    text = "\n".join(
        part.get("text", "")
        for part in payload[0]["content"]
        if part.get("type") == "input_text"
    )

    assert "What is the exact department area?" in text
    assert '<trusted_facility_tool_results round="1">' in text
    assert '"authoritative":true' in text
    assert '"evidenceClass":"derived"' in text


def test_openai_response_normalizes_text_tool_calls_and_usage():
    response = server._normalize_openai_agent_response(_raw_openai_response())

    assert server._accumulate_response_text(response) == "Grounded answer."
    assert server.extract_provider_tool_calls(response, "deviation-analyst") == [{
        "name": "highlight_parts", "args": {"part_numbers": ["100006"]},
    }]
    assert response.usage.input_tokens == 41
    assert response.usage.output_tokens == 12
    assert response.usage.cache_read_input_tokens == 7


def test_openai_adapter_uses_responses_contract_without_network():
    captured = {}

    class _Responses:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return _raw_openai_response()

    fake_client = SimpleNamespace(responses=_Responses())
    response = asyncio.run(server._invoke_agent_model(
        fake_client,
        provider="openai",
        model="gpt-5.6-sol",
        max_tokens=256,
        system="System rules",
        messages=[{"role": "user", "content": "Answer this."}],
        tools=[{
            "name": "highlight_parts",
            "description": "Highlight parts.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        }],
        required_tool_name="highlight_parts",
        reasoning_effort="low",
    ))

    assert captured["instructions"] == "System rules"
    assert captured["model"] == "gpt-5.6-sol"
    assert captured["reasoning"] == {"effort": "low"}
    assert captured["tools"][0]["type"] == "function"
    assert captured["tool_choice"] == {
        "type": "function",
        "name": "highlight_parts",
    }
    assert server._accumulate_response_text(response) == "Grounded answer."
