import pytest

from ai_inspector.documentation.form_fields import (
    FormFieldError,
    add_form_fields,
    form_field,
    open_fields,
    read_form_fields,
    validate_form_fields,
)

fitz = pytest.importorskip("fitz")


def _fields():
    return [
        form_field("header.lot", "Lot or serial number", (72, 100, 300, 116), role="provide"),
        form_field("header.part", "Part number", (320, 100, 540, 116), role="provide", value="MMLE-101"),
        form_field("char.1.measured", "Measured value, mm", (360, 200, 450, 216)),
        form_field("char.1.conforms", "Conforms", (460, 200, 474, 214), kind="checkbox"),
        form_field("notes", "Notes", (72, 300, 540, 360), kind="multiline"),
        form_field("inspector.signature", "Inspector signature", (72, 400, 300, 430), kind="signature"),
    ]


def _pdf(fields):
    document = fitz.open()
    document.new_page(width=612, height=792)
    assert add_form_fields(fitz, document, fields) == len(fields)
    return document.tobytes()


def test_fields_round_trip_through_a_filled_pdf():
    blank = _pdf(_fields())
    values = read_form_fields(blank)
    assert values["header.lot"] == {"kind": "text", "value": None, "page": 0}
    assert values["header.part"]["value"] == "MMLE-101"
    assert values["char.1.conforms"]["value"] is False
    assert values["inspector.signature"] == {"kind": "signature", "value": False, "page": 0}

    # A reader fills the record fields and one open field.
    document = fitz.open(stream=blank, filetype="pdf")
    for widget in document[0].widgets():
        if widget.field_name == "char.1.measured":
            widget.field_value = "12.011"
        elif widget.field_name == "char.1.conforms":
            widget.field_value = widget.on_state()
        elif widget.field_name == "header.lot":
            widget.field_value = "LOT-7"
        else:
            continue
        widget.update()
    values = read_form_fields(document.tobytes())
    assert values["char.1.measured"]["value"] == "12.011"
    assert values["char.1.conforms"]["value"] is True
    assert values["header.lot"]["value"] == "LOT-7"


def test_open_fields_are_provide_fields_without_a_value():
    assert open_fields(_fields()) == [{"name": "header.lot", "label": "Lot or serial number"}]


def test_field_tooltips_and_multiline_flag_reach_the_pdf():
    document = fitz.open(stream=_pdf(_fields()), filetype="pdf")
    widgets = {widget.field_name: widget for widget in document[0].widgets()}
    assert widgets["header.lot"].field_label == "Lot or serial number"
    assert widgets["notes"].field_flags & fitz.PDF_TX_FIELD_IS_MULTILINE
    assert widgets["header.lot"].fill_color != [1.0, 1.0, 1.0]  # open fields are tinted
    assert widgets["char.1.measured"].fill_color == [1.0, 1.0, 1.0]  # the others are white


@pytest.mark.parametrize("arguments", [
    ("bad name!", "x", (0, 0, 10, 10)),
    ("ok", "x", (10, 10, 5, 20)),
])
def test_invalid_fields_are_rejected(arguments):
    with pytest.raises(FormFieldError):
        form_field(*arguments)
    with pytest.raises(FormFieldError):
        form_field("ok", "x", (0, 0, 10, 10), kind="radio")
    with pytest.raises(FormFieldError):
        form_field("sig", "x", (0, 0, 10, 10), kind="signature", value="signed")


def test_validation_catches_duplicates_and_fields_off_the_page():
    fields = _fields()
    validate_form_fields(fields, [(612, 792)])
    with pytest.raises(FormFieldError, match="duplicate"):
        validate_form_fields(fields + [fields[0]], [(612, 792)])
    with pytest.raises(FormFieldError, match="outside"):
        validate_form_fields([form_field("wide", "x", (500, 10, 700, 20))], [(612, 792)])
    with pytest.raises(FormFieldError, match="page"):
        validate_form_fields([form_field("p2", "x", (0, 0, 10, 10), page=1)], [(612, 792)])


def test_a_file_that_is_not_a_pdf_is_refused():
    with pytest.raises(FormFieldError):
        read_form_fields(b"not a pdf")
