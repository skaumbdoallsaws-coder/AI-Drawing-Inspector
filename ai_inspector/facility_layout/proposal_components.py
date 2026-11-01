"""Bind assisted component finishes to exact catalog visual bytes and real slots."""
from collections.abc import Mapping
import re

from .component_materials import normalize_component_materials
from .errors import FacilityConflictError, FacilityLayoutError, FacilityValidationError


def validate_proposal_components(service, principal, site_id, layout_id, base_revision, operations):
    for op in operations:
        placement = op.get("placement")
        # A rack row's template is a placement too: its copies would carry the finish past the proof below.
        if (op.get("op") in ("place_asset", "place_asset_array") and isinstance(placement, Mapping)
                and placement.get("componentMaterials") is not None):
            raise FacilityValidationError("component_target_requires_saved_visual",
                "Place the asset without componentMaterials and put set_component_materials for it after its "
                "place_asset, with the keys and visualSha256 from inspect_facility_components (its assetId).")
    edits = [op for op in operations if op.get("op") == "set_component_materials" and op.get("materials") is not None]
    if not edits:
        return []
    current = service.get_layout(principal, site_id, layout_id)
    if current["revision"] != base_revision:
        raise FacilityConflictError("revision_conflict", "The saved layout changed before component validation.")
    reference = {"siteId": site_id, "layoutId": layout_id, "revision": base_revision}
    placements = {row["placementId"]: row for row in current["layout"]["placements"]}
    replaced = {op.get("placementId") for op in operations if op.get("op") in {"replace_asset", "delete_placement"}}
    # A placement this batch makes takes its part finishes in the same preview, after its place_asset, proven
    # against its asset's catalog visual (inspect_facility_components with the assetId): the same bytes and keys.
    # Its id as the engine takes it (_op_place_asset): one it would make up instead cannot be named here.
    created = {}
    for position, op in enumerate(operations):
        new = op.get("placement") if op.get("op") == "place_asset" else None
        if not isinstance(new, Mapping) or not all(isinstance(new.get(key), str)
                                                   for key in ("assetId", "assetDefinitionRevision")):
            continue
        requested = new.get("placementId", op.get("placementId"))
        if isinstance(requested, str):
            created.setdefault(requested, (position, new))
    proofs = []
    # A visual's bytes and part keys follow from its asset revision and representation alone, so each distinct
    # visual is read once however many placements share it (a planned site paints 300+ copies of three models).
    visuals = {}
    for position, op in enumerate(operations):
        if op.get("op") != "set_component_materials" or op.get("materials") is None:
            continue
        expected_hash = op.get("visualSha256")
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_hash):
            raise FacilityValidationError("component_visual_proof_required",
                "Inspect the saved placement's components and supply its exact visualSha256 before previewing material edits.")
        identifier = op.get("placementId")
        placement, saved = placements.get(identifier), True
        if placement is None and identifier in created and created[identifier][0] < position:
            placement, saved = created[identifier][1], False
        if placement is None or identifier in replaced:
            raise FacilityValidationError("component_target_requires_saved_visual",
                "Give part finishes to a saved placement, or to one placed earlier in this preview (inspect its "
                "assetId); save and inspect a replaced placement first.")
        try:
            materials = normalize_component_materials(op["materials"])
        except ValueError as exc:
            raise FacilityValidationError("invalid_component_materials", str(exc)) from exc
        visual = (placement["assetId"], placement["assetDefinitionRevision"], materials["representation"])
        if visual not in visuals:
            resolver = service.component_inventory_resolver
            if resolver is None:
                raise FacilityValidationError("component_inventory_unavailable", "This host cannot verify component visual authority.")
            try:
                inventory = (resolver(principal, reference, identifier, materials["representation"]) if saved else
                             resolver(principal, reference, None, materials["representation"], asset=visual[:2]))
            except FacilityLayoutError:
                raise
            except Exception as exc:
                raise FacilityValidationError("component_inventory_unavailable",
                    "The saved visual could not be verified. Inspect its components again before proposing changes.") from exc
            if (inventory.get("identity") != reference or inventory.get("placementId") != (identifier if saved else None)
                    or inventory.get("assetId") != placement["assetId"]
                    or inventory.get("assetDefinitionRevision") != placement["assetDefinitionRevision"]
                    or inventory.get("representation") != materials["representation"]):
                raise FacilityConflictError("component_visual_revision_conflict", "The component visual binding has changed. Inspect it again.")
            visuals[visual] = inventory
        inventory = visuals[visual]
        if inventory.get("visualSha256") != expected_hash:
            raise FacilityConflictError("component_visual_revision_conflict",
                "The visual bytes have changed since component inspection. Inspect the current visual and preview again.")
        available = {slot["key"] for slot in inventory["slots"]}
        if any(row["key"] not in available for row in materials["overrides"]):
            raise FacilityValidationError("component_material_key_unavailable",
                "A requested component key is absent from this exact visual. Use keys returned by component inspection.")
        proofs.append({"placementId": identifier, "assetId": placement["assetId"],
            "assetDefinitionRevision": placement["assetDefinitionRevision"],
            "representation": materials["representation"], "visualSha256": expected_hash})
    return proofs
