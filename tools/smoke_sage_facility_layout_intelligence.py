"""Read-only semantic smoke check for the currently saved Facility Layout."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_inspector.facility_layout.chat_context import (  # noqa: E402
    FACILITY_ANALYSIS_DIGEST_MAXIMUM_BYTES,
    build_facility_analysis_digest,
)
from ai_inspector.facility_layout.host import (  # noqa: E402
    LOCAL_LAYOUT_ID,
    LOCAL_SITE_ID,
    LocalFacilityLayoutHost,
)
from ai_inspector.facility_layout.semantic_model import (  # noqa: E402
    build_facility_semantic_map,
)


DEFAULT_ROOT = REPO_ROOT / ".runtime" / "facility-layout"
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "runtime_logs"
    / "sage_facility_layout_live_semantic_smoke.json"
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def _layout_path(root: Path) -> Path:
    return (
        root
        / "layouts"
        / "local"
        / LOCAL_SITE_ID
        / "layouts"
        / f"{LOCAL_LAYOUT_ID}.json"
    )


def _semantic_pages(
    host: LocalFacilityLayoutHost,
    *,
    revision: str,
    view: str,
    turn_id: str,
) -> tuple[list[dict[str, Any]], int]:
    records: list[dict[str, Any]] = []
    cursor: str | None = None
    total_count = 0
    for _page_index in range(8):
        arguments: dict[str, Any] = {
            "view": view,
            "pageSize": 50,
        }
        if cursor:
            arguments["cursor"] = cursor
        page = host.agent_runtime.execute_read_tool(
            host.principal(),
            site_id=LOCAL_SITE_ID,
            layout_id=LOCAL_LAYOUT_ID,
            expected_revision=revision,
            tool_name="inspect_facility_semantics",
            arguments=arguments,
            turn_id=turn_id,
        )
        total_count = int(page.get("totalCount") or total_count)
        records.extend(
            dict(item)
            for item in page.get("records", [])
            if isinstance(item, dict)
        )
        cursor = page.get("nextCursor")
        if not cursor:
            return records, total_count
    raise RuntimeError(
        f"Semantic view '{view}' exceeded the eight-page smoke bound."
    )


def run_saved_layout_smoke(root: str | Path) -> dict[str, Any]:
    facility_root = Path(root).resolve()
    layout_path = _layout_path(facility_root)
    if not layout_path.is_file():
        raise FileNotFoundError(
            f"Saved Facility Layout does not exist: {layout_path}"
        )

    before = layout_path.read_bytes()
    before_mtime_ns = layout_path.stat().st_mtime_ns
    before_sha256 = _sha256(before)
    host = LocalFacilityLayoutHost(
        facility_root,
        process_map_root=REPO_ROOT / "generated" / "training",
        private_assets=True,
    )
    try:
        principal = host.principal()
        current = host.service.get_layout(
            principal,
            LOCAL_SITE_ID,
            LOCAL_LAYOUT_ID,
        )
        revision = str(current["revision"])
        bundle = host.agent_runtime.resolve_context(
            principal,
            site_id=LOCAL_SITE_ID,
            layout_id=LOCAL_LAYOUT_ID,
            expected_revision=revision,
        )
        projected = build_facility_analysis_digest(
            bundle.digest,
            bundle.state,
        )
        overview = host.agent_runtime.execute_read_tool(
            principal,
            site_id=LOCAL_SITE_ID,
            layout_id=LOCAL_LAYOUT_ID,
            expected_revision=revision,
            tool_name="inspect_facility_semantics",
            arguments={"view": "overview"},
            turn_id="saved-layout-semantic-smoke",
        )
        departments, department_total = _semantic_pages(
            host,
            revision=revision,
            view="departments",
            turn_id="saved-layout-semantic-smoke",
        )
        semantic = build_facility_semantic_map(bundle.state)
    finally:
        host.close()

    after = layout_path.read_bytes()
    after_mtime_ns = layout_path.stat().st_mtime_ns
    summary = overview["facilitySummary"]
    operational = summary["spatialMetrics"][
        "operationallyUsableFreeArea"
    ]
    blockers = summary["spatialMetrics"]["completeness"]["blockers"]
    department_ids = sorted(
        str(item.get("zoneId"))
        for item in departments
        if item.get("zoneId")
    )
    unknown_assets = sorted(
        str(item.get("assetId"))
        for item in semantic.get("assets", [])
        if item.get("semanticType") == "unknown"
        or item.get("semanticTypeEvidenceStatus") == "unknown"
    )
    assertions = {
        "layoutBytesUnchanged": after == before,
        "layoutTimestampUnchanged": after_mtime_ns == before_mtime_ns,
        "repositoryRevisionMatchesSavedBytes": revision == before_sha256,
        "trustedRevisionMatchesRepository": (
            bundle.state["identity"]["revision"] == revision
        ),
        "analysisContextWithinBound": (
            projected["canonicalUtf8Bytes"]
            <= FACILITY_ANALYSIS_DIGEST_MAXIMUM_BYTES
        ),
        "analysisContextExcludesRawPlacements": (
            "placements" not in projected
        ),
        "zoneIndexIsComplete": (
            len(projected.get("zoneIndex", [])) == summary["zoneCount"]
        ),
        "departmentPaginationIsComplete": (
            len(department_ids)
            == department_total
            == summary["departmentCount"]
        ),
        "allCatalogAssetsHaveSemanticMeaning": not unknown_assets,
        "gatedOperationalAreaHasEvidence": (
            (
                operational.get("evidenceStatus") == "derived"
                and operational.get("areaSquareMeters") is not None
            )
            or (
                operational.get("evidenceStatus") == "unknown"
                and operational.get("areaSquareMeters") is None
                and bool(blockers)
            )
        ),
    }
    return {
        "status": (
            "passed" if all(assertions.values()) else "failed"
        ),
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z"),
        "gitCommit": _git_commit(),
        "providerCalls": 0,
        "networkCalls": 0,
        "mode": "read_only_saved_layout_smoke",
        "layout": {
            "path": str(layout_path),
            "revision": revision,
            "sha256Before": before_sha256,
            "sha256After": _sha256(after),
            "byteSize": len(before),
        },
        "counts": {
            "placements": summary["placementCount"],
            "zones": summary["zoneCount"],
            "departments": summary["departmentCount"],
            "floorMarkings": summary["floorMarkingCount"],
            "routes": summary["routeCount"],
            "catalogAssets": len(bundle.state.get("assets", [])),
            "assetRoleTypes": len(overview.get("assetRoleSummary", [])),
        },
        "context": {
            "canonicalUtf8Bytes": projected["canonicalUtf8Bytes"],
            "maximumBytes": FACILITY_ANALYSIS_DIGEST_MAXIMUM_BYTES,
            "zoneIndexCount": len(projected.get("zoneIndex", [])),
            "departmentIds": department_ids,
        },
        "evidence": {
            "operationalFreeAreaStatus": operational.get(
                "evidenceStatus"
            ),
            "operationalFreeAreaBlockerCodes": sorted(
                str(item.get("code"))
                for item in blockers
                if isinstance(item, dict) and item.get("code")
            ),
            "unknownAssetSemanticIds": unknown_assets,
        },
        "assertions": assertions,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a no-provider, read-only semantic smoke against the saved "
            "Facility Layout repository."
        )
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--quiet", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    report = run_saved_layout_smoke(args.root)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True)
        + "\n",
        encoding="ascii",
        newline="\n",
    )
    if not args.quiet:
        counts = report["counts"]
        print(
            "Saved Facility semantic smoke: "
            f"{report['status']} - {counts['placements']} placements, "
            f"{counts['zones']} zones, {counts['departments']} departments"
        )
        print(
            "Layout bytes unchanged: "
            f"{report['assertions']['layoutBytesUnchanged']}"
        )
        print(f"Evidence: {output}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
