import base64
from copy import deepcopy
import json
import struct

import pytest

from tools.gym_theme_wall import theme_wall, linear_rgb
from tools.style_private_gym_apex_court import audit, change_document

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==')


@pytest.mark.parametrize('face', [-1, 1])
@pytest.mark.parametrize('logo', [False, True])
def test_wall_envelope_alpha_and_lights(face, logo):
    raw = theme_wall(dict(width=19.6, depth=.3, height=5.5), PNG, face=face, logo_png=PNG if logo else None)
    size = struct.unpack_from('<I', raw, 12)[0]
    doc = json.loads(raw[20:20 + size])
    positions = [doc['accessors'][p['attributes']['POSITION']] for m in doc['meshes'] for p in m['primitives']]
    for index, expected in enumerate([(-9.8, 9.8), (0, 5.5), (-.15, .15)]):
        assert min(a['min'][index] for a in positions) == pytest.approx(expected[0])
        assert max(a['max'][index] for a in positions) == pytest.approx(expected[1])
    artwork = [m for m in doc['materials'] if m.get('extras', {}).get('facilityArtwork')]
    assert len(artwork) == (2 if logo else 1)
    assert all(m['alphaMode'] == 'BLEND' for m in artwork)
    assert raw.count(PNG) == (2 if logo else 1)
    lights = doc['extensions']['KHR_lights_punctual']['lights']
    assert len(lights) == 2 and all(l['type'] == 'spot' and l['range'] == 7 for l in lights)
    gold = next(m for m in doc['materials'] if m['name'].startswith('APEX metallic'))
    assert gold['pbrMetallicRoughness']['baseColorFactor'] == linear_rgb('#c99b39') + [1]
    assert gold['extras']['facilityAuthoredFinish'] is True
    player_mesh = next(m for m in doc['meshes'] if m['name'] == 'Transparent player artwork')
    player = doc['accessors'][player_mesh['primitives'][0]['attributes']['POSITION']]
    assert (player['min'][0] + player['max'][0]) / 2 == 0
    assert (player['min'][1] + player['max'][1]) / 2 == 2.75


def test_revision_updates_preserve_geometry_and_external_color():
    replacements = {str(i): dict(assetId='new-' + str(i), assetDefinitionRevision='new-rev',
                                appearance=dict(color='#292d32')) for i in range(3)}
    before = dict(placements=[dict(placementId=str(i), assetId='old-' + str(i),
        assetDefinitionRevision='old-rev', transform=dict(position=dict(x=i, y=0, z=0))) for i in range(3)],
        extensions=dict(facilityPerimeterWalls=dict(settings=dict(exteriorFinish=dict(wallFaces=[
            dict(placementId='0', assetDefinitionRevision='old-rev', color='#55585a', face='positive_z')])))),
        floorMarkings=[dict(markingId='court-line')], updatedAt='before')
    before['placements'].append(dict(placementId='hoop', transform=dict(position=dict(x=0, y=3.05, z=0)),
        snapRelationship=dict(family='wall_attachment', supportPlacementId='0', supportAssetDefinitionRevision='old-rev')))
    candidate = change_document(before, replacements)
    assert candidate['placements'][-1]['snapRelationship']['supportAssetDefinitionRevision'] == 'new-rev'
    assert candidate['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['wallFaces'][0]['color'] == '#55585a'
    audit(before, candidate, replacements)
    tampered = deepcopy(candidate)
    tampered['placements'][-1]['transform']['position']['y'] += .1
    with pytest.raises(AssertionError):
        audit(before, tampered, replacements)


def test_invalid_face_is_rejected():
    with pytest.raises(AssertionError):
        theme_wall(dict(width=19.6, depth=.3, height=5.5), PNG, face=0)


def test_branding_only_back_wall_has_no_player_image():
    raw = theme_wall(dict(width=19.6, depth=.3, height=5.5), None, face=-1, logo_png=PNG)
    size = struct.unpack_from('<I', raw, 12)[0]
    doc = json.loads(raw[20:20 + size])
    assert len(doc['images']) == 1
    assert not any(m['name'] == 'Transparent player artwork' for m in doc['meshes'])
    assert any(m['name'] == 'APEX GYM - HIGHER EVERYDAY' for m in doc['meshes'])
    assert len(doc['extensions']['KHR_lights_punctual']['lights']) == 2


def test_centered_branding_is_above_the_backboard_within_the_existing_wall():
    raw = theme_wall(dict(width=19.6, depth=.3, height=5.5), None, face=-1,
                     logo_png=PNG, logo_box=(0, 4.525, 4.95, 1.65))
    size = struct.unpack_from('<I', raw, 12)[0]
    doc = json.loads(raw[20:20 + size])
    mesh = next(m for m in doc['meshes'] if m['name'] == 'APEX GYM - HIGHER EVERYDAY')
    bounds = doc['accessors'][mesh['primitives'][0]['attributes']['POSITION']]
    assert (bounds['min'][0] + bounds['max'][0]) / 2 == 0
    assert bounds['min'][1] == pytest.approx(3.7)
    assert bounds['max'][1] == pytest.approx(5.35)
