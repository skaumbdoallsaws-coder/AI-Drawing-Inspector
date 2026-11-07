"""Bounded live Sage acceptance on the real straight rack/pusher. Opt-in: --live.

Runs against this worktree's own isolated pilot host (tools/run_packaging_sage_pilot.py with an isolated
profile that has its own ChatGPT sign-in), never a running desktop or another owner's pilot. One Sage turn on
ChatGPT plan usage (no API key, no API fallback). No carrier rates, research, purchase or address.

The STEP is imported locally through the host's API and its mass is the documented density estimate. Sage then
inspects the product, reads the catalog, adds the requested protection, chooses cartons, arranges the four
pairs, saves, validates and links the review PDF, which this script downloads (export). The protection is a
labelled test assumption, not a requirement.

    python tests/verify_packaging_sage_rack_live.py --url http://127.0.0.1:<own port> --output .runtime/<new> --live
    (--dry-run instead of --live does everything up to the prompt and sends nothing.)
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STEP = Path(os.environ.get("PACKAGING_STEP_SAMPLE")
            or r"C:\Users\might\OneDrive\Desktop\Black Acrylic Glued (Step)\full assembly Concept 1- Straight pusher.step")
FOAM = "ethafoam-220-0924"  # The catalog record the prompt asks for; its density is the cited typical value.
HEADERS = {"X-InspectorPro-Request": "packaging"}
PROMPT = ("This packaging document is one straight rack and pusher pair (five PMMA solids from the imported STEP); "
          "quantity 4 is our four-pair sales set. Keep the product, its dimensions, its estimated mass and the quantity "
          "unchanged. Inspect the saved document and read the packaging catalog. Add protection: require 25.4 mm of "
          "Ethafoam 220 on the floor, top and every side, using the catalog's cited density, and record it as a test "
          "assumption that is not drop-tested. From the catalog, choose the cartons that can hold the 508 mm parts with "
          "that lining, propose arrangements with them, apply the best candidate, validate the saved result and give me "
          "the draft review PDF link. Do not request carrier rates or research, and change nothing else. Be brief.")
REQUIRED_TOOLS = ("inspect_packaging", "packaging_resources", "propose_packaging", "edit_packaging", "validate_packaging")
EXPECTED_FINDINGS = {"allowance_unknown", "contents_unconfirmed"}  # Errors this setup leaves on purpose.


def prepare(page, url, output):
    """The TEST document, made locally: the real STEP, the cited PMMA density estimate, four pairs, no packages."""
    api = url + "/api/packaging"
    status = page.request.get(api + "/status").json()
    capabilities = status.get("capabilities", [])
    assert "step_import" in capabilities, capabilities
    catalog = page.request.get(api + "/catalog").json()
    pmma = next(m["material"] for m in catalog["materials"] if m["id"].startswith("pmma"))
    foam = next(m["material"] for m in catalog["materials"] if m["id"] == FOAM)
    imported = page.request.post(api + "/sources/step?name=" + "Straight%20rack%20and%20pusher%20pair",
                                 data=STEP.read_bytes(), headers=HEADERS | {"Content-Type": "application/step"})
    assert imported.ok, imported.text()
    source = imported.json()
    estimate = page.request.post(api + f"/sources/{source['id']}/mass-estimate", headers=HEADERS, data={
        "source_revision": source["source_revision"], "material": pmma,
        "exclusions": "Excludes magnets, adhesive, finish and all packaging."})
    assert estimate.ok, estimate.text()
    product = estimate.json()["product"]
    design = {"name": "TEST live Sage rack x4 " + uuid4().hex[:6], "quantity": 4, "product": product, "packages": [],
              "constraints": {"clearance_m": 0.02, "gap_m": 0.01, "allowed_orientations": [0, 1, 2, 3, 4, 5],
                              "contents": "unconfirmed"}}
    created = page.request.post(api + "/documents", headers=HEADERS, data=design)
    assert created.ok, created.text()
    document = created.json()
    (output / "prepared.json").write_text(json.dumps({"document_id": document["id"], "revision": document["revision"],
                                                      "product": product, "foam": foam}, indent=2), encoding="utf-8")
    return document, foam


def verify(url, output, *, dry_run=False):
    errors, started = [], time.monotonic()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--enable-unsafe-swiftshader"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.set_default_timeout(30000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("dialog", lambda dialog: dialog.accept())
        try:
            document, foam = prepare(page, url, output)
            design = document["design"]
            page.goto(url + "/?packagingPilot=1", wait_until="domcontentloaded", timeout=60000)
            page.locator('[data-tab="training"]').click()
            page.locator("#trainingTypeRibbonTrigger").click()
            page.locator("#trainingTypeRibbonOption-packaging_shipping").click()
            frame = page.frame_locator("#packagingWorkspaceFrame")
            page.get_by_role("button", name="Document packaging commands", exact=True).click()
            page.locator("#packaging-menu-open").click()
            frame.locator("#document-list .document-row").filter(has_text=design["name"]).get_by_role("button", name="Open", exact=True).click()
            expect(frame.locator("#document-name")).to_have_value(design["name"])
            page.locator("#rightRailAgent").click()
            expect(page.locator("#agentInput")).to_be_visible()
            page.locator("#agentModelBtn").click()
            page.locator('[data-reasoning-level="medium"]').click()
            page.locator("#agentInput").fill(PROMPT)
            page.screenshot(path=str(output / "before.png"))
            if dry_run:  # Everything up to the turn; nothing is sent.
                result = {"dry_run": True, "document_id": document["id"], "page_errors": errors}
                (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
                print(json.dumps(result), flush=True)
                assert not errors, errors
                return
            status = page.request.get(url + "/api/packaging/status").json()
            assert "sage_chat_execution" in status.get("capabilities", []), status["capabilities"]
            turn = time.monotonic()
            with page.expect_response(lambda r: "/api/agent/chat/v2/stream" in r.url, timeout=60000) as pending:
                page.locator("#agentSendBtn").click()  # The only prompt this script sends.
            response = pending.value
            assert response.status == 200, response.text()
            events = [json.loads(line[6:]) for line in response.text().splitlines() if line.startswith("data: ")]
            turn_seconds = round(time.monotonic() - turn, 1)
            terminal = events[-1]
            (output / "terminal.json").write_text(json.dumps(terminal, indent=2), encoding="utf-8")
            assert terminal.get("event") == "response_completed", terminal
            final = terminal["final"]
            evidence = final.get("codex_packaging", {})
            assert evidence.get("authMode") == "chatgpt_plan" and evidence.get("apiFallback") is False, evidence
            assert evidence.get("mutationOutcome") == "committed" and evidence.get("checkedPackaging") is True, evidence
            calls = evidence.get("verifiedToolCalls", [])
            names = [c["tool"] for c in calls if c.get("ok")]
            assert all(name in names for name in REQUIRED_TOOLS), names

            saved = page.request.get(f"{url}/api/packaging/documents/{document['id']}").json()
            new = saved["design"]
            assert saved["revision"] > document["revision"]
            assert new["quantity"] == 4 and new["name"] == design["name"]
            for key in ("dimensions_m", "source_id", "source_revision", "mass_kg", "mass_basis", "mass_calculation"):
                assert new["product"][key] == design["product"][key], key  # Product, size and estimate unchanged.
            cushion = new["constraints"].get("cushion") or {}
            assert all(abs(cushion.get(k, 0) - 0.0254) < 1e-4 for k in ("floor_m", "top_m", "sides_m")), cushion
            assert cushion["material"]["density_kg_m3"] == foam["density_kg_m3"], (cushion, foam)
            assert cushion["material"]["name"] == foam["name"], (cushion, foam)
            assert new["packages"] and all(package["inserts"] for package in new["packages"]), new["packages"]
            assessment = saved["assessment"]
            assert assessment["placed_quantity"] == 4, assessment["placed_quantity"]
            errors_found = {f["code"] for f in assessment["findings"] if f["severity"] == "error"}
            assert errors_found <= EXPECTED_FINDINGS, errors_found
            assert assessment["total_gross_kg"] is None  # The allowance is unknown; no weight is invented.

            report = page.request.get(f"{url}/api/packaging/documents/{document['id']}/report.pdf?revision={saved['revision']}")
            assert report.ok and report.body()[:4] == b"%PDF", report.status
            (output / "review.pdf").write_bytes(report.body())
            assert "report.pdf" in final.get("response", ""), "The answer does not link the review PDF."
            expect(frame.locator("#document-name")).to_be_enabled(timeout=30000)
            page.screenshot(path=str(output / "after.png"))
            assert not errors, errors
            result = {"passed": True, "document_id": document["id"], "saved_revision": saved["revision"],
                      "tools": names, "tool_calls": len(calls), "turn_seconds": turn_seconds,
                      "total_seconds": round(time.monotonic() - started, 1), "auth_mode": evidence["authMode"],
                      "api_fallback": False, "cartons": [p["carton"]["name"] for p in new["packages"]],
                      "cushion_evidence": cushion.get("evidence"), "findings": sorted(f["code"] for f in assessment["findings"]),
                      "packages": assessment["packages"], "response": final.get("response"), "page_errors": errors}
            (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps(result, indent=2), flush=True)
        except BaseException:
            page.screenshot(path=str(output / "failure.png"))
            raise
        finally:
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="This worktree's own pilot host, e.g. http://127.0.0.1:8493")
    parser.add_argument("--output", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true", help="Send the one Sage prompt (ChatGPT plan usage)")
    mode.add_argument("--dry-run", action="store_true", help="Everything up to the prompt; nothing is sent")
    args = parser.parse_args()
    host = urlsplit(args.url)
    if host.scheme != "http" or host.hostname != "127.0.0.1" or host.port in (None, 8181):
        raise SystemExit("Use this worktree's own loopback pilot host; port 8181 is another owner's pilot")
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / ".runtime"):
        raise SystemExit("Evidence must remain in this worktree's .runtime directory")
    if not STEP.is_file():
        raise SystemExit("The real rack/pusher STEP is not on this computer; nothing was run")
    output.mkdir(parents=True, exist_ok=False)
    verify(args.url.rstrip("/"), output, dry_run=args.dry_run)
