import pytest

from ai_inspector.inspection_sheet.document import (
    build_inspection_sheet_document,
    conformance,
    display_text,
    drawing_characteristics,
    field_token,
    parse_tolerance,
    requirement_limits,
)
from ai_inspector.inspection_sheet.store import InspectionSheetStore, InspectionSheetStoreError
from ai_inspector.utils.drawing_map import normalize_drawing_map

fitz = pytest.importorskip("fitz")


def _annotation(name, text, value_m, x, y, **extra):
    return {"annotationName": name, "annotationType": "dimension", "dimensionText": text,
            "dimensionValue": value_m, "positionSheet": [x, y], "visible": True, "isDangling": False, **extra}


def _drawing_map():
    return normalize_drawing_map({
        "partNumber": "P-1", "sheetWidth": 0.4, "sheetHeight": 0.3,
        "sheets": [{"sheetName": "Sheet1", "views": [
            {"viewName": "Front", "viewOutline": [0.02, 0.1, 0.2, 0.28], "annotations": [
                _annotation("d2", "25.00", 0.025, 0.05, 0.12),
                _annotation("d1", "<MOD-DIAM>90.00", 0.09, 0.10, 0.25),
                _annotation("d3", "12.00", 0.012, 0.03, 0.20, toleranceType="bilateral", tolerancePlus=0.00002,
                            toleranceMinus=0.00001),
                _annotation("dangling", "1.00", 0.001, 0.1, 0.1, isDangling=True),
                {"annotationName": "n1", "annotationType": "note", "noteText": "NOTE", "positionSheet": [0.1, 0.1]},
            ]},
            {"viewName": "Detail A", "viewOutline": [0.22, 0.1, 0.38, 0.28], "annotations": [
                _annotation("d4", "3x 4.30", 0.0043, 0.30, 0.15),
                _annotation("d5", "8.00", 0.008, 0.25, 0.27, isReference=True),
            ]},
        ]}],
    }, "P-1")


def _descriptions():
    return {"descriptions": {"Front/d1": "Outside diameter.", "0|Front/d2": "Height of the land."}}


def _profile():
    return {"features": [
        {"name": "Main journals", "type": "journal", "count": 5,
         "inspection_reason": "Journal diameter sets the clearance; it also sets the oil film. More text."},
        {"name": "Bolt circle", "count": 8, "inspection_reason": "Hole positions locate the flywheel;"},
    ]}


def _document(values=None, parts=None):
    return build_inspection_sheet_document(
        assembly={"assemblyNumber": "ASM-1", "name": "Test engine", "sourceRevision": "rev-1"},
        bom=[{"item": 1, "partNumber": "P-1", "description": "Piston", "quantity": 4},
             {"item": 2, "partNumber": "P 2/B", "description": "Crankshaft", "quantity": 1},
             {"item": 3, "partNumber": "P-3", "description": "Screw", "quantity": 8},
             {"item": 4, "partNumber": "Not specified", "description": "Unnamed", "quantity": 1}],
        parts=parts if parts is not None else {
            "P-1": {"drawingMap": _drawing_map(), "descriptions": _descriptions(), "hasDrawingPdf": True},
            "P 2/B": {"profile": _profile()},
            "P-3": {},
        },
        values=values or {},
    )


def test_drawing_dimensions_are_numbered_like_the_report_tab():
    rows = drawing_characteristics(_drawing_map(), _descriptions())
    # Sheet, view order, then top to bottom, then left to right; dangling dimensions and notes are left out.
    assert [row["annotationName"] for row in rows] == ["d1", "d3", "d2", "d5", "d4"]
    assert [row["number"] for row in rows] == [1, 2, 3, 4, 5]
    first = rows[0]
    assert first["text"] == "\u00d890.00" and first["nominal"] == 90.0 and first["decimals"] == 2
    assert first["description"] == "Outside diameter."
    assert rows[2]["description"] == "Height of the land."
    assert rows[1]["ownTolerance"] == {"kind": "drawing", "plus": pytest.approx(0.02), "minus": pytest.approx(0.01)}
    assert rows[4]["count"] == 3 and rows[4]["nominal"] == pytest.approx(4.3)
    assert rows[3]["reference"] is True


def test_the_loader_keeps_drawing_tolerances():
    annotation = _drawing_map()["sheets"][0]["views"][0]["annotations"][2]
    assert annotation["toleranceType"] == "bilateral"
    assert annotation["tolerancePlus"] == pytest.approx(0.00002)


def test_missing_information_becomes_open_fields_and_nothing_is_guessed():
    document = _document()
    sections = {section["partNumber"]: section for section in document["sections"]}
    assert list(sections) == ["P-1", "P 2/B", "P-3"]  # "Not specified" gets a BOM line, not a section
    assert [section["source"] for section in sections.values()] == ["drawing", "profile", "none"]

    piston = sections["P-1"]
    by_name = {row["annotationName"]: row for row in piston["characteristics"]}
    assert by_name["d3"]["lower"] == pytest.approx(11.99) and by_name["d3"]["upper"] == pytest.approx(12.02)
    assert by_name["d1"]["lower"] is None and by_name["d1"]["tolerance"] is None  # waits for the general tolerance
    assert by_name["d5"]["fields"] == {}  # reference dimensions are not inspected

    crank = sections["P 2/B"]
    assert field_token("P 2/B") == "P_2_B"
    assert [row["fields"]["requirement"] for row in crank["features"]] == ["char.P_2_B.1.requirement",
                                                                          "char.P_2_B.2.requirement"]
    assert crank["features"][0]["reason"] == "Journal diameter sets the clearance;"[:-1] + "."
    assert sections["P-3"]["features"][0]["name"] == "Inspect to drawing"

    open_names = [field["name"] for field in document["openFields"]]
    assert open_names[:4] == ["header.customer", "header.order", "header.lot", "header.sample_size"]
    assert "part.P-1.general_tolerance" in open_names and "part.P-1.drawing_revision" in open_names
    assert document["summary"]["openFields"] == len(open_names) == 4 + 2 + (1 + 2) + (1 + 1)
    kinds = {field["name"]: field["kind"] for field in document["fields"]}
    assert kinds["signoff.inspector.signature"] == "signature" and kinds["bom.4.conforms"] == "checkbox"


def test_provided_values_fill_the_sheet_and_change_its_revision():
    blank = _document()
    values = {"part.P-1.general_tolerance": {"value": "\u00b10.10 mm"},
              "char.P_2_B.1.requirement": {"value": "\u00d840.00 \u00b10.02"},
              "header.lot": {"value": "LOT-7"}}
    filled = _document(values)
    piston = filled["sections"][0]
    d1 = next(row for row in piston["characteristics"] if row["annotationName"] == "d1")
    assert d1["tolerance"]["kind"] == "general" and (d1["lower"], d1["upper"]) == (89.9, 90.1)
    d3 = next(row for row in piston["characteristics"] if row["annotationName"] == "d3")
    assert d3["tolerance"]["kind"] == "drawing"  # a dimension's own tolerance wins
    assert filled["sections"][1]["features"][0]["lower"] == pytest.approx(39.98)
    assert filled["summary"]["openFields"] == blank["summary"]["openFields"] - 3
    assert filled["documentRevision"] != blank["documentRevision"]
    assert _document(values)["documentRevision"] == filled["documentRevision"]


@pytest.mark.parametrize("text, expected", [
    ("40.00 \u00b10.02", (39.98, 40.02)),
    ("\u00d840 +/- 0.1 mm", (39.9, 40.1)),
    ("40 +0.02 -0.01", (39.99, 40.02)),
    ("40 +0.02/-0.01", (39.99, 40.02)),
    ("40.02 - 39.98", (39.98, 40.02)),
    ("M8x1.25-6g", None),
    ("Ra 1.6", None),
])
def test_requirement_limits(text, expected):
    limits = requirement_limits(text)
    assert (None if limits is None else (limits["lower"], limits["upper"])) == pytest.approx(expected) \
        if expected else limits is None


def test_conformance_reports_and_never_overrides_the_inspector():
    values = {"part.P-1.general_tolerance": {"value": "0.1"},
              "char.P-1.1.measured": {"value": "90.05"},
              "char.P-1.3.measured": {"value": "25.30"}, "char.P-1.3.conforms": {"value": True},
              "char.P-1.5.measured": {"value": "about 4"},
              "char.P_2_B.2.measured": {"value": "120"}}
    document = _document(values)
    result = conformance(document, values)
    status = {(row["partNumber"], row["number"]): row for row in result["rows"]}
    assert status[("P-1", 1)]["status"] == "PASS"
    assert status[("P-1", 3)]["status"] == "FAIL" and status[("P-1", 3)]["disagreement"] is True
    assert status[("P-1", 5)]["status"] == "UNREADABLE"
    assert status[("P 2/B", 2)]["status"] == "NO_LIMITS"  # its requirement is still open
    assert status[("P-1", 2)]["status"] == "PENDING"
    assert ("P-1", 4) not in status  # the reference dimension
    assert result["disagreements"] == 1
    assert document["summary"]["results"]["FAIL"] == 1


def test_store_rules(tmp_path):
    store = InspectionSheetStore(tmp_path)
    fields = _document()["fields"]
    result = store.set_values("ASM-1", [
        {"name": "header.lot", "value": "  LOT 7 ", "quote": "the lot is LOT 7"},
        {"name": "bom.1.conforms", "value": "yes"},
        {"name": "signoff.inspector.signature", "value": "J. Doe"},
        {"name": "char.P-1.1.conforms", "value": "maybe"},
        {"name": "nonsense", "value": "1"},
    ], fields, source="chat")
    assert result["set"] == ["header.lot", "bom.1.conforms"]
    assert [item["name"] for item in result["refused"]] == ["signoff.inspector.signature", "char.P-1.1.conforms",
                                                            "nonsense"]
    values = store.values("ASM-1")
    assert values["header.lot"]["value"] == "LOT 7" and values["header.lot"]["quote"] == "the lot is LOT 7"
    assert values["bom.1.conforms"]["value"] is True

    # A returned copy never clears, and an unchanged value keeps its first source.
    result = store.set_values("ASM-1", [{"name": "header.lot", "value": ""}, {"name": "bom.1.conforms", "value": True}],
                              fields, source="returned_pdf")
    assert result == {"set": [], "cleared": [], "refused": []}
    assert store.values("ASM-1")["bom.1.conforms"]["source"] == "chat"

    result = store.set_values("ASM-1", [{"name": "header.lot", "value": ""}], fields, source="workspace")
    assert result["cleared"] == ["header.lot"]
    with pytest.raises(InspectionSheetStoreError):
        store.set_values("../x", [], fields, source="chat")
    with pytest.raises(InspectionSheetStoreError):
        store.set_values("ASM-1", [], fields, source="guess")


def _drawing_pdf(path):
    document = fitz.open()
    page = document.new_page(width=0.4 / 0.0254 * 72, height=0.3 / 0.0254 * 72)
    page.draw_rect(page.rect + (20, 20, -20, -20), color=(0, 0, 0))
    document.save(path)
    return path


def test_the_pdf_has_every_field_and_reads_back(tmp_path):
    from ai_inspector.inspection_sheet.exports import (
        InspectionSheetExportError,
        build_inspection_sheet_pdf_bytes,
        read_returned_inspection_sheet,
    )

    document = _document({"header.lot": {"value": "LOT-7"}})
    built = build_inspection_sheet_pdf_bytes(document, drawing_pdfs={"P-1": _drawing_pdf(tmp_path / "p1.pdf")},
                                             built_at="2026-10-25 12:00 UTC")
    assert built["fields"] == len(document["fields"])
    pdf = fitz.open(stream=built["pdf"], filetype="pdf")
    assert pdf.page_count == built["pages"] >= 4
    assert "assembly=ASM-1" in pdf.metadata["keywords"]
    widgets = {widget.field_name: widget for page in pdf for widget in page.widgets()}
    assert set(widgets) == {field["name"] for field in document["fields"]}
    assert widgets["header.lot"].field_value == "LOT-7"
    assert widgets["header.customer"].fill_color  # open: tinted
    text = "".join(page.get_text() for page in pdf)
    assert "Information still needed" in text and "Assembly check" in text and "\u00d890.00" in text

    returned = read_returned_inspection_sheet(built["pdf"])
    assert returned["assemblyNumber"] == "ASM-1" and returned["documentRevision"] == document["documentRevision"]
    assert returned["fields"]["header.lot"]["value"] == "LOT-7"
    other = fitz.open()
    other.new_page()
    with pytest.raises(InspectionSheetExportError, match="not an InspectorPro inspection sheet"):
        read_returned_inspection_sheet(other.tobytes())


def test_routes_build_serve_take_values_and_read_a_returned_copy(tmp_path, monkeypatch):
    import server
    from fastapi.testclient import TestClient

    drawing = _drawing_pdf(tmp_path / "p1.pdf")
    monkeypatch.setattr(server, "INSPECTION_SHEET_ROOT", tmp_path / "store")

    def compile_sheet(assembly_number):
        if assembly_number != "ASM-1":
            raise server.PartsManualNotFoundError("unknown assembly")
        return _document(server._inspection_sheet_store().values("ASM-1")), {"P-1": drawing}

    monkeypatch.setattr(server, "_inspection_sheet_document", compile_sheet)
    client = TestClient(server.app)

    state = client.get("/api/inspection-sheet/ASM-1").json()
    assert state["built"] is None and state["summary"]["openFields"] == len(state["openFields"])
    assert client.get("/api/inspection-sheet/NOPE").status_code == 404

    built = client.post("/api/inspection-sheet/ASM-1/build").json()
    response = client.get(built["built"]["pdfUrl"])
    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    assert client.get("/api/inspection-sheet/ASM-1/documents/" + "0" * 64 + "/pdf").status_code == 404

    values = client.post("/api/inspection-sheet/ASM-1/values", json={"values": [
        {"name": "part.P-1.general_tolerance", "value": "0.05"}]}).json()
    assert values["values"]["set"] == ["part.P-1.general_tolerance"]
    assert "part.P-1.general_tolerance" not in [field["name"] for field in values["openFields"]]

    pdf = fitz.open(stream=response.content, filetype="pdf")
    for page in pdf:
        for widget in page.widgets():
            if widget.field_name == "char.P-1.1.measured":
                widget.field_value = "90.20"
                widget.update()
            if widget.field_name == "char.P-1.1.conforms":
                widget.field_value = widget.on_state()
                widget.update()
    returned = client.post("/api/inspection-sheet/ASM-1/returned-pdf",
                           files={"file": ("filled.pdf", pdf.tobytes(), "application/pdf")}).json()
    assert returned["returned"]["set"] == ["char.P-1.1.measured", "char.P-1.1.conforms"]
    assert returned["returned"]["counts"]["FAIL"] == 1 and returned["returned"]["disagreements"] == 1
    assert returned["lastReturn"]["counts"]["FAIL"] == 1
    # The general tolerance given in the workspace survives the older copy's blank field.
    assert "part.P-1.general_tolerance" in [field["name"] for field in returned["providedFields"]]

    monkeypatch.setattr(server, "_inspection_sheet_document",
                        lambda number: (dict(_document(), assemblyNumber="OTHER"), {}))
    wrong = client.post("/api/inspection-sheet/OTHER/returned-pdf",
                        files={"file": ("filled.pdf", pdf.tobytes(), "application/pdf")})
    assert wrong.status_code == 409 and "for ASM-1, not OTHER" in wrong.json()["message"]


def test_display_text():
    assert display_text("<MOD-DIAM>30.00 THRU") == "\u00d830.00 THRU"
    assert display_text("45.00<MOD-DEG>\r\n") == "45.00\u00b0"
    assert display_text("<HOLE-DEPTH>6") == "6"


@pytest.mark.parametrize("text, expected", [
    ("0.1", (0.1, 0.1)),
    ("±0.10 mm", (0.1, 0.1)),
    ("+/- 0.05", (0.05, 0.05)),
    ("+0.10 -0.05", (0.1, 0.05)),
    ("+0.1/-0.05 mm", (0.1, 0.05)),
    ("±0.004 in", (0.1016, 0.1016)),
    (".X ±0.1 .XX ±0.05", None),  # a decimal-place block is not one tolerance
    ("0.1 or 0.05", None),
    ("1%", None),
    ("-0.05", None),
    ("tight", None),
])
def test_general_tolerance_is_read_strictly(text, expected):
    result = parse_tolerance(text)
    assert (None if result is None else (result["plus"], result["minus"])) == (
        pytest.approx(expected) if expected else None)


def test_an_asymmetric_general_tolerance_gives_asymmetric_limits():
    document = _document({"part.P-1.general_tolerance": {"value": "+0.10 -0.05"}})
    d1 = next(row for row in document["sections"][0]["characteristics"] if row["annotationName"] == "d1")
    assert (d1["lower"], d1["upper"]) == (89.95, 90.1)


def test_a_tolerance_the_app_cannot_read_stays_open_with_the_reason():
    document = _document({"part.P-1.general_tolerance": {"value": "0.1 or 0.05"}})
    d1 = next(row for row in document["sections"][0]["characteristics"] if row["annotationName"] == "d1")
    assert d1["lower"] is None and d1["upper"] is None
    entry = next(field for field in document["openFields"] if field["name"] == "part.P-1.general_tolerance")
    assert "not one tolerance the app can read" in entry["problem"]
    assert document["summary"]["openFields"] == _document()["summary"]["openFields"]
    from ai_inspector.inspection_sheet.exports import build_inspection_sheet_pdf_bytes
    pdf = build_inspection_sheet_pdf_bytes(document, drawing_pdfs={}, built_at="2026-10-25 12:00 UTC")["pdf"]
    widgets = {widget.field_name: widget for page in fitz.open(stream=pdf, filetype="pdf")
               for widget in page.widgets()}
    assert widgets["part.P-1.general_tolerance"].field_value == "0.1 or 0.05"
    assert widgets["part.P-1.general_tolerance"].fill_color != [1.0, 1.0, 1.0]  # still amber: needs attention
