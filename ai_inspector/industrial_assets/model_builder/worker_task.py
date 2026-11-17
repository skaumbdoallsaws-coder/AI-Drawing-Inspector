"""The build task; called only after worker resource limits and private bootstrap."""
import sys

from .errors import require, json_bytes
from .job_io import directory, file_path, read_inputs, PREVIEW_REQUEST
from .include_contract import read_sources, prepare_sources
from .protocol import make_result


def execute_build(job_dir):
    job = directory(job_dir)
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
        # MB4a deliberately uses the import renderer and its shaders unchanged.
        pictures = module("preview").render_previews(module("reader").read_model(result.glb, extended_materials=True))
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
