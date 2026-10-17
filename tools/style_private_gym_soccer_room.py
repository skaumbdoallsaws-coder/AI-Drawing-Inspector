"""Unify inward soccer wall finishes and enlarge the existing wall-bound graphics."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from shutil import copytree
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.apex_equipment_materials import np
from PIL import Image
from tools.add_private_gym_outdoor_art import alpha_uv
from tools.build_private_gym import STORE, LAYOUT, write, saved_hashes
from tools.update_private_gym_kitchen_soccer import SPECS, PREFIX, sha
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations

OUT=ROOT/'.runtime/private-gym-soccer-finish-20261011'
COLOR='#444e52'
FACES={PREFIX+'south-west':'positive_z',PREFIX+'south-east':'positive_z',
       PREFIX+'west':'positive_z',PREFIX+'east-south':'negative_z',PREFIX+'east-north':'negative_z'}
ART_IDS={s['id'] for s in SPECS}


def settings_for(before, replacement=None):
    settings=deepcopy(before['extensions']['facilityPerimeterWalls']['settings'])
    finish=settings['exteriorFinish'];placements={p['placementId']:p for p in before['placements']}
    for pid,face in FACES.items():
        matching=[f for f in finish['wallFaces'] if f['placementId']==pid and f['face']==face]
        assert len(matching)<=1
        record=dict(placementId=pid,face=face,assetDefinitionRevision=placements[pid]['assetDefinitionRevision'],color=COLOR)
        if matching:
            assert matching[0]['assetDefinitionRevision']==record['assetDefinitionRevision']
            matching[0].update(record)
        else:finish['wallFaces'].append(record)
    arts={a['artworkId']:a for a in finish['fittedArtworks']}
    assert ART_IDS <= arts.keys()
    for aid in ART_IDS:
        a=arts[aid]
        a['region'][1]=.02 if aid!='soccer-speed-discipline' else 0
        a['region'][3]=.98 if aid!='soccer-speed-discipline' else 1
        a['coverage']=1
    arts['soccer-speed-discipline']['region']=[0,0,1,1]
    if replacement:
        arts['soccer-speed-discipline'].update(imagePath=replacement['imagePath'],uv=replacement['uv'])
    return settings


def audit(before,after,replacement=None):
    expected=deepcopy(before)
    expected['extensions']['facilityPerimeterWalls']['settings']=settings_for(before,replacement)
    expected['updatedAt']=after['updatedAt']
    assert expected==after,'Unexpected change beyond the five inward finishes and three soccer graphics'
    assert before['placements']==after['placements']
    return dict(interiorFacesPainted=len(FACES),color=COLOR,placementsUnchanged=len(before['placements']),
        heroWallAndBrandingUnchanged=True,outdoorFacesUnchanged=True,courtAndOpeningsUnchanged=True,
        goalGraphicsHeightMeters=6.2*.96,goalGraphicsCenteredAtHeightMeters=3.1,
        goalGraphicLinearEnlargement=6.2*.96/3.82,proportionsPreserved=True)


def stage(mural=None):
    OUT.mkdir(parents=True,exist_ok=True)
    target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    raw=target.read_bytes();before=json.loads(raw)
    for name,data in [('before.json',raw),('catalog-before.json',(ROOT/PRIVATE_ASSET_MANIFEST).read_bytes())]:
        p=OUT/name
        if p.exists():assert p.read_bytes()==data,'Staging base changed'
        else:p.write_bytes(data)
    replacement=None
    if mural:
        source=Path(mural);digest=sha(source)
        with Image.open(source) as im:
            uv,box=alpha_uv(im)
        assert abs((box[2]-box[0])/(box[3]-box[1])-28.5/6.2)<.12,'Wide mural must fit the wall without distortion'
        replacement=dict(imagePath='/generated/facility-wall-art/'+digest+'.png',uv=uv,source=str(source))
    settings=settings_for(before,replacement)
    sources=[]
    for art in settings['exteriorFinish']['fittedArtworks']:
        if art['artworkId'] not in ART_IDS:continue
        rel=art['imagePath'].lstrip('/')
        source=Path(mural) if mural and art['artworkId']=='soccer-speed-discipline' else ROOT/rel
        raw_image=source.read_bytes()
        with Image.open(source) as im:
            _,box=alpha_uv(im);pixels=list(im.size)
        dest=OUT/'staged-project'/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw_image)
        sources.append(dict(artworkId=art['artworkId'],artifact=rel,sha256=sha(source),originalPixels=pixels,
                            alphaBounds=list(box),source=str(source)))
    candidate=apply_facility_layout_operations(before,[dict(op='set_perimeter_walls',wallSettings=settings)])['document']
    stage=OUT/'validation-store'
    for folder in ['authorities','layouts/local']:
        copytree(_native_fs_path(STORE/folder),_native_fs_path(stage/folder),dirs_exist_ok=True)
    host=LocalFacilityLayoutHost(stage,private_assets=True,private_asset_root=ROOT)
    try:
        catalog=host.authoritative_asset_catalog()
        spatial=host.service._diagnose_spatial(host.principal(),'site-local',candidate)
        write(OUT/'spatial.json',spatial);host.service._require_spatially_valid(spatial)
        candidate=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))['layout']
        checks=audit(before,candidate,replacement)
    finally:host.close()
    write(OUT/'candidate.json',candidate)
    write(OUT/'report.json',dict(status='validated',baseRevision=layout_revision(before),checks=checks,
        replacement=replacement,sources=sources,layoutHashes=saved_hashes()))
    fixture=deepcopy(candidate)
    fixture['placements']=[p for p in candidate['placements'] if p['placementId'].startswith(PREFIX)
        and p['transform']['position']['x']<43]
    finish=fixture['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']
    finish['fittedArtworks']=[a for a in finish['fittedArtworks'] if a['artworkId'] in ART_IDS]
    finish['artworks']=[]
    finish['wallFaces']=[f for f in finish['wallFaces'] if f['placementId'] in FACES]
    aids={p['assetId'] for p in fixture['placements']}
    library={a['assetId']:a for a in json.loads((ROOT/PRIVATE_ASSET_MANIFEST).read_bytes())['assets']}
    write(OUT/'render-fixture.json',dict(layout=fixture,catalog=[a for a in catalog if a['assetId'] in aids],
        artifacts={a:dict(url='/'+library[a]['artifact'],sourceToCanonical=library[a]['sourceToCanonical']) for a in aids},
        ids=[s['id'] for s in SPECS],sources=sources))
    print(json.dumps(checks))


def save():
    report=json.loads((OUT/'report.json').read_bytes())
    proof=json.loads((OUT/'visual-review.json').read_bytes())
    assert proof['status']=='passed' and proof['candidateSha256']==sha(OUT/'candidate.json')
    target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    assert target.read_bytes()==(OUT/'before.json').read_bytes(),'Saved gym changed'
    assert (ROOT/PRIVATE_ASSET_MANIFEST).read_bytes()==(OUT/'catalog-before.json').read_bytes()
    for s in report['sources']:
        src=OUT/'staged-project'/s['artifact'];dest=ROOT/s['artifact']
        assert sha(src)==s['sha256']
        if dest.exists():assert sha(dest)==s['sha256']
        else:RevisionedAuthorityRepository._atomic_write(dest,src.read_bytes())
    before=json.loads((OUT/'before.json').read_bytes());candidate=json.loads((OUT/'candidate.json').read_bytes())
    audit(before,candidate,report['replacement'])
    host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
    try:
        receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,report['baseRevision'])
        audit(before,receipt['layout'],report['replacement'])
    finally:host.close()
    write(OUT/'saved.json',receipt['layout'])
    hashes=saved_hashes()
    assert all(hashes[k]==v for k,v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
    report.update(status='saved',savedRevision=receipt['revision'],otherLayoutsUnchanged=True)
    write(OUT/'report.json',report);print('saved')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('phase',choices=['stage','save'])
    parser.add_argument('--mural');args=parser.parse_args()
    stage(args.mural) if args.phase=='stage' else save()
