"""Measure FDL latency through rendered Sage chat, including interpretation."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import platform
import sys
import time
from uuid import uuid4

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.facility_layout.design_brief import (
    create_facility_design_brief,
)
from ai_inspector.facility_layout.design_repository import (
    FacilityDesignRepository,
)


DEFAULT_URL = (
    "http://127.0.0.1:8167/"
    "?facilityLayoutId=fl-fdl-generic-material-travel-v6"
    "&build=fdl-r7-chat-benchmark"
)
DEFAULT_OUTPUT = (
    ROOT / ".runtime" / "fdl-evidence" / "fdl-chat-performance.json"
)
MEASURED_RUNS = 20
LAYOUT_ID = "fl-fdl-generic-material-travel-v6"
INITIAL_PROMPT = (
    "Reduce loaded material travel from Machining Output FIFO to Inspection "
    "Input FIFO. Keep CNC Mill 03 and Inspection Station 02 fixed. You may "
    "move Output Buffer A and Input Buffer B, and you may reroute Material "
    "Transfer Aisle, Main Boulevard, and Input Approach Aisle. Use 24 loaded "
    "trips per Day Shift. "
    "Show alternatives, but do not apply or save anything."
)
CORRECTION_PROMPT = (
    "Keep the current Main Boulevard fixed too."
)


def nearest_rank(values: list[float], percentile: int) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil((percentile / 100) * len(ordered)))
    return ordered[rank - 1]


def open_facility(page, url: str) -> None:
    page.goto(url, wait_until="load", timeout=120_000)
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
    page.wait_for_function(
        """expected => !!(
            window._trainFacilityLayoutAuthoringApp
            && _trainFacilityLayoutAuthoringApp.workspace
            && !_trainFacilityLayoutAuthoringApp.session.getState().busy
            && _trainFacilityLayoutAuthoringApp.session.getState().layout.layoutId
                === expected
        )""",
        arg=LAYOUT_ID,
        timeout=120_000,
    )
    page.evaluate("() => document.fonts.ready")
    page.evaluate(
        """() => {
            if (window._setRightDockMode) window._setRightDockMode('agent');
            else if (window._toggleAgentPanel) window._toggleAgentPanel();
        }"""
    )
    page.wait_for_selector("#agentInput", state="visible", timeout=30_000)
    page.click("#agentChatNewBtn")
    page.wait_for_function(
        """() => {
            const memory = document.querySelector('#agentMemoryStatus');
            const rows = document.querySelectorAll(
                '#agentMessages .agent-msg-row'
            );
            return !!(
                memory
                && ['ready', 'off', 'unavailable'].includes(
                    memory.dataset.state
                )
                && rows.length === 0
            );
        }""",
        timeout=30_000,
    )
    page.evaluate("() => window._selectAgent('deviation-analyst')")
    page.wait_for_function(
        "window._getCurrentAgentKey() === 'deviation-analyst'",
        timeout=15_000,
    )


def archive_benchmark_brief(brief_id: str) -> None:
    repository = FacilityDesignRepository(ROOT / ".runtime" / "facility-layout")
    current = repository.get_brief("local", "site-local", brief_id)["brief"]
    body = deepcopy(current["semanticBody"])
    body["status"] = "archived"
    source_ref = f"benchmark-archive-{uuid4().hex[:16]}"
    archived = create_facility_design_brief(
        brief_id=brief_id,
        semantic_body=body,
        source_turn_refs=[*current["sourceTurnRefs"], source_ref],
        principal_id="fdl-benchmark-harness",
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        parent_brief_revision=current["briefRevision"],
    )
    repository.advance_brief(
        tenant_id="local",
        site_id="site-local",
        brief=archived,
        expected_brief_revision=current["briefRevision"],
    )


def _send(page, prompt: str) -> float:
    started = time.perf_counter()
    page.fill("#agentInput", prompt)
    page.click("#agentSendBtn")
    return started


def _wait_for_chat_idle(page, prior_assistant_count: int) -> str:
    page.wait_for_function(
        """count => {
            const rows = document.querySelectorAll(
                '#agentMessages .agent-msg-row.assistant'
            );
            return !!(
                rows.length > count
                && !document.querySelector(
                    '#agentMessages .agent-working-row'
                )
                && !document.querySelector(
                    '#agentMessages .agent-stream-pending'
                )
            );
        }""",
        arg=prior_assistant_count,
        timeout=300_000,
    )
    rows = page.locator("#agentMessages .agent-msg-row.assistant")
    if rows.count() <= prior_assistant_count:
        return ""
    return rows.last.inner_text()


def _provider_failure_after(page, prior_assistant_count: int) -> str:
    return page.evaluate(
        """count => {
            const rows = Array.from(document.querySelectorAll(
                '#agentMessages .agent-msg-row.assistant'
            ));
            if (rows.length <= count) return '';
            const row = rows[rows.length - 1];
            const message = row.querySelector('.agent-msg');
            const text = (message ? message.textContent : row.textContent).trim();
            return /could not (generate a response|respond because)/i.test(text)
                ? text : '';
        }""",
        prior_assistant_count,
    )


def _latest_assistant_tool_source(page) -> str:
    return page.evaluate(
        """() => {
            const runtime = window.__agentChatStreamV1;
            return runtime
                && typeof runtime.latestAssistantToolSource === 'function'
                ? runtime.latestAssistantToolSource() : '';
        }"""
    )


def measure_once(page) -> dict:
    workspace_state = page.evaluate(
        """() => ({
            briefRevision: _trainFacilityLayoutAuthoringApp.workspace
                .designState.brief?.briefRevision || null,
            previewVisibleAt: _trainFacilityLayoutAuthoringApp.workspace
                .designState.lastPreviewVisibleAt || 0,
            assistantCount: document.querySelectorAll(
                '#agentMessages .agent-msg-row.assistant'
            ).length,
        })"""
    )
    initial_start = _send(page, INITIAL_PROMPT)
    page.wait_for_function(
        """prior => {
            const app = window._trainFacilityLayoutAuthoringApp;
            const design = app && app.workspace && app.workspace.designState;
            const rows = Array.from(document.querySelectorAll(
                '#agentMessages .agent-msg-row.assistant'
            ));
            const last = rows.length ? rows[rows.length - 1] : null;
            const lastMessage = last && last.querySelector('.agent-msg');
            const failed = !!(
                rows.length > prior.assistantCount
                && last
                && /could not (generate a response|respond because)/i.test(
                    lastMessage ? lastMessage.textContent : last.textContent
                )
            );
            const objective = app && app.workspace
                && app.workspace.designObjective;
            const targetRefs = design && design.brief
                && design.brief.semanticBody
                && design.brief.semanticBody.objective
                && design.brief.semanticBody.objective.targetRefs || [];
            return failed || !!(
                design && design.brief
                && design.brief.briefRevision !== prior.briefRevision
                && targetRefs.length >= 2
                && objective
                && objective.getBoundingClientRect().height > 0
                && objective.textContent.trim().length > 0
            );
        }""",
        arg={
            "briefRevision": workspace_state["briefRevision"],
            "assistantCount": workspace_state["assistantCount"],
        },
        timeout=300_000,
    )
    failure = _provider_failure_after(
        page, workspace_state["assistantCount"]
    )
    if failure:
        raise RuntimeError(f"Sage provider failure: {failure}")
    targets_visible = time.perf_counter()
    target_text = page.evaluate(
        "() => _trainFacilityLayoutAuthoringApp.workspace.designObjective.textContent.trim()"
    )
    print("  initial targets visible", flush=True)
    page.wait_for_function(
        """prior => {
            const design = _trainFacilityLayoutAuthoringApp.workspace.designState;
            return !!(
                !design.busy
                && design.lastPreviewVisibleAt > prior
                && design.proposals.length > 0
            );
        }""",
        arg=workspace_state["previewVisibleAt"],
        timeout=300_000,
    )
    first_visible = time.perf_counter()
    print("  initial proposal visible", flush=True)
    initial_answer = _wait_for_chat_idle(
        page, workspace_state["assistantCount"]
    )
    initial_tool_source = _latest_assistant_tool_source(page)
    if initial_tool_source != "facility_design_deterministic_create":
        raise RuntimeError(
            "Exact initial intent did not use the deterministic Sage path: "
            + (initial_tool_source or "missing tool source")
        )
    print("  initial response committed", flush=True)
    initial = page.evaluate(
        """() => {
            const design = _trainFacilityLayoutAuthoringApp.workspace.designState;
            return {
                briefId: design.brief.briefId,
                briefRevision: design.brief.briefRevision,
                previewVisibleAt: design.lastPreviewVisibleAt,
                previewStartedAt: design.lastPreviewStartedAt,
                proposalCount: design.proposals.length,
                assistantCount: document.querySelectorAll(
                    '#agentMessages .agent-msg-row.assistant'
                ).length,
            };
        }"""
    )

    correction_start = _send(page, CORRECTION_PROMPT)
    print("  correction submitted", flush=True)
    page.wait_for_function(
        """prior => {
            const design = _trainFacilityLayoutAuthoringApp.workspace.designState;
            const rows = Array.from(document.querySelectorAll(
                '#agentMessages .agent-msg-row.assistant'
            ));
            const last = rows.length ? rows[rows.length - 1] : null;
            const lastMessage = last && last.querySelector('.agent-msg');
            const failed = !!(
                rows.length > prior.assistantCount
                && last
                && /could not (generate a response|respond because)/i.test(
                    lastMessage ? lastMessage.textContent : last.textContent
                )
            );
            return failed || !!(
                design.brief
                && design.brief.briefRevision !== prior.briefRevision
                && !design.busy
                && design.lastPreviewVisibleAt > prior.previewVisibleAt
                && design.proposals.length > 0
            );
        }""",
        arg={
            "briefRevision": initial["briefRevision"],
            "previewVisibleAt": initial["previewVisibleAt"],
            "assistantCount": initial["assistantCount"],
        },
        timeout=300_000,
    )
    failure = _provider_failure_after(page, initial["assistantCount"])
    if failure:
        raise RuntimeError(f"Sage provider failure: {failure}")
    correction_visible = time.perf_counter()
    print("  corrected proposal visible", flush=True)
    corrected_answer = _wait_for_chat_idle(page, initial["assistantCount"])
    correction_tool_source = _latest_assistant_tool_source(page)
    if correction_tool_source != "facility_design_deterministic_correction":
        raise RuntimeError(
            "Exact correction did not use the deterministic Sage path: "
            + (correction_tool_source or "missing tool source")
        )
    print("  corrected response committed", flush=True)
    corrected = page.evaluate(
        """() => {
            const app = _trainFacilityLayoutAuthoringApp;
            const design = app.workspace.designState;
            const session = app.session.getState();
            return {
                proposalCount: design.proposals.length,
                previewVisibleAt: design.lastPreviewVisibleAt,
                previewStartedAt: design.lastPreviewStartedAt,
                dirty: session.dirty,
                baseRevision: session.baseRevision,
                draftRevision: session.revision || session.draftRevision,
            };
        }"""
    )
    combined_answer = (initial_answer + corrected_answer).casefold()
    if (
        "could not generate a response" in combined_answer
        or "could not respond because" in combined_answer
    ):
        raise RuntimeError("Sage returned a provider failure during benchmark")
    return {
        "inputPath": "rendered_sage_chat",
        "initialToolSource": initial_tool_source,
        "correctionToolSource": correction_tool_source,
        "submissionToTargetsMs": (targets_visible - initial_start) * 1000,
        "firstUsefulPreviewMs": (first_visible - initial_start) * 1000,
        "deterministicFirstPreviewMs": (
            initial["previewVisibleAt"] - initial["previewStartedAt"]
        ),
        "deterministicCorrectionPreviewMs": (
            corrected["previewVisibleAt"] - corrected["previewStartedAt"]
        ),
        "correctionToPreviewMs": (
            correction_visible - correction_start
        ) * 1000,
        "initialProposalCount": initial["proposalCount"],
        "correctedProposalCount": corrected["proposalCount"],
        "briefId": initial["briefId"],
        "renderedTargetText": target_text,
        "dirty": corrected["dirty"],
        "baseRevision": corrected["baseRevision"],
        "draftRevision": corrected["draftRevision"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=os.environ.get("APP_URL", DEFAULT_URL))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--runs", type=int, default=MEASURED_RUNS)
    arguments = parser.parse_args()
    if arguments.runs < 1:
        raise SystemExit("--runs must be positive")
    errors: dict[str, list[str]] = {
        "page": [],
        "console": [],
        "request": [],
        "http5xx": [],
        "provider": [],
    }
    samples = []
    benchmark_error = None
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
        page = context.new_page()
        page.on("pageerror", lambda error: errors["page"].append(str(error)))
        page.on(
            "console",
            lambda message: errors["console"].append(message.text)
            if message.type == "error"
            else None,
        )
        page.on(
            "requestfailed",
            lambda request: errors["request"].append(
                f"{request.method} {request.url}: {request.failure}"
            ),
        )
        page.on(
            "response",
            lambda response: errors["http5xx"].append(
                f"{response.status} {response.url}"
            )
            if response.status >= 500
            else None,
        )
        try:
            open_facility(page, arguments.url)
            print("FDL chat benchmark: warmup", flush=True)
            warmup = measure_once(page)  # Discard one warmup.
            archive_benchmark_brief(warmup["briefId"])
            for index in range(arguments.runs):
                print(
                    f"FDL chat benchmark: measured run {index + 1}/"
                    f"{arguments.runs}",
                    flush=True,
                )
                open_facility(page, arguments.url)
                sample = measure_once(page)
                samples.append(sample)
                archive_benchmark_brief(sample["briefId"])
        except Exception as error:
            benchmark_error = str(error)
            errors["provider"].append(benchmark_error)
        browser_version = browser.version
        browser.close()

    if benchmark_error:
        artifact = {
            "schemaVersion": "facility-design-chat-performance-evidence-v2",
            "recordedAt": datetime.now(timezone.utc).isoformat().replace(
                "+00:00", "Z"
            ),
            "status": "blocked",
            "reason": benchmark_error,
            "protocol": {
                "warmupRuns": 1,
                "measuredRunsRequested": arguments.runs,
                "measuredRunsCompleted": len(samples),
                "inputPath": "rendered Sage chat through #agentInput",
                "url": arguments.url,
            },
            "errors": errors,
        }
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(artifact, indent=2, sort_keys=True) + "\n",
            encoding="ascii",
        )
        print(json.dumps(artifact))
        raise SystemExit(2)

    metrics = {
        "submissionToTargetsP95Ms": nearest_rank(
            [item["submissionToTargetsMs"] for item in samples], 95
        ),
        "firstUsefulPreviewP95Ms": nearest_rank(
            [item["firstUsefulPreviewMs"] for item in samples], 95
        ),
        "deterministicFirstPreviewP95Ms": nearest_rank(
            [item["deterministicFirstPreviewMs"] for item in samples], 95
        ),
        "deterministicCorrectionPreviewP95Ms": nearest_rank(
            [item["deterministicCorrectionPreviewMs"] for item in samples], 95
        ),
        "correctionToUpdatedPreviewP95Ms": nearest_rank(
            [item["correctionToPreviewMs"] for item in samples], 95
        ),
    }
    thresholds = {
        "submissionToTargetsP95Ms": 10_000,
        "firstUsefulPreviewP95Ms": 30_000,
        "deterministicFirstPreviewP95Ms": 15_000,
        "deterministicCorrectionPreviewP95Ms": 10_000,
        "correctionToUpdatedPreviewP95Ms": 20_000,
    }
    gates = {
        name: metrics[name] <= limit
        for name, limit in thresholds.items()
    }
    artifact = {
        "schemaVersion": "facility-design-chat-performance-evidence-v2",
        "recordedAt": datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "protocol": {
            "warmupRuns": 1,
            "measuredRuns": arguments.runs,
            "percentile": "nearest-rank-p95",
            "inputPath": "rendered Sage chat through #agentInput",
            "requiredInitialToolSource": "facility_design_deterministic_create",
            "requiredCorrectionToolSource": (
                "facility_design_deterministic_correction"
            ),
            "viewport": {"width": 1920, "height": 1080},
            "deviceScaleFactor": 1,
            "url": arguments.url,
        },
        "machine": {
            "name": "Dell 15 DC15250",
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logicalCores": os.cpu_count(),
            "python": platform.python_version(),
            "browser": f"Chromium {browser_version}",
        },
        "metrics": metrics,
        "thresholdsMs": thresholds,
        "gates": gates,
        "samples": samples,
        "errors": errors,
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    print(json.dumps({"metrics": metrics, "gates": gates, "errors": errors}))
    if not all(gates.values()) or any(errors.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
