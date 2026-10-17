from copy import deepcopy
import json
from pathlib import Path

import pytest

from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.facility_layout.validate import validate_layout
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.errors import FacilityLayoutError


def layout():
    doc = json.loads((Path(__file__).parent / 'fixtures/facility_layout/empty_cell.json').read_text())
    doc['placements'] = [dict(placementId=f'pl-{i}', assetId='asset-rack',
        assetDefinitionRevision='a' * 64, positionMode='locked' if i == 0 else 'manual',
        transform=dict(position=dict(x=i * 5, y=0, z=0),
                       quaternion=dict(x=0, y=0, z=0, w=1), scale=1),
        snapRelationship=None, metadata={}) for i in range(3)]
    return doc


def change(doc, color, ids=None):
    return apply_facility_layout_operations(doc, [dict(op='set_appearance',
        placementIds=ids or ['pl-0', 'pl-1'], color=color)])


def test_appearance_is_atomic_instance_local_revisioned_and_resettable():
    original = layout()
    before = deepcopy(original)
    result = change(original, '#2478BC')
    colored = result['document']
    assert original == before
    assert layout_revision(original) != layout_revision(colored)
    assert result['createdIds'] == []
    assert set(result['affectedIds']) == {'pl-0', 'pl-1'}
    assert colored['placements'][0]['appearance'] == {'color': '#2478bc'}
    assert colored['placements'][1]['appearance'] == {'color': '#2478bc'}
    assert colored['placements'][2] == original['placements'][2]
    assert change(colored, None)['document'] == original
    assert change(colored, '#2478bc')['document'] == colored
    assert change(original, None)['document'] == original


@pytest.mark.parametrize('color', ['red', '#abc', '#12345678', {}, 123, True, 'url(http://a)'])
def test_bad_colors_rejected_without_mutation(color):
    doc = layout()
    before = deepcopy(doc)
    with pytest.raises(FacilityLayoutError):
        change(doc, color)
    assert doc == before


@pytest.mark.parametrize('ids', [['pl-0', 'pl-missing'], ['pl-0', 'pl-0'], ['zn-zone']])
def test_bad_selection_rejects_whole_batch(ids):
    doc = layout()
    before = deepcopy(doc)
    with pytest.raises(FacilityLayoutError):
        change(doc, '#112233', ids)
    assert doc == before


@pytest.mark.parametrize('appearance', [None, {}, {'color': 'red'}, {'color': '#123456', 'opacity': .5}])
def test_save_validation_rejects_invalid_appearance(appearance):
    doc = layout()
    doc['placements'][0]['appearance'] = appearance
    with pytest.raises(FacilityLayoutError):
        validate_layout(doc)


def test_duplicate_preserves_appearance_without_modifying_source():
    doc = change(layout(), '#28866b')['document']
    result = apply_facility_layout_operations(doc, [dict(op='duplicate_placement',
        sourcePlacementId='pl-1', newPlacementId='pl-copy', position=dict(x=20, y=0, z=0))])
    duplicate = next(p for p in result['document']['placements'] if p['placementId'] == 'pl-copy')
    assert duplicate['appearance'] == {'color': '#28866b'}
