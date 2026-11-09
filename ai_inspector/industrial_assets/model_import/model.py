"""Flattened arrays and normalized materials shared with the later recipe phase."""
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Part:
    key: str
    name: str
    node: str
    mesh: str
    material: int
    positions: np.ndarray
    normals: np.ndarray | None
    uv0: np.ndarray | None
    indices: np.ndarray


@dataclass
class ModelImage:
    data: bytes
    mime_type: str
    width: int
    height: int
    source_width: int
    source_height: int


@dataclass
class Model:
    name: str
    format: str
    source_bytes: int
    source_sha256: str
    generator: str
    parts: list[Part]
    materials: list[dict]
    images: list[ModelImage]
    licence: dict
    warnings: list[str] = field(default_factory=list)
