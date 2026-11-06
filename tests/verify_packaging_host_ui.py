"""Credential-independent main-host admission checks; no chat request is sent."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]


def verify(url: str, output: Path):
    output.mkdir(parents=True, exist_ok=False)
    errors, calls = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--enable-unsafe-swiftshader"])
        context = browser.new_context(viewport={"width": 1600, "height": 1000})
        page = context.new_page()
        page.set_default_timeout(20000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("dialog", lambda dialog: dialog.accept())
        page.on("request", lambda request: calls.append((request.method, request.url)))
        try:
            page.goto(url + "/?packagingPilot=1", wait_until="domcontentloaded", timeout=60000)
            page.locator('[data-tab="training"]').click()
            page.locator("#trainingTypeRibbonTrigger").click()
            page.locator("#trainingTypeRibbonOption-packaging_shipping").click()
            frame = page.frame_locator("#packagingWorkspaceFrame")
            expect(frame.locator("#command-product")).to_be_enabled()
            frame.locator("#command-product").click()
            frame.locator("#document-name").fill("TEST admission panels " + uuid4().hex[:8])
            frame.get_by_role("button", name="Add manual product", exact=True).click()
            frame.get_by_role("button", name="Save", exact=True).click()
            expect(frame.locator("#document-status")).to_contain_text("Saved")
            page.wait_for_function("Boolean(window._packagingChatIdentity?.()?.conversation_id)")
            # Resource/account dialogs block admission before any state is published.
            frame.get_by_role("button", name="Imported sources", exact=True).click()
            expect(frame.locator("#resource-dialog")).to_be_visible()
            rejected = page.evaluate("""async () => {
                try { await window.InspectorProPackagingHost.prepare(); return ''; }
                catch(error) { return error.message; }
            }""")
            assert "Save or reload" in rejected, rejected
            assert not any(method == "POST" and path.endswith("/api/packaging/editor") for method, path in calls)
            page.keyboard.press("Escape")
            expect(frame.locator("#resource-dialog")).to_be_hidden()
            result = page.evaluate("""async () => {
                const state = await window.InspectorProPackagingHost.prepare();
                return {state:state.state,revision:state.revision};
            }""")
            assert result["state"] == "locked", result
            expect(frame.locator("html")).to_have_attribute("data-packaging-locked", "true")
            expect(frame.locator("#command-product")).to_be_disabled()
            expect(frame.locator("#command-appearance")).to_be_disabled()
            expect(frame.locator("#command-graphics")).to_be_disabled()
            expect(frame.locator("#close-panel")).to_be_disabled()
            expect(frame.get_by_role("button", name="New", exact=True)).to_be_disabled()
            page.screenshot(path=str(output / "host-locked.png"))
            frame.locator("#packaging-resume-editing").click()
            expect(frame.locator("html")).to_have_attribute("data-packaging-locked", "false")
            expect(frame.locator("#command-appearance")).to_be_enabled()

            # Closing a panel retains unapplied input and must not mint admission.
            frame.locator('[name="quantity"]').fill("2")
            frame.locator("#close-panel").click()
            before = len([path for method, path in calls if method == "POST" and path.endswith("/api/packaging/editor")])
            rejected = page.evaluate("""async () => {
                try { await window.InspectorProPackagingHost.prepare(); return ''; }
                catch(error) { return error.message; }
            }""")
            assert "Save or reload" in rejected, rejected
            after = len([path for method, path in calls if method == "POST" and path.endswith("/api/packaging/editor")])
            assert before == after
            frame.locator("#command-product").click()
            expect(frame.locator('[name="quantity"]')).to_have_value("2")
            frame.get_by_role("button", name="Save", exact=True).click()
            expect(frame.locator("#document-status")).to_contain_text("Saved")

            # Changing the real host workflow revokes before disposing the editor.
            awaitable = "async () => { const s = await window.InspectorProPackagingHost.prepare(); return s.state; }"
            assert page.evaluate(awaitable) == "locked"
            page.locator('[data-tab="assembly"]').click()
            expect(page.locator("#packagingWorkspaceFrame")).to_have_count(0)
            assert any(method == "POST" and path.endswith("/revoke") for method, path in calls)
            assert not any("/api/agent/chat/v2/stream" in path or path.endswith("/api/agent/chat") for _, path in calls)
            assert not errors, errors
            result = {"passed": True, "page_errors": errors,
                      "checks": ["actual main-host iframe", "new ribbon disabled under Sage lock", "Resume editing reconciliation",
                                 "open resource dialog rejected before publication", "closed dirty panel rejected before publication", "workflow switch revocation", "no model inference"]}
            (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps({**result, "output": str(output)}), flush=True)
        except Exception:
            page.screenshot(path=str(output / "failure.png"), full_page=True)
            (output / "failure.txt").write_text(page.locator("body").inner_text(), encoding="utf-8")
            raise
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8181")
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime" / ("packaging-host-panels-" + uuid4().hex[:10]))
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to(ROOT / ".runtime"):
        parser.error("Output must remain inside this worktree's .runtime directory")
    verify(args.url.rstrip("/"), args.output.resolve())
