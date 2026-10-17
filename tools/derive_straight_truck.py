"""A separate rigid straight pose of the articulated 40-foot source truck."""
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import struct
import numpy as np
from tools.render_industrial_asset_software_thumbnail import (
    _scene_instances, _source_transform_matrix, _position_view, _transform_points)

ROOT=Path(__file__).resolve().parents[1]
SOURCE='asset-truck-40ft-container'
ASSET='asset-truck-40ft-container-straight'


@lru_cache(maxsize=1)
def derive():
    library=json.loads((ROOT/'generated/industrial_assets/local_library/catalog.json').read_text())
    original=next(a for a in library['assets'] if a['assetId']==SOURCE)
    data=(ROOT/original['artifact']).read_bytes()
    size,kind=struct.unpack_from('<II',data,12);assert kind==0x4e4f534a
    doc=json.loads(data[20:20+size]);offset=28+size
    assert len(doc['meshes'])==3
    assert all(set(n)<= {'mesh','name'} for n in doc['nodes'])
    canonical=_source_transform_matrix(original['sourceToCanonical'])
    points={}
    for mid,matrix in _scene_instances(doc,canonical):
        points[mid]=np.concatenate([_transform_points(_position_view(data,offset,doc,p['attributes']['POSITION']),matrix)
                                    for p in doc['meshes'][mid]['primitives']])
    from shapely.geometry import MultiPoint
    corners=np.array(MultiPoint(points[2][:,[0,2]]).minimum_rotated_rectangle.exterior.coords)[:4]
    edges=np.roll(corners,-1,axis=0)-corners
    axis=edges[np.argmax(np.linalg.norm(edges,axis=1))]
    if axis[1]<0:axis=-axis
    axis/=np.linalg.norm(axis)
    center=corners.mean(axis=0);cab_x=(points[0][:,0].min()+points[0][:,0].max())/2
    pivot=np.array([cab_x,0,center[1]+(cab_x-center[0])*axis[1]/axis[0]])
    angle=-math.atan2(axis[0],axis[1]);c,s=math.cos(angle),math.sin(angle)
    rotate=np.array([[c,0,s],[0,1,0],[-s,0,c]])
    articulation=np.eye(4);articulation[:3,:3]=rotate;articulation[:3,3]=pivot-rotate@pivot
    posed={i:_transform_points(p,articulation) if i in (1,2) else p for i,p in points.items()}
    all_points=np.concatenate(list(posed.values()));low=all_points.min(axis=0);high=all_points.max(axis=0)
    shift=np.array([-(low[0]+high[0])/2,-low[1],-(low[2]+high[2])/2])
    translation=np.eye(4);translation[:3,3]=shift
    for node in doc['nodes']:
        matrix=translation@(articulation if node['mesh'] in (1,2) else np.eye(4))@canonical
        node['matrix']=matrix.T.reshape(-1).tolist()
    payload=json.dumps(doc,separators=(',',':')).encode();payload+=b' '*((-len(payload))%4)
    binary_chunks=data[20+size:]
    result=struct.pack('<III',0x46546c67,2,20+len(payload)+len(binary_chunks))+struct.pack('<II',len(payload),0x4e4f534a)+payload+binary_chunks
    dimensions=high-low;rear=float(posed[2][:,2].min()+shift[2])
    assert dimensions[0]<2.56 and 15<dimensions[2]<20
    spec=dict(assetId=ASSET,displayName='40 ft Container Truck - Straight Dock Pose',category=original['category'],
        dimensions=dict(zip(('width','height','depth'),map(float,dimensions))),
        artifact='generated/industrial_assets/factory02_truck_yard/truck-straight/model.glb',
        description='Rigid re-pose of the existing truck. Same scale; visual coupling centre inferred from intersecting chassis axes, not a manufacturer kinematic model.',
        tags=['truck','container','40ft','straight-pose'],source=dict(kind='derived-pose',assetId=SOURCE,
            sha256=hashlib.sha256(data).hexdigest(),yawCorrectionRadians=angle,pivotMeters=pivot.tolist(),rearZMeters=rear),
        sourceToCanonical=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1])
    return result,spec,rear
