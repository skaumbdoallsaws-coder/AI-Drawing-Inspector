"""Rich generated narrative frames. Legacy plain block paths never enter here."""
from .commands import DocumentEditError
from .rich_text import validate, require_capabilities
from .targets import rich_block_capabilities


def base_style(block, override=None):
    kind = block.get("blockType")
    if kind in {"note", "status_panel"}:
        return {"fontFamily": "Arial", "fontStyle": "normal", "textDecoration": "none", "fontSize": 10, "fontWeight": 400, "color": "#18212a",
                "baseLineHeight": 1.4, "textAlign": "left",
                "signalWord": str(block.get("signalWord") or block.get("tone") or "notice").upper()}
    if kind == "cad_figure":
        return {"fontFamily": "Arial", "fontStyle": "normal", "textDecoration": "none", "fontSize": 7.5, "fontWeight": 400, "color": "#596a76",
                "baseLineHeight": 1.6, "textAlign": "center"}
    style = {**(block.get("style") or {}), **((override or {}).get("style") or {})}
    size = float(style.get("fontSize") or 10)
    return {"fontFamily": "Arial", "fontStyle": "normal", "textDecoration": "none", "fontSize": size, "fontWeight": style.get("fontWeight") or 400,
            "color": style.get("color") or "#18212a", "textAlign": style.get("textAlign") or "left",
            "baseLineHeight": float(style["lineHeight"]) / size if style.get("lineHeight") else 1.35}


def effective_override(page, block):
    from ai_inspector.operations_manual.exports import _page_override
    return _page_override(page, block.get("stableId", "")) or _page_override(page, block.get("blockId", ""))


def rich_value(document, page, block):
    override = effective_override(page, block)
    if "richText" not in override:
        return None
    target = {"pageId": page["pageId"], "targetId": block.get("stableId") or block.get("blockId", "")}
    try:
        value = validate(override["richText"])
        require_capabilities(value, rich_block_capabilities(document.get("documentType"), block.get("blockType")) or {}, targets=[target])
        return value
    except DocumentEditError as error:
        raise DocumentEditError(error.code, str(error), **{**error.details, "targets": [target]}) from error


def has_rich_blocks(document):
    return any("richText" in effective_override(page, block) for page in document.get("pages", [])
               for block in page.get("layoutBlocks", []) if block.get("blockId"))


def block_frame(document, page, block):
    from ai_inspector.operations_manual.exports import _block_frame
    # A canonical identity override can be present without its disposable alias projection.
    composition = page.get("documentationComposition") or {}
    projected = {**page, "documentationComposition": {**composition, "pageElementOverrides": {
        **composition.get("pageElementOverrides", {}), block.get("blockId", ""): effective_override(page, block)}}}
    return _block_frame(projected, block, document)


def content_frame(block, frame):
    x, y, w, h = (float(frame[key]) for key in ("x", "y", "width", "height"))
    if block.get("blockType") in {"note", "status_panel"}:
        return (x + 68, y + 2, x + w, y + h - 2)
    if block.get("blockType") == "cad_figure":
        return (x, y + h - 16, x + w, y + h)
    return (x, y, x + w, y + h)


def prepare_pdf_blocks(fitz, document, *, canvas_rounding=False):
    from .rich_layout import layout_text, ObjectLayout
    plans, missing, overflowing = {}, [], []
    for page in document.get("pages", []):
        rows = plans.setdefault(page["pageId"], {})
        for block in page.get("layoutBlocks", []):
            value = rich_value(document, page, block)
            if value is None:
                continue
            target = {"pageId": page["pageId"], "targetId": block.get("stableId") or block.get("blockId", "")}
            style = base_style(block, effective_override(page, block))
            frame = content_frame(block, block_frame(document, page, block))
            layout = layout_text(value, frame, style, fitz_module=fitz, canvas_rounding=canvas_rounding)
            if layout.unrenderable:
                missing.append({**target, "codePoints": list(layout.unrenderable)})
            if layout.overflow:
                overflowing.append({**target, "measuredHeight": layout.measured_height, "frame": list(frame)})
            if block.get("blockType") in {"note", "status_panel"} and not layout.overflow:
                # align-items:center in the padded notice grid, without moving the symbol.
                offset = (frame[3] - frame[1] - layout.measured_height) / 2
                frame = (frame[0], frame[1] + offset, frame[2], frame[3])
                layout = layout_text(value, frame, style, fitz_module=fitz, canvas_rounding=canvas_rounding)
            rows[block.get("blockId", "")] = ObjectLayout(target, frame, style, False, layout)
    from .fit import collecting
    if missing and not collecting():
        raise DocumentEditError("unsupported_export_glyph", "No available PDF font renders these characters.", targets=missing)
    if overflowing:
        from .fit import overflow
        overflow(overflowing, "Rich narrative text must fit its generated frame.")
    return plans
