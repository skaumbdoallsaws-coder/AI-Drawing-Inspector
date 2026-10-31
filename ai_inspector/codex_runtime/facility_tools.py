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
    from .library_tools import tool_specs as library_tool_specs
    from ai_inspector.facility_layout.parking_review import tool_spec as parking_tool_spec
    from ai_inspector.facility_layout.workstation_review import tool_spec as workstation_tool_spec
    from .research_tools import tool_specs as research_tool_specs
    from .site_tools import tool_specs as site_tool_specs
    return [{"name": "inspect_facility_context", "description":
             "Read the authorized saved layout summary and stable entity IDs. Call this before detailed inspection. No edits.",
             "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
            *[deepcopy(spec) for spec in facility_layout_read_tool_specs() if spec["name"] in READ_NAMES],
            *engineering_tool_specs(), *authoring_tool_specs(), *component_tool_specs(), *library_tool_specs(),
            parking_tool_spec(), workstation_tool_spec(), *research_tool_specs(), *site_tool_specs()]


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
        self.progress = None  # TurnProgress when the chat pane shows steps
        self.closed, self.calls = False, 0
        self.packages = {}  # whole planned designs, staged by preview_planned_design (assisted_tools.py)
        self.pdf, self.pdfs = None, []  # the PDFs prepared this turn, shown as file cards under the reply
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

    def take_image(self):
        """The picture the last tool call produced, if any; handed out once."""
        image, self.last_image = getattr(self, "last_image", None), None
        return image

    async def call(self, name, arguments):
        async with self.lock:
            self.last_image = None
            self.before_call(name)
            step = await self.progress.tool_started(name, arguments) if self.progress else None
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
            if step:
                await self.progress.tool_finished(step, result)
            return result

    def before_call(self, name):
        pass

    def layout_names(self):
        """Zone, item and catalog names for progress wording, at the bound revision."""
        from .progress import LayoutNames
        layout = read_bound_layout(self.runtime, self.principal, self.reference)["layout"]
        provider = getattr(self.runtime, "asset_catalog_provider", None)
        return LayoutNames(layout, provider(self.principal, self.reference["siteId"]) if provider else [])

    def _component_inventory(self, placement_id, representation):
        """The saved placement's visual fingerprint and part keys, as Sage's component inspection reads them."""
        resolver = self.runtime.service.component_inventory_resolver
        if resolver is None:
            raise PilotError('codex_visual_unavailable', 'Component inspection is not configured for this host.', 422)
        return resolver(self.principal, self.reference, placement_id, representation)

    def _resolver(self):
        from ai_inspector.facility_layout.errors import FacilityLayoutError
        service, site_id, cache = self.runtime.service, self.reference['siteId'], {}

        def resolve(asset_id, revision):
            if (asset_id, revision) not in cache:
                try:
                    cache[asset_id, revision] = service._resolve_asset_dependency(self.principal, site_id, asset_id,
                                                                                   revision)[0]
                except FacilityLayoutError:
                    cache[asset_id, revision] = None
            return cache[asset_id, revision]
        return resolve

    def _keep_pdf(self, card):
        self.pdfs = [c for c in self.pdfs if c['url'] != card['url']] + [card]
        self.pdf = card

    def _map_pdf(self, kind):
        """The evacuation or emergency map, built once as its link will build it, kept as a file card."""
        import re
        from urllib.parse import quote
        from ai_inspector.facility_layout.emergency_pdf import EmergencyMapError, render_emergency_pdf
        site_id, layout_id = self.reference['siteId'], self.reference['layoutId']
        saved = read_bound_layout(self.runtime, self.principal, self.reference)
        try:
            content, info = render_emergency_pdf(saved['layout'], self._resolver(), kind=kind,
                                                 revision=saved.get('revision') or '')
        except EmergencyMapError as exc:
            return {'readOnly': True, 'available': False, 'kind': kind, 'reason': str(exc)}
        name = re.sub(r'[\\/:*?"<>|]+', ' ', saved['layout'].get('displayName') or layout_id).strip()[:100] or 'Layout'
        title = 'evacuation map' if kind == 'evacuation' else 'emergency map'
        url = (f"/api/facility-layouts/{quote(site_id, safe='')}/{quote(layout_id, safe='')}/plan.pdf"
               f"?revision={quote(str(saved.get('revision') or ''), safe='')}&kind={kind}")
        self._keep_pdf({'type': 'file', 'fileName': f'{name} - {title}.pdf', 'url': url,
                        'mimeType': 'application/pdf', 'detail': 'PDF - 1 poster page - 11 x 17 in - ready to print'})
        return dict(info, readOnly=True, available=True, fileName=self.pdf['fileName'], pages=1, bytes=len(content),
                    revision=saved.get('revision'), shownInChat='as a file card the user clicks to open')

    def _layout_pdf(self, kind='layout'):
        """Build the bound layout's plan PDF once, as its link will (plan_pdf.create_plan_pdf_router), and keep a
        file card for the reply."""
        if kind != 'layout':
            return self._map_pdf(kind)
        import re
        from urllib.parse import quote
        from ai_inspector.facility_layout.plan_pdf import _fit_check, load_template, render_plan_pdf
        service = self.runtime.service
        site_id, layout_id = self.reference['siteId'], self.reference['layoutId']
        saved = read_bound_layout(self.runtime, self.principal, self.reference)
        resolve = self._resolver()
        content = render_plan_pdf(saved['layout'], resolve, revision=saved.get('revision') or '',
                                  fit=_fit_check(service, self.principal, site_id, saved['layout']))
        pages = len(re.findall(rb'/Type\s*/Page(?![a-zA-Z])', content))
        titles = {sheet['title'].capitalize(): sheet['number'] for sheet in load_template()['sheets']}
        sheets = [f'{number} {title.lower()}' for title, number in titles.items()][-pages:] if pages else []
        name = re.sub(r'[\\/:*?"<>|]+', ' ', saved['layout'].get('displayName') or layout_id).strip()[:100] or 'Layout'
        url = (f"/api/facility-layouts/{quote(site_id, safe='')}/{quote(layout_id, safe='')}/plan.pdf"
               f"?revision={quote(str(saved.get('revision') or ''), safe='')}")
        self._keep_pdf({'type': 'file', 'fileName': f'{name} - layout plan.pdf', 'url': url,
                        'mimeType': 'application/pdf',
                        'detail': f"PDF - {pages} sheet{'s' if pages != 1 else ''} - 11 x 17 in - ready to print"})
        return {'readOnly': True, 'available': True, 'fileName': self.pdf['fileName'], 'pages': pages,
                'sheets': sheets, 'paper': '11 x 17 in (tabloid), landscape', 'bytes': len(content),
                'revision': saved.get('revision'), 'shownInChat': 'as a file card the user clicks to open'}

    def _read_data(self, name, arguments):
        from .site_tools import CATALOG_TOOLS, NAMES as SITE_NAMES, STEP_TOOLS, read_site
        if name == 'prepare_layout_pdf':
            return self._layout_pdf(arguments.get('kind') or 'layout')
        if name == 'suggest_emergency_teams':
            from ai_inspector.facility_layout.emergency_plan import suggest_emergency_plan
            saved = read_bound_layout(self.runtime, self.principal, self.reference)
            result = suggest_emergency_plan(saved['layout'], self._resolver())
            result['staging'] = ('Show the user the teams, zones and meeting points first. Stage the plan, with '
                                 'the user\'s changes, as one set_emergency_plan operation.')
            return dict(result, identity=deepcopy(self.reference), savedLayoutOnly=True, readOnly=True)
        if name in SITE_NAMES:
            from ai_inspector.facility_layout.site_imagery import site_photo_path
            saved = read_bound_layout(self.runtime,self.principal,self.reference)
            photo_path = lambda image: site_photo_path(self.runtime.service, self.principal,  # noqa: E731
                                                       self.reference['siteId'], image['imageId'])
            try:
                catalog = ({asset['assetId']: asset for asset in
                            self.runtime.asset_catalog_provider(self.principal, self.reference['siteId'])}
                           if name in CATALOG_TOOLS else None)  # model sizes, and exact revisions for placements
                inventory = self._component_inventory if name == 'plan_design_paint' else None
                result = read_site(saved['layout'],name,arguments,photo_path,catalog,inventory)
            except ValueError as exc:
                from ai_inspector.facility_layout.site_steps import StepError
                # A build step that cannot do what was asked says why; Sage tells the user and asks.
                code = 'site_step_refused' if isinstance(exc, StepError) else 'site_arguments_invalid'
                raise PilotError(code,str(exc),422) from exc
            # A picture rides beside the JSON result, for runtimes that can show one (mcp_bridge.py).
            self.last_image = result.pop('_image', None)
            if name in STEP_TOOLS and result.get('available'):
                # Each build step waits here as one package; Sage reads the summary, not the operations.
                package = result.pop('operations')
                package_id = f"{result['step']}-{len(self.packages) + 1}"
                self.packages[package_id] = package
                result['package'] = {'packageId': package_id, 'operations': len(package)}
                result['staging'] = ('Stage this step with preview_planned_design and this packageId: one review. '
                                     'Then stop: the user asks for the next step.')
            if name == 'plan_design_paint' and result.get('available'):
                package = result.pop('operations')
                package_id = f'paint-{len(self.packages) + 1}'
                self.packages[package_id] = package
                result['package'] = {'packageId': package_id, 'operations': len(package)}
                result['staging'] = ('Stage the paint at once with preview_planned_design and this packageId: '
                                     'one review covers the walls, the yard target and every truck, pickup and rack.')
            return dict(result,identity=deepcopy(self.reference),savedLayoutOnly=True,readOnly=True)
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
        if name == "list_facility_library":
            from .library_tools import list_library
            return list_library(arguments)
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
