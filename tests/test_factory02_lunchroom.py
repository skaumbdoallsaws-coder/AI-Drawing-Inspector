from copy import deepcopy
import json
from pathlib import Path
import pytest
from shapely.geometry import box
from shapely.ops import unary_union
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.facility_layout.plan_settings import shell_with_plan_boundary
from ai_inspector.facility_layout.spatial import diagnose_layout
from tools import expand_factory02_lunchroom as lunch
from tools import add_factory02_cafeteria as cafe
from tools import add_factory02_kitchen_walls as kitchen
from tools.audit_independent_factory_layer2 import marking_polygon


def inputs(monkeypatch):
    doc=json.loads((Path(__file__).parent/'fixtures/facility_layout/empty_cell.json').read_text())
    doc.update(layoutId=lunch.LAYOUT_ID,placements=[],zones=[],routes=[],floorMarkings=[])
    doc.setdefault('extensions',{})['facilityPlan']=dict(widthMeters=376,depthMeters=200.04,
        gridSpacingMeters=1.524,majorGridSpacingMeters=7.62)
    sizes={lunch.TABLE:(1.51097,1.5113,.74233),lunch.CHAIR:(.587,.5499,.8299),
        lunch.KITCHEN:(3.4654,4.547,2.48),'asset-green-garbage-container':(.68,.691,1.1764),
        'asset-user-library-sink-1':(1.2192,.6096,1.016),
        'asset-old-factory-wall':(.25,71,6),'asset-old-office-wall':(23,.18,3)}
    sizes.update({s['assetId']:tuple(s['dimensions'][k] for k in ('width','depth','height')) for s in lunch.wall_specs()[1]})
    catalog={}
    for aid,(w,d,h) in sizes.items():
        geometry=dict(footprintPolygons=[lunch.boundary((-w/2,-d/2,w/2,d/2))],
            heightInterval=dict(minimumY=0,maximumY=h))
        catalog[aid]=dict(assetId=aid,assetDefinitionRevision='a'*64,displayName=aid,
            definition=dict(geometry=deepcopy(geometry),readiness=dict(placementReady=dict(value=True))),
            geometry=geometry,clearances=[])
    monkeypatch.setattr(cafe,'layout_revision',lambda _:cafe.BASE_REVISION)
    doc=apply_facility_layout_operations(doc,cafe.cafeteria_operations(doc,catalog))['document']
    monkeypatch.setattr(kitchen,'layout_revision',lambda _:kitchen.BASE_REVISION)
    doc=apply_facility_layout_operations(doc,kitchen.kitchen_operations(doc))['document']
    for zid,b in [('zn-parking-office-extension',(299.75,0,376,96)),
                  ('zn-parking-office-office',(302,10,325,28.5))]:
        doc['zones'].append(dict(zoneId=zid,label=zid,zoneType='workcell',boundary=lunch.boundary(b),
            floorElevation=0,anchors=[],evidence=[],extensions={}))
    for pid,aid,x,z in [('pl-parking-office-wall-factory-upper','asset-old-factory-wall',299.88964,55.5),
                       ('pl-parking-office-wall-office-north','asset-old-office-wall',313.5,28.41)]:
        doc['placements'].append(dict(placementId=pid,assetId=aid,assetDefinitionRevision='a'*64,
            positionMode='locked',snapRelationship=None,metadata={},
            transform=dict(position=dict(x=x,y=0,z=z),quaternion=dict(x=0,y=0,z=0,w=1),scale=1)))
    doc['floorMarkings'].append(dict(markingId='fm-parking-office-000-office-floor-000',
        markingType='solid_line',label='Office Floor',semanticRole='decorative',
        transform=dict(position=dict(x=313.5,y=0,z=24.15),rotationDegrees=0),
        width=23,depth=8.7,fillColor='#d9e0e4',strokeColor='#d9e0e4',opacity=1,text='',
        positionMode='manual',metadata={},evidence=[]))
    doc['floorMarkings'].append(dict(markingId='fm-parking-office-000-asphalt-000',
        markingType='solid_line',label='Parking Surface',semanticRole='decorative',
        transform=dict(position=dict(x=351,y=0,z=29.2),rotationDegrees=0),
        width=46,depth=1.6,fillColor='#343c42',strokeColor='#343c42',opacity=1,text='',
        positionMode='manual',metadata={},evidence=[]))
    monkeypatch.setattr(lunch,'layout_revision',lambda _:lunch.BASE)
    return doc,catalog


def build(monkeypatch):
    doc,catalog=inputs(monkeypatch)
    ops,removed=lunch.operations(doc,catalog)
    result=apply_facility_layout_operations(doc,ops)['document']
    return doc,catalog,ops,removed,result


def test_96_seats_relocation_future_capacity_and_preservation(monkeypatch):
    doc,catalog,ops,removed,result=build(monkeypatch)
    report=lunch.audit(doc,result,catalog,removed)
    assert report['tables']==24 and report['diningSeats']==96
    assert report['reservedSeats']==24 and report['oldCafeteriaCleared']
    old_ids={p['placementId'] for p in doc['placements'] if p['placementId'].startswith(lunch.FURNITURE_PREFIX)}
    assert old_ids <= {p['placementId'] for p in result['placements']}
    assert lunch.operations(doc,catalog)==(ops,removed)
    assert all('zoneId' not in p for p in result['placements'])


def test_authoring_leaves_inputs_unchanged_and_reuses_ids(monkeypatch):
    doc,catalog=inputs(monkeypatch);before=deepcopy((doc,catalog))
    ops,_=lunch.operations(doc,catalog)
    assert (doc,catalog)==before
    assert {o['placementId'] for o in ops if o['op']=='delete_placement'}==lunch.REMOVED_WALLS
    assert sum(o['op']=='move_placement' for o in ops)==21
    assert sum(o.get('placement',{}).get('assetId')==lunch.TABLE for o in ops)==20
    assert sum(o.get('placement',{}).get('assetId')==lunch.CHAIR for o in ops)==80


def test_real_spatial_checks_accept_both_entrances_and_reject_blockage(monkeypatch):
    _,catalog,_,_,result=build(monkeypatch)
    def metrics(layout):
        return diagnose_layout(layout,list(catalog.values()),
            shell=shell_with_plan_boundary({'features':[]},layout))['metrics']
    actual=metrics(result)
    assert actual['placementCollisions']==0 and actual['obstructedAisleCount']==0
    for ending,axis,value in [('wall-factory-lower','z',44.2),('wall-office-shared-left','x',313.25)]:
        bad=deepcopy(result)
        p=next(p for p in bad['placements'] if p['placementId'].endswith(ending))
        p['transform']['position'][axis]=value
        assert metrics(bad)['obstructedAisleCount']>0


def test_floor_tiles_do_not_cover_new_paths_or_overlap_existing_ground(monkeypatch):
    before,_,_,_,result=build(monkeypatch)
    ground=[marking_polygon(m) for m in result['floorMarkings']
            if m['markingId'].startswith(('fm-lunchroom-000-','fm-parking-office-000-office-floor-',
                                         'fm-parking-office-000-asphalt-'))]
    for i,p in enumerate(ground):
        assert all(p.intersection(q).area<1e-8 for q in ground[i+1:]+lunch.paint_exclusions())
    original=unary_union([box(*lunch.FLOOR)]+[marking_polygon(m) for m in before['floorMarkings']
                        if m['markingId'].startswith(('fm-parking-office-000-office-floor-',
                                                     'fm-parking-office-000-asphalt-'))])
    expected=original.difference(unary_union(lunch.paint_exclusions()))
    assert unary_union(ground).symmetric_difference(expected).area<1e-8


@pytest.mark.parametrize('fault',['chair-facing','kitchen-not-moved','unrelated-change','lost-seat'])
def test_audit_rejects_incomplete_or_incorrect_changes(monkeypatch,fault):
    doc,catalog,_,removed,result=build(monkeypatch)
    if fault=='chair-facing':
        p=next(p for p in result['placements'] if p['placementId'].endswith('table-1-chair-1'))
        p['transform']['quaternion']=dict(x=0,y=1,z=0,w=0)
    elif fault=='kitchen-not-moved':
        p=next(p for p in result['placements'] if p['placementId']==lunch.FURNITURE_PREFIX+'kitchen')
        p['transform']['position']=dict(x=57.3,y=0,z=32.8)
    elif fault=='unrelated-change':result['displayName']='Accidental rename'
    else:result['placements']=[p for p in result['placements'] if not p['placementId'].endswith('table-24-chair-4')]
    with pytest.raises(AssertionError):lunch.audit(doc,result,catalog,removed)


def test_wrong_layout_revision_or_unready_furniture_refuses(monkeypatch):
    doc,catalog=inputs(monkeypatch)
    with pytest.raises(ValueError,match='changed'):lunch.operations(dict(doc,layoutId='fl-other'),catalog)
    catalog[lunch.TABLE]['definition']['readiness']['placementReady']['value']=False
    with pytest.raises(ValueError,match='not placement-ready'):lunch.operations(doc,catalog)
    monkeypatch.setattr(lunch,'layout_revision',lambda _:'changed')
    with pytest.raises(ValueError,match='changed'):lunch.operations(doc,catalog)
