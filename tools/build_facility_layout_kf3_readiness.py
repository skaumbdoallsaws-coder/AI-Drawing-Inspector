"""Build the reproducible KF3 asset-library readiness audit."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.facility_layout.host import (
    LOCAL_ASSET_CATALOG,
    build_private_local_asset_catalog,
)
from ai_inspector.facility_layout.planning_readiness import (
    compile_asset_catalog_planning_readiness,
)


OUTPUT = ROOT / "docs" / "facility-layout-kf3-asset-readiness-report.json"


def build_report() -> dict:
    private_assets = build_private_local_asset_catalog(ROOT)
    assets_by_revision = {
        (item["assetId"], item["assetDefinitionRevision"]): item
        for item in (*LOCAL_ASSET_CATALOG, *private_assets)
    }
    compiled = compile_asset_catalog_planning_readiness(
        list(assets_by_revision.values())
    )
    direction_statuses: Counter[str] = Counter()
    levels: Counter[str] = Counter()
    blocker_codes: Counter[str] = Counter()
    asset_rows = []
    for asset in compiled["assets"]:
        levels[asset["readiness"]["level"]] += 1
        blocker_codes.update(asset["readiness"]["blockerCodes"])
        for record in asset["directionalInterfaces"]["requiredRoles"].values():
            direction_statuses[record["evidenceStatus"]] += 1
        asset_rows.append({
            "assetId": asset["assetId"],
            "assetDefinitionRevision": asset["assetDefinitionRevision"],
            "displayName": asset["displayName"],
            "category": asset["category"],
            "footprintAvailable": asset["physicalEnvelope"]["footprint"][
                "available"
            ],
            "heightAvailable": asset["physicalEnvelope"]["height"][
                "available"
            ],
            "readinessLevel": asset["readiness"]["level"],
            "controlledPlanningReady": asset["readiness"][
                "controlledPlanningReady"
            ],
            "clearanceRecordCount": asset["clearances"]["recordCount"],
            "blockerCodes": asset["readiness"]["blockerCodes"],
            "unresolvedEvidenceCount": len(
                asset["readiness"]["unresolvedEvidenceCodes"]
            ),
        })
    return {
        "reportKind": "facility_layout_kf3_asset_readiness",
        "planningReadinessVersion": compiled["planningReadinessVersion"],
        "scope": {
            "builtInAssetRevisionCount": len(LOCAL_ASSET_CATALOG),
            "privateAssetRevisionCount": len(private_assets),
            "uniqueAssetRevisionCount": compiled["assetCount"],
        },
        "summary": {
            "revisionBoundFootprintCount": compiled[
                "revisionBoundFootprintCount"
            ],
            "unavailableCount": compiled["unavailableCount"],
            "controlledPlanningReadyCount": compiled[
                "controlledPlanningReadyCount"
            ],
            "readinessLevels": dict(sorted(levels.items())),
            "directionalEvidenceStatuses": dict(
                sorted(direction_statuses.items())
            ),
            "blockerCodeCounts": dict(sorted(blocker_codes.items())),
        },
        "conclusions": [
            "Every inventoried asset revision has a revision-bound footprint or is explicitly unavailable.",
            "Missing directional interfaces and clearances remain explicit; no inference is promoted into a hard rule.",
            "The current library is suitable for bounded geometric previews, but controlled planning remains gated by reviewed clearance and planning evidence.",
        ],
        "assets": asset_rows,
    }


def main() -> None:
    report = build_report()
    OUTPUT.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="ascii",
    )
    print(
        f"wrote {OUTPUT.relative_to(ROOT)}: "
        f"{report['scope']['uniqueAssetRevisionCount']} revisions"
    )


if __name__ == "__main__":
    main()
