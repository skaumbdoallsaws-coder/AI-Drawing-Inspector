import json
import struct

import numpy as np
import pytest

from tools import add_factory02_conference_rooms as conference
from tools.render_industrial_asset_software_thumbnail import (
    _position_view, _scene_instances, _transform_points,
)


@pytest.mark.parametrize('width', [5.6, 7.1])
def test_screen_mount_preserves_fractional_offsets_and_catalog_bounds(tmp_path, monkeypatch, width):
    source = conference.box_glb(.9144, .0635, .5715)
    (tmp_path / 'screen.glb').write_bytes(source)
    monkeypatch.setattr(conference, 'ROOT', tmp_path)
    screen = dict(artifact='screen.glb', sourceToCanonical=conference.IDENTITY,
                  dimensions=dict(width=.9144, height=.5715, depth=.0635))
    data, depth, shift = conference.presentation_wall(width, screen)
    length = struct.unpack_from('<I', data, 12)[0]
    doc = json.loads(data[20:20 + length])
    wall, display = [], []
    for mesh_id, matrix in _scene_instances(doc, np.eye(4)):
        mesh = doc['meshes'][mesh_id]
        points = wall if mesh['name'] == 'Presentation wall' else display
        for primitive in mesh['primitives']:
            points.append(_transform_points(_position_view(
                data, 28 + length, doc, primitive['attributes']['POSITION']), matrix))
    wall, display = np.concatenate(wall), np.concatenate(display)
    assert display[:, 1].min() == pytest.approx(1.30)
    assert display[:, 1].max() == pytest.approx(1.8715)
    assert wall[:, 2].min() - display[:, 2].max() == pytest.approx(.02)
    all_points = np.concatenate([wall, display])
    assert np.ptp(all_points, axis=0) == pytest.approx([width, 3, depth])
    assert (all_points[:, 2].min() + all_points[:, 2].max()) / 2 + shift == pytest.approx(0, abs=1e-7)
    assert (tmp_path / 'screen.glb').read_bytes() == source
    for material in doc['materials'][:-1]:
        assert material['extras']['facilityArtwork'] is True
        assert 'baseColorTexture' in material['pbrMetallicRoughness']
