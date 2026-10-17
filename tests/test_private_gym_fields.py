"""Geometry and candidate-preservation checks for the authored sports extension."""
from copy import deepcopy
import json
import math
from pathlib import Path
import pytest
from tools.private_gym_field_geometry import FIELD, soccer_markings, goal_glb


def test_markings_are_unique_and_match_small_sided_dimensions():
    markings=soccer_markings()
    assert len({x['key'] for x in markings})==len(markings)
    assert FIELD['maxX']-FIELD['minX']==32
    assert FIELD['maxZ']-FIELD['minZ']==18
    straight={x['key']:x for x in markings if x['key'] in ('south','north','east','west','halfway')}
    assert straight['south']['width']==straight['north']['width']==32
    assert straight['west']['width']==straight['east']['width']==18
    assert straight['halfway']['width']==18
    assert all(x['depth']==.08 for x in straight.values())
    assert {x['x'] for x in markings if x['key'].endswith('spot')}=={11,21,31}


@pytest.mark.parametrize('prefix,cx,cz,r',[
    ('center-circle',21,48,3),('west-penalty',5,48,6),('east-penalty',37,48,6)])
def test_arc_endpoints_remain_on_authored_radius(prefix,cx,cz,r):
    for line in [x for x in soccer_markings() if x['key'].startswith(prefix)]:
        theta=-math.radians(line['rotation'])
        for sign in (-1,1):
            x=line['x']+sign*math.cos(theta)*line['width']/2
            z=line['z']+sign*math.sin(theta)*line['width']/2
            assert math.hypot(x-cx,z-cz)==pytest.approx(r,abs=1e-8)


def test_goal_has_real_opening_and_finite_meshes():
    import io
    import numpy as np
    import trimesh
    scene=trimesh.load_scene(io.BytesIO(goal_glb()),file_type='glb',process=False)
    assert len(scene.geometry)==2
    assert scene.extents==pytest.approx([3.16,2.08,1.3],abs=1e-6)
    assert scene.bounds[0][1]==pytest.approx(0,abs=1e-6)
    assert all(np.isfinite(g.vertices).all() for g in scene.geometry.values())


def test_staged_candidate_preserves_saved_entities_and_scale():
    folder=Path(__file__).resolve().parents[1]/'.runtime/private-gym-fields-20261008'
    if not (folder/'candidate.json').exists():
        pytest.skip('Run the authoring stage before candidate integration checks')
    before=json.loads((folder/'before.json').read_text())
    after=json.loads((folder/'candidate.json').read_text())
    for field,key in [('placements','placementId'),('zones','zoneId'),('routes','routeId'),('floorMarkings','markingId')]:
        current={v[key]:v for v in after[field]}
        assert all(current[v[key]]==v for v in before[field])
    assert before['extensions']['facilityPerimeterWalls']==after['extensions']['facilityPerimeterWalls']
    assert all(p['transform']['scale']==1 for p in after['placements'])
    assert after['extensions']['facilityPlan']==before['extensions']['facilityPlan']
    assert max(s['maxZ'] for s in after['extensions']['facilityGround']['surfaces'])==72


def test_mutating_an_existing_placement_fails_preservation():
    folder=Path(__file__).resolve().parents[1]/'.runtime/private-gym-fields-20261008'
    if not (folder/'candidate.json').exists():
        pytest.skip('Run the authoring stage before candidate integration checks')
    from tools.expand_private_gym_fields import audit
    before=json.loads((folder/'before.json').read_text())
    altered=deepcopy(json.loads((folder/'candidate.json').read_text()))
    altered['placements'][0]['transform']['position']['x']+=1
    with pytest.raises(AssertionError,match='Existing placements changed'):
        audit(before,altered,{},[])
