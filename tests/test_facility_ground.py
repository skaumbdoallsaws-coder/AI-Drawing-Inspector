from copy import deepcopy
import pytest
from ai_inspector.facility_layout.ground import normalize_ground, supports_footprint
from ai_inspector.facility_layout.plan_settings import shell_with_plan_boundary


def tile(sid, x0, x1, y=0, end=None):
    return dict(surfaceId=sid,minX=x0,maxX=x1,minZ=0,maxZ=10,
        startElevation=y,endElevation=y if end is None else end,slopeAxis='x',color='#888888')


def test_ground_overrides_plan_without_mutating_shell():
    shell=dict(features=[dict(featureId='old',featureKind='floor_surface'),dict(featureId='wall',featureKind='wall')])
    before=deepcopy(shell)
    layout=dict(extensions=dict(facilityGround=dict(schemaVersion=1,surfaces=[tile('yard',-20,-10,-1.35),tile('ramp',-10,0,-1.35,0),tile('factory',0,40)])))
    result=shell_with_plan_boundary(shell,layout)
    assert shell==before
    assert [f['featureId'] for f in result['features']]==['wall','yard','factory']


def test_support_across_tiles_but_not_gaps_slopes_or_wrong_elevation():
    ground=normalize_ground(dict(schemaVersion=1,surfaces=[tile('one',-20,-10,-1.35),tile('two',-10,0,-1.35),tile('ramp',0,10,-1.35,0)]))
    points=[(-11,2),(-9,2),(-9,4),(-11,4)]
    assert supports_footprint(ground,points,-1.35)
    assert not supports_footprint(ground,points,0)
    assert not supports_footprint(ground,points,-1.35,'one')
    assert not supports_footprint(ground,[(-1,2),(1,2),(1,4),(-1,4)],-1.35)
    ground['surfaces'][1]['minX']=-9
    assert not supports_footprint(ground,points,-1.35)


@pytest.mark.parametrize('change',[
    lambda g:g['surfaces'].append(tile('two',5,15)),
    lambda g:g['surfaces'].append(tile('one',10,20)),
    lambda g:g['surfaces'][0].update(startElevation=float('nan')),
    lambda g:g['surfaces'][0].update(minX=True),
    lambda g:g['surfaces'][0].update(maxX=0),
    lambda g:g['surfaces'][0].update(color='red'),
    lambda g:g['surfaces'][0].update(slopeAxis='y'),
    lambda g:g.update(unknown=True),
    lambda g:g.update(schemaVersion=True),
])
def test_invalid_ground_rejected(change):
    g=dict(schemaVersion=1,surfaces=[tile('one',0,10)])
    change(g)
    with pytest.raises(ValueError):normalize_ground(g)


def test_ground_operation_roundtrip_and_atomic_rejection():
    import json
    from pathlib import Path
    from ai_inspector.facility_layout.operations import apply_facility_layout_operations, FacilityLayoutOperationError
    doc=json.loads((Path(__file__).parent/'fixtures/facility_layout/empty_cell.json').read_text())
    before=deepcopy(doc)
    value=dict(schemaVersion=1,surfaces=[tile('yard',-30,0,-1.35),tile('factory',0,30)])
    result=apply_facility_layout_operations(doc,[dict(op='set_ground',ground=value)])
    assert result['document']['extensions']['facilityGround']==value
    assert result['canonicalDiff'] and doc==before
    bad=deepcopy(value);bad['surfaces'][1]['minX']=-1
    with pytest.raises(FacilityLayoutOperationError):
        apply_facility_layout_operations(doc,[dict(op='set_ground',ground=value),dict(op='set_ground',ground=bad)])
    assert doc==before
    restored=apply_facility_layout_operations(result['document'],[dict(op='set_ground',ground=None)])['document']
    assert 'facilityGround' not in restored['extensions']
    from ai_inspector.facility_layout.plan_settings import default_plan_settings
    with pytest.raises(FacilityLayoutOperationError,match='explicit ground levels'):
        apply_facility_layout_operations(result['document'],[dict(op='set_plan_settings',planSettings=default_plan_settings(width_meters=80))])


def test_real_spatial_engine_rejects_wrong_level_and_accepts_yard():
    import json
    from pathlib import Path
    from ai_inspector.facility_layout.spatial import diagnose_layout
    doc=json.loads((Path(__file__).parent/'fixtures/facility_layout/empty_cell.json').read_text());doc['zones']=[]
    doc['extensions']={'facilityGround':dict(schemaVersion=1,surfaces=[tile('yard',-30,0,-1.35),tile('factory',0,30)])}
    doc['placements']=[dict(placementId='pl-ground',assetId='asset-test',assetDefinitionRevision='a'*64,positionMode='manual',metadata={},snapRelationship=None,
        transform=dict(position=dict(x=-10,y=-1.35,z=5),quaternion=dict(x=0,y=0,z=0,w=1),scale=1))]
    asset=dict(assetId='asset-test',geometry=dict(footprintPolygons=[[dict(x=-1,z=-1),dict(x=1,z=-1),dict(x=1,z=1),dict(x=-1,z=1)]],heightInterval=dict(minimumY=0,maximumY=2)),clearances=[])
    shell=shell_with_plan_boundary(dict(features=[]),doc)
    def codes():return {f['code'] for f in diagnose_layout(doc,[asset],shell=shell)['findings'] if f['severity']=='error'}
    assert 'unsupported_mounting_surface' not in codes()
    doc['placements'][0]['transform']['position']['y']=0
    assert 'unsupported_mounting_surface' in codes()
