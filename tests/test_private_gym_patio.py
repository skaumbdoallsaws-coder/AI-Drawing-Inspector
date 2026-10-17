from copy import deepcopy
import pytest
from tools.add_private_gym_patio import ASSET, KEYS, REMOVED, ground_surfaces, operations


def base():
    return {'extensions': {'facilityGround': {'schemaVersion': 1, 'surfaces': [
        dict(surfaceId='unrelated',minX=0,minZ=0,maxX=20,maxZ=20,startElevation=0,endElevation=0,slopeAxis='x',color='#111111'),
        dict(surfaceId='private-gym-fields-turf',minX=44,minZ=40,maxX=82,maxZ=72,startElevation=0,endElevation=0,slopeAxis='x',color='#387b43'),
    ]}}}


def test_paving_replaces_only_blue_corner_and_keeps_floor_area():
    before = base()
    snapshot = deepcopy(before)
    surfaces = ground_surfaces(before)
    assert before == snapshot
    assert surfaces[0] == before['extensions']['facilityGround']['surfaces'][0]
    assert sum((s['maxX']-s['minX'])*(s['maxZ']-s['minZ']) for s in surfaces[1:]) == 38*32
    paving = next(s for s in surfaces if s['surfaceId'] == 'gym-patio-paving')
    assert [paving[k] for k in ['minX','minZ','maxX','maxZ']] == [68,62,82,72]
    assert all(s['startElevation'] == s['endElevation'] == 0 for s in surfaces)


def test_changed_turf_boundary_refuses_old_recipe():
    before = base()
    before['extensions']['facilityGround']['surfaces'][1]['maxX'] = 84
    with pytest.raises(AssertionError):
        ground_surfaces(before)


def test_removal_targets_cardio_not_red_training_wall():
    catalog = {ASSET+k: {'assetDefinitionRevision':'exact-'+k} for k in KEYS}
    ops = operations(base(),catalog)
    deleted = {o['placementId'] for o in ops if o['op'] == 'delete_placement'}
    assert deleted == REMOVED
    assert not any('training-support' in p or 'wall-mounted-rack' in p for p in deleted)
    assert len([o for o in ops if o['op'] == 'place_asset']) == 9


def test_roof_is_attached_at_real_elevation_and_assets_are_revision_bound():
    catalog = {ASSET+k: {'assetDefinitionRevision':'exact-'+k} for k in KEYS}
    placed = [o['placement'] for o in operations(base(),catalog) if o['op'] == 'place_asset']
    roof = next(p for p in placed if p['assetId'] == ASSET+'roof')
    assert roof['transform']['position']['y'] == pytest.approx(2.1336)
    assert roof['snapRelationship']['family'] == 'surface_attachment'
    assert roof['snapRelationship']['supportPlacementId'] == 'pl-gym-patio-pergola-supports'
    assert all(p['transform']['scale'] == 1 for p in placed)
    assert all(p['assetDefinitionRevision'] == catalog[p['assetId']]['assetDefinitionRevision'] for p in placed)
