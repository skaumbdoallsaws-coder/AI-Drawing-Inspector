"""Pre-allocation estimates. No numpy, textures or geometry expansion here."""
import math

from .errors import ModelBuildError, TRIANGLE_LIMIT, require
from .schema import PATTERNS

MAX_COMPONENTS = 3000
MAX_TRIANGLES = TRIANGLE_LIMIT
MAX_PRIMITIVES = 400
MAX_MATERIALS = 64
MAX_PRINTS = 8
MAX_PRINT_PIXELS = 4_000_000
MAX_TEXTURE_PIXELS = 16_000_000
INCLUDE_BYTES = 8 * 1024 * 1024
TOTAL_INCLUDE_BYTES = 16 * 1024 * 1024


def copies(entry):
    for key in PATTERNS:
        if key not in entry:
            continue
        pattern = entry[key]
        if key == "mirror":
            return 2
        if key == "grid":
            return math.prod(pattern["count"])
        return pattern["count"]
    return 1


def panel_pixels(entry):
    width, height = entry["size"]
    long_side = max(64, min(1024, round(max(width, height) * 2500)))
    factor = long_side / max(width, height)
    return max(1, round(width * factor)), max(1, round(height * factor))


def triangles(entry):
    shape = entry["shape"]
    if shape == "box":
        return 12
    if shape == "panel":
        return 14
    if shape == "cylinder":
        n, end = entry["segments"], entry["radiusTo"]
        total = (2 if end else 1) * n
        hollow = "hollow" in entry
        if hollow:
            total += 2 * n
        for cap, radius in (("start", entry["radius"]), ("end", end)):
            if radius and entry["caps"] in ("both", cap):
                total += (2 if hollow else 1) * n
        return total
    if shape == "tube":
        count, n = len(entry["path"]), entry["sides"]
        return 2 * n * (count if entry["closed"] else count - 1) + (0 if entry["closed"] else 2 * n)
    if shape == "lathe":
        from .recipe import lathe_profile
        points = lathe_profile(entry["profile"])
        return entry["segments"] * sum((int(a[0] > 0) + int(b[0] > 0))
                                       for a, b in zip(points, points[1:] + points[:1]))
    if shape == "torus":
        return 16 * entry["segments"]
    if shape == "sphere":
        return 528 if entry["part"] == "whole" else 288
    if shape == "extrude":
        return 4 * len(entry["profile"]) - 4
    raise AssertionError(shape)


def estimate(recipe, *, include_stats=None):
    """Stats for later MB3 are host/reader-validated, never supplied by recipe fields."""
    result = {"components": 0, "triangles": 0, "primitives": 0, "materials": 0,
              "printedPanels": 0, "printPixels": 0, "texturePixels": 0, "includes": 0, "includeBytes": 0}
    slots = set()
    material_slots = set()
    includes = include_stats or {}

    def visit(entries, multiplier, path):
        for i, entry in enumerate(entries):
            p = f"{path}[{i}]"
            count = multiplier * copies(entry)
            require(count <= MAX_COMPONENTS, p, "Pattern multiplication exceeds 3000", "budget_exceeded")
            if "group" in entry:
                visit(entry["group"], count, p + ".group")
                continue
            result["components"] += count * (2 if entry.get("shape") == "panel" else 1)
            if "include" in entry:
                result["includes"] += count
                stats = includes.get(entry["id"])
                if stats is not None:
                    require(stats["bytes"] <= INCLUDE_BYTES, p, "Include exceeds 8 MiB", "budget_exceeded")
                    result["includeBytes"] += stats["bytes"] * count
                    result["texturePixels"] += stats["texturePixels"] * count
                    result["triangles"] += stats["triangles"] * count
                    result["primitives"] += stats["primitives"] * count
                    result["materials"] += stats["materials"] * count
            else:
                result["triangles"] += triangles(entry) * count
                slot = (entry["name"], ("back:" + entry["material"] + ":" + entry["back"])
                        if entry["shape"] == "panel" else entry["material"])
                slots.add(slot)
                # Writer material identity includes the node name, even for shared recipe materials.
                material_slots.add(slot)
                if entry["shape"] == "panel":
                    slots.add((entry["name"], "print:" + entry["id"]))
                    material_slots.add((entry["name"], "print:" + entry["id"]))
                    result["printedPanels"] += count
                    result["printPixels"] += math.prod(panel_pixels(entry)) * count
            check(p)

    def check(path):
        if result["triangles"] > MAX_TRIANGLES:
            raise ModelBuildError("budget_exceeded", path, "triangles exceeds 60000",
                                  triangles=result["triangles"])
        checks = (("components", MAX_COMPONENTS), ("triangles", MAX_TRIANGLES),
                  ("printedPanels", MAX_PRINTS), ("printPixels", MAX_PRINT_PIXELS),
                  ("includes", 3), ("includeBytes", TOTAL_INCLUDE_BYTES))
        for key, maximum in checks:
            require(result[key] <= maximum, path, f"{key} exceeds {maximum}", "budget_exceeded")
        require(result["primitives"] + len(slots) <= MAX_PRIMITIVES, path,
                "Output exceeds 400 primitives", "budget_exceeded")
        require(result["materials"] + len(material_slots) <= MAX_MATERIALS, path,
                "Output exceeds 64 materials", "budget_exceeded")
        require(result["texturePixels"] + result["printPixels"] <= MAX_TEXTURE_PIXELS, path,
                "Decoded textures exceed 16 megapixels", "budget_exceeded")

    visit(recipe["entries"], 1, "$.entries")
    result["primitives"] += len(slots)
    result["materials"] += len(material_slots)
    result["texturePixels"] += result["printPixels"]
    return result
