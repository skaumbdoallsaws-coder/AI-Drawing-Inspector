"""Audit inspection profiles against the CAD feature icon registry.

This is intended to run during part-library injection. It keeps runtime UI
deterministic while still surfacing new semantic feature meanings or
SolidWorks operations that need icon coverage.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "static" / "cad_feature_icon_registry.json"
DEFAULT_OUTPUT_DIR = ROOT / "generated" / "cad_feature_icon_candidates"
DEFAULT_PROFILE_ROOTS = [
    ROOT / "400S_Sorted_Library",
    ROOT / "generated" / "engine_motion" / "claude_profile_packet" / "draft_profiles",
]


def normalize(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def slug(value: Any, fallback: str = "candidate") -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    return text or fallback


def contains_alias(normalized_text: str, alias: Any) -> bool:
    alias_text = normalize(alias)
    if not alias_text:
        return False
    return re.search(rf"(^| ){re.escape(alias_text)}(?= |$|[0-9])", normalized_text) is not None


def load_json(path: Path) -> Any | None:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def load_registry(path: Path) -> dict[str, Any]:
    registry = load_json(path)
    if not isinstance(registry, dict):
        raise SystemExit(f"Invalid registry: {path}")
    registry.setdefault("fallbackIcon", "ip-cad-icon-feature-group")
    registry.setdefault("semantic", [])
    registry.setdefault("operations", [])
    return registry


def match_registry(text: str, entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    normalized = normalize(text)
    if not normalized:
        return None
    for entry in entries:
        aliases = entry.get("aliases") or []
        if any(contains_alias(normalized, alias) for alias in aliases):
            return entry
    return None


def iter_profile_paths(profile_roots: list[Path]) -> list[Path]:
    paths: list[Path] = []
    for root in profile_roots:
        if root.is_file() and root.suffix.lower() == ".json":
            paths.append(root)
        elif root.is_dir():
            paths.extend(p for p in root.rglob("*.json") if p.is_file())
    return sorted(set(paths))


def looks_like_profile(data: Any) -> bool:
    return isinstance(data, dict) and isinstance(data.get("features"), list) and bool(data.get("part_number"))


def operation_name(operation: Any) -> str:
    if isinstance(operation, str):
        return operation
    if isinstance(operation, dict):
        return (
            operation.get("sw_name")
            or operation.get("name")
            or operation.get("operation")
            or operation.get("cad_feature_id")
            or "SolidWorks operation"
        )
    return "SolidWorks operation"


def operation_role(operation: Any) -> str:
    if isinstance(operation, dict):
        return operation.get("role") or operation.get("description") or operation.get("type") or ""
    return ""


def suggest_icon(text: str, kind: str, registry: dict[str, Any]) -> tuple[str, str]:
    normalized = normalize(text)
    rules = [
        ("ip-cad-icon-ring-grooves", "groove", ["ring", "groove"]),
        ("ip-cad-icon-counterbore", "hole", ["counterbore", "counter bore", "spotface", "countersink", "tap"]),
        ("ip-cad-icon-pin-bore", "hole", ["bore", "hole", "journal", "bearing"]),
        ("ip-cad-icon-dome", "surface", ["dome", "crown", "surface", "spherical"]),
        ("ip-cad-icon-cut", "cut", ["slot", "relief", "pocket", "cut", "shell", "keyway", "clearance"]),
        ("ip-cad-icon-boss", "boss", ["boss", "pad", "rib", "flange", "mount"]),
        ("ip-cad-icon-mirror", "mirror", ["mirror"]),
        ("ip-cad-icon-revolve", "revolve", ["revolve", "revolution"]),
        ("ip-cad-icon-plane", "ref", ["datum", "plane", "axis", "reference"]),
        ("ip-cad-icon-sketch", "sketch", ["sketch", "profile"]),
        ("ip-cad-icon-concentric", "mate", ["mate", "concentric", "coincident"]),
    ]
    for icon, meta, words in rules:
        if any(contains_alias(normalized, word) for word in words):
            return icon, meta
    return registry.get("fallbackIcon", "ip-cad-icon-feature-group"), ("semantic" if kind == "semantic" else "op")


def source_ref(path: Path, profile: dict[str, Any], feature: dict[str, Any], operation: Any | None = None) -> dict[str, Any]:
    ref = {
        "part_number": profile.get("part_number"),
        "part_name": profile.get("part_name"),
        "profile_path": str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path),
        "feature_name": feature.get("name"),
        "feature_type": feature.get("type"),
    }
    if operation is not None:
        ref["operation_name"] = operation_name(operation)
    return ref


def add_candidate(
    candidates: dict[tuple[str, str], dict[str, Any]],
    *,
    kind: str,
    label: str,
    text: str,
    source: dict[str, Any],
    registry: dict[str, Any],
) -> None:
    key = (kind, normalize(label or text))
    icon, meta = suggest_icon(text, kind, registry)
    candidate = candidates.get(key)
    if not candidate:
        aliases = [label] if label else []
        candidate = {
            "candidate_id": f"{kind}_{slug(label or text)}",
            "kind": kind,
            "label": label or text,
            "normalized_text": normalize(text),
            "suggested_icon": icon,
            "suggested_meta": meta if kind == "operation" else None,
            "suggested_aliases": sorted(set(a for a in aliases if a)),
            "review_status": "needs_review",
            "needs_new_svg": icon == registry.get("fallbackIcon", "ip-cad-icon-feature-group"),
            "recommended_registry_entry": {
                "icon": icon,
                **({"meta": meta} if kind == "operation" else {}),
                "aliases": sorted(set(a for a in aliases if a)),
            },
            "sources": [],
        }
        candidates[key] = candidate
    candidate["sources"].append(source)


def audit_profiles(registry: dict[str, Any], profile_paths: list[Path]) -> dict[str, Any]:
    candidates: dict[tuple[str, str], dict[str, Any]] = {}
    covered_semantic = 0
    covered_operations = 0
    scanned_profiles = 0
    scanned_features = 0
    scanned_operations = 0
    skipped_files = 0
    coverage_by_icon: dict[str, int] = defaultdict(int)

    for path in profile_paths:
        data = load_json(path)
        if not looks_like_profile(data):
            skipped_files += 1
            continue
        scanned_profiles += 1
        features = data.get("features") or []
        for feature in features:
            if not isinstance(feature, dict):
                continue
            scanned_features += 1
            semantic_text = " ".join(
                str(feature.get(key) or "")
                for key in ("type", "name", "spatial_description", "inspection_reason")
            )
            semantic_match = match_registry(semantic_text, registry.get("semantic", []))
            if semantic_match:
                covered_semantic += 1
                coverage_by_icon[semantic_match.get("icon", "unknown")] += 1
            else:
                add_candidate(
                    candidates,
                    kind="semantic",
                    label=str(feature.get("name") or feature.get("type") or "Semantic feature"),
                    text=semantic_text,
                    source=source_ref(path, data, feature),
                    registry=registry,
                )

            for operation in feature.get("solidworks_operations") or []:
                scanned_operations += 1
                op_text = f"{operation_name(operation)} {operation_role(operation)}"
                op_match = match_registry(op_text, registry.get("operations", []))
                if op_match:
                    covered_operations += 1
                    coverage_by_icon[op_match.get("icon", "unknown")] += 1
                else:
                    add_candidate(
                        candidates,
                        kind="operation",
                        label=operation_name(operation),
                        text=op_text,
                        source=source_ref(path, data, feature, operation),
                        registry=registry,
                    )

    candidate_list = sorted(candidates.values(), key=lambda c: (c["kind"], c["label"]))
    return {
        "registry_path": str(DEFAULT_REGISTRY.relative_to(ROOT)),
        "summary": {
            "profiles_scanned": scanned_profiles,
            "json_files_skipped": skipped_files,
            "features_scanned": scanned_features,
            "operations_scanned": scanned_operations,
            "semantic_features_covered": covered_semantic,
            "operations_covered": covered_operations,
            "candidate_count": len(candidate_list),
            "semantic_candidate_count": sum(1 for c in candidate_list if c["kind"] == "semantic"),
            "operation_candidate_count": sum(1 for c in candidate_list if c["kind"] == "operation"),
        },
        "coverage_by_icon": dict(sorted(coverage_by_icon.items())),
        "candidates": candidate_list,
    }


def write_review_markdown(report: dict[str, Any], output_path: Path) -> None:
    lines = [
        "# CAD Feature Icon Candidate Review",
        "",
        "Generated by `tools/cad_feature_icon_audit.py`.",
        "",
        "## Summary",
        "",
    ]
    for key, value in report["summary"].items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Candidates", ""])
    if not report["candidates"]:
        lines.append("No missing icon mappings found.")
    for candidate in report["candidates"]:
        lines.extend([
            f"### {candidate['label']}",
            "",
            f"- Kind: `{candidate['kind']}`",
            f"- Suggested icon: `{candidate['suggested_icon']}`",
            f"- Needs new SVG: `{candidate['needs_new_svg']}`",
            f"- Suggested aliases: {', '.join(candidate['suggested_aliases']) or '(none)'}",
            f"- Sources: {len(candidate['sources'])}",
            "",
        ])
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit CAD feature icon coverage and create review candidates.")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--profile-root", type=Path, action="append", default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    registry = load_registry(args.registry)
    profile_roots = args.profile_root or DEFAULT_PROFILE_ROOTS
    profile_paths = iter_profile_paths(profile_roots)
    report = audit_profiles(registry, profile_paths)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "icon_candidates.json"
    md_path = args.out_dir / "README.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_review_markdown(report, md_path)

    summary = report["summary"]
    print(
        "CAD feature icon audit: "
        f"{summary['profiles_scanned']} profiles, "
        f"{summary['features_scanned']} features, "
        f"{summary['operations_scanned']} operations, "
        f"{summary['candidate_count']} candidates"
    )
    print(f"Wrote {json_path.relative_to(ROOT)}")
    print(f"Wrote {md_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
