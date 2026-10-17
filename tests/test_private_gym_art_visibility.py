"""Exact-scope checks for the two requested gym artwork relocations."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import fix_private_gym_art_visibility as fix
from ai_inspector.industrial_assets.artifacts import inspect_glb


@pytest.fixture(scope='module')
def staged():
    if not (fix.OUT/'candidate.json').exists():
        pytest.skip('Local artwork correction has not been staged')
    host=fix.LocalFacilityLayoutHost(fix.OUT/'validation-store',private_assets=True,
        private_asset_root=fix.OUT/'staged-project')
    try:
        yield (json.loads((fix.OUT/'before.json').read_text()),json.loads((fix.OUT/'candidate.json').read_text()),
            {a['assetId']:a for a in host.authoritative_asset_catalog()})
    finally:
        host.close()


def test_relocation_preserves_every_existing_placement(staged):
    before, after, catalog = staged
    result = fix.audit(before, after, catalog)
    assert result['originalPlacementsUnchanged'] == len(before['placements'])
    assert after['placements'][:-1] == before['placements']
    assert fix.artwork(after, fix.SLOGAN)['startMeters'] == 37
    assert fix.artwork(after,'apex-interior-h05') == fix.artwork(before,'apex-interior-h05')


def test_decal_has_no_opaque_backing_and_reuses_exact_png(staged):
    before, _, _ = staged
    png = (ROOT/fix.artwork(before,fix.EAGLE)['imagePath'].lstrip('/')).read_bytes()
    raw = fix.decal_glb(png)
    assert png in raw
    assert inspect_glb(raw).to_manifest_dict()['sceneTriangleCount'] == 4
    doc, _ = fix.unpack(raw)
    nodes = doc['scenes'][0]['nodes']
    assert len(nodes) == 2
    assert all(doc['nodes'][n]['mesh'] != 0 for n in nodes)
    material = doc['materials'][doc['meshes'][doc['nodes'][nodes[0]]['mesh']]['primitives'][0]['material']]
    assert material['alphaMode'] == 'BLEND'
    assert material['extras']['facilityArtwork']


@pytest.mark.parametrize('field', ['wall','equipment','basketball','slogan','eagle-position','eagle-scale','eagle-attachment'])
def test_unrequested_or_misaligned_changes_are_rejected(staged,field):
    before, original, catalog = staged
    after = deepcopy(original)
    decal = next(p for p in after['placements'] if p['placementId']==fix.PLACEMENT)
    if field == 'wall':
        next(p for p in after['placements'] if p['placementId']==fix.SUPPORT)['transform']['position']['z'] += .5
    elif field == 'equipment':
        after['placements'][0]['transform']['position']['x'] += .5
    elif field == 'basketball':
        fix.artwork(after,'apex-interior-h05')['startMeters'] += .5
    elif field == 'slogan':
        fix.artwork(after,fix.SLOGAN)['startMeters'] = 42
    elif field == 'eagle-position':
        decal['transform']['position']['z'] += .5
    elif field == 'eagle-scale':
        decal['transform']['scale'] = 2
    else:
        decal['snapRelationship']['face'] = 'negative_z'
    with pytest.raises(AssertionError):
        fix.audit(before,after,catalog)
