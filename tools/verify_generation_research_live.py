"""Opt-in real chat/provider check on an isolated empty destination.

Prompts are CLI inputs, never recipes or candidate geometry. Saved application
layouts are not used. This exercises HTTP/provider/tools, not native Electron UI.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--correction")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--private-assets", action="store_true")
    parser.add_argument("--require-research", action="store_true")
    parser.add_argument("--require-source-read", action="store_true")
    parser.add_argument("--require-local-documents", action="store_true",
                        help="Require a local summary, a readable PDF page and retention of that page in the planning context")
    parser.add_argument("--forbid-public-research", action="store_true")
    parser.add_argument("--require-process-sequence", action="store_true")
    parser.add_argument("--expected-placement-counts", nargs="+", type=int)
    parser.add_argument("--expect-quantity-only-correction", action="store_true")
    parser.add_argument("--stream", action="store_true", help="Exercise the actual v2 SSE chat endpoint and retain status events")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / ".runtime"):
        parser.error("Evidence output must be a new directory under the project's .runtime.")
    output.mkdir(parents=True, exist_ok=False)
    import server
    from fastapi.testclient import TestClient
    from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, LOCAL_SITE_ID, LOCAL_LAYOUT_ID
    from ai_inspector.facility_layout.canonical import layout_revision
    from ai_inspector.facility_layout.generation_exploration import SEARCH_TOOL, READ_TOOL, DOCUMENT_TOOL, PREPARE_TOOL
    from ai_inspector.facility_layout.generation_presentation import generation_research_source_block

    original_host = server._FACILITY_LAYOUT_HOST
    host = LocalFacilityLayoutHost(output / "isolated-facility", private_assets=args.private_assets)
    before = host.ensure_bootstrap()["layout"]["layout"]
    base = layout_revision(before)
    server._FACILITY_LAYOUT_HOST = host
    state = {"scope": "isolated HTTP chat; live provider; not native desktop", "savedBaseRevision": base,
             "privateCatalog": args.private_assets, "turns": [], "tools": [], "saveCalls": 0, "passed": False}
    original_execute = host.generation_agent_service.execute
    def execute(*positional, **kwargs):
        started = time.monotonic()
        trace = {"tool": kwargs["tool_name"], "arguments": deepcopy(kwargs["arguments"])}
        state["tools"].append(trace)
        try:
            result = original_execute(*positional, **kwargs)
            trace.update(status="succeeded", result=deepcopy(result))
            return result
        except Exception as exc:
            trace.update(status="failed", code=getattr(exc, "code", type(exc).__name__), message=str(exc), details=getattr(exc, "details", {}))
            raise
        finally:
            trace["elapsedSeconds"] = time.monotonic() - started
            (output / "progress.json").write_text(json.dumps(state, indent=2, ensure_ascii=True), encoding="utf-8")
            print(json.dumps({"tool": trace["tool"], "status": trace.get("status"), "code": trace.get("code"),
                              "message": trace.get("message"), "elapsedSeconds": trace["elapsedSeconds"]}), flush=True)
    def refuse_save(*args, **kwargs):
        state["saveCalls"] += 1
        raise AssertionError("Preview attempted Save")
    host.generation_agent_service.execute = execute
    host.service.save_layout = refuse_save
    session = "live-" + uuid.uuid4().hex
    reference = {"workspaceId": session, "sourceContextRef": None, "editorContext": {
        "baseRevision": base, "draftRevision": base, "dirty": False, "conflicted": False, "pending": False,
        "generationRunId": None, "designTransactionId": None}}
    history = []
    try:
        with TestClient(server.app) as client:
            for message in [args.prompt] + ([args.correction] if args.correction else []):
                started = time.monotonic()
                tool_start = len(state["tools"])
                response = client.post("/api/agent/chat/v2/stream" if args.stream else "/api/agent/chat", json={"message": message, "history": history,
                    "agent_type": "deviation-analyst", "session_id": session, "client_turn_id": uuid.uuid4().hex,
                    "inspection_context": {"attachments": {"session": {"active_mode": "training"}, "facility_layout": {
                        "siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": base, "generationPlanning": reference}}}})
                events = []
                if args.stream and response.status_code == 200:
                    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
                    terminal = next((item for item in events if item.get("event") in {"response_completed", "response_error"}), {})
                    payload = terminal.get("final") or {"error": terminal}
                else:
                    payload = response.json()
                state["turns"].append({"message": message, "httpStatus": response.status_code,
                    "elapsedSeconds": time.monotonic() - started, "response": payload, "streamEvents": events})
                expected_sources = generation_research_source_block(state["tools"][tool_start:])
                source_blocks = [block for block in payload.get("content_blocks", []) if block.get("type") == "sources"]
                assert source_blocks == ([expected_sources] if expected_sources else []), "Displayed sources differ from retained tool receipts"
                state["turns"][-1]["sourceCardsMatchReceipts"] = True
                print(json.dumps({"httpStatus": response.status_code, "elapsedSeconds": state["turns"][-1]["elapsedSeconds"],
                    "planning": payload.get("facility_generation_planning"), "response": str(payload.get("response", ""))[:1800]}), flush=True)
                if response.status_code != 200 or payload.get("facility_generation_planning", {}).get("status") != "preview_ready":
                    raise AssertionError("Live conversation did not produce a validated preview; inspect retained evidence.")
                preview = payload["facility_generation_planning"]["preview"]
                if args.require_process_sequence:
                    assert preview.get("processValidation", {}).get("checkedSequenceCount", 0) > 0, "No executable process sequence checked"
                reference["sourceContextRef"] = preview["sourceContextRef"]
                binding = host.generation_agent_service.bind(host.principal(), site_id=LOCAL_SITE_ID,
                    layout_id=LOCAL_LAYOUT_ID, base_revision=base, reference=reference)
                prior = host.generation_admission_service.prior_package(host.principal(), binding)
                assert prior["previewId"] == preview["previewId"] and prior["previewRevision"] == preview["previewRevision"]
                state["turns"][-1]["modelPackage"] = prior["package"]
                state["turns"][-1]["requirementLedger"] = host.generation_agent_service._ledger(host.principal(), binding)
                history.extend([{"role": "user", "content": message}, {"role": "assistant", "content": payload.get("response", "")}])
        if args.expected_placement_counts:
            assert [turn["response"]["facility_generation_planning"]["preview"]["counts"]["placements"]
                    for turn in state["turns"]] == args.expected_placement_counts, "Requested placement counts differ"
        if args.expect_quantity_only_correction:
            assert len(state["turns"]) == 2, "Quantity-only comparison requires two completed turns"
            original, corrected = [deepcopy(turn["modelPackage"]) for turn in state["turns"]]
            changed = 0
            for original_resource, corrected_resource in zip(original["equipmentRequirements"], corrected["equipmentRequirements"]):
                assert original_resource["requirementId"] == corrected_resource["requirementId"], "Correction changed resource identities"
                changed += original_resource["quantity"] != corrected_resource["quantity"]
                corrected_resource["quantity"] = original_resource["quantity"]
            assert changed == 1 and corrected == original, "Quantity correction changed another package field"
            state["quantityOnlyCorrection"] = True
        if args.require_research:
            assert any(item["tool"] in {SEARCH_TOOL, READ_TOOL} and item["status"] == "succeeded" for item in state["tools"]), "No successful live research"
        if args.require_source_read:
            assert any(item["tool"] == READ_TOOL and item["status"] == "succeeded" for item in state["tools"]), "No successful source read"
        if args.require_local_documents:
            documents = [item["result"] for item in state["tools"] if item["tool"] == DOCUMENT_TOOL and item["status"] == "succeeded"]
            assert any(item["action"] == "summary" for item in documents), "No local capability summary read"
            pages = [item for item in documents if item["action"] == "page" and item.get("textStatus") == "extracted"]
            assert pages, "No readable local PDF page consulted"
            retained = [ref for item in state["tools"] if item["tool"] == PREPARE_TOOL and item["status"] == "succeeded"
                        for ref in item["arguments"].get("localDocumentRefs", [])]
            assert any(item["localDocumentRef"] in retained for item in pages), "No local PDF page retained in the planning context"
        if args.forbid_public_research:
            assert not any(item["tool"] in {SEARCH_TOOL, READ_TOOL} for item in state["tools"]), "Offline conversation attempted public research"
        after = host.service.get_layout(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID)["layout"]
        assert after == before and state["saveCalls"] == 0
        state.update(passed=True, savedAfterRevision=layout_revision(after))
        return 0
    except Exception as exc:
        state["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        print(json.dumps(state["failure"]), flush=True)
        return 1
    finally:
        after = host.service.get_layout(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID)["layout"]
        state["savedAfterRevision"] = layout_revision(after)
        state["savedUnchanged"] = after == before and state["saveCalls"] == 0
        if not state["savedUnchanged"]:
            state["passed"] = False
        (output / "report.json").write_text(json.dumps(state, indent=2, ensure_ascii=True), encoding="utf-8")
        server._FACILITY_LAYOUT_HOST = original_host
        host.close()


if __name__ == "__main__":
    raise SystemExit(main())
