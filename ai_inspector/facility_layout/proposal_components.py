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
                "Place and save the asset without componentMaterials, inspect its components, "
                "then use set_component_materials with the returned visualSha256.")
    edits = [op for op in operations if op.get("op") == "set_component_materials" and op.get("materials") is not None]
    if not edits:
        return []
    current = service.get_layout(principal, site_id, layout_id)
    if current["revision"] != base_revision:
        raise FacilityConflictError("revision_conflict", "The saved layout changed before component validation.")
    reference = {"siteId": site_id, "layoutId": layout_id, "revision": base_revision}
    placements = {row["placementId"]: row for row in current["layout"]["placements"]}
    replaced = {op.get("placementId") for op in operations if op.get("op") in {"replace_asset", "delete_placement"}}
    proofs = []
    # A visual's bytes and part keys follow from its asset revision and representation alone, so each distinct
    # visual is read once however many placements share it (a planned site paints 300+ copies of three models).
    visuals = {}
    for op in edits:
        expected_hash = op.get("visualSha256")
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_hash):
            raise FacilityValidationError("component_visual_proof_required",
                "Inspect the saved placement's components and supply its exact visualSha256 before previewing material edits.")
        identifier = op.get("placementId")
        placement = placements.get(identifier)
        if placement is None or identifier in replaced:
            raise FacilityValidationError("component_target_requires_saved_visual",
                "Save and inspect a new or replaced placement before proposing component finishes.")
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
                inventory = resolver(principal, reference, identifier, materials["representation"])
            except FacilityLayoutError:
                raise
            except Exception as exc:
                raise FacilityValidationError("component_inventory_unavailable",
                    "The saved visual could not be verified. Inspect its components again before proposing changes.") from exc
            if (inventory.get("identity") != reference or inventory.get("placementId") != identifier
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
