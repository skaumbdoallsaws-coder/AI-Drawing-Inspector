"""New artwork references must come from the site's controlled image importer, or be artwork the app ships."""
from collections.abc import Mapping

from .decal_images import scope_directory
from .decals import IMAGE_PATH
from .errors import FacilityValidationError


def image_references(value):
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == "imagePath" and isinstance(item, str):
                yield item
            else:
                yield from image_references(item)
    elif isinstance(value, list):
        for item in value:
            yield from image_references(item)


def shipped_artwork():
    """The fixed images the site planner puts in its designs (the logo on the side walls, the yard crosshair)."""
    from .site_plan import LOGO_IMAGE, TARGET_IMAGE
    return {LOGO_IMAGE, TARGET_IMAGE}


def validate_proposal_artwork(service, principal, site_id, layout, operations):
    known = set(image_references(layout)) | shipped_artwork()
    for path in set(image_references(operations)) - known:
        if not IMAGE_PATH.fullmatch(path) or path.split("/")[3] != site_id:
            raise FacilityValidationError("artwork_import_required",
                "Use an existing layout artwork or import the new image with the app's image upload control first.")
        root = service.layout_repository.root / "decal-images"
        folder = scope_directory(root, principal, site_id)
        target = folder / path.rsplit("/", 1)[1]
        if (folder.is_symlink() or folder.is_junction() or target.is_symlink()
                or not target.is_file() or not 0 < target.stat().st_size <= 10 * 1024 * 1024):
            raise FacilityValidationError("artwork_import_required",
                "The imported image is not available for this site. Import it again before creating a decal.")
