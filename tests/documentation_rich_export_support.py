"""Read real proof artifacts and compare them with the canonical content model.

Used by the isolated P2b smoke; no app import, stores, credentials or browser mocks.
"""
from io import BytesIO
import zipfile

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def _xp(node, expression):
    return node.xpath(expression, namespaces=NS)


def _value(node, expression):
    values = _xp(node, expression)
    return values[0] if values else None


def compare_docx(payload, target, model):
    from ai_inspector.documentation.rich_docx import font_family, marker_gap
    from docx import Document
    from lxml import etree
    Document(BytesIO(payload))
    with zipfile.ZipFile(BytesIO(payload)) as package:
        document = etree.fromstring(package.read("word/document.xml"))
        numbering = etree.fromstring(package.read("word/numbering.xml"))
        relationships = {node.get("Id"): node for node in etree.fromstring(package.read("word/_rels/document.xml.rels"))}
    table = next(t for t in _xp(document, '//w:tbl')
                 if _value(t, './w:tblPr/w:tblCaption/@w:val') == "Authored text: " + target)
    paragraphs = _xp(table, './w:tr/w:tc/w:p')
    assert len(paragraphs) == len(model.paragraphs)
    actual, expected, list_records, ids = [], [], [], {}
    for index, (xml, p) in enumerate(zip(paragraphs, model.paragraphs)):
        family = p.font_family.casefold()
        family = "Courier New" if "courier" in family else "Times New Roman" if "times" in family or "georgia" in family else "Arial"
        assert _value(xml, './w:pPr/w:rPr/w:rFonts/@w:ascii') == family
        assert _value(xml, './w:pPr/w:rPr/w:sz/@w:val') == str(round(p.font_size * 2))
        assert _value(xml, './w:pPr/w:spacing/@w:lineRule') == "atLeast"
        assert _value(xml, './w:pPr/w:spacing/@w:line') == str(round(20 * p.line_height * p.font_size))
        assert _value(xml, './w:pPr/w:pStyle/@w:val') == (p.named_style.title() if p.named_style else "Heading" + str(p.heading_level) if p.heading_level else None)
        assert _value(xml, './w:pPr/w:spacing/@w:before') == str(round(20 * p.space_before))
        assert _value(xml, './w:pPr/w:spacing/@w:after') == str(round(20 * p.space_after))
        assert _value(xml, './w:pPr/w:jc/@w:val') == ("both" if p.align == "justify" else p.align)
        if p.indent and not p.list_path:
            assert _value(xml, './w:pPr/w:ind/@w:left') == str(round(20 * p.indent))
        base = p.base_run or model.base_run
        assert _value(xml, './w:pPr/w:rPr/w:color/@w:val').lower() == base.color.lstrip("#").lower()
        assert (_value(xml, './w:pPr/w:rPr/w:b/@w:val') == "1") == base.bold
        assert (_value(xml, './w:pPr/w:rPr/w:i/@w:val') == "1") == base.italic
        expected_chars = []
        for run in p.runs:
            text = "\n" if run.kind == "break" else run.text.replace("\r", " ")
            expected_chars.extend({"text": char, "bold": bool(run.bold), "italic": bool(run.italic),
                                   "underline": bool(run.underline), "color": run.color.lower(), "href": run.href,
                                   "font": font_family(run.font_family or p.font_family),
                                   "size": round((run.font_size if run.font_size is not None else p.font_size) * 2),
                                   "strike": run.strike, "highlight": run.highlight, "script": run.script} for char in text)
        if expected_chars and expected_chars[-1]["text"] == "\n":
            expected_chars.pop()
        actual_chars = []
        for run in _xp(xml, './w:r | ./w:hyperlink/w:r'):
            parent = run.getparent()
            href = None
            if parent.tag.endswith("}hyperlink"):
                relation = relationships[parent.get("{" + NS["r"] + "}id")]
                assert relation.get("TargetMode") == "External" and relation.get("Type").endswith("/hyperlink")
                href = relation.get("Target")
            attrs = {"bold": _value(run, './w:rPr/w:b/@w:val') == "1",
                     "italic": _value(run, './w:rPr/w:i/@w:val') == "1",
                     "underline": _value(run, './w:rPr/w:u/@w:val') == "single",
                     "color": "#" + _value(run, './w:rPr/w:color/@w:val').lower(), "href": href,
                     "font": _value(run, './w:rPr/w:rFonts/@w:ascii'),
                     "size": int(_value(run, './w:rPr/w:sz/@w:val')),
                     "strike": _value(run, './w:rPr/w:strike/@w:val') == "1",
                     "highlight": ("#" + _value(run, './w:rPr/w:shd/@w:fill').lower()) if _value(run, './w:rPr/w:shd/@w:fill') else None,
                     "script": _value(run, './w:rPr/w:vertAlign/@w:val')}
            assert _value(run, './w:rPr/w:szCs/@w:val') == str(attrs["size"])
            assert all(_value(run, './w:rPr/w:rFonts/@w:' + k) == attrs["font"] for k in ("ascii", "hAnsi", "cs"))
            assert not _xp(run, './w:rPr/w:highlight')
            if attrs["highlight"]:
                assert _value(run, './w:rPr/w:shd/@w:val') == "clear"
                assert _value(run, './w:rPr/w:shd/@w:color') == "auto"
            for leaf in _xp(run, './w:t | ./w:br | ./w:tab'):
                text = "\n" if leaf.tag.endswith("}br") else "\t" if leaf.tag.endswith("}tab") else leaf.text or ""
                actual_chars.extend({"text": char, **attrs} for char in text)
        assert actual_chars == expected_chars, {"paragraph": index, "actual": actual_chars, "expected": expected_chars}
        actual.append(actual_chars)
        expected.append(expected_chars)
        num_id = _value(xml, './w:pPr/w:numPr/w:numId/@w:val')
        if p.list_path:
            depth = len(p.list_path)
            assert _value(xml, './w:pPr/w:ind/@w:left') == str(round((depth * 40 + p.indent) * 20))
            assert _value(xml, './w:pPr/w:ind/@w:hanging') == (str(round(p.indent * 20) + marker_gap(p)) if p.marker is not None else "0")
            if p.marker is not None:
                level = p.list_path[-1]
                assert num_id and _value(xml, './w:pPr/w:numPr/w:ilvl/@w:val') == str(depth - 1)
                if level.list_id in ids:
                    assert ids[level.list_id] == num_id
                else:
                    assert num_id not in ids.values()
                    ids[level.list_id] = num_id
                number = _xp(numbering, './w:num[@w:numId="' + num_id + '"]')[0]
                abstract = _value(number, './w:abstractNumId/@w:val')
                definition = _xp(numbering, './w:abstractNum[@w:abstractNumId="' + abstract + '"]/w:lvl')[0]
                fmt = _value(definition, './w:numFmt/@w:val')
                assert fmt == ("bullet" if level.kind == "bulletList" else "decimal")
                marker = ("\uf0b7", "o", "\uf0a7")[min(depth - 1, 2)] if level.kind == "bulletList" else f"%{depth}."
                assert _value(definition, './w:lvlText/@w:val') == marker
                assert _value(definition, './w:lvlJc/@w:val') == "right"
                assert _value(number, './w:lvlOverride/w:startOverride/@w:val') == str(level.start)
                list_records.append({"paragraph": index, "depth": depth, "start": level.start, "kind": level.kind})
            else:
                assert num_id is None
        else:
            assert num_id is None
    kinds = [child.tag.rsplit("}", 1)[-1] for child in numbering]
    assert max(i for i, kind in enumerate(kinds) if kind == "abstractNum") < min(i for i, kind in enumerate(kinds) if kind == "num")
    return {"text": "\n".join("".join(c["text"] for c in p) for p in actual), "paragraphs": actual, "lists": list_records}


def compare_pdf(payload, document, page_id, target, output_path):
    import fitz
    from ai_inspector.documentation.rich_layout import prepare_pdf_objects
    with fitz.open(stream=payload, filetype="pdf") as pdf:
        page_index = next(i for i, page in enumerate(document["pages"]) if page["pageId"] == page_id)
        page = pdf[page_index]
        plan = prepare_pdf_objects(fitz, document, (page.rect.width, page.rect.height))[page_id][target]
        traces = page.get_texttrace()
        fills = [span for span in traces if span["type"] == 0]
        drawings = page.get_drawings()
        links = page.get_links()
        rows = []
        for line in plan.layout.lines:
            found = []
            for run in line.runs:
                def matches(span):
                    chars = span["chars"]
                    return bool(chars) and abs(chars[0][2][0] - run.x) < .15 and abs(chars[0][2][1] - run.baseline) < .15 \
                        and "".join(chr(c[0]) for c in chars) == run.text
                span = next((s for s in fills if matches(s)), None)
                assert span is not None, {"missingRun": run.text, "origin": [run.x, run.baseline]}
                fills.remove(span)
                expected_color = tuple(int(run.color[i:i+2], 16) / 255 for i in (1, 3, 5))
                assert all(abs(a - b) < .002 for a, b in zip(span["color"], expected_color))
                assert abs(span["size"] - run.font_size) < .1
                font_name = span["font"].lower().replace(" ", "")
                assert any(name in font_name for name in ("nimbus", "helvetica", "times", "courier", "droidsansfallback")), font_name
                if run.font != "cjk":
                    assert bool(span["flags"] & 16) == run.bold and bool(span["flags"] & 2) == run.italic
                family_names = {"Arial": ("helvetica", "nimbussans"), "Helvetica": ("helvetica", "nimbussans"),
                                "Times New Roman": ("times", "nimbusroman"), "Courier New": ("courier", "nimbusmono")}
                from ai_inspector.documentation.rich_fonts import font
                if run.font != "cjk":
                    assert any(name in font_name for name in family_names[font(run.font_family).canvas]), font_name
                for enabled, offset, thickness in ((run.underline, run.underline_offset, run.underline_width),
                                                  (run.strike, run.strike_offset, run.strike_width)):
                    if enabled and not run.hanging:
                        assert any(item[0] == "l" and abs(item[1].x - run.x) < .1
                                   and abs(item[1].y - run.baseline - offset) < .1
                                   and abs(item[2].x - run.x - run.width) < .1
                                   and abs(drawing["width"] - thickness) < .01
                                   and all(abs(a - b) < .002 for a, b in zip(drawing["color"], expected_color))
                                   for drawing in drawings for item in drawing["items"])
                if run.highlight:
                    highlight_color = tuple(int(run.highlight[i:i+2], 16) / 255 for i in (1, 3, 5))
                    assert any(drawing.get("fill") is not None and drawing["seqno"] < span["seqno"]
                               and all(abs(a - b) < .1 for a, b in zip(drawing["rect"], run.highlight_rect))
                               and all(abs(a - b) < .002 for a, b in zip(drawing["fill"], highlight_color))
                               for drawing in drawings)
                if run.href and not run.hanging:
                    assert any(link.get("uri") == run.href and all(abs(a - b) < .1 for a, b in zip(link["from"], run.rect)) for link in links)
                found.append({"text": run.text, "font": span["font"], "size": span["size"], "bold": run.bold,
                              "italic": run.italic, "underline": run.underline, "color": run.color, "href": run.href,
                              "marker": run.marker, "hanging": run.hanging, "family": run.font_family,
                              "strike": run.strike, "highlight": run.highlight, "script": run.script,
                              "baseline": run.baseline, "rect": list(run.rect)})
            rows.append(found)
        page.get_pixmap(matrix=fitz.Matrix(2, 2)).save(str(output_path))
        page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=fitz.Rect(plan.frame)).save(str(output_path.with_name(output_path.stem + "-region.png")))
        return {"lines": rows, "text": "\n".join("".join(run["text"] for run in line if not run["marker"]) for line in rows),
                "links": [{"uri": link.get("uri"), "rect": list(link["from"])} for link in links if link.get("uri")]}


def export_characters(snapshot, format, fields=("bold", "italic", "underline", "color", "href", "size")):
    """Semantic changes only; downstream positions may move when an advance changes."""
    if format == "docx":
        return [char for paragraph in snapshot["paragraphs"] for char in paragraph]
    return [{"text": char, **{key: run[key] for key in fields}}
            for line in snapshot["lines"] for run in line if not run["marker"] for char in run["text"]]
