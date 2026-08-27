"""Build the machine-readable KF0 Facility Layout baseline package.

The package freezes the current command, tool, feature, evaluation, budget,
and test surfaces without treating stale release evidence as a passing test.
It is intentionally a development artifact builder, not a release verifier.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterable, Mapping
import xml.etree.ElementTree as ET


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"
RUNTIME_ROOT = REPO_ROOT / ".runtime" / "kf0"
PLAN_PATH = DOCS_ROOT / "facility-layout-sage-knowledge-foundation-plan.md"
MANIFEST_PATH = DOCS_ROOT / "facility-layout-kf0-baseline-manifest.json"
CROSSWALK_PATH = DOCS_ROOT / "facility-layout-kf0-command-crosswalk.json"
DECISIONS_PATH = DOCS_ROOT / "facility-layout-kf0-decisions.json"
GAPS_PATH = DOCS_ROOT / "facility-layout-kf0-capability-gaps.json"
REPORT_PATH = DOCS_ROOT / "facility-layout-kf0-baseline-report.md"
BROWSER_RESULT_PATH = RUNTIME_ROOT / "browser-tests.json"
FACILITY_JUNIT_PATH = RUNTIME_ROOT / "facility-python.xml"
AGENT_JUNIT_PATH = RUNTIME_ROOT / "agent-python.xml"
INTELLIGENCE_PATH = RUNTIME_ROOT / "intelligence-evaluation.json"
SAVED_LAYOUT_SMOKE_PATH = RUNTIME_ROOT / "saved-layout-smoke.json"

SCHEMA_VERSION = "facility-layout-kf0-baseline-v1"
BYTES4_ESTIMATOR = "bytes4-v1"
FACILITY_DEFAULT_MODEL = "claude-sonnet-4-5-20250929"

NON_RIBBON_SURFACES: dict[str, str] = {
    "assets": "asset_browser",
    "fit-layout": "plan_and_3d_navigation",
    "top-view": "plan_and_3d_navigation",
    "orbit": "3d_navigation",
    "walkthrough": "3d_navigation",
    "drone": "3d_navigation",
    "record": "3d_capture",
}

SESSION_HANDLERS: dict[str, list[str]] = {
    "rectangle-zone": ["FacilitySession.createRectangleZone"],
    "polygon-zone": ["FacilitySession.createPolygonZone"],
    "bulk-zones": ["FacilitySession.createZones"],
    "aisle": ["FacilitySession.createAisle"],
    "floor-marking": ["FacilitySession.createFloorMarking"],
    "rotate": ["FacilitySession.rotateSelected90"],
    "duplicate": ["FacilitySession.duplicateSelected"],
    "delete": ["FacilitySession.deleteSelected"],
    "clear-all": ["FacilitySession.clearLayout"],
    "lock": ["FacilitySession.lockSelected", "FacilitySession.unlockSelected"],
    "align": ["FacilitySession.movePlacements"],
    "distribute": ["FacilitySession.movePlacements"],
    "relative": ["FacilitySession.movePlacements"],
    "distance": ["FacilitySession.movePlacements"],
    "offset": ["FacilitySession.movePlacements", "FacilitySession.duplicatePlacements"],
    "linear-pattern": ["FacilitySession.applyPattern"],
    "circular-pattern": ["FacilitySession.applyPattern"],
    "perimeter-pattern": ["FacilitySession.applyPattern"],
    "cell-layout": ["FacilitySession.applyPattern"],
    "create-cell-group": ["FacilitySession.createCellGroup"],
    "ungroup-cell": ["FacilitySession.ungroupCell"],
    "vertical-stack": ["FacilitySession.applyPattern"],
    "surface-stack": ["FacilitySession.applyPattern"],
    "mirror": ["FacilitySession.applyPattern"],
    "swap": ["FacilitySession.applyPattern"],
    "undo": ["FacilitySession.undo"],
    "redo": ["FacilitySession.redo"],
    "auto-arrange": ["FacilitySession.requestLayoutProposal"],
    "save": ["FacilitySession.save"],
}

KERNEL_HANDLERS: dict[str, list[str]] = {
    "rectangle-zone": ["add_zone"],
    "polygon-zone": ["add_zone"],
    "bulk-zones": ["add_zone"],
    "aisle": ["add_aisle"],
    "floor-marking": ["add_floor_marking"],
    "rotate": ["rotate_placement"],
    "duplicate": ["duplicate_placement", "add_zone", "add_floor_marking"],
    "delete": ["delete_placement", "delete_zone", "delete_floor_marking"],
    "clear-all": ["clear_layout_contents"],
    "lock": ["set_position_mode"],
    "align": ["move_placement"],
    "distribute": ["move_placement"],
    "relative": ["move_placement"],
    "distance": ["move_placement"],
    "offset": ["move_placement", "duplicate_placement"],
    "linear-pattern": ["duplicate_placement", "move_placement"],
    "circular-pattern": ["duplicate_placement", "move_placement"],
    "perimeter-pattern": ["duplicate_placement", "move_placement"],
    "cell-layout": ["move_placement"],
    "create-cell-group": ["add_zone"],
    "ungroup-cell": ["delete_zone"],
    "vertical-stack": ["duplicate_placement", "set_snap_relationship"],
    "surface-stack": ["move_placement", "set_snap_relationship"],
    "mirror": ["duplicate_placement", "move_placement"],
    "swap": ["move_placement"],
    "undo": ["replay_inverse_draft_batch"],
    "redo": ["replay_draft_batch"],
    "auto-arrange": ["validated_proposal_batch"],
    "save": ["revision_compare_and_swap", "atomic_repository_write"],
}

RELATED_AGENT_TOOLS: dict[str, list[str]] = {
    "assets": ["search_industrial_assets"],
    "relative": ["preview_facility_move"],
    "distance": ["preview_facility_move"],
    "offset": ["preview_facility_move"],
    "auto-arrange": ["build_facility_layout_preview"],
}

AGENT_TOOL_OWNERS: dict[str, str] = {
    "search_industrial_assets": "observation.asset_catalog_read",
    "inspect_facility_entities": "observation.entity_read",
    "inspect_facility_region": "observation.region_read",
    "inspect_facility_findings": "observation.findings_read",
    "inspect_process_bindings": "observation.process_binding_read",
    "inspect_facility_semantics": "semantic_model.semantic_projection",
    "inspect_pattern_provenance": "observation.pattern_provenance_read",
    "inspect_cell_layout_provenance": "observation.cell_provenance_read",
    "analyze_facility_spatial": "spatial.deterministic_analysis",
    "analyze_facility_fit": "fit_analysis.bounded_fit_analysis",
    "preview_facility_move": "agent_runtime.exact_move_preview",
    "build_facility_layout_preview": "semantic_plan.semantic_preview_compiler",
    "present_chat_visualization": "chat_content.validated_visualization",
    "present_chat_table": "chat_content.validated_table",
}

EXPECTED_QUARANTINES: dict[str, dict[str, str]] = {
    "tests.test_facility_layout_accessibility_audit::test_checked_in_raw_and_summary_are_consistent_when_present": {
        "category": "stale_accessibility_capture",
        "owner": "facility-release-evidence",
        "reason": "The checked-in accessibility raw and summary artifacts predate current Facility UI sources, so recomputation correctly invalidates the stored pass.",
        "expiryCondition": "Regenerate the full accessibility browser audit against the current source tree and commit matching raw and summary artifacts.",
    },
    "tests.test_facility_layout_backend_release_benchmark::test_committed_artifact_is_bound_to_generated_fixtures_and_sources": {
        "category": "stale_backend_release_benchmark",
        "owner": "facility-performance-evidence",
        "reason": "The committed release benchmark is bound to an older source snapshot and cannot certify the current build.",
        "expiryCondition": "Run the full release-eligible backend benchmark on the approved hardware profile and commit its new source-bound artifact.",
    },
    "tests.test_facility_layout_p11_release::test_static_accessibility_and_visual_manifests_are_source_bound": {
        "category": "stale_visual_and_accessibility_manifest",
        "owner": "facility-release-evidence",
        "reason": "P11 visual and accessibility manifests remain internally readable but their source bindings no longer match current UI files.",
        "expiryCondition": "Recapture all required light, dark, desktop, mobile, WebGL recovery, and accessibility artifacts against current sources.",
    },
    "tests.test_facility_layout_p11_release::test_licensing_inventory_covers_vendored_javascript_and_blocks_assets": {
        "category": "incomplete_licensing_inventory",
        "owner": "facility-licensing-review",
        "reason": "The vendored JavaScript inventory does not yet cover every current vendored artifact; legal readiness must remain blocked.",
        "expiryCondition": "Update the vendored dependency inventory with license artifacts and complete the required human legal review.",
    },
    "tests.test_facility_layout_p11_release::test_consolidated_verdict_is_derived_and_retains_external_gates": {
        "category": "derived_release_gate_blocked",
        "owner": "facility-release-evidence",
        "reason": "The consolidated visual gate correctly inherits the stale source-bound visual evidence and cannot remain green.",
        "expiryCondition": "Regenerate the upstream visual and accessibility evidence, then regenerate the consolidated P11 verdict.",
    },
    "tests.test_facility_layout_p11_soak::test_accelerated_soak_proves_mechanics_but_not_elapsed_time": {
        "category": "elapsed_soak_build_changed",
        "owner": "facility-soak-evidence",
        "reason": "The real elapsed-soak ledger belongs to an older build, so the verifier reports build_changed instead of treating it as current evidence.",
        "expiryCondition": "Complete a new elapsed soak against one unchanged current build and commit its source-bound event ledger.",
    },
    "tests.test_facility_layout_p4_renderer::test_p4_browser_evidence_is_complete_and_bound_to_sources": {
        "category": "stale_p4_browser_capture",
        "owner": "facility-browser-evidence",
        "reason": "The P4 browser capture is bound to older editor and renderer source hashes.",
        "expiryCondition": "Rerun the P4 browser verifier and commit a capture bound to current sources.",
    },
    "tests.test_facility_layout_p5_authoring::test_p5_browser_evidence_is_complete_and_bound_to_real_sources": {
        "category": "stale_p5_authoring_capture",
        "owner": "facility-browser-evidence",
        "reason": "The P5 authoring capture is bound to older editor, workspace, or renderer source hashes.",
        "expiryCondition": "Rerun the P5 authoring verifier and commit current source-bound evidence.",
    },
    "tests.test_facility_layout_p5_product::test_product_evidence_is_bound_to_current_sources": {
        "category": "stale_p5_product_capture",
        "owner": "facility-browser-evidence",
        "reason": "The P5 product capture no longer matches the current app and workspace sources.",
        "expiryCondition": "Rerun the P5 product verifier and commit current source-bound evidence.",
    },
    "tests.test_facility_layout_p6_product::test_p6_product_evidence_is_bound_to_current_sources": {
        "category": "stale_p6_product_capture",
        "owner": "facility-browser-evidence",
        "reason": "The P6 product capture no longer matches the current spatial and workspace sources.",
        "expiryCondition": "Rerun the P6 product verifier and commit current source-bound evidence.",
    },
    "tests.test_facility_layout_p8_product::test_p8_product_evidence_is_bound_to_current_sources": {
        "category": "stale_p8_product_capture",
        "owner": "facility-browser-evidence",
        "reason": "The P8 product capture no longer matches the current planner, service, and workspace sources.",
        "expiryCondition": "Rerun the P8 product verifier and commit current source-bound evidence.",
    },
    "tests.test_facility_layout_p9_product::test_p9_product_evidence_is_bound_to_current_sources": {
        "category": "stale_p9_product_capture",
        "owner": "facility-browser-evidence",
        "reason": "The P9 semantic product capture is bound to an older agent-runtime and server source snapshot.",
        "expiryCondition": "Rerun the P9 product verifier and commit current source-bound evidence.",
    },
    "tests.test_facility_layout_release_performance_benchmark::test_smoke_artifacts_are_source_bound_and_cover_real_adapters": {
        "category": "stale_browser_performance_smoke",
        "owner": "facility-performance-evidence",
        "reason": "The browser performance smoke contains measurements for an older set of twelve source hashes and is not current release evidence.",
        "expiryCondition": "Rerun the browser performance smoke and subsequent release profile against the current source tree and approved hardware.",
    },
}

SOURCE_PATHS = (
    "server.py",
    "ai_inspector/facility_layout/agent_runtime.py",
    "ai_inspector/facility_layout/authority_repository.py",
    "ai_inspector/facility_layout/chat_context.py",
    "ai_inspector/facility_layout/chat_intent.py",
    "ai_inspector/facility_layout/feature_flags.py",
    "ai_inspector/facility_layout/fit_analysis.py",
    "ai_inspector/facility_layout/intelligence_evaluation.py",
    "ai_inspector/facility_layout/observation.py",
    "ai_inspector/facility_layout/operations.py",
    "ai_inspector/facility_layout/orchestration.py",
    "ai_inspector/facility_layout/plan_settings.py",
    "ai_inspector/facility_layout/planner.py",
    "ai_inspector/facility_layout/semantic_model.py",
    "ai_inspector/facility_layout/semantic_plan.py",
    "ai_inspector/facility_layout/service.py",
    "ai_inspector/facility_layout/spatial.py",
    "ai_inspector/agent_skills/generate-facility-layout/contract.yaml",
    "ai_inspector/agent_skills/generate-facility-layout/SKILL.md",
    "static/facility_layout_app.js",
    "static/facility_layout_editor.js",
    "static/facility_layout_patterns.js",
    "static/facility_layout_recorder.js",
    "static/facility_layout_session.js",
    "static/facility_layout_three_adapter.js",
    "static/facility_layout_workspace.js",
    "static/index.html",
    "tools/build_facility_layout_kf0_baseline.py",
    "tests/test_facility_layout_kf0_knowledge_foundation.py",
    "tests/fixtures/facility_layout/semantic_intelligence/evaluation-cases-v1.json",
    "tests/fixtures/facility_layout/semantic_intelligence/golden-facility-a.json",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _source_record(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "path": _relative(path),
        "byteLength": len(payload),
        "sha256": _sha256_bytes(payload),
    }


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="ascii"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )


def _git_value(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _junit_summary(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    failures = []
    skipped = []
    for case in cases:
        test_id = f"{case.get('classname')}::{case.get('name')}"
        failure = case.find("failure")
        skip = case.find("skipped")
        if failure is not None:
            failures.append(
                {
                    "testId": test_id,
                    "message": str(failure.get("message") or "test failed"),
                }
            )
        elif skip is not None:
            skipped.append(test_id)
    return {
        "artifact": _source_record(path),
        "total": len(cases),
        "passed": len(cases) - len(failures) - len(skipped),
        "failed": len(failures),
        "skipped": len(skipped),
        "failures": failures,
        "skippedTestIds": skipped,
    }


def _browser_test_paths() -> list[Path]:
    return sorted((REPO_ROOT / "tests").glob("test_facility_layout*.js"))


def _run_browser_tests() -> dict[str, Any]:
    records = []
    for path in _browser_test_paths():
        result = subprocess.run(
            ["node", str(path)],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        output = (result.stdout or "") + (result.stderr or "")
        match = re.search(
            r"(\d+)\s*/\s*(\d+)[^\r\n]*\bpassed\b",
            output,
            re.IGNORECASE,
        )
        passed = int(match.group(1)) if match else 0
        total = int(match.group(2)) if match else 0
        records.append(
            {
                "path": _relative(path),
                "sha256": _sha256(path),
                "exitCode": result.returncode,
                "passed": passed,
                "total": total,
                "status": (
                    "passed"
                    if result.returncode == 0 and total > 0 and passed == total
                    else "failed"
                ),
            }
        )
    payload = {
        "schemaVersion": "facility-layout-kf0-browser-tests-v1",
        "generatedAtUtc": _utc_now(),
        "command": "node tests/test_facility_layout*.js",
        "files": records,
        "summary": {
            "fileCount": len(records),
            "passed": sum(item["passed"] for item in records),
            "total": sum(item["total"] for item in records),
            "failedFiles": [
                item["path"] for item in records if item["status"] != "passed"
            ],
        },
    }
    _write_json(BROWSER_RESULT_PATH, payload)
    return payload


def _parse_ribbon_command_ids() -> list[str]:
    source = (REPO_ROOT / "static" / "index.html").read_text(
        encoding="utf-8-sig"
    )
    marker = "const FACILITY_LAYOUT_RIBBON_CONFIG = Object.freeze(["
    start = source.index(marker)
    end = source.index("]);", start)
    block = source[start:end]
    command_ids: list[str] = []
    for match in re.finditer(r"commands:\s*\[([^\]]*)\]", block, re.DOTALL):
        command_ids.extend(re.findall(r"'([^']+)'", match.group(1)))
    if len(command_ids) != len(set(command_ids)):
        raise RuntimeError("Facility ribbon command IDs are duplicated")
    return command_ids


def _command_capabilities(command_id: str, effect: str) -> list[str]:
    if command_id == "assets":
        return ["asset_library"]
    if command_id == "auto-arrange":
        return ["agent_preview"]
    if effect in {"draft_edit", "persistent_save"}:
        capabilities = ["manual_edit"]
        if command_id == "aisle":
            capabilities.append("routing")
        return capabilities
    return ["viewer_v2"]


def _command_tests(command_id: str, effect: str, surface: str) -> list[str]:
    tests = {
        "tests/test_facility_layout_semantic_model.py",
        "tests/test_facility_layout_intelligence_evaluation.py",
    }
    if surface == "ribbon":
        tests.add("tests/test_facility_layout_p11_contracts.js")
    tests.add("tests/test_facility_layout_workspace.js")
    if effect in {"draft_edit", "persistent_save"}:
        tests.update(
            {
                "tests/test_facility_layout_session.js",
                "tests/test_facility_layout_operations.py",
                "tests/test_facility_layout_service.py",
            }
        )
    if surface in {"3d_navigation", "plan_and_3d_navigation"}:
        tests.add("tests/test_facility_layout_three_adapter.js")
    if surface == "3d_capture":
        tests.add("tests/test_facility_layout_recorder.js")
    return sorted(tests)


def _build_crosswalk(generated_at: str) -> dict[str, Any]:
    from ai_inspector.facility_layout import feature_flags as flag_module
    from ai_inspector.facility_layout.operations import (
        supported_facility_layout_operations,
    )
    from ai_inspector.facility_layout.semantic_model import (
        AGENT_TOOL_SEMANTICS,
        FACILITY_COMMAND_SEMANTICS,
    )

    ribbon_ids = _parse_ribbon_command_ids()
    semantic_ids = [item["commandId"] for item in FACILITY_COMMAND_SEMANTICS]
    if len(semantic_ids) != 39 or len(set(semantic_ids)) != 39:
        raise RuntimeError("Expected exactly 39 unique Facility semantic commands")
    if len(ribbon_ids) != 32:
        raise RuntimeError("Expected exactly 32 Facility ribbon commands")
    non_ribbon = set(semantic_ids) - set(ribbon_ids)
    if non_ribbon != set(NON_RIBBON_SURFACES):
        raise RuntimeError(
            f"Unclassified non-ribbon Facility commands: {sorted(non_ribbon)}"
        )

    commands = []
    for item in FACILITY_COMMAND_SEMANTICS:
        command_id = item["commandId"]
        surface = "ribbon" if command_id in ribbon_ids else NON_RIBBON_SURFACES[command_id]
        if command_id in {"orbit", "walkthrough", "drone", "record"}:
            ui_handler = "Workspace._handleThreeNavigationClick"
        else:
            ui_handler = "Workspace.executeCommand"
        commands.append(
            {
                **item,
                "uiSurface": surface,
                "uiHandler": ui_handler,
                "sessionHandlers": SESSION_HANDLERS.get(command_id, []),
                "operationKernelHandlers": KERNEL_HANDLERS.get(command_id, []),
                "operationKernelApplicability": (
                    "applicable" if command_id in KERNEL_HANDLERS else "not_applicable"
                ),
                "deterministicOwner": (
                    "facility.operations_and_repository"
                    if item["effect"] in {"draft_edit", "persistent_save"}
                    else (
                        "facility.recorder"
                        if item["effect"] == "viewport_capture"
                        else "facility.workspace_and_renderer"
                    )
                ),
                "requiredCapabilities": _command_capabilities(
                    command_id, item["effect"]
                ),
                "relatedAgentTools": RELATED_AGENT_TOOLS.get(command_id, []),
                "tests": _command_tests(command_id, item["effect"], surface),
            }
        )

    agent_tools = []
    for item in AGENT_TOOL_SEMANTICS:
        tool_id = item["commandId"]
        owner = AGENT_TOOL_OWNERS.get(tool_id)
        if owner is None:
            raise RuntimeError(f"Agent tool has no deterministic owner: {tool_id}")
        agent_tools.append(
            {
                **item,
                "deterministicOwner": owner,
                "requiredCapabilities": [
                    "agent_preview"
                    if item["effect"] == "preview"
                    else "viewer_v2"
                ],
                "tests": [
                    "tests/test_facility_layout_agent_runtime.py",
                    "tests/test_facility_layout_intelligence_evaluation.py",
                ],
            }
        )
    if len(agent_tools) != 14 or len({x["commandId"] for x in agent_tools}) != 14:
        raise RuntimeError("Expected exactly 14 unique Facility agent tools")

    capability_flags = dict(flag_module._CAPABILITY_FLAGS)
    dependencies = {
        key: list(value) for key, value in flag_module._DEPENDENCIES.items()
    }
    feature_flags = [
        {
            "capability": capability,
            "environmentVariable": flag_name,
            "dependencies": dependencies[capability],
        }
        for capability, flag_name in capability_flags.items()
    ]
    effects = Counter(item["effect"] for item in commands)
    expected_effects = {
        "draft_edit": 28,
        "persistent_save": 1,
        "read": 1,
        "viewport": 8,
        "viewport_capture": 1,
    }
    if dict(sorted(effects.items())) != expected_effects:
        raise RuntimeError(f"Unexpected Facility command effects: {effects}")

    payload = {
        "schemaVersion": "facility-layout-kf0-command-crosswalk-v1",
        "generatedAtUtc": generated_at,
        "sources": [
            _source_record(REPO_ROOT / "ai_inspector/facility_layout/semantic_model.py"),
            _source_record(REPO_ROOT / "ai_inspector/facility_layout/feature_flags.py"),
            _source_record(REPO_ROOT / "ai_inspector/facility_layout/operations.py"),
            _source_record(REPO_ROOT / "static/index.html"),
            _source_record(REPO_ROOT / "static/facility_layout_workspace.js"),
            _source_record(REPO_ROOT / "static/facility_layout_session.js"),
        ],
        "commandRegistry": {
            "count": len(commands),
            "ribbonCount": len(ribbon_ids),
            "nonRibbonCount": len(non_ribbon),
            "effectCounts": dict(sorted(effects.items())),
            "canonicalSha256": _sha256_bytes(_canonical_bytes(commands)),
            "commands": commands,
        },
        "agentToolRegistry": {
            "count": len(agent_tools),
            "canonicalSha256": _sha256_bytes(_canonical_bytes(agent_tools)),
            "tools": agent_tools,
        },
        "operationKernel": {
            "supportedOperationCount": len(supported_facility_layout_operations()),
            "supportedOperations": list(supported_facility_layout_operations()),
        },
        "featureFlagLadder": {
            "count": len(feature_flags),
            "orderedCapabilities": list(capability_flags),
            "flags": feature_flags,
        },
        "classification": {
            "allCommandsClassified": len(commands) == 39,
            "allAgentToolsClassified": len(agent_tools) == 14,
            "allEffectsClassified": set(effects) == set(expected_effects),
            "allFeatureFlagsClassified": len(feature_flags) == 7,
            "unclassifiedCommandIds": [],
            "unclassifiedAgentToolIds": [],
        },
    }
    return payload


def _effective_configuration() -> dict[str, Any]:
    shared_provider = str(os.getenv("INSPECTORPRO_SAGE_PROVIDER") or "").strip()
    shared_model = str(os.getenv("INSPECTORPRO_SAGE_ANTHROPIC_MODEL") or "").strip()
    shared_effort = str(
        os.getenv("INSPECTORPRO_SAGE_OPENAI_REASONING_EFFORT") or ""
    ).strip()
    return {
        "provider": "anthropic",
        "providerSource": "forced_for_non_deviation_agent",
        "model": shared_model or FACILITY_DEFAULT_MODEL,
        "modelSource": (
            "INSPECTORPRO_SAGE_ANTHROPIC_MODEL"
            if shared_model
            else "SAGE_ANTHROPIC_MODEL_DEFAULT"
        ),
        "reasoningEffort": None,
        "reasoningEffortSource": "not_applicable_for_anthropic",
        "sharedProviderOverrideObserved": shared_provider or None,
        "sharedOpenAiReasoningEffortObserved": shared_effort or None,
        "apiKeyRecorded": False,
        "futureFacilityScopedEnvironmentVariables": [
            "INSPECTORPRO_FACILITY_LAYOUT_SAGE_PROVIDER",
            "INSPECTORPRO_FACILITY_LAYOUT_SAGE_ANTHROPIC_MODEL",
            "INSPECTORPRO_FACILITY_LAYOUT_SAGE_OPENAI_MODEL",
            "INSPECTORPRO_FACILITY_LAYOUT_SAGE_OPENAI_REASONING_EFFORT",
        ],
    }


def _build_decisions(generated_at: str) -> dict[str, Any]:
    from ai_inspector.facility_layout.agent_runtime import (
        FACILITY_LAYOUT_AGENT_CURSOR_TTL_SECONDS,
        FACILITY_LAYOUT_AGENT_MAXIMUM_CALLS_PER_TURN,
        FACILITY_LAYOUT_AGENT_MAXIMUM_RESPONSE_BYTES,
        FACILITY_LAYOUT_AGENT_TURN_TTL_SECONDS,
    )
    from ai_inspector.facility_layout.operations import MAX_OPERATION_BATCH
    from ai_inspector.facility_layout.planner import MAXIMUM_PLANNED_INSTANCES

    budget_contract = {
        "toolCallsPerTurn": FACILITY_LAYOUT_AGENT_MAXIMUM_CALLS_PER_TURN,
        "toolResponseBytes": FACILITY_LAYOUT_AGENT_MAXIMUM_RESPONSE_BYTES,
        "cursorTtlSeconds": FACILITY_LAYOUT_AGENT_CURSOR_TTL_SECONDS,
        "turnTtlSeconds": FACILITY_LAYOUT_AGENT_TURN_TTL_SECONDS,
        "operationBatch": MAX_OPERATION_BATCH,
        "plannedInstances": MAXIMUM_PLANNED_INSTANCES,
        "skillContextHardEstimatedTokens": 12000,
        "skillContextTargetEstimatedTokens": 9600,
        "stageRegistrySliceCanonicalBytes": 8192,
        "stageRegistrySliceMaximumEstimatedTokens": 2048,
        "estimator": {
            "id": BYTES4_ESTIMATOR,
            "formula": "ceil(canonical_utf8_bytes / 4)",
            "isModelTokenizer": False,
        },
        "headroomPercent": 20,
    }
    budget_bytes = _canonical_bytes(budget_contract)
    payload = {
        "schemaVersion": "facility-layout-kf0-decisions-v1",
        "generatedAtUtc": generated_at,
        "authorityPolicy": {
            "modelMayGrantHumanAuthority": False,
            "modelMayApproveOrRelease": False,
            "geometryFeasibilityIsAuthority": False,
            "prototypeModeRequiresExplicitFlag": True,
            "prototypeAssumptionsRemainVisible": True,
            "humanApprovalRequiredForPersistentSave": True,
            "finalSaveIsSeparateExplicitCommand": True,
        },
        "stageTaxonomy": [
            {"stage": 1, "id": "facility_envelope", "label": "Facility envelope and plan settings"},
            {"stage": 2, "id": "macro_departments", "label": "Macro departments"},
            {"stage": 3, "id": "primary_circulation", "label": "Primary circulation and crossings"},
            {"stage": 4, "id": "department_subdivisions", "label": "Department subdivisions"},
            {"stage": 5, "id": "department_resources", "label": "Department resources and staging"},
            {"stage": 6, "id": "seed_cells", "label": "Seed manufacturing cells"},
            {"stage": 7, "id": "repeated_modules", "label": "Repeated cells, rows, and modules"},
            {"stage": 8, "id": "floor_communication", "label": "Floor communication and support details"},
            {"stage": 9, "id": "deterministic_validation", "label": "Full deterministic validation"},
            {"stage": 10, "id": "review_and_save", "label": "Review and explicit save"},
        ],
        "gateG1Defaults": {
            "minimumFacilityAxisMeters": 0.5,
            "maximumFacilityAxisMeters": 10000.0,
            "supportedSourceUnits": ["m", "mm", "ft", "in"],
            "minimumDepartmentCount": 1,
            "maximumDepartmentCount": 50,
            "explicitProportionsOverrideDefaults": True,
            "labelsOnlyDefault": "equal_area_partition_with_disclosed_assumption",
            "inventExpansionReserve": False,
            "inventCorridor": False,
            "inventSafetySeparation": False,
            "savePolicy": "separate_explicit_user_command",
        },
        "runtimeBudgets": budget_contract,
        "runtimeBudgetArtifactMeasurement": {
            "canonicalBytes": len(budget_bytes),
            "estimatedTokens": (len(budget_bytes) + 3) // 4,
            "estimatorId": BYTES4_ESTIMATOR,
            "canonicalSha256": _sha256_bytes(budget_bytes),
        },
        "configuration": _effective_configuration(),
        "durableRunDecisions": {
            "legacyPendingStoreRole": "read_only_follow_up_pointer_only",
            "legacyPendingStoreTtlSeconds": 1800,
            "legacyPendingStoreIsRestartSafe": False,
            "generationRepositoryRequired": True,
            "generationRunIdleExpiryHours": 24,
            "terminalTombstoneRetentionDays": 30,
            "singleWritableRunPerLayout": True,
            "crossProcessLockRequired": True,
            "modelTextMayEnqueueContinuation": False,
        },
    }
    return payload


def _build_gaps(generated_at: str) -> dict[str, Any]:
    gaps = [
        ("K1", "partial", "The 39 commands have descriptive semantics, but one versioned contract does not yet own inputs, defaults, prohibitions, failures, receipts, and handler identity.", "KF1"),
        ("K2", "partial", "All ten geometric strategies exist; full structured strategy inputs, outputs, assumptions, evidence, and failure contracts are not canonical.", "KF1"),
        ("K3", "missing", "UI commands, Python semantics, feature gates, and agent tools are separate registries with no generated parity owner.", "KF1-KF2"),
        ("K4", "missing", "Semantic Plan v1 cannot author a general facility envelope and arbitrary labeled department partition from intent.", "KF2-KF5"),
        ("K5", "missing", "There is no restart-safe staged generation graph, durable receipt chain, invalidation model, or cumulative save proposal.", "KF1-KF5"),
        ("K6", "partial", "Physical footprints are usable, but many assets lack authored sides, access envelopes, utilities, clearances, and planning-readiness evidence.", "KF3"),
        ("K7", "partial", "Ten strategies are implemented, but no canonical recipe registry composes manufacturing concepts and four structured strategy field groups remain missing.", "KF1-KF4"),
        ("K8", "partial", "The bounded server analyzer compares line, L, and U only while the browser implements ten strategy families.", "KF4"),
        ("K9", "missing", "The 827-placement reference factory is not represented as intent, semantic tool selection, receipt, validation, and correction traces.", "KF6"),
        ("K10", "partial", "The generation skill is revision-bound and bounded but assumes one complete preview and has no stage-sliced command knowledge or durable resume context.", "KF2-KF5"),
    ]
    records = [
        {
            "capabilityId": capability,
            "status": status,
            "gap": gap,
            "closureMilestone": milestone,
            "blocksGateG1": capability in {"K1", "K3", "K4", "K5", "K10"},
        }
        for capability, status, gap, milestone in gaps
    ]
    return {
        "schemaVersion": "facility-layout-kf0-capability-gaps-v1",
        "generatedAtUtc": generated_at,
        "records": records,
        "summary": dict(sorted(Counter(item["status"] for item in records).items())),
        "allK1ThroughK10Classified": [item["capabilityId"] for item in records]
        == [f"K{index}" for index in range(1, 11)],
    }


def _test_source_path(test_id: str) -> Path:
    module = test_id.split("::", 1)[0]
    return REPO_ROOT / (module.replace(".", "/") + ".py")


def _build_quarantines(
    facility_junit: Mapping[str, Any],
) -> list[dict[str, Any]]:
    failures = {item["testId"]: item for item in facility_junit["failures"]}
    if set(failures) != set(EXPECTED_QUARANTINES):
        unexplained = sorted(set(failures) - set(EXPECTED_QUARANTINES))
        absent = sorted(set(EXPECTED_QUARANTINES) - set(failures))
        raise RuntimeError(
            f"KF0 quarantine set changed; unexplained={unexplained}, absent={absent}"
        )
    records = []
    junit_artifact = facility_junit["artifact"]
    for index, test_id in enumerate(sorted(failures), start=1):
        policy = EXPECTED_QUARANTINES[test_id]
        test_source = _test_source_path(test_id)
        records.append(
            {
                "quarantineId": f"KF0-Q{index:02d}",
                "testId": test_id,
                "category": policy["category"],
                "owner": policy["owner"],
                "reason": policy["reason"],
                "observedFailure": failures[test_id]["message"],
                "testSource": _source_record(test_source),
                "baselineEvidence": junit_artifact,
                "expiryCondition": policy["expiryCondition"],
                "changedSurfaceIntersection": False,
                "nonIntersectionEvidence": {
                    "kf0ChangedSurface": [
                        "KF0 baseline tooling",
                        "KF0 machine-readable contracts",
                        "KF0 contract tests",
                    ],
                    "reason": "This test validates historical release certification or an external release gate, not the KF0 command, tool, budget, authority, or evaluation contracts.",
                    "independentCurrentBehaviorEvidence": [
                        ".runtime/kf0/intelligence-evaluation.json",
                        ".runtime/kf0/saved-layout-smoke.json",
                        ".runtime/kf0/browser-tests.json",
                        ".runtime/kf0/agent-python.xml",
                    ],
                },
                "blocksChangedSurfaceRegressionClaim": False,
                "blocksFacilityReleaseClaim": True,
                "disposition": "quarantined_release_evidence",
            }
        )
    return records


def _evaluation_inventory() -> dict[str, Any]:
    path = REPO_ROOT / "tests/fixtures/facility_layout/semantic_intelligence/evaluation-cases-v1.json"
    payload = _load_json(path)
    cases = payload["cases"]
    records = [
        {
            "id": item["id"],
            "suite": item["suite"],
            "classification": "regression_visible",
            "heldOut": False,
        }
        for item in cases
    ]
    if len(records) != 71 or len({item["id"] for item in records}) != 71:
        raise RuntimeError("Expected exactly 71 unique existing evaluation cases")
    return {
        "source": _source_record(path),
        "count": len(records),
        "classification": "regression_visible_not_held_out",
        "suiteCounts": dict(sorted(Counter(item["suite"] for item in records).items())),
        "cases": records,
    }


def _build_manifest(
    generated_at: str,
    crosswalk: Mapping[str, Any],
    decisions: Mapping[str, Any],
    gaps: Mapping[str, Any],
) -> dict[str, Any]:
    required = [
        FACILITY_JUNIT_PATH,
        AGENT_JUNIT_PATH,
        INTELLIGENCE_PATH,
        SAVED_LAYOUT_SMOKE_PATH,
        BROWSER_RESULT_PATH,
    ]
    missing = [_relative(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"Missing KF0 runtime artifacts: {missing}")

    facility_junit = _junit_summary(FACILITY_JUNIT_PATH)
    agent_junit = _junit_summary(AGENT_JUNIT_PATH)
    intelligence = _load_json(INTELLIGENCE_PATH)
    saved_smoke = _load_json(SAVED_LAYOUT_SMOKE_PATH)
    browser = _load_json(BROWSER_RESULT_PATH)
    quarantines = _build_quarantines(facility_junit)
    unexplained = facility_junit["failed"] - len(quarantines)

    layout_path = Path(saved_smoke["layout"]["path"])
    if not layout_path.is_file():
        raise RuntimeError(f"Saved reference layout is missing: {layout_path}")
    current_layout_hash = _sha256(layout_path)
    if current_layout_hash != saved_smoke["layout"]["sha256After"]:
        raise RuntimeError("Saved reference layout changed after the smoke run")

    source_records = [_source_record(REPO_ROOT / path) for path in SOURCE_PATHS]
    source_records.append(_source_record(PLAN_PATH))
    source_snapshot_hash = _sha256_bytes(_canonical_bytes(source_records))
    changed_surface_green = (
        intelligence["status"] == "passed"
        and intelligence["summary"]["failedCount"] == 0
        and saved_smoke["status"] == "passed"
        and all(saved_smoke["assertions"].values())
        and browser["summary"]["passed"] == browser["summary"]["total"]
        and not browser["summary"]["failedFiles"]
        and agent_junit["failed"] == 0
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAtUtc": generated_at,
        "plan": _source_record(PLAN_PATH),
        "sourceRevision": {
            "gitCommit": _git_value("rev-parse", "HEAD"),
            "workingTreeDirty": bool(_git_value("diff", "--name-only")),
            "sourceSnapshotSha256": source_snapshot_hash,
            "sources": source_records,
        },
        "registryHashes": {
            "commandRegistrySha256": crosswalk["commandRegistry"]["canonicalSha256"],
            "agentToolRegistrySha256": crosswalk["agentToolRegistry"]["canonicalSha256"],
            "crosswalkArtifactSha256": _sha256_bytes(_canonical_bytes(crosswalk)),
            "decisionsArtifactSha256": _sha256_bytes(_canonical_bytes(decisions)),
            "capabilityGapsArtifactSha256": _sha256_bytes(_canonical_bytes(gaps)),
        },
        "fixtures": {
            "evaluation": _evaluation_inventory(),
            "savedReferenceLayout": {
                "path": _relative(layout_path),
                "byteLength": layout_path.stat().st_size,
                "sha256": current_layout_hash,
                "revision": saved_smoke["layout"]["revision"],
                "placements": saved_smoke["counts"]["placements"],
                "zones": saved_smoke["counts"]["zones"],
                "departments": saved_smoke["counts"]["departments"],
            },
        },
        "baselineRuns": {
            "facilityPython": {
                **facility_junit,
                "command": "python -m pytest <45 Facility Python files> -q -p no:cacheprovider",
            },
            "focusedAgentPython": {
                **agent_junit,
                "command": "python -m pytest <7 focused agent/provider files> -q -p no:cacheprovider",
            },
            "browserJavaScript": {
                "artifact": _source_record(BROWSER_RESULT_PATH),
                **browser["summary"],
            },
            "deterministicIntelligence": {
                "artifact": _source_record(INTELLIGENCE_PATH),
                "status": intelligence["status"],
                "summary": intelligence["summary"],
                "providerCalls": intelligence["providerCalls"],
                "networkCalls": intelligence["networkCalls"],
                "effectiveConfiguration": decisions["configuration"],
            },
            "savedLayoutSmoke": {
                "artifact": _source_record(SAVED_LAYOUT_SMOKE_PATH),
                "status": saved_smoke["status"],
                "assertionCount": len(saved_smoke["assertions"]),
                "allAssertionsPassed": all(saved_smoke["assertions"].values()),
                "providerCalls": saved_smoke["providerCalls"],
                "networkCalls": saved_smoke["networkCalls"],
            },
        },
        "quarantines": quarantines,
        "baselineDisposition": {
            "rawFailureCount": facility_junit["failed"],
            "quarantinedFailureCount": len(quarantines),
            "unexplainedFailureCount": unexplained,
            "changedSurfaceSuitesGreen": changed_surface_green,
            "facilityReleaseEvidenceCurrent": False,
            "facilityReleaseBlockedByQuarantines": True,
            "kf0ExitEligible": unexplained == 0 and changed_surface_green,
        },
        "classification": {
            "semanticCommandCount": crosswalk["commandRegistry"]["count"],
            "agentToolCount": crosswalk["agentToolRegistry"]["count"],
            "featureFlagCount": crosswalk["featureFlagLadder"]["count"],
            "evaluationCaseCount": 71,
            "capabilityGapCount": len(gaps["records"]),
        },
    }


def _report_markdown(manifest: Mapping[str, Any]) -> str:
    runs = manifest["baselineRuns"]
    disposition = manifest["baselineDisposition"]
    lines = [
        "# Facility Layout KF0 Baseline Report",
        "",
        f"Generated: {manifest['generatedAtUtc']}",
        "",
        "## Verdict",
        "",
        "KF0 baseline accepted. Current semantic, saved-layout, browser, and agent behavior is green. The historical release evidence remains explicitly blocked and is not being used to claim current release readiness.",
        "",
        "## Fresh Results",
        "",
        "| Surface | Result |",
        "| --- | --- |",
        f"| Deterministic intelligence | {runs['deterministicIntelligence']['summary']['passedCount']}/{runs['deterministicIntelligence']['summary']['checkCount']} checks; 12 gates; 71 cases; 0 provider calls |",
        f"| Saved reference layout | {runs['savedLayoutSmoke']['assertionCount']}/{runs['savedLayoutSmoke']['assertionCount']} assertions; 827 placements; bytes unchanged |",
        f"| Facility browser JavaScript | {runs['browserJavaScript']['passed']}/{runs['browserJavaScript']['total']} tests |",
        f"| Focused agent/provider Python | {runs['focusedAgentPython']['passed']} passed, {runs['focusedAgentPython']['failed']} failed |",
        f"| Full Facility Python | {runs['facilityPython']['passed']} passed, {runs['facilityPython']['failed']} quarantined failures, {runs['facilityPython']['skipped']} skipped |",
        "",
        "## Failure Disposition",
        "",
        f"All {disposition['rawFailureCount']} failures have machine-readable dispositions. Ten are stale source-bound captures; the remaining records are licensing, elapsed-soak, and derived release gates. Every quarantine blocks a Facility release claim, but none intersects the KF0 contract/tooling changed surface.",
        "",
        "The baseline contains zero unexplained failures. Quarantine details, owners, source hashes, and expiry conditions are in `facility-layout-kf0-baseline-manifest.json`.",
        "",
        "## Frozen Surface",
        "",
        "- 39 semantic UI commands: 32 ribbon and 7 non-ribbon.",
        "- Effects: 28 draft edits, 8 viewport, 1 read, 1 persistent save, and 1 viewport capture.",
        "- 14 agent tools with one deterministic owner each.",
        "- 7 ordered feature capabilities and dependencies.",
        "- 71 existing evaluation cases classified as regression-visible, never held out.",
        "- 10 generation stages and the G1 bounds/defaults frozen.",
        "- Facility baseline provider/model frozen as Anthropic / `claude-sonnet-4-5-20250929`; no provider calls were made by deterministic baseline runs.",
        "",
        "## Artifacts",
        "",
        "- `facility-layout-kf0-command-crosswalk.json`",
        "- `facility-layout-kf0-decisions.json`",
        "- `facility-layout-kf0-capability-gaps.json`",
        "- `facility-layout-kf0-baseline-manifest.json`",
        "",
        "These are historical baseline records. Later milestones may change source hashes, but must preserve or explicitly migrate the frozen semantic IDs, effects, authority boundaries, and evaluation cases.",
        "",
    ]
    return "\n".join(lines)


def _validate(
    manifest: Mapping[str, Any],
    crosswalk: Mapping[str, Any],
    decisions: Mapping[str, Any],
    gaps: Mapping[str, Any],
    *,
    check_current_sources: bool,
) -> list[str]:
    errors: list[str] = []
    if manifest.get("schemaVersion") != SCHEMA_VERSION:
        errors.append("manifest_schema_invalid")
    if crosswalk.get("commandRegistry", {}).get("count") != 39:
        errors.append("command_count_invalid")
    if crosswalk.get("agentToolRegistry", {}).get("count") != 14:
        errors.append("agent_tool_count_invalid")
    if crosswalk.get("featureFlagLadder", {}).get("count") != 7:
        errors.append("feature_flag_count_invalid")
    if manifest.get("fixtures", {}).get("evaluation", {}).get("count") != 71:
        errors.append("evaluation_case_count_invalid")
    if len(manifest.get("quarantines", [])) != 13:
        errors.append("quarantine_count_invalid")
    if manifest.get("baselineDisposition", {}).get("unexplainedFailureCount") != 0:
        errors.append("unexplained_baseline_failures")
    if manifest.get("baselineDisposition", {}).get("changedSurfaceSuitesGreen") is not True:
        errors.append("changed_surface_not_green")
    if gaps.get("allK1ThroughK10Classified") is not True:
        errors.append("capability_gap_matrix_incomplete")
    if len(decisions.get("stageTaxonomy", [])) != 10:
        errors.append("stage_taxonomy_incomplete")
    required_quarantine_fields = {
        "testId",
        "owner",
        "reason",
        "testSource",
        "expiryCondition",
        "changedSurfaceIntersection",
        "nonIntersectionEvidence",
    }
    for item in manifest.get("quarantines", []):
        missing = required_quarantine_fields - set(item)
        if missing:
            errors.append(f"quarantine_fields_missing:{item.get('quarantineId')}:{sorted(missing)}")
        if item.get("blocksFacilityReleaseClaim") is not True:
            errors.append(f"quarantine_release_not_blocked:{item.get('quarantineId')}")
    if check_current_sources:
        for item in manifest.get("sourceRevision", {}).get("sources", []):
            path = REPO_ROOT / item["path"]
            if not path.is_file() or _sha256(path) != item["sha256"]:
                errors.append(f"source_hash_mismatch:{item['path']}")
        layout = manifest.get("fixtures", {}).get("savedReferenceLayout", {})
        layout_path = REPO_ROOT / str(layout.get("path") or "")
        if not layout_path.is_file() or _sha256(layout_path) != layout.get("sha256"):
            errors.append("saved_reference_layout_hash_mismatch")
    return errors


def build(*, run_browser_tests: bool = True) -> dict[str, Path]:
    sys.path.insert(0, str(REPO_ROOT))
    generated_at = _utc_now()
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    if run_browser_tests or not BROWSER_RESULT_PATH.is_file():
        browser = _run_browser_tests()
        if browser["summary"]["failedFiles"]:
            raise RuntimeError(
                f"Facility browser tests failed: {browser['summary']['failedFiles']}"
            )
    crosswalk = _build_crosswalk(generated_at)
    decisions = _build_decisions(generated_at)
    gaps = _build_gaps(generated_at)
    manifest = _build_manifest(generated_at, crosswalk, decisions, gaps)
    errors = _validate(
        manifest,
        crosswalk,
        decisions,
        gaps,
        check_current_sources=True,
    )
    if errors:
        raise RuntimeError(f"KF0 artifact validation failed: {errors}")
    _write_json(CROSSWALK_PATH, crosswalk)
    _write_json(DECISIONS_PATH, decisions)
    _write_json(GAPS_PATH, gaps)
    _write_json(MANIFEST_PATH, manifest)
    REPORT_PATH.write_text(_report_markdown(manifest), encoding="ascii")
    return {
        "crosswalk": CROSSWALK_PATH,
        "decisions": DECISIONS_PATH,
        "gaps": GAPS_PATH,
        "manifest": MANIFEST_PATH,
        "report": REPORT_PATH,
    }


def check(*, current_sources: bool) -> list[str]:
    artifacts = [MANIFEST_PATH, CROSSWALK_PATH, DECISIONS_PATH, GAPS_PATH]
    missing = [_relative(path) for path in artifacts if not path.is_file()]
    if missing:
        return [f"missing_artifact:{path}" for path in missing]
    return _validate(
        _load_json(MANIFEST_PATH),
        _load_json(CROSSWALK_PATH),
        _load_json(DECISIONS_PATH),
        _load_json(GAPS_PATH),
        check_current_sources=current_sources,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--check-current-sources", action="store_true")
    parser.add_argument("--reuse-browser-results", action="store_true")
    args = parser.parse_args()
    if args.check or args.check_current_sources:
        errors = check(current_sources=args.check_current_sources)
        if errors:
            print(json.dumps({"status": "failed", "errors": errors}, indent=2))
            return 1
        print(json.dumps({"status": "passed"}, indent=2))
        return 0
    paths = build(run_browser_tests=not args.reuse_browser_results)
    print(
        json.dumps(
            {"status": "passed", "artifacts": {k: _relative(v) for k, v in paths.items()}},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
