"""Run the source-controlled parts-manual customer-pilot release gate."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]


def _run(name: str, command: list[str], report: dict[str, object]) -> bool:
    print(f"\n=== {name} ===", flush=True)
    started = time.monotonic()
    completed = subprocess.run(command, cwd=ROOT, check=False)
    row = {
        "command": command,
        "durationSeconds": round(time.monotonic() - started, 3),
        "returnCode": completed.returncode,
    }
    report["stages"].append({"name": name, **row})
    print(
        f"{'PASS' if completed.returncode == 0 else 'FAIL'} {name} "
        f"({row['durationSeconds']}s)",
        flush=True,
    )
    return completed.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify InspectorPro's parts-manual pilot release path."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8125")
    parser.add_argument("--assembly", default="MMLE-50D")
    parser.add_argument("--minimum-occurrences", type=int, default=200)
    parser.add_argument("--expected-pages", type=int, default=15)
    parser.add_argument("--expected-technical-pages", type=int, default=12)
    parser.add_argument(
        "--live-only",
        action="store_true",
        help="Run only the live production publication proof.",
    )
    args = parser.parse_args()

    output_dir = ROOT / ".runtime" / "parts_manual_pilot_verification"
    output_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "assembly": args.assembly,
        "baseUrl": args.base_url.rstrip("/"),
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "stages": [],
    }
    python = sys.executable
    commands: list[tuple[str, list[str]]] = []
    if not args.live_only:
        basetemp = output_dir / f"pytest-{time.time_ns()}"
        commands.extend(
            [
                (
                    "deterministic unit and contract tests",
                    [
                        python,
                        "-m",
                        "pytest",
                        "tests/test_documentation_library_assembly.py",
                        "tests/test_parts_manual_ui_contract.py",
                        "tests/test_part_number_registry.py",
                        "tests/test_assembly_knowledge_assembly_profile.py",
                        "tests/test_parts_manual.py",
                        "-q",
                        f"--basetemp={basetemp}",
                        "-p",
                        "no:cacheprovider",
                    ],
                ),
                (
                    "cross-assembly technical samples",
                    [python, "-u", "tests/smoke_parts_manual_technical_samples.py"],
                ),
                (
                    "isolated Sage publication",
                    [python, "-u", "tests/smoke_parts_manual_sage_publication.py"],
                ),
            ]
        )
    commands.append(
        (
            "live customer-pilot publication",
            [
                python,
                "-u",
                "tests/smoke_parts_manual_pilot_publication.py",
                "--base-url",
                args.base_url.rstrip("/"),
                "--assembly",
                args.assembly,
                "--minimum-occurrences",
                str(args.minimum_occurrences),
                "--expected-pages",
                str(args.expected_pages),
                "--expected-technical-pages",
                str(args.expected_technical_pages),
            ],
        )
    )

    passed = True
    for name, command in commands:
        if not _run(name, command, report):
            passed = False
            break
    report["status"] = "PASS" if passed else "FAIL"
    report["finishedAt"] = datetime.now(timezone.utc).isoformat()
    report_path = output_dir / "summary.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nPilot verification: {report['status']}", flush=True)
    print(f"Report: {report_path}", flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
