"""Generate the Phase 0 agent-skills telemetry and prompt baseline.

Usage:
    python tools/agent_skills_phase0_baseline.py
    python tools/agent_skills_phase0_baseline.py --db path/to/metrics.sqlite

The generated JSON is the machine-readable snapshot. The Markdown file is a
short review surface. Neither file contains prompts, responses, or API keys.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import server  # noqa: E402
from ai_inspector.telemetry.store import default_db_path  # noqa: E402


DEFAULT_JSON_OUT = REPO_ROOT / "docs" / "agent-skills-phase0-baseline.json"
DEFAULT_MD_OUT = REPO_ROOT / "docs" / "agent-skills-phase0-baseline.md"

CONTEXT_SECTIONS = [
    "[PART]",
    "[MODE]",
    "[DRAWING MODE]",
    "[INSPECTION]",
    "[FACILITY LAYOUT]",
    "[PLANT PROCESS]",
    "[ASSEMBLY TRAINING]",
    "[MOTION]",
    "[MOTION - reference only]",
    "DIMENSIONS THE USER HAS SELECTED",
    "AVAILABLE DIMENSIONS ON THIS DRAWING",
    "AVAILABLE DRAWING VIEWS",
    "PARTS THE USER HAS SELECTED",
    "USER-FACING FEATURES ON THIS PART",
    "AVAILABLE CAD FEATURES ON THIS PART",
    "AVAILABLE SEMANTIC REGIONS ON THIS PART",
    "AVAILABLE PARTS IN THIS ASSEMBLY",
    "PART PHYSICAL PROPERTIES",
    "NEARBY PARTS",
    "MATE RELATIONSHIPS",
    "SOLIDWORKS EXPLODE STEPS",
    "PAUSED WALKTHROUGH",
    "PART FEATURE CHANGES",
    "REVISION CHANGES",
    "GEOMETRY DIFF",
    "FAI TABLE",
    "FAI CHAT COMMANDS",
    "INSPECTION READINESS",
]


def _percentile(values: Iterable[float], pct: float) -> float | None:
    clean = sorted(float(value) for value in values if value is not None and math.isfinite(float(value)))
    if not clean:
        return None
    index = int(math.ceil((pct / 100.0) * len(clean))) - 1
    return clean[max(0, min(index, len(clean) - 1))]


def _rounded(value: float | None, digits: int = 1) -> float | None:
    return round(value, digits) if value is not None else None


def _metric_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    latency = [float(row.get("latencyMs") or 0.0) for row in rows]
    input_tokens = [int(row.get("inputTokens") or 0) for row in rows]
    output_tokens = [int(row.get("outputTokens") or 0) for row in rows]
    total_tokens = [int(row.get("totalTokens") or 0) for row in rows]
    statuses: Dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "unknown")
        statuses[status] = statuses.get(status, 0) + 1
    return {
        "events": len(rows),
        "first_timestamp_utc": rows[0].get("timestampUtc") if rows else None,
        "last_timestamp_utc": rows[-1].get("timestampUtc") if rows else None,
        "statuses": statuses,
        "models": sorted({str(row.get("model") or "") for row in rows if row.get("model")}),
        "latency_ms": {
            "min": _rounded(min(latency) if latency else None),
            "p50": _rounded(_percentile(latency, 50)),
            "p75": _rounded(_percentile(latency, 75)),
            "p90": _rounded(_percentile(latency, 90)),
            "p95": _rounded(_percentile(latency, 95)),
            "p99": _rounded(_percentile(latency, 99)),
            "mean": _rounded(statistics.fmean(latency) if latency else None),
            "max": _rounded(max(latency) if latency else None),
        },
        "input_tokens": {
            "p50": int(_percentile(input_tokens, 50) or 0),
            "p95": int(_percentile(input_tokens, 95) or 0),
            "mean": _rounded(statistics.fmean(input_tokens) if input_tokens else None),
            "total": sum(input_tokens),
        },
        "output_tokens": {
            "p50": int(_percentile(output_tokens, 50) or 0),
            "p95": int(_percentile(output_tokens, 95) or 0),
            "mean": _rounded(statistics.fmean(output_tokens) if output_tokens else None),
            "total": sum(output_tokens),
        },
        "total_tokens": {
            "p50": int(_percentile(total_tokens, 50) or 0),
            "p95": int(_percentile(total_tokens, 95) or 0),
            "mean": _rounded(statistics.fmean(total_tokens) if total_tokens else None),
            "total": sum(total_tokens),
        },
        "latency_thresholds": {
            str(threshold): {
                "within": sum(1 for value in latency if value <= threshold),
                "over": sum(1 for value in latency if value > threshold),
                "over_rate": _rounded(
                    (sum(1 for value in latency if value > threshold) / len(latency)) if latency else 0.0,
                    4,
                ),
            }
            for threshold in (1500, 2000, 2500, 3000, 3500, 4000, 5000)
        },
    }


def _read_telemetry(db_path: Path) -> Dict[str, Any]:
    if not db_path.exists():
        return {"database": str(db_path), "available": False, "workflows": {}}
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = [dict(row) for row in connection.execute(
            "SELECT * FROM telemetry_events WHERE provider='anthropic' ORDER BY timestampUtc"
        )]
    workflows: Dict[str, Any] = {}
    for workflow in ("viewport_intent", "agent_chat"):
        selected = [row for row in rows if row.get("workflow") == workflow]
        workflows[workflow] = _metric_stats(selected)
        by_agent = {}
        for agent_type in sorted({str(row.get("agentType") or "none") for row in selected}):
            by_agent[agent_type] = _metric_stats(
                [row for row in selected if str(row.get("agentType") or "none") == agent_type]
            )
        workflows[workflow]["by_agent_type"] = by_agent
    return {
        "database": str(db_path.relative_to(REPO_ROOT) if db_path.is_relative_to(REPO_ROOT) else db_path),
        "available": True,
        "provider_events": len(rows),
        "workflows": workflows,
    }


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _prompt_inventory() -> Dict[str, Any]:
    agents: Dict[str, Any] = {}
    for agent_type, base_prompt in server.AGENT_PROMPTS.items():
        appendix = server.build_tool_appendix(agent_type)
        specs = server.AGENT_TOOL_SPECS.get(agent_type, [])
        agents[agent_type] = {
            "base_prompt_chars": len(base_prompt),
            "base_prompt_words": len(base_prompt.split()),
            "tool_appendix_chars": len(appendix),
            "combined_static_chars": len(base_prompt + appendix),
            "combined_static_token_estimate_chars_div_4": math.ceil(len(base_prompt + appendix) / 4),
            "tools": [spec["name"] for spec in specs],
            "tool_count": len(specs),
        }

    html = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    dispatcher_start = html.index("async function _dispatchUiAction")
    dispatcher_end = html.index("\n        function ", dispatcher_start)
    dispatcher = html[dispatcher_start:dispatcher_end]
    ui_actions = re.findall(r"case '([^']+)':", dispatcher)

    return {
        "agents": agents,
        "mode_contracts": {
            mode: {
                "label": contract.get("label"),
                "addendum_chars": len(server._mode_system_addendum(mode)),
            }
            for mode, contract in server.MODE_CONTRACTS.items()
        },
        "mode_contract_count": len(server.MODE_CONTRACTS),
        "frontend_ui_actions": ui_actions,
        "frontend_ui_action_count": len(ui_actions),
        "context_sections": CONTEXT_SECTIONS,
        "context_section_count": len(CONTEXT_SECTIONS),
    }


def _timeout_assessment(telemetry: Dict[str, Any]) -> Dict[str, Any]:
    viewport = telemetry.get("workflows", {}).get("viewport_intent", {})
    p95 = (viewport.get("latency_ms") or {}).get("p95")
    threshold = (viewport.get("latency_thresholds") or {}).get("2000", {})
    shadow_timeout = int(math.ceil((float(p95 or 0) * 1.5) / 250.0) * 250) if p95 else None
    return {
        "previous_candidate_timeout_ms": 2000,
        "observed_calls_over_2000_ms": threshold.get("over"),
        "observed_over_2000_rate": threshold.get("over_rate"),
        "measured_p95_ms": p95,
        "phase2_shadow_timeout_ms": shadow_timeout,
        "serial_production_status": "not_approved",
        "decision": (
            "A 2000 ms serial timeout is not viable for the current classifier. "
            "Use the measured shadow budget while optimizing; approve a serial router only after "
            "latency and total-turn token targets are met."
        ),
    }


def build_snapshot(db_path: Path) -> Dict[str, Any]:
    telemetry = _read_telemetry(db_path)
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git_head(),
        "phase": "agent-skills-phase0",
        "telemetry": telemetry,
        "timeout_assessment": _timeout_assessment(telemetry),
        "prompt_and_capability_inventory": _prompt_inventory(),
        "frozen_regression_bars": [
            "tests/test_viewport_intent_mapping.js",
            "tests/test_viewport_authorization_parity.py",
            "tests/test_fai_response_grounding.py",
            "tests/test_viewport_intent_classifier.py",
            "tests/test_mode_contract.py",
            "tests/test_agent_response_encoding.py",
            "tests/smoke_fai_motion_contract.py",
        ],
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:,.1f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def render_markdown(snapshot: Dict[str, Any]) -> str:
    telemetry = snapshot["telemetry"]
    viewport = telemetry.get("workflows", {}).get("viewport_intent", {})
    chat = telemetry.get("workflows", {}).get("agent_chat", {})
    timeout = snapshot["timeout_assessment"]
    inventory = snapshot["prompt_and_capability_inventory"]
    lines = [
        "# Agent Skills Phase 0 Baseline",
        "",
        f"Generated: `{snapshot['generated_at_utc']}`",
        f"Git HEAD: `{snapshot['git_head']}`",
        f"Telemetry database: `{telemetry.get('database')}`",
        "",
        "## Classifier Baseline",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Calls | {_fmt(viewport.get('events'))} |",
        f"| Success | {_fmt((viewport.get('statuses') or {}).get('success', 0))} |",
        f"| Latency p50 | {_fmt((viewport.get('latency_ms') or {}).get('p50'))} ms |",
        f"| Latency p95 | {_fmt((viewport.get('latency_ms') or {}).get('p95'))} ms |",
        f"| Latency p99 | {_fmt((viewport.get('latency_ms') or {}).get('p99'))} ms |",
        f"| Input tokens p50 | {_fmt((viewport.get('input_tokens') or {}).get('p50'))} |",
        f"| Input tokens p95 | {_fmt((viewport.get('input_tokens') or {}).get('p95'))} |",
        f"| Total tokens / call mean | {_fmt((viewport.get('total_tokens') or {}).get('mean'))} |",
        "",
        "A 2,000 ms serial timeout would reject "
        f"`{_fmt(timeout.get('observed_calls_over_2000_ms'))}` observed calls "
        f"(`{_fmt((timeout.get('observed_over_2000_rate') or 0) * 100)}%`). "
        f"The Phase 2 shadow timeout derived from 1.5 x p95 is `{_fmt(timeout.get('phase2_shadow_timeout_ms'))} ms`. "
        "Serial production routing remains unapproved until it is optimized and remeasured.",
        "",
        "## Main Agent Baseline",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Calls | {_fmt(chat.get('events'))} |",
        f"| Latency p50 | {_fmt((chat.get('latency_ms') or {}).get('p50'))} ms |",
        f"| Latency p95 | {_fmt((chat.get('latency_ms') or {}).get('p95'))} ms |",
        f"| Input tokens p50 | {_fmt((chat.get('input_tokens') or {}).get('p50'))} |",
        f"| Input tokens p95 | {_fmt((chat.get('input_tokens') or {}).get('p95'))} |",
        "",
        "## Static Prompt and Tool Inventory",
        "",
        "| Agent | Base chars | Tool appendix chars | Combined chars | Approx. static tokens | Tools |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for agent_type, item in inventory["agents"].items():
        lines.append(
            f"| {agent_type} | {_fmt(item['base_prompt_chars'])} | {_fmt(item['tool_appendix_chars'])} | "
            f"{_fmt(item['combined_static_chars'])} | {_fmt(item['combined_static_token_estimate_chars_div_4'])} | "
            f"{_fmt(item['tool_count'])} |"
        )
    lines += [
        "",
        f"Mode contracts: `{inventory['mode_contract_count']}`",
        f"Frontend UI action types: `{inventory['frontend_ui_action_count']}`",
        f"Context sections inventoried: `{inventory['context_section_count']}`",
        "",
        "Mode addendum sizes:",
        "",
    ]
    for mode, item in inventory["mode_contracts"].items():
        lines.append(f"- `{mode}`: `{item['addendum_chars']}` characters")
    lines += [
        "",
        "## Frozen Regression Bars",
        "",
    ]
    lines.extend(f"- `{path}`" for path in snapshot["frozen_regression_bars"])
    lines += [
        "",
        "The complete tool names, UI action types, context-section inventory, per-agent telemetry, "
        "threshold counts, and token totals are in `agent-skills-phase0-baseline.json`.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=default_db_path())
    parser.add_argument("--json-out", type=Path, default=DEFAULT_JSON_OUT)
    parser.add_argument("--md-out", type=Path, default=DEFAULT_MD_OUT)
    args = parser.parse_args()

    db_path = args.db if args.db.is_absolute() else (REPO_ROOT / args.db)
    snapshot = build_snapshot(db_path.resolve())
    json_out = args.json_out if args.json_out.is_absolute() else (REPO_ROOT / args.json_out)
    md_out = args.md_out if args.md_out.is_absolute() else (REPO_ROOT / args.md_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(snapshot, indent=2, ensure_ascii=True) + "\n", encoding="ascii")
    md_out.write_text(render_markdown(snapshot), encoding="ascii")
    print(json.dumps({
        "json": str(json_out),
        "markdown": str(md_out),
        "classifier_events": snapshot["telemetry"].get("workflows", {}).get("viewport_intent", {}).get("events", 0),
        "classifier_p50_ms": snapshot["telemetry"].get("workflows", {}).get("viewport_intent", {}).get("latency_ms", {}).get("p50"),
        "classifier_p95_ms": snapshot["telemetry"].get("workflows", {}).get("viewport_intent", {}).get("latency_ms", {}).get("p95"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
