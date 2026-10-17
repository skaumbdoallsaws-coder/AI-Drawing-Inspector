"""Build a same-envelope wall with alpha artwork, metallic trim and local lights."""
import json
import math
import struct

from ai_inspector.industrial_assets.artifacts import build_aabb_proxy_glb, inspect_glb


def linear_rgb(value):
    channels = [int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]


def theme_wall(dimensions, player_png, *, face, logo_png=None, logo_box=None):
    w, d, h = [dimensions[k] for k in ('width', 'depth', 'height')]
    assert face in (-1, 1) and w > 10 and h == 5.5
    raw = build_aabb_proxy_glb(dict(minimum=dict(x=-w / 2, y=0, z=-d / 2),
                                   maximum=dict(x=w / 2, y=h, z=d / 2)))
    size = struct.unpack_from('<I', raw, 12)[0]
    doc = json.loads(raw[20:20 + size])
    data = bytearray(raw[28 + size:])
    doc['extensionsUsed'] = ['KHR_materials_unlit', 'KHR_lights_punctual']
    doc['extensions'] = {'KHR_lights_punctual': {'lights': []}}
    doc['images'], doc['textures'] = [], []
    doc['samplers'] = [dict(magFilter=9729, minFilter=9987, wrapS=33071, wrapT=33071)]
    materials = doc.setdefault('materials', [])

    def view(payload, target=None):
        data.extend(b'\0' * (-len(data) % 4))
        record = dict(buffer=0, byteOffset=len(data), byteLength=len(payload))
        if target:
            record['target'] = target
        data.extend(payload)
        doc['bufferViews'].append(record)
        return len(doc['bufferViews']) - 1

    def floats(values, kind, count, minimum=None, maximum=None):
        record = dict(bufferView=view(struct.pack('<' + 'f' * len(values), *values), 34962),
                      componentType=5126, count=count, type=kind)
        if minimum is not None:
            record.update(min=minimum, max=maximum)
        doc['accessors'].append(record)
        return len(doc['accessors']) - 1

    def material(name, color, metallic=0, roughness=.7, emissive=None):
        record = dict(name=name, doubleSided=False,
                      extras=dict(facilityAuthoredFinish=True),
                      pbrMetallicRoughness=dict(baseColorFactor=linear_rgb(color) + [1],
                                               metallicFactor=metallic, roughnessFactor=roughness))
        if emissive:
            record['emissiveFactor'] = linear_rgb(emissive)
        materials.append(record)
        return len(materials) - 1

    gold = material('APEX metallic gold #C99B39', '#c99b39', .65, .38)
    lamp = material('Warm linear wall light', '#ffe0a8', .1, .45, '#ffe0a8')

    def quad(name, bounds, mat, texture=False):
        x0, y0, x1, y1 = bounds
        assert -w / 2 <= x0 < x1 <= w / 2 and 0 <= y0 < y1 <= h
        left, right = (x0, x1) if face == 1 else (x1, x0)
        z = face * d / 2
        pos = floats([left, y0, z, right, y0, z, right, y1, z, left, y1, z],
                     'VEC3', 4, [x0, y0, z], [x1, y1, z])
        attrs = dict(POSITION=pos, NORMAL=floats([0, 0, face] * 4, 'VEC3', 4))
        if texture:
            attrs['TEXCOORD_0'] = floats([0, 1, 1, 1, 1, 0, 0, 0], 'VEC2', 4)
        doc['accessors'].append(dict(bufferView=view(struct.pack('<6H', 0, 1, 2, 0, 2, 3), 34963),
                                    componentType=5123, count=6, type='SCALAR', min=[0], max=[3]))
        mesh = len(doc['meshes'])
        doc['meshes'].append(dict(name=name, primitives=[dict(attributes=attrs,
            indices=len(doc['accessors']) - 1, material=mat, mode=4)]))
        node = len(doc['nodes'])
        doc['nodes'].append(dict(name=name, mesh=mesh))
        doc['scenes'][0]['nodes'].append(node)

    def artwork(name, png, cx, cy, max_width, max_height):
        assert png.startswith(b'\x89PNG\r\n\x1a\n')
        width, height = struct.unpack('>II', png[16:24])
        scale = min(max_width / width, max_height / height)
        aw, ah = width * scale, height * scale
        index = len(doc['images'])
        doc['images'].append(dict(bufferView=view(png), mimeType='image/png'))
        doc['textures'].append(dict(sampler=0, source=index))
        materials.append(dict(name=name, alphaMode='BLEND', doubleSided=False,
            extras=dict(facilityArtwork=True), extensions={'KHR_materials_unlit': {}},
            pbrMetallicRoughness=dict(baseColorFactor=[1, 1, 1, 1],
                baseColorTexture=dict(index=index), metallicFactor=0, roughnessFactor=1)))
        quad(name, (cx - aw / 2, cy - ah / 2, cx + aw / 2, cy + ah / 2), len(materials) - 1, True)

    if player_png is not None:
        artwork('Transparent player artwork', player_png, 0, h / 2, 5.3, 4.65)
    if logo_png:
        artwork('APEX GYM - HIGHER EVERYDAY', logo_png, *(logo_box or (5.3, 3.0, 7.0, 2.6)))
    for y in (.32, 5.18):
        quad('Continuous gold accent', (-w / 2 + .08, y, w / 2 - .08, y + .032), gold)
    for x in (-w / 2 + .32, w / 2 - .35):
        quad('Gold corner detail', (x, .32, x + .032, 5.212), gold)
    for x in (-w * .3, w * .3):
        quad('Warm linear luminaire', (x - 1.2, 5.05, x + 1.2, 5.08), lamp)
        lights = doc['extensions']['KHR_lights_punctual']['lights']
        light_index = len(lights)
        lights.append(dict(name='Warm wall wash', type='spot', color=[1, .78, .52],
                           intensity=8, range=7, spot=dict(innerConeAngle=.15, outerConeAngle=.95)))
        angle = math.atan2(-1, face * .2)
        node = len(doc['nodes'])
        doc['nodes'].append(dict(name='Warm wall wash', translation=[x, 5.08, face * (d / 2 + .4)],
            rotation=[math.sin(angle / 2), 0, 0, math.cos(angle / 2)],
            extensions={'KHR_lights_punctual': dict(light=light_index)}))
        doc['scenes'][0]['nodes'].append(node)
    doc['asset']['generator'] = 'InspectorPro APEX court finish'
    data.extend(b'\0' * (-len(data) % 4))
    doc['buffers'][0]['byteLength'] = len(data)
    encoded = json.dumps(doc, separators=(',', ':')).encode('ascii')
    encoded += b' ' * (-len(encoded) % 4)
    result = struct.pack('<4sII', b'glTF', 2, 28 + len(encoded) + len(data))
    result += struct.pack('<I4s', len(encoded), b'JSON') + encoded
    result += struct.pack('<I4s', len(data), b'BIN\0') + data
    inspect_glb(result)
    assert (player_png is None or player_png in result) and (logo_png is None or logo_png in result)
    return result
