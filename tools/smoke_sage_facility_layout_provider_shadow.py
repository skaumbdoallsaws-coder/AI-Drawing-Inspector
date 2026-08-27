"""Run one real-provider, read-only Facility intelligence shadow check.

The smoke intentionally targets child-cell metrics omitted from the bounded
default prompt digest. A passing run therefore proves the provider requested
an authoritative server read before presenting the answer. The saved layout
must remain byte- and revision-identical.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_inspector.facility_layout.host import (
    LOCAL_LAYOUT_ID,
    LOCAL_SITE_ID,
    LocalFacilityLayoutHost,
)


DEFAULT_LAYOUT = (
    REPO_ROOT
    / ".runtime"
    / "facility-layout"
    / "layouts"
    / "local"
    / "site-local"
    / "layouts"
    / "fl-main.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "runtime_logs"
    / "sage_facility_layout_provider_shadow.json"
)
TARGET_CELLS = ("Assembly Cell A01", "Assembly Cell A02")
SOURCE_PATHS = (
    "server.py",
    "ai_inspector/facility_layout/semantic_model.py",
    "ai_inspector/facility_layout/agent_runtime.py",
    "ai_inspector/facility_layout/chat_context.py",
    "ai_inspector/agent_skills/analyze-facility-layout/SKILL.md",
    "tools/smoke_sage_facility_layout_provider_shadow.py",
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _source_bindings() -> list[dict[str, Any]]:
    bindings = []
    for relative in SOURCE_PATHS:
        raw = (REPO_ROOT / relative).read_bytes()
        bindings.append({
            "path": relative,
            "sha256": _sha256(raw),
            "byteSize": len(raw),
        })
    return bindings


def _post_json(url: str, payload: Mapping[str, Any], timeout: float) -> dict:
    request = Request(
        url,
        data=_canonical_bytes(payload),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            raw = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail[:2000]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Provider-shadow request failed: {exc}") from exc
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("Provider-shadow response is not an object")
    return value


def _table(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for block in payload.get("content_blocks") or []:
        if not isinstance(block, Mapping) or block.get("type") != "table":
            continue
        table = block.get("table")
        if isinstance(table, Mapping):
            return table
    return None


def _table_rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    table = _table(payload)
    if table is None:
        return []
    return [
        row
        for row in table.get("rows") or []
        if isinstance(row, Mapping)
    ]


def _table_text(rows: list[Mapping[str, Any]]) -> str:
    return " ".join(
        str(cell)
        for row in rows
        for cell in row.get("cells") or []
    ).casefold()


def _table_contains_number(rendered: str, value: float) -> bool:
    return any(
        token in rendered
        for token in {
            f"{value:.6f}",
            f"{value:.5f}",
            f"{value:.4f}",
            f"{value:.3f}",
            f"{value:.2f}",
            f"{value:.1f}",
        }
    )


def _table_contains_expected_metrics(
    rows: list[Mapping[str, Any]],
    expectations: Mapping[str, Mapping[str, Any]],
) -> bool:
    rows_by_entity = {
        str(row.get("entityId") or row.get("entity_id") or ""): " ".join(
            str(cell) for cell in row.get("cells") or []
        ).casefold()
        for row in rows
    }
    for name, expected in expectations.items():
        rendered = rows_by_entity.get(str(expected.get("zoneId") or ""), "")
        if not rendered or name.casefold() not in rendered:
            return False
        if not _table_contains_number(
            rendered,
            float(expected["areaSquareMeters"]),
        ):
            return False
    return True


def _semantic_expectations(
    layout_root: Path,
    revision: str,
) -> dict[str, dict[str, Any]]:
    host = LocalFacilityLayoutHost(
        layout_root,
        private_assets=True,
        private_asset_root=REPO_ROOT,
    )
    try:
        current = host.service.get_layout(
            host.principal(),
            LOCAL_SITE_ID,
            LOCAL_LAYOUT_ID,
        )
        if str(current["revision"]) != revision:
            raise RuntimeError("Saved layout revision changed before oracle build")
        state = current["layout"]
        ids_by_label = {
            str(item.get("label") or ""): str(item.get("zoneId") or "")
            for item in state.get("zones") or []
            if isinstance(item, Mapping)
        }
        target_ids = [ids_by_label.get(name, "") for name in TARGET_CELLS]
        if not all(target_ids):
            raise RuntimeError("Provider-shadow target cells are unavailable")
        result = host.agent_runtime.execute_read_tool(
            host.principal(),
            site_id=LOCAL_SITE_ID,
            layout_id=LOCAL_LAYOUT_ID,
            expected_revision=revision,
            tool_name="inspect_facility_semantics",
            arguments={
                "view": "zones",
                "ids": target_ids,
                "pageSize": len(target_ids),
            },
            turn_id="provider-shadow-oracle",
            live_facts={},
        )
        expectations = {}
        for record in result.get("records") or []:
            if not isinstance(record, Mapping):
                continue
            physical = (
                (record.get("spatialMetrics") or {}).get(
                    "physicalFloorContact"
                )
                if isinstance(record.get("spatialMetrics"), Mapping)
                else {}
            )
            physical = physical if isinstance(physical, Mapping) else {}
            label = str(record.get("label") or "")
            if label not in TARGET_CELLS:
                continue
            expectations[label] = {
                "zoneId": str(record.get("zoneId") or ""),
                "areaSquareMeters": record.get("areaSquareMeters"),
                "areaEvidenceStatus": record.get("areaEvidenceStatus"),
                "footprintSquareMeters": physical.get(
                    "netUnionAreaSquareMeters"
                ),
                "footprintEvidenceStatus": physical.get(
                    "evidenceStatus"
                ),
                "layoutProvenance": record.get("layoutProvenance"),
            }
        if set(expectations) != set(TARGET_CELLS):
            raise RuntimeError("Semantic oracle did not return both cells")
        return expectations
    finally:
        host.close()


def _evidence_boundary_present(
    rows: list[Mapping[str, Any]],
    columns: list[Mapping[str, Any]],
    expectations: Mapping[str, Mapping[str, Any]],
) -> bool:
    labels = [str(item.get("label") or "").casefold() for item in columns]
    area_index = next((
        index
        for index, label in enumerate(labels)
        if "evidence" in label and "area" in label
    ), None)
    footprint_index = next((
        index
        for index, label in enumerate(labels)
        if any(token in label for token in ("evidence", "status", "class"))
        and any(token in label for token in ("physical", "footprint"))
    ), None)
    if area_index is None or footprint_index is None:
        return False
    rows_by_entity = {
        str(row.get("entityId") or row.get("entity_id") or ""): [
            str(cell).casefold() for cell in row.get("cells") or []
        ]
        for row in rows
    }
    for expected in expectations.values():
        cells = rows_by_entity.get(str(expected.get("zoneId") or ""), [])
        if max(area_index, footprint_index) >= len(cells):
            return False
        footprint_status = str(
            expected.get("footprintEvidenceStatus") or "unknown"
        ).casefold()
        if footprint_status not in cells[footprint_index]:
            return False
        area_status = str(
            expected.get("areaEvidenceStatus") or "unknown"
        ).casefold()
        if area_status not in cells[area_index]:
            return False
    return True


def _provenance_boundary_present(
    rows: list[Mapping[str, Any]],
    expectations: Mapping[str, Mapping[str, Any]],
) -> bool:
    rows_by_entity = {
        str(row.get("entityId") or row.get("entity_id") or ""): " ".join(
            str(cell) for cell in row.get("cells") or []
        ).casefold()
        for row in rows
    }
    for expected in expectations.values():
        rendered = rows_by_entity.get(str(expected.get("zoneId") or ""), "")
        provenance = expected.get("layoutProvenance")
        provenance = provenance if isinstance(provenance, Mapping) else {}
        command = str(provenance.get("command") or "").casefold()
        strategy = provenance.get("authoredStrategy")
        if command and command not in rendered:
            return False
        if strategy is None and not any(
            phrase in rendered
            for phrase in ("not persisted", "unknown", "not authored")
        ):
            return False
    return True


def run(
    *,
    base_url: str,
    layout_path: Path,
    output_path: Path,
    timeout: float,
) -> dict:
    before_raw = layout_path.read_bytes()
    before_stat = layout_path.stat()
    before_layout = json.loads(before_raw.decode("utf-8"))
    revision = str(before_layout.get("revision") or _sha256(before_raw))
    session_id = "sage-facility-provider-shadow-20260812"
    prompt = (
        "Compare Assembly Cell A01 and Assembly Cell A02 without changing "
        "the layout. Use the authoritative Facility semantic tool, not the "
        "default summary. Return a structured table with each cell's exact "
        "gross area in square meters, area evidence class, physical-footprint "
        "evidence status, and authored layout-strategy provenance. Do not "
        "substitute placement counts for area. Clearly state any metric that "
        "remains unknown."
    )
    response = _post_json(
        base_url.rstrip("/") + "/api/agent/chat",
        {
            "message": prompt,
            "history": [],
            "inspection_context": {
                "attachments": {
                    "facility_layout": {
                        "siteId": "site-local",
                        "layoutId": "fl-main",
                        "revision": revision,
                    },
                    "session": {"active_mode": "training"},
                }
            },
            "agent_type": "deviation-analyst",
            "session_id": session_id,
            "client_turn_id": session_id + "-turn-1",
        },
        timeout,
    )
    after_raw = layout_path.read_bytes()
    after_stat = layout_path.stat()
    after_layout = json.loads(after_raw.decode("utf-8"))
    expectations = _semantic_expectations(
        layout_path.parents[4],
        revision,
    )
    trace = response.get("facility_read_trace")
    calls = (
        trace.get("calls")
        if isinstance(trace, Mapping) and isinstance(trace.get("calls"), list)
        else []
    )
    provider_usage = (
        trace.get("providerUsage")
        if isinstance(trace, Mapping)
        and isinstance(trace.get("providerUsage"), Mapping)
        else {}
    )
    answer_provider_calls = int(provider_usage.get("calls") or 0)
    router_provider_calls = 1
    table = _table(response)
    rows = _table_rows(response)
    columns = [
        item
        for item in (table.get("columns") if table else []) or []
        if isinstance(item, Mapping)
    ]
    answer = str(response.get("response") or "")
    assertions = {
        "httpResponseReceived": bool(response),
        "authoritativeReadTracePresent": bool(calls),
        "semanticReadSucceeded": any(
            item.get("tool") == "inspect_facility_semantics"
            and item.get("status") == "succeeded"
            and item.get("revision") == revision
            for item in calls
            if isinstance(item, Mapping)
        ),
        "structuredTablePresent": bool(rows),
        "exactRequestedMetricsPresented": (
            _table_contains_expected_metrics(rows, expectations)
        ),
        "evidenceBoundaryPreserved": _evidence_boundary_present(
            rows,
            columns,
            expectations,
        ),
        "provenanceBoundaryPreserved": _provenance_boundary_present(
            rows,
            expectations,
        ),
        "noBrowserMutationToolReturned": not bool(response.get("tool_calls")),
        "layoutBytesUnchanged": before_raw == after_raw,
        "layoutTimestampUnchanged": (
            before_stat.st_mtime_ns == after_stat.st_mtime_ns
        ),
        "layoutRevisionUnchanged": (
            str(after_layout.get("revision") or _sha256(after_raw)) == revision
        ),
    }
    status = "passed" if all(assertions.values()) else "failed"
    artifact = {
        "schemaVersion": "sage-facility-provider-shadow-v1",
        "status": status,
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z"),
        "mode": "real_provider_read_only_shadow",
        "provider": str(os.getenv("INSPECTORPRO_SAGE_PROVIDER") or "anthropic"),
        "providerCalls": answer_provider_calls + router_provider_calls,
        "networkCalls": answer_provider_calls + router_provider_calls,
        "providerCallAccounting": {
            "router": router_provider_calls,
            "answer": answer_provider_calls,
            "applicationHttpRequests": 1,
        },
        "promptSha256": _sha256(prompt.encode("utf-8")),
        "layout": {
            "path": str(layout_path.resolve()),
            "revisionBefore": revision,
            "revisionAfter": str(after_layout.get("revision") or _sha256(after_raw)),
            "sha256Before": _sha256(before_raw),
            "sha256After": _sha256(after_raw),
            "byteSize": len(before_raw),
        },
        "assertions": assertions,
        "toolTrace": calls,
        "presentation": {
            "contentBlockTypes": [
                str(item.get("type") or "")
                for item in response.get("content_blocks") or []
                if isinstance(item, Mapping)
            ],
            "tableRowCount": len(rows),
            "tableColumns": [
                str(item.get("label") or "")[:120]
                for item in columns[:12]
            ],
            "tableRows": [
                {
                    "cells": [
                        str(cell)[:240]
                        for cell in list(row.get("cells") or [])[:12]
                    ],
                    "entityId": str(row.get("entityId") or "")[:160],
                }
                for row in rows[:10]
            ],
            "responseSha256": _sha256(answer.encode("utf-8")),
        },
        "expected": expectations,
        "sourceBindings": _source_bindings(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(
        json.dumps(artifact, indent=2, ensure_ascii=True).encode("ascii") + b"\n"
    )
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8124")
    parser.add_argument("--layout", type=Path, default=DEFAULT_LAYOUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()
    artifact = run(
        base_url=args.base_url,
        layout_path=args.layout,
        output_path=args.output,
        timeout=args.timeout,
    )
    print(
        "Sage Facility provider shadow: "
        f"{artifact['status']} - "
        f"{sum(artifact['assertions'].values())}/"
        f"{len(artifact['assertions'])} assertions"
    )
    print(f"Layout bytes unchanged: {artifact['assertions']['layoutBytesUnchanged']}")
    print(f"Evidence: {args.output.resolve()}")
    return 0 if artifact["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
