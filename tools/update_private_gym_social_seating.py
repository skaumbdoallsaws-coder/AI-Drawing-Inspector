"""Stage and save scoped gaming-room seating and reception material changes."""
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
from shutil import copytree
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tools')]
from tools.apex_equipment_materials import build_variant
from tools.build_private_gym import LAYOUT, STORE, write, saved_hashes
from tools.add_private_gym_fitness_centre import footprint
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations

OUT = ROOT/'.runtime/private-gym-social-seating-20261010'
LIVING = 'asset-gym-living-room-1'
NEW = 'pl-gym-gaming-living-room-1'
REMOVED = {'pl-gym-wellness-lounge-sofa-west', 'pl-gym-wellness-lounge-sofa-south',
           'pl-gym-wellness-lounge-coffee-table'}
TABLE = 'asset-5589t51-round-plastic-folding-table'
CHAIR = 'asset-chair-black'
TARGETS = {
    'pl-019c7f9a007a6a7bd4551b1b': TABLE,
    'pl-1a0f0488a0a285f5c4b6f883': TABLE,
    'pl-0f138aa232b057f9c9675654': CHAIR,
    'pl-6c844324023b2782ee455a6b': CHAIR,
    'pl-9402d5717888893f93a5d473': CHAIR,
    'pl-bbe8c0402d82dfa39989a090': CHAIR,
}


def changes(before, catalog):
    by_id = {p['placementId']:p for p in before['placements']}
    assert REMOVED <= by_id.keys() and NEW not in by_id
    ops = [dict(op='delete_placement', placementId=pid) for pid in sorted(REMOVED)]
    for pid, source in TARGETS.items():
        p = deepcopy(by_id[pid])
        assert p['assetId'] == source
        asset = catalog[source+'-reception-apex']
        p.update({k:asset[k] for k in ('assetId','assetDefinitionRevision')})
        ops.extend([dict(op='delete_placement',placementId=pid), dict(op='place_asset',placement=p)])
    ops.append(dict(op='place_asset',placement=dict(
        placementId=NEW, assetId=LIVING, assetDefinitionRevision=catalog[LIVING]['assetDefinitionRevision'],
        positionMode='manual', snapRelationship=None,
        transform=dict(position=dict(x=3.6,y=0,z=-6.6),quaternion=dict(x=0,y=0,z=0,w=1),scale=1),
        metadata=dict(instanceLabel='Living Room 1 - Gaming Room TV Seating',room='lounge',
            gymRole='amenity',inputMethod='independent-authoring',
            scaleEvidence='Unitless STL provisionally interpreted as inches from sofa width and seat height'))))
    return apply_facility_layout_operations(before,ops,updated_at=datetime.now(timezone.utc).isoformat())['document']


def audit(before, after, catalog):
    expected = changes(before,catalog)
    expected['updatedAt'] = after['updatedAt']
    assert after == expected, 'Unexpected change outside requested seating and six reception finishes'
    old = {p['placementId']:p for p in before['placements']}
    new = {p['placementId']:p for p in after['placements']}
    assert old.keys()-new.keys() == REMOVED and new.keys()-old.keys() == {NEW}
    for pid in old.keys() & new.keys():
        if pid in TARGETS:
            a,b = deepcopy(old[pid]),deepcopy(new[pid])
            for value in (a,b):
                value.pop('assetId');value.pop('assetDefinitionRevision')
            assert a == b
        else:
            assert old[pid] == new[pid]
    bounds = footprint(new[NEW],catalog)
    x0,z0,x1,z1 = bounds
    assert 1 < x0 < x1 < 6.1 and -8.2 < z0 < z1 < -5
    gaps = []
    for p in after['placements']:
        pos = p['transform']['position']
        if p['placementId'] == NEW or pos['y'] != 0 or not (0 <= pos['x'] < 22 and -18 < pos['z'] <= -3):
            continue
        bx0,bz0,bx1,bz1 = footprint(p,catalog)
        gap = (max(x0-bx1,bx0-x1,0)**2 + max(z0-bz1,bz0-z1,0)**2)**.5
        assert gap > .85, ('Seating clearance',p['placementId'],gap)
        gaps.append(dict(placementId=p['placementId'],footprintGapMeters=gap))
    return dict(removed=sorted(REMOVED),added=NEW,colored=sorted(TARGETS),footprint=bounds,
        gaps=gaps,unchangedPlacements=len(old)-len(REMOVED)-len(TARGETS),layoutExpansionRequired=False)


def stage():
    OUT.mkdir(parents=True,exist_ok=True)
    target = STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    raw = target.read_bytes()
    manifest = ROOT/PRIVATE_ASSET_MANIFEST
    original = manifest.read_bytes()
    before,library = json.loads(raw),json.loads(original)
    for name,data in [('before.json',raw),('catalog-before.json',original)]:
        p = OUT/name
        if p.exists():
            assert p.read_bytes() == data, 'Staging source changed'
        else:
            p.write_bytes(data)
    by_id = {a['assetId']:a for a in library['assets']}
    staged = OUT/'staged-project'
    checks, originals, variants = [],{},{}
    for aid in (TABLE,CHAIR):
        old = by_id[aid]
        # The table top is a separate CAD body. The chair is one imported body;
        # use a reviewed below-seat region for its gold legs, not a part-name guess.
        overrides = {'0':'gold'} if aid == TABLE else {'0':'frame','regions':[
            dict(sourceRole='frame',bounds=[[-1,-.01,-1],[1,.40,1]],role='gold')]}
        payload,evidence = build_variant(old,overrides)
        relative = 'generated/industrial_assets/private_gym/reception-furniture/'+aid+'-'+evidence['displaySha256'][:16]+'.glb'
        RevisionedAuthorityRepository._atomic_write(staged/relative,payload)
        new = deepcopy(old)
        new.update(assetId=aid+'-reception-apex',artifact=relative,displayName=old['displayName']+' - APEX Black and Gold')
        new['description'] += ' Scoped black-and-gold display finish; source geometry and dimensions unchanged.'
        new['source'] = dict(kind='authored-primitive',generator=Path(__file__).name,
            originalAssetId=aid,originalSha256=evidence['sourceSha256'])
        new['tags'] += ['apex','black and gold','reception']
        assert new['assetId'] not in by_id
        library['assets'].append(new)
        originals[old['artifact']] = evidence['previousDisplaySha256']
        variants[relative] = evidence['displaySha256']
        checks.append(evidence)
    library['summary']['total'] = len(library['assets'])
    write(staged/PRIVATE_ASSET_MANIFEST,library)
    validation = OUT/'validation-store'
    for rel in ['authorities','layouts/local']:
        copytree(_native_fs_path(STORE/rel),_native_fs_path(validation/rel),dirs_exist_ok=True)
    host = LocalFacilityLayoutHost(validation,private_assets=True,private_asset_root=staged)
    try:
        catalog = {a['assetId']:a for a in host.authoritative_asset_catalog()}
        for aid in (TABLE,CHAIR):
            assert catalog[aid]['definition']['geometry'] == catalog[aid+'-reception-apex']['definition']['geometry']
        candidate = changes(before,catalog)
        spatial = host.service._diagnose_spatial(host.principal(),'site-local',candidate)
        write(OUT/'spatial.json',spatial)
        host.service._require_spatially_valid(spatial)
        receipt = host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))
        candidate = receipt['layout']
        layout_checks = audit(before,candidate,catalog)
    finally:
        host.close()
    write(OUT/'candidate.json',candidate)
    write(OUT/'report.json',dict(status='validated',baseRevision=layout_revision(before),checks=layout_checks,
        materialChecks=checks,layoutHashes=saved_hashes(),originalAssetHashes=originals,variantHashes=variants))
    fixture = deepcopy(candidate)
    fixture['placements'] = [p for p in candidate['placements']
        if 0<=p['transform']['position']['x']<=22 and -18<=p['transform']['position']['z']<=10]
    finish = fixture['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']
    finish['fittedArtworks'] = [];finish['wallFaces'] = []
    aids = {p['assetId'] for p in fixture['placements']}
    entries = {a['assetId']:a for a in library['assets'] if a['assetId'] in aids}
    write(OUT/'render-fixture.json',dict(layout=fixture,catalog=[catalog[a] for a in sorted(aids)],
        artifacts={a:dict(url=('/staged/' if e['artifact'] in variants else '/')+e['artifact'],
            sourceToCanonical=e['sourceToCanonical']) for a,e in entries.items()}))
    print(json.dumps(layout_checks))


def finish(phase):
    report = json.loads((OUT/'report.json').read_bytes())
    target = STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    manifest = ROOT/PRIVATE_ASSET_MANIFEST
    staged = OUT/'staged-project'
    assert target.read_bytes() == (OUT/'before.json').read_bytes(),'Saved gym changed'
    for rel,digest in report['originalAssetHashes'].items():
        assert hashlib.sha256((ROOT/rel).read_bytes()).hexdigest() == digest
    proof = json.loads((OUT/'visual-review.json').read_bytes())
    assert proof['status'] == 'passed' and proof['candidateSha256'] == hashlib.sha256((OUT/'candidate.json').read_bytes()).hexdigest()
    if phase == 'publish':
        assert report['status'] == 'validated'
        assert manifest.read_bytes() == (OUT/'catalog-before.json').read_bytes(),'Library changed'
        for rel,digest in report['variantHashes'].items():
            data = (staged/rel).read_bytes()
            assert hashlib.sha256(data).hexdigest() == digest
            if (ROOT/rel).exists():
                assert (ROOT/rel).read_bytes() == data
            else:
                RevisionedAuthorityRepository._atomic_write(ROOT/rel,data)
        RevisionedAuthorityRepository._atomic_write(manifest,(staged/PRIVATE_ASSET_MANIFEST).read_bytes())
        report['status'] = 'published'
    else:
        assert report['status'] == 'published'
        assert manifest.read_bytes() == (staged/PRIVATE_ASSET_MANIFEST).read_bytes()
        host = LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
        try:
            catalog = {a['assetId']:a for a in host.authoritative_asset_catalog()}
            before = json.loads((OUT/'before.json').read_bytes())
            candidate = json.loads((OUT/'candidate.json').read_bytes())
            audit(before,candidate,catalog)
            receipt = host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,report['baseRevision'])
            audit(before,receipt['layout'],catalog)
            assert json.loads(target.read_bytes()) == receipt['layout']
        finally:
            host.close()
        write(OUT/'saved.json',receipt['layout'])
        hashes = saved_hashes()
        assert all(hashes[k] == v for k,v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
        report.update(status='saved',savedRevision=receipt['revision'],otherLayoutsUnchanged=True)
    write(OUT/'report.json',report)
    print(report['status'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['stage','publish','save'])
    args = parser.parse_args()
    stage() if args.phase == 'stage' else finish(args.phase)
