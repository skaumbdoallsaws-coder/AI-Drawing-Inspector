"""P4a-1 export matrix: real pixels and native OOXML, no binary fixtures."""
from copy import deepcopy
import hashlib
import io
import math
import zipfile

import fitz
import pytest
from lxml import etree

from ai_inspector.documentation import objects, rich_layout, rich_docx
from ai_inspector.documentation.commands import DocumentEditError
from ai_inspector.documentation.rich_text import from_plain
from ai_inspector.parts_manual import pdf as parts
from ai_inspector.operations_manual import exports as ops
from ai_inspector.specification_sheet import exports as spec
from tests.test_documentation_rich_exports import (
    BUILDERS, NUMBER, PAGE, TARGET, fixture_document, image_path, build, build_docx,
    store_pdf, attach, mixed, docx_parts, legacy_module,
)
from tests.test_documentation_objects import value

COLORS = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0))
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
      "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
      "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"}


def quadrant_png():
    with fitz.open() as pdf:
        page = pdf.new_page(width=200, height=100)
        for rect, color in zip(((0, 0, 100, 50), (100, 0, 200, 50), (0, 50, 100, 100), (100, 50, 200, 100)), COLORS):
            page.draw_rect(rect, color=None, fill=tuple(c/255 for c in color))
        return page.get_pixmap(alpha=False).tobytes("png")


def install_picture(root):
    data = quadrant_png()
    key = hashlib.sha256(data).hexdigest()
    path = root / NUMBER.lower() / "documentation-assets" / (key + ".png")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"assetId": key, "filename": "quadrants.png", "mimeType": "image/png",
            "url": "/api/parts-manual/" + NUMBER + "/documentation-assets/" + key}


def put(document, items, order=None):
    descriptor = document["pages"][0]
    values = {v["objectId"]: deepcopy(v) for v in items}
    order = order or list(values)
    descriptor["documentationObjects"] = deepcopy(values)
    descriptor["documentationComposition"] = {"documentObjects": values, "objectOrder": order}
    descriptor["documentationObjectOrder"] = list(order)
    return document


def image(root, **fields):
    return value("document-object-image", "image", asset=install_picture(root),
        frame={"x": .25, "y": .3, "width": .4, "height": .3, "rotation": 0}, **fields)


def color_at(page, point):
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    return pix.pixel(round(point[0] * 2), round(point[1] * 2))[:3]


def assert_color(actual, expected, tolerance=3):
    assert max(abs(a-b) for a, b in zip(actual, expected)) <= tolerance, (actual, expected)


def drawn_points(item, size, fractions=((.25, .25), (.75, .25), (.25, .75), (.75, .75)), pixels=(200, 100)):
    f = item["frame"]
    w, h = f["width"] * size[0], f["height"] * size[1]
    source, (x, y, dw, dh) = objects.placement(item, (w, h), pixels)
    angle = math.radians(f["rotation"])
    cx, cy = (f["x"] + f["width"]/2)*size[0], (f["y"] + f["height"]/2)*size[1]
    return [(cx + math.cos(angle)*(u-.5)*dw - math.sin(angle)*(v-.5)*dh,
             cy + math.sin(angle)*(u-.5)*dw + math.cos(angle)*(v-.5)*dh) for u, v in fractions]


@pytest.mark.parametrize("builder", BUILDERS)
@pytest.mark.parametrize("mode,crop", [("contain", None), ("cover", None),
    ("contain", {"x": .5, "y": 0, "width": .5, "height": .5})])
@pytest.mark.parametrize("angle", [0, 90, 180, -90])
def test_pdf_image_placement_rotation_crop_and_footprint(builder, mode, crop, angle, tmp_path, image_path):
    item = image(tmp_path, contentMode=mode, **({"crop": crop} if crop else {}))
    item["frame"]["rotation"] = angle
    document = put(fixture_document(builder), [item])
    baseline = build(builder, fixture_document(builder), tmp_path)
    payload = build(builder, document, tmp_path)
    with fitz.open(stream=payload, filetype="pdf") as pdf:
        page = pdf[0]
        size = (page.rect.width, page.rect.height)
        expected = (COLORS[1],) * 4 if crop else COLORS
        for point, color in zip(drawn_points(item, size), expected):
            assert_color(color_at(page, point), color)
        f = item["frame"]
        _, (_, _, dw, dh) = objects.placement(item, (f["width"]*size[0], f["height"]*size[1]), (200, 100))
        cx, cy = (f["x"]+f["width"]/2)*size[0], (f["y"]+f["height"]/2)*size[1]
        footprint = (dh, dw) if angle % 180 else (dw, dh)
        # The converted image is drawn through a Form XObject; pixel proof includes the entire rotated extent.
        for point, color in zip(drawn_points(item, size, ((.04,.04),(.96,.04),(.04,.96),(.96,.96))), expected):
            assert_color(color_at(page, point), color)
        with fitz.open(stream=baseline, filetype="pdf") as previous:
            for point in ((cx-footprint[0]/2-5,cy),(cx+footprint[0]/2+5,cy),
                          (cx,cy-footprint[1]/2-5),(cx,cy+footprint[1]/2+5)):
                assert_color(color_at(page,point),color_at(previous[0],point))


@pytest.mark.parametrize("builder", BUILDERS)
def test_pdf_image_opacity_over_white(builder, tmp_path, image_path):
    item = image(tmp_path, crop={"x": 0, "y": 0, "width": .5, "height": .5},
                 styleOverrides={"opacity": .5})
    document = put(fixture_document(builder), [item])
    # A white text box establishes the reference background in every page generator.
    white = value("document-object-white", "text", content="", frame={**item["frame"]},
                  styleOverrides={"fill": "#fffffe", "fontSize": 10})
    put(document, [white, item])
    with fitz.open(stream=build(builder, document, tmp_path), filetype="pdf") as pdf:
        for point in drawn_points(item, (pdf[0].rect.width, pdf[0].rect.height)):
            assert_color(color_at(pdf[0], point), (255, 127, 127), 3)


@pytest.mark.parametrize("builder", BUILDERS)
@pytest.mark.parametrize("shape", ["rectangle", "ellipse", "arrow", "revision_cloud", "detail_box"])
@pytest.mark.parametrize("angle", [0, 31])
def test_pdf_shapes_match_canvas_paths(builder, shape, angle, tmp_path, image_path):
    document = fixture_document(builder)
    size = objects.page_size(document)
    item = value("document-object-shape", shapeType=shape, styleOverrides={
        "fill": "#ff0000", "outlineColor": "#0000ff", "lineWidth": 4},
        frame={"x": .2, "y": .3, "width": .4, "height": .3, "rotation": angle})
    put(document, [item])
    with fitz.open(stream=build(builder, document, tmp_path), filetype="pdf") as pdf:
        page = pdf[0]
        f, size = item["frame"], (page.rect.width, page.rect.height)
        cx, cy, scale = (f["x"]+f["width"]/2)*size[0], (f["y"]+f["height"]/2)*size[1], min(f["width"]*size[0], f["height"]*size[1])/100
        def point(x, y):
            a = math.radians(angle)
            return (cx+math.cos(a)*(x-50)*scale-math.sin(a)*(y-50)*scale,
                    cy+math.sin(a)*(x-50)*scale+math.cos(a)*(y-50)*scale)
        assert_color(color_at(page, point(50, 50)), (0, 0, 255) if shape == "arrow" else (255, 0, 0))
        outline = (88,50) if shape == "arrow" else (50,4) if shape == "ellipse" else (20,3) if shape == "revision_cloud" else (3,3)
        if shape not in {"revision_cloud", "detail_box"}:  # Dashed samples can land in a gap; verify their drawing below.
            assert_color(color_at(page, point(*outline)), (0,0,255))
        drawings = [d for d in page.get_drawings() if d.get("color") and d["color"][2] > .99 and d["color"][0] < .01]
        assert any(d["width"] == pytest.approx(6) for d in drawings)
        if shape in {"revision_cloud", "detail_box"}:
            assert any(("7 4" if shape == "revision_cloud" else "6 4") in d["dashes"] for d in drawings)


@pytest.mark.parametrize("builder", BUILDERS)
@pytest.mark.parametrize("order,expected", [([0,1,2], (0,0,255)), ([2,0,1], (0,255,0))])
def test_pdf_stacking_including_text_fill(builder, order, expected, tmp_path, image_path):
    frame = {"x": .3, "y": .3, "width": .3, "height": .3, "rotation": 0}
    rows = [value("document-object-red", frame=frame, styleOverrides={"fill": "#ff0000", "lineWidth": 0}),
            value("document-object-text", "text", content="", frame=frame, styleOverrides={"fill": "#00ff00"}),
            value("document-object-blue", frame=frame, styleOverrides={"fill": "#0000ff", "lineWidth": 0})]
    document = put(fixture_document(builder), rows, [rows[i]["objectId"] for i in order])
    with fitz.open(stream=build(builder, document, tmp_path), filetype="pdf") as pdf:
        assert_color(color_at(pdf[0], (.45*pdf[0].rect.width, .45*pdf[0].rect.height)), expected)


@pytest.mark.parametrize("builder", ["operations", "wi", "specification"])
@pytest.mark.parametrize("angle", [0, 90, 180, -90])
def test_docx_native_images_shape_picture_and_flow(builder, angle, tmp_path, image_path):
    img = image(tmp_path, crop={"x": .5, "y": 0, "width": .5, "height": .5},
                altText="Green quadrant", styleOverrides={"opacity": .5})
    img["frame"]["rotation"] = angle
    shape = value("document-object-shape", name="Red square", frame={"x": .2, "y": .7, "width": .1, "height": .1, "rotation": 0},
                  styleOverrides={"fill": "#ff0000", "outlineColor": "#000000", "lineWidth": 0})
    document = put(fixture_document(builder), [shape, img])  # Stacking opposes flow.
    payload = build_docx(builder, document, tmp_path)
    package = docx_parts(payload)
    drawings = package["word/document.xml"].xpath("//wp:inline", namespaces=NS)
    authored = [d for d in drawings if d.xpath("wp:docPr/@descr", namespaces=NS) in [["Green quadrant"], ["Shape: Red square"]]]
    assert [d.xpath("wp:docPr/@descr", namespaces=NS)[0] for d in authored] == ["Green quadrant", "Shape: Red square"]
    native = authored[0]
    src = native.xpath(".//a:srcRect", namespaces=NS)[0]
    assert dict(src.attrib) == {"l": "50000", "t": "0", "r": "0", "b": "50000"}
    assert src.getnext().tag.endswith("stretch")
    assert native.xpath(".//a:xfrm/@rot", namespaces=NS) == ([str((angle % 360)*60000)] if angle else [])
    assert native.xpath(".//a:blip/a:alphaModFix/@amt", namespaces=NS) == ["50000"]
    size = objects.page_size(document)
    _, (_, _, w, h) = objects.placement(img, (img["frame"]["width"]*size[0], img["frame"]["height"]*size[1]), (200,100))
    extent = native.xpath(".//pic:spPr/a:xfrm/a:ext", namespaces=NS)[0]
    assert int(extent.get("cx")) == pytest.approx(w*12700, abs=1)
    assert int(extent.get("cy")) == pytest.approx(h*12700, abs=1)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        media = [archive.read(name) for name in archive.namelist() if name.startswith("word/media/")]
    assert quadrant_png() in media  # Native picture keeps the original compressed bytes.
    sw, sh = shape["frame"]["width"]*size[0], shape["frame"]["height"]*size[1]
    rendered = [fitz.Pixmap(data) for data in media if data != quadrant_png()]
    shape_pix = next(p for p in rendered if p.width == math.ceil(sw*4) and p.height == math.ceil(sh*4) and p.alpha)
    assert_color(shape_pix.pixel(shape_pix.width//2, shape_pix.height//2)[:3], (255,0,0))
    assert shape_pix.pixel(0,0)[3] == 0


@pytest.mark.parametrize("builder", BUILDERS)
@pytest.mark.parametrize("failure", ["missing", "unreadable", "rotation"])
def test_export_refusals_name_object_and_write_no_artifact(builder, failure, tmp_path, image_path):
    item = image(tmp_path)
    if failure == "rotation":
        item["frame"]["rotation"] = 17
    else:
        path = tmp_path / NUMBER.lower() / "documentation-assets" / (item["asset"]["assetId"]+".png")
        if failure == "missing":
            path.unlink()
        else:
            path.write_bytes(b"not a picture")
    document = put(fixture_document(builder), [item])
    with pytest.raises((DocumentEditError, parts.PartsManualPdfError)) as caught:
        store_pdf(builder, document, tmp_path)
    assert item["objectId"] in str(caught.value) or item["objectId"] in str(getattr(caught.value, "details", {}))
    if isinstance(caught.value, DocumentEditError):
        assert caught.value.code == ("unsupported_export_rotation" if failure == "rotation" else "parts_manual_pdf")
    assert not list(tmp_path.rglob("*.pdf"))


@pytest.mark.parametrize("builder", BUILDERS)
@pytest.mark.parametrize("text", [False, True])
def test_text_only_pdf_content_is_identical_to_p3b2(builder, text, tmp_path, image_path, monkeypatch):
    document = fixture_document(builder)
    if text:
        attach(document, mixed())
    save = fitz.Document.tobytes
    monkeypatch.setattr(fitz.Document, "tobytes", lambda self,*a,**kw: save(self,*a,**{**kw,"no_new_id":True}))
    current = build(builder, document, tmp_path)
    # Load the old implementation AND its caller; this executes the previous drawing code.
    old_layout = legacy_module(rich_layout, monkeypatch, "5cf7f26")
    with monkeypatch.context() as patch:
        import sys
        patch.setitem(sys.modules, "ai_inspector.documentation.rich_layout", old_layout)
        old_caller = legacy_module(parts if builder == "parts" else spec if builder in {"specification","fillable"} else ops, patch, "5cf7f26")
        if builder in {"specification","fillable"}:
            old_caller.draft_render_path = lambda *args: image_path
        modules = (old_caller if builder == "parts" else parts,
                   old_caller if builder in {"specification","fillable"} else spec,
                   old_caller if builder in {"operations","wi"} else ops)
        previous = build(builder, document, tmp_path, modules=modules)
    assert current == previous


@pytest.mark.parametrize("builder", ["operations", "wi", "specification"])
def test_text_only_docx_xml_parts_equal_p3b2(builder, tmp_path, image_path, monkeypatch):
    document = attach(fixture_document(builder), mixed())
    current = docx_parts(build_docx(builder, document, tmp_path))
    old_docx = legacy_module(rich_docx, monkeypatch, "5cf7f26")
    with monkeypatch.context() as patch:
        import sys
        patch.setitem(sys.modules, "ai_inspector.documentation.rich_docx", old_docx)
        old_caller = legacy_module(spec if builder == "specification" else ops, patch, "5cf7f26")
        if builder == "specification":
            old_caller.draft_render_path = lambda *args: image_path
        previous = docx_parts(build_docx(builder, document, tmp_path, old_caller))
    assert current.keys() == previous.keys()
    for name in current:
        assert etree.tostring(current[name]) == etree.tostring(previous[name]), name


@pytest.mark.parametrize("builder", ["operations","wi","specification"])
@pytest.mark.parametrize("failure", ["missing","unreadable","rotation"])
def test_docx_refusal_is_named_before_any_artifact(builder,failure,tmp_path,image_path):
    from ai_inspector.work_instructions import exports as wi
    item = image(tmp_path)
    if failure == "rotation":
        item["frame"]["rotation"] = 45
    else:
        asset = tmp_path/NUMBER.lower()/"documentation-assets"/(item["asset"]["assetId"]+".png")
        if failure == "missing":
            asset.unlink()
        else:
            asset.write_bytes(b"bad image")
    document = put(fixture_document(builder),[item])
    writer = {"operations":ops.store_prototype_docx,"wi":wi.store_review_docx,"specification":spec.store_specification_docx}[builder]
    with pytest.raises(DocumentEditError) as caught:
        writer(tmp_path,NUMBER,document)
    assert item["objectId"] in str(caught.value.details)
    assert caught.value.code == ("unsupported_export_rotation" if failure == "rotation" else "parts_manual_pdf")
    assert not list(tmp_path.rglob("*.docx"))


def test_jpeg_keeps_original_dct_and_native_docx_bytes(tmp_path,image_path):
    data = fitz.Pixmap(quadrant_png()).tobytes("jpeg")
    key = hashlib.sha256(data).hexdigest()
    folder = tmp_path/NUMBER.lower()/"documentation-assets"
    folder.mkdir(parents=True,exist_ok=True)
    (folder/(key+".jpg")).write_bytes(data)
    item = value("document-object-jpeg","image",asset={"assetId":key,"mimeType":"image/jpeg",
        "filename":"quadrants.jpg","url":"/api/parts-manual/PROOF/documentation-assets/"+key})
    document = put(fixture_document("operations"),[item])
    with fitz.open(stream=build("operations",document,tmp_path),filetype="pdf") as pdf:
        images = [pdf.extract_image(row[0]) for row in pdf[0].get_images(full=True)]
        assert any(img["ext"] == "jpeg" and img["image"] == data for img in images)
    with zipfile.ZipFile(io.BytesIO(build_docx("operations",document,tmp_path))) as archive:
        assert data in [archive.read(name) for name in archive.namelist() if name.startswith("word/media/")]


def test_docx_native_text_opacity_blends_against_the_flow_paper(tmp_path,image_path):
    document = attach(fixture_document("operations"),from_plain("Opacity"),style={
        "color":"#ff0000","fill":"#0000ff","opacity":.5})
    xml = docx_parts(build_docx("operations",document,tmp_path))["word/document.xml"]
    boxes = xml.xpath('//w:tbl[w:tblPr/w:tblCaption[starts-with(@w:val,"Authored text: ")]]',namespaces=NS)
    assert boxes[0].xpath('.//w:rPr/w:color/@w:val',namespaces=NS) == ["FF8080","FF8080"]
    assert boxes[0].xpath('./w:tr/w:tc/w:tcPr/w:shd/@w:fill',namespaces=NS) == ["8080FF"]


def test_object_only_operations_pdf_cache_has_new_stamp(tmp_path,image_path):
    from ai_inspector.documentation.rich_layout import PDF_RENDERER_VERSION
    item = value(styleOverrides={"fill":"#ff0000"})
    document = put(fixture_document("operations"),[item])
    first = ops.store_prototype_pdf(tmp_path,NUMBER,document)
    assert first["rendererVersion"] == PDF_RENDERER_VERSION and not first["cacheHit"]
    assert ops.store_prototype_pdf(tmp_path,NUMBER,document)["cacheHit"]


@pytest.mark.parametrize("builder", ["operations", "wi", "specification"])
@pytest.mark.parametrize("angle", [0, 90, 180, -90])
def test_docx_picture_extent_caps_the_rotated_footprint(builder, angle, tmp_path, image_path):
    item = image(tmp_path, altText="Width cap")
    item["frame"] = {"x": .1, "y": .1, "width": 1.3, "height": 1.4, "rotation": angle}
    document = put(fixture_document(builder), [item])
    xml = docx_parts(build_docx(builder, document, tmp_path))["word/document.xml"]
    picture = next(d for d in xml.xpath("//wp:inline", namespaces=NS)
                   if d.xpath("wp:docPr/@descr", namespaces=NS) == ["Width cap"])
    section = xml.xpath("//w:sectPr", namespaces=NS)[-1]
    get = lambda element, key: int(element.get("{" + NS["w"] + "}" + key))
    page = section.find("{" + NS["w"] + "}pgSz")
    margins = section.find("{" + NS["w"] + "}pgMar")
    available = (get(page, "w") - get(margins, "left") - get(margins, "right")) / 20
    size = objects.page_size(document)
    _, (_, _, w, h) = objects.placement(item, (1.3*size[0], 1.4*size[1]), (200,100))
    scale = min(1, available / (h if angle % 180 else w))
    extent = picture.xpath(".//pic:spPr/a:xfrm/a:ext", namespaces=NS)[0]
    assert int(extent.get("cx")) == pytest.approx(w*scale*12700, abs=1)
    assert int(extent.get("cy")) == pytest.approx(h*scale*12700, abs=1)
    assert (h if angle % 180 else w)*scale <= available + 1e-9


# COLORS indices seen at the top left, top right, bottom left and bottom right of the displayed
# picture, for stored quadrants red, green, blue, yellow and each EXIF orientation.
ORIENTED = {1: (0, 1, 2, 3), 2: (1, 0, 3, 2), 3: (3, 2, 1, 0), 4: (2, 3, 0, 1),
            5: (0, 2, 1, 3), 6: (2, 0, 3, 1), 7: (3, 1, 2, 0), 8: (1, 3, 0, 2)}


def camera_jpeg(turn):
    from PIL import Image
    picture = Image.new("RGB", (200, 100))
    for box, color in zip(((0, 0, 100, 50), (100, 0, 200, 50), (0, 50, 100, 100), (100, 50, 200, 100)), COLORS):
        picture.paste(color, box)
    exif = Image.Exif()
    exif[0x0112] = turn
    output = io.BytesIO()
    picture.save(output, "JPEG", quality=95, subsampling=0, exif=exif.tobytes())
    return output.getvalue()


def camera_item(root, turn, angle=0, opacity=1):
    data = camera_jpeg(turn)
    key = hashlib.sha256(data).hexdigest()
    folder = root / NUMBER.lower() / "documentation-assets"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (key + ".jpg")).write_bytes(data)
    item = value("document-object-camera", "image", altText="Camera picture", asset={
        "assetId": key, "mimeType": "image/jpeg", "filename": "camera.jpg",
        "url": "/api/parts-manual/" + NUMBER + "/documentation-assets/" + key},
        frame={"x": .25, "y": .3, "width": .4, "height": .3, "rotation": angle},
        styleOverrides={"opacity": opacity})
    return data, item


@pytest.mark.parametrize("builder", ["parts", "operations"])
@pytest.mark.parametrize("turn", range(1, 9))
@pytest.mark.parametrize("angle,opacity", [(0, 1), (0, .5), (90, 1)])
def test_pdf_shows_a_camera_picture_the_way_the_canvas_does(builder, turn, angle, opacity, tmp_path, image_path):
    data, item = camera_item(tmp_path, turn, angle, opacity)
    pixels = (100, 200) if turn >= 5 else (200, 100)
    assert objects.picture_info(data) == (pixels, turn)
    white = value("document-object-white", "text", content="", frame={"x": .2, "y": .2, "width": .5, "height": .5,
        "rotation": 0}, styleOverrides={"fill": "#ffffff", "fontSize": 10})
    document = put(fixture_document(builder), [white, item])
    expected = [tuple(round(c * opacity + 255 * (1 - opacity)) for c in COLORS[i]) for i in ORIENTED[turn]]
    with fitz.open(stream=build(builder, document, tmp_path), filetype="pdf") as pdf:
        size = (pdf[0].rect.width, pdf[0].rect.height)
        for fractions in (((.25, .25), (.75, .25), (.25, .75), (.75, .75)), ((.06, .06), (.94, .06), (.06, .94), (.94, .94))):
            for point, color in zip(drawn_points(item, size, fractions, pixels), expected):
                assert_color(color_at(pdf[0], point), color, 6)


@pytest.mark.parametrize("turn", range(1, 9))
def test_docx_holds_a_camera_picture_upright(turn, tmp_path, image_path):
    from PIL import Image
    data, item = camera_item(tmp_path, turn)
    pixels = (100, 200) if turn >= 5 else (200, 100)
    document = put(fixture_document("operations"), [item])
    payload = build_docx("operations", document, tmp_path)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        media = [archive.read(name) for name in archive.namelist() if name.startswith("word/media/")]
    if turn == 1:
        assert data in media  # An upright picture keeps its original compressed bytes.
        stored = data
    else:
        assert data not in media
        stored = next(m for m in media if m[:3] == b"\xff\xd8\xff" and Image.open(io.BytesIO(m)).size == pixels)
    with Image.open(io.BytesIO(stored)) as picture:
        assert picture.getexif().get(0x0112, 1) == 1
        shown = picture.convert("RGB")
        for (u, v), index in zip(((.25, .25), (.75, .25), (.25, .75), (.75, .75)), ORIENTED[turn]):
            assert_color(shown.getpixel((int(u * pixels[0]), int(v * pixels[1]))), COLORS[index], 6)
    xml = docx_parts(payload)["word/document.xml"]
    native = next(d for d in xml.xpath("//wp:inline", namespaces=NS)
                  if d.xpath("wp:docPr/@descr", namespaces=NS) == ["Camera picture"])
    size = objects.page_size(document)
    _, (_, _, w, h) = objects.placement(item, (.4 * size[0], .3 * size[1]), pixels)
    extent = native.xpath(".//pic:spPr/a:xfrm/a:ext", namespaces=NS)[0]
    assert int(extent.get("cx")) == pytest.approx(w * 12700, abs=1)
    assert int(extent.get("cy")) == pytest.approx(h * 12700, abs=1)
    assert native.xpath(".//a:xfrm/@rot", namespaces=NS) == []
