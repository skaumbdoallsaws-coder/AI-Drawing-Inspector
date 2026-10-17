"""Reposition only the pool slogan and the shower-room eagle, with native review."""
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
from shutil import copytree
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tools'),
    str(Path.home()/'AppData/Roaming/Python/Python314/site-packages')]
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from tools.build_private_gym import LAYOUT, STORE, IDENTITY, write, saved_hashes
from tools.private_gym_reception_art import wall_glb
from tools.apex_equipment_materials import unpack, pack
from tools.equip_factory02_cubicles import transform

OUT = ROOT/'.runtime/private-gym-art-visibility-20261008'
ASSET = 'asset-private-gym-shower-eagle-decal'
PLACEMENT = 'pl-private-gym-shower-eagle-decal'
SUPPORT = 'pl-9b54f9f414ff77a8cad8cb2d'
EAGLE = 'apex-interior-a04'
SLOGAN = 'higher-everyday'
DIMS = dict(width=2.2, height=2.8, depth=.008)
LOCAL_X, LOCAL_Y, GAP = -2.8, .1, .01


def artwork(layout, key):
    return next(a for a in layout['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['artworks']
        if a['artworkId'] == key)


def decal_glb(png):
    doc, data = unpack(wall_glb(png, DIMS, fit='contain', face=1, name='Shower Room Eagle'))
    # Two alpha faces give the decal finite thickness without an opaque backing.
    doc['scenes'][0]['nodes'] = [n for n in doc['scenes'][0]['nodes'] if doc['nodes'][n].get('mesh') != 0]
    back = deepcopy(doc['nodes'][doc['scenes'][0]['nodes'][0]])
    back.update(name='Eagle decal reverse', scale=[1,1,-1])
    doc['scenes'][0]['nodes'].append(len(doc['nodes']))
    doc['nodes'].append(back)
    raw = pack(doc, data)
    from ai_inspector.industrial_assets.artifacts import inspect_glb
    assert inspect_glb(raw).to_manifest_dict()['sceneTriangleCount'] == 4
    return raw


def prepare(before, library):
    source = ROOT/artwork(before, EAGLE)['imagePath'].lstrip('/')
    png = source.read_bytes()
    payload = decal_glb(png)
    rel = 'generated/industrial_assets/private_gym/art-visibility/eagle-' + hashlib.sha256(payload).hexdigest()[:16] + '.glb'
    dest = OUT/'staged-project'/rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(payload)
    assert all(e['assetId'] != ASSET for e in library['assets'])
    library['assets'].append(dict(assetId=ASSET, displayName='APEX Shower Room Eagle', category='Building Structures',
        artifact=rel, dimensions=DIMS, sourceToCanonical=IDENTITY, tags=['gym','artwork','wall decal'],
        description='Unmodified transparent eagle artwork mounted opposite the shower-room basketball player.',
        source=dict(kind='authored-wall-art', imagePath=source.relative_to(ROOT).as_posix(),
            sha256=hashlib.sha256(png).hexdigest(), imageModified=False, previousArtworkId=EAGLE)))
    library['summary']['total'] = len(library['assets'])
    write(OUT/'staged-project'/PRIVATE_ASSET_MANIFEST, library)
    return rel, source.relative_to(ROOT).as_posix()


def build(before, catalog):
    settings = deepcopy(before['extensions']['facilityPerimeterWalls']['settings'])
    arts = settings['exteriorFinish']['artworks']
    next(a for a in arts if a['artworkId'] == SLOGAN)['startMeters'] = 37
    settings['exteriorFinish']['artworks'] = [a for a in arts if a['artworkId'] != EAGLE]
    wall = next(p for p in before['placements'] if p['placementId'] == SUPPORT)
    bounds = catalog[wall['assetId']]['definition']['geometry']['aabb']
    local_z = bounds['maximum']['z'] + GAP + DIMS['depth']/2
    placement = dict(placementId=PLACEMENT, assetId=ASSET, assetDefinitionRevision=catalog[ASSET]['assetDefinitionRevision'],
        transform=transform(wall, LOCAL_X, local_z, 0, LOCAL_Y), positionMode='manual',
        snapRelationship=dict(family='wall_attachment', supportPlacementId=SUPPORT,
            supportAssetDefinitionRevision=wall['assetDefinitionRevision'], face='positive_z',
            localX=LOCAL_X, localY=LOCAL_Y, normalGapMeters=GAP),
        metadata=dict(instanceLabel='Shower Room Eagle', room='bath', inputMethod='independent-authoring'))
    ops = [dict(op='set_perimeter_walls', wallSettings=settings), dict(op='place_asset', placement=placement)]
    return apply_facility_layout_operations(before, ops, updated_at=datetime.now(timezone.utc).isoformat())['document'], ops


def audit(before, after, catalog):
    expected = deepcopy(before)
    arts = expected['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['artworks']
    next(a for a in arts if a['artworkId'] == SLOGAN)['startMeters'] = 37
    expected['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['artworks'] = [a for a in arts if a['artworkId'] != EAGLE]
    added = [p for p in after['placements'] if p['placementId'] == PLACEMENT]
    assert len(added) == 1
    expected['placements'].extend(added)
    expected['updatedAt'] = after['updatedAt']
    assert expected == after, 'Unrequested layout content changed'
    wall = next(p for p in before['placements'] if p['placementId'] == SUPPORT)
    b = catalog[wall['assetId']]['definition']['geometry']['aabb']
    art = added[0]
    assert art['assetId'] == ASSET and art['transform']['scale'] == 1
    assert art['assetDefinitionRevision'] == catalog[ASSET]['assetDefinitionRevision']
    wanted = transform(wall, LOCAL_X, b['maximum']['z'] + GAP + DIMS['depth']/2, 0, LOCAL_Y)
    for field in ('position','quaternion'):
        assert all(abs(art['transform'][field][axis]-value) < 1e-6 for axis,value in wanted[field].items())
    assert art['snapRelationship'] == dict(family='wall_attachment', supportPlacementId=SUPPORT,
        supportAssetDefinitionRevision=wall['assetDefinitionRevision'], face='positive_z',
        localX=LOCAL_X, localY=LOCAL_Y, normalGapMeters=GAP)
    assert b['minimum']['x'] <= LOCAL_X-DIMS['width']/2 < LOCAL_X+DIMS['width']/2 <= b['maximum']['x']
    assert 0 <= LOCAL_Y < LOCAL_Y+DIMS['height'] <= b['maximum']['y']
    slogan = artwork(after, SLOGAN)
    assert 36.2 < slogan['startMeters'] and slogan['startMeters']+slogan['widthMeters'] < 49.7
    # Both art faces open onto the same clear washroom aisle beyond the bay partitions.
    from shapely.geometry import box
    from tools.audit_independent_factory_layer2 import footprint
    corridor = box(51.4, 18.0, 59.8, 20.2)
    obstacles = []
    for p in after['placements']:
        bounds = catalog[p['assetId']]['definition']['geometry']['aabb']
        y = p['transform']['position']['y']
        if y+bounds['maximum']['y'] < 1.1 or y+bounds['minimum']['y'] > 2.9:
            continue
        if footprint(p, catalog[p['assetId']]).intersection(corridor).area > 1e-7:
            obstacles.append(p['placementId'])
    assert not obstacles, ('Artwork sightline obstructed', obstacles)
    return dict(sloganFitsPoolWall=True, eagleFacesBasketballArtwork=True,
        originalArtworkImageUnmodified=True, originalPlacementsUnchanged=len(before['placements']),
        wallsAndEquipmentUnmoved=True, oldOccludedEagleRemoved=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['stage','publish-assets','save'])
    phase=parser.parse_args().phase
    OUT.mkdir(parents=True,exist_ok=True)
    target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    manifest=ROOT/PRIVATE_ASSET_MANIFEST
    staged=OUT/'staged-project'
    if phase!='stage':
        report=json.loads((OUT/'report.json').read_text())
        assert target.read_bytes()==(OUT/'before.json').read_bytes(), 'Saved gym changed'
        if phase=='publish-assets':
            assert report['status']=='validated' and manifest.read_bytes()==(OUT/'catalog-before.json').read_bytes()
            for rel in report['artifacts']:
                payload=(staged/rel).read_bytes()
                dest=ROOT/rel
                if dest.exists(): assert dest.read_bytes()==payload
                else: RevisionedAuthorityRepository._atomic_write(dest,payload)
            RevisionedAuthorityRepository._atomic_write(manifest,(staged/PRIVATE_ASSET_MANIFEST).read_bytes())
            report['status']='assets-published'
        else:
            assert report['status']=='assets-published'
            raw=(OUT/'candidate.json').read_bytes()
            proof=json.loads((OUT/'native-check.json').read_text())
            assert proof['status']=='preview-verified' and proof['candidateHash']==hashlib.sha256(raw).hexdigest()
            assert manifest.read_bytes()==(staged/PRIVATE_ASSET_MANIFEST).read_bytes()
            for rel,digest in report['assetHashes'].items(): assert hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()==digest
            host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
            try:
                catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
                audit(json.loads((OUT/'before.json').read_bytes()),json.loads(raw),catalog)
                receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,json.loads(raw),report['baseRevision'])
                audit(json.loads((OUT/'before.json').read_bytes()),receipt['layout'],catalog)
            finally: host.close()
            write(OUT/'saved.json',receipt['layout'])
            report.update(status='saved',savedRevision=receipt['revision'])
            hashes=saved_hashes()
            assert all(hashes[k]==v for k,v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
            report['otherLayoutsUnchanged']=True
        write(OUT/'report.json',report)
        print(report['status'])
        return
    raw=target.read_bytes()
    before=json.loads(raw)
    catalog_raw=manifest.read_bytes()
    for name,payload in [('before.json',raw),('catalog-before.json',catalog_raw)]:
        path=OUT/name
        if path.exists(): assert path.read_bytes()==payload, 'Base changed'
        else: path.write_bytes(payload)
    rel,source=prepare(before,json.loads(catalog_raw))
    stage=OUT/'validation-store'
    for folder in ['authorities','layouts/local']:
        copytree(_native_fs_path(STORE/folder),_native_fs_path(stage/folder),dirs_exist_ok=True)
    host=LocalFacilityLayoutHost(stage,private_assets=True,private_asset_root=staged)
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        candidate,ops=build(before,catalog)
        checks=audit(before,candidate,catalog)
        spatial=host.service._diagnose_spatial(host.principal(),'site-local',candidate)
        write(OUT/'spatial.json',spatial)
        host.service._require_spatially_valid(spatial)
        receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))
        audit(before,receipt['layout'],catalog)
    finally: host.close()
    write(OUT/'operations.json',ops)
    write(OUT/'candidate.json',receipt['layout'])
    write(OUT/'report.json',dict(status='validated',baseRevision=layout_revision(before),layoutHashes=saved_hashes(),
        artifacts=[rel],assetHashes={rel:hashlib.sha256((staged/rel).read_bytes()).hexdigest(),
            source:hashlib.sha256((ROOT/source).read_bytes()).hexdigest()},checks=checks))
    profile=json.loads((ROOT/'.runtime/private-gym-pool-20261008/profile.json').read_text())
    profile.update(profileId='private-gym-art-visibility',origin='http://127.0.0.1:8564',dataRoot=str(OUT),
        backendId=str(uuid.uuid4()),storeId=str(uuid.uuid4()))
    write(OUT/'profile.json',profile)
    def shot(name,p,t):
        return dict(name=name,position=dict(zip(('x','y','z'),p)),target=dict(zip(('x','y','z'),t)),thresholds=dict(detail=1000))
    eagle=shot('03-shower-eagle',(56,1.65,19.1),(51.28,1.5,19.1))
    write(OUT/'review-config.json',dict(profileId=profile['profileId'],minimumAssetMeshes=1,requiredAssets=[ASSET],
        requiredWallArt=[SLOGAN,'apex-interior-h05'],shots=[
            shot('01-pool-slogan',(43,1.65,-7),(43,1.8,0)),
            shot('02-pool-slogan-oblique',(38,3,-7),(43,1.8,0)),eagle,
            shot('04-opposite-basketball',(55.5,1.65,19.4),(60,1.8,19.5)),
            shot('05-shower-room-context',(55.6,7,19.2),(55.6,0,19.3))],
        finalShot=dict(eagle,name='06-saved-shower-eagle')))
    print(json.dumps(checks))


if __name__=='__main__':
    main()
