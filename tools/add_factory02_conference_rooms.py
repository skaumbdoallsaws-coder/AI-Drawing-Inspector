"""Stage and verify three furnished conference rooms in Factory 02's annex."""
from copy import deepcopy
import argparse
import hashlib
import json
import math
from pathlib import Path
from shutil import copytree
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from shapely.geometry import LineString,box
from shapely.ops import unary_union
from ai_inspector.facility_layout.authority_repository import _native_fs_path,RevisionedAuthorityRepository
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost,PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.industrial_assets.artifacts import build_aabb_proxy_glb,inspect_glb
from tools.add_factory02_parking_office import boundary,hashes,write_json,verify_native_candidate
from tools.audit_independent_factory_layer2 import footprint
from tools.brand_factory02_walls import branded_glb

STORE=ROOT/'.runtime/facility-layout'
IMPORT=ROOT/'.runtime/conference-import-20261003'
LAYOUT='fl-independent-factory-20260928'
RELATIVE=Path('layouts/local/site-local/layouts')/(LAYOUT+'.json')
BASE='7cda8a31e3f728d02d3f7a39ea841c3952bf2e1341ac6671ad269182ffd6b1f8'
CHAIR='asset-chair-black'
TABLE='asset-breakroom-conference-table'
SCREEN='asset-breakroom-conference-screen'
REPLACED='pl-lunchroom-wall-north'
ROOMS=[dict(key='boardroom',label='Conference 01 - 12 Seats',bounds=(302,64,309.5,74.2),seats=12,door=303.2),
       dict(key='meeting-a',label='Conference 02 - 8 Seats',bounds=(309.7,64,315.7,71),seats=8,door=310.9),
       dict(key='meeting-b',label='Conference 03 - 8 Seats',bounds=(315.9,64,321.9,71),seats=8,door=317.1)]
IDENTITY=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def box_glb(width,depth,height):
    return build_aabb_proxy_glb(dict(minimum=dict(x=-width/2,y=0,z=-depth/2),
        maximum=dict(x=width/2,y=height,z=depth/2)))


def presentation_wall(width,screen):
    # Keep the original screen geometry/materials within a floor-supported wall assembly.
    raw=(ROOT/screen['artifact']).read_bytes();size=struct.unpack_from('<I',raw,12)[0]
    doc=json.loads(raw[20:20+size]);data=bytearray(raw[28+size:])
    assert not any(doc.get(k) for k in ['animations','skins','images','textures'])
    wall=box_glb(width,.18,3);length=struct.unpack_from('<I',wall,12)[0]
    part=json.loads(wall[20:20+length]);binary=wall[28+length:]
    view_offset=len(doc['bufferViews']);accessor_offset=len(doc['accessors'])
    data.extend(b'\0'*(-len(data)%4));binary_offset=len(data);data.extend(binary)
    for view in part['bufferViews']:
        view['byteOffset']=view.get('byteOffset',0)+binary_offset
        doc['bufferViews'].append(view)
    for accessor in part['accessors']:
        accessor['bufferView']+=view_offset;doc['accessors'].append(accessor)
    doc.setdefault('materials',[]).append(dict(name='Conference presentation wall',
        pbrMetallicRoughness=dict(baseColorFactor=[.78,.86,.88,1],metallicFactor=0,roughnessFactor=1)))
    primitive=part['meshes'][0]['primitives'][0]
    primitive['attributes']={k:v+accessor_offset for k,v in primitive['attributes'].items()}
    primitive['indices']+=accessor_offset;primitive['material']=len(doc['materials'])-1
    mesh=len(doc['meshes']);doc['meshes'].append(dict(name='Presentation wall',primitives=[primitive]))
    # A constant-color texture keeps the screen's black face distinct in neutral view,
    # through the existing artwork material policy rather than a global viewer change.
    from io import BytesIO
    from PIL import Image
    image=BytesIO();Image.new('RGB',(1,1),'white').save(image,format='PNG')
    def append_view(payload,target=None):
        data.extend(b'\0'*(-len(data)%4))
        view=dict(buffer=0,byteOffset=len(data),byteLength=len(payload))
        if target:view['target']=target
        data.extend(payload);doc['bufferViews'].append(view);return len(doc['bufferViews'])-1
    doc['images']=[dict(bufferView=append_view(image.getvalue()),mimeType='image/png')]
    doc['textures']=[dict(source=0)]
    for material in doc['materials'][:-1]:
        material.setdefault('pbrMetallicRoughness',{})['baseColorTexture']=dict(index=0)
        material['extras']=dict(facilityArtwork=True)
    for screen_mesh in doc['meshes'][:-1]:
        for p in screen_mesh['primitives']:
            count=doc['accessors'][p['attributes']['POSITION']]['count']
            doc['accessors'].append(dict(bufferView=append_view(b'\0'*(count*8),34962),componentType=5126,count=count,type='VEC2'))
            p['attributes']['TEXCOORD_0']=len(doc['accessors'])-1
    wall_node=len(doc['nodes']);doc['nodes'].append(dict(mesh=mesh,name='Presentation wall'))
    import numpy as np
    source=np.array(screen['sourceToCanonical']).reshape(4,4,order='F')
    turn=np.diag([-1.,1.,-1.,1.]);turn[1,3]=1.30;turn[2,3]=-.09-.02-screen['dimensions']['depth']/2
    child=list(doc['scenes'][doc.get('scene',0)]['nodes'])
    parent=len(doc['nodes']);doc['nodes'].append(dict(name='Wall-mounted 40-inch display',
        matrix=(turn@source).flatten(order='F').tolist(),children=child))
    doc['scene']=0;doc['scenes']=[dict(nodes=[wall_node,parent])]
    doc['buffers'][0]['byteLength']=len(data)
    encoded=json.dumps(doc,separators=(',',':')).encode('ascii');encoded+=b' '*(-len(encoded)%4)
    result=struct.pack('<4sII',b'glTF',2,28+len(encoded)+len(data))
    result+=struct.pack('<I4s',len(encoded),b'JSON')+encoded+struct.pack('<I4s',len(data),b'BIN\0')+data
    inspect_glb(result)
    depth=.18+.02+screen['dimensions']['depth'];center_shift=(depth-.18)/2
    # Check transformed vertices, not just declared bounds: integer matrices can
    # silently discard fractional mounting offsets and embed the display in the wall.
    from tools.render_industrial_asset_software_thumbnail import _scene_instances,_position_view,_transform_points
    screen_points=[];wall_points=[]
    for mesh_id,matrix in _scene_instances(doc,np.eye(4)):
        points=wall_points if mesh_id==mesh else screen_points
        for p in doc['meshes'][mesh_id]['primitives']:
            points.append(_transform_points(_position_view(result,28+len(encoded),doc,p['attributes']['POSITION']),matrix))
    screen_points=np.concatenate(screen_points);wall_points=np.concatenate(wall_points)
    assert abs(screen_points[:,1].min()-1.30)<1e-6,'Incorrect display mounting height'
    gap=wall_points[:,2].min()-screen_points[:,2].max()
    assert abs(gap-.02)<1e-6,'Display is not in front of the presentation wall'
    points=np.concatenate([screen_points,wall_points])
    assert np.allclose(np.ptp(points,axis=0),[width,3,depth],atol=1e-6,rtol=0),'Incorrect assembly bounds'
    return result,depth,center_shift


def walls():
    panels=[('cafe-left',(300.03464,60.82,312.25,61)),('cafe-right',(314.25,60.82,334,61))]
    for room in ROOMS:
        key=room['key'];x0,z0,x1,z1=room['bounds'];door=room['door']
        panels.extend([(key+'-west',(x0,z0,x0+.18,z1)),
            (key+'-east',(x1-.18,z0,x1,z1)),
            (key+'-front-left',(x0+.20,z0,door-.7,z0+.18)),
            (key+'-front-right',(door+.7,z0,x1-.20,z0+.18))])
    return panels


def prepare_assets(out,library):
    entries=json.loads((IMPORT/'entries.json').read_text());source_hashes=json.loads((IMPORT/'before-hashes.json').read_text())['sources']
    for entry in entries:
        assert digest(Path(r'C:/Users/might/Downloads/conference room')/entry['source']['fileName'])==source_hashes[entry['source']['fileName']]
        evidence=json.loads(((ROOT/entry['artifact']).parent/'thumbnail-evidence.json').read_text())
        assert evidence['passed'] and evidence['source']['sha256']==digest(ROOT/entry['artifact'])
    library['assets'].extend(entries);screen=next(a for a in entries if a['assetId']==SCREEN)
    specs=[];artifacts=[];locations=[]
    for key,b in walls():
        x0,z0,x1,z1=b;w,d=x1-x0,z1-z0
        assert w>.001 and d>.001
        settings=dict(width=7,centerX=0,centerY=2,face=-1)
        data=branded_glb(dict(width=w,depth=d,height=3),settings)[0] if key=='cafe-left' else box_glb(w,d,3)
        specs.append((key,w,d,data,IDENTITY))
        locations.append(dict(key=key,x=(x0+x1)/2,z=(z0+z1)/2))
    for room in ROOMS:
        x0,z0,x1,z1=room['bounds'];key=room['key']+'-screen-wall'
        data,d,shift=presentation_wall(x1-x0-.4,screen)
        matrix=IDENTITY.copy();matrix[14]=shift
        specs.append((key,x1-x0-.4,d,data,matrix))
        locations.append(dict(key=key,x=(x0+x1)/2,z=z1-.09-shift))
    for key,w,d,data,matrix in specs:
        artifact='generated/industrial_assets/factory02_conference/'+key+'/model.glb'
        dest=out/'staged-project'/artifact;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
        artifacts.append(artifact)
        library['assets'].append(dict(assetId='asset-factory02-conference-'+key,
            displayName='Conference '+key.replace('-',' ').title(),category='Building Structures',
            artifact=artifact,dimensions=dict(width=w,depth=d,height=3),sourceToCanonical=matrix,
            description='Authored concept partition'+(' with the supplied 40-inch screen mounted at 1.30 m.' if 'screen-wall' in key else '.'),
            tags=['wall','perimeter','conference'],source=dict(kind='authored-primitive',generator=Path(__file__).name,
                screenSourceSha256=screen['source']['sha256'] if 'screen-wall' in key else None)))
    assert len({a['assetId'] for a in library['assets']})==len(library['assets'])
    library['summary']['total']=len(library['assets'])
    return artifacts,locations


def operations(catalog,locations,chair_scale):
    ops=[dict(op='delete_placement',placementId=REPLACED)]
    seats=[];tables=[]
    def place(key,aid,x,z,yaw=0,color=None,locked=False,scale=1):
        a=catalog[aid];half=math.radians(yaw)/2
        p=dict(placementId='pl-conference-'+key,assetId=aid,assetDefinitionRevision=a['assetDefinitionRevision'],
            transform=dict(position=dict(x=x,y=0,z=z),quaternion=dict(x=0,y=math.sin(half),z=0,w=math.cos(half)),scale=scale),
            positionMode='locked' if locked else 'manual',snapRelationship=None,
            metadata=dict(instanceLabel=key.replace('-',' ').title(),inputMethod='independent-authoring'))
        if color:p['appearance']=dict(color=color)
        ops.append(dict(op='place_asset',placement=p));return p
    def zone(key,label,b,color):
        ops.append(dict(op='add_zone',zone=dict(zoneId='zn-conference-'+key,label=label,zoneType='workcell',
            boundary=boundary(b),floorElevation=0,anchors=[],evidence=[],extensions=dict(style=dict(fillColor=color)))))
    def paint(key,b,color,text=''):
        x0,z0,x1,z1=b
        ops.append(dict(op='add_floor_marking',floorMarking=dict(markingId='fm-conference-'+key,
            markingType='floor_text' if text else 'solid_line',label=key.replace('-',' ').title(),semanticRole='decorative',
            transform=dict(position=dict(x=(x0+x1)/2,y=.008 if text else 0,z=(z0+z1)/2),rotationDegrees=0),
            width=x1-x0,depth=z1-z0,fillColor=color,strokeColor=color,opacity=1,text=text,
            positionMode='manual',metadata=dict(authoredIn='conference_extension'),evidence=[])))
    for loc in locations:
        color='#d1dddf' if loc['key'].endswith('screen-wall') else '#e3e8e8'
        place('wall-'+loc['key'],'asset-factory02-conference-'+loc['key'],loc['x'],loc['z'],color=color,locked=True)
    zone('corridor','Conference Rooms - Shared Corridor',(300.03464,60.82,334,64),'#bbcfd5')
    # Floor is split around the route paint to avoid coplanar flicker.
    from tools.expand_factory02_lunchroom import rectangle_tiles
    routes=[('cafe-link',[(313.25,58),(313.25,62.5)],1.4),
            ('corridor',[(303.2,62.5),(320.6,62.5)],1.4)]
    for room in ROOMS:routes.append((room['key']+'-entry',[(room['door'],62.5),(room['door'],65)],1.2))
    corridors=unary_union([LineString(p).buffer(w/2,cap_style=2,join_style=2) for _,p,w in routes])
    for room in ROOMS:
        x0,z0,x1,z1=room['bounds'];cx=(x0+x1)/2;cz=(z0+z1)/2;key=room['key']
        zone(key,room['label'],room['bounds'],'#afc5cc')
        for i,b in enumerate(rectangle_tiles((x0+.18,z0+.18,x1-.18,z1-.27),[corridors])):
            paint(key+'-floor-'+str(i),b,'#dce5e7')
        count=2 if room['seats']==12 else 1
        aabb=catalog[TABLE]['definition']['geometry']['aabb']
        length=aabb['maximum']['x']-aabb['minimum']['x']
        for i in range(count):
            p=place(key+'-table-'+str(i+1),TABLE,cx,cz+(i-(count-1)/2)*(length+.03),90,color='#9faeaf')
            tables.append(p['placementId'])
        n=5 if count==2 else 3
        for side in [-1,1]:
            for i in range(n):
                x=cx+side*1.4;z=cz+(i-(n-1)/2)*1.15
                p=place(key+f'-chair-{len(seats)+1:02}',CHAIR,x,z,-side*90,color='#385d69',scale=chair_scale)
                seats.append(dict(id=p['placementId'],target=dict(x=cx,z=z)))
        end=(count*length+(count-1)*.03)/2+.6
        for sign in [-1,1]:
            z=cz+sign*end
            p=place(key+f'-chair-{len(seats)+1:02}',CHAIR,cx,z,180 if sign==1 else 0,color='#385d69',scale=chair_scale)
            seats.append(dict(id=p['placementId'],target=dict(x=cx,z=cz)))
        paint(key+'-label',(cx-1.7,z0+.42,cx+1.7,z0+.87),'#2c4854',room['label'].upper())
    for i,b in enumerate(rectangle_tiles((300.1,61,333.9,64),[corridors])):paint('corridor-floor-'+str(i),b,'#d6e1e3')
    for key,points,width in routes:
        ops.append(dict(op='add_aisle',routeId='rt-conference-'+key,aisle=dict(label=key.replace('-',' ').title(),
            centerline=[dict(x=x,y=0,z=z) for x,z in points],corridorWidth=width,aisleKind='pedestrian',
            direction='two_way',color='#62becb',clearanceEvidenceStatus='unverified')))
    return ops,dict(seats=seats,tables=tables,routes=routes,chairScale=chair_scale)


def audit(before,after,catalog,details):
    for field,key,prefix in [('placements','placementId','pl-conference-'),('zones','zoneId','zn-conference-'),
        ('routes','routeId','rt-conference-'),('floorMarkings','markingId','fm-conference-')]:
        old=[p for p in before[field] if p[key]!=REPLACED]
        new=[p for p in after[field] if not p[key].startswith(prefix)]
        assert old==new,field+' unrelated edits'
    for key in set(before)-{'placements','zones','routes','floorMarkings','updatedAt'}:assert before[key]==after[key],key
    added=[p for p in after['placements'] if p['placementId'].startswith('pl-conference-')]
    assert sum(p['assetId']==CHAIR for p in added)==28
    assert sum(p['assetId']==TABLE for p in added)==4
    assert sum(p['assetId'].endswith('screen-wall') for p in added)==3
    all_shapes={p['placementId']:footprint(p,catalog[p['assetId']]) for p in after['placements']}
    clear=unary_union([LineString(points).buffer(width/2,cap_style=2,join_style=2) for _,points,width in details['routes']])
    for p in added:
        shape=all_shapes[p['placementId']]
        assert shape.intersection(clear).area<1e-7,('corridor',p['placementId'])
        for q in after['placements']:
            if q['placementId']!=p['placementId']:
                assert shape.intersection(all_shapes[q['placementId']]).area<1e-7,(p['placementId'],q['placementId'])
    by_id={p['placementId']:p for p in added}
    for item in details['seats']:
        p=by_id[item['id']];pos=p['transform']['position'];q=p['transform']['quaternion']
        dx=item['target']['x']-pos['x'];dz=item['target']['z']-pos['z'];length=math.hypot(dx,dz)
        assert math.isclose(2*q['y']*q['w'],dx/length,abs_tol=1e-7)
        assert math.isclose(1-2*q['y']**2,dz/length,abs_tol=1e-7)
    assert clear.is_valid and clear.geom_type=='Polygon','Disconnected room access'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--chair-scale',type=float,default=1)
    parser.add_argument('--publish-assets',action='store_true')
    parser.add_argument('--publish-layout',action='store_true')
    parser.add_argument('--native-report',type=Path)
    args=parser.parse_args();out=args.output.resolve();target=STORE/RELATIVE;manifest=ROOT/PRIVATE_ASSET_MANIFEST
    if args.publish_assets or args.publish_layout:
        report=json.loads((out/'report.json').read_text());staged=out/'staged-project'
        assert target.read_bytes()==(out/'before.json').read_bytes(),'Saved layout changed'
        assert hashes(target.parent)==report['layoutHashes'],'Saved layouts changed'
        if args.publish_assets:
            assert report['status']=='validated' and manifest.read_bytes()==(out/'catalog-before.json').read_bytes()
            for artifact in report['artifacts']:
                dest=ROOT/artifact;assert not dest.exists();dest.parent.mkdir(parents=True,exist_ok=True)
                RevisionedAuthorityRepository._atomic_write(dest,(staged/artifact).read_bytes())
            RevisionedAuthorityRepository._atomic_write(manifest,(staged/PRIVATE_ASSET_MANIFEST).read_bytes())
            report['status']='assets-published'
        else:
            assert report['status']=='assets-published' and args.native_report
            assert manifest.read_bytes()==(staged/PRIVATE_ASSET_MANIFEST).read_bytes()
            for artifact in report['artifacts']:assert (ROOT/artifact).read_bytes()==(staged/artifact).read_bytes()
            candidate=json.loads((out/'candidate.json').read_text())
            verify_native_candidate(json.loads(args.native_report.read_text()),candidate,(out/'validation-store'/RELATIVE).read_bytes())
            assert layout_revision(candidate)==report['candidateRevision']
            host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
            try:
                catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
                audit(json.loads((out/'before.json').read_text()),candidate,catalog,report['details'])
                saved=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,BASE)
            finally:host.close()
            others=lambda values:{k:v for k,v in values.items() if k!=target.name}
            assert others(hashes(target.parent))==others(report['layoutHashes'])
            write_json(out/'saved.json',saved['layout'])
            report.update(status='saved',savedRevision=saved['revision'],otherLayoutsUnchanged=True)
    else:
        raw=target.read_bytes();before=json.loads(raw);assert layout_revision(before)==BASE
        out.mkdir(parents=True,exist_ok=False);(out/'before.json').write_bytes(raw)
        (out/'catalog-before.json').write_bytes(manifest.read_bytes());library=json.loads(manifest.read_text())
        artifacts,locations=prepare_assets(out,library);write_json(out/'staged-project'/PRIVATE_ASSET_MANIFEST,library)
        stage=out/'validation-store'
        copytree(_native_fs_path(STORE/'authorities'),_native_fs_path(stage/'authorities'))
        copytree(_native_fs_path(STORE/'layouts/local'),_native_fs_path(stage/'layouts/local'))
        host=LocalFacilityLayoutHost(stage,private_assets=True,private_asset_root=out/'staged-project')
        try:
            catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
            ops,details=operations(catalog,locations,args.chair_scale);write_json(out/'operations.json',ops)
            result=apply_facility_layout_operations(before,ops,base_revision=BASE)
            candidate=result['document']
            audit(before,candidate,catalog,details)
            spatial=host.service._diagnose_spatial(host.principal(),'site-local',candidate)
            write_json(out/'spatial.json',spatial);host.service._require_spatially_valid(spatial)
            saved=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,BASE)
            write_json(out/'candidate.json',saved['layout'])
            report=dict(status='validated',baseRevision=BASE,candidateRevision=saved['revision'],
                layoutHashes=hashes(target.parent),artifacts=artifacts,details=details,rooms=ROOMS,
                placementCount=len(candidate['placements']),newChairs=28,newTables=4,wallScreens=3,
                limitations=['Concept layout; acoustic, structural, egress, electrical and display readability requirements unqualified.'])
        finally:host.close()
    write_json(out/'report.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in {'layoutHashes','artifacts','details'}}))


if __name__=='__main__':main()
