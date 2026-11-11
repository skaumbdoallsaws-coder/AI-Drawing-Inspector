"""Authored object geometry and operations; managed assets never come from caller paths.

Composition pixels are PDF points. Shapes use the canvas' 100-unit SVG viewBox
with default xMidYMid meet: a centred square, 1.5 * lineWidth non-scaling stroke,
and non-scaling SVG dash lengths (7/4 or 6/4 composition points).
"""
from __future__ import annotations

from copy import deepcopy
import math

from .commands import DocumentEditError, digest, binding, canonical_bytes

OPERATIONS = frozenset({"set_object_frame", "set_image_crop", "set_object_order", "arrange_objects"})
ARRANGEMENTS = ("align_left", "align_center", "align_right", "align_top", "align_middle", "align_bottom",
                "distribute_horizontal", "distribute_vertical")


def fail(code, message, object_id=None):
    raise DocumentEditError(code, message, **({"objectId": object_id, "targets": [{"targetId": object_id}]} if object_id else {}))


def crop_value(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"x", "y", "width", "height"}:
        fail("invalid_image_crop", "Crop requires x, y, width and height.")
    if any(type(n) not in (int, float) or not math.isfinite(n) for n in value.values()):
        fail("invalid_image_crop", "Crop values must be finite numbers.")
    x, y, w, h = (value[k] for k in ("x", "y", "width", "height"))
    if not (0 <= x < 1 and 0 <= y < 1 and .01 <= w <= 1 and .01 <= h <= 1
            and x + w <= 1 + 1e-9 and y + h <= 1 + 1e-9):
        fail("invalid_image_crop", "Crop must stay inside the source picture, with width and height at least 0.01.")
    result = {key: round(float(n), 6) for key, n in value.items()}
    for offset, extent in (("x", "width"), ("y", "height")):
        if result[offset] + result[extent] > 1:
            result[extent] = round(1 - result[offset], 6)
    if result == {"x": 0, "y": 0, "width": 1, "height": 1}:
        return None
    return result


def frame_value(value):
    from ai_inspector.parts_manual.documentation import _document_frame, DocumentationSceneError
    try:
        return _document_frame(value)
    except (DocumentationSceneError, TypeError, ValueError) as error:
        fail("invalid_object_frame", str(error))


def image_angle(value, frame, *, export=False):
    if value.get("type") == "image" and abs(float(frame.get("rotation", 0)) % 90) > 1e-9:
        fail("unsupported_export_rotation" if export else "unsupported_object_operation",
             "Image rotation must use 90-degree increments.", value.get("objectId"))


def check_aspect(value, frame, release=False):
    if value.get("aspectLock") and not release:
        old = value["frame"]["width"] / value["frame"]["height"]
        if abs(frame["width"] / frame["height"] / old - 1) > .001 + 1e-12:
            fail("aspect_locked", "Release aspectLock before changing the object's proportions.", value["objectId"])


def normalize_order(page):
    objects = page.get("documentObjects", {})
    order = list(dict.fromkeys(key for key in page.get("objectOrder", []) if key in objects))
    order.extend(key for key in objects if key not in order)
    if order:
        page["objectOrder"] = order
    else:
        page.pop("objectOrder", None)
    return order


def ordered_objects(page):
    display = page.get("documentationObjects") or page.get("documentObjects") or {}
    composition = page.get("documentationComposition") or (page.get("renderRequest") or {}).get("composition") or {}
    canonical = composition.get("documentObjects") or {}
    objects = {**canonical, **display}
    order = page.get("documentationObjectOrder", page.get("objectOrder", composition.get("objectOrder")))
    keys = list(objects) if order is None else list(order)
    for key in dict.fromkeys([*keys, *objects]):
        if key in objects:
            yield key, objects[key]


def has_objects(document):
    return any(next(ordered_objects(page), None) is not None for page in document.get("pages", []))


def page_size(document):
    size = document.get("publicationLayout", {}).get("page", {})
    default = (612, 792) if document.get("documentType") == "product_specification_sheet" else (
        (792, 612) if document.get("documentType") == "illustrated_parts_manual" else (960, 540))
    return float(size.get("width") or default[0]), float(size.get("height") or default[1])


def box(frame, size):
    pw, ph = size
    x, y, w, h = (float(frame[k]) for k in ("x", "y", "width", "height"))
    a = math.radians(float(frame.get("rotation", 0)))
    rw, rh = abs(w * pw * math.cos(a)) + abs(h * ph * math.sin(a)), abs(w * pw * math.sin(a)) + abs(h * ph * math.cos(a))
    return {"x": (x * pw + w * pw / 2 - rw / 2) / pw,
            "y": (y * ph + h * ph / 2 - rh / 2) / ph, "width": rw / pw, "height": rh / ph}


def arrangement_frames(objects, arrangement, size):
    if arrangement not in ARRANGEMENTS or not 2 <= len(objects) <= 64 or (
            arrangement.startswith("distribute") and len(objects) < 3):
        fail("invalid_object_frame", "Choose an alignment with 2-64 objects or distribution with 3-64.")
    for value in objects:
        if value.get("locked"):
            fail("object_locked", "Unlock every selected object before arranging.", value["objectId"])
    horizontal = arrangement in {"align_left", "align_center", "align_right", "distribute_horizontal"}
    axis, extent = ("x", "width") if horizontal else ("y", "height")
    bounds = {v["objectId"]: box(v["frame"], size) for v in objects}
    low = min(b[axis] for b in bounds.values())
    high = max(b[axis] + b[extent] for b in bounds.values())
    ordered = sorted(objects, key=lambda v: (bounds[v["objectId"]][axis], v["objectId"]))
    gap = (high - low - sum(b[extent] for b in bounds.values())) / (len(objects) - 1)
    cursor, result = low, []
    for value in ordered:
        b = bounds[value["objectId"]]
        if arrangement.startswith("distribute"):
            desired = cursor
            cursor += b[extent] + gap
        elif arrangement in {"align_left", "align_top"}:
            desired = low
        elif arrangement in {"align_right", "align_bottom"}:
            desired = high - b[extent]
        else:
            desired = (low + high - b[extent]) / 2
        frame = dict(value["frame"])
        delta = desired - b[axis]
        if abs(delta) > 1e-12:
            frame[axis] = round(frame[axis] + delta, 6)
        frame = frame_value(frame)
        result.append({"targetId": value["objectId"], "frame": frame})
    if all(row["frame"] == next(v["frame"] for v in objects if v["objectId"] == row["targetId"]) for row in result):
        fail("invalid_object_frame", "The arrangement moves nothing.")
    return result


def object_hash(value):
    return digest({"type": value.get("type"), "frame": value.get("frame"), "aspectLock": bool(value.get("aspectLock")),
                   "locked": bool(value.get("locked")), "contentMode": value.get("contentMode"), "crop": value.get("crop"),
                   "assetId": value.get("asset", {}).get("assetId"), "shapeType": value.get("shapeType")})


def order_hash(page):
    return digest([key for key, _ in ordered_objects(page)])


def object_batch(operations):
    if not isinstance(operations, list) or not 1 <= len(operations) <= 12 or any(
            not isinstance(o, dict) or o.get("operation") not in OPERATIONS for o in operations):
        fail("invalid_document_operation", "Send 1-12 object operations, separately from text and value operations.")
    if len({o.get("pageId") for o in operations}) != 1 or not operations[0].get("pageId"):
        fail("invalid_document_operation", "An object batch must belong to one page.")
    return "objects"


def apply_operation(page, operation, size):
    """Return a canonical scene command and a changed page; never modify the input."""
    result = deepcopy(page)
    values = result.setdefault("documentObjects", {})
    order = normalize_order(result)
    kind, oid = operation["operation"], operation.get("objectId")
    def require(key):
        value = values.get(key)
        if value is None:
            fail("object_not_found", "The authored object no longer exists.", key)
        if value.get("locked"):
            fail("object_locked", "Unlock the object before changing it.", key)
        return value
    command = {"operation": kind, "pageId": operation["pageId"], "targetType": "document_object", "targetId": oid}
    changed = []
    if kind == "set_object_frame":
        value = require(oid)
        names = {"x", "y", "width", "height", "rotation"}
        patch = {k: operation[k] for k in names if k in operation}
        if not patch:
            fail("invalid_object_frame", "Supply at least one frame value.", oid)
        locked = operation.get("aspectLock", value.get("aspectLock", False))
        if type(locked) is not bool:
            fail("invalid_object_frame", "aspectLock must be a boolean.", oid)
        frame = frame_value({**value["frame"], **patch})
        if value.get("aspectLock") and locked and ("width" in patch) != ("height" in patch):
            ratio = value["frame"]["width"] / value["frame"]["height"]
            if "width" in patch:
                frame["height"] = frame["width"] / ratio
            else:
                frame["width"] = frame["height"] * ratio
        frame = frame_value(frame)
        check_aspect(value, frame, release=not locked)
        image_angle(value, frame)
        command["frame"] = frame
        if "aspectLock" in operation:
            command["aspectLock"] = locked
        value["frame"] = frame
        if locked:
            value["aspectLock"] = True
        else:
            value.pop("aspectLock", None)
        changed = [oid]
    elif kind == "set_image_crop":
        value = require(oid)
        if value["type"] != "image":
            fail("unsupported_object_operation", "Only images have a crop.", oid)
        crop = crop_value(operation.get("crop"))
        image_angle(value, value["frame"])
        command["crop"] = crop
        if operation.get("crop") is not None:
            command["contentMode"] = value["contentMode"] = "contain"
        if crop:
            value["crop"] = crop
            value["contentMode"] = "contain"
        else:
            value.pop("crop", None)
        changed = [oid]
    elif kind == "set_object_order":
        if "order" in operation and ("to" in operation or operation.get("objectId") is not None):
            fail("invalid_object_order", "Supply either the full order or an object and destination.")
        if "order" in operation:
            new = operation["order"]
        else:
            require(oid)
            new = list(order)
            index = new.index(oid)
            destination = {"front": len(new) - 1, "back": 0, "forward": min(index + 1, len(new) - 1),
                           "backward": max(0, index - 1)}.get(operation.get("to"))
            if destination is None:
                fail("invalid_object_order", "Choose front, back, forward or backward.")
            new.insert(destination, new.pop(index))
        if not isinstance(new, list) or any(not isinstance(k, str) for k in new) or len(new) != len(set(new)) or set(new) != set(values):
            fail("invalid_object_order", "Order must contain every object exactly once.")
        for key in new:
            require(key)
        command.update(targetType="figure", targetId=operation["pageId"], order=list(new))
        result["objectOrder"] = list(new)
        changed = [key for i, key in enumerate(new) if order[i] != key]
    elif kind == "arrange_objects":
        ids = operation.get("objectIds", [])
        if not isinstance(ids, list) or len(ids) != len(set(ids)):
            fail("invalid_object_frame", "Select distinct authored objects.")
        selected = [require(key) for key in ids]
        frames = arrangement_frames(selected, operation.get("arrangement"), size)
        command.update(targetType="selection", targetId="", arrangement=operation["arrangement"], frames=frames)
        for row in frames:
            if values[row["targetId"]]["frame"] != row["frame"]:
                changed.append(row["targetId"])
                values[row["targetId"]]["frame"] = row["frame"]
    else:
        fail("unsupported_object_operation", "Unsupported authored object operation.")
    if result == page:
        fail({"set_object_order": "invalid_object_order", "set_image_crop": "invalid_image_crop"}.get(kind, "invalid_object_frame"),
             "The operation changes nothing.", oid)
    return result, command, {"objects": [{"objectId": key, "frame": deepcopy(values[key]["frame"]),
                                        "objectHash": object_hash(values[key])} for key in changed],
                            **({"orderHash": digest(result.get("objectOrder", []))} if kind == "set_object_order" else {})}


def placement(value, frame_size, pixels):
    width, height = frame_size
    w, h = pixels
    source = deepcopy(value.get("crop")) or {"x": 0., "y": 0., "width": 1., "height": 1.}
    if not value.get("crop") and value.get("contentMode", "contain") == "cover":
        if w / h > width / height:
            source["width"] = width / height / (w / h)
            source["x"] = (1 - source["width"]) / 2
        else:
            source["height"] = (w / h) / (width / height)
            source["y"] = (1 - source["height"]) / 2
    ratio = source["width"] * w / (source["height"] * h)
    dw, dh = min(width, height * ratio), min(height, width / ratio)
    return source, ((width - dw) / 2, (height - dh) / 2, dw, dh)


def image_bytes(root, assembly, value):
    from ai_inspector.parts_manual.pdf import _documentation_asset_path, PartsManualPdfError
    if root is None:
        fail("parts_manual_pdf", "The managed asset store is unavailable.", value.get("objectId"))
    try:
        return _documentation_asset_path(root, assembly, value.get("asset", {})).read_bytes()
    except (OSError, PartsManualPdfError) as error:
        fail("parts_manual_pdf", "The managed image is missing or unreadable.", value.get("objectId"))


def picture_info(data, value=None):
    """Displayed pixel size and EXIF orientation (1-8) of a managed picture; reads the header only.

    The canvas and MuPDF's image-to-PDF conversion show a JPEG the way its EXIF
    orientation says; Word and a decoded pixmap show the stored pixels.
    """
    from io import BytesIO
    from PIL import Image
    try:
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
            turn = image.getexif().get(0x0112, 1) if image.format == "JPEG" else 1
    except Exception as error:
        fail("parts_manual_pdf", "The managed image cannot be read.", (value or {}).get("objectId"))
    if turn not in (2, 3, 4, 5, 6, 7, 8):
        turn = 1
    if width < 1 or height < 1:
        fail("parts_manual_pdf", "The managed image cannot be read.", (value or {}).get("objectId"))
    return ((height, width) if turn >= 5 else (width, height)), turn


def pixel_size(data, value=None):
    return picture_info(data, value)[0]


def upright(data, value=None):
    """The same bytes, or an upright re-encoding when the camera stored the picture turned."""
    if picture_info(data, value)[1] == 1:
        return data
    from io import BytesIO
    from PIL import Image, ImageOps
    try:
        with Image.open(BytesIO(data)) as image:
            profile = image.info.get("icc_profile")
            turned = ImageOps.exif_transpose(image)
            output = BytesIO()
            turned.save(output, "JPEG", quality=95, **({"icc_profile": profile} if profile else {}))
            return output.getvalue()
    except Exception as error:
        fail("parts_manual_pdf", "The managed image cannot be read.", (value or {}).get("objectId"))


def read_objects(snapshot, page_ids, root, assembly):
    if not isinstance(page_ids, list) or not 1 <= len(page_ids) <= 8 or len(page_ids) != len(set(page_ids)):
        fail("invalid_document_operation", "Read 1-8 distinct page IDs.")
    document, state = snapshot["document"], snapshot["state"]
    state = {**state, "revision": state.get("scene", {}).get("editRevision", state["revision"])}
    size = page_size(document)
    pages = {p["pageId"]: p for p in document.get("pages", [])}
    result = {**binding(state), "sceneRevision": state["sceneRevision"], "pages": []}
    for key in page_ids:
        if key not in pages:
            fail("object_not_found", "The page no longer exists.", key)
        page = pages[key]
        rows = []
        for oid, value in ordered_objects(page):
            row = {"objectId": oid, "type": value["type"], "name": value["name"], "locked": bool(value.get("locked")),
                   "frame": deepcopy(value["frame"]), "box": box(value["frame"], size), "aspectLock": bool(value.get("aspectLock")),
                   "objectHash": object_hash(value)}
            if value["type"] == "image":
                row.update(assetId=value["asset"]["assetId"], pixelSize=list(pixel_size(image_bytes(root, assembly, value), value)),
                           contentMode=value.get("contentMode", "contain"), crop=deepcopy(value.get("crop")), altText=value.get("altText", ""))
            elif value["type"] == "shape":
                row["shapeType"] = value["shapeType"]
            else:
                row["targetId"] = next((t["targetId"] for t in snapshot["targets"].values()
                    if t["targetType"] == "document_object" and t["pageId"] == key and t["alias"] == oid), oid)
            rows.append(row)
        result["pages"].append({"pageId": key, "pageSize": list(size), "orderHash": order_hash(page), "objects": rows})
    if len(canonical_bytes(result)) > 65536:
        fail("read_result_too_large", "Read fewer pages of objects.")
    return result


def validate_command(command):
    """Stored shape validation only: never enforce current locks or aspect/angle policy on replay."""
    kind = command["operation"]
    if kind == "set_object_frame":
        if command.get("targetType") != "document_object":
            fail("invalid_object_frame", "A frame needs an authored object.")
        frame_value(command.get("frame"))
        if "aspectLock" in command and type(command["aspectLock"]) is not bool:
            fail("invalid_object_frame", "aspectLock must be a boolean.")
    elif kind == "set_image_crop":
        if command.get("targetType") != "document_object":
            fail("unsupported_object_operation", "A crop needs an image.")
        crop_value(command.get("crop"))
    elif kind == "set_object_order":
        order = command.get("order")
        if command.get("targetType") != "figure" or not isinstance(order, list) or any(not isinstance(k, str) for k in order) or len(order) != len(set(order)):
            fail("invalid_object_order", "Page order must contain distinct object IDs.")
    elif kind == "arrange_objects":
        frames = command.get("frames")
        if command.get("targetType") != "selection" or command.get("arrangement") not in ARRANGEMENTS or not isinstance(frames, list) or not 2 <= len(frames) <= 64:
            fail("invalid_object_frame", "An arrangement needs 2-64 object frames.")
        seen = set()
        for row in frames:
            if not isinstance(row, dict) or set(row) != {"targetId", "frame"} or not isinstance(row["targetId"], str) or row["targetId"] in seen:
                fail("invalid_object_frame", "Arrangement frames must have distinct IDs.")
            seen.add(row["targetId"])
            frame_value(row["frame"])


def live_command(scene, command):
    validate_command(command)
    page = scene.get("pages", {}).get(command["pageId"], {})
    objects = page.get("documentObjects", {})
    kind = command["operation"]
    def require(key):
        value = objects.get(key)
        if value is None:
            fail("object_not_found", "The authored object no longer exists.", key)
        if value.get("locked"):
            fail("object_locked", "Unlock the object before changing it.", key)
        return value
    if kind == "arrange_objects":
        changed = []
        for row in command["frames"]:
            value = require(row["targetId"])
            frame = frame_value(row["frame"])
            check_aspect(value, frame)
            image_angle(value, frame)
            if frame != value["frame"]:
                changed.append(row["targetId"])
        if not changed:
            fail("invalid_object_frame", "The arrangement moves nothing.")
        return {"arrangement": command["arrangement"], "frames": deepcopy(command["frames"]), "movedObjectIds": changed}
    if kind == "set_object_order":
        if set(command["order"]) != set(objects):
            fail("invalid_object_order", "Order must contain every object exactly once.")
        for key in objects:
            require(key)
        if command["order"] == normalize_order(deepcopy(page)):
            fail("invalid_object_order", "The order changes nothing.")
        return {"order": list(command["order"])}
    value = require(command["targetId"])
    if kind == "set_object_frame":
        frame = frame_value(command["frame"])
        release = command.get("aspectLock") is False
        check_aspect(value, frame, release)
        image_angle(value, frame)
        if frame == value["frame"] and command.get("aspectLock", bool(value.get("aspectLock"))) == bool(value.get("aspectLock")):
            fail("invalid_object_frame", "The frame changes nothing.", value["objectId"])
        return {"frame": frame, **({"aspectLock": command["aspectLock"]} if "aspectLock" in command else {})}
    if value["type"] != "image":
        fail("unsupported_object_operation", "Only images have a crop.", value["objectId"])
    crop = crop_value(command.get("crop"))
    image_angle(value, value["frame"])
    contain = command.get("contentMode") == "contain" or command.get("crop") is not None
    if crop == value.get("crop") and not (contain and value.get("contentMode") == "cover"):
        fail("invalid_image_crop", "The crop changes nothing.", value["objectId"])
    return {"crop": crop, **({"contentMode": "contain"} if contain else {})}


def _rect(fitz, value, size):
    f = value["frame"]
    return fitz.Rect(f["x"] * size[0], f["y"] * size[1],
                     (f["x"] + f["width"]) * size[0], (f["y"] + f["height"]) * size[1])


def draw_pdf_image(fitz, page, value, style, root, assembly):
    """Clip in source PDF points, then rotate the drawn footprint clockwise."""
    image_angle(value, value["frame"], export=True)
    data = image_bytes(root, assembly, value)
    pixels = pixel_size(data, value)
    rect = _rect(fitz, value, (page.rect.width, page.rect.height))
    source, (x, y, w, h) = placement(value, (rect.width, rect.height), pixels)
    opacity = float(style.get("opacity", 1))
    if opacity < 1:
        try:
            pixmap = fitz.Pixmap(upright(data, value))
            if pixmap.colorspace and pixmap.colorspace.n != 3:
                pixmap = fitz.Pixmap(fitz.csRGB, pixmap)
            if not pixmap.alpha:
                pixmap = fitz.Pixmap(pixmap, 1)
            # Pixmap samples are premultiplied: scale RGB and alpha together exactly once.
            samples = bytes(pixmap.samples).translate(bytes(round(level * opacity) for level in range(256)))
            pixmap = fitz.Pixmap(pixmap.colorspace, pixmap.width, pixmap.height, samples, True)
            data = pixmap.tobytes("png")
        except DocumentEditError:
            raise
        except Exception as error:
            fail("parts_manual_pdf", "The managed image cannot be drawn: " + str(error), value.get("objectId"))
    try:
        with fitz.open(stream=data) as picture:
            pdf_bytes = picture.convert_to_pdf()
        with fitz.open(stream=pdf_bytes, filetype="pdf") as source_pdf:
            bounds = source_pdf[0].rect
            clip = fitz.Rect(source["x"] * bounds.width, source["y"] * bounds.height,
                             (source["x"] + source["width"]) * bounds.width,
                             (source["y"] + source["height"]) * bounds.height)
            angle = int(value["frame"].get("rotation", 0)) % 360
            cx, cy = rect.x0 + rect.width / 2, rect.y0 + rect.height / 2
            dw, dh = (h, w) if angle in (90, 270) else (w, h)
            target = fitz.Rect(cx - dw / 2, cy - dh / 2, cx + dw / 2, cy + dh / 2)
            page.show_pdf_page(target, source_pdf, 0, clip=clip, rotate=(360 - angle) % 360,
                               keep_proportion=False)
    except Exception as error:
        fail("parts_manual_pdf", "The managed image cannot be drawn: " + str(error), value.get("objectId"))


def draw_pdf_shape(fitz, page, value, style, *, frame=None):
    """The canvas SVG's centred square and paths, transformed in page coordinates."""
    from ai_inspector.parts_manual.pdf import _hex_rgb
    rect = fitz.Rect(frame) if frame is not None else _rect(fitz, value, (page.rect.width, page.rect.height))
    cx, cy, unit = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2, min(rect.width, rect.height) / 100
    angle = math.radians(value["frame"].get("rotation", 0))
    sine, cosine = math.sin(angle), math.cos(angle)
    def point(x, y):
        dx, dy = (x - 50) * unit, (y - 50) * unit
        return fitz.Point(cx + cosine * dx - sine * dy, cy + sine * dx + cosine * dy)
    drawing = page.new_shape()
    kind = value.get("shapeType", "rectangle")
    def line(a, b):
        drawing.draw_line(point(*a), point(*b))
    def curve(a, b, c, d):
        drawing.draw_bezier(point(*a), point(*b), point(*c), point(*d))
    if kind == "arrow":
        line((3, 50), (88, 50))
        line((72, 34), (88, 50))
        line((88, 50), (72, 66))
    elif kind == "ellipse":
        k = .5522847498307936
        curve((97, 50), (97, 50 + 46*k), (50 + 47*k, 96), (50, 96))
        curve((50, 96), (50 - 47*k, 96), (3, 50 + 46*k), (3, 50))
        curve((3, 50), (3, 50 - 46*k), (50 - 47*k, 4), (50, 4))
        curve((50, 4), (50 + 47*k, 4), (97, 50 - 46*k), (97, 50))
    elif kind == "revision_cloud":
        # SVG rect rx=12; circular corners have cubic controls at k * radius.
        c = 12 * .5522847498307936
        line((15, 3), (85, 3)); curve((85, 3), (85+c, 3), (97, 15-c), (97, 15))
        line((97, 15), (97, 85)); curve((97, 85), (97, 85+c), (85+c, 97), (85, 97))
        line((85, 97), (15, 97)); curve((15, 97), (15-c, 97), (3, 85+c), (3, 85))
        line((3, 85), (3, 15)); curve((3, 15), (3, 15-c), (15-c, 3), (15, 3))
    else:
        line((3, 3), (97, 3)); line((97, 3), (97, 97))
        line((97, 97), (3, 97)); line((3, 97), (3, 3))
    width = max(0, float(style.get("lineWidth") or 0)) * 1.5
    opacity = float(style.get("opacity", 1))
    drawing.finish(color=_hex_rgb(style.get("outlineColor"), "#ABBAC4") if width else None,
                   fill=None if kind == "arrow" else _hex_rgb(style.get("fill"), "#FFFFFF"),
                   width=width, closePath=kind != "arrow", lineCap=0, lineJoin=0,
                   dashes={"revision_cloud": "[7 4] 0", "detail_box": "[6 4] 0"}.get(kind),
                   stroke_opacity=opacity, fill_opacity=opacity)
    drawing.commit()


def shape_picture(value, style, frame_size):
    """Render this object alone, at four pixels per point, on transparent paper."""
    import fitz
    w, h = frame_size
    footprint = box({"x": 0, "y": 0, "width": 1, "height": 1,
                     "rotation": value["frame"].get("rotation", 0)}, (w, h))
    rw, rh = footprint["width"] * w, footprint["height"] * h
    with fitz.open() as pdf:
        page = pdf.new_page(width=rw, height=rh)
        draw_pdf_shape(fitz, page, value, style, frame=((rw-w)/2, (rh-h)/2, (rw+w)/2, (rh+h)/2))
        return page.get_pixmap(matrix=fitz.Matrix(4, 4), alpha=True).tobytes("png"), (rw, rh)


def _docx_picture(output, data, size, description, *, source=None, rotation=0, opacity=1):
    from io import BytesIO
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt
    section = output.sections[-1]
    available = (section.page_width - section.left_margin - section.right_margin) / 12700
    w, h = size
    footprint_width = h if rotation % 180 else w
    scale = min(1, available / footprint_width)
    paragraph = output.add_paragraph()
    paragraph.paragraph_format.space_before = paragraph.paragraph_format.space_after = Pt(0)
    picture = paragraph.add_run().add_picture(BytesIO(data), width=Pt(w * scale), height=Pt(h * scale))
    inline = picture._inline
    inline.docPr.set("descr", description)
    blip_fill = next(inline.iter(qn("pic:blipFill")))
    if source and source != {"x": 0, "y": 0, "width": 1, "height": 1}:
        crop = OxmlElement("a:srcRect")
        for key, amount in (("l", source["x"]), ("t", source["y"]),
                            ("r", 1-source["x"]-source["width"]), ("b", 1-source["y"]-source["height"])):
            crop.set(key, str(round(amount * 100000)))
        stretch = blip_fill.find(qn("a:stretch"))
        if stretch is not None:
            stretch.addprevious(crop)
        else:
            blip_fill.append(crop)
    if opacity < 1:
        alpha = OxmlElement("a:alphaModFix")
        alpha.set("amt", str(round(opacity * 100000)))
        blip_fill.find(qn("a:blip")).append(alpha)
    transform = next(inline.iter(qn("a:xfrm")))
    if rotation:
        transform.set("rot", str((rotation % 360) * 60000))
    return picture


def docx_image(output, value, style, frame_size, root, assembly):
    image_angle(value, value["frame"], export=True)
    data = image_bytes(root, assembly, value)
    source, (_, _, w, h) = placement(value, frame_size, pixel_size(data, value))
    data = upright(data, value)
    return _docx_picture(output, data, (w, h), value.get("altText") or value["name"], source=source,
                         rotation=int(value["frame"].get("rotation", 0)), opacity=float(style.get("opacity", 1)))


def docx_shape(output, value, style, frame_size):
    data, size = shape_picture(value, style, frame_size)
    return _docx_picture(output, data, size, "Shape: " + value["name"])


def prepare_batch(scene, document, operations, expected_revision):
    """Check every hash against the pre-image, then evolve one private page in order."""
    from .commands import check_preconditions
    object_batch(operations)
    page_id = operations[0]["pageId"]
    if page_id not in {p["pageId"] for p in document.get("pages", [])}:
        fail("object_not_found", "The page no longer exists.", page_id)
    page = deepcopy(scene.get("pages", {}).get(page_id, {}))
    values = page.get("documentObjects", {})
    current = {key: object_hash(value) for key, value in values.items()}
    order_key = "@object-order:" + page_id
    current[order_key] = order_hash(page)
    expected, commands, results = {}, [], []
    for index, operation in enumerate(operations):
        kind = operation["operation"]
        if kind == "set_object_order":
            hashes = {order_key: operation.get("expectedOrderHash")}
        elif kind == "arrange_objects":
            ids, hashes_list = operation.get("objectIds"), operation.get("expectedObjectHashes")
            if not isinstance(ids, list) or not isinstance(hashes_list, list) or len(ids) != len(hashes_list):
                fail("invalid_object_frame", "Supply one object hash per selected ID.")
            hashes = dict(zip(ids, hashes_list))
        else:
            hashes = {operation.get("objectId"): operation.get("expectedObjectHash")}
        for key in hashes:
            if key not in current:
                fail("object_not_found", "The authored object no longer exists.", key)
        check_preconditions(scene, expected_revision, hashes, current)
        expected.update(hashes)
        try:
            page, command, result = apply_operation(page, operation, page_size(document))
        except DocumentEditError as error:
            raise DocumentEditError(error.code, str(error), **{**error.details, "operationIndex": index}) from error
        commands.append(command)
        results.append({"operationIndex": index, **result})
    return commands, expected, current, results
