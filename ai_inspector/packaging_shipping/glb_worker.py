"""Self-contained GLB parser; launched with -I -S and one host-owned dependency root."""
from io import BytesIO
import hashlib
import json
from pathlib import Path
import struct
import sys
import warnings

MAX_BYTES = 24 * 1024 * 1024


class ImportRejected(Exception):
    def __init__(self, code, message, status):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def convert(payload, name, meters_per_unit):
    import numpy as np
    import trimesh
    from PIL import Image
    if meters_per_unit not in (1.0, 0.001, 0.0254):
        raise ImportRejected('units_required', "Choose meters, millimeters or inches for the model's stored coordinates.", 400)
    if not 20 <= len(payload) <= MAX_BYTES:
        raise ImportRejected('source_too_large', 'Use a self-contained GLB no larger than 24 MiB.', 413)
    try:
        magic, version, length, json_size, kind = struct.unpack_from('<4sIIII', payload)
        if magic != b'glTF' or version != 2 or length != len(payload) or kind != 0x4E4F534A or json_size > min(MAX_BYTES, len(payload) - 20):
            raise ValueError('header')
        document = json.loads(payload[20:20 + json_size])
        if len(document.get('nodes', [])) > 2000 or sum(int(a.get('count', 0)) for a in document.get('accessors', [])) > 3000000:
            raise ValueError('complexity')
        if document.get('extensionsRequired') or document.get('animations') or document.get('skins'):
            raise ValueError('animated or compressed geometry')
        if any('uri' in obj for section in ('buffers', 'images') for obj in document.get(section, [])):
            raise ValueError('external or inline resources')
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            scene = trimesh.load_scene(BytesIO(payload), file_type='glb', process=False)
            if not scene.geometry or sum(len(g.faces) for g in scene.geometry.values()) > 300000:
                raise ValueError('complexity')
            scene.apply_scale(meters_per_unit)
            bounds = scene.bounds
            dimensions = bounds[1] - bounds[0]
            if not np.isfinite(bounds).all() or np.any(dimensions <= 0) or np.any(dimensions > 5):
                raise ValueError('dimensions')
            scene.apply_translation(-bounds.mean(axis=0))
            normalized = scene.export(file_type='glb')
    except Exception as exc:
        raise ImportRejected('source_invalid', 'This GLB is unsupported or exceeds the import limits. Use static, embedded geometry with confirmed units.', 400) from exc
    revision = hashlib.sha256(payload + str(meters_per_unit).encode()).hexdigest()
    metadata = {'name': name[:160] or 'Imported product', 'dimensions_m': dimensions.tolist(),
                'source_revision': revision, 'meters_per_source_unit': meters_per_unit,
                'geometry_evidence': 'Imported GLB bounding envelope; confirm against source CAD.',
                'mass_basis': 'unknown', 'mass_kg': None}
    return metadata, normalized


if __name__ == '__main__':
    # This argument comes from the native startup binding, never upload metadata.
    # Append a directory directly: no site.addsitedir, .pth or sitecustomize.
    dependencies, job = Path(sys.argv[1]), Path(sys.argv[2])
    if not dependencies.is_absolute() or not dependencies.is_dir() or not job.is_absolute():
        raise SystemExit(2)
    sys.path.append(str(dependencies))
    meta, glb = convert((job / 'input.glb').read_bytes(), 'Imported product', float(sys.argv[3]))
    (job / 'metadata.json').write_text(json.dumps(meta, allow_nan=False), encoding='utf-8')
    (job / 'normalized.glb').write_bytes(glb)
