"""Headless browser check of recovery drafts: unsaved work survives a closed editor and interrupted saves reconcile.

Self-contained: it starts its own packaging app from this worktree on a free local port with a throwaway store in
the system temp directory and aborts every browser request to another host. A "crash" closes the editor page
without saving; interrupted saves are simulated by intercepting the editor's own save request. No running pilot,
desktop host, carrier, research or Sage request is involved, and the native desktop guard is not exercised.

    python tests/verify_packaging_recovery_ui.py [--output .runtime/<new folder>]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.parse import urlsplit
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.verify_packaging_comparison_ui import HEADERS, designs  # noqa: E402
from tests.verify_packaging_research_ui import start_pilot, tools_scope  # noqa: E402


def verify(url, output, service, principal):
    errors, external, checks, prompts = [], [], [], []
    scope, owner = tools_scope(principal), principal.principal_id
    seed, _ = designs()
    seed["name"] = "TEST recovery " + uuid4().hex[:6]

    def drafts():
        return service.drafts(scope, owner)

    def revision(doc_id):
        return service.get(scope, doc_id)["revision"]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--enable-unsafe-swiftshader"])
        context = browser.new_context(viewport={"width": 1440, "height": 1000})

        def local_only(route):
            if urlsplit(route.request.url).netloc != urlsplit(url).netloc:
                external.append(route.request.url)
                route.abort()
            else:
                route.continue_()

        context.route("**/*", local_only)
        created = context.request.post(url + "/api/packaging/documents?contents_confirmed=true", data=seed, headers=HEADERS)
        assert created.ok, created.text()
        doc = created.json()
        doc_path = "/api/packaging/documents/" + doc["id"]

        def editor():
            page = context.new_page()
            page.set_default_timeout(20000)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("dialog", lambda dialog: (prompts.append(dialog.message), dialog.accept()))
            page.goto(url + "/packaging", wait_until="networkidle")
            return page

        def open_document(page):
            page.get_by_role("button", name="Open", exact=True).click()
            page.locator(".document-row").filter(has_text=seed["name"]).get_by_role("button", name="Open", exact=True).click()
            expect(page.locator("#document-name")).to_have_value(seed["name"])

        def rename(page, name):
            with page.expect_response(lambda r: r.request.method == "PUT" and "/api/packaging/drafts/" in r.url) as put:
                page.locator("#document-name").fill(name)
            assert put.value.ok, put.value.text()

        def recovery(page, expected):
            dialog = page.locator("#resource-dialog")
            expect(dialog).to_contain_text("Recover unsaved work")
            expect(dialog).to_contain_text(expected)
            return dialog

        def saved_put(page):
            return page.expect_request(lambda r: r.method == "PUT" and r.url.endswith(doc_path))

        # A. Unsaved edits survive a closed editor; Restore and Save; the draft is then removed.
        page = editor()
        expect(page.locator("#resource-dialog")).to_have_count(0)
        open_document(page)
        rename(page, "TEST recovered A")
        assert [(d["status"], d["name"]) for d in drafts()] == [("current", "TEST recovered A")]
        page.close()
        page = editor()
        dialog = recovery(page, "Unsaved changes to revision 0 | checkpoint")
        dialog.screenshot(path=str(output / "recover-dialog.png"))
        dialog.get_by_role("button", name="Restore 1", exact=True).click()
        expect(page.locator("#document-name")).to_have_value("TEST recovered A")
        expect(page.locator("#document-status")).to_contain_text("Revision 0 | Unsaved changes")
        with page.expect_response(lambda r: r.request.method == "DELETE" and "/api/packaging/drafts/" in r.url):
            page.get_by_role("button", name="Save", exact=True).click()
        assert revision(doc["id"]) == 1 and drafts() == []
        checks.append("A: unsaved edits survived a closed editor, were restored, saved as revision 1 and the draft was removed")

        # B. The save reached the server but its response was lost: recovery reports it saved and removes the draft.
        rename(page, "TEST saved B")

        def lose_response(route):
            if route.request.method != "PUT":
                return route.fallback()
            route.fetch()
            route.abort()

        page.route("**" + doc_path, lose_response)
        with page.expect_event("requestfailed", lambda r: r.method == "PUT" and r.url.endswith(doc_path)):
            page.get_by_role("button", name="Save", exact=True).click()
        assert revision(doc["id"]) == 2 and drafts()[0]["status"] == "saved"
        page.close()
        page = editor()
        dialog = recovery(page, "Saved before the interruption")
        dialog.get_by_role("button", name="Open saved document 1", exact=True).click()
        expect(page.locator("#message")).to_contain_text("These changes were already saved (revision 2). The recovery draft was removed.")
        expect(page.locator("#document-name")).to_have_value("TEST saved B")
        assert revision(doc["id"]) == 2 and drafts() == []
        checks.append("B: a save whose response was lost was reported as saved (revision 2, applied once) and its draft removed")

        # C. The save never reached the server: Restore, then Save replays the original request ID once.
        rename(page, "TEST replayed C")
        page.unroute("**" + doc_path)
        page.route("**" + doc_path, lambda route: route.abort() if route.request.method == "PUT" else route.fallback())
        with page.expect_event("requestfailed", lambda r: r.method == "PUT" and r.url.endswith(doc_path)):
            page.get_by_role("button", name="Save", exact=True).click()
        pending = drafts()[0]["pending"]
        assert revision(doc["id"]) == 2 and pending["kind"] == "edit", pending
        page.close()
        page = editor()
        dialog = recovery(page, "Unsaved changes to revision 2 | a save was interrupted")
        dialog.get_by_role("button", name="Restore 1", exact=True).click()
        expect(page.locator("#document-name")).to_have_value("TEST replayed C")
        with saved_put(page) as sent:
            page.get_by_role("button", name="Save", exact=True).click()
        assert json.loads(sent.value.post_data)["request_id"] == pending["request_id"]
        expect(page.locator("#document-status")).to_contain_text("Revision 3 | Saved")
        assert revision(doc["id"]) == 3
        checks.append("C: a save that never arrived was restored and Save replayed its original request ID once (revision 3)")

        # D. The document changed after the checkpoint: Restore asks first, then loads the draft on the newer revision.
        rename(page, "TEST behind D")
        page.close()
        current = service.get(scope, doc["id"])
        changed = context.request.put(url + doc_path, headers=HEADERS, data={
            "expected_revision": 3, "request_id": "edit_TEST_elsewhere", "design": current["design"] | {"quantity": 3}})
        assert changed.ok, changed.text()
        page = editor()
        dialog = recovery(page, "Unsaved changes to revision 3; the document is now at revision 4")
        prompts.clear()
        dialog.get_by_role("button", name="Restore 1", exact=True).click()
        expect(page.locator("#document-name")).to_have_value("TEST behind D")
        expect(page.locator("#document-status")).to_contain_text("Revision 4 | Unsaved changes")
        assert any("saved document is now at revision 4" in p and "replaces that revision's design" in p for p in prompts), prompts
        assert revision(doc["id"]) == 4
        checks.append("D: a draft behind the saved revision was loaded on revision 4 only after a confirmation; nothing was saved")
        with page.expect_response(lambda r: r.request.method == "DELETE" and "/api/packaging/drafts/" in r.url):
            page.get_by_role("button", name="Reload saved document", exact=True).click()
        assert drafts() == []

        # E. A new document's draft: found again through Open, then discarded after a confirmation.
        page.get_by_role("button", name="New", exact=True).click()
        rename(page, "TEST new E")
        page.close()
        page = editor()
        recovery(page, "New document, not saved")
        page.keyboard.press("Escape")
        page.get_by_role("button", name="Open", exact=True).click()
        page.get_by_role("button", name="Recover unsaved work", exact=True).click()
        dialog = recovery(page, "TEST new E")
        prompts.clear()
        dialog.get_by_role("button", name="Discard draft 1", exact=True).click()
        expect(page.locator("#message")).to_contain_text("Recovery draft discarded.")
        assert drafts() == [] and any("cannot be recovered afterwards" in p for p in prompts), prompts
        assert [d["id"] for d in service.list(scope)] == [doc["id"]]  # The discarded new document was never created.
        page.screenshot(path=str(output / "after-discard.png"), full_page=True)
        checks.append("E: a new document's draft was listed from the Open dialog and discarded after a confirmation")

        # F. A checkpoint that cannot be written is reported; the report clears once a checkpoint is written again.
        drafts_glob = "**/api/packaging/drafts/**"
        page.route(drafts_glob, lambda route: route.abort() if route.request.method == "PUT" else route.fallback())
        with page.expect_event("requestfailed", lambda r: r.method == "PUT" and "/api/packaging/drafts/" in r.url):
            page.locator("#document-name").fill("TEST unrecorded F")
        expect(page.locator("#message")).to_contain_text("Unsaved changes are not checkpointed for recovery")
        expect(page.locator("#document-status")).to_contain_text("Recovery checkpoint failed")
        assert drafts() == []
        page.unroute(drafts_glob)
        rename(page, "TEST recorded F")
        expect(page.locator("#document-status")).not_to_contain_text("Recovery checkpoint failed")
        assert [(d["status"], d["name"]) for d in drafts()] == [("new", "TEST recorded F")]
        checks.append("F: a checkpoint that could not be written was reported (message and header); the report cleared after the next write")
        context.close()
        browser.close()
    return {"passed": not errors and not external, "page_errors": errors, "external_requests": external, "checks": checks}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime" / ("packaging-recovery-ui-" + uuid4().hex[:10]))
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / ".runtime"):
        parser.error("Output must stay in this worktree's .runtime directory")
    output.mkdir(parents=True, exist_ok=False)
    storage = Path(tempfile.mkdtemp(prefix="pk-recovery-ui-"))
    url, server, thread, service, principal = start_pilot(storage)
    try:
        result = verify(url, output, service, principal) | {"output": str(output)}
    finally:
        server.should_exit = True
        thread.join(timeout=20)
        shutil.rmtree(storage, ignore_errors=True)
    (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)
    sys.exit(0 if result["passed"] else 1)
