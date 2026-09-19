"""Bounded bridge to the existing browser-owned construction builders."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any, Mapping, Sequence

from .canonical import layout_revision
from .errors import FacilityValidationError

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "static/contracts/facility-construction-commands-v1.json"
MAX_COMPILER_BYTES = 8 * 1024 * 1024
MAX_COMPILER_SECONDS = 20
CONSTRUCTION_COMMANDS = ("cell-layout", "surface-stack", "create-cell-group", "linear-pattern")
CONSTRUCTION_TOOLS = {"preview_facility_" + name.replace("-", "_"): name for name in CONSTRUCTION_COMMANDS}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")


def construction_compiler_revision() -> str:
    digest = hashlib.sha256()
    for relative in ("static/contracts/facility-construction-commands-v1.json",
                     "static/facility_layout_patterns.js", "static/facility_layout_session.js",
                     "static/facility_layout_command_adapter.js", "tools/compile_facility_construction_command.js"):
        digest.update(relative.encode("ascii"))
        digest.update((ROOT / relative).read_bytes())
    return digest.hexdigest()


def construction_tool_specs() -> list[dict[str, Any]]:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    return [{"name": tool, "description": (
        f"Preview {command} using explicit IDs and existing catalog geometry. Returns a durable "
        "proposal and exact candidate revision; does not change the editor or save. Chain the "
        "returned proposalId as parentProposalId and candidateRevision as expectedDraftRevision. "
        "For the first command use an empty parentProposalId and the current layout revision. "
        "Reuse requestId and identical values for retries. Read the returned entity IDs before continuing. "
        "Cardinal north means direction=north (+Z), never vertical (-Z). "
        "Normal inspection tools read the saved editor, not this candidate; use the returned candidate receipt for subsequent commands."
    ), "input_schema": {"type": "object", "properties": {
        "requestId": {"type": "string", "minLength": 1, "maxLength": 100},
        "expectedDraftRevision": {"type": "string", "minLength": 64, "maxLength": 64},
        "parentProposalId": {"type": "string"},
        "arguments": deepcopy(contract["commands"][command]),
    }, "required": ["requestId", "expectedDraftRevision", "parentProposalId", "arguments"],
        "additionalProperties": False}} for tool, command in CONSTRUCTION_TOOLS.items()]


def compile_construction_command(*, layout: Mapping[str, Any], catalog: Sequence[Mapping[str, Any]],
                                 command_id: str, arguments: Mapping[str, Any], request_id: str,
                                 namespace: str) -> list[dict[str, Any]]:
    if command_id not in CONSTRUCTION_COMMANDS:
        raise FacilityValidationError("facility_construction_command_unknown", "Unsupported construction command.")
    executable = shutil.which("node")
    if not executable:
        raise FacilityValidationError("facility_construction_runtime_unavailable", "The construction compiler requires Node on the host.")
    payload = canonical_bytes({"layout": layout, "catalog": list(catalog), "operationIdNamespace": namespace,
                               "command": {"commandId": command_id, "arguments": arguments,
                                           "requestId": request_id, "expectedDraftRevision": layout_revision(layout)}})
    if len(payload) > MAX_COMPILER_BYTES:
        raise FacilityValidationError("facility_construction_payload_too_large", "Construction compiler input exceeds its byte budget.")
    try:
        result = subprocess.run([executable, "--max-old-space-size=128", str(ROOT / "tools/compile_facility_construction_command.js")],
                                input=payload, capture_output=True, timeout=MAX_COMPILER_SECONDS, cwd=ROOT)
    except subprocess.TimeoutExpired as exc:
        raise FacilityValidationError("facility_construction_compile_timeout", "Construction compilation exceeded its time budget.") from exc
    if len(result.stdout) > MAX_COMPILER_BYTES:
        raise FacilityValidationError("facility_construction_payload_too_large", "Construction compiler output exceeds its byte budget.")
    try:
        output = json.loads(result.stdout)
    except (ValueError, UnicodeError) as exc:
        raise FacilityValidationError("facility_construction_compile_failed", "Construction compiler returned no valid result.") from exc
    if result.returncode or output.get("ok") is not True:
        error = output.get("error") or {}
        raise FacilityValidationError(error.get("code", "facility_construction_compile_failed"),
                                      error.get("message", "Construction compilation failed."))
    operations = output.get("operations")
    if not isinstance(operations, list) or not 1 <= len(operations) <= 500:
        raise FacilityValidationError("facility_construction_operations_invalid", "Construction compiler returned no bounded operation plan.")
    return operations
