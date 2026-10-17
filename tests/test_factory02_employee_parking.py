from copy import deepcopy
import json
from pathlib import Path
import pytest
from ai_inspector.facility_layout.plan_settings import shell_with_plan_boundary
from ai_inspector.facility_layout.spatial import diagnose_layout
from tools import add_factory02_employee_parking as parking


@pytest.fixture(scope='module')
def candidate():
    before = json.loads((Path(__file__).parent / 'fixtures/facility_layout/empty_cell.json').read_text())
    before.update(floorMarkings=[], extensions=dict(facilityPlan=dict(widthMeters=376, depthMeters=200,
        gridSpacingMeters=1.524, majorGridSpacingMeters=7.62)))
    catalog = {}
    sizes = {parking.CAR_IDS[0]: (1.846975, 4.721245, 1.395562),
             parking.CAR_IDS[1]: (2.044933, 4.762566, 1.284203), parking.STOP: (1.6, .16, .14)}
    for aid, (w, d, h) in sizes.items():
        g = dict(footprintPolygons=[parking.boundary((-w/2, -d/2, w/2, d/2))], heightInterval=dict(minimumY=0, maximumY=h))
        catalog[aid] = dict(assetId=aid, assetDefinitionRevision='a'*64, definition=dict(geometry=g), geometry=g, clearances=[])
    snapshot = deepcopy(before)
    ops = parking.operations(catalog)
    result = parking.apply_batches(before, ops)
    assert before == snapshot and len(ops) > 500
    return before, result, catalog


def test_complete_lot_preserves_existing_state_and_has_clear_access(candidate):
    before, result, catalog = candidate
    report = parking.audit(before, result, catalog)
    assert report['newSpaces'] == 214 and report['occupiedSpaces'] == 143
    assert report['vehicleCirculationConnected'] and report['pedestrianConnectionsClear']
    assert len(result['placements']) - len(before['placements']) == 357


def test_real_spatial_validator_accepts_bays_and_rejects_car_in_crossing(candidate):
    _, result, catalog = candidate
    def metrics(layout):
        return diagnose_layout(layout, list(catalog.values()), shell=shell_with_plan_boundary({'features': []}, layout))['metrics']
    m = metrics(result)
    assert m['placementCollisions'] == 0 and m['obstructedAisleCount'] == 0
    blocked = deepcopy(result)
    car = next(p for p in blocked['placements'] if p['placementId'].endswith('car-001'))
    car['transform']['position'] = dict(x=339.5, y=0, z=41.3)
    assert metrics(blocked)['obstructedAisleCount'] > 0


@pytest.mark.parametrize('fault', ['existing-edit', 'missing-car', 'wrong-scale', 'wrong-model',
    'car-in-aisle', 'missing-bay', 'missing-walk', 'missing-surface'])
def test_audit_rejects_faults(candidate, fault):
    before, source, catalog = candidate
    result = deepcopy(source)
    car = next(p for p in result['placements'] if p['placementId'].endswith('car-001'))
    if fault == 'existing-edit': result['displayName'] = 'Unexpected name'
    elif fault == 'missing-car': result['placements'].remove(car)
    elif fault == 'wrong-scale': car['transform']['scale'] = 2
    elif fault == 'wrong-model': car['assetId'] = parking.STOP
    elif fault == 'car-in-aisle': car['transform']['position']['z'] = 41.3
    elif fault == 'missing-walk': result['routes'].pop()
    else:
        prefix = 'fm-employee-parking-' + ('bay-' if fault == 'missing-bay' else 'surface-')
        result['floorMarkings'].remove(next(m for m in result['floorMarkings'] if m['markingId'].startswith(prefix)))
    with pytest.raises(AssertionError): parking.audit(before, result, catalog)
