"""Opt-in Sage mass/provenance acceptance using an already imported real STEP."""
from copy import deepcopy
from pathlib import Path
import argparse
import json
from uuid import uuid4

from playwright.sync_api import sync_playwright, expect


def verify(url, source_document, output):
    output.mkdir(parents=True, exist_ok=False)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--enable-unsafe-swiftshader"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.set_default_timeout(30000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("dialog", lambda dialog: dialog.accept())
        api = url + "/api/packaging/documents"
        original = page.request.get(api+"/"+source_document).json()
        design = deepcopy(original["design"])
        design["name"] = "TEST Sage density " + uuid4().hex[:8]
        design["product"].update(mass_kg=None, mass_basis="unknown", mass_evidence="", mass_calculation=None)
        created = page.request.post(api, data=design, headers={"X-InspectorPro-Request": "packaging"})
        assert created.ok, created.text()
        document = created.json()
        try:
            page.goto(url + "/?packagingPilot=1", wait_until="domcontentloaded", timeout=60000)
            page.locator('[data-tab="training"]').click()
            page.locator("#trainingTypeRibbonTrigger").click()
            page.locator("#trainingTypeRibbonOption-packaging_shipping").click()
            frame = page.frame_locator("#packagingWorkspaceFrame")
            frame.get_by_role("button", name="Open", exact=True).click()
            frame.locator("#document-list > div").filter(has_text=design["name"]).get_by_role("button", name="Open", exact=True).click()
            expect(frame.locator("#document-name")).to_have_value(design["name"])
            page.locator("#rightRailAgent").click()
            expect(page.locator("#agentInput")).to_be_visible()
            page.locator("#agentModelBtn").click()
            page.locator('[data-reasoning-level="medium"]').click()
            prompt = ("The imported STEP is one PMMA rack and straight pusher. All five solids are PMMA. "
                "Use the cited PMMA density from the packaging catalog to estimate its mass from the STEP solid volume. "
                "Exclude magnets and adhesive and keep it labelled an estimate. Apply that mass estimate to this document. "
                "Keep all dimensions, four-pair placements, foam pockets, materials, graphics and unknown carton weights unchanged. "
                "Validate the saved result and give me the draft review PDF link. Do not request carrier rates. Be brief.")
            page.locator("#agentInput").fill(prompt)
            page.screenshot(path=str(output/"before.png"))
            with page.expect_response(lambda r: "/api/agent/chat/v2/stream" in r.url, timeout=30000) as pending:
                page.locator("#agentSendBtn").click()
            response = pending.value
            assert response.status == 200, response.text()
            events = [json.loads(line[6:]) for line in response.text().splitlines() if line.startswith("data: ")]
            terminal = events[-1]
            (output/"terminal.json").write_text(json.dumps(terminal, indent=2), encoding="utf-8")
            assert terminal.get("event") == "response_completed", terminal
            final = terminal["final"]
            evidence = final.get("codex_packaging", {})
            assert evidence.get("mutationOutcome") == "committed", evidence
            assert evidence.get("checkedPackaging") is True, evidence
            assert evidence.get("authMode") == "chatgpt_plan" and evidence.get("apiFallback") is False
            saved = page.request.get(api+"/"+document["id"]).json()
            assert saved["design"]["product"]["mass_basis"] == "estimate"
            expected_mass = original["design"]["product"]["mass_kg"]
            assert abs(saved["design"]["product"]["mass_kg"] - expected_mass) < 1e-9
            for key in ("packages", "constraints", "quantity", "name"):
                assert saved["design"][key] == design[key], key
            for key in ("dimensions_m", "source_id", "source_revision", "appearance"):
                assert saved["design"]["product"][key] == design["product"][key], key
            names = [r["tool"] for r in evidence["verifiedToolCalls"] if r["ok"]]
            assert all(n in names for n in ("inspect_packaging", "packaging_resources", "estimate_packaging_mass", "edit_packaging", "validate_packaging")), names
            expect(frame.locator("#document-name")).to_be_enabled(timeout=15000)
            frame.locator("#command-validation").click()
            expect(frame.locator("#validation-panel")).to_contain_text("4 / 4 products placed")
            page.screenshot(path=str(output/"after.png"))
            frame.get_by_role("button", name="Undo", exact=True).click()
            expect(frame.locator("#document-status")).to_contain_text("Saved")
            assert page.request.get(api+"/"+document["id"]).json()["design"]["product"]["mass_kg"] is None
            frame.get_by_role("button", name="Redo", exact=True).click()
            expect(frame.locator("#document-status")).to_contain_text("Saved")
            assert abs(page.request.get(api+"/"+document["id"]).json()["design"]["product"]["mass_kg"] - expected_mass) < 1e-9
            assert page.request.get(api+"/"+source_document).json() == original
            assert not errors, errors
            result = {"document_id": document["id"], "tools": names, "auth_mode": evidence["authMode"],
                      "api_fallback": False, "source_document_unchanged": True, "undo_redo": True,
                      "response": final["response"], "page_errors": errors}
            (output/"result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps(result, indent=2), flush=True)
        except BaseException:
            page.screenshot(path=str(output/"failure.png"))
            raise
        finally:
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8181")
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not args.live:
        raise ValueError("Live inference requires explicit --live opt-in")
    root = Path(__file__).resolve().parents[1] / ".runtime"
    if not args.output.resolve().is_relative_to(root):
        raise ValueError("Evidence must remain in this isolated worktree")
    verify(args.url.rstrip("/"), args.document_id, args.output)
