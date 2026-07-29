"""Generate a concise deterministic P10 workflow-package verification report."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.facility_layout.observation import TrustedFacilityContext
from ai_inspector.facility_layout.semantic_plan import (
    compile_semantic_facility_plan,
)
from ai_inspector.facility_layout.workflows import (
    compile_manufacturing_cell_package,
    compile_warehouse_lane_package,
)


FIXTURES = (
    ROOT / "tests" / "fixtures" / "facility_layout" / "workflows"
)


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="ascii"))


def _verify(name: str, compiler) -> dict:
    fixture = _load(name)
    first = compiler(fixture["spec"])
    second = compiler(fixture["spec"])
    state = TrustedFacilityContext(
        "facility_layout.state",
        fixture["trustedState"],
    )
    evidence = TrustedFacilityContext(
        "facility_layout.evidence",
        fixture["trustedEvidence"],
    )
    sage = compile_semantic_facility_plan(
        first["semanticPlan"],
        state=state,
        evidence=evidence,
    )
    manual = dict(first["manualPlannerRequest"])
    semantic = dict(sage["plannerRequest"])
    manual.pop("requestId", None)
    semantic.pop("requestId", None)
    return {
        "packageType": first["packageType"],
        "packageId": first["packageId"],
        "specFingerprint": first["specFingerprint"],
        "deterministic": first == second,
        "manualAndSageIntentMatch": manual == semantic,
        "previewOnly": first["previewOnly"],
        "reviewRequired": first["reviewRequired"],
        "semanticSummary": sage["semanticSummary"],
        "deferredCodes": sorted(
            {
                item["code"]
                for item in first["deferredItems"]
                if item.get("code")
            }
        ),
    }


def main() -> int:
    result = {
        "phase": "P10",
        "workflowPackages": [
            _verify(
                "warehouse-lane.json",
                compile_warehouse_lane_package,
            ),
            _verify(
                "cnc-tending-cell.json",
                compile_manufacturing_cell_package,
            ),
        ],
    }
    result["ok"] = all(
        item["deterministic"]
        and item["manualAndSageIntentMatch"]
        and item["previewOnly"]
        and item["reviewRequired"]
        for item in result["workflowPackages"]
    )
    print(
        json.dumps(
            result,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
