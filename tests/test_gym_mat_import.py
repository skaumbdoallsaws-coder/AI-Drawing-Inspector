"""Focused checks for the gym batch's lossless empty-compound repair."""
import json
from pathlib import Path
import struct
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import import_gym_mat_assets as batch


def glb(document, binary=b'geometry-buffer!'):
    encoded = json.dumps(document).encode()
    encoded += b' ' * (-len(encoded) % 4)
    binary += b'\0' * (-len(binary) % 4)
    tail = struct.pack('<II', len(binary), 0x004E4942) + binary
    return struct.pack('<IIIII', 0x46546C67, 2, 20+len(encoded)+len(tail), len(encoded), 0x4E4F534A) + encoded + tail


def fixture(tmp_path, monkeypatch, empty_position=-1):
    monkeypatch.setattr(batch, 'ROOT', tmp_path)
    monkeypatch.setattr(batch, 'OUT', tmp_path / 'batch')
    source = tmp_path / 'asset/model.glb'
    source.parent.mkdir()
    source.write_bytes(glb(dict(
        meshes=[{'name': 'empty', 'primitives': [{'attributes': {'POSITION': empty_position}, 'indices': -1}]},
                {'name': 'surface', 'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1}]}],
        nodes=[{'mesh': 0, 'children': [1]}, {'mesh': 1, 'translation': [1, 2, 3]}],
        accessors=[{'type': 'VEC3'}, {'type': 'SCALAR'}])))
    batch.common.write(batch.OUT / 'inventory.json', [{'assetId': 'test', 'target': 'asset'}])
    batch.common.write(batch.OUT / 'test-conversion.json', dict(status='converted', artifact='asset/model.glb',
        sourceFaces=3, meshedFaces=3, negligibleFaces=[]))
    return source


def test_empty_compound_repair_preserves_binary_and_remaps_nodes(tmp_path, monkeypatch):
    source = fixture(tmp_path, monkeypatch)
    before = source.read_bytes()
    batch.repair_empty_compounds(set())
    receipt = batch.read(batch.OUT / 'test-conversion.json')
    after = (tmp_path / receipt['artifact']).read_bytes()
    original_size = struct.unpack_from('<I', before, 12)[0]
    repaired_size = struct.unpack_from('<I', after, 12)[0]
    assert before[20+original_size:] == after[20+repaired_size:]
    document = json.loads(after[20:20+repaired_size])
    assert len(document['meshes']) == 1
    assert document['meshes'][0]['name'] == 'surface'
    assert document['nodes'] == [{'children': [1]}, {'mesh': 0, 'translation': [1, 2, 3]}]
    assert source.read_bytes() == before
    assert receipt['emptyCompoundRepair']['binaryGeometryUnchanged']
    batch.repair_empty_compounds(set())
    assert batch.read(batch.OUT / 'test-conversion.json') == receipt


def test_malformed_real_geometry_is_not_discarded(tmp_path, monkeypatch):
    source = fixture(tmp_path, monkeypatch, empty_position=-2)
    with pytest.raises(AssertionError):
        batch.repair_empty_compounds(set())
    assert not source.with_name('model-valid.glb').exists()
    assert batch.read(batch.OUT / 'test-conversion.json')['artifact'] == 'asset/model.glb'


def test_repair_requires_complete_cad_face_coverage(tmp_path, monkeypatch):
    source = fixture(tmp_path, monkeypatch)
    receipt = batch.read(batch.OUT / 'test-conversion.json')
    receipt['meshedFaces'] = 2
    batch.common.write(batch.OUT / 'test-conversion.json', receipt)
    with pytest.raises(AssertionError):
        batch.repair_empty_compounds(set())
    assert not source.with_name('model-valid.glb').exists()


def test_selected_assets_only(tmp_path, monkeypatch):
    source = fixture(tmp_path, monkeypatch)
    batch.repair_empty_compounds({'another-asset'})
    assert not source.with_name('model-valid.glb').exists()
