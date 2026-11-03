"""Site context (SC1): a layout's georeference, building pose and aerial imagery."""
from io import BytesIO
import json
from pathlib import Path
import types

from PIL import Image
import pytest

from ai_inspector.facility_layout import site_imagery
from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.facility_layout.geo import geographic_box
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.facility_layout.site_context import KEY, default_building_pose, normalize_site_context
from ai_inspector.facility_layout.validate import validate_layout

ORIGIN = {"originLatitude": 44.9778, "originLongitude": -93.265}


def layout():
    return json.loads((Path(__file__).parent / "fixtures/facility_layout/empty_cell.json").read_text())


def site_id(doc):
    return doc["association"]["siteId"]


def image(doc, half=200.0, digest="c" * 64, source="usgs_naip"):
    return {"imageId": digest, "imagePath": f"/api/facility-site-imagery/{site_id(doc)}/{digest}.jpg",
            "source": source, "captured": "2021-06-18",
            "geoBounds": geographic_box(ORIGIN["originLatitude"], ORIGIN["originLongitude"], half, half),
            "widthPixels": 800, "heightPixels": 800}


def apply(doc, *operations):
    return apply_facility_layout_operations(doc, list(operations))["document"]


def test_a_georeference_alone_gets_the_default_pose_and_no_imagery():
    doc = layout()
    value = normalize_site_context({"version": 1, "georeference": {**ORIGIN, "label": " 1 Main St "}}, doc)
    assert value["georeference"] == {"datum": "WGS84", **ORIGIN, "placedBy": "coordinates", "label": "1 Main St"}
    assert value["buildingPose"] == default_building_pose(doc)
    assert value["imagery"] == []


def test_image_corners_are_derived_from_its_box_and_follow_the_origin():
    doc = layout()
    value = normalize_site_context({"version": 1, "georeference": ORIGIN, "imagery": [image(doc)]}, doc)
    item = value["imagery"][0]
    assert [round(c["x"]) for c in item["corners"]] == [-200, 200, 200, -200]
    assert [round(c["z"]) for c in item["corners"]] == [-200, -200, 200, 200]
    assert item["license"] == "public_domain" and "USGS" in item["attribution"]
    assert item["metersPerPixel"] == pytest.approx(0.5, abs=0.01)
    # Stale derived fields from a client are recomputed, never trusted.
    stale = {**image(doc), "corners": [{"x": 0, "z": 0}] * 4, "metersPerPixel": 9}
    assert normalize_site_context({"version": 1, "georeference": ORIGIN, "imagery": [stale]}, doc)["imagery"][0] == item
    # Moving the origin 100 m north moves the same image 100 m south in the property frame.
    moved = dict(ORIGIN, originLatitude=ORIGIN["originLatitude"] + 100 / 111135.0)
    shifted = normalize_site_context({"version": 1, "georeference": moved, "imagery": [image(doc)]}, doc)["imagery"][0]
    assert shifted["corners"][0]["z"] == pytest.approx(item["corners"][0]["z"] - 100, abs=0.5)


@pytest.mark.parametrize("patch", [
    {"georeference": {"originLatitude": 95, "originLongitude": 0}},
    {"georeference": {**ORIGIN, "datum": "NAD27"}},
    {"georeference": {**ORIGIN, "placedBy": "satellite"}},
    {"buildingPose": {"x": 9000, "z": 0, "bearingDegrees": 0}},
    {"version": 2},
    {"extra": True},
])
def test_invalid_site_contexts_are_rejected(patch):
    with pytest.raises(ValueError):
        normalize_site_context({"version": 1, "georeference": ORIGIN, **patch}, layout())


@pytest.mark.parametrize("patch", [
    lambda doc: {"imagery": [image(doc, source=[])]},
    lambda doc: {"overlays": [{"layer": []}]},
    lambda doc: {"layerChecks": {"geometryKey": "0123456789abcdef", "results": [{"layer": {}}]}},
])
def test_kinds_that_are_not_strings_are_rejected(patch):
    # 2026-11-03: a list or an object here made the dict lookup raise TypeError (an HTTP 500 on a whole save).
    doc = layout()
    with pytest.raises(ValueError):
        normalize_site_context({"version": 1, "georeference": ORIGIN, **patch(doc)}, doc)


def test_images_must_be_stored_for_this_site_and_listed_once():
    doc = layout()
    foreign = dict(image(doc), imagePath="/api/facility-site-imagery/other-site/" + "c" * 64 + ".jpg")
    with pytest.raises(ValueError, match="another site"):
        normalize_site_context({"version": 1, "georeference": ORIGIN, "imagery": [foreign]}, doc)
    with pytest.raises(ValueError, match="twice"):
        normalize_site_context({"version": 1, "georeference": ORIGIN, "imagery": [image(doc), image(doc)]}, doc)
    with pytest.raises(ValueError, match="too large"):
        normalize_site_context({"version": 1, "georeference": ORIGIN, "imagery": [image(doc, half=2500)]}, doc)


def test_the_operation_saves_validates_and_removes_the_site_context():
    doc = layout()
    placed = apply(doc, {"op": "set_site_context", "siteContext": {"version": 1, "georeference": ORIGIN,
                                                                    "imagery": [image(doc)]}})
    assert placed["extensions"][KEY]["imagery"][0]["corners"][0]["x"] == pytest.approx(-200, abs=0.5)
    assert placed["placements"] == doc["placements"] and placed["zones"] == doc["zones"]
    validate_layout(placed)
    assert KEY not in apply(placed, {"op": "set_site_context", "siteContext": None})["extensions"]
    with pytest.raises(FacilityLayoutError):
        apply(doc, {"op": "set_site_context", "siteContext": {"version": 1}})


# The imagery service, with the network replaced ---------------------------------------------

def jpeg(width=64, height=64):
    out = BytesIO()
    Image.new("RGB", (width, height), (90, 120, 80)).save(out, format="JPEG")
    return out.getvalue()


class Reply:
    def __init__(self, body, content_type):
        self.body, self.headers = body, {"Content-Type": content_type}

    def read(self, _limit=None):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_network(monkeypatch, replies):
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
    monkeypatch.setattr(site_imagery, "_urlopen", opener)
    return calls


def drawn_answer(bounds, size=64, host="imagery.nationalmap.gov", widen=1.0):
    """An exportImage JSON answer; widen > 1 stretches the box north-south as the basemap does."""
    middle = (bounds["south"] + bounds["north"]) / 2
    half = (bounds["north"] - bounds["south"]) / 2 * widen
    extent = {"xmin": bounds["west"], "ymin": middle - half, "xmax": bounds["east"], "ymax": middle + half,
              "spatialReference": {"wkid": 4326, "latestWkid": 4326}}
    answer = {"href": f"https://{host}/arcgis/rest/directories/output/_ags_test.jpg",
              "width": size, "height": size, "extent": extent}
    return Reply(json.dumps(answer).encode(), "application/json")


IDENTIFY = json.dumps({"catalogItems": {"features": [{"attributes": {"acquisition_date": 1623974400000}}]}}).encode()


def test_plan_request_is_square_at_half_a_metre_per_pixel():
    plan = site_imagery.plan_request(44.9778, -93.265, 250)
    assert plan["widthPixels"] == plan["heightPixels"] == 1000
    assert plan["bounds"]["south"] < 44.9778 < plan["bounds"]["north"]
    with pytest.raises(ValueError):
        site_imagery.plan_request(44.9778, -93.265, 5000)


def test_a_failed_naip_answer_is_retried_and_dated(monkeypatch):
    bounds = geographic_box(44.9778, -93.265, 50, 50)
    calls = fake_network(monkeypatch, [Reply(b"<html>502</html>", "text/html"), drawn_answer(bounds),
                                       Reply(jpeg(), "image/jpeg"), Reply(IDENTIFY, "application/json")])
    content, source, captured, drawn = site_imagery.fetch_aerial(bounds, 64, 64)
    assert source == "usgs_naip" and captured == "2021-06-18"
    assert Image.open(BytesIO(content)).format == "JPEG"
    assert drawn == pytest.approx(bounds)
    assert len(calls) == 4 and "bbox=" in calls[1] and "identify" in calls[3]
    # NAIP is asked to draw exactly the box; the picture is fetched from the link it answers with.
    assert "adjustAspectRatio=false" in calls[1] and "f=json" in calls[1]
    assert calls[2] == "https://imagery.nationalmap.gov/arcgis/rest/directories/output/_ags_test.jpg"


def test_the_photo_keeps_the_box_the_service_drew(monkeypatch):
    # The basemap widens the box to square pixels in degrees: 1.4 times taller at 45 N. The photo
    # covers the wider box, so that is the box to keep, or north-south distances shrink by 30 %.
    bounds = geographic_box(44.9778, -93.265, 250, 250)
    fake_network(monkeypatch, [OSError("down"), OSError("down"),
                               drawn_answer(bounds, host="basemap.nationalmap.gov", widen=1.41),
                               Reply(jpeg(), "image/jpeg")])
    _, source, _, drawn = site_imagery.fetch_aerial(bounds, 64, 64)
    assert source == "usgs_imagery" and drawn["west"] == bounds["west"] and drawn["east"] == bounds["east"]
    assert (drawn["north"] - drawn["south"]) == pytest.approx(1.41 * (bounds["north"] - bounds["south"]))
    # A link to another host, a picture of another size or a box elsewhere is refused.
    elsewhere = dict(bounds, south=bounds["north"] + 0.01, north=bounds["north"] + 0.02)
    for bad in (drawn_answer(bounds, host="example.com"), drawn_answer(bounds, size=32),
                drawn_answer(elsewhere)):
        fake_network(monkeypatch, [bad] * 3)
        with pytest.raises(FacilityLayoutError):
            site_imagery.fetch_aerial(bounds, 64, 64)


def test_the_basemap_stands_in_when_naip_is_down_and_errors_are_clear(monkeypatch):
    bounds = geographic_box(44.9778, -93.265, 50, 50)
    fake_network(monkeypatch, [OSError("down"), OSError("down"),
                               drawn_answer(bounds, host="basemap.nationalmap.gov"), Reply(jpeg(), "image/jpeg")])
    assert site_imagery.fetch_aerial(bounds, 64, 64)[1:3] == ("usgs_imagery", None)
    fake_network(monkeypatch, [OSError("down")] * 3)
    with pytest.raises(FacilityLayoutError) as error:
        site_imagery.fetch_aerial(bounds, 64, 64)
    assert error.value.code == "site_imagery_unavailable"
    # A wrong-sized picture is not accepted as the requested box.
    fake_network(monkeypatch, [drawn_answer(bounds), Reply(jpeg(32, 32), "image/jpeg")] * 3)
    with pytest.raises(FacilityLayoutError):
        site_imagery.fetch_aerial(bounds, 64, 64)


def test_geocode_returns_us_census_matches(monkeypatch):
    answer = {"result": {"addressMatches": [{"matchedAddress": "350 S 5TH ST, MINNEAPOLIS, MN, 55415",
                                             "coordinates": {"x": -93.26545, "y": 44.97754}}]}}
    fake_network(monkeypatch, [Reply(json.dumps(answer).encode(), "application/json")])
    assert site_imagery.geocode("350 S 5th St, Minneapolis, MN") == [
        {"label": "350 S 5TH ST, MINNEAPOLIS, MN, 55415", "latitude": 44.97754, "longitude": -93.26545}]
    with pytest.raises(ValueError):
        site_imagery.geocode("x")


def test_images_are_stored_once_per_site(tmp_path):
    principal = types.SimpleNamespace(tenant_id="local")
    first = site_imagery.store_jpeg(tmp_path, principal, "site-a", jpeg())
    assert site_imagery.store_jpeg(tmp_path, principal, "site-a", jpeg()) == first
    assert len(list(tmp_path.rglob("*.jpg"))) == 1


# The high-resolution option: the 2025 Twin Cities metro photo from MnGeo -----------------------

def test_metro_photo_is_drawn_for_exactly_the_requested_box(monkeypatch):
    bounds = geographic_box(45.0212, -92.7776, 150, 150)
    calls = fake_network(monkeypatch, [Reply(b"<ServiceException>busy</ServiceException>", "application/vnd.ogc.se_xml"),
                                       Reply(jpeg(), "image/jpeg")])
    content, source, captured, drawn = site_imagery.fetch_mngeo_metro(bounds, 64, 64)
    assert (source, captured, drawn) == ("mngeo_metro", "2025-04", bounds)
    assert Image.open(BytesIO(content)).size == (64, 64)
    # A WMS error document is retried once; GetMap asks for the box itself, in latitude/longitude.
    assert len(calls) == 2 and "LAYERS=met25" in calls[1] and "SRS=EPSG%3A4326" in calls[1]
    assert f"{bounds['west']:.8f}%2C{bounds['south']:.8f}" in calls[1]


def test_metro_photo_outside_the_metro_or_without_coverage_is_refused(monkeypatch):
    calls = fake_network(monkeypatch, [])
    with pytest.raises(FacilityLayoutError) as error:
        site_imagery.fetch_mngeo_metro(geographic_box(44.50, -88.06, 150, 150), 64, 64)  # Green Bay, WI
    assert (error.value.code, error.value.status_code, calls) == ("site_imagery_not_covered", 422, [])
    white = BytesIO()
    Image.new("RGB", (64, 64), (255, 255, 255)).save(white, format="JPEG")
    fake_network(monkeypatch, [Reply(white.getvalue(), "image/jpeg")])
    with pytest.raises(FacilityLayoutError) as error:
        site_imagery.fetch_mngeo_metro(geographic_box(45.0212, -92.7776, 150, 150), 64, 64)
    assert error.value.code == "site_imagery_not_covered"


def test_metro_photo_is_finer_and_kept_with_its_attribution():
    plan = site_imagery.plan_request(45.0212, -92.7776, 150, site_imagery.HIGH_RES_METERS_PER_PIXEL)
    assert plan["widthPixels"] == plan["heightPixels"] == 1000
    assert site_imagery.plan_request(45.0212, -92.7776, 1000, 0.3)["widthPixels"] == site_imagery.MAX_SIDE_PIXELS
    doc = layout()
    value = normalize_site_context({"version": 1, "georeference": dict(ORIGIN),
                                    "imagery": [dict(image(doc, source="mngeo_metro"), captured="2025-04")]}, doc)
    assert value["imagery"][0]["license"] == "public_domain"
    assert value["imagery"][0]["attribution"].startswith("Metropolitan Council / MnGeo 2025")
