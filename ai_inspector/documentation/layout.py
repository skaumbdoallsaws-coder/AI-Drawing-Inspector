"""Fixed paper presets and design-to-publication geometry (standard library only)."""
from copy import deepcopy
from dataclasses import dataclass
import math

PAPERS = {"Letter": (612.0, 792.0), "A4": (595.28, 841.89)}
DESIGN = {
    "illustrated_parts_manual": (792.0, 612.0, "landscape"),
    "operations_and_maintenance_manual": (960.0, 540.0, "landscape"),
    "work_instructions": (960.0, 540.0, "landscape"),
    "product_specification_sheet": (612.0, 792.0, "portrait"),
}
_CONTENT = {
    "illustrated_parts_manual": (28.0, 62.0, 736.0, 502.0),
    "operations_and_maintenance_manual": (56.0, 74.0, 848.0, 432.0),
    "work_instructions": (56.0, 74.0, 848.0, 432.0),
    "product_specification_sheet": (36.0, 82.0, 540.0, 654.0),
}


def page_setups(document_type):
    if document_type not in DESIGN:
        return []
    dw, dh, orientation = DESIGN[document_type]
    x, y, w, h = _CONTENT[document_type]
    result = []
    for paper, portrait in PAPERS.items():
        pw, ph = portrait if orientation == "portrait" else portrait[::-1]
        result.append({"id": paper.lower() + "-" + orientation, "paper": paper,
            "orientation": orientation, "page": {"width": pw, "height": ph},
            "margins": {"top": round(y * ph / dh, 2), "right": round((dw-x-w) * pw / dw, 2),
                        "bottom": round((dh-y-h) * ph / dh, 2), "left": round(x * pw / dw, 2)},
            "layoutMode": "fixed"})
    return result


def normalize_page_setup(document_type, value):
    from .commands import DocumentEditError
    def refuse():
        raise DocumentEditError("unsupported_page_setup", "Choose a supported paper preset in this publication's design orientation.")
    if not isinstance(value, dict) or set(value) - {"paper", "orientation", "margins", "layoutMode"}:
        refuse()
    preset = next((p for p in page_setups(document_type)
                   if p["paper"] == value.get("paper") and p["orientation"] == value.get("orientation")), None)
    if preset is None or value.get("layoutMode", "fixed") != "fixed":
        refuse()
    if "margins" in value:
        margins = value["margins"]
        if not isinstance(margins, dict) or set(margins) != set(preset["margins"]):
            refuse()
        if any(type(v) not in (int, float) or not math.isfinite(v)
               or abs(v-preset["margins"][k]) > .01 + 1e-9 for k, v in margins.items()):
            refuse()
    return {k: deepcopy(preset[k]) for k in ("paper", "orientation", "margins", "layoutMode")}


@dataclass(frozen=True)
class Geometry:
    page: dict
    design: dict
    sx: float
    sy: float
    identity: bool

    def x(self, value):
        return value if self.identity else round(value * self.sx, 4)

    def y(self, value):
        return value if self.identity else round(value * self.sy, 4)

    w = x
    h = y

    def rect(self, value):
        if self.identity:
            return value
        if isinstance(value, dict):
            return {**value, **{k: (self.x if k in ("x", "width") else self.y)(value[k])
                               for k in ("x", "y", "width", "height")}}
        return type(value)((self.x(value[0]), self.y(value[1]), self.w(value[2]), self.h(value[3])))

    def fitz_rect(self, x0, y0, x1, y1):
        return (self.x(x0), self.y(y0), self.x(x1), self.y(y1))

    def layout(self, value):
        if self.identity:
            return value
        def walk(item):
            if isinstance(item, dict):
                if {"x", "y", "width", "height"} <= item.keys():
                    return self.rect(item)
                return {k: walk(v) for k, v in item.items()}
            return [walk(v) for v in item] if isinstance(item, list) else item
        result = walk(value)
        result["page"] = {**result["page"], **self.page,
                          "aspectRatio": self.page["width"] / self.page["height"]}
        return result

    def blocks(self, pages):
        """Stretch fixed generated frames, row allocations and column gaps.

        Both fixed compilers emit flat block frames: items/rows have semantic content, not frames.
        columnWidths are fractions; columns/itemNumber are counts; fontSize and style.lineHeight
        are type metrics. None is a design-page length. Capture pixel limits/occupancy and CAD
        transforms are likewise unchanged; only the capture frame and its aspect are page geometry.
        """
        if self.identity:
            return
        for page in pages:
            for block in page.get("layoutBlocks", []):
                if "frame" in block:
                    block["frame"] = self.rect(block["frame"])
                if "rowHeights" in block:
                    block["rowHeights"] = [self.h(v) for v in block["rowHeights"]]
                if "columnGap" in block:
                    block["columnGap"] = self.w(block["columnGap"])
            request = page.get("renderRequest") or {}
            if "frame" in request:
                request["frame"] = self.rect(request["frame"])
                frame = request["frame"]
                caption = 0 if page.get("pageType") == "operations_cover" else 18
                if isinstance(request.get("image"), dict):
                    request["image"]["targetAspectRatio"] = frame["width"] / (frame["height"] - caption)


def geometry(document_type, page_setup=None):
    width, height, orientation = DESIGN[document_type]
    design = {"width": width, "height": height, "orientation": orientation}
    if page_setup is None:
        return Geometry(dict(design), design, 1.0, 1.0, True)
    setup = normalize_page_setup(document_type, page_setup)
    pw, ph = PAPERS[setup["paper"]]
    if orientation == "landscape":
        pw, ph = ph, pw
    return Geometry({"width": pw, "height": ph, "orientation": orientation}, design,
                    pw / width, ph / height, (pw, ph) == (width, height))


def document_geometry(document):
    return geometry(document["documentType"], document.get("pageSetup"))


def page_setup_options(document_type, scene):
    current = scene.get("pageSetup")
    selected = normalize_page_setup(document_type, current) if current is not None else None
    return {"current": deepcopy(current), "design": geometry(document_type).design,
            "presets": [{**p, "selected": selected == normalize_page_setup(document_type,
                {"paper": p["paper"], "orientation": p["orientation"]})} for p in page_setups(document_type)]}
