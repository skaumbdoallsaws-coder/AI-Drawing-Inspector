"""Bounded, principal-scoped image import for facility decals."""
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
import re
import tempfile
import warnings

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from .authorization import require_facility_action
from .errors import FacilityLayoutError
from .repository import _native_fs_path

MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 20_000_000


def normalize_image(payload):
    if not payload or len(payload) > MAX_BYTES:
        raise ValueError("Choose a PNG or JPEG image smaller than 10 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(payload)) as source:
                if source.format not in ("PNG", "JPEG") or getattr(source, "n_frames", 1) != 1:
                    raise ValueError("Choose a single-frame PNG or JPEG image.")
                if source.width * source.height > MAX_PIXELS or max(source.size) > 16384:
                    raise ValueError("Image exceeds the 20-megapixel import limit.")
                source.load()
                rgba = ImageOps.exif_transpose(source).convert("RGBA")
                rgba.thumbnail((4096, 4096), Image.Resampling.LANCZOS)
                bounds = rgba.getchannel("A").point(lambda v: 255 if v > 2 else 0).getbbox()
                if not bounds:
                    raise ValueError("Image is fully transparent.")
                w, h = rgba.size
                left, top, right, bottom = bounds
                left, top, right, bottom = max(0, left-2), max(0, top-2), min(w, right+2), min(h, bottom+2)
                # Recreate pixels without EXIF, comments, or other imported metadata.
                clean = Image.frombytes("RGBA", rgba.size, rgba.tobytes())
                output = BytesIO()
                clean.save(output, format="PNG")
                return output.getvalue(), {"width": w, "height": h,
                    "uv": [left/w, 1-bottom/h, right/w, 1-top/h]}
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("The image could not be decoded safely. Choose a PNG or JPEG.") from exc


def scope_directory(root, principal, site_id):
    # Hashed scope components avoid filesystem-sensitive principal/site names.
    scope = sha256((principal.tenant_id + "\0" + site_id).encode()).hexdigest()
    return Path(_native_fs_path(Path(root) / scope))


def store_image(root, principal, site_id, payload):
    content, metadata = normalize_image(payload)
    digest = sha256(content).hexdigest()
    folder = scope_directory(root, principal, site_id)
    folder.mkdir(parents=True, exist_ok=True)
    target = Path(_native_fs_path(folder / (digest + ".png")))
    if not target.exists():
        fd, temporary = tempfile.mkstemp(prefix="image-", suffix=".tmp", dir=folder)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return dict(metadata, imagePath=f"/api/facility-decal-images/{site_id}/{digest}.png")


def create_decal_image_router(*, service, principal_resolver, feature_gate=None):
    router = APIRouter()
    root = service.layout_repository.root / "decal-images"

    def error_response(error):
        return JSONResponse(status_code=error.status_code, content={"error": error.to_dict()})

    @router.post("/api/facility-layouts/{site_id}/{layout_id}/decal-images")
    async def import_image(site_id: str, layout_id: str, request: Request):
        try:
            if feature_gate:
                feature_gate("manual_edit")
            principal = principal_resolver(request)
            require_facility_action(principal, tenant_id=principal.tenant_id, site_id=site_id, action="layout.edit")
            await run_in_threadpool(service.get_layout, principal, site_id, layout_id)
            if request.headers.get("content-type", "").split(";")[0] not in ("image/png", "image/jpeg"):
                raise FacilityLayoutError("invalid_decal_image", "Choose a PNG or JPEG image.", status_code=415)
            payload = bytearray()
            async for chunk in request.stream():
                if len(payload) + len(chunk) > MAX_BYTES:
                    raise FacilityLayoutError("decal_image_too_large", "Image exceeds the 10 MB limit.", status_code=413)
                payload.extend(chunk)
            return await run_in_threadpool(store_image, root, principal, site_id, bytes(payload))
        except ValueError as exc:
            return error_response(FacilityLayoutError("invalid_decal_image", str(exc)))
        except FacilityLayoutError as exc:
            return error_response(exc)

    @router.get("/api/facility-decal-images/{site_id}/{digest}.png")
    async def get_image(site_id: str, digest: str, request: Request):
        try:
            principal = principal_resolver(request)
            require_facility_action(principal, tenant_id=principal.tenant_id, site_id=site_id, action="layout.read")
            if not re.fullmatch(r"[a-f0-9]{64}", digest):
                raise FacilityLayoutError("decal_image_missing", "Image was not found.", status_code=404)
            path = Path(_native_fs_path(scope_directory(root, principal, site_id) / (digest + ".png")))
            if not path.is_file():
                raise FacilityLayoutError("decal_image_missing", "Image was not found.", status_code=404)
            return FileResponse(path, media_type="image/png", headers={
                "Cache-Control": "private, no-cache", "X-Content-Type-Options": "nosniff"})
        except FacilityLayoutError as exc:
            return error_response(exc)

    return router
