from copy import deepcopy
import json
from pathlib import Path

import pytest

from ai_inspector.facility_layout.component_materials import normalize_component_materials
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from tests.test_facility_decals import document
from tests.test_facility_layout_api import _client, _layout, _placement_operation


def material():
    return dict(representation="overview", overrides=[dict(key="m1-s0", color="#C99B39", roughness=.4, metalness=.65)])


def test_published_schema_describes_component_materials():
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root/'static/contracts/facility-layout-schema-v1.json').read_text())
    contract = schema['$defs']['placement']['properties']['componentMaterials']
    assert set(contract['required']) == set(material())
    assert contract['additionalProperties'] is False
    assert contract['properties']['representation']['enum'] == ['overview', 'detail']
    overrides = contract['properties']['overrides']
    assert (overrides['minItems'], overrides['maxItems']) == (1, 512)
    finish = overrides['items']
    assert set(finish['required']) == set(material()['overrides'][0])
    assert finish['additionalProperties'] is False
    for field in ('roughness', 'metalness'):
        assert finish['properties'][field] == dict(type='number', minimum=0, maximum=1)


def test_one_occurrence_preserves_other_instances_and_geometry():
    before = document()
    first = _placement_operation()["placement"]
    second = deepcopy(first)
    second["placementId"] = "pl-other"
    before["placements"] = [first, second]
    op = dict(op="set_component_materials", placementId=first["placementId"], materials=material())
    after = apply_facility_layout_operations(before, [op])["document"]
    assert after["placements"][1] == second
    assert after["placements"][0]["transform"] == first["transform"]
    assert after["placements"][0]["componentMaterials"]["overrides"][0]["color"] == "#c99b39"
    restored = apply_facility_layout_operations(after, [dict(op, materials=None)])["document"]
    assert restored["placements"] == before["placements"]


@pytest.mark.parametrize("key,value", [("key", "../../0"), ("color", "yellow"), ("roughness", True), ("metalness", 1.1), ("roughness", float("nan"))])
def test_invalid_finish_rejected(key, value):
    v = material()
    v["overrides"][0][key] = value
    with pytest.raises(ValueError): normalize_component_materials(v)


def test_http_round_trip_and_read_only_role(tmp_path):
    client, _, shell, policy = _client(tmp_path)
    created = client.post('/api/facility-layouts/site-a', json=dict(layout=_layout(shell, policy))).json()
    placement = _placement_operation()
    op = dict(op="set_component_materials", placementId=placement["placement"]["placementId"], materials=material())
    url = '/api/facility-layouts/site-a/fl-api-cell'
    body = dict(baseRevision=created['revision'], operations=[placement, op])
    assert client.put(url, json=body, headers={'X-Test-Role':'viewer'}).status_code == 403
    response = client.put(url, json=body)
    assert response.status_code == 200, response.text
    assert client.get(url).json()['layout']['placements'][0]['componentMaterials']['overrides'][0]['color'] == '#c99b39'
