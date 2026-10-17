from copy import deepcopy
import pytest
from ai_inspector.facility_layout.interior_walls import compile_interior_walls, validate_interior_walls, append_interior_features
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from tests.test_facility_decals import document, apply, art


def wall():
    return dict(wallId='iw-office',label='Office partition',start=dict(x=20,z=5),end=dict(x=20,z=25),heightMeters=3,
        thicknessMeters=.2,baseElevation=0,color='#45484B',openings=[dict(startMeters=5,endMeters=8)])


def set_wall(doc, walls):
    return apply_facility_layout_operations(doc,[dict(op='set_interior_walls',walls=dict(version=1,walls=walls))])['document']


def test_physical_panels_and_shell_match_and_keep_door_clear():
    doc=set_wall(document(),[wall()])
    validate_interior_walls(doc)
    panels=doc['extensions']['facilityInteriorWalls']['walls'][0]['panels']
    assert len(panels)==2
    assert max(v['z'] for v in panels[0])==10
    assert min(v['z'] for v in panels[1])==13
    shell={}
    append_interior_features(shell,doc)
    assert len(shell['features'])==2
    assert shell['features'][0]['geometry']['height']==3
    assert doc['placements']==document()['placements']


@pytest.mark.parametrize('patch', [dict(end=dict(x=20,z=5)),dict(thicknessMeters=-1),dict(heightMeters=True),dict(color='gold'),
    dict(start=dict(x=0,z=5),end=dict(x=0,z=20)),dict(baseElevation=3),dict(openings=[dict(startMeters=19,endMeters=25)])])
def test_bad_partitions_rejected(patch):
    with pytest.raises(ValueError):compile_interior_walls(dict(version=1,walls=[dict(wall(),**patch)]),document())


def test_wall_art_follows_identity_and_cannot_cross_door():
    doc=set_wall(document(),[wall()])
    decal=art(target=dict(wallId='iw-office',side='left'),region=[.05,.1,.2,.9])
    after=apply(doc,[decal])
    with pytest.raises(Exception,match='opening'):
        apply(doc,[dict(decal,region=[.1,.1,.8,.9])])
    grown=set_wall(after,[dict(wall(),heightMeters=4)])
    assert grown['extensions']['facilityDecals']==after['extensions']['facilityDecals']
    removed=set_wall(grown,[])
    assert removed['extensions']['facilityDecals']['artworks']==[]


def test_tampered_panels_are_rejected():
    doc=set_wall(document(),[wall()])
    doc['extensions']['facilityInteriorWalls']['walls'][0]['panels'][0][0]['x']=300
    with pytest.raises(ValueError):validate_interior_walls(doc)
