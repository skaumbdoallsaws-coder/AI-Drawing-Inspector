"""Center Factory 02 cubicle workstations on their measured inside corners."""
from copy import deepcopy
import argparse
import hashlib
import json
import math
from pathlib import Path
from shutil import copytree
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
from shapely.geometry import Polygon, box
from shapely.ops import unary_union
from ai_inspector.facility_layout.authority_repository import _native_fs_path, RevisionedAuthorityRepository
from ai_inspector.facility_layout.canonical import canonicalize_layout, layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from tools.add_factory02_parking_office import hashes,write_json,verify_native_candidate
from tools.equip_factory02_cubicles import transform
from tools.render_industrial_asset_software_thumbnail import (
    _scene_instances,_source_transform_matrix,_position_view,_index_view,_transform_points)

STORE=ROOT/'.runtime/facility-layout'
LAYOUT='fl-independent-factory-20260928'
RELATIVE=Path('layouts/local/site-local/layouts')/(LAYOUT+'.json')
BASE='fa73087d8e932fb3f8f46fe472ea014dc2c7205f65f2c631412f3b2f719022f9'
CUBICLE='asset-import-cubicle-corner-workstation'
ITEMS=[('monitor',-.67,-.67,45,.26,.105),('keyboard',-.43,-.43,45,.23,.075),
       ('mouse',-.17,-.66,45,.049,.073),('computer',.22,-.75,0,.095,.24)]


def measure(spec):
    raw=(ROOT/spec['artifact']).read_bytes()
    length=struct.unpack_from('<I',raw,12)[0]
    doc=json.loads(raw[20:20+length]);offset=28+length;batches=[]
    for mesh_id,matrix in _scene_instances(doc,_source_transform_matrix(spec['sourceToCanonical'])):
        for p in doc['meshes'][mesh_id]['primitives']:
            v=_position_view(raw,offset,doc,p['attributes']['POSITION'])
            i=_index_view(raw,offset,doc,p['indices']) if 'indices' in p else np.arange(len(v))
            batches.append(_transform_points(v[i],matrix).reshape(-1,3,3))
    triangles=np.concatenate(batches)
    normals=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
    ys=triangles[:,:,1].mean(axis=1)
    horizontal=(np.ptp(triangles[:,:,1],axis=1)<1e-6)&(normals[:,1]>1e-8)&(ys>.74)&(ys<.80)
    height=float(ys[horizontal].max())
    top=triangles[horizontal&(abs(ys-height)<1e-6)]
    surface=unary_union([Polygon(t[:,[0,2]]) for t in top])
    surfaces=[]
    for name,x,z,angle,hw,hd in ITEMS:
        r=math.radians(angle);c=math.cos(r);s=math.sin(r)
        points=[(x+c*u+s*v,z-s*u+c*v) for u,v in [(-hw,-hd),(hw,-hd),(hw,hd),(-hw,hd)]]
        assert surface.buffer(1e-6).covers(Polygon(points)), ('Unsupported device surface',name)
        surfaces.append(dict(surfaceId='corner-'+name,label='Corner '+name,
            localFrame=dict(origin=dict(x=x,y=height,z=z),normal=dict(x=0,y=1,z=0),
                            xAxis=dict(x=c,y=0,z=-s),zAxis=dict(x=s,y=0,z=c)),
            bounds=dict(minimumX=-hw,maximumX=hw,minimumZ=-hd,maximumZ=hd),
            allowedSides=['above'],evidenceStatus='derived'))
    w=spec['dimensions']['width']/2;d=spec['dimensions']['depth']/2
    components=[box(-w,-d,-.2,d),box(-.2,-d,w,-.2)]
    coverage=unary_union(components).buffer(1e-6)
    # Check complete projected triangles, not only vertices, before opening the knee recess.
    for triangle in triangles:
        projected=Polygon(triangle[:,[0,2]]).convex_hull
        assert coverage.covers(projected), 'Footprint fails to contain source CAD'
    spec['footprintPolygons']=[[dict(x=x,z=z) for x,z in list(p.exterior.coords)[:-1]] for p in components]
    spec['supportSurfaces']=surfaces
    return dict(worktopHeight=height,sourceSha256=hashlib.sha256(raw).hexdigest(),
                allProjectedTrianglesContained=len(triangles),supportSurfacesOnCAD=True,
                chairLocalPosition=dict(x=.24,z=.24),chairLocalYaw=225)


def build(before,catalog):
    candidate=deepcopy(before);by_id={p['placementId']:p for p in candidate['placements']}
    asset=catalog[CUBICLE];surfaces={s['surfaceId']:s for s in asset['supportSurfaces']}
    for i in range(1,11):
        cubicle=by_id[f'pl-parking-office-cubicle-{i:02}']
        cubicle.update(assetId=CUBICLE,assetDefinitionRevision=asset['assetDefinitionRevision'])
        by_id[f'pl-parking-office-chair-{i:02}']['transform']=transform(cubicle,.24,.24,225)
        for name,x,z,angle,_hw,_hd in ITEMS:
            item=by_id[f'pl-cubicle-{i:02}-{name}'];sid='corner-'+name
            item['transform']=transform(cubicle,x,z,angle,surfaces[sid]['localFrame']['origin']['y'])
            item['snapRelationship'].update(surfaceId=sid,localPosition=dict(x=x,z=z),localRotationDegrees=angle)
    return canonicalize_layout(candidate)


def audit(before,after):
    expected=deepcopy(before);actual=deepcopy(after)
    by_id={p['placementId']:p for p in actual['placements']}
    assert len(by_id)==len(expected['placements'])==1118
    allowed={}
    for i in range(1,11):
        allowed[f'pl-parking-office-cubicle-{i:02}']=['assetId','assetDefinitionRevision']
        allowed[f'pl-parking-office-chair-{i:02}']=['transform']
        for name,*_ in ITEMS:allowed[f'pl-cubicle-{i:02}-{name}']=['transform','snapRelationship']
    for p in expected['placements']:
        for key in allowed.get(p['placementId'],[]):p[key]=by_id[p['placementId']][key]
    expected['updatedAt']=actual['updatedAt']
    assert expected==actual, 'Unrelated content changed'
    for i in range(1,11):
        chair=by_id[f'pl-parking-office-chair-{i:02}']['transform']
        monitor=by_id[f'pl-cubicle-{i:02}-monitor']['transform']
        dx=monitor['position']['x']-chair['position']['x'];dz=monitor['position']['z']-chair['position']['z']
        yaw=2*math.atan2(chair['quaternion']['y'],chair['quaternion']['w'])
        assert abs(math.sin(yaw)-dx/math.hypot(dx,dz))<1e-7
        assert abs(math.cos(yaw)-dz/math.hypot(dx,dz))<1e-7


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--publish-catalog',action='store_true')
    parser.add_argument('--publish-layout',action='store_true')
    parser.add_argument('--native-report',type=Path)
    args=parser.parse_args();out=args.output.resolve();target=STORE/RELATIVE;manifest=ROOT/PRIVATE_ASSET_MANIFEST
    if args.publish_catalog or args.publish_layout:
        report=json.loads((out/'report.json').read_text())
        assert target.read_bytes()==(out/'before.json').read_bytes(), 'Saved layout changed'
        assert hashes(target.parent)==report['layoutHashes']
        if args.publish_catalog:
            assert report['status']=='validated'
            assert manifest.read_bytes()==(out/'catalog-before.json').read_bytes()
            RevisionedAuthorityRepository._atomic_write(manifest,(out/'catalog.json').read_bytes())
            report['status']='catalog-published'
        else:
            assert report['status']=='catalog-published' and args.native_report
            assert manifest.read_bytes()==(out/'catalog.json').read_bytes()
            candidate=json.loads((out/'candidate.json').read_text());before=json.loads((out/'before.json').read_text())
            verify_native_candidate(json.loads(args.native_report.read_text()),candidate,(out/'validation-store'/RELATIVE).read_bytes())
            assert layout_revision(candidate)==report['candidateRevision'];audit(before,candidate)
            host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
            try:saved=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,BASE)
            finally:host.close()
            audit(before,saved['layout']);write_json(out/'saved.json',saved['layout'])
            others=lambda values:{k:v for k,v in values.items() if k!=target.name}
            assert others(hashes(target.parent))==others(report['layoutHashes'])
            report.update(status='saved',savedRevision=saved['revision'],otherLayoutsUnchanged=True)
    else:
        raw=target.read_bytes();before=json.loads(raw);assert layout_revision(before)==BASE
        out.mkdir(parents=True,exist_ok=False);(out/'before.json').write_bytes(raw)
        (out/'catalog-before.json').write_bytes(manifest.read_bytes());library=json.loads(manifest.read_text())
        assert not any(a['assetId']==CUBICLE for a in library['assets'])
        spec=deepcopy(next(a for a in library['assets'] if a['assetId']=='asset-import-cubicle'))
        spec.update(assetId=CUBICLE,displayName='Corner Cubicle Workstation')
        measured=measure(spec);library['assets'].append(spec);library['summary']['total']=len(library['assets'])
        write_json(out/'catalog.json',library);write_json(out/'staged-project'/PRIVATE_ASSET_MANIFEST,library)
        stage=out/'validation-store'
        copytree(_native_fs_path(STORE/'authorities'),_native_fs_path(stage/'authorities'))
        copytree(_native_fs_path(STORE/'layouts/local'),_native_fs_path(stage/'layouts/local'))
        host=LocalFacilityLayoutHost(stage,private_assets=True,private_asset_root=out/'staged-project')
        try:
            catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
            candidate=build(before,catalog);audit(before,candidate)
            spatial=host.service._diagnose_spatial(host.principal(),'site-local',candidate)
            write_json(out/'spatial.json',spatial);host.service._require_spatially_valid(spatial)
            saved=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,BASE)
            audit(before,saved['layout']);write_json(out/'candidate.json',saved['layout'])
            report=dict(status='validated',baseRevision=BASE,candidateRevision=saved['revision'],
                        layoutHashes=hashes(target.parent),measurement=measured,cubiclesCorrected=10,
                        placements=len(candidate['placements']),newPlacements=0,otherPlacementsUnchanged=1058)
        finally:host.close()
    write_json(out/'report.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='layoutHashes'}))


if __name__=='__main__':main()
