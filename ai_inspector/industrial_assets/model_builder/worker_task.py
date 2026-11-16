"""The build task; called only after worker resource limits and private bootstrap."""
import sys

from .errors import require, json_bytes
from .job_io import directory, file_path, read_inputs, refuse_includes
from .protocol import make_result


def execute_build(job_dir):
    job = directory(job_dir)
    recipe, allowed = read_inputs(job)
    refuse_includes(recipe["entries"])
    require(not any(name == "ai_inspector" or name.startswith("ai_inspector.") for name in sys.modules),
            "$", "Application parents must not be loaded by the build worker", "job_invalid")
    from .build import build_model
    result = build_model(recipe, allowed_categories=allowed["categories"],
                         allowed_appearance_ids=allowed["appearanceIds"])
    require(not any(name == "ai_inspector" or name.startswith("ai_inspector.") for name in sys.modules),
            "$", "Application parents must not be loaded by the build worker", "job_invalid")
    summary = make_result(result, allowed)
    encoded = json_bytes(summary)
    # Exclusive writes, completion marker last. MB4 owns atomic draft publication.
    with file_path(job, "model.glb").open("xb") as stream:
        stream.write(result.glb)
    with file_path(job, "result.json").open("xb") as stream:
        stream.write(encoded)
    return summary
