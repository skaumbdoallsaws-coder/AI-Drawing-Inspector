"""Focused authoring checks for the work/lounge and wellness annex."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.expand_private_gym_wellness import wall_specs, ROOMS, material_rules
from tools.apex_equipment_materials import pack
from shapely.geometry import box


def test_partition_segments_do_not_interpenetrate_or_touch():
    specs=wall_specs()
    assert len({s[0] for s in specs})==len(specs)
    shapes=[]
    for key,w,d,h,x,z in specs:
        assert min(w,d,h)>.01
        shape=box(x-w/2,z-d/2,x+w/2,z+d/2)
        for other_key,other in shapes:
            assert shape.distance(other)>.005,(key,other_key)
        shapes.append((key,shape))


def test_private_bay_openings_remain_clear():
    shapes=[box(x-w/2,z-d/2,x+w/2,z+d/2) for _,w,d,_,x,z in wall_specs()]
    for i in range(5):
        center=52.325+1.65*i
        opening=box(center-.55,16.3,center+.55,16.95)
        assert all(opening.intersection(s).area<1e-8 for s in shapes)


def test_annex_has_separate_work_meeting_and_food_spaces():
    keys=['conference','work','kitchen','cafe','lounge','corridor']
    for i,key in enumerate(keys):
        a=box(*ROOMS[key][1])
        assert a.area>0 and a.bounds[3]<=0
        for other in keys[i+1:]:assert a.intersection(box(*ROOMS[other][1])).area==0
    assert ROOMS['recovery'][1]==(54,0,60,10)


def test_vanity_finishes_preserve_ceramic_and_distinguish_hardware(tmp_path,monkeypatch):
    import tools.expand_private_gym_wellness as module
    doc={'asset':{'version':'2.0'},'meshes':[{'name':'VANITY-DOUBLE SINK','primitives':[]}], 'nodes':[]}
    (tmp_path/'source.glb').write_bytes(pack(doc,b''))
    monkeypatch.setattr(module,'ROOT',tmp_path)
    rules=material_rules('vanity',{'artifact':'source.glb'})
    assert rules['0:0']=='frame'
    assert rules['0:1']=='gold'
    assert rules['0:2']=='steel'
    assert rules['0:3']=='marking'
