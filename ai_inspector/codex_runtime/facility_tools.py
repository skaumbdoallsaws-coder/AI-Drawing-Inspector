"""Read-only MCP contracts over the existing, revision-bound facility runtime."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
import time

from anyio import CancelScope

from ai_inspector.facility_layout.observation import facility_layout_read_tool_specs
from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.facility_layout.agent_runtime import FacilityLayoutAgentRuntimeError
from .policy import PilotError


READ_NAMES = frozenset({"inspect_facility_entities", "inspect_facility_semantics",
                        "inspect_facility_findings", "analyze_facility_spatial",
                        "search_industrial_assets", "inspect_facility_region", "analyze_facility_fit",
                        "inspect_pattern_provenance", "inspect_cell_layout_provenance"})
OUTPUT_SCHEMA = {
    "type": "object", "required": ["ok"], "properties": {
        "ok": {"type": "boolean"}, "data": {"type": "object"},
        "error": {"type": "object", "required": ["code", "message"],
                  "properties": {"code": {"type": "string"}, "message": {"type": "string"}, "details": {"type": "object"}},
                  "additionalProperties": False},
    }, "additionalProperties": False,
}


def tool_specs():
    from .engineering_schemas import tool_specs as engineering_tool_specs
    from .authoring_reads import tool_specs as authoring_tool_specs
    from .component_inventory import tool_specs as component_tool_specs
    from ai_inspector.facility_layout.parking_review import tool_spec as parking_tool_spec
    from ai_inspector.facility_layout.workstation_review import tool_spec as workstation_tool_spec
    from .research_tools import tool_specs as research_tool_specs
    return [{"name": "inspect_facility_context", "description":
             "Read the authorized saved layout summary and stable entity IDs. Call this before detailed inspection. No edits.",
             "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
            *[deepcopy(spec) for spec in facility_layout_read_tool_specs() if spec["name"] in READ_NAMES],
            *engineering_tool_specs(), *authoring_tool_specs(), *component_tool_specs(), parking_tool_spec(), workstation_tool_spec(), *research_tool_specs()]


def read_bound_layout(runtime, principal, reference):
    """Authorize and re-read saved identity without constructing geometry context."""
    if not isinstance(reference, dict) or set(reference) != {"siteId", "layoutId", "revision"}:
        raise PilotError("codex_document_required", "Select a saved Facility Layout for the read-only pilot.", 409)
    try:
        current = runtime.service.get_layout(principal, reference["siteId"], reference["layoutId"])
        if current["revision"] != reference["revision"]:
            raise PilotError("codex_document_unavailable", "The saved document has changed. Refresh it before retrying.", 409)
        return current
    except FacilityLayoutError as exc:
        raise PilotError("codex_document_unavailable", "The saved document is unavailable, unauthorized, or has changed. Refresh it before retrying.", 409) from exc


class FacilityReadGateway:
    def __init__(self, runtime, principal, reference, *, turn_id, max_calls=8, timeout=120, status_sink=None, researcher=None):
        from jsonschema import Draft202012Validator
        if not isinstance(reference, dict) or set(reference) != {"siteId", "layoutId", "revision"}:
            raise PilotError("codex_document_required", "Select a saved Facility Layout for the read-only pilot.", 409)
        self.runtime, self.principal = runtime, principal
        self.reference = deepcopy(reference)
        self.turn_id, self.max_calls = turn_id, max_calls
        self.deadline = time.monotonic() + timeout
        self.status_sink = status_sink
        self.closed, self.calls = False, 0
        self.credential_check = None
        self.receipts = []
        self.lock = asyncio.Lock()
        self.specs = tool_specs()
        self.validators = {spec["name"]: Draft202012Validator(spec["input_schema"]) for spec in self.specs}
        from .research_tools import PublicResearchSession
        self.research = PublicResearchSession(turn_id=turn_id, check=self.check, researcher=researcher)
        self.check()

    def check(self):
        if self.credential_check:
            self.credential_check()
        if self.closed or time.monotonic() >= self.deadline:
            raise PilotError("codex_run_closed", "This inspection is no longer active.", 409)
        return read_bound_layout(self.runtime, self.principal, self.reference)

    async def call(self, name, arguments):
        async with self.lock:
            self.before_call(name)
            started = time.monotonic()
            self.calls += 1
            try:
                if self.calls > self.max_calls:
                    self.closed = True
                    raise PilotError("codex_tool_budget_exhausted", "The inspection tool budget has been reached.", 409)
                self.check()
                if name not in self.validators:
                    raise PilotError("codex_tool_denied", "This tool is not authorized in the read-only pilot.", 403)
                errors = argument_errors(self.validators[name], arguments)
                if errors:
                    error = PilotError("codex_tool_arguments_invalid", "Arguments do not match the tool schema. Correct the listed fields and retry.", 422)
                    error.argument_findings = errors
                    raise error
                if self.status_sink:
                    from .research_tools import NAMES
                    await self.status_sink("codex_researching" if name in NAMES else "codex_inspecting")
                work = asyncio.create_task(asyncio.to_thread(self._read_data, name, arguments))
                try:
                    data = await asyncio.shield(work)
                except asyncio.CancelledError:
                    # A read already executing cannot be interrupted safely. Join it before releasing the host.
                    self.closed = True
                    # Shield level cancellation; asyncio.shield also protects against direct Task.cancel().
                    with CancelScope(shield=True):
                        while not work.done():
                            try:
                                await asyncio.shield(work)
                            except asyncio.CancelledError:
                                continue
                            except Exception:
                                break
                        if not work.cancelled():
                            work.exception()
                    raise
                self.check()
                result = {"ok": True, "data": data}
                if len(json.dumps(result, allow_nan=False).encode()) > 65536:
                    raise PilotError("codex_result_too_large", "Narrow the inspection or request a smaller page.", 422)
            except Exception as error:
                code = getattr(error, "code", "codex_tool_failed")
                # Domain errors have controlled public messages. Never expose arbitrary exceptions or paths.
                message = str(error) if isinstance(error, (PilotError, FacilityLayoutError, FacilityLayoutAgentRuntimeError)) else "The inspection could not be completed."
                result = {"ok": False, "error": {"code": str(code), "message": message}}
                if isinstance(error, PilotError) and getattr(error, "argument_findings", None):
                    result["error"]["details"] = {"findings": error.argument_findings}
                if isinstance(error, (FacilityLayoutError, FacilityLayoutAgentRuntimeError)) and isinstance(getattr(error, "details", None), dict):
                    details = {key: deepcopy(value[:10] if isinstance(value, list) else value)
                        for key, value in error.details.items()
                        if key in {"findings", "currentRevision", "operationIndex", "references", "targetId"}}
                    if details and len(json.dumps(details, allow_nan=False).encode()) <= 16000:
                        result["error"]["details"] = details
            self.receipts.append({"tool": name if name in self.validators else "denied", "ok": result["ok"],
                "argumentHash": hashlib.sha256(json.dumps(arguments, sort_keys=True).encode()).hexdigest(),
                "durationMs": round((time.monotonic() - started) * 1000),
                "errorCode": result.get("error", {}).get("code")})
            return result

    def before_call(self, name):
        pass

    def _read_data(self, name, arguments):
        from .engineering_tools import ENGINEERING_READ_NAMES, read_engineering_facts
        from .authoring_reads import READ_NAMES as AUTHORING_READ_NAMES, read_authoring
        from .research_tools import NAMES
        if name in NAMES:
            return self.research.run(name, arguments)
        if name == "review_facility_parking":
            from ai_inspector.facility_layout.parking_review import review_parking
            saved = read_bound_layout(self.runtime, self.principal, self.reference)
            return dict(review_parking(saved["layout"], arguments["zoneIds"], arguments.get("requestedSpaces")),
                        identity=deepcopy(self.reference), savedLayoutOnly=True, readOnly=True)
        if name == "review_facility_workstations":
            from ai_inspector.facility_layout.workstation_review import review_document
            saved = read_bound_layout(self.runtime, self.principal, self.reference)
            return dict(review_document(self.runtime.service, self.principal, self.reference["siteId"],
                        saved["layout"], arguments), identity=deepcopy(self.reference), savedLayoutOnly=True, readOnly=True)
        if name == "inspect_facility_components":
            from .component_inventory import inspect_components
            return inspect_components(self.runtime, self.principal, self.reference, arguments)
        if name in AUTHORING_READ_NAMES:
            return read_authoring(self.runtime, self.principal, self.reference, name, arguments)
        if name in ENGINEERING_READ_NAMES:
            return read_engineering_facts(self.runtime, self.principal, self.reference, name, arguments)
        if name == "inspect_facility_context":
            bundle = self.runtime.resolve_context(self.principal, site_id=self.reference["siteId"],
                layout_id=self.reference["layoutId"], expected_revision=self.reference["revision"])
            edit_spec = next((spec for spec in self.specs if spec["name"] == "preview_facility_operations"), None)
            operations = [] if edit_spec is None else [item["properties"]["op"]["const"]
                for item in edit_spec["input_schema"]["properties"]["operations"]["items"]["oneOf"]]
            return {"identity": deepcopy(bundle.state["identity"]), "digest": deepcopy(bundle.digest),
                    "savedLayoutOnly": True, "readOnly": True, "publicResearch": self.research.status(), "authoring": {
                        "previewOperations": operations, "approvalRequired": True, "canCommit": False,
                        "maxOperationsPerPreview": 50, "maxPreviewBytes": 24000,
                        "toolCallsRemaining": max(0, self.max_calls-self.calls),
                        "inspectionTools": [spec["name"] for spec in self.specs if not spec["name"].startswith("preview_")],
                        "imageImport": "Use the app's image upload control for new local artwork; tools cannot open arbitrary files."}}
        return self.runtime.execute_read_tool(self.principal,
            site_id=self.reference["siteId"], layout_id=self.reference["layoutId"],
            expected_revision=self.reference["revision"], tool_name=name,
            arguments=arguments, turn_id=self.turn_id)


def argument_errors(validator, arguments):
    """Return useful bounded diagnostics for the requested operation, not every union branch."""
    from itertools import islice
    findings = []
    grouped = {}
    for error in islice(validator.iter_errors(arguments), 12):
        relevant = [error]
        if error.validator == "oneOf" and isinstance(error.instance, dict) and error.context:
            op = error.instance.get("op")
            branches = error.schema.get("oneOf", [])
            operation_names = [branch.get("properties", {}).get("op", {}).get("const") for branch in branches]
            if operation_names and all(operation_names) and op not in operation_names:
                findings.append({"path": "/" + "/".join(str(p) for p in error.absolute_path) + "/op",
                    "message": "Use the required 'op' discriminator. Supported operations: " + ", ".join(operation_names)})
                continue
            indices = {i for i, branch in enumerate(branches)
                       if branch.get("properties", {}).get("op", {}).get("const") == op}
            matches = [e for e in error.context if e.schema_path and e.schema_path[0] in indices]
            if matches:
                relevant = matches
        for item in relevant:
            path = "/" + "/".join(str(p) for p in item.absolute_path)
            key = (path, item.validator)
            if key in grouped:
                continue
            if item.validator == "required" and isinstance(item.instance, dict):
                missing = [name for name in item.validator_value if name not in item.instance]
                message = "Required properties missing: " + ", ".join(missing)
            else:
                message = item.message
            grouped[key] = True
            findings.append({"path": path, "message": message[:1500]})
    return findings[:12]
