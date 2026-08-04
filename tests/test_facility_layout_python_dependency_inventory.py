from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.inventory_facility_python_dependencies import (
    MappingDistributionProvider,
    build_inventory,
    exit_code_for_inventory,
    parse_direct_requirements,
    render_notice_draft,
    write_inventory_outputs,
)


GENERATED_AT = "2026-07-29T12:00:00Z"
ENVIRONMENT = {
    "pythonImplementation": "CPython",
    "pythonVersion": "3.14.0",
    "operatingSystem": "TestOS",
    "operatingSystemRelease": "1",
    "machineArchitecture": "test-arch",
}


def _snapshot(
    name: str,
    version: str,
    *,
    license_expression: str | None = "MIT",
    legacy_license: str | None = None,
    license_classifiers: list[str] | None = None,
) -> dict:
    raw = (
        f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n"
    ).encode("ascii")
    classifiers = license_classifiers or []
    return {
        "name": name,
        "version": version,
        "licenseExpression": license_expression,
        "legacyLicense": legacy_license,
        "classifiers": list(classifiers),
        "licenseClassifiers": list(classifiers),
        "homePage": "https://example.test/home",
        "resolvedHomepage": "https://example.test/home",
        "projectUrls": [
            {
                "raw": "Source, https://example.test/source",
                "label": "Source",
                "url": "https://example.test/source",
            }
        ],
        "metadata": {
            "metadataVersion": "2.4",
            "summary": f"{name} test package",
            "requiresPython": ">=3.10",
            "author": "Test Author",
            "authorEmail": "author@example.test",
            "maintainer": None,
            "maintainerEmail": None,
            "headers": {
                "Metadata-Version": ["2.4"],
                "Name": [name],
                "Version": [version],
            },
            "rawSource": {
                "present": True,
                "byteLength": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            },
        },
        "installation": {
            "distInfoName": f"{name}-{version}.dist-info",
            "installer": "pip",
            "directUrl": None,
            "directUrlSource": None,
        },
    }


def _build(
    tmp_path: Path,
    requirements: str,
    snapshots: dict[str, dict],
) -> dict:
    requirements_path = tmp_path / "requirements.txt"
    source_path = tmp_path / "inventory_tool.py"
    requirements_path.write_text(requirements, encoding="ascii")
    source_path.write_text("# deterministic source\n", encoding="ascii")
    return build_inventory(
        requirements_path,
        provider=MappingDistributionProvider(snapshots),
        generator_source=source_path,
        generated_at_utc=GENERATED_AT,
        environment=ENVIRONMENT,
        root=tmp_path,
    )


def test_parser_identifies_direct_requirements_extras_markers_and_pins():
    parsed = parse_direct_requirements(
        """
        # comment
        fastapi==0.124.0
        uvicorn[standard]>=0.38  # inline comment
        demo @ https://example.test/demo.whl#sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
        windows-only==2.0; sys_platform == "win32"
        """
    )

    requirements = parsed["requirements"]
    assert parsed["findings"] == []
    assert [item["canonicalName"] for item in requirements] == [
        "fastapi",
        "uvicorn",
        "demo",
        "windows-only",
    ]
    assert requirements[0]["exactlyPinned"] is True
    assert requirements[1]["extras"] == ["standard"]
    assert requirements[1]["exactlyPinned"] is False
    assert requirements[2]["exactlyPinned"] is True
    assert requirements[3]["marker"] == 'sys_platform == "win32"'


def test_parser_fails_closed_for_directives_duplicates_and_invalid_lines():
    parsed = parse_direct_requirements(
        """
        -r more-requirements.txt
        demo==1.0
        demo==1.1
        this is not a requirement ???
        """
    )

    assert {item["code"] for item in parsed["findings"]} == {
        "unsupported_requirements_directive",
        "duplicate_direct_requirement",
        "invalid_direct_requirement",
    }


def test_exact_metadata_and_source_hashes_are_preserved(tmp_path: Path):
    inventory = _build(
        tmp_path,
        "Example-Package==1.2.3\n",
        {"example-package": _snapshot("Example-Package", "1.2.3")},
    )

    dependency = inventory["dependencies"][0]
    distribution = dependency["installedDistribution"]
    assert inventory["machineAssessment"]["gateMet"] is True
    assert inventory["releaseGateMet"] is False
    assert inventory["humanLegalApproval"] == {
        "status": "not_performed",
        "required": True,
        "approved": False,
        "legalClearanceClaimed": False,
        "statement": (
            "Machine-observed metadata is evidence for review, not legal "
            "advice or approval. A qualified human must determine license "
            "obligations for the exact distributed artifact."
        ),
    }
    assert distribution["version"] == "1.2.3"
    assert distribution["licenseExpression"] == "MIT"
    assert distribution["classifiers"] == []
    assert distribution["resolvedHomepage"] == "https://example.test/home"
    assert distribution["metadata"]["headers"]["Name"] == [
        "Example-Package"
    ]
    assert len(distribution["metadata"]["rawSource"]["sha256"]) == 64
    requirements_bytes = (tmp_path / "requirements.txt").read_bytes()
    assert inventory["sourceBinding"]["requirements"]["sha256"] == (
        hashlib.sha256(requirements_bytes).hexdigest()
    )
    assert len(inventory["sourceBinding"]["generator"]["sha256"]) == 64
    assert len(inventory["sourceBinding"]["combinedSha256"]) == 64


def test_missing_unpinned_unknown_and_version_mismatch_block_machine_gate(
    tmp_path: Path,
):
    inventory = _build(
        tmp_path,
        (
            "missing==1.0\n"
            "loose>=2.0\n"
            "unknown==1.0\n"
            "mismatch==3.0\n"
        ),
        {
            "loose": _snapshot("loose", "2.1"),
            "unknown": _snapshot(
                "unknown",
                "1.0",
                license_expression=None,
                legacy_license=None,
            ),
            "mismatch": _snapshot("mismatch", "2.0"),
        },
    )

    codes = set(inventory["machineAssessment"]["blockerCodes"])
    assert {
        "direct_requirement_missing",
        "direct_requirement_unpinned",
        "license_metadata_unknown",
        "installed_version_outside_declared_specifier",
    } <= codes
    assert inventory["machineAssessment"]["gateMet"] is False
    assert exit_code_for_inventory(inventory) == 2


def test_pymupdf_dual_agpl_commercial_terms_are_explicit_blockers(
    tmp_path: Path,
):
    inventory = _build(
        tmp_path,
        "PyMuPDF==1.27.2.3\n",
        {
            "pymupdf": _snapshot(
                "PyMuPDF",
                "1.27.2.3",
                license_expression=None,
                legacy_license=(
                    "Dual Licensed - GNU AFFERO GPL 3.0 or "
                    "Artifex Commercial License"
                ),
            )
        },
    )

    codes = set(inventory["machineAssessment"]["blockerCodes"])
    assert {
        "strong_copyleft_review_required",
        "commercial_or_dual_license_review_required",
        "pymupdf_dual_agpl_commercial_review_required",
    } <= codes
    assessment = inventory["dependencies"][0]["installedDistribution"][
        "licenseAssessment"
    ]
    assert assessment["strongCopyleftTermsDetected"] == [
        "gnu_affero",
        "gpl",
    ]
    assert assessment["commercialOrDualTermsDetected"] == [
        "commercial_license",
        "dual_license",
    ]
    assert assessment["legalConclusion"] is None


def test_notice_is_a_draft_and_never_claims_legal_clearance(tmp_path: Path):
    inventory = _build(
        tmp_path,
        "example==1.0\n",
        {"example": _snapshot("example", "1.0")},
    )
    notice = render_notice_draft(inventory)

    assert "DRAFT - MACHINE GENERATED - NOT LEGAL CLEARANCE" in notice
    assert "Human legal approval: **NOT PERFORMED**" in notice
    assert "Release clearance claimed: **NO**" in notice
    assert "`example==1.0`" in notice
    assert "MIT" in notice
    assert "legal clearance." in notice


def test_outputs_are_ascii_deterministic_and_round_trip(tmp_path: Path):
    inventory = _build(
        tmp_path,
        "example==1.0\n",
        {"example": _snapshot("example", "1.0")},
    )
    inventory_path = tmp_path / "licensing" / "inventory.json"
    notice_path = tmp_path / "docs" / "NOTICE-DRAFT.md"

    write_inventory_outputs(inventory, inventory_path, notice_path)
    first_inventory = inventory_path.read_bytes()
    first_notice = notice_path.read_bytes()
    write_inventory_outputs(inventory, inventory_path, notice_path)

    assert inventory_path.read_bytes() == first_inventory
    assert notice_path.read_bytes() == first_notice
    assert json.loads(first_inventory.decode("ascii")) == inventory
    first_notice.decode("ascii")
