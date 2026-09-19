"""Publication-grade PDF composition for illustrated parts manuals."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

from .artifacts import PartsManualRenderArtifactError, render_artifact_path
from .layout import PAGE_HEIGHT_PT, PAGE_WIDTH_PT, page_layout, publication_layout, rect_tuple
from .version import (
    PARTS_MANUAL_DEFAULT_END_CONDITION,
    PARTS_MANUAL_RENDER_PIPELINE_VERSION,
)


_ASSEMBLY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_DEFAULT_THEME: Dict[str, Any] = {
    "companyName": "InspectorPro",
    "colors": {
        "primary": "#071B2A",
        "secondary": "#C7E1F2",
        "accent": "#43B5EE",
        "text": "#18212A",
        "muted": "#596A76",
        "page": "#FFFFFF",
        "rule": "#ABBAC4",
    },
    "typography": {
        "headingFont": "Arial",
        "bodyFont": "Arial",
        "headingWeight": 700,
        "bodyWeight": 400,
    },
    "table": {
        "headerFill": "#FFFFFF",
        "bodyFill": "#FFFFFF",
        "ruleColor": "#6E787F",
    },
    "annotation": {
        "balloonColor": "#148FD0",
        "leaderColor": "#111820",
    },
    "logo": None,
}


class PartsManualPdfError(ValueError):
    pass


def _hex_rgb(value: Any, fallback: str = "#000000") -> tuple[float, float, float]:
    text = str(value or fallback).strip()
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", text) is None:
        text = fallback
    return tuple(int(text[index : index + 2], 16) / 255 for index in (1, 3, 5))


def _document_theme(document: Mapping[str, Any]) -> Dict[str, Any]:
    source = document.get("theme")
    source = source if isinstance(source, Mapping) else {}
    result = json.loads(json.dumps(_DEFAULT_THEME))
    for key in ("themeId", "name", "version", "companyName", "logo"):
        if key in source:
            result[key] = source.get(key)
    for key in ("colors", "typography", "table", "annotation"):
        if isinstance(source.get(key), Mapping):
            result[key].update(source[key])
    return result


def _pdf_font(family: Any, weight: Any = 400, style: Any = "normal") -> str:
    name = str(family or "Arial").casefold()
    bold = int(weight or 400) >= 600
    italic = str(style or "normal") == "italic"
    if "courier" in name:
        return "cobi" if bold and italic else "cobo" if bold else "coit" if italic else "cour"
    if "georgia" in name or "times" in name:
        return "tibi" if bold and italic else "tibo" if bold else "tiit" if italic else "tiro"
    return "hebi" if bold and italic else "hebo" if bold else "heit" if italic else "helv"


def _composition(descriptor: Mapping[str, Any]) -> Mapping[str, Any]:
    direct = descriptor.get("documentationComposition")
    if isinstance(direct, Mapping):
        return direct
    request = descriptor.get("renderRequest")
    nested = request.get("composition") if isinstance(request, Mapping) else None
    return nested if isinstance(nested, Mapping) else {}


def _page_element_override(
    descriptor: Mapping[str, Any], element_id: str
) -> Mapping[str, Any]:
    overrides = _composition(descriptor).get("pageElementOverrides")
    override = overrides.get(element_id) if isinstance(overrides, Mapping) else None
    return override if isinstance(override, Mapping) else {}


def _page_element_text(
    descriptor: Mapping[str, Any], element_id: str, fallback: Any
) -> str:
    override = _page_element_override(descriptor, element_id)
    return str(override.get("text") if "text" in override else fallback or "")


def _page_element_style(
    descriptor: Mapping[str, Any], element_id: str
) -> Mapping[str, Any]:
    value = _page_element_override(descriptor, element_id).get("style")
    return value if isinstance(value, Mapping) else {}


def _publication_rect(fitz: Any, descriptor: Mapping[str, Any]) -> Any:
    return fitz.Rect(*rect_tuple(descriptor))


def _page_element_rect(
    fitz: Any,
    page: Any,
    descriptor: Mapping[str, Any],
    rect: Mapping[str, Any],
    element_id: str,
) -> Any:
    result = _publication_rect(fitz, rect)
    override = _page_element_override(descriptor, element_id)
    translation = override.get("translation") if isinstance(override, Mapping) else None
    if isinstance(translation, (list, tuple)) and len(translation) >= 2:
        dx = float(translation[0]) * page.rect.width
        dy = float(translation[1]) * page.rect.height
        result = fitz.Rect(
            result.x0 + dx,
            result.y0 + dy,
            result.x1 + dx,
            result.y1 + dy,
        )
    size_delta = override.get("sizeDelta") if isinstance(override, Mapping) else None
    if isinstance(size_delta, (list, tuple)) and len(size_delta) >= 2:
        width = max(24.0, result.width + float(size_delta[0]) * page.rect.width)
        height = max(24.0, result.height + float(size_delta[1]) * page.rect.height)
        result = fitz.Rect(result.x0, result.y0, result.x0 + width, result.y0 + height)
    return result


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _pdf_paths(root: str | Path, assembly_number: str, document_revision: str) -> tuple[Path, Path]:
    assembly = str(assembly_number or "").strip().lower()
    revision = str(document_revision or "").strip().lower()
    if _ASSEMBLY_RE.fullmatch(assembly) is None or _SHA256_RE.fullmatch(revision) is None:
        raise PartsManualPdfError("invalid PDF artifact identity")
    base = Path(root).resolve()
    directory = (base / assembly / "documents" / revision).resolve()
    try:
        directory.relative_to(base)
    except ValueError as exc:
        raise PartsManualPdfError("invalid PDF artifact path") from exc
    filename = f"{assembly}-illustrated-parts-manual.pdf"
    return directory / filename, directory / f"{assembly}-illustrated-parts-manual.json"


def _native_path(value: Path) -> str:
    resolved = str(value.resolve())
    if os.name != "nt" or resolved.startswith("\\\\?\\"):
        return resolved
    if resolved.startswith("\\\\"):
        return "\\\\?\\UNC\\" + resolved[2:]
    return "\\\\?\\" + resolved


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None

    try:
        descriptor, name = tempfile.mkstemp(prefix=".tmp-", suffix=path.suffix, dir=str(path.parent))
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(_native_path(temporary), _native_path(path))
        temporary = None
    finally:
        if temporary is not None:
            try:
                os.unlink(_native_path(temporary))
            except FileNotFoundError:
                pass


def _validate_document(document: Mapping[str, Any]) -> None:
    findings = []
    pages = [row for row in document.get("pages") or [] if isinstance(row, Mapping)]
    if document.get("status") != "publication_ready":
        findings.append("document is not publication-ready")
    if (document.get("publicationAudit") or {}).get("status") != "PASS":
        findings.append("manual coverage and grouping audit did not pass")
    if (document.get("calloutAudit") or {}).get("status") != "PASS":
        findings.append("manual callout and BOM coverage is incomplete")
    if not str(document.get("documentNumber") or "").strip():
        findings.append("document number is missing")
    # A controlled OEM revision is optional.  The document compiler deliberately
    # suppresses InspectorPro library/source revisions because presenting one as
    # the product revision would be misleading.  An absent revision is therefore
    # rendered as unspecified rather than blocking an otherwise valid manual.
    if len(pages) != int(document.get("pageCount") or -1):
        findings.append("page count does not match the document model")
    expected_numbers = list(range(1, len(pages) + 1))
    if [int(row.get("pageNumber") or 0) for row in pages] != expected_numbers:
        findings.append("page numbers are not contiguous")
    page_ids = {str(row.get("pageId") or "") for row in pages}
    contents = next((row for row in pages if row.get("pageType") == "table_of_contents"), None)
    if contents is None:
        findings.append("table of contents is missing")
    else:
        missing_targets = [
            str(entry.get("pageId") or "")
            for entry in contents.get("entries") or []
            if str(entry.get("pageId") or "") not in page_ids
        ]
        if missing_targets:
            findings.append("table of contents references nonexistent pages")
    for page in pages:
        if not str(page.get("title") or "").strip():
            findings.append(f"{page.get('pageId') or 'page'} has no meaningful title")
        if page.get("pageType") in {"assembly_overview", "manual_section"}:
            if not str(page.get("figureNumber") or "").strip():
                findings.append(f"{page.get('pageId')} has no figure number")
        if page.get("pageType") == "manual_section":
            bom = [row for row in page.get("bom") or [] if isinstance(row, Mapping)]
            if not bom:
                findings.append(f"{page.get('pageId')} has no BOM")
            for row in bom:
                if not str(row.get("description") or "").strip() or int(row.get("quantity") or 0) < 1:
                    findings.append(f"{page.get('pageId')} contains an invalid BOM row")
    if findings:
        raise PartsManualPdfError("PDF publication QA failed: " + "; ".join(dict.fromkeys(findings)))


def _required_render_paths(
    root: str | Path,
    assembly_number: str,
    document: Mapping[str, Any],
) -> Dict[str, Path]:
    missing = []
    invalid = []
    result: Dict[str, Path] = {}
    for page in document.get("pages") or []:
        if not isinstance(page, Mapping) or not isinstance(page.get("renderRequest"), Mapping):
            continue
        page_id = str(page.get("pageId") or "")
        request = page["renderRequest"]
        image = request.get("image")
        if not isinstance(image, Mapping) or image.get("status") != "ready":
            missing.append(page_id)
            continue
        if image.get("renderPipelineVersion") != PARTS_MANUAL_RENDER_PIPELINE_VERSION:
            invalid.append(f"{page_id}: render pipeline is stale")
        if (image.get("quality") or {}).get("status") != "PASS":
            invalid.append(f"{page_id}: render quality did not pass")
        expected_items = {
            int(row.get("itemNumber") or 0)
            for row in request.get("calloutItems") or []
            if isinstance(row, Mapping)
        }
        actual_items = {
            int(row.get("itemNumber") or 0)
            for row in image.get("balloons") or []
            if isinstance(row, Mapping)
        }
        if expected_items != actual_items:
            invalid.append(f"{page_id}: balloon/BOM mapping is incomplete")
        callout_quality = (image.get("quality") or {}).get("calloutQuality") or {}
        if expected_items and (
            callout_quality.get("status") != "PASS"
            or callout_quality.get("anchorMethod") != "frontmost_camera_raycast"
            or callout_quality.get("leaderStyle") != "auto_straight_first"
            or callout_quality.get("routeValidationMethod") != "frontmost_raycast_sampling"
            or int(callout_quality.get("leaderCrossingCount") or 0) != 0
            or int(callout_quality.get("geometryIntersectionCount") or 0) != 0
            or int(callout_quality.get("leaderBalloonCollisionCount") or 0) != 0
            or int(callout_quality.get("nearParallelCongestionCount") or 0) != 0
            or float(callout_quality.get("maximumVisibleLeaderLength") or 1.0) > 0.35
            or float(callout_quality.get("maximumLeaderDetourRatio") or 99.0) > 2.25
            or int(callout_quality.get("maximumAutomaticElbowCount") or 0) > 1
            or int(callout_quality.get("balloonCircumferenceAttachmentCount") or 0)
            != len(expected_items)
        ):
            invalid.append(f"{page_id}: technical callout QA did not pass")
        try:
            result[page_id] = render_artifact_path(
                root,
                assembly_number,
                str(document.get("documentRevision") or ""),
                page_id,
            )
        except PartsManualRenderArtifactError:
            missing.append(page_id)
    if missing:
        raise PartsManualPdfError(
            "Capture the required technical illustrations before generating the PDF: "
            + ", ".join(missing)
        )
    if invalid:
        raise PartsManualPdfError("PDF publication QA failed: " + "; ".join(invalid))
    return result


def _fit_text(
    fitz: Any,
    page: Any,
    rect: Any,
    value: Any,
    *,
    fontsize: float = 8.0,
    fontname: str = "helv",
    color: tuple[float, float, float] = (0.12, 0.16, 0.20),
    align: int = 0,
) -> None:
    text = str(value or "")
    available_width = max(1.0, rect.width - 2.0)
    measured = fitz.get_text_length(text, fontname=fontname, fontsize=fontsize)
    size = max(4.5, fontsize * min(1.0, available_width / max(measured, 1.0) * 0.96))
    page.insert_textbox(rect, text, fontsize=size, fontname=fontname, color=color, align=align)


_BRAND_BLUE = (105 / 255, 206 / 255, 1.0)
_BRAND_NAVY = (0.035, 0.075, 0.12)


def _documentation_asset_path(
    root: str | Path,
    assembly_number: str,
    asset: Mapping[str, Any],
) -> Path:
    assembly = str(assembly_number or "").strip().lower()
    asset_id = str(asset.get("assetId") or "").strip().lower()
    mime_type = str(asset.get("mimeType") or "").strip().lower()
    if _ASSEMBLY_RE.fullmatch(assembly) is None or _SHA256_RE.fullmatch(asset_id) is None:
        raise PartsManualPdfError("documentation image has an invalid managed identity")
    extension = ".png" if mime_type == "image/png" else ".jpg" if mime_type == "image/jpeg" else ""
    if not extension:
        raise PartsManualPdfError("documentation image must be PNG or JPEG")
    base = Path(root).resolve()
    path = (base / assembly / "documentation-assets" / f"{asset_id}{extension}").resolve()
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise PartsManualPdfError("documentation image path is invalid") from exc
    if not path.is_file():
        raise PartsManualPdfError(
            f"documentation image asset is missing: {asset.get('filename') or asset_id}"
        )
    return path


def _draw_brand_mark(
    fitz: Any,
    page: Any,
    theme: Mapping[str, Any],
    root: str | Path,
    assembly_number: str,
    rect: Any,
    *,
    fontsize: float,
    inspector_color: tuple[float, float, float] = (1, 1, 1),
) -> None:
    logo = theme.get("logo")
    if isinstance(logo, Mapping):
        path = _documentation_asset_path(root, assembly_number, logo)
        page.insert_image(rect, filename=str(path), keep_proportion=True)
        return
    _draw_wordmark(
        fitz,
        page,
        fitz.Point(rect.x0, rect.y0 + fontsize),
        fontsize=fontsize,
        inspector_color=inspector_color,
        pro_color=_hex_rgb((theme.get("colors") or {}).get("accent"), "#43B5EE"),
    )


def _draw_wordmark(
    fitz: Any,
    page: Any,
    origin: Any,
    *,
    fontsize: float,
    inspector_color: tuple[float, float, float] = (1, 1, 1),
    pro_color: tuple[float, float, float] = _BRAND_BLUE,
) -> None:
    page.insert_text(
        origin,
        "Inspector",
        fontsize=fontsize,
        fontname="hebo",
        color=inspector_color,
    )
    inspector_width = fitz.get_text_length("Inspector", fontname="hebo", fontsize=fontsize)
    page.insert_text(
        fitz.Point(origin.x + inspector_width, origin.y),
        "Pro",
        fontsize=fontsize,
        fontname="hebo",
        color=pro_color,
    )


def _draw_header(
    fitz: Any,
    page: Any,
    descriptor: Mapping[str, Any],
    document: Mapping[str, Any],
    root: str | Path,
    assembly_number: str,
) -> None:
    theme = _document_theme(document)
    colors = theme["colors"]
    typography = theme["typography"]
    page.draw_rect(
        fitz.Rect(0, 0, page.rect.width, 50),
        color=None,
        fill=_hex_rgb(colors["primary"], "#071B2A"),
    )
    _draw_brand_mark(
        fitz,
        page,
        theme,
        root,
        assembly_number,
        fitz.Rect(28, 12, 142, 38),
        fontsize=13,
    )
    figure = str(descriptor.get("figureNumber") or "").strip()
    title = str(descriptor.get("title") or "")
    default_heading = f"FIGURE {figure} - {title}" if figure else title.upper()
    heading = _page_element_text(descriptor, "header_title", default_heading)
    product = str((document.get("product") or {}).get("name") or "Product")
    revision = str(document.get("revision") or "").strip()
    default_metadata = (
        f"{product} | {document.get('documentNumber')}"
        + (f" | Rev {revision}" if revision else "")
        + (f" | Figure {figure}" if figure else "")
    )
    metadata = _page_element_text(descriptor, "header_meta", default_metadata)
    metadata_style = _page_element_style(descriptor, "header_meta")
    heading_style = _page_element_style(descriptor, "header_title")
    _fit_text(
        fitz,
        page,
        fitz.Rect(170, 7, page.rect.width - 28, 19),
        metadata,
        fontsize=float(metadata_style.get("fontSize") or 6.6),
        fontname=_pdf_font(
            metadata_style.get("fontFamily") or typography["bodyFont"],
            metadata_style.get("fontWeight") or typography["bodyWeight"],
            metadata_style.get("fontStyle"),
        ),
        color=_hex_rgb(metadata_style.get("color"), "#879FAC"),
        align=fitz.TEXT_ALIGN_RIGHT,
    )
    _fit_text(
        fitz,
        page,
        fitz.Rect(170, 23, page.rect.width - 28, 42),
        heading,
        fontsize=float(heading_style.get("fontSize") or 10.5),
        fontname=_pdf_font(
            heading_style.get("fontFamily") or typography["headingFont"],
            heading_style.get("fontWeight") or typography["headingWeight"],
            heading_style.get("fontStyle"),
        ),
        color=_hex_rgb(heading_style.get("color"), colors["secondary"]),
        align={
            "left": fitz.TEXT_ALIGN_LEFT,
            "center": fitz.TEXT_ALIGN_CENTER,
            "right": fitz.TEXT_ALIGN_RIGHT,
        }.get(str(heading_style.get("textAlign") or "right"), fitz.TEXT_ALIGN_RIGHT),
    )


def _draw_footer(
    fitz: Any,
    page: Any,
    document: Mapping[str, Any],
    descriptor: Mapping[str, Any],
) -> None:
    theme = _document_theme(document)
    colors = theme["colors"]
    typography = theme["typography"]
    footer_style = _page_element_style(descriptor, "footer")
    y = page.rect.height - 27
    page.draw_line(
        fitz.Point(28, y),
        fitz.Point(page.rect.width - 28, y),
        color=_hex_rgb(colors["rule"], "#ABBAC4"),
        width=0.6,
    )
    product = str((document.get("product") or {}).get("name") or "Product")
    figure = str(descriptor.get("figureNumber") or "N/A")
    revision = str(document.get("revision") or "").strip()
    default_left = (
        f"{product} | {document.get('documentNumber')}"
        + (f" | Rev {revision}" if revision else "")
        + " "
        f"| Figure {figure}"
    )
    left = _page_element_text(descriptor, "footer", default_left)
    footer_font = _pdf_font(
        footer_style.get("fontFamily") or typography["bodyFont"],
        footer_style.get("fontWeight") or typography["bodyWeight"],
        footer_style.get("fontStyle"),
    )
    footer_color = _hex_rgb(footer_style.get("color"), colors["muted"])
    _fit_text(
        fitz,
        page,
        fitz.Rect(28, y + 7, page.rect.width - 170, y + 21),
        left,
        fontsize=float(footer_style.get("fontSize") or 7.3),
        fontname=footer_font,
        color=footer_color,
    )
    page.insert_textbox(
        fitz.Rect(page.rect.width - 160, y + 7, page.rect.width - 28, y + 21),
        f"Page {descriptor.get('pageNumber')} of {document.get('pageCount')}",
        fontsize=float(footer_style.get("fontSize") or 7.3),
        fontname=footer_font,
        color=footer_color,
        align=fitz.TEXT_ALIGN_RIGHT,
    )


def _image_fit_rect(fitz: Any, target: Any, image: Mapping[str, Any]) -> Any:
    width = max(1.0, float(image.get("widthPx") or 4))
    height = max(1.0, float(image.get("heightPx") or 3))
    source_ratio = width / height
    target_ratio = target.width / max(target.height, 1.0)
    if source_ratio >= target_ratio:
        fitted_height = target.width / source_ratio
        offset = (target.height - fitted_height) / 2
        return fitz.Rect(target.x0, target.y0 + offset, target.x1, target.y1 - offset)
    fitted_width = target.height * source_ratio
    offset = (target.width - fitted_width) / 2
    return fitz.Rect(target.x0 + offset, target.y0, target.x1 - offset, target.y1)


def _draw_image(
    fitz: Any,
    page: Any,
    image_path: Path,
    rect: Any,
    image: Mapping[str, Any],
    *,
    framed: bool = True,
) -> Any:
    if framed:
        page.draw_rect(rect, color=(0.77, 0.81, 0.84), fill=(1, 1, 1), width=0.65)
        inset = fitz.Rect(rect.x0 + 4, rect.y0 + 4, rect.x1 - 4, rect.y1 - 4)
    else:
        inset = rect
    fitted = _image_fit_rect(fitz, inset, image)
    page.insert_image(fitted, filename=str(image_path), keep_proportion=True)
    return fitted


def _draw_balloons(
    fitz: Any,
    page: Any,
    image_rect: Any,
    image: Mapping[str, Any],
    theme: Mapping[str, Any] | None = None,
) -> None:
    theme = theme or _DEFAULT_THEME
    annotation = theme.get("annotation") if isinstance(theme, Mapping) else {}
    annotation = annotation if isinstance(annotation, Mapping) else {}
    annotation_color = _hex_rgb(annotation.get("leaderColor"), "#111820")
    balloon_color = _hex_rgb(annotation.get("balloonColor"), "#148FD0")

    def page_point(value: Mapping[str, Any]) -> Any:
        return fitz.Point(
            image_rect.x0 + float(value.get("x") or 0) * image_rect.width,
            image_rect.y0 + float(value.get("y") or 0) * image_rect.height,
        )

    def draw_path(points: Sequence[Mapping[str, Any]]) -> None:
        converted = [page_point(point) for point in points]
        for start, end in zip(converted, converted[1:]):
            page.draw_line(start, end, color=annotation_color, width=0.8)

    def draw_end_condition(
        target_value: Mapping[str, Any],
        next_value: Mapping[str, Any],
        end_condition: str,
        normal: Any = None,
    ) -> None:
        target_point = page_point(target_value)
        if end_condition == "none":
            return
        if end_condition == "dot":
            page.draw_circle(
                target_point,
                1.7,
                color=annotation_color,
                fill=annotation_color,
            )
            return
        next_point = page_point(next_value)
        dx = next_point.x - target_point.x
        dy = next_point.y - target_point.y
        length = max(math.hypot(dx, dy), 0.001)
        ux = dx / length
        uy = dy / length
        # Prefer the local outward surface normal so the head sits perpendicular
        # to the silhouette instead of inheriting the orthogonal route axis. Only
        # adopt it when it broadly agrees with the leader, so the head can never
        # point back along its own line.
        if isinstance(normal, Mapping):
            try:
                normal_x = float(normal.get("x"))
                normal_y = float(normal.get("y"))
            except (TypeError, ValueError):
                normal_x = normal_y = 0.0
            normal_magnitude = math.hypot(normal_x, normal_y)
            if normal_magnitude > 0:
                normal_x /= normal_magnitude
                normal_y /= normal_magnitude
                if normal_x * ux + normal_y * uy > 0.30:
                    ux, uy = normal_x, normal_y
        base_x = target_point.x + ux * 7.0
        base_y = target_point.y + uy * 7.0
        for sign in (-1.0, 1.0):
            wing = fitz.Point(
                base_x + (-uy) * 3.2 * sign,
                base_y + ux * 3.2 * sign,
            )
            page.draw_line(target_point, wing, color=annotation_color, width=0.9)

    for row in image.get("balloons") or []:
        target = row.get("target") or {}
        balloon = row.get("balloon") or {}
        bx = image_rect.x0 + float(balloon.get("x") or 0) * image_rect.width
        by = image_rect.y0 + float(balloon.get("y") or 0) * image_rect.height
        balloon_attachment = row.get("balloonAttachment") or balloon
        leader_points = [target, *(row.get("leaderPath") or []), balloon_attachment]
        draw_path(leader_points)
        end_condition = str(
            row.get("endCondition") or PARTS_MANUAL_DEFAULT_END_CONDITION
        )
        draw_end_condition(
            target, leader_points[1], end_condition, row.get("anchorNormal")
        )
        for branch in row.get("branches") or []:
            branch_target = branch.get("target") or {}
            branch_points = [branch_target, *(branch.get("leaderPath") or [])]
            draw_path(branch_points)
            if len(branch_points) > 1:
                draw_end_condition(
                    branch_target, branch_points[1], end_condition,
                    branch.get("anchorNormal"),
                )
        page.draw_circle(
            fitz.Point(bx, by),
            10,
            color=balloon_color,
            fill=(1, 1, 1),
            width=1.2,
        )
        label = str(row.get("itemNumber") or "")
        label_width = fitz.get_text_length(label, fontname="hebo", fontsize=8)
        page.insert_text(
            fitz.Point(bx - label_width * 0.5, by + 2.8),
            label,
            fontsize=8,
            fontname="hebo",
            color=balloon_color,
        )
        quantity_label = str(row.get("quantityLabel") or "").strip()
        if quantity_label:
            if str(row.get("routeSide") or "") == "left":
                quantity_rect = fitz.Rect(bx + 12, by - 7, bx + 34, by + 5)
                align = fitz.TEXT_ALIGN_LEFT
            else:
                quantity_rect = fitz.Rect(bx - 34, by - 7, bx - 12, by + 5)
                align = fitz.TEXT_ALIGN_RIGHT
            page.insert_textbox(
                quantity_rect,
                quantity_label,
                fontsize=6.4,
                fontname="hebo",
                color=balloon_color,
                align=align,
            )


def draw_balloon_manifest(
    fitz: Any,
    page: Any,
    image_rect: Any,
    image: Mapping[str, Any],
    theme: Mapping[str, Any] | None = None,
) -> None:
    """Draw the shared validated callout manifest over a technical figure."""

    _draw_balloons(fitz, page, image_rect, image, theme)


def _draw_bom_table(
    fitz: Any,
    page: Any,
    rect: Any,
    rows: Sequence[Mapping[str, Any]],
    theme: Mapping[str, Any] | None = None,
) -> None:
    theme = theme or _DEFAULT_THEME
    columns = (0.11, 0.30, 0.49, 0.10)
    headers = ("ITEM", "PART NUMBER", "DESCRIPTION", "QTY")
    x_positions = [rect.x0]
    for ratio in columns:
        x_positions.append(x_positions[-1] + rect.width * ratio)
    header_height = 18.0
    available_height = max(0.0, rect.height - header_height)
    row_height = min(18.0, available_height / max(1, len(rows)))
    if rows and row_height < 12.0:
        raise PartsManualPdfError("BOM rows do not fit inside the publication-safe page region")
    table_bottom = rect.y0 + header_height + row_height * len(rows)
    table_rect = fitz.Rect(rect.x0, rect.y0, rect.x1, table_bottom)
    table_theme = theme.get("table") if isinstance(theme, Mapping) else {}
    table_theme = table_theme if isinstance(table_theme, Mapping) else {}
    colors = theme.get("colors") if isinstance(theme, Mapping) else {}
    colors = colors if isinstance(colors, Mapping) else {}
    typography = theme.get("typography") if isinstance(theme, Mapping) else {}
    typography = typography if isinstance(typography, Mapping) else {}
    rule_color = _hex_rgb(table_theme.get("ruleColor"), "#6E787F")
    light_rule_color = tuple(min(1.0, value + (1.0 - value) * 0.42) for value in rule_color)
    page.draw_rect(
        table_rect,
        color=rule_color,
        fill=_hex_rgb(table_theme.get("bodyFill"), "#FFFFFF"),
        width=0.65,
    )
    page.draw_rect(
        fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + header_height),
        color=None,
        fill=_hex_rgb(table_theme.get("headerFill"), "#FFFFFF"),
    )
    body_font = _pdf_font(
        typography.get("bodyFont"), typography.get("bodyWeight"), "normal"
    )
    heading_font = _pdf_font(
        typography.get("headingFont"), typography.get("headingWeight"), "normal"
    )
    text_color = _hex_rgb(colors.get("text"), "#18212A")
    for index, header in enumerate(headers):
        page.insert_textbox(
            fitz.Rect(x_positions[index] + 3, rect.y0 + 5, x_positions[index + 1] - 3, rect.y0 + 16),
            header,
            fontsize=6.5,
            fontname=heading_font,
            color=text_color,
            align=fitz.TEXT_ALIGN_CENTER if index in {0, 3} else fitz.TEXT_ALIGN_LEFT,
        )
    page.draw_line(
        fitz.Point(rect.x0, rect.y0 + header_height),
        fitz.Point(rect.x1, rect.y0 + header_height),
        color=rule_color,
        width=0.85,
    )
    current_y = rect.y0 + header_height
    for row_index, row in enumerate(rows):
        bottom = current_y + row_height
        values = (
            str(row.get("item") or ""),
            str(row.get("displayPartNumber") or "Not specified"),
            str(row.get("description") or ""),
            str(row.get("quantity") or ""),
        )
        for index, value in enumerate(values):
            _fit_text(
                fitz,
                page,
                fitz.Rect(x_positions[index] + 3, current_y + 3, x_positions[index + 1] - 3, bottom),
                value,
                fontsize=min(6.6, max(5.6, row_height - 7.0)),
                fontname=body_font,
                color=text_color,
                align=fitz.TEXT_ALIGN_CENTER if index in {0, 3} else fitz.TEXT_ALIGN_LEFT,
            )
        page.draw_line(
            fitz.Point(rect.x0, bottom),
            fitz.Point(rect.x1, bottom),
            color=light_rule_color,
            width=0.3,
        )
        current_y = bottom
    for x in x_positions[1:-1]:
        page.draw_line(
            fitz.Point(x, rect.y0),
            fitz.Point(x, table_bottom),
            color=light_rule_color,
            width=0.35,
        )


def _draw_key_value_table(fitz: Any, page: Any, rows: Iterable[tuple[str, Any]], rect: Any) -> None:
    y = rect.y0
    for index, (label, raw_value) in enumerate(rows):
        value = str(raw_value or "Not specified")
        fill = (0.95, 0.97, 0.985) if index % 2 else (1, 1, 1)
        page.draw_rect(fitz.Rect(rect.x0, y, rect.x1, y + 30), color=(0.78, 0.82, 0.85), fill=fill, width=0.4)
        page.insert_textbox(
            fitz.Rect(rect.x0 + 8, y + 9, rect.x0 + 160, y + 24),
            label.upper(),
            fontsize=7.4,
            fontname="hebo",
            color=(0.16, 0.32, 0.43),
        )
        _fit_text(
            fitz,
            page,
            fitz.Rect(rect.x0 + 170, y + 8, rect.x1 - 8, y + 25),
            value,
            fontsize=8.2,
        )
        y += 30


def _document_object_style(
    theme: Mapping[str, Any], value: Mapping[str, Any]
) -> Dict[str, Any]:
    typography = theme.get("typography") or {}
    colors = theme.get("colors") or {}
    style_ref = str(value.get("styleRef") or "body")
    defaults = {
        "title": {"fontSize": 26.0, "fontWeight": typography.get("headingWeight", 700)},
        "heading": {"fontSize": 18.0, "fontWeight": typography.get("headingWeight", 700)},
        "body": {"fontSize": 10.0, "fontWeight": typography.get("bodyWeight", 400)},
        "caption": {"fontSize": 8.0, "fontWeight": typography.get("bodyWeight", 400)},
        "accent": {
            "fontSize": 12.0,
            "fontWeight": typography.get("headingWeight", 700),
            "color": colors.get("accent", "#43B5EE"),
        },
    }
    result: Dict[str, Any] = {
        "fontFamily": (
            typography.get("headingFont")
            if style_ref in {"title", "heading", "accent"}
            else typography.get("bodyFont")
        ),
        "fontStyle": "normal",
        "textDecoration": "none",
        "textAlign": "left",
        "color": colors.get("text", "#18212A"),
        "fill": "#FFFFFF",
        "outlineColor": colors.get("rule", "#ABBAC4"),
        "lineWidth": 1.0,
        "opacity": 1.0,
        **defaults.get(style_ref, defaults["body"]),
    }
    overrides = value.get("styleOverrides")
    if isinstance(overrides, Mapping):
        result.update(overrides)
    return result


def _draw_documentation_objects(
    fitz: Any,
    page: Any,
    descriptor: Mapping[str, Any],
    document: Mapping[str, Any],
    root: str | Path,
    assembly_number: str,
) -> None:
    objects = descriptor.get("documentationObjects")
    if not isinstance(objects, Mapping):
        return
    theme = _document_theme(document)
    for value in objects.values():
        if not isinstance(value, Mapping):
            continue
        frame = value.get("frame")
        if not isinstance(frame, Mapping):
            continue
        rect = fitz.Rect(
            float(frame.get("x") or 0) * page.rect.width,
            float(frame.get("y") or 0) * page.rect.height,
            (float(frame.get("x") or 0) + float(frame.get("width") or 0))
            * page.rect.width,
            (float(frame.get("y") or 0) + float(frame.get("height") or 0))
            * page.rect.height,
        )
        rotation = float(frame.get("rotation") or 0)
        morph = None if abs(rotation) < 1e-9 else (rect.tl + (rect.br - rect.tl) * 0.5, fitz.Matrix(rotation))
        style = _document_object_style(theme, value)
        opacity = float(style.get("opacity") if style.get("opacity") is not None else 1.0)
        object_type = str(value.get("type") or "")
        if object_type == "text":
            fill = style.get("fill")
            if fill and str(fill).upper() != "#FFFFFF":
                page.draw_rect(
                    rect,
                    color=None,
                    fill=_hex_rgb(fill, "#FFFFFF"),
                    fill_opacity=opacity,
                    morph=morph,
                )
            outline_width = float(style.get("lineWidth") or 0)
            if outline_width > 0 and "outlineColor" in (value.get("styleOverrides") or {}):
                page.draw_rect(
                    rect,
                    color=_hex_rgb(style.get("outlineColor"), "#ABBAC4"),
                    width=outline_width,
                    stroke_opacity=opacity,
                    morph=morph,
                )
            alignment = {
                "left": fitz.TEXT_ALIGN_LEFT,
                "center": fitz.TEXT_ALIGN_CENTER,
                "right": fitz.TEXT_ALIGN_RIGHT,
            }.get(str(style.get("textAlign") or "left"), fitz.TEXT_ALIGN_LEFT)
            page.insert_textbox(
                fitz.Rect(rect.x0 + 3, rect.y0 + 2, rect.x1 - 3, rect.y1 - 2),
                str(value.get("content") or ""),
                fontsize=float(style.get("fontSize") or 10),
                fontname=_pdf_font(
                    style.get("fontFamily"),
                    style.get("fontWeight"),
                    style.get("fontStyle"),
                ),
                color=_hex_rgb(style.get("color"), "#18212A"),
                align=alignment,
                fill_opacity=opacity,
                morph=morph,
            )
            if style.get("textDecoration") == "underline":
                page.draw_line(
                    fitz.Point(rect.x0 + 3, rect.y1 - 4),
                    fitz.Point(rect.x1 - 3, rect.y1 - 4),
                    color=_hex_rgb(style.get("color"), "#18212A"),
                    width=0.7,
                    morph=morph,
                    stroke_opacity=opacity,
                )
            continue
        if object_type == "image":
            asset = value.get("asset")
            if not isinstance(asset, Mapping):
                raise PartsManualPdfError("documentation image object has no managed asset")
            if abs(rotation % 90) > 1e-9:
                raise PartsManualPdfError(
                    "documentation image rotation must use 90-degree increments"
                )
            page.insert_image(
                rect,
                filename=str(_documentation_asset_path(root, assembly_number, asset)),
                keep_proportion=str(value.get("contentMode") or "contain") == "contain",
                rotate=int(rotation) % 360,
            )
            continue
        if object_type != "shape":
            continue
        color = _hex_rgb(style.get("outlineColor"), "#ABBAC4")
        fill = _hex_rgb(style.get("fill"), "#FFFFFF")
        width = float(style.get("lineWidth") or 1.0)
        shape_type = str(value.get("shapeType") or "rectangle")
        if shape_type == "ellipse":
            page.draw_oval(
                rect,
                color=color,
                fill=fill,
                width=width,
                stroke_opacity=opacity,
                fill_opacity=opacity,
                morph=morph,
            )
        elif shape_type == "arrow":
            start = fitz.Point(rect.x0, rect.y0 + rect.height * 0.5)
            end = fitz.Point(rect.x1, rect.y0 + rect.height * 0.5)
            page.draw_line(start, end, color=color, width=width, morph=morph)
            page.draw_line(end, fitz.Point(end.x - 9, end.y - 5), color=color, width=width, morph=morph)
            page.draw_line(end, fitz.Point(end.x - 9, end.y + 5), color=color, width=width, morph=morph)
        else:
            page.draw_rect(
                rect,
                color=color,
                fill=fill,
                width=width,
                dashes="3 2" if shape_type in {"revision_cloud", "detail_box"} else None,
                radius=0.12 if shape_type == "revision_cloud" else None,
                stroke_opacity=opacity,
                fill_opacity=opacity,
                morph=morph,
            )


def build_manual_pdf_bytes(
    root: str | Path,
    assembly_number: str,
    document: Mapping[str, Any],
) -> bytes:
    try:
        import fitz
    except ImportError as exc:
        raise PartsManualPdfError("PyMuPDF is required to generate parts manuals") from exc

    _validate_document(document)
    render_paths = _required_render_paths(root, assembly_number, document)
    pdf = fitz.open()
    layout_contract = document.get("publicationLayout")
    if not isinstance(layout_contract, Mapping):
        layout_contract = publication_layout()
    page_size = layout_contract.get("page") or {}
    width = float(page_size.get("width") or PAGE_WIDTH_PT)
    height = float(page_size.get("height") or PAGE_HEIGHT_PT)
    pending_links: list[tuple[int, tuple[float, float, float, float], int]] = []
    pages = list(document.get("pages") or [])
    theme = _document_theme(document)
    theme_colors = theme["colors"]
    theme_typography = theme["typography"]
    for descriptor in pages:
        page_number = int(descriptor.get("pageNumber") or len(pdf) + 1)
        page_type = str(descriptor.get("pageType") or "")
        page = pdf.new_page(width=width, height=height)
        page.draw_rect(
            page.rect,
            color=None,
            fill=_hex_rgb(theme_colors["page"], "#FFFFFF"),
        )

        if page_type == "cover":
            cover_layout = page_layout("cover", layout=layout_contract)
            primary = _hex_rgb(theme_colors["primary"], "#071B2A")
            accent = _hex_rgb(theme_colors["accent"], "#43B5EE")
            for region_name, fill in (
                ("topAccent", accent),
                ("topRule", primary),
                ("leftAccent", accent),
                ("bottomBand", primary),
            ):
                page.draw_rect(
                    fitz.Rect(*rect_tuple(cover_layout[region_name])),
                    color=None,
                    fill=fill,
                )
            _draw_brand_mark(
                fitz,
                page,
                theme,
                root,
                assembly_number,
                fitz.Rect(42, 39, 210, 71),
                fontsize=20,
                inspector_color=primary,
            )
            page.insert_text(
                fitz.Point(194, 59),
                "TECHNICAL PUBLICATIONS",
                fontsize=7.2,
                fontname="helv",
                color=_hex_rgb(theme_colors["muted"], "#596A76"),
            )
            cover_title = _page_element_text(
                descriptor, "header_title", "ILLUSTRATED PARTS MANUAL"
            )
            cover_title_style = _page_element_style(descriptor, "header_title")
            page.insert_text(
                fitz.Point(42, 99),
                cover_title,
                fontsize=float(cover_title_style.get("fontSize") or 25),
                fontname=_pdf_font(
                    cover_title_style.get("fontFamily") or theme_typography["headingFont"],
                    cover_title_style.get("fontWeight") or theme_typography["headingWeight"],
                    cover_title_style.get("fontStyle"),
                ),
                color=_hex_rgb(cover_title_style.get("color"), theme_colors["accent"]),
            )
            product = descriptor.get("product") or {}
            cover_subtitle = _page_element_text(
                descriptor,
                "cover_subtitle",
                product.get("name") or document.get("title") or "",
            )
            subtitle_style = _page_element_style(descriptor, "cover_subtitle")
            page.insert_textbox(
                fitz.Rect(42, 116, width - 42, 145),
                cover_subtitle,
                fontsize=float(subtitle_style.get("fontSize") or 14),
                fontname=_pdf_font(
                    subtitle_style.get("fontFamily") or theme_typography["bodyFont"],
                    subtitle_style.get("fontWeight") or theme_typography["bodyWeight"],
                    subtitle_style.get("fontStyle"),
                ),
                color=_hex_rgb(subtitle_style.get("color"), theme_colors["text"]),
            )
            image = descriptor["renderRequest"]["image"]
            _draw_image(
                fitz,
                page,
                render_paths[str(descriptor["pageId"])],
                _page_element_rect(
                    fitz,
                    page,
                    descriptor,
                    cover_layout["illustration"],
                    "illustration",
                ),
                image,
                framed=bool(cover_layout.get("illustrationFramed", False)),
            )
            control = descriptor.get("documentControl") or {}
            metadata = [
                f"Assembly Number: {product.get('assemblyNumber') or 'Not specified'}",
                f"Document Number: {control.get('documentNumber')}",
            ]
            if control.get("revision"):
                metadata.append(f"Revision: {control.get('revision')}")
            if control.get("releaseDate"):
                metadata.append(f"Release Date: {control.get('releaseDate')}")
            page.insert_textbox(
                fitz.Rect(*rect_tuple(cover_layout["documentControl"])),
                "\n".join(metadata),
                fontsize=9.2,
                fontname="helv",
                color=(0.18, 0.23, 0.27),
                align=fitz.TEXT_ALIGN_CENTER,
            )
            footer_left = fitz.Rect(*rect_tuple(cover_layout["footerLeft"]))
            footer_right = fitz.Rect(*rect_tuple(cover_layout["footerRight"]))
            page.insert_textbox(
                footer_left,
                str(product.get("name") or "Product"),
                fontsize=7.4,
                fontname="helv",
                color=(1, 1, 1),
            )
            footer_identity = str(control.get("documentNumber") or "Document number not specified")
            if control.get("revision"):
                footer_identity += f" | Rev {control.get('revision')}"
            page.insert_textbox(
                footer_right,
                footer_identity,
                fontsize=7.4,
                fontname="helv",
                color=(1, 1, 1),
                align=fitz.TEXT_ALIGN_RIGHT,
            )
        elif page_type == "document_information":
            _draw_header(fitz, page, descriptor, document, root, assembly_number)
            page.insert_textbox(fitz.Rect(48, 70, width - 48, 98), "DOCUMENT CONTROL", fontsize=18, fontname="hebo", color=(0.05, 0.27, 0.44))
            control = descriptor.get("documentControl") or {}
            _draw_key_value_table(
                fitz,
                page,
                [
                    ("Document title", control.get("documentTitle")),
                    ("Product", control.get("product")),
                    ("Model", control.get("model")),
                    ("Assembly number", control.get("assemblyNumber")),
                    ("Document number", control.get("documentNumber")),
                    ("Revision", control.get("revision")),
                    ("Release date", control.get("releaseDate")),
                ],
                fitz.Rect(48, 112, width - 48, 322),
            )
            page.insert_textbox(fitz.Rect(48, 358, width - 48, 382), "REVISION HISTORY", fontsize=12, fontname="hebo", color=(0.05, 0.27, 0.44))
            for index, row in enumerate(descriptor.get("revisionHistory") or []):
                y = 394 + index * 32
                text = f"Rev {row.get('revision')} | {row.get('date') or 'Date not specified'} | {row.get('description')}"
                page.insert_textbox(fitz.Rect(56, y, width - 56, y + 24), text, fontsize=8.5, fontname="helv", color=(0.16, 0.21, 0.25))
            _draw_footer(fitz, page, document, descriptor)
        elif page_type == "table_of_contents":
            _draw_header(fitz, page, descriptor, document, root, assembly_number)
            page.insert_textbox(fitz.Rect(48, 66, width - 48, 96), "TABLE OF CONTENTS", fontsize=18, fontname="hebo", color=(0.05, 0.27, 0.44))
            page.insert_textbox(fitz.Rect(58, 102, 145, 119), "FIGURE", fontsize=7, fontname="hebo", color=(0.25, 0.36, 0.43))
            page.insert_textbox(fitz.Rect(150, 102, width - 90, 119), "TITLE", fontsize=7, fontname="hebo", color=(0.25, 0.36, 0.43))
            page.insert_textbox(fitz.Rect(width - 88, 102, width - 58, 119), "PAGE", fontsize=7, fontname="hebo", color=(0.25, 0.36, 0.43), align=fitz.TEXT_ALIGN_RIGHT)
            y = 124.0
            for entry in descriptor.get("entries") or []:
                row_rect = fitz.Rect(58, y, width - 58, y + 27)
                figure = str(entry.get("figureNumber") or "INDEX")
                page.insert_textbox(fitz.Rect(row_rect.x0, row_rect.y0 + 6, 142, row_rect.y1), figure, fontsize=8.5, fontname="hebo", color=(0.05, 0.43, 0.70))
                page.insert_textbox(fitz.Rect(150, row_rect.y0 + 6, row_rect.x1 - 42, row_rect.y1), str(entry.get("title") or ""), fontsize=9, fontname="helv", color=(0.12, 0.17, 0.21))
                page.draw_line(fitz.Point(150, row_rect.y1 - 3), fitz.Point(row_rect.x1, row_rect.y1 - 3), color=(0.82, 0.85, 0.87), dashes="1 3", width=0.4)
                page.insert_textbox(fitz.Rect(row_rect.x1 - 38, row_rect.y0 + 6, row_rect.x1, row_rect.y1), str(entry.get("pageNumber") or ""), fontsize=9, fontname="hebo", color=(0.05, 0.43, 0.70), align=fitz.TEXT_ALIGN_RIGHT)
                pending_links.append((page_number - 1, (row_rect.x0, row_rect.y0, row_rect.x1, row_rect.y1), int(entry.get("pageNumber") or 1) - 1))
                y += 29
            _draw_footer(fitz, page, document, descriptor)
        elif page_type == "assembly_overview":
            _draw_header(fitz, page, descriptor, document, root, assembly_number)
            overview_layout = page_layout("assembly_overview", layout=layout_contract)
            image = descriptor["renderRequest"]["image"]
            image_rect = _draw_image(
                fitz,
                page,
                render_paths[str(descriptor["pageId"])],
                _page_element_rect(
                    fitz,
                    page,
                    descriptor,
                    overview_layout["illustration"],
                    "illustration",
                ),
                image,
            )
            _draw_balloons(fitz, page, image_rect, image, theme)
            group_index = _page_element_rect(
                fitz,
                page,
                descriptor,
                overview_layout["groupIndex"],
                "group_index",
            )
            page.insert_textbox(fitz.Rect(group_index.x0, group_index.y0, group_index.x1, group_index.y0 + 22), "ILLUSTRATED GROUP INDEX", fontsize=9.2, fontname="hebo", color=(0.05, 0.33, 0.53))
            y = group_index.y0 + 30
            for group in descriptor.get("manualGroupItems") or []:
                row_rect = fitz.Rect(group_index.x0, y, group_index.x1, y + 42)
                page.draw_circle(fitz.Point(605, y + 14), 9, color=(0.04, 0.35, 0.57), fill=(1, 1, 1), width=1)
                group_label = str(group.get("itemNumber") or "")
                group_label_width = fitz.get_text_length(group_label, fontname="hebo", fontsize=7.5)
                page.insert_text(fitz.Point(605 - group_label_width * 0.5, y + 16.6), group_label, fontsize=7.5, fontname="hebo", color=(0.03, 0.20, 0.31))
                _fit_text(fitz, page, fitz.Rect(620, y + 4, row_rect.x1, y + 20), group.get("name"), fontsize=7.8, fontname="hebo")
                page.insert_textbox(fitz.Rect(620, y + 22, row_rect.x1, y + 37), f"Figure {group.get('figureNumber')} | Page {group.get('pageNumber')}", fontsize=6.8, fontname="helv", color=(0.35, 0.42, 0.47))
                pending_links.append((page_number - 1, (row_rect.x0, row_rect.y0, row_rect.x1, row_rect.y1), int(group.get("pageNumber") or 1) - 1))
                y += 46
            _draw_footer(fitz, page, document, descriptor)
        elif page_type == "manual_section":
            _draw_header(fitz, page, descriptor, document, root, assembly_number)
            image = descriptor["renderRequest"]["image"]
            rows = descriptor.get("bom") or []
            section_layout = page_layout(
                "manual_section",
                layout_mode=str(descriptor.get("pageLayout") or ""),
                layout=layout_contract,
            )
            image_box = _page_element_rect(
                fitz,
                page,
                descriptor,
                section_layout["illustration"],
                "illustration",
            )
            bom_box = _page_element_rect(
                fitz,
                page,
                descriptor,
                section_layout["bom"],
                "bom",
            )
            image_rect = _draw_image(fitz, page, render_paths[str(descriptor["pageId"])], image_box, image)
            _draw_balloons(fitz, page, image_rect, image, theme)
            _draw_bom_table(fitz, page, bom_box, rows, theme)
            _draw_footer(fitz, page, document, descriptor)
        elif page_type == "manual_section_parts_list":
            _draw_header(fitz, page, descriptor, document, root, assembly_number)
            parts_layout = page_layout("manual_section_parts_list", layout=layout_contract)
            _draw_bom_table(
                fitz,
                page,
                _publication_rect(fitz, parts_layout["bom"]),
                descriptor.get("bom") or [],
                theme,
            )
            _draw_footer(fitz, page, document, descriptor)
        elif page_type == "parts_index":
            _draw_header(fitz, page, descriptor, document, root, assembly_number)
            page.insert_textbox(fitz.Rect(48, 66, width - 48, 96), "PART NUMBER INDEX", fontsize=18, fontname="hebo", color=(0.05, 0.27, 0.44))
            y = 106.0
            for row_index, row in enumerate(descriptor.get("entries") or []):
                refs = ", ".join(
                    f"Figure {ref.get('figureNumber')}, Item {ref.get('itemNumber')}"
                    for ref in row.get("references") or []
                )
                fill = (0.95, 0.97, 0.985) if row_index % 2 else (1, 1, 1)
                page.draw_rect(fitz.Rect(48, y, width - 48, y + 21), color=(0.82, 0.85, 0.87), fill=fill, width=0.35)
                _fit_text(fitz, page, fitz.Rect(56, y + 5, 190, y + 18), row.get("partNumber"), fontsize=7.2, fontname="hebo")
                _fit_text(fitz, page, fitz.Rect(198, y + 5, 475, y + 18), row.get("description"), fontsize=7.1)
                _fit_text(fitz, page, fitz.Rect(485, y + 5, width - 56, y + 18), refs, fontsize=6.9, color=(0.05, 0.39, 0.63), align=fitz.TEXT_ALIGN_RIGHT)
                first_ref = next(iter(row.get("references") or []), None)
                if first_ref:
                    pending_links.append((page_number - 1, (48, y, width - 48, y + 21), int(first_ref.get("pageNumber") or 1) - 1))
                y += 22
            _draw_footer(fitz, page, document, descriptor)
        else:
            pdf.close()
            raise PartsManualPdfError(f"unsupported manual page type: {page_type}")

        _draw_documentation_objects(
            fitz,
            page,
            descriptor,
            document,
            root,
            assembly_number,
        )

    for source_page, rectangle, target_page in pending_links:
        pdf[source_page].insert_link(
            {"kind": fitz.LINK_GOTO, "from": fitz.Rect(*rectangle), "page": target_page}
        )

    toc = [[1, str(document.get("title") or "Illustrated Parts Manual"), 1]]
    for descriptor in pages:
        page_type = descriptor.get("pageType")
        if page_type == "table_of_contents":
            toc.append([1, "Table of Contents", int(descriptor["pageNumber"])])
        elif page_type in {"assembly_overview", "manual_section", "parts_index"}:
            label = str(descriptor.get("title") or "Manual Section")
            if descriptor.get("figureNumber"):
                label = f"Figure {descriptor['figureNumber']} - {label}"
            toc.append([1, label, int(descriptor["pageNumber"])])
    pdf.set_toc(toc)
    pdf.set_metadata(
        {
            "title": str(document.get("title") or "Illustrated Parts Manual"),
            "author": "InspectorPro",
            "subject": f"Illustrated parts manual for {assembly_number}",
            "keywords": "illustrated parts manual, BOM, exploded view, parts index",
        }
    )
    payload = pdf.tobytes(garbage=4, deflate=True)
    pdf.close()
    return payload


def store_manual_pdf(
    root: str | Path,
    assembly_number: str,
    document: Mapping[str, Any],
) -> Dict[str, Any]:
    payload = build_manual_pdf_bytes(root, assembly_number, document)
    document_revision = str(document.get("documentRevision") or "")
    pdf_path, metadata_path = _pdf_paths(root, assembly_number, document_revision)
    descriptor: Dict[str, Any] = {
        "status": "ready",
        "qualityStatus": "PASS",
        "mimeType": "application/pdf",
        "documentRevision": document_revision,
        "manualPlanRevision": str(document.get("manualPlanRevision") or ""),
        "sourceRevision": str(document.get("sourceRevision") or ""),
        "pageCount": int(document.get("pageCount") or 0),
        "byteLength": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "generatedAt": _utc_now(),
    }
    _write_atomic(pdf_path, payload)
    _write_atomic(
        metadata_path,
        (json.dumps(descriptor, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("ascii"),
    )
    descriptor["url"] = (
        f"/api/parts-manual/{assembly_number}/documents/{document_revision}/pdf"
    )
    return descriptor


def manual_pdf_path(root: str | Path, assembly_number: str, document_revision: str) -> Path:
    pdf_path, metadata_path = _pdf_paths(root, assembly_number, document_revision)
    if not os.path.isfile(_native_path(pdf_path)) or not os.path.isfile(_native_path(metadata_path)):
        raise PartsManualPdfError("parts manual PDF not found")
    return Path(_native_path(pdf_path))
