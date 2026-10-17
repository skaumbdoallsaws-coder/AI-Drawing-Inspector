"""Move the lounge TV and seating together to the owner's requested right corner."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from shutil import copytree
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.apex_equipment_materials import np
from tools.build_private_gym import STORE, LAYOUT, write, saved_hashes
from tools.import_additional_gym_assets import sha
from tools.add_private_gym_fitness_centre import footprint
from ai_inspector.facility_layout.authority_repository import _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations

OUT=ROOT/'.runtime/private-gym-lounge-right-corner-20261010'
SEATING='pl-gym-gaming-living-room-1'
TV='pl-gym-gaming-complete-tv-unit'
MOVED={SEATING,TV}
EAST='pl-gym-wellness-lounge-east-upper'
BACK='pl-gym-wellness-lounge-north-right'


def change(before,catalog):
    placements={p['placementId']:p for p in before['placements']}
    right=footprint(placements[EAST],catalog)[0]
    current=footprint(placements[SEATING],catalog)[2]
    delta=math.floor((right-1.4-current)*100)/100
    assert delta>10, 'Seating is not in its reviewed starting corner'
    ops=[]
    for pid in sorted(MOVED):
        p=placements[pid]
        assert p['positionMode']=='manual' and p['snapRelationship'] is None
        position=deepcopy(p['transform']['position'])
        position['x']=round(position['x']+delta,6)
        ops.append(dict(op='move_placement',placementId=pid,position=position))
    return apply_facility_layout_operations(before,ops,updated_at=datetime.now(timezone.utc).isoformat())['document']


def gap(a,b):
    return math.hypot(max(a[0]-b[2],b[0]-a[2],0),max(a[1]-b[3],b[1]-a[3],0))


def audit(before,after,catalog):
    expected=change(before,catalog);expected['updatedAt']=after['updatedAt']
    assert expected==after, 'Unexpected change outside the two requested furniture placements'
    old={p['placementId']:p for p in before['placements']}
    new={p['placementId']:p for p in after['placements']}
    shift=[new[pid]['transform']['position']['x']-old[pid]['transform']['position']['x'] for pid in sorted(MOVED)]
    assert abs(shift[0]-shift[1])<1e-9
    bounds={pid:footprint(new[pid],catalog) for pid in MOVED}
    east=footprint(new[EAST],catalog);back=footprint(new[BACK],catalog)
    assert east[0]-bounds[SEATING][2]>=1.4
    assert back[0]<bounds[TV][0]<bounds[TV][2]<back[2]
    assert abs(back[1]-bounds[TV][3]-.04)<1e-5
    assert gap(bounds[SEATING],bounds[TV])>1.3
    clearances=[]
    for p in after['placements']:
        pos=p['transform']['position']
        if p['placementId'] in MOVED or pos['y']!=0 or p.get('metadata',{}).get('room')!='lounge':
            continue
        box=footprint(p,catalog)
        distance=min(gap(box,b) for b in bounds.values())
        assert distance>.5, ('Furniture clearance',p['placementId'],distance)
        clearances.append(dict(placementId=p['placementId'],gapMeters=distance))
    return dict(moved=sorted(MOVED),translationXMeters=shift[0],footprints=bounds,
        eastWalkwayMeters=east[0]-bounds[SEATING][2],tvWallGapMeters=back[1]-bounds[TV][3],
        preservedSeatingToTVGapMeters=gap(bounds[SEATING],bounds[TV]),clearances=clearances,
        otherPlacementsUnchanged=len(before['placements'])-2,geometryAndFinishesUnchanged=True)


def stage():
    OUT.mkdir(parents=True,exist_ok=True)
    target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    raw=target.read_bytes();before=json.loads(raw)
    base=OUT/'before.json'
    if base.exists():assert base.read_bytes()==raw,'Staged base changed'
    else:base.write_bytes(raw)
    store=OUT/'validation-store'
    for rel in ['authorities','layouts/local']:
        copytree(_native_fs_path(STORE/rel),_native_fs_path(store/rel),dirs_exist_ok=True)
    host=LocalFacilityLayoutHost(store,private_assets=True,private_asset_root=ROOT)
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        candidate=change(before,catalog)
        spatial=host.service._diagnose_spatial(host.principal(),'site-local',candidate)
        write(OUT/'spatial.json',spatial);host.service._require_spatially_valid(spatial)
        candidate=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))['layout']
        checks=audit(before,candidate,catalog)
    finally:host.close()
    write(OUT/'candidate.json',candidate)
    write(OUT/'report.json',dict(status='validated',baseRevision=layout_revision(before),checks=checks,
        layoutHashes=saved_hashes(),catalogHash=sha(ROOT/PRIVATE_ASSET_MANIFEST)))
    fixture=deepcopy(candidate)
    fixture['placements']=[p for p in candidate['placements'] if 0<=p['transform']['position']['x']<=22 and -18<=p['transform']['position']['z']<=-3]
    finish=fixture['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']
    finish['fittedArtworks']=[];finish['wallFaces']=[]
    aids={p['assetId'] for p in fixture['placements']}
    library=json.loads((ROOT/PRIVATE_ASSET_MANIFEST).read_bytes())
    entries={a['assetId']:a for a in library['assets'] if a['assetId'] in aids}
    write(OUT/'render-fixture.json',dict(layout=fixture,catalog=[catalog[a] for a in sorted(aids)],
        artifacts={aid:dict(url='/'+a['artifact'],sourceToCanonical=a['sourceToCanonical']) for aid,a in entries.items()}))
    print(json.dumps(checks))


def save():
    report=json.loads((OUT/'report.json').read_bytes())
    assert report['status']=='validated'
    assert sha(ROOT/PRIVATE_ASSET_MANIFEST)==report['catalogHash']
    proof=json.loads((OUT/'visual-review.json').read_bytes())
    assert proof['status']=='passed' and proof['candidateSha256']==sha(OUT/'candidate.json')
    target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    assert target.read_bytes()==(OUT/'before.json').read_bytes(),'Saved gym changed'
    host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        before=json.loads((OUT/'before.json').read_bytes());candidate=json.loads((OUT/'candidate.json').read_bytes())
        audit(before,candidate,catalog)
        receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,report['baseRevision'])
        audit(before,receipt['layout'],catalog)
        assert json.loads(target.read_bytes())==receipt['layout']
    finally:host.close()
    write(OUT/'saved.json',receipt['layout'])
    hashes=saved_hashes()
    assert all(hashes[k]==v for k,v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
    report.update(status='saved',savedRevision=receipt['revision'],otherLayoutsUnchanged=True)
    write(OUT/'report.json',report)
    print('saved')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['stage','save'])
    args=parser.parse_args()
    stage() if args.phase=='stage' else save()
