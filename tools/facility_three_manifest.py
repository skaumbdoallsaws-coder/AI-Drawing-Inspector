"""Pure manifest binding for the P0 offline Three.js smoke."""

import hashlib
import json
import re


# three-offline-smoke.html maps `three` and `three/addons/` to r184.
# three-offline-smoke.js imports Three and GLTFLoader; Three imports core,
# and GLTFLoader imports BufferGeometryUtils and SkeletonUtils (both use Three).
# Paths are relative to static/vendor/three/0.184.0, in sorted order.
P0_VENDOR_PATHS = (
    "build/three.core.min.js",
    "build/three.module.min.js",
    "examples/jsm/loaders/GLTFLoader.js",
    "examples/jsm/utils/BufferGeometryUtils.js",
    "examples/jsm/utils/SkeletonUtils.js",
)


def p0_manifest_entries_sha256(manifest_text: str) -> str:
    """Hash only P0's File/Bytes/SHA-256 rows from VERSIONS.md.

    Canonical bytes are ASCII JSON of [path, byte_count, sha256] lists sorted
    by path, with compact separators and no trailing newline. Row order,
    line endings, prose, and unused entries do not affect the hash. Missing,
    malformed, or duplicate required entries raise ValueError.
    """
    entries = {}
    for line in manifest_text.splitlines():
        match = re.fullmatch(
            r"\| `([^`]+)` \| ([0-9]+) \| `([0-9a-f]{64})` \|", line
        )
        if match and match[1] in P0_VENDOR_PATHS:
            relative, byte_count, sha256 = match.groups()
            if relative in entries:
                raise ValueError(f"Duplicate P0 entry in VERSIONS.md: {relative}")
            entries[relative] = [relative, int(byte_count), sha256]
    missing = sorted(set(P0_VENDOR_PATHS) - entries.keys())
    if missing:
        raise ValueError(
            "Missing or malformed P0 entries in VERSIONS.md: " + ", ".join(missing)
        )
    payload = json.dumps(
        [entries[relative] for relative in sorted(P0_VENDOR_PATHS)],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("ascii")).hexdigest()
