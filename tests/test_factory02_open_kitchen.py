from copy import deepcopy
import json
from pathlib import Path
import pytest
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from tools import open_factory02_kitchen as kitchen
from tools.add_factory02_parking_office import boundary


def inputs(monkeypatch):
    doc=json.loads((Path(__file__).parent/'fixtures/facility_layout/empty_cell.json').read_text())
    doc['layoutId']=kitchen.LAYOUT_ID
    doc=apply_facility_layout_operations(doc,[dict(op='set_perimeter_walls',wallSettings=dict(
        boundarySource='polygon',boundary=boundary((324.8,52,332,58.6)),heightMeters=2.8,
        thicknessMeters=.15,openings=[dict(edge=3,startMeters=1.3,endMeters=5.3)]))])['document']
    geometry=dict(footprintPolygons=[boundary((-.075,-3.375,.075,3.375))],
                  heightInterval=dict(minimumY=0,maximumY=2.8))
    catalog={kitchen.ASSET:dict(assetId=kitchen.ASSET,assetDefinitionRevision='a'*64,
        geometry=geometry,definition=dict(geometry=deepcopy(geometry)))}
    monkeypatch.setattr(kitchen,'layout_revision',lambda _:kitchen.BASE)
    return doc,catalog


def test_only_remove_enclosure_and_retain_exact_back_wall(monkeypatch):
    doc,catalog=inputs(monkeypatch);original=deepcopy(doc)
    ops=kitchen.operations(doc,catalog)
    assert [op['op'] for op in ops]==['set_perimeter_walls','place_asset']
    result=apply_facility_layout_operations(doc,ops)['document']
    assert kitchen.audit(doc,result,catalog)['allOtherContentUnchanged']
    assert doc==original


@pytest.mark.parametrize('fault',['unrelated-change','back-wall-moved','enclosure-retained'])
def test_audit_rejects_unrequested_changes(monkeypatch,fault):
    doc,catalog=inputs(monkeypatch)
    result=apply_facility_layout_operations(doc,kitchen.operations(doc,catalog))['document']
    if fault=='unrelated-change':result['displayName']='Changed'
    elif fault=='back-wall-moved':result['placements'][-1]['transform']['position']['x']+=1
    else:result['extensions'][kitchen.KEY]=doc['extensions'][kitchen.KEY]
    with pytest.raises(AssertionError):kitchen.audit(doc,result,catalog)


def test_wrong_layout_stale_revision_and_wrong_enclosure_refuse(monkeypatch):
    doc,catalog=inputs(monkeypatch)
    with pytest.raises(ValueError,match='changed'):kitchen.operations(dict(doc,layoutId='other'),catalog)
    altered=deepcopy(doc);altered['extensions'][kitchen.KEY]['settings']['boundary'][0]['x']=1
    with pytest.raises(ValueError,match='missing'):kitchen.operations(altered,catalog)
    monkeypatch.setattr(kitchen,'layout_revision',lambda _:'stale')
    with pytest.raises(ValueError,match='changed'):kitchen.operations(doc,catalog)
