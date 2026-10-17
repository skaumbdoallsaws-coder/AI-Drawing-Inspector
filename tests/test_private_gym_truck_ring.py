"""Exact scope, embedded artwork and reviewed component finish checks."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import apex_equipment_materials as theme
from tools.private_gym_truck_ring import RING, PICKUP, REMOVED, audit, change_document, ring_logo
from PIL import Image
import numpy as np
import pytest
import trimesh


def test_ring_logo_is_centered_preserves_original_buffers_and_materials():
    mesh=trimesh.creation.box(extents=[8,3,8]);mesh.apply_translation([0,1.5,0])
    raw=trimesh.Scene(mesh).export(file_type='glb')
    image=BytesIO();Image.new('RGBA',(40,10),(201,155,57,128)).save(image,format='PNG')
    result,proof=ring_logo(raw,np.eye(4).flatten(order='F').tolist(),image.getvalue())
    before,binary=theme.unpack(raw);after,data=theme.unpack(result)
    assert data[:len(binary)]==binary
    for field in ['accessors','bufferViews','materials','meshes','nodes']:
        assert after[field][:len(before.get(field,[]))]==before.get(field,[])
    assert proof['centerCanonical']==[0,1.003,0] and proof['widthMeters']==4.6
    assert proof['depthMeters']==1.15 and proof['addedTriangles']==2
    assert image.getvalue() in result
    assert after['materials'][-1]['extras']['facilityArtwork'] is True


def sample_asset(tmp_path):
    boxes=[]
    for y in [0,2]:
        mesh=trimesh.creation.box(extents=[.5,.5,.5]);mesh.apply_translation([0,y,0]);boxes.append(mesh)
    scene=trimesh.Scene();scene.add_geometry(trimesh.util.concatenate(boxes),geom_name='body')
    (tmp_path/'model.glb').write_bytes(scene.export(file_type='glb'))
    return dict(assetId='test',artifact='model.glb',sourceToCanonical=np.eye(4).flatten(order='F').tolist())


def test_reviewed_connected_part_requires_exact_identity(tmp_path,monkeypatch):
    asset=sample_asset(tmp_path);monkeypatch.setattr(theme,'ROOT',tmp_path)
    component=dict(mesh='body',faces=12,bounds=[[-.25,1.75,-.25],[.25,2.25,.25]],role='smoked_glass')
    _,proof=theme.build_variant(asset,{'0':'vehicle_paint','connectedComponents':[component]})
    assert proof['roles']==['smoked_glass','vehicle_paint'] and proof['triangleCount']==24
    component['faces']=13
    with pytest.raises(AssertionError,match='Component identity changed'):
        theme.build_variant(asset,{'connectedComponents':[component]})


def test_radial_wheel_finish_leaves_outside_and_other_roles_untouched(tmp_path,monkeypatch):
    asset=sample_asset(tmp_path);monkeypatch.setattr(theme,'ROOT',tmp_path)
    region=dict(bounds=[[-5,-5,-5],[5,5,5]],sourceRole='rubber',role='gold',
                cylinder=dict(axis=0,center=[0,0,0],radius=.5))
    _,proof=theme.build_variant(asset,{'0':'rubber','regions':[region]})
    assert proof['roles']==['gold','rubber'] and proof['triangleCount']==24
    _,proof=theme.build_variant(asset,{'0':'frame','regions':[region]})
    assert proof['roles']==['frame']


def test_only_requested_outdoor_items_are_removed():
    ids=[RING,PICKUP,*sorted(REMOVED),'indoor-goal','indoor-ball']
    before=dict(updatedAt='before',placements=[dict(placementId=i,assetId='original',transform={'x':1}) for i in ids],
                zones=['retain'],floorMarkings=['retain'],routes=[])
    refs={RING:dict(assetId='branded-ring'),PICKUP:dict(assetId='colored-ford')}
    after=change_document(before,refs);audit(before,after,refs)
    assert [p['placementId'] for p in after['placements']]==[RING,PICKUP,'indoor-goal','indoor-ball']
    altered=deepcopy(after);altered['placements'][0]['transform']['x']=2
    with pytest.raises(AssertionError):audit(before,altered,refs)
    before['routes']=[dict(endpoint=next(iter(REMOVED)))]
    with pytest.raises(AssertionError,match='still referenced'):change_document(before,refs)
