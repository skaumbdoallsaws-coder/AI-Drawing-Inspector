"""Material projection and sequential, bounded image normalization."""
from io import BytesIO
import math
import warnings as image_warnings

import numpy as np
from PIL import Image, UnidentifiedImageError

from .errors import ModelImportError
from .model import ModelImage
from .validation import clean_text, integer, mapping, number, reference, require, sequence, vector, warn

SUPPORTED_EXTENSIONS = {
    "KHR_materials_emissive_strength", "KHR_texture_transform", "KHR_materials_unlit",
    "KHR_materials_pbrSpecularGlossiness", "KHR_mesh_quantization",
}


def check_extensions(document: dict, warnings: list[str]) -> bool:
    used = sequence(document.get("extensionsUsed", []), 256)
    required = sequence(document.get("extensionsRequired", []), 256)
    require(all(isinstance(v, str) and len(v) <= 200 for v in [*used, *required]))
    require(set(required) <= set(used))
    require(set(required) <= SUPPORTED_EXTENSIONS, "gltf_extension_required")
    for name in used:
        if name not in SUPPORTED_EXTENSIONS:
            warn(warnings, "Ignored optional extension: " + name)
    if document.get("animations"):
        warn(warnings, "Animations were omitted; the model uses its rest pose.")
    return "KHR_mesh_quantization" in used


def _texture(info, textures, samplers, images, warnings) -> dict | None:
    if info is None:
        return None
    info = mapping(info)
    texture = mapping(textures[reference(info.get("index"), textures)])
    transform = mapping(mapping(info.get("extensions", {})).get("KHR_texture_transform", {}))
    tex_coord = integer(transform.get("texCoord", info.get("texCoord", 0)), 0)
    if tex_coord != 0:
        warn(warnings, "A base colour texture using a non-zero UV channel was omitted.")
        return None
    if "source" not in texture:
        warn(warnings, "A texture without a supported fallback image was omitted.")
        return None
    image = reference(texture["source"], images)
    sampler = mapping(samplers[reference(texture["sampler"], samplers)]) if "sampler" in texture else {}
    wrap_s, wrap_t = sampler.get("wrapS", 10497), sampler.get("wrapT", 10497)
    require(type(wrap_s) is int and wrap_s in (33071, 33648, 10497))
    require(type(wrap_t) is int and wrap_t in (33071, 33648, 10497))
    for key, allowed in (("magFilter", (9728, 9729)), ("minFilter", (9728, 9729, 9984, 9985, 9986, 9987))):
        if key in sampler:
            require(type(sampler[key]) is int and sampler[key] in allowed)
    return {"image": image, "wrapS": wrap_s, "wrapT": wrap_t,
            "offset": vector(transform.get("offset", [0, 0]), 2),
            "scale": vector(transform.get("scale", [1, 1]), 2),
            "rotation": number(transform.get("rotation", 0))}


def default_material() -> dict:
    return {"name": "", "baseColor": [1.0, 1.0, 1.0, 1.0], "texture": None,
            "alphaMode": "OPAQUE", "alphaCutoff": 0.5, "emissive": [0.0, 0.0, 0.0],
            "doubleSided": False, "roughness": 1.0, "metalness": 1.0, "unlit": False}


def read_materials(document: dict, limits, warnings: list[str], *, extended_materials: bool = False) -> list[dict]:
    textures = sequence(document.get("textures", []), 4096)
    samplers = sequence(document.get("samplers", []), 4096)
    images = sequence(document.get("images", []), limits.images)
    for texture in textures:
        texture = mapping(texture)
        if "source" in texture:
            reference(texture["source"], images)
        if "sampler" in texture:
            reference(texture["sampler"], samplers)
    materials = []
    for raw in sequence(document.get("materials", []), limits.materials):
        raw = mapping(raw)
        extensions = mapping(raw.get("extensions", {}))
        mapping(extensions.get("KHR_materials_unlit", {}))
        pbr = mapping(raw.get("pbrMetallicRoughness", {}))
        legacy = extensions.get("KHR_materials_pbrSpecularGlossiness")
        factor, texture = pbr.get("baseColorFactor", [1, 1, 1, 1]), pbr.get("baseColorTexture")
        roughness, metalness = pbr.get("roughnessFactor", 1), pbr.get("metallicFactor", 1)
        if legacy is not None:
            legacy = mapping(legacy)
            factor, texture = legacy.get("diffuseFactor", [1, 1, 1, 1]), legacy.get("diffuseTexture")
            roughness, metalness = 1 - number(legacy.get("glossinessFactor", 1), 0, 1), 0
            warn(warnings, "Specular-glossiness material was approximated using its diffuse colour and texture.")
        alpha = raw.get("alphaMode", "OPAQUE")
        require(alpha in ("OPAQUE", "MASK", "BLEND"))
        double_sided = raw.get("doubleSided", False)
        require(type(double_sided) is bool)
        emission = vector(raw.get("emissiveFactor", [0, 0, 0]), 3, 0, 1)
        strength = number(mapping(extensions.get("KHR_materials_emissive_strength", {})).get("emissiveStrength", 1), 0)
        emission = [number(value * strength, 0) for value in emission]
        material = {"name": clean_text(raw.get("name")), "baseColor": vector(factor, 4, 0, 1),
                    "texture": _texture(texture, textures, samplers, images, warnings),
                    "alphaMode": alpha, "alphaCutoff": number(raw.get("alphaCutoff", 0.5), 0),
                    "emissive": emission, "doubleSided": double_sided,
                    "roughness": number(roughness, 0, 1), "metalness": number(metalness, 0, 1),
                    "unlit": "KHR_materials_unlit" in extensions}
        if extended_materials:
            from .extended_materials import read_extras
            material.update(read_extras(raw))
            material["emissiveTexture"] = _texture(raw.get("emissiveTexture"), textures, samplers, images, warnings)
            # The flattened Part has one UV channel. Both maps must share its transform.
            base, emission = material["texture"], material["emissiveTexture"]
            if base is not None and emission is not None:
                require(all(base[k] == emission[k] for k in ("offset", "scale", "rotation")),
                        "gltf_texture_unsupported")
            if texture is not None:
                require(base is not None, "gltf_texture_unsupported")
            if raw.get("emissiveTexture") is not None:
                require(emission is not None, "gltf_texture_unsupported")
        omitted_maps = ("normalTexture", "occlusionTexture") if extended_materials else (
            "normalTexture", "occlusionTexture", "emissiveTexture")
        if any(key in raw for key in omitted_maps) or "metallicRoughnessTexture" in pbr:
            warn(warnings, ("Only base colour and emissive textures are retained; other texture maps were omitted."
                            if extended_materials else
                            "Only base colour textures are retained; other texture maps were omitted."))
        materials.append(material)
    return materials


def transform_uv(uv: np.ndarray, texture: dict | None) -> np.ndarray:
    if texture is None:
        return uv.copy()
    angle = texture["rotation"]
    cosine, sine = math.cos(angle), math.sin(angle)
    rotation = np.array([[cosine, -sine], [sine, cosine]])
    with np.errstate(over="ignore", invalid="ignore"):
        result = (uv * texture["scale"]) @ rotation.T + texture["offset"]
    require(bool(np.isfinite(result).all()))
    return result


def _magic(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    raise ModelImportError("image_unsafe")


def read_images(container, accessors, materials, limits, texture_max_px: int = 1024, *, lossless=False) -> list[ModelImage]:
    require(texture_max_px in (256, 512, 1024, 2048))
    alpha_images = {m["texture"]["image"] for m in materials if m["texture"] and m["alphaMode"] != "OPAQUE"}
    output, pixels = [], 0
    for index, raw in enumerate(sequence(container.document.get("images", []), limits.images)):
        raw = mapping(raw)
        require(("uri" in raw) != ("bufferView" in raw))
        data = container.resource(raw["uri"]) if "uri" in raw else accessors.image_bytes(raw["bufferView"])
        expected = _magic(data)
        try:
            with image_warnings.catch_warnings():
                image_warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(data)) as source:
                    width, height = source.size
                    require(source.format == expected and getattr(source, "n_frames", 1) == 1, "image_unsafe")
                    pixels += width * height
                    require(0 < width <= limits.image_side and 0 < height <= limits.image_side
                            and width * height <= limits.image_pixels and pixels <= limits.total_image_pixels,
                            "image_unsafe")
                    if expected == "JPEG":
                        source.draft("RGB", (texture_max_px, texture_max_px))
                    source.thumbnail((texture_max_px, texture_max_px), Image.Resampling.LANCZOS)
                    mode = "RGBA" if index in alpha_images else "RGB"
                    with source.convert(mode) as resized:
                        alpha_used = mode == "RGBA" and resized.getextrema()[3] != (255, 255)
                        with BytesIO() as stream:
                            if alpha_used or lossless:
                                # A fresh image drops all source metadata.
                                with Image.frombytes(mode, resized.size, resized.tobytes()) as clean:
                                    clean.save(stream, format="PNG")
                                mime = "image/png"
                            else:
                                with resized.convert("RGB") as rgb:
                                    with Image.frombytes("RGB", rgb.size, rgb.tobytes()) as clean:
                                        clean.save(stream, format="JPEG", quality=85)
                                mime = "image/jpeg"
                            output.append(ModelImage(stream.getvalue(), mime, resized.width, resized.height, width, height))
        except ModelImportError:
            raise
        except (OSError, ValueError, SyntaxError, EOFError, UnidentifiedImageError,
                Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise ModelImportError("image_unsafe") from None
    return output
