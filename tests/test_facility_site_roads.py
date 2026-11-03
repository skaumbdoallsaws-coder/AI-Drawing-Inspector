"""Roads around a site from the US Census TIGER/Line map: fetch, store, and what Sage reads (network faked)."""
from copy import deepcopy
import math

import pytest

from ai_inspector.facility_layout import site_roads
from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.facility_layout.geo import from_property, geographic_box
from ai_inspector.facility_layout.site_context import KEY, normalize_site_context
from tests.test_facility_site_layers import answer, route
from tests.test_facility_site_property import fixture

LAT, LON = 45.0, -93.0  # the fixture's origin


def lonlat(x, z):
    latitude, longitude, _ = from_property(x, z, LAT, LON)
    return [longitude, latitude]


def feature(name, mtfcc, *points, oid=1):
    return {"attributes": {"NAME": name, "MTFCC": mtfcc, "OID": oid},
            "geometry": {"paths": [[lonlat(x, z) for x, z in points]]}}


HIGHWAY = [(160, -800), (160, 800)]          # east of the lot, runs far past the box
SECONDARY = [feature("State Hwy 95", "S1200", *HIGHWAY, oid=11), feature("St Croix Trl N", "S1200", *HIGHWAY, oid=12),
             feature("3rd St N", "S1200", (160, -100), (160, 100), oid=14),  # the town's name for one stretch
             feature("County Rd 21", "S1200", (400, -800), (400, 800), oid=13)]  # past the photo, inside twice its reach
LOCAL = [feature("4th Ave N", "S1400", (-300, -6), (0, -6), (300, -6), oid=21),
         feature("Riverside Trail", "S1710", (0, 40), (90, 40), oid=22),
         feature(None, "S1400", (-50, 120), (-50, 200), oid=23)]
RAIL = [feature(None, "R1011", (-20, -400), (-20, 400), oid=31)]


def tiger(monkeypatch, local=LOCAL, secondary=SECONDARY, rail=RAIL):
    return route(monkeypatch, [("MapServer/2/query", answer({"features": []})),
                               ("MapServer/6/query", answer({"features": secondary})),
                               ("MapServer/8/query", answer({"features": local})),
                               ("MapServer/9/query", answer({"features": rail}))])


def box():
    return geographic_box(LAT, LON, 250, 250)


def test_roads_are_clipped_classified_and_merged_by_shape(monkeypatch):
    asked = tiger(monkeypatch)
    roads = site_roads.fetch_roads(box())
    assert roads["source"] == "census_tiger" and roads["geoBounds"] == box() and len(asked) == 4
    items = roads["items"]
    assert [(item["mtfcc"], item["names"]) for item in items] == [
        ("S1200", ["County Rd 21"]), ("S1200", ["St Croix Trl N", "State Hwy 95", "3rd St N"]),  # one road
        ("S1400", ["4th Ave N"]), ("S1400", []), ("R1011", [])]  # the trail is left out
    assert len({item["roadId"] for item in items}) == 5
    # Local streets and rail stay inside the photo; main roads reach twice as far.
    photo, wide = box(), geographic_box(LAT, LON, 500, 500)
    for item in items:
        area = wide if item["mtfcc"] == "S1200" else photo
        for longitude, latitude in item["lonLat"]:
            assert area["west"] - 1e-6 <= longitude <= area["east"] + 1e-6
            assert area["south"] - 1e-6 <= latitude <= area["north"] + 1e-6
    highway = next(item for item in items if "State Hwy 95" in item["names"])
    assert max(abs(lat - LAT) for _lon, lat in highway["lonLat"]) * 111_132 == pytest.approx(500, abs=3)
    assert "outFields=OID,NAME,MTFCC" in asked[0] and "inSR=4326" in asked[0]


@pytest.mark.parametrize("fail", ["down", "too many"])
def test_a_missing_layer_fails_the_whole_road_map(monkeypatch, fail):
    local = OSError("down") if fail == "down" else answer({"features": LOCAL, "exceededTransferLimit": True})
    route(monkeypatch, [("MapServer/2/query", answer({"features": []})),
                        ("MapServer/6/query", answer({"features": SECONDARY})),
                        ("MapServer/8/query", local),
                        ("MapServer/9/query", answer({"features": RAIL}))])
    with pytest.raises(FacilityLayoutError) as error:
        site_roads.fetch_roads(box())
    assert (error.value.code, error.value.status_code) == ("site_roads_unavailable", 502)


def site_with_roads(monkeypatch):
    tiger(monkeypatch)
    doc = fixture()
    doc["extensions"][KEY]["roads"] = site_roads.fetch_roads(box())
    return doc


def test_stored_roads_get_kinds_labels_and_property_frame_lines(monkeypatch):
    doc = site_with_roads(monkeypatch)
    context = normalize_site_context(doc["extensions"][KEY], doc)
    roads = context["roads"]
    assert roads["attribution"] == "US Census Bureau TIGER/Line roads (public domain)"
    county, highway, street, unnamed, rail = roads["items"]
    assert (highway["kind"], highway["label"]) == ("arterial", "St Croix Trl N (State Hwy 95, 3rd St N)")
    assert (street["kind"], unnamed["label"], rail["label"]) == ("local", "Unnamed road", "Railroad")
    assert all(abs(point["x"] - 160) < 0.05 for point in highway["line"])
    assert highway["lengthMeters"] == pytest.approx(1000, abs=2.0)  # clipped to twice the 500 m photo
    # Derived fields sent back stale are recomputed from the stored longitude/latitude.
    stale = deepcopy(context)
    stale["roads"]["items"][0]["line"] = [{"x": 0, "z": 0}, {"x": 1, "z": 1}]
    assert normalize_site_context(stale, doc)["roads"] == roads


@pytest.mark.parametrize("patch", [{"mtfcc": "S1710"}, {"mtfcc": []}, {"roadId": "bad id!"}, {"names": ["a"] * 5},
                                   {"lonLat": [[-93.0, 45.0]]}, {"lonLat": [[-93.0, 45.0]] * 401},
                                   {"extra": 1}])
def test_invalid_roads_are_rejected(monkeypatch, patch):
    doc = site_with_roads(monkeypatch)
    doc["extensions"][KEY]["roads"]["items"][0].update(patch)
    with pytest.raises(ValueError):
        normalize_site_context(doc["extensions"][KEY], doc)


def test_road_ids_must_be_unique_and_the_source_known(monkeypatch):
    doc = site_with_roads(monkeypatch)
    roads = doc["extensions"][KEY]["roads"]
    with pytest.raises(ValueError):
        normalize_site_context({**doc["extensions"][KEY], "roads": {**roads, "source": "osm"}}, doc)
    with pytest.raises(ValueError):
        normalize_site_context({**doc["extensions"][KEY], "roads": {**roads, "source": []}}, doc)
    roads["items"][1]["roadId"] = roads["items"][0]["roadId"]
    with pytest.raises(ValueError):
        normalize_site_context(doc["extensions"][KEY], doc)


def test_sage_reads_each_roads_kind_distance_side_and_the_lot_edges_it_runs_along(monkeypatch):
    doc = site_with_roads(monkeypatch)
    context = normalize_site_context(doc["extensions"][KEY], doc)
    summary = site_roads.summarize_roads(doc, context)
    by_name = {item["name"]: item for item in summary["items"]}
    street = by_name["4th Ave N"]  # 6 m south of the lot's south edge (edge 0)
    assert (street["kind"], street["sideOfBuilding"], street["alongLotEdges"]) == ("local", "south", [0])
    assert street["distanceFromLotMeters"] == pytest.approx(6, abs=0.1)
    highway = by_name["St Croix Trl N (State Hwy 95, 3rd St N)"]  # 60 m east of the lot's east edge (edge 1)
    assert (highway["kind"], highway["sideOfBuilding"], highway["alongLotEdges"]) == ("arterial", "east", [])
    assert highway["distanceFromLotMeters"] == pytest.approx(60, abs=0.1)
    rail = by_name["Railroad"]  # 20 m west of the lot's west edge (edge 3)
    assert (rail["sideOfBuilding"], rail["alongLotEdges"]) == ("west", [3])
    distances = [item["distanceFromBuildingMeters"] for item in summary["items"]]
    assert distances == sorted(distances) and summary["source"].startswith("US Census")


def test_the_roads_route_checks_the_box_and_the_site(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ai_inspector.facility_layout.authorization import FacilityPrincipal
    from ai_inspector.facility_layout.site_imagery import create_site_imagery_router
    tiger(monkeypatch)
    service = SimpleNamespace(layout_repository=SimpleNamespace(root=tmp_path), get_layout=lambda *args: None)
    principal = FacilityPrincipal("editor", "tenant-a", ("site-a",), ("editor",))
    app = FastAPI()
    app.include_router(create_site_imagery_router(service=service, principal_resolver=lambda request: principal))
    with TestClient(app) as client:
        url = "/api/facility-layouts/site-a/layout-a/site-roads"
        response = client.post(url, json={"geoBounds": box()})
        assert response.status_code == 200 and len(response.json()["items"]) == 5
        too_big = {"south": 44.9, "west": -93.1, "north": 45.1, "east": -92.9}
        assert client.post(url, json={"geoBounds": too_big}).json()["error"]["code"] == "invalid_site_roads_request"
        assert client.post(url.replace("site-a", "site-b"), json={"geoBounds": box()}).status_code == 404
        assert math.isfinite(response.json()["geoBounds"]["north"])


def test_local_streets_reach_out_to_the_nearest_main_road_and_no_further(monkeypatch):
    # Hwy 61 runs past the photo, 450 m west; 5th Ave N leads out to it and meets it at a shared vertex.
    hwy = [feature("Hwy 61", "S1200", (-450, -800), (-450, 100), (-450, 800), oid=41)]
    local = [feature("5th Ave N", "S1400", (0, 100), (-200, 100), (-450, 100), oid=42),
             feature("Elm St", "S1400", (-450, -300), (-300, -300), oid=43),       # outside the photo, leads nowhere
             feature("Dead End Rd", "S1400", (100, -100), (100, -200), oid=44)]    # in the photo, no way out
    tiger(monkeypatch, local=local, secondary=hwy, rail=[])
    items = {item["names"][0]: item for item in site_roads.fetch_roads(box())["items"] if item["names"]}
    assert set(items) == {"Hwy 61", "5th Ave N", "Dead End Rd"}
    fifth = items["5th Ave N"]["lonLat"]
    assert min(lon for lon, _lat in fifth) == pytest.approx(lonlat(-450, 100)[0], abs=1e-6)  # one line, out to the highway
    assert max(lon for lon, _lat in fifth) == pytest.approx(lonlat(0, 100)[0], abs=1e-6)
    photo = box()
    assert all(photo["west"] - 1e-6 <= lon for lon, _lat in items["Dead End Rd"]["lonLat"])


def test_too_many_streets_in_the_wide_box_falls_back_to_the_photos_own(monkeypatch):
    import urllib.parse

    def local(request):
        west = float(urllib.parse.unquote_plus(request.full_url).split("geometry=")[1].split(",")[0])
        if west < box()["west"] - 1e-4:  # the wide box
            return answer({"features": [], "exceededTransferLimit": True})
        return answer({"features": LOCAL})

    asked = route(monkeypatch, [("MapServer/2/query", answer({"features": []})),
                                ("MapServer/6/query", answer({"features": SECONDARY})),
                                ("MapServer/8/query", local),
                                ("MapServer/9/query", answer({"features": RAIL}))])
    roads = site_roads.fetch_roads(box())
    assert sum("MapServer/8/query" in url for url in asked) == 2
    assert [item["names"] for item in roads["items"] if item["mtfcc"] == "S1400"] == [["4th Ave N"], []]


def test_simplifying_keeps_the_vertices_where_streets_meet(monkeypatch):
    # Elm St crosses 6th St at (40, 0), a vertex both share; on its own the vertex is collinear and would go.
    local = [feature("6th St", "S1400", (-200, 0), (40, 0), (200, 0), oid=51),
             feature("Elm St", "S1400", (40, -200), (40, 0), (40, 200), oid=52)]
    tiger(monkeypatch, local=local, secondary=[], rail=[])
    items = {item["names"][0]: item for item in site_roads.fetch_roads(box())["items"]}
    crossing = lonlat(40, 0)
    for name in ("6th St", "Elm St"):
        assert any(abs(lon - crossing[0]) < 1e-6 and abs(lat - crossing[1]) < 1e-6 for lon, lat in items[name]["lonLat"])


def test_each_vehicle_entrance_gets_its_way_to_the_main_road(monkeypatch):
    from ai_inspector.facility_layout.site_access import vehicle_routes
    # The lot fronts Mill St (local), which meets State Hwy 95 at (160, -8); the railway crosses Mill St at grade.
    hwy = [feature("State Hwy 95", "S1200", (160, -800), (160, -8), (160, 800), oid=61)]
    local = [feature("Mill St", "S1400", (-200, -8), (-20, -8), (160, -8), oid=62)]
    rail = [feature(None, "R1011", (-20, -400), (-20, -8), (-20, 400), oid=63)]
    tiger(monkeypatch, local=local, secondary=hwy, rail=rail)
    doc = fixture()
    context = doc["extensions"][KEY]
    context["roads"] = site_roads.fetch_roads(box())
    context["property"] = {"boundary": [{"x": -60, "z": 0}, {"x": 140, "z": 0}, {"x": 140, "z": 100}, {"x": -60, "z": 100}],
                           "setbacksMeters": {"street": 0, "side": 0, "rear": 0}, "streetEdges": [0], "rearEdges": [2],
                           "entrances": [{"entranceId": "trucks", "edgeIndex": 0, "x": 60, "z": 0, "use": "trucks", "widthMeters": 12},
                                         {"entranceId": "cars", "edgeIndex": 0, "x": -40, "z": 0, "use": "cars", "widthMeters": 7},
                                         {"entranceId": "walk", "edgeIndex": 0, "x": 0, "z": 0, "use": "pedestrians", "widthMeters": 2}]}
    stored = normalize_site_context(context, doc)
    routes = {route["entranceId"]: route for route in stored["routes"]}
    assert set(routes) == {"trucks", "cars"}  # pedestrians walk
    trucks, cars = routes["trucks"], routes["cars"]
    assert trucks["mainRoad"] == "State Hwy 95" and trucks["roads"] == ["Mill St"]  # the streets used to get there
    assert trucks["lengthMeters"] == pytest.approx(8 + 100, abs=1.5) and trucks["railCrossings"] == 0
    assert cars["railCrossings"] == 1 and cars["railCrossingsAtGrade"] == 1  # east along Mill St, over the tracks
    assert (cars["points"][-1]["x"], cars["points"][-1]["z"]) == pytest.approx((160, -8), abs=0.5)
    assert normalize_site_context(stored, doc)["routes"] == stored["routes"]  # derived, so stable
    assert vehicle_routes({**stored, "property": {**stored["property"], "entrances": []}}) == []
