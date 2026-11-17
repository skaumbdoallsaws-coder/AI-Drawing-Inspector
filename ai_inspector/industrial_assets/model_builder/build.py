"""In-process kernel seam shared with the limited worker; publication belongs to MB4."""
from copy import deepcopy
from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np

from .adapt import to_model
from .budgets import MAX_MATERIALS, MAX_PRIMITIVES, MAX_TRIANGLES, estimate
from .errors import ModelBuildError, require
from .imports import module
from .lints import lint_model
from .recipe import ENGINE_VERSION, normalize_recipe, portable_recipe
from .scene import bounds, expand
from .prints import print_lints, render_prints


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
    prints: dict
    includes: list
    attribution: dict | None
    include_sources: dict
    image_ids: list

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


def build_model(recipe, *, allowed_categories=None, allowed_appearance_ids=(), font_directory=None, include_sources=None):
    normalized = normalize_recipe(recipe, allowed_categories=allowed_categories,
                                  allowed_appearance_ids=allowed_appearance_ids)
    from .include_contract import entries, prepare_sources
    from .composition import load_models, include_results
    include_sources, attribution = prepare_sources(normalized, include_sources)
    budgets = estimate(normalized, include_stats={k: v["info"]["stats"] for k, v in include_sources.items()})
    loaded = load_models(normalized, include_sources, allowed_appearance_ids)
    components = expand(normalized, loaded)
    low, high = bounds(components)
    dimensions = dict(zip(("width", "height", "depth"), (high-low).tolist()))
    shift = np.array([-(low[0]+high[0])/2, normalized["hangHeight"]-low[1], -(low[2]+high[2])/2])
    components = [c.transformed(np.eye(3), shift) for c in components]
    prints = render_prints(components, font_directory=font_directory)
    model, part_map, include_maps, image_ids = to_model(components, normalized, prints, loaded)
    includes = include_results(normalized, components, loaded, include_maps)
    canonical_check(model, dimensions, normalized["hangHeight"])
    count = sum(len(p.indices) for p in model.parts)
    require(count <= MAX_TRIANGLES and len(model.parts) <= MAX_PRIMITIVES, "$",
            "Output exceeds its geometry budget", "budget_exceeded")
    try:
        glb = module("writer").write_glb(model, generator=ENGINE_VERSION, grouped=True, extended_materials=True)
        from .identity import bind_includes
        glb = bind_includes(glb, includes, attribution)
        require(len(glb) <= 30*1024*1024, "$", "Output GLB exceeds 30 MiB", "budget_exceeded")
    except module("errors").ModelImportError as error:
        code = "budget_exceeded" if error.code == "model_output_too_large" else "geometry_invalid"
        raise ModelBuildError(code, "$", "GLB writer refused " + error.code) from None
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
    # The catalog checks the footprint against these float64 dimensions to 1e-8; the float32 Part arrays can round an
    # extreme point outward by ~3e-8 (any coordinate float32 cannot hold), so take it from the float64 components.
    footprint = module("footprint").footprint([SimpleNamespace(positions=c.mesh.positions) for c in components],
                                              normalized["footprint"])
    lints, warnings = lint_model(components, normalized, dimensions, shift, count)
    lints.extend(print_lints(components, prints))
    for entry, _, _ in entries(normalized):
        if include_sources[entry["id"]]["manifest"]["hasSurfaces"]:
            lints.append({"code": "include_surfaces_dropped", "entryIds": [entry["id"]], "instances": []})
    for item in loaded.values():
        for warning in item["model"].warnings:
            if warning not in warnings and len(warnings) < 20:
                warnings.append(warning[:300])
    portable, metadata = portable_recipe(normalized)
    provenance = {"generator": ENGINE_VERSION, "hangHeight": normalized["hangHeight"],
                  "sizeBasis": portable["sizeBasis"], "sources": metadata["sources"],
                  "sitePrivate": {"references": metadata["references"]}}
    return BuildResult(normalized, model, glb, dimensions, catalog_dimensions, shift.tolist(), part_map,
                        lints, warnings, surfaces, footprint, components, budgets, provenance, prints,
                        includes, attribution, include_sources, image_ids)
