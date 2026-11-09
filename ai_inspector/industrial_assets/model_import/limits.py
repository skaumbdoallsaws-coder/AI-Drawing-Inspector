"""Central intake budgets, injectable downward in generated-fixture tests."""
from dataclasses import dataclass

MIB = 1024 * 1024
SUMMARY_BYTES = 48 * 1024
CACHE_METADATA_BYTES = 16 * MIB
CACHE_BYTES = 384 * MIB
CPU_SECONDS = 60
WALL_SECONDS = 70
MEMORY_BYTES = 1536 * MIB
OPEN_FILES = 64
CACHE_VERSION = 1


@dataclass(frozen=True)
class Limits:
    upload_bytes: int = 128 * MIB
    zip_entries: int = 512
    zip_bytes: int = 512 * MIB
    zip_ratio: int = 200
    json_bytes: int = 16 * MIB
    nodes: int = 4096
    depth: int = 64
    primitives: int = 4096
    triangles: int = 2_000_000
    vertices: int = 3_000_000
    materials: int = 64
    images: int = 32
    image_side: int = 8192
    image_pixels: int = 64_000_000
    total_image_pixels: int = 256_000_000
    text_files: int = 8
    text_bytes: int = 64 * 1024
    # Bound metadata tables even outside the selected scene.
    accessors: int = 65536
    buffer_views: int = 65536


DEFAULT_LIMITS = Limits()
