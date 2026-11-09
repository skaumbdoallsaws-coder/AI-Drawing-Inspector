"""Generated fixtures only; no app initialization, private downloads or binary files."""
from copy import deepcopy
from io import BytesIO
import importlib.util
import json
from pathlib import Path
import struct
import sys
import zipfile

PACKAGE = Path(__file__).resolve().parents[1] / "ai_inspector" / "industrial_assets" / "model_import"
PACKAGE_NAME = "_model_import_tests"


def load_package():
    if PACKAGE_NAME not in sys.modules:
        spec = importlib.util.spec_from_file_location(PACKAGE_NAME, PACKAGE / "__init__.py",
                                                     submodule_search_locations=[str(PACKAGE)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[PACKAGE_NAME] = module
        spec.loader.exec_module(module)
    return sys.modules[PACKAGE_NAME]


def module(name):
    load_package()
    return __import__(PACKAGE_NAME + "." + name, fromlist=[name])


def glb(document, blob=b""):
    document = deepcopy(document)
    document.setdefault("asset", {"version": "2.0"})
    document.setdefault("buffers", [{"byteLength": len(blob)}] if blob else [])
    encoded = json.dumps(document, separators=(",", ":"), ensure_ascii=True).encode()
    encoded += b" " * (-len(encoded) % 4)
    result = struct.pack("<II", len(encoded), 0x4E4F534A) + encoded
    if blob:
        blob += b"\0" * (-len(blob) % 4)
        result += struct.pack("<II", len(blob), 0x004E4942) + blob
    return struct.pack("<4sII", b"glTF", 2, 12 + len(result)) + result


def unzip_model(document, blob, *, name="pack/model.gltf", resources=None, text=None, compression=zipfile.ZIP_STORED):
    document = deepcopy(document)
    document["buffers"][0]["uri"] = "scene.bin"
    prefix = name.rsplit("/", 1)[0] + "/" if "/" in name else ""
    entries = {name: json.dumps(document).encode(), prefix + "scene.bin": blob}
    entries.update(resources or {})
    if text is not None:
        entries[prefix + "license.txt"] = text.encode()
    return zip_bytes(entries, compression=compression)


def zip_bytes(entries, *, compression=zipfile.ZIP_STORED):
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        for name, payload in entries.items() if isinstance(entries, dict) else entries:
            archive.writestr(name, payload)
    return output.getvalue()


class Fixture:
    def __init__(self):
        self.document = {"asset": {"version": "2.0", "generator": "MI0a fixture"},
                         "buffers": [{"byteLength": 0}], "bufferViews": [], "accessors": [],
                         "meshes": [], "nodes": [], "scenes": [{"nodes": []}], "scene": 0}
        self.blob = bytearray()

    def data(self, payload, *, stride=None, target=None):
        self.blob.extend(b"\0" * (-len(self.blob) % 4))
        view = {"buffer": 0, "byteOffset": len(self.blob), "byteLength": len(payload)}
        if stride is not None:
            view["byteStride"] = stride
        if target is not None:
            view["target"] = target
        self.blob.extend(payload)
        self.document["buffers"][0]["byteLength"] = len(self.blob)
        self.document["bufferViews"].append(view)
        return len(self.document["bufferViews"]) - 1

    def array(self, values, kind="VEC3", component=5126, *, normalized=False, vertex=True):
        import numpy as np
        dtype = {5120: "i1", 5121: "u1", 5122: "<i2", 5123: "<u2", 5125: "<u4", 5126: "<f4"}[component]
        array = np.array(values, dtype=dtype)
        if array.ndim == 1:
            array = array[:, None]
        row_size = array.shape[1] * array.dtype.itemsize
        stride = ((row_size + 3) // 4 * 4) if vertex else row_size
        if stride != row_size:
            payload = b"".join(row.tobytes() + b"\0" * (stride - row_size) for row in array)
        else:
            payload = array.tobytes()
        view = self.data(payload, stride=stride if stride != row_size else None,
                         target=34962 if vertex else 34963)
        self.document["accessors"].append({"bufferView": view, "componentType": component,
                                           "count": len(array), "type": kind, "normalized": normalized})
        return len(self.document["accessors"]) - 1

    def triangle(self, positions=None, *, mode=4, indexed=True):
        positions = positions if positions is not None else [[0, 0, 0], [0, 0, 1], [1, 0, 0]]
        primitive = {"attributes": {"POSITION": self.array(positions)}, "mode": mode}
        if indexed:
            primitive["indices"] = self.array(list(range(len(positions))), "SCALAR", 5123, vertex=False)
        self.document["meshes"].append({"name": "mesh", "primitives": [primitive]})
        self.document["nodes"].append({"mesh": len(self.document["meshes"]) - 1, "name": "node"})
        self.document["scenes"][0]["nodes"].append(len(self.document["nodes"]) - 1)
        return primitive

    def image(self, data, *, mime="image/png"):
        images = self.document.setdefault("images", [])
        images.append({"bufferView": self.data(data), "mimeType": mime})
        textures = self.document.setdefault("textures", [])
        textures.append({"source": len(images) - 1})
        return len(textures) - 1

    def bytes(self):
        return glb(self.document, bytes(self.blob))


def image_bytes(mode="RGBA", size=(8, 8), color=(40, 80, 120, 128), format="PNG", **options):
    from PIL import Image
    output = BytesIO()
    with Image.new(mode, size, color) as image:
        image.save(output, format=format, **options)
    return output.getvalue()


def textured_box():
    fixture = Fixture()
    points = [[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1],
              [0, 1, 0], [1, 1, 0], [1, 1, 1], [0, 1, 1]]
    primitive = fixture.triangle(points, indexed=False)
    faces = [0, 1, 2, 0, 2, 3, 4, 7, 6, 4, 6, 5, 0, 4, 5, 0, 5, 1,
             1, 5, 6, 1, 6, 2, 2, 6, 7, 2, 7, 3, 3, 7, 4, 3, 4, 0]
    primitive["indices"] = fixture.array(faces, "SCALAR", 5123, vertex=False)
    primitive["attributes"]["NORMAL"] = fixture.array([[0, 1, 0]] * 8)
    primitive["attributes"]["TEXCOORD_0"] = fixture.array([[0, 0], [1, 0], [1, 1], [0, 1]] * 2, "VEC2")
    texture = fixture.image(image_bytes())
    fixture.document["materials"] = [{"name": "paint", "alphaMode": "MASK", "doubleSided": True,
                                      "pbrMetallicRoughness": {"baseColorTexture": {"index": texture}}}]
    primitive["material"] = 0
    return fixture
