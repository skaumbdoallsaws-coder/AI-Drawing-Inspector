"""Worker-produced scalar metadata for paging without loading geometry in the host."""
from copy import deepcopy

from .errors import ModelImportError
from .limits import DEFAULT_LIMITS, INSPECTION_BYTES, SUMMARY_BYTES
from .protocol import validate_summary, validate_source_part, validate_licence
from .validation import clean_text, json_bytes, require


def validate_inspection(value, summary):
    require(isinstance(value, dict) and set(value) == {"parts", "licence"}, "model_worker_failed")
    require(isinstance(value["parts"], list) and len(value["parts"]) == summary["partsTotal"],
            "model_worker_failed")
    previous = -1
    for part in value["parts"]:
        validate_source_part(part)
        index = int(part["key"][1:])
        # Keys name source primitives, including omitted points/lines. Offsets
        # count retained parts; neither inspection nor paging renumbers them.
        require(part["key"] == f"p{index}" and previous < index < DEFAULT_LIMITS.primitives,
                "model_worker_failed")
        previous = index
    offset = summary["partsOffset"]
    require(summary["parts"] == value["parts"][offset:offset + len(summary["parts"])], "model_worker_failed")
    require(sum(p["triangles"] for p in value["parts"]) == summary["triangles"], "model_worker_failed")
    licence = value["licence"]
    require(isinstance(licence, dict) and isinstance(licence.get("excerpt"), str), "model_worker_failed")
    require(len(licence["excerpt"].encode("utf-8")) <= 2048 and clean_text(licence["excerpt"], 2048) == licence["excerpt"],
            "model_worker_failed")
    validate_licence(licence, excerpt_limit=2048)
    require(len(json_bytes(value)) <= INSPECTION_BYTES, "model_worker_failed")
    return value


def inspection_page(summary, metadata, offset, limit):
    require(type(offset) is int and 0 <= offset <= summary["partsTotal"]
            and type(limit) is int and 1 <= limit <= 64, "recipe_invalid")
    value = deepcopy(summary)
    value["partsOffset"] = offset
    value["parts"] = metadata["parts"][offset:offset + limit]
    while True:
        end = offset + len(value["parts"])
        value["nextPartsOffset"] = end if end < value["partsTotal"] else None
        if len(json_bytes(value)) <= SUMMARY_BYTES:
            break
        require(len(value["parts"]) > 1, "model_worker_failed")
        value["parts"].pop()
    return validate_summary(value)
