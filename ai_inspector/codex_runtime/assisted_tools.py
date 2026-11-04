"""Proposal-only tools. Approval and commit are deliberately not MCP capabilities."""
from ai_inspector.facility_layout.asset_orientation import resolve_orientation_intents
from ai_inspector.facility_layout.operation_proposals import create
from ai_inspector.facility_layout.placement_intents import PLACEMENT_INTENT_KEYS, resolve_placement_intents
from .edit_schemas import obj, operation_batch_schema, text
from .policy import PilotError

PACKAGE_LIMITS = (1000, 600_000)  # a design package from the server's planner, not model-written operations
PREVIEWS = {"preview_facility_operations", "preview_facility_undo", "preview_planned_design",
            "preview_floor_plan_import"}
from .facility_tools import FacilityReadGateway, tool_specs
from .authoring_artifacts import prepare_lettering, tool_specs as artifact_specs
from .operation_contracts import contracts, tool_spec as contract_spec
from .floor_plan_tools import PREVIEW as FLOOR_PLAN_PREVIEW, preview as preview_floor_plan, preview_spec


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
         "plan_warehouse_contents), the paint plan_design_paint prepared, or a pattern, cell, position or stack "
         "from plan_facility_pattern, plan_facility_cell, plan_facility_position or plan_facility_stack, or basic "
         "shapes from place_along_line, place_grid or roof_frame. The same validation as "
         "preview_facility_operations; this tool never saves. In Apply Directly mode the app applies a package "
         "without findings after your turn (approvalRequired false); otherwise it opens a review. A package belongs "
         "to this turn and the saved layout it was planned on.", "input_schema": obj({"packageId": text(40)})},
        {"name": "preview_facility_undo", "description":
         "Prepare an exact Undo preview for an approved commit receipt. Fails if the layout has changed since that commit. "
         "The app handles user authorization according to the selected edit mode; this tool never saves.",
         "input_schema": obj({"receiptId": text()})},
        preview_spec(),
    ]


class FacilityEditGateway(FacilityReadGateway):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from jsonschema import Draft202012Validator
        editing = edit_tool_specs()
        self.operation_schema = editing[0]["input_schema"]
        from ai_inspector.facility_layout.sage_shapes import tool_specs as shape_tool_specs
        self.specs = [*tool_specs(), *editing, *shape_tool_specs(), *artifact_specs(),
                      contract_spec(self.operation_schema)]
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
                                 "Plan it first with a build step, plan_design_paint, plan_facility_pattern, "
                                 "plan_facility_cell, plan_facility_position, plan_facility_stack, "
                                 "place_along_line, place_grid or roof_frame and use the packageId it returned.", 404)
            result = create(self.runtime.service, self.principal, self.reference["siteId"], self.reference["layoutId"],
                            self.reference["revision"], operations=package, edit_mode=self.edit_mode, limits=PACKAGE_LIMITS,
                            planned=True)
            return self._staged(result)
        if name == FLOOR_PLAN_PREVIEW:
            return self._staged_for_review(*preview_floor_plan(self, arguments))
        from ai_inspector.facility_layout import sage_shapes
        if name in sage_shapes.NAMES:
            return self._shapes(name, arguments)
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
        if any(isinstance(item, dict) and item.get("op") == "set_scene" and isinstance(item.get("scene"), dict)
               and "sceneId" in item["scene"] for item in operations or []):
            from ai_inspector.facility_layout.operations import keep_current_scene
            from .facility_tools import read_bound_layout
            operations = keep_current_scene(
                operations, read_bound_layout(self.runtime, self.principal, self.reference)["layout"])
        result = create(self.runtime.service, self.principal, self.reference["siteId"], self.reference["layoutId"],
            self.reference["revision"], operations=operations, undo_receipt_id=arguments.get("receiptId"),
            edit_mode=self.edit_mode)
        return self._staged(result)

    def _staged_for_review(self, kind, result):
        """A drawing's change staged (floor_plan_tools.preview): never applied directly, in any edit mode."""
        if kind == "conversion":
            proposal = result["proposal"]
            self.proposal = {**self.reference, "proposalId": proposal["proposalId"]}
            return {"proposalId": proposal["proposalId"], "baseRevision": proposal["baseRevision"], "saved": False,
                    "approvalRequired": True, "editMode": "preview",
                    "directApplyPolicy": proposal["directApplyPolicy"], "expiresAt": proposal["expiresAt"],
                    "metrics": proposal["metrics"], "conversionId": result["conversionId"],
                    "review": "The app opens a review of what the drawing converts to; nothing is saved until the "
                              "user approves it."}
        alternative = result["alternative"]
        self.proposal = {**self.reference, "proposalId": result["proposalId"]}
        return {"proposalId": result["proposalId"], "baseRevision": result["baseRevision"], "saved": False,
                "approvalRequired": True, "editMode": "preview",
                "directApplyPolicy": alternative["directApplyPolicy"], "expiresAt": result["expiresAt"],
                "validation": alternative["validation"], "metrics": alternative["metrics"],
                "diffHash": alternative["operationReceipt"]["diffHash"],
                "review": "The app opens a review of the drawing's new placement or layer roles; nothing is saved "
                          "until the user approves it."}

    def _obstacles(self, layout):
        """The layout's obstacle map (BS4) from the spatial checks' own inputs: the items' asset definitions, the
        effective shell with its walls and the evidence authority for clearance envelopes."""
        from ai_inspector.facility_layout.errors import FacilityLayoutError
        from ai_inspector.facility_layout.obstacle_map import ObstacleMap
        try:
            context = self.runtime.service._spatial_context(self.principal, self.reference["siteId"], layout)
        except FacilityLayoutError as error:
            raise PilotError(error.code, error.message, 409) from None
        return ObstacleMap(layout, shell=context.shell, asset_definitions=context.asset_definitions,
                           evidence_authority=context.evidence_authority)

    def _shapes(self, name, arguments):
        """Basic shapes (docs/sage-basic-shapes-plan.md, BS3-BS4): one model into the shared library with its
        picture, or a planned package of them for preview_planned_design that keeps clear of what is in the way."""
        from copy import deepcopy
        from ai_inspector.facility_layout import sage_shapes
        from ai_inspector.facility_layout.errors import FacilityLayoutError
        from .facility_tools import read_bound_layout
        register = getattr(self.runtime, "author_shape", None)
        if register is None:
            raise PilotError("authored_assets_unavailable",
                             "Basic-shape models need the app's private asset library; it is off here.", 409)

        def make(family, parameters):
            try:
                return register(family, parameters)
            except FacilityLayoutError as error:
                raise PilotError(error.code, error.message, 409 if error.status_code == 409 else 422) from None

        try:
            if name == sage_shapes.AUTHOR_TOOL:
                result = sage_shapes.author(make, arguments)
                self.last_image = result.pop("_image")
                return dict(result, identity=deepcopy(self.reference), savedLayoutOnly=True, readOnly=False)
            saved = read_bound_layout(self.runtime, self.principal, self.reference)
            obstacles = self._obstacles(saved["layout"])     # the roof frame reads only the floor elevation
            result = sage_shapes.plan(name, saved["layout"], arguments, revision=self.reference["revision"],
                                      author=make, obstacles=obstacles)
        except ValueError as exc:
            raise PilotError("shape_plan_refused", str(exc), 422) from exc
        image = result.pop("_image", None)
        if image is not None:
            self.last_image = image
        package = result.pop("operations")
        package_id = f"{sage_shapes.PREFIXES[name]}-{len(self.packages) + 1}"
        self.packages[package_id] = package
        result["package"] = {"packageId": package_id, "operations": len(package)}
        result["staging"] = ("Stage it unchanged with preview_planned_design and this packageId: one review. "
                             "Describe it from this summary; never rewrite its positions.")
        return dict(result, identity=deepcopy(self.reference), savedLayoutOnly=True, readOnly=True)

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
