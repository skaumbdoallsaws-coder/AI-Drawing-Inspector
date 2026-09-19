"""Run the frozen Facility Layout reference-quality Level-B benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.facility_layout.host import build_private_local_asset_catalog
from ai_inspector.facility_layout.reference_benchmark import (
    evaluate_reference_generalization,
)


DEFAULT_OUTPUT = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "reference_quality"
    / "level-b-evaluation.json"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    catalog = build_private_local_asset_catalog(ROOT)
    report = evaluate_reference_generalization(catalog)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passedCount"] == report["caseCount"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
