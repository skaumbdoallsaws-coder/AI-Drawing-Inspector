"""Per-occurrence material overrides bound to an asset's exact visual revision."""
from collections.abc import Mapping
import math
import re


def normalize_component_materials(value):
    if not isinstance(value, Mapping) or set(value) != {"representation", "overrides"}:
        raise ValueError("Unsupported component materials")
    if value["representation"] not in ("overview", "detail"):
        raise ValueError("Component materials require a loaded CAD visual")
    overrides = value["overrides"]
    if not isinstance(overrides, list) or not 1 <= len(overrides) <= 512:
        raise ValueError("Choose 1 to 512 component materials")
    result, keys = [], set()
    for item in overrides:
        if not isinstance(item, Mapping) or set(item) != {"key", "color", "roughness", "metalness"}:
            raise ValueError("Unsupported component finish")
        key = item["key"]
        if not isinstance(key, str) or not re.fullmatch(r"m[0-9]{1,6}-s[0-9]{1,4}", key) or key in keys:
            raise ValueError("Each component finish needs a unique mesh/material key")
        keys.add(key)
        if not isinstance(item["color"], str) or not re.fullmatch(r"#[a-fA-F0-9]{6}", item["color"]):
            raise ValueError("Choose a six-digit component color")
        for name in ("roughness", "metalness"):
            n = item[name]
            if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or not 0 <= n <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        result.append(dict(item, color=item["color"].lower()))
    return dict(representation=value["representation"], overrides=sorted(result, key=lambda item: item["key"]))
