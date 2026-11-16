"""In-process kernel seam. Production worker task and publication arrive in MB1b/MB4."""
from copy import deepcopy
from dataclasses import dataclass

import numpy as np

from .adapt import to_model
from .budgets import MAX_MATERIALS, MAX_PRIMITIVES, MAX_TRIANGLES, estimate
from .errors import require
from .imports import module
from .lints import lint_model
from .recipe import ENGINE_VERSION, normalize_recipe, portable_recipe
from .scene import bounds, expand


@dataclass
class BuildResult:
    recipe: dict
    model: object
    glb: bytes
    dimensions: dict
    catalog_dimensions: dict
    shift: list
    part_map: dict
    lints: list
    warnings: list
    surfaces: list
    footprint: list
    components: list
    budgets: dict
    provenance: dict

    @property
    def triangles(self):
        return sum(len(part.indices) for part in self.model.parts)


def canonical_check(model, dimensions, base_height):
    """Worker-safe counterpart of primitives.verify, over the arrays being serialized."""
    low, high = module("transforms").bounds(model.parts)
    require(abs(low[1]-base_height) <= 1e-5 and abs(low[0]+high[0]) <= 1e-5
            and abs(low[2]+high[2]) <= 1e-5, "$", "Output is not in its canonical frame", "geometry_invalid")
    require(bool(np.all(low >= -15-1e-6)) and bool(np.all(high <= 15+1e-6)), "$",
            "Canonical coordinates must remain within +/-15 m", "geometry_invalid")
    for key, size in zip(("width", "height", "depth"), high-low):
        require(size > 0 and abs(size-dimensions[key]) <= 1e-5, "$.size." + key,
                "Output dimensions do not match its bounds", "geometry_invalid")


def build_model(recipe, *, allowed_categories=None, allowed_appearance_ids=()):
    normalized = normalize_recipe(recipe, allowed_categories=allowed_categories,
                                  allowed_appearance_ids=allowed_appearance_ids)
    budgets = estimate(normalized)
    components = expand(normalized)
    low, high = bounds(components)
    dimensions = dict(zip(("width", "height", "depth"), (high-low).tolist()))
    shift = np.array([-(low[0]+high[0])/2, normalized["hangHeight"]-low[1], -(low[2]+high[2])/2])
    components = [c.transformed(np.eye(3), shift) for c in components]
    model, part_map = to_model(components, normalized)
    canonical_check(model, dimensions, normalized["hangHeight"])
    count = sum(len(p.indices) for p in model.parts)
    require(count <= MAX_TRIANGLES and len(model.parts) <= MAX_PRIMITIVES, "$",
            "Output exceeds its geometry budget", "budget_exceeded")
    glb = module("writer").write_glb(model, generator=ENGINE_VERSION, grouped=True, extended_materials=True)
    # Cheap GLB JSON read, no application imports and no filesystem access.
    import json
    import struct
    document = json.loads(glb[20:20+struct.unpack_from("<I", glb, 12)[0]])
    require(len(document["materials"]) <= MAX_MATERIALS, "$.materials",
            "Emitted material count exceeds 64", "budget_exceeded")
    catalog_dimensions = dict(dimensions, height=normalized["hangHeight"] + dimensions["height"])
    shifted = deepcopy(normalized)
    for i, surface in enumerate(shifted["surfaces"]):
        surface["height"] += float(shift[1])
        surface["rect"] = [v + float(shift[0 if i % 2 == 0 else 2]) for i, v in enumerate(surface["rect"])]
        x0, z0, x1, z1 = surface["rect"]
        require(-dimensions["width"]/2-1e-7 <= x0 < x1 <= dimensions["width"]/2+1e-7
                and -dimensions["depth"]/2-1e-7 <= z0 < z1 <= dimensions["depth"]/2+1e-7
                and normalized["hangHeight"]-1e-7 <= surface["height"] <= catalog_dimensions["height"]+1e-7,
                f"$.surfaces[{i}]", "Surface must be inside the final model bounds")
    surfaces = module("footprint").support_surfaces(shifted, catalog_dimensions)
    footprint = module("footprint").footprint(model.parts, normalized["footprint"])
    lints, warnings = lint_model(components, normalized, dimensions, shift, count)
    if any(c.role == "print" for c in components):
        warnings.append("MB1a: printed faces show their background color; text and artwork arrive in MB2.")
    portable, metadata = portable_recipe(normalized)
    provenance = {"generator": ENGINE_VERSION, "hangHeight": normalized["hangHeight"],
                  "sizeBasis": portable["sizeBasis"], "sources": metadata["sources"],
                  "sitePrivate": {"references": metadata["references"]}}
    return BuildResult(normalized, model, glb, dimensions, catalog_dimensions, shift.tolist(), part_map,
                       lints, warnings, surfaces, footprint, components, budgets, provenance)
