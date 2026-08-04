"""Inventory direct Python dependencies for the Facility Layout pilot.

This tool records machine-observed package metadata. It does not interpret
license obligations or represent legal approval. The command writes evidence
before returning a non-zero status when the machine assessment is blocked.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata as importlib_metadata
import json
from pathlib import Path
import platform
import re
import sys
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REQUIREMENTS = ROOT / "requirements.txt"
DEFAULT_INVENTORY = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "licensing"
    / "python-direct-dependency-inventory.json"
)
DEFAULT_NOTICE = (
    ROOT / "docs" / "facility-layout-python-third-party-notices-draft.md"
)
SCHEMA_VERSION = "facility-layout-python-dependency-inventory-v1"

_STRONG_COPYLEFT_PATTERNS = (
    ("agpl", re.compile(r"\bAGPL(?:[- ]?[0-9.]+)?\b", re.IGNORECASE)),
    (
        "gnu_affero",
        re.compile(
            r"GNU\s+AFFERO(?:\s+GENERAL\s+PUBLIC\s+LICENSE|\s+GPL)",
            re.IGNORECASE,
        ),
    ),
    (
        "gpl",
        re.compile(r"(?<![A-Z])GPL(?:[- ]?[0-9.]+)?\b", re.IGNORECASE),
    ),
    (
        "gnu_gpl",
        re.compile(r"GNU\s+GENERAL\s+PUBLIC\s+LICENSE", re.IGNORECASE),
    ),
)
_COMMERCIAL_REVIEW_PATTERNS = (
    (
        "commercial_license",
        re.compile(r"\bcommercial\s+licen[cs]e\b", re.IGNORECASE),
    ),
    (
        "dual_license",
        re.compile(r"\bdual(?:ly)?[\s-]+licen[cs]ed?\b", re.IGNORECASE),
    ),
    (
        "proprietary",
        re.compile(r"\bproprietary\b", re.IGNORECASE),
    ),
)
_UNKNOWN_LICENSE_VALUES = {"", "unknown", "n/a", "none", "not specified"}


class DistributionProvider(Protocol):
    """Resolve an installed distribution into serializable exact metadata."""

    def resolve(self, name: str) -> Mapping[str, Any] | None:
        """Return a snapshot, or None when the distribution is not installed."""


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _file_artifact(path: Path, *, root: Path | None = None) -> dict[str, Any]:
    payload = path.read_bytes()
    display_path: str
    if root is not None:
        try:
            display_path = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            display_path = path.name
    else:
        display_path = path.name
    return {
        "path": display_path,
        "byteLength": len(payload),
        "sha256": _sha256_bytes(payload),
    }


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _metadata_headers(message: Any) -> dict[str, list[str]]:
    names = sorted({str(key) for key in message.keys()}, key=str.casefold)
    return {
        name: [str(value) for value in (message.get_all(name) or [])]
        for name in names
    }


def _metadata_value(headers: Mapping[str, list[str]], name: str) -> str | None:
    for key, values in headers.items():
        if key.casefold() == name.casefold() and values:
            return values[0]
    return None


def _metadata_values(
    headers: Mapping[str, list[str]],
    name: str,
) -> list[str]:
    for key, values in headers.items():
        if key.casefold() == name.casefold():
            return list(values)
    return []


def _project_urls(headers: Mapping[str, list[str]]) -> list[dict[str, str]]:
    records = []
    for raw in _metadata_values(headers, "Project-URL"):
        label, separator, url = raw.partition(",")
        records.append(
            {
                "raw": raw,
                "label": label.strip() if separator else "",
                "url": url.strip() if separator else raw.strip(),
            }
        )
    return records


def _resolved_homepage(
    headers: Mapping[str, list[str]],
    project_urls: list[dict[str, str]],
) -> str | None:
    homepage = _metadata_value(headers, "Home-page")
    if homepage and homepage.strip():
        return homepage.strip()
    for record in project_urls:
        if record["label"].casefold() in {"homepage", "home"}:
            return record["url"] or None
    return None


class ImportlibDistributionProvider:
    """Read the exact installed distribution metadata via importlib.metadata."""

    def resolve(self, name: str) -> Mapping[str, Any] | None:
        try:
            distribution = importlib_metadata.distribution(name)
        except importlib_metadata.PackageNotFoundError:
            return None

        message = distribution.metadata
        headers = _metadata_headers(message)
        raw_metadata = distribution.read_text("METADATA")
        raw_bytes = (
            raw_metadata.encode("utf-8")
            if raw_metadata is not None
            else b""
        )
        direct_url = distribution.read_text("direct_url.json")
        installer = distribution.read_text("INSTALLER")
        project_urls = _project_urls(headers)
        distribution_path = getattr(distribution, "_path", None)

        return {
            "name": _metadata_value(headers, "Name") or name,
            "version": distribution.version,
            "licenseExpression": _metadata_value(
                headers,
                "License-Expression",
            ),
            "legacyLicense": _metadata_value(headers, "License"),
            "classifiers": _metadata_values(headers, "Classifier"),
            "licenseClassifiers": [
                value
                for value in _metadata_values(headers, "Classifier")
                if value.startswith("License ::")
            ],
            "homePage": _metadata_value(headers, "Home-page"),
            "resolvedHomepage": _resolved_homepage(headers, project_urls),
            "projectUrls": project_urls,
            "metadata": {
                "metadataVersion": _metadata_value(
                    headers,
                    "Metadata-Version",
                ),
                "summary": _metadata_value(headers, "Summary"),
                "requiresPython": _metadata_value(
                    headers,
                    "Requires-Python",
                ),
                "author": _metadata_value(headers, "Author"),
                "authorEmail": _metadata_value(headers, "Author-email"),
                "maintainer": _metadata_value(headers, "Maintainer"),
                "maintainerEmail": _metadata_value(
                    headers,
                    "Maintainer-email",
                ),
                "headers": headers,
                "rawSource": {
                    "present": raw_metadata is not None,
                    "byteLength": len(raw_bytes),
                    "sha256": _sha256_bytes(raw_bytes),
                },
            },
            "installation": {
                "distInfoName": (
                    Path(str(distribution_path)).name
                    if distribution_path is not None
                    else None
                ),
                "installer": installer.strip() if installer else None,
                "directUrl": (
                    json.loads(direct_url)
                    if direct_url and direct_url.strip()
                    else None
                ),
                "directUrlSource": (
                    {
                        "byteLength": len(direct_url.encode("utf-8")),
                        "sha256": _sha256_bytes(
                            direct_url.encode("utf-8")
                        ),
                    }
                    if direct_url is not None
                    else None
                ),
            },
        }


class MappingDistributionProvider:
    """Deterministic provider used by focused tests and offline fixtures."""

    def __init__(self, snapshots: Mapping[str, Mapping[str, Any]]) -> None:
        self._snapshots = {
            canonicalize_name(name): dict(snapshot)
            for name, snapshot in snapshots.items()
        }

    def resolve(self, name: str) -> Mapping[str, Any] | None:
        snapshot = self._snapshots.get(canonicalize_name(name))
        return dict(snapshot) if snapshot is not None else None


def _logical_requirement_lines(text: str) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    parts: list[str] = []
    start_line = 0
    for line_number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not parts:
            start_line = line_number
        continuation = stripped.endswith("\\")
        piece = stripped[:-1].rstrip() if continuation else stripped
        parts.append(piece)
        if continuation:
            continue
        combined = " ".join(item for item in parts if item).strip()
        if combined:
            result.append((start_line, combined))
        parts = []
    if parts:
        result.append((start_line, " ".join(parts).strip()))
    return result


def _strip_inline_comment(line: str) -> str:
    return re.sub(r"\s+#.*$", "", line).strip()


def _is_hash_bound_url(url: str | None) -> bool:
    if not url:
        return False
    fragment = urlsplit(url).fragment
    return bool(
        re.search(
            r"(?:^|[&;])(?:sha256|hash)=?[0-9a-f]{32,}",
            fragment,
            re.IGNORECASE,
        )
    )


def _is_exact_pin(requirement: Requirement) -> bool:
    if requirement.url:
        return _is_hash_bound_url(requirement.url)
    specifiers = list(requirement.specifier)
    return (
        len(specifiers) == 1
        and specifiers[0].operator in {"==", "==="}
        and "*" not in specifiers[0].version
    )


def parse_direct_requirements(text: str) -> dict[str, Any]:
    """Parse direct PEP 508 requirements and retain fail-closed findings."""

    requirements = []
    findings = []
    seen: dict[str, int] = {}
    for line_number, logical_line in _logical_requirement_lines(text):
        if logical_line.startswith("#"):
            continue
        clean = _strip_inline_comment(logical_line)
        if not clean:
            continue
        if clean.startswith(("-", "--")):
            findings.append(
                {
                    "code": "unsupported_requirements_directive",
                    "lineNumber": line_number,
                    "message": (
                        "Requirements directives and includes are not "
                        "resolved by this direct-dependency inventory."
                    ),
                    "raw": logical_line,
                }
            )
            continue
        try:
            requirement = Requirement(clean)
        except InvalidRequirement as exc:
            findings.append(
                {
                    "code": "invalid_direct_requirement",
                    "lineNumber": line_number,
                    "message": str(exc),
                    "raw": logical_line,
                }
            )
            continue

        canonical_name = canonicalize_name(requirement.name)
        marker_applies = True
        if requirement.marker is not None:
            try:
                marker_applies = requirement.marker.evaluate()
            except Exception as exc:
                marker_applies = False
                findings.append(
                    {
                        "code": "requirement_marker_evaluation_failed",
                        "lineNumber": line_number,
                        "dependency": canonical_name,
                        "message": str(exc),
                    }
                )
        if canonical_name in seen:
            findings.append(
                {
                    "code": "duplicate_direct_requirement",
                    "lineNumber": line_number,
                    "dependency": canonical_name,
                    "message": (
                        "The dependency is declared more than once; a single "
                        "authoritative declaration is required."
                    ),
                    "firstLineNumber": seen[canonical_name],
                }
            )
        else:
            seen[canonical_name] = line_number

        requirements.append(
            {
                "lineNumber": line_number,
                "raw": logical_line,
                "parsed": str(requirement),
                "name": requirement.name,
                "canonicalName": canonical_name,
                "extras": sorted(requirement.extras),
                "specifier": str(requirement.specifier),
                "marker": (
                    str(requirement.marker)
                    if requirement.marker is not None
                    else None
                ),
                "url": requirement.url,
                "appliesToCurrentEnvironment": marker_applies,
                "exactlyPinned": _is_exact_pin(requirement),
                "_requirement": requirement,
            }
        )
    return {"requirements": requirements, "findings": findings}


def _license_text(snapshot: Mapping[str, Any]) -> str:
    values = [
        snapshot.get("licenseExpression"),
        snapshot.get("legacyLicense"),
        *snapshot.get("licenseClassifiers", []),
    ]
    return "\n".join(str(value) for value in values if value)


def _matched_terms(
    text: str,
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
) -> list[str]:
    return sorted(name for name, pattern in patterns if pattern.search(text))


def _license_unknown(snapshot: Mapping[str, Any]) -> bool:
    values = [
        str(snapshot.get("licenseExpression") or "").strip(),
        str(snapshot.get("legacyLicense") or "").strip(),
        *[
            str(value).strip()
            for value in snapshot.get("licenseClassifiers", [])
        ],
    ]
    meaningful = [
        value
        for value in values
        if value.casefold() not in _UNKNOWN_LICENSE_VALUES
    ]
    return not meaningful


def _blocker(
    code: str,
    message: str,
    *,
    dependency: str | None = None,
    line_number: int | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {"code": code, "message": message}
    if dependency is not None:
        value["dependency"] = dependency
    if line_number is not None:
        value["lineNumber"] = line_number
    return value


def _normalize_snapshot(
    snapshot: Mapping[str, Any],
    requested_name: str,
) -> dict[str, Any]:
    value = json.loads(json.dumps(snapshot, ensure_ascii=True))
    value.setdefault("name", requested_name)
    value.setdefault("version", "")
    value.setdefault("licenseExpression", None)
    value.setdefault("legacyLicense", None)
    value.setdefault("classifiers", [])
    value.setdefault("licenseClassifiers", [])
    value.setdefault("homePage", None)
    value.setdefault("resolvedHomepage", value.get("homePage"))
    value.setdefault("projectUrls", [])
    value.setdefault("metadata", {})
    value.setdefault("installation", {})
    return value


def _dependency_inventory(
    parsed: Mapping[str, Any],
    provider: DistributionProvider,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    dependencies = []
    blockers = []
    for source in parsed["requirements"]:
        requirement: Requirement = source["_requirement"]
        public_source = {
            key: value
            for key, value in source.items()
            if key != "_requirement"
        }
        dependency_blockers = []

        if not source["exactlyPinned"]:
            dependency_blockers.append(
                _blocker(
                    "direct_requirement_unpinned",
                    (
                        "The direct requirement is not bound to one exact "
                        "version or a hash-bound direct URL."
                    ),
                    dependency=source["canonicalName"],
                    line_number=source["lineNumber"],
                )
            )

        snapshot = None
        installed_satisfies = None
        if source["appliesToCurrentEnvironment"]:
            observed = provider.resolve(requirement.name)
            if observed is None:
                dependency_blockers.append(
                    _blocker(
                        "direct_requirement_missing",
                        "The active direct requirement is not installed.",
                        dependency=source["canonicalName"],
                        line_number=source["lineNumber"],
                    )
                )
            else:
                snapshot = _normalize_snapshot(observed, requirement.name)
                version = str(snapshot.get("version") or "")
                installed_satisfies = (
                    requirement.specifier.contains(
                        version,
                        prereleases=True,
                    )
                    if requirement.specifier
                    else True
                )
                if not version:
                    dependency_blockers.append(
                        _blocker(
                            "installed_version_unknown",
                            "Installed distribution metadata has no version.",
                            dependency=source["canonicalName"],
                            line_number=source["lineNumber"],
                        )
                    )
                elif not installed_satisfies:
                    dependency_blockers.append(
                        _blocker(
                            "installed_version_outside_declared_specifier",
                            (
                                f"Installed version {version} does not satisfy "
                                f"{source['specifier']}."
                            ),
                            dependency=source["canonicalName"],
                            line_number=source["lineNumber"],
                        )
                    )

                if _license_unknown(snapshot):
                    dependency_blockers.append(
                        _blocker(
                            "license_metadata_unknown",
                            (
                                "No usable license expression, legacy license "
                                "value, or license classifier was observed."
                            ),
                            dependency=source["canonicalName"],
                            line_number=source["lineNumber"],
                        )
                    )

                license_text = _license_text(snapshot)
                strong_terms = _matched_terms(
                    license_text,
                    _STRONG_COPYLEFT_PATTERNS,
                )
                commercial_terms = _matched_terms(
                    license_text,
                    _COMMERCIAL_REVIEW_PATTERNS,
                )
                if strong_terms:
                    dependency_blockers.append(
                        _blocker(
                            "strong_copyleft_review_required",
                            (
                                "Installed metadata contains strong-copyleft "
                                f"terms: {', '.join(strong_terms)}."
                            ),
                            dependency=source["canonicalName"],
                            line_number=source["lineNumber"],
                        )
                    )
                if commercial_terms:
                    dependency_blockers.append(
                        _blocker(
                            "commercial_or_dual_license_review_required",
                            (
                                "Installed metadata contains commercial or "
                                f"dual-license terms: {', '.join(commercial_terms)}."
                            ),
                            dependency=source["canonicalName"],
                            line_number=source["lineNumber"],
                        )
                    )
                if source["canonicalName"] == "pymupdf":
                    dependency_blockers.append(
                        _blocker(
                            "pymupdf_dual_agpl_commercial_review_required",
                            (
                                "PyMuPDF distribution requires explicit human "
                                "review of its AGPL/commercial licensing path."
                            ),
                            dependency=source["canonicalName"],
                            line_number=source["lineNumber"],
                        )
                    )

                snapshot["licenseAssessment"] = {
                    "metadataPresent": not _license_unknown(snapshot),
                    "strongCopyleftTermsDetected": strong_terms,
                    "commercialOrDualTermsDetected": commercial_terms,
                    "humanLegalReviewRequired": True,
                    "legalConclusion": None,
                }

        blockers.extend(dependency_blockers)
        dependencies.append(
            {
                "directRequirement": public_source,
                "resolutionStatus": (
                    "inactive_marker"
                    if not source["appliesToCurrentEnvironment"]
                    else ("installed" if snapshot is not None else "missing")
                ),
                "installedVersionSatisfiesSpecifier": installed_satisfies,
                "installedDistribution": snapshot,
                "machineReview": {
                    "status": (
                        "blocked"
                        if dependency_blockers
                        else "metadata_recorded"
                    ),
                    "blockerCodes": sorted(
                        {item["code"] for item in dependency_blockers}
                    ),
                },
            }
        )
    return dependencies, blockers


def _deduplicate_blockers(
    blockers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    unique = {}
    for item in blockers:
        key = _canonical_json_bytes(item)
        unique[key] = item
    return sorted(
        unique.values(),
        key=lambda item: (
            item["code"],
            item.get("dependency", ""),
            item.get("lineNumber", 0),
            item["message"],
        ),
    )


def build_inventory(
    requirements_path: Path,
    *,
    provider: DistributionProvider | None = None,
    generator_source: Path | None = None,
    generated_at_utc: str | None = None,
    environment: Mapping[str, Any] | None = None,
    root: Path | None = ROOT,
) -> dict[str, Any]:
    """Build a source-bound direct-dependency machine inventory."""

    provider = provider or ImportlibDistributionProvider()
    generator_source = generator_source or Path(__file__)
    requirements_text = requirements_path.read_text(encoding="utf-8")
    parsed = parse_direct_requirements(requirements_text)
    dependencies, dependency_blockers = _dependency_inventory(
        parsed,
        provider,
    )
    parse_blockers = [
        _blocker(
            item["code"],
            item["message"],
            dependency=item.get("dependency"),
            line_number=item.get("lineNumber"),
        )
        for item in parsed["findings"]
    ]
    blockers = _deduplicate_blockers(
        [*parse_blockers, *dependency_blockers]
    )
    source_binding = {
        "algorithm": "sha256",
        "requirements": _file_artifact(requirements_path, root=root),
        "generator": _file_artifact(generator_source, root=root),
    }
    source_binding["combinedSha256"] = _sha256_bytes(
        _canonical_json_bytes(source_binding)
    )
    machine_gate_met = not blockers

    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAtUtc": generated_at_utc or _utc_now(),
        "inventoryScope": {
            "kind": "installed_machine_direct_requirements",
            "directRequirementsOnly": True,
            "transitiveClosureInventoried": False,
            "packagedArtifactInventoried": False,
            "statement": (
                "This inventory resolves active direct declarations from "
                "requirements.txt against one installed Python environment. "
                "It is not a lock file or a packaged-wheel inventory."
            ),
        },
        "environment": dict(
            environment
            or {
                "pythonImplementation": platform.python_implementation(),
                "pythonVersion": platform.python_version(),
                "operatingSystem": platform.system(),
                "operatingSystemRelease": platform.release(),
                "machineArchitecture": platform.machine(),
            }
        ),
        "sourceBinding": source_binding,
        "requirementParseFindings": parsed["findings"],
        "directRequirementCount": len(dependencies),
        "dependencies": dependencies,
        "machineAssessment": {
            "status": "complete" if machine_gate_met else "blocked",
            "gateMet": machine_gate_met,
            "blockerCount": len(blockers),
            "blockerCodes": sorted({item["code"] for item in blockers}),
            "blockers": blockers,
            "policy": {
                "missingDependency": "block",
                "unversionedOrRangeRequirement": "block",
                "unknownLicenseMetadata": "block",
                "strongCopyleftTerm": "block_for_human_review",
                "commercialOrDualLicenseTerm": "block_for_human_review",
                "pymupdf": "always_block_for_human_review",
            },
        },
        "humanLegalApproval": {
            "status": "not_performed",
            "required": True,
            "approved": False,
            "legalClearanceClaimed": False,
            "statement": (
                "Machine-observed metadata is evidence for review, not legal "
                "advice or approval. A qualified human must determine license "
                "obligations for the exact distributed artifact."
            ),
        },
        "releaseGateMet": False,
    }


def _single_line(value: Any, limit: int = 160) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _license_display(distribution: Mapping[str, Any] | None) -> str:
    if distribution is None:
        return "MISSING"
    value = (
        distribution.get("licenseExpression")
        or distribution.get("legacyLicense")
        or "; ".join(distribution.get("licenseClassifiers", []))
        or "UNKNOWN"
    )
    return _single_line(value).replace("|", "\\|")


def render_notice_draft(inventory: Mapping[str, Any]) -> str:
    """Render a review draft without asserting notice completeness."""

    machine = inventory["machineAssessment"]
    lines = [
        "# Facility Layout Pilot Python Third-Party Notice Draft",
        "",
        "> **DRAFT - MACHINE GENERATED - NOT LEGAL CLEARANCE**",
        ">",
        "> This document records installed metadata for direct Python",
        "> requirements. It does not determine obligations, approve",
        "> redistribution, or replace review of the exact packaged artifact.",
        "",
        "## Inventory Binding",
        "",
        f"- Generated: `{inventory['generatedAtUtc']}`",
        (
            "- Requirements SHA-256: "
            f"`{inventory['sourceBinding']['requirements']['sha256']}`"
        ),
        (
            "- Inventory tool SHA-256: "
            f"`{inventory['sourceBinding']['generator']['sha256']}`"
        ),
        (
            "- Machine assessment: "
            f"**{str(machine['status']).upper()}** "
            f"({machine['blockerCount']} blockers)"
        ),
        "- Human legal approval: **NOT PERFORMED**",
        "- Release clearance claimed: **NO**",
        "",
        "## Direct Requirements",
        "",
        "| Requirement | Installed distribution | Version | Metadata license declaration | Review |",
        "| --- | --- | --- | --- | --- |",
    ]
    for dependency in inventory["dependencies"]:
        requirement = dependency["directRequirement"]
        distribution = dependency["installedDistribution"]
        name = (
            distribution.get("name")
            if distribution is not None
            else "MISSING"
        )
        version = (
            distribution.get("version")
            if distribution is not None
            else "MISSING"
        )
        review = dependency["machineReview"]["status"]
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{requirement['parsed']}`",
                    str(name).replace("|", "\\|"),
                    f"`{version}`",
                    _license_display(distribution),
                    review,
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Machine Blockers",
            "",
        ]
    )
    if machine["blockers"]:
        for item in machine["blockers"]:
            dependency = (
                f" (`{item['dependency']}`)"
                if item.get("dependency")
                else ""
            )
            lines.append(
                f"- `{item['code']}`{dependency}: {item['message']}"
            )
    else:
        lines.append("- No machine blockers were detected.")

    lines.extend(
        [
            "",
            "## Human Review Required",
            "",
            "Before distributing a pilot build, a qualified reviewer must:",
            "",
            "1. Inventory the exact packaged artifacts and transitive dependencies.",
            "2. Confirm the governing license path for every distribution.",
            "3. Review required attribution, notice, source-offer, and disclosure terms.",
            "4. Resolve every machine blocker, including the PyMuPDF licensing path.",
            "5. Approve the final notice text and retain that approval separately.",
            "",
            "This draft intentionally contains no statement that the Facility Layout",
            "pilot, its Python dependencies, or this notice has legal clearance.",
            "",
        ]
    )
    return "\n".join(lines)


def write_inventory_outputs(
    inventory: Mapping[str, Any],
    inventory_path: Path,
    notice_path: Path,
) -> None:
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    notice_path.parent.mkdir(parents=True, exist_ok=True)
    inventory_path.write_text(
        json.dumps(
            inventory,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="ascii",
        newline="\n",
    )
    notice_path.write_text(
        render_notice_draft(inventory),
        encoding="ascii",
        newline="\n",
    )


def exit_code_for_inventory(inventory: Mapping[str, Any]) -> int:
    """Fail closed when the installed-machine assessment is blocked."""

    return 0 if inventory["machineAssessment"]["gateMet"] else 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inventory installed direct Python dependencies for the "
            "Facility Layout pilot."
        )
    )
    parser.add_argument(
        "--requirements",
        type=Path,
        default=DEFAULT_REQUIREMENTS,
    )
    parser.add_argument(
        "--inventory-output",
        type=Path,
        default=DEFAULT_INVENTORY,
    )
    parser.add_argument(
        "--notice-output",
        type=Path,
        default=DEFAULT_NOTICE,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    inventory = build_inventory(args.requirements)
    write_inventory_outputs(
        inventory,
        args.inventory_output,
        args.notice_output,
    )
    status = inventory["machineAssessment"]["status"].upper()
    blockers = inventory["machineAssessment"]["blockerCount"]
    print(
        f"{status}: wrote {args.inventory_output} and "
        f"{args.notice_output} ({blockers} machine blockers)."
    )
    print("Human legal approval remains required; no clearance is claimed.")
    return exit_code_for_inventory(inventory)


if __name__ == "__main__":
    raise SystemExit(main())
