"""Explicitly opted-in, two-turn live Sage/Codex check on copied facility data."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import site
import sqlite3
import sys
import time


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Authorize at most two read-only model turns using the selected credentials")
    parser.add_argument("--subscription-profile", type=Path, help="Use only this desktop profile's encrypted ChatGPT account")
    parser.add_argument("--stale-check", action="store_true", help="One turn; a test-only concurrent writer advances the disposable copy during a real read")
    parser.add_argument("--edit-check", action="store_true", help="One turn: real invalid placement, correction preview, test-only approval and undo on the disposable copy")
    parser.add_argument("--direct-check", action="store_true", help="With --edit-check: exercise standing direct consent and exact Undo")
    parser.add_argument("--authoring-request", help="With --edit-check: test this request on the copied layout, then approve and undo the exact result")
    parser.add_argument("--workflow-check", action="store_true", help="Two read-only turns inspecting authored navigation and process bindings")
    parser.add_argument("--research-check", action="store_true", help="One read-only turn: public search, selected-source read and chat citations")
    parser.add_argument("--model", required=True)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--dependency-dir", required=True, type=Path)
    parser.add_argument("--api-key-file", type=Path, help="Read only the OpenAI credential from this existing dotenv file")
    parser.add_argument("--credential-profile-id", help="Read the existing desktop profile's API credential from Windows Credential Manager")
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--layout-file", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path, help="New disposable directory")
    args = parser.parse_args()
    if args.direct_check and not args.edit_check:
        parser.error("--direct-check requires --edit-check")
    if args.authoring_request and not args.edit_check:
        parser.error("--authoring-request requires --edit-check")
    if sum((args.stale_check, args.edit_check, args.workflow_check, args.research_check)) > 1:
        parser.error("Choose one acceptance scenario")
    if not args.live:
        parser.error("Pass --live only after approval for model inference")
    sys.path.insert(0, str(ROOT))
    site.addsitedir(str(args.dependency_dir.resolve()))
    if args.credential_profile_id and args.api_key_file:
        parser.error("Select one credential source")
    if args.subscription_profile:
        if args.credential_profile_id or args.api_key_file:
            parser.error("Subscription mode cannot use API credentials")
        from desktop.runtime.application_profile import load_application_profile
        profile = load_application_profile(args.subscription_profile.resolve()).value
        os.environ.update({"INSPECTORPRO_CODEX_AUTH_MODE": "chatgpt_plan",
            "INSPECTORPRO_CODEX_AUTH_PROFILE_ID": profile["profileId"],
            "INSPECTORPRO_CODEX_AUTH_ROOT": str(Path(profile["dataRoot"]) / "chatgpt-auth")})
        key = ""
    elif args.credential_profile_id:
        from desktop.runtime.codex_credentials import read_api_key
        key = read_api_key(args.credential_profile_id)
    else:
        key = os.environ.get("INSPECTORPRO_CODEX_API_KEY")
    if not key and args.api_key_file:
        from dotenv import dotenv_values
        values = dotenv_values(args.api_key_file, interpolate=False)
        key = values.get("INSPECTORPRO_CODEX_API_KEY") or values.get("OPENAI_API_KEY")
        del values
    if not key and not args.subscription_profile:
        parser.error("No explicitly supplied OpenAI API credential is available")

    output = args.output_root.resolve()
    if ROOT not in output.parents:
        parser.error("The disposable output must be inside the repository")
    output.mkdir(parents=True, exist_ok=False)
    source_bytes = args.layout_file.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    document = json.loads(source_bytes)
    store = output / "facility"
    authority_source = (args.source_root / "authorities").resolve()
    if sys.platform == "win32":
        store = Path("\\\\?\\" + str(store))
        authority_source = Path("\\\\?\\" + str(authority_source))
    shutil.copytree(authority_source, store / "authorities")
    os.environ.update({
        "PYTHON_DOTENV_DISABLED": "1",
        "INSPECTORPRO_FACILITY_LAYOUT_ROOT": str(store),
        "INSPECTORPRO_FACILITY_PRIVATE_ASSETS": "1",
        "INSPECTORPRO_MEMORY_V1_MODE": "off",
        "INSPECTORPRO_MEMORY_DB_PATH": str(output / "memory.sqlite"),
        "INSPECTORPRO_METRICS_DB": str(output / "metrics.sqlite"),
        "INSPECTORPRO_PARTS_MANUAL_ROOT": str(output / "parts-manual"),
        "INSPECTORPRO_OPERATIONS_MANUAL_ROOT": str(output / "operations-manual"),
        "INSPECTORPRO_SPECIFICATION_SHEET_ROOT": str(output / "specification-sheet"),
        "INSPECTORPRO_WORK_INSTRUCTION_ROOT": str(output / "work-instruction"),
        "INSPECTORPRO_CODEX_READONLY_PILOT": "1",
        "INSPECTORPRO_CODEX_EDIT_PREVIEWS": "1" if args.edit_check else "0",
        "INSPECTORPRO_CODEX_ALLOW_PAID_INFERENCE": "0" if args.subscription_profile else "1",
        "INSPECTORPRO_CODEX_ALLOW_SUBSCRIPTION_INFERENCE": "1" if args.subscription_profile else "0",
        "INSPECTORPRO_CODEX_AUTH_MODE": "chatgpt_plan" if args.subscription_profile else "api_key",
        "INSPECTORPRO_CODEX_API_KEY": key,
        "INSPECTORPRO_CODEX_BINARY": str(args.binary.resolve()),
        "INSPECTORPRO_CODEX_PILOT_ROOT": str(output / "pilot"),
        "INSPECTORPRO_CODEX_MODEL": args.model,
        "INSPECTORPRO_CODEX_WEB_RESEARCH": "1" if args.research_check else "0",
        "INSPECTORPRO_CODEX_RESEARCH_PROVIDER": "openai",
        "INSPECTORPRO_CHAT_STREAMING": "1",
        "INSPECTORPRO_STREAMING_AGENTS": "sage",
    })
    del key
    if args.edit_check:
        from ai_inspector.facility_layout.feature_flags import FACILITY_LAYOUT_FEATURE_FLAGS
        os.environ.update({name: "1" for name in FACILITY_LAYOUT_FEATURE_FLAGS})
    from fastapi.testclient import TestClient
    import server
    from ai_inspector.facility_layout.host import LOCAL_SITE_ID
    from ai_inspector.codex_runtime.facility_tools import FacilityReadGateway

    host = server._FACILITY_LAYOUT_HOST
    host.ensure_bootstrap()
    principal = host.principal()
    copied = host.layout_repository.create_layout(principal, LOCAL_SITE_ID, document)
    reference = {"siteId": LOCAL_SITE_ID, "layoutId": document["layoutId"], "revision": copied["revision"]}
    evidence = {"model": args.model, "authMode": "chatgpt_plan" if args.subscription_profile else "api_key",
        "apiFallback": False, "sourceSha256": source_hash, "readOnly": True,
        "staleCheck": args.stale_check, "editCheck": args.edit_check, "workflowCheck": args.workflow_check,
        "researchCheck": args.research_check,
        "acceptanceScope": "Execution, exact commit and Undo; not design completeness" if args.authoring_request else "Selected acceptance scenario",
        "expected": {"zones": len(document["zones"]), "placements": len(document["placements"])},
        "turns": [], "status": "running"}
    messages = [
        "Inspect this saved gym layout. How many zones and placed assets does it contain? "
        "Then find the cardio zone and inspect its authored dimensions or area, and name two actual "
        "equipment placements there. Use the real inspection data, not just the zone's label. "
        "Do not change or save anything. Keep the answer under 150 words.",
        "Which zone did we just examine? Recheck its authored area in square metres and tell me "
        "whether the station count in its label proves the number of equipment placements. "
        "Keep it brief and do not change anything.",
    ]
    original_read = FacilityReadGateway._read_data
    if args.research_check:
        messages = [
            "This is a read-only public-research verification. Inspect the saved layout context first, but do not "
            "send its contents or identifiers to the web. Then use search_public_sources restricted to access-board.gov "
            "to locate the U.S. Access Board's official ADA guidance on accessible car parking space and adjacent "
            "access-aisle widths. Use read_public_source on the relevant returned researchId/sourceIndex to read the "
            "actual source. Report the minimum car-space and access-aisle widths with units and a clickable source link. "
            "Distinguish those access aisles from vehicle maneuvering/drive aisles; do not claim this gym complies. "
            "Use at most one successful search and one source read, and keep the answer under 130 words. "
            "Do not edit, preview or save anything."]
    if args.workflow_check:
        messages = [
            "Inspect the saved layout, then check its authored navigation context using observe_navigation_context. "
            "Report actual actor, anchor and movement-program counts and any missing semantics. Do not compile routes "
            "or claim that authored navigation is validated. Do not change anything. Keep it under 120 words.",
            "Now inspect_saved_process_bindings for this same saved layout. Report the total recorded bindings "
            "and give at most two examples if any exist. Distinguish recorded Process Map references from validation "
            "of those maps; report missing bindings honestly. Do not change anything. Keep it under 100 words."]
    if args.edit_check:
        messages = [
            "This is a disposable-copy placement validation test. Inspect the saved gym first. "
            "Then preview moving treadmill pl-e1f4de8e9d905153b1179895 to position x=18.5, y=0, z=2.1 metres. "
            "Submit that exact candidate to the preview tool so the actual validator can check it. "
            "If it rejects interference, correct the position to x=15.2, y=0, z=2.1 and preview again. "
            "Preserve the orientation and every other object. Do not rename the layout or make any other changes. "
            "Do not approve or save anything. Return the valid preview for my review, under 100 words."]
    if args.stale_check:
        messages = ["Inspect this saved layout and report its name and asset count from the tools. Do not change anything."]

        def read_with_concurrent_save(reader, name, arguments):
            data = original_read(reader, name, arguments)
            if not evidence.get("concurrentWriter"):
                current = host.service.get_layout(principal, LOCAL_SITE_ID, document["layoutId"])
                changed = current["layout"]
                changed["displayName"] += " (concurrent test revision)"
                receipt = host.layout_repository.save_layout(principal, LOCAL_SITE_ID,
                    document["layoutId"], changed, current["revision"])
                evidence["concurrentWriter"] = {"tool": name, "testOnly": True,
                    "previousRevision": current["revision"], "resultingRevision": receipt["revision"]}
            return data

        # Synchronize the external writer at the read boundary; the model,
        # geometry reads, repository save and revision guard remain real.
        FacilityReadGateway._read_data = read_with_concurrent_save
    if args.direct_check:
        messages[0] = messages[0].replace(
            "Do not approve or save anything. Return the valid preview for my review, under 100 words.",
            "Apply Directly mode is selected. Stage the corrected batch; the app will handle authorization and saving. Keep it under 60 words.")
    if args.authoring_request:
        messages = [args.authoring_request]
    try:
        client = TestClient(server.app)
        thread_ids = []
        for index, message in enumerate(messages, 1):
            started = time.monotonic()
            response = client.post("/api/agent/chat/v2/stream", json={
                "message": message, "agent_type": "deviation-analyst", "session_id": "codex-live-check",
                "agent_session_id": "codex-live-check", "conversation_id": "codex-live-conversation",
                "client_turn_id": "codex-live-turn-" + str(index),
                "inspection_context": {"attachments": {
                    "session": {"active_mode": "facility_layout"},
                    "facility_layout": {**reference, "state": {"dirty": False, "conflict": False,
                        "editMode": "direct" if args.direct_check else "preview"}},
                }},
            })
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            terminal = next((event for event in reversed(events) if event.get("event") in {"response_completed", "response_error"}), {})
            final = terminal.get("final") or {}
            result = {"turn": index, "message": message, "httpStatus": response.status_code,
                "elapsedSeconds": round(time.monotonic() - started, 3),
                "terminal": terminal.get("event"), "errorCode": terminal.get("code"),
                "answer": final.get("response"), "inspection": final.get("codex_inspection"),
                "contentBlocks": final.get("content_blocks", []),
                "streamDeltas": sum(event.get("event") == "text_delta" for event in events),
                "phases": sorted({event["phase"] for event in events if event.get("phase")}),
                "actionMode": final.get("facility_action_mode"), "uiToolCalls": final.get("tool_calls")}
            evidence["turns"].append(result)
            if terminal.get("event") == "response_error":
                journal_path = output / "pilot" / "pilot.sqlite"
                if journal_path.is_file():
                    with sqlite3.connect(journal_path) as db:
                        row = db.execute("SELECT result FROM turns WHERE turn_id=?", ("codex-live-turn-" + str(index),)).fetchone()
                        result["diagnostic"] = json.loads(row[0]).get("diagnostic") if row else None
            print(json.dumps(result), flush=True)
            if args.stale_check:
                with sqlite3.connect(output / "pilot" / "pilot.sqlite") as db:
                    status, recorded = db.execute("SELECT status,result FROM turns WHERE turn_id=?",
                        ("codex-live-turn-1",)).fetchone()
                recorded = json.loads(recorded)
                evidence["journal"] = {"status": status, **recorded}
                if (terminal.get("event") != "response_error" or terminal.get("code") != "codex_document_unavailable"
                        or final or status != "failed" or not evidence.get("concurrentWriter")
                        or not any(r.get("errorCode") == "codex_document_unavailable" for r in recorded.get("receipts", []))):
                    raise RuntimeError("Stale revision was not rejected with a failed tool receipt")
                evidence["status"] = "passed"
                break
            if args.edit_check:
                if terminal.get("event") != "response_completed" or final.get("facility_action_mode") != ("COMMIT" if args.direct_check else "PREVIEW"):
                    raise RuntimeError("No completed editing preview")
                receipts = final["codex_inspection"]["verifiedToolCalls"]
                previews = [r for r in receipts if r["tool"] == "preview_facility_operations"]
                if not args.authoring_request and (len(previews) < 2 or previews[0]["ok"] or not previews[-1]["ok"]):
                    raise RuntimeError("No model-driven invalid-placement then correction evidence")
                assert host.service.get_layout(principal, LOCAL_SITE_ID, document["layoutId"])["revision"] == copied["revision"]
                commands = final.get("tool_calls") or []
                assert len(commands) == 1 and commands[0]["name"] == "present_codex_facility_preview"
                proposal_id = commands[0]["args"]["proposalId"]
                preview = host.service.get_layout_proposal_preview(principal, LOCAL_SITE_ID, document["layoutId"], proposal_id)
                alternative = preview["alternative"]
                if not args.authoring_request:
                    assert alternative["operations"] == [{"op": "move_placement", "placementId": "pl-e1f4de8e9d905153b1179895",
                        "position": {"x": 15.2, "y": 0, "z": 2.1}}]
                else:
                    assert alternative["operations"]
                    (output / "authoring-preview.json").write_text(json.dumps(preview, indent=2), encoding="utf-8")
                binding = alternative["transactionBinding"]
                authorization = {"explicit_approval": not args.direct_check,
                    "authorization_mode": "direct" if args.direct_check else "explicit", "direct_consent": args.direct_check}
                if args.direct_check:
                    assert commands[0]["args"]["editMode"] == "direct" and alternative["directApplyPolicy"]["eligible"]
                approval = host.service.approve_layout_proposal(principal, LOCAL_SITE_ID, document["layoutId"],
                    proposal_id, binding, session_id="test-only-approver", idempotency_key="test-approved-move", **authorization)
                committed = host.service.apply_layout_proposal(principal, LOCAL_SITE_ID, document["layoutId"],
                    approval["approvalToken"], binding, session_id="test-only-approver", idempotency_key="test-approved-move")
                from ai_inspector.facility_layout.operation_proposals import create
                undo = create(host.service, principal, LOCAL_SITE_ID, document["layoutId"], committed["revision"],
                    undo_receipt_id=committed["receipt"]["receiptId"], edit_mode="direct" if args.direct_check else "preview")
                undo_binding = undo["alternative"]["transactionBinding"]
                undo_approval = host.service.approve_layout_proposal(principal, LOCAL_SITE_ID, document["layoutId"],
                    undo["proposalId"], undo_binding, session_id="test-only-approver", idempotency_key="test-approved-undo", **authorization)
                restored = host.service.apply_layout_proposal(principal, LOCAL_SITE_ID, document["layoutId"],
                    undo_approval["approvalToken"], undo_binding, session_id="test-only-approver", idempotency_key="test-approved-undo")
                expected = dict(copied["layout"])
                expected["updatedAt"] = restored["layout"]["updatedAt"]
                assert expected == restored["layout"]
                evidence["approvedEdit"] = {"testOnlyApprover": True, "proposalId": proposal_id,
                    "authorizationMode": approval.get("authorizationMode", "explicit"),
                    "receiptId": committed["receipt"]["receiptId"], "undoReceiptId": restored["receipt"]["receiptId"],
                    "restoredExactContent": True, "finalRevision": restored["revision"]}
                evidence["status"] = "passed"
                break
            if terminal.get("event") != "response_completed" or final.get("facility_action_mode") != "READ_ONLY" or final.get("tool_calls") != []:
                raise RuntimeError("Live inspection did not complete through the read-only Sage path")
            if not result["streamDeltas"]:
                raise RuntimeError("No streamed answer was observed")
            receipts = (result["inspection"] or {}).get("verifiedToolCalls", [])
            if not any(receipt.get("ok") for receipt in receipts):
                raise RuntimeError("No successful model-selected inspection tool call")
            if index == 1 and len({r["tool"] for r in receipts if r.get("ok")}) < 2:
                raise RuntimeError("The first turn did not exercise a multi-tool inspection")
            if args.workflow_check:
                expected_tool = "observe_navigation_context" if index == 1 else "inspect_saved_process_bindings"
                assert any(r["tool"] == expected_tool and r["ok"] for r in receipts), expected_tool
            if args.research_check:
                for expected_tool in ("inspect_facility_context", "search_public_sources", "read_public_source"):
                    if not any(r["tool"] == expected_tool and r["ok"] for r in receipts):
                        raise RuntimeError("Missing successful live tool: " + expected_tool)
                research = result["inspection"].get("researchReceipts", [])
                reads = [r for r in research if r.get("operation") == "read" and r.get("complete")
                    and r.get("provider") == "openai" and r.get("productionEligible") is False
                    and any(s.get("url") == r.get("requestedUrl") and s.get("retrieval") == "fetched_document"
                        for s in r.get("sources", []))]
                cards = [s for b in result["contentBlocks"] if b.get("type") == "sources" for s in b.get("sources", [])]
                verified_urls = {s["url"] for r in research for s in r.get("sources", [])}
                if (not reads or not cards or any(s.get("url") not in verified_urls for s in cards)
                        or not any(r["requestedUrl"] in (result["answer"] or "") for r in reads)):
                    raise RuntimeError("Complete source read and receipt-derived chat citations were not verified")
                evidence["researchVerified"] = {"readUrls": [r["requestedUrl"] for r in reads],
                    "sourceCards": len(cards), "receiptCount": len(research), "allCardUrlsFromReceipts": True}
                break
            with sqlite3.connect(output / "pilot" / "pilot.sqlite") as db:
                thread_ids.append(db.execute("SELECT thread_id FROM sessions").fetchone()[0])
        if not args.stale_check and not args.edit_check and not args.research_check:
            evidence["sameThreadResumed"] = thread_ids[0] == thread_ids[1]
            evidence["countsPresentInAnswer"] = args.workflow_check or all(str(count) in evidence["turns"][0]["answer"] for count in evidence["expected"].values())
            if not evidence["sameThreadResumed"] or not evidence["countsPresentInAnswer"]:
                raise RuntimeError("Thread continuity or reported counts did not match the saved layout")
        evidence["status"] = "passed"
    except Exception as error:
        evidence["status"] = "failed"
        evidence["failureType"] = type(error).__name__
        evidence["failureCode"] = getattr(error, "code", None)
    finally:
        FacilityReadGateway._read_data = original_read
        evidence["sourceUnchanged"] = hashlib.sha256(args.layout_file.read_bytes()).hexdigest() == source_hash
        evidence["copiedRevisionUnchanged"] = host.service.get_layout(principal, LOCAL_SITE_ID, document["layoutId"])["revision"] == copied["revision"]
        expected_revision = evidence.get("approvedEdit", {}).get("finalRevision",
            evidence.get("concurrentWriter", {}).get("resultingRevision", copied["revision"]))
        evidence["copiedRevisionMatchesExpected"] = host.service.get_layout(principal, LOCAL_SITE_ID, document["layoutId"])["revision"] == expected_revision
        if not evidence["sourceUnchanged"] or not evidence["copiedRevisionMatchesExpected"]:
            evidence["status"] = "failed"
        host.close()
        (output / "live-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in evidence.items() if key != "turns"}), flush=True)
    return 0 if evidence["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
