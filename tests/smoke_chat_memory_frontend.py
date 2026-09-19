from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "runtime_logs"


def _legacy_registry() -> dict[str, Any]:
    def session(agent: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "key": agent,
            "messages": messages,
            "summary": "",
            "scrollTop": 0,
            "pendingInput": "",
            "pendingCrossContext": None,
            "chatSessionId": f"legacy-session:{agent}",
            "workflowState": None,
            "workflowStateEvent": None,
        }

    messages = [
        {
            "id": "legacy-user",
            "role": "user",
            "blocks": [{"type": "text", "text": "Legacy question"}],
            "meta": {},
            "ts": 1,
        },
        {
            "id": "legacy-assistant",
            "role": "assistant",
            "blocks": [{"type": "text", "text": "Legacy answer"}],
            "meta": {},
            "ts": 2,
        },
    ]
    return {
        "version": 1,
        "currentConversationId": "legacy-chat-1",
        "conversations": {
            "legacy-chat-1": {
                "id": "legacy-chat-1",
                "title": "Legacy Pilot Chat",
                "createdAt": 1,
                "updatedAt": 2,
                "meta": {"lastAgent": "deviation-analyst"},
                "state": {
                    "currentAgent": "deviation-analyst",
                    "sessions": {
                        "inspector": session("inspector", []),
                        "deviation-analyst": session(
                            "deviation-analyst", messages
                        ),
                        "parts-finder": session("parts-finder", []),
                    },
                },
            }
        },
        "workspaceRecovery": {},
    }


def run(base_url: str) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    page_errors: list[str] = []
    chat_payloads: list[dict[str, Any]] = []
    chat_attempt = {"count": 0}

    def check(name: str, condition: bool, evidence: Any = None) -> None:
        checks.append({"name": name, "ok": bool(condition), "evidence": evidence})
        if not condition:
            raise AssertionError(f"{name}: {evidence!r}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 960})
        context.add_init_script(
            "localStorage.setItem('inspectorpro.chat_registry.v1', "
            + json.dumps(json.dumps(_legacy_registry()))
            + ");"
        )
        page = context.new_page()
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.route(
            "**/api/agent/chat/streaming-status",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"enabled": False, "agents": []}),
            ),
        )

        def route_chat(route) -> None:
            payload = route.request.post_data_json
            chat_payloads.append(payload)
            chat_attempt["count"] += 1
            if chat_attempt["count"] == 1:
                route.fulfill(
                    status=503,
                    content_type="application/json",
                    body=json.dumps({
                        "detail": {
                            "error": {
                                "code": "memory_unavailable",
                                "message": "Durable memory unavailable.",
                            }
                        }
                    }),
                )
                return
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "response": "Committed retry response.",
                    "tool_calls": [],
                    "memory": {
                        "mode": "enforce",
                        "turnId": "turn-browser-1",
                        "turnSequence": 1,
                        "replayed": True,
                        "warnings": [],
                    },
                }),
            )

        page.route("**/api/agent/chat", route_chat)
        page.goto(base_url, wait_until="domcontentloaded")
        page.wait_for_function(
            "document.getElementById('agentMemoryStatus')?.dataset.state === 'ready'",
            timeout=30000,
        )
        page.evaluate("window._toggleAgentPanel()")
        page.wait_for_selector("#agentPanel", state="visible")

        registry = page.evaluate(
            "JSON.parse(localStorage.getItem('inspectorpro.chat_registry.v1'))"
        )
        server_ids = [
            key
            for key, value in registry["conversations"].items()
            if value.get("backing") == "server"
        ]
        check("server conversation created", len(server_ids) >= 1, server_ids)
        check(
            "legacy chat archived",
            registry["conversations"]["legacy-chat-1"].get("readOnly") is True,
        )
        check(
            "current conversation is server-backed",
            registry["currentConversationId"] in server_ids,
            registry["currentConversationId"],
        )
        server_id = registry["currentConversationId"]

        server_listing = page.evaluate(
            "fetch('/api/agent/conversations?limit=50').then(r => r.json())"
        )
        listed_ids = [row["conversationId"] for row in server_listing["conversations"]]
        check("legacy chat was not uploaded", "legacy-chat-1" not in listed_ids)

        second_context = browser.new_context(viewport={"width": 1280, "height": 800})
        second_page = second_context.new_page()
        second_page.on("pageerror", lambda error: page_errors.append(str(error)))
        second_page.route(
            "**/api/agent/chat/streaming-status",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"enabled": False, "agents": []}),
            ),
        )
        second_page.goto(base_url, wait_until="domcontentloaded")
        second_page.wait_for_function(
            "document.getElementById('agentMemoryStatus')?.dataset.state === 'ready'",
            timeout=30000,
        )
        second_registry = second_page.evaluate(
            "JSON.parse(localStorage.getItem('inspectorpro.chat_registry.v1'))"
        )
        check(
            "second browser discovers server conversation",
            server_id in second_registry["conversations"],
            list(second_registry["conversations"]),
        )
        check(
            "browser caches remain isolated",
            "legacy-chat-1" not in second_registry["conversations"],
            list(second_registry["conversations"]),
        )
        second_context.close()

        page.click("#agentChatSwitcher")
        page.click('[data-conv-id="legacy-chat-1"]')
        page.wait_for_function(
            "document.getElementById('agentInput').disabled === true"
        )
        check(
            "legacy archive remains readable",
            "Legacy answer" in page.locator("#agentMessages").inner_text(),
        )
        check(
            "legacy archive is read only",
            "read only" in page.locator("#agentInput").get_attribute("placeholder"),
        )

        page.click("#agentChatSwitcher")
        page.click(f'[data-conv-id="{server_id}"]')
        page.wait_for_function(
            "document.getElementById('agentMemoryStatus')?.dataset.state === 'ready'",
            timeout=15000,
        )
        page.fill("#agentInput", "Retry this exact memory turn.")
        page.click("#agentSendBtn")
        page.wait_for_selector(".agent-stream-retry", timeout=15000)
        check(
            "memory failure is visible",
            "Memory unavailable" in page.locator("#agentMessages").inner_text(),
        )
        page.click(".agent-stream-retry")
        page.wait_for_function(
            "document.getElementById('agentMessages').innerText.includes('Committed retry response.')",
            timeout=15000,
        )
        check("two network attempts recorded", len(chat_payloads) == 2, len(chat_payloads))
        check("retry payload is byte-equivalent", chat_payloads[0] == chat_payloads[1])
        first = chat_payloads[0]
        check("server conversation ID sent", first.get("conversation_id") == server_id)
        check("server agent session ID sent", bool(first.get("agent_session_id")))
        check("client turn ID sent", str(first.get("client_turn_id", "")).startswith("client-turn:"))
        check("browser history omitted", first.get("history") == [])
        check(
            "semantic targets frozen",
            set(first["request_context"]["semantic_targets"])
            == {
                "partOccurrenceIds",
                "processMapNodeIds",
                "processMapEdgeIds",
                "facilityPlacementIds",
                "faiCharacteristicIds",
            },
        )

        # Replace the server detail response on reload to prove history hydration
        # is driven by committed server messages rather than the local cache.
        restored_payload = {
            "conversation": {
                "conversationId": server_id,
                "title": "Server Restored Chat",
                "status": "active",
                "createdAt": "2026-08-07T00:00:00Z",
                "updatedAt": "2026-08-07T01:00:00Z",
                "lastTurnSequence": 7,
                "retentionUntil": None,
                "metadata": {},
            },
            "agentSessions": [
                {
                    "agentSessionId": first["agent_session_id"],
                    "conversationId": server_id,
                    "agentType": "inspector",
                    "status": "active",
                }
            ],
            "messages": [
                {
                    "role": "user",
                    "content": "Server-restored question",
                    "turnId": "turn-restored",
                    "sequence": 7,
                    "clientTurnId": "client-restored",
                    "agentSessionId": first["agent_session_id"],
                    "agentType": "inspector",
                },
                {
                    "role": "assistant",
                    "content": "Server-restored answer",
                    "turnId": "turn-restored",
                    "sequence": 7,
                    "committedAt": "2026-08-07T01:00:00Z",
                    "agentSessionId": first["agent_session_id"],
                    "agentType": "inspector",
                },
            ],
            "memoryMode": "enforce",
        }
        page.route(
            f"**/api/agent/conversations/{server_id}",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(restored_payload),
            ),
        )
        page.evaluate("localStorage.clear()")
        page.reload(wait_until="domcontentloaded")
        page.wait_for_function(
            "document.getElementById('agentMemoryStatus')?.dataset.state === 'ready'",
            timeout=30000,
        )
        check(
            "clearing local storage does not erase server history",
            "Server-restored answer" in page.locator("#agentMessages").inner_text(),
        )

        # Exercise the real delete path after the synthetic detail response has
        # proved reload hydration. The UI must replace the deleted conversation,
        # and the deleted server record must not reappear after another reload.
        page.unroute(f"**/api/agent/conversations/{server_id}")
        panel_visible = page.locator("#agentPanel").is_visible()
        if not panel_visible:
            page.evaluate("window._toggleAgentPanel()")
            page.wait_for_selector("#agentPanel", state="visible")
        page.click("#agentChatMenuBtn")
        page.click("#chatMenuClear")
        page.wait_for_function(
            """deletedId => {
                const raw = localStorage.getItem('inspectorpro.chat_registry.v1');
                if (!raw) return false;
                const registry = JSON.parse(raw);
                return registry.currentConversationId
                    && registry.currentConversationId !== deletedId
                    && document.getElementById('agentMemoryStatus')?.dataset.state === 'ready';
            }""",
            arg=server_id,
            timeout=30000,
        )
        replacement_id = page.evaluate(
            "JSON.parse(localStorage.getItem('inspectorpro.chat_registry.v1')).currentConversationId"
        )
        listing_after_delete = page.evaluate(
            "fetch('/api/agent/conversations?limit=50').then(r => r.json())"
        )
        ids_after_delete = [
            row["conversationId"]
            for row in listing_after_delete["conversations"]
        ]
        check(
            "deleting server conversation removes it",
            server_id not in ids_after_delete,
            ids_after_delete,
        )
        check(
            "deleting server conversation creates replacement",
            replacement_id in ids_after_delete,
            replacement_id,
        )

        page.reload(wait_until="domcontentloaded")
        page.wait_for_function(
            "document.getElementById('agentMemoryStatus')?.dataset.state === 'ready'",
            timeout=30000,
        )
        registry_after_delete_reload = page.evaluate(
            "JSON.parse(localStorage.getItem('inspectorpro.chat_registry.v1'))"
        )
        check(
            "deleted server conversation stays removed after reload",
            server_id not in registry_after_delete_reload["conversations"],
            list(registry_after_delete_reload["conversations"]),
        )

        if not page.locator("#agentPanel").is_visible():
            page.evaluate("window._toggleAgentPanel()")
            page.wait_for_selector("#agentPanel", state="visible")

        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(
            path=str(ARTIFACT_DIR / "sage_memory_p17_frontend.png"),
            full_page=True,
        )
        browser.close()

    result = {
        "baseUrl": base_url,
        "checks": checks,
        "pageErrors": page_errors,
        "passed": sum(1 for item in checks if item["ok"]),
        "total": len(checks),
    }
    (ARTIFACT_DIR / "sage_memory_p17_frontend.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=True) + "\n",
        encoding="ascii",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8057/")
    args = parser.parse_args()
    result = run(args.base_url)
    print(f"{result['passed']}/{result['total']} passed")
    if result["pageErrors"]:
        raise SystemExit("page errors: " + repr(result["pageErrors"]))


if __name__ == "__main__":
    main()
