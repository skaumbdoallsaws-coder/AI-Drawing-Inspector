"""Bounded, self-contained GLB ingestion; mass is never inferred from a shell."""
from io import BytesIO
import asyncio
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory
import warnings

from .service import PackagingError

MAX_BYTES = 24 * 1024 * 1024


def import_glb(payload: bytes, name: str, meters_per_unit: float):
    import numpy as np
    import trimesh
    from PIL import Image
    if meters_per_unit not in (1.0, 0.001, 0.0254):
        raise PackagingError("units_required", "Choose meters, millimeters or inches for the model's stored coordinates.", 400)
    if not 20 <= len(payload) <= MAX_BYTES:
        raise PackagingError("source_too_large", "Use a self-contained GLB no larger than 24 MiB.", 413)
    try:
        magic, version, length, json_size, kind = struct.unpack_from("<4sIIII", payload)
        if magic != b"glTF" or version != 2 or length != len(payload) or kind != 0x4E4F534A or json_size > min(MAX_BYTES, len(payload) - 20):
            raise ValueError("header")
        document = json.loads(payload[20:20 + json_size])
        if len(document.get("nodes", [])) > 2000 or sum(int(a.get("count", 0)) for a in document.get("accessors", [])) > 3000000:
            raise ValueError("complexity")
        if document.get("extensionsRequired") or document.get("animations") or document.get("skins"):
            raise ValueError("animated or compressed geometry")
        if any("uri" in obj for section in ("buffers", "images") for obj in document.get(section, [])):
            raise ValueError("external or inline resources")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            scene = trimesh.load_scene(BytesIO(payload), file_type="glb", process=False)
            if not scene.geometry or sum(len(g.faces) for g in scene.geometry.values()) > 300000:
                raise ValueError("complexity")
            scene.apply_scale(meters_per_unit)
            bounds = scene.bounds
            dimensions = bounds[1] - bounds[0]
            if not np.isfinite(bounds).all() or np.any(dimensions <= 0) or np.any(dimensions > 5):
                raise ValueError("dimensions")
            scene.apply_translation(-bounds.mean(axis=0))
            normalized = scene.export(file_type="glb")
    except Exception as exc:
        raise PackagingError("source_invalid", "This GLB is unsupported or exceeds the import limits. Use static, embedded geometry with confirmed units.", 400) from exc
    revision = hashlib.sha256(payload + str(meters_per_unit).encode()).hexdigest()
    metadata = {"name": name[:160] or "Imported product", "dimensions_m": dimensions.tolist(),
                "source_revision": revision, "meters_per_source_unit": meters_per_unit,
                "geometry_evidence": "Imported GLB bounding envelope; confirm against source CAD.",
                "mass_basis": "unknown", "mass_kg": None}
    return metadata, normalized


async def import_glb_isolated(payload, name, meters_per_unit, root):
    """A cancelled/slow model parse cannot leave a thread editing the workspace."""
    if meters_per_unit not in (1.0, 0.001, 0.0254):
        raise PackagingError("units_required", "Choose meters, millimeters or inches for the model's stored coordinates.", 400)
    directory = Path(root) / "import-jobs"
    directory.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="glb-", dir=directory) as temp:
        job = Path(temp)
        (job / "input.glb").write_bytes(payload)
        # Only the parser's runtime environment is inherited, not service credentials.
        env = {k: v for k, v in os.environ.items() if k.upper() in {
            "SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "APPDATA", "LOCALAPPDATA",
            "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "PYTHONUTF8", "VIRTUAL_ENV"}}
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "ai_inspector.packaging_shipping.sources", str(job), str(meters_per_unit),
            cwd=Path(__file__).resolve().parents[2], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            await asyncio.wait_for(process.wait(), timeout=25)
        except (TimeoutError, asyncio.CancelledError):
            if process.returncode is None:
                process.kill()
            await process.wait()
            if asyncio.current_task().cancelling():
                raise
            raise PackagingError("source_timeout", "Model import exceeded its time limit. Use a smaller static GLB.", 422)
        if process.returncode != 0 or not (job / "metadata.json").is_file():
            raise PackagingError("source_invalid", "The model could not be imported. Check its format, units and complexity.", 422)
        metadata = json.loads((job / "metadata.json").read_text(encoding="utf-8"))
        metadata["name"] = name[:160] or "Imported product"
        result = job / "normalized.glb"
        if result.stat().st_size > MAX_BYTES * 2:
            raise PackagingError("source_too_large", "Normalized geometry exceeds the import size limit.", 413)
        return metadata, result.read_bytes()


if __name__ == "__main__":
    job = Path(sys.argv[1])
    meta, glb = import_glb((job / "input.glb").read_bytes(), "Imported product", float(sys.argv[2]))
    (job / "metadata.json").write_text(json.dumps(meta, allow_nan=False), encoding="utf-8")
    (job / "normalized.glb").write_bytes(glb)
