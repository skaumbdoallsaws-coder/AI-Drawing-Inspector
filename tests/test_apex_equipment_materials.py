"""Geometry, finish and scope checks for the Private Gym material authoring tool."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import apex_equipment_materials as theme
from tools.private_gym_equipment_theme import audit, OVERRIDES, SPORTS
import numpy as np
import pytest
import trimesh


@pytest.mark.parametrize('name,expected',[
    ('assento.sldprt','upholstery'),('cushion-big','upholstery'),
    ('cojin_redondo_1','upholstery'),('cojinete_2','steel'),
    ('tubo_para_cojines','frame'),('estrutura_para_tapiz','frame'),
    ('seat-fix','frame'),('coussinet','steel'),('pin_selector','gold'),
    ('hand grip','rubber'),('washer','steel'),('Part001','frame'),
])
def test_conservative_component_labels(name,expected):
    assert theme.named_role(name)==expected


def test_palette_is_linear_and_protected():
    for role,(color,metal,rough) in theme.PALETTE.items():
        m=theme.material(role)
        assert m['extras']['facilityAuthoredFinish'] is True
        assert m['pbrMetallicRoughness']==dict(baseColorFactor=theme.linear_rgb(color)+[1],
                                            metallicFactor=metal,roughnessFactor=rough)
    assert theme.material('upholstery')['pbrMetallicRoughness']['metallicFactor']==0
    assert theme.material('gold_padding')['pbrMetallicRoughness']['metallicFactor']==0


def test_sports_component_roles_are_scoped():
    assert len(SPORTS)==5 and all(not a.endswith('-apex') for a in SPORTS)
    bag=OVERRIDES['asset-gym-sports-boxing-bag']
    assert all(bag[str(i)]=='gold_padding' for i in range(44,48))
    assert bag['0']=='steel' and '57' not in bag
    goal=OVERRIDES['asset-private-gym-fields-soccer-goal']
    assert goal=={'0':'gold','1':'marking'}
    assert OVERRIDES['asset-gym-sports-basketball-hoop']['0:6']=='rim_orange'


def test_override_wins_without_changing_binary_geometry():
    raw=trimesh.Scene(trimesh.creation.box()).export(file_type='glb')
    before,data=theme.unpack(raw)
    edited,records=theme.annotate(raw,{'0':'upholstery'})
    after,edited_data=theme.unpack(edited)
    assert data==edited_data
    assert before['nodes']==after['nodes'] and before['accessors']==after['accessors']
    assert records[0]['role']=='upholstery'


def test_region_splitting_and_batching_preserve_geometry(tmp_path,monkeypatch):
    scene=trimesh.Scene()
    for i,x in enumerate([-1,1]):
        mesh=trimesh.creation.box(extents=[.5,.5,.5]);mesh.apply_translation([x,0,0])
        scene.add_geometry(mesh,geom_name='structure'+str(i))
    source=tmp_path/'model.glb';source.write_bytes(scene.export(file_type='glb'))
    monkeypatch.setattr(theme,'ROOT',tmp_path)
    asset=dict(assetId='test',artifact='model.glb',sourceToCanonical=np.eye(4).flatten(order='F').tolist())
    raw,evidence=theme.build_variant(asset,{'regions':[dict(bounds=[[0,-1,-1],[2,1,1]],role='gold')]})
    assert evidence['triangleCount']==24 and evidence['maxBoundsChangeMeters']==0
    assert evidence['roles']==['frame','gold']
    assert source.read_bytes()==scene.export(file_type='glb')
    assert set(m['name'] for m in theme.unpack(raw)[0]['materials'])=={'APEX frame','APEX gold'}


def test_layout_audit_rejects_movement_and_art_changes():
    before=dict(updatedAt='old',placements=[dict(placementId='p',assetId='a',transform={'x':1})],art=['keep'])
    after=json.loads(json.dumps(before));after['placements'][0]['assetId']='b'
    audit(before,after,{'p':{'assetId':'b'}})
    after['placements'][0]['transform']['x']=2
    with pytest.raises(AssertionError):audit(before,after,{'p':{'assetId':'b'}})
    after['placements'][0]['transform']['x']=1;after['art']=[]
    with pytest.raises(AssertionError):audit(before,after,{'p':{'assetId':'b'}})
