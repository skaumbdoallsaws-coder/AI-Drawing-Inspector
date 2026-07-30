from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from tools.audit_facility_layout_accessibility import (
    CATEGORY_CHECKS,
    DEFAULT_OUTPUT_DIR,
    RAW_SCHEMA,
    SUMMARY_SCHEMA,
    THEMES,
    build_source_binding,
    interpret_accessibility_evidence,
    source_binding_status,
)


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="ascii")


def _manual_checklist(root: Path) -> Path:
    path = root / "docs" / "manual-screen-reader.md"
    _write(
        path,
        "# Manual Screen-Reader Checklist\n\n**Status: Pending**\n",
    )
    return path


def _contrast_sample(kind: str) -> dict:
    return {
        "sampleId": f"{kind}-001",
        "label": f"{kind} sample",
        "contrastRatio": 7.0,
        "requiredRatio": 4.5 if kind == "text" else 3.0,
        "passed": True,
    }


def _passing_raw(root: Path, source_paths: tuple[str, ...]) -> dict:
    categories = {
        name: {
            "checks": {check: True for check in checks},
            "passed": True,
        }
        for name, checks in CATEGORY_CHECKS.items()
    }
    runs = []
    for theme in THEMES:
        runs.append(
            {
                "theme": theme,
                "contrast": {
                    "textSamples": [_contrast_sample("text")],
                    "controlSamples": [_contrast_sample("control")],
                    "textFailures": [],
                    "controlFailures": [],
                },
            }
        )
    return {
        "schemaVersion": RAW_SCHEMA,
        "screenReaderAudit": "not_performed",
        "sourceBinding": build_source_binding(root, source_paths),
        "sourceStableDuringAudit": True,
        "network": {"externalResponses": []},
        "categories": categories,
        "runs": runs,
    }


def _fixture(tmp_path: Path) -> tuple[dict, tuple[str, ...], Path]:
    source_paths = (
        "static/facility_layout_workspace.js",
        "static/facility_layout_workspace.css",
        "tools/audit.py",
    )
    for index, relative in enumerate(source_paths):
        _write(tmp_path / relative, f"source-{index}\n")
    raw = _passing_raw(tmp_path, source_paths)
    return raw, source_paths, _manual_checklist(tmp_path)


def test_interpreter_accepts_automated_evidence_but_keeps_manual_gate_pending(
    tmp_path: Path,
):
    raw, source_paths, checklist = _fixture(tmp_path)

    summary = interpret_accessibility_evidence(
        raw,
        root=tmp_path,
        source_paths=source_paths,
        manual_checklist_path=checklist,
    )

    assert summary["schemaVersion"] == SUMMARY_SCHEMA
    assert summary["automatedAuditPassed"] is True
    assert summary["manualScreenReaderAudit"]["status"] == "pending"
    assert summary["claims"]["manualScreenReaderAudit"] is False
    assert summary["releaseGateMet"] is False
    assert summary["status"] == (
        "automated_pass_manual_screen_reader_pending"
    )
    assert summary["blockers"] == [
        "manual_screen_reader_audit_pending"
    ]


def test_missing_check_and_contradictory_pass_flag_fail_closed(
    tmp_path: Path,
):
    raw, source_paths, checklist = _fixture(tmp_path)
    del raw["categories"]["keyboard"]["checks"][
        "tabKeyboardActivationWorks"
    ]
    raw["categories"]["keyboard"]["passed"] = True

    summary = interpret_accessibility_evidence(
        raw,
        root=tmp_path,
        source_paths=source_paths,
        manual_checklist_path=checklist,
    )

    keyboard = summary["categoryStatus"]["keyboard"]
    assert keyboard["passed"] is False
    assert keyboard["missingChecks"] == ["tabKeyboardActivationWorks"]
    assert keyboard["reportedResultMatchesChecks"] is False
    assert summary["automatedAuditPassed"] is False
    assert "automated_keyboard_audit_failed" in summary["blockers"]
    assert "keyboard_reported_result_mismatch" in (
        summary["integrityFindings"]
    )


def test_missing_category_and_fake_screen_reader_claim_fail_closed(
    tmp_path: Path,
):
    raw, source_paths, checklist = _fixture(tmp_path)
    del raw["categories"]["announcements"]
    raw["screenReaderAudit"] = "passed"

    summary = interpret_accessibility_evidence(
        raw,
        root=tmp_path,
        source_paths=source_paths,
        manual_checklist_path=checklist,
    )

    assert summary["automatedAuditPassed"] is False
    assert "automated_announcements_audit_failed" in summary["blockers"]
    assert (
        "automated_runner_screen_reader_claim_invalid"
        in summary["blockers"]
    )
    assert summary["claims"]["manualScreenReaderAudit"] is False


def test_stale_or_duplicated_source_binding_fails_closed(tmp_path: Path):
    raw, source_paths, checklist = _fixture(tmp_path)
    _write(tmp_path / source_paths[0], "changed\n")

    stale = interpret_accessibility_evidence(
        raw,
        root=tmp_path,
        source_paths=source_paths,
        manual_checklist_path=checklist,
    )
    assert stale["sourceBinding"]["matches"] is False
    assert stale["sourceBinding"]["stalePaths"] == [source_paths[0]]
    assert stale["automatedAuditPassed"] is False

    raw = _passing_raw(tmp_path, source_paths)
    duplicated_path = raw["sourceBinding"]["files"][0]["path"]
    raw["sourceBinding"]["files"].append(
        deepcopy(raw["sourceBinding"]["files"][0])
    )
    duplicated = source_binding_status(
        raw["sourceBinding"],
        root=tmp_path,
        source_paths=source_paths,
    )
    assert duplicated["matches"] is False
    assert duplicated["requiredInputsExact"] is False
    assert duplicated["duplicatePaths"] == [duplicated_path]


def test_bad_contrast_and_external_response_cannot_be_hidden_by_pass_flags(
    tmp_path: Path,
):
    raw, source_paths, checklist = _fixture(tmp_path)
    sample = raw["runs"][0]["contrast"]["textSamples"][0]
    sample["contrastRatio"] = 2.0
    sample["passed"] = True
    raw["network"]["externalResponses"] = [
        "https://example.invalid/tracker.js"
    ]

    summary = interpret_accessibility_evidence(
        raw,
        root=tmp_path,
        source_paths=source_paths,
        manual_checklist_path=checklist,
    )

    assert summary["contrastRecordsValid"] is False
    assert summary["categoryStatus"]["contrast"]["passed"] is False
    assert summary["categoryStatus"]["network"]["passed"] is False
    assert "contrast_evidence_records_invalid" in summary["blockers"]
    assert "external_network_response_observed" in summary["blockers"]
    assert summary["automatedAuditPassed"] is False


def test_manual_checklist_must_exist_and_remain_explicitly_pending(
    tmp_path: Path,
):
    raw, source_paths, checklist = _fixture(tmp_path)
    checklist.write_text(
        "# Manual Screen-Reader Checklist\n\nStatus: Complete\n",
        encoding="ascii",
    )

    summary = interpret_accessibility_evidence(
        raw,
        root=tmp_path,
        source_paths=source_paths,
        manual_checklist_path=checklist,
    )

    assert summary["manualScreenReaderAudit"]["status"] == "unrecognized"
    assert "manual_screen_reader_checklist_invalid" in summary["blockers"]
    assert summary["releaseGateMet"] is False


def test_checked_in_raw_and_summary_are_consistent_when_present():
    raw_path = (
        DEFAULT_OUTPUT_DIR / "facility-layout-accessibility-raw.json"
    )
    summary_path = (
        DEFAULT_OUTPUT_DIR / "facility-layout-accessibility-summary.json"
    )
    if not raw_path.is_file() or not summary_path.is_file():
        return

    raw = json.loads(raw_path.read_text(encoding="ascii"))
    stored = json.loads(summary_path.read_text(encoding="ascii"))
    recomputed = interpret_accessibility_evidence(
        raw,
        raw_artifact_path=raw_path,
    )

    assert stored["schemaVersion"] == SUMMARY_SCHEMA
    assert stored["automatedAuditPassed"] == (
        recomputed["automatedAuditPassed"]
    )
    assert stored["releaseGateMet"] is False
    assert stored["blockers"] == recomputed["blockers"]
    assert stored["sourceBinding"] == recomputed["sourceBinding"]
    assert stored["rawArtifact"] == recomputed["rawArtifact"]
    assert stored["manualScreenReaderAudit"] == (
        recomputed["manualScreenReaderAudit"]
    )
