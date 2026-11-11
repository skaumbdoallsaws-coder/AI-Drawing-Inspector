"""P3b-1 authored tables: model, operations, measured geometry and native exports."""
from collections import Counter
from copy import deepcopy
import json
import math
from pathlib import Path
import uuid

import pytest

from ai_inspector.documentation import rich_text as rich
from ai_inspector.documentation import tables
from ai_inspector.documentation.commands import DocumentEditError, canonical_bytes, operation_store
from ai_inspector.documentation.rich_layout import content_model, layout_text, ObjectLayout, draw_pdf_object, prepare_pdf_objects
from ai_inspector.documentation.rich_docx import write_content
from ai_inspector.documentation.search import edit_rich, find_document_text
from ai_inspector.documentation.targets import rich_text_capabilities
from tests.test_documentation_rich_text import scene, envelope, KIND, PAGE, OBJECT
from tests.test_documentation_refresh import mmle_client
from tests.test_documentation_rich_blocks import narrative  # noqa: F401  (operations manual with eligible blocks)

ROOT = Path(__file__).resolve().parents[1]
CAPS = {"schemaVersions": [1, 2, 3], "features": list(rich.FEATURES), "listDepth": 6}


def ids(start=100):
    counter = iter(range(start, start + 100000))
    return lambda: "rt-" + str(uuid.UUID(int=next(counter)))


def table_value(rows=3, columns=4, *, header=True, text=True):
    value, _ = tables.apply(envelope("Before"), {"operation": "create_table", "rows": rows,
        "columns": columns, "headerRow": header}, width=800, id_factory=ids())
    table = value["doc"]["content"][1]
    if text:
        for y, row in enumerate(table["content"]):
            for x, cell in enumerate(row["content"]):
                cell["content"][0]["content"] = [{"type": "text", "text": f"R{y}C{x}"}]
    return rich.validate(value)


def table_of(value):
    return next(n for n in value["doc"]["content"] if n["type"] == "table")


def cells(value):
    return [entry["cell"] for entry in tables.grid(table_of(value))[0]]


def modify(value, action, *, width=800, **fields):
    return tables.apply(value, {"operation": "modify_table", "tableId": table_of(value)["attrs"]["id"],
        "action": action, **fields}, width=width, id_factory=ids(10000))


def refused(code, callback):
    with pytest.raises(DocumentEditError) as error:
        callback()
    assert error.value.code == code
    return error.value


def test_old_vectors_and_minimal_versions():
    vectors = json.loads((ROOT / "tests/fixtures/rich_text_v2_vectors.json").read_text(encoding="utf-8"))
    # Use the same vector shape as the typography gate.
    for vector in vectors:
        if "expected" in vector:
            expected = vector["expected"]
            assert canonical_bytes(rich.validate(expected)) == canonical_bytes(expected)
    for version in (1, 2, 3):
        value = envelope("unchanged")
        value["schemaVersion"] = version
        assert rich.validate(value) == envelope("unchanged")
    value = table_value()
    assert rich.validate(value)["schemaVersion"] == 3
    assert rich.used_features(value) == {"features": ["table"], "listDepth": 0}
    for version in (1, 2):
        old = deepcopy(value)
        old["schemaVersion"] = version
        refused("unsupported_rich_text_schema", lambda: rich.validate(old))
    stripped, result = modify(value, "delete_table")
    assert result is None and stripped == envelope("Before")


def test_node_and_byte_budgets_depend_on_table(monkeypatch):
    def many(count, with_table):
        value = table_value(1, 1, text=False) if with_table else envelope("")
        # doc + first paragraph + (table,row,cell,paragraph when present) + leaves
        value["doc"]["content"][0]["content"] = [{"type": "text", "text": "x"} for _ in range(count)]
        return value
    rich.validate(many(510, False))
    refused("rich_text_too_large", lambda: rich.validate(many(511, False)))
    rich.validate(many(2042, True))
    refused("rich_text_too_large", lambda: rich.validate(many(2043, True)))
    for with_table, limit in ((False, rich.MAX_BYTES), (True, rich.TABLE_MAX_BYTES)):
        value = many(1, with_table)
        leaf = value["doc"]["content"][0]["content"][0]
        leaf["text"] = "x" * (limit - len(canonical_bytes(rich.validate(value))) + 1)
        assert len(canonical_bytes(rich.validate(value))) == limit
        leaf["text"] += "x"
        refused("rich_text_too_large", lambda: rich.validate(value))
    # Cell and row caps are independent of the canonical JSON ceiling.
    monkeypatch.setattr(rich, "TABLE_MAX_BYTES", 1024 * 1024)
    rich.validate(table_value(50, 12, text=False))


@pytest.mark.parametrize("mutation,code", [
    (lambda t: t["attrs"]["columns"][0].update(width=249), "invalid_table_grid"),
    (lambda t: t["attrs"]["columns"][0].update(width=True), "invalid_table_grid"),
    (lambda t: t["attrs"]["columns"][0].update(id=t["attrs"]["id"]), "rich_text_node_id_collision"),
    (lambda t: t["attrs"].update(ownership="generated"), "invalid_table_grid"),
    (lambda t: t["attrs"].update(style="striped"), "invalid_table_grid"),
    (lambda t: t["attrs"].update(extra=1), "invalid_rich_text"),
    (lambda t: t["content"][0]["content"][0]["attrs"].update(colspan=0), "invalid_table_grid"),
    (lambda t: t["content"][0]["content"][0]["attrs"].update(rowspan=4), "invalid_table_grid"),
    (lambda t: t["content"][0]["content"][0]["attrs"].update(colspan=2), "invalid_table_grid"),
    (lambda t: t["content"][0]["content"].pop(), "invalid_table_grid"),
    (lambda t: t["content"][1].update(content=[]), "invalid_table_grid"),
    (lambda t: t["content"][0]["content"][0]["attrs"].update(verticalAlign="baseline"), "invalid_table_grid"),
    (lambda t: t["content"][0]["content"][0]["attrs"].update(fill="red"), "invalid_rich_text"),
    (lambda t: t["content"][0]["content"][0]["content"][0]["attrs"].update(namedStyle="title"), "invalid_rich_text"),
])
def test_validator_refusals(mutation, code):
    value = table_value()
    mutation(table_of(value))
    refused(code, lambda: rich.validate(value))


def test_grid_overlap_caps_placement_and_normalization():
    value = table_value()
    table = table_of(value)
    # A lower row's colspan crosses a cell carried from the previous row.
    table["content"][0]["content"][1]["attrs"]["rowspan"] = 2
    table["content"][1]["content"].pop(1)
    table["content"][1]["content"][0]["attrs"]["colspan"] = 2
    refused("invalid_table_grid", lambda: rich.validate(value))
    for count, axis in ((51, "rows"), (13, "columns")):
        refused("table_too_large", lambda: tables.apply(envelope(), {
            "operation": "create_table", "rows": count if axis == "rows" else 1,
            "columns": count if axis == "columns" else 1}, width=800))
    value = table_value()
    table = table_of(value)
    table["content"][0]["content"][0]["attrs"].update(colspan=1, rowspan=1, verticalAlign="top", fill="#ABcDEF")
    normalized = cells(rich.validate(value))[0]["attrs"]
    assert normalized["fill"] == "#abcdef" and not {"colspan", "rowspan", "verticalAlign"} & normalized.keys()
    nested = deepcopy(value)
    nested_table = table_of(nested)
    nested_table["content"][0]["content"][0]["content"] = [deepcopy(table)]
    refused("invalid_table_grid", lambda: rich.validate(nested))
    for kind in ("heading", "bulletList"):
        bad = table_value()
        p = cells(bad)[0]["content"][0]
        p["type"] = kind
        if kind == "heading":
            p["attrs"]["level"] = 1
        else:
            p["content"] = [{"type": "listItem", "attrs": {"id": ids(9000)()}, "content": [envelope("cell", start=9001)["doc"]["content"][0]]}]
        refused("invalid_table_grid", lambda: rich.validate(bad))
    bad = table_value()
    bad["doc"]["content"] = [{"type": "bulletList", "attrs": {"id": ids(8000)()}, "content": [
        {"type": "listItem", "attrs": {"id": ids(8001)()}, "content": [bad["doc"]["content"][0], table_of(bad)]}]}]
    refused("invalid_table_grid", lambda: rich.validate(bad))


def test_row_insert_delete_preserves_ids_and_moves_spanning_content():
    value = table_value()
    table = table_of(value)
    survivor = cells(value)[0]
    value, _ = modify(value, "merge_cells", cellIds=[survivor["attrs"]["id"], cells(value)[4]["attrs"]["id"]])
    before = deepcopy(next(c for c in cells(value) if c["attrs"]["id"] == survivor["attrs"]["id"]))
    original_ids = rich.node_ids(value)
    row = table_of(value)["content"][1]["attrs"]["id"]
    inserted, result = modify(value, "insert_row", rowId=row, position="before")
    assert original_ids <= rich.node_ids(inserted)
    assert len(result["rows"]) == 4
    spanning = next(c for c in cells(inserted) if c["attrs"]["id"] == survivor["attrs"]["id"])
    assert spanning["attrs"]["rowspan"] == 3 and spanning["content"] == before["content"]
    first_row = table_of(value)["content"][0]["attrs"]["id"]
    deleted, _ = modify(value, "delete_row", rowId=first_row)
    moved = cells(deleted)[0]
    assert moved["attrs"]["id"] == survivor["attrs"]["id"] and moved["content"] == before["content"]
    assert "rowspan" not in moved["attrs"]


def test_column_insert_delete_and_largest_remainder():
    value = table_value(2, 3)
    old = rich.node_ids(value)
    cols = table_of(value)["attrs"]["columns"]
    assert [c["width"] for c in cols] == [334, 333, 333]
    value, result = modify(value, "insert_column", columnId=cols[1]["id"], position="before")
    assert old <= rich.node_ids(value)
    assert [c["width"] for c in table_of(value)["attrs"]["columns"]] == [250, 250, 250, 250]
    assert len(set(result["columnIds"])) == 4
    value, _ = modify(value, "delete_column", columnId=result["columnIds"][1])
    assert [c["width"] for c in table_of(value)["attrs"]["columns"]] == [334, 333, 333]
    assert rich.node_ids(value) == old
    assert tables._shares([1, 998], 500) == [1, 499]
    # A colspan grows through an insertion and shrinks when that column is deleted.
    value, _ = modify(value, "merge_cells", cellIds=[c["attrs"]["id"] for c in cells(value)[:2]])
    anchor = cells(value)[0]["attrs"]["id"]
    col = table_of(value)["attrs"]["columns"][1]["id"]
    inserted, result = modify(value, "insert_column", columnId=col, position="before")
    assert cells(inserted)[0]["attrs"]["colspan"] == 3
    removed, _ = modify(inserted, "delete_column", columnId=result["columnIds"][1])
    assert cells(removed)[0]["attrs"]["id"] == anchor and cells(removed)[0]["attrs"]["colspan"] == 2


def test_merge_order_empty_cells_split_and_row_compaction():
    value = table_value(3, 2)
    originals = deepcopy(cells(value))
    selected = [c["attrs"]["id"] for c in originals[:4]]
    cells(value)[1]["content"][0].pop("content")
    merged, _ = modify(value, "merge_cells", cellIds=list(reversed(selected)))
    anchor = cells(merged)[0]
    assert anchor["attrs"]["id"] == selected[0] and anchor["type"] == "tableHeader"
    assert anchor["content"] == [originals[i]["content"][0] for i in (0, 2, 3)]
    assert len(table_of(merged)["content"]) == 2 and "rowspan" not in anchor["attrs"]
    styled, _ = modify(merged, "set_cell_style", cellIds=[selected[0]], style={"fill": "#ABCDEF", "verticalAlign": "bottom"})
    split, _ = modify(styled, "split_cells", cellIds=[selected[0]])
    first, second = cells(split)[:2]
    assert first["content"] == anchor["content"] and first["attrs"]["id"] == selected[0]
    assert second["type"] == "tableHeader" and second["attrs"]["fill"] == "#abcdef"
    assert second["attrs"]["verticalAlign"] == "bottom" and not second["content"][0].get("content")
    assert second["attrs"]["id"] not in rich.node_ids(value)
    cleared, _ = modify(split, "set_cell_style", cellIds=[selected[0]], style={"header": False, "fill": None, "verticalAlign": "top"})
    assert cells(cleared)[0]["type"] == "tableCell"
    assert not {"fill", "verticalAlign"} & cells(cleared)[0]["attrs"].keys()
    plain, _ = modify(cleared, "set_table_style", style="plain")
    assert table_of(plain)["attrs"]["style"] == "plain"


def test_operation_refusals_are_pure_and_physical_minimum():
    value = table_value()
    before = canonical_bytes(value)
    table = table_of(value)
    options = [
        ("table_not_found", "delete_row", {"rowId": "missing"}),
        ("table_not_found", "delete_column", {"columnId": "missing"}),
        ("table_not_found", "merge_cells", {"cellIds": ["missing", cells(value)[0]["attrs"]["id"]]}),
        ("cells_not_rectangular", "merge_cells", {"cellIds": [cells(value)[0]["attrs"]["id"], cells(value)[5]["attrs"]["id"]]}),
        ("invalid_table_operation", "split_cells", {"cellIds": [cells(value)[0]["attrs"]["id"]]}),
        ("invalid_table_operation", "insert_row", {"rowId": table["content"][0]["attrs"]["id"], "position": {}}),
        ("invalid_table_operation", "set_table_style", {"style": {}}),
        ("invalid_table_operation", "set_cell_style", {"cellIds": [cells(value)[0]["attrs"]["id"]], "style": {"header": 1}}),
    ]
    for code, action, fields in options:
        refused(code, lambda: modify(value, action, **fields))
        assert canonical_bytes(value) == before
    widths = [{"columnId": c["id"], "width": n} for c, n in zip(table["attrs"]["columns"], [1, 333, 333, 333])]
    refused("table_column_too_narrow", lambda: modify(value, "set_widths", widths=widths))
    widths[0]["columnId"] = "missing"
    refused("table_not_found", lambda: modify(value, "set_widths", widths=widths))
    refused("table_column_too_narrow", lambda: tables.apply(envelope(), {"operation": "create_table", "rows": 1, "columns": 4}, width=48))
    one = table_value(1, 1)
    refused("invalid_table_operation", lambda: modify(one, "delete_row", rowId=table_of(one)["content"][0]["attrs"]["id"]))
    refused("invalid_table_operation", lambda: modify(one, "delete_column", columnId=table_of(one)["attrs"]["columns"][0]["id"]))
    value = table_value(1, 2)
    refused("table_column_too_narrow", lambda: modify(value, "insert_column", width=30,
        columnId=table_of(value)["attrs"]["columns"][0]["id"], position="after"))
    only_table = table_value(1, 1)
    only_table["doc"]["content"].pop(0)
    empty, result = modify(only_table, "delete_table")
    assert result is None and rich.plain_text(empty) == "" and empty["schemaVersion"] == 1


def test_whole_replace_reorders_rows_ids_and_reserved_columns(scene):
    value = table_value()
    scene.edit(value)
    reordered = deepcopy(value)
    table_of(reordered)["content"].reverse()
    scene.batch(reordered)
    assert scene.value() == reordered and rich.node_ids(scene.value()) == rich.node_ids(value)
    scene.add("document-object-other")
    collision = envelope("other", start=20000)
    collision["doc"]["content"][0]["attrs"]["id"] = table_of(value)["attrs"]["columns"][0]["id"]
    refused("rich_text_node_id_collision", lambda: scene.edit(collision, "document-object-other"))


def test_projection_find_and_ranges_inside_cells(scene):
    value = table_value(2, 2)
    assert rich.plain_text(value) == "Before\nR0C0\nR0C1\nR1C0\nR1C1"
    scene.edit(value)
    state, _, targets = scene.snapshot()
    found, _ = find_document_text(state, targets, {"query": "R", "scopeIds": [OBJECT], "caseSensitive": True})
    assert [(m["start"], m["end"]) for m in found["matches"]] == [(7, 8), (12, 13), (17, 18), (22, 23)]
    base = {"targetId": OBJECT, "expectedContentHash": "h", "start": 7, "end": 11, "expectedText": "R0C0"}
    changed = edit_rich(value, {**base, "operation": "replace_range", "text": "Changed"}, CAPS, OBJECT)
    assert rich.node_ids(changed) == rich.node_ids(value)
    assert cells(changed)[1:] == cells(value)[1:] and changed["schemaVersion"] == 3
    formatted = edit_rich(value, {**base, "operation": "format_range", "add": [{"feature": "italic"}]}, CAPS, OBJECT)
    assert cells(formatted)[0]["content"][0]["content"][0]["marks"] == [{"type": "italic"}]
    assert cells(formatted)[1:] == cells(value)[1:]
    refused("invalid_text_range", lambda: edit_rich(value, {**base, "operation": "replace_range",
        "end": 12, "expectedText": "R0C0\n", "text": ""}, CAPS, OBJECT))


def test_measured_chromium_row_fixture_exact():
    fixture = json.loads((ROOT / "tests/fixtures/documentation_table_row_heights.json").read_text(encoding="utf-8"))
    assert len(fixture["cases"]) == 160
    for index, case in enumerate(fixture["cases"]):
        assert tables.row_heights(len(case["rowHeights"]), case["cells"], canvas_rounding=True) == case["rowHeights"], index


@pytest.mark.parametrize("width,shares", [(400, [250] * 4), (319.25, [334, 333, 333]), (101, [120, 330, 550])])
def test_column_edges_and_content_inset(width, shares):
    value = table_value(1, len(shares))
    for col, share in zip(table_of(value)["attrs"]["columns"], shares):
        col["width"] = share
    plan = layout_text(value, (20, 30, 20 + width, 800), {"fontSize": 10}, canvas_rounding=True)
    table = plan.tables[0]
    expected = [math.floor((width - 1) * s / 1000 * 64) / 64 for s in shares[:-1]]
    expected.append(width - 1 - sum(expected))
    assert table.column_edges == pytest.approx([20.5] + [20.5 + sum(expected[:i]) for i in range(1, len(shares) + 1)])
    for cell in table.cells.values():
        assert cell.content_box == pytest.approx((cell.box[0] + 4.5, cell.box[1] + 4.5, cell.box[2] - 4.5, cell.box[3] - 4.5))


def test_vertical_alignment_headers_and_block_flow():
    value = table_value(1, 3)
    content = cells(value)
    content[0]["content"][0]["content"] = [{"type": "text", "text": "One\nTwo\nThree"}]
    content[1]["attrs"]["verticalAlign"] = "middle"
    content[2]["attrs"]["verticalAlign"] = "bottom"
    value["doc"]["content"].append(envelope("After", start=5000)["doc"]["content"][0])
    plan = layout_text(value, (0, 0, 400, 800), {"fontSize": 10})
    table = plan.tables[0]
    assert table.box == pytest.approx((0, 12, 400, 58))
    assert plan.measured_height == pytest.approx(70)
    by_cell = list(table.cells.values())
    assert [c.layout.lines[0].top for c in by_cell] == pytest.approx([17, 29, 41])
    assert all(r.bold and r.font_size == 10 for c in by_cell for line in c.layout.lines for r in line.runs)
    assert all(c.model.fill == "#e9eef2" for c in by_cell)
    narrow = layout_text(value, (0, 0, 30, 800), {"fontSize": 10})
    assert narrow.overflow and "table_column_too_narrow" in narrow.reasons


def export_pair(value):
    import fitz
    from docx import Document
    plan = layout_text(value, (20, 20, 420, 700), {"fontSize": 10})
    pdf = fitz.open()
    page = pdf.new_page(width=500, height=800)
    draw_pdf_object(fitz, page, ObjectLayout({"pageId": PAGE, "targetId": OBJECT},
        (17, 17, 423, 703), {"fontSize": 10, "fill": "#ffffff"}, False, plan))
    doc = Document()
    cell = doc.add_table(rows=1, cols=1).cell(0, 0)
    write_content(doc, plan.content, {"pageId": PAGE, "targetId": OBJECT}, cell.add_paragraph,
        first=cell.paragraphs[0], container=cell, table_width=400)
    return pdf, doc, plan


def test_pdf_text_counts_positions_fills_and_rule_paint_order():
    value = table_value(2, 2)
    for cell in cells(value):
        cell["content"][0]["content"][0]["text"] = "Repeated"
    pdf, _, plan = export_pair(value)
    page = pdf[0]
    assert Counter(page.get_text().split()) == Counter({"Before": 1, "Repeated": 4})
    actual = [span for block in page.get_text("dict")["blocks"] if "lines" in block
              for line in block["lines"] for span in line["spans"]]
    expected = [r for line in plan.lines for r in line.runs]
    assert [s["text"] for s in actual] == [r.text for r in expected]
    for span, run in zip(actual, expected):
        assert span["origin"] == pytest.approx((run.x, run.baseline), abs=.01)
        assert span["size"] == pytest.approx(run.font_size)
    drawings = page.get_drawings()
    fills = [d for d in drawings if d["fill"] is not None]
    rules = [d for d in drawings if d["color"] is not None]
    assert len(fills) == 3 and rules
    assert all(d["width"] == 1 for d in rules)
    assert max(d["seqno"] for d in drawings) < min(t["seqno"] for t in page.get_texttrace())
    pdf.close()


def test_docx_nested_grid_spans_fills_borders_and_native_runs():
    from docx.oxml.ns import qn
    value = table_value()
    value, _ = modify(value, "merge_cells", cellIds=[c["attrs"]["id"] for c in cells(value)[:2]])
    anchors = tables.grid(table_of(value))[0]
    selected = [e["cell"]["attrs"]["id"] for e in anchors if e["column"] == 2 and e["row"] in (1, 2)]
    value, _ = modify(value, "merge_cells", cellIds=selected)
    value, _ = modify(value, "set_cell_style", cellIds=[selected[0]], style={"fill": "#ABCDEF", "verticalAlign": "middle"})
    pdf, doc, plan = export_pair(value)
    table = doc.tables[0]._tbl.xpath("./w:tr/w:tc/w:tbl")[0]
    assert table.xpath("./w:tblPr/w:tblLayout/@w:type") == ["fixed"]
    assert sum(map(int, table.xpath("./w:tblGrid/w:gridCol/@w:w"))) == round(399 * 20)
    assert table.xpath(".//w:gridSpan/@w:val") == ["2"]
    assert table.xpath(".//w:vMerge/@w:val") == ["restart", "continue"]
    continuation = table.xpath(".//w:tc[w:tcPr/w:vMerge[@w:val='continue']]")[0]
    assert len(continuation.xpath("./w:p")) == 1 and not continuation.xpath(".//w:t")
    assert not table.xpath(".//w:trHeight")
    assert len(table.xpath("./w:tr/w:trPr/w:cantSplit")) == 3
    assert set(table.xpath(".//w:tcMar/*/@w:w")) == {"90"}
    assert set(table.xpath(".//w:tcBorders/*/@w:sz")) == {"8"}
    assert set(table.xpath(".//w:tcBorders/*/@w:color")) == {"8A98A5"}
    assert "ABCDEF" in table.xpath(".//w:shd/@w:fill") and "center" in table.xpath(".//w:vAlign/@w:val")
    assert table.xpath("./w:tr[1]//w:r/w:rPr/w:b/@w:val") and set(table.xpath("./w:tr[1]//w:r/w:rPr/w:b/@w:val")) == {"1"}
    expected = [r.text for block in content_model(value).blocks if hasattr(block, "cells") for c in block.cells for p in c.content.paragraphs for r in p.runs]
    assert table.xpath(".//w:t/text()") == expected
    plain, _ = modify(value, "set_table_style", style="plain")
    pdf.close()
    pdf, doc, _ = export_pair(plain)
    assert set(doc.tables[0]._tbl.xpath(".//w:tbl//w:tcBorders/*/@w:val")) == {"nil"}
    assert not [d for d in pdf[0].get_drawings() if d.get("color") is not None]
    pdf.close()


def test_preflight_reports_table_width_and_height_targets():
    import fitz
    value = table_value()
    item = {"type": "text", "content": value, "frame": {"x": .1, "y": .1, "width": .03, "height": .05}}
    document = {"pages": [{"pageId": PAGE, "documentationObjects": {OBJECT: item}}]}
    error = refused("layout_overflow", lambda: prepare_pdf_objects(fitz, document, (960, 720)))
    assert error.details["targets"][0]["targetId"] == OBJECT
    assert "table_column_too_narrow" in error.details["targets"][0]["reasons"]


def test_batch_limits_coalescing_and_capabilities(scene, monkeypatch):
    scene.edit(table_value())
    _, _, targets = scene.snapshot()
    table = table_of(scene.value())
    def op(action, **extra):
        return {"operation": "modify_table", "targetId": OBJECT, "expectedContentHash": "h",
                "tableId": table["attrs"]["id"], "action": action, **extra}
    group = [op("set_table_style", style="plain"), op("set_cell_style", cellIds=[cells(scene.value())[0]["attrs"]["id"]], style={"fill": "#123456"})]
    writes, result = tables.coalesce_tables(targets, group, {OBJECT: 800})
    assert len(writes) == 1 and writes[0]["expectedContentHash"] == "h"
    assert table_of(writes[0]["richText"])["attrs"]["style"] == "plain"
    assert cells(writes[0]["richText"])[0]["attrs"]["fill"] == "#123456"
    assert [r["operationIndex"] for r in result] == [0, 1]
    assert result[0]["table"] == tables.describe(table)
    assert operation_store(group * 12) == "scene"
    refused("invalid_table_operation", lambda: operation_store(group * 12 + group[:1]))
    for kind in ("replace_text", "replace_rich_text", "replace_range", "format_range"):
        refused("invalid_table_operation", lambda: operation_store(group + [{"operation": kind, "targetId": OBJECT}]))
    other = [{"operation": "replace_text", "targetId": f"other-{i}"} for i in range(12)]
    assert operation_store(group + other) == "scene"
    refused("invalid_document_operation", lambda: operation_store(group + other + [{"operation": "replace_text", "targetId": "other-13"}]))
    for block in ("table", "key_value_table", "bom_table"):
        refused("table_not_authored", lambda: tables.require_target({"targetType": "page_element", "attributes": {"blockType": block}}))
    refused("unsupported_rich_text_feature", lambda: tables.require_target({"targetType": "page_element", "documentType": KIND,
        "attributes": {"blockType": "paragraph"}}))
    import ai_inspector.documentation.targets as target_module
    monkeypatch.setattr(target_module, "rich_text_capabilities", lambda t: {**CAPS, "features": ["bold"]})
    refused("unsupported_rich_text_feature", lambda: tables.require_target(targets[OBJECT]))


def test_sage_table_sequence_receipt_retry_and_exact_undo(mmle_client, monkeypatch):
    import server
    from tests.test_codex_documentation_tools import gateway, call
    monkeypatch.setenv(rich.FEATURE_FLAG, "on")
    host = server._DocumentationAgentHost()
    # Supervisor: the turn's 120 s limit is not under test; a loaded machine ran past it (codex_run_closed).
    reader = gateway(host, "MMLE-50D", timeout=3600)
    snapshot = host.document_snapshot("MMLE-50D", KIND)
    state = snapshot["state"]
    page = snapshot["document"]["pages"][0]["pageId"]
    route = "/api/operations-manual/MMLE-50D/documentation-scene/commands"
    response = mmle_client.post(route, json={"baseRevision": state["sceneRevision"],
        "sourceRevision": state["sourceRevision"], "manualPlanRevision": state["manualPlanRevision"],
        "operation": "add_object", "pageId": page, "targetType": "document_object", "targetId": OBJECT,
            "documentObject": {"objectId": OBJECT, "type": "text", "name": "Table proof", "source": "user",
                "content": "Plain pre-image", "frame": {"x": .1, "y": .2, "width": .75, "height": .5}}})
    assert response.status_code == 200, response.text
    snapshot = host.document_snapshot("MMLE-50D", KIND)
    target = next(t for t in snapshot["targets"].values() if t["alias"] == OBJECT)
    def batch(operations, request):
        current = host.document_snapshot("MMLE-50D", KIND)
        read = call(reader, "read_document_pages", {"documentType": KIND, "targets": [{"targetId": target["targetId"]}]})
        assert read["ok"], read
        args = {"documentId": current["state"]["documentId"], "expectedRevision": current["state"]["revision"],
            "requestId": request, "operations": [{**o, "targetId": target["targetId"],
                "expectedContentHash": current["hashes"][target["targetId"]]} for o in operations]}
        result = call(reader, "apply_document_edits", args)
        assert result["ok"], result
        assert call(reader, "apply_document_edits", args) == result
        return result["data"]["receipt"]
    created = batch([{"operation": "create_table", "rows": 2, "columns": 3, "headerRow": True}], "table-create")
    identity = created["operationResults"][0]["table"]
    snapshot = host.document_snapshot("MMLE-50D", KIND)
    original = deepcopy(snapshot["targets"][target["targetId"]]["richField"]["richText"])
    full = call(reader, "read_document_pages", {"documentType": KIND, "targets": [{"targetId": target["targetId"]}]})["data"]
    bad = {"documentId": full["documentId"], "expectedRevision": full["revision"], "requestId": "table-atomic-refusal",
        "operations": [{"operation": "modify_table", "targetId": target["targetId"],
            "expectedContentHash": full["targets"][0]["contentHash"], "tableId": identity["tableId"], **action} for action in (
                {"action": "set_table_style", "style": "plain"}, {"action": "delete_row", "rowId": "missing"})]}
    failure = call(reader, "apply_document_edits", bad)
    assert failure["error"]["code"] == "table_not_found"
    assert host.document_snapshot("MMLE-50D", KIND)["targets"][target["targetId"]]["richField"]["richText"] == original
    actions = [{"operation": "modify_table", "tableId": identity["tableId"], "action": "set_table_style", "style": "plain"},
        {"operation": "modify_table", "tableId": identity["tableId"], "action": "delete_row", "rowId": identity["rows"][1]["rowId"]}]
    receipt = batch(actions, "table-two-operations")
    assert receipt["revision"] == receipt["beforeRevision"] + 1
    assert len(receipt["operationResults"][0]["table"]["rows"]) == 2
    assert len(receipt["operationResults"][1]["table"]["rows"]) == 1
    host.undo_document_change("MMLE-50D", KIND, {"documentId": receipt["documentId"],
        "changeId": receipt["changeId"], "expectedRevision": receipt["revision"], "requestId": "undo-table"})
    restored = host.document_snapshot("MMLE-50D", KIND)["targets"][target["targetId"]]["richField"]["richText"]
    assert canonical_bytes(restored) == canonical_bytes(original)


def test_create_after_id_invalid_ids_and_table_caps(monkeypatch):
    value = envelope("First")
    value["doc"]["content"].append(envelope("Last", start=7000)["doc"]["content"][0])
    made, result = tables.apply(value, {"operation": "create_table", "rows": 1, "columns": 1,
        "afterId": value["doc"]["content"][0]["attrs"]["id"]}, width=13, id_factory=ids())
    assert [n["type"] for n in made["doc"]["content"]] == ["paragraph", "table", "paragraph"]
    assert result["tableId"] == made["doc"]["content"][1]["attrs"]["id"]
    refused("table_not_found", lambda: tables.apply(value, {"operation": "create_table", "rows": 1,
        "columns": 1, "afterId": "missing"}, width=800))
    refused("table_not_found", lambda: tables.apply(made, {"operation": "modify_table", "tableId": "missing",
        "action": "delete_table"}, width=800))
    for node in (table_of(made), table_of(made)["content"][0], cells(made)[0]):
        bad = deepcopy(made)
        old = node["attrs"]["id"]
        def replace_id(item):
            if item.get("attrs", {}).get("id") == old:
                item["attrs"]["id"] = "generated-id"
            for child in item.get("content", []):
                replace_id(child)
        replace_id(bad["doc"])
        refused("invalid_rich_text_node_id", lambda: rich.validate(bad))
    monkeypatch.setattr(rich, "TABLE_MAX_BYTES", 1024 * 1024)
    value = table_value(50, 12, text=False)
    for action, fields in (("insert_row", {"rowId": table_of(value)["content"][0]["attrs"]["id"], "position": "after"}),
                           ("insert_column", {"columnId": table_of(value)["attrs"]["columns"][0]["id"], "position": "after"})):
        refused("table_too_large", lambda: modify(value, action, **fields))
    table_of(value)["content"][0]["content"].append(deepcopy(cells(value)[0]))
    refused("table_too_large", lambda: rich.validate(value))


def test_spanning_split_keeps_content_and_only_anchor_attributes():
    value = table_value()
    first = cells(value)[0]["attrs"]["id"]
    value, _ = modify(value, "merge_cells", cellIds=[first, cells(value)[4]["attrs"]["id"]])
    value, _ = modify(value, "set_cell_style", cellIds=[first], style={"header": False, "fill": "#102030", "verticalAlign": "middle"})
    before = deepcopy(cells(value)[0])
    result, _ = modify(value, "split_cells", cellIds=[first])
    assert cells(result)[0]["content"] == before["content"] and cells(result)[0]["attrs"]["id"] == first
    lower = tables.grid(table_of(result))[1][1][0]["cell"]
    assert lower["type"] == "tableCell"
    assert lower["attrs"]["fill"] == "#102030" and lower["attrs"]["verticalAlign"] == "middle"
    assert not lower["content"][0].get("content")
    assert lower["attrs"]["id"] not in rich.node_ids(value)


def test_deleting_column_moves_a_spanning_anchor():
    value = table_value(2, 3)
    original = deepcopy(cells(value)[0])
    value, _ = modify(value, "merge_cells", cellIds=[cells(value)[0]["attrs"]["id"], cells(value)[1]["attrs"]["id"]])
    content = deepcopy(cells(value)[0]["content"])
    result, _ = modify(value, "delete_column", columnId=table_of(value)["attrs"]["columns"][0]["id"])
    assert cells(result)[0]["attrs"]["id"] == original["attrs"]["id"]
    assert "colspan" not in cells(result)[0]["attrs"] and cells(result)[0]["content"] == content


def test_generated_whole_field_table_refusal_and_locked_structural_refusal(narrative):
    value = table_value()
    # Supervisor: the refusal is proven on an eligible generated paragraph (the narrative scene). Codex's test used
    # the plain scene, whose generated block is not rich-eligible and is refused earlier as a derived field.
    assert "table" not in narrative.field("generated-note")["richTextCapabilities"]["features"]
    refused("unsupported_rich_text_feature", lambda: narrative.command({"operation": "replace_rich_text",
        "targetType": "page_element", "targetId": "generated-note", "richText": value}))
    _, _, targets = narrative.snapshot()
    locked = {**targets[OBJECT], "operation": "read_only"}
    refused("read_only_derived_field", lambda: tables.require_target(locked))


def test_oversized_table_identity_receipt_refuses_before_save(scene):
    from ai_inspector.documentation.commands import content_hash
    from ai_inspector.documentation.targets import hash_values, owner_state
    from ai_inspector.documentation.provenance import prepare_text_command
    from tests.test_documentation_rich_text import NUMBER
    state, document, targets = scene.snapshot()
    before = scene.path.read_bytes()
    field = scene.field()
    command = prepare_text_command(document, {"operation": "replace_rich_text", "pageId": PAGE,
        "targetType": "document_object", "targetId": OBJECT, "richText": table_value()})
    values = hash_values(targets)
    refused("codex_result_too_large", lambda: scene.repo.apply_batch(NUMBER, "source-a", "plan-a",
        base_revision=state["sceneRevision"], expected_revision=state["revision"], request_id="too-many-identities",
        commands=[command], page_targets={PAGE: {"document_object": [OBJECT]}},
        expected_hashes={OBJECT: field["contentHash"]},
        current_hashes={key: content_hash(owner_state(state, targets[key]), key, item) for key, item in values.items()},
        hashes_revision=state["sceneRevision"], identity_document=scene.base,
        table_results=[{"operationIndex": n, "targetId": OBJECT, "table": {"cellIds": ["rt-" + "a" * 36] * 600}} for n in range(24)]))
    assert scene.path.read_bytes() == before


def test_large_table_read_keeps_the_existing_explicit_ceiling(scene):
    value = table_value(1, 1)
    cells(value)[0]["content"][0]["content"] = [{"type": "text", "text": "x" * 40000}]
    scene.edit(value)
    refused("read_result_too_large", scene.field)


@pytest.mark.parametrize("version", [1, 2])
def test_schema_one_and_two_store_roundtrip_bytes(scene, version):
    value = envelope("Legacy text", marks=[{"type": "bold"}])
    if version == 2:
        value["schemaVersion"] = 2
        value["doc"]["content"][0]["attrs"].update(indent=0, lineHeight=1.2)
        value["doc"]["content"][0]["content"][0]["marks"].append({"type": "strike"})
    canonical = canonical_bytes(rich.validate(value))
    scene.edit(value)
    saved = scene.path.read_bytes()
    assert canonical_bytes(scene.value()) == canonical
    assert canonical_bytes(scene.field()["richText"]) == canonical
    assert scene.path.read_bytes() == saved
    scene.batch(value, request_id="unchanged-legacy")
    assert canonical_bytes(scene.value()) == canonical


# Supervisor tests (P3b-1 gate).

def test_delete_column_drops_a_row_left_without_a_starting_cell():
    value = table_value(3, 2)
    before = table_of(value)
    grid = [[cell["attrs"]["id"] for cell in row["content"]] for row in before["content"]]
    merged, _ = modify(value, "merge_cells", cellIds=[grid[1][0], grid[2][0]])
    assert [len(row["content"]) for row in table_of(merged)["content"]] == [2, 2, 1]
    # Column 2 holds the last row's only starting cell: the row goes with it, as after a merge.
    result, described = modify(merged, "delete_column", columnId=before["attrs"]["columns"][1]["id"])
    table = table_of(result)
    assert [row["attrs"]["id"] for row in table["content"]] == [row["attrs"]["id"] for row in before["content"][:2]]
    assert [[cell["attrs"]["id"] for cell in row["content"]] for row in table["content"]] == [[grid[0][0]], [grid[1][0]]]
    assert all("rowspan" not in cell["attrs"] and "colspan" not in cell["attrs"] for cell in cells(result))
    assert [column["width"] for column in table["attrs"]["columns"]] == [1000]
    assert rich.plain_text(result) == "Before\nR0C0\nR1C0\nR2C0"
    assert described == tables.describe(table)


def test_an_empty_cell_style_is_refused():
    value = table_value(2, 2)
    refused("invalid_table_operation", lambda: modify(value, "set_cell_style",
        cellIds=[cells(value)[0]["attrs"]["id"]], style={}))


def test_a_table_past_the_box_bound_is_refused_as_a_table_with_advice():
    error = refused("table_too_large", lambda: tables.apply(envelope("Before"),
        {"operation": "create_table", "rows": 50, "columns": 12}, width=800, id_factory=ids()))
    assert "second table" in str(error)
    value, _ = tables.apply(envelope("Before"), {"operation": "create_table", "rows": 46, "columns": 12},
                            width=800, id_factory=ids())
    row = table_of(value)["content"][0]["attrs"]["id"]
    refused("table_too_large", lambda: modify(value, "insert_row", rowId=row, position="after"))
    # A whole-field write keeps the general code: it is not a table operation.
    big = table_value(46, 12, text=False)
    for cell in cells(big):
        cell["content"][0]["content"] = [{"type": "text", "text": "x" * 40}]
    refused("rich_text_too_large", lambda: rich.validate(big))
