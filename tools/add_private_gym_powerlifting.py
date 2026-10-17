"""Stage and save three powerlifting additions using existing layout operations."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from shutil import copytree
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT),str(ROOT/'tools'),str(Path.home()/'AppData/Roaming/Python/Python314/site-packages')]
from shapely.geometry import LineString, Polygon, box
from tools.import_private_gym_powerlifting import OUT, ITEMS, base
from tools.add_private_gym_decorations import polygon, sha
from tools.add_private_gym_calisthenics import yaw
from tools.build_private_gym import STORE, LAYOUT, write, saved_hashes
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.facility_layout.spatial import placement_spatial_records

A = 'asset-gym-powerlifting-'
P = 'pl-gym-powerlifting-'
M = 'fm-gym-powerlifting-'
POSES = {'rack':(52.7,65.1,0), 'bar':(52.7,69.7,0), 'rear-delt':(43.5,24,90)}
PADS = {'rack':(52.7,64.8,4.4,4.6), 'bar':(52.7,69.7,4.4,3.6)}


def markings():
    result = []
    for key,(x,z,w,d) in PADS.items():
        for suffix,cx,cz,width,depth,color,y in [
            ('pad',x,z,w,d,'#17191C',.006),
            ('left',x-w/2,z,.04,d,'#C99B39',.008),
            ('right',x+w/2,z,.04,d,'#C99B39',.008),
            ('front',x,z-d/2,w,.04,'#C99B39',.008),
            ('back',x,z+d/2,w,.04,'#C99B39',.008)]:
            result.append(dict(markingId=M+key+'-'+suffix,markingType='solid_line',
                label='APEX '+key+' lifting '+suffix,semanticRole='decorative',positionMode='manual',
                transform=dict(position=dict(x=cx,y=y,z=cz),rotationDegrees=0),width=width,depth=depth,
                fillColor=color,strokeColor=color,opacity=1,text='',evidence=[],
                metadata=dict(authoredIn='private-gym-powerlifting',planningAllowance='Concept lifting bay; substrate and load capacity unverified')))
    return result


def operations(catalog):
    ops = []
    for key,(x,z,angle) in POSES.items():
        asset = catalog[A+key]
        ops.append(dict(op='place_asset',placement=dict(placementId=P+key,assetId=A+key,
            assetDefinitionRevision=asset['assetDefinitionRevision'],positionMode='manual',
            transform=dict(position=dict(x=x,y=0,z=z),quaternion=yaw(angle),scale=1),snapRelationship=None,
            metadata=dict(instanceLabel=asset['displayName'],inputMethod='independent-authoring'))))
    ops.extend(dict(op='add_floor_marking',floorMarking=m) for m in markings())
    return ops


def audit(before,after,catalog):
    expected = apply_facility_layout_operations(before,operations(catalog),updated_at=after['updatedAt'])['document']
    assert expected == after, 'Unrelated layout content changed'
    old = {p['placementId']:p for p in before['placements']}
    new = {p['placementId']:p for p in after['placements']}
    assert new.keys()-old.keys() == {P+k for k in POSES}
    assert all(new[pid] == p for pid,p in old.items())
    routes = [LineString([(p['x'],p['z']) for p in r['centerline']]).buffer(r['corridorWidth']/2,cap_style=2)
              for r in before['routes'] if len(r.get('centerline',[]))>1]
    zones = {z['zoneId']:Polygon([(v['x'],v['z']) for v in z['boundary']]) for z in before['zones']}
    zones_for = {'rack':'zn-private-gym-fields-turf','bar':'zn-private-gym-fields-turf','rear-delt':'zn-56b39c0a0c81cf9619bef4d2'}
    envelopes = {k:box(x-w/2,z-d/2,x+w/2,z+d/2) for k,(x,z,w,d) in PADS.items()}
    envelopes['rear-delt'] = box(42.28,22.55,45.15,25.45)
    existing = {pid:polygon(p,catalog) for pid,p in old.items()}
    records = {}
    for key in POSES:
        p = new[P+key]
        shape,clear = polygon(p,catalog),envelopes[key]
        assert p['transform']['scale'] == 1
        assert all(abs(r.minimum_y)<.0011 for r in placement_spatial_records(p,catalog[A+key]))
        assert clear.contains(shape) and zones[zones_for[key]].contains(clear)
        assert all(clear.intersection(r).area<1e-6 for r in routes), ('Walkway blocked',key)
        for pid,other in existing.items():
            assert clear.intersection(other).area<1e-6, ('Exercise allowance blocked',key,pid)
        for other,region in envelopes.items():
            if other != key:
                assert clear.intersection(region).area<1e-6
        if key in ('rack','bar'):
            assert clear.intersection(box(49,42.5,72,52.5)).area == 0, 'Sled lanes blocked'
            assert clear.intersection(box(68,62,82,72)).area == 0, 'Patio blocked'
        records[key] = dict(footprint=list(shape.bounds),reservedConceptArea=list(clear.bounds),
                            nearestExistingEquipmentMeters=min(shape.distance(g) for g in existing.values()))
    return dict(addedPlacements=3,originalPlacementsPreserved=len(old),addedFloorMarkings=len(markings()),
                footprints=records,nativeScalePreserved=True,routesAndSledLanesClear=True,
                existingArtworkWallsAndRoomsUnchanged=True,
                limitations='Concept clearance only; manufacturer operating envelope, anchoring, weather exposure and floor load capacity unverified')


def stage():
    target = STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    manifest = ROOT/PRIVATE_ASSET_MANIFEST
    raw,original = target.read_bytes(),manifest.read_bytes()
    before,library = json.loads(raw),json.loads(original)
    for name,data in [('before.json',raw),('catalog-before.json',original)]:
        file = OUT/name
        if file.exists():
            assert file.read_bytes()==data,'Staging base changed'
        else:
            file.write_bytes(data)
    entries = [json.loads((base.LIBRARY/('gym-powerlifting-'+key)/'catalog-entry.json').read_bytes()) for key,_,_ in ITEMS]
    assert not {a['assetId'] for a in entries}.intersection(a['assetId'] for a in library['assets'])
    source_hashes = {a['source']['sha256'] for a in entries}
    assert not source_hashes.intersection(a.get('source',{}).get('sha256') for a in library['assets']), 'Source already in catalog'
    library['assets'].extend(entries)
    library['summary']['total'] = len(library['assets'])
    staged = OUT/'staged-project'
    write(staged/PRIVATE_ASSET_MANIFEST,library)
    store = OUT/'validation-store'
    for rel in ['authorities','layouts/local']:
        copytree(_native_fs_path(STORE/rel),_native_fs_path(store/rel),dirs_exist_ok=True)
    host = LocalFacilityLayoutHost(store,private_assets=True,private_asset_root=staged)
    try:
        catalog = {a['assetId']:a for a in host.authoritative_asset_catalog()}
        ops = operations(catalog)
        write(OUT/'operations.json',ops)
        candidate = apply_facility_layout_operations(before,ops)['document']
        checks = audit(before,candidate,catalog)
        spatial = host.service._diagnose_spatial(host.principal(),'site-local',candidate)
        write(OUT/'spatial.json',spatial)
        host.service._require_spatially_valid(spatial)
        candidate = host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))['layout']
        audit(before,candidate,catalog)
    finally:
        host.close()
    write(OUT/'candidate.json',candidate)
    write(OUT/'report.json',dict(status='validated',baseRevision=layout_revision(before),checks=checks,
        assetHashes={a['artifact']:sha(ROOT/a['artifact']) for a in entries},layoutHashes=saved_hashes(),
        candidateSha256=sha(OUT/'candidate.json'),sourceFiles=[a['source']['fileName'] for a in entries]))
    byid = {a['assetId']:a for a in library['assets']}
    fixtures = {}
    for area in ('outdoor','indoor'):
        fixture = deepcopy(candidate)
        def included(p):
            x,z = p['transform']['position']['x'],p['transform']['position']['z']
            return x>=41 and z>=30 if area=='outdoor' else 40<=x<=52 and 12<=z<=30
        fixture['placements'] = [p for p in candidate['placements'] if included(p)]
        ids = {p['placementId'] for p in fixture['placements']}
        finish = fixture['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']
        finish['fittedArtworks'] = [a for a in finish['fittedArtworks'] if 'edge' in a['target'] or a['target'].get('placementId') in ids]
        finish['wallFaces'] = [a for a in finish['wallFaces'] if a['placementId'] in ids]
        aids = {p['assetId'] for p in fixture['placements']}
        fixtures[area] = dict(layout=fixture,catalog=[catalog[a] for a in sorted(aids)],
            artifacts={a:dict(url='/'+byid[a]['artifact'],sourceToCanonical=byid[a]['sourceToCanonical']) for a in aids})
    write(OUT/'render-fixtures.json',fixtures)
    print(json.dumps(checks),flush=True)


def save():
    report = json.loads((OUT/'report.json').read_bytes())
    for name in ['visual-review.json','browser-check.json']:
        proof = json.loads((OUT/name).read_bytes())
        assert proof['status']=='passed' and proof['candidateSha256']==sha(OUT/'candidate.json')
    target = STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    manifest = ROOT/PRIVATE_ASSET_MANIFEST
    assert target.read_bytes()==(OUT/'before.json').read_bytes(),'Saved gym changed'
    assert manifest.read_bytes()==(OUT/'catalog-before.json').read_bytes(),'Library changed'
    for rel,digest in report['assetHashes'].items():
        assert sha(ROOT/rel)==digest
    staged = (OUT/'staged-project'/PRIVATE_ASSET_MANIFEST).read_bytes()
    RevisionedAuthorityRepository._atomic_write(manifest,staged)
    host = LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
    try:
        catalog = {a['assetId']:a for a in host.authoritative_asset_catalog()}
        before,candidate = (json.loads((OUT/name).read_bytes()) for name in ('before.json','candidate.json'))
        audit(before,candidate,catalog)
        receipt = host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,report['baseRevision'])
        audit(before,receipt['layout'],catalog)
    finally:
        host.close()
    write(OUT/'saved.json',receipt['layout'])
    assert json.loads(target.read_bytes()) == receipt['layout']
    hashes = saved_hashes()
    assert all(hashes[k]==v for k,v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
    report.update(status='saved',savedRevision=receipt['revision'],otherLayoutsUnchanged=True)
    write(OUT/'report.json',report)
    print('Saved loaded rack, loaded barbell and fly/rear-delt machine',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['stage','save'])
    globals()[parser.parse_args().phase]()
