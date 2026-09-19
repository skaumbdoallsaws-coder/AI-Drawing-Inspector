"""Persistent presentation overrides for CAD-grounded manual pages.

The manual plan owns product semantics.  This module owns only how those
semantics are composed for publication: group and occurrence translations,
figure placement, callout composition, and a replayable command history shared
by people and Sage.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time
from typing import Any, Dict, Iterable, Mapping, Optional


DOCUMENTATION_SCENE_SCHEMA_VERSION = 2
DOCUMENTATION_TARGET_TYPES = frozenset(
    {
        "manual_group",
        "occurrence",
        "figure",
        "balloon",
        "leader",
        "page_element",
        "document_object",
        "document_theme",
        "selection",
    }
)
DOCUMENTATION_COMMAND_OPERATIONS = frozenset(
    {
        "translate",
        "rotate",
        "resize",
        "arrange",
        "adjust_explode",
        "set_view",
        "set_anchor",
        "set_leader_style",
        "auto_route",
        "set_end_condition",
        "set_repeated_strategy",
        "clear_callouts",
        "add_callout",
        "remove_callout",
        "restore_callouts",
        "add_object",
        "remove_object",
        "update_text",
        "update_style",
        "set_theme",
        "apply_template",
        "reset",
        "reset_page",
    }
)
DOCUMENTATION_COMMAND_ACTORS = frozenset({"user", "sage", "system"})
DOCUMENTATION_ANCHOR_SIDES = frozenset({"center", "left", "right", "top", "bottom"})
DOCUMENTATION_LEADER_STYLES = frozenset({"auto", "straight", "orthogonal"})
DOCUMENTATION_LEADER_END_CONDITIONS = frozenset({"arrow", "dot", "none"})
# Newly authored parts-manual callouts inherit the generated default. Mirrors
# ai_inspector.parts_manual.version.PARTS_MANUAL_DEFAULT_END_CONDITION; an
# arrowhead stays reachable per leader through set_end_condition.
DOCUMENTATION_DEFAULT_END_CONDITION = "dot"
# Repeated-part callout strategies a user may request explicitly. Automatic
# generation always uses DOCUMENTATION_DEFAULT_REPEATED_PART_STRATEGY; a
# "branched" layout is only ever produced when a user asks for it here.
DOCUMENTATION_DEFAULT_REPEATED_PART_STRATEGY = "representative_with_count"
DOCUMENTATION_REPEATED_PART_STRATEGIES = frozenset(
    {"representative_with_count", "branched"}
)
DOCUMENTATION_ARRANGEMENTS = frozenset(
    {
        "align_left",
        "align_center",
        "align_right",
        "align_top",
        "align_middle",
        "align_bottom",
        "distribute_horizontal",
        "distribute_vertical",
        "move_selection",
    }
)
DOCUMENTATION_CAMERA_PRESETS = frozenset({"isometric", "front", "top", "right"})

_ASSEMBLY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")
_PAGE_ID_RE = re.compile(r"^page-[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_DOCUMENT_OBJECT_ID_RE = re.compile(
    r"^document-object-[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"
)
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_WRITE_LOCK = threading.RLock()
_MAX_COMMANDS = 2000
_MAX_CALLOUT_ITEMS = 256
_MAX_TRANSLATION_COMPONENT = 10000.0
_MAX_ARRANGE_TARGETS = 64
_MAX_ROTATION_COMPONENT = 180.0
_MAX_SIZE_COMPONENT = 1.0
_MAX_EXPLODE_DELTA = 1.0
_MIN_EXPLODE_SCALE = 0.4
_MAX_EXPLODE_SCALE = 2.5
_MAX_DOCUMENT_TEXT = 4000
_MAX_OBJECT_NAME = 120
_MAX_TEMPLATE_NAME = 120
_DOCUMENT_OBJECT_TYPES = frozenset({"text", "image", "shape"})
_DOCUMENT_SHAPE_TYPES = frozenset(
    {"rectangle", "ellipse", "arrow", "revision_cloud", "detail_box"}
)
_DOCUMENT_TEXT_ALIGNS = frozenset({"left", "center", "right"})
_DOCUMENT_FONT_FAMILIES = frozenset(
    {
        "Arial",
        "Helvetica",
        "Inter",
        "Georgia",
        "Times New Roman",
        "Courier New",
    }
)

DEFAULT_DOCUMENT_THEME: Dict[str, Any] = {
    "themeId": "inspectorpro-technical",
    "name": "InspectorPro Technical",
    "version": 1,
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

DEFAULT_PAGE_MASTERS: Dict[str, Any] = {
    "cover": {
        "masterId": "cover",
        "name": "Branded Cover",
        "pageTypes": ["cover"],
        "showHeader": True,
        "showFooter": False,
    },
    "technical": {
        "masterId": "technical",
        "name": "Technical Figure",
        "pageTypes": ["assembly_overview", "manual_section"],
        "showHeader": True,
        "showFooter": True,
    },
    "reference": {
        "masterId": "reference",
        "name": "Reference Page",
        "pageTypes": [
            "document_information",
            "table_of_contents",
            "manual_section_parts_list",
            "parts_index",
        ],
        "showHeader": True,
        "showFooter": True,
    },
}


class DocumentationSceneError(RuntimeError):
    pass


class DocumentationSceneNotFoundError(DocumentationSceneError):
    pass


class DocumentationSceneConflictError(DocumentationSceneError):
    def __init__(self, current_revision: str):
        self.current_revision = current_revision
        super().__init__("documentation scene revision conflict")


class DocumentationSceneBindingError(DocumentationSceneError):
    def __init__(
        self,
        *,
        scene_source_revision: str,
        current_source_revision: str,
        scene_manual_plan_revision: str,
        current_manual_plan_revision: str,
    ):
        self.scene_source_revision = scene_source_revision
        self.current_source_revision = current_source_revision
        self.scene_manual_plan_revision = scene_manual_plan_revision
        self.current_manual_plan_revision = current_manual_plan_revision
        super().__init__("documentation scene is bound to an older source or manual plan")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def canonical_documentation_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            indent=2,
            separators=(",", ": "),
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def documentation_scene_revision(value: Any) -> str:
    return hashlib.sha256(canonical_documentation_bytes(value)).hexdigest()


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Optional[Path] = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".tmp-documentation-",
            suffix=path.suffix,
            dir=str(path.parent),
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(6):
            try:
                os.replace(temporary_path, path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.03 * (2**attempt))
        temporary_path = None
    except OSError as exc:
        raise DocumentationSceneError(
            f"failed to write documentation scene: {exc}"
        ) from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _vector(value: Any, *, required: bool = True) -> list[float]:
    if value is None and not required:
        return [0.0, 0.0, 0.0]
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise DocumentationSceneError("translation must contain exactly three values")
    result = []
    for component in value:
        if isinstance(component, bool):
            raise DocumentationSceneError("translation values must be finite numbers")
        try:
            number = float(component)
        except (TypeError, ValueError) as exc:
            raise DocumentationSceneError(
                "translation values must be finite numbers"
            ) from exc
        if not math.isfinite(number) or abs(number) > _MAX_TRANSLATION_COMPONENT:
            raise DocumentationSceneError(
                "translation values must be finite and within the documentation workspace"
            )
        result.append(0.0 if abs(number) < 1e-12 else number)
    return result


def _annotation_vector(value: Any) -> list[float]:
    result = _vector(value)
    if abs(result[2]) > 1e-12 or abs(result[0]) > 2.0 or abs(result[1]) > 2.0:
        raise DocumentationSceneError(
            "annotation translation must be a normalized two-dimensional offset"
        )
    return result


def _anchor_point(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise DocumentationSceneError("leader anchor point must contain x and y")
    result: list[float] = []
    for component in value:
        if isinstance(component, bool):
            raise DocumentationSceneError("leader anchor point must be normalized")
        try:
            number = float(component)
        except (TypeError, ValueError) as exc:
            raise DocumentationSceneError("leader anchor point must be normalized") from exc
        if not math.isfinite(number) or not 0.0 <= number <= 1.0:
            raise DocumentationSceneError("leader anchor point must be normalized")
        result.append(number)
    return result


def _rotation_vector(value: Any) -> list[float]:
    result = _vector(value)
    if any(abs(component) > _MAX_ROTATION_COMPONENT for component in result):
        raise DocumentationSceneError(
            "rotation values must be between -180 and 180 degrees"
        )
    return result


def _size_vector(value: Any) -> list[float]:
    result = _vector(value)
    if abs(result[2]) > 1e-12 or any(
        abs(component) > _MAX_SIZE_COMPONENT for component in result[:2]
    ):
        raise DocumentationSceneError(
            "size delta must be a normalized two-dimensional value"
        )
    return result


def _bounded_size_vector(value: Iterable[float]) -> list[float]:
    return [
        max(-_MAX_SIZE_COMPONENT, min(_MAX_SIZE_COMPONENT, float(component)))
        for component in value
    ]


def _explode_delta(value: Any) -> float:
    if isinstance(value, bool):
        raise DocumentationSceneError("explode delta must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise DocumentationSceneError("explode delta must be a finite number") from exc
    if not math.isfinite(result) or abs(result) > _MAX_EXPLODE_DELTA:
        raise DocumentationSceneError("explode delta must be between -1 and 1")
    return result


def _normalized_rotation(value: Iterable[float]) -> list[float]:
    result = []
    for component in value:
        normalized = (float(component) + 180.0) % 360.0 - 180.0
        result.append(0.0 if abs(normalized) < 1e-12 else normalized)
    return result


def _add_vectors(left: Iterable[float], right: Iterable[float]) -> list[float]:
    return [
        float(left_value) + float(right_value)
        for left_value, right_value in zip(left, right)
    ]


def _is_zero_vector(value: Iterable[float]) -> bool:
    return all(abs(float(component)) < 1e-12 for component in value)


def _bounded_number(
    value: Any,
    *,
    field: str,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool):
        raise DocumentationSceneError(f"{field} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise DocumentationSceneError(f"{field} must be a finite number") from exc
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise DocumentationSceneError(
            f"{field} must be between {minimum:g} and {maximum:g}"
        )
    return result


def _color(value: Any, *, field: str) -> str:
    result = str(value or "").strip().upper()
    if _HEX_COLOR_RE.fullmatch(result) is None:
        raise DocumentationSceneError(f"{field} must be a six-digit hex color")
    return result


def _document_style(value: Any, *, allow_empty: bool = True) -> Dict[str, Any]:
    if value is None and allow_empty:
        return {}
    if not isinstance(value, Mapping):
        raise DocumentationSceneError("documentation style must be an object")
    allowed = {
        "fontFamily",
        "fontSize",
        "fontWeight",
        "fontStyle",
        "textDecoration",
        "textAlign",
        "color",
        "fill",
        "outlineColor",
        "lineWidth",
        "opacity",
    }
    unknown = set(value) - allowed
    if unknown:
        raise DocumentationSceneError(
            "unsupported documentation style field: " + sorted(unknown)[0]
        )
    result: Dict[str, Any] = {}
    if "fontFamily" in value:
        font = str(value.get("fontFamily") or "").strip()
        if font not in _DOCUMENT_FONT_FAMILIES:
            raise DocumentationSceneError("unsupported documentation font family")
        result["fontFamily"] = font
    if "fontSize" in value:
        result["fontSize"] = _bounded_number(
            value.get("fontSize"), field="font size", minimum=4, maximum=144
        )
    if "fontWeight" in value:
        weight = int(
            _bounded_number(
                value.get("fontWeight"), field="font weight", minimum=100, maximum=900
            )
        )
        if weight % 100:
            raise DocumentationSceneError("font weight must use 100-point increments")
        result["fontWeight"] = weight
    if "fontStyle" in value:
        font_style = str(value.get("fontStyle") or "")
        if font_style not in {"normal", "italic"}:
            raise DocumentationSceneError("unsupported font style")
        result["fontStyle"] = font_style
    if "textDecoration" in value:
        decoration = str(value.get("textDecoration") or "")
        if decoration not in {"none", "underline"}:
            raise DocumentationSceneError("unsupported text decoration")
        result["textDecoration"] = decoration
    if "textAlign" in value:
        alignment = str(value.get("textAlign") or "")
        if alignment not in _DOCUMENT_TEXT_ALIGNS:
            raise DocumentationSceneError("unsupported text alignment")
        result["textAlign"] = alignment
    for field in ("color", "fill", "outlineColor"):
        if field in value:
            result[field] = _color(value.get(field), field=field)
    if "lineWidth" in value:
        result["lineWidth"] = _bounded_number(
            value.get("lineWidth"), field="line width", minimum=0, maximum=24
        )
    if "opacity" in value:
        result["opacity"] = _bounded_number(
            value.get("opacity"), field="opacity", minimum=0, maximum=1
        )
    return result


def _document_frame(value: Any) -> Dict[str, float]:
    if not isinstance(value, Mapping):
        raise DocumentationSceneError("documentation object frame must be an object")
    return {
        "x": _bounded_number(value.get("x"), field="object x", minimum=-1, maximum=2),
        "y": _bounded_number(value.get("y"), field="object y", minimum=-1, maximum=2),
        "width": _bounded_number(
            value.get("width"), field="object width", minimum=0.01, maximum=2
        ),
        "height": _bounded_number(
            value.get("height"), field="object height", minimum=0.01, maximum=2
        ),
        "rotation": _bounded_number(
            value.get("rotation", 0), field="object rotation", minimum=-180, maximum=180
        ),
    }


def _document_asset(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DocumentationSceneError("image object requires a managed asset")
    asset_id = str(value.get("assetId") or "").strip().lower()
    mime_type = str(value.get("mimeType") or "").strip().lower()
    url = str(value.get("url") or "").strip()
    filename = str(value.get("filename") or "").strip()
    if re.fullmatch(r"[0-9a-f]{64}", asset_id) is None:
        raise DocumentationSceneError("documentation asset ID is invalid")
    if mime_type not in {"image/png", "image/jpeg"}:
        raise DocumentationSceneError("documentation asset must be PNG or JPEG")
    if not url.startswith("/api/parts-manual/") or "/documentation-assets/" not in url:
        raise DocumentationSceneError("documentation asset URL is not managed")
    if not filename or len(filename) > 255:
        raise DocumentationSceneError("documentation asset filename is invalid")
    return {
        "assetId": asset_id,
        "mimeType": mime_type,
        "url": url,
        "filename": filename,
    }


def _document_object(value: Any, *, expected_id: Optional[str] = None) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DocumentationSceneError("documentation object must be an object")
    object_id = str(value.get("objectId") or expected_id or "").strip()
    if _DOCUMENT_OBJECT_ID_RE.fullmatch(object_id) is None:
        raise DocumentationSceneError("documentation object ID is invalid")
    if expected_id is not None and object_id != expected_id:
        raise DocumentationSceneError("documentation object ID does not match its target")
    object_type = str(value.get("type") or "").strip()
    if object_type not in _DOCUMENT_OBJECT_TYPES:
        raise DocumentationSceneError("unsupported documentation object type")
    name = str(value.get("name") or "").strip()
    if not name or len(name) > _MAX_OBJECT_NAME:
        raise DocumentationSceneError("documentation object name is invalid")
    style_ref = str(value.get("styleRef") or "body").strip()
    if style_ref not in {"title", "heading", "body", "caption", "accent"}:
        raise DocumentationSceneError("unsupported documentation style reference")
    result: Dict[str, Any] = {
        "objectId": object_id,
        "type": object_type,
        "name": name,
        "frame": _document_frame(value.get("frame")),
        "styleRef": style_ref,
        "styleOverrides": _document_style(value.get("styleOverrides")),
        "locked": bool(value.get("locked", False)),
        "source": str(value.get("source") or "user"),
    }
    if result["source"] not in {"user", "template", "sage"}:
        raise DocumentationSceneError("unsupported documentation object source")
    if object_type == "text":
        content = str(value.get("content") or "")
        if len(content) > _MAX_DOCUMENT_TEXT:
            raise DocumentationSceneError("documentation text is too long")
        result["content"] = content
    elif object_type == "image":
        result["asset"] = _document_asset(value.get("asset"))
        result["contentMode"] = str(value.get("contentMode") or "contain")
        if result["contentMode"] not in {"contain", "cover"}:
            raise DocumentationSceneError("unsupported image content mode")
        result["altText"] = str(value.get("altText") or "")[:512]
    else:
        shape_type = str(value.get("shapeType") or "rectangle")
        if shape_type not in _DOCUMENT_SHAPE_TYPES:
            raise DocumentationSceneError("unsupported documentation shape")
        result["shapeType"] = shape_type
    return result


def _document_theme(value: Any, *, merge_default: bool = True) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DocumentationSceneError("documentation theme must be an object")
    base = copy.deepcopy(DEFAULT_DOCUMENT_THEME) if merge_default else {}
    theme_id = str(value.get("themeId") or base.get("themeId") or "").strip()
    name = str(value.get("name") or base.get("name") or "").strip()
    company = str(value.get("companyName") or base.get("companyName") or "").strip()
    if not theme_id or len(theme_id) > _MAX_TEMPLATE_NAME or not name or len(name) > _MAX_TEMPLATE_NAME:
        raise DocumentationSceneError("documentation theme identity is invalid")
    if not company or len(company) > _MAX_TEMPLATE_NAME:
        raise DocumentationSceneError("documentation company name is invalid")
    result = base
    result.update(
        {
            "themeId": theme_id,
            "name": name,
            "companyName": company,
            "version": int(
                _bounded_number(
                    value.get("version", base.get("version", 1)),
                    field="theme version",
                    minimum=1,
                    maximum=1000000,
                )
            ),
        }
    )
    colors = dict(result.get("colors") or {})
    if isinstance(value.get("colors"), Mapping):
        colors.update(value.get("colors") or {})
    required_colors = set(DEFAULT_DOCUMENT_THEME["colors"])
    if set(colors) != required_colors:
        raise DocumentationSceneError("documentation theme colors are incomplete")
    result["colors"] = {
        field: _color(colors[field], field=f"theme {field}")
        for field in sorted(required_colors)
    }
    typography = dict(result.get("typography") or {})
    if isinstance(value.get("typography"), Mapping):
        typography.update(value.get("typography") or {})
    heading_font = str(typography.get("headingFont") or "")
    body_font = str(typography.get("bodyFont") or "")
    if heading_font not in _DOCUMENT_FONT_FAMILIES or body_font not in _DOCUMENT_FONT_FAMILIES:
        raise DocumentationSceneError("documentation theme uses an unsupported font")
    result["typography"] = {
        "headingFont": heading_font,
        "bodyFont": body_font,
        "headingWeight": int(
            _bounded_number(
                typography.get("headingWeight"), field="heading weight", minimum=100, maximum=900
            )
        ),
        "bodyWeight": int(
            _bounded_number(
                typography.get("bodyWeight"), field="body weight", minimum=100, maximum=900
            )
        ),
    }
    table = dict(result.get("table") or {})
    if isinstance(value.get("table"), Mapping):
        table.update(value.get("table") or {})
    result["table"] = {
        field: _color(table.get(field), field=f"table {field}")
        for field in DEFAULT_DOCUMENT_THEME["table"]
    }
    annotation = dict(result.get("annotation") or {})
    if isinstance(value.get("annotation"), Mapping):
        annotation.update(value.get("annotation") or {})
    result["annotation"] = {
        field: _color(annotation.get(field), field=f"annotation {field}")
        for field in DEFAULT_DOCUMENT_THEME["annotation"]
    }
    logo = value.get("logo", result.get("logo"))
    result["logo"] = None if logo is None else _document_asset(logo)
    return result


def _page_masters(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DocumentationSceneError("page masters must be an object")
    result: Dict[str, Any] = {}
    for key, source in value.items():
        master_id = str(key or "").strip()
        if not master_id or len(master_id) > 80 or not isinstance(source, Mapping):
            raise DocumentationSceneError("page master is invalid")
        name = str(source.get("name") or "").strip()
        page_types = list(dict.fromkeys(str(row) for row in source.get("pageTypes") or [] if row))
        if not name or len(name) > _MAX_TEMPLATE_NAME or not page_types:
            raise DocumentationSceneError("page master metadata is invalid")
        result[master_id] = {
            "masterId": master_id,
            "name": name,
            "pageTypes": page_types,
            "showHeader": bool(source.get("showHeader", True)),
            "showFooter": bool(source.get("showFooter", True)),
        }
    if not result:
        raise DocumentationSceneError("at least one page master is required")
    return result


def _page_override(scene_pages: Dict[str, Any], page_id: str) -> Dict[str, Any]:
    return scene_pages.setdefault(
        page_id,
        {
            "figureOverride": None,
            "manualGroupOverrides": {},
            "occurrenceOverrides": {},
            "balloonOverrides": {},
            "leaderOverrides": {},
            "documentObjects": {},
        },
    )


def _callout_items(value: Any, *, allow_none: bool = False) -> Optional[list[Dict[str, Any]]]:
    if value is None and allow_none:
        return None
    if not isinstance(value, list) or len(value) > _MAX_CALLOUT_ITEMS:
        raise DocumentationSceneError("manual callout items must be a bounded list")
    normalized: list[Dict[str, Any]] = []
    item_numbers: set[int] = set()
    callout_ids: set[str] = set()
    allowed_text_fields = {
        "definitionId",
        "partNumber",
        "engineeringPartNumber",
        "displayPartNumber",
        "partNumberSource",
        "description",
        "descriptionSource",
        "configuration",
        "sectionId",
        "name",
        "figureNumber",
    }
    for index, source in enumerate(value, start=1):
        if not isinstance(source, Mapping):
            raise DocumentationSceneError("manual callout item must be an object")
        try:
            item_number = int(source.get("itemNumber") or source.get("item") or 0)
            quantity = int(source.get("quantity") or 0)
        except (TypeError, ValueError) as exc:
            raise DocumentationSceneError("manual callout item numbers are invalid") from exc
        callout_id = str(source.get("calloutId") or "").strip()
        occurrence_ids = list(
            dict.fromkeys(str(item) for item in source.get("occurrenceIds") or [] if item)
        )
        if item_number != index or item_number in item_numbers:
            raise DocumentationSceneError(
                "manual callout item numbers must be contiguous and start at one"
            )
        if not callout_id or len(callout_id) > 160 or callout_id in callout_ids:
            raise DocumentationSceneError("manual callout IDs must be unique")
        if quantity < 1 or not occurrence_ids:
            raise DocumentationSceneError(
                "manual callout items require at least one component occurrence"
            )
        anchor_scope = str(source.get("anchorScope") or "component_instance")
        if anchor_scope == "component_instance" and quantity != len(occurrence_ids):
            raise DocumentationSceneError(
                "manual callout quantity must match its component occurrences"
            )
        if anchor_scope not in {"component_instance", "manual_group"}:
            raise DocumentationSceneError("manual callout anchor scope is invalid")
        anchor_preference = str(source.get("anchorPreference") or "bounding_box_center")
        if anchor_preference not in {"bounding_box_center", "visible_edge"}:
            raise DocumentationSceneError("manual callout anchor preference is invalid")
        end_condition = str(
            source.get("endCondition") or DOCUMENTATION_DEFAULT_END_CONDITION
        )
        if end_condition not in DOCUMENTATION_LEADER_END_CONDITIONS:
            raise DocumentationSceneError("manual callout leader end condition is invalid")
        row: Dict[str, Any] = {
            "itemNumber": item_number,
            "item": item_number,
            "calloutId": callout_id,
            "quantity": quantity,
            "occurrenceIds": occurrence_ids,
            "anchorScope": anchor_scope,
            "anchorPreference": anchor_preference,
            "endCondition": end_condition,
        }
        for field in allowed_text_fields:
            if source.get(field) is None:
                continue
            text = str(source.get(field)).strip()
            if len(text) > 512:
                raise DocumentationSceneError("manual callout metadata is too long")
            row[field] = text
        if source.get("pageNumber") is not None:
            try:
                row["pageNumber"] = int(source.get("pageNumber"))
            except (TypeError, ValueError) as exc:
                raise DocumentationSceneError("manual callout page number is invalid") from exc
        item_numbers.add(item_number)
        callout_ids.add(callout_id)
        normalized.append(row)
    return normalized


def _target_collection(page: Dict[str, Any], target_type: str) -> tuple[Dict[str, Any], str]:
    if target_type == "manual_group":
        return page["manualGroupOverrides"], "manualGroupOverrides"
    if target_type == "occurrence":
        return page["occurrenceOverrides"], "occurrenceOverrides"
    if target_type == "balloon":
        return page["balloonOverrides"], "balloonOverrides"
    if target_type == "page_element":
        return page.setdefault("pageElementOverrides", {}), "pageElementOverrides"
    if target_type == "document_object":
        return page.setdefault("documentObjects", {}), "documentObjects"
    raise DocumentationSceneError("figure overrides do not use a target collection")


def _remove_empty_leader_override(page: Dict[str, Any], target_id: str) -> None:
    override = page["leaderOverrides"].get(target_id)
    if isinstance(override, Mapping) and not override:
        page["leaderOverrides"].pop(target_id, None)


def _remove_empty_target_override(
    collection: Dict[str, Any], target_id: str
) -> None:
    override = collection.get(target_id)
    if isinstance(override, Mapping) and not override:
        collection.pop(target_id, None)


def _replay_target_command(
    page: Dict[str, Any],
    *,
    target_type: str,
    target_id: str,
    operation: str,
    command: Mapping[str, Any],
) -> None:
    if target_type == "figure":
        if operation == "reset":
            page["figureOverride"] = None
            return
        current = dict(page.get("figureOverride") or {})
        if operation == "translate":
            translation = _add_vectors(
                current.get("translation") or [0.0, 0.0, 0.0],
                _vector(command.get("translation")),
            )
            if _is_zero_vector(translation):
                current.pop("translation", None)
            else:
                current["translation"] = translation
        elif operation == "rotate":
            rotation = _normalized_rotation(
                _add_vectors(
                    current.get("rotation") or [0.0, 0.0, 0.0],
                    _rotation_vector(command.get("rotation")),
                )
            )
            if _is_zero_vector(rotation):
                current.pop("rotation", None)
            else:
                current["rotation"] = rotation
        elif operation == "set_view":
            current["cameraPreset"] = str(command.get("cameraPreset") or "")
        elif operation == "adjust_explode":
            scale = max(
                _MIN_EXPLODE_SCALE,
                min(
                    _MAX_EXPLODE_SCALE,
                    float(current.get("explodeScale") or 1.0)
                    + _explode_delta(command.get("explodeDelta")),
                ),
            )
            if abs(scale - 1.0) < 1e-12:
                current.pop("explodeScale", None)
            else:
                current["explodeScale"] = scale
        page["figureOverride"] = current or None
        return

    if target_type == "leader":
        if operation == "reset":
            page["leaderOverrides"].pop(target_id, None)
        elif operation == "set_anchor":
            current = dict(page["leaderOverrides"].get(target_id) or {})
            if command.get("anchorPoint") is not None:
                current["anchorPoint"] = _anchor_point(command.get("anchorPoint"))
                current.pop("anchorSide", None)
            else:
                current["anchorSide"] = str(command.get("anchorSide") or "")
                current.pop("anchorPoint", None)
            page["leaderOverrides"][target_id] = current
        elif operation == "set_leader_style":
            current = dict(page["leaderOverrides"].get(target_id) or {})
            leader_style = str(command.get("leaderStyle") or "auto")
            if leader_style == "auto":
                current.pop("leaderStyle", None)
            else:
                current["leaderStyle"] = leader_style
            page["leaderOverrides"][target_id] = current
            _remove_empty_leader_override(page, target_id)
        elif operation == "auto_route":
            current = dict(page["leaderOverrides"].get(target_id) or {})
            for field in (
                "anchorSide", "anchorPoint", "corridorTranslation", "leaderStyle"
            ):
                current.pop(field, None)
            page["leaderOverrides"][target_id] = current
            _remove_empty_leader_override(page, target_id)
        elif operation == "set_end_condition":
            current = dict(page["leaderOverrides"].get(target_id) or {})
            current["endCondition"] = str(
                command.get("endCondition") or DOCUMENTATION_DEFAULT_END_CONDITION
            )
            page["leaderOverrides"][target_id] = current
        elif operation == "set_repeated_strategy":
            current = dict(page["leaderOverrides"].get(target_id) or {})
            strategy = str(
                command.get("repeatedPartStrategy")
                or DOCUMENTATION_DEFAULT_REPEATED_PART_STRATEGY
            )
            # The default needs no stored override; dropping it keeps the
            # override collection a record of real user intent only.
            if strategy == DOCUMENTATION_DEFAULT_REPEATED_PART_STRATEGY:
                current.pop("repeatedPartStrategy", None)
            else:
                current["repeatedPartStrategy"] = strategy
            page["leaderOverrides"][target_id] = current
            _remove_empty_leader_override(page, target_id)
        elif operation == "translate":
            current = dict(page["leaderOverrides"].get(target_id) or {})
            translation = _add_vectors(
                current.get("corridorTranslation") or [0.0, 0.0, 0.0],
                _annotation_vector(command.get("translation")),
            )
            if _is_zero_vector(translation):
                current.pop("corridorTranslation", None)
            else:
                current["corridorTranslation"] = translation
            page["leaderOverrides"][target_id] = current
            _remove_empty_leader_override(page, target_id)
        return

    if target_type == "document_object":
        objects = page.setdefault("documentObjects", {})
        if operation == "remove_object":
            objects.pop(target_id, None)
            return
        current = copy.deepcopy(dict(objects.get(target_id) or {}))
        if not current:
            raise DocumentationSceneError("documentation object does not exist")
        if current.get("locked") and operation not in {"update_text", "update_style"}:
            raise DocumentationSceneError("locked documentation object cannot be transformed")
        if operation == "translate":
            translation = _annotation_vector(command.get("translation"))
            frame = dict(current.get("frame") or {})
            frame["x"] = max(-1.0, min(2.0, float(frame.get("x") or 0) + translation[0]))
            frame["y"] = max(-1.0, min(2.0, float(frame.get("y") or 0) + translation[1]))
            current["frame"] = _document_frame(frame)
        elif operation == "resize":
            size_delta = _size_vector(command.get("sizeDelta"))
            frame = dict(current.get("frame") or {})
            frame["width"] = max(
                0.01, min(2.0, float(frame.get("width") or 0.01) + size_delta[0])
            )
            frame["height"] = max(
                0.01, min(2.0, float(frame.get("height") or 0.01) + size_delta[1])
            )
            current["frame"] = _document_frame(frame)
        elif operation == "rotate":
            rotation = _rotation_vector(command.get("rotation"))
            frame = dict(current.get("frame") or {})
            frame["rotation"] = _normalized_rotation(
                [0.0, 0.0, float(frame.get("rotation") or 0) + rotation[2]]
            )[2]
            current["frame"] = _document_frame(frame)
        elif operation == "update_text":
            if current.get("type") != "text":
                raise DocumentationSceneError("only text objects have editable text")
            current["content"] = str(command.get("text") or "")
        elif operation == "update_style":
            merged_style = dict(current.get("styleOverrides") or {})
            merged_style.update(_document_style(command.get("style"), allow_empty=False))
            current["styleOverrides"] = merged_style
        objects[target_id] = _document_object(current, expected_id=target_id)
        return

    collection, _ = _target_collection(page, target_type)
    if operation == "reset":
        collection.pop(target_id, None)
        return
    current = dict(collection.get(target_id) or {})
    if operation == "translate":
        translation = _add_vectors(
            current.get("translation") or [0.0, 0.0, 0.0],
            (
                _annotation_vector(command.get("translation"))
                if target_type in {"balloon", "page_element"}
                else _vector(command.get("translation"))
            ),
        )
        if _is_zero_vector(translation):
            current.pop("translation", None)
        else:
            current["translation"] = translation
    elif operation == "rotate":
        rotation = _normalized_rotation(
            _add_vectors(
                current.get("rotation") or [0.0, 0.0, 0.0],
                _rotation_vector(command.get("rotation")),
            )
        )
        if _is_zero_vector(rotation):
            current.pop("rotation", None)
        else:
            current["rotation"] = rotation
    elif operation == "resize":
        size_delta = _bounded_size_vector(
            _add_vectors(
                current.get("sizeDelta") or [0.0, 0.0, 0.0],
                _size_vector(command.get("sizeDelta")),
            )
        )
        if _is_zero_vector(size_delta):
            current.pop("sizeDelta", None)
        else:
            current["sizeDelta"] = size_delta
    elif operation == "update_text":
        text = str(command.get("text") or "")
        if len(text) > _MAX_DOCUMENT_TEXT:
            raise DocumentationSceneError("documentation text is too long")
        current["text"] = text
    elif operation == "update_style":
        style = dict(current.get("style") or {})
        style.update(_document_style(command.get("style"), allow_empty=False))
        current["style"] = style
    collection[target_id] = current
    _remove_empty_target_override(collection, target_id)


def replay_documentation_commands(commands: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Build the active page overrides from the command prefix."""
    pages: Dict[str, Any] = {}
    for source_command in commands:
        command = dict(source_command)
        page_id = str(command.get("pageId") or "")
        target_type = str(command.get("targetType") or "")
        target_id = str(command.get("targetId") or "")
        operation = str(command.get("operation") or "")
        page = _page_override(pages, page_id)
        if operation == "reset_page":
            pages.pop(page_id, None)
            _page_override(pages, page_id)
            continue
        if operation == "add_object":
            document_object = _document_object(
                command.get("documentObject"), expected_id=target_id
            )
            objects = page.setdefault("documentObjects", {})
            if target_id in objects:
                raise DocumentationSceneError("documentation object already exists")
            objects[target_id] = document_object
            continue
        if operation in {"set_theme", "apply_template"}:
            continue
        if operation in {
            "clear_callouts",
            "add_callout",
            "remove_callout",
            "restore_callouts",
        }:
            callout_items = _callout_items(
                command.get("calloutItems"),
                allow_none=operation == "restore_callouts",
            )
            page["manualCalloutItems"] = copy.deepcopy(callout_items)
            active_ids = {
                str(row.get("calloutId") or "") for row in callout_items or []
            }
            page["balloonOverrides"] = {
                key: value
                for key, value in page.get("balloonOverrides", {}).items()
                if key in active_ids
            }
            page["leaderOverrides"] = {
                key: value
                for key, value in page.get("leaderOverrides", {}).items()
                if key in active_ids
            }
            continue
        if operation == "arrange":
            for transform in command.get("transforms") or []:
                _replay_target_command(
                    page,
                    target_type=str(transform.get("targetType") or ""),
                    target_id=str(transform.get("targetId") or ""),
                    operation="translate",
                    command=transform,
                )
            continue
        _replay_target_command(
            page,
            target_type=target_type,
            target_id=target_id,
            operation=operation,
            command=command,
        )

    empty_page_ids = []
    for page_id, page in pages.items():
        if (
            page.get("figureOverride") is None
            and not page.get("manualGroupOverrides")
            and not page.get("occurrenceOverrides")
            and not page.get("balloonOverrides")
            and not page.get("leaderOverrides")
            and not page.get("pageElementOverrides")
            and not page.get("documentObjects")
            and page.get("manualCalloutItems") is None
        ):
            empty_page_ids.append(page_id)
    for page_id in empty_page_ids:
        pages.pop(page_id, None)
    return pages


def replay_documentation_theme(
    commands: Iterable[Mapping[str, Any]],
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    theme = copy.deepcopy(DEFAULT_DOCUMENT_THEME)
    page_masters = copy.deepcopy(DEFAULT_PAGE_MASTERS)
    for source_command in commands:
        operation = str(source_command.get("operation") or "")
        if operation == "set_theme":
            patch = source_command.get("theme")
            if not isinstance(patch, Mapping):
                raise DocumentationSceneError("theme command requires a theme")
            merged = copy.deepcopy(theme)
            for key, value in patch.items():
                if key in {"colors", "typography", "table", "annotation"}:
                    nested = dict(merged.get(key) or {})
                    if not isinstance(value, Mapping):
                        raise DocumentationSceneError("theme section must be an object")
                    nested.update(value)
                    merged[key] = nested
                else:
                    merged[key] = copy.deepcopy(value)
            theme = _document_theme(merged)
        elif operation == "apply_template":
            theme = _document_theme(source_command.get("theme"))
            page_masters = _page_masters(source_command.get("pageMasters"))
    return theme, page_masters


def _arrange_transforms(value: Any) -> list[Dict[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= _MAX_ARRANGE_TARGETS:
        raise DocumentationSceneError(
            "arrangement must contain between 1 and 64 target transforms"
        )
    normalized: list[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    allowed_types = {"manual_group", "occurrence", "balloon", "page_element"}
    for row in value:
        if not isinstance(row, Mapping):
            raise DocumentationSceneError("arrangement transform must be an object")
        target_type = str(row.get("targetType") or "")
        target_id = str(row.get("targetId") or "")
        if target_type not in allowed_types or not target_id:
            raise DocumentationSceneError("arrangement target is invalid")
        key = (target_type, target_id)
        if key in seen:
            raise DocumentationSceneError("arrangement target is duplicated")
        seen.add(key)
        translation = (
            _annotation_vector(row.get("translation"))
            if target_type in {"balloon", "page_element"}
            else _vector(row.get("translation"))
        )
        if _is_zero_vector(translation):
            raise DocumentationSceneError("arrangement must move every target")
        normalized.append(
            {
                "targetType": target_type,
                "targetId": target_id,
                "translation": translation,
            }
        )
    return normalized


def _upgrade_documentation_scene(scene: Dict[str, Any]) -> Dict[str, Any]:
    schema_version = scene.get("schemaVersion")
    if schema_version not in {1, DOCUMENTATION_SCENE_SCHEMA_VERSION}:
        raise DocumentationSceneError("unsupported documentation scene schema")
    commands = scene.get("commands")
    if not isinstance(commands, list):
        raise DocumentationSceneError("documentation command history is invalid")
    cursor = scene.get("historyCursor")
    if not isinstance(cursor, int) or isinstance(cursor, bool):
        raise DocumentationSceneError("documentation history cursor is invalid")
    active_commands = commands[:cursor]
    scene["schemaVersion"] = DOCUMENTATION_SCENE_SCHEMA_VERSION
    scene["pages"] = replay_documentation_commands(active_commands)
    theme, page_masters = replay_documentation_theme(active_commands)
    scene["theme"] = theme
    scene["pageMasters"] = page_masters
    return scene


def validate_documentation_scene(scene: Mapping[str, Any]) -> None:
    if not isinstance(scene, Mapping):
        raise DocumentationSceneError("documentation scene must be an object")
    if scene.get("schemaVersion") != DOCUMENTATION_SCENE_SCHEMA_VERSION:
        raise DocumentationSceneError("unsupported documentation scene schema")
    if _ASSEMBLY_RE.fullmatch(str(scene.get("assemblyNumber") or "")) is None:
        raise DocumentationSceneError("documentation scene assembly number is invalid")
    if not str(scene.get("sourceRevision") or ""):
        raise DocumentationSceneError("documentation scene source revision is required")
    if not str(scene.get("manualPlanRevision") or ""):
        raise DocumentationSceneError("documentation scene manual-plan revision is required")
    commands = scene.get("commands")
    if not isinstance(commands, list) or len(commands) > _MAX_COMMANDS:
        raise DocumentationSceneError("documentation command history is invalid")
    cursor = scene.get("historyCursor")
    if not isinstance(cursor, int) or isinstance(cursor, bool) or not 0 <= cursor <= len(commands):
        raise DocumentationSceneError("documentation history cursor is invalid")
    for command in commands:
        if not isinstance(command, Mapping):
            raise DocumentationSceneError("documentation command must be an object")
        if command.get("operation") not in DOCUMENTATION_COMMAND_OPERATIONS:
            raise DocumentationSceneError("unsupported documentation command")
        if command.get("targetType") not in DOCUMENTATION_TARGET_TYPES:
            raise DocumentationSceneError("unsupported documentation target type")
        if command.get("actor") not in DOCUMENTATION_COMMAND_ACTORS:
            raise DocumentationSceneError("unsupported documentation command actor")
        if _PAGE_ID_RE.fullmatch(str(command.get("pageId") or "")) is None:
            raise DocumentationSceneError("documentation page ID is invalid")
        if command.get("targetType") not in {"figure", "selection"} and not str(
            command.get("targetId") or ""
        ):
            raise DocumentationSceneError("documentation command target ID is required")
        if command.get("operation") == "arrange":
            if command.get("targetType") != "selection":
                raise DocumentationSceneError("arrangement requires a target selection")
            if command.get("arrangement") not in DOCUMENTATION_ARRANGEMENTS:
                raise DocumentationSceneError("unsupported documentation arrangement")
            _arrange_transforms(command.get("transforms"))
            continue
        operation = str(command.get("operation") or "")
        target_type = str(command.get("targetType") or "")
        if operation == "add_object":
            if target_type != "document_object":
                raise DocumentationSceneError("object insertion requires a document object")
            _document_object(command.get("documentObject"), expected_id=str(command.get("targetId") or ""))
            continue
        if operation == "set_theme":
            if target_type != "document_theme":
                raise DocumentationSceneError("theme updates require the document theme")
            _document_theme(command.get("theme"))
            continue
        if operation == "apply_template":
            if target_type != "document_theme":
                raise DocumentationSceneError("templates apply to the document theme")
            _document_theme(command.get("theme"))
            _page_masters(command.get("pageMasters"))
            continue
        if command.get("targetType") == "selection":
            raise DocumentationSceneError("selection targets require an arrangement")
        if command.get("operation") == "set_view":
            if command.get("targetType") != "figure":
                raise DocumentationSceneError("only figures have publication views")
            if command.get("cameraPreset") not in DOCUMENTATION_CAMERA_PRESETS:
                raise DocumentationSceneError("unsupported documentation camera preset")
        if command.get("operation") == "adjust_explode":
            if command.get("targetType") != "figure":
                raise DocumentationSceneError("only figures have explosion spacing")
            if abs(_explode_delta(command.get("explodeDelta"))) < 1e-12:
                raise DocumentationSceneError("explode adjustment must change spacing")
        if command.get("operation") == "reset_page" and command.get(
            "targetType"
        ) != "figure":
            raise DocumentationSceneError("page reset requires the figure target")
        if command.get("operation") in {
            "clear_callouts",
            "restore_callouts",
        } and command.get("targetType") != "figure":
            raise DocumentationSceneError(
                "page callout collection commands require the figure target"
            )
        if command.get("operation") == "add_callout" and command.get(
            "targetType"
        ) not in {"occurrence", "manual_group"}:
            raise DocumentationSceneError(
                "adding a callout requires a component or manual group target"
            )
        if command.get("operation") == "remove_callout" and command.get(
            "targetType"
        ) != "balloon":
            raise DocumentationSceneError(
                "removing a callout requires a balloon target"
            )
        if command.get("operation") in {
            "clear_callouts",
            "add_callout",
            "remove_callout",
        }:
            _callout_items(command.get("calloutItems"))
        if command.get("operation") == "restore_callouts":
            if command.get("calloutItems") is not None:
                raise DocumentationSceneError(
                    "restoring generated callouts must clear the manual callout override"
                )
        if command.get("operation") == "translate":
            if command.get("targetType") in {
                "balloon",
                "leader",
                "page_element",
                "document_object",
            }:
                _annotation_vector(command.get("translation"))
            else:
                _vector(command.get("translation"))
        if command.get("operation") == "rotate":
            if command.get("targetType") not in {
                "figure",
                "manual_group",
                "occurrence",
                "document_object",
            }:
                raise DocumentationSceneError(
                    "only CAD presentation targets and document objects can rotate"
                )
            _rotation_vector(command.get("rotation"))
        if command.get("operation") == "resize":
            if command.get("targetType") not in {"page_element", "document_object"}:
                raise DocumentationSceneError("only publication objects can resize")
            _size_vector(command.get("sizeDelta"))
        if command.get("operation") == "remove_object" and command.get(
            "targetType"
        ) != "document_object":
            raise DocumentationSceneError("only document objects can be removed")
        if command.get("operation") == "update_text":
            if command.get("targetType") not in {"page_element", "document_object"}:
                raise DocumentationSceneError("selected target has no editable text")
            if len(str(command.get("text") or "")) > _MAX_DOCUMENT_TEXT:
                raise DocumentationSceneError("documentation text is too long")
        if command.get("operation") == "update_style":
            if command.get("targetType") not in {"page_element", "document_object"}:
                raise DocumentationSceneError("selected target has no editable style")
            _document_style(command.get("style"), allow_empty=False)
        if command.get("operation") == "set_anchor":
            if command.get("targetType") != "leader":
                raise DocumentationSceneError("only leaders have editable anchors")
            anchor_side = command.get("anchorSide")
            anchor_point = command.get("anchorPoint")
            if (anchor_side is None) == (anchor_point is None):
                raise DocumentationSceneError(
                    "leader anchor requires exactly one side or visible point"
                )
            if anchor_side is not None and anchor_side not in DOCUMENTATION_ANCHOR_SIDES:
                raise DocumentationSceneError("unsupported documentation anchor side")
            if anchor_point is not None:
                _anchor_point(anchor_point)
        if command.get("operation") == "set_leader_style":
            if command.get("targetType") != "leader":
                raise DocumentationSceneError("only leaders have editable route styles")
            if command.get("leaderStyle") not in DOCUMENTATION_LEADER_STYLES:
                raise DocumentationSceneError("unsupported documentation leader style")
        if command.get("operation") == "auto_route" and command.get(
            "targetType"
        ) != "leader":
            raise DocumentationSceneError("auto route requires a leader target")
        if command.get("operation") == "set_end_condition":
            if command.get("targetType") != "leader":
                raise DocumentationSceneError(
                    "only leaders have editable end conditions"
                )
            if command.get("endCondition") not in DOCUMENTATION_LEADER_END_CONDITIONS:
                raise DocumentationSceneError(
                    "unsupported documentation leader end condition"
                )
        if command.get("operation") == "set_repeated_strategy":
            if command.get("targetType") != "leader":
                raise DocumentationSceneError(
                    "only leaders have an editable repeated-part strategy"
                )
            if command.get(
                "repeatedPartStrategy"
            ) not in DOCUMENTATION_REPEATED_PART_STRATEGIES:
                raise DocumentationSceneError(
                    "unsupported documentation repeated-part strategy"
                )
        if command.get("targetType") == "leader" and command.get("operation") not in {
            "translate",
            "set_anchor",
            "set_leader_style",
            "auto_route",
            "set_end_condition",
            "set_repeated_strategy",
            "reset",
        }:
            raise DocumentationSceneError("unsupported leader command")
        if command.get("targetType") != "leader" and command.get("operation") == "set_anchor":
            raise DocumentationSceneError("only leaders have editable anchors")
        if command.get("targetType") != "leader" and command.get(
            "operation"
        ) == "set_end_condition":
            raise DocumentationSceneError("only leaders have editable end conditions")
        if command.get("targetType") != "leader" and command.get(
            "operation"
        ) == "set_repeated_strategy":
            raise DocumentationSceneError(
                "only leaders have an editable repeated-part strategy"
            )
    replayed = replay_documentation_commands(commands[:cursor])
    if scene.get("pages") != replayed:
        raise DocumentationSceneError(
            "documentation overrides do not match the active command history"
        )
    replayed_theme, replayed_masters = replay_documentation_theme(commands[:cursor])
    if scene.get("theme") != replayed_theme:
        raise DocumentationSceneError(
            "documentation theme does not match the active command history"
        )
    if scene.get("pageMasters") != replayed_masters:
        raise DocumentationSceneError(
            "page masters do not match the active command history"
        )


class DocumentationSceneRepository:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def _scene_path(self, assembly_number: str) -> Path:
        value = str(assembly_number or "").strip()
        if _ASSEMBLY_RE.fullmatch(value) is None:
            raise DocumentationSceneNotFoundError("unknown assembly")
        directory = (self.root / value.lower()).resolve()
        try:
            directory.relative_to(self.root)
        except ValueError as exc:
            raise DocumentationSceneNotFoundError("unknown assembly") from exc
        return directory / "documentation-scene.json"

    @staticmethod
    def new_scene(
        assembly_number: str,
        source_revision: str,
        manual_plan_revision: str,
    ) -> Dict[str, Any]:
        return {
            "schemaVersion": DOCUMENTATION_SCENE_SCHEMA_VERSION,
            "assemblyNumber": str(assembly_number),
            "sourceRevision": str(source_revision),
            "manualPlanRevision": str(manual_plan_revision),
            "createdAt": None,
            "updatedAt": None,
            "pages": {},
            "theme": copy.deepcopy(DEFAULT_DOCUMENT_THEME),
            "pageMasters": copy.deepcopy(DEFAULT_PAGE_MASTERS),
            "commands": [],
            "historyCursor": 0,
        }

    def read(
        self,
        assembly_number: str,
        source_revision: str,
        manual_plan_revision: str,
    ) -> Dict[str, Any]:
        path = self._scene_path(assembly_number)
        if path.is_file():
            try:
                scene = json.loads(path.read_text("ascii"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise DocumentationSceneError(
                    f"could not read documentation scene: {exc}"
                ) from exc
        else:
            scene = self.new_scene(
                assembly_number,
                source_revision,
                manual_plan_revision,
            )
        scene = _upgrade_documentation_scene(scene)
        validate_documentation_scene(scene)
        source_current = str(scene.get("sourceRevision")) == str(source_revision)
        plan_current = str(scene.get("manualPlanRevision")) == str(manual_plan_revision)
        cursor = int(scene.get("historyCursor") or 0)
        return {
            "scene": copy.deepcopy(scene),
            "revision": documentation_scene_revision(scene),
            "persisted": path.is_file(),
            "sourceCurrent": source_current,
            "manualPlanCurrent": plan_current,
            "canUndo": cursor > 0,
            "canRedo": cursor < len(scene.get("commands") or []),
        }

    def rebaseline(
        self,
        assembly_number: str,
        source_revision: str,
        manual_plan_revision: str,
        *,
        preserve_theme: bool = True,
    ) -> Dict[str, Any]:
        """Replace stale page overrides while retaining reusable brand settings."""
        with _WRITE_LOCK:
            loaded = self.read(
                assembly_number,
                source_revision,
                manual_plan_revision,
            )
            previous = loaded["scene"]
            scene = self.new_scene(
                assembly_number,
                source_revision,
                manual_plan_revision,
            )
            if preserve_theme:
                scene["theme"] = copy.deepcopy(
                    previous.get("theme") or DEFAULT_DOCUMENT_THEME
                )
                scene["pageMasters"] = copy.deepcopy(
                    previous.get("pageMasters") or DEFAULT_PAGE_MASTERS
                )
            now = _utc_now()
            scene["createdAt"] = now
            scene["updatedAt"] = now
            validate_documentation_scene(scene)
            _write_atomic(
                self._scene_path(assembly_number),
                canonical_documentation_bytes(scene),
            )
            return {
                "scene": copy.deepcopy(scene),
                "revision": documentation_scene_revision(scene),
                "persisted": True,
                "sourceCurrent": True,
                "manualPlanCurrent": True,
                "canUndo": False,
                "canRedo": False,
                "rebaselined": True,
                "previousRevision": documentation_scene_revision(previous),
            }

    @staticmethod
    def _assert_revision(scene: Mapping[str, Any], base_revision: str) -> None:
        revision = documentation_scene_revision(scene)
        if str(base_revision or "") != revision:
            raise DocumentationSceneConflictError(revision)

    @staticmethod
    def _assert_binding(
        scene: Mapping[str, Any],
        source_revision: str,
        manual_plan_revision: str,
    ) -> None:
        if (
            str(scene.get("sourceRevision") or "") != str(source_revision)
            or str(scene.get("manualPlanRevision") or "") != str(manual_plan_revision)
        ):
            raise DocumentationSceneBindingError(
                scene_source_revision=str(scene.get("sourceRevision") or ""),
                current_source_revision=str(source_revision),
                scene_manual_plan_revision=str(scene.get("manualPlanRevision") or ""),
                current_manual_plan_revision=str(manual_plan_revision),
            )

    @staticmethod
    def _validate_target(
        *,
        page_id: str,
        target_type: str,
        target_id: str,
        page_targets: Mapping[str, Mapping[str, Iterable[str]]],
    ) -> None:
        page = page_targets.get(page_id)
        if not isinstance(page, Mapping):
            raise DocumentationSceneError("documentation page is not editable")
        known = {str(value) for value in page.get(target_type) or []}
        expected_id = page_id if target_type == "figure" else target_id
        if expected_id not in known:
            raise DocumentationSceneError(
                "documentation target does not belong to the selected page"
            )

    def apply_command(
        self,
        assembly_number: str,
        source_revision: str,
        manual_plan_revision: str,
        *,
        base_revision: str,
        command: Mapping[str, Any],
        page_targets: Mapping[str, Mapping[str, Iterable[str]]],
    ) -> Dict[str, Any]:
        with _WRITE_LOCK:
            loaded = self.read(
                assembly_number,
                source_revision,
                manual_plan_revision,
            )
            scene = loaded["scene"]
            self._assert_revision(scene, base_revision)
            self._assert_binding(scene, source_revision, manual_plan_revision)

            operation = str(command.get("operation") or "")
            target_type = str(command.get("targetType") or "")
            page_id = str(command.get("pageId") or "")
            target_id = str(command.get("targetId") or "")
            actor = str(command.get("actor") or "user")
            if operation not in DOCUMENTATION_COMMAND_OPERATIONS:
                raise DocumentationSceneError("unsupported documentation command")
            if target_type not in DOCUMENTATION_TARGET_TYPES:
                raise DocumentationSceneError("unsupported documentation target type")
            if actor not in DOCUMENTATION_COMMAND_ACTORS:
                raise DocumentationSceneError("unsupported documentation command actor")
            transforms = None
            arrangement = None
            global_operation = operation in {"set_theme", "apply_template"}
            add_object_operation = operation == "add_object"
            if operation == "arrange":
                if target_type != "selection":
                    raise DocumentationSceneError(
                        "arrangement requires a target selection"
                    )
                arrangement = str(command.get("arrangement") or "")
                if arrangement not in DOCUMENTATION_ARRANGEMENTS:
                    raise DocumentationSceneError(
                        "unsupported documentation arrangement"
                    )
                transforms = _arrange_transforms(command.get("transforms"))
                for transform in transforms:
                    self._validate_target(
                        page_id=page_id,
                        target_type=transform["targetType"],
                        target_id=transform["targetId"],
                        page_targets=page_targets,
                    )
            elif global_operation:
                if target_type != "document_theme" or target_id != "company-theme":
                    raise DocumentationSceneError("document theme target is invalid")
                if page_id not in page_targets:
                    raise DocumentationSceneError("documentation page is not editable")
            elif add_object_operation:
                if target_type != "document_object":
                    raise DocumentationSceneError("object insertion target is invalid")
                if page_id not in page_targets:
                    raise DocumentationSceneError("documentation page is not editable")
                existing = {
                    str(value)
                    for value in page_targets[page_id].get("document_object") or []
                }
                if target_id in existing:
                    raise DocumentationSceneError("documentation object already exists")
            else:
                if target_type == "selection":
                    raise DocumentationSceneError(
                        "selection targets require an arrangement"
                    )
                self._validate_target(
                    page_id=page_id,
                    target_type=target_type,
                    target_id=target_id,
                    page_targets=page_targets,
                )
            translation = None
            if operation == "translate":
                translation = (
                    _annotation_vector(command.get("translation"))
                    if target_type in {
                        "balloon",
                        "leader",
                        "page_element",
                        "document_object",
                    }
                    else _vector(command.get("translation"))
                )
                if _is_zero_vector(translation):
                    raise DocumentationSceneError("translation must move the target")
            rotation = None
            if operation == "rotate":
                if target_type not in {
                    "figure",
                    "manual_group",
                    "occurrence",
                    "document_object",
                }:
                    raise DocumentationSceneError(
                        "only CAD presentation targets and document objects can rotate"
                    )
                rotation = _rotation_vector(command.get("rotation"))
                if _is_zero_vector(rotation):
                    raise DocumentationSceneError("rotation must turn the target")
            size_delta = None
            if operation == "resize":
                if target_type not in {"page_element", "document_object"}:
                    raise DocumentationSceneError("only publication objects can resize")
                size_delta = _size_vector(command.get("sizeDelta"))
                if _is_zero_vector(size_delta):
                    raise DocumentationSceneError("resize must change the target size")
            camera_preset = None
            if operation == "set_view":
                if target_type != "figure":
                    raise DocumentationSceneError(
                        "only figures have publication views"
                    )
                camera_preset = str(command.get("cameraPreset") or "")
                if camera_preset not in DOCUMENTATION_CAMERA_PRESETS:
                    raise DocumentationSceneError(
                        "unsupported documentation camera preset"
                    )
            explode_delta = None
            if operation == "adjust_explode":
                if target_type != "figure":
                    raise DocumentationSceneError(
                        "only figures have explosion spacing"
                    )
                explode_delta = _explode_delta(command.get("explodeDelta"))
                if abs(explode_delta) < 1e-12:
                    raise DocumentationSceneError(
                        "explode adjustment must change spacing"
                    )
            if operation == "reset_page" and target_type != "figure":
                raise DocumentationSceneError("page reset requires the figure target")
            if operation in {"clear_callouts", "restore_callouts"} and target_type != "figure":
                raise DocumentationSceneError(
                    "page callout collection commands require the figure target"
                )
            if operation == "add_callout" and target_type not in {
                "occurrence",
                "manual_group",
            }:
                raise DocumentationSceneError(
                    "adding a callout requires a component or manual group target"
                )
            if operation == "remove_callout" and target_type != "balloon":
                raise DocumentationSceneError(
                    "removing a callout requires a balloon target"
                )
            callout_items = None
            if operation in {"clear_callouts", "add_callout", "remove_callout"}:
                callout_items = _callout_items(command.get("calloutItems"))
            elif operation == "restore_callouts":
                if command.get("calloutItems") is not None:
                    raise DocumentationSceneError(
                        "restoring generated callouts must clear the manual callout override"
                    )
            anchor_side = None
            anchor_point = None
            if operation == "set_anchor":
                if target_type != "leader":
                    raise DocumentationSceneError("only leaders have editable anchors")
                if command.get("anchorPoint") is not None:
                    anchor_point = _anchor_point(command.get("anchorPoint"))
                else:
                    anchor_side = str(command.get("anchorSide") or "")
                    if anchor_side not in DOCUMENTATION_ANCHOR_SIDES:
                        raise DocumentationSceneError("unsupported documentation anchor side")
            leader_style = None
            if operation == "set_leader_style":
                if target_type != "leader":
                    raise DocumentationSceneError("only leaders have editable route styles")
                leader_style = str(command.get("leaderStyle") or "")
                if leader_style not in DOCUMENTATION_LEADER_STYLES:
                    raise DocumentationSceneError("unsupported documentation leader style")
            end_condition = None
            if operation == "set_end_condition":
                if target_type != "leader":
                    raise DocumentationSceneError(
                        "only leaders have editable end conditions"
                    )
                end_condition = str(command.get("endCondition") or "")
                if end_condition not in DOCUMENTATION_LEADER_END_CONDITIONS:
                    raise DocumentationSceneError(
                        "unsupported documentation leader end condition"
                    )
            repeated_part_strategy = None
            if operation == "set_repeated_strategy":
                if target_type != "leader":
                    raise DocumentationSceneError(
                        "only leaders have an editable repeated-part strategy"
                    )
                repeated_part_strategy = str(command.get("repeatedPartStrategy") or "")
                if repeated_part_strategy not in DOCUMENTATION_REPEATED_PART_STRATEGIES:
                    raise DocumentationSceneError(
                        "unsupported documentation repeated-part strategy"
                    )
            document_object = None
            if operation == "add_object":
                document_object = _document_object(
                    command.get("documentObject"), expected_id=target_id
                )
            if operation == "remove_object" and target_type != "document_object":
                raise DocumentationSceneError("only document objects can be removed")
            text = None
            if operation == "update_text":
                if target_type not in {"page_element", "document_object"}:
                    raise DocumentationSceneError("selected target has no editable text")
                text = str(command.get("text") or "")
                if len(text) > _MAX_DOCUMENT_TEXT:
                    raise DocumentationSceneError("documentation text is too long")
            style = None
            if operation == "update_style":
                if target_type not in {"page_element", "document_object"}:
                    raise DocumentationSceneError("selected target has no editable style")
                style = _document_style(command.get("style"), allow_empty=False)
            theme = None
            page_masters = None
            if operation == "set_theme":
                theme = _document_theme(command.get("theme"))
            elif operation == "apply_template":
                theme = _document_theme(command.get("theme"))
                page_masters = _page_masters(command.get("pageMasters"))

            cursor = int(scene.get("historyCursor") or 0)
            commands = list(scene.get("commands") or [])[:cursor]
            if len(commands) >= _MAX_COMMANDS:
                raise DocumentationSceneError("documentation command history is full")
            now = _utc_now()
            persisted_command: Dict[str, Any] = {
                "commandId": f"documentation-command-{secrets.token_hex(8)}",
                "operation": operation,
                "targetType": target_type,
                "targetId": target_id if target_type != "figure" else page_id,
                "pageId": page_id,
                "actor": actor,
                "createdAt": now,
            }
            if translation is not None:
                persisted_command["translation"] = translation
            if rotation is not None:
                persisted_command["rotation"] = rotation
            if size_delta is not None:
                persisted_command["sizeDelta"] = size_delta
            if transforms is not None:
                persisted_command["transforms"] = transforms
                persisted_command["arrangement"] = arrangement
            if camera_preset is not None:
                persisted_command["cameraPreset"] = camera_preset
            if explode_delta is not None:
                persisted_command["explodeDelta"] = explode_delta
            if anchor_side is not None:
                persisted_command["anchorSide"] = anchor_side
            if anchor_point is not None:
                persisted_command["anchorPoint"] = anchor_point
            if leader_style is not None:
                persisted_command["leaderStyle"] = leader_style
            if end_condition is not None:
                persisted_command["endCondition"] = end_condition
            if repeated_part_strategy is not None:
                persisted_command["repeatedPartStrategy"] = repeated_part_strategy
            if document_object is not None:
                persisted_command["documentObject"] = copy.deepcopy(document_object)
            if text is not None:
                persisted_command["text"] = text
            if style is not None:
                persisted_command["style"] = copy.deepcopy(style)
            if theme is not None:
                persisted_command["theme"] = copy.deepcopy(theme)
            if page_masters is not None:
                persisted_command["pageMasters"] = copy.deepcopy(page_masters)
            if operation in {"clear_callouts", "add_callout", "remove_callout"}:
                persisted_command["calloutItems"] = copy.deepcopy(callout_items)
            elif operation == "restore_callouts":
                persisted_command["calloutItems"] = None
            commands.append(persisted_command)
            if not scene.get("createdAt"):
                scene["createdAt"] = now
            scene["updatedAt"] = now
            scene["commands"] = commands
            scene["historyCursor"] = len(commands)
            scene["pages"] = replay_documentation_commands(commands)
            scene["theme"], scene["pageMasters"] = replay_documentation_theme(commands)
            validate_documentation_scene(scene)
            _write_atomic(
                self._scene_path(assembly_number),
                canonical_documentation_bytes(scene),
            )
            return {
                "scene": copy.deepcopy(scene),
                "command": copy.deepcopy(persisted_command),
                "revision": documentation_scene_revision(scene),
                "persisted": True,
                "sourceCurrent": True,
                "manualPlanCurrent": True,
                "canUndo": True,
                "canRedo": False,
            }

    def move_history(
        self,
        assembly_number: str,
        source_revision: str,
        manual_plan_revision: str,
        *,
        base_revision: str,
        direction: str,
    ) -> Dict[str, Any]:
        if direction not in {"undo", "redo"}:
            raise DocumentationSceneError("unsupported documentation history operation")
        with _WRITE_LOCK:
            loaded = self.read(
                assembly_number,
                source_revision,
                manual_plan_revision,
            )
            scene = loaded["scene"]
            self._assert_revision(scene, base_revision)
            self._assert_binding(scene, source_revision, manual_plan_revision)
            commands = list(scene.get("commands") or [])
            cursor = int(scene.get("historyCursor") or 0)
            next_cursor = cursor - 1 if direction == "undo" else cursor + 1
            if next_cursor < 0 or next_cursor > len(commands):
                raise DocumentationSceneError(f"nothing to {direction}")
            scene["historyCursor"] = next_cursor
            active_commands = commands[:next_cursor]
            scene["pages"] = replay_documentation_commands(active_commands)
            scene["theme"], scene["pageMasters"] = replay_documentation_theme(
                active_commands
            )
            scene["updatedAt"] = _utc_now()
            validate_documentation_scene(scene)
            _write_atomic(
                self._scene_path(assembly_number),
                canonical_documentation_bytes(scene),
            )
            return {
                "scene": copy.deepcopy(scene),
                "revision": documentation_scene_revision(scene),
                "persisted": True,
                "sourceCurrent": True,
                "manualPlanCurrent": True,
                "canUndo": next_cursor > 0,
                "canRedo": next_cursor < len(commands),
            }
