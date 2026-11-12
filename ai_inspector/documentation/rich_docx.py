"""Flowing native DOCX text objects. No PDF positions, font engine or text boxes."""
from dataclasses import dataclass
import math

from .commands import DocumentEditError
from .rich_fonts import font
from .rich_layout import authored_objects, content_model, PADDING, LIST_INDENT

DOCX_RENDERER_VERSION = "rich-text-docx-6"


def font_family(value):
    return font(value).docx


# Like the canvas's outside markers ("3. " ends where the item text starts), a marker is right-aligned one space
# before the text, so a wide number ("10." at 16 pt) never pushes the text to Word's next tab stop.
_SPACE_EM = {"Arial": 0.278, "Times New Roman": 0.25, "Courier New": 0.6}


def marker_gap(paragraph):
    return round(_SPACE_EM[font_family(paragraph.font_family)] * paragraph.font_size * 20)


# w:pPr child order (ECMA-376 CT_PPr); python-docx does not export its own copy.
_PPR_ORDER = ("w:pStyle", "w:keepNext", "w:keepLines", "w:pageBreakBefore", "w:framePr", "w:widowControl", "w:numPr",
              "w:suppressLineNumbers", "w:pBdr", "w:shd", "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap",
              "w:overflowPunct", "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi", "w:adjustRightInd",
              "w:snapToGrid", "w:spacing", "w:ind", "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc",
              "w:textDirection", "w:textAlignment", "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle",
              "w:rPr", "w:sectPr", "w:pPrChange")


def _element(name, **attributes):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    item = OxmlElement(name)
    for key, value in attributes.items():
        item.set(qn("w:" + key), str(value))
    return item


def _properties(run, paragraph):
    """Direct formatting also applies to the paragraph mark, including empty p."""
    props = _element("w:rPr")
    family = font_family(run.font_family or paragraph.font_family)
    props.append(_element("w:rFonts", ascii=family, hAnsi=family, cs=family))
    for name, enabled in (("b", run.bold), ("bCs", run.bold), ("i", run.italic), ("iCs", run.italic)):
        props.append(_element("w:" + name, val=int(enabled)))
    if run.strike:
        props.append(_element("w:strike", val="1"))
    props.append(_element("w:color", val=run.color.lstrip("#").upper()))
    if paragraph.named_style:
        # Word's built-in Title style spaces its letters out (0.25 pt) and kerns them; the canvas does neither.
        # Zero turns both off (supervisor P3a-2).
        props.append(_element("w:spacing", val=0))
        props.append(_element("w:kern", val=0))
    size = round(2 * (run.font_size if run.font_size is not None else paragraph.font_size))
    props.append(_element("w:sz", val=size))
    props.append(_element("w:szCs", val=size))
    props.append(_element("w:u", val="single" if run.underline else "none"))
    if run.highlight:
        props.append(_element("w:shd", val="clear", color="auto", fill=run.highlight.lstrip("#").upper()))
    if run.kind == "gap":
        # Fit the native spacer run to exactly three points; ordinary character spacing rounds its added advance.
        props.append(_element("w:fitText", val=round(run.gap * 20)))
    if run.script:
        # Word chooses its own script scale/offset; retain the authored nominal size.
        props.append(_element("w:vertAlign", val=run.script))
    return props


def tokens(paragraph):
    """Raw text with only the documented canvas control-character mapping."""
    result = []
    for run in paragraph.runs:
        if run.kind == "break":
            result.append((run, "br", ""))
            continue
        pending = []
        for char in run.text:
            if char in {"\n", "\t"}:
                if pending:
                    result.append((run, "t", "".join(pending)))
                    pending = []
                result.append((run, "br" if char == "\n" else "tab", ""))
            else:
                pending.append(" " if char == "\r" else char)
        if pending:
            result.append((run, "t", "".join(pending)))
    if result and result[-1][1] == "br":
        result.pop()  # A final break does not create another canvas line.
    return result


class _Numbering:
    def __init__(self, output):
        self.output, self.instances = output, {}

    def number(self, namespace, level, depth, gap):
        from docx.oxml.ns import qn
        key = (namespace, level.list_id)
        if key in self.instances:
            return self.instances[key]
        root = self.output.part.numbering_part.element
        abstract_id = max((int(n.get(qn("w:abstractNumId"))) for n in root.findall(qn("w:abstractNum"))), default=-1) + 1
        num_id = max((int(n.get(qn("w:numId"))) for n in root.findall(qn("w:num"))), default=0) + 1
        abstract = _element("w:abstractNum", abstractNumId=abstract_id)
        abstract.append(_element("w:multiLevelType", val="multilevel"))
        # Each list instance owns its counter; ancestor counters never leak into
        # a nested decimal marker. Define just its own depth, using %N, not %1.%2.
        ilvl = depth - 1
        definition = _element("w:lvl", ilvl=ilvl)
        definition.append(_element("w:start", val=level.start))
        bullet = level.kind == "bulletList"
        definition.append(_element("w:numFmt", val="bullet" if bullet else "decimal"))
        definition.append(_element("w:suff", val="tab"))
        symbols = (("Symbol", "\uf0b7"), ("Courier New", "o"), ("Wingdings", "\uf0a7"))
        family, marker = symbols[min(ilvl, 2)] if bullet else ("Arial", f"%{depth}.")
        definition.append(_element("w:lvlText", val=marker))
        definition.append(_element("w:lvlJc", val="right"))
        props = _element("w:pPr")
        tabs = _element("w:tabs")
        tabs.append(_element("w:tab", val="num", pos=round(LIST_INDENT * depth * 20)))
        props.append(tabs)
        props.append(_element("w:ind", left=round(LIST_INDENT * depth * 20), hanging=gap))
        definition.append(props)
        rpr = _element("w:rPr")
        rpr.append(_element("w:rFonts", ascii=family, hAnsi=family, cs=family))
        definition.append(rpr)
        abstract.append(definition)
        # Word requires all abstractNum elements before every num element.
        first_num = root.find(qn("w:num"))
        if first_num is None:
            root.append(abstract)
        else:
            first_num.addprevious(abstract)
        number = _element("w:num", numId=num_id)
        number.append(_element("w:abstractNumId", val=abstract_id))
        override = _element("w:lvlOverride", ilvl=ilvl)
        override.append(_element("w:startOverride", val=level.start))
        number.append(override)
        # numIdMacAtCleanup, if present, is the final numbering child.
        cleanup = root.find(qn("w:numIdMacAtCleanup"))
        if cleanup is None:
            root.append(number)
        else:
            cleanup.addprevious(number)
        self.instances[key] = num_id
        return num_id


@dataclass(frozen=True)
class ObjectContent:
    target: dict
    frame: tuple
    style: dict
    outline: bool
    content: object
    value: dict | None = None


def prepare_objects(document, page_size):
    from ai_inspector.parts_manual.pdf import _document_object_style, _document_theme
    result, rotated = {}, []
    theme = _document_theme(document)
    width, height = page_size
    for page in document.get("pages", []):
        objects = result.setdefault(page["pageId"], [])
        from .objects import ordered_objects, image_angle
        text = {key: stored for key, value, stored in authored_objects(page)}
        for key, value in ordered_objects(page):
            stored = text.get(key)
            target = {"pageId": page["pageId"], "targetId": key}
            frame = value.get("frame") or {}
            x, y, w, h, rotation = (float(frame.get(name) or 0) for name in ("x", "y", "width", "height", "rotation"))
            if not all(math.isfinite(n) for n in (x, y, w, h, rotation)) or w <= 0 or h <= 0:
                raise DocumentEditError("invalid_export_layout", "Text object frame must be finite and have positive dimensions.", targets=[target])
            if value.get("type") != "text":
                image_angle(value, frame, export=True)
                objects.append(ObjectContent(target, (x * width, y * height, w * width, h * height),
                               _document_object_style(theme, value), False, None, value))
                continue
            if abs(rotation) > 1e-9:
                rotated.append(target)
                continue
            style = _document_object_style(theme, value)
            try:
                model = content_model(stored, style)
            except DocumentEditError as error:
                raise DocumentEditError(error.code, str(error), **{**error.details, "targets": [target]}) from error
            # Word has font fallback, but XML 1.0 cannot represent these controls.
            invalid = sorted({ord(c) for p in model.paragraphs for r in p.runs for c in r.text
                              if ord(c) < 32 and c not in "\t\n\r" or ord(c) in {0xfffe, 0xffff}})
            if invalid:
                raise DocumentEditError("unsupported_export_character", "DOCX XML cannot represent these control characters.",
                                        targets=[target], codePoints=[f"U+{c:04X}" for c in invalid])
            objects.append(ObjectContent(target, (x * width, y * height, w * width, h * height), style,
                           "outlineColor" in (value.get("styleOverrides") or {}), model))
        objects.sort(key=lambda item: (item.frame[1], item.frame[0], item.target["targetId"]))
    if rotated:
        raise DocumentEditError("unsupported_export_rotation", "Rotated authored text is not supported by the DOCX layout.", targets=rotated)
    return result


def artifact_metadata(document, page_size, horizontal_margins):
    """Only object-bearing DOCX artifacts get the new cache key and width report."""
    plans = prepare_objects(document, page_size)
    objects = [item for values in plans.values() for item in values]
    if not objects:
        return {}
    # Word stores page size and each margin in whole twips. Match the actual
    # section width, including the half-twip rounding at the cap boundary.
    available = (round(page_size[0] * 20) - 2 * round(horizontal_margins * 10)) / 20
    metadata = {"rendererVersion": DOCX_RENDERER_VERSION, "authoredText": {"placement": "flowing_single_cell_tables",
        "widthCaps": [{**item.target, "requestedWidthPt": item.frame[2], "widthPt": available}
                      for item in objects if item.value is None and item.frame[2] > available]}}
    if any(item.value is not None for item in objects):
        metadata["authoredObjects"] = {"placement": "flow_top_left_id", "overlapAndStacking": False,
                                       "shapes": "individual_transparent_pictures"}
    return metadata


class DocxObjects:
    def __init__(self, output, document, page_size, *, shade_cell, border_cell, clear_borders, asset_root=None, assembly_number=None):
        self.asset_root, self.assembly_number = asset_root, assembly_number
        self.output = output
        self.pages = prepare_objects(document, page_size)
        self.numbering = _Numbering(output)
        self.shade_cell, self.border_cell, self.clear_borders = shade_cell, border_cell, clear_borders

    def flush(self, page_id, before=float("inf")):
        pending = self.pages[page_id]
        while pending and pending[0].frame[1] < before:
            self._write(pending.pop(0))

    def _write(self, item):
        if item.value is not None:
            from .objects import docx_image, docx_shape
            if item.value["type"] == "image":
                docx_image(self.output, item.value, item.style, item.frame[2:], self.asset_root, self.assembly_number)
            else:
                docx_shape(self.output, item.value, item.style, item.frame[2:])
            return
        from dataclasses import replace
        from docx.oxml.ns import qn
        from docx.opc.constants import RELATIONSHIP_TYPE as RT
        from docx.shared import Pt
        from docx.enum.table import WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT

        section = self.output.sections[-1]
        available = (section.page_width - section.left_margin - section.right_margin) / 12700
        width = min(item.frame[2], available)
        table = self.output.add_table(rows=1, cols=1)
        table.autofit = False
        table.alignment = WD_TABLE_ALIGNMENT.LEFT
        table.columns[0].width = Pt(width)
        table._tbl.tblPr.find(qn("w:tblW")).set(qn("w:w"), str(round(width * 20)))
        table._tbl.tblPr.find(qn("w:tblW")).set(qn("w:type"), "dxa")
        self.clear_borders(table)
        borders = table._tbl.tblPr.find(qn("w:tblBorders"))
        # The neighbouring border helper appends. This table also has a fixed
        # layout, whose schema position follows tblBorders.
        table._tbl.tblPr.remove(borders)
        layout = table._tbl.tblPr.find(qn("w:tblLayout"))
        layout.addprevious(borders)
        table._tbl.tblPr.append(_element("w:tblCaption", val="Authored text: " + item.target["targetId"]))
        row = table.rows[0]
        row.height, row.height_rule = Pt(item.frame[3]), WD_ROW_HEIGHT_RULE.AT_LEAST
        cell = row.cells[0]
        cell.width = Pt(width)
        outline = max(0, float(item.style.get("lineWidth") or 0)) if item.outline else 0
        if outline:
            for edge in ("top", "left", "bottom", "right"):
                self.border_cell(cell, edge, item.style["outlineColor"], max(1, round(outline * 8)))
        self.shade_cell(cell, str(item.style.get("fill") or "#FFFFFF").lstrip("#").upper())
        margins = _element("w:tcMar")
        for edge in ("top", "left", "bottom", "right"):
            margins.append(_element("w:" + edge, w=round((PADDING + outline) * 20), type="dxa"))
        cell._tc.get_or_add_tcPr().append(margins)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
        write_content(self.output, item.content, item.target, cell.add_paragraph,
                      first=cell.paragraphs[0], numbering=self.numbering, container=cell,
                      table_width=width - 2 * (PADDING + outline))
        opacity = float(item.style.get("opacity", 1))
        if opacity < 1:
            # Native Word text has no run alpha. In the white flow, blend direct colours with paper.
            for element in cell._tc.iter():
                for attribute in ({"w:color", "w:fill", "w:val"} if element.tag == qn("w:color") else {"w:color", "w:fill"}):
                    value = element.get(qn(attribute))
                    if value and len(value) == 6 and all(c in "0123456789abcdefABCDEF" for c in value):
                        element.set(qn(attribute), "".join(f"{round(int(value[i:i+2], 16) * opacity + 255 * (1-opacity)):02X}"
                                                        for i in (0, 2, 4)))


def _write_table(output, model, target, container, width, numbering):
    from docx.table import _Cell
    from .tables import column_widths
    columns = column_widths(width, [c["width"] for c in model.columns])
    if any(w < 12 for w in columns):
        from .fit import overflow
        overflow([{**target, "reasons": ["table_column_too_narrow"]}],
                 "Table columns must be at least twelve points wide.")
    twips = [round(w * 20) for w in columns[:-1]]
    twips.append(round((width - 1) * 20) - sum(twips))
    table = _element("w:tbl")
    props = _element("w:tblPr")
    props.append(_element("w:tblW", w=sum(twips), type="dxa"))
    props.append(_element("w:tblLayout", type="fixed"))
    table.append(props)
    grid = _element("w:tblGrid")
    for w in twips:
        grid.append(_element("w:gridCol", w=w))
    table.append(grid)
    occupied = {}
    for cell in model.cells:
        for y in range(cell.row, cell.row + cell.rowspan):
            for x in range(cell.column, cell.column + cell.colspan):
                occupied[y, x] = cell
    for y in range(len(model.row_ids)):
        row = _element("w:tr")
        row_props = _element("w:trPr")
        row_props.append(_element("w:cantSplit"))
        row.append(row_props)
        x = 0
        while x < len(columns):
            model_cell = occupied[y, x]
            cell = _element("w:tc")
            props = _element("w:tcPr")
            props.append(_element("w:tcW", w=sum(twips[x:x + model_cell.colspan]), type="dxa"))
            if model_cell.colspan > 1:
                props.append(_element("w:gridSpan", val=model_cell.colspan))
            if model_cell.rowspan > 1:
                props.append(_element("w:vMerge", val="restart" if y == model_cell.row else "continue"))
            borders = _element("w:tcBorders")
            for edge in ("top", "left", "bottom", "right"):
                borders.append(_element("w:" + edge, **({"val": "single", "sz": 8, "color": "8A98A5"}
                    if model.style == "grid" else {"val": "nil"})))
            props.append(borders)
            if model_cell.fill:
                props.append(_element("w:shd", val="clear", color="auto", fill=model_cell.fill.lstrip("#").upper()))
            margins = _element("w:tcMar")
            for edge in ("top", "left", "bottom", "right"):
                margins.append(_element("w:" + edge, w=90, type="dxa"))
            props.append(margins)
            props.append(_element("w:vAlign", val="center" if model_cell.vertical_align == "middle" else model_cell.vertical_align))
            cell.append(props)
            row.append(cell)
            first = _element("w:p")
            cell.append(first)
            if y == model_cell.row:
                proxy = _Cell(cell, container)
                write_content(output, model_cell.content, target, proxy.add_paragraph,
                              first=proxy.paragraphs[0], numbering=numbering)
            x += model_cell.colspan
        table.append(row)
    container._tc.append(table)


def _write_flow(output, content, target, add_paragraph, first, numbering, container, width):
    from .rich_layout import Content, Table
    if container is None or width is None:
        raise DocumentEditError("invalid_export_layout", "An authored table requires its text-box flow and width.")
    pending = first
    for block in content.blocks:
        if isinstance(block, Table):
            if pending is not None:
                pending._p.getparent().remove(pending._p)
                pending = None
            _write_table(output, block, target, container, width, numbering)
        else:
            write_content(output, Content((block,), content.base_size, content.base_run), target,
                          add_paragraph, first=pending, numbering=numbering)
            pending = None
    if isinstance(content.blocks[-1], Table):
        # OOXML requires a final paragraph in a cell, even after a nested table.
        paragraph = add_paragraph()
        props = paragraph._p.get_or_add_pPr()
        props.append(_element("w:spacing", before=0, after=0, line=1, lineRule="exact"))
        run = _element("w:rPr")
        run.append(_element("w:sz", val=1))
        props.append(run)


def narrative_bookmark(target):
    import hashlib
    return "rich_" + hashlib.sha256(str(target).encode("utf-8")).hexdigest()[:24]


def write_content(output, content, target, add_paragraph=None, *, first=None, numbering=None, narrative=False,
                  container=None, table_width=None):
    """Native paragraphs in the caller's flow (or an authored object's existing cell)."""
    from dataclasses import replace
    from docx.oxml.ns import qn
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.shared import Pt
    add_paragraph = add_paragraph or output.add_paragraph
    numbering = numbering or _Numbering(output)
    invalid = sorted({ord(c) for p in content.paragraphs for r in p.runs for c in r.text
                      if ord(c) < 32 and c not in "\t\n\r" or ord(c) in {0xfffe, 0xffff}})
    if invalid:
        raise DocumentEditError("unsupported_export_character", "DOCX XML cannot represent these characters.",
                                targets=[target], codePoints=[f"U+{c:04X}" for c in invalid])
    if content.blocks:
        return _write_flow(output, content, target, add_paragraph, first, numbering, container, table_width)
    for index, model in enumerate(content.paragraphs):
        paragraph = first if index == 0 and first is not None else add_paragraph()
        if narrative:
            bookmark = max((int(n.get(qn("w:id"))) for n in output.element.iter(qn("w:bookmarkStart"))), default=0) + 1
            start = _element("w:bookmarkStart", id=bookmark)
            # _element's own first parameter is called name; pass the bookmark name as an attribute (supervisor P3a-3).
            start.set(qn("w:name"), narrative_bookmark(target["targetId"]) + "_" + str(index))
            paragraph._p.append(start)
        if model.named_style:
            from docx.enum.style import WD_STYLE_TYPE
            name = model.named_style.title()
            if name not in output.styles:
                added = output.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
                added.base_style = output.styles["Normal"]
            paragraph.style = output.styles[name]
        elif model.heading_level:
            paragraph.style = output.styles[f"Heading {model.heading_level}"]
        fmt = paragraph.paragraph_format
        fmt.space_before = Pt(model.space_before)
        fmt.space_after = Pt(model.space_after)
        fmt.keep_with_next = fmt.keep_together = fmt.widow_control = False
        props = paragraph._p.get_or_add_pPr()
        spacing = props.find(qn("w:spacing"))
        spacing.set(qn("w:line"), str(round(model.line_height * model.font_size * 20)))
        spacing.set(qn("w:lineRule"), "atLeast")
        # A paragraph's own textAlign wins over the box's justify, as on the canvas (content_model keeps "justify").
        align = "both" if model.align == "justify" else model.align
        props.append(_element("w:jc", val=align))
        if model.list_path:
            depth = len(model.list_path)
            if model.marker is not None:
                number = numbering.number((target["pageId"], target["targetId"]), model.list_path[-1],
                                               depth, marker_gap(model))
                numpr = props.get_or_add_numPr()
                numpr.append(_element("w:ilvl", val=depth - 1))
                numpr.append(_element("w:numId", val=number))
            # Continuations retain the text start but have no numbering.
            indent = props.get_or_add_ind()
            indent.set(qn("w:left"), str(round((LIST_INDENT * depth + model.indent) * 20)))
            indent.set(qn("w:hanging"), str(round(model.indent * 20) + marker_gap(model)) if model.marker is not None else "0")
            if model.indent and model.marker is not None:
                # Numbering positions the outside marker at the li start, not the indented paragraph. Word starts the
                # text at the first tab stop after the number, and the level's own list tab (at the li start, see
                # _Numbering) comes first: clear it so the text starts at the indent (Word 16 render, P3a-1 gate).
                tabs = props.get_or_add_tabs()
                tabs.append(_element("w:tab", val="clear", pos=round(LIST_INDENT * depth * 20)))
                tabs.append(_element("w:tab", val="num", pos=round((LIST_INDENT * depth + model.indent) * 20)))
        elif model.indent:
            props.get_or_add_ind().set(qn("w:left"), str(round(model.indent * 20)))
        if model.named_style:
            # The template's Title style draws a bottom border and its contextual spacing drops the space between
            # two Title paragraphs; the canvas has neither (supervisor P3a-2). Direct formatting turns both off.
            borders = _element("w:pBdr")
            for side in ("top", "left", "bottom", "right", "between", "bar"):
                borders.append(_element("w:" + side, val="nil"))
            props.insert_element_before(borders, *_PPR_ORDER[_PPR_ORDER.index("w:pBdr") + 1:])
            props.insert_element_before(_element("w:contextualSpacing", val=0),
                                        *_PPR_ORDER[_PPR_ORDER.index("w:contextualSpacing") + 1:])
        base = model.base_run or replace(content.base_run, bold=content.base_run.bold or bool(model.heading_level))
        props.append(_properties(base, model))
        for run, kind, value in tokens(model):
            element = _element("w:r")
            element.append(_properties(run, model))
            leaf = _element("w:" + kind)
            if kind == "t":
                leaf.set(qn("xml:space"), "preserve")
                leaf.text = value  # No NFC or glyph filtering in DOCX.
            element.append(leaf)
            if run.href:
                link = _element("w:hyperlink")
                link.set(qn("r:id"), paragraph.part.relate_to(run.href, RT.HYPERLINK, is_external=True))
                link.append(element)
                paragraph._p.append(link)
            else:
                paragraph._p.append(element)
        if narrative:
            paragraph._p.append(_element("w:bookmarkEnd", id=bookmark))
