"""Read a downloaded GLB (untrusted data: parsed as numbers and images only) into world-space parts, and write new
GLBs from textured parts and plain-colour Mesh parts. Used by safety_models.py.
  parts(path) -> [Part(name, P, N, U, I, material)] with node transforms baked in."""
import io
import json
import struct
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

COMP = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
SIZE = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


@dataclass
class Material:
    name: str
    color: list = field(default_factory=lambda: [1.0, 1.0, 1.0, 1.0])
    image: object = None            # PIL image (base colour)
    emissive: list = None
    emissive_image: object = None
    metallic: float = 0.0
    roughness: float = 0.8
    blend: bool = False
    double_sided: bool = False


@dataclass
class Part:
    name: str
    P: np.ndarray
    N: np.ndarray
    U: object
    I: np.ndarray
    material: Material


class Source:
    def __init__(self, path):
        data = open(path, "rb").read()
        magic, version, length = struct.unpack("<4sII", data[:12])
        assert magic == b"glTF" and version == 2 and length == len(data), "not a whole GLB 2.0"
        json_len = struct.unpack("<I", data[12:16])[0]
        self.g = json.loads(data[20:20 + json_len])
        self.bin = data[20 + json_len + 8:]
        self.images = {}

    def accessor(self, index):
        a = self.g["accessors"][index]
        view = self.g["bufferViews"][a["bufferView"]]
        n, k = a["count"], SIZE[a["type"]]
        dtype = np.dtype(COMP[a["componentType"]])
        stride = view.get("byteStride") or dtype.itemsize * k
        offset = view.get("byteOffset", 0) + a.get("byteOffset", 0)
        raw = np.frombuffer(self.bin, dtype=np.uint8, count=stride * (n - 1) + dtype.itemsize * k, offset=offset)
        rows = np.lib.stride_tricks.as_strided(raw, shape=(n, dtype.itemsize * k), strides=(stride, 1))
        out = np.ascontiguousarray(rows).view(dtype).reshape(n, k).astype(np.float64)
        if a.get("normalized"):
            out /= np.iinfo(dtype).max
        return out

    def image(self, texture_index):
        if texture_index not in self.images:
            source = self.g["textures"][texture_index]["source"]
            image = self.g["images"][source]
            view = self.g["bufferViews"][image["bufferView"]]
            start = view.get("byteOffset", 0)
            pic = Image.open(io.BytesIO(bytes(self.bin[start:start + view["byteLength"]])))
            pic.load()
            self.images[texture_index] = pic
        return self.images[texture_index]

    def material(self, index):
        if index is None:
            return Material("default")
        m = self.g["materials"][index]
        pbr = m.get("pbrMetallicRoughness") or {}
        sg = (m.get("extensions") or {}).get("KHR_materials_pbrSpecularGlossiness")
        out = Material(m.get("name") or f"material{index}")
        if sg:
            out.color = list(sg.get("diffuseFactor", [1, 1, 1, 1]))
            if "diffuseTexture" in sg:
                out.image = self.image(sg["diffuseTexture"]["index"])
            out.roughness = 1 - float(sg.get("glossinessFactor", 0.2))
        else:
            out.color = list(pbr.get("baseColorFactor", [1, 1, 1, 1]))
            if "baseColorTexture" in pbr:
                out.image = self.image(pbr["baseColorTexture"]["index"])
            out.metallic = float(pbr.get("metallicFactor", 1.0 if "metallicRoughnessTexture" not in pbr else 0.5))
            out.roughness = float(pbr.get("roughnessFactor", 1.0 if "metallicRoughnessTexture" not in pbr else 0.6))
            if "metallicRoughnessTexture" in pbr:  # texture dropped: keep a middle value
                out.metallic, out.roughness = min(out.metallic, 0.4), max(out.roughness, 0.5)
        if m.get("emissiveFactor") and any(m["emissiveFactor"]):
            out.emissive = list(m["emissiveFactor"])
            if "emissiveTexture" in m:
                out.emissive_image = self.image(m["emissiveTexture"]["index"])
        out.blend = m.get("alphaMode") == "BLEND" or (m.get("extensions") or {}).get("KHR_materials_transmission") \
            is not None
        out.double_sided = bool(m.get("doubleSided"))
        return out

    @staticmethod
    def local(node):
        if "matrix" in node:
            return np.array(node["matrix"], dtype=float).reshape(4, 4).T
        t = np.array(node.get("translation", [0, 0, 0]), dtype=float)
        x, y, z, w = node.get("rotation", [0, 0, 0, 1])
        s = np.array(node.get("scale", [1, 1, 1]), dtype=float)
        r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                      [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                      [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        m = np.eye(4)
        m[:3, :3] = r * s
        m[:3, 3] = t
        return m

    def parts(self, skip=()):
        out = []
        scene = self.g["scenes"][self.g.get("scene", 0)]
        stack = [(i, np.eye(4)) for i in scene["nodes"]]
        while stack:
            index, parent = stack.pop()
            node = self.g["nodes"][index]
            world = parent @ self.local(node)
            stack += [(c, world) for c in node.get("children", [])]
            if "mesh" not in node or any(s in (node.get("name") or "") for s in skip):
                continue
            normal_m = np.linalg.inv(world[:3, :3]).T
            for k, prim in enumerate(self.g["meshes"][node["mesh"]]["primitives"]):
                if prim.get("mode", 4) != 4:
                    continue
                a = prim["attributes"]
                P = self.accessor(a["POSITION"]) @ world[:3, :3].T + world[:3, 3]
                N = (self.accessor(a["NORMAL"]) @ normal_m.T) if "NORMAL" in a else None
                if N is not None:
                    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
                U = self.accessor(a["TEXCOORD_0"]) if "TEXCOORD_0" in a else None
                I = (self.accessor(prim["indices"]).ravel().astype(np.int64) if "indices" in prim
                     else np.arange(len(P)))
                if np.linalg.det(world[:3, :3]) < 0:  # a mirroring transform flips the winding
                    I = I.reshape(-1, 3)[:, ::-1].ravel()
                out.append(Part(f"{node.get('name', 'mesh')}/{k}", P, N, U, I,
                                self.material(prim.get("material"))))
        return out


def mesh_part(name, mesh, color, *, emissive=None, roughness=0.6, metallic=0.0):
    """A plain-colour part from an f02_barriers.Mesh (hex colour)."""
    from f02_barriers import linear
    return Part(name, np.array(mesh.p, dtype=float), np.array(mesh.n, dtype=float), None,
                np.array(mesh.i, dtype=np.int64),
                Material(name, color=linear(color), emissive=emissive, roughness=roughness, metallic=metallic))


def quad_part(name, image, centre, width, height, facing=(0, 0, 1), *, emissive=None):
    """A textured rectangle (a sign face) centred at `centre`, facing +Z or -Z or +X / -X."""
    cx, cy, cz = centre
    hw, hh = width / 2, height / 2
    fx, _, fz = facing
    if fz:   # in the X-Y plane
        s = 1 if fz > 0 else -1
        P = [(cx - s * hw, cy - hh, cz), (cx + s * hw, cy - hh, cz), (cx + s * hw, cy + hh, cz), (cx - s * hw, cy + hh, cz)]
    else:    # in the Z-Y plane
        s = 1 if fx > 0 else -1
        P = [(cx, cy - hh, cz + s * hw), (cx, cy - hh, cz - s * hw), (cx, cy + hh, cz - s * hw), (cx, cy + hh, cz + s * hw)]
    U = [(0, 1), (1, 1), (1, 0), (0, 0)]
    return Part(name, np.array(P, dtype=float), np.array([facing] * 4, dtype=float), np.array(U, dtype=float),
                np.array([0, 1, 2, 0, 2, 3]), Material(name, image=image, emissive=emissive, roughness=0.5))


def text_image(lines, bg, fg, size=(512, 256), font_px=96, symbol=None, area=None):
    """A sign face: background colour, bold centred text lines (PIL default font scaled via a TrueType face)."""
    from PIL import ImageDraw, ImageFont
    pic = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(pic)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", font_px)
    except OSError:
        font = ImageFont.load_default()
    heights = [draw.textbbox((0, 0), t, font=font)[3] - draw.textbbox((0, 0), t, font=font)[1] for t in lines]
    total = sum(heights) + (len(lines) - 1) * font_px * 0.25
    top, bottom = area or ((0.58, 0.96) if symbol else (0.0, 1.0))  # below the symbol when there is one
    y = size[1] * top + (size[1] * (bottom - top) - total) / 2
    for text, h in zip(lines, heights):
        box = draw.textbbox((0, 0), text, font=font)
        draw.text(((size[0] - (box[2] - box[0])) / 2 - box[0], y - box[1]), text, fill=fg, font=font)
        y += h + font_px * 0.25
    if symbol:
        symbol(draw, pic.size)
    return pic


class Writer:
    def __init__(self, root):
        self.bin = bytearray()
        self.g = {"asset": {"version": "2.0", "generator": "safety_models.py"}, "scene": 0,
                  "scenes": [{"nodes": [0]}], "nodes": [{"name": root, "children": []}], "meshes": [],
                  "materials": [], "textures": [], "images": [], "accessors": [], "bufferViews": [],
                  "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}]}
        self.image_cache = {}

    def view(self, payload, target=None):
        while len(self.bin) % 4:
            self.bin.append(0)
        entry = {"buffer": 0, "byteOffset": len(self.bin), "byteLength": len(payload)}
        if target:
            entry["target"] = target
        self.bin += payload
        self.g["bufferViews"].append(entry)
        return len(self.g["bufferViews"]) - 1

    def accessor(self, array, kind, target, minmax=False):
        array = np.ascontiguousarray(array)
        comp = 5125 if array.dtype == np.uint32 else 5126
        entry = {"bufferView": self.view(array.tobytes(), target), "componentType": comp, "count": len(array),
                 "type": kind}
        if minmax:
            entry["min"], entry["max"] = array.min(0).tolist(), array.max(0).tolist()
        self.g["accessors"].append(entry)
        return len(self.g["accessors"]) - 1

    def texture(self, image, max_size, alpha):
        key = (id(image), max_size, alpha)
        if key not in self.image_cache:
            pic = image.convert("RGBA" if alpha else "RGB")
            if max(pic.size) > max_size:
                scale = max_size / max(pic.size)
                pic = pic.resize((max(1, round(pic.size[0] * scale)), max(1, round(pic.size[1] * scale))),
                                 Image.LANCZOS)
            buffer = io.BytesIO()
            if alpha:
                pic.save(buffer, "PNG", optimize=True)
                mime = "image/png"
            else:
                pic.save(buffer, "JPEG", quality=86)
                mime = "image/jpeg"
            self.g["images"].append({"bufferView": self.view(buffer.getvalue()), "mimeType": mime})
            self.g["textures"].append({"sampler": 0, "source": len(self.g["images"]) - 1})
            self.image_cache[key] = len(self.g["textures"]) - 1
        return self.image_cache[key]

    def add(self, part, role, max_texture=512):
        m = part.material
        material = {"name": role, "pbrMetallicRoughness": {"baseColorFactor": [round(c, 5) for c in m.color],
                                                          "metallicFactor": m.metallic,
                                                          "roughnessFactor": m.roughness},
                    # The facility 3D view shows a model's own materials only when they are marked authored.
                    "extras": {"facilityAuthoredFinish": True, "facilityMaterialRole": role}}
        if m.blend:
            material["alphaMode"] = "BLEND"
            if material["pbrMetallicRoughness"]["baseColorFactor"][3] > 0.6:
                material["pbrMetallicRoughness"]["baseColorFactor"][3] = 0.35
        if m.double_sided:
            material["doubleSided"] = True
        has_uv = part.U is not None and (m.image is not None or m.emissive_image is not None)
        if has_uv and m.image is not None:
            material["pbrMetallicRoughness"]["baseColorTexture"] = {
                "index": self.texture(m.image, max_texture, m.blend)}
        if m.emissive:
            material["emissiveFactor"] = [round(c, 4) for c in m.emissive[:3]]
            if has_uv and m.emissive_image is not None:
                material["emissiveTexture"] = {"index": self.texture(m.emissive_image, max_texture, False)}
        self.g["materials"].append(material)
        N = part.N
        if N is None:  # flat normals from the triangles
            N = np.zeros_like(part.P)
            tri = part.I.reshape(-1, 3)
            fn = np.cross(part.P[tri[:, 1]] - part.P[tri[:, 0]], part.P[tri[:, 2]] - part.P[tri[:, 0]])
            for k in range(3):
                np.add.at(N, tri[:, k], fn)
            N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
        used, I = np.unique(part.I, return_inverse=True)
        attributes = {"POSITION": self.accessor(part.P[used].astype(np.float32), "VEC3", 34962, True),
                      "NORMAL": self.accessor(N[used].astype(np.float32), "VEC3", 34962)}
        if has_uv:
            attributes["TEXCOORD_0"] = self.accessor(part.U[used].astype(np.float32), "VEC2", 34962)
        prim = {"attributes": attributes, "indices": self.accessor(I.astype(np.uint32), "SCALAR", 34963),
                "material": len(self.g["materials"]) - 1, "mode": 4}
        self.g["meshes"].append({"name": role, "primitives": [prim]})
        self.g["nodes"].append({"name": role, "mesh": len(self.g["meshes"]) - 1})
        self.g["nodes"][0]["children"].append(len(self.g["nodes"]) - 1)

    def bytes(self):
        while len(self.bin) % 4:
            self.bin.append(0)
        self.g["buffers"] = [{"byteLength": len(self.bin)}]
        for key in ("textures", "images"):
            if not self.g[key]:
                del self.g[key]
        if "textures" not in self.g:
            del self.g["samplers"]
        text = json.dumps(self.g, separators=(",", ":")).encode()
        text += b" " * (-len(text) % 4)
        body = (struct.pack("<II", len(text), 0x4E4F534A) + text + struct.pack("<II", len(self.bin), 0x004E4942)
                + bytes(self.bin))
        return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body


def bounds(parts):
    P = np.vstack([p.P for p in parts])
    return P.min(0), P.max(0)


def transform(parts, R=np.eye(3), scale=1.0):
    """Rotate, scale, then put the footprint centre at x = z = 0 and the base at y = 0."""
    for p in parts:
        p.P = p.P @ R.T * scale
        if p.N is not None:
            p.N = p.N @ R.T
            if np.linalg.det(R) < 0:
                p.I = p.I.reshape(-1, 3)[:, ::-1].ravel()
    lo, hi = bounds(parts)
    shift = np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
    for p in parts:
        p.P = p.P - shift
    return parts


def rot_y(degrees):
    a = np.radians(degrees)
    return np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])


def rot_x(degrees):
    a = np.radians(degrees)
    return np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])


def offset(parts, d):
    for p in parts:
        p.P = p.P + np.array(d, dtype=float)
    return parts
