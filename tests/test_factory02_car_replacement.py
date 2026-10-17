from copy import deepcopy
import json
from pathlib import Path
import pytest
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.plan_settings import shell_with_plan_boundary
from ai_inspector.facility_layout.spatial import diagnose_layout
from tools import add_factory02_employee_parking as parking
from tools import replace_factory02_parking_cars as cars


@pytest.fixture(scope='module')
def candidate():
    empty = json.loads((Path(__file__).parent / 'fixtures/facility_layout/empty_cell.json').read_text())
    empty.update(floorMarkings=[], extensions=dict(facilityPlan=dict(widthMeters=376, depthMeters=200,
        gridSpacingMeters=1.524, majorGridSpacingMeters=7.62)))
    sizes = {parking.CAR_IDS[0]: (1.846975, 4.721245, 1.395562),
             parking.CAR_IDS[1]: (2.044933, 4.762566, 1.284203), parking.STOP: (1.6, .16, .14)}
    sizes.update(dict(zip(cars.IMPORTED_ASSETS, [(1.887865, 4.758197, 1.118569),
        (2.052937, 4.777102, 1.295184), (2.246375, 4.706258, 1.215282)])))
    catalog = {}
    for aid, (w, d, h) in sizes.items():
        geometry = dict(footprintPolygons=[parking.boundary((-w/2, -d/2, w/2, d/2))],
            aabb=dict(minimum=dict(x=-w/2, y=0, z=-d/2), maximum=dict(x=w/2, y=h, z=d/2)),
            heightInterval=dict(minimumY=0, maximumY=h))
        catalog[aid] = dict(assetId=aid, displayName=aid, assetDefinitionRevision='a'*64,
            definition=dict(geometry=geometry), geometry=geometry, clearances=[])
    before = parking.apply_batches(empty, parking.operations(catalog))
    snapshot = deepcopy(before)
    ops = cars.operations(before, catalog)
    after = cars.apply_facility_layout_operations(before, ops, base_revision=layout_revision(before))['document']
    assert snapshot == before and len(ops) == 8
    return before, after, catalog


def test_four_accepted_replacements_retain_identity_and_surroundings(candidate):
    before, after, catalog = candidate
    report = cars.audit(before, after, catalog)
    assert report['replacedCars'] == 4 and report['minimumSideMarginMeters'] > .45
    assert report['modelCounts'] == {aid: 4 for aid in cars.ASSETS}
    assert report['remainingPlacementsUnchanged'] == len(before['placements']) - 4
    assert not any(p['assetId'] in cars.REJECTED_ASSETS for p in after['placements'])


@pytest.mark.parametrize('fault', ['scale', 'position', 'rotation', 'revision', 'model', 'missing',
                                 'marking', 'unrelated', 'document', 'duplicate'])
def test_audit_rejects_unapproved_changes(candidate, fault):
    before, source, catalog = candidate
    after = deepcopy(source)
    p = next(p for p in after['placements'] if p['placementId'] in cars.REPLACEMENTS)
    if fault == 'scale': p['transform']['scale'] = .9
    elif fault == 'position': p['transform']['position']['x'] += 1
    elif fault == 'rotation': p['transform']['quaternion']['y'] = .5
    elif fault == 'revision': p['assetDefinitionRevision'] = 'b'*64
    elif fault == 'model': p['assetId'] = parking.CAR_IDS[0]
    elif fault == 'missing': after['placements'].remove(p)
    elif fault == 'duplicate': after['placements'].append(deepcopy(p))
    elif fault == 'marking': after['floorMarkings'][0]['label'] = 'changed'
    elif fault == 'unrelated': next(p for p in after['placements'] if p['placementId'] not in cars.REPLACEMENTS)['transform']['scale'] = 2
    elif fault == 'document': after['displayName'] = 'changed'
    with pytest.raises(AssertionError): cars.audit(before, after, catalog)


def test_missing_or_already_replaced_target_fails(candidate):
    before, after, catalog = candidate
    with pytest.raises(AssertionError): cars.operations(after, catalog)
    before = deepcopy(before)
    before['placements'] = [p for p in before['placements'] if p['placementId'] != next(iter(cars.REPLACEMENTS))]
    with pytest.raises(KeyError): cars.operations(before, catalog)


def test_oversized_library_geometry_is_not_shrunk_to_fit(candidate):
    before, after, source = candidate
    catalog = deepcopy(source)
    catalog[cars.ASSETS[0]]['definition']['geometry']['aabb']['maximum']['x'] = 5
    with pytest.raises(AssertionError): cars.audit(before, after, catalog)


def test_spatial_validator_accepts_cars_and_rejects_obstructed_crossing(candidate):
    _, source, catalog = candidate
    def check(layout):
        return diagnose_layout(layout, list(catalog.values()), shell=shell_with_plan_boundary({'features': []}, layout))['metrics']
    result = check(source)
    assert result['placementCollisions'] == 0 and result['obstructedAisleCount'] == 0
    blocked = deepcopy(source)
    p = next(p for p in blocked['placements'] if p['placementId'] in cars.REPLACEMENTS)
    p['transform']['position'] = dict(x=339.5, y=0, z=41.3)
    assert check(blocked)['obstructedAisleCount'] > 0


@pytest.mark.parametrize('aid', cars.IMPORTED_ASSETS)
def test_private_import_canonical_ground_and_full_scale(aid):
    manifest = cars.IMPORT / 'entries.json'
    if not manifest.exists(): pytest.skip('Private user-supplied model not present')
    import numpy as np
    import trimesh
    entry = next(a for a in json.loads(manifest.read_text()) if a['assetId'] == aid)
    canonical = np.array(entry['sourceToCanonical']).reshape((4, 4), order='F')
    assert np.allclose(np.linalg.svd(canonical[:3, :3])[1], [1, 1, 1])
    def measured(path):
        scene = trimesh.load_scene(path, process=False)
        bounds = []
        for node in scene.graph.nodes_geometry:
            world, key = scene.graph[node]
            v = trimesh.transform_points(scene.geometry[key].vertices, canonical @ world)
            bounds.append([v.min(axis=0), v.max(axis=0)])
        return np.array([np.min(np.array(bounds)[:, 0], axis=0), np.max(np.array(bounds)[:, 1], axis=0)])
    full = measured((cars.ROOT / entry['artifact']).parent / 'model.glb')
    display = measured(cars.ROOT / entry['artifact'])
    assert abs(full[0, 1]) < 1e-7
    assert np.allclose(full[1]-full[0], [entry['dimensions'][k] for k in ('width', 'height', 'depth')], atol=1e-7)
    assert np.max(np.abs(full-display)) <= .003 and abs(display[0, 1]) <= .003
