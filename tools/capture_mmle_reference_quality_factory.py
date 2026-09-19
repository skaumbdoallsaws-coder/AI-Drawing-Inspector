"""End-to-end browser proof for the MMLE reference-quality prototype factory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "reference_quality"
    / "browser"
)
PROMPT = (
    "Build the trusted MMLE-50D reference-quality factory prototype from its "
    "Facility Planning package. Keep it unsaved and do not release it."
)
AMENDMENT_PROMPT = (
    "Reduce the raw material rack batch to 89. Keep every other area, route, "
    "marking, and resource unchanged. Keep the complete result unsaved."
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _open_facility(page, app_url: str) -> None:
    page.goto(app_url, wait_until="load", timeout=120_000)
    page.wait_for_function(
        """() => (
            window.__inspectorProMainScriptReady === true
            && typeof switchTab === 'function'
            && typeof _trainApplyTrainingTypeDefaults === 'function'
        )""",
        timeout=120_000,
    )
    page.evaluate(
        """() => {
            const previous = trainingState.type;
            trainingState.type = 'facility_layout';
            trainingState.viewportMode = 'facility_layout';
            _trainApplyTrainingTypeDefaults(previous);
            switchTab('training');
        }"""
    )
    page.wait_for_selector(
        "#trainFacilityLayoutAuthoring.ip-flw-root",
        state="visible",
        timeout=120_000,
    )
    page.wait_for_function(
        """() => !!(
            window._trainFacilityLayoutAuthoringApp
            && _trainFacilityLayoutAuthoringApp.workspace
            && !_trainFacilityLayoutAuthoringApp.session.getState().busy
        )""",
        timeout=120_000,
    )
    page.evaluate(
        """() => {
            if (window._setRightDockMode) {
                window._setRightDockMode('agent');
            } else if (window._toggleAgentPanel) {
                window._toggleAgentPanel();
            }
        }"""
    )
    page.wait_for_selector("#agentInput", state="visible", timeout=30_000)
    page.click("#agentChatNewBtn")
    page.evaluate("() => window._selectAgent('deviation-analyst')")
    page.wait_for_function(
        "window._getCurrentAgentKey() === 'deviation-analyst'",
        timeout=15_000,
    )


def _saved_layout(page) -> dict[str, Any]:
    return page.evaluate(
        """async () => {
            const response = await fetch('/api/facility-layouts/site-local/fl-main');
            if (!response.ok) throw new Error(`saved layout ${response.status}`);
            return await response.json();
        }"""
    )


def _draft_snapshot(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
            const state = _trainFacilityLayoutAuthoringApp.session.getState();
            const draft = state.generatedDraft || {};
            return {
                runId: String(draft.runId || ''),
                status: String(draft.status || ''),
                saveEligibility: String(draft.saveEligibility || ''),
                dirty: !!state.dirty,
                zones: (state.layout.zones || []).length,
                routes: (state.layout.routes || []).length,
                placements: (state.layout.placements || []).length,
                floorMarkings: (state.layout.floorMarkings || []).length,
                draftRevision: String(draft.draftLayoutRevision || ''),
                receiptCount: (draft.receiptChain || []).length,
                prototypeMode: draft.prototypeMode === true,
                workflowScope: String(draft.workflowScope || ''),
            };
        }"""
    )


def _program_resource_evidence(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
            const state = _trainFacilityLayoutAuthoringApp.session.getState();
            const layout = state.layout;
            const batchId = 'raw-material-racks';
            const placements = layout.placements || [];
            const belongsToBatch = item => !!(
                item
                && item.metadata
                && item.metadata.batchId === batchId
            );
            return {
                targetCount: placements.filter(belongsToBatch).length,
                zones: JSON.stringify(layout.zones || []),
                routes: JSON.stringify(layout.routes || []),
                floorMarkings: JSON.stringify(layout.floorMarkings || []),
                unrelatedPlacements: JSON.stringify(
                    placements.filter(item => !belongsToBatch(item))
                ),
            };
        }"""
    )


def _plan_evidence(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
            const workspace = _trainFacilityLayoutAuthoringApp.workspace;
            const diagnostics = workspace.topAdapter.getDiagnostics();
            const viewport = document.querySelector('#ip-flw-plan-view');
            const layers = [
                'zones',
                'routes',
                'placements',
                'floor-markings',
            ].map(name => document.querySelector(
                `#ip-flw-plan-view [data-layer="${name}"]`
            )).filter(Boolean);
            const viewportRect = viewport.getBoundingClientRect();
            const rects = layers.map(node => node.getBoundingClientRect())
                .filter(rect => rect.width > 0 && rect.height > 0);
            const content = rects.length ? {
                left: Math.min(...rects.map(rect => rect.left)),
                top: Math.min(...rects.map(rect => rect.top)),
                right: Math.max(...rects.map(rect => rect.right)),
                bottom: Math.max(...rects.map(rect => rect.bottom)),
            } : null;
            const widthRatio = content
                ? (content.right - content.left) / viewportRect.width : 0;
            const heightRatio = content
                ? (content.bottom - content.top) / viewportRect.height : 0;
            return {
                diagnostics,
                occupiedViewportRatio: Math.max(widthRatio, heightRatio),
                occupiedWidthRatio: widthRatio,
                occupiedHeightRatio: heightRatio,
            };
        }"""
    )


def _image_evidence(path: Path) -> dict[str, Any]:
    image = Image.open(path).convert("RGB")
    statistics = ImageStat.Stat(image)
    spread = sum(max(channel) - min(channel) for channel in image.getextrema())
    return {
        "path": str(path),
        "width": image.width,
        "height": image.height,
        "byteLength": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "channelMean": [round(value, 3) for value in statistics.mean],
        "nonBlank": spread > 24 and path.stat().st_size > 25_000,
    }


def _layer_state_evidence(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    layout = str(result.pop("draftLayout"))
    payload = layout.encode("utf-8")
    result["draftLayoutByteLength"] = len(payload)
    result["draftLayoutSha256"] = hashlib.sha256(payload).hexdigest()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default=os.environ.get("APP_URL", "http://127.0.0.1:8141/"),
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    page_errors: list[str] = []
    console_errors: list[str] = []
    failed_requests: list[str] = []
    server_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--enable-unsafe-swiftshader"],
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1,
            service_workers="block",
        )
        context.add_init_script(
            "localStorage.setItem('inspectorpro.theme', 'light');"
        )
        page = context.new_page()
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.on(
            "requestfailed",
            lambda request: failed_requests.append(
                f"{request.method} {request.url}: {request.failure}"
            ),
        )
        page.on(
            "response",
            lambda response: server_errors.append(
                f"{response.status} {response.url}"
            )
            if response.status >= 500
            else None,
        )

        _open_facility(page, args.url)
        saved_before = _saved_layout(page)
        assert saved_before["layout"]["zones"] == []
        saved_before_bytes = _canonical_bytes(saved_before)

        assistant_rows = page.locator(
            "#agentMessages .agent-msg-row.assistant"
        )
        before_count = assistant_rows.count()
        page.fill("#agentInput", PROMPT)
        page.click("#agentSendBtn")
        page.wait_for_function(
            """expected => {
                const app = window._trainFacilityLayoutAuthoringApp;
                if (!app || !app.session) return false;
                const state = app.session.getState();
                const draft = state.generatedDraft;
                return !!(
                    document.querySelectorAll(
                        '#agentMessages .agent-msg-row.assistant'
                    ).length > expected
                    && draft
                    && draft.status === 'complete'
                    && !state.busy
                    && !document.querySelector(
                        '#agentMessages .agent-working-row'
                    )
                );
            }""",
            arg=before_count,
            timeout=600_000,
        )
        page.wait_for_timeout(2_000)
        answer = assistant_rows.last.inner_text()
        answer_normalized = " ".join(answer.split()).lower()
        assert "complete prototype factory is ready" in answer_normalized
        assert "one unsaved draft" in answer_normalized
        assert "45 total areas" in answer_normalized
        assert "827 assets" in answer_normalized
        assert "8 routes" in answer_normalized
        assert "50 markings" in answer_normalized
        assert "use save" in answer_normalized
        assert "undo" in answer_normalized
        draft = _draft_snapshot(page)
        assert draft["status"] == "complete"
        assert draft["dirty"] is True
        assert draft["prototypeMode"] is True
        assert draft["workflowScope"] == "reference_quality_facility_program"
        assert {
            key: draft[key]
            for key in ("zones", "routes", "placements", "floorMarkings")
        } == {
            "zones": 45,
            "routes": 8,
            "placements": 827,
            "floorMarkings": 50,
        }

        page.evaluate(
            """async () => {
                const workspace = _trainFacilityLayoutAuthoringApp.workspace;
                workspace._setViewMode('plan');
                workspace.topAdapter.fitLayout();
            }"""
        )
        page.wait_for_timeout(1_500)
        plan_overview = _plan_evidence(page)
        overview_labels = plan_overview["diagnostics"]["zoneLabels"]
        assert overview_labels["semanticLevel"] == "overview"
        assert len(overview_labels["visibleZoneIds"]) == 6
        assert overview_labels["labelOverlapArea"] <= 1
        assert 0.65 <= plan_overview["occupiedViewportRatio"] <= 0.90, (
            "Plan occupied viewport ratio is "
            f"{plan_overview['occupiedViewportRatio']:.4f}"
        )
        plan_path = output / "01-mmle-reference-quality-plan-and-chat.png"
        page.screenshot(path=str(plan_path), full_page=False)

        page.evaluate(
            """() => {
                const workspace = _trainFacilityLayoutAuthoringApp.workspace;
                const view = document.querySelector('#ip-flw-plan-view');
                const rect = view.getBoundingClientRect();
                workspace.topAdapter.zoomAt({
                    clientX: rect.left + rect.width / 2,
                    clientY: rect.top + rect.height / 2,
                }, 2);
            }"""
        )
        page.wait_for_timeout(750)
        plan_detail = _plan_evidence(page)
        detail_labels = plan_detail["diagnostics"]["zoneLabels"]
        assert detail_labels["semanticLevel"] == "detail"
        assert len(detail_labels["visibleZoneIds"]) > 6
        assert detail_labels["labelOverlapArea"] <= 1
        plan_detail_path = output / "02-mmle-reference-quality-plan-detail.png"
        page.locator("#ip-flw-plan-view").screenshot(path=str(plan_detail_path))

        draft_layout_before_layers = page.evaluate(
            """() => JSON.stringify(
                _trainFacilityLayoutAuthoringApp.session.getState().layout
            )"""
        )
        draft_revision_before_layers = draft["draftRevision"]
        page.click('[data-plan-command="layers"]')
        page.wait_for_selector(
            '.ip-flw-layer-panel:not([hidden])',
            state="visible",
        )
        page.uncheck('[data-facility-layer="routes"]')
        page.wait_for_function(
            """() => {
                const workspace = _trainFacilityLayoutAuthoringApp.workspace;
                const state = workspace.getState();
                return document.querySelectorAll(
                    '#ip-flw-plan-view [data-route-id]'
                ).length === 0
                    && state.layers.visibility.routes === false
                    && workspace.topAdapter.getDiagnostics()
                        .layerVisibility.routes === false
                    && workspace.threeAdapter.getDiagnostics()
                        .layerVisibility.routes === false;
            }"""
        )
        layer_hidden_state = page.evaluate(
            """() => {
                const app = _trainFacilityLayoutAuthoringApp;
                const workspaceState = app.workspace.getState();
                const session = app.session.getState();
                return {
                    workspace: workspaceState.layers,
                    top: app.workspace.topAdapter.getDiagnostics()
                        .layerVisibility,
                    three: app.workspace.threeAdapter.getDiagnostics()
                        .layerVisibility,
                    visiblePlanRoutes: document.querySelectorAll(
                        '#ip-flw-plan-view [data-route-id]'
                    ).length,
                    draftRevision: session.generatedDraft
                        ? session.generatedDraft.draftLayoutRevision : null,
                    draftLayout: JSON.stringify(session.layout),
                };
            }"""
        )
        assert layer_hidden_state["visiblePlanRoutes"] == 0
        assert layer_hidden_state["draftRevision"] == draft_revision_before_layers
        assert layer_hidden_state["draftLayout"] == draft_layout_before_layers
        layer_path = output / "05-mmle-reference-quality-layer-controls.png"
        page.screenshot(path=str(layer_path), full_page=False)
        page.click('[data-layer-action="show-all"]')
        page.wait_for_function(
            """() => {
                const workspace = _trainFacilityLayoutAuthoringApp.workspace;
                const state = workspace.getState();
                return document.querySelectorAll(
                    '#ip-flw-plan-view [data-route-id]'
                ).length === 8
                    && Object.values(state.layers.visibility).every(Boolean)
                    && Object.values(workspace.topAdapter.getDiagnostics()
                        .layerVisibility).every(Boolean)
                    && Object.values(workspace.threeAdapter.getDiagnostics()
                        .layerVisibility).every(Boolean);
            }"""
        )
        layer_restored_state = page.evaluate(
            """() => {
                const app = _trainFacilityLayoutAuthoringApp;
                const workspaceState = app.workspace.getState();
                const session = app.session.getState();
                return {
                    workspace: workspaceState.layers,
                    top: app.workspace.topAdapter.getDiagnostics()
                        .layerVisibility,
                    three: app.workspace.threeAdapter.getDiagnostics()
                        .layerVisibility,
                    visiblePlanRoutes: document.querySelectorAll(
                        '#ip-flw-plan-view [data-route-id]'
                    ).length,
                    draftRevision: session.generatedDraft
                        ? session.generatedDraft.draftLayoutRevision : null,
                    draftLayout: JSON.stringify(session.layout),
                };
            }"""
        )
        assert layer_restored_state["visiblePlanRoutes"] == 8
        assert layer_restored_state["draftRevision"] == draft_revision_before_layers
        assert layer_restored_state["draftLayout"] == draft_layout_before_layers
        page.click('[data-plan-command="layers"]')

        page.evaluate(
            """() => {
                const workspace = _trainFacilityLayoutAuthoringApp.workspace;
                workspace._setViewMode('3d');
                workspace.threeAdapter.isometricView();
                workspace.threeAdapter.fitLayout();
                workspace.threeAdapter.invalidate();
            }"""
        )
        page.wait_for_selector(
            "#ip-flw-three-view:not([hidden]) canvas",
            state="visible",
            timeout=120_000,
        )
        page.wait_for_function(
            """() => {
                const adapter = _trainFacilityLayoutAuthoringApp
                    .workspace.threeAdapter;
                const diagnostics = adapter.getDiagnostics();
                return diagnostics.status === 'ready'
                    && diagnostics.placementCount === 827
                    && diagnostics.floorMarkingCount === 50
                    && diagnostics.pendingLoads === 0;
            }""",
            timeout=180_000,
        )
        page.wait_for_timeout(2_000)
        three_path = output / "03-mmle-reference-quality-3d-and-chat.png"
        page.screenshot(path=str(three_path), full_page=False)
        canvas_path = output / "04-mmle-reference-quality-3d-canvas.png"
        page.locator("#ip-flw-three-view canvas").screenshot(
            path=str(canvas_path)
        )
        three_diagnostics = page.evaluate(
            """() => _trainFacilityLayoutAuthoringApp.workspace
                .threeAdapter.getDiagnostics()"""
        )
        assert three_diagnostics["lastFit"]["mode"] == "layout"
        three_occupancy = three_diagnostics["lastFit"]["viewportOccupancy"]
        assert 0.65 <= three_occupancy["maximumRatio"] <= 0.90

        saved_after = _saved_layout(page)
        assert _canonical_bytes(saved_after) == saved_before_bytes

        resource_before = _program_resource_evidence(page)
        amendment_before_count = assistant_rows.count()
        page.fill("#agentInput", AMENDMENT_PROMPT)
        page.click("#agentSendBtn")
        page.wait_for_function(
            """expected => {
                const app = window._trainFacilityLayoutAuthoringApp;
                if (!app || !app.session) return false;
                const state = app.session.getState();
                return !!(
                    document.querySelectorAll(
                        '#agentMessages .agent-msg-row.assistant'
                    ).length > expected
                    && !state.busy
                    && !document.querySelector(
                        '#agentMessages .agent-working-row'
                    )
                );
            }""",
            arg=amendment_before_count,
            timeout=180_000,
        )
        page.wait_for_timeout(1_000)
        amendment_answer = assistant_rows.last.inner_text()
        amendment_answer_normalized = " ".join(
            amendment_answer.split()
        ).lower()
        assert (
            "raw-material-racks was updated" in amendment_answer_normalized
        ), amendment_answer
        assert "active unsaved prototype" in amendment_answer_normalized, (
            amendment_answer
        )
        assert "protected geometry" in amendment_answer_normalized, (
            amendment_answer
        )
        assert "unrelated placements" in amendment_answer_normalized, (
            amendment_answer
        )
        assert "use save" in amendment_answer_normalized, amendment_answer
        assert "undo" in amendment_answer_normalized, amendment_answer
        page.wait_for_function(
            """value => {
                const state = _trainFacilityLayoutAuthoringApp
                    .session.getState();
                const generated = state.generatedDraft;
                return !!(
                    generated
                    && generated.status === 'complete'
                    && generated.draftLayoutRevision !== value.priorRevision
                    && (generated.receiptChain || []).length
                        === value.priorReceiptCount + 1
                    && (state.layout.placements || []).length === 826
                );
            }""",
            arg={
                "priorRevision": draft["draftRevision"],
                "priorReceiptCount": draft["receiptCount"],
            },
            timeout=30_000,
        )
        amended_draft = _draft_snapshot(page)
        assert amended_draft["placements"] == 826
        assert amended_draft["zones"] == 45
        assert amended_draft["routes"] == 8
        assert amended_draft["floorMarkings"] == 50
        assert amended_draft["receiptCount"] == draft["receiptCount"] + 1
        resource_after = _program_resource_evidence(page)
        assert resource_before["targetCount"] == 90
        assert resource_after["targetCount"] == 89
        for key in (
            "zones",
            "routes",
            "floorMarkings",
            "unrelatedPlacements",
        ):
            assert resource_after[key] == resource_before[key]
        amendment_run = page.evaluate(
            """async () => {
                const app = _trainFacilityLayoutAuthoringApp;
                const state = app.session.getState();
                return await app.transport.getGenerationRun({
                    runId: state.generatedDraft.runId,
                });
            }"""
        )
        assert amendment_run["facilityProgramAmendmentCount"] == 1
        assert amendment_run["facilityProgramRevision"] != (
            amendment_run["baseFacilityProgramRevision"]
        )
        page.evaluate(
            """async () => {
                const workspace = _trainFacilityLayoutAuthoringApp.workspace;
                workspace._setViewMode('plan');
                workspace.topAdapter.fitLayout();
            }"""
        )
        page.wait_for_timeout(1_000)
        amendment_path = (
            output / "06-mmle-reference-quality-local-amendment.png"
        )
        page.screenshot(path=str(amendment_path), full_page=False)
        saved_after_amendment = _saved_layout(page)
        assert _canonical_bytes(saved_after_amendment) == saved_before_bytes

        awaitable = page.evaluate(
            """async () => {
                await _trainFacilityLayoutAuthoringApp.session.undo();
                return true;
            }"""
        )
        assert awaitable is True
        page.wait_for_function(
            """() => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                return !state.busy
                    && !state.generatedDraft
                    && (state.layout.zones || []).length === 0
                    && (state.layout.routes || []).length === 0
                    && (state.layout.placements || []).length === 0
                    && (state.layout.floorMarkings || []).length === 0;
            }""",
            timeout=120_000,
        )
        undo = _draft_snapshot(page)
        saved_final = _saved_layout(page)
        assert _canonical_bytes(saved_final) == saved_before_bytes
        browser.close()

    images = [
        _image_evidence(path)
        for path in (
            plan_path,
            plan_detail_path,
            three_path,
            canvas_path,
            layer_path,
            amendment_path,
        )
    ]
    assert all(item["nonBlank"] for item in images)
    assert page_errors == []
    assert console_errors == []
    assert failed_requests == []
    assert server_errors == []
    report = {
        "schemaVersion": 1,
        "prompt": PROMPT,
        "answer": answer,
        "amendmentPrompt": AMENDMENT_PROMPT,
        "amendmentAnswer": amendment_answer,
        "draft": draft,
        "amendedDraft": amended_draft,
        "facilityProgramAmendment": {
            "count": amendment_run["facilityProgramAmendmentCount"],
            "baseProgramRevision": amendment_run[
                "baseFacilityProgramRevision"
            ],
            "programRevision": amendment_run["facilityProgramRevision"],
            "targetCountBefore": resource_before["targetCount"],
            "targetCountAfter": resource_after["targetCount"],
            "protectedGeometryByteIdentical": all(
                resource_after[key] == resource_before[key]
                for key in ("zones", "routes", "floorMarkings")
            ),
            "unrelatedPlacementsByteIdentical": (
                resource_after["unrelatedPlacements"]
                == resource_before["unrelatedPlacements"]
            ),
        },
        "planOverview": plan_overview,
        "planDetail": plan_detail,
        "layerControlEvidence": {
            "hidden": _layer_state_evidence(layer_hidden_state),
            "restored": _layer_state_evidence(layer_restored_state),
            "draftBytesUnchanged": True,
            "draftRevisionUnchanged": True,
        },
        "threeDiagnostics": {
            "status": three_diagnostics.get("status"),
            "placementCount": three_diagnostics.get("placementCount"),
            "floorMarkingCount": three_diagnostics.get("floorMarkingCount"),
            "pendingLoads": three_diagnostics.get("pendingLoads"),
            "lastFit": three_diagnostics.get("lastFit"),
        },
        "savedLayoutUnchanged": True,
        "undoRestoredBlankBase": (
            undo["zones"] == 0
            and undo["routes"] == 0
            and undo["placements"] == 0
            and undo["floorMarkings"] == 0
        ),
        "images": images,
        "errors": {
            "page": page_errors,
            "console": console_errors,
            "requests": failed_requests,
            "server5xx": server_errors,
        },
    }
    report_path = output.parent / "browser-evidence.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
