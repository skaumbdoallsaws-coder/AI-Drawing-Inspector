"""Outdoor murals preserve the reviewed walls and the rest of Private Gym."""
from copy import deepcopy
import json

from PIL import Image
import pytest

from tools import add_private_gym_outdoor_art as art


def test_alpha_uv_trims_margins_without_changing_source():
    image = Image.new('RGBA', (100, 80), (0, 0, 0, 0))
    image.paste((201, 155, 57, 255), (10, 20, 90, 60))
    raw = image.tobytes()
    uv, box = art.alpha_uv(image)
    assert box == (8, 18, 92, 62)
    assert uv == pytest.approx([.08, .225, .92, .775])
    assert image.tobytes() == raw


@pytest.mark.parametrize('image', [
    Image.new('RGB', (20, 20)),
    Image.new('RGBA', (20, 20), (0, 0, 0, 255)),
    Image.new('RGBA', (20, 20), (0, 0, 0, 0)),
])
def test_art_requires_visible_content_and_transparency(image):
    with pytest.raises(AssertionError):
        art.alpha_uv(image)


@pytest.fixture
def staged():
    if not (art.OUT/'candidate.json').exists():
        pytest.skip('Local outdoor artwork has not been staged')
    return tuple(json.loads((art.OUT/name).read_text()) for name in
                 ['before.json', 'candidate.json', 'report.json', 'render-fixture.json'])


def test_exact_two_additions_preserve_all_other_content(staged):
    before, after, report, _ = staged
    checks = art.audit(before, after, report['records'])
    assert checks['unchangedPlacements'] == len(before['placements'])
    assert art.build(before, report['records'])['placements'] == before['placements']
    with pytest.raises(AssertionError):
        art.build(after, report['records'])
    changed = deepcopy(after)
    changed['placements'][0]['transform']['scale'] = 2
    with pytest.raises(AssertionError, match='beyond'):
        art.audit(before, changed, report['records'])


def test_murals_bind_to_exact_outdoor_faces(staged):
    before, _, report, fixture = staged
    catalog = {a['assetId']: a for a in fixture['catalog']}
    art.check_targets(before, catalog)
    assert [(r['artworkId'], r['target']) for r in report['records']] == [
        ('outdoor-apex-wolf', dict(placementId='pl-private-gym-fields-east-north', face='positive_z')),
        ('outdoor-peak-performance', dict(placementId='pl-private-gym-sports-court-back', face='positive_z')),
    ]
    for spec in art.SPECS:
        for field, value in [('position', dict(x=0, y=0, z=0)), ('scale', 2),
                             ('quaternion', dict(x=0, y=1, z=0, w=0))]:
            changed = deepcopy(before)
            wall = next(p for p in changed['placements'] if p['placementId'] == spec['placement'])
            wall['transform'][field] = value
            with pytest.raises(AssertionError):
                art.check_targets(changed, catalog)
    stale = deepcopy(catalog)
    stale[art.SPECS[0]['asset']]['assetDefinitionRevision'] = '0'*64
    with pytest.raises(AssertionError):
        art.check_targets(before, stale)


def test_original_png_bytes_and_visible_content_preserved(staged):
    _, _, report, _ = staged
    for source, record in zip(report['sources'], report['records']):
        original = art.Path.home()/'Downloads'/source['file']
        staged_image = art.OUT/'staged-project'/source['artifact']
        assert original.read_bytes() == staged_image.read_bytes()
        assert art.hashlib.sha256(staged_image.read_bytes()).hexdigest() == source['sha256']
        with Image.open(original) as image:
            uv, box = art.alpha_uv(image)
            assert record['uv'] == uv
            assert source['alphaBounds'] == list(box)
        assert record['coverage'] == .98
