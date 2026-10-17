"""Publish a reviewed chair and replace only the middle recovery chair."""
import argparse
from copy import deepcopy
import json
from math import hypot, sqrt
from shutil import copytree
from tools.import_private_gym_massage_product import ROOT, OUT, SOURCE, TARGET, ASSET, base
from tools.apex_equipment_materials import unpack, pack, material
from tools.build_private_gym import STORE, LAYOUT, saved_hashes
from tools.add_private_gym_fitness_centre import footprint
from ai_inspector.facility_layout.authority_repository import _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST

APEX=ASSET+'-apex'
PLACEMENT='pl-gym-wellness-recovery-chair-2'


def theme():
    raw=(TARGET/'model.glb').read_bytes();doc,data=unpack(raw)
    original=deepcopy(doc)
    assert len(doc['meshes'])==1 and len(doc['meshes'][0]['primitives'])==5
    assert [p['material'] for p in doc['meshes'][0]['primitives']]==list(range(5))
    roles=['frame','upholstery','gold','frame','frame']
    doc['materials']=[material(role) for role in roles]
    doc['materials'][2]['pbrMetallicRoughness'].update(metallicFactor=.2,roughnessFactor=.45)
    expected=deepcopy(original);expected['materials']=doc['materials']
    assert doc==expected
    payload=pack(doc,data)
    assert unpack(payload)[1]==data
    dest=TARGET/'model-apex.glb'
    if dest.exists():assert dest.read_bytes()==payload
    else:dest.write_bytes(payload)
    entry=json.loads((TARGET/'catalog-entry.json').read_bytes())
    new=deepcopy(entry)
    new.update(assetId=APEX,artifact=dest.relative_to(ROOT).as_posix(),displayName='Massage Product Chair - APEX')
    new['source']['appearanceVariantOf']=ASSET
    new['description']+=' Graphite upholstery, black shell/base, gold side trim; original component geometry retained.'
    new['tags']+=['APEX','black and gold']
    base.write(TARGET/'catalog-entry-apex.json',new)
    base.write(OUT/'material-review.json',dict(geometryPreserved=True,binaryGeometryUnchanged=True,
        originalSha256=base.sha(TARGET/'model.glb'),apexSha256=base.sha(dest),materialRoles=roles))
    return entry,new


def change(before,catalog):
    candidate=deepcopy(before)
    p=next(p for p in candidate['placements'] if p['placementId']==PLACEMENT)
    assert p['assetId']=='asset-gym-wellness-massage-chair-apex'
    assert p['transform']['position']==dict(x=55.7,y=0,z=4.5)
    assert p['snapRelationship'] is None and p['transform']['scale']==1
    p.update({k:catalog[APEX][k] for k in ('assetId','assetDefinitionRevision')})
    # The STEP chair faces source +Y, or canonical -Z. Face it into the room (+X).
    p['transform']['quaternion']=dict(x=0,y=round(-sqrt(.5),9),z=0,w=round(sqrt(.5),9))
    p['metadata']['instanceLabel']='Massage Product Chair - Recovery Station 2'
    return candidate


def audit(before,after,catalog):
    expected=change(before,catalog);expected['updatedAt']=after['updatedAt']
    assert expected==after,'Unrelated layout content changed'
    p=next(p for p in after['placements'] if p['placementId']==PLACEMENT)
    bounds=footprint(p,catalog)
    assert 54.5<bounds[0]<bounds[2]<57 and 3.5<bounds[1]<bounds[3]<5.5
    gaps=[]
    for other in after['placements']:
        if other['placementId']==PLACEMENT or other.get('metadata',{}).get('room')!='recovery':continue
        box=footprint(other,catalog)
        distance=hypot(max(bounds[0]-box[2],box[0]-bounds[2],0),max(bounds[1]-box[3],box[1]-bounds[3],0))
        assert distance>1.2,('Recovery station clearance',other['placementId'],distance)
        gaps.append(dict(placementId=other['placementId'],gapMeters=distance))
    return dict(replacedPlacement=PLACEMENT,footprint=bounds,faces='positive_x_toward_central_aisle',
        otherPlacementsUnchanged=len(before['placements'])-1,remainingMassageChairs=2,massageTables=2,
        staticPoseOnly=True,recliningEnvelopeVerified=False,gaps=gaps)


def stage():
    entries=theme()
    path=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    raw=path.read_bytes();catalog_raw=(ROOT/PRIVATE_ASSET_MANIFEST).read_bytes()
    for name,data in [('before.json',raw),('catalog-before.json',catalog_raw)]:
        file=OUT/name
        if file.exists():assert file.read_bytes()==data,'Staged base changed'
        else:file.write_bytes(data)
    before,library=json.loads(raw),json.loads(catalog_raw)
    assert not {ASSET,APEX}.intersection(a['assetId'] for a in library['assets'])
    library['assets']+=list(entries);library['summary']['total']=len(library['assets'])
    staged=OUT/'staged-project';base.write(staged/PRIVATE_ASSET_MANIFEST,library)
    store=OUT/'validation-store'
    for rel in ['authorities','layouts/local']:
        copytree(_native_fs_path(STORE/rel),_native_fs_path(store/rel),dirs_exist_ok=True)
    host=LocalFacilityLayoutHost(store,private_assets=True,private_asset_root=staged)
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        candidate=change(before,catalog)
        spatial=host.service._diagnose_spatial(host.principal(),'site-local',candidate)
        base.write(OUT/'spatial.json',spatial);host.service._require_spatially_valid(spatial)
        candidate=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))['layout']
        checks=audit(before,candidate,catalog)
    finally:host.close()
    base.write(OUT/'candidate.json',candidate)
    base.write(OUT/'report.json',dict(status='validated',baseRevision=layout_revision(before),checks=checks,
        layoutHashes=saved_hashes(),sourceSha256=base.sha(SOURCE),artifactSha256=base.sha(TARGET/'model-apex.glb')))
    fixture=deepcopy(candidate)
    fixture['placements']=[p for p in candidate['placements'] if 54<=p['transform']['position']['x']<=60 and 0<=p['transform']['position']['z']<=10]
    finish=fixture['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']
    finish['fittedArtworks']=[];finish['wallFaces']=[]
    aids={p['assetId'] for p in fixture['placements']}
    assets={a['assetId']:a for a in library['assets'] if a['assetId'] in aids}
    base.write(OUT/'render-fixture.json',dict(layout=fixture,catalog=[catalog[a] for a in sorted(aids)],
        artifacts={aid:dict(url='/'+a['artifact'],sourceToCanonical=a['sourceToCanonical']) for aid,a in assets.items()}))
    print(json.dumps(checks))


def finish(phase):
    report=json.loads((OUT/'report.json').read_bytes())
    path=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    manifest=ROOT/PRIVATE_ASSET_MANIFEST
    assert path.read_bytes()==(OUT/'before.json').read_bytes(),'Saved gym changed'
    assert base.sha(SOURCE)==report['sourceSha256'] and base.sha(TARGET/'model-apex.glb')==report['artifactSha256']
    proof=json.loads((OUT/'visual-review.json').read_bytes())
    assert proof['status']=='passed' and proof['candidateSha256']==base.sha(OUT/'candidate.json')
    if phase=='publish':
        assert report['status']=='validated' and manifest.read_bytes()==(OUT/'catalog-before.json').read_bytes()
        base.write(manifest,json.loads((OUT/'staged-project'/PRIVATE_ASSET_MANIFEST).read_bytes()))
        report['status']='published'
    else:
        assert report['status']=='published' and manifest.read_bytes()==(OUT/'staged-project'/PRIVATE_ASSET_MANIFEST).read_bytes()
        host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
        try:
            catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
            before=json.loads((OUT/'before.json').read_bytes());candidate=json.loads((OUT/'candidate.json').read_bytes())
            audit(before,candidate,catalog)
            receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,report['baseRevision'])
            audit(before,receipt['layout'],catalog)
            assert json.loads(path.read_bytes())==receipt['layout']
        finally:host.close()
        base.write(OUT/'saved.json',receipt['layout'])
        hashes=saved_hashes()
        assert all(hashes[k]==v for k,v in report['layoutHashes'].items() if k not in (path.name,'registry.json'))
        report.update(status='saved',savedRevision=receipt['revision'],otherLayoutsUnchanged=True)
    base.write(OUT/'report.json',report);print(report['status'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['stage','publish','save'])
    args=parser.parse_args()
    stage() if args.phase=='stage' else finish(args.phase)
