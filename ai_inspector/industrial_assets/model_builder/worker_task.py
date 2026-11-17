"""The build task; called only after worker resource limits and private bootstrap."""
import sys

from .errors import require, json_bytes
from .job_io import directory, file_path, read_inputs, read_focus_inputs, read_json, validate_appearance_colors, ALLOWED_BYTES, PREVIEW_REQUEST, APPEARANCE_COLORS, FOCUS_REQUEST
from .include_contract import read_sources, prepare_sources
from .protocol import make_result


def execute_build(job_dir):
    job = directory(job_dir)
    if file_path(job, FOCUS_REQUEST).exists():
        return execute_focus(job)
    recipe, allowed = read_inputs(job)
    sources, _ = prepare_sources(recipe, read_sources(job, recipe))
    require(not any(name == "ai_inspector" or name.startswith("ai_inspector.") for name in sys.modules),
            "$", "Application parents must not be loaded by the build worker", "job_invalid")
    from .build import build_model
    result = build_model(recipe, allowed_categories=allowed["categories"],
                          allowed_appearance_ids=allowed["appearanceIds"], font_directory=job / "fonts",
                          include_sources=sources)
    require(not any(name == "ai_inspector" or name.startswith("ai_inspector.") for name in sys.modules),
            "$", "Application parents must not be loaded by the build worker", "job_invalid")
    summary = make_result(result, allowed)
    if file_path(job, PREVIEW_REQUEST).exists():
        from .imports import module
        from .pictures import render_previews
        colors = validate_appearance_colors(read_json(job, APPEARANCE_COLORS, ALLOWED_BYTES))
        pictures = render_previews(module("reader").read_model(result.glb, extended_materials=True),
                                   appearance_colors=colors)
        for name, data in (("preview.png", pictures.preview), ("thumbnail.webp", pictures.thumbnail)):
            with file_path(job, name).open("xb") as stream:
                stream.write(data)
    encoded = json_bytes(summary)
    # Exclusive writes, completion marker last. MB4 owns atomic draft publication.
    with file_path(job, "model.glb").open("xb") as stream:
        stream.write(result.glb)
    with file_path(job, "result.json").open("xb") as stream:
        stream.write(encoded)
    return summary


def execute_focus(job):
    from .imports import module
    from .pictures import render_previews
    request, colors, payload = read_focus_inputs(job)
    require(not any(name == "ai_inspector" or name.startswith("ai_inspector.") for name in sys.modules),
            "$", "Application parents must not be loaded by the build worker", "job_invalid")
    model = module("reader").read_model(payload, extended_materials=True, texture_max_px=2048)
    require(all(part["index"] < len(model.parts) and model.parts[part["index"]].name == part["name"]
                for part in request["parts"]), "$.focus.parts", "Focus parts differ from the model", "job_invalid")
    pictures = render_previews(model, appearance_colors=colors,
                               focus_indices=[part["index"] for part in request["parts"]], thumbnail=False)
    require(not any(name == "ai_inspector" or name.startswith("ai_inspector.") for name in sys.modules),
            "$", "Application parents must not be loaded by the build worker", "job_invalid")
    with file_path(job, "preview.png").open("xb") as stream:
        stream.write(pictures.preview)
    return {"focused": True}
