"""Host-only build entry: limited worker launch, checked output, application verification.

Kept outside model_builder so the private worker package never imports an
application parent. The caller owns the job directory; MB4 owns publication.
"""
import asyncio
import struct
import threading
from hashlib import sha256

from . import primitives
from .model_builder.errors import ModelBuildError, decode_error, json_bytes
from .model_builder.imports import module
from .model_builder import job_io, protocol
from .model_builder import include_contract
from .model_builder.recipe import RECIPE_BYTES, normalize_recipe

launch = module("runner")
ModelImportError = module("errors").ModelImportError
WALL_SECONDS = module("limits").WALL_SECONDS


def write_job_inputs(job_dir, recipe, *, categories, appearance_ids, font_directory=None, include_catalog=None, previews=False):
    """Populate an empty host-owned job with normalized JSON and pinned-font copies.

    font_directory is trusted host configuration, never a field in recipe data.
    The worker independently checks the copies against its bundled manifest.
    """
    allowed = job_io.validate_allowed({"categories": list(categories), "appearanceIds": list(appearance_ids)})
    normalized = normalize_recipe(recipe, allowed_categories=allowed["categories"],
                                  allowed_appearance_ids=allowed["appearanceIds"])
    wanted = include_contract.entries(normalized)
    if wanted and include_catalog is None:
        raise ModelBuildError("include_missing", "$.includes", "Build includes need a trusted host catalog resolver")
    sources = include_catalog.resolve_recipe(normalized) if wanted else {}
    job = job_io.directory(job_dir)
    if next(job.iterdir(), None) is not None:
        raise ModelBuildError("job_invalid", "$", "Build inputs need an empty job directory")
    bundled, manifest = job_io.pinned_font()
    source = bundled if font_directory is None else job_io.directory(font_directory)
    font_name = manifest["regular"]["file"]
    font = job_io.read_bytes(source, font_name, job_io.FONT_BYTES)
    # Read all data before creating anything. Roll back only paths created here.
    files, folders = [], []
    try:
        for name in ("fonts", "includes"):
            folder = job / name
            folder.mkdir()
            folders.append(folder)
        inputs = [
                (job, "recipe.json", json_bytes(normalized)), (job, "allowed.json", json_bytes(allowed)),
                (job / "fonts", "fonts.json", json_bytes(manifest)), (job / "fonts", font_name, font)]
        if previews:
            from ..facility_layout.appearance_library import load_library
            appearances = load_library()["appearances"]
            colors = {key: appearances[key]["color"] for key in allowed["appearanceIds"]
                      if key in appearances and isinstance(appearances[key].get("color"), str)}
            job_io.validate_appearance_colors(colors)
            inputs.append((job, job_io.PREVIEW_REQUEST, json_bytes({"previews": True})))
            inputs.append((job, job_io.APPEARANCE_COLORS, json_bytes(colors)))
        if wanted:
            inputs.append((job / "includes", "manifest.json", json_bytes(
                [sources[entry["id"]]["manifest"] for entry, _, _ in wanted])))
            inputs.extend((job / "includes", f"{i}.glb", sources[entry["id"]]["payload"])
                          for i, (entry, _, _) in enumerate(wanted))
        for folder, name, payload in inputs:
            target = job_io.file_path(folder, name)
            with target.open("xb") as stream:
                files.append(target)
                stream.write(payload)
        return normalized
    except (OSError, ValueError, ModelImportError):
        for target in reversed(files):
            module("cleanup").retry_cleanup(target.unlink)
        for folder in reversed(folders):
            module("cleanup").retry_cleanup(folder.rmdir)
        raise


def _include_fingerprint(job):
    folder = job_io.directory(job / "includes")
    names = job_io.names(folder, 4)
    if not names <= {"manifest.json", "0.glb", "1.glb", "2.glb"}:
        raise ModelBuildError("job_invalid", "$.includes", "Unexpected include input files")
    return {name: sha256(job_io.read_bytes(folder, name, include_contract.MANIFEST_BYTES if name == "manifest.json"
                                         else include_contract.INCLUDE_BYTES)).hexdigest() for name in sorted(names)}


def _clean_outputs(job):
    for name in job_io.OUTPUT_NAMES:
        try:
            target = job_io.file_path(job, name)
            module("cleanup").retry_cleanup(lambda: target.unlink(missing_ok=True))
        except (OSError, ValueError, ModelImportError):
            pass


def run_build(job_dir, dependency_root, *, cancel_event=None, timeout=WALL_SECONDS, _owned=None):
    """Return the full validated result, retaining model.glb/result.json on success."""
    event = cancel_event if cancel_event is not None else threading.Event()
    if event.is_set():
        raise ModelImportError("model_cancelled")
    try:
        job, dependencies = job_io.directory(job_dir), job_io.directory(dependency_root)
        preview_request = job_io.file_path(job, job_io.PREVIEW_REQUEST).exists()
        expected = job_io.INPUT_NAMES | ({job_io.PREVIEW_REQUEST, job_io.APPEARANCE_COLORS} if preview_request else set())
        if job_io.names(job, len(expected)) != expected:
            raise ModelImportError("model_worker_failed")
        before = (job_io.read_bytes(job, "recipe.json", RECIPE_BYTES),
                  job_io.read_bytes(job, "allowed.json", job_io.ALLOWED_BYTES), _include_fingerprint(job),
                   job_io.read_bytes(job, job_io.PREVIEW_REQUEST, 128) if preview_request else None,
                   job_io.read_bytes(job, job_io.APPEARANCE_COLORS, job_io.ALLOWED_BYTES) if preview_request else None)
    except (OSError, ValueError, ModelImportError):
        raise ModelImportError("model_worker_failed") from None
    if _owned is not None:
        _owned.set()
    success = False
    try:
        launch._launch(job, dependencies, "build", event, timeout, build_error_decoder=decode_error)
        try:
            recipe, allowed = job_io.read_inputs(job, outputs=True)
            after = (job_io.read_bytes(job, "recipe.json", RECIPE_BYTES),
                     job_io.read_bytes(job, "allowed.json", job_io.ALLOWED_BYTES), _include_fingerprint(job),
                      job_io.read_bytes(job, job_io.PREVIEW_REQUEST, 128) if preview_request else None,
                      job_io.read_bytes(job, job_io.APPEARANCE_COLORS, job_io.ALLOWED_BYTES) if preview_request else None)
            if before != after:
                raise ModelImportError("model_worker_failed")
            result, payload = protocol.read_result(job, recipe, allowed,
                                                   include_sources=include_contract.read_sources(job, recipe))
            protocol.validate_glb_metadata(primitives.gltf_json(payload), result, payload=payload)
            checked = primitives.verify(payload, result["dimensions"], base_height=recipe["hangHeight"])
            if checked["triangles"] != result["triangles"] or checked["bytes"] != result["outputBytes"]:
                raise ModelImportError("model_worker_failed")
            if preview_request:
                for name, kind, maximum in (("preview.png", "preview", module("limits").PREVIEW_BYTES),
                                             ("thumbnail.webp", "thumbnail", module("limits").THUMBNAIL_BYTES)):
                    module("pictures").validate_picture(job_io.read_bytes(job, name, maximum), kind)
        except (OSError, ValueError, KeyError, TypeError, IndexError, struct.error,
                OverflowError, RecursionError, ModelImportError):
            raise ModelImportError("model_worker_failed") from None
        if event.is_set():
            raise ModelImportError("model_cancelled")
        success = True
        return result
    finally:
        if not success:
            _clean_outputs(job)


async def run_build_async(job_dir, dependency_root, *, cancel_event=None, timeout=WALL_SECONDS):
    event = cancel_event if cancel_event is not None else threading.Event()
    owned = threading.Event()
    work = asyncio.create_task(asyncio.to_thread(run_build, job_dir, dependency_root,
                                                cancel_event=event, timeout=timeout, _owned=owned))
    try:
        await asyncio.wait({work})
        return work.result()
    except asyncio.CancelledError:
        await launch._cancel_and_join(work, event)
        if owned.is_set():
            try:
                _clean_outputs(job_io.directory(job_dir))
            except (OSError, ValueError, ModelImportError):
                pass
        raise


def prepare_build_draft(recipe, destination, cancel_event, *, dependency_root, categories, appearance_ids,
                        scope, created, include_catalog=None, derived_from=None):
    """Stage a complete immutable draft inside the caller's reserved job folder."""
    from pathlib import Path
    from .model_builder import drafts
    destination = Path(destination)
    job = destination.parent / "worker"
    job.mkdir()
    normalized = write_job_inputs(job, recipe, categories=categories, appearance_ids=appearance_ids,
                                  include_catalog=include_catalog, previews=True)
    result = run_build(job, dependency_root, cancel_event=cancel_event)
    return drafts.write_draft(
        destination, normalized, result, job_io.read_bytes(job, "model.glb", protocol.GLB_BYTES),
        job_io.read_bytes(job, "preview.png", drafts.FILES["preview.png"]),
        job_io.read_bytes(job, "thumbnail.webp", drafts.FILES["thumbnail.webp"]),
        scope=scope, created=created, derived_from=derived_from)


def appearance_colors():
    """Only bundled base colors cross into the worker, never local custom finishes."""
    from ..facility_layout.appearance_library import load_library
    entries = load_library()["appearances"]
    return job_io.validate_appearance_colors({key: row["color"] for key, row in entries.items()
                                              if isinstance(row.get("color"), str)})


def run_focus(job_dir, dependency_root, payload, parts, *, cancel_event=None, timeout=WALL_SECONDS):
    """Re-render a pinned GLB in the same contained build launch as draft pictures."""
    event = cancel_event if cancel_event is not None else threading.Event()
    if event.is_set():
        raise ModelImportError("model_cancelled")
    if type(payload) is not bytes or not 0 < len(payload) <= protocol.GLB_BYTES:
        raise ModelBuildError("job_invalid", "$.focus.model", "Focus model exceeds its byte limit")
    job = job_io.directory(job_dir)
    dependencies = job_io.directory(dependency_root)
    if job_io.names(job, 0):
        raise ModelBuildError("job_invalid", "$.focus", "Focus job must be empty")
    request = {"modelSha256": sha256(payload).hexdigest(), "parts": parts}
    if len(json_bytes(request)) > 4096:
        raise ModelBuildError("job_invalid", "$.focus.parts", "Focus selection is too large")
    colors = appearance_colors()
    inputs = (("model.glb", payload), (job_io.FOCUS_REQUEST, json_bytes(request)),
              (job_io.APPEARANCE_COLORS, json_bytes(colors)))
    for name, data in inputs:
        with job_io.file_path(job, name).open("xb") as stream:
            stream.write(data)
    job_io.read_focus_inputs(job)
    before = tuple(sha256(data).hexdigest() for _, data in inputs)
    launch._launch(job, dependencies, "build", event, timeout, build_error_decoder=decode_error)
    focus, checked_colors, checked_payload = job_io.read_focus_inputs(job, outputs=True)
    if (focus != request or checked_colors != colors or checked_payload != payload
            or before != tuple(sha256(job_io.read_bytes(job, name, len(data))).hexdigest() for name, data in inputs)):
        raise ModelImportError("model_worker_failed")
    picture = job_io.read_bytes(job, "preview.png", module("limits").PREVIEW_BYTES)
    module("pictures").validate_picture(picture, "preview")
    if event.is_set():
        raise ModelImportError("model_cancelled")
    return picture
