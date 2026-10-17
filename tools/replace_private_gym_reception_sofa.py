"""Replace only the lion-wall reception sofa with the supplied living-room group."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from shutil import copytree
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT),str(ROOT/'tools'),str(Path.home()/'AppData/Roaming/Python/Python314/site-packages')]
from tools.import_private_gym_living_room import OUT, TARGET, ASSET
from tools.build_private_gym import LAYOUT, STORE, write, saved_hashes
from tools.add_private_gym_calisthenics import yaw
from tools.add_private_gym_fitness_centre import footprint
from ai_inspector.facility_layout.authority_repository import _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations

OLD = 'pl-gym-reception-lion-sofa'
NEW = 'pl-gym-reception-living-room-1'


def operations(before,catalog):
    old=next(p for p in before['placements'] if p['placementId']==OLD)
    assert old['assetId']=='asset-gym-wellness-sofa-apex'
    assert old['transform']['position']==dict(x=.7,y=0,z=7)
    assert not any(p['placementId']==NEW for p in before['placements'])
    zone=next(z for z in before['zones'] if z['label']=='Reception + Social Lounge')
    assert zone['boundary']==[dict(x=0,z=0),dict(x=12,z=0),dict(x=12,z=10),dict(x=0,z=10)]
    b=catalog[ASSET]['definition']['geometry']['aabb']
    x=round(.33-b['minimum']['z'],6)
    placement=dict(placementId=NEW,assetId=ASSET,assetDefinitionRevision=catalog[ASSET]['assetDefinitionRevision'],
        positionMode='manual',transform=dict(position=dict(x=x,y=0,z=7),quaternion=yaw(90),scale=1),
        snapRelationship=None,metadata=dict(instanceLabel='Living Room 1 - Lion Wall Reception',
            inputMethod='independent-authoring',room='reception',gymRole='amenity',
            scaleEvidence='Unitless STL provisionally interpreted as inches from sofa width and seat height'))
    return [dict(op='delete_placement',placementId=OLD),dict(op='place_asset',placement=placement)]


def audit(before,after,catalog):
    old={p['placementId']:p for p in before['placements']}
    new={p['placementId']:p for p in after['placements']}
    assert old.keys()-new.keys()=={OLD} and new.keys()-old.keys()=={NEW}
    assert all(new[pid]==p for pid,p in old.items() if pid!=OLD)
    expected=operations(before,catalog)[1]['placement']
    assert new[NEW]==expected
    a,b=deepcopy(before),deepcopy(after)
    for v in (a,b):
        v.pop('placements');v.pop('updatedAt')
    assert a==b,'Unrelated room, artwork, marking or route changed'
    bounds=footprint(new[NEW],catalog)
    x0,z0,x1,z1=bounds
    assert .32<x0<x1<3.5 and 4.5<z0<z1<9.5
    gaps=[]
    for p in new.values():
        pos=p['transform']['position']
        if p['placementId']==NEW or not (0<=pos['x']<12 and 0<=pos['z']<10):
            continue
        bx0,bz0,bx1,bz1=footprint(p,catalog)
        dx=max(x0-bx1,bx0-x1,0)
        dz=max(z0-bz1,bz0-z1,0)
        distance=(dx*dx+dz*dz)**.5
        assert distance>1.2,('Reception clearance reduced',p['placementId'],distance)
        gaps.append(dict(placementId=p['placementId'],boundingFootprintGapMeters=distance))
    return dict(removed=OLD,added=NEW,footprint=bounds,otherPlacementsUnchanged=len(old)-1,
        clearances=gaps,roomAndArtworkUnchanged=True,layoutExpansionRequired=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['stage','save'])
    phase=parser.parse_args().phase
    target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    if phase=='save':
        report=json.loads((OUT/'layout-report.json').read_bytes())
        assert target.read_bytes()==(OUT/'layout-before.json').read_bytes(),'Saved gym changed'
        raw=(OUT/'candidate.json').read_bytes()
        proof=json.loads((OUT/'layout-visual-review.json').read_bytes())
        assert proof['status']=='passed' and proof['candidateSha256']==hashlib.sha256(raw).hexdigest()
        entry=json.loads((TARGET/'catalog-entry.json').read_bytes())
        published=json.loads((ROOT/PRIVATE_ASSET_MANIFEST).read_bytes())
        assert next(a for a in published['assets'] if a['assetId']==ASSET)==entry
        host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
        try:
            catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
            before=json.loads((OUT/'layout-before.json').read_bytes())
            audit(before,json.loads(raw),catalog)
            receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,json.loads(raw),report['baseRevision'])
            audit(before,receipt['layout'],catalog)
            assert json.loads(target.read_bytes())==receipt['layout']
        finally:
            host.close()
        write(OUT/'saved.json',receipt['layout'])
        hashes=saved_hashes()
        assert all(hashes[k]==v for k,v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
        report.update(status='saved',savedRevision=receipt['revision'],otherLayoutsUnchanged=True)
        write(OUT/'layout-report.json',report)
        print('saved')
        return
    before=json.loads(target.read_bytes())
    backup=OUT/'layout-before.json'
    if backup.exists():
        assert backup.read_bytes()==target.read_bytes()
    else:
        backup.write_bytes(target.read_bytes())
    entry=json.loads((TARGET/'catalog-entry.json').read_bytes())
    library=json.loads((ROOT/PRIVATE_ASSET_MANIFEST).read_bytes())
    assert not any(a['assetId']==ASSET for a in library['assets'])
    library['assets'].append(entry)
    library['summary']['total']=len(library['assets'])
    staged=OUT/'staged-project'
    write(staged/PRIVATE_ASSET_MANIFEST,library)
    stage=OUT/'validation-store'
    for rel in ['authorities','layouts/local']:
        copytree(_native_fs_path(STORE/rel),_native_fs_path(stage/rel),dirs_exist_ok=True)
    host=LocalFacilityLayoutHost(stage,private_assets=True,private_asset_root=staged)
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        ops=operations(before,catalog)
        candidate=apply_facility_layout_operations(before,ops,updated_at=datetime.now(timezone.utc).isoformat())['document']
        checks=audit(before,candidate,catalog)
        spatial=host.service._diagnose_spatial(host.principal(),'site-local',candidate)
        write(OUT/'spatial.json',spatial)
        host.service._require_spatially_valid(spatial)
        receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))
        candidate=receipt['layout']
        audit(before,candidate,catalog)
    finally:
        host.close()
    write(OUT/'candidate.json',candidate)
    write(OUT/'layout-report.json',dict(status='validated',baseRevision=layout_revision(before),checks=checks,
        layoutHashes=saved_hashes(),artifactSha256=hashlib.sha256((ROOT/entry['artifact']).read_bytes()).hexdigest()))
    fixture=deepcopy(candidate)
    fixture['placements']=[p for p in candidate['placements'] if 0<=p['transform']['position']['x']<12 and 0<=p['transform']['position']['z']<10]
    aids={p['assetId'] for p in fixture['placements']}
    entries={a['assetId']:a for a in library['assets'] if a['assetId'] in aids}
    write(OUT/'render-fixture.json',dict(layout=fixture,catalog=[catalog[a] for a in sorted(aids)],
        artifacts={a:dict(url='/'+e['artifact'],sourceToCanonical=e['sourceToCanonical']) for a,e in entries.items()}))
    print(json.dumps(checks))


if __name__=='__main__':
    main()
