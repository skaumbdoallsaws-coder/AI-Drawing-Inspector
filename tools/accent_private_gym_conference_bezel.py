"""Give only the Private Gym conference screen an immutable gold bezel variant."""
import argparse
from copy import deepcopy
from tools import accent_private_gym_tv_bezel as writer
from tools.apex_equipment_materials import unpack, pack, material, np

OUT=writer.ROOT/'.runtime/private-gym-conference-gold-bezel-20261010'
SOURCE='asset-breakroom-conference-screen'
ASSET=SOURCE+'-gym-gold-bezel'
PLACEMENT='pl-gym-wellness-conference-screen'


def accent(raw):
    doc,data=unpack(raw)
    original=deepcopy(doc)
    assert len(doc['meshes'])==6
    bezel=doc['meshes'][5]['primitives'][0]
    assert bezel==dict(attributes=dict(NORMAL=11,POSITION=5),indices=17,material=0,mode=4)
    pos=doc['accessors'][5]
    assert np.allclose(pos['min'],[0,-.0127,-.00254])
    assert np.allclose(pos['max'],[.9144,.5588,0])
    assert doc['accessors'][17]['count']==1104
    gold=material('gold')
    gold['name']='APEX gold conference screen bezel'
    gold['pbrMetallicRoughness'].update(metallicFactor=.15,roughnessFactor=.45)
    bezel['material']=len(doc['materials'])
    doc['materials'].append(gold)
    expected=deepcopy(original)
    expected['materials'].append(gold)
    expected['meshes'][5]['primitives'][0]['material']=len(original['materials'])
    assert doc==expected
    payload=pack(doc,data)
    assert unpack(payload)[1]==data
    return payload,dict(bezelTriangles=368,geometryPreserved=True,
        originalVertexBuffersPreserved=True,screenAndHousingUnchanged=True,color='#C99B39')


def audit(before,after,catalog):
    expected=deepcopy(before)
    p=next(p for p in expected['placements'] if p['placementId']==PLACEMENT)
    assert p['assetId']==SOURCE
    p.update({k:catalog[ASSET][k] for k in ('assetId','assetDefinitionRevision')})
    expected['updatedAt']=after['updatedAt']
    assert expected==after,'Unexpected change outside the conference-screen asset binding'
    return dict(placementId=PLACEMENT,otherPlacementsUnchanged=len(before['placements'])-1,
        transformUnchanged=True,wallAttachmentUnchanged=True,blackScreenUnchanged=True)


writer.OUT=OUT
writer.SOURCE=SOURCE
writer.ASSET=ASSET
writer.PLACEMENT=PLACEMENT
writer.ARTIFACT=writer.ROOT/'generated/industrial_assets/local_library/breakroom-conference-screen/model-gym-gold-bezel.glb'
writer.FIXTURE_BOUNDS=(21.9,30.1,-11.1,-2.9)
writer.accent=accent
writer.audit=audit

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['stage','publish','save'])
    args=parser.parse_args()
    writer.stage() if args.phase=='stage' else writer.finish(args.phase)
