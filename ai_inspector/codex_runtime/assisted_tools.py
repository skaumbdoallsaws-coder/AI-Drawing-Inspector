"""Proposal-only tools. Approval and commit are deliberately not MCP capabilities."""
from ai_inspector.facility_layout.asset_orientation import resolve_orientation_intents
from ai_inspector.facility_layout.operation_proposals import create
from .edit_schemas import obj, operation_batch_schema, text
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
        if name in {"preview_facility_operations", "preview_facility_undo"}:
            self.proposal = None

    async def call(self, name, arguments):
        result = await super().call(name, arguments)
        if name in {"preview_facility_operations", "preview_facility_undo"} and not result["ok"]:
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
        if name not in {"preview_facility_operations", "preview_facility_undo"}:
            return super()._read_data(name, arguments)
        operations = arguments.get("operations")
        if any(isinstance(item, dict) and "orientation" in item for item in operations or []):
            from .facility_tools import read_bound_layout
            operations = resolve_orientation_intents(operations,
                catalog=self.runtime.asset_catalog_provider(self.principal, self.reference["siteId"]),
                layout=read_bound_layout(self.runtime, self.principal, self.reference)["layout"])
        result = create(self.runtime.service, self.principal, self.reference["siteId"], self.reference["layoutId"],
            self.reference["revision"], operations=operations, undo_receipt_id=arguments.get("receiptId"),
            edit_mode=self.edit_mode)
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
