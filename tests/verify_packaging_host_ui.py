"""Credential-independent main-host admission checks; no chat request is sent."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageChops, ImageStat
from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]


def verify(url: str, output: Path, preview_document: str | None = None):
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
            expect(frame.locator(".app-header")).to_be_hidden()
            expect(frame.locator("#command-ribbon")).to_be_hidden()
            expect(page.locator("#packaging-ribbon-product")).to_be_enabled()
            page.locator("#packaging-ribbon-product").click()
            frame.locator("#document-name").fill("TEST admission panels " + uuid4().hex[:8])
            frame.get_by_role("button", name="Add manual product", exact=True).click()
            page.locator("#packaging-ribbon-save").click()
            expect(frame.locator("#document-status")).to_contain_text("Saved")
            frame.locator("#close-panel").click()
            expect(page.locator("#packaging-ribbon-product")).to_be_focused()

            # Full viewport, native ribbon density, and no iframe remount while
            # panels, theme, viewport width, and model display modes change.
            child = page.locator("#packagingWorkspaceFrame").element_handle().content_frame()
            marker = child.evaluate("window.__ribbonMount = crypto.randomUUID()")
            for width, height in [(1600, 1000), (1280, 800), (1000, 800)]:
                page.set_viewport_size({"width": width, "height": height})
                metrics = page.evaluate("""() => {
                    const frame = document.getElementById('packagingWorkspaceFrame');
                    const toolbar = frame.contentDocument.getElementById('view-actions').getBoundingClientRect();
                    const viewport = frame.contentDocument.getElementById('viewport').getBoundingClientRect();
                    const ribbon = document.querySelector('.packaging-ribbon-shell').getBoundingClientRect();
                    const product = document.getElementById('packaging-ribbon-product').getBoundingClientRect();
                    const save = document.getElementById('packaging-ribbon-save').getBoundingClientRect();
                    return { centered:Math.abs(toolbar.x+toolbar.width/2-viewport.x-viewport.width/2),
                        viewportHeight:viewport.height, toolbarInside:toolbar.y >= viewport.y && toolbar.bottom < viewport.bottom,
                        ribbonInside:product.y >= ribbon.y && save.right <= ribbon.right+1,
                        headerHeight:frame.getBoundingClientRect().y, ribbonBottom:ribbon.bottom,
                        overflow:document.documentElement.scrollWidth > innerWidth+1 };
                }""")
                assert metrics["centered"] < 2 and metrics["toolbarInside"], metrics
                assert metrics["ribbonInside"] and not metrics["overflow"], metrics
                assert metrics["viewportHeight"] > height * .6, metrics
                assert metrics["headerHeight"] >= metrics["ribbonBottom"], metrics
                assert child.evaluate("window.__ribbonMount") == marker
                page.screenshot(path=str(output / f"host-ribbon-{width}.png"))
                # Overflow menu retains all finish/review commands on narrow hosts.
                appearance = page.locator("#packaging-ribbon-appearance")
                if appearance.is_visible():
                    appearance.click()
                else:
                    page.get_by_role("button", name="More packaging commands", exact=True).click()
                    page.locator("#packaging-menu-appearance").click()
                expect(frame.locator("#panel-title")).to_have_text("Appearance")
                frame.locator("#close-panel").click()
            page.set_viewport_size({"width": 1600, "height": 1000})
            for mode in ["Shaded with edges", "Wireframe"]:
                frame.get_by_role("button", name=mode, exact=True).click()
                frame.locator("#viewport canvas").screenshot(path=str(output / f"{mode}.png"))
            shaded = Image.open(output / "Shaded with edges.png").convert("RGB")
            wire = Image.open(output / "Wireframe.png").convert("RGB")
            assert max(ImageStat.Stat(shaded).stddev) > 3, "Blank 3D viewport"
            assert ImageChops.difference(shaded, wire).getbbox(), "Display modes did not change canvas"
            frame.get_by_role("button", name="Shaded with edges", exact=True).click()
            page.evaluate("document.documentElement.dataset.theme = 'light'")
            expect(frame.locator("html")).to_have_attribute("data-theme", "light")
            page.screenshot(path=str(output / "host-light.png"))
            page.evaluate("document.documentElement.dataset.theme = 'dark'")
            expect(frame.locator("html")).to_have_attribute("data-theme", "dark")
            expect(page.locator("#packaging-ribbon-resume")).to_be_hidden()
            page.evaluate("window._toggleLeftPanel()")
            page.locator("#rightRailAgent").click()
            expect(page.locator("#agentPanel")).to_be_visible()
            for width in [1600, 1280, 1000]:
                page.set_viewport_size({"width": width, "height": 900})
                bounds = page.evaluate("""() => {
                    const ribbon = document.querySelector('.packaging-ribbon-shell').getBoundingClientRect();
                    const save = document.getElementById('packaging-ribbon-save').getBoundingClientRect();
                    const frame = document.getElementById('packagingWorkspaceFrame');
                    const toolbar = frame.contentDocument.getElementById('view-actions').getBoundingClientRect();
                    return {right:save.right, limit:ribbon.right, toolbarRight:toolbar.right,
                        frameWidth:frame.clientWidth, overflow:document.documentElement.scrollWidth > innerWidth+1};
                }""")
                assert bounds["right"] <= bounds["limit"]+1 and not bounds["overflow"], bounds
                assert bounds["toolbarRight"] <= bounds["frameWidth"], bounds
                page.screenshot(path=str(output / f"host-sage-{width}.png"))
                page.get_by_role("button", name="Document packaging commands", exact=True).click()
                expect(page.locator("#packaging-menu-open")).to_be_visible()
                page.locator("#packaging-menu-open").click()
                expect(frame.locator("#open-dialog")).to_be_visible()
                expect(page.locator("#packaging-ribbon-product")).to_be_disabled()
                frame.locator("#close-open").click()
                expect(page.locator("#packaging-ribbon-product")).to_be_enabled()
            page.set_viewport_size({"width": 1600, "height": 1000})
            page.locator("#packaging-ribbon-product").click()
            page.wait_for_function("Boolean(window._packagingChatIdentity?.()?.conversation_id)")
            # Resource/account dialogs block admission before any state is published.
            frame.get_by_role("button", name="Imported sources", exact=True).click()
            expect(frame.locator("#resource-dialog")).to_be_visible()
            expect(page.locator("#packaging-ribbon-product")).to_be_disabled()
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
            expect(frame.locator("#document-new")).to_be_disabled()
            expect(page.locator("#packaging-ribbon-product")).to_be_disabled()
            expect(page.locator("#packaging-ribbon-save")).to_be_disabled()
            assert child.evaluate("window.InspectorProPackaging.executeCommand('new')") is False
            page.screenshot(path=str(output / "host-locked.png"))
            page.locator("#packaging-ribbon-resume").click()
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
            page.locator("#packaging-ribbon-product").click()
            expect(frame.locator('[name="quantity"]')).to_have_value("2")
            page.locator("#packaging-ribbon-save").click()
            expect(frame.locator("#document-status")).to_contain_text("Saved")

            # Changing the real host workflow revokes before disposing the editor.
            awaitable = "async () => { const s = await window.InspectorProPackagingHost.prepare(); return s.state; }"
            assert page.evaluate(awaitable) == "locked"
            page.locator('[data-tab="assembly"]').click()
            expect(page.locator("#packagingWorkspaceFrame")).to_have_count(0)
            assert any(method == "POST" and path.endswith("/revoke") for method, path in calls)
            assert not any("/api/agent/chat/v2/stream" in path or path.endswith("/api/agent/chat") for _, path in calls)
            if preview_document:
                document_url = url + "/api/packaging/documents/" + preview_document
                response = page.request.get(document_url)
                assert response.ok, response.text()
                original = response.json()
                page.locator('[data-tab="training"]').click()
                frame = page.frame_locator("#packagingWorkspaceFrame")
                page.get_by_role("button", name="Document packaging commands", exact=True).click()
                page.locator("#packaging-menu-open").click()
                frame.locator("#document-list > div").filter(has_text=original["design"]["name"]).get_by_role("button", name="Open", exact=True).click()
                expect(frame.locator("#document-name")).to_have_value(original["design"]["name"])
                expect(frame.locator("#scene-message")).to_have_text("", timeout=30000)
                frame.get_by_role("button", name="Appearance colors", exact=True).click()
                frame.get_by_label("Section", exact=True).check()
                frame.get_by_role("button", name="Fit view", exact=True).click()
                page.screenshot(path=str(output / "host-saved-package.png"))
                frame.get_by_role("button", name="Top", exact=True).click()
                page.screenshot(path=str(output / "host-saved-package-top.png"))
                assert page.request.get(document_url).json() == original, "Preview changed the saved document"
            degraded = context.new_page()
            degraded.on("pageerror", lambda error: errors.append(str(error)))
            degraded.add_init_script("""const getContext = HTMLCanvasElement.prototype.getContext;
                HTMLCanvasElement.prototype.getContext = function(type, ...args) {
                    return String(type).includes('webgl') ? null : getContext.call(this, type, ...args);
                };""")
            degraded.goto(url + "/packaging", wait_until="networkidle")
            expect(degraded.locator("#scene-message")).to_contain_text("3D unavailable")
            degraded.evaluate("document.documentElement.dataset.theme = 'light'")
            degraded.locator("#command-product").click()
            expect(degraded.locator("#tool-panel")).to_be_visible()
            degraded.close()
            assert not errors, errors
            result = {"passed": True, "page_errors": errors,
                      "checks": ["actual main-host iframe", "shared workflow ribbon and centered viewport toolbar", "1600/1280/1000 widths and overflow commands",
                                 "nonblank canvas and display-mode pixel changes", "light/dark theme sync", "WebGL-unavailable numeric editor", "no iframe remount",
                                 "new ribbon disabled under Sage lock", "Resume editing reconciliation",
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
    parser.add_argument("--preview-document", help="Optional saved document to load read-only for final viewport captures")
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime" / ("packaging-host-panels-" + uuid4().hex[:10]))
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to(ROOT / ".runtime"):
        parser.error("Output must remain inside this worktree's .runtime directory")
    verify(args.url.rstrip("/"), args.output.resolve(), args.preview_document)
