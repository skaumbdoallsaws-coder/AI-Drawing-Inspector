"""Public reference layers: county parcels, flood zones, wetlands, contours and soils (network faked)."""
from copy import deepcopy
from io import BytesIO
import json
import math
import urllib.parse

from PIL import Image, ImageDraw
import pytest

from ai_inspector.facility_layout import site_imagery, site_layers
from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.facility_layout.geo import geographic_box
from ai_inspector.facility_layout.site_context import KEY, analyze_site_context, normalize_site_context, site_geometry_key
from tests.test_facility_site_context import Reply
from tests.test_facility_site_property import fixture

LAT, LON = 45.0207, -92.7756


def route(monkeypatch, routes):
    """Answer each request by the first route whose text is in its URL; record every URL asked."""
    asked = []

    def opener(request, timeout):
        url = urllib.parse.unquote_plus(request.full_url)
        asked.append(url)
        for needle, reply in routes:
            if needle in url:
                result = reply(request) if callable(reply) else reply
                if isinstance(result, Exception):
                    raise result
                return result
        raise OSError(f"no fake route for {url[:120]}")
    monkeypatch.setattr(site_imagery, "_urlopen", opener)
    return asked


def answer(value):
    return Reply(json.dumps(value).encode(), "application/json")


def png(size=64, line=True):
    picture = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    if line:
        ImageDraw.Draw(picture).line([(0, 10), (size, 50)], fill=(0, 0, 0, 255), width=3)
    out = BytesIO()
    picture.save(out, format="PNG")
    return out.getvalue()


def circle(lat, lon, radius_m, count):
    return [[lon + radius_m * math.cos(2 * math.pi * i / count) / (111_320 * math.cos(math.radians(lat))),
             lat + radius_m * math.sin(2 * math.pi * i / count) / 111_132] for i in range(count + 1)]


# Parcels ------------------------------------------------------------------------------------------

def test_a_parcel_becomes_a_simplified_boundary_without_owner_fields(monkeypatch):
    parcel = {"attributes": {"state_pin": "27163-1102920210001", "co_name": "Washington", "ctu_name": "Bayport",
                             "anumber": "100", "st_name": "Fourth", "st_pos_typ": "Ave", "lot": "7",
                             "plat_name": "Mill Lots Bayport", "acres_poly": 2.8},
              "geometry": {"rings": [circle(LAT, LON, 60, 838)]}}
    asked = route(monkeypatch, [("plan_parcels_open", answer({"features": [parcel]}))])
    result = site_layers.fetch_parcel(LAT, LON, LAT, LON)
    assert result["parcelId"] == "27163-1102920210001" and result["county"] == "Washington"
    assert result["simplified"]["fromVertices"] == 838 and 3 <= len(result["boundary"]) <= 120
    assert result["areaSquareMeters"] == pytest.approx(math.pi * 60 ** 2, rel=0.01)
    assert result["legal"] == "Lot 7, Mill Lots Bayport" and result["address"] == "100 Fourth Ave, Bayport"
    # Only outline, PIN, address and acreage are asked for: never owner or tax fields.
    assert "owner" not in asked[0] and "tax" not in asked[0] and "outFields=" + site_layers.PARCEL_FIELDS in asked[0]


def test_parcel_lookup_refuses_outside_minnesota_and_reports_no_parcel(monkeypatch):
    asked = route(monkeypatch, [("plan_parcels_open", answer({"features": []}))])
    with pytest.raises(FacilityLayoutError) as error:
        site_layers.fetch_parcel(44.50, -88.06, 44.50, -88.06)  # Green Bay, WI
    assert (error.value.code, error.value.status_code, asked) == ("site_parcel_not_covered", 422, [])
    with pytest.raises(FacilityLayoutError) as error:
        site_layers.fetch_parcel(LAT, LON, LAT, LON)
    assert error.value.code == "site_parcel_not_found" and error.value.status_code == 404


# Display images ---------------------------------------------------------------------------------

def test_contours_come_light_with_an_interval_for_the_area(monkeypatch):
    bounds = geographic_box(LAT, LON, 150, 150)
    extent = {"xmin": bounds["west"], "ymin": bounds["south"], "xmax": bounds["east"], "ymax": bounds["north"],
              "spatialReference": {"wkid": 4326}}
    href = "https://elevation.nationalmap.gov/arcgis/rest/directories/out/_ags_c.png"
    asked = route(monkeypatch, [("_ags_c.png", Reply(png(), "image/png")),
                                ("exportImage", answer({"href": href, "width": 64, "height": 64, "extent": extent}))])
    content, drawn, detail = site_layers.fetch_overlay("contours", bounds, 64, 64)
    assert detail == "2 ft contours" and drawn == pytest.approx(bounds)
    assert "Preset 2ft Contour Interval" in asked[0] and "adjustAspectRatio=false" in asked[0]
    picture = Image.open(BytesIO(content)).convert("RGBA")
    drawn_pixels = [p for p in picture.getdata() if p[3] > 0]
    assert drawn_pixels and all(p[:3] == site_layers.CONTOUR_COLOR for p in drawn_pixels)


def test_flood_image_leaves_out_minimal_hazard_and_keeps_the_box_drawn(monkeypatch):
    bounds = geographic_box(LAT, LON, 150, 150)
    widened = {"xmin": bounds["west"], "ymin": bounds["south"] - 0.001, "xmax": bounds["east"],
               "ymax": bounds["north"] + 0.001, "spatialReference": {"wkid": 4326}}
    href = "https://hazards.fema.gov/arcgis/rest/directories/arcgisoutput/_ags_f.png"
    asked = route(monkeypatch, [("_ags_f.png", Reply(png(), "image/png")),
                                ("NFHL/MapServer/export", answer({"href": href, "width": 64, "height": 64, "extent": widened}))])
    _content, drawn, _detail = site_layers.fetch_overlay("flood", bounds, 64, 64)
    assert drawn["south"] == pytest.approx(bounds["south"] - 0.001)
    assert site_layers.FEMA_SHOWN in asked[0] and "show:28" in asked[0]


def test_soil_map_is_drawn_for_exactly_the_box(monkeypatch):
    bounds = geographic_box(LAT, LON, 150, 150)
    asked = route(monkeypatch, [("SDM.wms", Reply(png(line=False), "image/png"))])
    _content, drawn, detail = site_layers.fetch_overlay("soils", bounds, 64, 64)
    assert drawn == bounds and "LAYERS=mapunitpoly" in asked[0] and detail.startswith("Soil")


# Checks -------------------------------------------------------------------------------------------

def dem_tiff(low=210.0, high=212.4, size=48):
    grid = Image.new("F", (size, size))
    grid.putdata([low + (high - low) * (i % size) / (size - 1) for i in range(size * size)])
    out = BytesIO()
    grid.save(out, format="TIFF")
    return out.getvalue()


def test_checks_classify_each_layer_and_survive_one_service_failing(monkeypatch):
    flood = answer({"features": [{"attributes": {"FLD_ZONE": "AE", "SFHA_TF": "T", "ZONE_SUBTY": None}},
                                 {"attributes": {"FLD_ZONE": "X", "SFHA_TF": "F",
                                                 "ZONE_SUBTY": "0.2 PCT ANNUAL CHANCE FLOOD HAZARD"}},
                                 {"attributes": {"FLD_ZONE": "X", "SFHA_TF": "F",
                                                 "ZONE_SUBTY": "AREA OF MINIMAL FLOOD HAZARD"}}]})
    soils = Reply(json.dumps({"Table": [["1677144", "858", "Urban land-Chetek complex, 0 to 3 percent slopes"]]}).encode(),
                  "application/json")
    route(monkeypatch, [("NFHL/MapServer/28/query", lambda _r: flood),
                        ("Wetlands/MapServer/0/query", OSError("down")),
                        ("post.rest", lambda _r: soils),
                        ("exportImage", lambda _r: Reply(dem_tiff(), "image/tiff"))])
    ring = circle(LAT, LON, 15, 16)
    result = site_layers.check_layers([{"target": "building", "label": "Building", "ring": ring}],
                                      ["flood", "wetlands", "soils", "contours"])
    by_layer = {r["layer"]: r for r in result["results"]}
    assert [i["code"] for i in by_layer["flood"]["items"]] == ["AE", "X 0.2%"]
    assert [i["severity"] for i in by_layer["flood"]["items"]] == ["high", "moderate"]
    assert by_layer["soils"]["items"][0]["code"] == "858"
    assert by_layer["contours"]["metric"]["fallMeters"] == pytest.approx(2.0, abs=0.5)
    assert by_layer["contours"]["items"][0]["severity"] == "moderate"
    assert "wetlands" not in by_layer and result["errors"] == [
        {"layer": "wetlands", "message": "The wetlands service did not answer."}]


# The site context -----------------------------------------------------------------------------------

def overlay(doc, layer="flood", digest="d" * 64):
    site = doc["association"]["siteId"]
    return {"layer": layer, "imageId": digest, "imagePath": f"/api/facility-site-imagery/{site}/{digest}.png",
            "source": site_layers.LAYERS[layer]["source"], "captured": "2026-10-22",
            "geoBounds": geographic_box(45.0, -93.0, 150, 150), "widthPixels": 600, "heightPixels": 600,
            "detail": "FEMA flood hazard zones"}


def test_overlays_and_parcel_sourced_lots_are_kept_with_derived_corners():
    doc = fixture()
    context = deepcopy(doc["extensions"][KEY])
    context["overlays"] = [overlay(doc), overlay(doc, "contours", "e" * 64)]
    context["property"]["source"] = "county_parcel"
    value = normalize_site_context(context, doc)
    assert [o["layer"] for o in value["overlays"]] == ["flood", "contours"]
    assert len(value["overlays"][0]["corners"]) == 4 and value["overlays"][0]["license"] == "public_domain"
    assert value["property"]["source"] == "county_parcel"
    with pytest.raises(ValueError):
        normalize_site_context({**context, "overlays": [overlay(doc), overlay(doc)]}, doc)
    with pytest.raises(ValueError):
        normalize_site_context({**context, "overlays": [dict(overlay(doc), source="usgs_3dep")]}, doc)


def test_check_findings_are_reported_and_go_stale_when_the_building_moves():
    doc = fixture()
    context = normalize_site_context(doc["extensions"][KEY], doc)
    checks = {"geometryKey": site_geometry_key(doc, context), "checkedAt": "2026-10-22", "errors": [],
              "results": [{"layer": "flood", "target": "building", "targetLabel": "Building", "metric": None,
                           "items": [{"code": "AE", "label": "1% annual chance flood area (Zone AE)", "severity": "high"}]},
                          {"layer": "soils", "target": "lot", "targetLabel": "Lot", "metric": None,
                           "items": [{"code": "858", "label": "Urban land", "severity": "info"}]}]}
    doc["extensions"][KEY] = {**doc["extensions"][KEY], "layerChecks": checks}
    findings = analyze_site_context(doc)["findings"]
    assert {"code": "site_flood_zone", "severity": "warning", "target": "building",
            "message": "Building: 1% annual chance flood area (Zone AE) (FEMA flood map)."} in findings
    assert not any(f["code"] == "site_soil" for f in findings)  # information only
    pose = dict(doc["extensions"][KEY]["buildingPose"], x=doc["extensions"][KEY]["buildingPose"]["x"] + 5)
    doc["extensions"][KEY] = {**doc["extensions"][KEY], "buildingPose": pose}
    codes = [f["code"] for f in analyze_site_context(doc)["findings"]]
    assert "site_layer_checks_stale" in codes and "site_flood_zone" not in codes
