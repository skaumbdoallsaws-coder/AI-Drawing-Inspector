from copy import deepcopy
import pytest
from ai_inspector.facility_layout.floor_surfaces import normalize_floor_surfaces
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from tests.test_facility_decals import document


def finish():
    return dict(surfaceId='fs-patio',label='Patio',boundary=[dict(x=1,z=1),dict(x=8,z=1),dict(x=8,z=8),dict(x=1,z=8)],elevation=0,material='paving',color='#979b9e',roughness=.9)


def test_finish_preserves_ground_equipment_and_structural_walls():
    before=document()
    after=apply_facility_layout_operations(before,[dict(op='set_floor_surfaces',surfaces=dict(version=1,surfaces=[finish()]))])['document']
    assert after['placements']==before['placements']
    assert after['extensions']['facilityPerimeterWalls']==before['extensions']['facilityPerimeterWalls']
    assert 'facilityGround' not in after['extensions']
    assert after['extensions']['facilityFloorSurfaces']['surfaces'][0]==finish()


@pytest.mark.parametrize('patch',[dict(elevation=1),dict(roughness=True),dict(color='gold'),dict(material='fake'),dict(boundary=[dict(x=0,z=0)]),
    dict(boundary=[dict(x=-1,z=1),dict(x=8,z=1),dict(x=8,z=8)])])
def test_invalid_finish(patch):
    with pytest.raises(ValueError):normalize_floor_surfaces(dict(version=1,surfaces=[dict(finish(),**patch)]),document())


def test_overlap_rejected_and_dock_levels_preserved():
    with pytest.raises(ValueError,match='overlap'):
        normalize_floor_surfaces(dict(version=1,surfaces=[finish(),dict(finish(),surfaceId='fs-other')]),document())
    doc=document()
    doc['extensions']['facilityGround']=dict(schemaVersion=1,surfaces=[dict(surfaceId='yard',minX=0,maxX=10,minZ=0,maxZ=10,startElevation=-1.35,endElevation=-1.35,slopeAxis='x',color='#555555')])
    ground=deepcopy(doc['extensions']['facilityGround'])
    with pytest.raises(ValueError,match='ground'):
        normalize_floor_surfaces(dict(version=1,surfaces=[finish()]),doc)
    result=normalize_floor_surfaces(dict(version=1,surfaces=[dict(finish(),elevation=-1.35)]),doc)
    assert result['surfaces'][0]['elevation']==-1.35
    assert doc['extensions']['facilityGround']==ground


def test_outdoor_finish_uses_explicit_ground_extent_not_original_plan():
    doc=document()
    doc['extensions']['facilityGround']=dict(schemaVersion=1,surfaces=[dict(surfaceId='patio',minX=-10,maxX=0,minZ=0,maxZ=10,startElevation=0,endElevation=0,slopeAxis='x',color='#555555')])
    outdoor=dict(finish(),boundary=[dict(x=x,z=z) for x,z in [(-8,1),(-1,1),(-1,8),(-8,8)]])
    result=normalize_floor_surfaces(dict(version=1,surfaces=[outdoor]),doc)
    assert result['surfaces'][0]['boundary']==outdoor['boundary']
    unsupported=dict(outdoor,boundary=[dict(x=x,z=z) for x,z in [(-12,1),(-1,1),(-1,8),(-12,8)]])
    with pytest.raises(ValueError,match='ground'):
        normalize_floor_surfaces(dict(version=1,surfaces=[unsupported]),doc)
    with pytest.raises(ValueError,match='ground'):
        normalize_floor_surfaces(dict(version=1,surfaces=[dict(outdoor,elevation=1)]),doc)
