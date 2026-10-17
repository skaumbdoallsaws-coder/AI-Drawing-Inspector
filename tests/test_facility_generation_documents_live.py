"""Paid, opt-in summary-to-manual tool-use probes; not full layout qualification."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

import pytest

from ai_inspector.facility_layout.generation_agent import CONTEXT_TOOL, generation_tool_specs
from ai_inspector.facility_layout.generation_exploration import DOCUMENT_TOOL, CATALOG_TOOL
from ai_inspector.facility_layout.generation_research_policy import POLICY_TOOL
from ai_inspector.facility_layout.errors import FacilityValidationError
from ai_inspector.facility_layout.host import build_private_local_asset_catalog
from tests.test_facility_generation_admission import case
from tests.test_facility_generation_agent import chat, execute
from tests.test_facility_generation_exploration import brief


pytestmark = pytest.mark.skipif(os.environ.get("INSPECTORPRO_LIVE_EQUIPMENT_DOCUMENTS") != "1",
                               reason="Explicit opt-in required for paid provider requests and the private public-manual archive.")


@pytest.mark.parametrize("asset_id,model_name,topic,content_markers", [
    ("asset-haas-st30-lathe", "Haas ST-30", "G76 threading", ("first pass cutting depth", "thread taper amount", "setting 95")),
    ("asset-mobile-lift-mmle-50d", "MMLE-50D", "braking and stationary use", ("brake lift table when not moving", "press the brake pedal")),
])
def test_live_summary_then_manual(brief, monkeypatch, asset_id, model_name, topic, content_markers):
    import anthropic
    import server
    config = server._sage_answer_provider_config("deviation-analyst", active_mode="facility_layout")
    assert config.provider == "anthropic"
    asset = next(row for row in build_private_local_asset_catalog() if row["assetId"] == asset_id)
    catalog = brief["service"].catalog_provider(brief["principal"], brief["binding"]["siteId"])
    monkeypatch.setattr(brief["service"], "catalog_provider", lambda *args: [*catalog, asset])
    monkeypatch.setattr(brief["agent"].exploration.researcher, "run", lambda **kwargs: pytest.fail("Offline request used web research"))
    prompt = f"We may use the {model_name} in a new cell. First read its local capability summary, then read the manual section about {topic} so we can identify setup limitations. Do not search the internet. Do not generate or save a layout yet."
    brief["message"], brief["turn"] = prompt, "live-local-documents-" + asset_id
    execute(brief, POLICY_TOOL, {"expectedPolicyRevision": None, "decision": "deny", "sourceText": "Do not search the internet."})
    overview = execute(brief, CONTEXT_TOOL, {})
    catalog_page = execute(brief, CATALOG_TOOL, {"query": asset_id, "offset": 0, "limit": 8})
    system = server._apply_facility_layout_request_tool_policy({}, prompt,
        facility_state={"generationPlanning": brief["reference"]})["prompt"]
    specs = [{key: spec[key] for key in ("name", "description", "input_schema")} for spec in generation_tool_specs()]
    messages = [{"role": "user", "content": prompt}]
    for number, (tool, args, result) in enumerate(((CONTEXT_TOOL, {}, overview),
        (CATALOG_TOOL, {"query": asset_id, "offset": 0, "limit": 8}, catalog_page))):
        call_id = f"seed-{number}"
        messages.extend([{"role": "assistant", "content": [{"type": "tool_use", "id": call_id, "name": tool, "input": args}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": call_id, "content": json.dumps(result)}]}])
    report = {"assetId": asset_id, "prompt": prompt, "model": config.model, "provider": config.provider,
        "scope": "Live model selects summary/manual reads after seeded context and catalog. No web, browser, layout generation, Apply or Save.",
        "responses": [], "receipts": [], "recoveryErrors": [], "contentMarkers": content_markers, "passed": False}
    started = time.perf_counter()

    async def probe():
        summary_read = False
        async with anthropic.AsyncAnthropic(api_key=config.api_key, timeout=90, max_retries=0) as client:
            for _ in range(6):
                response = await server._invoke_agent_model(client, model=config.model, max_tokens=2200, system=system,
                    messages=messages, tools=specs, provider=config.provider, required_tool_name=None)
                content = [item.model_dump() for item in response.content]
                report["responses"].append({"content": content, "usage": response.usage.model_dump()})
                calls = [item for item in content if item["type"] == "tool_use"]
                assert calls, "Provider stopped before the requested manual read."
                messages.append({"role": "assistant", "content": content})
                results = []
                for call in calls:
                    assert call["name"] in {CONTEXT_TOOL, CATALOG_TOOL, DOCUMENT_TOOL}, "Unexpected action during offline source reading."
                    try:
                        result = execute(brief, call["name"], call["input"])
                    except FacilityValidationError as exc:
                        if exc.code != "equipment_document_revision_mismatch" or exc.details.get("failureKind") != "reference_mismatch":
                            raise
                        error = {"code": exc.code, "message": str(exc), "details": exc.details}
                        report["recoveryErrors"].append(error)
                        results.append({"type": "tool_result", "tool_use_id": call["id"], "is_error": True, "content": json.dumps(error)})
                        continue
                    report["receipts"].append({"tool": call["name"], "result": result})
                    if call["name"] == DOCUMENT_TOOL:
                        assert result["assetId"] == asset_id
                        if result["action"] == "summary":
                            summary_read = True
                        else:
                            assert summary_read, "Manual accessed before the requested summary."
                        # A contents/index mention alone does not satisfy the requested section read.
                        text = " ".join(result.get("text", "").lower().split())
                        if (result["action"] == "page" and result["textStatus"] == "extracted"
                                and all(marker in text for marker in content_markers)):
                            assert "manual" in result["documentId"].lower(), "A brochure did not satisfy the manual request."
                            assert result["executableConstraints"] is False
                            return
                    results.append({"type": "tool_result", "tool_use_id": call["id"], "content": json.dumps(result)})
                messages.append({"role": "user", "content": results})
            pytest.fail("Summary-to-manual probe exhausted six provider calls.")

    try:
        asyncio.run(probe())
        report["passed"] = True
    except Exception as exc:
        report["errorType"] = type(exc).__name__
        raise
    finally:
        report["elapsedSeconds"] = time.perf_counter() - started
        root = Path(os.environ.get("INSPECTORPRO_EQUIPMENT_DOCUMENT_EVIDENCE", ".runtime/equipment-documents-live"))
        root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        (root / f"{stamp}-{asset_id}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
