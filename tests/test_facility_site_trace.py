"""Paved features on the stored site photo: find, trace and measure (find-and-build plan, step F).

The photo is synthetic: a striped asphalt lot with parked cars, a street joined to it by a driveway,
a white roof against its east side, a dry-grass patch, and a parking strip running south from it.
"""
from copy import deepcopy
import base64
from io import BytesIO
import json
import math

import numpy as np
from PIL import Image
import pytest

from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.facility_layout.geo import from_property, geographic_box
from ai_inspector.facility_layout.site_context import KEY, analyze_site_context, normalize_site_context
from ai_inspector.facility_layout.site_trace import annotated_photo, find_features, trace_feature
from tests.test_facility_site_property import fixture

HALF = 100.0          # the photo covers 200 x 200 m
SIZE = 400            # at 0.5 m a pixel
LOT = (-60, 20, -30, 30)        # x min, x max, z min, z max: 80 x 60 m of asphalt
STRIP = (-60, -40, -90, -30)    # a 20 m parking strip running south from the lot
ROOF = (20, 60, -20, 20)        # a white roof right against the lot's east side
GRASS = (-60, -30, 30, 38)      # dry grass north of the lot's west half
DRIVE = (-10, -4, 30, 40)       # a 6 m driveway up to the street
STREET_Z = 44.0                 # a 9 m street, east-west


def pixels(x0, x1, z0, z1):
    """Pixel rows and columns covering a property-frame rectangle."""
    col = lambda x: int(round((x + HALF) / (2 * HALF) * SIZE))  # noqa: E731
    row = lambda z: int(round((HALF - z) / (2 * HALF) * SIZE))  # noqa: E731
    return slice(row(z1), row(z0)), slice(col(x0), col(x1))


def scene() -> bytes:
    rng = np.random.default_rng(7)
    rgb = np.empty((SIZE, SIZE, 3), dtype=np.float32)
    rgb[:] = (62, 118, 52)  # summer grass
    rgb += rng.normal(0, 6, rgb.shape)
    for area in (LOT, STRIP, DRIVE):
        rgb[pixels(*area)] = (108, 108, 112) + rng.normal(0, 4, rgb[pixels(*area)].shape)
    rgb[pixels(-100, 100, STREET_Z - 4.5, STREET_Z + 4.5)] = (100, 100, 104)
    rgb[pixels(*ROOF)] = (214, 214, 212)
    rgb[pixels(*GRASS)] = (184, 168, 132)
    rows, cols = pixels(*LOT)
    for column in range(cols.start + 4, cols.stop - 2, 5):  # stall stripes every 2.5 m
        rgb[rows.start + 2:rows.stop - 2, column] = (232, 232, 232)
    for _ in range(60):  # parked cars, 2 x 4.5 m
        x = rng.uniform(LOT[0] + 3, LOT[1] - 3)
        z = rng.uniform(LOT[2] + 4, LOT[3] - 4)
        rgb[pixels(x - 1, x + 1, z - 2.25, z + 2.25)] = rng.choice([(200, 30, 30), (20, 20, 22), (230, 230, 230),
                                                                    (40, 60, 150), (150, 150, 150)])
    out = BytesIO()
    Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)).save(out, format="JPEG", quality=92)
    return out.getvalue()


def lonlat(x, z):
    latitude, longitude, _ = from_property(x, z, 45.0, -93.0)
    return [longitude, latitude]


@pytest.fixture()
def site(tmp_path):
    doc = fixture()
    path = tmp_path / "photo.jpg"
    path.write_bytes(scene())
    context = doc["extensions"][KEY]
    site_id = doc["association"]["siteId"]
    context["imagery"] = [{"imageId": "a" * 64, "imagePath": f"/api/facility-site-imagery/{site_id}/{'a' * 64}.jpg",
                           "source": "usgs_naip", "captured": "2021-06-18",
                           "geoBounds": geographic_box(45.0, -93.0, HALF, HALF),
                           "widthPixels": SIZE, "heightPixels": SIZE}]
    context["roads"] = {"source": "census_tiger", "fetched": "2026-10-23", "geoBounds": geographic_box(45.0, -93.0, HALF, HALF),
                        "items": [{"roadId": "street", "names": ["4th Ave N"], "mtfcc": "S1400",
                                   "lonLat": [lonlat(-100, STREET_Z), lonlat(100, STREET_Z)]}]}
    return doc, normalize_site_context(context, doc), (lambda image: path)


def outline_box(traced):
    xs = [p["x"] for p in traced["outline"]]
    zs = [p["z"] for p in traced["outline"]]
    return min(xs), max(xs), min(zs), max(zs)


def test_a_box_traces_just_the_lot_meant_and_measures_it(site):
    doc, context, photo = site
    traced = trace_feature(doc, context, photo, box={"minX": -70, "maxX": 25, "minZ": -30, "maxZ": 35})
    x0, x1, z0, z1 = outline_box(traced)
    # The lot is 80 x 60 m; the roof against it, the dry grass, the driveway and the strip stay out.
    assert (x0, x1, z0, z1) == pytest.approx(LOT, abs=2.0)
    assert traced["areaSquareMeters"] == pytest.approx(80 * 60, rel=0.06)
    assert (traced["lengthMeters"], traced["widthMeters"]) == pytest.approx((80, 60), abs=2.5)
    assert traced["longAxisBearingDegrees"] == pytest.approx(90, abs=3)  # its long side runs east-west
    assert traced["perimeterMeters"] == pytest.approx(280, rel=0.08)
    assert 4 <= len(traced["outline"]) <= 48 and traced["accuracyMeters"] == 1.5  # two 0.75 m work pixels
    assert traced["photo"]["captured"] == "2021-06-18" and not traced["touchesPhotoEdge"]
    assert [road["name"] for road in traced["roadsWithin15Meters"]] == ["4th Ave N"]


def test_a_point_takes_all_the_joined_pavement_but_not_the_street_roof_or_grass(site):
    doc, context, photo = site
    traced = trace_feature(doc, context, photo, -20.0, 0.0)
    x0, x1, z0, z1 = outline_box(traced)
    assert z0 == pytest.approx(STRIP[2], abs=2.5)          # the strip south of the lot is joined pavement
    assert x1 < ROOF[0] + 2.5 and z1 < LOT[3] + 2.5         # the roof and the driveway or street are not
    assert traced["areaSquareMeters"] == pytest.approx(80 * 60 + 20 * 60, rel=0.07)


@pytest.mark.parametrize("point,message", [((0.0, -70.0), "No pavement"), ((150.0, 0.0), "outside the site photo")])
def test_a_trace_off_the_pavement_or_the_photo_is_refused(site, point, message):
    doc, context, photo = site
    with pytest.raises(FacilityLayoutError) as error:
        trace_feature(doc, context, photo, *point)
    assert error.value.status_code == 422 and message in str(error.value)


def test_a_site_without_a_photo_cannot_be_traced(site):
    doc, context, photo = site
    with pytest.raises(FacilityLayoutError) as error:
        trace_feature(doc, {**context, "imagery": []}, photo, 0.0, 0.0)
    assert error.value.code == "site_photo_missing"


def test_finding_letters_the_paved_areas_largest_first_and_draws_them(site):
    doc, context, photo = site
    found = find_features(doc, context, photo)
    features = found["features"]
    assert [f["featureId"] for f in features][:2] == ["A", "B"]
    lot, roof = features[0], features[1]
    assert lot["areaSquareMeters"] == pytest.approx(80 * 60 + 20 * 60, rel=0.08)
    assert roof["areaSquareMeters"] == pytest.approx(40 * 40, rel=0.1)  # light roofs are found too, apart from the lot
    image = Image.open(BytesIO(base64.b64decode(annotated_photo(found["photoObject"], features))))
    assert image.size == (SIZE, SIZE) and image.format == "JPEG"


def test_existing_pavement_is_reference_only_in_the_site_analysis(site):
    doc, context, _photo = site
    # Existing pavement that runs under the building and through the setbacks raises no findings and is not paving.
    outline = [{"x": -60, "z": -30}, {"x": 20, "z": -30}, {"x": 20, "z": 30}, {"x": -60, "z": 30}]
    doc["extensions"][KEY] = {**context, "areas": [{"areaId": "lot", "label": "Existing pavement (USGS NAIP, 2021)",
                                                   "kind": "existing_pavement", "surface": "asphalt", "boundary": outline}]}
    analysis = analyze_site_context(doc)
    assert not any(f.get("areaId") == "lot" for f in analysis["findings"])
    assert analysis["metrics"]["pavedAreaSquareMeters"] == 0
    assert analysis["metrics"]["areas"][0]["kind"] == "existing_pavement"


def test_sage_looks_at_the_photo_and_traces_a_feature(site):
    from ai_inspector.codex_runtime.site_tools import read_site
    doc, context, photo = site
    doc["extensions"][KEY] = context
    looked = read_site(doc, "look_at_site_photo", {}, photo)
    image = looked.pop("_image")
    assert image["mimeType"] == "image/jpeg" and len(base64.b64decode(image["data"])) > 1000
    assert looked["features"][0]["featureId"] == "A" and len(json.dumps(looked)) < 65536
    traced = read_site(doc, "trace_site_feature", {"box": {"minX": -70, "maxX": 25, "minZ": -30, "maxZ": 35}}, photo)
    assert traced["areaSquareMeters"] == pytest.approx(4800, rel=0.06) and "_image" not in traced
    with pytest.raises(ValueError):
        read_site(doc, "trace_site_feature", {"x": 1.0}, photo)
    with pytest.raises(ValueError):
        read_site(doc, "look_at_site_photo", {}, None)


def test_existing_pavement_does_not_block_a_fitted_building(site):
    from ai_inspector.facility_layout.site_fit import analyze_site_fit
    doc, context, _photo = site
    covering = [{"x": -1, "z": -1}, {"x": 101, "z": -1}, {"x": 101, "z": 81}, {"x": -1, "z": 81}]
    context = deepcopy(context)
    context["property"]["setbacksMeters"] = {"street": 0, "side": 0, "rear": 0}
    doc["extensions"][KEY] = {**context, "areas": [{"areaId": "lot", "label": "Existing pavement", "kind": "existing_pavement",
                                                   "surface": "asphalt", "boundary": covering}]}
    result = analyze_site_fit(doc, {"widthMeters": 40, "depthMeters": 30})
    assert result["candidates"], result.get("reason")
    assert math.isfinite(result["candidates"][0]["buildingPose"]["x"])


def test_the_trace_route_reads_the_stored_photo_for_the_draft(site, tmp_path):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ai_inspector.facility_layout.authorization import FacilityPrincipal
    from ai_inspector.facility_layout.decal_images import scope_directory
    from ai_inspector.facility_layout.site_imagery import create_site_imagery_router
    doc, context, photo = site
    doc["extensions"][KEY] = context
    principal = FacilityPrincipal("editor", "tenant-a", ("site-a",), ("editor",))
    folder = scope_directory(tmp_path / "store" / "site-imagery", principal, "site-a")
    folder.mkdir(parents=True)
    (folder / ("a" * 64 + ".jpg")).write_bytes(photo(None).read_bytes())
    service = SimpleNamespace(layout_repository=SimpleNamespace(root=tmp_path / "store"), get_layout=lambda *args: None)
    app = FastAPI()
    app.include_router(create_site_imagery_router(service=service, principal_resolver=lambda request: principal))
    with TestClient(app) as client:
        url = "/api/facility-layouts/site-a/fl-empty-cell/site-trace"
        traced = client.post(url, json={"layout": doc, "box": {"minX": -70, "maxX": 25, "minZ": -30, "maxZ": 35}}).json()
        assert traced["areaSquareMeters"] == pytest.approx(4800, rel=0.06)
        assert client.post(url, json={"layout": doc, "x": 1.0}).json()["error"]["code"] == "invalid_site_trace"
        off = client.post(url, json={"layout": doc, "x": 0.0, "z": -70.0})
        assert off.status_code == 422 and off.json()["error"]["code"] == "site_trace_failed"
        assert client.post(url.replace("site-a", "site-b"), json={"layout": doc, "x": 0, "z": 0}).status_code == 404


def test_sage_traces_the_paved_lot_inside_the_property_line(site):
    # Bayport (2026-10-24): with the photo centred on the street address, the lot merged with pavement beyond its
    # property line; withinProperty keeps the trace to the user's property.
    from ai_inspector.codex_runtime.site_tools import read_site
    doc, context, photo = site
    doc["extensions"][KEY] = {key: value for key, value in context.items() if key != "property"}
    assert read_site(doc, "trace_site_feature", {"withinProperty": True}, photo)["available"] is False  # no line yet
    context["property"] = {"boundary": [{"x": -70, "z": -30}, {"x": 25, "z": -30}, {"x": 25, "z": 35}, {"x": -70, "z": 35}],
                           "setbacksMeters": {"street": 0, "side": 0, "rear": 0}, "streetEdges": [], "rearEdges": []}
    doc["extensions"][KEY] = normalize_site_context(context, doc)
    traced = read_site(doc, "trace_site_feature", {"withinProperty": True}, photo)
    assert traced["areaSquareMeters"] == pytest.approx(80 * 60, rel=0.06)  # the lot, not the strip joined to it
    assert outline_box(traced) == pytest.approx(LOT, abs=2.0)
    with pytest.raises(ValueError, match="outside the property"):
        read_site(doc, "trace_site_feature", {"withinProperty": True,
                                              "box": {"minX": 100, "maxX": 120, "minZ": 0, "maxZ": 10}}, photo)
