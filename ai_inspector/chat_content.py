"""Validated rich-content contracts for InspectorPro chat responses."""

from __future__ import annotations

import copy
import math
import re
from typing import Any, Dict, Mapping, Optional, Sequence
from urllib.parse import urlsplit


BLOCK_TYPES = frozenset({
    "markdown",
    "sources",
    "facts",
    "visualization",
    "table",
    "entity_reference",
    "actions",
})
SOURCE_TYPES = frozenset({
    "manufacturer",
    "supplier",
    "standard",
    "technical-document",
    "web",
})
VISUALIZATION_TYPES = frozenset({
    "bar",
    "donut",
    "heatmap",
    "line",
    "scatter",
    "histogram",
    "pareto",
    "pie",
    "kpi",
})
ACTION_IDS = frozenset({
    "highlight_asset",
    "locate_in_plan",
    "show_in_3d",
    "open_drawing",
    "open_inspection",
    "open_process_map",
    "highlight_feature",
})
_SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
CHAT_VISUALIZATION_TOOL = "present_chat_visualization"
CHAT_TABLE_TOOL = "present_chat_table"
_INCOMPLETE_PRESENTATION_PREAMBLE = re.compile(
    r"^(?:i(?:'ll|\s+will|\s+am\s+going\s+to)|let\s+me|we(?:'ll|\s+will))\b",
    re.IGNORECASE,
)
_VISUALIZATION_REQUESTS = (
    ("pareto", re.compile(r"\bpareto(?:\s+chart)?\b", re.IGNORECASE)),
    (
        "heatmap",
        re.compile(
            r"\b(?:heat\s*maps?|matrix\s+(?:charts?|plots?))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "donut",
        re.compile(r"\b(?:donut|doughnut)\s+(?:charts?|graphs?)\b", re.IGNORECASE),
    ),
    (
        "pie",
        re.compile(r"\bpie\s+(?:charts?|graphs?)\b", re.IGNORECASE),
    ),
    ("histogram", re.compile(r"\bhistograms?\b", re.IGNORECASE)),
    (
        "scatter",
        re.compile(r"\b(?:scatter(?:\s+plots?)?|scatterplots?)\b", re.IGNORECASE),
    ),
    (
        "line",
        re.compile(r"\b(?:line\s+(?:charts?|graphs?)|trend\s+(?:charts?|graphs?))\b", re.IGNORECASE),
    ),
    (
        "bar",
        re.compile(r"\b(?:(?:bar|column)\s+(?:charts?|graphs?))\b", re.IGNORECASE),
    ),
    (
        "kpi",
        re.compile(r"\b(?:kpis?|scorecards?|metric\s+cards?)\b", re.IGNORECASE),
    ),
)


def _text(value: Any, maximum: int) -> str:
    return str(value if value is not None else "").strip()[:maximum]


def _display_unit(value: Any) -> str:
    unit = _text(value, 80)
    superscripts = {"2": "\u00b2", "3": "\u00b3"}
    unit = re.sub(
        r"\b(mm|cm|km|in|ft|yd|m)\s*\^\s*([23])\b",
        lambda match: match.group(1) + superscripts[match.group(2)],
        unit,
        flags=re.IGNORECASE,
    )
    return re.sub(
        r"\b(mm|cm|km|in|ft|yd|m)([23])\b",
        lambda match: match.group(1) + superscripts[match.group(2)],
        unit,
        flags=re.IGNORECASE,
    )


def _safe_url(value: Any) -> Optional[str]:
    candidate = _text(value, 2048)
    if not candidate:
        return None
    if candidate.startswith("/") and not candidate.startswith("//"):
        return candidate
    if candidate.startswith("#"):
        return candidate
    parsed = urlsplit(candidate)
    if parsed.scheme.lower() not in {"http", "https", "mailto"}:
        return None
    if parsed.scheme.lower() in {"http", "https"} and not parsed.hostname:
        return None
    return candidate


def _domain(url: str) -> str:
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _primitive(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _normalize_source(raw: Mapping[str, Any], index: int) -> Optional[Dict[str, Any]]:
    url = _safe_url(raw.get("url") or raw.get("sourceUrl"))
    if not url:
        return None
    source_type = _text(raw.get("sourceType"), 40)
    if source_type not in SOURCE_TYPES:
        source_type = "web"
    links = []
    for item in list(raw.get("links") or [])[:4]:
        if not isinstance(item, Mapping):
            continue
        link_url = _safe_url(item.get("url"))
        if not link_url:
            continue
        links.append({
            "label": _text(item.get("label") or "Open", 60),
            "url": link_url,
            "kind": _text(item.get("kind") or "source", 32),
        })
    specifications: Dict[str, str] = {}
    raw_specifications = raw.get("specifications")
    if isinstance(raw_specifications, Mapping):
        for key, value in list(raw_specifications.items())[:8]:
            if _primitive(value):
                specifications[_text(key, 80)] = _text(value, 160)
    return {
        "id": _text(raw.get("id") or f"source_{index + 1}", 120),
        "title": _text(raw.get("title") or raw.get("name") or url, 240),
        "url": url,
        "domain": _text(raw.get("domain") or _domain(url), 160),
        "publisher": _text(
            raw.get("publisher")
            or raw.get("supplier")
            or raw.get("manufacturer"),
            160,
        ),
        "sourceType": source_type,
        "retrievedAt": _text(raw.get("retrievedAt"), 64),
        "description": _text(raw.get("description"), 500),
        "partNumber": _text(
            raw.get("partNumber") or raw.get("part_number") or raw.get("sku"),
            120,
        ),
        "price": _text(raw.get("price"), 80),
        "availability": _text(raw.get("availability"), 80),
        "iconUrl": _safe_url(raw.get("iconUrl") or raw.get("favicon")),
        "specifications": specifications,
        "links": links,
    }


def _normalize_action(raw: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    action_id = _text(raw.get("actionId") or raw.get("action_id"), 80)
    if action_id not in ACTION_IDS:
        return None
    entity_id = _text(raw.get("entityId") or raw.get("entity_id"), 160)
    if entity_id and not _SAFE_ID.fullmatch(entity_id):
        return None
    if not entity_id and action_id not in {"open_drawing", "open_inspection"}:
        return None
    return {
        "actionId": action_id,
        "label": _text(raw.get("label") or action_id.replace("_", " "), 80),
        "entityId": entity_id,
        "entityType": _text(raw.get("entityType") or raw.get("entity_type"), 80),
    }


def _normalize_visualization(raw: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    chart_type = _text(raw.get("type"), 32).lower()
    if chart_type not in VISUALIZATION_TYPES:
        return None
    raw_data = raw.get("data")
    if not isinstance(raw_data, Sequence) or isinstance(raw_data, (str, bytes)):
        return None
    data = []
    for row in list(raw_data)[:200]:
        if not isinstance(row, Mapping):
            continue
        clean_row = {}
        for key, value in list(row.items())[:20]:
            if _primitive(value):
                clean_row[_text(key, 80)] = copy.deepcopy(value)
        if clean_row:
            data.append(clean_row)
    if not data:
        return None
    encoding = raw.get("encoding")
    if not isinstance(encoding, Mapping):
        encoding = {}
    options = raw.get("options")
    if not isinstance(options, Mapping):
        options = {}

    def optional_boolean(key: str) -> Optional[bool]:
        value = options.get(key)
        return value if isinstance(value, bool) else None

    return {
        "type": chart_type,
        "metricId": _text(raw.get("metricId") or raw.get("metric_id"), 120)
        or None,
        "title": _text(raw.get("title"), 160),
        "subtitle": _text(raw.get("subtitle"), 240),
        "data": data,
        "encoding": {
            "x": _text(encoding.get("x") or encoding.get("label"), 80),
            "y": _text(encoding.get("y") or encoding.get("value"), 80),
            "color": _text(encoding.get("color"), 80),
            "entityId": _text(
                encoding.get("entityId") or encoding.get("entity_id"),
                80,
            ),
        },
        "options": {
            "showValues": optional_boolean("showValues"),
            "showPercentages": optional_boolean("showPercentages"),
            "showLegend": optional_boolean("showLegend"),
        },
        "unit": _text(raw.get("unit"), 32),
    }


def _normalize_table(raw: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    raw_columns = raw.get("columns")
    raw_rows = raw.get("rows")
    if (
        not isinstance(raw_columns, Sequence)
        or isinstance(raw_columns, (str, bytes))
        or not isinstance(raw_rows, Sequence)
        or isinstance(raw_rows, (str, bytes))
    ):
        return None
    columns = []
    for item in list(raw_columns)[:12]:
        if not isinstance(item, Mapping):
            continue
        label = _text(item.get("label"), 120)
        if not label:
            continue
        columns.append({
            "label": label,
            "unit": _text(item.get("unit"), 40),
        })
    if not columns:
        return None
    rows = []
    for item in list(raw_rows)[:200]:
        if not isinstance(item, Mapping):
            continue
        raw_cells = item.get("cells")
        if not isinstance(raw_cells, Sequence) or isinstance(
            raw_cells,
            (str, bytes),
        ):
            continue
        cells = [_text(value, 240) for value in list(raw_cells)[: len(columns)]]
        cells.extend([""] * (len(columns) - len(cells)))
        entity_id = _text(item.get("entityId") or item.get("entity_id"), 160)
        if entity_id and not _SAFE_ID.fullmatch(entity_id):
            entity_id = ""
        rows.append({
            "cells": cells,
            "entityId": entity_id or None,
        })
    if not rows:
        return None
    return {
        "title": _text(raw.get("title"), 160),
        "subtitle": _text(raw.get("subtitle"), 240),
        "columns": columns,
        "rows": rows,
    }


def normalize_chat_content_block(raw: Any) -> Optional[Dict[str, Any]]:
    """Return a bounded, presentation-only block or ``None`` when invalid."""

    if not isinstance(raw, Mapping):
        return None
    block_type = _text(raw.get("type"), 40).lower()
    if block_type not in BLOCK_TYPES:
        return None
    if block_type == "markdown":
        value = _text(raw.get("text"), 50_000)
        return {"type": block_type, "text": value} if value else None
    if block_type == "sources":
        sources = []
        for index, item in enumerate(list(raw.get("sources") or [])[:20]):
            if not isinstance(item, Mapping):
                continue
            source = _normalize_source(item, index)
            if source:
                sources.append(source)
        return (
            {
                "type": block_type,
                "title": _text(raw.get("title") or "Sources", 120),
                "sources": sources,
            }
            if sources
            else None
        )
    if block_type == "facts":
        facts = []
        for item in list(raw.get("facts") or [])[:40]:
            if not isinstance(item, Mapping):
                continue
            label = _text(item.get("label"), 120)
            value = _text(item.get("value"), 240)
            if not label or not value:
                continue
            provenance = _text(item.get("provenance"), 20)
            if provenance not in {"source", "derived", "agent"}:
                provenance = "agent"
            facts.append({
                "label": label,
                "value": value,
                "unit": _text(item.get("unit"), 40),
                "sourceId": _text(
                    item.get("sourceId") or item.get("source_id"),
                    120,
                ),
                "provenance": provenance,
            })
        return (
            {
                "type": block_type,
                "title": _text(raw.get("title") or "Evidence", 120),
                "facts": facts,
            }
            if facts
            else None
        )
    if block_type == "visualization":
        spec = raw.get("spec") or raw.get("visualization") or raw
        if not isinstance(spec, Mapping):
            return None
        normalized = _normalize_visualization(spec)
        return {"type": block_type, "spec": normalized} if normalized else None
    if block_type == "table":
        table = raw.get("table") if isinstance(raw.get("table"), Mapping) else raw
        normalized = _normalize_table(table)
        return {"type": block_type, "table": normalized} if normalized else None
    if block_type == "entity_reference":
        entity = raw.get("entity") if isinstance(raw.get("entity"), Mapping) else raw
        entity_id = _text(
            entity.get("id") or entity.get("entityId") or entity.get("entity_id"),
            160,
        )
        label = _text(entity.get("label") or entity.get("name"), 180)
        if not entity_id or not _SAFE_ID.fullmatch(entity_id) or not label:
            return None
        actions = [
            normalized
            for item in list(raw.get("actions") or [])[:6]
            if isinstance(item, Mapping)
            for normalized in [_normalize_action(item)]
            if normalized
        ]
        return {
            "type": block_type,
            "entity": {
                "id": entity_id,
                "entityType": _text(
                    entity.get("entityType") or entity.get("entity_type") or "entity",
                    80,
                ),
                "label": label,
                "subtitle": _text(entity.get("subtitle"), 240),
            },
            "actions": actions,
        }
    actions = [
        normalized
        for item in list(raw.get("actions") or [])[:8]
        if isinstance(item, Mapping)
        for normalized in [_normalize_action(item)]
        if normalized
    ]
    return {"type": "actions", "actions": actions} if actions else None


def normalize_chat_content_blocks(value: Any) -> list[Dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    blocks = []
    for raw in list(value)[:24]:
        normalized = normalize_chat_content_block(raw)
        if normalized:
            blocks.append(normalized)
    return blocks


def normalize_chat_response_payload(result: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize a response's optional rich blocks without changing plain text."""

    payload = copy.deepcopy(dict(result))
    raw_blocks = payload.pop("contentBlocks", None)
    if raw_blocks is None:
        raw_blocks = payload.get("content_blocks")
    if raw_blocks is not None:
        blocks = normalize_chat_content_blocks(raw_blocks)
        if blocks:
            payload["content_blocks"] = blocks
        else:
            payload.pop("content_blocks", None)
    return payload


def requested_visualization_type(message: Any) -> Optional[str]:
    """Return an explicitly requested chart type, excluding negated types."""

    text = re.sub(r"\s+", " ", str(message or "").strip())
    if not text:
        return None
    candidates = []
    for chart_type, pattern in _VISUALIZATION_REQUESTS:
        for match in pattern.finditer(text):
            prefix = text[max(0, match.start() - 24) : match.start()]
            if re.search(
                r"\b(?:not|don't|do\s+not|instead\s+of|rather\s+than)\s+(?:an?\s+)?$",
                prefix,
                re.IGNORECASE,
            ):
                continue
            candidates.append((match.start(), chart_type))
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])[1]


def requested_visualization_options(message: Any) -> Dict[str, bool]:
    """Return explicit chart display preferences from one user turn.

    These preferences affect presentation only. They never select data or
    authorize an application action.
    """

    text = re.sub(r"\s+", " ", str(message or "").strip()).casefold()
    if not text:
        return {}
    options: Dict[str, bool] = {}

    if re.search(
        r"\b(?:no|hide|without|do\s+not\s+show|don't\s+show)\s+"
        r"(?:the\s+)?(?:percentage|percent)\s*(?:labels?|values?)?\b",
        text,
    ):
        options["showPercentages"] = False
    elif re.search(
        r"\b(?:show|include|with|add|label(?:s|ed)?\s+with)\b"
        r"[^.!?;]{0,40}\b(?:percentage|percent)s?\b",
        text,
    ):
        options["showPercentages"] = True

    if re.search(
        r"\b(?:no|hide|without|do\s+not\s+show|don't\s+show)\s+"
        r"(?:the\s+)?(?:value|count)\s*(?:labels?)?\b",
        text,
    ):
        options["showValues"] = False
    elif re.search(
        r"\b(?:show|include|with|add|use)\b[^.!?;]{0,40}"
        r"\b(?:value|count|placement-count)s?\s*(?:labels?)?\b",
        text,
    ):
        options["showValues"] = True

    if re.search(
        r"\b(?:no|hide|without|do\s+not\s+show|don't\s+show)\s+"
        r"(?:the\s+)?legend\b",
        text,
    ):
        options["showLegend"] = False
    elif re.search(
        r"\b(?:show|include|with|add)\b[^.!?;]{0,60}\blegend\b",
        text,
    ):
        options["showLegend"] = True
    return options


def requested_table(message: Any) -> bool:
    """Return whether the current turn explicitly requests a table."""

    text = re.sub(r"\s+", " ", str(message or "").strip())
    for match in re.finditer(r"\btables?\b", text, re.IGNORECASE):
        prefix = text[max(0, match.start() - 24) : match.start()]
        if not re.search(
            r"\b(?:not(?:\s+as)?|don't|do\s+not|instead\s+of|"
            r"rather\s+than)\s+(?:an?\s+)?$",
            prefix,
            re.IGNORECASE,
        ):
            return True
    return False


def chat_visualization_tool_spec(
    required_chart_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Return the closed presentation-only chart tool contract."""

    nullable_text = {"type": ["string", "null"]}
    chart_types = sorted(VISUALIZATION_TYPES)
    if required_chart_type in VISUALIZATION_TYPES:
        chart_types = [str(required_chart_type)]
    return {
        "name": CHAT_VISUALIZATION_TOOL,
        "description": (
            "Present one validated chart in InspectorPro chat. This tool is "
            "presentation-only: it cannot inspect, preview, or modify the "
            "Facility Layout. Use exact values from trusted context and put "
            "unsupported values in prose as unavailable instead of inventing "
            "chart data."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "chart_type",
                "metric_id",
                "title",
                "subtitle",
                "unit",
                "show_values",
                "show_percentages",
                "show_legend",
                "data",
            ],
            "properties": {
                "chart_type": {
                    "type": "string",
                    "enum": chart_types,
                },
                "metric_id": {
                    "type": ["string", "null"],
                    "maxLength": 120,
                    "description": (
                        "Stable semantic metric identifier when the source "
                        "workflow defines one; null for ad hoc charts."
                    ),
                },
                "title": {**nullable_text, "maxLength": 160},
                "subtitle": {**nullable_text, "maxLength": 240},
                "unit": {**nullable_text, "maxLength": 32},
                "show_values": {"type": ["boolean", "null"]},
                "show_percentages": {"type": ["boolean", "null"]},
                "show_legend": {"type": ["boolean", "null"]},
                "data": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 200,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "label",
                            "value",
                            "entity_id",
                            "series",
                        ],
                        "properties": {
                            "label": {
                                "type": "string",
                                "maxLength": 120,
                            },
                            "value": {"type": "number"},
                            "entity_id": {
                                "type": ["string", "null"],
                                "maxLength": 160,
                            },
                            "series": {
                                "type": ["string", "null"],
                                "maxLength": 80,
                            },
                        },
                    },
                },
            },
        },
    }


def chat_visualization_block_from_args(
    args: Any,
    *,
    required_chart_type: Optional[str] = None,
    required_options: Optional[Mapping[str, bool]] = None,
) -> Optional[Dict[str, Any]]:
    """Convert one model chart intent into a normalized content block."""

    if not isinstance(args, Mapping):
        return None
    chart_type = _text(args.get("chart_type"), 32).lower()
    if chart_type not in VISUALIZATION_TYPES:
        return None
    if required_chart_type in VISUALIZATION_TYPES:
        chart_type = str(required_chart_type)
    raw_data = args.get("data")
    if not isinstance(raw_data, Sequence) or isinstance(
        raw_data,
        (str, bytes),
    ):
        return None
    rows = []
    for raw in list(raw_data)[:200]:
        if not isinstance(raw, Mapping):
            continue
        label = _text(raw.get("label"), 120)
        value = raw.get("value")
        if not label or isinstance(value, bool) or not isinstance(
            value,
            (int, float),
        ):
            continue
        numeric_value = float(value)
        if not math.isfinite(numeric_value):
            continue
        entity_id = _text(raw.get("entity_id"), 160)
        if entity_id and not _SAFE_ID.fullmatch(entity_id):
            entity_id = ""
        rows.append({
            "label": label,
            "value": numeric_value,
            "entityId": entity_id or None,
            "series": _text(raw.get("series"), 80) or None,
        })
    if not rows:
        return None
    supplied_options = {
        "showValues": args.get("show_values"),
        "showPercentages": args.get("show_percentages"),
        "showLegend": args.get("show_legend"),
    }
    for key, value in dict(required_options or {}).items():
        if key in supplied_options and isinstance(value, bool):
            supplied_options[key] = value
    return normalize_chat_content_block({
        "type": "visualization",
        "spec": {
            "type": chart_type,
            "title": _text(args.get("title"), 160),
            "subtitle": _text(args.get("subtitle"), 240),
            "unit": _text(args.get("unit"), 32),
            "metricId": _text(args.get("metric_id"), 120) or None,
            "data": rows,
            "encoding": {
                "x": "label",
                "y": "value",
                "color": "series",
                "entityId": "entityId",
            },
            "options": supplied_options,
        },
    })


def chat_table_tool_spec() -> Dict[str, Any]:
    """Return the closed presentation-only table tool contract."""

    nullable_text = {"type": ["string", "null"]}
    return {
        "name": CHAT_TABLE_TOOL,
        "description": (
            "Present one validated data table in InspectorPro chat. This tool "
            "is presentation-only and cannot inspect or modify application "
            "state. Use exact values from trusted context. Each row must have "
            "cells in the same order as columns."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["title", "subtitle", "columns", "rows"],
            "properties": {
                "title": {**nullable_text, "maxLength": 160},
                "subtitle": {**nullable_text, "maxLength": 240},
                "columns": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 12,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["label", "unit"],
                        "properties": {
                            "label": {"type": "string", "maxLength": 120},
                            "unit": {**nullable_text, "maxLength": 40},
                        },
                    },
                },
                "rows": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 200,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["cells", "entity_id"],
                        "properties": {
                            "cells": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 12,
                                "items": {"type": "string", "maxLength": 240},
                            },
                            "entity_id": {
                                "type": ["string", "null"],
                                "maxLength": 160,
                            },
                        },
                    },
                },
            },
        },
    }


def chat_table_block_from_args(args: Any) -> Optional[Dict[str, Any]]:
    """Convert one model table intent into a normalized content block."""

    if not isinstance(args, Mapping):
        return None
    return normalize_chat_content_block({
        "type": "table",
        "table": {
            "title": args.get("title"),
            "subtitle": args.get("subtitle"),
            "columns": args.get("columns"),
            "rows": args.get("rows"),
        },
    })


def complete_chat_table_prose(
    response_text: Any,
    content_blocks: Sequence[Mapping[str, Any]],
    *,
    request_message: Any = "",
) -> str:
    """Replace an empty/tool-only table response with grounded prose."""

    text = _text(response_text, 50_000)
    table = next(
        (
            block.get("table")
            for block in content_blocks
            if isinstance(block, Mapping)
            and block.get("type") == "table"
            and isinstance(block.get("table"), Mapping)
        ),
        None,
    )
    if table is None:
        return text
    looks_incomplete = (
        not text
        or text.casefold() == "no response from agent."
        or (
            len(text) <= 320
            and _INCOMPLETE_PRESENTATION_PREAMBLE.match(text) is not None
        )
    )
    if not looks_incomplete:
        return text

    columns = [
        _text(item.get("label"), 120)
        for item in list(table.get("columns") or [])[:12]
        if isinstance(item, Mapping) and _text(item.get("label"), 120)
    ]
    rows = [
        item
        for item in list(table.get("rows") or [])[:200]
        if isinstance(item, Mapping)
    ]
    title = _text(table.get("title"), 160) or "Requested comparison"
    compared = columns[1:] if len(columns) > 1 else columns
    lines = [f"## {title}", ""]
    if compared:
        lines.append(
            "The table compares "
            + ", ".join(f"**{label}**" for label in compared)
            + f" across {len(rows)} supplied row"
            + ("s." if len(rows) != 1 else ".")
        )
    else:
        lines.append(
            f"The table contains {len(rows)} supplied row"
            + ("s." if len(rows) != 1 else ".")
        )
    follow_up = re.search(
        r"\b(?:end\s+by\s+)?ask(?:ing)?\s+(?:me\s+)?whether\s+i\s+want\s+"
        r"(.+?)(?:[.!?]|$)",
        str(request_message or ""),
        re.IGNORECASE,
    )
    if follow_up:
        requested = _text(follow_up.group(1), 180).rstrip(".?!")
        if requested:
            lines.extend(["", f"Would you like {requested}?"])
    return "\n".join(lines)


def complete_chat_visualization_prose(
    response_text: Any,
    content_blocks: Sequence[Mapping[str, Any]],
) -> str:
    """Replace a provider preamble with a deterministic chart conclusion.

    Presentation tools terminate the provider turn in the current browser
    protocol. Some providers therefore return a future-tense preamble next to
    an otherwise valid chart call. This guard derives a bounded conclusion
    from the already validated chart data; it never invents another metric.
    """

    text = _text(response_text, 50_000)
    chart = next(
        (
            block.get("spec")
            for block in content_blocks
            if isinstance(block, Mapping)
            and block.get("type") == "visualization"
            and isinstance(block.get("spec"), Mapping)
        ),
        None,
    )
    if chart is None:
        return text
    looks_incomplete = (
        not text
        or (
            len(text) <= 320
            and _INCOMPLETE_PRESENTATION_PREAMBLE.match(text) is not None
        )
    )
    if not looks_incomplete:
        return text

    rows = []
    for raw in list(chart.get("data") or [])[:200]:
        if not isinstance(raw, Mapping):
            continue
        label = _text(raw.get("label"), 120)
        value = raw.get("value")
        if (
            not label
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            continue
        series = _text(raw.get("series"), 120)
        rows.append((f"{label} / {series}" if series else label, float(value)))
    if not rows:
        return text or "Here is the requested evidence-backed chart."

    def rendered_value(value: float) -> str:
        return str(int(value)) if value.is_integer() else f"{value:.4g}"

    ranked = sorted(rows, key=lambda item: (-item[1], item[0].lower()))
    bottom = sorted(rows, key=lambda item: (item[1], item[0].lower()))
    comparison_count = min(2, len(rows))
    unit = _display_unit(chart.get("unit"))

    def rendered_items(items: Sequence[tuple[str, float]]) -> str:
        return ", ".join(
            f"**{label}** ({rendered_value(value)}"
            f"{f' {unit}' if unit else ''})"
            for label, value in items
        )

    title = _text(chart.get("title"), 160) or "Chart analysis"
    metric = unit or "the supplied metric"
    lines = [
        f"## {title}",
        "",
        f"The chart compares {len(rows)} categories using {metric}.",
        f"Highest values: {rendered_items(ranked[:comparison_count])}.",
    ]
    if len(rows) > 1:
        lines.append(
            f"Lowest values: {rendered_items(bottom[:comparison_count])}."
        )
    lines.extend([
        "",
        (
            "These values describe only the charted metric; they do not by "
            "themselves prove capacity, utilization, safety, clearance, "
            "causation, or process performance."
        ),
        (
            f"Priority review: examine **{ranked[0][0]}**, the highest observed "
            "value, against the applicable unresolved engineering evidence "
            "before changing the layout."
        ),
    ])
    return "\n".join(lines)


__all__ = [
    "ACTION_IDS",
    "BLOCK_TYPES",
    "CHAT_TABLE_TOOL",
    "CHAT_VISUALIZATION_TOOL",
    "SOURCE_TYPES",
    "VISUALIZATION_TYPES",
    "chat_table_block_from_args",
    "chat_table_tool_spec",
    "chat_visualization_block_from_args",
    "chat_visualization_tool_spec",
    "complete_chat_visualization_prose",
    "complete_chat_table_prose",
    "normalize_chat_content_block",
    "normalize_chat_content_blocks",
    "normalize_chat_response_payload",
    "requested_visualization_options",
    "requested_visualization_type",
    "requested_table",
]
