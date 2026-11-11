"""Authored table grids and pure operations. No store, font engine or browser."""
from __future__ import annotations

from copy import deepcopy
import math
import re
import uuid

from .commands import DocumentEditError

TABLE_OPERATIONS = {"create_table", "modify_table"}
TABLE_NODES = {"table", "tableRow", "tableCell", "tableHeader"}
MAX_ROWS, MAX_COLUMNS, MAX_CELLS = 50, 12, 600


def fail(code="invalid_table_operation", message="Invalid authored table operation."):
    raise DocumentEditError(code, message)


def grid(table):
    """Return row-major anchors and a complete occupancy grid; never infer gaps."""
    rows, columns = table.get("content", []), table.get("attrs", {}).get("columns", [])
    if len(rows) > MAX_ROWS or len(columns) > MAX_COLUMNS or sum(len(r.get("content", [])) for r in rows) > MAX_CELLS:
        fail("table_too_large", "Tables are limited to 50 rows, 12 columns and 600 cells.")
    if not rows or not columns:
        fail("invalid_table_grid", "A table needs rows and columns.")
    occupied = [[None] * len(columns) for _ in rows]
    anchors = []
    for y, row in enumerate(rows):
        if not row.get("content"):
            fail("invalid_table_grid", "Every row needs a cell that starts in it.")
        x = 0
        for cell in row["content"]:
            while x < len(columns) and occupied[y][x] is not None:
                x += 1
            w, h = cell["attrs"].get("colspan", 1), cell["attrs"].get("rowspan", 1)
            if type(w) is not int or type(h) is not int or w < 1 or h < 1 or x + w > len(columns) or y + h > len(rows):
                fail("invalid_table_grid", "A cell span leaves the table.")
            entry = {"row": y, "column": x, "rowspan": h, "colspan": w, "cell": cell}
            for yy in range(y, y + h):
                for xx in range(x, x + w):
                    if occupied[yy][xx] is not None:
                        fail("invalid_table_grid", "Cells overlap.")
                    occupied[yy][xx] = entry
            anchors.append(entry)
            x += w
    if any(cell is None for row in occupied for cell in row):
        fail("invalid_table_grid", "Cells must tile the whole table.")
    return anchors, occupied


def column_widths(width, shares, *, canvas_rounding=False):
    """Collapsed-rule grid: W wide outside, W-1 between outer rule centres."""
    total = width - 1
    widths = [total * share / 1000 for share in shares[:-1]]
    if canvas_rounding:
        widths = [math.floor(value * 64) / 64 for value in widths]
    return widths + [total - sum(widths)]


def row_heights(count, cells, *, canvas_rounding=False):
    """Chromium's measured spanning-cell distribution (stable insertion ordering)."""
    heights = [max((cell["boxHeight"] for cell in cells if cell["row"] == row and cell["rowspan"] == 1), default=0)
               for row in range(count)]
    spans = []
    def first(a, b):
        ar, br = a["row"], b["row"]
        ae, be = ar + a["rowspan"], br + b["rowspan"]
        if ar == br and ae == be:
            return a["boxHeight"] > b["boxHeight"]
        if ar >= br and ae <= be:
            return True
        if br >= ar and be <= ae:
            return False
        # Blink: "lower rows win" means the smaller row index (supervisor: the brief's wording was ambiguous).
        return ar < br
    for cell in cells:
        if cell["rowspan"] <= 1:
            continue
        index = len(spans)
        while index and first(cell, spans[index - 1]):
            index -= 1
        spans.insert(index, cell)
    starts = {cell["row"] for cell in spans}
    for cell in spans:
        rows = list(range(cell["row"], cell["row"] + cell["rowspan"]))
        deficit = cell["boxHeight"] - sum(heights[row] for row in rows)
        if deficit <= 0:
            continue
        sharing = [row for row in rows[1:] if row in starts]
        if sharing:
            weights = [1] * len(sharing)
        else:
            sharing = [row for row in rows if heights[row] > 0]
            weights = [heights[row] for row in sharing]
        if not sharing:
            heights[rows[-1]] += deficit
            continue
        assigned, total = 0, sum(weights)
        for index, (row, weight) in enumerate(zip(sharing, weights)):
            part = deficit - assigned if index == len(sharing) - 1 else deficit * weight / total
            if canvas_rounding and index != len(sharing) - 1:
                part = math.floor(part * 64) / 64
            heights[row] += part
            assigned += part
    return heights


def _shares(values, total=1000):
    """Largest remainder with a lower bound of one; ties follow column order."""
    if not values or total < len(values):
        fail()
    remaining, active, result = total, list(range(len(values))), [0] * len(values)
    while active:
        weight = sum(values[i] for i in active)
        small = [i for i in active if remaining * values[i] / weight < 1]
        if not small:
            exact = {i: remaining * values[i] / weight for i in active}
            for i in active:
                result[i] = math.floor(exact[i])
            for i in sorted(active, key=lambda i: (-(exact[i] - result[i]), i))[:total - sum(result)]:
                result[i] += 1
            break
        for i in small:
            result[i] = 1
            remaining -= 1
            active.remove(i)
    return result


def describe(table):
    if table is None:
        return None
    return {"tableId": table["attrs"]["id"], "columnIds": [c["id"] for c in table["attrs"]["columns"]],
            "rows": [{"rowId": row["attrs"]["id"], "cellIds": [c["attrs"]["id"] for c in row["content"]]}
                     for row in table["content"]]}


def require_target(target):
    from .targets import rich_text_capabilities
    attributes = target.get("attributes") or {}
    if target.get("targetType") != "document_object" and (attributes.get("blockType") in {"table", "key_value_table", "bom_table"}
            or attributes.get("definitionId") or str(target.get("alias", "")).startswith("part.")):
        fail("table_not_authored", "Generated and BOM tables cannot be structurally edited.")
    caps = rich_text_capabilities(target) or {}
    if "table" not in caps.get("features", []) or 3 not in caps.get("schemaVersions", []):
        raise DocumentEditError("unsupported_rich_text_feature", "This target does not support authored tables.",
                                targets=[target.get("targetId")], features=["table"])
    if target.get("operation") == "read_only":
        fail("read_only_derived_field", "This text box is read-only.")
    return caps


def apply(value, operation, *, width, id_factory=None):
    """Copy, apply one operation and validate. Existing identities are never allocated again."""
    from .rich_text import validate, node_ids
    value = deepcopy(validate(value))
    if not isinstance(operation, dict):
        fail()
    used = node_ids(value)
    factory = id_factory or (lambda: "rt-" + str(uuid.uuid4()))
    def allocate():
        for _ in range(1024):
            identity = factory()
            if identity not in used:
                used.add(identity)
                return identity
        fail("invalid_table_operation", "Could not allocate a new table identity.")
    def paragraph():
        return {"type": "paragraph", "attrs": {"id": allocate()}}
    def cell(kind="tableCell", attrs=None):
        return {"type": kind, "attrs": {**(attrs or {}), "id": allocate()}, "content": [paragraph()]}
    def span(entry, name, value):
        entry[name] = value
        attrs = entry["cell"]["attrs"]
        if value == 1:
            attrs.pop(name, None)
        else:
            attrs[name] = value
    def drop_covered_rows(rows, anchors):
        # A row in which no cell starts is not a legal authored row: remove it and shrink the spans across it.
        for y in reversed(range(len(rows))):
            if not any(e["row"] == y for e in anchors):
                rows.pop(y)
                for e in anchors:
                    if e["row"] < y < e["row"] + e["rowspan"]:
                        span(e, "rowspan", e["rowspan"] - 1)
                    elif e["row"] > y:
                        e["row"] -= 1
    def rebuild(table, anchors):
        for row in table["content"]:
            row["content"] = []
        for entry in sorted(anchors, key=lambda e: (e["row"], e["column"])):
            table["content"][entry["row"]]["content"].append(entry["cell"])
    kind = operation.get("operation")
    common = {"operation", "targetId", "expectedContentHash", "legacyAlias"}
    blocks = value["doc"]["content"]
    if kind == "create_table":
        if set(operation) - common - {"afterId", "rows", "columns", "headerRow"}:
            fail()
        rows, columns = operation.get("rows"), operation.get("columns")
        if type(rows) is not int or type(columns) is not int or rows < 1 or columns < 1:
            fail()
        if rows > MAX_ROWS or columns > MAX_COLUMNS:
            fail("table_too_large")
        if "headerRow" in operation and type(operation["headerRow"]) is not bool:
            fail()
        position = len(blocks)
        if "afterId" in operation:
            position = next((i + 1 for i, b in enumerate(blocks) if b.get("attrs", {}).get("id") == operation["afterId"]), None)
            if position is None:
                fail("table_not_found")
        table = {"type": "table", "attrs": {"id": allocate(), "ownership": "authored", "style": "grid",
            "columns": [{"id": allocate(), "width": 1000 // columns + (i < 1000 % columns)} for i in range(columns)]},
            "content": [{"type": "tableRow", "attrs": {"id": allocate()},
                "content": [cell("tableHeader" if y == 0 and operation.get("headerRow") else "tableCell") for _ in range(columns)]}
                for y in range(rows)]}
        blocks.insert(position, table)
        physical = True
    elif kind == "modify_table":
        actions = {"insert_row": {"rowId", "position"}, "delete_row": {"rowId"},
                   "insert_column": {"columnId", "position"}, "delete_column": {"columnId"},
                   "merge_cells": {"cellIds"}, "split_cells": {"cellIds"}, "set_widths": {"widths"},
                   "set_cell_style": {"cellIds", "style"}, "set_table_style": {"style"}, "delete_table": set()}
        action = operation.get("action")
        if not isinstance(action, str) or action not in actions or set(operation) - common - {"tableId", "action"} - actions[action]:
            fail()
        if not actions[action] <= operation.keys():
            fail()
        table = next((b for b in blocks if b["type"] == "table" and b["attrs"]["id"] == operation.get("tableId")), None)
        if table is None:
            fail("table_not_found")
        anchors, occupied = grid(table)
        rows, columns = table["content"], table["attrs"]["columns"]
        physical = action in {"insert_column", "set_widths"}
        if action in {"insert_row", "delete_row", "insert_column", "delete_column"}:
            is_row = action.endswith("row")
            names = [r["attrs"]["id"] for r in rows] if is_row else [c["id"] for c in columns]
            reference = operation["rowId" if is_row else "columnId"]
            if reference not in names:
                fail("table_not_found")
            at = names.index(reference)
            insert = action.startswith("insert")
            if insert and operation["position"] not in ("before", "after"):
                fail()
            if not insert and len(names) == 1:
                fail(message="The only row or column cannot be deleted.")
            if insert and len(names) >= (MAX_ROWS if is_row else MAX_COLUMNS):
                fail("table_too_large")
            axis, dimension = ("row", "rowspan") if is_row else ("column", "colspan")
            line = at + (operation.get("position") == "after") if insert else at
            if insert:
                for entry in anchors:
                    start, end = entry[axis], entry[axis] + entry[dimension]
                    if start < line < end:
                        span(entry, dimension, entry[dimension] + 1)
                    elif start >= line:
                        entry[axis] += 1
                cross = len(columns) if is_row else len(rows)
                for other in range(cross):
                    covered = any(e[axis] <= line < e[axis] + e[dimension] and
                        e["column" if is_row else "row"] <= other < e["column" if is_row else "row"] + e["colspan" if is_row else "rowspan"] for e in anchors)
                    if not covered:
                        reference_cell = occupied[at][other] if is_row else occupied[other][at]
                        anchors.append({"row": line if is_row else other, "column": other if is_row else line,
                            "rowspan": 1, "colspan": 1, "cell": cell(reference_cell["cell"]["type"])})
                if is_row:
                    rows.insert(line, {"type": "tableRow", "attrs": {"id": allocate()}, "content": []})
                else:
                    new_width = math.floor(1000 / (len(columns) + 1) + .5)
                    for col, share in zip(columns, _shares([c["width"] for c in columns], 1000 - new_width)):
                        col["width"] = share
                    columns.insert(line, {"id": allocate(), "width": new_width})
            else:
                kept = []
                for entry in anchors:
                    start, end = entry[axis], entry[axis] + entry[dimension]
                    if start <= line < end:
                        if entry[dimension] == 1:
                            continue
                        span(entry, dimension, entry[dimension] - 1)
                    elif start > line:
                        entry[axis] -= 1
                    kept.append(entry)
                anchors = kept
                if is_row:
                    rows.pop(line)
                else:
                    columns.pop(line)
                    for col, share in zip(columns, _shares([c["width"] for c in columns])):
                        col["width"] = share
                    # Supervisor: the deleted column may have held a row's only starting cell; that row goes with
                    # it, as after a merge, instead of refusing the delete.
                    drop_covered_rows(rows, anchors)
            rebuild(table, anchors)
        elif action in {"merge_cells", "split_cells", "set_cell_style"}:
            ids = operation["cellIds"]
            if not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
                fail()
            selected = [e for e in anchors if e["cell"]["attrs"]["id"] in ids]
            if len(selected) != len(ids):
                fail("table_not_found")
            if action == "merge_cells":
                if len(selected) < 2:
                    fail("cells_not_rectangular")
                y0, x0 = min(e["row"] for e in selected), min(e["column"] for e in selected)
                y1, x1 = max(e["row"] + e["rowspan"] for e in selected), max(e["column"] + e["colspan"] for e in selected)
                if sum(e["rowspan"] * e["colspan"] for e in selected) != (y1 - y0) * (x1 - x0):
                    fail("cells_not_rectangular")
                anchor = occupied[y0][x0]
                paragraphs = list(anchor["cell"]["content"])
                for entry in selected:
                    if entry is anchor:
                        continue
                    content = entry["cell"]["content"]
                    if len(content) == 1 and not content[0].get("content"):
                        continue
                    paragraphs.extend(content)
                anchor["cell"]["content"] = paragraphs
                span(anchor, "rowspan", y1 - y0)
                span(anchor, "colspan", x1 - x0)
                anchors = [e for e in anchors if e is anchor or e["cell"]["attrs"]["id"] not in ids]
                drop_covered_rows(rows, anchors)
                rebuild(table, anchors)
            elif action == "split_cells":
                if any(e["rowspan"] == e["colspan"] == 1 for e in selected):
                    fail()
                for e in selected:
                    attrs = {k: v for k, v in e["cell"]["attrs"].items() if k in {"fill", "verticalAlign"}}
                    for y in range(e["row"], e["row"] + e["rowspan"]):
                        for x in range(e["column"], e["column"] + e["colspan"]):
                            if (y, x) != (e["row"], e["column"]):
                                anchors.append({"row": y, "column": x, "rowspan": 1, "colspan": 1, "cell": cell(e["cell"]["type"], attrs)})
                    span(e, "rowspan", 1)
                    span(e, "colspan", 1)
                rebuild(table, anchors)
            else:
                style = operation["style"]
                if not isinstance(style, dict) or not style or set(style) - {"header", "fill", "verticalAlign"}:
                    fail()
                if "header" in style and type(style["header"]) is not bool:
                    fail()
                if "fill" in style and style["fill"] is not None and (not isinstance(style["fill"], str) or re.fullmatch(r"#[0-9a-fA-F]{6}", style["fill"]) is None):
                    fail()
                if "verticalAlign" in style and style["verticalAlign"] not in ("top", "middle", "bottom"):
                    fail()
                for e in selected:
                    node = e["cell"]
                    if "header" in style:
                        node["type"] = "tableHeader" if style["header"] else "tableCell"
                    for name in ("fill", "verticalAlign"):
                        if name in style:
                            if style[name] is None or style[name] == "top":
                                node["attrs"].pop(name, None)
                            else:
                                node["attrs"][name] = style[name].lower()
        elif action == "set_widths":
            widths = operation["widths"]
            if (not isinstance(widths, list) or any(not isinstance(c, dict) or set(c) != {"columnId", "width"} for c in widths)
                    or len(widths) != len(columns) or any(not isinstance(c["columnId"], str) for c in widths)
                    or len({c["columnId"] for c in widths}) != len(widths)):
                fail()
            if {c["columnId"] for c in widths} != {c["id"] for c in columns}:
                fail("table_not_found")
            if any(type(c["width"]) is not int or c["width"] < 1 for c in widths) or sum(c["width"] for c in widths) != 1000:
                fail()
            by_id = {c["columnId"]: c["width"] for c in widths}
            for c in columns:
                c["width"] = by_id[c["id"]]
        elif action == "set_table_style":
            if operation["style"] not in ("grid", "plain"):
                fail()
            table["attrs"]["style"] = operation["style"]
        else:
            blocks.remove(table)
            table = None
            if not blocks:
                blocks.append(paragraph())
    else:
        fail()
    value["schemaVersion"] = 3
    try:
        result = validate(value)
    except DocumentEditError as error:
        # Supervisor: growth past the box's stored bound is a table refusal that says what to do. (The bound stops
        # an empty table at about 46 x 12 and one with short text in every cell at about 400 cells.)
        if error.code == "rich_text_too_large" and (kind == "create_table" or operation.get("action") in {
                "insert_row", "insert_column", "split_cells"}):
            fail("table_too_large", "This table would exceed what one text box can hold (96 KiB of content). "
                 "Use fewer cells, or put the rest in a second table in another text box.")
        raise
    if physical and table is not None and any(w < 12 for w in column_widths(width, [c["width"] for c in table["attrs"]["columns"]])):
        fail("table_column_too_narrow", "Each column must be at least 12 points wide.")
    return result, describe(table)


def coalesce_tables(targets, operations, widths):
    """Sequential per-target operations, retaining original operation order in results."""
    from .rich_text import from_plain, require_enabled, require_capabilities
    require_enabled()
    values, first, results = {}, {}, []
    for index, operation in enumerate(operations):
        if operation["operation"] not in TABLE_OPERATIONS:
            continue
        key = operation["targetId"]
        target = targets.get(key)
        if target is None:
            fail("table_not_found")
        caps = require_target(target)
        if key not in values:
            rich = target.get("richField") or {}
            values[key] = rich.get("richText") if rich.get("isRichText") else from_plain(target["text"])
            first[key] = operation
        values[key], table = apply(values[key], operation, width=widths[key])
        require_capabilities(values[key], caps, targets=[key])
        results.append({"operationIndex": index, "targetId": key, "table": table})
    output, emitted = [], set()
    for operation in operations:
        key = operation["targetId"]
        if key in values:
            if key not in emitted:
                output.append({"operation": "replace_rich_text", "targetId": key,
                    "expectedContentHash": first[key]["expectedContentHash"], "richText": values[key]})
                emitted.add(key)
        else:
            output.append(operation)
    return output, results
