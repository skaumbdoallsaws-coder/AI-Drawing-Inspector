"""Host-side checked launch for image and PDF reference intake."""
from hashlib import sha256
import threading

from .model_builder.errors import ModelBuildError, decode_error, json_bytes, parse_json
from .model_builder import job_io
from .model_builder.imports import module
from .model_builder.reference_worker import MAX_SOURCE, MAX_PAGE_BYTES, MAX_OUTPUT


def run_reference(job_dir, dependency_root, *, pdf=False, cancel_event=None, timeout=70):
    job = job_io.directory(job_dir)
    if job_io.names(job, 2) != {"source.bin", "request.json"}:
        raise ModelBuildError("job_invalid", "$", "Reference job needs only its source and request")
    source = job_io.read_bytes(job, "source.bin", MAX_SOURCE)
    if job_io.read_bytes(job, "request.json", 1024) != json_bytes({"pdf": pdf}):
        raise ModelBuildError("job_invalid", "$.request", "Reference job request differs")
    event = cancel_event or threading.Event()
    module("runner")._launch(job, job_io.directory(dependency_root), "reference", event, timeout,
                             build_error_decoder=decode_error)
    if event.is_set():
        raise module("errors").ModelImportError("model_cancelled")
    if job_io.read_bytes(job, "source.bin", MAX_SOURCE) != source:
        raise ModelBuildError("job_invalid", "$.source", "Reference source changed during intake")
    result = parse_json(job_io.read_bytes(job, "result.json", 512*1024), 512*1024)
    if (type(result) is not dict or set(result) != {"kind", "pages", "renderedPages", "sourceSha256"}
            or result["kind"] != ("pdf" if pdf else "image")
            or type(result["pages"]) is not int or not 1 <= result["pages"] <= 10000
            or type(result["renderedPages"]) is not list
            or len(result["renderedPages"]) != min(result["pages"], 20 if pdf else 1)
            or result["sourceSha256"] != sha256(source).hexdigest()):
        raise ModelBuildError("job_invalid", "$.result", "Invalid reference worker result")
    pages = job_io.directory(job / "pages")
    if job_io.names(pages, len(result["renderedPages"])) != {
            str(i)+".png" for i in range(len(result["renderedPages"]))}:
        raise ModelBuildError("job_invalid", "$.result", "Unexpected reference pages")
    total = 0
    for index, row in enumerate(result["renderedPages"]):
        if (type(row) is not dict or set(row) != {"page", "sha256", "bytes", "width", "height", "text"}
                or row["page"] != index or type(row["bytes"]) is not int or not 0 < row["bytes"] <= MAX_PAGE_BYTES
                or type(row["width"]) is not int or type(row["height"]) is not int
                or not 0 < row["width"] <= (1600 if pdf else 2048)
                or not 0 < row["height"] <= (1600 if pdf else 2048)
                or type(row["text"]) is not str or len(row["text"].encode()) > 16384):
            raise ModelBuildError("job_invalid", "$.result", "Invalid reference page record")
        payload = job_io.read_bytes(pages, str(index)+".png", MAX_PAGE_BYTES)
        from .model_builder.print_contract import png_dimensions
        try:
            dimensions = png_dimensions(payload, included=True)
        except ValueError as error:
            raise ModelBuildError("job_invalid", "$.result", "Invalid reference page pixels") from error
        if dimensions != (row["width"], row["height"]):
            raise ModelBuildError("job_invalid", "$.result", "Invalid reference page dimensions")
        if len(payload) != row["bytes"] or sha256(payload).hexdigest() != row["sha256"]:
            raise ModelBuildError("job_invalid", "$.result", "Reference page digest differs")
        total += len(payload)
    if total > MAX_OUTPUT or job_io.names(job, 4) != {"source.bin", "request.json", "pages", "result.json"}:
        raise ModelBuildError("job_invalid", "$.result", "Reference output exceeds its contract")
    return result
