"""The edge finish must not expand walls or change their opposite faces."""
from copy import deepcopy
from io import BytesIO
import pytest
from tools.apex_equipment_materials import trimesh, np, unpack
from tools.trim_private_gym_warrior_walls import trim_box, audit, TARGETS


def box_bytes():
    from tools.apex_equipment_materials import pack
    points = np.array([[x,y,z] for z in [-.084,.084] for y in [0,3.2] for x in [-2.,2.]], dtype='<f4')
    faces = np.array([[0,2,3],[0,3,1],[4,5,7],[4,7,6], [0,1,5],[0,5,4],
        [2,6,7],[2,7,3],[0,4,6],[0,6,2],[1,3,7],[1,7,5]], dtype='<u2')
    data = points.tobytes()+faces.tobytes()
    return pack(dict(asset={'version':'2.0'}, scene=0, scenes=[{'nodes':[0]}], nodes=[{'mesh':0}],
        meshes=[{'primitives':[{'attributes':{'POSITION':0},'indices':1,'mode':4}]}],
        buffers=[{'byteLength':len(data)}],
        bufferViews=[{'buffer':0,'byteOffset':0,'byteLength':points.nbytes},
            {'buffer':0,'byteOffset':points.nbytes,'byteLength':faces.nbytes}],
        accessors=[{'bufferView':0,'componentType':5126,'count':8,'type':'VEC3',
            'min':points.min(axis=0).tolist(),'max':points.max(axis=0).tolist()},
            {'bufferView':1,'componentType':5123,'count':36,'type':'SCALAR'}]), data)


@pytest.mark.parametrize('face,axis', [('positive_z',2),('positive_x',0),('negative_z',2),('negative_x',0)])
def test_face_partition_preserves_geometry_and_other_faces(face, axis):
    raw = box_bytes()
    result, evidence = trim_box(raw, face)
    before = trimesh.load(BytesIO(raw), file_type='glb', force='scene', process=False)
    after = trimesh.load(BytesIO(result), file_type='glb', force='scene', process=False)
    assert np.array_equal(before.bounds, after.bounds)
    old = np.concatenate([m.triangles for m in before.geometry.values()])
    new = np.concatenate([m.triangles for m in after.geometry.values()])
    side = 1 if face.startswith('positive') else 0
    original = old[~np.all(np.isclose(old[:,:,axis], before.bounds[side,axis]),axis=1)]
    for triangle in original:
        assert any(np.array_equal(triangle, t) for t in new)
    assert len(original) == 10 and len(new) == 20
    old_area = sum(m.area for m in before.geometry.values())
    assert abs(sum(m.area for m in after.geometry.values())-old_area) < 1e-5
    assert evidence['goldArea'] > 0 and evidence['trimWidthMeters'] == .025
    doc, _ = unpack(result)
    gold = doc['materials'][0]
    assert gold['extras']['facilityAuthoredFinish'] is True
    assert sum(p.get('material') == 0 for p in doc['meshes'][0]['primitives']) == 1
    assert trim_box(raw, face)[0] == result


@pytest.mark.parametrize('width', [0,-1,2,10])
def test_reject_invalid_width(width):
    with pytest.raises(AssertionError):
        trim_box(box_bytes(), 'positive_z', width)


def test_audit_allows_only_exact_bindings():
    before = dict(updatedAt='old', placements=[dict(placementId=pid, assetId='old',
        assetDefinitionRevision='r1', transform={'position':{'x':1}}, appearance={'color':'#3B4147'}) for pid in TARGETS],
        extensions={'unchanged':'artwork'})
    replacement = {pid:dict(assetId=pid+'-gold', assetDefinitionRevision='r2') for pid in TARGETS}
    after = deepcopy(before)
    for p in after['placements']:
        p.update(replacement[p['placementId']])
    after['updatedAt'] = 'new'
    audit(before, after, replacement)
    after['extensions']['unchanged'] = 'bad'
    with pytest.raises(AssertionError):
        audit(before, after, replacement)


def test_second_face_preserves_first_finish_and_binary_data():
    original, _ = trim_box(box_bytes(), 'positive_z')
    before, old_data = unpack(original)
    result, _ = trim_box(original, 'negative_z')
    after, data = unpack(result)
    assert data.startswith(old_data)
    assert after['meshes'][0]['primitives'][1:3] == before['meshes'][0]['primitives'][1:]
    assert after['materials'] == before['materials']
    assert after['nodes'] == before['nodes']


def test_partial_face_preserves_coverage_and_decorated_scene():
    from tools.apex_equipment_materials import pack
    doc, data = unpack(box_bytes())
    doc['nodes'] = [{'mesh':0}, {'mesh':1}, {'children':[0,1],
        'matrix':[0,0,-1,0,0,1,0,0,1,0,0,0,0,0,0,1]}]
    doc['scenes'] = [{'nodes':[2]}]
    doc['materials'] = [{'name':'Existing artwork','pbrMetallicRoughness':{'baseColorFactor':[1,1,1,1]}}]
    mural = deepcopy(doc['meshes'][0])
    mural['primitives'][0]['material'] = 0
    doc['meshes'].append(mural)
    result, evidence = trim_box(pack(doc,data), 'negative_z', tangent_interval=(-1.4,.9))
    after, new_data = unpack(result)
    assert after['meshes'][1] == mural
    assert after['nodes'] == doc['nodes'] and after['scenes'] == doc['scenes']
    assert after['materials'][0] == doc['materials'][0]
    assert new_data.startswith(data)
    assert evidence['surfaceArea'] == pytest.approx(4*3.2)
    assert evidence['goldArea'] == pytest.approx(2.3*3.2-(2.3-.05)*(3.2-.05), abs=1e-5)
    primitive = after['meshes'][0]['primitives'][-1]
    accessor = after['accessors'][primitive['attributes']['POSITION']]
    view = after['bufferViews'][accessor['bufferView']]
    points = np.frombuffer(new_data,dtype='<f4',count=accessor['count']*3,offset=view['byteOffset']).reshape((-1,3))
    a = after['accessors'][primitive['indices']]
    v = after['bufferViews'][a['bufferView']]
    faces = np.frombuffer(new_data,dtype='<u2',count=a['count'],offset=v['byteOffset']).reshape((-1,3))
    assert points[faces,:,][...,0].min() == pytest.approx(-1.4)
    assert points[faces,:,][...,0].max() == pytest.approx(.9)


@pytest.mark.parametrize('interval', [(-3,1),(-1,3),(1,-1),(0,0)])
def test_invalid_partial_interval(interval):
    with pytest.raises(AssertionError):
        trim_box(box_bytes(), 'negative_z', tangent_interval=interval)
