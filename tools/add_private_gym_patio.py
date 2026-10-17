"""Replace only the blue-circled cardio corner with a verified paved patio."""
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import hashlib
import json
import math
from pathlib import Path
from shutil import copytree
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools'),
    str(Path.home() / 'AppData/Roaming/Python/Python314/site-packages'),
    str(ROOT / '.runtime/model-import-20261002/mesh-dependencies')]
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.facility_layout.spatial import placement_spatial_records
from tools.build_private_gym import LAYOUT, STORE, write, saved_hashes

OUT = ROOT / '.runtime/private-gym-patio-20261009'
P = 'pl-gym-patio-'
ASSET = 'asset-gym-patio-'
PATIO = (68, 62, 82, 72)
TURF = 'private-gym-fields-turf'
REMOVED = {'pl-private-gym-fields-' + k for k in ['conditioning-bike-1', 'conditioning-bike-2', 'flat-bench']}
KEYS = ['enclosure', 'grill', 'picnic', 'drinks', 'plant', 'palm', 'supports', 'roof']


def ground_surfaces(before):
    surfaces = deepcopy(before['extensions']['facilityGround']['surfaces'])
    old = next(s for s in surfaces if s['surfaceId'] == TURF)
    assert [old[k] for k in ['minX','minZ','maxX','maxZ']] == [44,40,82,72]
    index = surfaces.index(old)
    pieces = []
    for key, bounds, color in [('west',(44,40,68,72),old['color']),
            ('south',(68,40,82,62),old['color']),('paving',PATIO,'#92999F')]:
        a,b,c,d = bounds
        part = deepcopy(old)
        part.update(surfaceId='gym-patio-'+key,minX=a,minZ=b,maxX=c,maxZ=d,color=color)
        pieces.append(part)
    surfaces[index:index+1] = pieces
    return surfaces


def operations(before, catalog):
    ground = deepcopy(before['extensions']['facilityGround'])
    ground['surfaces'] = ground_surfaces(before)
    a,b,c,d = PATIO
    ops = [dict(op='set_ground', ground=ground)]
    ops.extend(dict(op='delete_placement',placementId=pid) for pid in sorted(REMOVED))
    ops.append(dict(op='add_zone',zone=dict(zoneId='zn-gym-patio',label='APEX Barbecue Patio',zoneType='workcell',
        boundary=[dict(x=a,z=b),dict(x=c,z=b),dict(x=c,z=d),dict(x=a,z=d)],floorElevation=0,
        anchors=[],evidence=[],extensions=dict(style=dict(fillColor='#92999F')))))
    def place(key, asset, x, z, y=0, yaw=0, relationship=None):
        q = math.radians(yaw)/2
        ops.append(dict(op='place_asset',placement=dict(placementId=P+key,assetId=ASSET+asset,
            assetDefinitionRevision=catalog[ASSET+asset]['assetDefinitionRevision'],positionMode='manual',
            transform=dict(position=dict(x=x,y=y,z=z),quaternion=dict(x=0,y=math.sin(q),z=0,w=math.cos(q)),scale=1),
            snapRelationship=relationship,metadata=dict(instanceLabel=key.replace('-',' ').title(),
                room='barbecue-patio',inputMethod='independent-authoring'))))
    place('pergola-supports','supports',73,68)
    place('pergola-roof','roof',73,68,y=2.1335999965667725,
        relationship=dict(family='surface_attachment',attachmentId='surface:'+P+'pergola-roof',
            supportPlacementId=P+'pergola-supports',surfaceId='pergola-roof-seat',surfaceSource='asset_definition',
            localPosition=dict(x=0,z=0),localRotationDegrees=0,normalOffsetMeters=0,side='above',evidenceStatus='derived'))
    place('shaded-drinks-table','drinks',73,68)
    place('picnic-table-and-four-chairs','picnic',78.8,68.5)
    place('barbecue-grill','grill',78.8,63.8,yaw=90)
    place('decorative-plant-1','plant',75.5,62.8)
    place('decorative-plant-2','plant',81,70.9)
    place('palm-1','palm',69.3,70.7)
    place('palm-2','palm',81,65.6)
    def line(key,x,z,w,d,color):
        ops.append(dict(op='add_floor_marking',floorMarking=dict(markingId='fm-gym-patio-'+key,
            label='Patio '+key,markingType='solid_line',semanticRole='decorative',positionMode='manual',
            transform=dict(position=dict(x=x,y=.004,z=z),rotationDegrees=0),width=w,depth=d,
            fillColor=color,strokeColor=color,opacity=1,text='',evidence=[],metadata={})))
    for x in range(70,82,2):
        line('paver-x-'+str(x),x,67,.012,10,'#757D84')
    for z in range(64,72,2):
        line('paver-z-'+str(z),75,z,14,.012,'#757D84')
    return ops


def audit(before, after, catalog):
    from shapely.geometry import box, Polygon, LineString
    from shapely.ops import unary_union
    old = {p['placementId']:p for p in before['placements']}
    new = {p['placementId']:p for p in after['placements']}
    assert old.keys()-new.keys() == REMOVED
    assert all(new[pid] == p for pid,p in old.items() if pid not in REMOVED)
    added = [p for pid,p in new.items() if pid not in old]
    assert len(added) == 9 and all(p['placementId'].startswith(P) for p in added)
    assert after['zones'][:-1] == before['zones'] and after['zones'][-1]['zoneId'] == 'zn-gym-patio'
    assert after['floorMarkings'][:len(before['floorMarkings'])] == before['floorMarkings']
    for key, value in before.items():
        if key not in {'placements','zones','floorMarkings','extensions','updatedAt'}:
            assert after[key] == value, key
    for key, value in before['extensions'].items():
        if key != 'facilityGround':
            assert after['extensions'][key] == value, key
    assert after['extensions']['facilityGround']['surfaces'] == ground_surfaces(before)
    def surface_shape(s):
        return box(s['minX'],s['minZ'],s['maxX'],s['maxZ'])
    original = before['extensions']['facilityGround']['surfaces']
    current = after['extensions']['facilityGround']['surfaces']
    assert unary_union([surface_shape(s) for s in current]).symmetric_difference(
        unary_union([surface_shape(s) for s in original])).area < 1e-8
    for i, s in enumerate(current):
        for other in current[i+1:]:
            assert surface_shape(s).intersection(surface_shape(other)).area < 1e-8
    # Pedestrian approach stays outside the retained training wall and beneath the elevated roof.
    paths = [[(69.1,60),(69.1,65.2),(76,65.2),(76,70)],[(73,65.2),(73,66.2)]]
    for points in paths:
        corridor = LineString(points).buffer(.6, cap_style=2, join_style=2)
        for p in new.values():
            for record in placement_spatial_records(p,catalog[p['assetId']]):
                if record.minimum_y >= 2.05:
                    continue
                assert corridor.intersection(Polygon(record.polygon)).area < 1e-7, ('Blocked patio approach',p['placementId'])
    assert all(p['transform']['scale'] == 1 for p in added)
    assert new[P+'pergola-roof']['snapRelationship']['supportPlacementId'] == P+'pergola-supports'
    return dict(patioMeters=[14,10],areaSquareMeters=140,layoutExtended=False,
        enclosureMeters=[3.6576,3.6576,2.6416],seats=6,removedPlacements=sorted(REMOVED),
        retainedTrainingWallAndRack=True,otherPlacementsUnchanged=len(old)-len(REMOVED),
        checkedApproachWidthMeters=1.2,canopyTrianglesPreserved=29900)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['stage','publish-assets','save'])
    args = parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    target = STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    manifest = ROOT/PRIVATE_ASSET_MANIFEST
    staged = OUT/'staged-project'
    if args.phase != 'stage':
        report = json.loads((OUT/'report.json').read_text())
        assert target.read_bytes() == (OUT/'before.json').read_bytes(), 'Saved gym changed'
        if args.phase == 'publish-assets':
            assert report['status'] == 'validated'
            assert manifest.read_bytes() == (OUT/'catalog-before.json').read_bytes(), 'Catalog changed'
            RevisionedAuthorityRepository._atomic_write(manifest,(staged/PRIVATE_ASSET_MANIFEST).read_bytes())
            report['status'] = 'assets-published'
        else:
            assert report['status'] == 'assets-published'
            raw = (OUT/'candidate.json').read_bytes()
            proof = json.loads((OUT/'native-check.json').read_text())
            assert proof['status'] == 'preview-verified' and proof['candidateHash'] == hashlib.sha256(raw).hexdigest()
            assert manifest.read_bytes() == (staged/PRIVATE_ASSET_MANIFEST).read_bytes()
            for rel, digest in report['assetHashes'].items():
                assert hashlib.sha256((ROOT/rel).read_bytes()).hexdigest() == digest
            host = LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
            try:
                catalog = {a['assetId']:a for a in host.authoritative_asset_catalog()}
                audit(json.loads((OUT/'before.json').read_bytes()),json.loads(raw),catalog)
                receipt = host.service.save_layout(host.principal(),'site-local',LAYOUT,json.loads(raw),report['baseRevision'])
            finally:
                host.close()
            write(OUT/'saved.json',receipt['layout'])
            report.update(status='saved',savedRevision=receipt['revision'])
            hashes = saved_hashes()
            assert all(hashes[k] == v for k,v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
            report['otherLayoutsUnchanged'] = True
        write(OUT/'report.json',report)
        print(report['status'])
        return
    raw, catalog_raw = target.read_bytes(), manifest.read_bytes()
    before, library = json.loads(raw), json.loads(catalog_raw)
    for name, data in [('before.json',raw),('catalog-before.json',catalog_raw)]:
        file = OUT/name
        if file.exists():
            assert file.read_bytes() == data, 'Base changed'
        else:
            file.write_bytes(data)
    entries = [json.loads((ROOT/'generated/industrial_assets/local_library'/('gym-patio-'+k)/'catalog-entry.json').read_text()) for k in KEYS]
    assert not {e['assetId'] for e in entries}.intersection(e['assetId'] for e in library['assets'])
    library['assets'].extend(entries)
    library['summary']['total'] = len(library['assets'])
    write(staged/PRIVATE_ASSET_MANIFEST,library)
    stage = OUT/'validation-store'
    for rel in ['authorities','layouts/local']:
        copytree(_native_fs_path(STORE/rel),_native_fs_path(stage/rel),dirs_exist_ok=True)
    host = LocalFacilityLayoutHost(stage,private_assets=True,private_asset_root=staged)
    try:
        catalog = {a['assetId']:a for a in host.authoritative_asset_catalog()}
        ops = operations(before,catalog)
        write(OUT/'operations.json',ops)
        candidate = apply_facility_layout_operations(before,ops,updated_at=datetime.now(timezone.utc).isoformat())['document']
        write(OUT/'candidate-draft.json',candidate)
        checks = audit(before,candidate,catalog)
        spatial = host.service._diagnose_spatial(host.principal(),'site-local',candidate)
        write(OUT/'spatial.json',spatial)
        host.service._require_spatially_valid(spatial)
        receipt = host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))
    finally:
        host.close()
    write(OUT/'candidate.json',receipt['layout'])
    write(OUT/'report.json',dict(status='validated',baseRevision=layout_revision(before),layoutHashes=saved_hashes(),
        checks=checks,assetHashes={e['artifact']:hashlib.sha256((ROOT/e['artifact']).read_bytes()).hexdigest() for e in entries},
        limitations=['STL furniture and vegetation use inferred centimetres, not verified source units.',
            'Concept placement only. Grill operating/fire clearances, pergola structural loading and outdoor installation are unqualified.']))
    profile = json.loads((ROOT/'.runtime/private-gym-recovery-art-20261009/profile.json').read_text())
    profile.update(profileId='private-gym-patio',origin='http://127.0.0.1:8567',dataRoot=str(OUT),backendId=str(uuid.uuid4()),storeId=str(uuid.uuid4()))
    write(OUT/'profile.json',profile)
    def shot(name,p,t):
        return dict(name=name,position=dict(zip(('x','y','z'),p)),target=dict(zip(('x','y','z'),t)),thresholds=dict(detail=1000))
    write(OUT/'review-config.json',dict(profileId=profile['profileId'],minimumAssetMeshes=1,cameraFov=50,
        requiredAssets=[ASSET+k for k in KEYS if k!='enclosure'],shots=[
            shot('01-patio-overhead',(76,20,75),(75,0,66)),
            shot('02-patio-approach',(68.7,2.1,64),(75.5,1,68)),
            shot('03-shaded-seating',(73,1.8,65.1),(73,1,68.1)),
            shot('04-grill-and-picnic',(76,2,65),(79,.8,67.5)),
            shot('05-outdoor-context',(96,30,85),(63,0,56))],
        finalShot=shot('06-saved-patio',(86,10,79),(75,.7,66.5))))
    print(json.dumps(checks))


if __name__ == '__main__':
    main()
