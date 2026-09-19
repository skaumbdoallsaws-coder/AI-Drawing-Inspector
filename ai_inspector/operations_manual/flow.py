"""Deterministic 16:9 pagination for long-form technical content."""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, Iterable, Mapping, Sequence


PAGE_WIDTH_PT = 960.0
PAGE_HEIGHT_PT = 540.0
PAGE_MARGIN_X_PT = 56.0
PAGE_CONTENT_TOP_PT = 74.0
PAGE_CONTENT_BOTTOM_PT = 506.0
PAGE_CONTENT_WIDTH_PT = PAGE_WIDTH_PT - (2 * PAGE_MARGIN_X_PT)
PAGE_CONTENT_HEIGHT_PT = PAGE_CONTENT_BOTTOM_PT - PAGE_CONTENT_TOP_PT


@dataclass(frozen=True)
class TextStyle:
    font_size: float
    line_height: float
    weight: int = 400
    color: str = "#18212A"


BODY_STYLE = TextStyle(10.0, 14.0)
SMALL_STYLE = TextStyle(8.0, 11.0, color="#596A76")
HEADING_1_STYLE = TextStyle(20.0, 25.0, 700, "#071B2A")
HEADING_2_STYLE = TextStyle(14.0, 19.0, 700, "#071B2A")
TABLE_FONT_SIZE_PT = 7.5
TABLE_LINE_HEIGHT_PT = 10.0
TABLE_CELL_VERTICAL_PADDING_PT = 12.0
TABLE_MIN_ROW_HEIGHT_PT = 30.0
TABLE_HEADER_HEIGHT_PT = 25.0


def publication_layout() -> Dict[str, Any]:
    return {
        "page": {
            "width": PAGE_WIDTH_PT,
            "height": PAGE_HEIGHT_PT,
            "aspectRatio": PAGE_WIDTH_PT / PAGE_HEIGHT_PT,
            "orientation": "landscape",
            "logicalUnit": "pt",
        },
        "shared": {
            "header": {"x": 0, "y": 0, "width": PAGE_WIDTH_PT, "height": 56},
            "footer": {"x": 40, "y": 516, "width": 880, "height": 16},
            "content": {
                "x": PAGE_MARGIN_X_PT,
                "y": PAGE_CONTENT_TOP_PT,
                "width": PAGE_CONTENT_WIDTH_PT,
                "height": PAGE_CONTENT_HEIGHT_PT,
            },
        },
        "pageTypes": {
            "operations_cover": {
                "coverStyleVersion": 2,
                "header": {"x": 0, "y": 0, "width": PAGE_WIDTH_PT, "height": 72},
                "topAccent": {"x": 10, "y": 4, "width": 940, "height": 12},
                "topRule": {"x": 10, "y": 16, "width": 940, "height": 5},
                "leftAccent": {"x": 10, "y": 21, "width": 12, "height": 451},
                "bottomBand": {"x": 10, "y": 472, "width": 940, "height": 56},
                "footerLeft": {"x": 42, "y": 492, "width": 500, "height": 16},
                "footerRight": {"x": 560, "y": 492, "width": 358, "height": 16},
                "kicker": {"x": 64, "y": 88, "width": 832, "height": 26},
                "title": {"x": 64, "y": 120, "width": 832, "height": 48},
                "illustration": {"x": 150, "y": 176, "width": 660, "height": 276},
            },
            "operations_document_control": {
                "heading": {"x": 56, "y": 76, "width": 848, "height": 28},
                "table": {"x": 56, "y": 116, "width": 848, "height": 246},
                "status": {"x": 56, "y": 382, "width": 848, "height": 60},
            },
            "operations_contents": {
                "heading": {"x": 56, "y": 76, "width": 848, "height": 28},
                "list": {"x": 68, "y": 122, "width": 824, "height": 330},
            },
        },
    }


def _char_em(character: str) -> float:
    if character in " ilI.,:;'|!":
        return 0.30
    if character in "mwMW@%&":
        return 0.88
    if character.isupper() or character.isdigit():
        return 0.61
    return 0.52


@lru_cache(maxsize=8192)
def _renderer_text_width(text: str, font_size: float) -> float:
    try:
        import fitz

        return float(
            fitz.get_text_length(text, fontname="helv", fontsize=font_size)
        )
    except (ImportError, RuntimeError, ValueError):
        return sum(_char_em(character) for character in text) * font_size


def text_width(text: str, font_size: float) -> float:
    return _renderer_text_width(str(text), float(font_size))


def wrap_text(text: str, width: float, font_size: float) -> list[str]:
    words = re.findall(r"\S+", str(text or "").strip())
    if not words:
        return [""]
    lines: list[str] = []
    line = words[0]
    for word in words[1:]:
        candidate = f"{line} {word}"
        if text_width(candidate, font_size) <= width:
            line = candidate
            continue
        lines.append(line)
        if text_width(word, font_size) <= width:
            line = word
            continue
        fragment = ""
        for character in word:
            if fragment and text_width(fragment + character, font_size) > width:
                lines.append(fragment)
                fragment = character
            else:
                fragment += character
        line = fragment
    lines.append(line)
    return lines


def _frame(y: float, height: float, *, x: float = PAGE_MARGIN_X_PT, width: float = PAGE_CONTENT_WIDTH_PT) -> Dict[str, float]:
    return {
        "x": round(float(x), 3),
        "y": round(float(y), 3),
        "width": round(float(width), 3),
        "height": round(float(height), 3),
    }


class FlowLayoutEngine:
    """Places semantic blocks without allowing content to cross page bounds."""

    def __init__(self, *, start_page_number: int = 4):
        self.start_page_number = int(start_page_number)
        self._pages: list[Dict[str, Any]] = []
        self._page: Dict[str, Any] | None = None
        self._cursor_y = PAGE_CONTENT_TOP_PT
        self._section_title = ""

    def _new_page(self, section: Mapping[str, Any], *, continuation: bool = False) -> None:
        section_id = str(section.get("sectionId") or "section")
        page_number = self.start_page_number + len(self._pages)
        suffix = len([row for row in self._pages if row.get("sectionId") == section_id]) + 1
        title = str(section.get("title") or "Operations Manual")
        self._page = {
            "pageId": f"page-{section_id}-{suffix}",
            "pageNumber": page_number,
            "pageType": "operations_content",
            "sectionId": section_id,
            "title": title + (" (continued)" if continuation else ""),
            "layoutBlocks": [],
            "evidenceClaimIds": [],
        }
        self._pages.append(self._page)
        self._cursor_y = PAGE_CONTENT_TOP_PT
        self._section_title = title
        if continuation:
            self._append_block(
                {
                    "blockId": f"{section_id}-continuation-{suffix}",
                    "blockType": "continuation_heading",
                    "text": f"{title} (continued)",
                    "lines": [f"{title} (continued)"],
                    "style": self._style_dict(HEADING_2_STYLE),
                    "frame": _frame(self._cursor_y, 25),
                    "evidenceClaimIds": [],
                },
                height=31,
            )

    @staticmethod
    def _style_dict(style: TextStyle) -> Dict[str, Any]:
        return {
            "fontSize": style.font_size,
            "lineHeight": style.line_height,
            "fontWeight": style.weight,
            "color": style.color,
        }

    @property
    def _remaining(self) -> float:
        return PAGE_CONTENT_BOTTOM_PT - self._cursor_y

    def _ensure(self, section: Mapping[str, Any], required: float) -> None:
        if self._page is None:
            self._new_page(section)
        elif required > self._remaining:
            self._new_page(section, continuation=True)

    def _append_block(self, block: Dict[str, Any], *, height: float, gap: float = 8.0) -> None:
        assert self._page is not None
        self._page["layoutBlocks"].append(block)
        self._page["evidenceClaimIds"] = sorted(
            set(self._page["evidenceClaimIds"])
            | {str(value) for value in block.get("evidenceClaimIds") or []}
        )
        self._cursor_y += height + gap

    @staticmethod
    def _minimum_following_height(block: Mapping[str, Any] | None) -> float:
        """Reserve enough space for a meaningful first unit after a heading."""

        if not isinstance(block, Mapping):
            return (BODY_STYLE.line_height * 2) + 10.0
        block_type = str(block.get("blockType") or "")
        if block_type in {"note", "status_panel"}:
            return 68.0
        if block_type in {"list", "figure_legend"}:
            return 56.0
        if block_type in {"specification_table", "table", "source_table"}:
            return TABLE_HEADER_HEIGHT_PT + (TABLE_MIN_ROW_HEIGHT_PT * 2) + 10.0
        if block_type == "cad_figure":
            return 192.0
        return (BODY_STYLE.line_height * 2) + 10.0

    def _place_heading(
        self,
        section: Mapping[str, Any],
        block: Mapping[str, Any],
        next_block: Mapping[str, Any] | None = None,
    ) -> None:
        level = int((block.get("payload") or {}).get("level") or 1)
        style = HEADING_1_STYLE if level == 1 else HEADING_2_STYLE
        text = str((block.get("payload") or {}).get("text") or section.get("title") or "")
        lines = wrap_text(text, PAGE_CONTENT_WIDTH_PT, style.font_size)
        height = max(style.line_height, len(lines) * style.line_height)
        # Keep the heading with the first meaningful unit that follows.
        self._ensure(
            section,
            height + 8.0 + self._minimum_following_height(next_block),
        )
        self._append_block(
            {
                "blockId": str(block.get("blockId") or "heading"),
                "blockType": "heading",
                "text": text,
                "lines": lines,
                "style": self._style_dict(style),
                "frame": _frame(self._cursor_y, height),
                "evidenceClaimIds": list(block.get("evidenceClaimIds") or []),
            },
            height=height,
            gap=12,
        )

    def _place_paragraph(self, section: Mapping[str, Any], block: Mapping[str, Any]) -> None:
        payload = block.get("payload") or {}
        text = str(payload.get("text") or "")
        lines = wrap_text(text, PAGE_CONTENT_WIDTH_PT, BODY_STYLE.font_size)
        line_index = 0
        fragment_index = 1
        while line_index < len(lines):
            self._ensure(section, BODY_STYLE.line_height * 2)
            capacity = max(1, int(self._remaining // BODY_STYLE.line_height))
            take = min(capacity, len(lines) - line_index)
            remaining_after = len(lines) - line_index - take
            if remaining_after == 1 and take > 2:
                take -= 1
            if take == 1 and line_index > 0:
                self._new_page(section, continuation=True)
                continue
            fragment = lines[line_index : line_index + take]
            height = len(fragment) * BODY_STYLE.line_height
            self._append_block(
                {
                    "blockId": f"{block.get('blockId') or 'paragraph'}-{fragment_index}",
                    "sourceBlockId": str(block.get("blockId") or "paragraph"),
                    "blockType": "paragraph",
                    "text": " ".join(fragment),
                    "lines": fragment,
                    "style": self._style_dict(BODY_STYLE),
                    "frame": _frame(self._cursor_y, height),
                    "evidenceClaimIds": list(block.get("evidenceClaimIds") or []),
                },
                height=height,
                gap=8 if line_index + take >= len(lines) else 0,
            )
            line_index += take
            fragment_index += 1

    def _place_note(self, section: Mapping[str, Any], block: Mapping[str, Any]) -> None:
        payload = block.get("payload") or {}
        text = str(payload.get("text") or "")
        signal_word = str(payload.get("signalWord") or "").upper()
        display_text = f"{signal_word} {text}".strip()
        lines = wrap_text(display_text, PAGE_CONTENT_WIDTH_PT - 78, BODY_STYLE.font_size)
        height = max(58.0, (len(lines) * BODY_STYLE.line_height) + 16)
        self._ensure(section, height)
        self._append_block(
            {
                "blockId": str(block.get("blockId") or "note"),
                "blockType": "note",
                "text": text,
                "lines": lines,
                "tone": str(payload.get("tone") or "information"),
                "signalWord": signal_word,
                "style": self._style_dict(BODY_STYLE),
                "frame": _frame(self._cursor_y, height),
                "evidenceClaimIds": list(block.get("evidenceClaimIds") or []),
            },
            height=height,
            gap=10,
        )

    def _place_list(self, section: Mapping[str, Any], block: Mapping[str, Any]) -> None:
        payload = block.get("payload") or {}
        source_items = [
            copy.deepcopy(dict(row))
            for row in payload.get("items") or []
            if isinstance(row, Mapping)
        ]
        if not source_items:
            return
        block_type = str(block.get("blockType") or "list")
        list_style = str(payload.get("style") or "numbered")
        columns = max(1, min(2, int(payload.get("columns") or 1)))
        font_size = 7.8 if block_type == "figure_legend" else 9.4
        line_height = 10.5 if block_type == "figure_legend" else 13.2
        column_gap = 22.0 if columns == 2 else 0.0
        column_width = (
            PAGE_CONTENT_WIDTH_PT - ((columns - 1) * column_gap)
        ) / columns
        marker_width = 27.0 if list_style in {"numbered", "keyed"} else 8.0
        prepared: list[Dict[str, Any]] = []
        for index, source in enumerate(source_items, start=1):
            label = str(source.get("label") or "").strip()
            text = str(source.get("text") or source.get("description") or "").strip()
            quantity = max(1, int(source.get("quantity") or 1))
            display = f"{label}: {text}" if label and text else (label or text)
            lines = wrap_text(display, max(60.0, column_width - marker_width), font_size)
            prepared.append(
                {
                    **source,
                    "itemNumber": int(source.get("itemNumber") or index),
                    "label": label,
                    "text": text,
                    "displayText": display,
                    "lines": lines,
                    "quantity": quantity,
                    "height": max(
                        22.0 if block_type == "figure_legend" else 23.0,
                        (len(lines) * line_height)
                        + (6.0 if block_type == "figure_legend" else 5.0),
                    ),
                }
            )

        item_index = 0
        fragment = 1
        while item_index < len(prepared):
            self._ensure(section, 24.0)
            available = self._remaining
            chunk: list[Dict[str, Any]] = []
            row_heights: list[float] = []
            cursor = item_index
            while cursor < len(prepared):
                row = prepared[cursor : cursor + columns]
                row_height = max(float(item["height"]) for item in row)
                if row_heights and sum(row_heights) + row_height > available:
                    break
                if not row_heights and row_height > available:
                    self._new_page(section, continuation=True)
                    available = self._remaining
                    continue
                chunk.extend(row)
                row_heights.append(row_height)
                cursor += len(row)
            height = sum(row_heights)
            self._append_block(
                {
                    "blockId": f"{block.get('blockId') or block_type}-{fragment}",
                    "sourceBlockId": str(block.get("blockId") or block_type),
                    "blockType": block_type,
                    "figureId": (
                        str(payload.get("figureId") or "")
                        if block_type == "figure_legend"
                        else ""
                    ),
                    "listStyle": list_style,
                    "columns": columns,
                    "columnGap": column_gap,
                    "fontSize": font_size,
                    "lineHeight": line_height,
                    "items": chunk,
                    "rowHeights": [round(value, 3) for value in row_heights],
                    "continued": fragment > 1,
                    "frame": _frame(self._cursor_y, height),
                    "evidenceClaimIds": list(block.get("evidenceClaimIds") or []),
                },
                height=height,
                gap=10,
            )
            item_index += len(chunk)
            fragment += 1

    def _place_figure(self, section: Mapping[str, Any], block: Mapping[str, Any]) -> None:
        payload = block.get("payload") or {}
        requested = float(payload.get("height") or 300)
        # Leave room for the automatic continuation heading on a figure-only page.
        maximum_height = PAGE_CONTENT_HEIGHT_PT - 44.0
        height = min(maximum_height, max(180.0, requested))
        self._ensure(section, height + 4)
        self._append_block(
            {
                "blockId": str(block.get("blockId") or "figure"),
                "blockType": "cad_figure",
                "figureId": str(payload.get("figureId") or ""),
                "caption": str(payload.get("caption") or ""),
                "frame": _frame(self._cursor_y, height),
                "evidenceClaimIds": list(block.get("evidenceClaimIds") or []),
            },
            height=height,
            gap=12,
        )

    def _place_figure_with_legend(
        self,
        section: Mapping[str, Any],
        figure_block: Mapping[str, Any],
        legend_block: Mapping[str, Any],
    ) -> None:
        figure_payload = figure_block.get("payload") or {}
        legend_payload = legend_block.get("payload") or {}
        maximum_height = PAGE_CONTENT_HEIGHT_PT - 44.0
        requested_height = min(
            maximum_height,
            max(220.0, float(figure_payload.get("height") or 320.0)),
        )
        gap = 20.0
        figure_width = round(PAGE_CONTENT_WIDTH_PT * 0.625, 3)
        legend_width = PAGE_CONTENT_WIDTH_PT - figure_width - gap
        source_items = [
            row for row in legend_payload.get("items") or [] if isinstance(row, Mapping)
        ]
        columns = 1 if len(source_items) <= 10 else 2
        column_gap = 14.0 if columns == 2 else 0.0
        column_width = (legend_width - ((columns - 1) * column_gap)) / columns
        font_size = 7.2
        line_height = 9.5
        marker_width = 23.0
        prepared: list[Dict[str, Any]] = []
        for index, source in enumerate(source_items, start=1):
            label = str(source.get("label") or "").strip()
            text = str(source.get("text") or source.get("description") or "").strip()
            quantity = max(1, int(source.get("quantity") or 1))
            display = f"{label}: {text}" if label and text else (label or text)
            lines = wrap_text(display, max(54.0, column_width - marker_width), font_size)
            prepared.append(
                {
                    **copy.deepcopy(dict(source)),
                    "itemNumber": int(source.get("itemNumber") or index),
                    "label": label,
                    "text": text,
                    "displayText": display,
                    "lines": lines,
                    "quantity": quantity,
                    "height": max(22.0, (len(lines) * line_height) + 11.0),
                }
            )
        row_heights = [
            max(float(item["height"]) for item in prepared[index:index + columns])
            for index in range(0, len(prepared), columns)
        ]
        legend_height = sum(row_heights)
        pair_height = min(maximum_height, max(requested_height, legend_height))
        if legend_height > maximum_height + 1e-6:
            raise ValueError(
                f"{legend_block.get('blockId') or 'figure legend'} does not fit beside its figure"
            )
        self._ensure(section, pair_height + 4.0)
        assert self._page is not None
        y = self._cursor_y
        figure = {
            "blockId": str(figure_block.get("blockId") or "figure"),
            "blockType": "cad_figure",
            "figureId": str(figure_payload.get("figureId") or ""),
            "caption": str(figure_payload.get("caption") or ""),
            "frame": _frame(y, pair_height, width=figure_width),
            "evidenceClaimIds": list(figure_block.get("evidenceClaimIds") or []),
        }
        legend = {
            "blockId": str(legend_block.get("blockId") or "figure-legend"),
            "blockType": "figure_legend",
            "figureId": str(legend_payload.get("figureId") or ""),
            "listStyle": str(legend_payload.get("style") or "keyed"),
            "columns": columns,
            "columnGap": column_gap,
            "fontSize": font_size,
            "lineHeight": line_height,
            "items": prepared,
            "rowHeights": [round(value, 3) for value in row_heights],
            "continued": False,
            "frame": _frame(
                y,
                pair_height,
                x=PAGE_MARGIN_X_PT + figure_width + gap,
                width=legend_width,
            ),
            "evidenceClaimIds": list(legend_block.get("evidenceClaimIds") or []),
        }
        self._page["layoutBlocks"].extend([figure, legend])
        self._page["evidenceClaimIds"] = sorted(
            set(self._page["evidenceClaimIds"])
            | {str(value) for value in figure["evidenceClaimIds"]}
            | {str(value) for value in legend["evidenceClaimIds"]}
        )
        self._cursor_y += pair_height + 12.0

    def _place_table(self, section: Mapping[str, Any], block: Mapping[str, Any]) -> None:
        payload = block.get("payload") or {}
        columns = [str(value) for value in payload.get("columns") or []]
        source_rows = [
            copy.deepcopy(dict(row))
            for row in payload.get("rows") or []
            if isinstance(row, Mapping)
        ]
        column_count = max(1, len(columns))
        cell_width = (PAGE_CONTENT_WIDTH_PT / column_count) - 14.0
        maximum_fragment_lines = max(
            1,
            int(
                (
                    PAGE_CONTENT_HEIGHT_PT
                    - 40.0  # Continuation heading and gap on split tables.
                    - TABLE_HEADER_HEIGHT_PT
                    - TABLE_CELL_VERTICAL_PADDING_PT
                )
                // TABLE_LINE_HEIGHT_PT
            ),
        )
        rows: list[tuple[Dict[str, Any], float]] = []
        for source_row in source_rows:
            cells = [str(value or "") for value in source_row.get("cells") or []]
            wrapped = [
                wrap_text(value, cell_width, TABLE_FONT_SIZE_PT)
                for value in cells
            ]
            maximum_lines = max((len(value) for value in wrapped), default=1)
            for offset in range(0, maximum_lines, maximum_fragment_lines):
                fragment_lines = [
                    value[offset : offset + maximum_fragment_lines]
                    for value in wrapped
                ]
                fragment_row = copy.deepcopy(source_row)
                fragment_row["cells"] = [
                    " ".join(value).strip() for value in fragment_lines
                ]
                if offset:
                    fragment_row["rowContinuation"] = True
                visible_lines = max(
                    (len(value) for value in fragment_lines), default=1
                )
                height = max(
                    TABLE_MIN_ROW_HEIGHT_PT,
                    (visible_lines * TABLE_LINE_HEIGHT_PT)
                    + TABLE_CELL_VERTICAL_PADDING_PT,
                )
                rows.append((fragment_row, height))
        keep_together = bool(payload.get("keepTogether"))
        complete_height = TABLE_HEADER_HEIGHT_PT + sum(
            row_height for _, row_height in rows
        )
        if (
            keep_together
            and rows
            and complete_height <= PAGE_CONTENT_HEIGHT_PT - 40.0
            and self._page is not None
            and complete_height > self._remaining
        ):
            self._new_page(section, continuation=True)
        row_index = 0
        fragment = 1
        while row_index < len(rows) or (not rows and fragment == 1):
            self._ensure(
                section,
                TABLE_HEADER_HEIGHT_PT + TABLE_MIN_ROW_HEIGHT_PT,
            )
            available = self._remaining - TABLE_HEADER_HEIGHT_PT
            chunk: list[Dict[str, Any]] = []
            row_heights: list[float] = []
            while row_index + len(chunk) < len(rows):
                row, row_height = rows[row_index + len(chunk)]
                if row_heights and sum(row_heights) + row_height > available:
                    break
                if not row_heights and row_height > available:
                    self._new_page(section, continuation=True)
                    available = self._remaining - TABLE_HEADER_HEIGHT_PT
                    continue
                chunk.append(row)
                row_heights.append(row_height)
            if not rows:
                row_heights = [TABLE_MIN_ROW_HEIGHT_PT]
            height = TABLE_HEADER_HEIGHT_PT + sum(row_heights)
            self._append_block(
                {
                    "blockId": f"{block.get('blockId') or 'table'}-{fragment}",
                    "sourceBlockId": str(block.get("blockId") or "table"),
                    "blockType": "table",
                    "columns": columns,
                    "rows": chunk,
                    "rowHeights": [round(value, 3) for value in row_heights],
                    "continued": fragment > 1,
                    "frame": _frame(self._cursor_y, height),
                    "evidenceClaimIds": list(block.get("evidenceClaimIds") or []),
                },
                height=height,
                gap=10,
            )
            row_index += len(chunk)
            fragment += 1
            if not rows:
                break

    def _rebalance_orphan_continuations(self) -> None:
        for page_index in range(1, len(self._pages)):
            page = self._pages[page_index]
            if not str(page.get("title") or "").endswith("(continued)"):
                continue
            content = [
                block
                for block in page.get("layoutBlocks") or []
                if block.get("blockType") != "continuation_heading"
            ]
            used_height = sum(
                float((block.get("frame") or {}).get("height") or 0)
                for block in content
            )
            if len(content) != 1 or used_height >= 120.0:
                continue
            previous = self._pages[page_index - 1]
            if previous.get("sectionId") != page.get("sectionId"):
                continue
            donors = [
                block
                for block in previous.get("layoutBlocks") or []
                if block.get("blockType") != "continuation_heading"
            ]
            if not donors:
                continue
            donor = donors[-1]
            target = content[0]
            donor_type = str(donor.get("blockType") or "")
            target_type = str(target.get("blockType") or "")
            same_source = str(donor.get("sourceBlockId") or donor.get("blockId") or "") \
                == str(target.get("sourceBlockId") or target.get("blockId") or "")

            if donor_type == target_type == "table" and same_source:
                donor_rows = donor.get("rows") or []
                donor_heights = donor.get("rowHeights") or []
                while (
                    len(donor_rows) > 1
                    and len(content) == 1
                    and float((target.get("frame") or {}).get("height") or 0) < 120.0
                ):
                    row_height = float(donor_heights.pop() if donor_heights else TABLE_MIN_ROW_HEIGHT_PT)
                    row = donor_rows.pop()
                    if float(target["frame"]["y"]) + float(target["frame"]["height"]) + row_height > PAGE_CONTENT_BOTTOM_PT:
                        donor_rows.append(row)
                        donor_heights.append(row_height)
                        break
                    target.setdefault("rows", []).insert(0, row)
                    target.setdefault("rowHeights", []).insert(0, round(row_height, 3))
                    donor["frame"]["height"] = round(float(donor["frame"]["height"]) - row_height, 3)
                    target["frame"]["height"] = round(float(target["frame"]["height"]) + row_height, 3)
                continue

            if donor_type not in {"list", "figure_legend"}:
                continue
            columns = max(1, int(donor.get("columns") or 1))
            donor_items = donor.get("items") or []
            donor_heights = donor.get("rowHeights") or []
            if len(donor_items) <= columns or not donor_heights:
                continue
            moved_height = float(donor_heights[-1])
            moved_count = min(columns, len(donor_items))
            moved_items = donor_items[-moved_count:]
            shifted_bottom = (
                float(target["frame"]["y"])
                + moved_height
                + 10.0
                + float(target["frame"]["height"])
            )
            if shifted_bottom > PAGE_CONTENT_BOTTOM_PT:
                continue
            del donor_items[-moved_count:]
            donor_heights.pop()
            donor["frame"]["height"] = round(
                float(donor["frame"]["height"]) - moved_height,
                3,
            )
            fragment = copy.deepcopy(donor)
            fragment["blockId"] = f"{donor.get('sourceBlockId') or donor.get('blockId')}-balanced"
            fragment["items"] = moved_items
            fragment["rowHeights"] = [round(moved_height, 3)]
            fragment["continued"] = True
            fragment["frame"] = _frame(
                float(target["frame"]["y"]),
                moved_height,
            )
            target["frame"]["y"] = round(
                float(target["frame"]["y"]) + moved_height + 10.0,
                3,
            )
            page["layoutBlocks"].insert(1, fragment)

    def layout(self, sections: Sequence[Mapping[str, Any]]) -> list[Dict[str, Any]]:
        for section in sections:
            self._page = None
            blocks = sorted(
                [row for row in section.get("blocks") or [] if isinstance(row, Mapping)],
                key=lambda row: int(row.get("readingOrder") or 0),
            )
            block_index = 0
            while block_index < len(blocks):
                block = blocks[block_index]
                block_type = str(block.get("blockType") or "")
                next_block = blocks[block_index + 1] if block_index + 1 < len(blocks) else None
                if (
                    block_type == "cad_figure"
                    and next_block
                    and next_block.get("blockType") == "figure_legend"
                    and str((block.get("payload") or {}).get("figureId") or "")
                    == str((next_block.get("payload") or {}).get("figureId") or "")
                ):
                    self._place_figure_with_legend(section, block, next_block)
                    block_index += 2
                    continue
                if block_type == "heading":
                    self._place_heading(section, block, next_block)
                elif block_type == "paragraph":
                    self._place_paragraph(section, block)
                elif block_type in {"note", "status_panel"}:
                    self._place_note(section, block)
                elif block_type in {"list", "figure_legend"}:
                    self._place_list(section, block)
                elif block_type in {"specification_table", "table", "source_table"}:
                    self._place_table(section, block)
                elif block_type == "cad_figure":
                    self._place_figure(section, block)
                else:
                    # Unsupported semantic blocks are visible, not silently dropped.
                    fallback = copy.deepcopy(dict(block))
                    fallback["payload"] = {
                        "text": f"Draft block '{block_type or 'unknown'}' requires a renderer."
                    }
                    self._place_note(section, fallback)
                block_index += 1
        # Keep constraints are applied before placement. The former late
        # rebalance pass moved final rows out of valid figure keys, lists, and
        # tables, creating the visible orphan pages it was meant to repair.
        return copy.deepcopy(self._pages)


def assert_pages_within_bounds(pages: Iterable[Mapping[str, Any]]) -> None:
    for page in pages:
        for block in page.get("layoutBlocks") or []:
            frame = block.get("frame") or {}
            top = float(frame.get("y") or 0)
            bottom = top + float(frame.get("height") or 0)
            if top < PAGE_CONTENT_TOP_PT - 1e-6 or bottom > PAGE_CONTENT_BOTTOM_PT + 1e-6:
                raise ValueError(
                    f"{page.get('pageId')} block {block.get('blockId')} exceeds the content bounds"
                )


def assert_no_orphan_continuation_pages(
    pages: Iterable[Mapping[str, Any]],
) -> None:
    for page in pages:
        if not str(page.get("title") or "").endswith("(continued)"):
            continue
        content_blocks = [
            block
            for block in page.get("layoutBlocks") or []
            if block.get("blockType") != "continuation_heading"
        ]
        used_height = sum(
            float((block.get("frame") or {}).get("height") or 0)
            for block in content_blocks
        )
        if len(content_blocks) == 1 and used_height < 120.0:
            raise ValueError(
                f"{page.get('pageId')} is an orphan continuation page"
            )
