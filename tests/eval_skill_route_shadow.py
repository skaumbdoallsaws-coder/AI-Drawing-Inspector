"""Live Phase 2 semantic-route evaluation against synthetic labeled cases.

This is operator-run because it uses the configured Anthropic API key. It
never sends customer data, never executes a route, and writes no raw model
response. The fixture messages and context are synthetic and committed.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import server  # noqa: E402
from ai_inspector.agent_skills import ExactRouteCache, SkillRuntimeSettings, classify_shadow_route  # noqa: E402


FIXTURE = REPO_ROOT / "tests" / "fixtures" / "skill_route_cases.json"
OUTPUT = REPO_ROOT / "runtime_logs" / "skill_route_shadow_eval.json"


def _synthetic_context(variant: str) -> dict:
    base = {
        "active_mode": "report_fai",
        "active_tab": "report",
        "part_number": "SYNTH-P1",
        "part_name": "Synthetic inspected component",
        "has_drawing_file": True,
        "available_dimensions": [{"id": "5", "label": "Synthetic bore"}],
        "profile_features": [{"id": "synthetic-bore", "semantic_name": "Synthetic bore"}],
    }
    if variant == "empty":
        return {"active_mode": "report_fai", "active_tab": "report"}

    part_legend = [
        {"part_number": "SYNTH-P1", "description": "Synthetic inspected component"},
        {"part_number": "SYNTH-P2", "description": "Synthetic mating pin"},
        {"part_number": "SYNTH-P3", "description": "Synthetic link"},
        {"part_number": "SYNTH-H1", "description": "Synthetic lower housing"},
    ]
    motion = {
        "available": True,
        "motions": [
            {
                "motion_id": "synthetic-cycle",
                "groups": [
                    {
                        "id": "synthetic-affected-group",
                        "label": "Synthetic affected joint",
                        "function": "Shows the joint motion associated with the inspected bore.",
                        "part_numbers": ["SYNTH-P1", "SYNTH-P2", "SYNTH-P3"],
                    },
                    {
                        "id": "synthetic-full-mechanism",
                        "label": "Synthetic full mechanism",
                        "function": "Shows the complete assembly motion.",
                        "part_numbers": ["SYNTH-P1", "SYNTH-P2", "SYNTH-P3", "SYNTH-H1"],
                    },
                ],
            }
        ],
    }
    base["viewport_context"] = {
        "part_legend": part_legend,
        "motion": motion,
        "state": {
            "active_tab": "assembly" if variant == "assembly_motion" else "report",
            "motion_playing": False,
            "highlighted": [],
            "hidden": [],
        },
    }
    base["part_color_legend"] = part_legend

    if variant == "assembly_motion":
        base["active_mode"] = "assembly"
        base["active_tab"] = "assembly"
        base.pop("available_dimensions", None)
        base.pop("profile_features", None)
        return base

    base["fai_characteristics"] = [
        {"char_number": "1", "description": "Reference characteristic", "status": "PENDING", "measured": None},
        {"char_number": "2", "description": "Synthetic height", "status": "PASS", "measured": 10.0},
        {"char_number": "5", "description": "Synthetic bore diameter", "status": "FAIL", "measured": 32.0},
    ]
    return base


def _authorize(message, requested):
    return server._authorize_skill_shadow_effects(message, requested)


def _route_via_http(endpoint: str, case: dict, context: dict) -> tuple[dict | None, dict | None]:
    context = dict(context)
    if case.get("workflow_state"):
        context["skill_workflow_state"] = case["workflow_state"]
    payload = json.dumps(
        {
            "message": case["message"],
            "history": case.get("history") or [],
            "inspection_context": context,
            "agent": "sage",
            "bypass_cache": True,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/api/internal/agent-skills/test-route",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        body = json.loads(response.read().decode("utf-8"))
    return body.get("route"), body.get("failure")


def _run_case(case: dict, model: str, api_key: str | None, endpoint: str | None) -> dict:
    context = _synthetic_context(case["context"])
    failure_info: dict = {}
    if endpoint:
        route, http_failure = _route_via_http(endpoint, case, context)
        if isinstance(http_failure, dict):
            failure_info.update(http_failure)
    else:
        catalog, facts = server._build_skill_route_catalog(context, "sage")
        route = classify_shadow_route(
            case["message"],
            catalog=catalog,
            context_facts=facts,
            recent_turns=case.get("history") or [],
            workflow_state=case.get("workflow_state") or {},
            cache=ExactRouteCache(max_entries=4, ttl_seconds=60),
            model=model,
            timeout_seconds=4.75,
            max_tokens=700,
            api_key=api_key,
            agent_type="deviation-analyst",
            authorize=_authorize,
            failure=failure_info,
        )
    expected = case["expected"]
    checks = {
        "valid_route": route is not None,
        "workflow": bool(route) and route.get("primary_workflow") == expected["workflow"],
        "speech_act": bool(route) and route.get("speech_act") in expected["speech_acts"],
        "viewport_effect": bool(route)
        and route.get("requested_side_effects", {}).get("viewport_write") is expected["viewport_write"],
        "asset_effect": bool(route)
        and route.get("requested_side_effects", {}).get("asset_write") is expected["asset_write"],
        "skills": bool(route)
        and set(expected["skills"]).issubset(
            {item["id"] for item in route.get("skill_candidates") or []}
        ),
    }
    if "needs_clarification" in expected:
        checks["needs_clarification"] = bool(route) and route.get("needs_clarification") is expected["needs_clarification"]
    if "continue_existing_workflow" in expected:
        checks["continue_existing_workflow"] = bool(route) and route.get("continue_existing_workflow") is expected["continue_existing_workflow"]
    safe_route = None
    if route:
        safe_route = {
            "speech_act": route.get("speech_act"),
            "primary_workflow": route.get("primary_workflow"),
            "continue_existing_workflow": route.get("continue_existing_workflow"),
            "workflow_confidence": route.get("workflow_confidence"),
            "skill_candidates": route.get("skill_candidates"),
            "requested_side_effects": route.get("requested_side_effects"),
            "needs_clarification": route.get("needs_clarification"),
            "shadow": route.get("_shadow"),
        }
    return {
        "id": case["id"],
        "checks": checks,
        "route": safe_route,
        "failure": failure_info if route is None and failure_info else None,
    }


def _rate(results: list[dict], check: str) -> float:
    relevant = [result for result in results if check in result["checks"]]
    if check != "valid_route":
        # Availability is measured separately. Classification metrics answer
        # whether routes that survived timeout/schema validation are correct.
        relevant = [result for result in relevant if result["checks"].get("valid_route")]
    return sum(bool(result["checks"][check]) for result in relevant) / len(relevant) if relevant else 1.0


def run() -> int:
    fixture = json.loads(FIXTURE.read_text(encoding="ascii"))
    endpoint = (os.getenv("SKILL_ROUTE_EVAL_URL") or "").strip() or None
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not endpoint and not api_key:
        print("ANTHROPIC_API_KEY is not configured", file=sys.stderr)
        return 2
    model = SkillRuntimeSettings.from_env().router_model
    cases = fixture["cases"]
    selected_ids = {
        item.strip()
        for item in (os.getenv("SKILL_ROUTE_EVAL_CASES") or "").split(",")
        if item.strip()
    }
    if selected_ids:
        cases = [case for case in cases if case["id"] in selected_ids]
    worker_count = max(1, min(4, int(os.getenv("INSPECTORPRO_ROUTE_EVAL_WORKERS", "1"))))
    results = []
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="route-eval") as executor:
        futures = {
            executor.submit(_run_case, case, model, api_key, endpoint): case["id"]
            for case in cases
        }
        for future in as_completed(futures):
            case_id = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                result = {
                    "id": case_id,
                    "checks": {"valid_route": False},
                    "route": None,
                    "failure": {"reason": "harness_error", "error_type": type(exc).__name__},
                }
            results.append(result)
            failed = [name for name, ok in result["checks"].items() if not ok]
            reason = (result.get("failure") or {}).get("reason")
            suffix = f" :: {', '.join(failed)}" if failed else ""
            if failed and reason:
                suffix += f" [{reason}]"
            print(f"{'PASS' if not failed else 'FAIL'} {case_id}{suffix}")

    results.sort(key=lambda item: item["id"])
    metrics = {
        "valid_route_rate": _rate(results, "valid_route"),
        "workflow_accuracy": _rate(results, "workflow"),
        "speech_act_accuracy": _rate(results, "speech_act"),
        "viewport_effect_accuracy": _rate(results, "viewport_effect"),
        "asset_effect_accuracy": _rate(results, "asset_effect"),
        "skill_accuracy": _rate(results, "skills"),
        "clarification_accuracy": _rate(results, "needs_clarification"),
        "continuation_accuracy": _rate(results, "continue_existing_workflow"),
    }
    thresholds = fixture["thresholds"]
    threshold_checks = {
        name: metrics[name] >= threshold
        for name, threshold in thresholds.items()
    }
    failure_counts: dict = {}
    for result in results:
        info = result.get("failure") or {}
        if info.get("reason"):
            label = info["reason"]
            if info.get("error_type"):
                label = f"{label}:{info['error_type']}"
            failure_counts[label] = failure_counts.get(label, 0) + 1
    artifact = {
        "schema_version": 1,
        "model": model,
        "transport": "http" if endpoint else "direct",
        "case_count": len(cases),
        "thresholds": thresholds,
        "metrics": metrics,
        "threshold_checks": threshold_checks,
        "failure_counts": failure_counts,
        "results": results,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(artifact, indent=2, ensure_ascii=True) + "\n", encoding="ascii")
    print(json.dumps({"metrics": metrics, "threshold_checks": threshold_checks}, indent=2))
    print(f"results -> {OUTPUT.relative_to(REPO_ROOT)}")
    return 0 if all(threshold_checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(run())
