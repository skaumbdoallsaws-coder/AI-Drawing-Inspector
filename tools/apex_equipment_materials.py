"""Author non-destructive, component-aware display variants of gym CAD meshes."""
from collections import defaultdict
from copy import deepcopy
from io import BytesIO
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(Path.home()/'AppData/Roaming/Python/Python314/site-packages'),
               str(ROOT/'.runtime/model-import-20261002/mesh-dependencies')]
import numpy as np
import trimesh
from tools.gym_theme_wall import linear_rgb

PALETTE = {
    'frame': ('#17191C', .15, .68),
    'upholstery': ('#35393E', 0, .88),
    'steel': ('#92999F', .72, .38),
    'gold': ('#C99B39', .65, .4),
    'rubber': ('#17191C', 0, .92),
    'marking': ('#E4E7E9', 0, .75),
    'gold_padding': ('#C99B39', 0, .82),
    'rim_orange': ('#E66722', .15, .48),
    'vehicle_paint': ('#17191C', .35, .32),
    'smoked_glass': ('#344753', .18, .22),
}


def unpack(raw):
    assert raw[:4] == b'glTF' and struct.unpack_from('<I', raw, 4)[0] == 2
    length = struct.unpack_from('<I', raw, 12)[0]
    return json.loads(raw[20:20+length]), raw[28+length:]


def pack(doc, data):
    encoded = json.dumps(doc, separators=(',', ':')).encode('utf8')
    encoded += b' ' * (-len(encoded) % 4)
    data += b'\0' * (-len(data) % 4)
    return (struct.pack('<4sII', b'glTF', 2, 28+len(encoded)+len(data)) +
            struct.pack('<I4s', len(encoded), b'JSON') + encoded +
            struct.pack('<I4s', len(data), b'BIN\0') + data)


def material(role):
    color, metal, rough = PALETTE[role]
    return dict(name='APEX '+role, doubleSided=True,
                extras=dict(facilityAuthoredFinish=True, facilityMaterialRole=role),
                pbrMetallicRoughness=dict(baseColorFactor=linear_rgb(color)+[1],
                                         metallicFactor=metal, roughnessFactor=rough))


def named_role(name):
    """Conservative labels only; explicit per-source overrides resolve ambiguity."""
    name = name.lower()
    if re.search(r'(label|decal|marking|display|tableau de bord)', name):
        return 'marking'
    if re.search(r'(knob|molette|pin_selector|pino seletor|osigurac)', name) or name == 'lock':
        return 'gold'
    if re.search(r'(grip|gaine guidon|rubber|guma|espuma|rueda|roulette|feet|cep$|polia\.sldprt)', name):
        return 'rubber'
    if re.search(r'(support|soporte|estrutura|structure|chapa|tubo|seat-fix|barrier)', name):
        return 'frame'
    if re.search(r'(assento|encosto|upholstery|cushion|back-seat|naslon za ledja|tapiz|cojin_|seat[12])', name):
        return 'upholstery'
    if re.search(r'(bolt|screw|washer|hex.?nut|locknut|bearing|cojinete|chumacera|roulement|coussinet|trilho|shaft|flecha|guide.?rod|adjusting_rod)', name):
        return 'steel'
    return 'frame'


def source_path(asset):
    imported = asset.get('visualImport', {})
    if imported.get('sourceTriangles') and imported.get('displayTriangles') != imported['sourceTriangles']:
        return ROOT/asset['artifact']
    folder = (ROOT/asset['artifact']).parent
    return next(p for p in [folder/'model_colored.glb', folder/'model_body.glb', folder/'model.glb',
                            ROOT/asset['artifact']] if p.exists())


def annotate(raw, overrides=None):
    doc, data = unpack(raw)
    assert not doc.get('textures'), 'Textured source requires a preservation adapter'
    original = deepcopy(doc.get('materials', []))
    doc['materials'] = [material(r) for r in PALETTE]
    records = []
    for i, mesh in enumerate(doc['meshes']):
        name = mesh.get('name', '')
        valid = []
        for j, primitive in enumerate(mesh['primitives']):
            key = f'{i}:{j}'
            if primitive.get('attributes', {}).get('POSITION', -1) < 0:
                records.append(dict(key=key, name=name, omitted='invalid-position-accessor'))
                continue
            override = (overrides or {}).get(key, (overrides or {}).get(str(i),
                         (overrides or {}).get('material:'+str(primitive.get('material')))))
            role = override or named_role(name)
            assert role in PALETTE
            source_material = original[primitive['material']] if 'material' in primitive else {}
            primitive['material'] = list(PALETTE).index(role)
            valid.append(primitive)
            records.append(dict(key=key, name=name, role=role,
                                basis='reviewed-component' if override else 'component-label-or-neutral-fallback',
                                sourceMaterial=source_material))
        mesh['primitives'] = valid
        if not valid:
            for node in doc['nodes']:
                if node.get('mesh') == i:node.pop('mesh')
    return pack(doc, data), records


def build_variant(asset, overrides=None):
    source = source_path(asset)
    raw = source.read_bytes()
    annotated, records = annotate(raw, overrides)
    scene = trimesh.load(BytesIO(annotated), file_type='glb', force='scene', process=False)
    groups = defaultdict(list)
    count = 0
    for node in scene.graph.nodes_geometry:
        transform, name = scene.graph[node]
        mesh = scene.geometry[name]
        assert isinstance(mesh, trimesh.Trimesh), 'Unexpected non-triangle source geometry'
        mesh = mesh.copy()
        # Material batching changes neither topology nor component placement.
        mesh.apply_transform(transform)
        role = mesh.visual.material.name.removeprefix('APEX ')
        regions = [r for r in (overrides or {}).get('regions', [])
                   if r.get('sourceRole', role) == role]
        components = [c for c in (overrides or {}).get('connectedComponents', [])
                      if c['mesh'] == name]
        if regions or components:
            canonical = np.asarray(asset['sourceToCanonical']).reshape((4,4), order='F')
            points = trimesh.transform_points(mesh.vertices, canonical)
            centers = points[mesh.faces].mean(axis=1)
            assignment = np.full(len(mesh.faces), role, dtype=object)
            if components:
                # Weld only a temporary adjacency copy; color the original faces.
                welded = mesh.copy()
                welded.merge_vertices()
                assert np.allclose(welded.triangles, mesh.triangles, atol=2e-6, rtol=0)
                islands = trimesh.graph.connected_components(welded.face_adjacency,
                            nodes=np.arange(len(mesh.faces)), min_len=1)
                for component in components:
                    matches = []
                    for faces in islands:
                        if len(faces) != component['faces']:
                            continue
                        vertices = points[mesh.faces[faces]].reshape(-1, 3)
                        bounds = np.array([vertices.min(axis=0), vertices.max(axis=0)])
                        if np.allclose(bounds, component['bounds'], atol=2e-5, rtol=0):
                            matches.append(faces)
                    assert len(matches) == 1, ('Component identity changed', component)
                    assignment[matches[0]] = component['role']
            for region in regions:
                bounds = np.array(region['bounds'])
                mask = np.all((centers >= bounds[0]) & (centers <= bounds[1]), axis=1)
                if 'cylinder' in region:
                    cylinder = region['cylinder']
                    axis = cylinder['axis']
                    assert axis in (0, 1, 2) and cylinder['radius'] > 0
                    radial = np.delete(centers - cylinder['center'], axis, axis=1)
                    mask &= np.sum(radial**2, axis=1) <= cylinder['radius']**2
                assignment[mask] = region['role']
            for selected in sorted(set(assignment)):
                part = mesh.copy()
                part.update_faces(assignment == selected)
                part.remove_unreferenced_vertices()
                groups[selected].append(part)
        else:
            groups[role].append(mesh)
        count += len(mesh.faces)
    result = trimesh.Scene()
    for role, meshes in sorted(groups.items()):
        vertices, normals, faces = [], [], []
        offset = 0
        for mesh in meshes:
            vertices.append(mesh.vertices)
            normals.append(mesh.vertex_normals)
            faces.append(mesh.faces + offset)
            offset += len(mesh.vertices)
        merged = trimesh.Trimesh(vertices=np.vstack(vertices), faces=np.vstack(faces),
                                 vertex_normals=np.vstack(normals), process=False)
        merged.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(name='APEX '+role))
        result.add_geometry(merged, node_name='APEX '+role, geom_name='APEX '+role)
    payload = result.export(file_type='glb')
    doc, data = unpack(payload)
    doc['materials'] = [material(m['name'].removeprefix('APEX ')) for m in doc['materials']]
    doc['asset']['generator'] = 'InspectorPro component material authoring (no decimation)'
    payload = pack(doc, data)
    loaded = trimesh.load(BytesIO(payload), file_type='glb', force='scene', process=False)
    prior = trimesh.load(ROOT/asset['artifact'], force='scene', process=False)
    prior_count = sum(len(prior.geometry[prior.graph[n][1]].faces) for n in prior.graph.nodes_geometry)
    assert count == prior_count, (asset['assetId'], count, prior_count)
    max_change = float(np.max(np.abs(prior.bounds-loaded.bounds)))
    assert max_change < 2e-6, (asset['assetId'], max_change)
    for role in groups:
        exported = loaded.geometry['APEX '+role]
        expected = result.geometry['APEX '+role]
        assert np.array_equal(exported.faces, expected.faces)
        assert np.allclose(exported.vertices, expected.vertices, atol=2e-6, rtol=0)
    evidence = dict(assetId=asset['assetId'], source=source.relative_to(ROOT).as_posix(),
                    sourceSha256=hashlib.sha256(raw).hexdigest(),
                    previousDisplaySha256=hashlib.sha256((ROOT/asset['artifact']).read_bytes()).hexdigest(),
                    displaySha256=hashlib.sha256(payload).hexdigest(),
                    triangleCount=count, maxBoundsChangeMeters=max_change,
                    drawGroups=len(groups), roles=sorted(groups), components=records,
                    reviewedRegions=(overrides or {}).get('regions', []),
                    reviewedComponents=(overrides or {}).get('connectedComponents', []),
                    geometryPreserved=True, originalAssetUnchanged=True)
    return payload, evidence
