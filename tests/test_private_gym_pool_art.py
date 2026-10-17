"""Pool artwork keeps original image bytes and all existing room geometry."""
from copy import deepcopy
import json
import struct

import pytest

from tools import add_private_gym_pool_art as art


@pytest.fixture(scope='module')
def staged():
    if not (art.OUT/'candidate.json').exists():
        pytest.skip('Local pool artwork has not been staged')
    host = art.LocalFacilityLayoutHost(art.OUT/'validation-store', private_assets=True,
        private_asset_root=art.OUT/'staged-project')
    try:
        yield (json.loads((art.OUT/'before.json').read_text()), json.loads((art.OUT/'candidate.json').read_text()),
            {a['assetId']: a for a in host.authoritative_asset_catalog()})
    finally:
        host.close()


def test_only_two_asset_bindings_change(staged):
    before, after, catalog = staged
    assert art.audit(before, after, catalog)['geometryAndTransformsUnchanged']
    assert len(before['placements']) == len(after['placements'])


@pytest.mark.parametrize('spec', art.WALLS, ids=lambda s: s['name'])
def test_exact_png_and_inward_face(staged, spec):
    before, _, _ = staged
    library = json.loads((art.OUT/'catalog-before.json').read_text())
    wall = next(p for p in before['placements'] if p['placementId'] == spec['placement'])
    dims = next(a for a in library['assets'] if a['assetId'] == wall['assetId'])['dimensions']
    png = (art.Path.home()/'Downloads'/spec['file']).read_bytes()
    raw = art.side_wall_glb(png, dims, spec['inward'], spec['name'])
    assert png in raw
    doc, data = art.unpack(raw)
    assert art.inspect_glb(raw).scene_triangle_count == 14
    root = doc['nodes'][doc['scenes'][0]['nodes'][0]]
    m = root['matrix']
    assert [m[8], m[9], m[10]] == [spec['inward'], 0, 0]
    for axis, size in [('x', dims['width']), ('y', dims['height']), ('z', dims['depth'])]:
        bounds = art.inspect_glb(raw).aabb
        assert bounds['maximum'][axis]-bounds['minimum'][axis] == pytest.approx(size, abs=1e-5)
    image_mesh = doc['meshes'][1]['primitives'][0]
    material = doc['materials'][image_mesh['material']]
    assert material['alphaMode'] == 'BLEND'
    assert material['extras']['facilityArtwork']
    assert 'KHR_materials_unlit' in material['extensions']
    # UV ordering is untouched by the proper rotation, so lettering is not mirrored.
    accessor = doc['accessors'][image_mesh['attributes']['TEXCOORD_0']]
    view = doc['bufferViews'][accessor['bufferView']]
    uv = struct.unpack_from('<8f', data, view.get('byteOffset', 0)+accessor.get('byteOffset', 0))
    assert uv == (0,1,1,1,1,0,0,0)


@pytest.mark.parametrize('kind', ['wall-position', 'wall-color', 'equipment', 'slogan'])
def test_unrelated_changes_rejected(staged, kind):
    before, original, catalog = staged
    candidate = deepcopy(original)
    wall = next(p for p in candidate['placements'] if p['placementId'] == art.WALLS[0]['placement'])
    if kind == 'wall-position':
        wall['transform']['position']['x'] += .2
    elif kind == 'wall-color':
        wall['appearance']['color'] = '#FFFFFF'
    elif kind == 'equipment':
        candidate['placements'][0]['transform']['scale'] = 2
    else:
        candidate['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['artworks'][0]['startMeters'] += .5
    with pytest.raises(AssertionError):
        art.audit(before, candidate, catalog)
