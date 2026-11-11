"""P3a typography, capabilities, shared schema vectors and P2b-2 compatibility.

Runtime/real-app gates are run by the supervisor, not by the sandbox builder.
The independent geometry expectations below come from the supervisor's font
measurements, not the layout engine's line_box/decoration helpers.
"""
from copy import deepcopy
from contextlib import contextmanager
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import zipfile
from io import BytesIO

import fitz
import pytest

from ai_inspector.documentation.commands import DocumentEditError, canonical_bytes
from ai_inspector.documentation import rich_text, rich_layout, rich_docx
from tests import test_documentation_rich_exports as proof
from tests.documentation_rich_export_support import compare_docx, compare_pdf

ROOT = Path(__file__).resolve().parents[1]
P2B2 = "49cdaed"
# Independent expectations: family, ascent, descent. Do not import the production
# metric table here. Every schema uses CSS auto (size / 10). Positions follow
# Chromium as measured at the supervisor gate: line-through centred a third of the
# ascent above the baseline; an underline centred one thickness below it, which for
# every schema and plain text (CSS auto) is a tenth of the size.
METRICS = {
    "Arial": ("Helvetica", .9053, .2119),
    "Helvetica": ("Helvetica", .9053, .2119),
    "Times New Roman": ("Times", .8911, .2163),
    "Courier New": ("Courier", .8325, .3003),
}


def envelope(*blocks, version=2):
    counter = itertools.count(1)
    def identify(node):
        node = deepcopy(node)
        if node["type"] not in {"doc", "text"}:
            node.setdefault("attrs", {})["id"] = f"rt-00000000-0000-4000-8000-{next(counter):012x}"
        if "content" in node:
            node["content"] = [identify(child) for child in node["content"]]
        return node
    return {"format": "tiptap", "schemaVersion": version, "doc": identify({"type": "doc", "content": list(blocks)})}


def mark(kind, **attrs):
    return {"type": kind, **({"attrs": attrs} if attrs else {})}


def text(value, *marks):
    return {"type": "text", "text": value, **({"marks": list(marks)} if marks else {})}


def paragraph(*runs, **attrs):
    return {"type": "paragraph", "attrs": attrs, "content": list(runs)}


def nested(depth, *, mixed=False, indent=0):
    tail = None
    for level in range(depth, 0, -1):
        p = paragraph(text(f"Level {level}"), **({"indent": indent} if indent and level == depth else {}))
        kind = "orderedList" if mixed and level % 2 == 0 else "bulletList"
        tail = {"type": kind, **({"attrs": {"start": level + 1}} if kind == "orderedList" else {}),
                "content": [{"type": "listItem", "content": [p] + ([tail] if tail else [])}]}
    return tail


def first(value):
    return value["doc"]["content"][0]["content"][0]


def invalid(value, code="invalid_rich_text"):
    with pytest.raises(DocumentEditError) as caught:
        rich_text.validate(value)
    assert caught.value.code == code


@pytest.mark.parametrize("kind", ["strike", "subscript", "superscript", "highlight"])
@pytest.mark.parametrize("leaf", ["text", "hardBreak"])
def test_new_marks_and_no_attributes(kind, leaf):
    m = mark(kind, **({"color": "#AABBCC"} if kind == "highlight" else {}))
    run = text("x", m) if leaf == "text" else {"type": "hardBreak", "marks": [m]}
    value = envelope(paragraph(run))
    result = rich_text.validate(value)
    assert result["schemaVersion"] == 2
    if kind == "highlight":
        assert first(result)["marks"][0]["attrs"] == {"color": "#aabbcc"}
    first(value)["marks"][0]["attrs"] = {"unknown": 1}
    invalid(value)


@pytest.mark.parametrize("kind", ["paragraph", "heading"])
@pytest.mark.parametrize("name,low,high,step", [
    ("indent", 0, 72, .5), ("spaceBefore", 0, 36, .5), ("spaceAfter", 0, 36, .5), ("lineHeight", 1, 2, .05)])
def test_paragraph_numeric_bounds(kind, name, low, high, step):
    def make(n):
        block = paragraph(text("x"), **{name: n})
        block["type"] = kind
        if kind == "heading":
            block["attrs"]["level"] = 2
        return envelope(block)
    for n in (low, high, low + step, high - step):
        result = rich_text.validate(make(n))
        assert result["doc"]["content"][0]["attrs"][name] == pytest.approx(n)
        if n == int(n):
            assert type(result["doc"]["content"][0]["attrs"][name]) is int
    for n in (low - step, high + step, low + step / 2, True, False, None, "1", [], {}, float("nan"), float("inf")):
        invalid(make(n))


@pytest.mark.parametrize("kind", ["paragraph", "heading"])
def test_alignment_and_unknown_block_attributes(kind):
    for alignment in ("left", "center", "right", "justify", "Left", "", None, True, [], {}):
        block = paragraph(text("x"), textAlign=alignment)
        block["type"] = kind
        if kind == "heading":
            block["attrs"]["level"] = 1
        value = envelope(block)
        if alignment in ("left", "center", "right"):
            assert rich_text.validate(value)["schemaVersion"] == 2
        else:
            invalid(value)
    invalid(envelope(paragraph(text("x"), styleId="body")))
    invalid(envelope({"type": "bulletList", "attrs": {"indent": 1}, "content": [
        {"type": "listItem", "content": [paragraph(text("x"))]}]}))


def test_font_sizes_families_colors_types_and_unknown_attributes():
    for n in (6, 6.5, 9.5, 47.5, 48, 12.0):
        result = rich_text.validate(envelope(paragraph(text("x", mark("textStyle", fontSize=n)))))
        size = first(result)["marks"][0]["attrs"]["fontSize"]
        assert size == n and (type(size) is int if n == int(n) else type(size) is float)
    for n in (5.5, 48.5, 6.25, True, None, "12", [], {}, float("nan"), float("inf")):
        invalid(envelope(paragraph(text("x", mark("textStyle", fontSize=n)))))
    for family in METRICS:
        assert rich_text.validate(envelope(paragraph(text("x", mark("textStyle", fontFamily=family)))))["schemaVersion"] == 2
    for family in ("Georgia", "Inter", "Arial, serif", "arial", "", None, 12, [], {}):
        invalid(envelope(paragraph(text("x", mark("textStyle", fontFamily=family)))))
    for kind in ("highlight", "textStyle"):
        for color in ("red", "#fff", "#12345678", "#gg0000", None, 12, True, [], {}):
            invalid(envelope(paragraph(text("x", mark(kind, color=color)))))
        invalid(envelope(paragraph(text("x", mark(kind)))))
        invalid(envelope(paragraph(text("x", mark(kind, color="#112233", backgroundColor="#ffffff")))))
    result = rich_text.validate(envelope(paragraph(text("x", mark("textStyle", color="#ABCDEF", fontSize=9.5, fontFamily="Arial")))))
    assert first(result)["marks"][0]["attrs"] == {"color": "#abcdef", "fontSize": 9.5, "fontFamily": "Arial"}


def test_mark_order_minimal_version_and_schema_1_feature_refusal():
    marks = [mark("link", href="https://example.test/"), mark("textStyle", color="#AABBCC"),
             mark("highlight", color="#FEDCBA"), mark("superscript"), mark("strike"), mark("underline"), mark("italic"), mark("bold")]
    result = rich_text.validate(envelope(paragraph(text("x", *marks))))
    assert [m["type"] for m in first(result)["marks"]] == ["bold", "italic", "underline", "strike", "superscript", "highlight", "textStyle", "link"]
    invalid(envelope(paragraph(text("x", mark("subscript"), mark("superscript")))))
    invalid(envelope(paragraph(text("x", mark("strike"), mark("strike")))))
    ordinary = envelope(paragraph(text("x", mark("textStyle", color="#ABCDEF"))))
    one = deepcopy(ordinary)
    one["schemaVersion"] = 1
    assert canonical_bytes(rich_text.validate(ordinary)) == canonical_bytes(rich_text.validate(one))
    assert rich_text.field_read(ordinary)["richText"] == ordinary  # no canonical rewrite on read
    features = [envelope(paragraph(text("x", m))) for m in marks if m["type"] in {"strike", "superscript", "highlight"}]
    features += [envelope(paragraph(text("x", mark("subscript")))),
                 envelope(paragraph(text("x", mark("textStyle", fontSize=12)))),
                 envelope(paragraph(text("x", mark("textStyle", fontFamily="Arial")))), envelope(nested(4))]
    features += [envelope(paragraph(text("x"), **{k: v})) for k, v in
                 (("indent", 0), ("spaceBefore", 0), ("spaceAfter", 0), ("lineHeight", 1.2), ("textAlign", "left"))]
    for value in features:
        assert rich_text.validate(value)["schemaVersion"] == 2
        value["schemaVersion"] = 1
        invalid(value, "unsupported_rich_text_schema")
    for version in (0, 4, True, 2.0, "2", None):
        ordinary["schemaVersion"] = version
        invalid(ordinary, "unsupported_rich_text_schema")
    # Schema 3 (P3b, tables) is accepted; a document without a table is still stored as its minimal version.
    ordinary["schemaVersion"] = 3
    assert canonical_bytes(rich_text.validate(ordinary)) == canonical_bytes(rich_text.validate(one))


def test_six_list_levels_and_unchanged_resource_bounds():
    assert rich_text.validate(envelope(nested(3)))["schemaVersion"] == 1
    assert rich_text.validate(envelope(nested(6)))["schemaVersion"] == 2
    invalid(envelope(nested(7)), "rich_text_too_large")
    assert rich_text.MAX_BYTES == 24 * 1024 and rich_text.MAX_NODES == 512 and rich_text.MAX_DEPTH >= 14
    rich_text.validate(envelope(paragraph(*[text("a") for _ in range(510)])))
    invalid(envelope(paragraph(*[text("a") for _ in range(511)])), "rich_text_too_large")
    minimal = rich_text.validate(envelope(paragraph(text("x", mark("strike")))))
    overhead = len(canonical_bytes(minimal)) - 1
    first(minimal)["text"] = "x" * (rich_text.MAX_BYTES - overhead)
    rich_text.validate(minimal)
    first(minimal)["text"] += "x"
    invalid(minimal, "rich_text_too_large")


def render(value, tmp_path, style=None):
    value = rich_text.validate(value)
    document = proof.attach(proof.fixture_document("operations"), value, style=style)
    pdf, plan = proof.isolated_pdf(value, style=style)
    compare_pdf(pdf, document, proof.PAGE, proof.TARGET, tmp_path / "typography.png")
    docx = proof.build_docx("operations", document, tmp_path)
    compare_docx(docx, proof.TARGET, rich_layout.content_model(value, {"fontSize": 12, **(style or {})}))
    return pdf, plan, proof.docx_parts(docx)


@pytest.mark.parametrize("family", list(METRICS))
@pytest.mark.parametrize("bold", [False, True])
def test_pdf_run_fonts_sizes_decorations_and_highlight(tmp_path, family, bold):
    marks = [mark("strike"), mark("underline"), mark("highlight", color="#fecc80"),
             mark("textStyle", fontFamily=family, fontSize=48, color="#ab1234")]
    if bold:
        marks.append(mark("bold"))
    payload, plan, package = render(envelope(paragraph(text("Proof", *marks))), tmp_path)
    run = plan.layout.lines[0].runs[0]
    _, a, d = METRICS[family]
    assert run.font_size == 48
    assert run.baseline == pytest.approx(plan.layout.frame[1] + (1.2 + a - d) * 48 / 2)
    assert run.rect[1:] == pytest.approx((run.baseline - a * 48, run.x + run.width, run.baseline + d * 48))
    assert run.highlight_rect == pytest.approx(run.rect)
    assert run.underline_offset == pytest.approx(48 / 10)
    assert run.underline_width == pytest.approx(48 / 10)
    assert run.strike_offset == pytest.approx(-a / 3 * 48)
    assert run.strike_width == pytest.approx(48 / 10)
    table = proof.authored_tables(package["word/document.xml"])[0]
    assert proof.xp(table, './/w:r/w:rPr/w:strike/@w:val') == ["1"]
    assert proof.xp(table, './/w:r/w:rPr/w:shd/@w:fill') == ["FECC80"]


@pytest.mark.parametrize("script,shift", [("subscript", .14), ("superscript", -.45)])
def test_scripts_shift_glyphs_but_not_line_boxes(tmp_path, script, shift):
    value = envelope(paragraph(text("base "), text("script", mark(script), mark("textStyle", fontSize=24))))
    _, plan, package = render(value, tmp_path)
    line = plan.layout.lines[0]
    base, scripted = line.runs
    assert line.height == pytest.approx(1.2 * 24)
    assert scripted.font_size == pytest.approx(.65 * 24)
    assert scripted.baseline - base.baseline == pytest.approx(shift * 24)
    table = proof.authored_tables(package["word/document.xml"])[0]
    assert proof.xp(table, './/w:r/w:rPr/w:vertAlign/@w:val') == [script]
    # Word receives the nominal size and chooses its own scale and offset.
    assert proof.xp(table, './/w:r/w:rPr/w:sz/@w:val') == ["24", "48"]


def test_mixed_font_inline_union_is_hand_computed(tmp_path):
    runs = [text("a", mark("textStyle", fontFamily="Arial", fontSize=24)),
            text("b", mark("textStyle", fontFamily="Courier New", fontSize=24)),
            text("c", mark("superscript"), mark("textStyle", fontFamily="Times New Roman", fontSize=9.5))]
    _, plan, _ = render(envelope(paragraph(*runs, lineHeight=1)), tmp_path)
    # Arial supplies the highest top; Courier supplies the lowest bottom.
    above = (1 + .9053 - .2119) * 24 / 2
    below = (1 - .8325 + .3003) * 24 / 2
    line = plan.layout.lines[0]
    assert line.height == pytest.approx(above + below)
    assert line.baseline == pytest.approx(plan.layout.frame[1] + above)
    assert line.runs[2].baseline == pytest.approx(line.baseline - .45 * 9.5)
    assert plan.layout.measured_height == pytest.approx(above + below)


def test_paragraph_align_indent_spacing_line_height_and_native_lists(tmp_path):
    value = envelope(paragraph(text("center"), textAlign="center", indent=12.5, spaceBefore=3, spaceAfter=5, lineHeight=1),
                     paragraph(text("right"), textAlign="right", spaceBefore=7, spaceAfter=2, lineHeight=2),
                     nested(6, mixed=True, indent=18))
    _, plan, package = render(value, tmp_path)
    lines = plan.layout.lines
    x0, y0, x1, _ = plan.layout.frame
    assert lines[0].top == pytest.approx(y0 + 3)
    assert lines[0].runs[0].x == pytest.approx(x0 + 12.5 + (x1 - x0 - 12.5 - lines[0].width) / 2)
    assert lines[1].runs[0].x + lines[1].width == pytest.approx(x1)
    assert lines[1].top == pytest.approx(lines[0].top + 12 + 5 + 7)
    assert lines[1].height == pytest.approx(24)
    for depth, line in enumerate(lines[2:], 1):
        markers = [run for run in line.runs if run.marker]
        body = next(run for run in line.runs if not run.marker)
        assert max(run.x + run.width for run in markers) == pytest.approx(x0 + 40 * depth)
        assert body.x == pytest.approx(x0 + 40 * depth + (18 if depth == 6 else 0))
        assert "".join(run.text for run in markers) == (str(depth + 1) + ". " if depth % 2 == 0 else ("\u2022" if depth == 1 else "\u25aa") + " ")
    table = proof.authored_tables(package["word/document.xml"])[0]
    paragraphs = proof.xp(table, './w:tr/w:tc/w:p')
    assert proof.xp(paragraphs[-1], './w:pPr/w:ind/@w:left') == [str(258 * 20)]
    assert proof.xp(paragraphs[-1], './w:pPr/w:ind/@w:hanging') == [str(18 * 20 + 67)]
    # Word sends the text after the number to the level's list tab (240 pt) unless the paragraph clears it; with the
    # clear, Word 16 starts "Level 6" 18 pt right of the plain depth-6 position, as the canvas does.
    assert proof.xp(paragraphs[-1], './w:pPr/w:tabs/w:tab/@w:val') == ["clear", "num"]
    assert proof.xp(paragraphs[-1], './w:pPr/w:tabs/w:tab/@w:pos') == ["4800", "5160"]
    assert all(not proof.xp(p, './w:pPr/w:tabs') for p in paragraphs[2:-1])


def test_a_paragraph_alignment_wins_over_a_justified_box_in_docx(tmp_path):
    # On the canvas the paragraph's own text-align overrides the box's inherited justify; the DOCX must agree.
    _, plan, package = render(envelope(paragraph(text("own"), textAlign="center"), paragraph(text("box"))), tmp_path,
                              style={"textAlign": "justify"})
    paragraphs = proof.xp(proof.authored_tables(package["word/document.xml"])[0], './w:tr/w:tc/w:p')
    assert [proof.xp(p, './w:pPr/w:jc/@w:val') for p in paragraphs] == [["center"], ["both"]]
    # The PDF centres the paragraph and lays the justified box's own paragraph out flush left.
    x0, _, x1, _ = plan.layout.frame
    own, box = plan.layout.lines
    assert own.runs[0].x == pytest.approx(x0 + (x1 - x0 - own.width) / 2) and box.runs[0].x == pytest.approx(x0)


def test_highlight_fragments_links_and_small_fractional_sizes(tmp_path):
    value = envelope(paragraph(text("wrap linked highlighted words " * 4,
        mark("link", href="https://example.test/"), mark("highlight", color="#aabbcc"),
        mark("textStyle", fontFamily="Times New Roman", fontSize=24))))
    payload, plan, _ = render(value, tmp_path)
    assert len(plan.layout.lines) > 1
    with fitz.open(stream=payload, filetype="pdf") as pdf:
        fills = [d for d in pdf[0].get_drawings() if d.get("fill") and d["fill"][0] == pytest.approx(170 / 255, abs=.002)]
        assert len(fills) == sum(bool(r.highlight) for line in plan.layout.lines for r in line.runs)
    for size in (6, 9.5, 12, 24, 48):
        render(envelope(paragraph(text("size", mark("textStyle", fontSize=size)))), tmp_path)


def test_refusal_order_glyph_then_height_then_rotation():
    document = proof.attach(proof.fixture_document("operations"),
        rich_text.validate(envelope(paragraph(text("\U0001f642", mark("textStyle", fontFamily="Courier New"))))),
        frame={"x": .1, "y": .1, "width": .1, "height": .001, "rotation": 10})
    for expected, value in (("unsupported_export_glyph", None), ("layout_overflow", "a")):
        if value:
            document["pages"][0]["documentationComposition"]["documentObjects"][proof.TARGET]["content"] = rich_text.from_plain(value)
        with pytest.raises(DocumentEditError) as caught:
            rich_layout.prepare_pdf_objects(fitz, document, (600, 700))
        assert caught.value.code == expected


def test_python_and_js_font_table_stay_identical():
    # Static mirror assertion; no Node process or browser required by this test.
    source = (ROOT / "static/documentation_rich_text_core.js").read_text("utf-8")
    for metrics in rich_layout.canvas_font("Arial"), rich_layout.canvas_font("Times New Roman"), rich_layout.canvas_font("Courier New"):
        for field in ("ascent", "descent", "script_size", "sub_offset", "sup_offset"):
            value = str(getattr(metrics, field)).replace("0.", ".")
            # JS may retain a terminal zero to document the measured precision.
            assert field + ": " + value in source


_LEGACY_SOURCES = {}


@contextmanager
def p2b2_modules(monkeypatch, image_path=None):
    """Load the actual old drawing/writing code AND its callers, without checkout.

    Wiring-only oracles are insufficient: caller-local imports must see the old
    modules in sys.modules while the old exporter runs. Counters prove that path.
    """
    modules, calls = {}, {"pdf": 0, "docx": 0}
    with monkeypatch.context() as patch:
        for current in (rich_layout, rich_docx, proof.parts, proof.spec, proof.ops, proof.wi):
            relative = Path(current.__file__).resolve().relative_to(ROOT).as_posix()
            if relative not in _LEGACY_SOURCES:
                flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                _LEGACY_SOURCES[relative] = subprocess.run(["git", "show", f"{P2B2}:{relative}"], cwd=ROOT,
                    capture_output=True, check=True, creationflags=flags).stdout
            alias = current.__package__ + "._p3a_oracle_" + current.__name__.rsplit(".", 1)[-1]
            module = types.ModuleType(alias)
            module.__package__, module.__file__ = current.__package__, current.__file__
            patch.setitem(sys.modules, alias, module)
            exec(compile(_LEGACY_SOURCES[relative], relative, "exec"), module.__dict__)
            patch.setitem(sys.modules, current.__name__, module)
            package = sys.modules[current.__package__]
            patch.setattr(package, current.__name__.rsplit(".", 1)[-1], module)
            modules[current.__name__] = module
        layout = modules[rich_layout.__name__]
        docx = modules[rich_docx.__name__]
        draw, write = layout.draw_pdf_object, docx.DocxObjects._write
        def counted_draw(*args, **kwargs):
            calls["pdf"] += 1
            return draw(*args, **kwargs)
        def counted_write(*args, **kwargs):
            calls["docx"] += 1
            return write(*args, **kwargs)
        patch.setattr(layout, "draw_pdf_object", counted_draw)
        patch.setattr(docx.DocxObjects, "_write", counted_write)
        spec = modules[proof.spec.__name__]
        if image_path:
            spec.draft_render_path = lambda *args: image_path
        yield (modules[proof.parts.__name__], spec, modules[proof.ops.__name__]), layout, calls


def _xml_bytes(payload):
    with zipfile.ZipFile(BytesIO(payload)) as package:
        return {name: package.read(name) for name in package.namelist() if name.endswith((".xml", ".rels"))}


def assert_pdf_schema1_delta(current, previous, new_plans, old_plans):
    """Only the analytically derived y positions/decorations may differ."""
    with fitz.open(stream=current, filetype="pdf") as new, fitz.open(stream=previous, filetype="pdf") as old:
        assert len(new) == len(old)
        for new_page, old_page, page_id in zip(new, old, new_plans):
            assert new_page.rect == old_page.rect
            assert new_page.get_fonts() == old_page.get_fonts()
            pairs = []
            for target, new_plan in new_plans[page_id].items():
                old_plan = old_plans[page_id][target]
                assert len(new_plan.layout.lines) == len(old_plan.layout.lines)
                assert new_plan.layout.measured_height == pytest.approx(old_plan.layout.measured_height, abs=1e-8)
                for nl, ol in zip(new_plan.layout.lines, old_plan.layout.lines):
                    paragraph = new_plan.layout.content.paragraphs[nl.paragraph]
                    family = rich_docx.font_family(paragraph.font_family)
                    _, ascent, descent, *_ = METRICS[family]
                    bold = new_plan.layout.content.base_run.bold or paragraph.heading_level > 0
                    key = proof.parts._pdf_font(paragraph.font_family, 700 if bold else 400,
                                               "italic" if new_plan.layout.content.base_run.italic else "normal")
                    metrics = old_plan.layout.fonts.get(key)
                    delta = ((ascent - descent) - (metrics.ascender + metrics.descender)) * paragraph.font_size / 2
                    assert nl.baseline - ol.baseline == pytest.approx(delta, abs=1e-8)
                    assert len(nl.runs) == len(ol.runs)
                    for nr, run in zip(nl.runs, ol.runs):
                        assert (nr.text, nr.font, nr.font_size, nr.color, nr.x, nr.width, nr.bold, nr.italic,
                                nr.underline, nr.href, nr.marker, nr.hanging) == (
                                run.text, run.font, run.font_size, run.color, run.x, run.width, run.bold, run.italic,
                                run.underline, run.href, run.marker, run.hanging)
                        assert nr.baseline - run.baseline == pytest.approx(delta, abs=1e-8)
                        pairs.append((nr, run, delta))
            before, after = old_page.get_texttrace(), new_page.get_texttrace()
            assert len(before) == len(after)
            for os_, ns in zip(before, after):
                chars = os_["chars"]
                pair = next(((n, o, d) for n, o, d in pairs if chars and abs(chars[0][2][0] - o.x) < .01
                             and abs(chars[0][2][1] - o.baseline) < .01
                             and "".join(chr(c[0]) for c in chars) == o.text), None)
                delta = pair[2] if pair else 0
                for key in os_.keys() - {"bbox", "chars"}:
                    assert ns[key] == os_[key], key
                assert ns["bbox"] == pytest.approx(tuple(v + (delta if i % 2 else 0) for i, v in enumerate(os_["bbox"])), abs=.001)
                for old_char, new_char in zip(chars, ns["chars"]):
                    assert new_char[:2] == old_char[:2]
                    assert new_char[2] == pytest.approx((old_char[2][0], old_char[2][1] + delta), abs=.001)
                    assert new_char[3] == pytest.approx(tuple(v + (delta if i % 2 else 0) for i, v in enumerate(old_char[3])), abs=.001)
            before, after = old_page.get_drawings(), new_page.get_drawings()
            assert len(before) == len(after)
            for od, nd in zip(before, after):
                item = od["items"][0]
                pair = next(((n, o, d) for n, o, d in pairs if o.underline and not o.hanging and item[0] == "l"
                             and abs(item[1].x - o.x) < .01 and abs(item[1].y - o.baseline - o.font_size * .1) < .01), None)
                if pair is None:
                    assert nd == od  # fills, outlines, unrelated page drawings: exactly unchanged
                    continue
                nr, run, delta = pair
                # Schema-1 keeps CSS auto on the canvas: a tenth of the size thick, centred a tenth below the
                # baseline, where P2b already centred it; only the width and the baseline move.
                expected_y = item[1].y + delta
                assert nd["width"] == pytest.approx(run.font_size / 10, abs=.001)
                assert nd["items"][0][1].y == pytest.approx(expected_y, abs=.001)
                assert nd["items"][0][2].y == pytest.approx(expected_y, abs=.001)
                assert nd["items"][0][1].x == item[1].x and nd["items"][0][2].x == item[2].x
                for key in od.keys() - {"width", "rect", "items"}:
                    assert nd[key] == od[key]
            before, after = old_page.get_links(), new_page.get_links()
            assert len(before) == len(after)
            for ol, nl in zip(before, after):
                for key in ol.keys() - {"from"}:
                    assert nl[key] == ol[key]
                pair = next(((n, o, d) for n, o, d in pairs if o.href == ol.get("uri") and not o.hanging
                             and abs(o.rect[0] - ol["from"].x0) < .01 and abs(o.rect[1] - ol["from"].y0) < .01), None)
                if pair is None:
                    assert nl["from"] == ol["from"]
                    continue
                nr, run, delta = pair
                glyph_font = old_plans[page_id][next(iter(old_plans[page_id]))].layout.fonts.get(run.font)
                _, a, d, *_ = METRICS[rich_docx.font_family(nr.font_family)]
                expected = (ol["from"].x0, ol["from"].y0 + delta + (glyph_font.ascender - a) * run.font_size,
                            ol["from"].x1, ol["from"].y1 + delta + (d + glyph_font.descender) * run.font_size)
                assert tuple(nl["from"]) == pytest.approx(expected, abs=.001)


def assert_schema1_callers(document, builder, tmp_path, monkeypatch, image_path=None):
    """Full exporter oracle, including old rendering modules (not just old wiring)."""
    current_pdf = proof.build(builder, deepcopy(document), tmp_path)
    with fitz.open(stream=current_pdf, filetype="pdf") as pdf:
        size = (pdf[0].rect.width, pdf[0].rect.height)
    current_plans = rich_layout.prepare_pdf_objects(fitz, document, size, rich_only=builder == "parts")
    current_docx = proof.build_docx(builder, deepcopy(document), tmp_path) if builder not in {"parts", "fillable"} else None
    with p2b2_modules(monkeypatch, image_path) as (modules, old_layout, calls):
        previous_pdf = proof.build(builder, deepcopy(document), tmp_path, modules=modules)
        old_plans = old_layout.prepare_pdf_objects(fitz, document, size, rich_only=builder == "parts")
        previous_docx = proof.build_docx(builder, deepcopy(document), tmp_path,
            modules[1] if builder == "specification" else modules[2]) if current_docx else None
        assert calls["pdf"] > 0, "Oracle did not execute the P2b-2 drawing code"
        if current_docx:
            assert calls["docx"] > 0, "Oracle did not execute the P2b-2 DOCX writer"
    if current_docx:
        assert _xml_bytes(current_docx) == _xml_bytes(previous_docx)
    assert_pdf_schema1_delta(current_pdf, previous_pdf, current_plans, old_plans)


_CHECKED_SCHEMA1 = set()


def assert_schema1_vector(value, style, frame, tmp_path, monkeypatch):
    """Called for each distinct schema-1 value/style/frame exercised by P2b tests.

    DOCX always compares every XML part (including emoji/control refusals). PDF
    compares a real page drawn by each implementation at the requested bounds;
    invalid/overflow cases must refuse with the same code. No generated corpus.
    """
    if not isinstance(value, dict):
        return
    try:
        canonical = rich_text.validate(value)
    except DocumentEditError:
        return  # malformed inputs already have their explicit refusal tests
    if canonical["schemaVersion"] != 1:
        return
    key = canonical_bytes([value, style, frame])
    if key in _CHECKED_SCHEMA1:
        return
    document = proof.attach(proof.fixture_document("operations"), value, style=style, frame=frame)
    def get_docx(module=None):
        try:
            return _xml_bytes(proof.build_docx("operations", deepcopy(document), tmp_path, module)), None
        except DocumentEditError as error:
            return None, error.code
    def get_pdf(layout):
        try:
            plans = layout.prepare_pdf_objects(fitz, document, (600, 700))
            with fitz.open() as pdf:
                page = pdf.new_page(width=600, height=700)
                layout.draw_pdf_objects(fitz, page, document["pages"][0], plans)
                layout.finish_pdf_fonts(pdf, plans)
                return pdf.tobytes(garbage=4, deflate=True), plans, None
        except DocumentEditError as error:
            return None, None, error.code
    current_docx = get_docx()
    current_pdf, current_plans, current_error = get_pdf(rich_layout)
    with p2b2_modules(monkeypatch) as (modules, old_layout, calls):
        old_docx = get_docx(modules[2])
        previous_pdf, old_plans, old_error = get_pdf(old_layout)
        if old_docx[1] is None:
            assert calls["docx"] > 0
        if old_error is None:
            assert calls["pdf"] > 0
    assert current_docx == old_docx
    assert current_error == old_error
    if current_error is None:
        assert_pdf_schema1_delta(current_pdf, previous_pdf, current_plans, old_plans)
    _CHECKED_SCHEMA1.add(key)


def test_marked_hard_break_and_scripted_highlight_use_their_own_inline_boxes(tmp_path):
    value = envelope(paragraph(text("a"), {"type": "hardBreak", "marks": [mark("textStyle", fontSize=48)]},
        text("b", mark("superscript"), mark("highlight", color="#aabbcc"), mark("textStyle", fontSize=24))))
    _, plan, _ = render(value, tmp_path)
    assert len(plan.layout.lines) == 2
    assert plan.layout.lines[0].height == pytest.approx(48 * 1.2)
    run = plan.layout.lines[1].runs[0]
    assert run.highlight_rect[1] == pytest.approx(plan.layout.lines[1].baseline - .9053 * 24)
    assert run.rect[1] == pytest.approx(plan.layout.lines[1].baseline - .45 * 24 - .9053 * .65 * 24)


@pytest.mark.parametrize("attribute,value", [("attrs", None), ("attrs", True), ("attrs", []), ("attrs", "color")])
def test_mark_attribute_container_types(attribute, value):
    for kind in ("strike", "subscript", "superscript", "highlight", "textStyle"):
        raw = envelope(paragraph(text("x", {"type": kind, attribute: value})))
        invalid(raw)


def test_six_bullet_levels_and_box_font_fallbacks(tmp_path):
    _, plan, _ = render(envelope(nested(6)), tmp_path)
    assert ["".join(r.text for r in line.runs if r.marker) for line in plan.layout.lines] == [
        "\u2022 ", "\u25e6 ", "\u25aa ", "\u25aa ", "\u25aa ", "\u25aa "]
    for family, resolved in (("Georgia", "Times New Roman"), ("Inter", "Arial")):
        _, plan, _ = render(envelope(paragraph(text("mapped", mark("strike")))), tmp_path, {"fontFamily": family})
        _, a, d, *_ = METRICS[resolved]
        assert plan.layout.lines[0].baseline - plan.layout.frame[1] == pytest.approx((1.2 + a - d) * 12 / 2)


def test_schema2_scene_read_is_lossless_and_write_uses_minimal_version(tmp_path, monkeypatch):
    from tests.test_documentation_rich_text import RichScene
    monkeypatch.setenv(rich_text.FEATURE_FLAG, "on")
    scene = RichScene(tmp_path)
    value = rich_text.validate(envelope(paragraph(text("kept", mark("textStyle", fontSize=9.5),
                                                        mark("highlight", color="#aabbcc")), spaceBefore=2.5)))
    scene.batch(value, request_id="typography-two")
    before = scene.path.read_bytes()
    assert scene.value() == value
    assert scene.field()["richText"] == value
    assert scene.path.read_bytes() == before
    ordinary = rich_text.from_plain("ordinary")
    ordinary["schemaVersion"] = 2
    scene.batch(ordinary, request_id="typography-one")
    assert scene.value()["schemaVersion"] == 1
    assert scene.value() == rich_text.validate(ordinary)


_VECTORS = json.loads((ROOT / "tests/fixtures/rich_text_v2_vectors.json").read_text("utf-8"))


@pytest.mark.parametrize("vector", _VECTORS, ids=lambda vector: vector["name"])
def test_shared_schema_vectors(vector):
    if "code" in vector:
        invalid(vector["input"], vector["code"])
    else:
        assert canonical_bytes(rich_text.validate(vector["input"])) == canonical_bytes(vector["expected"])


def test_feature_and_named_style_tables_match_javascript():
    from ai_inspector.documentation.rich_fonts import NAMED_STYLES
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    script = "const c=require('./static/documentation_rich_text_core.js');process.stdout.write(JSON.stringify({features:c.FEATURES,styles:c.NAMED_STYLES}));"
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, check=True, creationflags=flags)
    mirror = json.loads(result.stdout)
    assert mirror == {"features": list(rich_text.FEATURES), "styles": NAMED_STYLES}


@pytest.mark.parametrize("name,scale,bold,italic,color", [
    ("title", 2.25, True, False, "#18212a"),
    ("caption", .85, False, True, "#5b6670"),
    ("note", .9, False, False, "#5b6670"),
])
def test_named_style_pdf_strut_and_docx_direct_formatting(tmp_path, name, scale, bold, italic, color):
    value = envelope(paragraph(text("Styled "), text("override", mark("bold"), mark("italic"),
        mark("textStyle", fontSize=6, color="#112233")), namedStyle=name, spaceBefore=3, spaceAfter=4, lineHeight=1.5))
    _, plan, package = render(value, tmp_path)
    p = plan.layout.content.paragraphs[0]
    assert p.named_style == name and p.font_size == pytest.approx(12 * scale)
    line = plan.layout.lines[0]
    assert line.height == pytest.approx(1.5 * 12 * scale)
    assert line.baseline == pytest.approx(plan.layout.frame[1] + 3 + (1.5 + .9053 - .2119) * 12 * scale / 2)
    first_run, override = line.runs
    assert first_run.font_size == pytest.approx(12 * scale)
    assert (first_run.bold, first_run.italic, first_run.color) == (bold, italic, color)
    assert (override.font_size, override.bold, override.italic, override.color) == (6, True, True, "#112233")
    assert plan.layout.measured_height == pytest.approx(3 + 1.5 * 12 * scale + 4)
    table = proof.authored_tables(package["word/document.xml"])[0]
    assert proof.xp(table, './/w:pPr/w:pStyle/@w:val') == [name.title()]
    assert proof.xp(table, './/w:pPr/w:rPr/w:sz/@w:val') == [str(round(24 * scale))]
    assert proof.xp(table, './/w:pPr/w:rPr/w:color/@w:val') == [color[1:].upper()]
    # The template's Title style carries a bottom border, contextual spacing, letter spacing and kerning; the
    # paragraph turns them off directly so Word shows the canvas look (supervisor P3a-2).
    paragraph_props = proof.xp(table, './/w:p/w:pPr')[0]
    assert proof.xp(paragraph_props, './w:pBdr/*/@w:val') == ["nil"] * 6
    assert proof.xp(paragraph_props, './w:contextualSpacing/@w:val') == ["0"]
    order = [child.tag.rsplit("}", 1)[1] for child in paragraph_props]
    assert order == sorted(order, key=["pStyle", "keepNext", "keepLines", "widowControl", "pBdr", "spacing",
                                       "contextualSpacing", "jc", "rPr"].index)
    for props in proof.xp(table, './/w:rPr'):
        assert proof.xp(props, './w:spacing/@w:val') == ["0"] and proof.xp(props, './w:kern/@w:val') == ["0"]
    styles = package["word/styles.xml"]
    assert proof.xp(styles, './w:style[@w:styleId="' + name.title() + '"]')
    if name == "note":
        assert proof.xp(styles, './w:style[@w:styleId="Note"]/w:basedOn/@w:val') == ["Normal"]


def test_adding_strike_does_not_change_existing_underlines():
    value = envelope(paragraph(text("underlined", mark("underline"))), version=1)
    old = rich_layout.layout_text(value, (0, 0, 500, 300), {"fontSize": 48})
    value["schemaVersion"] = 2
    value["doc"]["content"].append(envelope(paragraph(text("strike", mark("strike"))))["doc"]["content"][0])
    value["doc"]["content"][-1]["attrs"]["id"] = "rt-00000000-0000-4000-8000-000000000999"
    new = rich_layout.layout_text(value, (0, 0, 500, 300), {"fontSize": 48})
    assert old.lines[0] == new.lines[0]
    assert old.lines[0].runs[0].underline_width == pytest.approx(4.8)
    assert old.lines[0].runs[0].underline_offset == pytest.approx(4.8)


def test_rich_capability_read_shape_and_feature_inventory(tmp_path, monkeypatch):
    from tests.test_documentation_rich_text import RichScene
    monkeypatch.setenv(rich_text.FEATURE_FLAG, "on")
    scene = RichScene(tmp_path)
    field = scene.field()
    assert field["richTextEligible"]
    assert field["richTextCapabilities"] == {"schemaVersions": [1, 2, 3], "features": list(rich_text.FEATURES), "listDepth": 6}
    value = rich_text.validate(envelope(paragraph(text("title", mark("textStyle", fontSize=12, color="#112233")), namedStyle="title"), nested(6)))
    assert rich_text.used_features(value) == {"features": ["bulletList", "color", "fontSize", "namedStyle"], "listDepth": 6}
    scene.batch(value)
    before = scene.path.read_bytes()
    assert scene.field()["richText"] == value
    assert scene.path.read_bytes() == before


@pytest.mark.parametrize("narrow", ["features", "schemaVersions", "listDepth"])
@pytest.mark.parametrize("write", ["edit", "batch"])
def test_target_capabilities_are_enforced_on_both_write_paths(tmp_path, monkeypatch, narrow, write):
    from ai_inspector.documentation import targets
    from tests.test_documentation_rich_text import RichScene, PAGE, OBJECT
    monkeypatch.setenv(rich_text.FEATURE_FLAG, "on")
    scene = RichScene(tmp_path)
    caps = {"schemaVersions": [1, 2], "features": list(rich_text.FEATURES), "listDepth": 6}
    value = rich_text.validate(envelope(nested(4))) if narrow == "listDepth" else rich_text.validate(envelope(paragraph(text("x", mark("strike")))))
    caps[narrow] = [] if narrow == "features" else [1] if narrow == "schemaVersions" else 3
    monkeypatch.setattr(targets, "rich_text_capabilities", lambda target: deepcopy(caps))
    before = scene.path.read_bytes()
    with pytest.raises(DocumentEditError) as caught:
        getattr(scene, write)(value)
    assert caught.value.code == "unsupported_rich_text_feature"
    assert caught.value.details["targets"] == [{"pageId": PAGE, "targetId": OBJECT}]
    assert caught.value.details["features"] == (["bulletList"] if narrow == "listDepth" else ["strike"])
    assert scene.path.read_bytes() == before
