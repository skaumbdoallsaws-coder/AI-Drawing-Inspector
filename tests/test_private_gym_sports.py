"""Geometry and source-preservation checks for the user-authored sports annex."""
import json
import math
import struct

import pytest

from tools.expand_private_gym_sports import COURT, court_markings
from tools.import_private_gym_sports import remove_empty_cad_nodes


def test_court_lines_have_five_centimetre_width_and_unique_ids():
    lines = court_markings()
    assert len({p['key'] for p in lines}) == len(lines)
    assert all(p['depth']==.05 and p['width']>0 for p in lines)
    assert all(math.isfinite(p[k]) for p in lines for k in ('x','z','width','rotation'))


def test_half_court_size_rim_and_three_point_geometry():
    assert COURT['endlineZ']-COURT['halfZ']==14
    assert COURT['width']==15
    assert COURT['endlineZ']-COURT['rimZ']==pytest.approx(1.575)
    for p in court_markings():
        if not p['key'].startswith('three-point'): continue
        angle=math.radians(p['rotation'])
        for direction in (-1,1):
            x=p['x']+direction*p['width']/2*math.cos(angle)
            z=p['z']-direction*p['width']/2*math.sin(angle)
            assert math.hypot(x-COURT['centerX'],z-COURT['rimZ'])==pytest.approx(6.725)
    assert not any(p['key']=='free-throw-dashed-2' for p in court_markings())


def test_remove_only_empty_cad_container_mesh(tmp_path):
    document=dict(meshes=[dict(primitives=[dict(attributes=dict(POSITION=-1),indices=-1)]),
                          dict(primitives=[dict(attributes=dict(POSITION=0),indices=1)])],
                  nodes=[dict(mesh=0,children=[1]),dict(mesh=1)],accessors=[{},{}])
    data=json.dumps(document).encode();data+=b' '*((-len(data))%4)
    binary=struct.pack('<II',4,0x004e4942)+b'abcd'
    path=tmp_path/'model.glb'
    path.write_bytes(struct.pack('<III',0x46546c67,2,20+len(data)+len(binary))+
                     struct.pack('<II',len(data),0x4e4f534a)+data+binary)
    assert remove_empty_cad_nodes(path)==[0]
    raw=path.read_bytes();size=struct.unpack_from('<I',raw,12)[0];result=json.loads(raw[20:20+size])
    assert len(result['meshes'])==1
    assert result['nodes']==[dict(children=[1]),dict(mesh=0)]
    assert raw[20+size:]==binary
    assert remove_empty_cad_nodes(path)==[]
