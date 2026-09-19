#!/usr/bin/env python3
"""Build the frozen Sage Memory P1.0 workflow-state migration ledger."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tests" / "fixtures" / "memory" / "workflow-state-v1-migration-inventory.json"
SEARCH_CONTRACT_VERSION = 1
SEARCH_SYMBOLS = ("asset_fingerprint", "advance_workflow_state")
SOURCE_PATHS = (
    "ai_inspector/agent_skills/__init__.py",
    "ai_inspector/agent_skills/schemas/workflow-state.schema.json",
    "ai_inspector/agent_skills/workflow_state.py",
    "ai_inspector/facility_layout/spatial.py",
    "server.py",
    "tests/test_agent_workflow_state.py",
    "tests/test_facility_layout_agent_integration.py",
    "tests/test_process_map_analysis.py",
)
OCCURRENCE_KINDS = {
    "producer",
    "consumer",
    "serializer",
    "schema",
    "api_projection",
    "test",
}
MIGRATION_DISPOSITIONS = {
    "migrated",
    "pending",
    "removed",
    "retained_v1_reader",
}


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def _git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _classify(path: str, line: str, symbol: str) -> str:
    stripped = line.strip()
    if path.startswith("tests/"):
        return "test"
    if path.endswith(".schema.json"):
        return "schema"
    if path.endswith("/__init__.py"):
        return "api_projection"
    if re.search(rf"['\"]{re.escape(symbol)}['\"]\s*:", line):
        return "serializer" if path != "server.py" else "api_projection"
    if stripped.startswith("def ") and symbol in stripped:
        return "producer"
    if re.search(rf"\b(?:base_)?{re.escape(symbol)}\s*=", line):
        return "producer"
    return "consumer"


def _fixture_for(kind: str) -> str:
    return {
        "producer": "workflow-state-v2-transition",
        "consumer": "workflow-state-v2-transition",
        "serializer": "workflow-state-v2-roundtrip",
        "schema": "workflow-state-v2-contract",
        "api_projection": "workflow-state-v2-projection",
        "test": "workflow-state-v1-migration",
    }[kind]


def build_inventory(*, baseline_commit: str | None = None) -> dict[str, Any]:
    source_files: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    symbol_counts = {symbol: 0 for symbol in SEARCH_SYMBOLS}

    for relative_path in SOURCE_PATHS:
        path = ROOT / relative_path
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
        file_symbol_counts = {symbol: 0 for symbol in SEARCH_SYMBOLS}
        source_files.append(
            {
                "path": relative_path,
                "sha256": _sha256(raw),
                "bytes": len(raw),
            }
        )
        lines = text.splitlines()
        for line_number, line in enumerate(lines, start=1):
            for symbol in SEARCH_SYMBOLS:
                for match_index, match in enumerate(re.finditer(re.escape(symbol), line), start=1):
                    symbol_counts[symbol] += 1
                    file_symbol_counts[symbol] += 1
                    kind = _classify(relative_path, line, symbol)
                    if kind not in OCCURRENCE_KINDS:
                        raise AssertionError(f"unclassified occurrence: {relative_path}:{line_number}")
                    snippet = "\n".join(
                        lines[max(0, line_number - 2) : min(len(lines), line_number + 1)]
                    )
                    snippet_sha = _sha256(snippet.encode("utf-8"))
                    occurrence_id = (
                        f"{relative_path}::{symbol}::{kind}::"
                        f"{snippet_sha[:16]}::{file_symbol_counts[symbol]}"
                    )
                    entries.append(
                        {
                            "occurrenceId": occurrence_id,
                            "path": relative_path,
                            "symbol": symbol,
                            "baselineLine": line_number,
                            "lineOccurrence": match_index,
                            "sourceOrdinal": file_symbol_counts[symbol],
                            "sourceSnippetSha256": snippet_sha,
                            "occurrenceKind": kind,
                            "currentContract": (
                                "asset_fingerprint_v1"
                                if symbol == "asset_fingerprint"
                                else "advance_workflow_state_v1"
                            ),
                            "targetContract": (
                                "scope_and_revision_v2"
                                if symbol == "asset_fingerprint"
                                else "advance_workflow_state_v2"
                            ),
                            "migrationDisposition": "pending",
                            "verificationFixture": _fixture_for(kind),
                        }
                    )

    entries.sort(
        key=lambda item: (
            item["path"],
            item["baselineLine"],
            item["symbol"],
            item["lineOccurrence"],
        )
    )
    source_files.sort(key=lambda item: item["path"])
    source_manifest_sha = _sha256(_canonical_bytes(source_files))
    result = {
        "schemaVersion": "sage-workflow-state-v1-migration-inventory-1.0",
        "baselineCommit": baseline_commit or _git_head(),
        "baselineSourceManifestSha256": source_manifest_sha,
        "searchContractVersion": SEARCH_CONTRACT_VERSION,
        "search": {
            "matching": "case-sensitive non-overlapping substring occurrences",
            "symbols": list(SEARCH_SYMBOLS),
            "paths": list(SOURCE_PATHS),
        },
        "allowedOccurrenceKinds": sorted(OCCURRENCE_KINDS),
        "allowedMigrationDispositions": [
            "migrated",
            "pending",
            "removed",
            "retained_v1_reader",
        ],
        "counts": {
            "entries": len(entries),
            "files": len(source_files),
            "bySymbol": symbol_counts,
        },
        "sourceFiles": source_files,
        "entries": entries,
    }
    return result


def validate_inventory(
    inventory: dict[str, Any], *, require_closed: bool = False
) -> None:
    entries = inventory.get("entries")
    source_files = inventory.get("sourceFiles")
    counts = inventory.get("counts")
    if not isinstance(entries, list) or not isinstance(source_files, list):
        raise AssertionError("migration inventory rows are missing")
    if not isinstance(counts, dict):
        raise AssertionError("migration inventory counts are missing")
    if len({row.get("occurrenceId") for row in entries}) != len(entries):
        raise AssertionError("migration occurrence IDs must be unique")
    dispositions = {row.get("migrationDisposition") for row in entries}
    if not dispositions <= MIGRATION_DISPOSITIONS:
        raise AssertionError("migration inventory contains an invalid disposition")
    if require_closed and "pending" in dispositions:
        raise AssertionError("migration inventory still contains pending entries")
    if counts.get("entries") != len(entries) or counts.get("files") != len(source_files):
        raise AssertionError("migration inventory counts do not match its rows")
    symbol_counts = {
        symbol: sum(1 for row in entries if row.get("symbol") == symbol)
        for symbol in SEARCH_SYMBOLS
    }
    if counts.get("bySymbol") != symbol_counts:
        raise AssertionError("migration inventory symbol counts do not match its rows")
    if inventory.get("baselineSourceManifestSha256") != _sha256(
        _canonical_bytes(source_files)
    ):
        raise AssertionError("baseline source manifest hash is invalid")
    for row in entries:
        if row.get("occurrenceKind") not in OCCURRENCE_KINDS:
            raise AssertionError("migration occurrence kind is invalid")
        if not row.get("sourceSnippetSha256") or not row.get("verificationFixture"):
            raise AssertionError("migration occurrence lacks verification metadata")


def close_inventory_for_p12(inventory: dict[str, Any]) -> dict[str, Any]:
    """Close the frozen P1.0 ledger without rescanning changed source files."""

    result = copy.deepcopy(inventory)
    validate_inventory(result)
    for row in result["entries"]:
        path = row["path"]
        if (
            path == "ai_inspector/agent_skills/workflow_state.py"
            and row["symbol"] == "asset_fingerprint"
            and int(row["baselineLine"]) <= 292
        ):
            disposition = "retained_v1_reader"
        elif path in {
            "ai_inspector/agent_skills/schemas/workflow-state.schema.json",
            "ai_inspector/facility_layout/spatial.py",
        }:
            disposition = "removed"
        else:
            disposition = "migrated"
        row["migrationDisposition"] = disposition
    validate_inventory(result, require_closed=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help=f"write {OUTPUT.relative_to(ROOT)}")
    parser.add_argument("--check", action="store_true", help="compare generated data with the fixture")
    parser.add_argument(
        "--close-p12",
        action="store_true",
        help="close every frozen occurrence with its Phase 1.2 disposition",
    )
    args = parser.parse_args()
    existing = None
    if OUTPUT.is_file():
        existing = json.loads(OUTPUT.read_text(encoding="ascii"))
    pinned_commit = (
        str(existing.get("baselineCommit") or "")
        if args.check and isinstance(existing, dict)
        else None
    )
    if args.close_p12:
        if not isinstance(existing, dict):
            raise SystemExit("Sage Memory P1.0 migration inventory is missing")
        inventory = close_inventory_for_p12(existing)
    elif args.check and isinstance(existing, dict) and not any(
        row.get("migrationDisposition") == "pending"
        for row in existing.get("entries", [])
    ):
        validate_inventory(existing, require_closed=True)
        inventory = existing
    else:
        inventory = build_inventory(baseline_commit=pinned_commit or None)
    rendered = json.dumps(inventory, ensure_ascii=True, indent=2) + "\n"

    if args.write:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(rendered, encoding="ascii", newline="\n")
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="ascii") != rendered:
            raise SystemExit("Sage Memory P1.0 migration inventory is stale")
    if not args.write and not args.check:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
