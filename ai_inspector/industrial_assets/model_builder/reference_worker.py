"""Decode untrusted reference pictures inside the limited private worker."""
from hashlib import sha256
from io import BytesIO
import sys
import warnings

from .errors import ModelBuildError, json_bytes, parse_json, require
from .job_io import directory, file_path, read_bytes

MAX_SOURCE = 25 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_PAGE_BYTES = 4 * 1024 * 1024
MAX_OUTPUT = 40 * 1024 * 1024


def _image(raw):
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as source:
                require(source.format in {"PNG", "JPEG", "WEBP"} and
                        getattr(source, "n_frames", 1) == 1, "$.source", "Use one PNG, JPEG or WebP frame",
                        "reference_invalid")
                require(0 < source.width * source.height <= MAX_PIXELS,
                        "$.source", "The image exceeds 40 megapixels", "reference_limit")
                source.load()
                oriented = ImageOps.exif_transpose(source).convert("RGBA")
                if oriented.getchannel("A").getextrema()[0] == 255:
                    oriented = oriented.convert("RGB")  # no transparency: a quarter fewer bytes to store
                oriented.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
                clean = Image.frombytes(oriented.mode, oriented.size, oriented.tobytes())
                return _fit_png(clean, MAX_PAGE_BYTES)
    except ModelBuildError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ModelBuildError("reference_limit", "$.source", "The image exceeds 40 megapixels") from error
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, EOFError) as error:
        raise ModelBuildError("reference_invalid", "$.source", "The image could not be decoded safely") from error


def _fit_png(image, limit):
    """Encode a metadata-free PNG within limit bytes. Phone photos compress poorly as PNG (about 5-6 MB at
    2048 px), so the long side shrinks 15 % a step, always resampled from the full image, until it fits."""
    from PIL import Image
    scale = 1.0
    while True:
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        current = image if scale == 1.0 else image.resize(size, Image.Resampling.LANCZOS)
        buffer = BytesIO()
        current.save(buffer, format="PNG")
        if len(buffer.getvalue()) <= limit:
            return buffer.getvalue(), current.size
        require(max(size) > 512, "$.source", "The image is too detailed to store", "reference_limit")
        scale *= 0.85


def _pdf(raw):
    try:
        import fitz
    except ImportError as error:
        raise ModelBuildError("reference_pdf_unavailable", "$.source",
                              "PDF reading is not available in the trusted worker runtime") from error
    try:
        document = fitz.open(stream=raw, filetype="pdf")
        try:
            require(not document.needs_pass, "$.source", "Encrypted PDFs are not supported", "reference_invalid")
            require(0 < document.page_count <= 10000, "$.source", "Invalid PDF page count", "reference_invalid")
            result = []
            total = 0
            for index in range(min(document.page_count, 20)):
                page = document.load_page(index)
                scale = min(2, 1600/max(page.rect.width, page.rect.height))
                require(scale > 0, "$.source", "Invalid PDF page geometry", "reference_invalid")
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                require(pix.width * pix.height <= MAX_PIXELS and max(pix.width, pix.height) <= 1600,
                        "$.source", "PDF page exceeds its pixel limit", "reference_limit")
                from PIL import Image
                clean = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                buffer = BytesIO()
                clean.save(buffer, format="PNG")
                data = buffer.getvalue()
                require(len(data) <= MAX_PAGE_BYTES, "$.source", "PDF page exceeds 4 MB", "reference_limit")
                total += len(data)
                require(total <= MAX_OUTPUT, "$.source", "PDF pages exceed 40 MB", "reference_limit")
                excerpt = page.get_text("text").encode("utf-8")[:16384].decode("utf-8", "ignore")
                result.append((data, clean.size, excerpt))
            return document.page_count, result
        finally:
            document.close()
    except ModelBuildError:
        raise
    except (ValueError, RuntimeError, OSError, OverflowError, MemoryError) as error:
        raise ModelBuildError("reference_invalid", "$.source", "The PDF could not be decoded safely") from error


def execute_reference(job_dir):
    require(not any(name == "ai_inspector" or name.startswith("ai_inspector.") for name in sys.modules),
            "$", "Application parents must not enter the reference worker", "job_invalid")
    job = directory(job_dir)
    request = parse_json(read_bytes(job, "request.json", 1024), 1024)
    require(type(request) is dict and set(request) == {"pdf"} and type(request["pdf"]) is bool,
            "$.request", "Invalid reference job request", "job_invalid")
    raw = read_bytes(job, "source.bin", MAX_SOURCE)
    require(bool(raw), "$.source", "Empty reference file", "reference_invalid")
    if request["pdf"]:
        page_count, pages = _pdf(raw)
        kind = "pdf"
    else:
        data, size = _image(raw)
        pages, page_count, kind = [(data, size, "")], 1, "image"
    target = job / "pages"
    target.mkdir()
    rows = []
    for index, (data, (width, height), excerpt) in enumerate(pages):
        require(len(data) <= MAX_PAGE_BYTES, "$.source", "Reference page exceeds 4 MB", "reference_limit")
        with file_path(target, str(index) + ".png").open("xb") as stream:
            stream.write(data)
        rows.append({"page": index, "sha256": sha256(data).hexdigest(), "bytes": len(data),
                     "width": width, "height": height, "text": excerpt})
    record = {"kind": kind, "pages": page_count, "renderedPages": rows,
              "sourceSha256": sha256(raw).hexdigest()}
    with file_path(job, "result.json").open("xb") as stream:
        stream.write(json_bytes(record))
    require(not any(name == "ai_inspector" or name.startswith("ai_inspector.") for name in sys.modules),
            "$", "Application parents must not enter the reference worker", "job_invalid")
