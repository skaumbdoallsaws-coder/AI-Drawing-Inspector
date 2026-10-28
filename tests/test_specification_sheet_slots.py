"""Specification-sheet slots (docs/specification-sheet-slots-plan.md, SS1): stored values, the row list, templates,
the CAD facts, the release gate, and the reviewed MMLE-50D sheet unchanged."""
from __future__ import annotations

import json
import struct
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import server
from ai_inspector.specification_sheet.cad import assembly_mass, format_extents, format_mass, glb_extents
from ai_inspector.specification_sheet.slots import (
    SlotStore,
    SpecificationSlotError,
    TemplateStore,
    parse_slot,
    resolve,
    row_key,
    unsupported_numbers,
)

GOLDEN = Path(__file__).parent / "specification_sheet_mmle_50d_golden.txt"


def _capture() -> bytes:
    payload = BytesIO()
    Image.new("RGB", (2200, 2200), "white").save(payload, format="PNG")
    return payload.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "SPECIFICATION_SHEET_ROOT", tmp_path / "sheets")
    return TestClient(server.app)


def _render(client, assembly, document):
    page = document["pages"][0]
    return client.post(
        f"/api/specification-sheet/{assembly}/document/{page['pageId']}/render",
        data={"documentRevision": document["documentRevision"], "figureRevision": document["figureRevision"],
              "manualPlanRevision": document["manualPlanRevision"], "sourceRevision": document["sourceRevision"],
              "renderPipelineVersion": str(document["renderPipelineVersion"]), "balloons": "[]"},
        files={"file": ("product.png", _capture(), "image/png")},
    )


def _pdf_text(client, url):
    import fitz

    pdf = fitz.open(stream=client.get(url).content, filetype="pdf")
    try:
        return pdf[0].get_text("text")
    finally:
        pdf.close()


# --- the store and the rules ---------------------------------------------------------------------------------

def test_slot_names_and_row_keys():
    assert parse_slot("title") == ("prose", None, None)
    assert parse_slot("feature.2.text") == ("prose", None, None)
    assert parse_slot("spec.spindle_speed.value") == ("row", "spindle_speed", "value")
    with pytest.raises(SpecificationSlotError):
        parse_slot("feature.4.text")
    with pytest.raises(SpecificationSlotError):
        parse_slot("spec.Bad Key.value")
    assert row_key("Rated Capacity") == "rated_capacity"
    assert row_key("Rated Capacity", ["rated_capacity"]) == "rated_capacity_2"
    assert row_key("8\" chuck") == "8_chuck"


def test_store_keeps_values_with_their_source_and_clears_to_the_default(tmp_path):
    store = SlotStore(tmp_path, "100001")
    store.set_values([{"slot": "tagline", "value": "  Four   cylinders, one crank. "}], "workspace")
    store.set_values([{"slot": "spec.weight.value", "value": "95 lb", "quote": "it weighs 95 lb"}], "chat")
    data = store.read()
    assert data["values"]["tagline"]["value"] == "Four cylinders, one crank."
    assert data["values"]["tagline"]["source"] == "workspace"
    assert data["values"]["spec.weight.value"]["quote"] == "it weighs 95 lb"
    store.set_values([{"slot": "tagline", "value": ""}], "workspace")
    assert "tagline" not in store.read()["values"]
    with pytest.raises(SpecificationSlotError):
        store.set_values([{"slot": "tagline", "value": "x"}], "cad")
    with pytest.raises(SpecificationSlotError):
        store.set_values([{"slot": "title", "value": "x" * 700}], "workspace")


def test_accept_clears_only_unreviewed_values(tmp_path):
    store = SlotStore(tmp_path, "asm-1")
    store.set_values([{"slot": "tagline", "value": "Drafted line."}], "sage_draft")
    store.set_values([{"slot": "title", "value": "Typed title"}], "workspace")
    assert store.accept(["tagline", "title"], "workspace") == ["tagline"]
    assert store.read()["values"]["tagline"]["accepted"]["by"] == "workspace"
    assert store.accept(["tagline"], "workspace") == []


def test_removing_a_row_drops_its_values(tmp_path):
    store = SlotStore(tmp_path, "asm-1")
    store.set_rows([{"key": "spindle_speed", "label": "Spindle speed"}, {"key": "weight", "label": "Weight"}])
    store.set_values([{"slot": "spec.spindle_speed.value", "value": "6,000 rpm"}], "chat")
    store.set_rows([{"key": "weight", "label": "Weight"}])
    assert store.read()["values"] == {}
    with pytest.raises(SpecificationSlotError):
        store.set_rows([{"key": "a", "label": "A"}, {"key": "a", "label": "B"}])
    with pytest.raises(SpecificationSlotError):
        store.set_rows([{"key": f"row_{index}", "label": "Row"} for index in range(15)])


def test_templates_are_used_only_once_approved(tmp_path):
    templates = TemplateStore(tmp_path)
    rows = [{"key": "swing_over_bed", "label": "Swing over bed", "unit": "in", "hint": "largest diameter"}]
    templates.propose("cnc_lathe", "CNC lathe", rows, by="sage", assembly_number="asset-lathe")
    payload = templates.get("cnc_lathe")
    assert payload["approved"] is None and payload["proposal"]["rows"][0]["unit"] == "in"
    approved = templates.approve("cnc_lathe", by="chat")
    assert approved["approved"]["rows"] == rows and approved["proposal"] is None
    assert templates.list() == [{"type": "cnc_lathe", "label": "CNC lathe", "approved": True, "proposed": False,
                                 "rows": 1}]
    with pytest.raises(SpecificationSlotError):
        templates.approve("cnc_lathe", by="chat")


def test_resolve_flags_typing_over_cad_and_unreviewed_values():
    defaults = {"spec.weight.value": {"value": "92.3 lb", "source": "cad"},
                "tagline": {"value": None, "source": None, "hint": "one line"},
                "title": {"value": "Engine", "source": "library"}}
    stored = {"spec.weight.value": {"value": "95 lb", "source": "workspace"},
              "title": {"value": "Engine", "source": "sage_draft"}}
    slots = resolve(defaults, stored, ["spec.weight.value", "tagline", "title"])
    assert slots["spec.weight.value"]["overrides"] == {"value": "92.3 lb", "source": "cad"}
    assert slots["tagline"]["open"] and slots["tagline"]["hint"] == "one line"
    assert slots["title"]["unreviewed"] and "overrides" not in slots["title"]


def test_a_draft_may_only_restate_numbers_on_the_sheet():
    sheet = ["92.3 lb", "23.2 x 8.7 x 16.9 in", "Four Cylinder Engine Assembly"]
    assert unsupported_numbers("A 92.3 lb engine, 23.2 in long.", sheet) == []
    assert unsupported_numbers("Makes 150 hp at 6,000 rpm.", sheet) == ["150", "6000"]


# --- the CAD facts -------------------------------------------------------------------------------------------

def _glb(path, nodes, accessors):
    gltf = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": nodes,
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}], "accessors": accessors}
    chunk = json.dumps(gltf).encode()
    chunk += b" " * (-len(chunk) % 4)
    path.write_bytes(b"glTF" + struct.pack("<II", 2, 20 + len(chunk)) + struct.pack("<I4s", len(chunk), b"JSON")
                     + chunk)
    return path


def test_glb_extents_follow_node_transforms(tmp_path):
    accessors = [{"min": [-0.5, 0.0, -0.25], "max": [0.5, 1.0, 0.25]}]
    nodes = [{"children": [1], "scale": [2.0, 2.0, 2.0]},
             {"mesh": 0, "translation": [10.0, 0.0, 0.0], "rotation": [0.0, 0.7071068, 0.0, 0.7071068]}]
    extents = glb_extents(_glb(tmp_path / "model.glb", nodes, accessors))
    # rotated a quarter turn about the vertical: the 1.0 x 0.5 footprint turns to 0.5 x 1.0, then doubled
    assert extents == pytest.approx({"width": 1.0, "depth": 2.0, "height": 2.0}, abs=1e-4)
    assert glb_extents(tmp_path / "missing.glb") is None
    assert format_extents({"width": 2.579, "depth": 3.392, "height": 2.288}, "metric") == "2,579 x 3,392 x 2,288 mm"
    assert format_extents({"width": 0.589, "depth": 0.2199, "height": 0.4289}, "imperial") == "23.2 x 8.7 x 16.9 in"
    assert format_mass(41.888, "imperial") == "92.3 lb"
    assert format_mass(41.888, "metric") == "41.9 kg"


def test_weight_comes_from_the_cad_only_when_every_part_has_a_material():
    cache = {"a": {"physical": {"mass": 2.0, "assignedMaterial": "Steel"}},
             "b": {"physical": {"mass": 1.0, "assignedMaterial": None}}}
    whole = {"partDataCache": cache, "components": [{"type": "Part", "partDataKey": "a"},
                                                    {"type": "Part", "partDataKey": "a"},
                                                    {"type": "Assembly"}]}
    assert assembly_mass(whole) == {"massKg": 4.0, "note": "sum of 2 parts with materials"}
    whole["components"].append({"type": "Part", "partDataKey": "b"})
    assert assembly_mass(whole)["massKg"] is None
    assert assembly_mass(whole)["note"] == "1 of 3 parts have no material in the CAD"


# --- the sheet -----------------------------------------------------------------------------------------------

def test_an_assembly_without_a_profile_gets_a_sheet_with_open_slots(client):
    response = client.post("/api/specification-sheet/100001/generate?rebaseline=true")
    assert response.status_code == 200, response.text
    document = response.json()["document"]
    slots = document["slots"]
    assert slots["title"] == {**slots["title"], "value": "Four Cylinder Engine Assembly", "source": "library"}
    assert slots["spec.overall_dimensions.value"]["source"] == "cad"
    assert slots["spec.overall_dimensions.value"]["value"] == "23.2 x 8.7 x 16.9 in"
    assert slots["tagline"]["open"] and slots["feature.1.title"]["open"]
    gate = document["releaseGate"]
    assert gate["reviewPdfAllowed"] and gate["openSlotCount"] == len(gate["openSlots"]) == 8
    table = next(block for block in document["pages"][0]["layoutBlocks"] if block["blockId"] == "specifications-table")
    assert [row["slots"] for row in table["rows"]] == [
        ["spec.overall_dimensions.label", "spec.overall_dimensions.value"], ["spec.weight.label", "spec.weight.value"]]


def test_values_rows_units_and_type_through_the_routes(client):
    client.post("/api/specification-sheet/100001/generate?rebaseline=true")
    added = client.post("/api/specification-sheet/100001/rows",
                        json={"operation": "add", "label": "Displacement", "unit": "cc"}).json()
    assert added["rowKey"] == "displacement"
    stored = client.post("/api/specification-sheet/100001/values", json={"values": [
        {"slot": "spec.displacement.value", "value": "1,600 cc"},
        {"slot": "spec.weight.value", "value": "95 lb"},
        {"slot": "tagline", "value": "A four-cylinder engine for training."}]})
    assert stored.status_code == 200, stored.text
    document = stored.json()["document"]
    assert document["slots"]["spec.displacement.value"]["source"] == "workspace"
    assert document["slots"]["spec.weight.value"]["overrides"]["source"] == "cad"
    assert [item["topic"] for item in document["releaseGate"]["findings"]] == ["overrides_cad"]
    moved = client.post("/api/specification-sheet/100001/rows",
                        json={"operation": "move", "key": "displacement", "direction": -1}).json()
    assert [row["key"] for row in moved["document"]["sheet"]["rows"]] == [
        "overall_dimensions", "displacement", "weight"]
    metric = client.post("/api/specification-sheet/100001/settings", json={"units": "metric"}).json()
    assert metric["document"]["slots"]["spec.overall_dimensions.value"]["value"] == "589 x 220 x 429 mm"
    unknown = client.post("/api/specification-sheet/100001/values",
                          json={"values": [{"slot": "spec.torque.value", "value": "1"}]})
    assert unknown.status_code == 422
    removed = client.post("/api/specification-sheet/100001/rows",
                          json={"operation": "remove", "key": "displacement"}).json()
    assert "spec.displacement.value" not in removed["document"]["slots"]


def test_a_row_added_in_the_viewport_is_keyed_by_the_name_typed_into_it(client):
    client.post("/api/specification-sheet/100001/generate?rebaseline=true")
    added = client.post("/api/specification-sheet/100001/rows", json={
        "operation": "add", "label": "New specification", "provisional": True, "after": "overall_dimensions"}).json()
    assert added["rowKey"] == "new_specification"
    assert added["document"]["slots"]["spec.new_specification.label"]["value"] == "New specification"
    named = client.post("/api/specification-sheet/100001/values", json={"values": [
        {"slot": "spec.new_specification.label", "value": "Displacement"},
        {"slot": "spec.new_specification.value", "value": "1.6 L"}]}).json()
    assert named["renamedSlots"] == {"spec.new_specification.label": "spec.displacement.label",
                                     "spec.new_specification.value": "spec.displacement.value"}
    slots = named["document"]["slots"]
    assert "spec.new_specification.label" not in slots
    assert slots["spec.displacement.label"]["value"] == "Displacement"
    assert slots["spec.displacement.value"] == {**slots["spec.displacement.value"], "value": "1.6 L",
                                                "source": "workspace"}
    assert [row["key"] for row in named["document"]["sheet"]["rows"]] == [
        "overall_dimensions", "displacement", "weight"]
    # Once named, the row keeps its key when its name changes again.
    again = client.post("/api/specification-sheet/100001/values", json={"values": [
        {"slot": "spec.displacement.label", "value": "Engine displacement"}]}).json()
    assert again["renamedSlots"] == {}
    assert again["document"]["slots"]["spec.displacement.label"]["value"] == "Engine displacement"


def test_approving_a_template_gives_the_sheet_its_rows(client):
    client.post("/api/specification-sheet/100001/generate?rebaseline=true")
    store = SlotStore(server.SPECIFICATION_SHEET_ROOT, "100001")
    TemplateStore(server.SPECIFICATION_SHEET_ROOT).propose(
        "piston_engine", "Piston engine",
        [{"key": "overall_dimensions", "label": "Overall dimensions (W x D x H)"},
         {"key": "cylinders", "label": "Cylinders"}, {"key": "weight", "label": "Dry weight"}],
        by="sage", assembly_number="100001")
    store.set_type("piston_engine", "Piston engine", "sage")
    proposed = client.get("/api/specification-sheet/100001/slots").json()
    assert proposed["sheet"]["type"]["proposal"]["rows"][1]["key"] == "cylinders"
    assert [row["key"] for row in proposed["sheet"]["rows"]] == ["overall_dimensions", "weight"]
    approved = client.post("/api/specification-sheet/100001/template/approve",
                           json={"type": "piston_engine"}).json()
    document = approved["document"]
    assert [row["key"] for row in document["sheet"]["rows"]] == ["overall_dimensions", "cylinders", "weight"]
    assert document["slots"]["spec.weight.label"]["value"] == "Dry weight"
    assert document["slots"]["spec.weight.value"]["source"] == "cad"
    assert document["slots"]["spec.cylinders.value"]["open"]


def test_a_text_edit_keeps_the_capture_and_reaches_the_pdf(client):
    document = client.post("/api/specification-sheet/100001/generate?rebaseline=true").json()["document"]
    assert _render(client, "100001", document).status_code == 200
    edited = client.post("/api/specification-sheet/100001/values", json={"values": [
        {"slot": "tagline", "value": "Bench engine for assembly training."}]}).json()["document"]
    assert edited["documentRevision"] != document["documentRevision"]
    assert edited["figureRevision"] == document["figureRevision"]
    assert edited["pages"][0]["renderRequest"]["image"]["status"] == "ready"
    exported = client.post("/api/specification-sheet/100001/pdf")
    assert exported.status_code == 200, exported.text
    text = _pdf_text(client, exported.json()["pdf"]["url"])
    assert "Bench engine for assembly training." in text
    assert "23.2 x 8.7 x 16.9 in" in text


def test_reviewed_mmle_sheet_is_unchanged_and_flags_typed_over_evidence(client):
    document = client.post("/api/specification-sheet/MMLE-50D/generate?rebaseline=true").json()["document"]
    assert all(document["slots"][f"spec.{key}.value"]["source"] == "evidence"
               for key in ("rated_capacity", "vertical_travel", "shipping_weight"))
    assert document["releaseGate"]["openSlotCount"] == 0 and document["releaseGate"]["findings"] == []
    assert _render(client, "MMLE-50D", document).status_code == 200
    text = _pdf_text(client, client.post("/api/specification-sheet/MMLE-50D/pdf").json()["pdf"]["url"])
    assert text == GOLDEN.read_text("utf-8")
    changed = client.post("/api/specification-sheet/MMLE-50D/values", json={"values": [
        {"slot": "spec.rated_capacity.value", "value": "1,000 lb"}]}).json()["document"]
    finding = changed["releaseGate"]["findings"][0]
    assert finding["topic"] == "overrides_evidence" and "1,100 lb" in finding["message"]


def test_the_viewport_treats_every_text_as_a_slot():
    source = Path("static/index.html").read_text("utf-8")
    for name in ("_specSheetDecorateSlot", "_specSheetBeginSlotEdit", "_specSheetTable", "_specSheetAddRow",
                 "_specSheetRenderInspector", "_specSheetAfterRender", "_specSheetSlotPressed"):
        assert f"function {name}(" in source
    # A press that did not drag selects the slot (the page re-renders, so click never fires).
    assert "if (drag.specSlot) _specSheetSlotPressed(drag.specSlot);" in source
    # An open editor is committed by a press anywhere else; saves wait for each other.
    assert "active.finish('leave')" in source and "state.specSheetSaving" in source
    # The capture is stored against the figure, not the text.
    assert "form.append('figureRevision'" in source
    assert "provisional: true" in source
    # SS3: the fillable export and the returned copy are on the ribbon.
    assert "'Export Fillable PDF'" in source and "'Return Filled PDF'" in source
    assert "fillable ? 'fillable-pdf' : 'pdf'" in source and "/returned-pdf`" in source
    # SS6: a table shrinks as a whole (open hints, row heights, cell padding and line height), as the PDF draws it.
    assert "const shrinking = table ? [...block.querySelectorAll('.spec-slot')] : slots;" in source
    assert "element.style.lineHeight = `${size.line * scale}px`" in source
    # A value with line breaks (a list, one item per line) shows them, as the PDF draws them.
    assert "            white-space: pre-line;" in source


# --- SS3: exports from the slots -------------------------------------------------------------------------------
def _ready_engine(client):
    """The engine sheet with a typed tagline and an added row whose value is still open, captured."""
    client.post("/api/specification-sheet/100001/generate?rebaseline=true")
    client.post("/api/specification-sheet/100001/rows", json={"operation": "add", "label": "Displacement"})
    document = client.post("/api/specification-sheet/100001/values", json={"values": [
        {"slot": "tagline", "value": "A four-cylinder engine for training."}]}).json()["document"]
    assert _render(client, "100001", document).status_code == 200
    return document


def _fill(pdf_bytes, values):
    import fitz

    pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
    for widget in pdf[0].widgets():
        if widget.field_name in values:
            widget.field_value = values[widget.field_name]
            widget.update()
    payload = pdf.tobytes()
    pdf.close()
    return payload


def test_the_final_pdf_and_docx_leave_open_slots_out(client):
    from docx import Document

    _ready_engine(client)
    exported = client.post("/api/specification-sheet/100001/pdf").json()
    text = _pdf_text(client, exported["pdf"]["url"])
    assert "A four-cylinder engine for training." in text and "92.3 lb" in text
    assert "Displacement" not in text  # its value is open
    assert "Add " not in text and "feature" not in text.lower()  # open prose is left out, no placeholders
    words = Document(BytesIO(client.get(exported["docx"]["url"]).content))
    body = " | ".join(paragraph.text for paragraph in words.paragraphs)

    def cell_texts(tables):
        for table in tables:
            for row in table.rows:
                for cell in row.cells:
                    yield cell.text
                    yield from cell_texts(cell.tables)

    cells = " | ".join(cell_texts(words.tables))
    assert "A four-cylinder engine for training." in body and "Displacement" not in body + cells
    assert "92.3 lb" in cells


def test_the_fillable_pdf_has_the_open_slots_as_fields_and_a_returned_copy_fills_them(client):
    from ai_inspector.documentation.form_fields import read_form_fields

    _ready_engine(client)
    made = client.post("/api/specification-sheet/100001/fillable-pdf")
    assert made.status_code == 200, made.text
    artifact = made.json()["fillablePdf"]
    blank = client.get(artifact["url"]).content
    fields = read_form_fields(blank)
    assert set(fields) == {slot["slot"] for slot in artifact["openFields"]}
    assert "spec.displacement.value" in fields and "features.heading" in fields and "tagline" not in fields
    returned = _fill(blank, {"spec.displacement.value": "1.6 L", "feature.1.title": "Four cylinders"})
    read = client.post("/api/specification-sheet/100001/returned-pdf",
                       files={"file": ("filled.pdf", returned, "application/pdf")})
    assert read.status_code == 200, read.text
    payload = read.json()
    assert payload["returned"]["set"] == ["feature.1.title", "spec.displacement.value"]
    slots = payload["document"]["slots"]
    assert slots["spec.displacement.value"]["value"] == "1.6 L"
    assert slots["spec.displacement.value"]["source"] == "returned_pdf"
    # A value typed since the export is kept; an empty field never clears anything.
    client.post("/api/specification-sheet/100001/values", json={"values": [
        {"slot": "feature.2.title", "value": "Cast block"}]})
    again = client.post("/api/specification-sheet/100001/returned-pdf", files={"file": (
        "filled.pdf", _fill(blank, {"feature.2.title": "Something else"}), "application/pdf")}).json()
    assert again["returned"]["kept"] == ["feature.2.title"]
    assert again["document"]["slots"]["feature.2.title"]["value"] == "Cast block"
    assert again["document"]["slots"]["spec.displacement.value"]["value"] == "1.6 L"
    other = client.post("/api/specification-sheet/MMLE-50D/returned-pdf",
                        files={"file": ("filled.pdf", returned, "application/pdf")})
    assert other.status_code == 409 and "100001" in other.json()["message"]
    plain = client.post("/api/specification-sheet/100001/returned-pdf",
                        files={"file": ("plain.pdf", client.get(
                            client.post("/api/specification-sheet/100001/pdf").json()["pdf"]["url"]).content,
                            "application/pdf")})
    assert plain.status_code == 422 and "not a fillable" in plain.json()["message"]


def test_text_that_cannot_fit_names_its_slot(client):
    _ready_engine(client)
    document = client.post("/api/specification-sheet/100001/values", json={"values": [
        {"slot": "tagline", "value": "A four-cylinder engine. " * 22}]}).json()["document"]
    assert _render(client, "100001", document).status_code == 200
    failed = client.post("/api/specification-sheet/100001/pdf")
    assert failed.status_code == 422
    assert failed.json()["message"].startswith("Tagline does not fit its box")



def test_a_full_table_with_a_two_line_value_exports_with_its_rows_grown_and_drawn_smaller(client):
    """Found in the SS6 live run: twelve rows and a researched control name ("MSC-803 CNC Controls With Pendant")
    did not fit even at 70% because every PDF row had the same height. The viewport grows a row to its text and
    shrinks the table to its frame; the PDF now does the same."""
    import fitz

    client.post("/api/specification-sheet/100001/generate?rebaseline=true")
    labels = ["Cylinders", "Displacement", "Bore", "Stroke", "Power", "Torque", "Fuel", "Cooling", "Control"]
    for label in labels:
        client.post("/api/specification-sheet/100001/rows", json={"operation": "add", "label": label})
    rows = client.get("/api/specification-sheet/100001/slots").json()["sheet"]["rows"]
    values = [{"slot": f"spec.{row['key']}.value", "value": "1.6 L"} for row in rows if row["key"] not in (
        "overall_dimensions", "weight", "control")]
    values.append({"slot": "spec.control.value", "value": "MSC-803 CNC Controls With Pendant"})
    document = client.post("/api/specification-sheet/100001/values", json={"values": values}).json()["document"]
    assert _render(client, "100001", document).status_code == 200
    exported = client.post("/api/specification-sheet/100001/pdf")
    assert exported.status_code == 200, exported.json()
    pdf = fitz.open(stream=client.get(exported.json()["pdf"]["url"]).content, filetype="pdf")
    text = " ".join(pdf[0].get_text().split())
    assert "MSC-803 CNC Controls With Pendant" in text and "Control" in text


def test_typographic_characters_are_drawn_plain_and_undrawable_ones_name_their_slot(client):
    """Found in the SS6 live run: a researched turret value "10\u30108\u3011" printed as "10?8?" (the PDF's built-in
    fonts draw Latin-1 only)."""
    import fitz

    _ready_engine(client)
    document = client.post("/api/specification-sheet/100001/values", json={"values": [
        {"slot": "tagline", "value": "Speeds of 45\u20134,500 min\u207b\u00b9, a 6\u2033 chuck and 10\u30108\u3011 tools."}]}).json()[
        "document"]
    assert _render(client, "100001", document).status_code == 200
    exported = client.post("/api/specification-sheet/100001/pdf")
    assert exported.status_code == 200, exported.json()
    pdf = fitz.open(stream=client.get(exported.json()["pdf"]["url"]).content, filetype="pdf")
    text = " ".join(pdf[0].get_text().split())
    assert 'Speeds of 45-4,500 min-\u00b9, a 6" chuck and 10[8] tools.' in text and "?" not in text
    document = client.post("/api/specification-sheet/100001/values", json={"values": [
        {"slot": "tagline", "value": "A 5 \u03a9 coil."}]}).json()["document"]
    assert _render(client, "100001", document).status_code == 200
    failed = client.post("/api/specification-sheet/100001/pdf")
    assert failed.status_code == 422
    assert failed.json()["message"].startswith("Tagline has characters the PDF font cannot draw (\u03a9)")
