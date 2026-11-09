"""The inspect task, callable directly only for trusted generated-fixture tests."""
from pathlib import Path

from .cache import save_cache
from .job_io import bounded_read, file_digest, local_directory, regular_file
from .limits import DEFAULT_LIMITS
from .protocol import validate_summary
from .reader import read_model
from .summary import build_summary
from .validation import json_bytes, parse_json, require


def execute_inspect(job_dir: str | Path) -> dict:
    job = local_directory(job_dir)
    request = {}
    if regular_file(job, "request.json").exists():
        request = parse_json(bounded_read(job, "request.json", 4096), 4096)
    require(set(request) <= {"name", "textureMaxPx"})
    name = request.get("name", "Imported model")
    require(isinstance(name, str) and len(name) <= 1024)
    source = regular_file(job, "source.bin")
    require(source.stat().st_size <= DEFAULT_LIMITS.upload_bytes, "model_too_large")
    payload = bounded_read(job, "source.bin", DEFAULT_LIMITS.upload_bytes)
    model = read_model(payload, name, texture_max_px=request.get("textureMaxPx", 1024))
    summary = validate_summary(build_summary(model))
    save_cache(model, job)
    with regular_file(job, "summary.json").open("xb") as stream:
        stream.write(json_bytes(summary))
    files = {name: {"bytes": regular_file(job, name).stat().st_size,
                    "sha256": file_digest(regular_file(job, name))}
             for name in ("summary.json", "cache.json", "parts.npz")}
    # Last file is the completion marker. A killed worker never yields a usable partial cache.
    with regular_file(job, "result.json").open("xb") as stream:
        stream.write(json_bytes({"schemaVersion": 1, "files": files}))
    return summary
