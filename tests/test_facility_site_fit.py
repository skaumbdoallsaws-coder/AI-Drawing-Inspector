from copy import deepcopy
import pytest
from ai_inspector.facility_layout.site_context import KEY, analyze_site_context
from ai_inspector.facility_layout.site_fit import analyze_site_fit
from tests.test_facility_site_property import fixture


def check_candidates(doc,request,result):
    assert 0 < len(result['candidates']) <= 8
    assert result['evaluatedPoses'] <= 664
    for candidate in result['candidates']:
        draft=deepcopy(doc)
        draft['extensions'].setdefault('facilityPlan',{}).update(widthMeters=request['widthMeters'],depthMeters=request['depthMeters'])
        draft['extensions'][KEY]['buildingPose']=candidate['buildingPose']
        draft['extensions'][KEY].setdefault('areas',[]).extend(
            dict(area,areaId='candidate-'+str(i)) for i,area in enumerate(candidate['reservedAreas']))
        assert not analyze_site_context(draft)['findings']


def test_candidates_are_deterministic_verified_and_do_not_modify_layout():
    doc=fixture();before=deepcopy(doc)
    request={'widthMeters':24,'depthMeters':18,'parkingCount':10,'dockWallEdge':0,'truckCourtDepthMeters':12}
    result=analyze_site_fit(doc,request)
    check_candidates(doc,request,result)
    assert analyze_site_fit(doc,request)==result and doc==before
    assert all(len(c['reservedAreas'])==2 for c in result['candidates'])
    assert result['assumptions']['driveAisleWidthMeters']==6
    assert result['searchComplete'] and not result['exhaustive']


def test_rotated_court_survives_persisted_coordinate_precision():
    doc=fixture();doc['extensions'][KEY]['property']['setbacksMeters']={'street':0,'side':0,'rear':0}
    request={'widthMeters':24.125,'depthMeters':18.333,'bearingsDegrees':[23,47],
        'dockWallEdge':2,'truckCourtDepthMeters':8.75}
    check_candidates(doc,request,analyze_site_fit(doc,request))


def test_concave_lot_and_existing_areas_are_respected():
    doc=fixture();doc['extensions'][KEY]['property']['boundary']=[
        {'x':0,'z':0},{'x':100,'z':0},{'x':100,'z':80},{'x':50,'z':80},{'x':50,'z':40},{'x':0,'z':40}]
    doc['extensions'][KEY]['areas']=[{'areaId':'existing','label':'Existing','kind':'landscape','surface':'grass',
        'boundary':[{'x':60,'z':15},{'x':80,'z':15},{'x':80,'z':30},{'x':60,'z':30}]}]
    request={'widthMeters':15,'depthMeters':10,'bearingsDegrees':[23,90]}
    check_candidates(doc,request,analyze_site_fit(doc,request))


def test_missing_boundary_and_no_sampled_fit_are_explicit():
    doc=fixture();request={'widthMeters':900,'depthMeters':900}
    result=analyze_site_fit(doc,request)
    assert not result['candidates'] and 'does not prove' in result['reason']
    del doc['extensions'][KEY]['property']
    assert 'boundary is required' in analyze_site_fit(doc,request)['reason']


@pytest.mark.parametrize('patch',[{'widthMeters':True},{'depthMeters':float('nan')},
    {'bearingsDegrees':[]},{'parkingCount':True},{'parkingCount':201},{'dockWallEdge':4},
    {'truckCourtDepthMeters':20},{'untrusted':1}])
def test_solver_rejects_invalid_input_even_without_tool_schema(patch):
    with pytest.raises(ValueError):analyze_site_fit(fixture(),{'widthMeters':20,'depthMeters':15,**patch})
