"""Additional read adapters, not an agent loop or a CAD migration.

The caller supplies a fresh, admitted context on every check. Identity is never
selected by tool arguments. See docs/codex-additional-workflows.md for wiring.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
import re
import time
from typing import Callable, Mapping

from jsonschema import Draft202012Validator

from ai_inspector.facility_layout.authorization import FacilityPrincipal
from ai_inspector.facility_layout.navigation_intent import navigation_context_summary
from .engineering_schemas import BINDING, REFERENCE, tool_specs
from .facility_tools import read_bound_layout
from .policy import PilotError


MAX_ARGUMENT_BYTES = 8192
MAX_RESULT_BYTES = 65536
ENGINEERING_READ_NAMES = frozenset(spec["name"] for spec in tool_specs())
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}")
_MESSAGES = {
    "codex_engineering_context_invalid": "A current admitted saved-layout context is required.",
    "codex_engineering_context_changed": "The user, session, workspace or document changed. Start a new turn.",
    "codex_saved_layout_required": "Finish or discard unsaved edits, conflicts and previews before inspection.",
    "codex_document_unavailable": "The saved document is unavailable, unauthorized or stale. Refresh it.",
    "codex_run_closed": "This inspection is no longer active.",
    "codex_tool_budget_exhausted": "The inspection tool budget has been reached.",
    "codex_tool_denied": "This tool is not authorized for this workflow.",
    "codex_tool_arguments_invalid": "Arguments do not match the bounded tool schema.",
    "codex_result_too_large": "Narrow the query or request a smaller page.",
    "codex_tool_result_invalid": "The domain read did not match the saved-document contract.",
    "codex_tool_failed": "The engineering read could not be completed.",
}


def _error(code):
    return PilotError(code, _MESSAGES[code], 409)


def _bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(",", ":")).encode("ascii")


def engineering_tool_specs():
    """Both additive read specs for FacilityReadGateway/FacilityEditGateway.

    Each output_schema describes the parent's {ok, data}/{ok, error} envelope.
    This function creates no gateway, workflow selection, budget or runtime.
    """
    return tool_specs()


def _saved_facts(current, reference, name, arguments):
    if name == "observe_navigation_context":
        workflow = "facility_navigation"
        facts = navigation_context_summary(current["layout"],
            query=arguments.get("query", ""), actor_class=arguments.get("actorClass"),
            maximum_records=arguments.get("maximumRecords", 20))
    else:
        workflow = "facility_process_routes"
        # The broader runtime resolves Process Maps through a lazy-writing
        # registry. Read only authored references from the authorized layout.
        rows = current["layout"].get("processBindings", [])
        if not isinstance(rows, list) or len(rows) > 5000:
            raise _error("codex_result_too_large")
        ids = set(arguments.get("ids", []))
        rows = sorted((row for row in rows
            if (not ids or row["processBindingId"] in ids)
            and ("processMapId" not in arguments or row["processMapId"] == arguments["processMapId"])),
            key=lambda row: row["processBindingId"])
        offset = arguments.get("offset", 0)
        selected = rows[offset:offset + arguments.get("pageSize", 20)]
        records = [{key: row[key] for key in BINDING["properties"]} for row in selected]
        end = offset + len(records)
        facts = {"records": records, "returnedCount": len(records), "totalCount": len(rows),
                 "nextOffset": end if end < len(rows) else None}
    return {"workflow": workflow, "document": deepcopy(reference),
            "readOnly": True, "savedLayoutOnly": True, "facts": facts}


def read_engineering_facts(runtime, principal, reference, name, arguments):
    """Synchronous _read_data delegate; returns data, NOT a second envelope.

    Reuses the principal-authorized saved-layout getter before/after the read.
    The parent gateway owns the single lock, call/time budget, receipts, worker
    lifecycle and fresh user/session/workspace/dirty-state admission checks.
    No external Process Map resolver, preview, write, or Codex loop is invoked.
    """
    try:
        if not isinstance(name, str) or name not in ENGINEERING_READ_NAMES:
            raise _error("codex_tool_denied")
        spec = next(spec for spec in engineering_tool_specs() if spec["name"] == name)
        if (not isinstance(principal, FacilityPrincipal)
                or not Draft202012Validator(REFERENCE).is_valid(reference)):
            raise _error("codex_engineering_context_invalid")
        if (not isinstance(arguments, dict)
                or not Draft202012Validator(spec["input_schema"]).is_valid(arguments)
                or any(key in arguments and type(arguments[key]) is not int
                       for key in ("maximumRecords", "pageSize", "offset"))):
            raise _error("codex_tool_arguments_invalid")
        raw = _bytes(arguments)
        if len(raw) > MAX_ARGUMENT_BYTES:
            raise _error("codex_tool_arguments_invalid")
        arguments, reference = json.loads(raw), deepcopy(reference)
        current = read_bound_layout(runtime, principal, reference)
        data = _saved_facts(current, reference, name, arguments)
        result = {"ok": True, "data": data}
        if len(_bytes(result)) > MAX_RESULT_BYTES:
            raise _error("codex_result_too_large")
        if not Draft202012Validator(spec["output_schema"]).is_valid(result):
            raise _error("codex_tool_result_invalid")
        read_bound_layout(runtime, principal, reference)
        return data
    except Exception as exc:
        code = getattr(exc, "code", "codex_tool_failed")
        raise _error(code if code in _MESSAGES else "codex_tool_failed") from None


@dataclass(frozen=True)
class EngineeringContext:
    """Backend principal plus admitted request identity and latest normalized facts.

    normalized is normalize_agent_context(...)["flat"], not model arguments.
    The callback must be thread-safe and fail on revoked admission or disconnect.
    """

    principal: FacilityPrincipal
    session_id: str
    conversation_id: str
    normalized: Mapping


def _context_identity(context, workflow):
    if (not isinstance(context, EngineeringContext)
            or not isinstance(context.principal, FacilityPrincipal)
            or not isinstance(context.normalized, Mapping)
            or not all(isinstance(value, str) and _IDENTITY.fullmatch(value)
                       for value in (context.session_id, context.conversation_id))):
        raise _error("codex_engineering_context_invalid")
    normalized = context.normalized
    reference = normalized.get("facility_layout_ref")
    live = normalized.get("facility_layout_live_state")
    if (normalized.get("active_mode") != "facility_layout"
            or not Draft202012Validator(REFERENCE).is_valid(reference)):
        raise _error("codex_engineering_context_invalid")
    # Missing/ambiguous cleanliness is not proof of a saved editor state.
    if (not isinstance(live, Mapping) or live.get("dirty") is not False
            or live.get("conflict") is not False
            or live.get("pendingOperations", []) != []
            or any(normalized.get(key) is not None for key in (
                "facility_generation_ref", "facility_design_ref", "facility_layout_proposal_id"))):
        raise _error("codex_saved_layout_required")
    for key in ("siteId", "layoutId", "revision"):
        if key in live and live[key] != reference[key]:
            raise _error("codex_engineering_context_changed")
    for key in ("baseRevision", "draftRevision"):
        if key in live and live[key] != reference["revision"]:
            raise _error("codex_engineering_context_changed")
    principal = context.principal
    return {
        "protocol": "engineering-read-v1", "workflow": workflow,
        "tenant": principal.tenant_id, "principal": principal.principal_id,
        "user": principal.principal_id, "session": context.session_id,
        "conversation": context.conversation_id, "workspace": "facility_layout",
        "roles": sorted(principal.roles), "sites": sorted(principal.allowed_site_ids),
        "document": deepcopy(reference),
    }


class EngineeringReadGateway:
    """Serialized, revocable reads using existing facility authority and functions."""

    def __init__(self, workflow, runtime, *, current_context: Callable[[], EngineeringContext],
                 turn_id, max_calls=8, timeout=120, status_sink=None):
        self._spec = tool_specs(workflow)[0]
        if (not callable(current_context) or not isinstance(turn_id, str)
                or not _IDENTITY.fullmatch(turn_id)
                or type(max_calls) is not int or not 1 <= max_calls <= 8
                or type(timeout) not in (int, float) or not math.isfinite(timeout)
                or not 0 < timeout <= 120):
            raise _error("codex_engineering_context_invalid")
        self.workflow, self.runtime = workflow, runtime
        self.current_context = current_context
        self.turn_id, self.max_calls = turn_id, max_calls
        self.status_sink = status_sink
        self.deadline = time.monotonic() + timeout
        self.closed, self.calls = False, 0
        self.receipts = []
        self.lock = asyncio.Lock()
        try:
            self._binding = _context_identity(current_context(), workflow)
        except Exception as exc:
            self.closed = True
            code = getattr(exc, "code", "codex_engineering_context_invalid")
            raise _error(code if code in _MESSAGES else "codex_engineering_context_invalid") from None
        self.binding_key = hashlib.sha256(_bytes(self._binding)).hexdigest()
        self._input = Draft202012Validator(self._spec["input_schema"])
        self._output = Draft202012Validator(self._spec["output_schema"])
        self.check()

    @property
    def specs(self):
        return [deepcopy(self._spec)]

    @property
    def binding(self):
        return deepcopy(self._binding)

    def _active(self):
        if self.closed or time.monotonic() >= self.deadline:
            self.closed = True
            raise _error("codex_run_closed")

    def _checked(self):
        self._active()
        try:
            context = self.current_context()
            if _context_identity(context, self.workflow) != self._binding:
                raise _error("codex_engineering_context_changed")
            current = read_bound_layout(self.runtime, context.principal, self._binding["document"])
            self._active()
            return context.principal, current
        except Exception as exc:
            self.closed = True
            code = getattr(exc, "code", "codex_document_unavailable")
            raise _error(code if code in _MESSAGES else "codex_document_unavailable") from None

    def check(self):
        """Reauthorize on replay/finalization as well as before and after tools."""
        return self._checked()[1]

    def _read(self, arguments):
        principal, _ = self._checked()
        try:
            return read_engineering_facts(self.runtime, principal, self._binding["document"],
                                          self._spec["name"], arguments)
        finally:
            self._checked()

    async def call(self, name, arguments):
        async with self.lock:
            started = time.monotonic()
            argument_hash = None
            try:
                self._active()
                if self.calls >= self.max_calls:
                    self.closed = True
                    raise _error("codex_tool_budget_exhausted")
                self.calls += 1
                if name != self._spec["name"]:
                    raise _error("codex_tool_denied")
                if not isinstance(arguments, dict) or not self._input.is_valid(arguments):
                    raise _error("codex_tool_arguments_invalid")
                raw = _bytes(arguments)
                if len(raw) > MAX_ARGUMENT_BYTES:
                    raise _error("codex_tool_arguments_invalid")
                argument_hash = hashlib.sha256(raw).hexdigest()
                arguments = json.loads(raw)
                if self.status_sink:
                    async with asyncio.timeout(max(0, self.deadline - time.monotonic())):
                        await self.status_sink("codex_inspecting")
                work = asyncio.create_task(asyncio.to_thread(self._read, arguments))
                try:
                    async with asyncio.timeout(max(0, self.deadline - time.monotonic())):
                        data = await asyncio.shield(work)
                except (asyncio.CancelledError, TimeoutError):
                    self.closed = True
                    # Synchronous backend reads cannot be killed safely. Join and discard,
                    # including repeated outer cancellation, before releasing the host.
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
                self._active()
                result = {"ok": True, "data": data}
                if len(_bytes(result)) > MAX_RESULT_BYTES:
                    raise _error("codex_result_too_large")
                if not self._output.is_valid(result):
                    raise _error("codex_tool_result_invalid")
            except asyncio.CancelledError:
                self.closed = True
                self._receipt(name, argument_hash, started, "codex_run_closed")
                raise
            except Exception as exc:
                code = "codex_run_closed" if isinstance(exc, TimeoutError) else getattr(exc, "code", "codex_tool_failed")
                code = code if code in _MESSAGES else "codex_tool_failed"
                result = {"ok": False, "error": {"code": code, "message": _MESSAGES[code]}}
                if code == "codex_run_closed":
                    self.closed = True
            self._receipt(name, argument_hash, started, result.get("error", {}).get("code"))
            return result

    def _receipt(self, name, argument_hash, started, code):
        if len(self.receipts) < self.max_calls + 1:
            self.receipts.append({"tool": name if name == self._spec["name"] else "denied",
                "ok": code is None, "argumentHash": argument_hash, "bindingHash": self.binding_key,
                "durationMs": round((time.monotonic() - started) * 1000), "errorCode": code})


def create_engineering_gateway(workflow, runtime, *, current_context, turn_id,
                               max_calls=8, timeout=120, status_sink=None):
    """Factory for the generic pilot; never installs tools or launches Codex."""
    return EngineeringReadGateway(workflow, runtime, current_context=current_context,
        turn_id=turn_id, max_calls=max_calls, timeout=timeout, status_sink=status_sink)
