from copy import deepcopy
import json
import struct
import pytest
from tools import private_gym_reception_art as art


def test_art_fills_wall_face_and_embeds_the_selected_texture():
    if not art.TEXTURE.exists():pytest.skip('Private mural texture not present')
    png=art.TEXTURE.read_bytes();raw=art.wall_glb(png,dict(width=8,depth=.15,height=3.3))
    n=struct.unpack_from('<I',raw,12)[0];doc=json.loads(raw[20:20+n])
    primitive=doc['meshes'][-1]['primitives'][0]
    position=doc['accessors'][primitive['attributes']['POSITION']]
    assert position['min']==[-4,0,.075]
    assert position['max']==[4,3.3,.075]
    assert doc['materials'][primitive['material']]['extras']['facilityArtwork'] is True
    assert png in raw


def test_audit_permits_only_the_bound_wall_asset_change():
    before=dict(updatedAt='before',placements=[dict(placementId='wall',assetId='old',assetDefinitionRevision='1',transform={'x':6}),dict(placementId='desk',assetId='desk')])
    after=deepcopy(before);replacement=dict(assetId='new',assetDefinitionRevision='2')
    after['placements'][0].update(replacement);after['updatedAt']='after'
    art.audit(before,after,'wall',replacement)
    after['placements'][0]['transform']['x']=7
    with pytest.raises(AssertionError):art.audit(before,after,'wall',replacement)


def test_square_texture_is_rejected_for_the_wide_wall():
    png=b'\x89PNG\r\n\x1a\n'+b'\0'*8+struct.pack('>II',7200,7200)
    with pytest.raises(AssertionError):art.wall_glb(png,dict(width=8,depth=.15,height=3.3))


def test_portrait_is_contained_without_cropping_or_stretching():
    x0,y0,x1,y1=art.artwork_bounds(1087,1446,dict(width=8,depth=.15,height=3),'contain')
    assert (x1-x0)/(y1-y0)==pytest.approx(1087/1446)
    assert x0==-x1 and y0==pytest.approx(.1) and y1==pytest.approx(2.9)


def test_back_face_has_correct_winding_and_retains_original_pixels():
    source=art.ORIGINAL.parent/'Zulu Warrior with Shield and Spear.png'
    if not source.exists():pytest.skip('Private source artwork not present')
    png=source.read_bytes()
    raw=art.wall_glb(png,dict(width=8,depth=.15,height=3),fit='contain',face=-1,name='Warrior')
    n=struct.unpack_from('<I',raw,12)[0];doc=json.loads(raw[20:20+n]);binary=raw[28+n:]
    primitive=doc['meshes'][-1]['primitives'][0]
    accessor=doc['accessors'][primitive['attributes']['POSITION']]
    view=doc['bufferViews'][accessor['bufferView']]
    points=struct.unpack_from('<12f',binary,view.get('byteOffset',0))
    assert points[0]>points[3]
    assert points[2]==pytest.approx(-.075)
    assert points[10]>points[1]
    material=doc['materials'][primitive['material']]
    assert material['alphaMode']=='BLEND' and material['extras']['facilityArtwork']
    assert png in raw
