"""The globe flight's tiles: relayed from the USGS Imagery basemap, checked, never stored (network faked)."""
from io import BytesIO
import urllib.error

from PIL import Image
import pytest

from ai_inspector.facility_layout import site_imagery
from ai_inspector.facility_layout.errors import FacilityLayoutError
from tests.test_facility_site_context import Reply, jpeg
from tests.test_facility_site_layers import route


def png():
    out = BytesIO()
    Image.new("RGB", (8, 8), (0, 0, 0)).save(out, format="PNG")
    return out.getvalue()


def test_a_tile_comes_from_the_basemap_in_its_row_column_order(monkeypatch):
    asked = route(monkeypatch, [("USGSImageryOnly/MapServer/tile/", Reply(jpeg(), "image/jpeg"))])
    content, media_type = site_imagery.fetch_globe_tile(3, 1, 2)
    assert content == jpeg() and media_type == "image/jpeg"
    assert asked == [site_imagery.GLOBE_TILES + "/3/2/1"]
    route(monkeypatch, [("USGSImageryOnly/MapServer/tile/", Reply(png(), "image/png"))])
    assert site_imagery.fetch_globe_tile(0, 0, 0)[1] == "image/png"


@pytest.mark.parametrize("z,x,y", [(17, 0, 0), (-1, 0, 0), (2, 4, 0), (2, 0, -1), (0, 1, 0)])
def test_tiles_off_the_pyramid_are_refused_without_a_request(monkeypatch, z, x, y):
    asked = route(monkeypatch, [])
    with pytest.raises(FacilityLayoutError) as error:
        site_imagery.fetch_globe_tile(z, x, y)
    assert (error.value.code, error.value.status_code, asked) == ("site_globe_tile_missing", 404, [])


@pytest.mark.parametrize("reply,code,status", [
    (urllib.error.HTTPError("u", 404, "Not Found", {}, None), "site_globe_tile_missing", 404),
    (urllib.error.HTTPError("u", 500, "Server Error", {}, None), "site_globe_unavailable", 502),
    (OSError("timed out"), "site_globe_unavailable", 502),
    (Reply(b"<html>maintenance</html>", "text/html"), "site_globe_unavailable", 502),
    (Reply(b"\xff\xd8\xff" + b"0" * site_imagery.GLOBE_TILE_BYTES, "image/jpeg"), "site_globe_unavailable", 502),
])
def test_missing_failing_or_odd_answers_become_clear_errors(monkeypatch, reply, code, status):
    route(monkeypatch, [("USGSImageryOnly", reply)])
    with pytest.raises(FacilityLayoutError) as error:
        site_imagery.fetch_globe_tile(5, 7, 11)
    assert (error.value.code, error.value.status_code) == (code, status)


@pytest.fixture(autouse=True)
def empty_memory():
    site_imagery._globe_tiles.clear()
    site_imagery._globe_pending.clear()
    yield
    site_imagery._globe_tiles.clear()


def test_the_dive_column_is_three_by_three_tiles_around_the_place_at_every_zoom():
    keys = site_imagery.globe_column(45.0207, -92.7756)
    assert keys[0] == (0, 0, 0) and len([k for k in keys if k[0] == 1]) == 4
    assert all(len([k for k in keys if k[0] == z]) == 9 for z in range(2, 17))
    # Bayport, MN at zoom 16: column 15878, row 23569 holds the place, the block surrounds it.
    assert (16, 15878, 23569) in keys and {(16, 15877, 23568), (16, 15879, 23570)} <= set(keys)
    assert [k[0] for k in keys] == sorted(k[0] for k in keys)  # coarse tiles first, as the dive needs them


def test_tiles_are_fetched_once_and_then_served_from_memory(monkeypatch):
    asked = route(monkeypatch, [("USGSImageryOnly/MapServer/tile/", Reply(jpeg(), "image/jpeg"))])
    assert site_imagery.prefetch_globe(45.0207, -92.7756) == 140
    for future in list(site_imagery._globe_pending.values()):
        future.result(timeout=10)
    assert len(asked) == 140 and len(set(asked)) == 140
    assert site_imagery.globe_tile(16, 15878, 23569)[0] == jpeg()
    assert len(asked) == 140  # from memory
    with pytest.raises(FacilityLayoutError):
        site_imagery.globe_tile(17, 0, 0)


def test_a_failed_tile_is_not_remembered(monkeypatch):
    route(monkeypatch, [("USGSImageryOnly", OSError("down"))])
    with pytest.raises(FacilityLayoutError):
        site_imagery.globe_tile(3, 1, 2)
    assert not site_imagery._globe_tiles and not site_imagery._globe_pending
    asked = route(monkeypatch, [("USGSImageryOnly", Reply(jpeg(), "image/jpeg"))])
    assert site_imagery.globe_tile(3, 1, 2)[1] == "image/jpeg" and len(asked) == 1


def test_the_tile_route_is_scoped_to_a_readable_site_and_cacheable(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ai_inspector.facility_layout.authorization import FacilityPrincipal
    asked = route(monkeypatch, [("USGSImageryOnly/MapServer/tile/", Reply(jpeg(), "image/jpeg"))])
    service = SimpleNamespace(layout_repository=SimpleNamespace(root=tmp_path))
    principal = FacilityPrincipal("reader", "tenant-a", ("site-a",), ("viewer",))
    app = FastAPI()
    app.include_router(site_imagery.create_site_imagery_router(service=service, principal_resolver=lambda request: principal))
    with TestClient(app) as client:
        response = client.get("/api/facility-site-globe/site-a/4/3/5.jpg")
        assert response.status_code == 200 and response.content == jpeg()
        assert response.headers["content-type"] == "image/jpeg"
        assert response.headers["cache-control"] == "private, max-age=604800"
        assert client.get("/api/facility-site-globe/foreign-site/4/3/5.jpg").status_code == 404
        assert client.get("/api/facility-site-globe/site-a/17/0/0.jpg").json()["error"]["code"] == "site_globe_tile_missing"
        assert client.post("/api/facility-site-globe/foreign-site/prefetch", json={"latitude": 45, "longitude": -93}).status_code == 404
        assert client.post("/api/facility-site-globe/site-a/prefetch", json={"latitude": 91, "longitude": 0}).status_code == 400
        assert client.post("/api/facility-site-globe/site-a/prefetch", json={"latitude": 45}).status_code == 400
    assert asked == [site_imagery.GLOBE_TILES + "/4/5/3"]
    assert not any(tmp_path.rglob("*.jpg"))  # relayed, not stored
    with TestClient(app) as client:
        # The prefetch answers once the place's column is in memory: the globe dives after it.
        ready = client.post("/api/facility-site-globe/site-a/prefetch", json={"latitude": 45.0207, "longitude": -92.7756})
        assert ready.json() == {"tiles": 140, "ready": 140}
        assert len(asked) == 140  # 139 new: the z4 tile asked for above (4/3/5) came from memory
