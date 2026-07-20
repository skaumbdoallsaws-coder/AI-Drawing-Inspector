"""Live functional-interface reasoning smoke against a running InspectorPro server."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def _post(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=150) as response:
        return json.load(response)


def run(base_url: str) -> int:
    base = base_url.rstrip("/")
    checks: list[tuple[str, bool]] = []
    full = _get(f"{base}/api/functional-relationships/100001")
    part = _get(f"{base}/api/functional-relationships/100001/part/100006")
    assembly = _get(f"{base}/api/assembly-context/100006")
    checks.extend(
        [
            ("graph validates", full.get("validation", {}).get("ok") is True),
            ("all physical instances covered", full.get("validation", {}).get("coverage", {}).get("covered_instance_count") == 38),
            ("graph exposes forty interfaces", len(full.get("graph", {}).get("interfaces") or []) == 40),
            ("part context has cylinder guide", any(item.get("pattern_id") == "piston-cylinder-guide" for item in part.get("functional_relationships") or [])),
            ("upper cylinder block is explicit gap", any(item.get("entity_id") == "external:upper-cylinder-block" and item.get("presence") == "absent_from_extract" for item in part.get("functional_relationship_summary", {}).get("external_entities") or [])),
        ]
    )

    parts = [
        {
            "part_number": item.get("part_number"),
            "description": item.get("description", ""),
            "color_name": item.get("color_name", ""),
        }
        for item in assembly.get("part_color_legend") or []
        if item.get("part_number")
    ]
    payload = {
        "message": "What is the impact of the failed dimension on the assembly?",
        "history": [],
        "agent_type": "deviation-analyst",
        "session_id": "functional-relationship-live-smoke",
        "inspection_context": {
            "attachments": {
                "part": {"part_number": "100006", "part_name": "Piston"},
                "inspection": {
                    "fai_characteristics": [
                        {
                            "char_number": 1,
                            "description": "Main outside diameter of the piston body",
                            "nominal": 90.0,
                            "tol_plus": 0.05,
                            "tol_minus": 0.05,
                            "measured": 92.0,
                            "status": "FAIL",
                            "unit": "mm",
                        }
                    ]
                },
                "selection": {"available_parts": parts},
                "assembly": {
                    "assembly_number": "100001",
                    "mate_relationships": assembly.get("all_mate_relationships") or [],
                    "part_properties": assembly.get("part_properties") or [],
                    "part_color_legend": assembly.get("part_color_legend") or [],
                },
                "session": {
                    "active_tab": "assembly",
                    "active_mode": "assembly",
                    "mode_contract": {"tab": "assembly", "mode": "assembly", "state": {}},
                },
                "viewport": {
                    "state": {
                        "active_tab": "assembly",
                        "motion_playing": False,
                        "highlighted": [],
                        "hidden": [],
                    },
                    "part_legend": parts,
                },
            }
        },
    }
    result = _post(f"{base}/api/agent/chat", payload)
    answer = str(result.get("response") or "")
    lowered = answer.lower()
    skill_runtime = result.get("skill_runtime") or {}
    selected_skills = {
        str(item.get("id"))
        for item in skill_runtime.get("selection") or []
        if isinstance(item, dict)
    }
    checks.extend(
        [
            ("trace skill selected", "trace-assembly-impact" in selected_skills),
            (
                "answer identifies cylinder guide",
                "piston-cylinder-guide" in lowered
                or "cylinder bore" in lowered
                or "guides the piston" in lowered
                or "cylinder block and bore" in lowered,
            ),
            ("answer explains clearance consequence", "clearance" in lowered and any(word in lowered for word in ("reduce", "interference", "bind"))),
            (
                "answer explains assembly function",
                any(
                    word in lowered
                    for word in ("reciprocating", "translation", "travel", "motion", "operation", "assembly")
                ),
            ),
            (
                "answer states missing mating evidence",
                "not present" in lowered
                or "without the upper cylinder block" in lowered
                or "mating cylinder bore" in lowered
                or ("need" in lowered and "cylinder bore" in lowered)
                or "exact interference or failure mode is not determined" in lowered,
            ),
            ("answer does not claim proven no-fit", "will not fit" not in lowered and "cannot fit" not in lowered),
            ("read-only question emits no tools", not (result.get("tool_calls") or [])),
        ]
    )

    failures = 0
    for name, passed in checks:
        print(("PASS " if passed else "FAIL ") + name)
        if not passed:
            failures += 1
    print("ANSWER: " + answer)
    print(f"{len(checks) - failures}/{len(checks)} checks passed")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8021")
    args = parser.parse_args()
    return run(args.base_url)


if __name__ == "__main__":
    raise SystemExit(main())
