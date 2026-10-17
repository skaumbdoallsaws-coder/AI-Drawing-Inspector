"""Stage the kitchen rotation and three wall-bound soccer artworks without other edits."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from shutil import copytree
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.apex_equipment_materials import np
from PIL import Image
from tools.add_private_gym_outdoor_art import alpha_uv
from tools.add_private_gym_fitness_centre import footprint
from tools.build_private_gym import STORE, LAYOUT, write, saved_hashes
from tools.equip_factory02_cubicles import transform
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations

OUT = ROOT/'.runtime/private-gym-kitchen-soccer-20261011'
KITCHEN = 'pl-gym-wellness-kitchen-assembly'
MOVED = {KITCHEN, 'pl-gym-wellness-coffee-pot', 'pl-gym-wellness-microwave'}
PREFIX = 'pl-private-gym-fields-'
SPECS = [
    dict(id='soccer-speed-discipline', file='ChatGPT Image Oct 11, 2026, 03_02_22 PM-1.png',
         wall=PREFIX+'south-west', face='positive_z'),
    dict(id='soccer-train-champion', file='ChatGPT Image Oct 11, 2026, 03_02_23 PM-2.png',
         wall=PREFIX+'west', face='positive_z', goal=PREFIX+'west-match-goal'),
    dict(id='soccer-play-belong', file='ChatGPT Image Oct 11, 2026, 03_02_24 PM-3.png',
         wall=PREFIX+'east-north', face='negative_z', goal=PREFIX+'east-match-goal'),
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(before, catalog):
    placements = {p['placementId']: p for p in before['placements']}
    records, sources = [], []
    for spec in SPECS:
        source = Path.home()/'Downloads'/spec['file']
        raw = source.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        rel = 'generated/facility-wall-art/'+digest+'.png'
        with Image.open(source) as im:
            uv, box = alpha_uv(im)
            pixels = list(im.size)
        wall = placements[spec['wall']]
        entry = catalog[wall['assetId']]
        assert entry['assetDefinitionRevision'] == wall['assetDefinitionRevision']
        b = entry['definition']['geometry']['aabb']
        width, height = b['maximum']['x']-b['minimum']['x'], b['maximum']['y']-b['minimum']['y']
        assert wall['transform']['scale'] == 1
        if 'goal' in spec:
            goal = placements[spec['goal']]
            # The two end walls are rotated +90 degrees: local X points toward world -Z.
            assert wall['transform']['quaternion'] == dict(x=0,y=.707106781,z=0,w=.707106781)
            center = wall['transform']['position']['z']-goal['transform']['position']['z']
            gh = catalog[goal['assetId']]['definition']['geometry']['aabb']['maximum']['y']
            bottom = goal['transform']['position']['y']+gh+.15
            region = [(center-6-b['minimum']['x'])/width, bottom/height,
                      (center+6-b['minimum']['x'])/width, (height-.15)/height]
        else:
            region = [.02, .03, .98, .97]
        assert 0 <= region[0] < region[2] <= 1 and 0 <= region[1] < region[3] <= 1
        dest = OUT/'staged-project'/rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        records.append(dict(artworkId=spec['id'], imagePath='/'+rel, uv=uv,
            target=dict(placementId=spec['wall'], face=spec['face']), region=region, coverage=1))
        sources.append(dict(artworkId=spec['id'], file=spec['file'], artifact=rel, sha256=digest,
            originalPixels=pixels, alphaBounds=list(box), originalImageUnmodified=True))
    return records, sources


def change(before, catalog, records):
    by_id = {p['placementId']: p for p in before['placements']}
    island = deepcopy(by_id[KITCHEN])
    aabb = catalog[island['assetId']]['definition']['geometry']['aabb']
    back = footprint(by_id['pl-gym-wellness-annex-front-right'], catalog)
    left = footprint(by_id['pl-gym-wellness-lounge-east-lower'], catalog)
    assert island['transform']['quaternion'] == dict(x=0,y=0,z=0,w=1), 'Kitchen changed since review'
    # CAD cabinets are on local -X. Rotate -90 so their backs meet the outer wall.
    island['transform']['position'] = dict(x=round(left[2]+.1+aabb['maximum']['z'],6),
        y=0, z=round(back[3]+.08-aabb['minimum']['x'],6))
    island['transform']['quaternion'] = dict(x=0,y=-.707106781,z=0,w=.707106781)
    changed = {KITCHEN: island}
    surfaces = {s['surfaceId']: s for s in catalog[island['assetId']]['supportSurfaces']}
    for pid in sorted(MOVED-{KITCHEN}):
        p = deepcopy(by_id[pid]); r = p['snapRelationship']
        assert r['family'] == 'surface_attachment' and r['supportPlacementId'] == KITCHEN
        surface = surfaces[r['surfaceId']]
        p['transform'] = transform(island, r['localPosition']['x'], r['localPosition']['z'],
            r['localRotationDegrees'], surface['localFrame']['origin']['y'])
        p['transform']['quaternion'] = {k:round(v,9) for k,v in p['transform']['quaternion'].items()}
        changed[pid] = p
    ops = []
    for pid, p in changed.items():
        ops.extend([dict(op='move_placement',placementId=pid,position=p['transform']['position']),
                    dict(op='rotate_placement',placementId=pid,quaternion=p['transform']['quaternion'])])
    settings = deepcopy(before['extensions']['facilityPerimeterWalls']['settings'])
    artworks = settings['exteriorFinish'].setdefault('fittedArtworks', [])
    assert not {r['artworkId'] for r in records}.intersection(a['artworkId'] for a in artworks)
    artworks.extend(records)
    ops.append(dict(op='set_perimeter_walls',wallSettings=settings))
    return apply_facility_layout_operations(before,ops,updated_at=datetime.now(timezone.utc).isoformat())['document']


def audit(before, after, catalog, records):
    expected = change(before,catalog,records); expected['updatedAt'] = after['updatedAt']
    assert expected == after, 'Unexpected changes beyond the kitchen and three murals'
    old = {p['placementId']:p for p in before['placements']}
    new = {p['placementId']:p for p in after['placements']}
    for pid in MOVED:
        p = deepcopy(new[pid]); p['transform'] = old[pid]['transform']
        assert p == old[pid], 'Only transforms may change on the existing kitchen assembly and appliances'
    b = footprint(new[KITCHEN],catalog)
    back = footprint(new['pl-gym-wellness-annex-front-right'],catalog)
    divider = footprint(new['pl-gym-wellness-meeting-cafe-divider'],catalog)
    middle = footprint(new['pl-gym-wellness-lounge-east-middle'],catalog)
    fridge = footprint(new['pl-gym-wellness-fridge'],catalog)
    assert abs(b[1]-back[3]-.08)<1e-5
    assert divider[1]-b[3]>3 and middle[1]-b[3]>1.2
    assert fridge[0]-b[2]>.15
    assert new[PREFIX+'north'] == old[PREFIX+'north']
    return dict(movedPlacements=sorted(MOVED),otherPlacementsUnchanged=len(before['placements'])-3,
        kitchenFootprint=b,backWallGapMeters=b[1]-back[3],openRoomDepthMeters=divider[1]-b[3],
        entryClearanceMeters=middle[1]-b[3],fridgeGapMeters=fridge[0]-b[2],
        attachedAppliancesPreserved=True,soccerHeroWallUnchanged=True,existingArtUnchanged=True,
        geometryAndEquipmentScaleUnchanged=True,artworksAdded=3)


def stage():
    OUT.mkdir(parents=True,exist_ok=True)
    target = STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    raw = target.read_bytes(); before = json.loads(raw)
    for name, data in [('before.json',raw),('catalog-before.json',(ROOT/PRIVATE_ASSET_MANIFEST).read_bytes())]:
        path = OUT/name
        if path.exists(): assert path.read_bytes()==data, 'Staged base changed'
        else: path.write_bytes(data)
    store = OUT/'validation-store'
    for rel in ['authorities','layouts/local']:
        copytree(_native_fs_path(STORE/rel),_native_fs_path(store/rel),dirs_exist_ok=True)
    host = LocalFacilityLayoutHost(store,private_assets=True,private_asset_root=ROOT)
    try:
        catalog = {a['assetId']:a for a in host.authoritative_asset_catalog()}
        records,sources = prepare(before,catalog)
        candidate = change(before,catalog,records)
        spatial = host.service._diagnose_spatial(host.principal(),'site-local',candidate)
        write(OUT/'spatial.json',spatial); host.service._require_spatially_valid(spatial)
        candidate = host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))['layout']
        checks = audit(before,candidate,catalog,records)
    finally: host.close()
    write(OUT/'candidate.json',candidate)
    write(OUT/'report.json',dict(status='validated',baseRevision=layout_revision(before),checks=checks,
        layoutHashes=saved_hashes(),records=records,sources=sources))
    fixture = deepcopy(candidate)
    fixture['placements'] = [p for p in candidate['placements'] if p['placementId'].startswith(PREFIX)
        and p['transform']['position']['x']<43 or 20<=p['transform']['position']['x']<=36
        and -18<=p['transform']['position']['z']<=-3]
    finish = fixture['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']
    finish['fittedArtworks'] = records; finish['artworks'] = []; finish['wallFaces'] = []
    aids = {p['assetId'] for p in fixture['placements']}
    library = {a['assetId']:a for a in json.loads((ROOT/PRIVATE_ASSET_MANIFEST).read_bytes())['assets']}
    write(OUT/'render-fixture.json',dict(layout=fixture,catalog=[catalog[a] for a in sorted(aids)],
        artifacts={a:dict(url='/'+library[a]['artifact'],sourceToCanonical=library[a]['sourceToCanonical']) for a in aids},
        ids=[s['id'] for s in SPECS],sources=sources))
    print(json.dumps(checks))


def publish_or_save(phase):
    report = json.loads((OUT/'report.json').read_bytes())
    target = STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    assert target.read_bytes()==(OUT/'before.json').read_bytes(), 'Saved gym changed'
    assert (ROOT/PRIVATE_ASSET_MANIFEST).read_bytes()==(OUT/'catalog-before.json').read_bytes()
    if phase=='publish-images':
        assert report['status']=='validated'
        for s in report['sources']:
            raw = (OUT/'staged-project'/s['artifact']).read_bytes()
            assert hashlib.sha256(raw).hexdigest()==s['sha256']
            dest = ROOT/s['artifact']
            if dest.exists(): assert dest.read_bytes()==raw
            else: RevisionedAuthorityRepository._atomic_write(dest,raw)
        report['status']='images-published'
    else:
        assert report['status']=='images-published'
        proof = json.loads((OUT/'visual-review.json').read_bytes())
        assert proof['status']=='passed' and proof['candidateSha256']==sha(OUT/'candidate.json')
        for s in report['sources']: assert sha(ROOT/s['artifact'])==s['sha256']
        host = LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
        try:
            catalog = {a['assetId']:a for a in host.authoritative_asset_catalog()}
            before,candidate = json.loads((OUT/'before.json').read_bytes()),json.loads((OUT/'candidate.json').read_bytes())
            audit(before,candidate,catalog,report['records'])
            receipt = host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,report['baseRevision'])
            audit(before,receipt['layout'],catalog,report['records'])
        finally: host.close()
        write(OUT/'saved.json',receipt['layout'])
        hashes = saved_hashes()
        assert all(hashes[k]==v for k,v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
        report.update(status='saved',savedRevision=receipt['revision'],otherLayoutsUnchanged=True)
    write(OUT/'report.json',report)
    print(report['status'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['stage','publish-images','save'])
    phase=parser.parse_args().phase
    stage() if phase=='stage' else publish_or_save(phase)
