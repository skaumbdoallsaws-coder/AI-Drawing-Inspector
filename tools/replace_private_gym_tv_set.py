"""Import the requested additional-parts TV set and replace the wrong two-piece setup."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import hashlib
import json
from pathlib import Path
from shutil import copy2, copytree
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT),str(ROOT/'tools')]
from tools import import_additional_gym_assets as base
from tools.apex_equipment_materials import np, trimesh, unpack, pack, material
from tools.build_private_gym import STORE, LAYOUT, saved_hashes
from tools.add_private_gym_fitness_centre import footprint
from ai_inspector.facility_layout.authority_repository import _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations

OUT = ROOT/'.runtime/private-gym-correct-tv-20261010'
SOURCE = Path('C:/Users/might/OneDrive/Desktop/additional parts/tv unit.stl')
ASSET = 'asset-gym-additional-tv-unit'
TARGET = base.LIBRARY/'gym-additional-tv-unit'
NEW = 'pl-gym-gaming-complete-tv-unit'
OLD = {'pl-5e84906fc623a6e64c9aa17b','pl-26bc307d9c473d1d9c8e4955'}
WALL = 'pl-gym-wellness-lounge-north-left'


def convert():
    OUT.mkdir(parents=True,exist_ok=True);TARGET.mkdir(parents=True,exist_ok=True)
    if not (TARGET/SOURCE.name).exists(): copy2(SOURCE,TARGET/SOURCE.name)
    assert base.sha(SOURCE) == base.sha(TARGET/SOURCE.name)
    mesh = trimesh.load_mesh(SOURCE,process=False)
    assert len(mesh.faces) == 21812
    floor = np.all(np.abs(mesh.triangles[:,:,2]+100.78794860839844)<1e-5,axis=1)
    assert floor.sum() == 800
    assert np.allclose(np.ptp(mesh.triangles[floor].reshape(-1,3),axis=0),[400,400,0],atol=1e-4)
    mesh.update_faces(~floor);mesh.remove_unreferenced_vertices()
    original = mesh.copy()
    welded = mesh.copy();welded.merge_vertices()
    assert np.allclose(welded.triangles,mesh.triangles,atol=1e-5,rtol=0)
    islands = trimesh.graph.connected_components(welded.face_adjacency,nodes=np.arange(len(mesh.faces)),min_len=1)
    roles = np.full(len(mesh.faces),'upholstery',dtype=object)
    records = []
    for faces in islands:
        vertices = mesh.vertices[mesh.faces[faces]].reshape(-1,3)
        bounds = np.array([vertices.min(axis=0),vertices.max(axis=0)])
        role = 'upholstery'
        if len(faces) == 1656:
            assert np.allclose(sorted(np.ptp(vertices,axis=0)),[2,2,15],atol=2e-5)
            role = 'gold'
        elif len(faces) in (788,28): role = 'frame'
        elif len(faces) == 228:
            assert np.allclose(bounds[:,0],[-50.7,52.7],atol=1e-4)
            role = 'rubber'
        roles[faces] = role
        records.append(dict(faces=len(faces),bounds=bounds.tolist(),role=role))
    assert sum(r['role']=='gold' for r in records) == 4
    assert sum(r['role']=='rubber' for r in records) == 1
    mesh.apply_scale(.01)
    scene = trimesh.Scene()
    for role in sorted(set(roles)):
        part = mesh.copy();part.update_faces(roles==role);part.remove_unreferenced_vertices()
        part.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(name='APEX '+role))
        scene.add_geometry(part,node_name='APEX '+role,geom_name='APEX '+role)
    raw = scene.export(file_type='glb')
    doc,data = unpack(raw)
    doc['materials'] = [material(m['name'].removeprefix('APEX ')) for m in doc['materials']]
    raw = pack(doc,data)
    loaded = trimesh.load(BytesIO(raw),file_type='glb',force='scene',process=False)
    assert sum(len(m.faces) for m in loaded.geometry.values()) == len(mesh.faces) == 21012
    assert np.allclose(loaded.bounds,original.bounds*.01,atol=1e-6,rtol=0)
    for role in set(roles):
        expected = mesh.triangles[roles==role]
        assert np.allclose(loaded.geometry['APEX '+role].triangles,expected,atol=1e-6,rtol=0)
    (TARGET/'model.glb').write_bytes(raw)
    item = dict(assetId=ASSET,displayName='TV Unit - Complete Entertainment Set',source=SOURCE.name,
        sourceSha256=base.sha(SOURCE),format='.stl',target=TARGET.relative_to(ROOT).as_posix())
    base.write(OUT/'inventory.json',[item])
    base.write(OUT/(ASSET+'-conversion.json'),dict(status='converted',assetId=ASSET,sourceSha256=base.sha(SOURCE),
        artifact=(TARGET/'model.glb').relative_to(ROOT).as_posix(),sourceTriangles=21812,retainedTriangles=21012,
        removedPresentationFloorTriangles=800,furnitureGeometryPreserved=True,components=records,
        units=dict(sourceUnits='unspecified',assumedUnits='cm',scaleToMeters=.01,
            authority='inferred_from_complete_cabinet_and_television_proportions',requiresConfirmation=True)))
    base.write(OUT/'orientation.json',{ASSET:dict(rotation=[-90,0,0],
        note='Source Z-up, screen faces negative source Y. Centimetres are provisional, not manufacturer-verified.')})
    base.OUT = OUT
    base.prepare(OUT/'orientation.json',{ASSET})
    entry = json.loads((TARGET/'catalog-entry.json').read_bytes())
    entry['category'] = 'Office Furniture'
    entry['description'] = 'Complete owner-supplied tv unit.stl from additional parts: TV, side cabinets and shelves retained. Only presentation floor removed. Graphite/black with gold handles. Unitless source provisionally interpreted as centimetres; physical dimensions require confirmation.'
    entry['tags'] = ['TV','entertainment','shelving','lounge','apex','black and gold','concept scale']
    base.write(TARGET/'catalog-entry.json',entry)
    print(json.dumps(entry['dimensions']))


def change(before,catalog):
    old = {p['placementId']:p for p in before['placements']}
    assert OLD <= old.keys() and NEW not in old
    assert {old[pid]['assetId'] for pid in OLD} == {'asset-gym-lounge-tv-unit','asset-breakroom-conference-screen'}
    wall = old[WALL]
    assert wall['transform']['quaternion'] == dict(w=1,x=0,y=0,z=0)
    wall_box = catalog[wall['assetId']]['definition']['geometry']['aabb']
    box = catalog[ASSET]['definition']['geometry']['aabb']
    wall_face = wall['transform']['position']['z']+wall_box['minimum']['z']
    sofa = old['pl-gym-gaming-living-room-1']
    x = round(min(sofa['transform']['position']['x'],
        wall['transform']['position']['x']+wall_box['maximum']['x']-.35-box['maximum']['x']),6)
    placement = dict(placementId=NEW,assetId=ASSET,assetDefinitionRevision=catalog[ASSET]['assetDefinitionRevision'],
        positionMode='manual',snapRelationship=None,
        transform=dict(position=dict(x=x,y=0,z=round(wall_face-.04-box['maximum']['z'],6)),
            quaternion=dict(x=0,y=1,z=0,w=0),scale=1),
        metadata=dict(instanceLabel='TV Unit - Complete Gaming Room Set',room='lounge',gymRole='amenity',
            inputMethod='independent-authoring',sourceFile='additional parts/tv unit.stl',
            scaleEvidence='Unitless STL provisionally interpreted as centimetres from cabinet and TV proportions'))
    ops = [dict(op='delete_placement',placementId=pid) for pid in sorted(OLD)]
    ops.append(dict(op='place_asset',placement=placement))
    return apply_facility_layout_operations(before,ops,updated_at=datetime.now(timezone.utc).isoformat())['document']


def audit(before,after,catalog):
    expected = change(before,catalog);expected['updatedAt']=after['updatedAt']
    assert expected == after,'Unexpected change outside the two removed TV pieces and the replacement set'
    new = next(p for p in after['placements'] if p['placementId']==NEW)
    bounds = footprint(new,catalog)
    x0,z0,x1,z1 = bounds
    wall = next(p for p in before['placements'] if p['placementId']==WALL)
    wx0,wz0,wx1,wz1 = footprint(wall,catalog)
    assert wx0 < x0 < x1 < wx1-.3,'TV unit reaches hallway opening'
    assert abs(wz0-z1-.04) < 1e-5
    box=catalog[ASSET]['definition']['geometry']['aabb']
    wall_box=catalog[wall['assetId']]['definition']['geometry']['aabb']
    assert box['maximum']['y'] < wall_box['maximum']['y']
    gaps = []
    for p in after['placements']:
        pos = p['transform']['position']
        if p['placementId'] in (NEW,WALL) or pos['y']!=0 or not (0<=pos['x']<8 and -10<pos['z']<=-3): continue
        px0,pz0,px1,pz1 = footprint(p,catalog)
        gap = (max(x0-px1,px0-x1,0)**2+max(z0-pz1,pz0-z1,0)**2)**.5
        minimum = .5 if p['assetId']=='asset-gym-patio-plant' else .8
        assert gap > minimum,('TV set clearance',p['placementId'],gap)
        gaps.append(dict(placementId=p['placementId'],footprintGapMeters=gap))
    return dict(removed=sorted(OLD),added=NEW,footprint=bounds,wallGapMeters=wz0-z1,
        doorwayEdgeClearanceMeters=wx1-x1,gaps=gaps,otherPlacementsUnchanged=len(before['placements'])-2)


def stage():
    path = STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    raw = path.read_bytes();catalog_raw=(ROOT/PRIVATE_ASSET_MANIFEST).read_bytes()
    for name,data in [('before.json',raw),('catalog-before.json',catalog_raw)]:
        file=OUT/name
        if file.exists(): assert file.read_bytes()==data,'Staged base changed'
        else: file.write_bytes(data)
    before,library=json.loads(raw),json.loads(catalog_raw)
    entry=json.loads((TARGET/'catalog-entry.json').read_bytes())
    assert not any(a['assetId']==ASSET for a in library['assets'])
    library['assets'].append(entry);library['summary']['total']=len(library['assets'])
    staged=OUT/'staged-project';base.write(staged/PRIVATE_ASSET_MANIFEST,library)
    validation=OUT/'validation-store'
    for rel in ['authorities','layouts/local']:
        copytree(_native_fs_path(STORE/rel),_native_fs_path(validation/rel),dirs_exist_ok=True)
    host=LocalFacilityLayoutHost(validation,private_assets=True,private_asset_root=staged)
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        candidate=change(before,catalog)
        spatial=host.service._diagnose_spatial(host.principal(),'site-local',candidate)
        base.write(OUT/'spatial.json',spatial);host.service._require_spatially_valid(spatial)
        candidate=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))['layout']
        checks=audit(before,candidate,catalog)
    finally: host.close()
    base.write(OUT/'candidate.json',candidate)
    base.write(OUT/'report.json',dict(status='validated',baseRevision=layout_revision(before),checks=checks,
        layoutHashes=saved_hashes(),artifactSha256=base.sha(ROOT/entry['artifact']),sourceSha256=base.sha(SOURCE)))
    fixture=deepcopy(candidate)
    fixture['placements']=[p for p in candidate['placements'] if 0<=p['transform']['position']['x']<=22 and -18<=p['transform']['position']['z']<=-3]
    finish=fixture['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']
    finish['fittedArtworks']=[];finish['wallFaces']=[]
    aids={p['assetId'] for p in fixture['placements']}
    entries={a['assetId']:a for a in library['assets'] if a['assetId'] in aids}
    base.write(OUT/'render-fixture.json',dict(layout=fixture,catalog=[catalog[a] for a in sorted(aids)],
        artifacts={aid:dict(url='/'+e['artifact'],sourceToCanonical=e['sourceToCanonical']) for aid,e in entries.items()}))
    print(json.dumps(checks))


def finish(phase):
    report=json.loads((OUT/'report.json').read_bytes())
    path=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    manifest=ROOT/PRIVATE_ASSET_MANIFEST
    assert path.read_bytes()==(OUT/'before.json').read_bytes(),'Saved gym changed'
    proof=json.loads((OUT/'visual-review.json').read_bytes())
    assert proof['status']=='passed' and proof['candidateSha256']==base.sha(OUT/'candidate.json')
    entry=json.loads((TARGET/'catalog-entry.json').read_bytes())
    assert base.sha(ROOT/entry['artifact'])==report['artifactSha256']
    assert base.sha(SOURCE)==report['sourceSha256']
    if phase=='publish':
        assert report['status']=='validated'
        assert manifest.read_bytes()==(OUT/'catalog-before.json').read_bytes()
        base.write(manifest,json.loads((OUT/'staged-project'/PRIVATE_ASSET_MANIFEST).read_bytes()))
        report['status']='published'
    else:
        assert report['status']=='published'
        assert manifest.read_bytes()==(OUT/'staged-project'/PRIVATE_ASSET_MANIFEST).read_bytes()
        host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
        try:
            catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
            before=json.loads((OUT/'before.json').read_bytes());candidate=json.loads((OUT/'candidate.json').read_bytes())
            audit(before,candidate,catalog)
            receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,report['baseRevision'])
            audit(before,receipt['layout'],catalog)
            assert json.loads(path.read_bytes())==receipt['layout']
        finally:host.close()
        base.write(OUT/'saved.json',receipt['layout'])
        hashes=saved_hashes()
        assert all(hashes[k]==v for k,v in report['layoutHashes'].items() if k not in (path.name,'registry.json'))
        report.update(status='saved',savedRevision=receipt['revision'],otherLayoutsUnchanged=True)
    base.write(OUT/'report.json',report);print(report['status'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['convert','stage','publish','save'])
    args=parser.parse_args()
    {'convert':convert,'stage':stage}.get(args.phase,lambda:finish(args.phase))()
