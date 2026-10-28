"""The 2D plan PDF: one reusable sheet template, filled from any saved layout."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import re
import zlib

import pytest

from ai_inspector.facility_layout.pdf_canvas import Document, text_width
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.facility_layout.plan_pdf import (area_label, feet_inches, length_label, load_template, pick_scale,
                                                    quadrant_bearing, render_plan_pdf)
from ai_inspector.facility_layout.site_context import KEY
from ai_inspector.facility_layout.site_plan import plan_warehouse
from tests.test_facility_layout_api import _client, _layout, _principal
from tests.test_facility_site_plan import ARTERIAL, LOT, RAIL, STREET, site_doc, staged

NOW = datetime(2026, 10, 23, tzinfo=timezone.utc)
BOX = {"assetId": "asset-test-box", "displayName": "Test box",
       "geometry": {"obb": {"center": {"x": 0, "y": 0.5, "z": 0}, "halfExtents": {"x": 0.6, "y": 0.5, "z": 1.2}}}}


def check_structure(pdf: bytes) -> int:
    """The cross-reference table points at every object; returns the page count."""
    assert pdf.startswith(b"%PDF-1.4\n") and pdf.rstrip().endswith(b"%%EOF")
    start = int(re.search(rb"startxref\n(\d+)\n", pdf).group(1))
    assert pdf[start:].startswith(b"xref\n")
    count = int(re.match(rb"xref\n0 (\d+)\n", pdf[start:]).group(1))
    offsets = re.findall(rb"(\d{10}) 00000 n \n", pdf[start:])
    assert len(offsets) == count - 1
    for number, offset in enumerate(offsets, start=1):
        assert pdf[int(offset):].startswith(f"{number} 0 obj\n".encode())
    return int(re.search(rb"/Type /Pages /Kids \[[^\]]*\] /Count (\d+)", pdf).group(1))


def contents(pdf: bytes) -> list[bytes]:
    """Every page's decompressed drawing instructions, in order (images left out)."""
    pages = []
    for match in re.finditer(rb"<< ([^\n]*?)/Filter /FlateDecode /Length (\d+) >>\nstream\n", pdf):
        if b"/Subtype /Image" not in match.group(1):
            pages.append(zlib.decompress(pdf[match.end():match.end() + int(match.group(2))]))
    return pages


def test_lengths_are_feet_and_inches_with_metres_in_brackets():
    assert feet_inches(93.0) == "305'-1\"" and feet_inches(3.0) == "9'-10\"" and feet_inches(0.2) == '8"'
    assert length_label(3.7) == "12'-2\" (3.7 m)"
    assert area_label(5208) == "56,058 SF (5,208 m\xb2)"


def test_the_scale_is_the_largest_standard_scale_that_fits():
    scales = load_template()["scalesFeetPerInch"]
    assert pick_scale((0, 0, 93, 56), (0, 0, 911, 670), scales) == 30  # 1" = 20' would need 1,098 pt
    assert pick_scale((0, 0, 260, 160), (0, 0, 911, 670), scales) == 80


def test_the_writer_makes_a_well_formed_pdf_with_standard_fonts_and_an_image():
    document = Document(title="Test")
    page = document.add_page(1224, 792)
    page.line((10, 10), (100, 100), stroke="#18212A", width=0.5, dash=[3, 2])
    page.polygon([(0, 0), (10, 0), (10, 10)], fill="#ECEEF0", stroke="#C3C8CD")
    page.text(50, 50, "WAREHOUSE (A) \\ 56,058 SF", size=10, font="bold", align="center", angle=90)
    document.add_image("Logo", 2, 1, b"\x00\x00\x00\xff\xff\xff", b"\x00\xff")
    page.image("Logo", 0, 0, 20, 10)
    pdf = document.to_bytes()
    assert check_structure(pdf) == 1
    assert b"/BaseFont /Helvetica-Bold" in pdf and b"/SMask" in pdf
    [content] = contents(pdf)
    assert b"(WAREHOUSE \\(A\\) \\\\ 56,058 SF) Tj" in content and b"/Logo Do" in content
    assert text_width("WAREHOUSE", 10, "bold") == pytest.approx(66.11)


def test_a_layout_without_a_site_gets_only_the_floor_plan():
    layout = {"layoutId": "fl-test-hall", "displayName": "Test hall", "association": {"siteId": "site-a"},
              "extensions": {"facilityPlan": {"widthMeters": 40, "depthMeters": 30}},
              "zones": [{"zoneId": "zn-store", "zoneType": "storage", "label": "Storage",
                         "boundary": [{"x": 2, "z": 2}, {"x": 38, "z": 2}, {"x": 38, "z": 28}, {"x": 2, "z": 28}]}],
              "placements": [{"placementId": "pl-box", "assetId": "asset-test-box", "assetDefinitionRevision": "r1",
                              "transform": {"position": {"x": 10, "y": 0, "z": 10},
                                            "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1}, "scale": 1}},
                             {"placementId": "pl-unknown", "assetId": "asset-missing", "assetDefinitionRevision": "r1",
                              "transform": {"position": {"x": 20, "y": 0, "z": 20},
                                            "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1}, "scale": 1}}],
              "floorMarkings": [], "routes": []}
    before = deepcopy(layout)
    pdf = render_plan_pdf(layout, lambda asset_id, revision: BOX if asset_id == "asset-test-box" else None,
                          revision="abc123", now=NOW)
    assert check_structure(pdf) == 1 and layout == before
    [page] = contents(pdf)
    for text in (b"(FLOOR PLAN) Tj", b"(A-101) Tj", b"(1 OF 1) Tj", b"(Test hall) Tj", b"(2026-10-23) Tj",
                 b"(131'-3\" \\(40.0 m\\)) Tj", b"(98'-5\" \\(30.0 m\\)) Tj", b"(STORAGE) Tj", b"(Equipment) Tj"):
        assert text in page, text
    assert b"SITE PLAN" not in page


def planned_site():
    doc, site = site_doc(STREET, ARTERIAL, RAIL)
    doc["extensions"][KEY] = site
    return staged(doc, plan_warehouse(doc, site, LOT, "south")["operations"])


def test_a_planned_site_gets_a_site_plan_a_setting_out_plan_and_a_floor_plan():
    pdf = render_plan_pdf(planned_site(), None, revision="r", now=NOW)
    assert check_structure(pdf) == 3
    site_page, setting_out_page, floor_page = contents(pdf)
    for text in (b"(SITE PLAN) Tj", b"(C-101) Tj", b"(1 OF 3) Tj", b"(Property line) Tj", b"(Property area) Tj",
                 b"(3.46 acres \\(14,000 m\xb2\\)) Tj", b"(Exterior wall) Tj", b"(TO STATE HWY 95) Tj"):
        assert text in site_page, text
    for text in (b"(SETTING-OUT PLAN) Tj", b"(C-102) Tj", b"(2 OF 3) Tj", b"(A-B) Tj", b"(Centre) Tj",
                 b"(No reference points yet: ask Sage to add them.) Tj", b"(Not checked yet.) Tj"):
        assert text in setting_out_page, text
    for text in (b"(FLOOR PLAN) Tj", b"(A-101) Tj", b"(3 OF 3) Tj", b"(D1) Tj", b"(RECEIVING) Tj", b"(Dock doors) Tj"):
        assert text in floor_page, text
    assert re.search(rb"\(Mill St\) Tj|\(State Hwy 95\) Tj", site_page)  # a road name along its road


def test_the_site_plan_draws_the_traced_lot_smooth_and_painted_words_inside_their_markings():
    # Live 2026-10-24: the yard tiles printed as stepped blocks, and "ACCESSIBLE" and "EMPLOYEE ENTRANCE" ran
    # over the stall lines.
    built = planned_site()
    built["extensions"][KEY]["areas"].append({
        "areaId": "area-lot", "kind": "existing_pavement", "label": "Paved lot",
        "boundary": [{"x": -20, "z": 50}, {"x": 160, "z": 55}, {"x": 150, "z": 98}, {"x": 10, "z": 92}]})

    def marking(marking_id, kind, text, width, depth):
        return {"markingId": marking_id, "markingType": kind, "semanticRole": "parking", "text": text,
                "width": width, "depth": depth, "transform": {"position": {"x": 10, "y": 0, "z": -30}}}
    # At this sheet's 1" = 50' a 2.6 m box is about 12 pt long: room for "VAN", not for "ACCESSIBLE".
    built["floorMarkings"] = [marking("fm-van", "parking_box", "VAN", 2.4, 2.6),
                              marking("fm-accessible", "parking_box", "ACCESSIBLE", 2.4, 2.6),
                              marking("fm-door-label", "floor_text", "EMPLOYEE ENTRANCE", 4, 0.6)]
    site_page = contents(render_plan_pdf(built, None, now=NOW))[0]
    for text in (b"(Existing paving) Tj", b"(Pavement logo) Tj", b"(VAN) Tj"):
        assert text in site_page, text
    assert b"(ACCESSIBLE) Tj" not in site_page and b"(EMPLOYEE ENTRANCE) Tj" not in site_page


def test_bearings_read_as_a_surveyor_writes_them():
    assert quadrant_bearing(87.57) == "N 87\xb034'12\" E" and quadrant_bearing(357.57) == "N 2\xb025'48\" W"
    assert quadrant_bearing(267.57) == "S 87\xb034'12\" W" and quadrant_bearing(92.0) == "S 88\xb000'00\" E"


def test_the_setting_out_sheet_ties_each_corner_to_the_two_nearest_reference_points():
    built = planned_site()
    corners = [(0, 0), (140, 0), (140, 100), (0, 100)]
    with_points = apply_facility_layout_operations(deepcopy(built), [
        {"op": "upsert_site_reference", "reference": {"referenceId": f"rp-{i + 1}", "label": f"Corner {i + 1}",
                                                      "kind": "property_corner", "source": "county_parcel",
                                                      "x": x, "z": z, "accuracyMeters": 3}}
        for i, (x, z) in enumerate(corners)])["document"]
    fit = {"summary": ["At 2 of 5 mapped crossings near the building the road map is on average 2.8 m from the photo."],
           "survey": {"pending": "No reference point has a measured position yet."}}
    page = contents(render_plan_pdf(with_points, None, now=NOW, fit=fit))[1]
    for text in (b"(RP1) Tj", b"(RP4) Tj", b"(Corner 3) Tj", b"(county parcel, \xb13 m) Tj", b"(Reference point) Tj",
                 b"(Tie \\(distance and bearing\\)) Tj", b"(No reference point has a measured position yet.) Tj"):
        assert text in page, text
    assert page.count(b"(RP") >= 4 + 8  # four markers and two ties per corner in the table
    assert b"(At 2 of 5 mapped crossings near the building the road map is on average 2.8 m from the photo.) Tj" in page


def test_the_one_template_drives_every_sheet():
    template = load_template()
    assert [sheet["kind"] for sheet in template["sheets"]] == ["site", "setting-out", "floor"]
    assert template["page"] == {"widthInches": 17, "heightInches": 11, "marginInches": 0.35}
    custom = deepcopy(template)
    custom["sheets"] = [{"kind": "floor", "number": "X-9", "title": "PLANTA"}]
    custom["notes"] = ["A custom note."]
    custom["styles"]["wall"]["label"] = "Muro"
    doc, site = site_doc(STREET)
    doc["extensions"][KEY] = site
    built = staged(doc, plan_warehouse(doc, site, LOT, "south")["operations"])
    pdf = render_plan_pdf(built, None, now=NOW, template=custom)
    assert check_structure(pdf) == 1
    [page] = contents(pdf)
    assert b"(PLANTA) Tj" in page and b"(X-9) Tj" in page and b"(A custom note.) Tj" in page and b"(Muro) Tj" in page


def test_the_route_serves_the_saved_layout_and_respects_access(tmp_path):
    client, service, shell, policy = _client(tmp_path)
    service.create_layout(_principal(), "site-a", _layout(shell, policy))
    response = client.get("/api/facility-layouts/site-a/fl-api-cell/plan.pdf")
    assert response.status_code == 200 and response.headers["content-type"] == "application/pdf"
    assert 'filename="fl-api-cell-plan.pdf"' in response.headers["content-disposition"]
    assert check_structure(response.content) == 1
    missing = client.get("/api/facility-layouts/site-a/fl-missing/plan.pdf")
    assert missing.status_code == 404 and "error" in json.loads(missing.content)
    other_site = client.get("/api/facility-layouts/site-b/fl-api-cell/plan.pdf")
    assert other_site.status_code in (403, 404) and "error" in json.loads(other_site.content)
