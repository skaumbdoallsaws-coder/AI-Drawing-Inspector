"""Bounded containers and virtual resource names: zip entries are never extracted."""
from dataclasses import dataclass, field
from io import BytesIO
import re
import stat
import struct
import zipfile
import zlib

from .errors import ModelImportError
from .limits import DEFAULT_LIMITS, Limits
from .validation import parse_json, require

_TEXT = (".md", ".txt")


def is_text(name: str) -> bool:
    leaf = name.rsplit("/", 1)[-1].casefold()
    return leaf.startswith(("license", "readme")) or leaf.endswith(_TEXT)


def _safe_segments(name: str, *, relative: bool = False) -> list[str]:
    code = "gltf_external_resource" if relative else "zip_unsafe"
    require(isinstance(name, str) and 0 < len(name) <= 1024, code)
    name = name.replace("\\", "/")
    require(not name.startswith("/") and ":" not in name
            and not any(ord(c) < 32 or ord(c) == 127 for c in name), code)
    parts = name.split("/")
    if not relative:
        require(all(p not in {"", ".", ".."} for p in parts), code)
    return parts


def _decode_uri(uri: str) -> str:
    require(isinstance(uri, str) and len(uri) <= 4096, "gltf_external_resource")
    require(not any(c in uri for c in "?#"), "gltf_external_resource")
    data = bytearray()
    index = 0
    while index < len(uri):
        char = uri[index]
        if char == "%":
            require(index + 2 < len(uri) and re.fullmatch("[0-9a-fA-F]{2}", uri[index + 1:index + 3]),
                    "gltf_external_resource")
            data.append(int(uri[index + 1:index + 3], 16))
            index += 3
        else:
            try:
                data.extend(char.encode("utf-8"))
            except UnicodeError:
                raise ModelImportError("gltf_external_resource") from None
            index += 1
    try:
        return data.decode("utf-8")
    except UnicodeError:
        raise ModelImportError("gltf_external_resource") from None


@dataclass
class Container:
    document: dict
    binary: bytes | None
    entries: dict[str, bytes]
    model_name: str
    format: str
    texts: list[tuple[str, str]]
    used_entries: set[str] = field(default_factory=set)

    def resource(self, uri: str) -> bytes:
        # A GLB must be self-contained even when wrapped in a zip.
        require(self.format == "gltf-zip", "gltf_external_resource")
        segments = _safe_segments(_decode_uri(uri), relative=True)
        resolved = self.model_name.split("/")[:-1]
        for segment in segments:
            if segment in {"", "."}:
                continue
            if segment == "..":
                require(bool(resolved), "gltf_external_resource")
                resolved.pop()
            else:
                resolved.append(segment)
        key = "/".join(resolved)
        require(key in self.entries, "gltf_invalid")
        self.used_entries.add(key)
        return self.entries[key]

    def validate_resources(self) -> None:
        allowed = self.used_entries | {self.model_name} | {name for name, _ in self.texts}
        require(set(self.entries) <= allowed, "model_format_unsupported")


def _glb(payload: bytes, limits: Limits) -> tuple[dict, bytes | None]:
    require(len(payload) >= 20)
    magic, version, length = struct.unpack_from("<4sII", payload)
    require(magic == b"glTF" and version == 2 and length == len(payload))
    offset, document, binary = 12, None, None
    while offset < len(payload):
        require(offset + 8 <= len(payload))
        size, kind = struct.unpack_from("<II", payload, offset)
        offset += 8
        require(size % 4 == 0 and offset + size <= len(payload))
        if document is None:
            require(kind == 0x4E4F534A and size > 0)
            document = parse_json(payload[offset:offset + size], limits.json_bytes)
        else:
            require(kind == 0x004E4942 and binary is None)
            binary = payload[offset:offset + size]
        offset += size
    require(document is not None)
    return document, binary


def _zip_entries(payload: bytes, limits: Limits) -> dict[str, bytes]:
    entries, seen, expanded, texts = {}, set(), 0, 0
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            infos = archive.infolist()
            require(len(infos) <= limits.zip_entries, "zip_too_large")
            declared = 0
            for info in infos:
                original = info.orig_filename
                is_dir = original.endswith(("/", "\\"))
                name = "/".join(_safe_segments(original[:-1] if is_dir else original))
                require(name.casefold() not in seen, "zip_unsafe")
                seen.add(name.casefold())
                mode = info.external_attr >> 16
                require(stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR), "zip_unsafe")
                require(not info.flag_bits & 1 and info.compress_type in
                        (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), "zip_unsafe")
                require(info.file_size >= 0 and info.compress_size >= 0, "zip_unsafe")
                declared += info.file_size
                require(declared <= limits.zip_bytes and info.file_size <=
                        max(1, info.compress_size) * limits.zip_ratio, "zip_too_large")
                if is_dir:
                    require(info.file_size == 0, "zip_unsafe")
                    continue
                text = is_text(name)
                if text:
                    texts += 1
                    require(texts <= limits.text_files and info.file_size <= limits.text_bytes, "zip_too_large")
                content = bytearray()
                with archive.open(info) as stream:
                    while True:
                        block = stream.read(64 * 1024)
                        if not block:
                            break
                        expanded += len(block)
                        require(expanded <= limits.zip_bytes and len(content) + len(block) <= info.file_size,
                                "zip_too_large")
                        content.extend(block)
                require(len(content) == info.file_size, "zip_unsafe")
                entries[name] = bytes(content)
    except ModelImportError:
        raise
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, RuntimeError, ValueError,
            EOFError, NotImplementedError, UnicodeError, zlib.error):
        raise ModelImportError("zip_unsafe") from None
    # Also refuse file/directory aliases such as a file 'textures' plus 'textures/a.png'.
    file_keys = {p.casefold() for p in entries}
    for name in entries:
        parent = name.rsplit("/", 1)[0] if "/" in name else ""
        while parent:
            require(parent.casefold() not in file_keys, "zip_unsafe")
            parent = parent.rsplit("/", 1)[0] if "/" in parent else ""
    return entries


def open_container(payload: bytes, limits: Limits = DEFAULT_LIMITS) -> Container:
    require(isinstance(payload, bytes), "model_format_unsupported")
    require(len(payload) <= limits.upload_bytes, "model_too_large")
    if payload.startswith(b"glTF"):
        document, binary = _glb(payload, limits)
        return Container(document, binary, {}, "model.glb", "glb", [])
    require(payload.startswith(b"PK"), "model_format_unsupported")
    entries = _zip_entries(payload, limits)
    models = [p for p in entries if p.lower().endswith((".gltf", ".glb"))]
    require(len(models) == 1, "model_format_unsupported")
    model_name = models[0]
    texts = [(p, data.decode("utf-8-sig", errors="replace")) for p, data in entries.items() if is_text(p)]
    if model_name.lower().endswith(".glb"):
        document, binary = _glb(entries[model_name], limits)
        return Container(document, binary, entries, model_name, "glb-zip", texts)
    document = parse_json(entries[model_name], limits.json_bytes)
    return Container(document, None, entries, model_name, "gltf-zip", texts)
