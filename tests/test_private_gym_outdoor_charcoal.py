from copy import deepcopy
import json
import pytest
from tools import style_private_gym_outdoor_walls as style


@pytest.fixture
def staged():
    if not (style.OUT/'candidate.json').exists():
        pytest.skip('Local outdoor charcoal update not staged')
    return tuple(json.loads((style.OUT/name).read_bytes()) for name in ['before.json', 'candidate.json'])


def test_only_outward_faces_change(staged):
    before, after = staged
    assert style.audit(before, after)['outdoorFaces'] == 2
    get_faces = lambda doc: doc['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['wallFaces']
    faces = get_faces(after)
    for pid in style.TARGETS:
        rows = [f for f in faces if f['placementId'] == pid and f['face'] == 'positive_z']
        assert len(rows) == 1 and rows[0]['color'] == '#202428'
    untouched = lambda f: f['placementId'] not in style.TARGETS or f['face'] != 'positive_z'
    assert list(filter(untouched, get_faces(before))) == list(filter(untouched, faces))
    assert style.painted_settings(after) == style.painted_settings(before)


def test_equipment_and_artwork_cannot_change(staged):
    before, after = staged
    changed = deepcopy(after)
    changed['placements'][0]['transform']['scale'] = 2
    with pytest.raises(AssertionError):
        style.audit(before, changed)
    changed = deepcopy(after)
    changed['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['fittedArtworks'][0]['coverage'] = .5
    with pytest.raises(AssertionError):
        style.audit(before, changed)


def test_existing_finish_binding_cannot_be_stale(staged):
    before, _ = staged
    changed = deepcopy(before)
    face = next(f for f in changed['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['wallFaces']
                if f['placementId'] in style.TARGETS)
    face['assetDefinitionRevision'] = '0'*64
    with pytest.raises(AssertionError):
        style.painted_settings(changed)


def test_render_fixture_uses_exact_candidate_face_colors(staged):
    _, candidate = staged
    fixture = json.loads((style.OUT/'render-fixture.json').read_bytes())['layout']
    finish = lambda doc: doc['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']
    assert finish(fixture)['wallFaces'] == [f for f in finish(candidate)['wallFaces'] if f['placementId'] in style.TARGETS]
