from copy import deepcopy
from io import BytesIO
import json

import pytest
from PIL import Image

from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.decals import normalize_decals
from ai_inspector.facility_layout.decal_images import normalize_image, scope_directory
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.facility_layout.perimeter_walls import compile_perimeter_walls
from ai_inspector.facility_layout.validate import validate_layout
from tests.test_facility_wall_finishes import layout, settings, finish
from tests.test_facility_layout_api import _client, _layout, _principal, _placement_operation, _resolved_asset


def art(**patch):
    return dict(dict(artworkId="decal-a", label="Entrance logo", imagePath="/api/facility-decal-images/site-a/"+"a"*64+".png",
        uv=[0, .1, 1, .9], target={"edge": 0, "side": "interior"}, region=[.1, .1, .8, .9], coverage=1), **patch)


def document():
    doc = layout()
    doc["extensions"]["facilityPerimeterWalls"] = compile_perimeter_walls(settings(), doc)
    return doc


def apply(doc, artworks):
    return apply_facility_layout_operations(doc, [{"op": "set_decals", "decals": {"version": 1, "artworks": artworks}}])["document"]


def test_decals_do_not_create_paint_geometry_or_change_equipment():
    before = document()
    after = apply(before, [art()])
    assert after["extensions"]["facilityPerimeterWalls"] == before["extensions"]["facilityPerimeterWalls"]
    assert after["placements"] == before["placements"]
    assert layout_revision(after) != layout_revision(before)
    validate_layout(after)
    assert apply(after, [art()]) == after
    assert apply(after, [])["extensions"]["facilityDecals"]["artworks"] == []


def test_placed_wall_decal_does_not_require_perimeter():
    doc = layout()
    placement = _placement_operation()["placement"]
    doc["placements"] = [placement]
    after = apply(doc, [art(target={"placementId": placement["placementId"], "face": "negative_z"})])
    assert "facilityPerimeterWalls" not in after["extensions"]
    removed = apply_facility_layout_operations(after, [{"op": "delete_placement", "placementId": placement["placementId"]}])["document"]
    assert not removed["extensions"]["facilityDecals"]["artworks"]


@pytest.mark.parametrize("patch", [
    {"imagePath": "https://example.org/image.png"}, {"imagePath": "file:///a.png"},
    {"imagePath": "/api/facility-decal-images/site-b/"+"a"*64+".png"},
    {"imagePath": "/api/facility-decal-images/../"+"a"*64+".png"},
    {"label": ""}, {"label": "x"*121}, {"region": [0,0,2,1]}, {"region": [0,0,0,1]},
    {"uv": [0,0,True,1]}, {"coverage": False}, {"coverage": float("nan")},
    {"target": {"edge": True,"side":"interior"}}, {"target": {"edge": 99,"side":"interior"}},
    {"target": {"placementId":"missing","face":"positive_z"}}, {"extra": 1},
])
def test_invalid_records_fail_closed(patch):
    with pytest.raises(ValueError):
        normalize_decals({"version": 1,"artworks":[art(**patch)]}, document())


def test_door_conflicts_resize_and_remove_perimeter():
    doc = apply(document(), [art()])
    changed = settings()
    changed["openings"] = [{"edge":0,"startMeters":8,"endMeters":10}]
    with pytest.raises(Exception, match="door"):
        apply_facility_layout_operations(doc, [{"op":"set_perimeter_walls","wallSettings":changed}])
    removed = apply_facility_layout_operations(doc, [{"op":"set_perimeter_walls","wallSettings":None}])["document"]
    assert removed["extensions"]["facilityDecals"]["artworks"] == []
    grown = deepcopy(doc["extensions"]["facilityPlan"])
    grown["widthMeters"] *= 2
    resized = apply_facility_layout_operations(doc, [{"op":"set_plan_settings","planSettings":grown}])["document"]
    assert resized["extensions"]["facilityDecals"] == doc["extensions"]["facilityDecals"]


def test_existing_art_is_preserved_and_combined_budget_enforced():
    doc = document()
    doc["extensions"]["facilityPerimeterWalls"] = compile_perimeter_walls(settings(exteriorFinish=finish()), doc)
    existing = deepcopy(doc["extensions"]["facilityPerimeterWalls"])
    after = apply(doc, [art(artworkId="decal-"+str(i)) for i in range(47)])
    assert after["extensions"]["facilityPerimeterWalls"] == existing
    for entries in ([art(artworkId="emblem")], [art(), art()], [art(artworkId="d-"+str(i)) for i in range(48)]):
        with pytest.raises(ValueError): normalize_decals({"version":1,"artworks":entries}, doc)


def image_bytes(mode="RGBA", transparent=False, fmt="PNG"):
    image = Image.new(mode, (100, 80), (0,0,0,0) if mode=="RGBA" else (255,200,0))
    if mode=="RGBA" and not transparent:
        image.paste((201,155,57,255),(20,10,80,65))
    stream=BytesIO();image.save(stream,format=fmt);return stream.getvalue()


def test_image_normalization_and_alpha_trim():
    payload, metadata = normalize_image(image_bytes())
    assert metadata == dict(width=100,height=80,uv=[.18,1-67/80,.82,1-8/80])
    assert Image.open(BytesIO(payload)).mode == "RGBA"
    assert normalize_image(image_bytes()) == (payload, metadata)
    jpeg, meta = normalize_image(image_bytes(mode="RGB",fmt="JPEG"))
    assert Image.open(BytesIO(jpeg)).format == "PNG" and meta["uv"] == [0,0,1,1]


@pytest.mark.parametrize("payload", [b"<svg></svg>", b"not an image", b"", b"a"*(10*1024*1024+1), image_bytes(transparent=True)],
                         ids=["svg", "invalid", "empty", "oversized", "transparent"])
def test_invalid_images_rejected(payload):
    with pytest.raises(ValueError): normalize_image(payload)


def test_image_http_is_authorized_durable_and_deduplicated(tmp_path):
    client, service, shell, policy = _client(tmp_path)
    document = _layout(shell, policy)
    client.post("/api/facility-layouts/site-a", json={"layout":document})
    url = "/api/facility-layouts/site-a/fl-api-cell/decal-images"
    headers = {"Content-Type":"image/png"}
    denied = client.post(url, content=image_bytes(), headers=dict(headers, **{"X-Test-Role":"viewer"}))
    assert denied.status_code == 403
    response = client.post(url, content=image_bytes(), headers=headers)
    assert response.status_code == 200, response.text
    assert client.post(url, content=image_bytes(), headers=headers).json() == response.json()
    path = response.json()["imagePath"]
    data = client.get(path)
    assert data.status_code == 200 and data.headers["content-type"] == "image/png"
    assert client.get(path.replace("site-a","site-b")).status_code == 404
    assert client.get("/api/facility-decal-images/site-a/invalid.png").status_code == 404
    assert client.get("/api/facility-decal-images/site-a/"+"0"*64+".png").status_code == 404
    assert client.post(url, content=b"not an image", headers=headers).status_code == 422
    assert client.post(url, content=b"<svg/>", headers={"Content-Type":"image/svg+xml"}).status_code == 415
    assert client.post(url, content=b"x"*(10*1024*1024+1), headers=headers).status_code == 413
    folder=scope_directory(service.layout_repository.root/"decal-images",_principal(),"site-a")
    assert len(list(folder.glob("*.png"))) == 1
    assert not list(folder.glob("*.tmp"))
    assert service.get_layout(_principal(),"site-a","fl-api-cell")["layout"]["placements"] == []


def test_server_rejects_a_decal_bound_to_nonwall_equipment(tmp_path):
    client, service, shell, policy = _client(tmp_path)
    created = client.post('/api/facility-layouts/site-a', json={'layout':_layout(shell, policy)}).json()
    place = _placement_operation()
    record = art(target={'placementId':place['placement']['placementId'],'face':'positive_z'})
    operations = [place,dict(op='set_decals',decals=dict(version=1,artworks=[record]))]
    response = client.post('/api/facility-layouts/site-a/fl-api-cell/preview',json=dict(baseRevision=created['revision'],operations=operations))
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'invalid_decal_target'
    def wall_resolver(_principal, _site, asset_id, revision):
        entry = _resolved_asset(asset_id,revision)
        entry['definition']['tags'] = ['wall']
        entry['definition']['geometry']['aabb'] = dict(minimum=dict(x=-.5,y=0,z=-.5),maximum=dict(x=.5,y=1,z=.5))
        return entry
    service.asset_definition_resolver = wall_resolver
    response = client.post('/api/facility-layouts/site-a/fl-api-cell/preview',json=dict(baseRevision=created['revision'],operations=operations))
    assert response.status_code == 200, response.text
