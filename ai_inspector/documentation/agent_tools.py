"""The Documentation workspace's browser workflows, as tools: their names, descriptions and argument schemas.

The browser runs them (static/index.html executors). The older chat runtime offers them to Sage directly
(server.AGENT_TOOL_SPECS); Sage on Codex asks for them through run_documentation_workflow
(codex_runtime/documentation_tools.py), which checks the arguments against these same schemas.
"""

PARTS_MANUAL_PROPOSAL = {
    "name": "propose_parts_manual_structure",
    "description": (
        "Open the Illustrated Parts Manual workspace and compile one read-only, "
        "evidence-backed manual structure proposal for the currently loaded "
        "assembly. Use only when the user asks to suggest, plan, or generate "
        "manual groups/sections. This tool never approves groups, changes the "
        "CAD assembly, captures pages, generates a PDF, or commits anything."
    ),
    "args": {},
    "input_schema": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}
OPERATIONS_MANUAL_DRAFT = {
    "name": "generate_operations_manual_draft",
    "description": (
        "Open the shared Documentation workspace and generate the evidence-backed "
        "Operations and Maintenance Manual for the currently loaded assembly. "
        "Use when the user explicitly asks to build, create, or generate an operations "
        "manual. The live application reveals each 16:9 landscape page progressively, captures "
        "every requested technical figure in Hidden Lines Removed style during that fresh "
        "build, and stops with a review-ready document in the workspace. Its terminal receipt includes the "
        "registered evidence sources, public source links, claim counts, and original PDF "
        "source-page locators used by the "
        "compiled manual. Publishing review PDF and DOCX artifacts is a separate explicit tool. This tool "
        "never approves safety content, resolves evidence conflicts, changes source CAD, "
        "or publishes any artifact. Its successful terminal stage is review_ready."
    ),
    "args": {},
    "input_schema": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}
OPERATIONS_MANUAL_PUBLICATION = {
    "name": "publish_operations_manual",
    "description": (
        "Publish revision-bound Operations and Maintenance Manual review artifacts for "
        "the currently loaded assembly. Use only when the user explicitly asks to publish "
        "or export the operations manual, PDF, or editable DOCX. The live application opens "
        "the correct Documentation workflow, builds a review baseline when needed, freshly "
        "recaptures every required technical figure for this run, validates the resulting "
        "document revision, and exports both review PDF and DOCX artifacts. This is not a "
        "controlled release and never changes source CAD. Its receipt preserves claim-level "
        "source-page locators for every cited PDF."
    ),
    "args": {},
    "input_schema": {
        "type": "object",
        "properties": {
            "open_pdf": {
                "type": "boolean",
                "description": "Open the exported review PDF after validation.",
            },
            "open_docx": {
                "type": "boolean",
                "description": "Open the exported editable DOCX after validation.",
            },
        },
        "required": ["open_pdf", "open_docx"],
        "additionalProperties": False,
    },
}
SPECIFICATION_SHEET_DRAFT = {
    "name": "generate_specification_sheet_draft",
    "description": (
        "Open the shared Documentation workspace and generate the evidence-backed "
        "one-page product Specification Sheet for the currently loaded assembly. "
        "Use when the user explicitly asks to build, create, or generate a specification "
        "sheet, spec sheet, or product data sheet without asking to publish it. The live "
        "application starts blank, reveals the page progressively, and freshly captures "
        "the current assembled CAD product view before returning review_ready. This tool "
        "never invents product values, changes source CAD, or publishes an artifact."
    ),
    "args": {},
    "input_schema": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}
SPECIFICATION_SHEET_PUBLICATION = {
    "name": "publish_specification_sheet",
    "description": (
        "Publish the revision-bound one-page product Specification Sheet review PDF and "
        "editable DOCX for "
        "the currently loaded assembly. Use only when the user explicitly asks to publish "
        "or export the specification sheet, spec sheet, product data sheet, PDF, or DOCX. "
        "The live application opens the correct Documentation workflow, generates a "
        "review baseline when needed, freshly recaptures the assembled CAD product image "
        "for this run, validates the current document revision, and exports both artifacts. "
        "This is not a controlled release and never changes source CAD."
    ),
    "args": {},
    "input_schema": {
        "type": "object",
        "properties": {
            "open_pdf": {
                "type": "boolean",
                "description": "Open the exported review PDF after validation.",
            },
            "open_docx": {
                "type": "boolean",
                "description": "Open the exported editable DOCX after validation.",
            },
        },
        "required": ["open_pdf", "open_docx"],
        "additionalProperties": False,
    },
}
WORK_INSTRUCTIONS_DRAFT = {
    "name": "generate_work_instructions_draft",
    "description": (
        "Open the shared Documentation workspace and generate operator-facing "
        "Assembly Work Instructions for the loaded assembly. Use when the user "
        "explicitly asks to build, create, or generate work instructions or assembly "
        "instructions without asking for a PDF. The prototype treats the registered "
        "planning-ready process package as an assumed baseline, reveals every 16:9 "
        "page progressively, and freshly captures every required CAD figure. It never "
        "represents that assumption as manufacturing approval or controlled release."
    ),
    "args": {},
    "input_schema": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}
WORK_INSTRUCTIONS_PUBLICATION = {
    "name": "publish_work_instructions",
    "description": (
        "Export the revision-bound Assembly Work Instructions prototype review PDF and "
        "editable DOCX "
        "for the loaded assembly. Use only when the user explicitly asks to export "
        "or publish the work instructions, PDF, or DOCX. The live application builds "
        "the baseline when needed, freshly recaptures every required CAD figure for "
        "the current revision, validates the captures, and exports both artifacts. This "
        "is not manufacturing approval or controlled release."
    ),
    "args": {},
    "input_schema": {
        "type": "object",
        "properties": {
            "open_pdf": {
                "type": "boolean",
                "description": "Open the exported prototype review PDF.",
            },
            "open_docx": {
                "type": "boolean",
                "description": "Open the exported editable DOCX.",
            },
        },
        "required": ["open_pdf", "open_docx"],
        "additionalProperties": False,
    },
}
PARTS_MANUAL_DRAFT = {
    "name": "generate_parts_manual_draft",
    "description": (
        "Open the shared Documentation workspace and generate an illustrated parts manual "
        "for review without publishing a PDF. Use when the user explicitly asks to build, "
        "create, generate, draft, or prepare a parts manual but does not ask to publish or "
        "export it. The application creates or reuses the validated semantic hierarchy, "
        "reveals every page progressively, and freshly recaptures every required Hidden "
        "Lines Removed figure before returning review_ready. This is different from the "
        "read-only structure proposal tool and never changes source CAD geometry."
    ),
    "args": {},
    "input_schema": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}
PARTS_MANUAL_PUBLICATION = {
    "name": "generate_and_publish_parts_manual",
    "description": (
        "Run the complete, publication-gated illustrated-parts-manual workflow "
        "for the currently loaded assembly. Use only when the current user turn "
        "explicitly requests PDF publication or the complete end-to-end manual "
        "result. Deterministic application code preserves an existing publishable "
        "manual structure, optionally approves only complete trusted proposal "
        "candidates, compiles the Documentation scene, captures every required "
        "Hidden Lines Removed figure, validates revision-bound plan/render/callout "
        "evidence, and publishes the PDF. It never changes source CAD geometry and "
        "never replaces an existing publishable manual hierarchy. A successful "
        "stage=published result with a PDF artifact is required before claiming "
        "publication."
    ),
    "args": {},
    "input_schema": {
        "type": "object",
        "properties": {
            "approval_mode": {
                "type": "string",
                "enum": [
                    "use_approved_structure",
                    "approve_trusted_ready_candidates",
                ],
                "description": (
                    "Use the existing publishable structure, or allow the runtime "
                    "to approve a complete zero-conflict proposal backed only by "
                    "trusted CAD hierarchy or process-map evidence."
                ),
            },
            "layout_mode": {
                "type": "string",
                "enum": [
                    "preserve_current",
                    "generate_baseline_if_missing",
                ],
                "description": (
                    "Preserve all current Documentation composition, optionally "
                    "allowing deterministic baseline presentation where none exists."
                ),
            },
            "open_pdf": {
                "type": "boolean",
                "description": "Open the published PDF in InspectorPro after validation.",
            },
        },
        "required": ["approval_mode", "layout_mode", "open_pdf"],
        "additionalProperties": False,
    },
}
PARTS_MANUAL_DOCUMENTATION = {
    "name": "edit_parts_manual_composition",
    "description": (
        "Edit the presentation of an existing illustrated-parts-manual figure. "
        "Use only when the user explicitly asks to move, rotate, align, distribute, "
        "resize, adjust explosion spacing, change the publication view, or reset a figure or page, "
        "semantic manual group, exact component instance, item balloon, or leader, "
        "to add/remove/clear/restore page callouts, change a leader endpoint, "
        "snap a leader anchor, or explicitly asks "
        "to undo/redo a documentation edit. This changes documentation overrides "
        "only: it never changes CAD geometry, assembly transforms, manual-group "
        "membership, or source assembly identity. Documentation BOM rows and quantities "
        "are deterministically derived from the selected CAD definitions. Human and Sage edits use "
        "the same revision-bound command and undo/redo system."
    ),
    "args": {},
    "input_schema": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": [
                    "translate",
                    "rotate",
                    "align",
                    "distribute",
                    "resize",
                    "adjust_explode",
                    "set_view",
                    "set_anchor",
                    "set_leader_style",
                    "auto_route",
                    "set_end_condition",
                    "set_repeated_strategy",
                    "clear_callouts",
                    "add_callout",
                    "remove_callout",
                    "restore_callouts",
                    "reset",
                    "reset_page",
                    "undo",
                    "redo",
                ],
            },
            "page": {
                "type": "string",
                "description": "Figure number, page ID, or exact figure title.",
            },
            "target_type": {
                "type": "string",
                "enum": [
                    "figure",
                    "manual_group",
                    "occurrence",
                    "balloon",
                    "leader",
                    "page_element",
                ],
            },
            "target": {
                "type": "string",
                "description": "Exact visible group/component name or stable target ID.",
            },
            "targets": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 64,
                "description": "Exact visible target names or stable IDs for align/distribute.",
            },
            "direction": {
                "type": "string",
                "enum": ["left", "right", "up", "down"],
            },
            "amount": {
                "type": "number",
                "minimum": 0.001,
                "maximum": 10.0,
                "description": (
                    "Movement in model units for figures/groups/components, or normalized "
                    "page fraction for balloons/leaders (0.05 means 5%); defaults to 0.05."
                ),
            },
            "axis": {
                "type": "string",
                "enum": ["x", "y", "z"],
                "description": "Presentation rotation axis; defaults to y.",
            },
            "degrees": {
                "type": "number",
                "minimum": -180.0,
                "maximum": 180.0,
                "description": "Signed presentation rotation in degrees.",
            },
            "alignment": {
                "type": "string",
                "enum": ["left", "center", "right", "top", "middle", "bottom"],
            },
            "distribution": {
                "type": "string",
                "enum": ["horizontal", "vertical"],
            },
            "width_delta": {
                "type": "number",
                "minimum": -1.0,
                "maximum": 1.0,
                "description": "Publication-width change as a page fraction.",
            },
            "height_delta": {
                "type": "number",
                "minimum": -1.0,
                "maximum": 1.0,
                "description": "Publication-height change as a page fraction.",
            },
            "view": {
                "type": "string",
                "enum": ["isometric", "front", "top", "right"],
                "description": "Deterministic publication camera for the selected figure.",
            },
            "explode_delta": {
                "type": "number",
                "minimum": -1.0,
                "maximum": 1.0,
                "description": "Signed change to exploded-view spacing; typical steps are +/-0.15.",
            },
            "anchor_side": {
                "type": "string",
                "enum": ["center", "left", "right", "top", "bottom"],
                "description": "Projected selection-box center or visible target edge for set_anchor.",
            },
            "leader_style": {
                "type": "string",
                "enum": ["auto", "straight", "orthogonal"],
                "description": (
                    "Route style for set_leader_style. Auto restores deterministic "
                    "straight-first routing; straight forces a direct free-angle leader; "
                    "orthogonal keeps a manually editable elbow route."
                ),
            },
            "end_condition": {
                "type": "string",
                "enum": ["arrow", "dot", "none"],
                "description": "Target-end marker for set_end_condition on a leader.",
            },
            "repeated_part_strategy": {
                "type": "string",
                "enum": ["representative_with_count", "branched"],
                "description": (
                    "Repeated-part callout strategy for set_repeated_strategy on a "
                    "leader. Generation always defaults to representative_with_count "
                    "(one balloon, one leader, an nX badge); request branched only "
                    "when the user explicitly asks for a leader per occurrence."
                ),
            },
        },
        "required": ["operation"],
        "additionalProperties": False,
    },
}

# Not a document workflow: it opens a machine from the industrial asset library as the loaded assembly
# (docs/specification-sheet-slots-plan.md, SS5).
OPEN_LIBRARY_MACHINE = {
    "name": "open_library_machine",
    "description": (
        "Open a machine from the industrial asset library (a lathe, a forklift, a robot ...) as the loaded "
        "assembly: one part per body of its model, with only the Specification Sheet offered for it. The app "
        "opens it in the Documentation workspace on its specification sheet, or in the Assembly tab's 3D view "
        "(view: assembly)."
    ),
    "args": {"asset_id": "the library asset id, asset-...", "view": "assembly or documentation (the default)"},
    "input_schema": {
        "type": "object",
        "properties": {"asset_id": {"type": "string", "pattern": "^asset-[a-z0-9][a-z0-9-]{0,118}$"},
                       "view": {"type": "string", "enum": ["assembly", "documentation"]}},
        "required": ["asset_id"],
        "additionalProperties": False,
    },
}


DOCUMENTATION_AGENT_TOOL_SPECS = {spec["name"]: spec for spec in (
    PARTS_MANUAL_PROPOSAL,
    OPERATIONS_MANUAL_DRAFT,
    OPERATIONS_MANUAL_PUBLICATION,
    SPECIFICATION_SHEET_DRAFT,
    SPECIFICATION_SHEET_PUBLICATION,
    WORK_INSTRUCTIONS_DRAFT,
    WORK_INSTRUCTIONS_PUBLICATION,
    PARTS_MANUAL_DRAFT,
    PARTS_MANUAL_PUBLICATION,
    PARTS_MANUAL_DOCUMENTATION,
)}
