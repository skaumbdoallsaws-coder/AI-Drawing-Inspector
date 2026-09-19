"""Measure the frozen RQ8 deterministic generation and amendment gates."""

from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import PackageNotFoundError, version as package_version
import json
import logging
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Any, Callable

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.facility_layout.canonical import (
    canonical_layout_bytes,
    layout_revision,
)
from ai_inspector.facility_layout.facility_planning import (
    compile_facility_planning_package,
)
from ai_inspector.facility_layout.g1_planner import (
    compile_g1_department_operations,
    compile_g1_envelope_operations,
)
from ai_inspector.facility_layout.host import build_private_local_asset_catalog
from ai_inspector.facility_layout.knowledge_foundation import (
    facility_knowledge_revision,
)
from ai_inspector.facility_layout.operations import (
    apply_prevalidated_facility_layout_operations,
)
from ai_inspector.facility_layout.program_execution import (
    amend_facility_program_resource_batch,
    compile_facility_program_operation_plan,
    execute_facility_program_operation_plan,
)
from ai_inspector.facility_layout.reference_performance import (
    REFERENCE_PERFORMANCE_SCHEMA,
    summarize_timing_samples,
    validate_reference_performance_artifact,
)

PACKAGE_PATH = (
    ROOT
    / "generated"
    / "facility_planning"
    / "mmle-50d"
    / "mmle-50d-facility-planning-package-v1.json"
)
BASE_LAYOUT_PATH = (
    ROOT
    / ".runtime"
    / "facility-layout"
    / "layouts"
    / "local"
    / "site-local"
    / "layouts"
    / "fl-main.json"
)
BROWSER_EVIDENCE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "reference_quality"
    / "browser-evidence.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "reference_quality"
    / "performance-evaluation.json"
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _command(*args: str) -> str | None:
    try:
        result = subprocess.run(
            list(args),
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = (result.stdout or result.stderr).strip()
    return value or None


def _package_version(name: str) -> str | None:
    try:
        return package_version(name)
    except PackageNotFoundError:
        return None


def _machine() -> dict[str, Any]:
    try:
        import psutil

        physical_cores = psutil.cpu_count(logical=False)
        logical_processors = psutil.cpu_count(logical=True)
        ram_bytes = int(psutil.virtual_memory().total)
    except (ImportError, AttributeError):
        physical_cores = None
        logical_processors = os.cpu_count()
        ram_bytes = None
    return {
        "os": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "processor": platform.processor(),
        "physicalCores": physical_cores,
        "logicalProcessors": logical_processors,
        "ramBytes": ram_bytes,
        "python": platform.python_version(),
        "pythonExecutable": sys.executable,
        "serverWorkerCount": 1,
        "powerCondition": "AC power; no intentional competing benchmark workload",
    }


def _chromium() -> dict[str, Any]:
    with sync_playwright() as playwright:
        executable = Path(playwright.chromium.executable_path).resolve()
        browser = playwright.chromium.launch(headless=True)
        browser_version = browser.version
        browser.close()
    revision = next(
        (
            part
            for part in executable.parts
            if part.casefold().startswith("chromium-")
        ),
        None,
    )
    return {
        "playwrightVersion": _package_version("playwright"),
        "executable": str(executable),
        "executableSha256": _sha256(executable),
        "revision": revision,
        "version": browser_version,
    }


def _measure(function: Callable[[], Any], samples: int) -> tuple[Any, list[float]]:
    last = None
    values = []
    for _index in range(samples):
        started = time.perf_counter()
        last = function()
        values.append((time.perf_counter() - started) * 1000.0)
    return last, values


def _browser_evidence_summary(browser: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": str(BROWSER_EVIDENCE_PATH),
        "exactCounts": browser.get("draft"),
        "savedLayoutUnchanged": browser.get("savedLayoutUnchanged") is True,
        "undoRestoredBlankBase": browser.get("undoRestoredBlankBase") is True,
        "planOccupiedViewportRatio": (
            browser.get("planOverview") or {}
        ).get("occupiedViewportRatio"),
        "threeOccupiedViewportRatio": (
            ((browser.get("threeDiagnostics") or {}).get("lastFit") or {})
            .get("viewportOccupancy", {})
            .get("maximumRatio")
        ),
    }


def _macro_preview(
    base: dict[str, Any], program: dict[str, Any]
) -> dict[str, Any]:
    envelope = program["facility_envelope"]
    compiled_envelope = compile_g1_envelope_operations(
        base,
        {
            "width": envelope["width"],
            "depth": envelope["depth"],
            "sourceUnit": envelope["source_unit"],
            "displayName": envelope["display_name"],
            "gridSize": envelope["grid_size"],
        },
        replace_existing=False,
    )
    working = apply_prevalidated_facility_layout_operations(
        base,
        compiled_envelope["operations"],
        base_revision=layout_revision(base),
    )["document"]
    compiled_departments = compile_g1_department_operations(
        working, program["macro_departments"][0]
    )
    working = apply_prevalidated_facility_layout_operations(
        working,
        compiled_departments["operations"],
        base_revision=layout_revision(working),
    )["document"]
    if len(working["zones"]) != 6:
        raise RuntimeError("Macro preview did not create six departments.")
    return working


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--refresh-browser-evidence", action="store_true")
    args = parser.parse_args()
    if args.runs != 20:
        raise SystemExit("The frozen RQ8 qualification requires exactly 20 runs.")

    output = args.output.resolve()
    if args.refresh_browser_evidence:
        artifact = _load(output)
        browser = _load(BROWSER_EVIDENCE_PATH)
        artifact["revisions"]["browserEvidenceSha256"] = _sha256(
            BROWSER_EVIDENCE_PATH
        )
        artifact["revisions"]["inspectorProSource"] = _command(
            "git", "rev-parse", "HEAD"
        )
        artifact["machine"] = {**_machine(), "chromium": _chromium()}
        artifact["browserEvidence"] = _browser_evidence_summary(browser)
        artifact = validate_reference_performance_artifact(artifact)
        output.write_text(
            json.dumps(
                artifact,
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="ascii",
        )
        print(
            json.dumps(
                {
                    "status": artifact["status"],
                    "output": str(output),
                    "browserEvidenceSha256": artifact["revisions"][
                        "browserEvidenceSha256"
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger(
        "ai_inspector.facility_layout.program_execution"
    ).setLevel(logging.DEBUG)

    package = _load(PACKAGE_PATH)
    base = _load(BASE_LAYOUT_PATH)
    base_bytes = canonical_layout_bytes(base)
    browser = _load(BROWSER_EVIDENCE_PATH)
    catalog = list(build_private_local_asset_catalog(ROOT))
    compiled = compile_facility_planning_package(package, catalog)
    if compiled["blockingFindingCount"]:
        raise RuntimeError("The frozen planning package has blocking findings.")
    program = compiled["facilityProgram"]

    print("RQ8 warmup: macro preview", flush=True)
    warmup_macro = _macro_preview(base, program)
    print("RQ8 warmup: full operation-plan compile", flush=True)
    warmup_plan = compile_facility_program_operation_plan(program, base, catalog)
    print("RQ8 warmup: full operation-plan execute", flush=True)
    warmup_full = execute_facility_program_operation_plan(base, warmup_plan)
    expected_counts = {
        "zones": 45,
        "routes": 8,
        "placements": 827,
        "floorMarkings": 50,
    }
    if warmup_full["counts"] != expected_counts or warmup_full["saved"]:
        raise RuntimeError("The warmup full-reference result is invalid.")

    amendment_batch = next(
        item
        for item in program["resource_batches"]
        if item["batch_id"] == "raw-material-racks"
    )
    amendment_patch = {"quantity": amendment_batch["quantity"] - 1}
    print("RQ8 warmup: local resource amendment", flush=True)
    warmup_amendment = amend_facility_program_resource_batch(
        warmup_full["draftLayout"],
        program,
        catalog,
        batch_id=amendment_batch["batch_id"],
        patch=amendment_patch,
    )
    if warmup_amendment["saved"] or (
        warmup_amendment["undoLayout"] != warmup_full["draftLayout"]
    ):
        raise RuntimeError("The warmup local amendment is not exactly undoable.")

    _last_macro, macro_samples = _measure(
        lambda: _macro_preview(base, program), args.runs
    )

    def full_cycle() -> dict[str, Any]:
        plan = compile_facility_program_operation_plan(program, base, catalog)
        result = execute_facility_program_operation_plan(base, plan)
        if result["counts"] != expected_counts or result["saved"]:
            raise RuntimeError("A measured full-reference result is invalid.")
        if canonical_layout_bytes(result["undoLayout"]) != base_bytes:
            raise RuntimeError("A measured full-reference Undo changed the base.")
        return {"plan": plan, "result": result}

    last_full, full_samples = _measure(full_cycle, args.runs)

    def amendment_cycle() -> dict[str, Any]:
        result = amend_facility_program_resource_batch(
            warmup_full["draftLayout"],
            program,
            catalog,
            batch_id=amendment_batch["batch_id"],
            patch=amendment_patch,
        )
        if result["saved"] or result["validation"]["status"] != "valid":
            raise RuntimeError("A measured local amendment is invalid.")
        if result["undoLayout"] != warmup_full["draftLayout"]:
            raise RuntimeError("A measured local amendment is not exactly undoable.")
        return result

    last_amendment, amendment_samples = _measure(amendment_cycle, args.runs)

    measurements = {
        "firstMacroPreview": {
            "scope": "frozen FacilityProgram envelope and macro-stage compiler",
            **summarize_timing_samples(
                macro_samples, limit_milliseconds=10_000
            ),
        },
        "fullReferenceGeneration": {
            "scope": "operation-plan compilation plus complete deterministic execution",
            **summarize_timing_samples(
                full_samples, limit_milliseconds=90_000
            ),
        },
        "localResourceAmendment": {
            "scope": "dependency-independent target-area batch replacement plus deterministic validation",
            "batchId": amendment_batch["batch_id"],
            "patch": amendment_patch,
            **summarize_timing_samples(
                amendment_samples, limit_milliseconds=10_000
            ),
        },
    }
    artifact = {
        "schemaVersion": REFERENCE_PERFORMANCE_SCHEMA,
        "status": (
            "pass"
            if all(item["passed"] for item in measurements.values())
            else "fail"
        ),
        "protocol": {
            "discardedWarmupRuns": 1,
            "measuredRuns": 20,
            "percentileMethod": "nearest_rank",
            "clock": "time.perf_counter",
            "processCount": 1,
            "providerCallsIncluded": False,
        },
        "machine": {**_machine(), "chromium": _chromium()},
        "revisions": {
            "inspectorProSource": _command("git", "rev-parse", "HEAD"),
            "planningPackageSha256": _sha256(PACKAGE_PATH),
            "planningPackageRevision": compiled["planningPackageRevision"],
            "compileRevision": compiled["compileRevision"],
            "facilityProgramRevision": warmup_plan["programRevision"],
            "operationPlanRevision": warmup_plan["planRevision"],
            "assetCatalogRevision": facility_knowledge_revision(catalog),
            "browserEvidenceSha256": _sha256(BROWSER_EVIDENCE_PATH),
        },
        "measurements": measurements,
        "browserEvidence": _browser_evidence_summary(browser),
        "providerTiming": {
            "included": False,
            "reason": (
                "RQ8 deterministic gates exclude variable provider and network latency; "
                "the live Sage browser proof is revision-bound separately."
            ),
        },
    }
    artifact = validate_reference_performance_artifact(artifact)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(artifact, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    print(
        json.dumps(
            {
                "status": artifact["status"],
                "output": str(output),
                "p95Milliseconds": {
                    key: value["p95Milliseconds"]
                    for key, value in measurements.items()
                },
                "finalDraftRevision": last_full["result"]["draftLayoutRevision"],
                "amendedDraftRevision": last_amendment["draftLayoutRevision"],
                "macroZoneCount": len(warmup_macro["zones"]),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if artifact["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
