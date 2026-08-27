"""Run the source-bound Sage Facility Layout intelligence gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_inspector.facility_layout.intelligence_evaluation import (  # noqa: E402
    evaluate_sage_facility_layout_intelligence,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate deterministic Facility semantics, geometry, tools, "
            "intent, context, catalog coverage, and action boundaries."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            REPO_ROOT
            / "runtime_logs"
            / "sage_facility_layout_intelligence_evaluation.json"
        ),
    )
    parser.add_argument("--fixture", type=Path)
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Write the artifact without printing the summary.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    report = evaluate_sage_facility_layout_intelligence(
        REPO_ROOT,
        fixture_path=args.fixture,
    )
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
        newline="\n",
    )
    if not args.quiet:
        summary = report["summary"]
        print(
            "Sage Facility Layout intelligence: "
            f"{report['status']} - "
            f"{summary['passedCount']}/{summary['checkCount']} checks, "
            f"{len(report['gates'])} gates, "
            f"{summary['structuralConversationCaseCount']} conversation cases"
        )
        print(f"Evidence: {output}")
        print(
            "Claim boundary: deterministic contract/oracle only; "
            "provider calls = 0."
        )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
