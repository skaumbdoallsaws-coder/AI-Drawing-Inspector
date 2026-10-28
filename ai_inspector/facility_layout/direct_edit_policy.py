"""Conservative, backend-owned eligibility for standing layout-edit consent."""

DIRECT_OPERATIONS = frozenset({
    "rename_layout", "add_zone", "place_asset", "move_placement", "rotate_placement",
    "set_appearance", "set_component_materials", "set_scene", "duplicate_placement",
    "add_floor_marking", "add_floor_path", "edit_floor_marking", "add_aisle", "add_route",
    "upsert_floor_surface", "upsert_decal", "upsert_wall_artwork",
    # Setting-out reference points: marks on the site that move nothing (site findings still hold a batch back).
    "upsert_site_reference", "delete_site_reference",
})
MAX_DIRECT_OPERATIONS = 20
MAX_DIRECT_ENTITIES = 20
# A build-step package comes from the server's own planner: Sage names it (preview_planned_design) but never
# writes its operations. With the user's standing consent it may apply as a whole, larger than a routine batch,
# when it validates without findings (operation_proposals.prepare); Undo reverses it like any commit.
PLANNED_OPERATIONS = DIRECT_OPERATIONS | frozenset({
    "set_plan_settings", "set_building_pose", "set_perimeter_walls", "edit_perimeter_walls", "set_ground",
    "set_site_context", "upsert_site_area", "delete_site_area", "place_asset_array", "delete_asset_array",
    "delete_placement", "delete_zone", "delete_floor_marking", "delete_route", "upsert_interior_wall",
    "delete_interior_wall",
})
MAX_PLANNED_OPERATIONS = 1000


def _reference_area(operation):
    """An outline of what is on the photo today (existing pavement, traced or measured): a reference that changes
    no design, unlike a court, drive or car park."""
    from .site_context import REFERENCE_AREA_KINDS
    area = operation.get("area") if operation.get("op") == "upsert_site_area" else None
    return isinstance(area, dict) and area.get("kind") in REFERENCE_AREA_KINDS


def evaluate(operations, prepared, *, undo=False, planned=False):
    reason = None
    if planned and not undo:
        if not operations or any(op.get("op") not in PLANNED_OPERATIONS for op in operations):
            reason = "This operation needs review before applying."
        elif len(operations) > MAX_PLANNED_OPERATIONS:
            reason = "This batch is large enough to require review."
    elif not undo:
        if not operations or any(op.get("op") not in DIRECT_OPERATIONS and not _reference_area(op) for op in operations):
            reason = "This operation needs review before applying."
        elif len(operations) > MAX_DIRECT_OPERATIONS:
            reason = "This batch is large enough to require review."
        else:
            affected = set(prepared.get("affectedIds", [])) | set(prepared.get("createdIds", []))
            if len(affected) > MAX_DIRECT_ENTITIES:
                reason = "This batch affects too many objects to apply directly."
    return {"version": 1, "eligible": reason is None, "reason": reason}
