"""Offline report fixtures; neither engineering certification nor live rates."""
from copy import deepcopy
from io import BytesIO
import math
import socket

import pdfplumber
import pytest

from ai_inspector.packaging_shipping.geometry import assess
from ai_inspector.packaging_shipping.models import Design
from ai_inspector.packaging_shipping.report import render_report


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("A packaging report must not retrieve provider or image data")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def document_for(data, revision=7):
    design = Design.model_validate(data)
    return {"id": "pkg_report_fixture", "revision": revision, "schema_version": 2,
            "updated_at": "2026-11-05T12:34:56+00:00", "design": design.model_dump(mode="json"),
            "assessment": assess(design)}


@pytest.fixture
def rich_document():
    return document_for({
        "name": "Engineering review fixture with long catalog and product names",
        "product": {
            "name": "CalibrationAssembly" + "Q" * 141,
            "dimensions_m": [0.05, 0.03, 0.04], "mass_kg": 0.072, "mass_basis": "estimate",
            "mass_evidence": "Closed-solid source volume times declared material density; not weighed.",
            "source_id": "src_report_fixture", "source_revision": "a" * 64,
            "mass_calculation": {
                "volume_m3": 0.00006,
                "material": {"name": "Synthetic engineering polymer", "density_kg_m3": 1200.0,
                             "evidence": "Density certificate & lot <A-17>, laboratory reference only."},
                "exclusions": "Fasteners, internal electronics and adhesive excluded; review with the assembly owner.",
            },
        },
        "quantity": 1,
        "constraints": {"clearance_m": 0.0, "gap_m": 0.0, "allowed_orientations": [0],
                        "contents": "ordinary_nonhazardous"},
        "packages": [{
            "id": "box_review",
            "carton": {
                "name": "CatalogReviewCarton" + "C" * 141,
                "inner_m": [0.4, 0.2, 0.3], "outer_m": [0.42, 0.22, 0.32],
                "tare_kg": 0.25, "tare_evidence": "Full blank including flaps and overlaps; unweighed estimate.",
                "max_payload_kg": 10.0,
                "supplier": "Synthetic supplier & catalog <Review only>", "sku": "SKU-" + "S" * 156,
                "source_url": "https://example.invalid/catalog/" + "reference-" * 22,
                "board_blank": {"dimensions_m": [0.5, 0.5], "quantity": 2,
                                "mass_per_area_kg_m2": 0.5, "evidence": "Full-blank drawing BB-42 with basis-weight certificate."},
            },
            "placements": [{"id": "item_review", "position_m": [0.04, 0.04, 0.04], "orientation": 0}],
            "inserts": [{
                "id": "insert_review", "name": "PocketedSupportInsert" + "I" * 139,
                "dimensions_m": [0.3, 0.1, 0.2], "position_m": [0.02, 0.02, 0.02],
                "material": "Review foam", "density_kg_m3": 37.5,
                "material_evidence": "TEST density cert & lot <A-17>",
                "minimum_wall_m": 0.005, "minimum_floor_m": 0.01,
                "pockets": [
                    {"id": "rect_pocket", "shape": "rectangular", "dimensions_m": [0.08, 0.08, 0.08],
                     "position_m": [0.01, 0.02, 0.01]},
                    {"id": "round_pocket", "shape": "cylindrical", "dimensions_m": [0.06, 0.08, 0.06],
                     "position_m": [0.17, 0.02, 0.1]},
                ],
            }],
            "allowance_kg": 0.05, "allowance_evidence": "Tape and labels allowance; no postage.",
            "graphics": [
                {"id": "handling_text", "target": "carton", "face": "z+", "kind": "text",
                 "text": "<b>FRAGILE & keep dry</b> " + "LONGGRAPHIC" * 30,
                 "color": "#17191C", "u": 0.4, "v": 0.6, "width_fraction": 0.6,
                 "height_fraction": 0.2, "rotation_degrees": 90},
                {"id": "insert_artwork", "target": "insert", "target_id": "insert_review", "face": "y+",
                 "kind": "image", "image_id": "img_scoped_review_only", "width_fraction": 0.5,
                 "height_fraction": 0.25, "rotation_degrees": 180},
            ],
        }],
    })


def quote(revision, marker, amount="007.10"):
    return {"revision": revision, "provider": "Synthetic EasyPost", "quoted_at": "2026-11-05T11:00:00+00:00",
            "notice": f"{marker}; saved estimate only. No postage was purchased.",
            "results": [{"destination": {"city": "Chicago", "state": "IL", "zip": "60601"},
                         "totals": [{"mode": "test", "carrier": "Fixture Carrier", "service": "Ground",
                                     "account_id": "ca_TEST_REPORT", "amount": amount, "currency": "USD",
                                     "basis": "Saved separate-parcel snapshot"}]}]}


def report_text(document, quotes=()):
    payload = render_report(document, quotes)
    assert payload.startswith(b"%PDF-")
    with pdfplumber.open(BytesIO(payload)) as reader:
        assert reader.metadata["Title"] == "InspectorPro Packaging Review"
        return " ".join("\n".join(page.extract_text() or "" for page in reader.pages).split())


@pytest.mark.parametrize("damage,code", [
    ("wall", "pocket_wall_thin"), ("floor", "pocket_floor_thin"),
    ("closed", "pocket_not_top_open"), ("overlap", "pocket_web_thin"),
])
def test_invalid_cutouts_report_unavailable_mass_without_crashing(rich_document, damage, code):
    design = deepcopy(rich_document["design"])
    pockets = design["packages"][0]["inserts"][0]["pockets"]
    if damage == "wall":
        pockets[0]["position_m"][0] = 0.0
    elif damage == "floor":
        pockets[0]["position_m"][1] = 0.0
        pockets[0]["dimensions_m"][1] = 0.1
    elif damage == "closed":
        pockets[0]["dimensions_m"][1] = 0.05
    else:
        pockets[1]["position_m"] = list(pockets[0]["position_m"])
    document = document_for(design)
    assert document["assessment"]["packages"][0]["insert_kg"] is None
    assert document["assessment"]["packages"][0]["gross_kg"] is None
    text = report_text(document)
    for expected in ("Inserts: Unavailable kg", "Gross mass: Unavailable kg", "INVALID CUTOUT GEOMETRY",
                     "Net material volume: Unavailable m3", "Insert mass from net volume x density: Unavailable kg", code):
        assert expected in text
    assert "not accepted subtraction volumes" in text
    assert "None kg" not in text and "Inserts: 0.0000 kg" not in text


def test_density_mass_calculation_retains_evidence_and_exclusions(rich_document):
    text = report_text(rich_document)
    for expected in ("Density-based mass calculation (estimate)", "Recorded solid volume: 6e-05 m3",
                     "Physical density: 1200 kg/m3", "Synthetic engineering polymer",
                     "Density certificate & lot <A-17>, laboratory reference only.",
                     "Fasteners, internal electronics and adhesive excluded", "Mass per item: 0.072 kg",
                     "not a measured item mass", "src_report_fixture", "a" * 64):
        assert expected in text


def test_rectangular_and_cylindrical_net_geometry_is_reported(rich_document):
    text = report_text(rich_document)
    removed = 0.08 ** 3 + math.pi * 0.03 ** 2 * 0.08
    net = 0.3 * 0.1 * 0.2 - removed
    for expected in ("Gross block volume: 0.006 m3", f"Nominal pocket volume: {removed:.8g} m3",
                     f"Net material volume: {net:.8g} m3", f"Insert mass from net volume x density: {net * 37.5:.4f} kg",
                     "Pocket rect_pocket: rectangular", "Pocket round_pocket: cylindrical",
                     "Diameter: 60.00 mm", "Depth along +Y: 80.00 mm", "80.00 x 80.00 x 80.00",
                     "Required side wall / web: 5.00 mm", "Required remaining floor: 10.00 mm",
                     "positions are relative to the insert, not the carton", "Density source: TEST density cert & lot <A-17>"):
        assert expected in text
    assert "INVALID CUTOUT GEOMETRY" not in text


def test_catalog_evidence_board_blank_and_graphic_schedule(rich_document):
    text = report_text(rich_document)
    for expected in ("Catalog supplier: Synthetic supplier & catalog <Review only>",
                     "Catalog source / evidence: https://example.invalid/catalog/", "SKU:",
                     "Full board blank (mm): 500.00 x 500.00", "Basis weight: 0.5 kg/m2",
                     "Full-blank drawing BB-42", "Surface graphic schedule", "Target: carton | Face: z+",
                     "Face-local center (u, v): 0.400, 0.600", "Fit region: 60.0% width x 20.0% height",
                     "Rotation: 90 degrees", "Lettering: <b>FRAGILE & keep dry</b>",
                     "Target: insert insert_review | Face: y+", "Scoped image reference: img_scoped_review_only",
                     "not print-ready artwork or a verified carrier label"):
        assert expected in text


def test_revision_and_rate_snapshots_are_not_mutated_or_recalculated(rich_document):
    rich_document["assessment"]["packages"][0]["gross_kg"] = 987.654
    quotes = [quote(6, "STALE_SNAPSHOT", "111.11"), quote(7, "CURRENT_SNAPSHOT"),
              quote(7, "OLDER_CURRENT_SNAPSHOT", "222.22"), quote(8, "FUTURE_SNAPSHOT", "333.33")]
    before = deepcopy((rich_document, quotes))
    text = report_text(rich_document, quotes)
    assert (rich_document, quotes) == before
    for expected in ("Document pkg_report_fixture | Revision 7", "2026-11-05T12:34:56+00:00",
                     "Gross mass: 987.654 kg", "CURRENT_SNAPSHOT", "2026-11-05T11:00:00+00:00",
                     "Account ca_TEST_REPORT: 007.10 USD", "Saved separate-parcel snapshot"):
        assert expected in text
    for excluded in ("STALE_SNAPSHOT", "OLDER_CURRENT_SNAPSHOT", "FUTURE_SNAPSHOT", "111.11", "222.22", "333.33"):
        assert excluded not in text
    assert "No postage was purchased." in text


def test_saved_mass_rows_are_bound_to_package_identity_not_list_order(rich_document):
    second = deepcopy(rich_document["design"]["packages"][0])
    second["id"] = "box_second"
    second["placements"][0]["id"] = "item_second"
    rich_document["design"]["packages"].append(second)
    first_totals = deepcopy(rich_document["assessment"]["packages"][0])
    first_totals["gross_kg"] = 10.5
    second_totals = {**first_totals, "package_id": "box_second", "gross_kg": 20.5}
    rich_document["assessment"]["packages"] = [second_totals, first_totals]
    text = report_text(rich_document)
    first, second = text.split("Package box_second:", 1)
    assert "Gross mass: 10.5 kg" in first and "Gross mass: 20.5 kg" not in first
    assert "Gross mass: 20.5 kg" in second and "Gross mass: 10.5 kg" not in second


def test_older_document_fields_and_unknown_mass_remain_renderable(rich_document):
    design = deepcopy(rich_document["design"])
    product = design["product"]
    product.pop("mass_calculation")
    product.update(mass_kg=None, mass_basis="unknown", mass_evidence="")
    box = design["packages"][0]
    box.pop("graphics")
    for key in ("supplier", "sku", "source_url", "board_blank"):
        box["carton"].pop(key)
    box["inserts"][0].pop("pockets")
    document = document_for(design)
    # Simulate an older persisted payload, without optional v2 keys.
    document["design"] = design
    text = report_text(document, [quote(6, "STALE_ONLY")])
    for expected in ("Mass per item: Unavailable kg", "No pockets; solid rectangular insert.",
                     "Catalog supplier: Not recorded | SKU: Not recorded", "No surface graphics are recorded",
                     "No quotes are saved for this revision. No shipping price has been inferred."):
        assert expected in text
    assert "None kg" not in text and "STALE_ONLY" not in text


def test_empty_design_still_has_explicit_support_and_cushioning_caveat():
    text = report_text(document_for({}))
    assert "DRAFT FOR ENGINEERING REVIEW" in text
    assert "Detected geometric contact is not verification of load support or cushioning." in text
    assert "transport testing require engineering review before release" in text


def test_out_of_bounds_projection_cannot_draw_over_page_content(rich_document):
    data = deepcopy(rich_document["design"])
    data["packages"][0]["placements"][0]["position_m"] = [10000.0, 10000.0, 10000.0]
    text = report_text(document_for(data))
    assert "1 out-of-bounds product envelope(s) omitted from the projection" in text
    assert "10000000.00, 10000000.00, 10000000.00" in text
    assert "Product envelope violates the carton clearance." in text


def test_multipage_long_names_render_within_page_bounds(rich_document, tmp_path):
    pymupdf = pytest.importorskip("pymupdf", reason="Raster acceptance requires a local PDF renderer")
    payload = render_report(rich_document, [quote(7, "OFFLINE_RENDER_FIXTURE")])
    pdf_path = tmp_path / "packaging-review-v2.pdf"
    pdf_path.write_bytes(payload)
    with pdfplumber.open(BytesIO(payload)) as reader:
        assert len(reader.pages) >= 3
        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            assert f"Revision 7 | Page {page_number}" in text
            assert "InspectorPro | Draft packaging review" in text
            assert "\u25a0" not in text and "\ufffd" not in text
            if "Pocket rect_pocket:" in text:
                assert "80.00 x 80.00 x 80.00" in text
            if "Pocket round_pocket:" in text:
                assert "Diameter: 60.00 mm" in text
            if "Graphic handling_text:" in text:
                assert "Lettering:" in text
            if "Graphic insert_artwork:" in text:
                assert "Scoped image reference:" in text
            for char in page.chars:
                assert 46 <= char["x0"] < char["x1"] <= 566, (page_number, char)
                assert 35 <= char["top"] < char["bottom"] <= 774, (page_number, char)
    with pymupdf.open(stream=payload, filetype="pdf") as rendered:
        for page_number, page in enumerate(rendered, start=1):
            pixels = page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
            pixels.save(str(tmp_path / f"page-{page_number:02}.png"))
            assert min(pixels.samples) < 64
            assert sum(value < 200 for value in pixels.samples) > 5000
    print(f"Visual QA fixture: {pdf_path}")
