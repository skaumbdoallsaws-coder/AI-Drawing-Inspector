"""Version 1 numeric NPZ + JSON cache; no pickle, source paths or object arrays.

Only a worker (or a generated-fixture test) loads this cache. The host checks
file sizes and hashes, not numpy arrays. See README.md for the stable layout.
"""
from pathlib import Path
import zipfile

import numpy as np

from .errors import ModelImportError
from .limits import CACHE_BYTES, CACHE_METADATA_BYTES, CACHE_VERSION
from .model import Model, ModelImage, Part
from .validation import json_bytes, parse_json, require

from .job_io import regular_file, file_digest


def save_cache(model: Model, job: Path) -> None:
    arrays, parts, images = {}, [], []
    for index, part in enumerate(model.parts):
        record = {key: getattr(part, key) for key in ("key", "name", "node", "mesh", "material")}
        record["arrays"] = {}
        for field in ("positions", "normals", "uv0", "indices"):
            value = getattr(part, field)
            if value is not None:
                key = f"p{index}_{field}"
                arrays[key] = value
                record["arrays"][field] = key
        parts.append(record)
    for index, image in enumerate(model.images):
        key = f"image{index}"
        arrays[key] = np.frombuffer(image.data, dtype=np.uint8)
        images.append({"array": key, "mimeType": image.mime_type, "width": image.width, "height": image.height,
                       "sourceWidth": image.source_width, "sourceHeight": image.source_height})
    metadata = {"schemaVersion": CACHE_VERSION, "name": model.name, "format": model.format,
                "sourceBytes": model.source_bytes, "sourceSha256": model.source_sha256, "generator": model.generator,
                "materials": model.materials, "licence": model.licence, "warnings": model.warnings,
                "parts": parts, "images": images}
    content = json_bytes(metadata)
    require(len(content) <= CACHE_METADATA_BYTES, "gltf_too_complex")
    require(sum(array.nbytes + 512 for array in arrays.values()) <= CACHE_BYTES, "gltf_too_complex")
    with regular_file(job, "cache.json").open("xb") as stream:
        stream.write(content)
    with regular_file(job, "parts.npz").open("xb") as stream:
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            for key, array in arrays.items():
                with archive.open(key + ".npy", "w", force_zip64=True) as entry:
                    np.lib.format.write_array(entry, array, allow_pickle=False)
    require((job / "parts.npz").stat().st_size <= CACHE_BYTES, "gltf_too_complex")


def load_cache(job: str | Path) -> Model:
    """Load the documented cache in a worker; verify hashes before numpy opens it."""
    from .protocol import validate_manifest
    try:
        job = Path(job)
        manifest_path = regular_file(job, "result.json")
        require(manifest_path.stat().st_size <= 4096, "model_cache_invalid")
        manifest = validate_manifest(parse_json(manifest_path.read_bytes(), 4096))
        for name, entry in manifest["files"].items():
            file = regular_file(job, name)
            require(file.stat().st_size == entry["bytes"] and file_digest(file) == entry["sha256"],
                    "model_cache_invalid")
        metadata = parse_json(regular_file(job, "cache.json").read_bytes(), CACHE_METADATA_BYTES)
        require(metadata["schemaVersion"] == CACHE_VERSION, "model_cache_invalid")
        require(0 < len(metadata["parts"]) <= 4096 and len(metadata["images"]) <= 32
                and 0 < len(metadata["materials"]) <= 64, "model_cache_invalid")
        with zipfile.ZipFile(regular_file(job, "parts.npz")) as archive:
            names = archive.namelist()
            require(len(names) <= 4096 * 4 + 32 and len(names) == len(set(names)), "model_cache_invalid")
            require(sum(info.file_size for info in archive.infolist()) <= CACHE_BYTES, "model_cache_invalid")
            require(all(info.compress_type == zipfile.ZIP_STORED for info in archive.infolist()), "model_cache_invalid")
        expected = {key for part in metadata["parts"] for key in part["arrays"].values()}
        expected.update(image["array"] for image in metadata["images"])
        require({key + ".npy" for key in expected} == set(names), "model_cache_invalid")
        parts, images, vertices, triangles = [], [], 0, 0
        with np.load(regular_file(job, "parts.npz"), allow_pickle=False) as archive:
            for raw in metadata["parts"]:
                values = {field: archive[key] for field, key in raw["arrays"].items()}
                require(set(values) <= {"positions", "normals", "uv0", "indices"}
                        and {"positions", "indices"} <= set(values), "model_cache_invalid")
                positions, indices = values["positions"], values["indices"]
                for field, value in values.items():
                    width = 2 if field == "uv0" else 3
                    require(value.ndim == 2 and value.shape[1] == width and value.dtype ==
                            np.dtype("uint32" if field == "indices" else "float32"), "model_cache_invalid")
                    require(bool(np.isfinite(value).all()), "model_cache_invalid")
                    if field != "indices":
                        require(len(value) == len(positions), "model_cache_invalid")
                require(len(positions) > 0 and len(indices) > 0 and int(indices.max()) < len(positions),
                        "model_cache_invalid")
                require(type(raw["material"]) is int and 0 <= raw["material"] < len(metadata["materials"]),
                        "model_cache_invalid")
                vertices, triangles = vertices + len(positions), triangles + len(indices)
                require(vertices <= 3_000_000 and triangles <= 2_000_000, "model_cache_invalid")
                parts.append(Part(raw["key"], raw["name"], raw["node"], raw["mesh"], raw["material"],
                                  positions, values.get("normals"), values.get("uv0"), indices))
            for raw in metadata["images"]:
                data = archive[raw["array"]]
                require(data.dtype == np.uint8 and data.ndim == 1, "model_cache_invalid")
                require(raw["mimeType"] in ("image/png", "image/jpeg") and
                        all(type(raw[k]) is int and 0 < raw[k] <= 2048 for k in ("width", "height")),
                        "model_cache_invalid")
                images.append(ModelImage(data.tobytes(), raw["mimeType"], raw["width"], raw["height"],
                                         raw["sourceWidth"], raw["sourceHeight"]))
        return Model(metadata["name"], metadata["format"], metadata["sourceBytes"], metadata["sourceSha256"],
                     metadata["generator"], parts, metadata["materials"], images, metadata["licence"],
                     metadata["warnings"])
    except (ModelImportError, OSError, ValueError, KeyError, TypeError, OverflowError,
            EOFError, IndexError, zipfile.BadZipFile):
        raise ModelImportError("model_cache_invalid") from None
