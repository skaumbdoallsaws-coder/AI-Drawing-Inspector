"""Generate bounded wall-lettering assets without granting model filesystem access."""
from io import BytesIO

from ai_inspector.facility_layout.authorization import require_facility_action
from ai_inspector.facility_layout.decals import normalize_lettering
from ai_inspector.facility_layout.decal_images import store_image
from ai_inspector.facility_layout.errors import FacilityValidationError


def tool_specs():
    return [{"name": "prepare_facility_lettering", "read_only": False, "description":
        "Render transparent wall lettering into the authorized site's image store. This creates only an image asset, "
        "never a layout edit. Use the returned imagePath, uv and lettering in an upsert_decal preview on an inspected wall. "
        "The aspect ratio must match the intended wall region. This tool cannot open files or import arbitrary paths.",
        "input_schema": {"type": "object", "additionalProperties": False,
            "required": ["lettering", "aspectRatio"], "properties": {
                "aspectRatio": {"type": "number", "minimum": .125, "maximum": 8},
                "lettering": {"type": "object", "additionalProperties": False,
                    "required": ["text", "reference", "font", "align", "color"], "properties": {
                        "text": {"type": "string", "minLength": 1, "maxLength": 1000},
                        "reference": {"type": "string", "maxLength": 160},
                        "font": {"enum": ["Arial", "Georgia"]},
                        "align": {"enum": ["left", "center", "right"]},
                        "color": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"}}}}}}]


def render_lettering(settings, aspect):
    from PIL import Image, ImageDraw, ImageFont
    value = normalize_lettering(settings)
    width = round(min(3072, 2048 * aspect))
    height = round(width / aspect)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    font_name = "arialbd.ttf" if value["font"] == "Arial" else "georgiab.ttf"
    def font(size):
        try:
            return ImageFont.truetype(font_name, size)
        except OSError as exc:
            raise FacilityValidationError("lettering_font_unavailable", "The selected lettering font is not installed.") from exc
    def wrap(face):
        lines = []
        for paragraph in value["text"].split("\n"):
            line = ""
            for word in paragraph.split():
                trial = (line + " " + word).strip()
                if line and draw.textlength(trial, font=face) > width - 64:
                    lines.append(line)
                    line = word
                else:
                    line = trial
            lines.append(line)
        return lines
    for size in range(int(min(180, height * .35)), 7, -1):
        face = font(size)
        lines = wrap(face)
        content_height = len(lines) * size * 1.2 + (size * .95 if value["reference"] else 0)
        if content_height <= height - 64 and all(draw.textlength(line, font=face) <= width - 64 for line in lines):
            break
    else:
        raise FacilityValidationError("lettering_too_dense", "Use fewer words or a larger wall region.")
    y = (height - content_height) / 2
    def paint(line, current_font, top):
        length = draw.textlength(line, font=current_font)
        x = 32 if value["align"] == "left" else width - 32 - length if value["align"] == "right" else (width-length)/2
        draw.text((x, top), line, font=current_font, fill=value["color"], anchor="lt")
    for line in lines:
        paint(line, face, y)
        y += size * 1.2
    if value["reference"]:
        reference = value["reference"].replace("\n", " ")
        ref_size = max(6, round(size * .48))
        while ref_size > 6 and draw.textlength(reference, font=font(ref_size)) > width-64:
            ref_size -= 1
        if draw.textlength(reference, font=font(ref_size)) > width-64:
            raise FacilityValidationError("lettering_too_dense", "Shorten the reference for this wall region.")
        paint(reference, font(ref_size), y + size * .25)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue(), value


def prepare_lettering(runtime, principal, reference, arguments):
    from .facility_tools import read_bound_layout
    read_bound_layout(runtime, principal, reference)
    require_facility_action(principal, tenant_id=principal.tenant_id, site_id=reference["siteId"], action="layout.edit")
    runtime.service._require_capability("agent_preview")
    try:
        content, settings = render_lettering(arguments["lettering"], arguments["aspectRatio"])
    except ValueError as exc:
        raise FacilityValidationError("invalid_lettering", str(exc)) from exc
    root = runtime.service.layout_repository.root / "decal-images"
    asset = store_image(root, principal, reference["siteId"], content)
    return dict(asset, lettering=settings, saved=False, engineeringChanges=0, approvalRequired=True)
