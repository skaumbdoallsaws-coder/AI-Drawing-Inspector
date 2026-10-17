"""Equip Factory 02's ten cubicles using measured worktops and existing models."""
from copy import deepcopy
import argparse
import hashlib
import json
import math
from pathlib import Path
from shutil import copytree
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from shapely.geometry import Polygon, box
from shapely.ops import unary_union
from ai_inspector.facility_layout.authority_repository import _native_fs_path, RevisionedAuthorityRepository
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from tools.add_factory02_parking_office import hashes, write_json, verify_native_candidate
from tools.render_industrial_asset_software_thumbnail import (
    _scene_instances, _source_transform_matrix, _position_view, _index_view, _transform_points)

STORE = ROOT / '.runtime/facility-layout'
LAYOUT = 'fl-independent-factory-20260928'
RELATIVE = Path('layouts/local/site-local/layouts') / (LAYOUT+'.json')
BASE = 'e112af5311af254178c3b4b0fc2839a34db21579fc29aba09f6633e60e85b85a'
CUBICLE = 'asset-import-cubicle-workstation'
MONITOR = (-.75, .48)
CHAIR = (0, 1.5)
FACING = math.degrees(math.atan2(CHAIR[0]-MONITOR[0], CHAIR[1]-MONITOR[1]))
BOUNDS = {'monitor-worktop':(-1.015,.04,-.46,1.02),
          'input-worktop':(-1,.45,-.30,1.02),
          'side-worktop':(.44,-1,1,-.3)}
ITEMS = [('monitor','asset-screen-21',*MONITOR,FACING,'monitor-worktop'),
         ('keyboard','asset-keyboard',-.60,.82,FACING,'input-worktop'),
         ('mouse','asset-mouse',-.38,.64,FACING,'input-worktop'),
         ('computer','asset-computer-case',.72,-.70,0,'side-worktop')]


def measure_worktop(asset):
    raw = (ROOT / asset['artifact']).read_bytes()
    length = struct.unpack_from('<I',raw,12)[0]
    doc = json.loads(raw[20:20+length]); offset = 28+length; batches = []
    for mesh_id, matrix in _scene_instances(doc,_source_transform_matrix(asset['sourceToCanonical'])):
        for p in doc['meshes'][mesh_id]['primitives']:
            vertices = _position_view(raw,offset,doc,p['attributes']['POSITION'])
            indices = _index_view(raw,offset,doc,p['indices']) if 'indices' in p else np.arange(len(vertices))
            batches.append(_transform_points(vertices[indices],matrix).reshape(-1,3,3))
    triangles = np.concatenate(batches)
    normals = np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
    ys = triangles[:,:,1].mean(axis=1)
    horizontal = (np.ptp(triangles[:,:,1],axis=1)<1e-6)&(normals[:,1]>1e-8)&(ys>.74)&(ys<.80)
    height = float(ys[horizontal].max())
    top = triangles[horizontal & (abs(ys-height)<1e-6)]
    surface = unary_union([Polygon(t[:,[0,2]]) for t in top])
    for key,b in BOUNDS.items():
        assert surface.buffer(1e-6).covers(box(*b)), ('Worktop rectangle leaves CAD surface',key)
    assert height+.45 < 1.24, 'Tower must clear the overhead storage'
    surfaces = [dict(surfaceId=key,label=key.replace('-',' ').title(),
        localFrame=dict(origin=dict(x=0,y=height,z=0),normal=dict(x=0,y=1,z=0),
                        xAxis=dict(x=1,y=0,z=0),zAxis=dict(x=0,y=0,z=1)),
        bounds=dict(minimumX=b[0],minimumZ=b[1],maximumX=b[2],maximumZ=b[3]),
        allowedSides=['above'],evidenceStatus='derived') for key,b in BOUNDS.items()]
    return surfaces,dict(heightMeters=height,artifactSha256=hashlib.sha256(raw).hexdigest(),
                         rectanglesOnMeasuredSurface=True,topTriangleCount=len(top),
                         minimumTowerToOverheadGapMeters=1.24-height-.45)


def transform(cubicle, x, z, angle, y=0):
    p=cubicle['transform']['position'];q=cubicle['transform']['quaternion']
    yaw=2*math.atan2(q['y'],q['w']);r=yaw+math.radians(angle)
    return dict(position=dict(x=p['x']+math.cos(yaw)*x+math.sin(yaw)*z,y=p['y']+y,
                              z=p['z']-math.sin(yaw)*x+math.cos(yaw)*z),
                quaternion=dict(x=0,y=math.sin(r/2),z=0,w=math.cos(r/2)),scale=1)


def build(before,catalog):
    candidate=deepcopy(before);ops=[]
    by_id={p['placementId']:p for p in candidate['placements']}
    surfaces={s['surfaceId']:s for s in catalog[CUBICLE]['supportSurfaces']}
    for i in range(1,11):
        cubicle=by_id[f'pl-parking-office-cubicle-{i:02}']
        cubicle['assetId']=CUBICLE
        cubicle['assetDefinitionRevision']=catalog[CUBICLE]['assetDefinitionRevision']
        chair=by_id[f'pl-parking-office-chair-{i:02}']
        chair['transform']=transform(cubicle,*CHAIR,FACING+180)
        for key,aid,x,z,angle,surface_id in ITEMS:
            pid=f'pl-cubicle-{i:02}-{key}'
            assert pid not in by_id
            surface=surfaces[surface_id];a=catalog[aid]
            placement=dict(placementId=pid,assetId=aid,assetDefinitionRevision=a['assetDefinitionRevision'],
                transform=transform(cubicle,x,z,angle,surface['localFrame']['origin']['y']),
                positionMode='manual',appearance=dict(color='#303940'),
                metadata=dict(instanceLabel=f'Office Cubicle {i:02} {key}',inputMethod='independent-authoring'),
                snapRelationship=dict(family='surface_attachment',attachmentId='surface:'+pid,
                    supportPlacementId=cubicle['placementId'],surfaceId=surface_id,surfaceSource='asset_definition',
                    localPosition=dict(x=x,z=z),localRotationDegrees=angle,normalOffsetMeters=0,
                    side='above',evidenceStatus='derived'))
            ops.append(dict(op='place_asset',placement=placement))
    return apply_facility_layout_operations(candidate,ops)['document'],ops


def audit(before,after):
    expected=deepcopy(before);actual=deepcopy(after)
    original={p['placementId']:p for p in expected['placements']}
    for p in actual['placements'][:len(original)]:
        old=original[p['placementId']]
        if p['placementId'].startswith('pl-parking-office-chair-'):
            old['transform']=p['transform']
        elif p['placementId'].startswith('pl-parking-office-cubicle-'):
            old['assetId']=p['assetId']
            old['assetDefinitionRevision']=p['assetDefinitionRevision']
    added=actual['placements'][len(original):]
    assert len(added)==40
    for i in range(1,11):
        group=[p for p in added if p['placementId'].startswith(f'pl-cubicle-{i:02}-')]
        assert len(group)==4
        assert {p['assetId'] for p in group}=={item[1] for item in ITEMS}
        assert all(p['snapRelationship']['supportPlacementId']==f'pl-parking-office-cubicle-{i:02}' for p in group)
        chair=next(p for p in actual['placements'] if p['placementId']==f'pl-parking-office-chair-{i:02}')
        monitor=next(p for p in group if p['assetId']=='asset-screen-21')
        c=chair['transform'];m=monitor['transform'];dx=m['position']['x']-c['position']['x'];dz=m['position']['z']-c['position']['z']
        yaw=2*math.atan2(c['quaternion']['y'],c['quaternion']['w'])
        assert abs(math.sin(yaw)-dx/math.hypot(dx,dz))<1e-7
        assert abs(math.cos(yaw)-dz/math.hypot(dx,dz))<1e-7
    actual['placements']=actual['placements'][:len(original)]
    expected['updatedAt']=actual['updatedAt']
    assert expected==actual, 'Unrelated layout content changed'


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
        spec['assetId']=CUBICLE
        spec['displayName']='Cubicle Workstation'
        assert not spec.get('supportSurfaces')
        spec['supportSurfaces'],measurement=measure_worktop(spec)
        library['assets'].append(spec)
        library['summary']['total']=len(library['assets'])
        write_json(out/'catalog.json',library);write_json(out/'staged-project'/PRIVATE_ASSET_MANIFEST,library)
        stage=out/'validation-store'
        copytree(_native_fs_path(STORE/'authorities'),_native_fs_path(stage/'authorities'))
        copytree(_native_fs_path(STORE/'layouts/local'),_native_fs_path(stage/'layouts/local'))
        host=LocalFacilityLayoutHost(stage,private_assets=True,private_asset_root=out/'staged-project')
        try:
            catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
            candidate,ops=build(before,catalog);audit(before,candidate)
            spatial=host.service._diagnose_spatial(host.principal(),'site-local',candidate)
            write_json(out/'spatial.json',spatial);host.service._require_spatially_valid(spatial)
            saved=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,BASE)
            audit(before,saved['layout']);write_json(out/'candidate.json',saved['layout']);write_json(out/'operations.json',ops)
            report=dict(status='validated',baseRevision=BASE,candidateRevision=saved['revision'],
                        layoutHashes=hashes(target.parent),measurement=measurement,chairsFacingMonitors=10,
                        cubiclesEquipped=10,addedItems=40,placements=len(candidate['placements']),
                        originalChairDisplacementMeters=.05,otherPlacementsUnchanged=len(before['placements'])-20,
                        movementPrograms=len(before['extensions']['facilityNavigation']['movementPrograms']))
        finally:host.close()
    write_json(out/'report.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='layoutHashes'}))


if __name__=='__main__':main()
