from copy import deepcopy
import pytest
from tools.add_private_gym_warrior_art import CORRIDOR, END, GALLERY, SPECS, audit, plan


def fixture():
    doc = dict(zones=[dict(zoneId=CORRIDOR, boundary=[dict(x=0, z=-3), dict(x=36, z=0)])], placements=[])
    catalog = {}
    spans = [(0.252, 4.994), (7.006, 21.994), (22.012, 25.194), (26.806, 29.994), (30.012, 32.194), (33.806, 35.748)]
    for pid, (lo, hi) in zip(GALLERY+[END], spans+[(0, 2.862)]):
        guardian = pid == END
        length = hi-lo
        bounds = dict(minimum=dict(x=-.114 if guardian else -length/2, y=0, z=-length/2 if guardian else -.084),
            maximum=dict(x=.114 if guardian else length/2, y=3.2, z=length/2 if guardian else .084))
        aid = 'asset-'+pid
        catalog[aid] = dict(assetDefinitionRevision='reviewed', tags=['wall'], definition=dict(geometry=dict(aabb=bounds)))
        doc['placements'].append(dict(placementId=pid, assetId=aid, assetDefinitionRevision='reviewed',
            transform=dict(position=dict(x=.12 if guardian else (lo+hi)/2, y=0, z=-1.557 if guardian else -3),
                quaternion=dict(x=0, y=0, z=0, w=1), scale=1)))
    sources = [dict(name=name, artifact='unused.png', alphaBounds=[0, 0, 1086, 1448], uv=[0, 0, 1, 1]) for name, _ in SPECS]
    return doc, catalog, sources


def test_sequence_uses_measured_wall_segments_and_fits_without_crossing_doors():
    doc, catalog, sources = fixture()
    records, measurements = plan(doc, catalog, sources)
    assert [a['artworkId'] for a in records] == ['hall-warrior-'+name for name, _ in SPECS]
    assert all(a['heightMeters'] == pytest.approx(2.64) for a in measurements[:4])
    assert measurements[-1]['heightMeters'] == pytest.approx(2.944)
    assert measurements[-1]['centerAlongWall'] == -1.557
    for record, m in zip(records, measurements):
        assert 0 < record['region'][0] < record['region'][2] < 1
        assert record['region'][1] == .025
        assert m['bottomMeters'] == pytest.approx(.08)
        assert m['widthMeters']/m['heightMeters'] == pytest.approx(.75)
    assert all(a['centerAlongWall'] > b['centerAlongWall'] for a, b in zip(measurements[:3], measurements[1:4]))


def test_position_follows_actual_corridor_and_wall_dimensions():
    doc, catalog, sources = fixture()
    _, before = plan(doc, catalog, sources)
    for point in doc['zones'][0]['boundary']:
        point['x'] += 10
    for p in doc['placements']:
        p['transform']['position']['x'] += 10
    _, after = plan(doc, catalog, sources)
    for a, b in zip(before[:4], after[:4]):
        assert b['centerAlongWall'] == pytest.approx(a['centerAlongWall']+10)


@pytest.mark.parametrize('change', ['revision', 'rotation', 'missing', 'not-wall', 'moved-off-corridor'])
def test_unreviewed_or_missing_wall_refused(change):
    doc, catalog, sources = fixture()
    wall = doc['placements'][0]
    if change == 'revision':
        wall['assetDefinitionRevision'] = 'new'
    elif change == 'rotation':
        wall['transform']['quaternion']['y'] = 1
    elif change == 'missing':
        doc['placements'].pop(0)
    elif change == 'not-wall':
        catalog[wall['assetId']]['tags'] = []
    else:
        wall['transform']['position']['z'] -= 1
    with pytest.raises((AssertionError, StopIteration)):
        plan(doc, catalog, sources)


def test_audit_rejects_geometry_or_existing_branding_changes():
    doc, catalog, sources = fixture()
    records, _ = plan(doc, catalog, sources)
    doc.update(updatedAt='before', extensions=dict(facilityPerimeterWalls=dict(settings=dict(exteriorFinish=dict(artworks=[dict(artworkId='apex-existing')])))))
    candidate = deepcopy(doc)
    candidate['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['fittedArtworks'] = records
    candidate['updatedAt'] = 'after'
    assert audit(doc, candidate, records)['oppositeBrandingUnchanged']
    candidate['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['artworks'] = []
    with pytest.raises(AssertionError):
        audit(doc, candidate, records)
