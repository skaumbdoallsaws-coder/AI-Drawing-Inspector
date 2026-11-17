"""Print constants and bounded PNG checks, without numerical or imaging imports."""
import hashlib
import struct
import zlib

MIN_FONT_SIZE = 4
MAX_FONT_SIZE = 4096


class BarcodeRandom:
    """An independent versioned stream; decorative bars never use global random."""
    def __init__(self, seed):
        self.seed, self.counter = seed, 0

    def width(self):
        value = f"model-builder-1:barcode:{self.seed}:{self.counter}".encode("ascii")
        self.counter += 1
        return 1 + hashlib.sha256(value).digest()[0] % 4


def item_bounds(item, size):
    """Declared drawing extent in panel fractions; circle radius is a width fraction."""
    for key in ("box", "rect", "barcode", "stripes"):
        if key in item:
            return item[key]
    if "dots" in item:
        return item["dots"]["area"]
    if "circle" in item:
        u, v, radius = item["circle"]
        ry = radius * size[0] / size[1]
        return [u-radius, v-ry, u+radius, v+ry]
    a, b, c, d = item["line"]
    # Lines have a centred stroke. Rect/circle outlines are drawn inward.
    dx, dy = (item["lineMm"] / (2000*s) for s in size)
    return [min(a, c)-dx, min(b, d)-dy, max(a, c)+dx, max(b, d)+dy]


def outside_panel(item, size):
    a, b, c, d = item_bounds(item, size)
    return a < -1e-9 or b < -1e-9 or c > 1+1e-9 or d > 1+1e-9


def png_dimensions(data):
    """Accept only bounded metadata-free, non-interlaced RGB PNGs made by prints.

    Hashing alone does not validate a worker-supplied image. Check chunks, CRCs
    and the exact bounded decoded scanline size without loading Pillow in hosts.
    """
    if not isinstance(data, bytes) or len(data) > 4*1024*1024 + 65536 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Invalid print PNG")
    offset, width, height, seen_end, chunks = 8, 0, 0, False, 0
    compressed = bytearray()
    while offset < len(data):
        chunks += 1
        if chunks > 256:
            raise ValueError("Too many print PNG chunks")
        if len(data)-offset < 12:
            raise ValueError("Truncated print PNG")
        length, kind = struct.unpack_from(">I4s", data, offset)
        end = offset + 12 + length
        if end > len(data) or kind not in (b"IHDR", b"IDAT", b"IEND"):
            raise ValueError("Unsupported print PNG chunk")
        chunk = data[offset+8:end-4]
        if zlib.crc32(kind+chunk) & 0xffffffff != struct.unpack_from(">I", data, end-4)[0]:
            raise ValueError("Invalid print PNG CRC")
        if kind == b"IHDR":
            if offset != 8 or length != 13 or chunk[8:] != b"\x08\x02\x00\x00\x00":
                raise ValueError("Invalid print PNG header")
            width, height = struct.unpack_from(">II", chunk)
            if not (1 <= width <= 1024 and 1 <= height <= 1024 and max(width, height) >= 64):
                raise ValueError("Invalid print PNG size")
        elif kind == b"IDAT":
            if not width or seen_end:
                raise ValueError("Invalid print PNG order")
            compressed.extend(chunk)
        else:
            if length or not compressed or end != len(data):
                raise ValueError("Invalid print PNG end")
            seen_end = True
        offset = end
    if not seen_end:
        raise ValueError("Incomplete print PNG")
    stride = 3*width+1
    decoder = zlib.decompressobj()
    try:
        pixels = decoder.decompress(compressed, stride*height+1)
    except zlib.error:
        raise ValueError("Invalid print PNG pixels") from None
    if (len(pixels) != stride*height or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail
            or any(pixels[i] > 4 for i in range(0, len(pixels), stride))):
        raise ValueError("Invalid print PNG scanlines")
    return width, height
