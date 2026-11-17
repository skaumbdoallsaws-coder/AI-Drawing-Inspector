"""Worker-only include decoding, after bounded scalar preflight."""
from copy import deepcopy
from dataclasses import replace
import math

import numpy as np

from .errors import ModelBuildError, require
from .imports import module
from .include_contract import entries, planned_parts
from .schema import PATTERNS
from .shapes import Mesh


def load_models(recipe, sources, allowed_appearance_ids):
    loaded = {}
    limits = replace(module("limits").DEFAULT_LIMITS, upload_bytes=8*1024*1024,
                     triangles=60000, primitives=400, vertices=1_000_000,
                     image_pixels=16_000_000, total_image_pixels=16_000_000)
    for entry, path, ancestors in entries(recipe):
        item = sources[entry["id"]]
        try:
            model = module("reader").read_model(item["payload"], limits=limits,
                                                 texture_max_px=2048, extended_materials=True)
        except module("errors").ModelImportError as error:
            raise ModelBuildError("include_invalid", path, "Include reader refused " + error.code) from None
        planned = planned_parts(entry, item["info"], path)
        by_key = {part.key: part for part in model.parts}
        require(set(by_key) == {p["importKey"] for p in planned}, path,
                "Reader and include inventory disagree", "include_invalid")
        materials = {}
        for plan in planned:
            part = by_key[plan["importKey"]]
            require(len(part.indices) == plan["triangles"], path, "Reader triangle count changed", "include_invalid")
            if plan["replacement"] is not None:
                continue
            value = deepcopy(model.materials[part.material])
            value["name"] = plan["materialKey"]
            for key in ("texture", "emissiveTexture"):
                if value.get(key) is not None:
                    value[key] = {k: value[key][k] for k in ("image", "wrapS", "wrapT")}
            require(not (value.get("artwork") and "defaultFinish" in value), path,
                    "Printed include materials cannot carry a default finish", "print_invalid")
            if "defaultFinish" in value:
                require(value["defaultFinish"]["appearanceId"] in allowed_appearance_ids, path,
                        "Include default finish is not in the allowed appearance library", "include_invalid")
            if "finishGroup" in value:
                value["finishGroup"] = entry["id"] + ":" + value["finishGroup"]
                require(len(value["finishGroup"]) <= 120, path, "Namespaced finish group exceeds 120 characters",
                        "include_invalid")
            materials[plan["materialKey"]] = value
        anchorable = not any(any(k in group for k in PATTERNS) or group["rotate"]["x"] or group["rotate"]["z"]
                             for group in ancestors)
        loaded[entry["id"]] = {"model": model, "planned": planned, "materials": materials,
                                "record": item["manifest"], "anchorable": anchorable}
    return loaded


def components_for(entry, ancestors, path, loaded):
    from .scene import Component
    item = loaded[entry["id"]]
    matrix = np.asarray(item["record"]["sourceToCanonical"]).reshape(4, 4, order="F")
    parts = {part.key: part for part in item["model"].parts}
    result = []
    for plan in item["planned"]:
        part = parts[plan["importKey"]]
        # Only referenced vertices participate in the bounds, matching import preparation.
        used, inverse = np.unique(part.indices.reshape(-1), return_inverse=True)
        mesh = Mesh(part.positions[used].astype(float), inverse.reshape(-1, 3).astype(np.uint32),
                    None if part.uv0 is None else part.uv0[used].astype(float), False,
                    None if part.normals is None else part.normals[used].astype(float))
        try:
            mesh = mesh.transformed(matrix[:3, :3], matrix[:3, 3])
        except np.linalg.LinAlgError:
            raise ModelBuildError("include_invalid", path, "sourceToCanonical is numerically singular") from None
        result.append(Component(mesh, entry, "include", "", ancestors, path,
                                output_name=plan["outputName"], include_key=plan["key"],
                                include_material_key=plan["materialKey"],
                                include_material=item["materials"].get(plan["materialKey"]),
                                include_frame=np.eye(4), anchorable=item["anchorable"]))
    return result


def include_results(recipe, components, loaded, part_map):
    output = []
    for entry, _, _ in entries(recipe):
        item = loaded[entry["id"]]
        first = next(c for c in components if c.entry["id"] == entry["id"])
        frame = first.include_frame
        # A patterned/tilted include has no single yaw-only frame. Never invent an
        # anchor transform from its first copy or a projection of a tilted frame.
        value = ({"yaw": math.degrees(math.atan2(float(frame[0, 2]), float(frame[0, 0]))),
                  "translation": frame[:3, 3].tolist()} if first.anchorable else None)
        record = item["record"]
        output.append({"includeId": entry["id"], "assetId": entry["include"], "revision": entry["revision"],
                       "artifactSha256": record["artifactSha256"], "frame": value, "anchorable": first.anchorable,
                       "partMap": part_map[entry["id"]]})
    return output
