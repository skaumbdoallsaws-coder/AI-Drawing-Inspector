"""Worker-side preparation; cached geometry plus freshly decoded source textures."""
from hashlib import sha256
from pathlib import Path

from .accessors import Accessors
from .cache import load_cache
from .containers import open_container
from .credit import attribution, changes_text, credits_text
from .footprint import footprint, support_surfaces
from .identity import asset_identity
from .job_io import bounded_read, file_digest, local_directory, regular_file
from .limits import DEFAULT_LIMITS, SUMMARY_BYTES
from .materials import read_images
from .model import Model, Part
from .recipe import MODEL_IMPORT_ENGINE_VERSION, normalize_recipe
from .prepare_protocol import DRAFT_BYTES, DRAFT_FILES, PUBLIC_FIELDS, validate_draft
from .summary import material_summary
from .transforms import bounds, transform_model
from .validation import json_bytes, parse_json, require, warn
from .writer import write_glb

PARTS_BYTES = DRAFT_FILES["parts.jsonl"]


def part_record(part: Part) -> dict:
    return {"key": part.key, "name": part.name, "triangles": len(part.indices)}


def prepare_summary(draft: dict) -> dict:
    return {key: draft[key] for key in PUBLIC_FIELDS}


def build_draft(source: Model, recipe: dict, source_payload: bytes) -> tuple[dict, bytes, Model]:
    """Trusted-test seam; production invokes it only after resource limits."""
    recipe = normalize_recipe(recipe)
    require(sha256(source_payload).hexdigest() == source.source_sha256, "model_cache_invalid")
    model = transform_model(source, recipe)
    # MI0a's thumbnails may have discarded alpha or resolution. Decode original
    # images under the same D2 budgets, using the *patched* alpha modes.
    container = open_container(source_payload, DEFAULT_LIMITS)
    accessors = Accessors(container, DEFAULT_LIMITS)
    model.images = read_images(container, accessors, model.materials, DEFAULT_LIMITS, recipe["textureMaxPx"])
    payload = write_glb(model)
    low, high = bounds(model.parts)
    dimensions = dict(zip(("width", "height", "depth"), (high - low).tolist()))
    changes = changes_text(recipe)
    if source.licence.get("conflicts"):
        warn(model.warnings, "Source attribution conflicts remain unresolved; check the source licence evidence.")
    draft = {
        "schemaVersion": 1, "engineVersion": MODEL_IMPORT_ENGINE_VERSION, "recipe": recipe,
        "sourceSha256": source.source_sha256, "outputSha256": sha256(payload).hexdigest(),
        "dimensions": dimensions, "triangles": sum(len(p.indices) for p in model.parts),
        "partsTotal": len(model.parts), "parts": [part_record(p) for p in model.parts[:64]],
        "materialsTotal": len(model.materials),
        "materials": [material_summary(m, model.images) for m in model.materials[:64]],
        "surfaces": support_surfaces(recipe, dimensions), "footprint": footprint(model.parts, recipe["footprint"]),
        "warnings": model.warnings[:20], "attribution": attribution(source.licence, recipe, changes), "changes": changes,
    }
    draft["draftId"] = "md-" + asset_identity(draft)["sha256"][:24]
    draft["nextPartsOffset"] = len(draft["parts"]) if len(draft["parts"]) < draft["partsTotal"] else None
    while len(json_bytes(prepare_summary(draft))) > SUMMARY_BYTES and len(draft["materials"]) > 1:
        draft["materials"].pop()
    while len(json_bytes(prepare_summary(draft))) > SUMMARY_BYTES and len(draft["parts"]) > 1:
        draft["parts"].pop()
        draft["nextPartsOffset"] = len(draft["parts"])
    while len(json_bytes(prepare_summary(draft))) > SUMMARY_BYTES and draft["warnings"]:
        draft["warnings"].pop()
    require(len(json_bytes(prepare_summary(draft))) <= SUMMARY_BYTES and len(json_bytes(draft)) <= DRAFT_BYTES,
            "model_output_too_large")
    return draft, payload, model


def execute_prepare(job_dir: str | Path) -> dict:
    from .worker_task import execute_inspect
    job = local_directory(job_dir)
    recipe = normalize_recipe(parse_json(bounded_read(job, "recipe.json", 32 * 1024), 32 * 1024))
    if not regular_file(job, "result.json").exists():
        execute_inspect(job)
    source = load_cache(job)
    payload = bounded_read(job, "source.bin", DEFAULT_LIMITS.upload_bytes)
    draft, output, model = build_draft(source, recipe, payload)
    validate_draft(draft)
    directory = job / "output"
    require(not directory.exists() and not directory.is_symlink(), "model_worker_failed")
    directory.mkdir()
    directory = local_directory(directory)
    for name, content in (("model.glb", output), ("draft.json", json_bytes(draft)),
                          ("CREDITS.txt", credits_text(draft["attribution"]).encode("utf-8"))):
        require(len(content) <= DRAFT_FILES[name], "model_output_too_large")
        with regular_file(directory, name).open("xb") as stream:
            stream.write(content)
    with regular_file(directory, "parts.jsonl").open("xb") as stream:
        for part in model.parts:
            stream.write(json_bytes(part_record(part)) + b"\n")
        require(stream.tell() <= PARTS_BYTES, "model_output_too_large")
    files = {name: {"bytes": regular_file(directory, name).stat().st_size,
                   "sha256": file_digest(regular_file(directory, name))} for name in DRAFT_FILES}
    with regular_file(directory, "manifest.json").open("xb") as stream:
        stream.write(json_bytes({"schemaVersion": 1, "files": files}))
    return prepare_summary(draft)
