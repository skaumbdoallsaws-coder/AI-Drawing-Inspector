"""Per-occurrence material overrides bound to an asset's exact visual revision.

Each override targets one part (mesh primitive) of a placement's model. Two key
forms exist:

* ``mN-sN``: the renderer's mesh traversal order. Older layouts use it; it is
  only meaningful for the representation it was authored on.
* ``p:<node path>#<primitive>``: the glTF node names from the scene root, with
  ``~k`` marking the k-th sibling of a repeated name and ``@n`` an unnamed node.
  Names survive re-export and reordering far better than traversal order, so new
  edits use this form.

An override either sets a plain finish (color, roughness, metalness) or applies a
library/custom appearance with optional per-part adjustments.
"""
from collections.abc import Mapping
import math
import re

LEGACY_KEY = re.compile(r"m[0-9]{1,6}-s[0-9]{1,4}")
_SEGMENT = r"(?:[A-Za-z0-9._%-]+(?:~[0-9]{1,4})?|@[0-9]{1,6})"
PATH_KEY = re.compile(r"p:" + _SEGMENT + r"(?:/" + _SEGMENT + r"){0,127}#[0-9]{1,4}")
PLAIN_FIELDS = {"key", "color", "roughness", "metalness"}


def is_part_key(value) -> bool:
    return isinstance(value, str) and len(value) <= 512 and bool(
        LEGACY_KEY.fullmatch(value) or PATH_KEY.fullmatch(value))


def normalize_component_materials(value, layout=None):
    if not isinstance(value, Mapping) or set(value) != {"representation", "overrides"}:
        raise ValueError("Unsupported component materials")
    if value["representation"] not in ("overview", "detail"):
        raise ValueError("Component materials require a loaded CAD visual")
    overrides = value["overrides"]
    if not isinstance(overrides, list) or not 1 <= len(overrides) <= 512:
        raise ValueError("Choose 1 to 512 component materials")
    result, keys = [], set()
    for item in overrides:
        if not isinstance(item, Mapping) or "key" not in item:
            raise ValueError("Unsupported component finish")
        key = item["key"]
        if not is_part_key(key) or key in keys:
            raise ValueError("Each component finish needs a unique part key")
        keys.add(key)
        if "appearanceId" in item:
            from .appearance_library import normalize_appearance
            appearance = normalize_appearance({k: v for k, v in item.items() if k != "key"}, layout)
            result.append(dict({"key": key}, **appearance))
            continue
        if set(item) != PLAIN_FIELDS:
            raise ValueError("Unsupported component finish")
        if not isinstance(item["color"], str) or not re.fullmatch(r"#[a-fA-F0-9]{6}", item["color"]):
            raise ValueError("Choose a six-digit component color")
        for name in ("roughness", "metalness"):
            n = item[name]
            if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or not 0 <= n <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        result.append(dict(item, color=item["color"].lower()))
    return dict(representation=value["representation"], overrides=sorted(result, key=lambda item: item["key"]))
