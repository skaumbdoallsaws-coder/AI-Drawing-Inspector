"""Build and audit the synthetic MMLE reference-scale Facility Program."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import logging
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai_inspector.facility_layout.facility_planning import (
    compile_facility_planning_package,
)
from ai_inspector.facility_layout.host import build_private_local_asset_catalog
from ai_inspector.facility_layout.operations import create_layout_document
from ai_inspector.facility_layout.program_execution import (
    compile_facility_program_operation_plan,
    execute_facility_program_operation_plan,
    facility_program_allowed_contact_pairs,
)
from ai_inspector.facility_layout.spatial import diagnose_layout
from tools.build_mmle_facility_planning_package import (
    build_mmle_facility_planning_package,
)


def _base() -> dict[str, Any]:
    return create_layout_document(
        layout_id="fl-mmle-audit",
        display_name="Blank Facility",
        association={"siteId": "site-local", "areaId": "main"},
        coordinate_frame={
            "units": "m",
            "handedness": "right",
            "upAxis": "+Y",
            "floorAxes": ["+X", "+Z"],
            "datumId": "local-origin",
            "floorElevation": 0,
        },
        source_shell_ref={
            "shellId": "shell-local",
            "shellRevision": "a" * 64,
            "coordinateFrameFingerprint": "b" * 64,
        },
        policy_set_ref={
            "policySetId": "policy-local",
            "policySetRevision": "c" * 64,
        },
        created_at="2026-08-29T21:00:00Z",
    )


def _finding_groups(
    layout: Mapping[str, Any], findings: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    placements = {
        str(item.get("placementId") or ""): item
        for item in layout.get("placements", [])
        if isinstance(item, Mapping)
    }
    zones = {
        str(item.get("zoneId") or ""): str(item.get("label") or "")
        for item in layout.get("zones", [])
        if isinstance(item, Mapping)
    }

    def placement_ref(refs: Sequence[Any]) -> Mapping[str, Any] | None:
        for ref in refs:
            if str(ref) in placements:
                return placements[str(ref)]
        return None

    collisions: Counter[tuple[str, str, str]] = Counter()
    exclusions: Counter[tuple[str, str, str]] = Counter()
    aisles: Counter[tuple[str, str]] = Counter()
    for finding in findings:
        refs = [str(item) for item in finding.get("subjectRefs", [])]
        code = str(finding.get("code") or "")
        if code == "placement_collision":
            members = [placements[item] for item in refs if item in placements]
            if len(members) == 2:
                assets = sorted(str(item.get("assetId") or "") for item in members)
                areas = sorted(
                    str((item.get("metadata") or {}).get("targetArea") or "")
                    for item in members
                )
                collisions[(assets[0], assets[1], " | ".join(areas))] += 1
        elif code == "exclusion_zone_violation":
            placement = placement_ref(refs)
            zone_id = next((item for item in refs if item in zones), "")
            if placement is not None:
                exclusions[
                    (
                        str(placement.get("assetId") or ""),
                        str((placement.get("metadata") or {}).get("targetArea") or ""),
                        zones.get(zone_id, ""),
                    )
                ] += 1
        elif code == "aisle_obstructed":
            placement = placement_ref(refs)
            if placement is not None:
                aisles[
                    (
                        str(placement.get("assetId") or ""),
                        str((placement.get("metadata") or {}).get("targetArea") or ""),
                    )
                ] += 1
    return {
        "placementCollisions": [
            {"leftAsset": key[0], "rightAsset": key[1], "areas": key[2], "count": count}
            for key, count in collisions.most_common()
        ],
        "exclusionViolations": [
            {"asset": key[0], "targetArea": key[1], "exclusionArea": key[2], "count": count}
            for key, count in exclusions.most_common()
        ],
        "aisleObstructions": [
            {"asset": key[0], "targetArea": key[1], "count": count}
            for key, count in aisles.most_common()
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--draft-output", type=Path)
    parser.add_argument("--omit-crossings", action="store_true")
    parser.add_argument("--trace", action="store_true")
    args = parser.parse_args()
    if args.trace:
        logging.basicConfig(level=logging.DEBUG, force=True)
    root = args.project_root.resolve()

    started = time.perf_counter()
    catalog = build_private_local_asset_catalog(root)
    package = build_mmle_facility_planning_package(root, asset_catalog=catalog)
    if args.omit_crossings:
        package["floorCommunication"] = [
            item
            for item in package["floorCommunication"]
            if "route_labels" not in item
        ]
    compiled = compile_facility_planning_package(package, catalog)
    after_setup = time.perf_counter()
    plan = compile_facility_program_operation_plan(
        compiled["facilityProgram"], _base(), catalog
    )
    after_compile = time.perf_counter()
    result = execute_facility_program_operation_plan(_base(), plan)
    after_execute = time.perf_counter()
    draft = result["draftLayout"]
    analysis = diagnose_layout(
        draft,
        catalog,
        allowed_contact_pairs=facility_program_allowed_contact_pairs(draft),
    )
    after_audit = time.perf_counter()

    if args.draft_output:
        output = args.draft_output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(draft, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="ascii",
        )

    findings = [item for item in analysis.get("findings", []) if isinstance(item, Mapping)]
    summary = {
        "counts": result["counts"],
        "timingsSeconds": {
            "setup": round(after_setup - started, 3),
            "compile": round(after_compile - after_setup, 3),
            "execute": round(after_execute - after_compile, 3),
            "spatialAudit": round(after_audit - after_execute, 3),
            "total": round(after_audit - started, 3),
        },
        "findingCounts": dict(sorted(Counter(str(item.get("code") or "") for item in findings).items())),
        "blockingFindingCount": sum(item.get("severity") == "error" for item in findings),
        "groups": _finding_groups(draft, findings),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
