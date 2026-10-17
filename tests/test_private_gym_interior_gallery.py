from copy import deepcopy
import hashlib
import json
import pytest
from tools.private_gym_interior_gallery import OUT, SOURCE, ARRANGEMENT, audit


def candidate():
    if not (OUT/'candidate.json').exists():pytest.skip('Run the gallery stage for integration evidence')
    return (json.loads((OUT/'before.json').read_text()),json.loads((OUT/'candidate.json').read_text()),
            json.loads((OUT/'report.json').read_text())['records'])


def test_all_artworks_are_used_once_and_original_bytes_are_preserved():
    before,after,records=candidate()
    assert len(ARRANGEMENT)==len({r[0] for r in ARRANGEMENT})==18
    sources={str(p) for d in ('animals','human') for p in (SOURCE/d).glob('*.png')}
    assert sources=={r['source'] for r in records}
    for record in records:
        staged=OUT/'staged-project/generated/facility-wall-art'/(record['sha256']+'.png')
        assert hashlib.sha256(staged.read_bytes()).hexdigest()==record['sha256']
    assert audit(before,after,records)['originalWallsAndMuralsUnchanged']


def test_existing_geometry_and_artwork_cannot_be_changed():
    before,after,records=candidate()
    altered=deepcopy(after);altered['placements'][0]['transform']['position']['x']+=1
    with pytest.raises(AssertionError,match='Content beyond'):audit(before,altered,records)
    altered=deepcopy(after)
    altered['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['artworks'][0]['widthMeters']+=1
    with pytest.raises(AssertionError,match='Existing wall artwork'):audit(before,altered,records)
