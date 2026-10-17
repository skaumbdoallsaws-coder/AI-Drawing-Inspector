"""Pool annex contracts plus checks against the staged local CAD candidate."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import add_private_gym_pool as pool


def test_ground_tiles_cover_annex_without_overlap():
    from shapely.geometry import box
    from shapely.ops import unary_union
    surfaces = pool.ground_surfaces()
    shapes = [box(s['minX'],s['minZ'],s['maxX'],s['maxZ']) for s in surfaces]
    assert unary_union(shapes).equals(box(*pool.ANNEX))
    assert sum(p.area for p in shapes) == pytest.approx(box(*pool.ANNEX).area)
    recessed = [s for s in surfaces if s['startElevation'] < 0]
    assert len(recessed) == 1
    assert recessed[0]['startElevation'] == recessed[0]['endElevation'] == -1.75


def test_connection_is_a_physical_door_gap():
    segments = {w[0]:w for w in pool.walls()}
    south, north = segments['connection-south'], segments['connection-north']
    south_end = south[5] + south[2]/2
    north_start = north[5] - north[2]/2
    assert south_end == pytest.approx(-2.5)
    assert north_start == pytest.approx(-.7)
    assert north_start - south_end == pytest.approx(1.8)


@pytest.fixture(scope='module')
def staged():
    if not (pool.OUT/'candidate.json').exists():
        pytest.skip('Local CAD candidate has not been staged')
    host = pool.LocalFacilityLayoutHost(pool.OUT/'validation-store', private_assets=True,
        private_asset_root=pool.OUT/'staged-project')
    try:
        yield (json.loads((pool.OUT/'before.json').read_text()),
            json.loads((pool.OUT/'candidate.json').read_text()),
            {a['assetId']:a for a in host.authoritative_asset_catalog()})
    finally:
        host.close()


def test_staged_candidate_preserves_existing_rooms_and_has_clear_access(staged):
    before, candidate, catalog = staged
    checks = pool.audit(before, candidate, catalog)
    assert checks['nativeScalePreserved'] and checks['existingRoomsPreserved']
    assert len(candidate['placements']) == len(before['placements']) + 9


@pytest.mark.parametrize('change', ['old-placement','pool-height','pool-scale','jacuzzi-scale','extra-placement','ground'])
def test_audit_rejects_unapproved_changes(staged, change):
    before, source, catalog = staged
    candidate = deepcopy(source)
    by_id = {p['placementId']:p for p in candidate['placements']}
    if change == 'old-placement':
        pid = next(p['placementId'] for p in before['placements'] if p['placementId'] != pool.OLD_WALL)
        by_id[pid]['transform']['position']['x'] += .5
    elif change == 'pool-height':
        by_id[pool.P+'swimming-pool']['transform']['position']['y'] = 0
    elif change == 'pool-scale':
        by_id[pool.P+'swimming-pool']['transform']['scale'] = 2
    elif change == 'jacuzzi-scale':
        by_id[pool.P+'corner-jacuzzi']['transform']['scale'] = 2
    elif change == 'extra-placement':
        extra = deepcopy(by_id[pool.P+'corner-jacuzzi'])
        extra['placementId'] = 'unrequested-object'
        candidate['placements'].append(extra)
    else:
        candidate['extensions']['facilityGround']['surfaces'][-1]['startElevation'] = 0
    with pytest.raises(AssertionError):
        pool.audit(before, candidate, catalog)


@pytest.mark.parametrize('key,asset', [('concept-1',pool.POOL),('jacuzzi',pool.SPA)])
def test_source_finish_variants_preserve_cad_geometry(staged, key, asset):
    manifest = json.loads((pool.OUT/'staged-project'/pool.PRIVATE_ASSET_MANIFEST).read_text())
    entries = {e['assetId']:e for e in manifest['assets']}
    original = entries['asset-gym-pool-'+key]
    variant = entries[asset]
    original_doc, original_data = pool.unpack((ROOT/original['artifact']).read_bytes())
    variant_doc, variant_data = pool.unpack((pool.OUT/'staged-project'/variant['artifact']).read_bytes())
    assert variant_data == original_data
    for field in ['meshes','accessors','nodes','scenes']:
        assert variant_doc[field] == original_doc[field]
    assert variant['sourceToCanonical'] == original['sourceToCanonical']
    assert variant['dimensions'] == original['dimensions']
    assert all(m['extras']['facilityAuthoredFinish'] for m in variant_doc['materials'])
