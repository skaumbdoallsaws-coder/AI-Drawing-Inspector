"""Stage two native-scale appliance replacements and one wall-bound kitchen mural."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from shutil import copytree
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from tools.import_private_gym_kitchen_refresh import OUT,SOURCE,ITEMS,base
from tools.apex_equipment_materials import np
from PIL import Image
from shapely.geometry import box
from tools.add_private_gym_decorations import polygon,sha
from tools.add_private_gym_outdoor_art import alpha_uv
from tools.build_private_gym import STORE,LAYOUT,write,saved_hashes
from tools.equip_factory02_cubicles import transform
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository,_native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision,canonicalize_layout
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost,PRIVATE_ASSET_MANIFEST

COFFEE='pl-gym-wellness-coffee-pot'
GRILL='pl-gym-patio-barbecue-grill'
KITCHEN='pl-gym-wellness-kitchen-assembly'
WALL='pl-gym-wellness-meeting-cafe-divider'
ART='kitchen-salt-bae'
PREFIX='asset-gym-kitchen-refresh-'


def prepare_art(before,catalog):
    source=SOURCE/'Salt Bae Sprinkling Salt Over Steak.png';raw=source.read_bytes();digest=sha(source)
    with Image.open(source) as im:uv,bounds=alpha_uv(im);pixels=list(im.size)
    wall=next(p for p in before['placements'] if p['placementId']==WALL)
    assert wall['transform']['quaternion']==dict(x=0,y=0,z=0,w=1)
    assert catalog[wall['assetId']]['assetDefinitionRevision']==wall['assetDefinitionRevision']
    relative='generated/facility-wall-art/'+digest+'.png'
    dest=OUT/'staged-project'/relative;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
    record=dict(artworkId=ART,imagePath='/'+relative,uv=uv,
        target=dict(placementId=WALL,face='negative_z'),region=[.10,.10,.90,.96],coverage=1)
    evidence=dict(artifact=relative,sha256=digest,alphaBounds=list(bounds),pixels=pixels,originalImageUnmodified=True)
    return record,evidence


def change(before,catalog,record):
    result=deepcopy(before);ps={p['placementId']:p for p in result['placements']}
    coffee,grill=ps[COFFEE],ps[GRILL]
    assert coffee['assetId']=='asset-breakroom-coffee-pot'
    assert grill['assetId']=='asset-gym-patio-grill-apex-patio'
    for p,key in [(coffee,'espresso'),(grill,'grill')]:
        p.update({k:catalog[PREFIX+key][k] for k in ('assetId','assetDefinitionRevision')})
        p.pop('appearance',None)
    coffee['metadata']['instanceLabel']='Espresso Machine'
    grill['metadata']['instanceLabel']='APEX Patio Grill'
    grill['transform']['quaternion']=dict(x=0,y=0,z=0,w=1)
    surface=next(s for s in catalog[ps[KITCHEN]['assetId']]['supportSurfaces'] if s['surfaceId']=='island-appliance-worktop')
    b=surface['bounds'];a=catalog[coffee['assetId']]['definition']['geometry']['aabb']
    depth=a['maximum']['z']-a['minimum']['z'];width=a['maximum']['x']-a['minimum']['x']
    xlo,xhi=b['minimumX']+depth/2+.015,b['maximumX']-depth/2-.015
    zlo,zhi=b['minimumZ']+width/2+.015,b['maximumZ']-width/2-.015
    assert xlo<=xhi and zlo<=zhi,'Espresso machine does not fit the supported worktop at native scale'
    old=deepcopy(coffee['snapRelationship']['localPosition']);options=[]
    microwave=polygon(ps['pl-gym-wellness-microwave'],catalog)
    for x in np.linspace(xlo,xhi,25):
        for z in np.linspace(zlo,zhi,45):
            coffee['transform']=transform(ps[KITCHEN],float(x),float(z),90,surface['localFrame']['origin']['y'])
            if polygon(coffee,catalog).distance(microwave)>=.035:
                options.append(((x-old['x'])**2+(z-old['z'])**2,float(x),float(z)))
    assert options,'Espresso machine and microwave cannot share the reviewed worktop'
    _,x,z=min(options)
    coffee['transform']=transform(ps[KITCHEN],x,z,90,surface['localFrame']['origin']['y'])
    coffee['transform']['quaternion']={k:round(v,9) for k,v in coffee['transform']['quaternion'].items()}
    coffee['snapRelationship'].update(localPosition=dict(x=x,z=z),localRotationDegrees=90)
    art=result['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish'].setdefault('fittedArtworks',[])
    assert not any(a['artworkId']==ART for a in art)
    art.append(record)
    return canonicalize_layout(result)


def audit(before,after,catalog,record):
    expected=change(before,catalog,record);expected['updatedAt']=after['updatedAt']
    assert after==expected,'Unexpected edits beyond the coffee maker, grill and kitchen mural'
    old={p['placementId']:p for p in before['placements']};new={p['placementId']:p for p in after['placements']}
    assert set(old)==set(new) and all(old[k]==new[k] for k in old if k not in (COFFEE,GRILL))
    assert all(new[k]['transform']['scale']==1 for k in (COFFEE,GRILL))
    coffee=new[COFFEE];r=coffee['snapRelationship'];a=catalog[coffee['assetId']]['definition']['geometry']['aabb']
    s=next(s for s in catalog[new[KITCHEN]['assetId']]['supportSurfaces'] if s['surfaceId']==r['surfaceId'])
    b=s['bounds'];x,z=r['localPosition']['x'],r['localPosition']['z']
    half_d=(a['maximum']['z']-a['minimum']['z'])/2;half_w=(a['maximum']['x']-a['minimum']['x'])/2
    assert b['minimumX']<x-half_d<x+half_d<b['maximumX']
    assert b['minimumZ']<z-half_w<z+half_w<b['maximumZ']
    gap=polygon(coffee,catalog).distance(polygon(new['pl-gym-wellness-microwave'],catalog));assert gap>=.035-1e-7
    assert abs(coffee['transform']['position']['y']-s['localFrame']['origin']['y'])<1e-7
    grill=polygon(new[GRILL],catalog);assert box(68,62,82,72).contains(grill)
    gaps=[]
    for p in after['placements']:
        pos=p['transform']['position']
        if p['placementId']==GRILL or not(68<=pos['x']<=82 and 62<=pos['z']<=72) or pos['y']!=0:continue
        distance=grill.distance(polygon(p,catalog));assert distance>.6,(p['placementId'],distance)
        gaps.append(dict(placementId=p['placementId'],gapMeters=distance))
    assert new[GRILL]['transform']['position']==old[GRILL]['transform']['position']
    return dict(replacedPlacements=[COFFEE,GRILL],preservedPlacements=len(old)-2,addedArtworks=1,
        nativeScalePreserved=True,microwaveGapMeters=gap,worktopAttachmentPreserved=True,
        grillFaces='positive_z_toward_patio',grillFootprint=list(grill.bounds),patioFurnitureGaps=gaps,
        geometryAndExistingArtUnchanged=True)


def stage():
    target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json');manifest=ROOT/PRIVATE_ASSET_MANIFEST
    raw,original=target.read_bytes(),manifest.read_bytes();before,library=json.loads(raw),json.loads(original)
    for name,data in [('before.json',raw),('catalog-before.json',original)]:
        path=OUT/name
        if path.exists():assert path.read_bytes()==data,'Staging base changed'
        else:path.write_bytes(data)
    entries=[json.loads((base.LIBRARY/('gym-kitchen-refresh-'+key)/'catalog-entry.json').read_bytes()) for key,_,_ in ITEMS]
    assert not {a['assetId'] for a in entries}.intersection(a['assetId'] for a in library['assets'])
    library['assets'].extend(entries);library['summary']['total']=len(library['assets'])
    staged=OUT/'staged-project';write(staged/PRIVATE_ASSET_MANIFEST,library)
    store=OUT/'validation-store'
    for rel in ['authorities','layouts/local']:copytree(_native_fs_path(STORE/rel),_native_fs_path(store/rel),dirs_exist_ok=True)
    host=LocalFacilityLayoutHost(store,private_assets=True,private_asset_root=staged)
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        record,source=prepare_art(before,catalog);candidate=change(before,catalog,record)
        checks=audit(before,candidate,catalog,record)
        spatial=host.service._diagnose_spatial(host.principal(),'site-local',candidate)
        write(OUT/'spatial.json',spatial);host.service._require_spatially_valid(spatial)
        candidate=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))['layout']
        audit(before,candidate,catalog,record)
    finally:host.close()
    write(OUT/'candidate.json',candidate)
    write(OUT/'report.json',dict(status='validated',baseRevision=layout_revision(before),checks=checks,record=record,source=source,
        assetHashes={e['artifact']:sha(ROOT/e['artifact']) for e in entries},layoutHashes=saved_hashes()))
    fixture=deepcopy(candidate)
    fixture['placements']=[p for p in candidate['placements'] if (21<=p['transform']['position']['x']<=36 and -18<=p['transform']['position']['z']<=-10) or (68<=p['transform']['position']['x']<=82 and 62<=p['transform']['position']['z']<=72)]
    finish=fixture['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']
    finish['fittedArtworks']=[record];finish['artworks']=[];finish['wallFaces']=[]
    aids={p['assetId'] for p in fixture['placements']};assets={a['assetId']:a for a in library['assets'] if a['assetId'] in aids}
    write(OUT/'render-fixture.json',dict(layout=fixture,catalog=[catalog[a] for a in sorted(aids)],
        artifacts={a:dict(url='/'+e['artifact'],sourceToCanonical=e['sourceToCanonical']) for a,e in assets.items()}))
    print(json.dumps(checks),flush=True)


def save():
    report=json.loads((OUT/'report.json').read_bytes())
    for name in ['visual-review.json','browser-check.json']:
        proof=json.loads((OUT/name).read_bytes());assert proof['status']=='passed' and proof['candidateSha256']==sha(OUT/'candidate.json')
    target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json');manifest=ROOT/PRIVATE_ASSET_MANIFEST
    assert target.read_bytes()==(OUT/'before.json').read_bytes(),'Saved gym changed'
    assert manifest.read_bytes()==(OUT/'catalog-before.json').read_bytes(),'Library changed'
    for rel,digest in report['assetHashes'].items():assert sha(ROOT/rel)==digest
    s=report['source'];image=OUT/'staged-project'/s['artifact'];assert sha(image)==s['sha256']
    RevisionedAuthorityRepository._atomic_write(ROOT/s['artifact'],image.read_bytes())
    RevisionedAuthorityRepository._atomic_write(manifest,(OUT/'staged-project'/PRIVATE_ASSET_MANIFEST).read_bytes())
    host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        before=json.loads((OUT/'before.json').read_bytes());candidate=json.loads((OUT/'candidate.json').read_bytes())
        audit(before,candidate,catalog,report['record'])
        receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,report['baseRevision'])
        audit(before,receipt['layout'],catalog,report['record'])
    finally:host.close()
    write(OUT/'saved.json',receipt['layout']);hashes=saved_hashes()
    assert all(hashes[k]==v for k,v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
    report.update(status='saved',savedRevision=receipt['revision'],otherLayoutsUnchanged=True)
    write(OUT/'report.json',report);print('saved',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('phase',choices=['stage','save'])
    stage() if parser.parse_args().phase=='stage' else save()
