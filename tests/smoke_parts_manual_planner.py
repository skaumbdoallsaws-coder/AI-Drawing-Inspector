"""Live read-only browser proof for Sage parts-manual structure proposals."""

from __future__ import annotations

import atexit
import json
from pathlib import Path
import sys

from parts_manual_smoke_support import (
    IsolatedPartsManualServer,
    seed_internal_legacy_section,
)


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / ".runtime" / "parts_manual_planner_smoke"
OUT_DIR.mkdir(parents=True, exist_ok=True)
ASSEMBLY_NUMBER = "tricycle"
PRODUCTION_PLAN_PATH = (
    ROOT / "generated" / "parts_manual" / ASSEMBLY_NUMBER / "manual-plan.json"
)


def run() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed", file=sys.stderr)
        return 2

    production_plan_before = (
        PRODUCTION_PLAN_PATH.read_bytes() if PRODUCTION_PLAN_PATH.is_file() else None
    )
    isolated_server = IsolatedPartsManualServer(ROOT, OUT_DIR, ASSEMBLY_NUMBER)
    isolated_server.start()
    atexit.register(isolated_server.stop)
    app_url = isolated_server.app_url
    report: dict[str, object] = {
        "url": app_url,
        "assemblyNumber": ASSEMBLY_NUMBER,
        "repositoryMode": "isolated_temporary_server",
        "checks": {},
        "browserErrors": [],
    }

    def record(name: str, ok: bool, detail=None) -> None:
        report["checks"][name] = {"ok": bool(ok), "detail": detail}
        print(f"{'PASS' if ok else 'FAIL'} {name}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1720, "height": 1080})
        page.on("pageerror", lambda error: report["browserErrors"].append(str(error)))
        try:
            page.goto(
                f"{app_url}/?assemblyProfile={ASSEMBLY_NUMBER}",
                wait_until="domcontentloaded",
                timeout=90_000,
            )
            page.wait_for_function(
                """assemblyNumber => Boolean(
                    window.__compareDbg
                    && window.__compareDbg.state.partNumber === assemblyNumber
                    && window.__compareDbg.state.activeTab === 'assembly'
                    && window.__compareDbg.state.assyLiveScene
                    && window.__compareDbg.state.assyOccurrenceMeshMap
                )""",
                arg=ASSEMBLY_NUMBER,
                timeout=90_000,
            )
            seeded = seed_internal_legacy_section(
                page.request,
                app_url,
                ASSEMBLY_NUMBER,
            )
            record(
                "isolated_legacy_fixture_seeded",
                len(seeded.get("plan", {}).get("sections", [])) == 1
                and seeded["plan"]["sections"][0].get("name") == "body",
                {"storeRoot": str(isolated_server.store_root)},
            )
            before = page.evaluate(
                """async assemblyNumber => fetch(
                    '/api/parts-manual/' + encodeURIComponent(assemblyNumber)
                ).then(response => response.json())""",
                ASSEMBLY_NUMBER,
            )
            page.evaluate("() => window.__compareDbg.openDocumentationWorkflow()")
            manual = page.locator("#partsManualOverlay")
            manual.wait_for(state="visible", timeout=30_000)
            manual.get_by_role("button", name="Suggest Structure", exact=True).click()
            manual.locator(".manual-plan-proposal-row").first.wait_for(
                state="visible",
                timeout=30_000,
            )
            proposal_state = page.evaluate(
                """() => {
                    const state = window.__compareDbg.state;
                    const proposal = state.partsManualProposal || {};
                    return {
                        summary: proposal.summary || {},
                        names: (proposal.candidates || []).map(value => value.name),
                        statuses: (proposal.candidates || []).map(value => value.status),
                        superseded: proposal.supersededSectionIds || [],
                        candidateSuperseded: (proposal.candidates || [])
                            .flatMap(value => value.supersedesSectionIds || []),
                        selected: Array.from(state.partsManualSelectedCandidateIds || []),
                    };
                }"""
            )
            record(
                "proposal_uses_process_branches",
                proposal_state["summary"].get("readyCount") == 3
                and proposal_state["summary"].get("conflictCount") == 0
                and proposal_state["summary"].get("coveragePercent") == 100
                and proposal_state["names"] == [
                    "Front Steering and Wheel Assembly",
                    "Frame and Seat Assembly",
                    "Rear Wheel and Axle Assembly",
                ],
                proposal_state,
            )
            ready_boxes = manual.locator(
                ".manual-plan-proposal-row:not(.blocked) input[type=checkbox]"
            )
            blocked_boxes = manual.locator(
                ".manual-plan-proposal-row.blocked input[type=checkbox]"
            )
            record(
                "only_ready_candidates_are_selectable",
                ready_boxes.count() == 3
                and all(ready_boxes.nth(index).is_checked() for index in range(3))
                and blocked_boxes.count() == 0,
                {
                    "ready": ready_boxes.count(),
                    "blocked": blocked_boxes.count(),
                },
            )
            record(
                "incomplete_internal_draft_is_identified_for_atomic_replacement",
                len(proposal_state["superseded"]) == 1
                and proposal_state["superseded"][0]
                in proposal_state["candidateSuperseded"],
                proposal_state["superseded"],
            )
            first_ready = manual.locator(
                ".manual-plan-proposal-row:not(.blocked)"
            ).first
            first_ready.get_by_role("button", name="View", exact=True).click()
            isolated = page.evaluate(
                """() => ({
                    isolated: Array.from(window.__compareDbg.state.partsManualIsolatedOccurrenceIds || []).length,
                    expected: (window.__compareDbg.state.partsManualProposal?.candidates || [])
                        .find(value => value.status === 'ready')?.occurrenceIds.length || 0,
                })"""
            )
            record(
                "candidate_can_be_reviewed_in_3d",
                isolated["isolated"] == isolated["expected"] and isolated["isolated"] > 0,
                isolated,
            )
            after = page.evaluate(
                """async assemblyNumber => fetch(
                    '/api/parts-manual/' + encodeURIComponent(assemblyNumber)
                ).then(response => response.json())""",
                ASSEMBLY_NUMBER,
            )
            record(
                "proposal_and_3d_review_are_read_only",
                before["revision"] == after["revision"]
                and before["plan"] == after["plan"],
                {"before": before["revision"], "after": after["revision"]},
            )
            page.screenshot(
                path=str(OUT_DIR / "parts_manual_structure_proposal.png"),
                full_page=False,
            )
            record(
                "no_browser_errors",
                not report["browserErrors"],
                report["browserErrors"],
            )
        finally:
            browser.close()

    isolated_plan = isolated_server.plan_path
    isolated_plan_bytes = isolated_plan.read_bytes() if isolated_plan.is_file() else None
    if isolated_plan_bytes is not None:
        (OUT_DIR / "isolated_manual_plan.json").write_bytes(isolated_plan_bytes)
    isolated_server.stop()
    atexit.unregister(isolated_server.stop)
    production_plan_after = (
        PRODUCTION_PLAN_PATH.read_bytes() if PRODUCTION_PLAN_PATH.is_file() else None
    )
    record(
        "proof_uses_isolated_plan_store",
        isolated_plan_bytes is not None,
    )
    record(
        "production_manual_plan_untouched",
        production_plan_after == production_plan_before,
    )

    report_path = OUT_DIR / "parts_manual_planner.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report: {report_path}")
    return 0 if all(value["ok"] for value in report["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(run())
