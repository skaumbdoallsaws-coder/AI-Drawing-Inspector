"""Capture the FDL R3 browser evidence matrix without saving either layout."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import sys
from uuid import uuid4

from PIL import Image, ImageStat
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.facility_layout.design_brief import create_facility_design_brief
from ai_inspector.facility_layout.design_repository import FacilityDesignRepository


ORIGIN = "http://127.0.0.1:8167"
PRIMARY_LAYOUT_ID = "fl-fdl-material-travel-v1"
REFERENCE_LAYOUT_ID = "fl-reference-fdl-material-travel-v1"
OUTPUT = ROOT / ".runtime" / "fdl-evidence" / "browser-matrix"
VIEWPORTS = (
    (1920, 1080),
    (1440, 900),
    (1366, 768),
)
THEMES = ("light", "dark")
PRIMARY_INTENT = {
    "schema_version": "facility-design-intent-v1",
    "operation": "create_material_travel_brief",
    "source_label": "Output Buffer A",
    "target_label": "Input Buffer B",
    "loaded_trips_per_shift": 24,
    "shift_name": "Day Shift",
    "locked_entity_labels": ["CNC Mill 03", "Inspection Station 02"],
    "movable_placement_labels": ["Output Buffer A", "Input Buffer B"],
    "mutable_route_labels": ["Material Transfer Aisle", "Main Boulevard"],
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def archive_brief(repository: FacilityDesignRepository, brief_id: str) -> None:
    envelope = repository.get_brief("local", "site-local", brief_id)
    current = envelope["brief"]
    if current["semanticBody"]["status"] != "active":
        return
    body = deepcopy(current["semanticBody"])
    body["status"] = "archived"
    source_ref = f"browser-evidence-archive-{uuid4().hex[:16]}"
    archived = create_facility_design_brief(
        brief_id=brief_id,
        semantic_body=body,
        source_turn_refs=[*current["sourceTurnRefs"], source_ref],
        principal_id="fdl-browser-evidence-harness",
        created_at=utc_now(),
        parent_brief_revision=current["briefRevision"],
    )
    repository.advance_brief(
        tenant_id="local",
        site_id="site-local",
        brief=archived,
        expected_brief_revision=current["briefRevision"],
    )


def archive_prior_fixture_briefs(repository: FacilityDesignRepository) -> list[str]:
    archived = []
    for head in repository.list_brief_heads(
        "local", "site-local", layout_id=PRIMARY_LAYOUT_ID, active_only=True
    ):
        archive_brief(repository, head["briefId"])
        archived.append(head["briefId"])
    return archived


def app_url(layout_id: str, build: str) -> str:
    return f"{ORIGIN}/?facilityLayoutId={layout_id}&build={build}"


def api_url(layout_id: str) -> str:
    return f"{ORIGIN}/api/facility-layouts/site-local/{layout_id}"


def open_facility(page: Page, layout_id: str, build: str) -> None:
    page.goto(app_url(layout_id, build), wait_until="load", timeout=120_000)
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
        """layoutId => !!(
            window._trainFacilityLayoutAuthoringApp
            && _trainFacilityLayoutAuthoringApp.workspace
            && !_trainFacilityLayoutAuthoringApp.session.getState().busy
            && _trainFacilityLayoutAuthoringApp.session.getState().layout.layoutId
                === layoutId
        )""",
        arg=layout_id,
        timeout=120_000,
    )
    page.evaluate("() => document.fonts.ready")


def new_context(
    browser: Browser,
    *,
    width: int,
    height: int,
    theme: str,
    report: dict,
    scenario: str,
) -> tuple[BrowserContext, Page]:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        device_scale_factor=1,
        service_workers="block",
    )
    context.add_init_script(
        f"localStorage.setItem('inspectorpro.theme', {json.dumps(theme)});"
    )
    page = context.new_page()
    page.on(
        "pageerror",
        lambda error: report["errors"]["page"].append(f"{scenario}: {error}"),
    )
    def record_console(message) -> None:
        if message.type != "error":
            return
        entry = f"{scenario}: {message.text}"
        expected_transport_error = (
            scenario in {"ambiguity", "stale"}
            and "Failed to load resource" in message.text
            and ("409" in message.text or "422" in message.text)
        )
        if expected_transport_error:
            report["expectedTransportConsole"].append(entry)
        else:
            report["errors"]["console"].append(entry)

    page.on("console", record_console)
    page.on(
        "requestfailed",
        lambda request: report["errors"]["request"].append(
            f"{scenario}: {request.method} {request.url}: {request.failure}"
        ),
    )
    page.on(
        "response",
        lambda response: report["errors"]["http5xx"].append(
            f"{scenario}: {response.status} {response.url}"
        )
        if response.status >= 500
        else None,
    )
    return context, page


def saved_document(context: BrowserContext, layout_id: str) -> dict:
    response = context.request.get(api_url(layout_id))
    assert response.ok, (response.status, response.text())
    return response.json()


def workspace_call(page: Page, method: str, argument: dict | None = None):
    return page.evaluate(
        """async ({method, argument}) => {
            const workspace = _trainFacilityLayoutAuthoringApp.workspace;
            return await workspace[method](argument);
        }""",
        {"method": method, "argument": argument},
    )


def browser_state(page: Page) -> dict:
    return page.evaluate(
        """() => {
            const app = _trainFacilityLayoutAuthoringApp;
            const session = app.session.getState();
            const workspace = app.workspace;
            const design = workspace.designState;
            const frame = app.session.captureDesignEditorFrame();
            return {
                theme: document.documentElement.getAttribute('data-theme'),
                layoutId: session.layout.layoutId,
                baseRevision: session.baseRevision,
                draftRevision: session.revision || session.draftRevision,
                dirty: session.dirty,
                historyCursor: session.historyCursor,
                commandJournalHash: frame.commandJournalHash,
                viewMode: workspace.viewMode,
                panelCollapsed: Boolean(design.collapsed),
                status: design.status,
                statusText: workspace.designPanelTitle
                    ? workspace.designPanelTitle.textContent : '',
                objectiveText: workspace.designObjective
                    && workspace.designObjective.children[1]
                    ? workspace.designObjective.children[1].textContent : '',
                sourceText: workspace.designSource
                    ? workspace.designSource.textContent : '',
                briefId: design.brief && design.brief.briefId,
                briefRevision: design.brief && design.brief.briefRevision,
                proposalCount: design.proposals.length,
                selectedProposalId: design.selectedProposal
                    && design.selectedProposal.proposalId,
                proposalPreviewVisible: Boolean(design.proposalPreviewVisible),
                terminalReason: design.run && design.run.terminalReason,
                objectiveEndpoints: design.run && design.run.objectiveEndpoints,
                attentionKind: design.attentionKind,
                attentionIds: (design.attentionRefs || []).map(item => item.entityId),
                errorCode: design.error && design.error.code,
                candidateChipCount: document.querySelectorAll(
                    '[data-design-attention-entity]'
                ).length,
                transaction: session.designProposalDraft && {
                    transactionId: session.designProposalDraft.transactionId,
                    status: session.designProposalDraft.status,
                },
                three: workspace.threeAdapter
                    ? workspace.threeAdapter.getDiagnostics() : null,
            };
        }"""
    )


def audit_visible_design_text(page: Page) -> dict:
    return page.evaluate(
        """() => {
            const panel = document.querySelector('.ip-flw-design-panel');
            const visible = node => {
                const style = getComputedStyle(node);
                const rect = node.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden'
                    && !node.hidden && rect.width > 0 && rect.height > 0;
            };
            const nodes = panel ? Array.from(panel.querySelectorAll(
                'button, h3, p, strong, span'
            )).filter(visible) : [];
            const overlaps = [];
            for (let leftIndex = 0; leftIndex < nodes.length; leftIndex += 1) {
                for (let rightIndex = leftIndex + 1;
                        rightIndex < nodes.length; rightIndex += 1) {
                    const left = nodes[leftIndex];
                    const right = nodes[rightIndex];
                    if (left.contains(right) || right.contains(left)) continue;
                    const a = left.getBoundingClientRect();
                    const b = right.getBoundingClientRect();
                    const width = Math.min(a.right, b.right) - Math.max(a.left, b.left);
                    const height = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
                    if (width > 0 && height > 0) {
                        overlaps.push({
                            left: left.textContent.trim().slice(0, 80),
                            right: right.textContent.trim().slice(0, 80),
                            area: width * height,
                        });
                    }
                }
            }
            const overflow = nodes.filter(node => (
                node.scrollWidth > node.clientWidth + 1
                || node.scrollHeight > node.clientHeight + 1
            )).map(node => node.textContent.trim().slice(0, 80));
            const root = document.querySelector('#trainFacilityLayoutAuthoring');
            const rootRect = root && root.getBoundingClientRect();
            return {
                visibleTextNodes: nodes.length,
                overlaps,
                overflow,
                rootInsideViewport: Boolean(rootRect
                    && rootRect.left >= 0
                    && rootRect.top >= 0
                    && rootRect.right <= innerWidth + 1
                    && rootRect.bottom <= innerHeight + 1),
            };
        }"""
    )


def pixel_evidence(page: Page, selector: str) -> dict:
    image_bytes = page.locator(selector).screenshot()
    image = Image.open(BytesIO(image_bytes)).convert("RGB").resize((160, 100))
    statistics = ImageStat.Stat(image)
    colors = image.getcolors(maxcolors=image.width * image.height) or []
    return {
        "width": image.width,
        "height": image.height,
        "uniqueColors": len(colors),
        "channelStandardDeviation": [round(value, 3) for value in statistics.stddev],
        "nonBlank": len(colors) >= 16 and max(statistics.stddev) >= 3.0,
    }


def settle_view(page: Page, mode: str, collapsed: bool) -> None:
    page.evaluate(
        """async ({mode, collapsed}) => {
            const workspace = _trainFacilityLayoutAuthoringApp.workspace;
            workspace.designState.collapsed = collapsed;
            workspace._renderDesignPanel();
            workspace._setViewMode(mode);
            if (mode === '3d' && workspace.threeAdapter) {
                workspace.threeAdapter.fit();
                workspace.threeAdapter.invalidate();
            } else if (workspace.controller) {
                if (typeof workspace.controller.fitLayout === 'function') {
                    workspace.controller.fitLayout();
                } else if (typeof workspace.controller.fit === 'function') {
                    workspace.controller.fit();
                }
            }
            await document.fonts.ready;
            await new Promise(resolve => requestAnimationFrame(
                () => requestAnimationFrame(() => requestAnimationFrame(resolve))
            ));
        }""",
        {"mode": mode, "collapsed": collapsed},
    )
    if mode == "3d":
        try:
            page.wait_for_function(
                """() => {
                    const adapter = _trainFacilityLayoutAuthoringApp.workspace.threeAdapter;
                    if (!adapter) return false;
                    const diagnostics = adapter.getDiagnostics();
                    return diagnostics.mounted && diagnostics.pendingLoads === 0
                        && diagnostics.demandRendering.renderedFrames > 0;
                }""",
                timeout=30_000,
            )
        except Exception:
            # Diagnostics captured below make a pending/degraded renderer visible.
            pass
    page.wait_for_timeout(350)


def capture_state(page: Page, name: str, report: dict) -> dict:
    path = OUTPUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=False)
    state = browser_state(page)
    selector = ".ip-flw-three-view" if state["viewMode"] == "3d" else ".ip-flw-plan-view"
    evidence = {
        "screenshot": str(path),
        "state": state,
        "textAudit": audit_visible_design_text(page),
        "pixels": pixel_evidence(page, selector),
    }
    report["captures"][name] = evidence
    assert evidence["textAudit"]["overlaps"] == [], evidence["textAudit"]
    assert evidence["textAudit"]["overflow"] == [], evidence["textAudit"]
    assert evidence["textAudit"]["rootInsideViewport"] is True
    assert evidence["pixels"]["nonBlank"] is True, evidence["pixels"]
    if state["viewMode"] == "3d":
        assert state["three"]["mounted"] is True
        assert state["three"]["contextLost"] is False
        assert state["three"]["proposalPreviewActive"] == state["proposalPreviewVisible"]
    return evidence


def make_unsaved_editor_base(page: Page) -> dict:
    return page.evaluate(
        """async () => {
            const app = _trainFacilityLayoutAuthoringApp;
            const zone = app.session.getState().layout.zones[0];
            const original = zone.label;
            await app.session.editZoneLabel(zone.zoneId, original + ' evidence review');
            await app.session.editZoneLabel(zone.zoneId, original);
            const state = app.session.getState();
            return {
                zoneId: zone.zoneId,
                label: original,
                dirty: state.dirty,
                historyCursor: state.historyCursor,
                frame: app.session.captureDesignEditorFrame(),
            };
        }"""
    )


def create_primary_preview(page: Page) -> dict:
    created = workspace_call(page, "updateDesignBriefFromIntent", PRIMARY_INTENT)
    preview = workspace_call(page, "runDesignPreview", {"mode": "production_sage"})
    state = browser_state(page)
    assert preview["summary"]["status"] == "preview_ready"
    assert len(preview["proposals"]) == 2
    assert state["objectiveText"] == "Output Buffer A to Input Buffer B", state
    assert state["objectiveEndpoints"] == {
        "source": {
            "entityKind": "placement",
            "entityId": "pl-output-buffer-a",
            "connectorId": "material-output",
        },
        "target": {
            "entityKind": "placement",
            "entityId": "pl-input-buffer-b",
            "connectorId": "material-input",
        },
    }
    return {"briefId": created["brief"]["briefId"], "preview": preview, "state": state}


def show_unsaved_editor_source(page: Page) -> dict:
    return page.evaluate(
        """async intent => {
            const app = _trainFacilityLayoutAuthoringApp;
            const workspace = app.workspace;
            const created = await workspace.designTransport.createDesignBrief({
                workspaceId: 'workspace-facility-layout',
                editorFrame: app.session.captureDesignEditorFrame(),
                semanticIntent: intent,
                sourceTurnRef: 'browser-unsaved-editor-source',
            });
            window.__fdlEvidencePriorDesignState = workspace.designState;
            workspace.designState = Object.assign({}, workspace.designState, {
                active: true,
                collapsed: false,
                busy: false,
                status: 'brief_ready',
                error: null,
                brief: created.brief,
                run: null,
                baseline: null,
                proposals: [],
                selectedProposal: null,
                transaction: null,
                attentionKind: null,
                attentionRefs: [],
                proposalPreviewVisible: false,
            });
            workspace._syncDesignProposalPreview(false);
            workspace._renderDesignPanel();
            return {
                briefId: created.brief.briefId,
                briefRevision: created.brief.briefRevision,
                baseKind: created.brief.semanticBody.baseStateRef.baseKind,
            };
        }""",
        PRIMARY_INTENT,
    )


def restore_prior_design_state(page: Page) -> None:
    page.evaluate(
        """() => {
            const workspace = _trainFacilityLayoutAuthoringApp.workspace;
            workspace.designState = window.__fdlEvidencePriorDesignState;
            delete window.__fdlEvidencePriorDesignState;
            workspace._syncDesignProposalPreview(false);
            workspace._renderDesignPanel();
        }"""
    )


def run_matrix_case(
    browser: Browser,
    width: int,
    height: int,
    theme: str,
    report: dict,
    repository: FacilityDesignRepository,
    created_briefs: set[str],
) -> None:
    key = f"matrix-{width}x{height}-{theme}"
    context, page = new_context(
        browser,
        width=width,
        height=height,
        theme=theme,
        report=report,
        scenario=key,
    )
    try:
        open_facility(page, PRIMARY_LAYOUT_ID, key)
        saved_before = saved_document(context, PRIMARY_LAYOUT_ID)
        transaction_case = width == 1920 and height == 1080 and theme == "light"
        initial_frame = page.evaluate(
            "() => _trainFacilityLayoutAuthoringApp.session.captureDesignEditorFrame()"
        )
        result = create_primary_preview(page)
        created_briefs.add(result["briefId"])
        for mode in ("plan", "3d"):
            for collapsed in (False, True):
                settle_view(page, mode, collapsed)
                capture_state(
                    page,
                    f"{key}-{mode}-{'collapsed' if collapsed else 'expanded'}",
                    report,
                )
        if transaction_case:
            settle_view(page, "plan", False)
            workspace_call(page, "applySelectedDesignProposal")
            applied = capture_state(page, "transaction-applied-unsaved-plan", report)
            assert applied["state"]["dirty"] is True
            assert applied["state"]["transaction"] is not None
            settle_view(page, "3d", False)
            capture_state(page, "transaction-applied-unsaved-3d", report)
            unsaved_source = show_unsaved_editor_source(page)
            created_briefs.add(unsaved_source["briefId"])
            assert unsaved_source["baseKind"] == "editor_draft"
            settle_view(page, "plan", False)
            source_plan = capture_state(
                page, "unsaved-editor-source-before-execution-plan", report
            )
            assert source_plan["state"]["sourceText"].startswith(
                "Unsaved editor draft"
            )
            settle_view(page, "3d", False)
            source_three = capture_state(
                page, "unsaved-editor-source-before-execution-3d", report
            )
            assert source_three["state"]["sourceText"].startswith(
                "Unsaved editor draft"
            )
            restore_prior_design_state(page)
            workspace_call(page, "undoDesignProposal")
            settle_view(page, "plan", False)
            undone = capture_state(page, "transaction-exact-undo-plan", report)
            restored_frame = page.evaluate(
                "() => _trainFacilityLayoutAuthoringApp.session.captureDesignEditorFrame()"
            )
            assert restored_frame == initial_frame
            assert undone["state"]["transaction"] is None
            assert undone["state"]["dirty"] is False
            settle_view(page, "3d", False)
            capture_state(page, "transaction-exact-undo-3d", report)
        saved_after = saved_document(context, PRIMARY_LAYOUT_ID)
        assert saved_after == saved_before
        report["matrix"].append(
            {
                "viewport": {"width": width, "height": height},
                "theme": theme,
                "briefId": result["briefId"],
                "sourceKind": "saved_layout",
                "savedRevision": saved_after["revision"],
            }
        )
    finally:
        context.close()
        for brief_id in list(created_briefs):
            try:
                archive_brief(repository, brief_id)
                created_briefs.remove(brief_id)
            except Exception:
                pass


def run_reference_no_improvement(
    browser: Browser,
    report: dict,
    repository: FacilityDesignRepository,
    created_briefs: set[str],
) -> None:
    context, page = new_context(
        browser,
        width=1920,
        height=1080,
        theme="light",
        report=report,
        scenario="reference-no-improvement",
    )
    try:
        open_facility(page, REFERENCE_LAYOUT_ID, "fdl-r3-reference-proof")
        saved_before = saved_document(context, REFERENCE_LAYOUT_ID)
        intent = {
            "schema_version": "facility-design-intent-v1",
            "operation": "create_material_travel_brief",
            "source_label": "pl-584d7293ce7789624fb55c19",
            "target_label": "pl-8c54392d8f2f0ae7730f14c9",
            "loaded_trips_per_shift": 18,
            "shift_name": "Reference Day Shift",
            "locked_entity_labels": [],
            "movable_placement_labels": [
                "pl-584d7293ce7789624fb55c19",
                "pl-8c54392d8f2f0ae7730f14c9",
            ],
            "mutable_route_labels": ["rt-0a31aa446f0e827abbd49e5e"],
        }
        created = workspace_call(page, "updateDesignBriefFromIntent", intent)
        brief_id = created["brief"]["briefId"]
        created_briefs.add(brief_id)
        preview = workspace_call(page, "runDesignPreview", {"mode": "production_sage"})
        state = browser_state(page)
        assert preview["summary"]["terminalReason"] == (
            "facility_design_no_improved_alternative"
        )
        assert preview["proposals"] == []
        assert state["proposalCount"] == 0
        assert state["dirty"] is False
        for mode in ("plan", "3d"):
            settle_view(page, mode, False)
            capture_state(page, f"reference-no-improvement-{mode}", report)
        saved_after = saved_document(context, REFERENCE_LAYOUT_ID)
        assert saved_after == saved_before
        report["reference"] = {
            "briefId": brief_id,
            "layoutRevision": saved_after["revision"],
            "placementCount": len(saved_after["layout"]["placements"]),
            "routeCount": len(saved_after["layout"]["routes"]),
            "markingCount": len(saved_after["layout"]["floorMarkings"]),
            "terminalReason": state["terminalReason"],
            "baseline": preview["summary"]["baseline"],
            "sourceKind": "saved_layout",
            "savedLayoutUnchanged": True,
        }
    finally:
        context.close()
        for brief_id in list(created_briefs):
            try:
                archive_brief(repository, brief_id)
                created_briefs.remove(brief_id)
            except Exception:
                pass


def run_ambiguity(
    browser: Browser,
    report: dict,
) -> None:
    context, page = new_context(
        browser,
        width=1920,
        height=1080,
        theme="dark",
        report=report,
        scenario="ambiguity",
    )
    try:
        open_facility(page, REFERENCE_LAYOUT_ID, "fdl-r3-ambiguity-proof")
        saved_before = saved_document(context, REFERENCE_LAYOUT_ID)
        intent = {
            "schema_version": "facility-design-intent-v1",
            "operation": "create_material_travel_brief",
            "source_label": "CNC Milling Machine",
            "target_label": "pl-8c54392d8f2f0ae7730f14c9",
            "loaded_trips_per_shift": 18,
            "shift_name": "Reference Day Shift",
            "locked_entity_labels": [],
            "movable_placement_labels": [],
            "mutable_route_labels": ["rt-0a31aa446f0e827abbd49e5e"],
        }
        error = page.evaluate(
            """async intent => {
                try {
                    await _trainFacilityLayoutAuthoringApp.workspace
                        .updateDesignBriefFromIntent(intent);
                    return null;
                } catch (caught) {
                    return {
                        code: caught.code,
                        message: caught.message,
                        details: caught.details,
                    };
                }
            }""",
            intent,
        )
        assert error["code"] == "facility_design_referent_ambiguous", error
        state = browser_state(page)
        assert state["attentionKind"] == "ambiguous"
        assert state["candidateChipCount"] == 7
        for mode in ("plan", "3d"):
            settle_view(page, mode, False)
            capture_state(page, f"ambiguity-exact-candidates-{mode}", report)
        assert saved_document(context, REFERENCE_LAYOUT_ID) == saved_before
        report["ambiguity"] = {"error": error, "state": state}
    finally:
        context.close()


def run_stale(
    browser: Browser,
    report: dict,
    repository: FacilityDesignRepository,
    created_briefs: set[str],
) -> None:
    context, page = new_context(
        browser,
        width=1440,
        height=900,
        theme="dark",
        report=report,
        scenario="stale",
    )
    try:
        open_facility(page, PRIMARY_LAYOUT_ID, "fdl-r3-stale-proof")
        saved_before = saved_document(context, PRIMARY_LAYOUT_ID)
        created = workspace_call(page, "updateDesignBriefFromIntent", PRIMARY_INTENT)
        brief = created["brief"]
        created_briefs.add(brief["briefId"])
        external_intent = {
            "schema_version": "facility-design-intent-v1",
            "operation": "set_preference_order",
            "brief_id": brief["briefId"],
            "expected_brief_revision": brief["briefRevision"],
            "preference_metric_ids": [
                "movedPlacementCount",
                "loadedTravelMetersPerShift",
            ],
        }
        page.evaluate(
            """async ({briefId, intent}) => {
                const workspace = _trainFacilityLayoutAuthoringApp.workspace;
                await workspace.designTransport.updateDesignBrief({
                    briefId,
                    semanticIntent: intent,
                    sourceTurnRef: 'external-concurrent-correction',
                });
            }""",
            {"briefId": brief["briefId"], "intent": external_intent},
        )
        error = page.evaluate(
            """async () => {
                try {
                    await _trainFacilityLayoutAuthoringApp.workspace
                        .updateDesignBriefFromIntent({
                            schema_version: 'facility-design-intent-v1',
                            operation: 'add_geometry_locks',
                            target_labels: ['Main Boulevard'],
                        });
                    return null;
                } catch (caught) {
                    return {
                        code: caught.code,
                        message: caught.message,
                        details: caught.details,
                    };
                }
            }"""
        )
        assert error["code"] == "facility_design_brief_revision_conflict", error
        state = browser_state(page)
        assert state["attentionKind"] == "stale"
        assert state["attentionIds"]
        for mode in ("plan", "3d"):
            settle_view(page, mode, False)
            capture_state(page, f"stale-revision-{mode}", report)
        assert saved_document(context, PRIMARY_LAYOUT_ID) == saved_before
        report["stale"] = {"error": error, "state": state}
    finally:
        context.close()
        for brief_id in list(created_briefs):
            try:
                archive_brief(repository, brief_id)
                created_briefs.remove(brief_id)
            except Exception:
                pass


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    repository = FacilityDesignRepository(ROOT / ".runtime" / "facility-layout")
    created_briefs: set[str] = set()
    report = {
        "schemaVersion": "facility-design-browser-evidence-v1",
        "recordedAt": utc_now(),
        "serverOrigin": ORIGIN,
        "deviceScaleFactor": 1,
        "viewports": [
            {"width": width, "height": height} for width, height in VIEWPORTS
        ],
        "themes": list(THEMES),
        "priorTestBriefsArchived": archive_prior_fixture_briefs(repository),
        "matrix": [],
        "captures": {},
        "reference": None,
        "ambiguity": None,
        "stale": None,
        "expectedTransportConsole": [],
        "errors": {"page": [], "console": [], "request": [], "http5xx": []},
    }
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--enable-unsafe-swiftshader"],
            )
            report["browser"] = f"Chromium {browser.version}"
            try:
                for width, height in VIEWPORTS:
                    for theme in THEMES:
                        run_matrix_case(
                            browser,
                            width,
                            height,
                            theme,
                            report,
                            repository,
                            created_briefs,
                        )
                run_reference_no_improvement(
                    browser, report, repository, created_briefs
                )
                run_ambiguity(browser, report)
                run_stale(browser, report, repository, created_briefs)
            finally:
                browser.close()
    finally:
        for brief_id in list(created_briefs):
            try:
                archive_brief(repository, brief_id)
            except Exception:
                pass
        result_path = OUTPUT / "result.json"
        result_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="ascii",
        )
    assert all(not values for values in report["errors"].values()), report["errors"]
    assert len(report["matrix"]) == len(VIEWPORTS) * len(THEMES)
    assert len(report["captures"]) >= 36
    assert report["reference"]["placementCount"] == 827
    print(
        json.dumps(
            {
                "captures": len(report["captures"]),
                "matrixCases": len(report["matrix"]),
                "reference": report["reference"],
                "errors": report["errors"],
                "result": str(OUTPUT / "result.json"),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
