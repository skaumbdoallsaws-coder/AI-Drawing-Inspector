"""Stage, audit and revision-save table games without altering other gym areas."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from shutil import copytree
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from tools.import_private_gym_table_games import OUT, A, ITEMS, base
from tools.add_private_gym_games import surface, horizontal_geometry
from tools.add_private_gym_decorations import polygon, sha
from tools.build_private_gym import STORE, LAYOUT, write, saved_hashes
from tools.equip_factory02_cubicles import transform
from shapely.geometry import box
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import canonicalize_layout, layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST

P='pl-gym-table-games-'
POOL='pl-gym-games-pool'
TINY='pl-gym-wellness-tabletop-foosball'
PLINTH='pl-gym-wellness-tabletop-game-plinth'
COVERED='pl-gym-wellness-table-football'
CHAIRS=['pl-gym-wellness-game-chair-1','pl-gym-wellness-game-chair-2']
PLANT='pl-4583fc127fd8935eac67f7f6'


def decision():
    path=OUT/'decision.json'
    return json.loads(path.read_bytes()) if path.exists() else dict(replaceCovered=False)


def changes():
    replace=decision()['replaceCovered']
    return {TINY,PLINTH}|({COVERED} if replace else set()), {POOL,*CHAIRS}|(set() if replace else {PLANT})


def assets(library):
    entries=[json.loads((base.LIBRARY/('gym-table-games-'+k)/'catalog-entry.json').read_bytes()) for k,_,_ in ITEMS]
    original=next(a for a in library['assets'] if a['assetId']=='asset-gym-games-pool')
    s=surface('playing-surface','Measured billiards playing surface',-.85,.85,-.34,.34,.7450000047683716)
    assert horizontal_geometry(original,s['localFrame']['origin']['y']).covers(box(-.85,-.34,.85,.34))
    variant=deepcopy(original)
    variant.update(assetId=A+'pool-support',supportSurfaces=[s],displayName='APEX Pool Table - Accessory Support')
    variant['source']['supportedVariantOf']=original['assetId']
    entries.append(variant)
    assert not {a['assetId'] for a in entries}.intersection(a['assetId'] for a in library['assets'])
    library['assets'].extend(entries)
    library['summary']['total']=len(library['assets'])
    return entries


def change(before,catalog):
    result=deepcopy(before)
    removed,changed=changes()
    result['placements']=[p for p in result['placements'] if p['placementId'] not in removed]
    ps={p['placementId']:p for p in result['placements']}
    identity=dict(transform=dict(position=dict(x=0,y=0,z=0),quaternion=dict(x=0,y=0,z=0,w=1),scale=1))
    replace=decision()['replaceCovered']
    poses={'foosball':(11,-6,0) if replace else (9,-15.3,0),
           'blackjack':(9,-15.3,0) if replace else (20.35,-16.2,0),
           'organizer':(.95,-15.8,90)}
    for key,(x,z,angle) in poses.items():
        a=catalog[A+key]
        result['placements'].append(dict(placementId=P+key,assetId=a['assetId'],
            assetDefinitionRevision=a['assetDefinitionRevision'],positionMode='manual',
            snapRelationship=None,transform=transform(identity,x,z,angle,0),
            metadata=dict(instanceLabel=a['displayName'],inputMethod='independent-authoring')))
    chairs=[(8.3,-14.4,180),(9.7,-14.4,180)] if replace else [(19.7,-15.25,180),(21,-15.25,180)]
    for pid,(x,z,angle) in zip(CHAIRS,chairs):
        ps[pid]['transform']=transform(identity,x,z,angle,0)
    if not replace:
        ps[PLANT]['transform']=transform(identity,21.2,-12.6,0,0)
    a=catalog[A+'pool-support']
    ps[POOL].update({k:a[k] for k in ('assetId','assetDefinitionRevision')})
    a=catalog[A+'balls']
    result['placements'].append(dict(placementId=P+'balls',assetId=a['assetId'],assetDefinitionRevision=a['assetDefinitionRevision'],
        positionMode='manual',transform=transform(ps[POOL],0,0,0,.7450000047683716),
        snapRelationship=dict(family='surface_attachment',attachmentId='surface:'+P+'balls',supportPlacementId=POOL,
            surfaceId='playing-surface',surfaceSource='asset_definition',localPosition=dict(x=0,z=0),
            localRotationDegrees=0,normalOffsetMeters=0,side='above',evidenceStatus='derived'),
        metadata=dict(instanceLabel='15 Colored Pool Balls',inputMethod='independent-authoring')))
    return canonicalize_layout(result)


def audit(before,after,catalog):
    expected=change(before,catalog);expected['updatedAt']=after['updatedAt']
    assert after==expected,'Unrelated layout edits detected'
    old={p['placementId']:p for p in before['placements']}
    ps={p['placementId']:p for p in after['placements']}
    removed,changed=changes()
    assert old.keys()-ps.keys()==removed
    assert ps.keys()-old.keys()=={P+k for k,_,_ in ITEMS}
    assert all(old[k]==ps[k] for k in old if k not in removed|changed)
    pool=polygon(ps[POOL],catalog)
    cue=pool.envelope.buffer(1.45,join_style=2)
    main=box(5,-17.75,7,-3.1)
    tennis=box(12.6,-14.8,19.4,-8.8)
    arcade=box(12.25,-16.43,15.65,-14.85)
    added={P+k for k,_,_ in ITEMS}
    ground=(added|changed)-{POOL,P+'balls'}
    bounds={}
    for pid in ground:
        p=ps[pid];shape=polygon(p,catalog)
        assert box(.25,-17.75,21.75,-3.1).contains(shape),(pid,'Room boundary')
        assert all(shape.intersection(r).area<1e-6 for r in (cue,main,tennis,arcade)),(pid,'Playing or walking area blocked')
        for other,q in ps.items():
            if other==pid or q['transform']['position']['y']>1.4:
                continue
            assert shape.intersection(polygon(q,catalog)).area<1e-6,(pid,other,'Furniture overlap')
        bounds[pid]=list(shape.bounds)
    local=deepcopy(ps[P+'balls'])
    local['transform']=dict(position=dict(x=0,y=0,z=0),quaternion=dict(x=0,y=0,z=0,w=1),scale=1)
    assert box(-.85,-.34,.85,.34).contains(polygon(local,catalog))
    assert abs(ps[P+'balls']['transform']['position']['y']-.7450000047683716)<1e-6
    assert ps[P+'balls']['snapRelationship']['supportPlacementId']==POOL
    assert ps[POOL]['transform']==old[POOL]['transform']
    assert (ROOT/catalog[ps[POOL]['assetId']].get('artifact','generated/industrial_assets/local_library/gym-games-pool/model-display.glb')).exists()
    # Leave a standing allowance on both rod sides, separate from the main aisle.
    x,z=(11,-6) if decision()['replaceCovered'] else (9,-15.3)
    foos_allowance=box(x-.9,z-1.3,x+.9,z+1.3)
    for pid,p in ps.items():
        if pid!=P+'foosball' and p['transform']['position']['y']<1.4:
            assert foos_allowance.intersection(polygon(p,catalog)).area<1e-6,(pid,'Foosball approach obstructed')
    return dict(addedPlacements=sorted(added),removedPlacements=sorted(removed),changedPlacements=sorted(changed),
        untouchedPlacements=len(old)-len(removed|changed),footprints=bounds,ballCount=15,
        poolSurfaceHeightMeters=.7450000047683716,cueClearanceMeters=1.45,mainWalkwayMeters=2,
        replacementDecision=decision(),otherRoomsGeometryArtworkUnchanged=True,
        limitations='Conceptual furniture and playing clearances; not an installation or accessibility certification. STL ball units inferred as centimetres.')


def stage():
    target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json');manifest=ROOT/PRIVATE_ASSET_MANIFEST
    raw,original=target.read_bytes(),manifest.read_bytes()
    before,library=json.loads(raw),json.loads(original)
    for name,data in [('before.json',raw),('catalog-before.json',original)]:
        path=OUT/name
        if path.exists():assert path.read_bytes()==data,'Staging base changed'
        else:path.write_bytes(data)
    entries=assets(library);staged=OUT/'staged-project'
    write(staged/PRIVATE_ASSET_MANIFEST,library)
    store=OUT/'validation-store'
    for rel in ['authorities','layouts/local']:
        copytree(_native_fs_path(STORE/rel),_native_fs_path(store/rel),dirs_exist_ok=True)
    host=LocalFacilityLayoutHost(store,private_assets=True,private_asset_root=staged)
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        candidate=change(before,catalog);checks=audit(before,candidate,catalog)
        spatial=host.service._diagnose_spatial(host.principal(),'site-local',candidate)
        write(OUT/'spatial.json',spatial);host.service._require_spatially_valid(spatial)
        candidate=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))['layout']
        audit(before,candidate,catalog)
    finally:host.close()
    write(OUT/'candidate.json',candidate)
    write(OUT/'report.json',dict(status='validated',baseRevision=layout_revision(before),checks=checks,
        candidateSha256=sha(OUT/'candidate.json'),assetHashes={a['artifact']:sha(ROOT/a['artifact']) for a in entries},layoutHashes=saved_hashes()))
    byid={a['assetId']:a for a in library['assets']}
    fixture=deepcopy(candidate)
    fixture['placements']=[p for p in candidate['placements'] if 0<=p['transform']['position']['x']<=22 and -18<=p['transform']['position']['z']<=-3]
    ids={p['placementId'] for p in fixture['placements']};aids={p['assetId'] for p in fixture['placements']}
    finish=fixture['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']
    finish['fittedArtworks']=[a for a in finish['fittedArtworks'] if 'edge' in a['target'] or a['target'].get('placementId') in ids]
    finish['wallFaces']=[a for a in finish['wallFaces'] if a['placementId'] in ids]
    write(OUT/'render-fixtures.json',dict(room=dict(layout=fixture,catalog=[catalog[a] for a in sorted(aids)],
        artifacts={a:dict(url='/'+byid[a]['artifact'],sourceToCanonical=byid[a]['sourceToCanonical']) for a in aids})))
    print(json.dumps(checks),flush=True)


def save():
    report=json.loads((OUT/'report.json').read_bytes())
    for name in ['visual-review.json','browser-check.json']:
        proof=json.loads((OUT/name).read_bytes())
        assert proof['status']=='passed' and proof['candidateSha256']==sha(OUT/'candidate.json')
    target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json');manifest=ROOT/PRIVATE_ASSET_MANIFEST
    assert target.read_bytes()==(OUT/'before.json').read_bytes(),'Saved gym changed'
    assert manifest.read_bytes()==(OUT/'catalog-before.json').read_bytes(),'Library changed'
    for rel,digest in report['assetHashes'].items():assert sha(ROOT/rel)==digest
    RevisionedAuthorityRepository._atomic_write(manifest,(OUT/'staged-project'/PRIVATE_ASSET_MANIFEST).read_bytes())
    host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        before,candidate=(json.loads((OUT/name).read_bytes()) for name in ('before.json','candidate.json'))
        audit(before,candidate,catalog)
        receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,report['baseRevision'])
        audit(before,receipt['layout'],catalog)
    finally:host.close()
    assert json.loads(target.read_bytes())==receipt['layout']
    write(OUT/'saved.json',receipt['layout']);hashes=saved_hashes()
    assert all(hashes[k]==v for k,v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
    report.update(status='saved',savedRevision=receipt['revision'],otherLayoutsUnchanged=True)
    write(OUT/'report.json',report)
    print('Saved table-game additions and replacement',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['stage','save'])
    globals()[parser.parse_args().phase]()
