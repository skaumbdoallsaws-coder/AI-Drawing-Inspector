"""Host-only build bundle validation and assembly. Import validation stays separate."""
from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from . import primitives
from .model_builder import drafts, identity
from .model_builder.errors import json_bytes, parse_json
from .model_builder.recipe import portable_recipe, RECIPE_BYTES
from .model_builder.imports import module

FOLDER = Path("generated/industrial_assets/authored/built")
FILES = {"model.glb": 30*1024*1024, "thumbnail.webp": 64*1024, "recipe.json": RECIPE_BYTES,
         "bundle.json": 1024*1024, "CREDITS.txt": 16*1024}
FRAME = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def catalog_entry(draft):
    ident = identity.asset_identity(draft)
    return dict(identity.catalog_semantics(draft), assetId=ident["assetId"],
                artifact=(FOLDER / ident["assetId"] / "model.glb").as_posix(), sourceToCanonical=list(FRAME))


def manifest(draft, files):
    ident = identity.asset_identity(draft)
    return {"schemaVersion": 1, "kind": "build", "assetId": ident["assetId"], "identity": ident["identity"],
            "buildProvenance": deepcopy(draft["buildProvenance"]), "includes": deepcopy(draft["includes"]),
            "files": {k: {"sha256": sha256(v).hexdigest(), "bytes": len(v)} for k, v in files.items()}}


def bundle_files(source, draft_folder, draft):
    """Compare heavy installed bytes to the retained draft manifest on repeat registration."""
    from .model_builder.job_io import read_bytes
    frozen = parse_json(read_bytes(draft_folder, "manifest.json", 4096), 4096)
    files = {}
    for name in ("model.glb", "thumbnail.webp", *( ("CREDITS.txt",) if draft["attribution"] is not None else ())):
        payload = read_bytes(source, name, FILES[name])
        if frozen["files"].get(name) != {"bytes": len(payload), "sha256": sha256(payload).hexdigest()}:
            raise ValueError("Built bundle differs from its frozen draft")
        files[name] = payload
    portable, _ = portable_recipe(draft["recipe"])
    files["recipe.json"] = json_bytes(portable)
    files["bundle.json"] = json_bytes(manifest(draft, files))
    return files


def validate_bundle(entry, files):
    from ai_inspector.facility_layout.private_catalog import private_asset_spec, validate_attribution
    private_asset_spec(entry)
    expected_fields = set(identity.SEMANTIC_FIELDS) | {"assetId", "artifact", "sourceToCanonical"}
    if "attribution" in entry:
        expected_fields.add("attribution")
    if set(entry) != expected_fields or not identity.ASSET_ID.fullmatch(entry["assetId"]):
        raise ValueError("Invalid built catalog entry")
    if entry["artifact"] != (FOLDER / entry["assetId"] / "model.glb").as_posix() or entry["sourceToCanonical"] != FRAME:
        raise ValueError("Built models must use their own canonical bundle folder")
    required = set(FILES)-({"CREDITS.txt"} if "attribution" not in entry else set())
    if not isinstance(files, Mapping) or set(files) != required:
        raise ValueError("Built bundle files differ from its credit contract")
    frozen = dict(files)
    for name, payload in frozen.items():
        if not isinstance(payload, bytes) or not 0 < len(payload) <= FILES[name]:
            raise ValueError("Invalid built bundle file size")
    value = parse_json(frozen["bundle.json"], FILES["bundle.json"])
    if (type(value) is not dict or set(value) != {"schemaVersion", "kind", "assetId", "identity", "files", "buildProvenance", "includes"}
            or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1 or value["kind"] != "build"
            or value["assetId"] != entry["assetId"]):
        raise ValueError("Invalid built bundle manifest")
    expected_hashes = {name: {"sha256": sha256(data).hexdigest(), "bytes": len(data)} for name, data in frozen.items() if name != "bundle.json"}
    if value["files"] != expected_hashes:
        raise ValueError("Built bundle hashes or sizes differ")
    portable = parse_json(frozen["recipe.json"], RECIPE_BYTES)
    recipe = drafts.normalized_frozen(portable)
    if portable_recipe(recipe)[0] != portable or frozen["recipe.json"] != json_bytes(portable):
        raise ValueError("Installed recipe must be canonical and portable")
    provenance = identity.validate_provenance(entry["buildProvenance"])
    recipe["sizeBasis"]["sources"] = deepcopy(provenance["sources"])
    if identity.build_provenance(recipe, provenance["triangles"], provenance.get("derivedFrom")) != provenance or value["buildProvenance"] != provenance:
        raise ValueError("Built provenance differs from its recipe")
    dimensions = dict(entry["dimensions"], height=entry["dimensions"]["height"]-recipe["hangHeight"])
    verified = primitives.verify(frozen["model.glb"], dimensions, base_height=recipe["hangHeight"])
    if verified["triangles"] != provenance["triangles"] or verified["triangles"] > 60000:
        raise ValueError("Built triangle count differs from its provenance")
    module("pictures").validate_picture(frozen["thumbnail.webp"], "thumbnail")
    credit = entry.get("attribution")
    if credit is not None:
        credit = validate_attribution(credit)
        if credit.get("licenseClass") not in ("cc-by", "cc-by-sa") or not value["includes"]:
            raise ValueError("Built attribution must come from an allowed include")
        if frozen["CREDITS.txt"] != module("credit").credits_text(credit).encode("utf-8"):
            raise ValueError("Built credit differs from its catalog attribution")
    document = primitives.gltf_json(frozen["model.glb"])
    if document.get("asset", {}).get("generator") != identity.ENGINE_VERSION:
        raise ValueError("Built GLB has the wrong generator")
    identity.validate_includes(value["includes"], recipe, document, credit)
    draft = {"recipe": recipe, "outputSha256": expected_hashes["model.glb"]["sha256"], "includes": value["includes"],
             "catalogDimensions": entry["dimensions"], "surfaces": entry["supportSurfaces"], "footprint": entry["footprintPolygons"],
             "attribution": credit, "buildProvenance": provenance}
    if identity.catalog_semantics(draft) != {k: entry[k] for k in expected_fields-{"assetId", "artifact", "sourceToCanonical"}}:
        raise ValueError("Built catalog text differs from its recipe")
    expected = identity.asset_identity(draft, entry)
    if expected["assetId"] != entry["assetId"] or expected["identity"] != value["identity"]:
        raise ValueError("Built asset identity differs from its complete inputs")
    frozen["bundle.json"] = json_bytes(value)
    return frozen
