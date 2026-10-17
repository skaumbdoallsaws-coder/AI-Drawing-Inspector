"""Focused checks for office replacement scope and measured attachments."""
from copy import deepcopy
from tools.replace_private_gym_office import build, support_surface, SET, SHELF, LOGO, OLD_LABELS, COMPUTER_IDS, P


def fixture():
    def placement(pid,label):
        return dict(placementId=pid,assetId='old-asset',assetDefinitionRevision='old-revision',
            transform=dict(position=dict(x=33,y=0,z=-8),quaternion=dict(x=0,y=0,z=0,w=1),scale=1),
            metadata=dict(instanceLabel=label),snapRelationship=None)
    placements=[placement('old-'+str(i),label) for i,label in enumerate(sorted(OLD_LABELS))]
    placements += [placement(pid,pid) for pid in sorted(COMPUTER_IDS)]
    wall=placement('pl-gym-wellness-work-cafe-divider','Office Back Wall')
    wall['assetId']='wall';wall['transform']['position']=dict(x=33,y=0,z=-11)
    placements.extend([wall,placement('untouched','Reception Desk')])
    surface=support_surface(dict(sourceToCanonical=[1,0,0,0,0,0,-1,0,0,1,0,0,.03,.388,.122,1]))
    catalog={key:dict(assetDefinitionRevision='new-revision') for key in [SET,SHELF,LOGO]}
    catalog[SET]['supportSurfaces']=[surface]
    catalog['wall']=dict(definition=dict(geometry=dict(aabb=dict(maximum=dict(z=.084)))))
    return dict(placements=placements,updatedAt='before',zones=[dict(zoneId='room')]),catalog


def test_furniture_replacement_preserves_other_placements_and_room():
    before,catalog=fixture();snapshot=deepcopy(before)
    after,removed=build(before,catalog)
    assert before==snapshot
    assert len(removed)==5 and len(after['placements'])==len(before['placements'])-2
    assert after['zones']==before['zones']
    assert next(p for p in after['placements'] if p['placementId']=='untouched')==before['placements'][-1]


def test_accessories_are_bound_to_the_new_desktop():
    before,catalog=fixture();after,_=build(before,catalog)
    items={p['placementId']:p for p in after['placements']}
    for key in ['monitor','keyboard','mouse']:
        p=items['pl-gym-wellness-work-'+key]
        assert p['snapRelationship']['supportPlacementId']==P+'desk-and-three-chairs'
        assert p['snapRelationship']['surfaceId']=='worktop'
        assert p['transform']['position']['y']==catalog[SET]['supportSurfaces'][0]['localFrame']['origin']['y']


def test_logo_faces_the_door_on_the_existing_back_wall():
    before,catalog=fixture();after,_=build(before,catalog)
    logo=next(p for p in after['placements'] if p['assetId']==LOGO)
    assert logo['transform']['position']['x']==33
    assert logo['snapRelationship']['face']=='positive_z'
    assert logo['snapRelationship']['supportPlacementId']=='pl-gym-wellness-work-cafe-divider'
    assert logo['transform']['position']['y']+2<3.2


def test_logo_attachment_accounts_for_trimmed_wall_center():
    before,catalog=fixture()
    next(p for p in before['placements'] if p['assetId']=='wall')['transform']['position']['x']=32.93
    after,_=build(before,catalog)
    logo=next(p for p in after['placements'] if p['assetId']==LOGO)
    assert abs(logo['snapRelationship']['localX']-.07)<1e-8
