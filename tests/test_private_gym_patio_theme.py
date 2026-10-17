from copy import deepcopy
import hashlib
import json
import pytest
from tools import style_private_gym_patio as theme


@pytest.fixture
def staged():
    if not (theme.OUT/'report.json').exists():
        pytest.skip('Local patio finish variants not staged')
    return tuple(json.loads((theme.OUT/name).read_bytes()) for name in
                 ['before.json', 'candidate.json', 'report.json'])


def test_only_five_asset_bindings_change(staged):
    before, after, report = staged
    theme.audit(before, after, report['replacements'])
    assert len(report['replacements']) == 5
    assert [p['transform'] for p in before['placements']] == [p['transform'] for p in after['placements']]
    assert [p['snapRelationship'] for p in before['placements']] == [p['snapRelationship'] for p in after['placements']]
    assert before['extensions'] == after['extensions']
    changed = deepcopy(after)
    changed['placements'][0]['transform']['scale'] = 2
    with pytest.raises(AssertionError):
        theme.audit(before, changed, report['replacements'])


def test_original_assets_and_existing_library_entries_unchanged(staged):
    _, _, report = staged
    before = json.loads((theme.OUT/'catalog-before.json').read_bytes())
    after = json.loads((theme.OUT/'staged-project'/theme.PRIVATE_ASSET_MANIFEST).read_bytes())
    assert after['assets'][:len(before['assets'])] == before['assets']
    assert len(after['assets']) == len(before['assets'])+5
    for path, digest in report['originalAssetHashes'].items():
        assert hashlib.sha256((theme.ROOT/path).read_bytes()).hexdigest() == digest
    for new in after['assets'][len(before['assets']):]:
        old = next(a for a in before['assets'] if a['assetId'] == new['assetId'].removesuffix('-apex-patio'))
        for key in ('dimensions', 'sourceToCanonical', 'footprintPolygons', 'supportSurfaces', 'source'):
            assert new.get(key) == old.get(key)


def test_all_variants_preserve_mesh_counts_and_use_bounded_material_batches(staged):
    _, _, report = staged
    expected = dict(supports=22096, roof=7804, drinks=125040, picnic=74921, grill=35830)
    for check in report['checks']:
        assert check['triangles'] == expected[check['key']]
        assert check['geometryPreserved'] is True
        assert check['groups'] == (3 if check['key'] == 'grill' else 2)
    for path, digest in report['variantHashes'].items():
        payload = (theme.OUT/'staged-project'/path).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == digest
        doc, _ = theme.unpack(payload)
        assert all(m['extras']['facilityAuthoredFinish'] for m in doc['materials'])


def test_grill_keeps_hood_and_body_black_and_grates_steel(staged):
    evidence = json.loads((theme.OUT/'components/grill.json').read_bytes())
    roles = {c['key']: c['role'] for c in evidence['components']}
    assert roles == {'0:0': 'frame', '1:0': 'gold', '1:1': 'frame',
                     '2:0': 'steel', '3:0': 'steel', '4:0': 'gold', '4:1': 'frame'}


@pytest.mark.parametrize('key,faces,bounds,role', [
    ('supports', 268, [[0, 1.42, 0], [.14, 2.13, .7]], 'gold'),
    ('supports', 220, [[0, 0, 0], [.14, 2.13, .14]], None),
    ('roof', 220, [[-1.7, .4699, 0], [1.7, .508, .04]], 'gold'),
    ('picnic', 222, [[0, .505, 0], [.45, .525, .05]], 'gold'),
    ('picnic', 222, [[0, .058, 0], [.45, .091, .05]], None),
    ('picnic', 4844, [[.66, 0, .19], [1.37, .96, .23]], None),
])
def test_reviewed_components_leave_structural_frames_black(key, faces, bounds, role):
    assert theme.component_role(key, faces, bounds) == role
