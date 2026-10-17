"""Opt-in paid language checks, stopping at policy selection; NOT full chat/layout acceptance."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

import pytest

from ai_inspector.facility_layout.generation_agent import CONTEXT_TOOL, generation_tool_specs, generation_preflight_tool, generation_provider_tools
from ai_inspector.facility_layout.generation_exploration import CATALOG_TOOL
from ai_inspector.facility_layout.generation_research_policy import POLICY_TOOL
from ai_inspector.facility_layout.errors import FacilityConflictError
from tests.test_facility_generation_admission import case
from tests.test_facility_generation_agent import chat, execute
from tests.test_facility_generation_research_policy import set_policy

pytestmark = pytest.mark.skipif(os.environ.get("INSPECTORPRO_LIVE_RESEARCH_POLICY") != "1",
                               reason="Explicit opt-in required for paid provider requests.")

CASES = [
    ("offline", False, "Plan a small assembly room with our workbenches. Do not search the internet.", "deny", "deny"),
    ("paraphrase", False, "Work from the details I supplied and the local equipment list; keep this exercise offline.", "deny", "deny"),
    ("catalog-is-not-offline", False, "Use only catalog equipment, but research public workstation arrangement guidance before planning.", "allow", "allow"),
    ("retained-denial", True, "Try a U-shaped arrangement instead, leaving all other requirements in place.", "inherit", "deny"),
    ("permission-change", True, "Actually, you may look up public manufacturer documents now.", "allow", "allow"),
    ("narrow-restriction", False, "Research this only from original manufacturers, never reseller pages.", "clarify", "clarify"),
    ("topic-restriction", False, "You can look online for general assembly methods, but not for information about equipment.", "clarify", "clarify"),
    ("publisher-restriction", False, "Consult government publications exclusively when researching clearances for the layout.", "clarify", "clarify"),
]


@pytest.mark.parametrize("case_id,prior_denial,prompt,decision,mode", CASES, ids=[item[0] for item in CASES])
def test_live_policy_interpretation(chat, case_id, prior_denial, prompt, decision, mode):
    import anthropic
    import server
    config = server._sage_answer_provider_config("deviation-analyst", active_mode="facility_layout")
    assert config.provider == "anthropic", "This bounded language probe currently supports the configured Anthropic path only."
    if prior_denial:
        chat["message"] = "No internet research for this plan."
        set_policy(chat, "deny", chat["message"])
    chat["turn"], chat["message"] = "live-" + case_id, prompt
    overview = execute(chat, CONTEXT_TOOL, {})
    system = server._apply_facility_layout_request_tool_policy({}, prompt,
        facility_state={"generationPlanning": chat["reference"]})["prompt"]
    tools = [{key: spec[key] for key in ("name", "description", "input_schema")} for spec in generation_tool_specs()]
    messages = [{"role": "user", "content": prompt},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "context-seed", "name": CONTEXT_TOOL, "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "context-seed", "content": json.dumps(overview)}]}]
    report = {"case": case_id, "prompt": prompt, "priorDenial": prior_denial, "provider": config.provider,
              "model": config.model, "expectedDecision": decision, "expectedMode": mode,
              "scope": "Actual generation prompt/tool schemas and required policy step after seeded context inspection; no browser, web fetch, or layout generation.",
              "responses": [], "receipt": None, "recoveryErrors": [], "passed": False}
    started = time.perf_counter()

    async def probe():
        observed = [{"tool": CONTEXT_TOOL, "status": "succeeded", "result": overview}]
        async with anthropic.AsyncAnthropic(api_key=config.api_key, timeout=90, max_retries=0) as client:
            for _ in range(3):
                required = generation_preflight_tool(observed)
                response = await server._invoke_agent_model(client, model=config.model, max_tokens=2200,
                    system=system, messages=messages, tools=generation_provider_tools(tools, required), provider=config.provider,
                    required_tool_name=required)
                content = [item.model_dump() for item in response.content]
                report["responses"].append({"content": content, "usage": response.usage.model_dump()})
                calls = [item for item in content if item["type"] == "tool_use"]
                policy_calls = [item for item in calls if item["name"] == POLICY_TOOL]
                if policy_calls:
                    assert len(policy_calls) == 1
                    chosen = policy_calls[0]
                    try:
                        report["receipt"] = execute(chat, POLICY_TOOL, chosen["input"])
                    except FacilityConflictError as exc:
                        if exc.code != "generation_research_policy_revision_conflict":
                            raise
                        error = {"code": exc.code, "message": str(exc)}
                        report["recoveryErrors"].append(error)
                        observed.append({"tool": POLICY_TOOL, "status": "failed", "error": error})
                        messages.extend([{"role": "assistant", "content": content}, {"role": "user", "content": [
                            {"type": "tool_result", "tool_use_id": chosen["id"], "is_error": True, "content": json.dumps(error)}]}])
                        continue
                    assert chosen["input"]["decision"] == decision
                    assert report["receipt"]["mode"] == mode
                    return
                assert calls, "Provider stopped before selecting a research policy."
                messages.append({"role": "assistant", "content": content})
                results = []
                for call in calls:
                    assert call["name"] in {CONTEXT_TOOL, CATALOG_TOOL}, "Unexpected planning/research before policy selection."
                    result = execute(chat, call["name"], call["input"])
                    observed.append({"tool": call["name"], "status": "succeeded", "result": result})
                    results.append({"type": "tool_result", "tool_use_id": call["id"], "content": json.dumps(result)})
                messages.append({"role": "user", "content": results})
            pytest.fail("Policy selection exceeded three provider calls.")

    try:
        asyncio.run(probe())
        report["passed"] = True
    except Exception as exc:
        report["errorType"] = type(exc).__name__
        raise
    finally:
        report["elapsedSeconds"] = time.perf_counter() - started
        output = Path(os.environ.get("INSPECTORPRO_RESEARCH_POLICY_EVIDENCE", ".runtime/research-policy-live"))
        output.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        (output / f"{stamp}-{case_id}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
