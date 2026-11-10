"""P2b: real PDF and DOCX parts, export entry points, and legacy equality.

These tests use only temporary stores. Legacy oracles are the supervisor's
committed P2a-2/P2b-1 exporters, read with git show (no checkout/index changes).
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import hashlib
import itertools
import json
import os
import subprocess
import sys
import types
import io
import zipfile

import fitz
from PIL import Image
import pytest

from ai_inspector.documentation.commands import DocumentEditError
from ai_inspector.documentation.identity import VERSIONS
from ai_inspector.documentation.provenance import check_export
from ai_inspector.documentation.rich_text import from_plain, plain_text, validate
from ai_inspector.documentation.rich_layout import (
    content_model, layout_text, prepare_pdf_objects, draw_pdf_objects, finish_pdf_fonts, PDF_RENDERER_VERSION,
    BULLETS, LINE_HEIGHT, LINK_COLOR, LIST_INDENT, PADDING, SYNTHETIC_OBLIQUE,
)
from ai_inspector.parts_manual import pdf as parts
from ai_inspector.specification_sheet import exports as spec
from ai_inspector.operations_manual import exports as ops
from ai_inspector.work_instructions import exports as wi
from tests.test_documentation_refresh import mmle_client

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}


def docx_parts(payload):
    from lxml import etree
    from docx import Document
    Document(io.BytesIO(payload))  # A real python-docx package, not a constructed XML fragment.
    with zipfile.ZipFile(io.BytesIO(payload)) as package:
        return {name: etree.fromstring(package.read(name)) for name in package.namelist()
                if name.endswith((".xml", ".rels"))}


def xp(node, query):
    return node.xpath(query, namespaces=NS)


def authored_tables(document):
    return xp(document, '//w:tbl[w:tblPr/w:tblCaption[starts-with(@w:val,"Authored text: ")]]')


def build_docx(builder, document, root, module=None):
    if builder == "specification":
        return (module or spec).build_specification_docx_bytes(document, render_root=root, assembly_number=NUMBER)
    return (module or ops).build_prototype_docx_bytes(root, NUMBER, document)


@pytest.mark.parametrize("builder", ("specification", "operations", "wi"))
@pytest.mark.parametrize("mode", ("review", "draft", "customer", "controlled"))
def test_native_docx_runs_links_and_base_font(builder, mode, tmp_path, image_path):
    value = mixed()
    document = attach(fixture_document(builder, mode), value, style={"fontFamily": "Georgia", "fontSize": 13})
    document["pages"][0]["documentationObjects"][TARGET]["content"] = "DO NOT FLATTEN"
    before = deepcopy(document)
    package = docx_parts(build_docx(builder, document, tmp_path))
    table = authored_tables(package["word/document.xml"])[0]
    assert xml_text(table) == "Normal Bold Italic Both Under Red Link"
    for label, b, i, u, color in (("Normal ", "0", "0", "none", "18212A"),
        ("Bold ", "1", "0", "none", "18212A"), ("Italic ", "0", "1", "none", "18212A"),
        ("Both ", "1", "1", "none", "18212A"), ("Under ", "0", "0", "single", "18212A"),
        ("Red ", "0", "0", "none", "AB1234"), ("Link", "0", "0", "single", "0000EE")):
        run = next(r for r in xp(table, './/w:r') if xml_text(r) == label)
        assert xp(run, './w:rPr/w:b/@w:val') == [b]
        assert xp(run, './w:rPr/w:i/@w:val') == [i]
        assert xp(run, './w:rPr/w:u/@w:val') == [u]
        assert xp(run, './w:rPr/w:color/@w:val') == [color]
        assert xp(run, './w:rPr/w:sz/@w:val') == xp(run, './w:rPr/w:szCs/@w:val') == ["26"]
        for attribute in ("ascii", "hAnsi", "cs"):
            assert xp(run, './w:rPr/w:rFonts/@w:' + attribute) == ["Times New Roman"]
        assert not xp(run, './w:rPr/w:rFonts/@w:eastAsia')
    rid = xp(table, './/w:hyperlink/@r:id')[0]
    relation = next(r for r in package["word/_rels/document.xml.rels"] if r.get("Id") == rid)
    assert relation.get("Target") == "https://example.test/a?x=1&y=two%20words#part"
    assert relation.get("TargetMode") == "External"
    assert relation.get("Type").endswith("/hyperlink")
    assert not xp(table, './/w:rStyle[@w:val="Hyperlink"]')
    assert document == before


def test_docx_headings_empty_paragraph_marks_spacing_and_unicode(tmp_path, image_path):
    source = "  leading  e\u0301 \u4e2d\u6587 \U0001f642\tCR\r\nnext  "
    value = rich(*[{"type": "heading", "attrs": {"level": n}, "content": [text("Heading" + str(n))]} for n in (1, 2, 3)],
                 paragraph(), paragraph(text(source), {"type": "hardBreak"}),
                 paragraph(text("two"), {"type": "hardBreak"}, {"type": "hardBreak"}))
    document = attach(fixture_document("specification"), value, style={"fontFamily": "Courier", "fontSize": 16, "textAlign": "justify"})
    package = docx_parts(build_docx("specification", document, tmp_path))
    table = authored_tables(package["word/document.xml"])[0]
    paragraphs = xp(table, './w:tr/w:tc/w:p')
    assert [xp(p, './w:pPr/w:pStyle/@w:val') for p in paragraphs[:3]] == [["Heading1"], ["Heading2"], ["Heading3"]]
    sizes = [64, 48, 37, 32, 32, 32]
    for index, p in enumerate(paragraphs):
        assert xp(p, './w:pPr/w:jc/@w:val') == ["both"]
        assert xp(p, './w:pPr/w:spacing/@w:before') == xp(p, './w:pPr/w:spacing/@w:after') == ["0"]
        assert xp(p, './w:pPr/w:spacing/@w:lineRule') == ["atLeast"]
        size = (32, 24, 18.72, 16, 16, 16)[index]
        assert xp(p, './w:pPr/w:spacing/@w:line') == [str(round(size * 24))]
        assert xp(p, './w:pPr/w:rPr/w:sz/@w:val') == xp(p, './w:pPr/w:rPr/w:szCs/@w:val') == [str(sizes[index])]
        assert xp(p, './w:pPr/w:rPr/w:rFonts/@w:ascii') == ["Courier New"]
        if index < 3:
            assert xp(p, './w:r/w:rPr/w:b/@w:val') == ["1"]
            assert xp(p, './w:r/w:rPr/w:sz/@w:val') == [str(sizes[index])]
            assert xp(p, './w:r/w:rPr/w:color/@w:val') == ["18212A"]
    assert not xp(paragraphs[3], './w:r')
    assert xml_text(paragraphs[4]) == "  leading  e\u0301 \u4e2d\u6587 \U0001f642\tCR \nnext  "
    assert len(xp(paragraphs[4], './/w:tab')) == 1 and len(xp(paragraphs[4], './/w:br')) == 1
    assert xml_text(paragraphs[5]) == "two\n"
    assert all(t.get("{http://www.w3.org/XML/1998/namespace}space") == "preserve" for t in xp(table, './/w:t'))
    assert plain_text(value).endswith("two\n\n")  # Export has not changed the stored value.


def test_docx_native_numbering_order_starts_restarts_nesting_and_continuations(tmp_path):
    item = lambda *blocks: {"type": "listItem", "content": list(blocks)}
    bullet = lambda *items: {"type": "bulletList", "content": list(items)}
    ordered = lambda start, *items: {"type": "orderedList", "attrs": {"start": start}, "content": list(items)}
    value = rich(ordered(7, item(paragraph(text("seven")), paragraph(text("continuation")),
                     ordered(3, item(paragraph(text("nested")), ordered(9, item(paragraph(text("deep"))))))),
                     item(paragraph(text("eight")))),
                 ordered(2, item(paragraph(text("restart")))),
                 bullet(item(paragraph(text("disc")), bullet(item(paragraph(text("circle")), bullet(item(paragraph(text("square")))))))))
    document = attach(fixture_document("operations"), value)
    # The same model-local list IDs in a second field must not share Word counters.
    second = deepcopy(document["pages"][0]["documentationComposition"]["documentObjects"][TARGET])
    document["pages"][0]["documentationComposition"]["documentObjects"][TARGET + "-2"] = second
    package = docx_parts(build_docx("operations", document, tmp_path))
    tables = authored_tables(package["word/document.xml"])
    paragraphs = {xml_text(p): p for p in xp(tables[0], './/w:p')}
    numbering = package["word/numbering.xml"]
    tags = [e.tag.rsplit("}", 1)[-1] for e in numbering]
    assert max(i for i, tag in enumerate(tags) if tag == "abstractNum") < min(i for i, tag in enumerate(tags) if tag == "num")

    def definition(label):
        p = paragraphs[label]
        number = xp(p, './w:pPr/w:numPr/w:numId/@w:val')[0]
        level = xp(p, './w:pPr/w:numPr/w:ilvl/@w:val')[0]
        n = xp(numbering, './w:num[@w:numId="' + number + '"]')[0]
        aid = xp(n, './w:abstractNumId/@w:val')[0]
        return number, level, n, xp(numbering, './w:abstractNum[@w:abstractNumId="' + aid + '"]/w:lvl')[0]

    ids = []
    for label, depth, start in (("seven", 1, 7), ("nested", 2, 3), ("deep", 3, 9), ("restart", 1, 2)):
        number, level, n, definition_xml = definition(label)
        ids.append(number)
        assert level == str(depth - 1)
        assert xp(n, './w:lvlOverride/w:startOverride/@w:val') == [str(start)]
        assert xp(definition_xml, './w:lvlText/@w:val') == [f"%{depth}."]
        assert xp(definition_xml, './w:numFmt/@w:val') == ["decimal"]
        assert xp(paragraphs[label], './w:pPr/w:ind/@w:left') == [str(depth * 800)]
        # Right-aligned one Arial space (0.278 em of the fixture's 12 pt) before the text, like the canvas markers.
        assert xp(paragraphs[label], './w:pPr/w:ind/@w:hanging') == ["67"]
        assert xp(definition_xml, './w:lvlJc/@w:val') == ["right"]
    assert len(set(ids)) == 4
    assert definition("eight")[0] == definition("seven")[0]
    assert not xp(paragraphs["continuation"], './w:pPr/w:numPr')
    assert xp(paragraphs["continuation"], './w:pPr/w:ind/@w:left') == ["800"]
    for label, family, symbol in (("disc", "Symbol", "\uf0b7"), ("circle", "Courier New", "o"), ("square", "Wingdings", "\uf0a7")):
        d = definition(label)[3]
        assert xp(d, './w:numFmt/@w:val') == ["bullet"]
        assert xp(d, './w:lvlText/@w:val') == [symbol]
        assert xp(d, './w:rPr/w:rFonts/@w:ascii') == [family]
    assert set(xp(tables[0], './/w:numId/@w:val')).isdisjoint(xp(tables[1], './/w:numId/@w:val'))
    assert not any(marker in xml_text(tables[0]) for marker in ("7.", "3.", "9.", "\uf0b7"))


@pytest.mark.parametrize("builder", ("specification", "operations", "wi"))
def test_docx_table_geometry_width_cap_and_growing_cell(builder, tmp_path, image_path):
    document = attach(fixture_document(builder), "Long content\n" * 40,
                      style={"fill": "#eeccaa", "outlineColor": "#123456", "lineWidth": 2},
                      frame={"x": .1, "y": .2, "width": 1, "height": .01})
    writer = {"specification": spec.store_specification_docx, "operations": ops.store_prototype_docx, "wi": wi.store_review_docx}[builder]
    result = writer(tmp_path / "docx", NUMBER, document)
    payload = next((tmp_path / "docx").rglob("*.docx")).read_bytes()
    package = docx_parts(payload)
    table = authored_tables(package["word/document.xml"])[0]
    width, height, margins = (612, 792, 1.04 * 72) if builder == "specification" else (960, 540, 1.56 * 72)
    assert xp(table, './w:tblPr/w:tblW/@w:w') == [str(round((width - margins) * 20))]
    assert xp(table, './w:tblGrid/w:gridCol/@w:w') == xp(table, './w:tr/w:tc/w:tcPr/w:tcW/@w:w')
    assert xp(table, './w:tr/w:trPr/w:trHeight/@w:hRule') == ["atLeast"]
    assert xp(table, './w:tr/w:trPr/w:trHeight/@w:val') == [str(round(height * .01 * 20))]
    for side in ("top", "left", "bottom", "right"):
        assert xp(table, './/w:tcMar/w:' + side + '/@w:w') == ["100"]
        assert xp(table, './/w:tcBorders/w:' + side + '/@w:color') == ["123456"]
        assert xp(table, './/w:tcBorders/w:' + side + '/@w:sz') == ["16"]
    assert xp(table, './/w:tcPr/w:shd/@w:fill') == ["EECCAA"]
    assert not xp(table, './/w:txbxContent | .//w:pict | .//w:drawing')
    available = int(xp(table, "./w:tblPr/w:tblW/@w:w")[0]) / 20
    assert result["authoredText"]["widthCaps"] == [{"pageId": PAGE, "targetId": TARGET,
                                                   "requestedWidthPt": width, "widthPt": available}]
    assert xml_text(table).count("Long content") == 40


def test_docx_no_outline_padding_and_explicit_link_color(tmp_path):
    value = rich(paragraph(text("Tinted", {"type": "link", "attrs": {"href": "https://example.test/a%2Fb?x=1&y=2"}},
                                {"type": "textStyle", "attrs": {"color": "#aabbcc"}})))
    package = docx_parts(build_docx("operations", attach(fixture_document("operations"), value), tmp_path))
    table = authored_tables(package["word/document.xml"])[0]
    assert xp(table, './w:tblPr/w:tblBorders/*/@w:val') == ["nil"] * 6
    assert not xp(table, './/w:tcBorders')
    assert xp(table, './/w:tcMar/*/@w:w') == ["60"] * 4
    assert xp(table, './/w:shd/@w:fill') == ["FFFFFF"]
    assert xp(table, './/w:hyperlink/w:r/w:rPr/w:color/@w:val') == ["AABBCC"]
    assert xp(table, './/w:hyperlink/w:r/w:rPr/w:u/@w:val') == ["single"]


def test_docx_cache_rebuilds_previously_dropped_plain_objects(tmp_path):
    document = attach(fixture_document("operations"), "Previously missing")
    result = ops.store_prototype_docx(tmp_path, NUMBER, document)
    assert result["rendererVersion"] == "authored-text-docx-1"
    metadata = next(tmp_path.rglob("review-docx.json"))
    old = json.loads(metadata.read_text("ascii"))
    old["rendererVersion"] = ops._DOCX_RENDERER_VERSION
    old.pop("authoredText")
    metadata.write_bytes(json.dumps(old).encode("ascii"))
    assert not ops.store_prototype_docx(tmp_path, NUMBER, document)["cacheHit"]
    assert ops.store_prototype_docx(tmp_path, NUMBER, document)["cacheHit"]


def test_docx_invalid_xml_control_is_an_explicit_refusal(tmp_path):
    document = attach(fixture_document("operations"), from_plain("bad\x00control"))
    with pytest.raises(DocumentEditError) as caught:
        ops.store_prototype_docx(tmp_path, NUMBER, document)
    assert caught.value.code == "unsupported_export_character"
    assert caught.value.details["codePoints"] == ["U+0000"]
    assert caught.value.details["targets"] == [{"pageId": PAGE, "targetId": TARGET}]
    assert not list(tmp_path.rglob("*.docx"))


def add_ordered_objects(document, page, placements):
    for key, top, left in placements:
        obj = {"type": "text", "objectId": key, "content": key,
               "frame": {"x": left, "y": top, "width": .3, "height": .05}}
        page.setdefault("documentationComposition", {}).setdefault("documentObjects", {})[key] = obj


@pytest.mark.parametrize("builder", ("operations", "wi"))
def test_docx_objects_interleave_cover_body_and_end_before_page_break(builder, tmp_path, image_path, monkeypatch):
    monkeypatch.setattr(ops, "document_draft_render_path", lambda *args: image_path)
    document = fixture_document(builder)
    cover = document["pages"][0]
    cover.update(pageType="operations_cover", layoutBlocks=[
        {"blockId": "cover-kicker", "frame": {"y": 80}}, {"blockId": "cover-product", "frame": {"y": 120}}])
    document["product"]["name"] = "GENERATED TITLE"
    document["coverKicker"] = "GENERATED KICKER"
    add_ordered_objects(document, cover, [("cover-before", .01, .1), ("cover-between", .18, .1), ("cover-end", .95, .1)])
    body = {"pageId": "body", "pageNumber": 2, "pageType": "operations_section", "layoutBlocks": [
        {"blockId": "one", "blockType": "paragraph", "text": "GENERATED ONE", "frame": {"y": 100}},
        {"blockId": "two", "blockType": "paragraph", "text": "GENERATED TWO", "frame": {"y": 300}}]}
    add_ordered_objects(document, body, [("body-z", .3, .2), ("body-a", .3, .2), ("body-left", .3, .1), ("body-end", .99, .1)])
    document["pages"].append(body)
    document["pageCount"] = 2
    xml = docx_parts(build_docx(builder, document, tmp_path))["word/document.xml"]
    children = xp(xml, './w:body/*')
    labels = [xml_text(c) for c in children]
    selected = [s for s in labels if s.startswith(("cover-", "body-", "GENERATED"))]
    assert selected == ["cover-before", "GENERATED KICKER", "cover-between", "GENERATED TITLE", "cover-end",
                        "GENERATED ONE", "body-left", "body-a", "body-z", "GENERATED TWO", "body-end"]
    break_index = next(i for i, c in enumerate(children) if xp(c, './/w:br[@w:type="page"]'))
    assert labels.index("cover-end") < break_index < labels.index("GENERATED ONE")


def test_docx_specification_section_flush_order(tmp_path, image_path):
    document = fixture_document("specification")
    blocks = document["pages"][0]["layoutBlocks"]
    for block in blocks:
        block["open"] = False
        block["text"] = block["blockId"]
    add_ordered_objects(document, document["pages"][0], [("before-kicker", .01, .1), ("before-title", .1, .1),
        ("before-tagline", .13, .1), ("before-main", .2, .1), ("before-features", .6, .1), ("before-notes", .9, .1), ("after-notes", .99, .1)])
    xml = docx_parts(build_docx("specification", document, tmp_path))["word/document.xml"]
    labels = [xml_text(c) for c in xp(xml, './w:body/*')]
    def index(prefix):
        return next(i for i, label in enumerate(labels) if label.startswith(prefix))
    assert index("before-kicker") < index("spec-kicker") < index("before-title") < index("spec-title")
    assert index("spec-title") < index("before-tagline") < index("spec-tagline") < index("before-main")
    assert index("before-main") < index("Specifications") < index("before-features") < index("features-heading")
    assert index("features-heading") < index("before-notes") < index("after-notes")


@pytest.mark.parametrize("builder", ("specification", "operations", "wi"))
def test_docx_rotation_refuses_before_artifact_write(builder, tmp_path, image_path):
    writer = {"specification": spec.store_specification_docx, "operations": ops.store_prototype_docx, "wi": wi.store_review_docx}[builder]
    document = attach(fixture_document(builder), mixed(), frame={"x": .1, "y": .1, "width": .3, "height": .3, "rotation": 15})
    with pytest.raises(DocumentEditError) as caught:
        writer(tmp_path / "refused", NUMBER, document)
    assert caught.value.code == "unsupported_export_rotation"
    assert caught.value.details["targets"] == [{"pageId": PAGE, "targetId": TARGET}]
    assert not list((tmp_path / "refused").rglob("*.docx"))


@pytest.mark.parametrize("builder", ("specification", "operations", "wi"))
@pytest.mark.parametrize("mode", ("review", "draft", "customer", "controlled"))
def test_docx_legacy_xml_parts_equal_p2b1(builder, mode, tmp_path, image_path, monkeypatch):
    from lxml import etree
    document = fixture_document(builder, mode)
    old = legacy_module(spec if builder == "specification" else ops, monkeypatch, "9b01855")
    if builder == "specification":
        old.draft_render_path = lambda *args: image_path
    current = docx_parts(build_docx(builder, document, tmp_path))
    previous = docx_parts(build_docx(builder, document, tmp_path, old))
    assert current.keys() == previous.keys()
    for name in current:
        assert etree.tostring(current[name]) == etree.tostring(previous[name]), name


@pytest.mark.parametrize("builder", ("parts", "specification", "fillable", "operations", "wi"))
def test_rich_pdf_bytes_unchanged_since_p2b1(builder, tmp_path, image_path, monkeypatch):
    document = attach(fixture_document(builder), mixed())
    save = fitz.Document.tobytes
    monkeypatch.setattr(fitz.Document, "tobytes", lambda self, *a, **kw: save(self, *a, **{**kw, "no_new_id": True}))
    old = legacy_module(parts if builder == "parts" else spec if builder in {"specification", "fillable"} else ops, monkeypatch, "9b01855")
    if builder in {"specification", "fillable"}:
        old.draft_render_path = lambda *args: image_path
    modules = (old if builder == "parts" else parts, old if builder in {"specification", "fillable"} else spec,
               old if builder in {"operations", "wi"} else ops)
    assert build(builder, document, tmp_path) == build(builder, document, tmp_path, modules=modules)


def xml_text(node):
    return "".join("\n" if e.tag == "{" + NS["w"] + "}br" else "\t" if e.tag == "{" + NS["w"] + "}tab" else e.text or ""
                   for e in xp(node, './/w:t | .//w:br | .//w:tab'))

ROOT = Path(__file__).resolve().parents[1]
LEGACY_COMMIT = "b616417"
PAGE, TARGET, NUMBER = "proof-page", "document-object-proof", "PROOF"
# The parts store names its artifact folder by revision and accepts only a SHA-256.
REVISION = hashlib.sha256(b"rev-proof").hexdigest()
MODES = ("review", "draft", "customer", "controlled")
BUILDERS = ("parts", "specification", "fillable", "operations", "wi")
KINDS = {"parts": "illustrated_parts_manual", "specification": "product_specification_sheet",
         "fillable": "product_specification_sheet", "operations": "operations_and_maintenance_manual",
         "wi": "work_instructions"}


def rich(*blocks):
    count = itertools.count(1)

    def node(value):
        value = deepcopy(value)
        if value["type"] not in {"doc", "text"}:
            value.setdefault("attrs", {})["id"] = f"rt-00000000-0000-4000-8000-{next(count):012x}"
        if "content" in value:
            value["content"] = [node(child) for child in value["content"]]
        return value

    return validate({"format": "tiptap", "schemaVersion": 1,
                     "doc": node({"type": "doc", "content": list(blocks)})})


def text(value, *marks):
    return {"type": "text", "text": value, "marks": list(marks)}


def paragraph(*runs):
    return {"type": "paragraph", "content": list(runs)}


def mixed():
    return rich(paragraph(text("Normal "), text("Bold ", {"type": "bold"}),
        text("Italic ", {"type": "italic"}), text("Both ", {"type": "bold"}, {"type": "italic"}),
        text("Under ", {"type": "underline"}), text("Red ", {"type": "textStyle", "attrs": {"color": "#ab1234"}}),
        text("Link", {"type": "link", "attrs": {"href": "https://example.test/a?x=1&y=two%20words#part"}})))


def attach(document, value, *, style=None, frame=None):
    obj = {"objectId": TARGET, "type": "text", "name": "Proof", "content": deepcopy(value), "styleRef": "body",
           "frame": frame or {"x": 0.1, "y": 0.2, "width": 0.8, "height": 0.5, "rotation": 0},
           "styleOverrides": {"fontSize": 12, "color": "#18212a", **(style or {})}}
    page = document["pages"][0]
    page["documentationComposition"] = {"documentObjects": {TARGET: deepcopy(obj)}}
    if isinstance(value, dict):
        obj.update(content=plain_text(value), isRichText=True)
    page["documentationObjects"] = {TARGET: obj}
    return document


def fixture_document(builder, mode="review"):
    kind = KINDS[builder]
    return {"documentType": kind, "schemaVersion": VERSIONS[kind], "fieldMeta": {}, "provenanceTargets": [],
        "sourceRevision": "source-proof", "manualPlanRevision": "plan-proof", "documentRevision": REVISION,
        "documentNumber": "PROOF-001", "title": "Proof export", "pageCount": 1, "exportMode": mode,
        "product": {"name": "Proof", "assemblyNumber": NUMBER}, "status": "publication_ready",
        "publicationAudit": {"status": "PASS"}, "calloutAudit": {"status": "PASS"},
        "releaseGate": {"controlledPdfAllowed": True, "reviewPdfAllowed": True},
        "slots": {"proof": {"name": "Proof input"}} if builder in {"specification", "fillable"} else {},
        "pages": [{"pageId": PAGE, "pageNumber": 1, "title": "Proof page", "entries": [],
                   "pageType": "table_of_contents" if builder == "parts" else "product_specification" if builder in {"specification", "fillable"} else "operations_section",
                   "layoutBlocks": [
                       {"blockId": key, "text": "", "title": "", "open": key == "spec-kicker", "slot": "proof",
                        "frame": {"x": 36, "y": y, "width": 220, "height": 100}}
                       for key, y in [("spec-kicker", 70), ("spec-title", 85), ("spec-tagline", 110),
                                      ("features-heading", 550), ("spec-feature-1", 600),
                                      ("spec-feature-2", 600), ("spec-feature-3", 600)]
                   ] if builder in {"specification", "fillable"} else []}]}


@pytest.fixture
def image_path(tmp_path, monkeypatch):
    image = tmp_path / "capture.png"
    Image.new("RGB", (80, 80), "white").save(image)
    # The fixture has no capture request. Only the required image file lookup is
    # redirected; all PDF layout, drawing, readiness and export gates are real.
    monkeypatch.setattr(spec, "draft_render_path", lambda *args: image)
    return image


def build(builder, document, root, *, modules=None):
    p, s, o = modules or (parts, spec, ops)
    if builder == "parts":
        return p.build_manual_pdf_bytes(root, NUMBER, document)
    if builder == "specification":
        return s.build_specification_pdf_bytes(document, render_root=root, assembly_number=NUMBER)
    if builder == "fillable":
        return s.build_specification_fillable_pdf_bytes(document, render_root=root, assembly_number=NUMBER)[0]
    return o.build_prototype_pdf_bytes(root, NUMBER, document)


def store_pdf(builder, document, root):
    return {"parts": parts.store_manual_pdf, "specification": spec.store_specification_pdf,
            "fillable": spec.store_specification_fillable_pdf, "operations": ops.store_prototype_pdf,
            "wi": wi.store_review_pdf}[builder](root, NUMBER, document)


def isolated_pdf(value, *, style=None, frame=None):
    document = attach(fixture_document("operations"), value, style=style, frame=frame)
    plans = prepare_pdf_objects(fitz, document, (600, 700))
    with fitz.open() as pdf:
        page = pdf.new_page(width=600, height=700)
        draw_pdf_objects(fitz, page, document["pages"][0], plans)
        finish_pdf_fonts(pdf, plans)
        payload = pdf.tobytes(garbage=4, deflate=True)  # as the real builders save
    return payload, plans[PAGE][TARGET]


def spans(page):
    return [span for block in page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
            if "lines" in block for line in block["lines"] for span in line["spans"]]


def test_mixed_pdf_runs_fonts_colors_underlines_and_exact_links():
    value = mixed()
    before = deepcopy(value)
    payload, plan = isolated_pdf(value, style={"fill": "#eeeecc", "outlineColor": "#123456", "lineWidth": 2})
    assert value == before
    with fitz.open(stream=payload, filetype="pdf") as pdf:
        page = pdf[0]
        rows = spans(page)
        for word, bold, italic in [("Normal", False, False), ("Bold", True, False), ("Italic", False, True), ("Both", True, True)]:
            span = next(s for s in rows if word in s["text"])
            assert bool(span["flags"] & 16) is bold
            assert bool(span["flags"] & 2) is italic
            # Subsetting renames a font to e.g. "ABCDEF+Nimbus Sans Regular".
            assert any(name in span["font"].lower().replace(" ", "") for name in ("helvetica", "nimbussans")), span
        assert next(s for s in rows if "Red" in s["text"])["color"] == 0xAB1234
        underline = next(r for line in plan.layout.lines for r in line.runs if r.underline)
        assert any(item[0] == "l" and abs(item[1].y - (underline.baseline + underline.font_size * .1)) < .05
                   and abs(item[2].x - item[1].x - underline.width) < .05
                   for drawing in page.get_drawings() for item in drawing["items"])
        drawings = page.get_drawings()
        assert any(d["fill"] == pytest.approx((238/255, 238/255, 204/255), abs=.001) for d in drawings if d["fill"])
        assert any(d["width"] == 2 and d["color"] == pytest.approx((18/255, 52/255, 86/255), abs=.001) for d in drawings if d["color"])
        links = page.get_links()
        assert len(links) == 1 and links[0]["uri"] == "https://example.test/a?x=1&y=two%20words#part"
        linked = next(r for line in plan.layout.lines for r in line.runs if r.href)
        assert tuple(links[0]["from"]) == pytest.approx(linked.rect, abs=.01)
        for span in rows:
            x0, y0, x1, y1 = span["bbox"]
            assert x0 >= plan.frame[0] - .1 and y0 >= plan.frame[1] - .1
            assert x1 <= plan.frame[2] + .1 and y1 <= plan.frame[3] + .1


@pytest.mark.parametrize("family,fragment", [("Arial", ("helvetica", "nimbussans")),
    ("Times New Roman", ("times", "nimbusroman")), ("Courier New", ("courier", "nimbusmono"))])
def test_object_base_font_family_and_marks(family, fragment):
    payload, _ = isolated_pdf(mixed(), style={"fontFamily": family})
    with fitz.open(stream=payload, filetype="pdf") as pdf:
        for span in spans(pdf[0]):
            assert any(name in span["font"].lower().replace(" ", "") for name in fragment), span


def test_hard_breaks_headings_lists_starts_and_three_levels():
    item = lambda *blocks: {"type": "listItem", "content": list(blocks)}
    bullet = lambda *items: {"type": "bulletList", "content": list(items)}
    ordered = lambda start, *items: {"type": "orderedList", "attrs": {"start": start}, "content": list(items)}
    value = rich(*[{"type": "heading", "attrs": {"level": n}, "content": [text(f"Heading{n}")]} for n in (1, 2, 3)],
        paragraph(text("first"), {"type": "hardBreak"}, text("next")),
        ordered(7, item(paragraph(text("seven")), paragraph(text("continuation")),
                        bullet(item(paragraph(text("second level")), ordered(3, item(paragraph(text("third level"))))))),
                   item(paragraph(text("eight")))),
        ordered(1, item(paragraph(text("restart")))))
    payload, plan = isolated_pdf(value, style={"fontSize": 10}, frame={"x": .05, "y": .05, "width": .9, "height": .9})
    paragraphs = plan.layout.content.paragraphs
    assert [p.font_size for p in paragraphs[:3]] == pytest.approx([20, 15, 11.7])
    assert [p.marker for p in paragraphs if p.marker] == ["7.", "\u25e6", "3.", "8.", "1."]
    assert max(len(p.list_path) for p in paragraphs) == 3
    assert paragraphs[4].list_path[-1].list_id == paragraphs[5].list_path[-1].list_id
    assert paragraphs[-1].list_path[-1].list_id != paragraphs[4].list_path[-1].list_id
    body_x = {r.text: r.x for line in plan.layout.lines for r in line.runs if not r.marker}
    assert body_x["seven"] == body_x["continuation"] < body_x["second level"] < body_x["third level"]
    with fitz.open(stream=payload, filetype="pdf") as pdf:
        extracted = pdf[0].get_text()
        assert all(word in extracted for word in ("7.", "8.", "1.", "3.", "\u25e6", "first", "next", "continuation"))
        rows = spans(pdf[0])
        assert [next(s["size"] for s in rows if f"Heading{n}" in s["text"]) for n in (1, 2, 3)] == pytest.approx([20, 15, 11.7])
        assert all(next(s for s in rows if f"Heading{n}" in s["text"])["flags"] & 16 for n in (1, 2, 3))


def test_whitespace_nfc_tabs_and_cjk_do_not_mutate_canonical_content():
    source = "  lead  repeat\tend  \n\ne\u0301 \u4e2d\u6587"
    value = from_plain(source)
    original = deepcopy(value)
    model = content_model(value)
    assert "".join("\n" if r.kind == "break" else r.text for r in model.paragraphs[0].runs) == source
    layout = layout_text(value, (10, 10, 550, 650))
    try:
        cjk = fitz.Font(fontname="cjk")
        available = all(cjk.has_glyph(ord(c), fallback=False) for c in "\u4e2d\u6587")
    except (ValueError, RuntimeError):
        available = False
    if not available:
        assert {"U+4E2D", "U+6587"} & set(layout.unrenderable)
        with pytest.raises(DocumentEditError, match="built-in PDF font") as caught:
            isolated_pdf(value)
        assert caught.value.code == "unsupported_export_glyph"
        return
    payload, plan = isolated_pdf(value)
    assert not layout.unrenderable
    assert ["".join(r.text for r in line.runs) for line in plan.layout.lines] == ["  lead  repeat    end  ", "", "\u00e9 \u4e2d\u6587"]
    assert any(r.font == "cjk" for line in plan.layout.lines for r in line.runs)
    with fitz.open(stream=payload, filetype="pdf") as pdf:
        extracted = "".join(s["text"] for s in spans(pdf[0]))
        assert "  lead  repeat    end  " in extracted
        assert "\u00e9 \u4e2d\u6587" in extracted
    assert value == original and plain_text(value) == source


def test_word_wrap_keeps_spaces_and_uses_real_font_advance():
    source = "  alpha  beta supercalifragilisticexpialidocious  end  "
    layout = layout_text(from_plain(source), (10, 10, 95, 650), {"fontSize": 12})
    assert not layout.overflow and len(layout.lines) > 1
    assert "".join(r.text for line in layout.lines for r in line.runs) == source
    for line in layout.lines:
        for run in line.runs:
            assert run.width == pytest.approx(fitz.Font(fontname=run.font).text_length(run.text, fontsize=run.font_size))
            assert run.rect[0] >= 10 - .01 and (run.hanging or run.rect[2] <= 95 + .01)
        # A wrapped line never starts with the space it wrapped at (white-space: pre-wrap).
        assert line is layout.lines[0] or not line.runs[0].text.startswith(" ")
    # The first word fits together after the leading whitespace; wrapping does
    # not arbitrarily split a word that fits on a fresh line.
    assert any("alpha" in "".join(r.text for r in line.runs) for line in layout.lines)
    narrow = layout_text(from_plain("W"), (0, 0, 1, 100))
    assert narrow.overflow


@pytest.mark.parametrize("mark", ["bold", "italic"])
def test_cjk_fallback_synthesizes_bold_and_italic_like_the_browser(mark):
    value = rich(paragraph(text("A\u4e2d", {"type": mark})))
    payload, plan = isolated_pdf(value)
    runs = [run for line in plan.layout.lines for run in line.runs]
    assert [run.font for run in runs] == [("hebo" if mark == "bold" else "heit"), "cjk"]
    with fitz.open(stream=payload, filetype="pdf") as pdf:
        page = pdf[0]
        assert "A\u4e2d" in page.get_text()
        traces = [t for t in page.get_texttrace() if "Droid" in t["font"]]
        content = page.read_contents().decode("latin-1")
        if mark == "bold":
            # Fill plus stroke (render mode 2), stroked in the text color.
            assert {t["type"] for t in traces} == {0, 1}
            assert " 2 Tr " in content
        else:
            assert {t["type"] for t in traces} == {0}
            assert f"1 0 {SYNTHETIC_OBLIQUE:g} 1 ".replace("0.", ".") in content


@pytest.mark.parametrize("alignment", ["left", "center", "right"])
def test_alignment_and_wrapped_link_rectangles(alignment):
    href = "http://example.test/proof?x=1&y=2#section"
    source = "linked words with enough text to wrap onto several lines"
    value = rich(paragraph(text(source, {"type": "link", "attrs": {"href": href}}, {"type": "underline"})))
    payload, plan = isolated_pdf(value, style={"textAlign": alignment},
                                 frame={"x": .1, "y": .1, "width": .2, "height": .8})
    assert len(plan.layout.lines) > 1
    assert "".join(r.text for line in plan.layout.lines for r in line.runs) == source
    for line in plan.layout.lines:
        left = min(r.rect[0] for r in line.runs if not r.hanging)
        right = max(r.rect[2] for r in line.runs if not r.hanging)
        if alignment == "left":
            assert left == pytest.approx(plan.layout.frame[0], abs=.01)
        elif alignment == "right":
            assert right == pytest.approx(plan.layout.frame[2], abs=.01)
        else:
            assert left - plan.layout.frame[0] == pytest.approx(plan.layout.frame[2] - right, abs=.01)
    with fitz.open(stream=payload, filetype="pdf") as pdf:
        links = pdf[0].get_links()
        assert len(links) == sum(1 for line in plan.layout.lines for r in line.runs if not r.hanging)
        assert all(link["uri"] == href for link in links)
        assert len([d for d in pdf[0].get_drawings() if any(i[0] == "l" for i in d["items"])]) == len(links)


@pytest.mark.parametrize("builder", BUILDERS)
@pytest.mark.parametrize("mode", MODES)
def test_every_pdf_builder_draws_canonical_rich_objects(builder, mode, tmp_path, image_path):
    document = attach(fixture_document(builder, mode), mixed())
    # Deliberately wrong display projection proves the exporter uses the envelope.
    document["pages"][0]["documentationObjects"][TARGET]["content"] = "PROJECTION MUST NOT EXPORT"
    before = deepcopy(document)
    with fitz.open(stream=build(builder, document, tmp_path), filetype="pdf") as pdf:
        page = pdf[0]
        assert "Bold" in page.get_text() and "PROJECTION MUST NOT EXPORT" not in page.get_text()
        bold = next(s for s in spans(page) if "Bold" in s["text"])
        assert bold["flags"] & 16
        assert bold["bbox"][0] >= page.rect.width * .1
        assert bold["bbox"][1] == pytest.approx(page.rect.height * .2 + 2, abs=.2)
        assert page.get_links()[0]["uri"] == "https://example.test/a?x=1&y=two%20words#part"
        if builder == "fillable":
            assert len(list(page.widgets())) == 1
    assert document == before


@pytest.mark.parametrize("builder", BUILDERS)
@pytest.mark.parametrize("mode", MODES)
def test_every_pdf_store_writes_rich_content(builder, mode, tmp_path, image_path):
    store = tmp_path / "store"
    result = store_pdf(builder, attach(fixture_document(builder, mode), mixed()), store)
    assert result["status"] == "ready"
    output = list(store.rglob("*.pdf"))
    assert len(output) == 1
    with fitz.open(output[0]) as pdf:
        assert "Bold" in pdf[0].get_text()
        assert next(s for s in spans(pdf[0]) if "Bold" in s["text"])["flags"] & 16


@pytest.mark.parametrize("builder", ("specification", "fillable", "operations", "wi"))
def test_previously_dropped_plain_objects_are_present_at_their_frames(builder, tmp_path, image_path):
    frame = {"x": .12, "y": .25, "width": .7, "height": .2}
    document = attach(fixture_document(builder), "Authored plain proof", frame=frame)
    with fitz.open(stream=build(builder, document, tmp_path), filetype="pdf") as pdf:
        span = next(s for s in spans(pdf[0]) if "Authored plain proof" in s["text"])
        assert span["bbox"][0] == pytest.approx(pdf[0].rect.width * .12 + 3, abs=.1)
        assert span["bbox"][1] == pytest.approx(pdf[0].rect.height * .25 + 2, abs=.2)


@pytest.mark.parametrize("builder", BUILDERS)
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("failure", ["glyph", "overflow", "rotation"])
def test_refusals_name_targets_and_write_no_artifact(builder, mode, failure, tmp_path, image_path):
    source = "\U0001fae8" if failure == "glyph" else "large proof " * 60 if failure == "overflow" else "rotated"
    frame = {"x": .1, "y": .2, "width": .3, "height": .02 if failure == "overflow" else .3,
             "rotation": 15 if failure == "rotation" else 0}
    document = attach(fixture_document(builder, mode), from_plain(source), frame=frame)
    destination = tmp_path / "refused"
    with pytest.raises(DocumentEditError) as caught:
        store_pdf(builder, document, destination)
    assert caught.value.code == {"glyph": "unsupported_export_glyph", "overflow": "layout_overflow",
                                 "rotation": "unsupported_export_rotation"}[failure]
    assert caught.value.details["targets"][0]["targetId"] == TARGET
    assert caught.value.details["targets"][0]["pageId"] == PAGE
    if failure == "glyph":
        assert caught.value.details["codePoints"] == ["U+1FAE8"]
        assert caught.value.details["targets"][0]["codePoints"] == ["U+1FAE8"]
    assert not list(destination.rglob("*.pdf")) and not list(destination.rglob("*.json"))


@pytest.mark.parametrize("builder", ("specification", "fillable", "operations", "wi"))
def test_new_plain_path_also_refuses_overflow(builder, tmp_path, image_path):
    document = attach(fixture_document(builder), "A plain object needs room",
                      frame={"x": .1, "y": .2, "width": .1, "height": .001})
    with pytest.raises(DocumentEditError) as caught:
        store_pdf(builder, document, tmp_path / "refused")
    assert caught.value.code == "layout_overflow"
    assert caught.value.details["targets"][0]["targetId"] == TARGET
    assert not list((tmp_path / "refused").rglob("*.pdf"))


def test_parts_plain_overflow_is_unchanged_p4b_backlog(tmp_path):
    document = attach(fixture_document("parts"), "LEGACY SILENT DROP",
                      frame={"x": .1, "y": .2, "width": .4, "height": .01})
    with fitz.open(stream=build("parts", document, tmp_path), filetype="pdf") as pdf:
        assert "LEGACY SILENT DROP" not in pdf[0].get_text()


def test_glyph_preflight_collects_all_bad_fields_and_code_points():
    document = attach(fixture_document("operations"), from_plain("\U0001fae8"))
    page = document["pages"][0]
    second = deepcopy(page["documentationComposition"]["documentObjects"][TARGET])
    second["content"] = from_plain("\U0010ffff")
    page["documentationComposition"]["documentObjects"]["document-object-other"] = second
    with pytest.raises(DocumentEditError) as caught:
        prepare_pdf_objects(fitz, document, (600, 700))
    assert caught.value.code == "unsupported_export_glyph"
    assert {t["targetId"] for t in caught.value.details["targets"]} == {TARGET, "document-object-other"}
    assert set(caught.value.details["codePoints"]) == {"U+1FAE8", "U+10FFFF"}


def test_missing_or_invalid_canonical_envelope_never_exports_projection():
    document = attach(fixture_document("operations"), mixed())
    del document["pages"][0]["documentationComposition"]
    with pytest.raises(DocumentEditError) as caught:
        prepare_pdf_objects(fitz, document, (600, 700))
    assert caught.value.code == "missing_rich_text_content"
    document = attach(fixture_document("operations"), mixed())
    document["pages"][0]["documentationComposition"]["documentObjects"][TARGET]["content"]["doc"]["content"][0]["type"] = "image"
    with pytest.raises(DocumentEditError) as caught:
        prepare_pdf_objects(fitz, document, (600, 700))
    assert caught.value.details["targets"][0]["targetId"] == TARGET


def test_parts_direct_helper_uses_composition_even_without_display_objects(tmp_path):
    document = attach(fixture_document("parts"), mixed())
    descriptor = document["pages"][0]
    descriptor.pop("documentationObjects")
    with fitz.open() as pdf:
        page = pdf.new_page(width=792, height=612)
        parts._draw_documentation_objects(fitz, page, descriptor, document, tmp_path, NUMBER)
        payload = pdf.tobytes()
    with fitz.open(stream=payload, filetype="pdf") as pdf:
        assert next(s for s in spans(pdf[0]) if "Bold" in s["text"])["flags"] & 16


def legacy_module(current, monkeypatch, commit=LEGACY_COMMIT):
    relative = Path(current.__file__).resolve().relative_to(ROOT).as_posix()
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    source = subprocess.run(["git", "show", f"{commit}:{relative}"], cwd=ROOT,
                            capture_output=True, check=True, creationflags=flags).stdout
    name = current.__package__ + "._p2b_legacy_export"
    module = types.ModuleType(name)
    module.__package__, module.__file__ = current.__package__, current.__file__
    monkeypatch.setitem(sys.modules, name, module)
    exec(compile(source, relative, "exec"), module.__dict__)
    return module


@pytest.mark.parametrize("builder", BUILDERS)
@pytest.mark.parametrize("mode", MODES)
def test_legacy_export_bytes_equal_p2a_head(builder, mode, tmp_path, image_path, monkeypatch):
    document = fixture_document(builder, mode)
    if builder == "parts":
        attach(document, "Plain legacy object\nsecond line", style={"fontFamily": "Times New Roman", "fontStyle": "italic",
            "textDecoration": "underline", "fill": "#eeeeee", "outlineColor": "#334455"})
    # A fresh PDF normally generates a random trailer ID. Disable only that
    # entropy identically in both builders; every actual emitted byte is compared.
    save = fitz.Document.tobytes
    monkeypatch.setattr(fitz.Document, "tobytes", lambda self, *a, **kw: save(self, *a, **{**kw, "no_new_id": True}))
    legacy = legacy_module(parts if builder == "parts" else spec if builder in {"specification", "fillable"} else ops, monkeypatch)
    if builder in {"specification", "fillable"}:
        legacy.draft_render_path = lambda *args: image_path
    modules = (legacy if builder == "parts" else parts,
               legacy if builder in {"specification", "fillable"} else spec,
               legacy if builder in {"operations", "wi"} else ops)
    assert build(builder, deepcopy(document), tmp_path) == build(builder, deepcopy(document), tmp_path, modules=modules)


def test_operations_cache_invalidates_only_authored_text_exports(tmp_path, image_path):
    document = attach(fixture_document("operations"), "Previously dropped plain object")
    first = ops.store_prototype_pdf(tmp_path, NUMBER, document)
    assert first["rendererVersion"] == PDF_RENDERER_VERSION
    metadata = next(tmp_path.rglob("review-pdf.json"))
    descriptor = json.loads(metadata.read_text(encoding="ascii"))
    descriptor.pop("rendererVersion")
    metadata.write_text(json.dumps(descriptor), encoding="ascii")
    second = ops.store_prototype_pdf(tmp_path, NUMBER, document)
    assert not second["cacheHit"]
    assert ops.store_prototype_pdf(tmp_path, NUMBER, document)["cacheHit"]
    plain = fixture_document("operations")
    plain["documentRevision"] = "no-objects"
    assert "rendererVersion" not in ops.store_prototype_pdf(tmp_path, NUMBER, plain)
    assert ops.store_prototype_pdf(tmp_path, NUMBER, plain)["cacheHit"]


@pytest.mark.parametrize("builder", BUILDERS)
def test_rich_export_keeps_conflict_and_citation_release_gates(builder, tmp_path, image_path):
    document = attach(fixture_document(builder), mixed())
    document["conflicts"] = [{"conflictId": "conflict-proof", "pageId": PAGE, "targetId": TARGET, "status": "open"}]
    with fitz.open(stream=build(builder, document, tmp_path), filetype="pdf") as pdf:
        assert "Open manual edit conflict" in pdf[0].get_text()
    for mode in ("customer", "controlled"):
        with pytest.raises(DocumentEditError) as caught:
            check_export(document, mode)
        assert caught.value.code == "manual_edit_conflict"
    document.pop("conflicts")
    document["provenanceTargets"] = [{"targetId": TARGET, "pageId": PAGE, "alias": TARGET,
                                     "provenance": {"evidenceStatus": "edited_unverified"}}]
    for mode in ("customer", "controlled"):
        with pytest.raises(DocumentEditError) as caught:
            check_export(document, mode)
        assert caught.value.code == "unconfirmed_cited_values"


@pytest.mark.parametrize("builder,route,loader,pdf_writer,docx_writer", [
    ("specification", "specification-sheet", "_specification_sheet_build_document_with_scene", "store_specification_pdf", "store_specification_docx"),
    ("operations", "operations-manual", "_operations_manual_build_document_with_scene", "store_prototype_pdf", "store_prototype_docx"),
    ("wi", "work-instructions", "_work_instruction_build_document_with_scene", "store_work_instruction_review_pdf", "store_work_instruction_review_docx"),
])
@pytest.mark.parametrize("mode", MODES)
def test_combined_http_route_returns_real_docx_for_rich_document(builder, route, loader, pdf_writer, docx_writer, mode,
                                                               mmle_client, monkeypatch, image_path):
    import server
    document = attach(fixture_document(builder, mode), mixed())
    monkeypatch.setattr(server, loader, lambda **kwargs: (document, {}))
    # Keep the real builders/stores and download the route's actual companion.
    response = mmle_client.post(f"/api/{route}/MMLE-50D/pdf?mode={mode}")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["success"] and result["docx"]["status"] == "ready" and result["docx"]["url"]
    download = mmle_client.get(result["docx"]["url"])
    assert download.status_code == 200, download.text[:200] if not download.content.startswith(b"PK") else ""
    assert authored_tables(docx_parts(download.content)["word/document.xml"])


def test_layout_matches_the_canvas_box_css():
    # 12 pt Helvetica: lines are LINE_HEIGHT x size (CSS line-height: 1.2), not the font's natural 1.374.
    value = rich(paragraph(text("one")), paragraph(text("two")), paragraph(text("three")))
    _, plan = isolated_pdf(value, style={"fontSize": 12, "outlineColor": "#123456", "lineWidth": 2},
                           frame={"x": .1, "y": .1, "width": .5, "height": .5})
    layout = plan.layout
    inset = PADDING + 2  # border-box: the 2 pt border, then the 3 px padding
    assert layout.frame == pytest.approx((plan.frame[0] + inset, plan.frame[1] + inset,
                                          plan.frame[2] - inset, plan.frame[3] - inset))
    assert [line.height for line in layout.lines] == pytest.approx([LINE_HEIGHT * 12] * 3)
    assert layout.measured_height == pytest.approx(3 * LINE_HEIGHT * 12)
    helvetica = fitz.Font(fontname="helv")
    half_leading = (LINE_HEIGHT * 12 + (helvetica.ascender + helvetica.descender) * 12) / 2
    assert layout.lines[0].baseline == pytest.approx(layout.frame[1] + half_leading)
    # Exactly as many lines as the box holds fit; one more line overflows.
    holds = (layout.frame[3] - layout.frame[1]) // (LINE_HEIGHT * 12)
    fits = rich(*[paragraph(text(f"line {n}")) for n in range(int(holds))])
    assert not isolated_pdf(fits, style={"fontSize": 12, "outlineColor": "#123456", "lineWidth": 2},
                            frame={"x": .1, "y": .1, "width": .5, "height": .5})[1].layout.overflow
    too_many = rich(*[paragraph(text(f"line {n}")) for n in range(int(holds) + 1)])
    with pytest.raises(DocumentEditError) as caught:
        isolated_pdf(too_many, style={"fontSize": 12, "outlineColor": "#123456", "lineWidth": 2},
                     frame={"x": .1, "y": .1, "width": .5, "height": .5})
    assert caught.value.code == "layout_overflow"
    assert caught.value.details["targets"][0]["reasons"] == ["text_does_not_fit"]


def test_headings_links_and_markers_follow_browser_defaults():
    item = lambda *blocks: {"type": "listItem", "content": list(blocks)}
    bullet = lambda *items: {"type": "bulletList", "content": list(items)}
    value = rich({"type": "heading", "attrs": {"level": 1}, "content": [text("Title")]},
        paragraph(text("plain "), text("site", {"type": "link", "attrs": {"href": "https://example.test/"}}), text(" "),
                  text("red", {"type": "textStyle", "attrs": {"color": "#aa0000"}},
                       {"type": "link", "attrs": {"href": "https://example.test/red"}})),
        bullet(item(paragraph(text("disc")), bullet(item(paragraph(text("circle")), bullet(item(paragraph(text("square")))))))))
    payload, plan = isolated_pdf(value, style={"fontSize": 10}, frame={"x": .05, "y": .05, "width": .9, "height": .9})
    runs = {r.text.strip(): r for line in plan.layout.lines for r in line.runs if r.text.strip()}
    assert runs["Title"].bold and runs["Title"].font_size == pytest.approx(20) and runs["Title"].font == "hebo"
    assert runs["site"].underline and runs["site"].color == LINK_COLOR and runs["site"].href == "https://example.test/"
    # The canvas nests the color span inside the link, so the explicit color wins.
    assert runs["red"].underline and runs["red"].color == "#aa0000"
    assert not runs["plain"].underline and runs["plain"].color == "#18212a"
    # A marker glyph and its suffix space may come from two fonts, so a marker can be two runs.
    markers = [marks for marks in ([r for r in line.runs if r.marker] for line in plan.layout.lines) if marks]
    assert ["".join(r.text for r in marks) for marks in markers] == [glyph + " " for glyph in BULLETS]
    for marks, word in zip(markers, ("disc", "circle", "square")):
        # Outside markers end at the item text, and each list level indents LIST_INDENT.
        assert marks[-1].x + marks[-1].width == pytest.approx(runs[word].x)
        assert not any(r.underline or r.href for r in marks)
    assert runs["circle"].x - runs["disc"].x == pytest.approx(LIST_INDENT)
    assert runs["square"].x - runs["circle"].x == pytest.approx(LIST_INDENT)
    with fitz.open(stream=payload, filetype="pdf") as pdf:
        assert {link["uri"] for link in pdf[0].get_links()} == {"https://example.test/", "https://example.test/red"}


def test_a_final_break_adds_no_empty_line_and_spaces_hang():
    # As the canvas renders <p>a<br></p> and "a\n": one line, not two.
    for value in (rich(paragraph(text("a"), {"type": "hardBreak"})), from_plain("a\n")):
        assert len(layout_text(value, (0, 0, 300, 300), {"fontSize": 10}).lines) == 1
    two = layout_text(rich(paragraph(text("a"), {"type": "hardBreak"}, {"type": "hardBreak"})), (0, 0, 300, 300), {"fontSize": 10})
    assert len(two.lines) == 2
    # Trailing spaces never force a wrap and never count against the width.
    helvetica = fitz.Font(fontname="helv")
    word = helvetica.text_length("word", fontsize=10)
    layout = layout_text(from_plain("word" + " " * 40 + "next"), (0, 0, word + 1, 300), {"fontSize": 10})
    assert not layout.overflow
    assert ["".join(r.text for r in line.runs) for line in layout.lines] == ["word" + " " * 40, "next"]
    assert [r.hanging for r in layout.lines[0].runs] == [False, True]


def test_latin_outside_winansi_uses_the_object_font():
    payload, plan = isolated_pdf(from_plain("\u0101 \u0142 \u0151"))
    assert {r.font for line in plan.layout.lines for r in line.runs} == {"helv"}
    with fitz.open(stream=payload, filetype="pdf") as pdf:
        assert "\u0101 \u0142 \u0151" in pdf[0].get_text()


def test_embedded_fonts_are_subset_and_extractable():
    payload, _ = isolated_pdf(rich(paragraph(text("CJK \u6f22\u5b57 "), text("bold", {"type": "bold"}))))
    # The whole built-in CJK font is about 3.5 MB; a subset holds only the drawn glyphs.
    assert len(payload) < 200_000
    with fitz.open(stream=payload, filetype="pdf") as pdf:
        assert "CJK \u6f22\u5b57 bold" in pdf[0].get_text()


def test_off_page_boxes_name_the_reason():
    with pytest.raises(DocumentEditError) as caught:
        isolated_pdf("Off the page", frame={"x": .9, "y": .1, "width": .2, "height": .2})
    assert caught.value.code == "layout_overflow"
    assert caught.value.details["targets"][0]["reasons"] == ["outside_page"]


def test_line_breaks_follow_the_browser_for_ideographs_and_no_break_spaces():
    # Checked against Chromium with the canvas CSS (supervisor script, P2b-1 gate).
    em = 12.0
    rows = lambda layout: ["".join(r.text for r in line.runs) for line in layout.lines]
    # Ideographs fill the rest of a line instead of moving down as one word.
    mixed_line = layout_text(from_plain("ab " + "\u6f22" * 10), (0, 0, 6 * em, 300), {"fontSize": 12})
    assert rows(mixed_line) == ["ab " + "\u6f22" * 4, "\u6f22" * 6]
    # A closing full stop never starts a line: the ideograph before it moves down with it.
    kinsoku = layout_text(from_plain("\u6f22" * 5 + "\u3002" + "\u6f22"), (0, 0, 5 * em, 300), {"fontSize": 12})
    assert rows(kinsoku) == ["\u6f22" * 4, "\u6f22\u3002\u6f22"]
    # A no-break space binds "10 kg"; only U+0020 breaks.
    width = fitz.Font(fontname="helv").text_length("aaaa 10\u00a0k", fontsize=12)
    bound = layout_text(from_plain("aaaa 10\u00a0kg"), (0, 0, width, 300), {"fontSize": 12})
    assert rows(bound) == ["aaaa ", "10\u00a0kg"]
    # Lines measure advances: one ideograph is exactly one em wide.
    exact = layout_text(from_plain("\u6f22" * 6), (0, 0, 6 * em, 300), {"fontSize": 12})
    assert rows(exact) == ["\u6f22" * 6] and not exact.overflow


def test_text_box_paints_its_fill_over_what_lies_behind_like_the_canvas():
    # The canvas paints every text box with its fill, white by default, over a figure, a table or a page band
    # (_documentationResolvedObjectStyle + element.style.background). The PDF must hide the same things.
    payload, plan = isolated_pdf(from_plain("Over a figure"))
    with fitz.open(stream=payload, filetype="pdf") as pdf:
        page = pdf[0]
        fills = [d for d in page.get_drawings() if d["type"] == "f" and d.get("fill") is not None
                 and all(abs(a - b) < 0.01 for a, b in zip(d["rect"], plan.frame))]
        text = [span for span in page.get_texttrace() if span["type"] == 0]
    assert len(fills) == 1 and all(abs(c - 1.0) < 1e-3 for c in fills[0]["fill"])
    assert fills[0]["seqno"] < min(span["seqno"] for span in text)  # painted under the text
