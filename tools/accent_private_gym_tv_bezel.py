"""Color only the complete TV unit's bezel; retain screen and cabinetry materials."""
import argparse
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
from shutil import copytree
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from tools.apex_equipment_materials import np,trimesh,unpack,pack
from tools.import_additional_gym_assets import write,sha
from tools.build_private_gym import STORE,LAYOUT,saved_hashes
from ai_inspector.facility_layout.authority_repository import _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost,PRIVATE_ASSET_MANIFEST

OUT=ROOT/'.runtime/private-gym-tv-gold-bezel-20261010'
SOURCE='asset-gym-additional-tv-unit'
ASSET=SOURCE+'-gold-bezel'
PLACEMENT='pl-gym-gaming-complete-tv-unit'
ARTIFACT=ROOT/'generated/industrial_assets/local_library/gym-additional-tv-unit/model-gold-bezel-painted.glb'
FIXTURE_BOUNDS=(0,22,-18,-3)


def accent(raw):
    doc,data=unpack(raw)
    original=deepcopy(doc)
    index=next(i for i,m in enumerate(doc['meshes']) if m['name']=='APEX rubber')
    mesh=doc['meshes'][index]
    assert len(mesh['primitives'])==1
    primitive=mesh['primitives'][0]
    accessor=doc['accessors'][primitive['indices']]
    view=doc['bufferViews'][accessor['bufferView']]
    assert accessor['componentType']==5125 and accessor['count']==684 and not view.get('byteStride')
    indices=np.frombuffer(data,dtype='<u4',count=684,offset=view['byteOffset']+accessor.get('byteOffset',0)).reshape(-1,3)
    loaded=trimesh.load(BytesIO(raw),file_type='glb',force='scene',process=False)
    tv=loaded.geometry['APEX rubber']
    assert len(tv.faces)==228
    screen=np.flatnonzero(tv.area_faces>.2)
    assert screen.tolist()==[2,3]
    assert np.allclose(tv.triangles[screen][:,:,1],-.16215323,atol=1e-6)
    assert np.allclose(tv.triangles[screen].reshape(-1,3).min(axis=0),[-.461,-.16215323,-.3049517],atol=1e-5)
    assert np.allclose(tv.triangles[screen].reshape(-1,3).max(axis=0),[.481,-.16215323,.2270483],atol=1e-5)
    mask=np.ones(228,dtype=bool);mask[screen]=False
    gold=len(doc['materials'])
    bezel=deepcopy(next(m for m in doc['materials'] if m['name']=='APEX gold'))
    bezel['name']='APEX gold TV bezel'
    bezel['pbrMetallicRoughness'].update(metallicFactor=.15,roughnessFactor=.45)
    doc['materials'].append(bezel)
    mesh['primitives']=[]
    for rows,material in [(indices[mask],gold),(indices[~mask],primitive['material'])]:
        values=rows.ravel().astype('<u4')
        data+=b'\0'*(-len(data)%4)
        view_index=len(doc['bufferViews'])
        doc['bufferViews'].append(dict(buffer=0,byteOffset=len(data),byteLength=values.nbytes,target=34963))
        data+=values.tobytes()
        accessor_index=len(doc['accessors'])
        doc['accessors'].append(dict(bufferView=view_index,componentType=5125,count=len(values),type='SCALAR',
            min=[int(values.min())],max=[int(values.max())]))
        changed=deepcopy(primitive);changed.update(indices=accessor_index,material=material)
        mesh['primitives'].append(changed)
    doc['buffers'][0]['byteLength']=len(data)
    payload=pack(doc,data)
    assert data.startswith(unpack(raw)[1])
    for i,m in enumerate(original['meshes']):
        if i!=index: assert doc['meshes'][i]==m
    for key in ('nodes','scenes'):
        assert doc[key]==original[key]
    assert doc['materials'][:len(original['materials'])]==original['materials']
    checked=trimesh.load(BytesIO(payload),file_type='glb',force='scene',process=False)
    assert np.array_equal(loaded.bounds,checked.bounds)
    assert sum(len(m.faces) for m in loaded.geometry.values())==sum(len(m.faces) for m in checked.geometry.values())==21012
    assert np.array_equal(np.sort(np.concatenate([indices[mask],indices[~mask]]).ravel()),np.sort(indices.ravel()))
    return payload,dict(bezelTriangles=226,unchangedScreenTriangles=2,geometryPreserved=True,
        originalVertexBuffersPreserved=True,cabinetMaterialsUnchanged=True,color='#C99B39')


def audit(before,after,catalog):
    expected=deepcopy(before)
    p=next(p for p in expected['placements'] if p['placementId']==PLACEMENT)
    assert p['assetId']==SOURCE
    p.update({k:catalog[ASSET][k] for k in ('assetId','assetDefinitionRevision')})
    expected['updatedAt']=after['updatedAt']
    assert expected==after,'Unexpected change outside the television bezel asset binding'
    return dict(placementId=PLACEMENT,otherPlacementsUnchanged=len(before['placements'])-1,
        transformUnchanged=True,screenUnchanged=True,cabinetUnchanged=True)


def stage():
    OUT.mkdir(parents=True,exist_ok=True)
    path=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    raw=path.read_bytes();catalog_raw=(ROOT/PRIVATE_ASSET_MANIFEST).read_bytes()
    for name,data in [('before.json',raw),('catalog-before.json',catalog_raw)]:
        p=OUT/name
        if p.exists():assert p.read_bytes()==data,'Staged base changed'
        else:p.write_bytes(data)
    before,library=json.loads(raw),json.loads(catalog_raw)
    old=next(a for a in library['assets'] if a['assetId']==SOURCE)
    assert not any(a['assetId']==ASSET for a in library['assets'])
    payload,material_checks=accent((ROOT/old['artifact']).read_bytes())
    target=ARTIFACT
    if target.exists():assert target.read_bytes()==payload
    else:target.write_bytes(payload)
    new=deepcopy(old)
    new.update(assetId=ASSET,artifact=target.relative_to(ROOT).as_posix(),displayName=old['displayName']+' - Gold TV Bezel')
    new['description']+=' Gold television bezel only; display and cabinetry unchanged.'
    new['source']['appearanceVariantOf']=SOURCE
    new['tags']+=['gold TV bezel']
    library['assets'].append(new);library['summary']['total']=len(library['assets'])
    staged=OUT/'staged-project';write(staged/PRIVATE_ASSET_MANIFEST,library)
    validation=OUT/'validation-store'
    for rel in ['authorities','layouts/local']:
        copytree(_native_fs_path(STORE/rel),_native_fs_path(validation/rel),dirs_exist_ok=True)
    host=LocalFacilityLayoutHost(validation,private_assets=True,private_asset_root=staged)
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        assert catalog[ASSET]['definition']['geometry']==catalog[SOURCE]['definition']['geometry']
        candidate=deepcopy(before)
        p=next(p for p in candidate['placements'] if p['placementId']==PLACEMENT)
        p.update({k:catalog[ASSET][k] for k in ('assetId','assetDefinitionRevision')})
        spatial=host.service._diagnose_spatial(host.principal(),'site-local',candidate)
        write(OUT/'spatial.json',spatial);host.service._require_spatially_valid(spatial)
        candidate=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))['layout']
        checks=audit(before,candidate,catalog)
    finally:host.close()
    write(OUT/'candidate.json',candidate)
    write(OUT/'report.json',dict(status='validated',baseRevision=layout_revision(before),checks=checks,
        materialChecks=material_checks,layoutHashes=saved_hashes(),artifactSha256=sha(target),
        originalArtifact=old['artifact'],originalArtifactSha256=sha(ROOT/old['artifact'])))
    fixture=deepcopy(candidate)
    xmin,xmax,zmin,zmax=FIXTURE_BOUNDS
    fixture['placements']=[p for p in candidate['placements'] if xmin<=p['transform']['position']['x']<=xmax and zmin<=p['transform']['position']['z']<=zmax]
    finish=fixture['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']
    finish['fittedArtworks']=[];finish['wallFaces']=[]
    aids={p['assetId'] for p in fixture['placements']}
    entries={a['assetId']:a for a in library['assets'] if a['assetId'] in aids}
    write(OUT/'render-fixture.json',dict(layout=fixture,catalog=[catalog[a] for a in sorted(aids)],
        artifacts={a:dict(url='/'+e['artifact'],sourceToCanonical=e['sourceToCanonical']) for a,e in entries.items()}))
    print(json.dumps(material_checks))


def finish(phase):
    report=json.loads((OUT/'report.json').read_bytes())
    path=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    manifest=ROOT/PRIVATE_ASSET_MANIFEST
    assert path.read_bytes()==(OUT/'before.json').read_bytes(),'Saved gym changed'
    assert sha(ROOT/report['originalArtifact'])==report['originalArtifactSha256']
    assert sha(ARTIFACT)==report['artifactSha256']
    proof=json.loads((OUT/'visual-review.json').read_bytes())
    assert proof['status']=='passed' and proof['candidateSha256']==sha(OUT/'candidate.json')
    if phase=='publish':
        assert report['status']=='validated' and manifest.read_bytes()==(OUT/'catalog-before.json').read_bytes()
        write(manifest,json.loads((OUT/'staged-project'/PRIVATE_ASSET_MANIFEST).read_bytes()))
        report['status']='published'
    else:
        assert report['status']=='published' and manifest.read_bytes()==(OUT/'staged-project'/PRIVATE_ASSET_MANIFEST).read_bytes()
        host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
        try:
            catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
            before=json.loads((OUT/'before.json').read_bytes());candidate=json.loads((OUT/'candidate.json').read_bytes())
            audit(before,candidate,catalog)
            receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,report['baseRevision'])
            audit(before,receipt['layout'],catalog)
            assert json.loads(path.read_bytes())==receipt['layout']
        finally:host.close()
        write(OUT/'saved.json',receipt['layout'])
        hashes=saved_hashes()
        assert all(hashes[k]==v for k,v in report['layoutHashes'].items() if k not in (path.name,'registry.json'))
        report.update(status='saved',savedRevision=receipt['revision'],otherLayoutsUnchanged=True)
    write(OUT/'report.json',report);print(report['status'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['stage','publish','save'])
    args=parser.parse_args();stage() if args.phase=='stage' else finish(args.phase)
