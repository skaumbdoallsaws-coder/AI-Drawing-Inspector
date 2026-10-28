"""Proposal-only tools. Approval and commit are deliberately not MCP capabilities."""
from ai_inspector.facility_layout.asset_orientation import resolve_orientation_intents
from ai_inspector.facility_layout.operation_proposals import create
from ai_inspector.facility_layout.placement_intents import PLACEMENT_INTENT_KEYS, resolve_placement_intents
from .edit_schemas import obj, operation_batch_schema, text
from .policy import PilotError

PACKAGE_LIMITS = (1000, 600_000)  # a design package from the server's planner, not model-written operations
PREVIEWS = {"preview_facility_operations", "preview_facility_undo", "preview_planned_design"}
from .facility_tools import FacilityReadGateway, tool_specs
from .authoring_artifacts import prepare_lettering, tool_specs as artifact_specs
from .operation_contracts import contracts, tool_spec as contract_spec


def edit_tool_specs():
    schema = operation_batch_schema()
    return [
        {"name": "preview_facility_operations", "description":
         "Validate and stage one exact batch on the bound saved layout. This tool never saves. "
         "After the turn the app applies eligible edits in Apply Directly mode, otherwise it opens a review. "
         "Use real stable IDs and existing asset definitions; positions are meters in the layout coordinate frame. "
         "A validation error means no proposal was created: inspect the findings, correct the batch, and preview again. "
         "All operations in the batch apply together, not incrementally. Locked equipment cannot be moved. "
         "Omit generated IDs on add operations. Settings collections replace, not merge: preserve unrelated records. "
         "Zone color is extensions.style.fillColor; prefer upsert_floor_surface for a targeted floor finish. "
         "Artwork must reference existing content-addressed images; this tool cannot import files or generate images. "
         "At most 50 operations and 24000 serialized bytes per batch.", "input_schema": schema},
        {"name": "preview_planned_design", "description":
         "Stage a whole package by its packageId, as one review: one build step (plan_warehouse_building, "
         "plan_warehouse_zones, plan_floor_markings, plan_storage_layout, plan_site_docks, plan_site_parking, "
         "plan_warehouse_contents) or the paint plan_design_paint prepared. The same validation as "
         "preview_facility_operations; this tool never saves. In Apply Directly mode the app applies a package "
         "without findings after your turn (approvalRequired false); otherwise it opens a review. A package belongs "
         "to this turn and the saved layout it was planned on.", "input_schema": obj({"packageId": text(40)})},
        {"name": "preview_facility_undo", "description":
         "Prepare an exact Undo preview for an approved commit receipt. Fails if the layout has changed since that commit. "
         "The app handles user authorization according to the selected edit mode; this tool never saves.",
         "input_schema": obj({"receiptId": text()})},
    ]


class FacilityEditGateway(FacilityReadGateway):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from jsonschema import Draft202012Validator
        editing = edit_tool_specs()
        self.operation_schema = editing[0]["input_schema"]
        self.specs = [*tool_specs(), *editing, *artifact_specs(), contract_spec(self.operation_schema)]
        self.validators = {spec["name"]: Draft202012Validator(spec["input_schema"]) for spec in self.specs}
        self.proposal = None
        self.edit_mode = "preview"

    def before_call(self, name):
        if name in PREVIEWS:
            self.proposal = None

    async def call(self, name, arguments):
        result = await super().call(name, arguments)
        if name in PREVIEWS and not result["ok"]:
            self.proposal = None
        if name == "preview_facility_operations" and result.get("error", {}).get("code") == "codex_tool_arguments_invalid":
            import json
            details = result["error"]["details"]
            names = []
            rows = arguments.get("operations", []) if isinstance(arguments, dict) else []
            for finding in details["findings"]:
                parts = finding["path"].split("/")
                if len(parts) < 3 or parts[1] != "operations" or not parts[2].isdigit():
                    continue
                index = int(parts[2])
                if not isinstance(rows, list) or index >= len(rows) or not isinstance(rows[index], dict):
                    continue
                operation_name = rows[index].get("op", rows[index].get("type"))
                if isinstance(operation_name, str) and operation_name not in names:
                    names.append(operation_name)
            contract = contracts(self.operation_schema, names)
            if contract["properties"]["operations"]["items"]["oneOf"] and len(json.dumps(contract).encode()) < 28000:
                details["operationContract"] = contract
            details["recovery"] = "Use inspect_facility_operation_contracts for exact fields. Correct the whole batch; do not guess fields or repeat it unchanged."
        return result

    def _read_data(self, name, arguments):
        if name == "inspect_facility_operation_contracts":
            return {"readOnly": True, "schema": contracts(self.operation_schema, arguments["operations"])}
        if name == "prepare_facility_lettering":
            return prepare_lettering(self.runtime, self.principal, self.reference, arguments)
        if name == "preview_planned_design":
            package = self.packages.get(arguments["packageId"])
            if package is None:
                raise PilotError("codex_design_package_unknown",
                                 "Plan it first with a build step or plan_design_paint and use the packageId it returned.", 404)
            result = create(self.runtime.service, self.principal, self.reference["siteId"], self.reference["layoutId"],
                            self.reference["revision"], operations=package, edit_mode=self.edit_mode, limits=PACKAGE_LIMITS,
                            planned=True)
            return self._staged(result)
        if name not in {"preview_facility_operations", "preview_facility_undo"}:
            return super()._read_data(name, arguments)
        operations = arguments.get("operations")
        intents = ("orientation", *PLACEMENT_INTENT_KEYS)
        if any(isinstance(item, dict) and any(key in item for key in intents) for item in operations or []):
            from .facility_tools import read_bound_layout
            catalog = self.runtime.asset_catalog_provider(self.principal, self.reference["siteId"])
            layout = read_bound_layout(self.runtime, self.principal, self.reference)["layout"]
            # Turns first, so an item can sit on a desk placed and turned earlier in the batch.
            operations = resolve_orientation_intents(operations, catalog=catalog, layout=layout)
            operations = resolve_placement_intents(operations, catalog=catalog, layout=layout)
        result = create(self.runtime.service, self.principal, self.reference["siteId"], self.reference["layoutId"],
            self.reference["revision"], operations=operations, undo_receipt_id=arguments.get("receiptId"),
            edit_mode=self.edit_mode)
        return self._staged(result)

    def _staged(self, result):
        self.proposal = {**self.reference, "proposalId": result["proposalId"]}
        alternative = result["alternative"]
        if self.edit_mode == "direct":
            self.proposal["editMode"] = "direct"
        return {"proposalId": result["proposalId"], "baseRevision": result["baseRevision"],
            "saved": False, "approvalRequired": not (self.edit_mode == "direct" and alternative["directApplyPolicy"]["eligible"]),
            "editMode": self.edit_mode, "directApplyPolicy": alternative["directApplyPolicy"], "expiresAt": result["expiresAt"],
            "validation": alternative["validation"], "metrics": alternative["metrics"],
            "diffHash": alternative["operationReceipt"]["diffHash"],
            "affectedIds": alternative["operationReceipt"]["affectedIds"][:100],
            "createdIds": alternative["operationReceipt"]["createdIds"][:100]}
