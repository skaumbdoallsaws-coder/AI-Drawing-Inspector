"""Read untrusted model bytes only in the worker, with an in-process test entry."""
from hashlib import sha256

import numpy as np

from .accessors import Accessors
from .containers import open_container
from .errors import ModelImportError
from .geometry import flatten
from .licence import parse_licence
from .limits import DEFAULT_LIMITS, Limits
from .materials import check_extensions, read_images, read_materials
from .model import Model
from .validation import clean_text, mapping, require


def read_model(payload: bytes, name: str = "Imported model", *,
                limits: Limits = DEFAULT_LIMITS, texture_max_px: int = 1024,
                extended_materials: bool = False) -> Model:
    """No files, URLs or runtime state are accessed by this function."""
    try:
        container = open_container(payload, limits)
        document, warnings = container.document, []
        asset = mapping(document.get("asset"))
        require(asset.get("version") == "2.0" and asset.get("minVersion", "2.0") == "2.0")
        quantized = check_extensions(document, warnings)
        accessors = Accessors(container, limits)
        materials = read_materials(document, limits, warnings, extended_materials=extended_materials)
        parts = flatten(document, accessors, materials, limits, quantized, warnings,
                        preserve_node_names=extended_materials)
        images = read_images(container, accessors, materials, limits, texture_max_px)
        container.validate_resources()
        return Model(clean_text(name.replace("\\", "/").rsplit("/", 1)[-1]) or "Imported model",
                     container.format, len(payload), sha256(payload).hexdigest(), clean_text(asset.get("generator"), 300),
                     parts, materials, images, parse_licence(container.texts, asset), warnings)
    except ModelImportError:
        raise
    except MemoryError:
        raise ModelImportError("gltf_too_complex") from None
    except (TypeError, ValueError, KeyError, IndexError, OverflowError, RecursionError, np.linalg.LinAlgError):
        raise ModelImportError("gltf_invalid") from None
