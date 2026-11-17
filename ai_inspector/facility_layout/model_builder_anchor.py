"""Resolve a built asset's persisted include anchor for replacement previews and applies."""
from copy import deepcopy
from hashlib import sha256
import math

from .errors import FacilityLayoutError
from ..industrial_assets import model_builder_bundle as bundles
from ..industrial_assets.model_builder.errors import ModelBuildError, parse_json
from ..industrial_assets.model_builder.job_io import read_bytes
from ..industrial_assets.model_builder_host import IncludeCatalog


def _fail(code, message, *, details=None):
    raise FacilityLayoutError(code, message, status_code=409, details=details)


def _installed_bundle(host, asset_id, revision):
    host.list_assets()  # Rebind an installation published by another host before consulting its disk bytes.
    catalog = IncludeCatalog(host._component_visual_root)
    try:
        row, raw = catalog._record(asset_id, "$.assetId")
        if (row.get("assetDefinitionRevision") != revision
                or not asset_id.startswith("asset-built-") or not row.get("buildProvenance")):
            _fail("anchor_include_mismatch", "Choose the current registered built asset revision.")
        directory = host._component_visual_root / bundles.FOLDER / asset_id
        names = ("model.glb", "thumbnail.webp", "recipe.json", "bundle.json")
        if raw.get("attribution") is not None:
            names += ("CREDITS.txt",)
        files = {name: read_bytes(directory, name, bundles.FILES[name]) for name in names}
        bundles.validate_bundle(raw, files)
        manifest = parse_json(files["bundle.json"], bundles.FILES["bundle.json"])
        if manifest["files"]["model.glb"]["sha256"] != sha256(files["model.glb"]).hexdigest():
            raise ValueError("Built model bytes changed")
        return manifest
    except FacilityLayoutError:
        raise
    except (ModelBuildError, OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
        _fail("anchor_include_mismatch", "The installed built bundle no longer matches its catalog binding.")


def _old_artifact(host, placement, include):
    try:
        item = IncludeCatalog(host._component_visual_root).resolve(
            placement["assetId"], revision=placement["assetDefinitionRevision"],
            artifact_sha256=include["artifactSha256"], for_build=False)
        return item["payload"]
    except ModelBuildError as error:
        if error.code == "budget_exceeded":
            _fail("anchor_include_over_limit", "This host exceeds the include budget. Build a standalone hung tag "
                  "and propose it in front of the host.")
        _fail("anchor_include_mismatch", "The placed host's current catalog artifact or revision differs from "
              "the persisted include.")


def _pose(old, frame):
    transform = old.get("transform") or {}
    quaternion = transform.get("quaternion") or {}
    scale = transform.get("scale", 1)
    try:
        if (type(scale) not in (int, float) or abs(scale-1) > 1e-9
                or abs(quaternion["x"]) > 1e-7 or abs(quaternion["z"]) > 1e-7):
            raise ValueError("not a yaw-only unscaled placement")
        old_yaw = 2 * math.atan2(quaternion["y"], quaternion["w"])
        yaw = old_yaw + math.radians(frame["yaw"])
        c, s = math.cos(yaw), math.sin(yaw)
        fx, fy, fz = frame["translation"]
        position = transform["position"]
        return {"position": {"x": position["x"] + c*fx - s*fz,
                             "y": position["y"] - fy,
                             "z": position["z"] - s*fx - c*fz},
                "quaternion": {"w": math.cos(yaw/2), "x": 0, "y": math.sin(yaw/2), "z": 0},
                "scale": 1}
    except (KeyError, TypeError, ValueError, OverflowError):
        _fail("anchor_include_pose_invalid", "The placed host must be unscaled and yaw-only.")


def _finishes(host, principal, reference, placement, include, artifact):
    config = placement.get("componentMaterials")
    if not config:
        return None, [], []
    from ai_inspector.codex_runtime.component_inventory import material_slots
    from ai_inspector.codex_runtime.policy import PilotError
    from ai_inspector.industrial_assets.artifacts import _parse_glb_chunks
    try:
        representation = config["representation"]
        inventory = host._resolve_component_inventory(principal, reference, placement["placementId"], representation)
        document, _, _ = _parse_glb_chunks(artifact)
        artifact_keys = {slot["key"] for slot in material_slots(document)}
        source_slots = inventory["slots"]
        source_keys = {slot["key"] for slot in source_slots}
    except (PilotError, ValueError, KeyError, TypeError, IndexError, AttributeError):
        _fail("anchor_finish_unavailable", "The placed host's recorded part representation cannot be inspected.")
    # Stable paths can survive a lighter visual; an unrelated overview hierarchy cannot.
    hierarchy_changed = source_keys != artifact_keys
    by_key = {key: slot["key"] for slot in source_slots for key in (slot["key"], slot["legacyKey"])}
    mapped, carried, dropped = {}, [], []
    for override in config["overrides"]:
        old_key = override["key"]
        source_key = by_key.get(old_key)
        target = None if hierarchy_changed else include["partMap"].get(source_key)
        if target is None:
            dropped.append(old_key)
            continue
        finish = {key: deepcopy(value) for key, value in override.items() if key != "key"}
        if target in mapped and mapped[target] != finish:
            _fail("anchor_finish_conflict", "Two old parts map to one new part with different finishes.",
                  details={"partKey": target})
        mapped[target] = finish
        carried.append({"from": old_key, "to": target})
    result = ({"representation": "overview", "overrides": [{"key": key, **finish}
              for key, finish in sorted(mapped.items())]} if mapped else None)
    return result, carried, dropped


def resolve_anchor_replacement(host, principal, reference, layout, operation):
    """Return an operation with server-only pose/finishes and a bounded, user-visible loss report."""
    include_id = operation.get("anchorInclude")
    if not isinstance(include_id, str) or not 0 < len(include_id) <= 80:
        _fail("anchor_include_invalid", "Choose one include id from the registered built asset.")
    placement = next((item for item in layout.get("placements", [])
                      if item.get("placementId") == operation.get("placementId")), None)
    if placement is None:
        _fail("operation_target_not_found", "The placement to replace is unavailable.")
    manifest = _installed_bundle(host, operation.get("assetId"), operation.get("assetDefinitionRevision"))
    include = next((item for item in manifest["includes"] if item["includeId"] == include_id), None)
    if include is None:
        _fail("anchor_include_missing", "This built asset does not contain the requested include.")
    if not include["anchorable"] or include["frame"] is None:
        _fail("anchor_include_pose_invalid", "This include has no single yaw-only anchor frame.")
    if (placement["assetId"] != include["assetId"]
            or placement["assetDefinitionRevision"] != include["revision"]):
        _fail("anchor_include_mismatch", "The placed host identity differs from the built asset's include.")
    artifact = _old_artifact(host, placement, include)
    transform = _pose(placement, include["frame"])
    materials, carried, dropped = _finishes(host, principal, reference, placement, include, artifact)
    decals = [row["decalId"] for row in layout.get("extensions", {}).get("facilityEquipmentDecals", {}).get("decals", [])
              if row.get("placementId") == placement["placementId"]]
    resolved = dict(operation)
    resolved["_anchorResolved"] = {"transform": transform, "componentMaterials": materials}
    report = {"anchorInclude": include_id, "carriedFinishes": carried, "droppedFinishes": dropped,
              "droppedDecals": decals}
    return resolved, report
