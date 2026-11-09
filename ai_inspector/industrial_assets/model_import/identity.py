"""Pure D6 identity, independent of paths, clocks and the future import store."""
from copy import deepcopy
from hashlib import sha256
import re
import unicodedata

from .validation import json_bytes

SEMANTIC_FIELDS = ("displayName", "category", "description", "tags", "dimensions",
                   "supportSurfaces", "footprintPolygons", "attribution")


def catalog_semantics(draft: dict) -> dict:
    recipe = draft["recipe"]
    return {"displayName": recipe["name"], "category": recipe["category"], "description": recipe["description"],
            "tags": deepcopy(recipe["tags"]), "dimensions": deepcopy(draft["dimensions"]),
            "supportSurfaces": deepcopy(draft["surfaces"]), "footprintPolygons": deepcopy(draft["footprint"]),
            "attribution": deepcopy(draft["attribution"])}


def asset_identity(draft: dict, entry: dict | None = None) -> dict:
    """Return both the short assetId and complete inputs for conflict-safe MI2 reuse."""
    semantics = catalog_semantics(draft) if entry is None else {k: deepcopy(entry[k]) for k in SEMANTIC_FIELDS}
    identity = {"engine": draft["engineVersion"], "source": draft["sourceSha256"], "recipe": deepcopy(draft["recipe"]),
                "model": draft["outputSha256"], "entry": semantics}
    digest = sha256(json_bytes(identity)).hexdigest()
    name = unicodedata.normalize("NFKD", draft["recipe"]["name"]).encode("ascii", "ignore").decode().lower()
    slug = re.sub("[^a-z0-9]+", "-", name).strip("-")[:40].rstrip("-") or "model"
    return {"assetId": f"asset-import-{slug}-{digest[:24]}", "sha256": digest, "identity": identity}
