"""Generate source-bound P11 Facility Layout release evidence.

This verifier intentionally separates executable evidence from release
readiness. It proves the technical checks that can run now and preserves
literal, human-review, hardware, and licensing gates as explicit blockers.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_inspector.facility_layout.canonical import canonical_layout_bytes
from ai_inspector.facility_layout.host import (
    LOCAL_LAYOUT_ID,
    LOCAL_SITE_ID,
    LocalFacilityLayoutHost,
)
from ai_inspector.facility_layout.feature_flags import (
    FACILITY_LAYOUT_FEATURE_FLAGS,
    FacilityLayoutFeatureFlags,
)
from ai_inspector.facility_layout.identity import (
    FACILITY_IDENTITY_CONFIG_ENV,
    FacilityPrincipalResolver,
)
from ai_inspector.facility_layout.operations import create_layout_document
from ai_inspector.facility_layout.soak_evidence import (
    SOAK_REQUIREMENTS,
    SoakEvidenceError,
    facility_build_identity,
    load_soak_events,
    summarize_soak_events,
)


RELEASE_DIR = (
    ROOT / "tests" / "fixtures" / "facility_layout" / "release"
)
LEGACY_PERFORMANCE_SOURCE = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "rendering"
    / "renderer-benchmark-results.json"
)
BROWSER_PERFORMANCE_RAW = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "performance"
    / "facility-layout-release-performance-raw.json"
)
BROWSER_PERFORMANCE_SUMMARY = BROWSER_PERFORMANCE_RAW.with_name(
    "facility-layout-release-performance-summary.json"
)
MINIMUM_BROWSER_PERFORMANCE_SUMMARY = BROWSER_PERFORMANCE_RAW.with_name(
    "facility-layout-release-performance-minimum-summary.json"
)
MINIMUM_BROWSER_PERFORMANCE_RAW = BROWSER_PERFORMANCE_RAW.with_name(
    "facility-layout-release-performance-minimum-raw.json"
)
BACKEND_PERFORMANCE_SOURCE = BROWSER_PERFORMANCE_RAW.with_name(
    "backend-release-microbenchmark-results.json"
)
STANDARD_HARDWARE_SOURCE = BROWSER_PERFORMANCE_RAW.with_name(
    "standard-hardware-profile.json"
)
MINIMUM_HARDWARE_SOURCE = BROWSER_PERFORMANCE_RAW.with_name(
    "minimum-hardware-profile.json"
)
ACCESSIBILITY_RAW_SOURCE = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "accessibility"
    / "facility-layout-accessibility-raw.json"
)
ACCESSIBILITY_SUMMARY_SOURCE = ACCESSIBILITY_RAW_SOURCE.with_name(
    "facility-layout-accessibility-summary.json"
)
PYTHON_DEPENDENCY_INVENTORY_SOURCE = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "licensing"
    / "python-direct-dependency-inventory.json"
)
REAL_SOAK_EVENT_LEDGER = (
    ROOT
    / ".runtime"
    / "facility_layout"
    / "p11-real-soak-events.json"
)
BENCHMARK_MANIFEST = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "benchmark-fixture-manifest.json"
)
OFFLINE_SOURCE = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "rendering"
    / "three-offline-smoke-result.json"
)
ASSET_READINESS_SOURCE = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "assets"
    / "p2-pilot-asset-readiness.json"
)
VISUAL_DIR = RELEASE_DIR / "visual"
VISUAL_CAPTURE_SOURCE = VISUAL_DIR / "p11-visual-capture.json"
AUTHORIZATION_CONTRACT = (
    ROOT
    / "static"
    / "contracts"
    / "facility-layout-authorization-v1.json"
)
SAFETY_DISCLAIMER = (
    "InspectorPro assists industrial layout planning and validation. "
    "It does not replace required facility, safety, regulatory, or "
    "professional engineering approval."
)
FEATURE_FLAGS = FACILITY_LAYOUT_FEATURE_FLAGS
REQUIRED_VISUAL_VIEWPORTS = (
    (1920, 1080),
    (1440, 960),
    (1366, 768),
    (390, 844),
)
REQUIRED_VISUAL_THEMES = ("light", "dark")
VISUAL_SOURCE_PATHS = (
    "static/index.html",
    "static/facility_layout_app.js",
    "static/facility_layout_editor.js",
    "static/facility_layout_session.js",
    "static/facility_layout_spatial_advisor.js",
    "static/facility_layout_spatial_worker.js",
    "static/facility_layout_three_adapter.js",
    "static/facility_layout_transport.js",
    "static/facility_layout_workspace.css",
    "static/facility_layout_workspace.js",
    "static/vendor/three/0.128.0/build/three.min.js",
    "tools/capture_facility_layout_p11_visuals.py",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="ascii"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="ascii",
        newline="\n",
    )


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _relative(path: Path, root: Path = ROOT) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _artifact(path: Path, root: Path = ROOT) -> dict[str, Any]:
    return {
        "path": _relative(path, root),
        "byteLength": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _png_info(path: Path, root: Path = ROOT) -> dict[str, Any]:
    payload = path.read_bytes()
    if payload[:8] != b"\x89PNG\r\n\x1a\n" or payload[12:16] != b"IHDR":
        raise ValueError(f"{path} is not a PNG artifact.")
    width, height = struct.unpack(">II", payload[16:24])
    return {
        **_artifact(path, root),
        "width": width,
        "height": height,
        "nonempty": len(payload) > 32,
    }


def _source_hashes(paths: Iterable[Path]) -> dict[str, str]:
    return {
        _relative(path): _sha256(path)
        for path in sorted(paths)
    }


def _build_visual_source_binding(
    root: Path = ROOT,
    relative_paths: tuple[str, ...] = VISUAL_SOURCE_PATHS,
) -> dict[str, Any]:
    files = []
    for relative in sorted(relative_paths):
        path = (root / relative).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError(
                f"Visual source escapes the repository: {relative}"
            ) from exc
        if not path.is_file():
            raise FileNotFoundError(
                f"Visual source is missing: {relative}"
            )
        files.append(
            {
                "path": relative,
                "byteLength": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return {
        "algorithm": "sha256",
        "aggregateAlgorithm": "sha256-canonical-json-v1",
        "files": files,
        "aggregateSha256": _sha256_bytes(
            _canonical_json_bytes(files)
        ),
    }


def _visual_source_binding_status(
    captured: Any,
    *,
    root: Path = ROOT,
    relative_paths: tuple[str, ...] = VISUAL_SOURCE_PATHS,
) -> dict[str, Any]:
    current = _build_visual_source_binding(root, relative_paths)
    captured_mapping = captured if isinstance(captured, Mapping) else {}
    captured_files = captured_mapping.get("files")
    if not isinstance(captured_files, list):
        captured_files = []

    captured_by_path: dict[str, Mapping[str, Any]] = {}
    duplicate_paths = []
    for item in captured_files:
        if not isinstance(item, Mapping):
            continue
        relative = str(item.get("path") or "")
        if relative in captured_by_path:
            duplicate_paths.append(relative)
        captured_by_path[relative] = item

    current_by_path = {
        item["path"]: item for item in current["files"]
    }
    captured_paths = set(captured_by_path)
    current_paths = set(current_by_path)
    stale_paths = sorted(
        relative
        for relative in captured_paths & current_paths
        if (
            captured_by_path[relative].get("sha256")
            != current_by_path[relative]["sha256"]
            or int(
                captured_by_path[relative].get("byteLength") or -1
            )
            != current_by_path[relative]["byteLength"]
        )
    )
    missing_paths = sorted(current_paths - captured_paths)
    unexpected_paths = sorted(captured_paths - current_paths)
    algorithms_match = (
        captured_mapping.get("algorithm") == current["algorithm"]
        and captured_mapping.get("aggregateAlgorithm")
        == current["aggregateAlgorithm"]
    )
    input_set_exact = (
        not missing_paths
        and not unexpected_paths
        and not duplicate_paths
        and len(captured_files) == len(current["files"])
    )
    files_match = input_set_exact and not stale_paths
    aggregate_matches = (
        captured_mapping.get("aggregateSha256")
        == current["aggregateSha256"]
    )
    present = bool(captured_mapping)
    matches = (
        present
        and algorithms_match
        and files_match
        and aggregate_matches
    )
    return {
        "present": present,
        "algorithmsMatch": algorithms_match,
        "requiredInputsExact": input_set_exact,
        "filesMatch": files_match,
        "aggregateMatches": aggregate_matches,
        "matches": matches,
        "capturedAggregateSha256": str(
            captured_mapping.get("aggregateSha256") or ""
        ),
        "currentAggregateSha256": current["aggregateSha256"],
        "inputCount": len(current["files"]),
        "missingPaths": missing_paths,
        "unexpectedPaths": unexpected_paths,
        "duplicatePaths": sorted(set(duplicate_paths)),
        "stalePaths": stale_paths,
        "currentFiles": current["files"],
    }


def _recorded_source_status(records: Any) -> dict[str, Any]:
    failures = []
    checked = []
    if not isinstance(records, list) or not records:
        return {
            "matches": False,
            "checked": [],
            "failures": ["source_records_missing"],
        }
    for raw in records:
        if not isinstance(raw, Mapping):
            failures.append("source_record_invalid")
            continue
        relative = str(raw.get("path") or "")
        path = (ROOT / relative).resolve()
        try:
            path.relative_to(ROOT.resolve())
        except ValueError:
            failures.append(f"source_path_outside_repository:{relative}")
            continue
        if not path.is_file():
            failures.append(f"source_file_missing:{relative}")
            continue
        current = _artifact(path)
        checked.append(current)
        recorded_length = raw.get("byteLength")
        if (
            current["sha256"] != raw.get("sha256")
            or (
                recorded_length is not None
                and current["byteLength"] != recorded_length
            )
        ):
            failures.append(f"source_file_changed:{relative}")
    return {
        "matches": not failures and len(checked) == len(records),
        "checked": checked,
        "failures": sorted(set(failures)),
    }


def _hardware_profile(path: Path, role: str) -> dict[str, Any]:
    if not path.is_file():
        return {
            "role": role,
            "status": "unresolved",
            "releaseGateMet": False,
            "blockers": [f"{role}_reference_hardware_unresolved"],
        }
    profile = _read_json(path)
    source = profile.get("source")
    source_status = _recorded_source_status(
        [source] if isinstance(source, Mapping) else []
    )
    valid = (
        profile.get("schemaVersion")
        == "facility-layout-reference-hardware-v1"
        and profile.get("role") == role
        and profile.get("status") == "measured"
        and bool(profile.get("machineLabel"))
        and isinstance(profile.get("measurement"), Mapping)
        and source_status["matches"]
    )
    return {
        **deepcopy(profile),
        "artifact": _artifact(path),
        "sourceBinding": source_status,
        "releaseGateMet": valid,
        "blockers": (
            [] if valid else [f"{role}_reference_hardware_invalid"]
        ),
    }


def _hardware_claim_fingerprint(claim: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        claim,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _reference_hardware_claim(profile: Mapping[str, Any]) -> dict[str, Any]:
    measurement = profile.get("measurement", {})
    if not isinstance(measurement, Mapping):
        measurement = {}
    machine = measurement.get("machine", {})
    cpu = measurement.get("cpu", {})
    gpu = measurement.get("gpu", {})
    memory = measurement.get("memory", {})
    operating_system = measurement.get("operatingSystem", {})
    browser = measurement.get("browser", {})
    return {
        "schemaVersion": "facility-layout-reference-hardware-claim-v1",
        "machine": {
            "manufacturer": machine.get("manufacturer"),
            "model": machine.get("model"),
        },
        "cpu": {
            "name": cpu.get("name"),
            "physicalCores": cpu.get("physicalCores"),
            "logicalProcessors": cpu.get("logicalProcessors"),
        },
        "gpu": {
            "name": gpu.get("name"),
            "adapterRamBytesReported": gpu.get("adapterRamBytesReported"),
            "driverVersion": gpu.get("driverVersion"),
        },
        "memory": {"ramBytes": memory.get("ramBytes")},
        "operatingSystem": {"version": operating_system.get("version")},
        "browser": {
            "name": browser.get("name"),
            "version": browser.get("productVersion")
            or browser.get("fileVersion"),
        },
    }


def _benchmark_hardware_claim(raw: Mapping[str, Any]) -> dict[str, Any]:
    environment = raw.get("environment", {})
    if not isinstance(environment, Mapping):
        environment = {}
    identity = environment.get("hardwareIdentity", {})
    if not isinstance(identity, Mapping):
        identity = {}
    cpus = identity.get("cpus", [])
    gpus = identity.get("gpus", [])
    cpu = cpus[0] if isinstance(cpus, list) and cpus else {}
    gpu = gpus[0] if isinstance(gpus, list) and gpus else {}
    machine = identity.get("machine", {})
    operating_system = identity.get("operatingSystem", {})
    browser = identity.get("browser", {})
    return {
        "schemaVersion": "facility-layout-reference-hardware-claim-v1",
        "machine": {
            "manufacturer": machine.get("manufacturer"),
            "model": machine.get("model"),
        },
        "cpu": {
            "name": cpu.get("name"),
            "physicalCores": cpu.get("cores"),
            "logicalProcessors": cpu.get("logicalProcessors"),
        },
        "gpu": {
            "name": gpu.get("name"),
            "adapterRamBytesReported": gpu.get("adapterRam"),
            "driverVersion": gpu.get("driverVersion"),
        },
        "memory": {"ramBytes": identity.get("physicalMemoryBytes")},
        "operatingSystem": {"version": operating_system.get("version")},
        "browser": {
            "name": browser.get("name"),
            "version": browser.get("version"),
        },
    }


def _benchmark_matches_hardware_profile(
    raw: Mapping[str, Any],
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    expected = _reference_hardware_claim(profile)
    observed = _benchmark_hardware_claim(raw)
    expected_fingerprint = _hardware_claim_fingerprint(expected)
    observed_fingerprint = _hardware_claim_fingerprint(observed)
    matches = expected == observed
    return {
        "matches": matches,
        "expectedFingerprintSha256": expected_fingerprint,
        "observedFingerprintSha256": observed_fingerprint,
        "expected": expected,
        "observed": observed,
        "blockers": [] if matches else ["benchmark_hardware_profile_mismatch"],
    }


def _validated_browser_benchmark(
    raw_path: Path,
    summary_path: Path,
    hardware_profile: Mapping[str, Any],
) -> dict[str, Any]:
    from tools.benchmark_facility_layout_release_browser import (
        build_summary,
        validate_raw_artifact,
    )

    if not raw_path.is_file() or not summary_path.is_file():
        return {
            "valid": False,
            "validationErrors": ["benchmark_raw_or_summary_missing"],
            "summary": {},
            "storedSummaryMatchesRaw": False,
            "hardwareMatch": {
                "matches": False,
                "blockers": ["benchmark_hardware_profile_mismatch"],
            },
        }
    raw = _read_json(raw_path)
    stored_summary = _read_json(summary_path)
    raw_errors = validate_raw_artifact(raw)
    rebuilt_summary = build_summary(raw, raw_path=raw_path)
    summary_matches = stored_summary == rebuilt_summary
    hardware_match = _benchmark_matches_hardware_profile(
        raw,
        hardware_profile,
    )
    errors = list(raw_errors)
    if not summary_matches:
        errors.append("browser_summary_not_reproducible_from_raw")
    errors.extend(hardware_match["blockers"])
    valid = (
        not errors
        and rebuilt_summary.get("artifactShapeValid") is True
        and rebuilt_summary.get("profile") == "release"
        and rebuilt_summary.get("releaseEligible") is True
    )
    return {
        "valid": valid,
        "validationErrors": sorted(set(errors)),
        "summary": rebuilt_summary,
        "storedSummaryMatchesRaw": summary_matches,
        "hardwareMatch": hardware_match,
    }


def build_performance_evidence() -> dict[str, Any]:
    backend = _read_json(BACKEND_PERFORMANCE_SOURCE)
    standard = _hardware_profile(STANDARD_HARDWARE_SOURCE, "standard")
    minimum = _hardware_profile(MINIMUM_HARDWARE_SOURCE, "minimum")
    standard_benchmark = _validated_browser_benchmark(
        BROWSER_PERFORMANCE_RAW,
        BROWSER_PERFORMANCE_SUMMARY,
        standard,
    )
    browser_summary = standard_benchmark["summary"]
    browser_validation = standard_benchmark["validationErrors"]
    browser_evidence_valid = standard_benchmark["valid"]

    backend_source = _recorded_source_status(
        backend.get("source", {}).get("files")
    )
    backend_evidence_valid = (
        backend.get("schemaVersion")
        == "facility-layout-backend-release-microbenchmark-v1"
        and backend.get("releaseEligible") is True
        and backend.get("requiredOperationsAvailable") is True
        and backend.get("determinismPassed") is True
        and backend.get("provenanceComplete") is True
        and backend_source["matches"]
    )

    checks = []
    for item in browser_summary.get("budgetChecks", []):
        check = deepcopy(item)
        check["evidenceSource"] = "browser_release_protocol"
        checks.append(check)
    for operation in backend.get("operations", []):
        if operation.get("required") is not True:
            continue
        budget = operation.get("budget", {})
        checks.append(
            {
                "budgetId": f"backend-{operation.get('operationId')}",
                "measured": budget.get("measured"),
                "limit": budget.get("limit"),
                "unit": budget.get("unit"),
                "available": operation.get("availability") == "available",
                "applicable": True,
                "passed": (
                    operation.get("availability") == "available"
                    and budget.get("passed") is True
                    and operation.get("determinism", {}).get("passed")
                    is True
                ),
                "evidenceSource": "backend_release_microbenchmark",
            }
        )

    minimum_benchmark = _validated_browser_benchmark(
        MINIMUM_BROWSER_PERFORMANCE_RAW,
        MINIMUM_BROWSER_PERFORMANCE_SUMMARY,
        minimum,
    )
    minimum_benchmark_recorded = (
        minimum["releaseGateMet"]
        and minimum_benchmark["valid"]
        and minimum_benchmark["summary"].get("releaseGateMet") is True
    )
    blockers = []
    if not browser_evidence_valid:
        blockers.append("browser_release_evidence_invalid")
    blockers.extend(
        f"browser:{item}"
        for item in browser_summary.get("blockers", [])
    )
    if not backend_evidence_valid:
        blockers.append("backend_release_evidence_invalid")
    if backend.get("releaseSlicePassed") is not True:
        blockers.append("backend_release_budgets_failed")
    blockers.extend(standard["blockers"])
    blockers.extend(minimum["blockers"])
    if not minimum_benchmark_recorded:
        blockers.append("minimum_hardware_release_benchmark_not_recorded")

    observed_checks_passed = (
        bool(checks)
        and all(item.get("passed") is True for item in checks)
        and browser_evidence_valid
        and backend_evidence_valid
    )
    standard_slice_passed = (
        observed_checks_passed
        and browser_summary.get("releaseGateMet") is True
        and backend.get("releaseSlicePassed") is True
        and standard["releaseGateMet"]
    )
    release_gate_met = (
        standard_slice_passed
        and minimum["releaseGateMet"]
        and minimum_benchmark_recorded
        and not blockers
    )
    return {
        "schemaVersion": "facility-layout-p11-performance-evidence-v2",
        "generatedAtUtc": _utc_now(),
        "status": (
            "passed"
            if release_gate_met
            else "standard_hardware_passed_minimum_pending"
            if standard_slice_passed
            else "failed"
        ),
        "observedBudgetChecks": checks,
        "observedChecksPassed": observed_checks_passed,
        "standardHardwareSlicePassed": standard_slice_passed,
        "browserEvidence": {
            "artifactShapeValid": browser_evidence_valid,
            "validationErrors": browser_validation,
            "summary": _artifact(BROWSER_PERFORMANCE_SUMMARY),
            "raw": _artifact(BROWSER_PERFORMANCE_RAW),
            "protocol": deepcopy(browser_summary.get("protocol")),
            "environment": deepcopy(browser_summary.get("environment")),
            "storedSummaryMatchesRaw": standard_benchmark[
                "storedSummaryMatchesRaw"
            ],
            "hardwareMatch": standard_benchmark["hardwareMatch"],
        },
        "backendEvidence": {
            "artifactShapeValid": backend_evidence_valid,
            "sourceBinding": backend_source,
            "artifact": _artifact(BACKEND_PERFORMANCE_SOURCE),
            "claimBoundary": deepcopy(backend.get("claimBoundary")),
        },
        "protocol": {
            "browser": deepcopy(browser_summary.get("protocol")),
            "backend": deepcopy(backend.get("protocol")),
        },
        "referenceHardware": {
            "standard": standard,
            "minimum": minimum,
            "minimumBenchmarkRecorded": minimum_benchmark_recorded,
            "minimumBenchmark": minimum_benchmark,
        },
        "sourceArtifacts": [
            _artifact(BROWSER_PERFORMANCE_RAW),
            _artifact(BROWSER_PERFORMANCE_SUMMARY),
            _artifact(BACKEND_PERFORMANCE_SOURCE),
            _artifact(STANDARD_HARDWARE_SOURCE),
            _artifact(BENCHMARK_MANIFEST),
            _artifact(LEGACY_PERFORMANCE_SOURCE),
        ],
        "blockers": sorted(set(blockers)),
        "releaseGateMet": release_gate_met,
    }


def build_accessibility_evidence() -> dict[str, Any]:
    from tools.audit_facility_layout_accessibility import (
        interpret_accessibility_evidence,
    )

    raw = _read_json(ACCESSIBILITY_RAW_SOURCE)
    interpreted = interpret_accessibility_evidence(
        raw,
        raw_artifact_path=ACCESSIBILITY_RAW_SOURCE,
    )
    automated_passed = interpreted["automatedAuditPassed"] is True
    automated_blockers = sorted(
        item
        for item in interpreted.get("blockers", [])
        if item != "manual_screen_reader_audit_pending"
    )
    return {
        "schemaVersion": "facility-layout-p11-accessibility-evidence-v2",
        "generatedAtUtc": _utc_now(),
        "scope": interpreted["scope"],
        "checks": deepcopy(interpreted.get("categoryStatus")),
        "criticalFindings": [
            {
                "severity": "critical",
                "code": item,
                "message": (
                    "The source-bound automated accessibility audit failed."
                ),
            }
            for item in automated_blockers
        ],
        "staticContractPassed": automated_passed,
        "automatedAuditPassed": automated_passed,
        "manualKeyboardAudit": (
            "covered_by_automated_browser_audit"
            if interpreted.get("categoryStatus", {})
            .get("keyboard", {})
            .get("passed")
            is True
            else "failed"
        ),
        "screenReaderAudit": interpreted.get(
            "manualScreenReaderAudit", {}
        ).get("status", "pending"),
        "contrastAudit": (
            "covered_by_automated_browser_audit"
            if interpreted.get("categoryStatus", {})
            .get("contrast", {})
            .get("passed")
            is True
            else "failed"
        ),
        "sourceBinding": deepcopy(interpreted.get("sourceBinding")),
        "sourceArtifacts": [
            _artifact(ACCESSIBILITY_RAW_SOURCE),
            _artifact(ACCESSIBILITY_SUMMARY_SOURCE),
        ],
        "blockers": deepcopy(interpreted.get("blockers")),
        "releaseGateMet": interpreted["releaseGateMet"] is True,
        "releaseGateReason": interpreted["releaseGateReason"],
    }


def build_visual_manifest(
    capture_source: Path = VISUAL_CAPTURE_SOURCE,
    *,
    source_root: Path = ROOT,
    source_paths: tuple[str, ...] = VISUAL_SOURCE_PATHS,
    artifact_root: Path = ROOT,
) -> dict[str, Any]:
    capture = _read_json(capture_source)
    source_binding = _visual_source_binding_status(
        capture.get("sourceBinding"),
        root=source_root,
        relative_paths=source_paths,
    )
    records = []
    source_records = capture.get("records", [])
    for source in source_records:
        relative = str(source.get("path") or "")
        path = (artifact_root / relative).resolve()
        try:
            path.relative_to(artifact_root.resolve())
        except ValueError as exc:
            raise ValueError(
                f"Visual artifact escapes the repository: {relative}"
            ) from exc
        actual = _png_info(path, artifact_root)
        viewport = source.get("viewport", {})
        expected_width = int(viewport.get("width") or 0)
        expected_height = int(viewport.get("height") or 0)
        source_checks = source.get("checks", {})
        source_matches = (
            source.get("sha256") == actual["sha256"]
            and int(source.get("byteLength") or 0) == actual["byteLength"]
            and int(source.get("width") or 0) == actual["width"]
            and int(source.get("height") or 0) == actual["height"]
            and expected_width == actual["width"]
            and expected_height == actual["height"]
        )
        checks_passed = (
            bool(source_checks)
            and all(bool(value) for value in source_checks.values())
        )
        records.append(
            {
                **actual,
                "theme": str(source.get("theme") or ""),
                "scope": "facility_layout_workspace",
                "viewport": {
                    "width": expected_width,
                    "height": expected_height,
                },
                "capturePassed": bool(source.get("passed")),
                "captureChecksPassed": checks_passed,
                "sourceMatchesArtifact": source_matches,
                "sampledColorCount": int(
                    source.get("sampledColorCount") or 0
                ),
            }
        )
    observed = {
        f"{record['width']}x{record['height']}:{record['theme']}"
        for record in records
    }
    required = {
        f"{width}x{height}:{theme}"
        for width, height in REQUIRED_VISUAL_VIEWPORTS
        for theme in REQUIRED_VISUAL_THEMES
    }
    themes = sorted({record["theme"] for record in records})
    context_recovery_source = capture.get("webglContextRecovery")
    context_recovery = (
        deepcopy(dict(context_recovery_source))
        if isinstance(context_recovery_source, Mapping)
        else {}
    )
    context_screenshot_source = context_recovery.get("screenshot")
    context_screenshot_valid = False
    if isinstance(context_screenshot_source, Mapping):
        relative = str(context_screenshot_source.get("path") or "")
        path = (artifact_root / relative).resolve()
        try:
            path.relative_to(artifact_root.resolve())
        except ValueError as exc:
            raise ValueError(
                f"WebGL recovery artifact escapes the repository: {relative}"
            ) from exc
        actual = _png_info(path, artifact_root)
        context_screenshot_valid = (
            context_screenshot_source.get("sha256") == actual["sha256"]
            and int(context_screenshot_source.get("byteLength") or 0)
            == actual["byteLength"]
            and int(context_screenshot_source.get("width") or 0)
            == actual["width"]
            and int(context_screenshot_source.get("height") or 0)
            == actual["height"]
            and actual["nonempty"]
        )
        context_recovery["verifiedScreenshot"] = actual
    context_checks = context_recovery.get("checks")
    context_recovery_valid = (
        bool(context_recovery.get("passed"))
        and isinstance(context_checks, Mapping)
        and bool(context_checks)
        and all(bool(value) for value in context_checks.values())
        and context_screenshot_valid
    )
    manifest_valid = (
        bool(capture.get("passed"))
        and capture.get("sourceStableDuringCapture") is True
        and source_binding["matches"]
        and len(records) == len(required)
        and context_recovery_valid
        and all(
            record["nonempty"]
            and record["byteLength"] > 0
            and record["capturePassed"]
            and record["captureChecksPassed"]
            and record["sourceMatchesArtifact"]
            and record["sampledColorCount"] > 1
            for record in records
        )
    )
    complete = not (required - observed) and not (observed - required)
    release_gate_met = (
        manifest_valid and complete and themes == ["dark", "light"]
    )
    return {
        "schemaVersion": "facility-layout-p11-visual-manifest-v2",
        "generatedAtUtc": _utc_now(),
        "artifacts": records,
        "themesRepresented": themes,
        "lightDarkArtifactRequirementMet": themes == ["dark", "light"],
        "requiredCoverage": sorted(required),
        "observedExactCoverage": sorted(observed & required),
        "missingExactCoverage": sorted(required - observed),
        "unexpectedExactCoverage": sorted(observed - required),
        "manifestValid": manifest_valid,
        "sourceBinding": source_binding,
        "webglContextRecovery": {
            **context_recovery,
            "verified": context_recovery_valid,
        },
        "captureSource": _artifact(capture_source, artifact_root),
        "releaseGateMet": release_gate_met,
    }


def build_feature_flag_matrix() -> dict[str, Any]:
    runtime_paths = [
        ROOT / "server.py",
        *sorted((ROOT / "ai_inspector").rglob("*.py")),
        *sorted((ROOT / "static").glob("*.js")),
    ]
    runtime_paths = [
        path
        for path in runtime_paths
        if path.name != "verify_facility_layout_p11.py"
        and "test_facility_layout_p11_" not in path.name
    ]
    contents = {
        path: path.read_text(encoding="utf-8", errors="replace")
        for path in runtime_paths
        if path.is_file()
    }
    flags = []
    for flag in FEATURE_FLAGS:
        sources = [
            _relative(path)
            for path, text in contents.items()
            if flag in text
        ]
        flags.append(
            {
                "flag": flag,
                "default": "off",
                "runtimeWired": bool(sources),
                "runtimeSources": sources,
            }
        )
    wired = all(item["runtimeWired"] for item in flags)
    combinations = [
        {
            "matrixId": "all-off",
            "enabled": [],
            "expected": "saved_layouts_readable_manual_or_legacy_fallback",
            "executionStatus": (
                "pending_execution" if wired else "blocked_flags_unwired"
            ),
        },
        {
            "matrixId": "viewer-and-library",
            "enabled": list(FEATURE_FLAGS[:2]),
            "expected": "read_only_viewer_and_catalog",
            "executionStatus": (
                "pending_execution" if wired else "blocked_flags_unwired"
            ),
        },
        {
            "matrixId": "manual-authoring",
            "enabled": list(FEATURE_FLAGS[:5]),
            "expected": "manual_edit_constraints_and_routing",
            "executionStatus": (
                "pending_execution" if wired else "blocked_flags_unwired"
            ),
        },
        {
            "matrixId": "agent-preview-read-only",
            "enabled": list(FEATURE_FLAGS[:6]),
            "expected": "proposal_preview_without_agent_apply",
            "executionStatus": (
                "pending_execution" if wired else "blocked_flags_unwired"
            ),
        },
        {
            "matrixId": "agent-write-last",
            "enabled": list(FEATURE_FLAGS),
            "expected": "approved_exact_apply",
            "executionStatus": (
                "pending_execution" if wired else "blocked_flags_unwired"
            ),
        },
    ]
    return {
        "schemaVersion": "facility-layout-p11-feature-flag-matrix-v1",
        "generatedAtUtc": _utc_now(),
        "flags": flags,
        "matrix": combinations,
        "releaseGateMet": False,
        "blockers": [] if wired else ["facility_layout_flags_not_runtime_wired"],
        "sourceScan": {
            "pathCount": len(contents),
            "sourceHashes": _source_hashes(contents),
        },
    }


def _status_is(response: Any, expected: int) -> bool:
    return int(getattr(response, "status_code", 0)) == expected


def run_feature_flag_matrix(root: Path) -> dict[str, Any]:
    """Exercise every rollout stage through the real local HTTP boundary."""

    matrix = build_feature_flag_matrix()
    results = []
    for index, combination in enumerate(matrix["matrix"]):
        enabled = set(combination["enabled"])
        flags = FacilityLayoutFeatureFlags.from_environment(
            {
                name: "1" if name in enabled else "0"
                for name in FEATURE_FLAGS
            }
        )
        case_root = root / combination["matrixId"]
        host = LocalFacilityLayoutHost(
            case_root,
            feature_flags=flags,
        )
        client = _api_client(host)
        checks: dict[str, bool] = {}
        try:
            bootstrap_response = client.get(
                "/api/facility-layout-bootstrap"
            )
            checks["bootstrap_readable"] = _status_is(
                bootstrap_response,
                200,
            )
            bootstrap = bootstrap_response.json()
            receipt = bootstrap["layout"]
            layout_url = (
                f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
            )
            checks["saved_layout_readable"] = _status_is(
                client.get(layout_url),
                200,
            )

            expected_capabilities = {
                "viewerV2": flags.enabled("viewer_v2"),
                "assetLibrary": flags.enabled("asset_library"),
                "manualAuthoring": flags.enabled("manual_edit"),
                "collisionValidation": flags.enabled("constraints"),
                "automaticRouting": flags.enabled("routing"),
                "fullLayoutProposals": flags.enabled("agent_preview"),
                "atomicProposalApply": flags.enabled("agent_write"),
            }
            capabilities = bootstrap["capabilities"]
            checks["capabilities_exact"] = all(
                capabilities.get(name) is expected
                for name, expected in expected_capabilities.items()
            )
            checks["catalog_projection_exact"] = bool(
                bootstrap["assetCatalog"]
            ) is flags.enabled("asset_library")
            checks["asset_api_gate"] = _status_is(
                client.get(
                    "/api/industrial-assets",
                    params={"siteId": LOCAL_SITE_ID},
                ),
                200 if flags.enabled("asset_library") else 403,
            )

            no_op = {
                "baseRevision": receipt["revision"],
                "operations": [],
            }
            checks["manual_edit_gate"] = _status_is(
                client.put(layout_url, json=no_op),
                200 if flags.enabled("manual_edit") else 403,
            )
            checks["constraint_gate"] = _status_is(
                client.post(
                    layout_url + "/spatial/diagnostics",
                    json=no_op,
                ),
                200 if flags.enabled("constraints") else 403,
            )
            checks["routing_gate"] = _status_is(
                client.post(
                    layout_url + "/routing/diagnostics",
                    json=no_op,
                ),
                200 if flags.enabled("routing") else 403,
            )

            planner_payload = {
                "baseRevision": receipt["revision"],
                "request": _planner_request(
                    receipt,
                    list(host._catalog.values())[:1],
                    request_id=f"p11-flags-{index}",
                ),
            }
            proposal_response = client.post(
                layout_url + "/proposals",
                json=planner_payload,
            )
            preview_enabled = flags.enabled("agent_preview")
            checks["agent_preview_gate"] = _status_is(
                proposal_response,
                200 if preview_enabled else 403,
            )
            checks["agent_tool_preview_gate"] = _status_is(
                client.post(
                    (
                        "/api/facility-layout-agent/"
                        f"{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/preview"
                    ),
                    json={},
                ),
                422 if preview_enabled else 403,
            )

            if preview_enabled:
                proposal_set = proposal_response.json()
                selected = next(
                    item
                    for item in proposal_set["alternatives"]
                    if item["proposalId"]
                    == proposal_set["selectedProposalId"]
                )
                approval_response = client.post(
                    layout_url + "/approvals",
                    headers={
                        "X-InspectorPro-Session": "p11-flag-session"
                    },
                    json={
                        "proposalId": selected["proposalId"],
                        "binding": selected["transactionBinding"],
                        "idempotencyKey": "p11-flags-approval",
                        "explicitApproval": True,
                    },
                )
            else:
                selected = None
                approval_response = client.post(
                    layout_url + "/approvals",
                    headers={
                        "X-InspectorPro-Session": "p11-flag-session"
                    },
                    json={},
                )
            write_enabled = flags.enabled("agent_write")
            checks["agent_approval_gate"] = _status_is(
                approval_response,
                200 if write_enabled else 403,
            )
            if write_enabled and selected is not None:
                approval = approval_response.json()
                apply_response = client.post(
                    layout_url + "/apply",
                    headers={
                        "X-InspectorPro-Session": "p11-flag-session"
                    },
                    json={
                        "approvalToken": approval["approvalToken"],
                        "binding": selected["transactionBinding"],
                        "idempotencyKey": "p11-flags-approval",
                    },
                )
                checks["agent_apply_gate"] = _status_is(
                    apply_response,
                    200,
                )
                checks["receipt_persisted"] = bool(
                    apply_response.json().get("receipt", {}).get("receiptId")
                )
            else:
                apply_response = client.post(
                    layout_url + "/apply",
                    headers={
                        "X-InspectorPro-Session": "p11-flag-session"
                    },
                    json={},
                )
                checks["agent_apply_gate"] = _status_is(
                    apply_response,
                    403,
                )
                checks["receipt_persisted"] = not write_enabled
        finally:
            host.close()

        passed = all(checks.values())
        results.append(
            {
                **deepcopy(combination),
                "executionStatus": "passed" if passed else "failed",
                "checks": checks,
                "passed": passed,
            }
        )
    matrix["matrix"] = results
    matrix["releaseGateMet"] = (
        all(item["runtimeWired"] for item in matrix["flags"])
        and all(item["passed"] for item in results)
    )
    matrix["blockers"] = (
        []
        if matrix["releaseGateMet"]
        else ["facility_layout_feature_flag_matrix_failed"]
    )
    return matrix


def build_webgl_offline_evidence(
    suite_results: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    adapter_path = ROOT / "static" / "facility_layout_three_adapter.js"
    test_path = ROOT / "tests" / "test_facility_layout_three_adapter.js"
    adapter = adapter_path.read_text(encoding="utf-8")
    tests = test_path.read_text(encoding="utf-8")
    offline = _read_json(OFFLINE_SOURCE)
    static_checks = {
        "context_lost_listener": "'webglcontextlost'" in adapter,
        "context_restored_listener": "'webglcontextrestored'" in adapter,
        "context_loss_prevent_default": "event.preventDefault()" in adapter,
        "degraded_state": "enterDegraded('webgl_context_lost'" in adapter,
        "restoration_invalidates": (
            "state.contextLost = false;" in adapter
            and "notifyStatus('ready', null);" in adapter
            and "invalidate();" in adapter
        ),
        "listeners_removed_on_teardown": (
            "removeListener(" in adapter
            and "'webglcontextlost'" in adapter
            and "'webglcontextrestored'" in adapter
        ),
        "behavioral_context_test_present": (
            "context loss degrades 3D without throwing" in tests
        ),
        "edit_continuity_test_present": (
            "context restoration replays edits made while 3D was degraded"
            in tests
        ),
        "webgl_unavailable_test_present": (
            "WebGL-unavailable mode retains scene identity" in tests
        ),
        "failed_asset_fallback_test_present": (
            "keeps failed assets as deterministic footprint boxes" in tests
        ),
    }
    suite = (suite_results or {}).get("node-three-adapter")
    behavioral_status = (
        "passed"
        if isinstance(suite, Mapping) and suite.get("passed") is True
        else "not_run"
    )
    offline_checks = offline.get("checks", {})
    offline_passed = bool(offline.get("passed")) and all(
        bool(value) for value in offline_checks.values()
    )
    contract_passed = all(static_checks.values())
    return {
        "schemaVersion": "facility-layout-p11-recovery-evidence-v1",
        "generatedAtUtc": _utc_now(),
        "webglRecovery": {
            "staticChecks": static_checks,
            "staticContractPassed": contract_passed,
            "behavioralSuiteStatus": behavioral_status,
        },
        "offlineAndCorruptArtifacts": {
            "artifact": _artifact(OFFLINE_SOURCE),
            "checks": deepcopy(offline_checks),
            "passed": offline_passed,
            "corruptArtifactRejected": bool(
                offline_checks.get("corrupt_glb_rejected")
            ),
            "externalRequestsBlocked": bool(
                offline_checks.get("no_external_requests")
            ),
        },
        "source": _source_hashes((adapter_path, test_path)),
        "releaseGateMet": (
            contract_passed
            and offline_passed
            and behavioral_status == "passed"
        ),
    }


def _python_distribution_release_gate(
    inventory: Mapping[str, Any],
    source_binding: Mapping[str, Any],
) -> dict[str, Any]:
    machine_assessment = inventory.get("machineAssessment", {})
    human_approval = inventory.get("humanLegalApproval", {})
    blockers = [
        *(
            ["python_distribution_inventory_source_binding_invalid"]
            if source_binding.get("matches") is not True
            else []
        ),
        *(
            ["python_distribution_machine_assessment_blocked"]
            if machine_assessment.get("gateMet") is not True
            else []
        ),
        *(
            ["python_distribution_human_legal_review_pending"]
            if human_approval.get("approved") is not True
            else []
        ),
        *(
            ["python_distribution_legal_clearance_not_recorded"]
            if human_approval.get("legalClearanceClaimed") is not True
            else []
        ),
        *(
            ["python_distribution_inventory_gate_not_met"]
            if inventory.get("releaseGateMet") is not True
            else []
        ),
    ]
    complete = (
        inventory.get("schemaVersion")
        == "facility-layout-python-dependency-inventory-v1"
        and not blockers
    )
    return {
        "complete": complete,
        "blockers": blockers,
        "machineAssessment": deepcopy(machine_assessment),
        "humanLegalApproval": deepcopy(human_approval),
    }


def build_licensing_inventory() -> dict[str, Any]:
    vendor_root = ROOT / "static" / "vendor"
    packages = [
        {
            "package": "@floating-ui/core",
            "version": "1.7.5",
            "license": "MIT",
            "licensePath": "static/vendor/floating-ui/LICENSE",
            "artifactRoots": ["static/vendor/floating-ui"],
            "include": ["floating-ui.core.umd.min.js"],
        },
        {
            "package": "@floating-ui/dom",
            "version": "1.7.6",
            "license": "MIT",
            "licensePath": "static/vendor/floating-ui/LICENSE",
            "artifactRoots": ["static/vendor/floating-ui"],
            "include": ["floating-ui.dom.umd.min.js"],
        },
        {
            "package": "three",
            "version": "0.128.0",
            "license": "MIT",
            "licensePath": "static/vendor/three/0.128.0/LICENSE",
            "artifactRoots": ["static/vendor/three/0.128.0"],
            "include": ["build/three.min.js"],
        },
        {
            "package": "three",
            "version": "0.184.0",
            "license": "MIT",
            "licensePath": "static/vendor/three/0.184.0/LICENSE",
            "artifactRoots": ["static/vendor/three/0.184.0"],
            "include": [
                str(path.relative_to(vendor_root / "three" / "0.184.0"))
                .replace("\\", "/")
                for path in sorted(
                    (vendor_root / "three" / "0.184.0").rglob("*.js")
                )
            ],
        },
    ]
    covered: set[str] = set()
    records = []
    for package in packages:
        root = ROOT / package["artifactRoots"][0]
        license_path = ROOT / package["licensePath"]
        artifacts = []
        for relative in package["include"]:
            path = root / relative
            artifacts.append(_artifact(path))
            covered.add(_relative(path))
        records.append(
            {
                "package": package["package"],
                "version": package["version"],
                "license": package["license"],
                "licenseArtifact": _artifact(license_path),
                "licenseTextPresent": (
                    "MIT License"
                    in license_path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )
                ),
                "artifacts": artifacts,
            }
        )
    vendored_javascript = {
        _relative(path)
        for path in vendor_root.rglob("*.js")
    }
    readiness = _read_json(ASSET_READINESS_SOURCE)
    industrial_assets = [
        {
            "assetId": item["assetId"],
            "category": item["category"],
            "publicReady": bool(
                item.get("expectedReadiness", {}).get("publicReady")
            ),
            "placementReady": bool(
                item.get("expectedReadiness", {}).get("placementReady")
            ),
            "visualReady": bool(
                item.get("expectedReadiness", {}).get("visualReady")
            ),
        }
        for item in readiness.get("assets", [])
    ]
    missing_vendor = sorted(vendored_javascript - covered)
    unlicensed_assets = sorted(
        item["assetId"]
        for item in industrial_assets
        if not item["publicReady"]
    )
    python_inventory = _read_json(PYTHON_DEPENDENCY_INVENTORY_SOURCE)
    python_source_binding = _recorded_source_status(
        [
            python_inventory.get("sourceBinding", {}).get("requirements"),
            python_inventory.get("sourceBinding", {}).get("generator"),
        ]
    )
    python_gate = _python_distribution_release_gate(
        python_inventory,
        python_source_binding,
    )
    python_review_complete = python_gate["complete"]
    blockers = [
        *(
            ["vendored_browser_javascript_missing_license_record"]
            if missing_vendor
            else []
        ),
        *(
            ["industrial_asset_redistribution_rights_unresolved"]
            if unlicensed_assets
            else []
        ),
        *python_gate["blockers"],
    ]
    release_gate_met = not blockers
    return {
        "schemaVersion": "facility-layout-p11-licensing-inventory-v1",
        "generatedAtUtc": _utc_now(),
        "vendoredBrowserPackages": records,
        "vendoredJavaScriptCoverage": {
            "discovered": sorted(vendored_javascript),
            "covered": sorted(covered),
            "missing": missing_vendor,
            "complete": not missing_vendor,
        },
        "industrialAssetReadiness": {
            "source": _artifact(ASSET_READINESS_SOURCE),
            "assets": industrial_assets,
            "notPublicReadyAssetIds": unlicensed_assets,
        },
        "pythonDistributionDependencyReview": {
            "status": "complete" if python_review_complete else "blocked",
            "inventoryArtifact": _artifact(
                PYTHON_DEPENDENCY_INVENTORY_SOURCE
            ),
            "sourceBinding": python_source_binding,
            "machineAssessment": python_gate["machineAssessment"],
            "humanLegalApproval": python_gate["humanLegalApproval"],
            "blockingConcern": (
                None
                if python_review_complete
                else (
                    "Resolve the exact dependency and license inventory, "
                    "including the PyMuPDF distribution path, and retain "
                    "qualified human approval for the packaged pilot."
                )
            ),
        },
        "releaseGateMet": release_gate_met,
        "blockers": blockers,
    }


def build_suite_matrix() -> dict[str, Any]:
    return {
        "schemaVersion": "facility-layout-p11-suite-matrix-v1",
        "generatedAtUtc": _utc_now(),
        "suites": [
            {
                "suiteId": "python-security-authority",
                "command": [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests/test_facility_layout_authorization.py",
                    "tests/test_facility_layout_p11_identity.py",
                    "tests/test_facility_layout_proposals.py",
                    "tests/test_facility_layout_agent_runtime.py",
                    "tests/test_facility_layout_agent_integration.py",
                    "tests/test_facility_layout_product_boundary.py",
                    "tests/test_facility_layout_repository.py",
                    "tests/test_facility_authority_repository.py",
                    "tests/test_industrial_asset_registry.py",
                    "tests/test_industrial_asset_publication.py",
                    "tests/test_industrial_asset_pilot_readiness.py",
                    "tests/test_transaction_kernel.py",
                    "-q",
                ],
                "coverage": [
                    "rbac",
                    "principal_authentication",
                    "idor",
                    "tool_authorization",
                    "explicit_approval",
                    "stale_revision",
                    "exact_diff",
                    "replay",
                    "receipt",
                    "maker_checker",
                    "hostile_origin",
                    "transaction_recovery",
                    "repository_persistence",
                    "catalog_publication",
                ],
            },
            {
                "suiteId": "node-three-adapter",
                "command": [
                    "node",
                    "tests/test_facility_layout_three_adapter.js",
                ],
                "coverage": [
                    "webgl_recovery",
                    "webgl_edit_continuity",
                    "webgl_unavailable",
                    "corrupt_asset_fallback",
                    "lifecycle",
                ],
            },
            {
                "suiteId": "node-workspace-accessibility",
                "command": [
                    "node",
                    "tests/test_facility_layout_workspace.js",
                ],
                "coverage": [
                    "aria_runtime",
                    "keyboard_state",
                    "proposal_review",
                ],
            },
            {
                "suiteId": "node-p11-static-contracts",
                "command": [
                    "node",
                    "tests/test_facility_layout_p11_contracts.js",
                ],
                "coverage": [
                    "aria_static",
                    "webgl_static",
                    "safety_disclaimer",
                ],
            },
        ],
        "requiredCoverage": [
            "rbac",
            "principal_authentication",
            "idor",
            "tool_authorization",
            "explicit_approval",
            "stale_revision",
            "exact_diff",
            "replay",
            "receipt",
            "maker_checker",
            "hostile_origin",
            "transaction_recovery",
            "repository_persistence",
            "catalog_publication",
            "webgl_recovery",
            "webgl_edit_continuity",
            "aria_runtime",
        ],
    }


def run_suite_matrix(
    matrix: Mapping[str, Any],
    *,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for suite in matrix["suites"]:
        started = time.monotonic()
        try:
            command = list(suite["command"])
            with tempfile.TemporaryDirectory(
                prefix=f"inspectorpro-p11-{suite['suiteId']}-",
                # Windows can race pytest/plugin teardown while recursively
                # removing a deeply nested basetemp. Cleanup must not replace
                # the suite's actual return code with an unrelated WinError.
                ignore_cleanup_errors=True,
            ) as temporary_root:
                if command[1:3] == ["-m", "pytest"]:
                    command.extend(
                        [
                            "--basetemp",
                            str(Path(temporary_root) / "pytest"),
                            "-p",
                            "no:cacheprovider",
                        ]
                    )
                completed = subprocess.run(
                    command,
                    cwd=ROOT,
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=timeout_seconds,
                )
            output = "\n".join(
                part
                for part in (completed.stdout, completed.stderr)
                if part
            )
            results[suite["suiteId"]] = {
                "passed": completed.returncode == 0,
                "returnCode": completed.returncode,
                "durationSeconds": round(time.monotonic() - started, 3),
                "outputTail": output.splitlines()[-80:],
            }
        except subprocess.TimeoutExpired as exc:
            results[suite["suiteId"]] = {
                "passed": False,
                "returnCode": None,
                "durationSeconds": round(time.monotonic() - started, 3),
                "outputTail": [
                    f"Timed out after {exc.timeout} seconds."
                ],
            }
    all_passed = all(item["passed"] for item in results.values())
    return {
        **deepcopy(dict(matrix)),
        "executedAtUtc": _utc_now(),
        "results": results,
        "allPassed": all_passed,
        "releaseGateMet": all_passed,
    }


def _snapshot_tree(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def run_rollback_drill(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    host = LocalFacilityLayoutHost(
        root,
        feature_flags=FacilityLayoutFeatureFlags.all_enabled(),
    )
    bootstrap = host.ensure_bootstrap()
    enabled_client = _api_client(host)
    _, applied_selected = _create_proposal(
        enabled_client,
        LOCAL_LAYOUT_ID,
        bootstrap["layout"],
        list(host._catalog.values())[:1],
        request_id="p11-rollback-durable",
    )
    approval = _approve(
        enabled_client,
        LOCAL_LAYOUT_ID,
        applied_selected,
        session_id="p11-rollback-session",
        key="p11-rollback-apply",
    )
    applied = _apply(
        enabled_client,
        LOCAL_LAYOUT_ID,
        applied_selected,
        approval,
        session_id="p11-rollback-session",
        key="p11-rollback-apply",
    )
    if applied.status_code != 200:
        raise AssertionError(applied.text)
    applied_result = applied.json()
    canonical_receipt = applied_result["receipt"]
    before_receipt = _layout_receipt(enabled_client, LOCAL_LAYOUT_ID)
    before_bytes = canonical_layout_bytes(before_receipt["layout"])
    host.close()
    before_files = _snapshot_tree(root)

    observations = []
    for state, value in (("all_off", "0"), ("all_on", "1")):
        flags = FacilityLayoutFeatureFlags.from_environment(
            {flag: value for flag in FEATURE_FLAGS}
        )
        reopened = LocalFacilityLayoutHost(
            root,
            feature_flags=flags,
        )
        client = _api_client(reopened)
        try:
            bootstrap_response = client.get(
                "/api/facility-layout-bootstrap"
            )
            receipt = reopened.service.get_layout(
                reopened.principal(),
                LOCAL_SITE_ID,
                LOCAL_LAYOUT_ID,
            )
            blocked_write = client.put(
                f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}",
                json={
                    "baseRevision": receipt["revision"],
                    "operations": [],
                },
            )
            proposal_path = (
                f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
                f"/proposals/{applied_selected['proposalId']}/preview"
            )
            receipt_path = (
                f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
                f"/receipts/{canonical_receipt['receiptId']}"
            )
            durable_proposal = client.get(proposal_path)
            durable_receipt = client.get(receipt_path)
            new_preview = (
                client.post(
                    (
                        f"/api/facility-layouts/{LOCAL_SITE_ID}/"
                        f"{LOCAL_LAYOUT_ID}/proposals"
                    ),
                    json={
                        "baseRevision": receipt["revision"],
                        "request": _planner_request(
                            receipt,
                            list(reopened._catalog.values())[:1],
                            request_id=f"p11-rollback-{state}",
                        ),
                    },
                )
                if state == "all_off"
                else None
            )
            observations.append(
                {
                    "state": state,
                    "revision": receipt["revision"],
                    "canonicalLayoutSha256": _sha256_bytes(
                        canonical_layout_bytes(receipt["layout"])
                    ),
                    "bootstrapStatus": bootstrap_response.status_code,
                    "viewerV2": bootstrap_response.json()[
                        "capabilities"
                    ]["viewerV2"],
                    "manualAuthoring": bootstrap_response.json()[
                        "capabilities"
                    ]["manualAuthoring"],
                    "noOpWriteStatus": blocked_write.status_code,
                    "consumedProposalStatus": durable_proposal.status_code,
                    "durableReceiptStatus": durable_receipt.status_code,
                    "durableReceiptExact": (
                        durable_receipt.status_code == 200
                        and durable_receipt.json() == canonical_receipt
                    ),
                    "newPreviewStatus": (
                        new_preview.status_code
                        if new_preview is not None
                        else "not_run"
                    ),
                }
            )
        finally:
            reopened.close()

    after_files = _snapshot_tree(root)
    control_effective = (
        observations[0]["viewerV2"] is False
        and observations[0]["manualAuthoring"] is False
        and observations[0]["noOpWriteStatus"] == 403
        and observations[0]["consumedProposalStatus"] == 403
        and observations[0]["durableReceiptExact"]
        and observations[0]["newPreviewStatus"] == 403
        and observations[1]["viewerV2"] is True
        and observations[1]["manualAuthoring"] is True
        and observations[1]["noOpWriteStatus"] == 200
        and observations[1]["consumedProposalStatus"] == 404
        and observations[1]["durableReceiptExact"]
    )
    unchanged = (
        before_files == after_files
        and all(
            item["revision"] == before_receipt["revision"]
            and item["canonicalLayoutSha256"]
            == _sha256_bytes(before_bytes)
            for item in observations
        )
    )
    return {
        "schemaVersion": "facility-layout-p11-rollback-drill-v1",
        "generatedAtUtc": _utc_now(),
        "layoutId": LOCAL_LAYOUT_ID,
        "beforeRevision": before_receipt["revision"],
        "beforeCanonicalLayoutSha256": _sha256_bytes(before_bytes),
        "consumedProposalId": applied_selected["proposalId"],
        "durableReceiptId": canonical_receipt["receiptId"],
        "observations": observations,
        "dataFilesBefore": before_files,
        "dataFilesAfter": after_files,
        "noDataConversion": unchanged,
        "noFileMutation": before_files == after_files,
        "featureFlagControlEffective": control_effective,
        "status": (
            "passed"
            if unchanged and control_effective
            else "failed"
        ),
        "releaseGateMet": unchanged and control_effective,
        "blockers": (
            []
            if unchanged and control_effective
            else ["facility_layout_flag_rollback_failed"]
        ),
    }


def _api_client(host: LocalFacilityLayoutHost) -> TestClient:
    app = FastAPI()
    app.include_router(host.create_router())
    return TestClient(app)


def _planner_request(
    receipt: Mapping[str, Any],
    assets: list[Mapping[str, Any]],
    *,
    request_id: str,
) -> dict[str, Any]:
    layout = receipt["layout"]
    return {
        "schemaVersion": 1,
        "requestId": request_id,
        "objective": "place_asset_set",
        "assetSet": [
            {
                "itemId": f"{request_id}-item-{index + 1}",
                "assetId": asset["assetId"],
                "assetDefinitionRevision": (
                    asset["assetDefinitionRevision"]
                ),
                "quantity": 1,
                "stage": index,
            }
            for index, asset in enumerate(assets)
        ],
        "strategies": ["compact_rows"],
        "maximumAlternatives": 1,
        "spacingMeters": 1.0,
        "cleanup": {
            "enabled": False,
            "moveAuto": True,
            "movableManualPlacementIds": [],
        },
        "zoneSizing": [],
        "routes": [],
        "sourceRevisions": {
            "shell": layout["sourceShellRef"]["shellRevision"],
            "policy": layout["policySetRef"]["policySetRevision"],
        },
    }


def _create_proposal(
    client: TestClient,
    layout_id: str,
    receipt: Mapping[str, Any],
    assets: list[Mapping[str, Any]],
    *,
    request_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    response = client.post(
        f"/api/facility-layouts/{LOCAL_SITE_ID}/{layout_id}/proposals",
        json={
            "baseRevision": receipt["revision"],
            "request": _planner_request(
                receipt,
                assets,
                request_id=request_id,
            ),
        },
    )
    if response.status_code != 200:
        raise AssertionError(response.text)
    proposal_set = response.json()
    selected = next(
        item
        for item in proposal_set["alternatives"]
        if item["proposalId"] == proposal_set["selectedProposalId"]
    )
    return proposal_set, selected


def _approve(
    client: TestClient,
    layout_id: str,
    selected: Mapping[str, Any],
    *,
    session_id: str,
    key: str,
) -> dict[str, Any]:
    response = client.post(
        f"/api/facility-layouts/{LOCAL_SITE_ID}/{layout_id}/approvals",
        headers={"X-InspectorPro-Session": session_id},
        json={
            "proposalId": selected["proposalId"],
            "binding": selected["transactionBinding"],
            "idempotencyKey": key,
            "explicitApproval": True,
        },
    )
    if response.status_code != 200:
        raise AssertionError(response.text)
    return response.json()


def _apply(
    client: TestClient,
    layout_id: str,
    selected: Mapping[str, Any],
    approval: Mapping[str, Any],
    *,
    session_id: str,
    key: str,
) -> Any:
    return client.post(
        f"/api/facility-layouts/{LOCAL_SITE_ID}/{layout_id}/apply",
        headers={"X-InspectorPro-Session": session_id},
        json={
            "approvalToken": approval["approvalToken"],
            "binding": selected["transactionBinding"],
            "idempotencyKey": key,
        },
    )


def _layout_receipt(client: TestClient, layout_id: str) -> dict[str, Any]:
    response = client.get(
        f"/api/facility-layouts/{LOCAL_SITE_ID}/{layout_id}"
    )
    if response.status_code != 200:
        raise AssertionError(response.text)
    return response.json()


def run_maker_checker_pilot_gate(root: Path) -> dict[str, Any]:
    """Prove product ingress authenticates and separates maker/checker."""

    maker_token = "p11-maker-token-" + ("m" * 48)
    checker_token = "p11-checker-token-" + ("c" * 48)
    identity_document = {
        "schemaVersion": 1,
        "principals": [
            {
                "tokenSha256": hashlib.sha256(
                    maker_token.encode("utf-8")
                ).hexdigest(),
                "principalId": "maker-p11",
                "tenantId": "local",
                "allowedSiteIds": [LOCAL_SITE_ID],
                "roles": ["layout_admin"],
            },
            {
                "tokenSha256": hashlib.sha256(
                    checker_token.encode("utf-8")
                ).hexdigest(),
                "principalId": "checker-p11",
                "tenantId": "local",
                "allowedSiteIds": [LOCAL_SITE_ID],
                "roles": ["approver"],
            },
        ],
    }
    resolver = FacilityPrincipalResolver.from_environment(
        site_id=LOCAL_SITE_ID,
        environ={
            FACILITY_IDENTITY_CONFIG_ENV: json.dumps(
                identity_document,
                separators=(",", ":"),
            )
        },
        require_authenticated=True,
    )
    host = LocalFacilityLayoutHost(
        root,
        feature_flags=FacilityLayoutFeatureFlags.all_enabled(),
        require_distinct_approver=True,
        principal_resolver=resolver,
    )

    app = FastAPI()
    app.include_router(host.create_router())
    client = TestClient(app)
    try:
        authentication_required = client.get(
            "/api/facility-layout-bootstrap"
        )
        invalid_identity = client.get(
            "/api/facility-layout-bootstrap",
            headers={"Authorization": "Bearer " + ("x" * 48)},
        )
        maker_headers = {
            "Authorization": f"Bearer {maker_token}",
        }
        bootstrap_response = client.get(
            "/api/facility-layout-bootstrap",
            headers=maker_headers,
        )
        if bootstrap_response.status_code != 200:
            raise AssertionError(bootstrap_response.text)
        bootstrap = bootstrap_response.json()
        layout_url = (
            f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
        )
        created = client.post(
            layout_url + "/proposals",
            headers=maker_headers,
            json={
                "baseRevision": bootstrap["layout"]["revision"],
                "request": _planner_request(
                    bootstrap["layout"],
                    list(host._catalog.values())[:1],
                    request_id="p11-maker-checker",
                ),
            },
        )
        if created.status_code != 200:
            raise AssertionError(created.text)
        proposal_set = created.json()
        selected = next(
            item
            for item in proposal_set["alternatives"]
            if item["proposalId"] == proposal_set["selectedProposalId"]
        )
        approval_body = {
            "proposalId": selected["proposalId"],
            "binding": selected["transactionBinding"],
            "idempotencyKey": "p11-maker-checker-apply",
            "explicitApproval": True,
        }
        same_maker = client.post(
            layout_url + "/approvals",
            headers={
                **maker_headers,
                "X-InspectorPro-Session": "maker-p11-session",
            },
            json=approval_body,
        )
        checker_headers = {
            "Authorization": f"Bearer {checker_token}",
            "X-InspectorPro-Session": "checker-p11-session",
        }
        checker_approval = client.post(
            layout_url + "/approvals",
            headers=checker_headers,
            json=approval_body,
        )
        if checker_approval.status_code == 200:
            approval = checker_approval.json()
            applied = client.post(
                layout_url + "/apply",
                headers=checker_headers,
                json={
                    "approvalToken": approval["approvalToken"],
                    "binding": selected["transactionBinding"],
                    "idempotencyKey": "p11-maker-checker-apply",
                },
            )
        else:
            approval = {}
            applied = checker_approval
        same_maker_error = (
            same_maker.json().get("error", {}).get("code")
            if same_maker.headers.get("content-type", "").startswith(
                "application/json"
            )
            else None
        )
        receipt = (
            applied.json().get("receipt", {})
            if applied.status_code == 200
            else {}
        )
        checks = {
            "pilotPolicyEnabled": (
                host.require_distinct_approver
                and host.transaction_runtime.require_distinct_approver
            ),
            "productPrincipalIngress": (
                host.principal_mode == "bearer"
                and bootstrap["principal"]["principalId"] == "maker-p11"
            ),
            "bearerAuthenticationRequired": (
                authentication_required.status_code == 401
                and authentication_required.headers.get(
                    "www-authenticate"
                )
                == "Bearer"
                and invalid_identity.status_code == 401
            ),
            "bootstrapReportsPolicy": (
                bootstrap["capabilities"][
                    "makerCheckerRequired"
                ]
                is True
                and bootstrap["capabilities"][
                    "principalAuthentication"
                ]
                == "bearer"
            ),
            "sameMakerRejectedBeforeClaim": (
                same_maker.status_code == 403
                and same_maker_error == "maker_checker_required"
            ),
            "distinctCheckerApproved": (
                checker_approval.status_code == 200
            ),
            "distinctCheckerApplied": applied.status_code == 200,
            "canonicalReceiptPersisted": bool(
                receipt.get("receiptId")
            ),
        }
        return {
            "schemaVersion": "facility-layout-p11-maker-checker-v1",
            "generatedAtUtc": _utc_now(),
            "mode": {
                "requireDistinctApprover": True,
                "principalAuthentication": host.principal_mode,
                "defaultLocalDemoUnaffected": True,
            },
            "identities": {
                "maker": "maker-p11",
                "checker": "checker-p11",
                "distinct": True,
            },
            "observations": {
                "unauthenticatedStatus": (
                    authentication_required.status_code
                ),
                "invalidIdentityStatus": invalid_identity.status_code,
                "bootstrapPrincipalId": bootstrap["principal"][
                    "principalId"
                ],
                "sameMakerStatus": same_maker.status_code,
                "sameMakerErrorCode": same_maker_error,
                "checkerApprovalStatus": checker_approval.status_code,
                "checkerApplyStatus": applied.status_code,
                "receiptId": receipt.get("receiptId"),
            },
            "checks": checks,
            "releaseGateMet": all(checks.values()),
        }
    finally:
        client.close()
        host.close()


def _zone_fixture(zone_type: str, zone_id: str) -> dict[str, Any]:
    fixture = _read_json(
        ROOT
        / "tests"
        / "fixtures"
        / "facility_layout"
        / "two_asset_cell.json"
    )
    zone = deepcopy(fixture["zones"][0])
    zone["zoneId"] = zone_id
    zone["zoneType"] = zone_type
    zone["label"] = (
        "P11 Manufacturing Cell"
        if zone_type == "workcell"
        else "P11 Warehouse Storage"
    )
    # The local authoritative shell is 40 m by 30 m. Use its full valid
    # planning area so adding the workflow marker does not retroactively put
    # existing placements outside their only applicable zone.
    zone["boundary"] = [
        {"x": 0, "z": 0},
        {"x": 40, "z": 0},
        {"x": 40, "z": 30},
        {"x": 0, "z": 30},
    ]
    for anchor in zone.get("anchors", []):
        anchor["position"] = {"x": 2, "y": 0, "z": 2}
    zone.pop("allowedAssetCategories", None)
    return zone


def build_real_soak_evidence(
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    ledger_path = ledger_path or REAL_SOAK_EVENT_LEDGER
    if not ledger_path.is_file():
        return {
            "startedAtUtc": None,
            "lastEvaluatedAtUtc": _utc_now(),
            "elapsedDays": 0,
            "requirements": deepcopy(SOAK_REQUIREMENTS),
            "observed": {
                "layouts": 0,
                "editingSessions": 0,
                "agentPreviews": 0,
                "approvedReceiptBackedApplies": 0,
                "byteIdenticalDismissals": 0,
                "rejectedStaleOrUnauthorizedAttempts": 0,
                "reopenCyclesPerLayout": 0,
                "canonicalReceiptIds": [],
            },
            "workflowsExercised": [],
            "checks": {
                "evidenceLedgerPresent": False,
                "eventChainValid": False,
                "buildIdentityMatchesCurrent": False,
            },
            "status": "not_started",
            "releaseGateMet": False,
            "blockers": ["real_soak_not_started"],
            "note": (
                "Real self-use is credited only from the source-bound, "
                "append-only runtime evidence ledger."
            ),
        }
    try:
        ledger = load_soak_events(ledger_path)
        summary = summarize_soak_events(ledger)
    except (SoakEvidenceError, OSError) as error:
        return {
            "startedAtUtc": None,
            "lastEvaluatedAtUtc": _utc_now(),
            "elapsedDays": 0,
            "requirements": deepcopy(SOAK_REQUIREMENTS),
            "observed": {},
            "checks": {
                "evidenceLedgerPresent": True,
                "eventChainValid": False,
                "buildIdentityMatchesCurrent": False,
            },
            "status": "evidence_invalid",
            "releaseGateMet": False,
            "blockers": ["real_soak_evidence_invalid"],
            "error": str(error),
            "artifact": _artifact(ledger_path),
        }
    current_identity = facility_build_identity(ROOT)
    campaign_identity = ledger.get("campaign", {}).get("buildIdentity", {})
    build_matches = (
        campaign_identity.get("aggregateSha256")
        == current_identity["aggregateSha256"]
    )
    checks = {
        **deepcopy(summary.get("checks", {})),
        "evidenceLedgerPresent": True,
        "buildIdentityMatchesCurrent": build_matches,
    }
    release_gate_met = summary["releaseGateMet"] is True and build_matches
    status = summary["status"] if build_matches else "build_changed"
    blockers = []
    if not build_matches:
        blockers.append("real_soak_build_changed")
    if not release_gate_met and not blockers:
        blockers.append(f"real_soak_{status}")
    return {
        **summary,
        "checks": checks,
        "status": status,
        "releaseGateMet": release_gate_met,
        "blockers": blockers,
        "artifact": _artifact(ledger_path),
        "campaignBuildIdentity": deepcopy(campaign_identity),
        "currentBuildIdentity": current_identity,
    }


def run_accelerated_soak(
    root: Path,
    *,
    layout_count: int = 10,
    reopen_cycles: int = 5,
    real_soak_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if layout_count < 10:
        raise ValueError("P11 accelerated soak requires at least 10 layouts.")
    if reopen_cycles < 5:
        raise ValueError("P11 accelerated soak requires 5 reopen cycles.")

    root.mkdir(parents=True, exist_ok=True)
    host = LocalFacilityLayoutHost(root)
    bootstrap = host.ensure_bootstrap()
    principal = host.principal()
    frame = deepcopy(bootstrap["layout"]["layout"]["coordinateFrame"])
    source_shell_ref = deepcopy(
        bootstrap["layout"]["layout"]["sourceShellRef"]
    )
    policy_set_ref = deepcopy(
        bootstrap["layout"]["layout"]["policySetRef"]
    )
    assets = deepcopy(bootstrap["assetCatalog"][:2])
    client = _api_client(host)
    layout_ids: list[str] = []
    receipts: list[dict[str, Any]] = []
    dismissal_checks: list[dict[str, Any]] = []
    rejected_attempts: list[dict[str, Any]] = []
    proposal_previews = 0
    session_cycles = 0

    for index in range(layout_count):
        layout_id = f"fl-p11-soak-{index + 1:02d}"
        layout = create_layout_document(
            layout_id=layout_id,
            display_name=f"P11 Soak Layout {index + 1:02d}",
            association={
                "siteId": LOCAL_SITE_ID,
                "areaId": f"p11-area-{index + 1:02d}",
            },
            coordinate_frame=frame,
            source_shell_ref=source_shell_ref,
            policy_set_ref=policy_set_ref,
            created_at="2026-07-29T00:00:00Z",
        )
        created = host.service.create_layout(
            principal,
            LOCAL_SITE_ID,
            layout,
        )
        layout_ids.append(layout_id)

        before = _layout_receipt(client, layout_id)
        _, dismissed_selected = _create_proposal(
            client,
            layout_id,
            before,
            assets,
            request_id=f"p11-dismiss-{index + 1:02d}",
        )
        proposal_previews += 1
        preview = client.get(
            (
                f"/api/facility-layouts/{LOCAL_SITE_ID}/{layout_id}"
                f"/proposals/{dismissed_selected['proposalId']}/preview"
            )
        )
        if preview.status_code != 200 or not preview.json()["previewPure"]:
            raise AssertionError(preview.text)
        dismiss_session = f"p11-dismiss-session-{index + 1:02d}"
        dismissed = client.delete(
            (
                f"/api/facility-layouts/{LOCAL_SITE_ID}/{layout_id}"
                f"/proposals/{dismissed_selected['proposalId']}"
            ),
            headers={"X-InspectorPro-Session": dismiss_session},
        )
        if dismissed.status_code != 200:
            raise AssertionError(dismissed.text)
        session_cycles += 1
        after_dismiss = _layout_receipt(client, layout_id)
        byte_identical = (
            before["revision"] == after_dismiss["revision"]
            and canonical_layout_bytes(before["layout"])
            == canonical_layout_bytes(after_dismiss["layout"])
        )
        dismissal_checks.append(
            {
                "layoutId": layout_id,
                "proposalId": dismissed_selected["proposalId"],
                "byteIdentical": byte_identical,
            }
        )

        _, selected = _create_proposal(
            client,
            layout_id,
            after_dismiss,
            assets,
            request_id=f"p11-apply-{index + 1:02d}",
        )
        proposal_previews += 1
        session = f"p11-approve-session-{index + 1:02d}"
        key = f"p11-approved-apply-{index + 1:02d}"
        approval = _approve(
            client,
            layout_id,
            selected,
            session_id=session,
            key=key,
        )
        session_cycles += 1

        if index < 5:
            rejected = _apply(
                client,
                layout_id,
                selected,
                approval,
                session_id=f"{session}-wrong",
                key=key,
            )
            rejected_attempts.append(
                {
                    "layoutId": layout_id,
                    "kind": "wrong_session",
                    "statusCode": rejected.status_code,
                    "errorCode": (
                        rejected.json().get("error", {}).get("code")
                    ),
                    "rejected": rejected.status_code in (403, 409),
                }
            )
            session_cycles += 1

        applied = _apply(
            client,
            layout_id,
            selected,
            approval,
            session_id=session,
            key=key,
        )
        if applied.status_code != 200:
            raise AssertionError(applied.text)
        result = applied.json()
        if result.get("replayed") is not False:
            raise AssertionError("First apply unexpectedly replayed.")
        receipt = result["receipt"]
        receipt_response = client.get(
            (
                f"/api/facility-layouts/{LOCAL_SITE_ID}/{layout_id}"
                f"/receipts/{receipt['receiptId']}"
            )
        )
        if receipt_response.status_code != 200:
            raise AssertionError(receipt_response.text)
        retrieved = receipt_response.json()
        replay = _apply(
            client,
            layout_id,
            selected,
            approval,
            session_id=session,
            key=key,
        )
        if replay.status_code != 200 or replay.json().get("replayed") is not True:
            raise AssertionError(replay.text)
        replay_receipt = replay.json()["receipt"]
        session_cycles += 1
        receipts.append(
            {
                "layoutId": layout_id,
                "receiptId": receipt["receiptId"],
                "canonicalReceiptSha256": _sha256_bytes(
                    _canonical_json_bytes(receipt)
                ),
                "retrievedExactly": retrieved == receipt,
                "replayReceiptMatches": replay_receipt == receipt,
                "receipt": receipt,
            }
        )

    stale_layout_id = layout_ids[-1]
    stale_before = _layout_receipt(client, stale_layout_id)
    _, stale_selected = _create_proposal(
        client,
        stale_layout_id,
        stale_before,
        assets[:1],
        request_id="p11-stale-proposal",
    )
    proposal_previews += 1
    stale_session = "p11-stale-session"
    stale_key = "p11-stale-approval"
    stale_approval = _approve(
        client,
        stale_layout_id,
        stale_selected,
        session_id=stale_session,
        key=stale_key,
    )
    renamed = client.put(
        f"/api/facility-layouts/{LOCAL_SITE_ID}/{stale_layout_id}",
        json={
            "baseRevision": stale_before["revision"],
            "operations": [
                {
                    "op": "rename_layout",
                    "displayName": "P11 Stale Proposal Control",
                }
            ],
        },
    )
    if renamed.status_code != 200:
        raise AssertionError(renamed.text)
    stale_revision = renamed.json()["revision"]
    stale_apply = _apply(
        client,
        stale_layout_id,
        stale_selected,
        stale_approval,
        session_id=stale_session,
        key=stale_key,
    )
    after_stale = _layout_receipt(client, stale_layout_id)
    rejected_attempts.append(
        {
            "layoutId": stale_layout_id,
            "kind": "stale_revision",
            "statusCode": stale_apply.status_code,
            "errorCode": stale_apply.json().get("error", {}).get("code"),
            "rejected": (
                stale_apply.status_code == 409
                and after_stale["revision"] == stale_revision
            ),
        }
    )
    session_cycles += 1

    for layout_id, zone_type in (
        (layout_ids[0], "workcell"),
        (layout_ids[1], "storage"),
    ):
        current = _layout_receipt(client, layout_id)
        response = client.put(
            f"/api/facility-layouts/{LOCAL_SITE_ID}/{layout_id}",
            json={
                "baseRevision": current["revision"],
                "operations": [
                    {
                        "op": "add_zone",
                        "zone": _zone_fixture(
                            zone_type,
                            f"zn-p11-{zone_type}",
                        ),
                    }
                ],
            },
        )
        if response.status_code != 200:
            raise AssertionError(response.text)

    expected_revisions = {
        layout_id: _layout_receipt(client, layout_id)["revision"]
        for layout_id in layout_ids
    }
    client.close()
    host.close()

    reopen_checks = []
    for cycle in range(reopen_cycles):
        reopened = LocalFacilityLayoutHost(root)
        reopened_client = _api_client(reopened)
        for layout_id in layout_ids:
            session = f"p11-reopen-{cycle + 1:02d}-{layout_id}"
            response = reopened_client.get(
                f"/api/facility-layouts/{LOCAL_SITE_ID}/{layout_id}",
                headers={"X-InspectorPro-Session": session},
            )
            okay = (
                response.status_code == 200
                and response.json()["revision"]
                == expected_revisions[layout_id]
            )
            reopen_checks.append(
                {
                    "cycle": cycle + 1,
                    "layoutId": layout_id,
                    "passed": okay,
                }
            )
            session_cycles += 1
        for record in receipts:
            response = reopened_client.get(
                (
                    f"/api/facility-layouts/{LOCAL_SITE_ID}/"
                    f"{record['layoutId']}/receipts/{record['receiptId']}"
                )
            )
            if (
                response.status_code != 200
                or response.json() != record["receipt"]
            ):
                raise AssertionError(response.text)
        reopened_client.close()
        reopened.close()

    checks = {
        "tenOrMoreLayouts": len(layout_ids) >= 10,
        "twentyOrMorePreviews": proposal_previews >= 20,
        "tenOrMoreApprovedApplies": len(receipts) >= 10,
        "canonicalReceipts": all(
            item["retrievedExactly"]
            and item["replayReceiptMatches"]
            for item in receipts
        ),
        "fiveOrMoreByteIdenticalDismissals": sum(
            1 for item in dismissal_checks if item["byteIdentical"]
        )
        >= 5,
        "fiveOrMoreRejectedAttempts": sum(
            1 for item in rejected_attempts if item["rejected"]
        )
        >= 5,
        "fiveReopenCyclesPerLayout": (
            len(reopen_checks) == reopen_cycles * len(layout_ids)
            and all(item["passed"] for item in reopen_checks)
        ),
        "warehouseAndCellZonesExercised": True,
    }
    accelerated = {
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "layoutIds": layout_ids,
        "counts": {
            "layouts": len(layout_ids),
            "proposalPreviews": proposal_previews,
            "approvedReceiptBackedApplies": len(receipts),
            "byteIdenticalDismissals": sum(
                1 for item in dismissal_checks if item["byteIdentical"]
            ),
            "rejectedStaleOrUnauthorizedAttempts": sum(
                1 for item in rejected_attempts if item["rejected"]
            ),
            "reopenCyclesPerLayout": reopen_cycles,
            "acceleratedSessionCycles": session_cycles,
        },
        "dismissals": dismissal_checks,
        "rejectedAttempts": rejected_attempts,
        "canonicalReceipts": receipts,
        "reopenChecks": reopen_checks,
        "note": (
            "This deterministic acceleration proves mechanics and persistence. "
            "It is not credited as elapsed self-use time."
        ),
    }
    real_soak = (
        deepcopy(dict(real_soak_evidence))
        if isinstance(real_soak_evidence, Mapping)
        else build_real_soak_evidence()
    )
    return {
        "schemaVersion": "facility-layout-p11-soak-ledger-v1",
        "generatedAtUtc": _utc_now(),
        "acceleratedDeterministicSoak": accelerated,
        "realElapsedSoak": real_soak,
        "releaseGateMet": (
            accelerated["status"] == "passed"
            and real_soak["releaseGateMet"]
        ),
        "releaseGateReason": (
            "passed"
            if accelerated["status"] == "passed"
            and real_soak["releaseGateMet"]
            else real_soak["status"]
            if accelerated["status"] == "passed"
            else "accelerated_soak_failed"
        ),
    }


def _documentation_contract_checks(
    document_id: str,
    normalized_text: str,
) -> dict[str, bool]:
    text = normalized_text.lower()
    contracts = {
        "pilot_runbook": {
            "controlledPilotBoundary": (
                "controlled pilot preparation" in text
                and "does not declare" in text
                and "release-ready" in text
            ),
            "safetyAuthorityBoundary": SAFETY_DISCLAIMER.lower() in text,
            "makerCheckerRequired": (
                "require_distinct_approver=true" in text
            ),
            "rollbackPreservesData": (
                "must not delete or convert layout documents" in text
            ),
        },
        "release_gates": {
            "evidenceGenerationIsNotReadiness": (
                "does not mean the pilot gate is met" in text
            ),
            "standardAndMinimumHardwareRequired": (
                "standard and minimum hardware" in text
                and "hardware fingerprint" in text
                and "rebuilt from raw observations" in text
            ),
            "manualScreenReaderRequired": (
                "manual screen-reader" in text
            ),
            "licensingClearanceRequired": (
                "cleared redistribution rights" in text
                and "dependency license review" in text
            ),
            "exactSoakDurationRequired": (
                "1,209,600 continuous elapsed seconds" in text
            ),
            "generatedSoakCannotIncrementCounts": (
                "generated release json cannot increment its counts" in text
            ),
            "manualEvidenceEditsForbidden": (
                "do not change an evidence file manually" in text
            ),
        },
        "licensing": {
            "noAutomatedLegalClearanceClaim": (
                "without claiming legal clearance" in text
            ),
            "machineHumanAndLegalGatesRequired": (
                "machine dependency assessment passes" in text
                and "qualified human explicitly records approval" in text
                and "explicitly claims legal clearance" in text
            ),
            "industrialAssetRightsRequired": (
                "blocks public redistribution" in text
            ),
            "inventoryContradictionFailsClosed": (
                "cannot clear the p11 licensing gate" in text
            ),
        },
        "soak_procedure": {
            "exactContinuousDuration": (
                "1,209,600 continuous elapsed seconds" in text
            ),
            "campaignMetadataGenesisBound": (
                "forms the genesis hash" in text
            ),
            "recursiveWriteSourceBound": (
                "nested workflow modules" in text
                and "recursive source identity" in text
            ),
            "generatedProjectionCannotChangeCounts": (
                "editing it never changes soak counts" in text
            ),
            "realAndAcceleratedSeparated": (
                "accelerated activity never increments" in text
            ),
        },
    }
    return contracts.get(document_id, {"knownDocument": False})


def build_documentation_evidence() -> dict[str, Any]:
    paths = (
        (
            "pilot_runbook",
            ROOT / "docs" / "facility-layout-p11-pilot-runbook.md",
        ),
        (
            "release_gates",
            ROOT / "docs" / "facility-layout-p11-release-gates.md",
        ),
        (
            "licensing",
            ROOT / "docs" / "facility-layout-p11-licensing.md",
        ),
        (
            "soak_procedure",
            ROOT / "docs" / "facility-layout-p11-soak-procedure.md",
        ),
    )
    records = []
    for document_id, path in paths:
        text = path.read_text(encoding="ascii")
        normalized_text = " ".join(text.split())
        checks = _documentation_contract_checks(
            document_id,
            normalized_text,
        )
        records.append(
            {
                "documentId": document_id,
                **_artifact(path),
                "containsSafetyDisclaimer": (
                    SAFETY_DISCLAIMER in normalized_text
                ),
                "accuracyChecks": checks,
                "contractPassed": bool(checks) and all(checks.values()),
            }
        )
    runbook = records[0]
    all_contracts_passed = all(
        record["contractPassed"] for record in records
    )
    return {
        "schemaVersion": "facility-layout-p11-documentation-evidence-v2",
        "generatedAtUtc": _utc_now(),
        "documents": records,
        "pilotRunbookContainsSafetyDisclaimer": runbook[
            "containsSafetyDisclaimer"
        ],
        "allDocumentContractsPassed": all_contracts_passed,
        "releaseGateMet": (
            runbook["containsSafetyDisclaimer"] and all_contracts_passed
        ),
    }


def generate_release_evidence(
    output_dir: Path,
    *,
    run_suites: bool,
    skip_soak: bool,
    soak_root: Path | None = None,
    rollback_root: Path | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    suite_matrix = build_suite_matrix()
    suite_evidence = (
        run_suite_matrix(suite_matrix)
        if run_suites
        else {
            **suite_matrix,
            "results": {},
            "allPassed": False,
            "releaseGateMet": False,
            "executionStatus": "not_run",
        }
    )
    suite_results = suite_evidence.get("results", {})
    performance = build_performance_evidence()
    accessibility = build_accessibility_evidence()
    visuals = build_visual_manifest()
    with tempfile.TemporaryDirectory(
        prefix="facility-layout-p11-flags-",
    ) as temporary:
        flags = run_feature_flag_matrix(Path(temporary))
    with tempfile.TemporaryDirectory(
        prefix="facility-layout-p11-maker-checker-",
    ) as temporary:
        maker_checker = run_maker_checker_pilot_gate(
            Path(temporary)
        )
    recovery = build_webgl_offline_evidence(suite_results)
    licensing = build_licensing_inventory()
    documentation = build_documentation_evidence()

    with tempfile.TemporaryDirectory(
        prefix="facility-layout-p11-rollback-",
        dir=rollback_root.parent if rollback_root else None,
    ) as temporary:
        rollback = run_rollback_drill(
            rollback_root or Path(temporary)
        )

    real_soak = build_real_soak_evidence()
    if skip_soak:
        soak = {
            "schemaVersion": "facility-layout-p11-soak-ledger-v1",
            "generatedAtUtc": _utc_now(),
            "acceleratedDeterministicSoak": {
                "status": "not_run",
            },
            "realElapsedSoak": real_soak,
            "releaseGateMet": False,
            "releaseGateReason": (
                real_soak["status"]
                if not real_soak["releaseGateMet"]
                else "accelerated_soak_not_run"
            ),
        }
    else:
        with tempfile.TemporaryDirectory(
            prefix="facility-layout-p11-soak-",
            dir=soak_root.parent if soak_root else None,
        ) as temporary:
            soak = run_accelerated_soak(
                soak_root or Path(temporary),
                real_soak_evidence=real_soak,
            )

    artifacts = {
        "p11-performance-budget.json": performance,
        "p11-accessibility-evidence.json": accessibility,
        "p11-visual-manifest.json": visuals,
        "p11-feature-flag-matrix.json": flags,
        "p11-maker-checker-evidence.json": maker_checker,
        "p11-webgl-offline-evidence.json": recovery,
        "p11-licensing-inventory.json": licensing,
        "p11-suite-matrix.json": suite_evidence,
        "p11-rollback-drill.json": rollback,
        "p11-soak-ledger.json": soak,
        "p11-documentation-evidence.json": documentation,
    }
    for name, value in artifacts.items():
        _write_json(output_dir / name, value)

    accelerated_passed = (
        soak.get("acceleratedDeterministicSoak", {}).get("status")
        in ("passed", "not_run")
    )
    evidence_generation_passed = all(
        (
            performance["observedChecksPassed"],
            accessibility["staticContractPassed"],
            visuals["manifestValid"],
            recovery["webglRecovery"]["staticContractPassed"],
            recovery["offlineAndCorruptArtifacts"]["passed"],
            licensing["vendoredJavaScriptCoverage"]["complete"],
            rollback["noDataConversion"],
            maker_checker["releaseGateMet"],
            documentation["pilotRunbookContainsSafetyDisclaimer"],
            accelerated_passed,
        )
    )
    real_soak = soak["realElapsedSoak"]
    blockers = sorted(
        {
            *performance["blockers"],
            *flags["blockers"],
            *licensing["blockers"],
            *real_soak.get("blockers", []),
            *(
                ["accelerated_deterministic_soak_not_green"]
                if soak.get("acceleratedDeterministicSoak", {}).get("status")
                != "passed"
                else []
            ),
            *accessibility.get("blockers", []),
            *(
                ["visual_viewport_theme_matrix_incomplete"]
                if not visuals["releaseGateMet"]
                else []
            ),
            *(
                ["security_suite_matrix_not_green"]
                if not suite_evidence.get("allPassed")
                else []
            ),
            *(
                ["webgl_behavioral_suite_not_green"]
                if not recovery["releaseGateMet"]
                else []
            ),
            *rollback["blockers"],
            *(
                ["maker_checker_pilot_gate_failed"]
                if not maker_checker["releaseGateMet"]
                else []
            ),
            *(
                ["pilot_documentation_gate_failed"]
                if not documentation["releaseGateMet"]
                else []
            ),
        }
    )
    section_gates = {
        "performance": performance["releaseGateMet"],
        "accessibility": accessibility["releaseGateMet"],
        "visual": visuals["releaseGateMet"],
        "webglOffline": recovery["releaseGateMet"],
        "featureFlags": flags["releaseGateMet"],
        "makerChecker": maker_checker["releaseGateMet"],
        "securitySuites": bool(suite_evidence.get("releaseGateMet")),
        "rollback": rollback["releaseGateMet"],
        "licensing": licensing["releaseGateMet"],
        "acceleratedSoak": (
            soak.get("acceleratedDeterministicSoak", {}).get("status")
            == "passed"
        ),
        "realSoak": real_soak["releaseGateMet"],
        "documentation": documentation["releaseGateMet"],
    }
    release_gate_met = all(section_gates.values()) and not blockers
    result = {
        "schemaVersion": "facility-layout-p11-release-evidence-v1",
        "generatedAtUtc": _utc_now(),
        "evidenceGenerationPassed": evidence_generation_passed,
        "releaseGateMet": release_gate_met,
        "status": "passed" if release_gate_met else "blocked",
        "literalTimeBoundStatus": soak["realElapsedSoak"]["status"],
        "blockers": blockers,
        "sections": {
            "performance": performance["status"],
            "accessibility": (
                "static_pass_manual_audit_pending"
                if accessibility["staticContractPassed"]
                else "failed"
            ),
            "visual": (
                "passed"
                if visuals["releaseGateMet"]
                else "manifest_valid_matrix_incomplete"
                if visuals["manifestValid"]
                else "failed"
            ),
            "webglOffline": (
                "passed" if recovery["releaseGateMet"] else "partial"
            ),
            "featureFlags": (
                "passed" if flags["releaseGateMet"] else "blocked"
            ),
            "makerChecker": (
                "passed"
                if maker_checker["releaseGateMet"]
                else "failed"
            ),
            "securitySuites": (
                "passed"
                if suite_evidence.get("allPassed")
                else "not_green"
            ),
            "rollback": rollback["status"],
            "licensing": (
                "passed" if licensing["releaseGateMet"] else "blocked"
            ),
            "acceleratedSoak": soak[
                "acceleratedDeterministicSoak"
            ]["status"],
            "realSoak": soak["realElapsedSoak"]["status"],
            "documentation": (
                "passed"
                if documentation["releaseGateMet"]
                else "failed"
            ),
        },
        "sectionGates": section_gates,
        "artifacts": sorted(artifacts),
        "safetyDisclaimer": SAFETY_DISCLAIMER,
        "source": {
            "verifier": _artifact(Path(__file__).resolve()),
            "authorizationContract": _artifact(AUTHORIZATION_CONTRACT),
        },
    }
    _write_json(output_dir / "p11-release-evidence.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate P11 Facility Layout release evidence."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=RELEASE_DIR,
    )
    parser.add_argument(
        "--run-suite-matrix",
        action="store_true",
        help="Execute the existing security, WebGL, and workspace suites.",
    )
    parser.add_argument(
        "--skip-accelerated-soak",
        action="store_true",
    )
    parser.add_argument(
        "--require-release-ready",
        action="store_true",
        help="Return non-zero while any P11 release gate remains blocked.",
    )
    args = parser.parse_args()
    result = generate_release_evidence(
        args.output_dir.resolve(),
        run_suites=args.run_suite_matrix,
        skip_soak=args.skip_accelerated_soak,
    )
    print(
        "PASS" if result["evidenceGenerationPassed"] else "FAIL",
        "evidence_generation",
        sep="\t",
    )
    print(
        "PASS" if result["releaseGateMet"] else "BLOCKED",
        "release_gate",
        sep="\t",
    )
    for blocker in result["blockers"]:
        print("BLOCKER", blocker, sep="\t")
    print(
        "RESULT",
        (args.output_dir.resolve() / "p11-release-evidence.json"),
        sep="\t",
    )
    if not result["evidenceGenerationPassed"]:
        return 1
    if args.require_release_ready and not result["releaseGateMet"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
