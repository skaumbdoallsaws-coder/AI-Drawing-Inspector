"""Small header/chunk checks for worker-produced pictures; the host never decodes pixels."""
import struct
import zlib

from .errors import ModelImportError
from .limits import PREVIEW_BYTES, THUMBNAIL_BYTES
from .validation import require


def validate_picture(data: bytes, kind: str) -> None:
    try:
        if kind == "preview":
            require(len(data) <= PREVIEW_BYTES and data[:8] == b"\x89PNG\r\n\x1a\n", "model_worker_failed")
            offset, seen, color = 8, [], None
            while offset < len(data):
                length, tag = struct.unpack_from(">I4s", data, offset)
                end = offset + 12 + length
                require(end <= len(data), "model_worker_failed")
                body = data[offset + 8:offset + 8 + length]
                crc = struct.unpack_from(">I", data, offset + 8 + length)[0]
                require(zlib.crc32(tag + body) & 0xffffffff == crc, "model_worker_failed")
                if not seen:
                    require(tag == b"IHDR" and length == 13, "model_worker_failed")
                    w, h, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", body)
                    require((w, h, depth) == (768, 768, 8) and color in (2, 3)
                            and (compression, filtering, interlace) == (0, 0, 0), "model_worker_failed")
                elif tag == b"IHDR":
                    raise ModelImportError("model_worker_failed")
                if tag == b"IEND":
                    require(length == 0 and end == len(data), "model_worker_failed")
                seen.append(tag)
                offset = end
            require(seen[-1:] == [b"IEND"] and b"IDAT" in seen
                    and (color != 3 or b"PLTE" in seen), "model_worker_failed")
        else:
            require(kind == "thumbnail" and len(data) <= THUMBNAIL_BYTES and data[:4] == b"RIFF"
                    and data[8:12] == b"WEBP", "model_worker_failed")
            require(struct.unpack_from("<I", data, 4)[0] + 8 == len(data), "model_worker_failed")
            # The worker writes a single lossy, RGB, metadata-free frame.
            require(data[12:16] == b"VP8 ", "model_worker_failed")
            length = struct.unpack_from("<I", data, 16)[0]
            require(20 + length + (length & 1) == len(data) and data[23:26] == b"\x9d\x01\x2a"
                    and not data[20] & 1, "model_worker_failed")
            width, height = struct.unpack_from("<HH", data, 26)
            require((width & 0x3fff, height & 0x3fff) == (256, 256), "model_worker_failed")
    except (IndexError, struct.error, ValueError):
        raise ModelImportError("model_worker_failed") from None
