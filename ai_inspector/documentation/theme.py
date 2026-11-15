"""The document theme as Sage reads and changes it (theme tool, 2026-11-14).

The theme is the scene's document-wide look: company and theme names, seven named colours, heading and
body fonts and weights, table colours and callout colours. Sage changes it through apply_document_edits
with one operation sent alone, bound to the theme hash of its read, exactly like page setup. The logo is
a managed upload and stays with the workspace's theme dialog.
"""
from __future__ import annotations

from copy import deepcopy

from .commands import DocumentEditError

COLOR_FIELDS = ("primary", "secondary", "accent", "text", "muted", "page", "rule")
TABLE_FIELDS = ("headerFill", "bodyFill", "ruleColor")
ANNOTATION_FIELDS = ("balloonColor", "leaderColor")
TYPOGRAPHY_FIELDS = ("headingFont", "bodyFont", "headingWeight", "bodyWeight")
SECTIONS = {"colors": COLOR_FIELDS, "typography": TYPOGRAPHY_FIELDS, "table": TABLE_FIELDS,
            "annotation": ANNOTATION_FIELDS}
NAME_FIELDS = ("name", "companyName")
NAME_LIMIT = 120
WEIGHT_RANGE = (100, 900)
# PDF exports print with the standard PDF fonts (parts_manual.pdf._pdf_font); Word keeps the named font.
PDF_SUBSTITUTES = {"Inter": "Helvetica", "Georgia": "Times New Roman"}


def fonts() -> list[str]:
    from ai_inspector.parts_manual.documentation import _DOCUMENT_FONT_FAMILIES
    return sorted(_DOCUMENT_FONT_FAMILIES)


def view(theme: dict | None) -> dict:
    """The read's theme: every setting except the logo asset's internals."""
    from ai_inspector.parts_manual.documentation import DEFAULT_DOCUMENT_THEME
    source = theme or DEFAULT_DOCUMENT_THEME
    result = {key: deepcopy(value) for key, value in source.items() if key != "logo"}
    result["hasLogo"] = bool(source.get("logo"))
    return result


def options(templates: list[dict]) -> dict:
    return {"fonts": fonts(), "pdfFontSubstitutes": dict(PDF_SUBSTITUTES), "colorFormat": "#RRGGBB",
            "sections": {key: list(fields) for key, fields in SECTIONS.items()},
            "weightRange": list(WEIGHT_RANGE),
            "templates": [{"templateId": t["templateId"], "name": t["name"]} for t in templates],
            "workspaceOnly": ["logo"]}


def _normalized(theme: dict) -> dict:
    from ai_inspector.parts_manual.documentation import _document_theme, DocumentationSceneError
    try:
        return _document_theme(theme)
    except DocumentationSceneError as error:
        raise DocumentEditError("invalid_document_theme", str(error)) from error


def _same(left: dict, right: dict) -> bool:
    return ({k: v for k, v in left.items() if k != "version"} == {k: v for k, v in right.items() if k != "version"})


def merged(current: dict | None, patch: dict) -> dict:
    """The complete next theme: the current one with the named settings changed and the version advanced."""
    from ai_inspector.parts_manual.documentation import DEFAULT_DOCUMENT_THEME
    if not isinstance(patch, dict) or not patch:
        raise DocumentEditError("invalid_document_theme", "Name at least one theme setting to change.")
    before = _normalized(deepcopy(current or DEFAULT_DOCUMENT_THEME))
    result = deepcopy(before)
    for key, value in patch.items():
        if key in NAME_FIELDS:
            result[key] = value
        elif key in SECTIONS and isinstance(value, dict) and value and set(value) <= set(SECTIONS[key]):
            result[key] = {**(result.get(key) or {}), **deepcopy(value)}
        else:
            raise DocumentEditError("invalid_document_theme", "Only the settings listed in themeOptions.sections, "
                                    "name and companyName can change.", setting=str(key))
    result["version"] = int(before.get("version") or 1) + 1
    result = _normalized(result)
    if _same(before, result):
        raise DocumentEditError("document_theme_unchanged", "The theme already has these values; nothing was changed.")
    return result


def template_command(current: dict | None, page_masters: dict | None, templates: list[dict], template_id: str) -> dict:
    """The apply_template scene command for a saved template, as the theme dialog applies it."""
    template = next((t for t in templates if t.get("templateId") == template_id), None)
    if template is None:
        raise DocumentEditError("unknown_document_template", "No saved template has that ID; use themeOptions.templates.",
                                templateId=template_id)
    theme = _normalized(deepcopy(template.get("theme") or {}))
    if current is not None and _same(_normalized(deepcopy(current)), theme) and template.get("pageMasters") == page_masters:
        raise DocumentEditError("document_theme_unchanged", "The document already uses this template; nothing was changed.")
    return {"operation": "apply_template", "theme": theme, "pageMasters": deepcopy(template.get("pageMasters"))}
