"""Fixed local build inputs; no application, numerical, or image imports."""
from hashlib import sha256
from itertools import islice
from pathlib import Path
import stat

from .errors import ModelBuildError, json_bytes, parse_json, require
from .imports import module
from .recipe import RECIPE_BYTES, normalize_recipe

INPUT_NAMES = {"recipe.json", "allowed.json", "fonts", "includes"}
OUTPUT_NAMES = ("model.glb", "result.json", "error.json")
ALLOWED_BYTES = 256 * 1024
FONT_BYTES = 2 * 1024 * 1024
FONT_MANIFEST_BYTES = 4096


def directory(value):
    return module("job_io").local_directory(value)


def names(folder, maximum):
    """Read at most one extra directory entry, enough to reject unexpected files."""
    return {p.name for p in islice(folder.iterdir(), maximum+1)}


def file_path(folder, name):
    require(isinstance(name, str) and name not in {"", ".", ".."} and not any(c in name for c in "/\\:")
            and Path(name).name == name, "$", "Unsafe job filename", "job_invalid")
    folder = directory(folder)
    target = folder / name
    require(target.resolve().parent == folder, "$", "File leaves its job directory", "job_invalid")
    if target.exists() or target.is_symlink():
        info = target.lstat()
        require(stat.S_ISREG(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
                "$", "Job input must be a regular file", "job_invalid")
    return target


def read_bytes(folder, name, maximum):
    target = file_path(folder, name)
    require(target.stat().st_size <= maximum, "$", name + " exceeds its byte limit", "job_invalid")
    with target.open("rb") as stream:
        payload = stream.read(maximum+1)
    require(len(payload) <= maximum, "$", name + " exceeds its byte limit", "job_invalid")
    return payload


def read_json(folder, name, maximum):
    try:
        return parse_json(read_bytes(folder, name, maximum), maximum)
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, ModelBuildError):
            raise
        raise ModelBuildError("job_invalid", "$", "Invalid JSON in " + name) from error


def validate_allowed(value):
    require(type(value) is dict and set(value) == {"categories", "appearanceIds"}, "$",
            "allowed.json needs categories and appearanceIds", "job_invalid")
    for key, count, length in (("categories", 512, 80), ("appearanceIds", 1024, 120)):
        values = value[key]
        require(type(values) is list and len(values) <= count, "$", "Invalid " + key + " list", "job_invalid")
        require(all(type(v) is str and 0 < len(v) <= length and v.strip() == v
                    and all(ord(c) >= 32 for c in v) for v in values), "$",
                "Invalid " + key + " identifier", "job_invalid")
        require(len(set(values)) == len(values), "$", "Duplicate " + key + " identifier", "job_invalid")
    require(bool(value["categories"]), "$", "At least one category is required", "job_invalid")
    require(len(json_bytes(value)) <= ALLOWED_BYTES, "$", "Allowed lists exceed their byte limit", "job_invalid")
    return value


def pinned_font():
    """This manifest is installed code, not the job's replaceable copy."""
    folder = Path(__file__).resolve().parent / "fonts"
    manifest = read_json(folder, "fonts.json", FONT_MANIFEST_BYTES)
    require(type(manifest) is dict and set(manifest) == {"regular"}, "$.fonts",
            "Invalid bundled font manifest", "font_missing")
    entry = manifest["regular"]
    require(type(entry) is dict and set(entry) == {"file", "sha256", "bytes", "family", "licence"},
            "$.fonts", "Invalid bundled font record", "font_missing")
    require(type(entry["bytes"]) is int and 0 < entry["bytes"] <= FONT_BYTES
            and isinstance(entry["sha256"], str) and len(entry["sha256"]) == 64,
            "$.fonts", "Invalid bundled font digest", "font_missing")
    file_path(folder, entry["file"])  # Check the trusted record's basename too.
    return folder, manifest


def font_bytes(font_directory=None):
    """Read the pinned bytes, from a host-owned job copy or the bundled folder."""
    try:
        bundled, trusted = pinned_font()
        folder = bundled if font_directory is None else directory(font_directory)
        entry = trusted["regular"]
        require(read_json(folder, "fonts.json", FONT_MANIFEST_BYTES) == trusted, "$.fonts",
                "Font manifest differs from the bundled manifest", "font_missing")
        payload = read_bytes(folder, entry["file"], entry["bytes"])
        require(len(payload) == entry["bytes"] and sha256(payload).hexdigest() == entry["sha256"],
                "$.fonts", "Font bytes differ from the pinned SHA-256", "font_missing")
        return payload
    except (OSError, ValueError, module("errors").ModelImportError) as error:
        raise ModelBuildError("font_missing", "$.fonts", "The pinned job font is missing or invalid") from error


def validate_fonts(job):
    try:
        _, trusted = pinned_font()
        folder = directory(job / "fonts")
        require(names(folder, 2) == {"fonts.json", trusted["regular"]["file"]}, "$.fonts",
                "Expected only the pinned font and its manifest", "font_missing")
        font_bytes(folder)
        return trusted
    except (OSError, ValueError, module("errors").ModelImportError) as error:
        raise ModelBuildError("font_missing", "$.fonts", "The pinned job font is missing or invalid") from error


def read_inputs(job, *, outputs=False, check_fonts=True):
    try:
        job = directory(job)
        expected = INPUT_NAMES | ({"model.glb", "result.json"} if outputs else set())
        require(names(job, len(expected)) == expected, "$", "Job has missing or unexpected files", "job_invalid")
        include_dir = directory(job / "includes")
        require(next(include_dir.iterdir(), None) is None, "$.includes",
                "Composition arrives in MB3; includes must be empty", "composition_unavailable")
        allowed = validate_allowed(read_json(job, "allowed.json", ALLOWED_BYTES))
        raw = read_json(job, "recipe.json", RECIPE_BYTES)
        normalized = normalize_recipe(raw, allowed_categories=allowed["categories"],
                                      allowed_appearance_ids=allowed["appearanceIds"])
        require(json_bytes(raw) == json_bytes(normalized), "$", "recipe.json must contain the normalized recipe")
        if check_fonts:
            validate_fonts(job)
        return normalized, allowed
    except (OSError, module("errors").ModelImportError) as error:
        raise ModelBuildError("job_invalid", "$", "Unsafe or missing build input") from error


def refuse_includes(entries, path="$.entries"):
    for i, entry in enumerate(entries):
        location = f"{path}[{i}]"
        if "include" in entry:
            raise ModelBuildError("composition_unavailable", location + ".include")
        if "group" in entry:
            refuse_includes(entry["group"], location + ".group")
