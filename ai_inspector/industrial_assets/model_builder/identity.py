"""Portable builder identity and catalog provenance; no application imports."""
from copy import deepcopy
from hashlib import sha256
import math
import re
import struct
import unicodedata
from urllib.parse import urlsplit

from .errors import json_bytes, parse_json
from .recipe import ENGINE_VERSION, portable_recipe

ASSET_ID = re.compile(r"asset-built-[a-z0-9-]{1,40}-[0-9a-f]{24}")
DERIVED_ID = re.compile(r"asset-[A-Za-z0-9._-]{1,122}")
SEMANTIC_FIELDS = ("displayName", "category", "description", "tags", "dimensions",
                   "supportSurfaces", "footprintPolygons", "buildProvenance")


def validate_provenance(value):
    if (type(value) is not dict or not {"generator", "sizeBasis", "sources", "triangles", "recipeSha256"} <= set(value)
            or set(value)-{"generator", "sizeBasis", "sources", "triangles", "recipeSha256", "derivedFrom"}
            or value["generator"] != ENGINE_VERSION):
        raise ValueError("Invalid builder provenance fields")
    basis = value["sizeBasis"]
    if (type(basis) is not dict or set(basis) != {"kind", "note"}
            or basis["kind"] not in ("user", "layout", "document", "photo", "research", "typical")
            or not isinstance(basis["note"], str) or len(basis["note"]) > 160):
        raise ValueError("Invalid builder size basis")
    if (type(value["triangles"]) is not int or not 1 <= value["triangles"] <= 60000
            or not isinstance(value["recipeSha256"], str) or not re.fullmatch("[0-9a-f]{64}", value["recipeSha256"])):
        raise ValueError("Invalid builder geometry identity")
    if "derivedFrom" in value and (not isinstance(value["derivedFrom"], str) or not DERIVED_ID.fullmatch(value["derivedFrom"])):
        raise ValueError("Invalid builder derivedFrom identity")
    if type(value["sources"]) is not list or len(value["sources"]) > 3:
        raise ValueError("Invalid builder source list")
    texts = [basis["note"]]
    for source in value["sources"]:
        if type(source) is not dict or set(source) != {"url", "title"}:
            raise ValueError("Invalid builder source")
        if (not isinstance(source["url"], str) or not 1 <= len(source["url"]) <= 2048
                or not isinstance(source["title"], str) or not 1 <= len(source["title"]) <= 160):
            raise ValueError("Invalid builder source text")
        url = urlsplit(source["url"])
        if (url.scheme != "https" or not url.hostname or url.username is not None or url.password is not None
                or "\\" in source["url"] or any(c.isspace() for c in source["url"])):
            raise ValueError("Builder sources must be HTTPS URLs without credentials")
        url.port
        texts.extend(source.values())
    if any(any(unicodedata.category(c).startswith("C") for c in text) for text in texts):
        raise ValueError("Invalid builder provenance text")
    return deepcopy(value)


def build_provenance(recipe, triangles, derived_from=None):
    portable, metadata = portable_recipe(recipe)
    value = {"generator": ENGINE_VERSION, "sizeBasis": deepcopy(portable["sizeBasis"]),
             "sources": metadata["sources"], "triangles": triangles, "recipeSha256": sha256(json_bytes(portable)).hexdigest()}
    if derived_from is not None:
        value["derivedFrom"] = derived_from
    return validate_provenance(value)


def catalog_semantics(draft):
    recipe = draft["recipe"]
    sentence = "Generic illustrative model built by Sage; size: " + recipe["sizeBasis"]["kind"]
    description = (recipe["description"].rstrip() + "\n\n" if recipe["description"].strip() else "") + sentence
    value = {"displayName": recipe["name"], "category": recipe["category"], "description": description,
             "tags": deepcopy(recipe["tags"]), "dimensions": deepcopy(draft["catalogDimensions"]),
             "supportSurfaces": deepcopy(draft["surfaces"]), "footprintPolygons": deepcopy(draft["footprint"]),
             "buildProvenance": deepcopy(draft["buildProvenance"])}
    if draft["attribution"] is not None:
        value["attribution"] = deepcopy(draft["attribution"])
    return value


def asset_identity(draft, entry=None):
    portable, _ = portable_recipe(draft["recipe"])
    semantics = catalog_semantics(draft) if entry is None else {k: deepcopy(entry[k]) for k in SEMANTIC_FIELDS}
    if entry is not None and "attribution" in entry:
        semantics["attribution"] = deepcopy(entry["attribution"])
    includes = [{"assetId": v["assetId"], "revision": v["revision"], "representation": "artifact",
                 "visualSha256": v["artifactSha256"]} for v in draft["includes"]]
    identity = {"engine": ENGINE_VERSION, "recipe": sha256(json_bytes(portable)).hexdigest(), "includes": includes,
                "model": draft["outputSha256"], "entry": semantics}
    digest = sha256(json_bytes(identity)).hexdigest()
    name = unicodedata.normalize("NFKD", portable["name"]).encode("ascii", "ignore").decode().lower()
    slug = re.sub("[^a-z0-9]+", "-", name).strip("-")[:40].rstrip("-") or "model"
    return {"assetId": f"asset-built-{slug}-{digest[:24]}", "sha256": digest, "identity": identity}


def bind_includes(payload, includes, attribution=None):
    """Bind future anchor metadata to the GLB hash already in the complete identity.

    No private reference data goes into the artifact. Import output is untouched.
    """
    if not includes:
        return payload
    size = struct.unpack_from("<I", payload, 12)[0]
    document = parse_json(payload[20:20+size], 16*1024*1024)
    document["asset"].setdefault("extras", {})["facilityBuildIncludes"] = deepcopy(includes)
    document["asset"]["extras"]["facilityBuildAttribution"] = deepcopy(attribution)
    encoded = json_bytes(document)
    encoded += b" "*(-len(encoded) % 4)
    binary = payload[20+size:]
    return struct.pack("<4sII", b"glTF", 2, 20+len(encoded)+len(binary)) + struct.pack("<I4s", len(encoded), b"JSON") + encoded + binary


def validate_includes(includes, recipe, document, attribution=None):
    from .include_contract import entries
    from .schema import PATTERNS
    wanted = entries(recipe)
    if type(includes) is not list or len(includes) != len(wanted):
        raise ValueError("Invalid persisted includes")
    bound = document.get("asset", {}).get("extras", {}).get("facilityBuildIncludes", [])
    if json_bytes(bound) != json_bytes(includes):
        raise ValueError("Include frames and maps do not match the identity-bound GLB")
    if document.get("asset", {}).get("extras", {}).get("facilityBuildAttribution") != attribution:
        raise ValueError("Include attribution does not match the identity-bound GLB")
    from .adapt_keys import output_keys
    keys = output_keys(document)
    for value, (entry, _, ancestors) in zip(includes, wanted):
        if type(value) is not dict or set(value) != {"includeId", "assetId", "revision", "artifactSha256", "frame", "anchorable", "partMap"}:
            raise ValueError("Invalid persisted include fields")
        for target, source in (("includeId", "id"), ("assetId", "include"), ("revision", "revision"), ("artifactSha256", "artifactSha256")):
            if value[target] != entry[source]:
                raise ValueError("Persisted include differs from the recipe pin")
        anchorable = not any(any(k in a for k in PATTERNS) or a["rotate"]["x"] or a["rotate"]["z"] for a in ancestors)
        if type(value["anchorable"]) is not bool or value["anchorable"] != anchorable:
            raise ValueError("Invalid include anchoring flag")
        frame = value["frame"]
        if not anchorable:
            if frame is not None:
                raise ValueError("Non-anchorable includes have no single frame")
        else:
            if type(frame) is not dict or set(frame) != {"yaw", "translation"} or type(frame["translation"]) is not list or len(frame["translation"]) != 3:
                raise ValueError("Invalid include frame")
            if any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > cap
                   for v, cap in [(frame["yaw"], 180), *((v, 100) for v in frame["translation"])]):
                raise ValueError("Invalid include frame numbers")
        mapping = value["partMap"]
        if type(mapping) is not dict or not 1 <= len(mapping) <= 400:
            raise ValueError("Invalid include part map")
        if any(not isinstance(k, str) or len(k) > 512 or not re.fullmatch(r"p:.+#[0-9]+", k)
               or not isinstance(v, str) or v not in keys for k, v in mapping.items()):
            raise ValueError("Invalid include part key")
