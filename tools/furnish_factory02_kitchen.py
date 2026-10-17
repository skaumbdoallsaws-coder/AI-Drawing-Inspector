"""Publish imported appliances and place them on the measured Factory 02 island."""
from copy import deepcopy
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from shutil import copytree
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
from shapely.geometry import Polygon,box
from shapely.ops import unary_union
from ai_inspector.facility_layout.authority_repository import _native_fs_path,RevisionedAuthorityRepository
from ai_inspector.facility_layout.canonical import canonicalize_layout,layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost,PRIVATE_ASSET_MANIFEST
from tools.add_factory02_parking_office import hashes,write_json,verify_native_candidate
from tools.equip_factory02_cubicles import transform

IMPORT=ROOT/'.runtime/breakroom-import-20261003'
STORE=ROOT/'.runtime/facility-layout'
LAYOUT='fl-independent-factory-20260928'
RELATIVE=Path('layouts/local/site-local/layouts')/(LAYOUT+'.json')
BASE='32a632f9865fa302fc3d2708493017688071b928596a85ca81f2032d70486c36'
KITCHEN='asset-kitchen-assembly-appliance-worktop'
KITCHEN_PLACEMENT='pl-independent-cafeteria-kitchen'
WORKTOP=(.19,.62,.94,1.76)
ITEMS=[('coffee-pot',.76,.83,-90,'#45545c'),('toaster',.42,.72,-90,'#c7cdd1'),
       ('microwave',.55,1.40,-90,'#8598a2')]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def measured_surface(spec):
    module_spec=importlib.util.spec_from_file_location('kitchen_mesh_measure',ROOT/'.runtime/truck-dock-measurements/inspect_meshes.py')
    module=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(module)
    raw,parts=module.read_meshes(spec)
    part=next(p for p in parts if 'tischplatte-block' in p['name'])
    triangles=part['triangles'];y=triangles[:,:,1].mean(axis=1)
    select=(np.ptp(triangles[:,:,1],axis=1)<1e-6)&(abs(y-.95)<1e-6)
    surface=unary_union([Polygon(t[:,[0,2]]) for t in triangles[select]])
    assert surface.buffer(1e-6).covers(box(*WORKTOP)), 'Appliance area must be on the actual countertop'
    height=float(y[select].mean())
    # The designated area is beyond the hob and sink, not just inside the assembly AABB.
    for p in parts:
        if 'kochfeld' in p['name']:
            pts=p['triangles'].reshape(-1,3)
            assert not box(*WORKTOP).intersects(box(pts[:,0].min(),pts[:,2].min(),pts[:,0].max(),pts[:,2].max()).buffer(.1))
    spec['supportSurfaces']=[dict(surfaceId='island-appliance-worktop',label='Island appliance worktop',
        localFrame=dict(origin=dict(x=0,y=height,z=0),normal=dict(x=0,y=1,z=0),
                        xAxis=dict(x=1,y=0,z=0),zAxis=dict(x=0,y=0,z=1)),
        bounds=dict(minimumX=WORKTOP[0],minimumZ=WORKTOP[1],maximumX=WORKTOP[2],maximumZ=WORKTOP[3]),
        allowedSides=['above'],evidenceStatus='derived')]
    return dict(height=height,sourceSha256=hashlib.sha256(raw).hexdigest(),bounds=WORKTOP,
                actualCountertopCoverage=True,hobExcluded=True)


def build(before,catalog):
    candidate=deepcopy(before)
    kitchen=next(p for p in candidate['placements'] if p['placementId']==KITCHEN_PLACEMENT)
    kitchen.update(assetId=KITCHEN,assetDefinitionRevision=catalog[KITCHEN]['assetDefinitionRevision'])
    height=catalog[KITCHEN]['supportSurfaces'][0]['localFrame']['origin']['y']
    for slug,x,z,yaw,color in ITEMS:
        aid='asset-breakroom-'+slug;pid='pl-breakroom-'+slug
        candidate['placements'].append(dict(placementId=pid,assetId=aid,
            assetDefinitionRevision=catalog[aid]['assetDefinitionRevision'],
            transform=transform(kitchen,x,z,yaw,height),positionMode='manual',appearance=dict(color=color),
            metadata=dict(instanceLabel=catalog[aid]['displayName'],inputMethod='independent-authoring'),
            snapRelationship=dict(family='surface_attachment',attachmentId='surface:'+pid,
                supportPlacementId=KITCHEN_PLACEMENT,surfaceId='island-appliance-worktop',
                surfaceSource='asset_definition',localPosition=dict(x=x,z=z),localRotationDegrees=yaw,
                normalOffsetMeters=0,side='above',evidenceStatus='derived')))
    fridge=catalog['asset-breakroom-refrigerator']
    # Align the front toward the kitchen access side, outside the original assembly footprint.
    anchor=dict(transform=dict(position=dict(x=329.8,y=0,z=58.4),quaternion=dict(x=0,y=0,z=0,w=1)))
    candidate['placements'].append(dict(placementId='pl-breakroom-refrigerator',assetId=fridge['assetId'],
        assetDefinitionRevision=fridge['assetDefinitionRevision'],transform=transform(anchor,0,0,-90),
        positionMode='manual',appearance=dict(color='#e4e8e7'),snapRelationship=None,
        metadata=dict(instanceLabel='Kitchen Refrigerator',inputMethod='independent-authoring')))
    return canonicalize_layout(candidate)


def audit(before,after):
    expected=deepcopy(before);actual=deepcopy(after)
    old=next(p for p in expected['placements'] if p['placementId']==KITCHEN_PLACEMENT)
    new=next(p for p in actual['placements'] if p['placementId']==KITCHEN_PLACEMENT)
    old.update(assetId=new['assetId'],assetDefinitionRevision=new['assetDefinitionRevision'])
    added=actual['placements'][len(expected['placements']):]
    assert len(added)==4 and len({p['assetId'] for p in added})==4
    assert {p['placementId'] for p in added}=={'pl-breakroom-'+k for k in ['coffee-pot','microwave','toaster','refrigerator']}
    actual['placements']=actual['placements'][:len(expected['placements'])]
    expected['updatedAt']=actual['updatedAt'];assert expected==actual,'Unrelated layout content changed'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--publish-catalog',action='store_true')
    parser.add_argument('--publish-layout',action='store_true')
    parser.add_argument('--native-report',type=Path)
    args=parser.parse_args();out=args.output.resolve();target=STORE/RELATIVE;manifest=ROOT/PRIVATE_ASSET_MANIFEST
    if args.publish_catalog or args.publish_layout:
        report=json.loads((out/'report.json').read_text())
        sources=json.loads((IMPORT/'before-hashes.json').read_text())['sources']
        for name,digest in sources.items():
            assert sha(Path.home()/'Downloads/more break stuff'/name)==digest,'Original CAD source changed'
        assert target.read_bytes()==(out/'before.json').read_bytes(),'Saved layout changed'
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
        entries=json.loads((IMPORT/'entries.json').read_text());old_ids={a['assetId'] for a in library['assets']}
        assert not old_ids.intersection({a['assetId'] for a in entries}|{KITCHEN})
        source_hashes=json.loads((IMPORT/'before-hashes.json').read_text())['sources']
        for entry in entries:
            target_dir=(ROOT/entry['artifact']).parent
            assert sha(target_dir/entry['source']['fileName'])==entry['source']['sha256']==source_hashes[entry['source']['fileName']]
            evidence=json.loads((target_dir/'thumbnail-evidence.json').read_text())
            assert evidence['passed'] and all(evidence['checks'].values())
            assert evidence['source']['sha256']==sha(ROOT/entry['artifact'])
        spec=deepcopy(next(a for a in library['assets'] if a['assetId']=='asset-kitchen-assembly'))
        spec.update(assetId=KITCHEN,displayName='Kitchen Assembly with Appliance Worktop')
        measured=measured_surface(spec)
        library['assets'].extend([*entries,spec]);library['summary']['total']=len(library['assets'])
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
                        layoutHashes=hashes(target.parent),measurement=measured,addedAppliances=4,
                        placements=len(candidate['placements']),existingPlacementGeometryUnchanged=True,
                        limitations=['Concept furnishing only; utilities, ventilation, support load and appliance operating clearances are not qualified.'],
                        sourceWarnings=json.loads((IMPORT/'source-warnings.json').read_text()))
        finally:host.close()
    write_json(out/'report.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='layoutHashes'}))


if __name__=='__main__':main()
