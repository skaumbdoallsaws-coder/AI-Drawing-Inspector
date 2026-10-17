"""Conservative, backend-owned eligibility for standing layout-edit consent."""

DIRECT_OPERATIONS = frozenset({
    "rename_layout", "add_zone", "place_asset", "move_placement", "rotate_placement",
    "set_appearance", "set_component_materials", "duplicate_placement",
    "add_floor_marking", "add_floor_path", "edit_floor_marking", "add_aisle", "add_route",
    "upsert_floor_surface", "upsert_decal", "upsert_wall_artwork",
})
MAX_DIRECT_OPERATIONS = 20
MAX_DIRECT_ENTITIES = 20


def evaluate(operations, prepared, *, undo=False):
    reason = None
    if not undo:
        if not operations or any(op.get("op") not in DIRECT_OPERATIONS for op in operations):
            reason = "This operation needs review before applying."
        elif len(operations) > MAX_DIRECT_OPERATIONS:
            reason = "This batch is large enough to require review."
        else:
            affected = set(prepared.get("affectedIds", [])) | set(prepared.get("createdIds", []))
            if len(affected) > MAX_DIRECT_ENTITIES:
                reason = "This batch affects too many objects to apply directly."
    return {"version": 1, "eligible": reason is None, "reason": reason}
