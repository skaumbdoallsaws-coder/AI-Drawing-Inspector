"""Local-library acceptance for the authored gym; never writes the user's store."""
from copy import deepcopy
import json
import math
from pathlib import Path
import pytest
from shapely.geometry import LineString, box
from shapely.ops import unary_union
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from tools import build_private_gym as gym


@pytest.fixture(scope='module')
def built(tmp_path_factory):
    manifest=gym.ROOT/PRIVATE_ASSET_MANIFEST
    if not manifest.exists():pytest.skip('Private gym catalog is not distributed with the repository')
    library=json.loads(manifest.read_text())
    if not any(a['assetId']=='asset-private-gym-reception-brand' for a in library['assets']):
        pytest.skip('Private gym architectural assets have not been prepared')
    host=LocalFacilityLayoutHost(tmp_path_factory.mktemp('gym-store'),private_assets=True,private_asset_root=gym.ROOT)
    try:catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
    finally:host.close()
    blank=json.loads((Path(__file__).parent/'fixtures/facility_layout/empty_cell.json').read_text())
    blank.update(placements=[],zones=[],floorMarkings=[],routes=[],extensions=dict(facilityPlan=gym.PLAN))
    snapshot=deepcopy(blank)
    candidate,ops=gym.build(catalog,blank)
    assert blank==snapshot
    return candidate,catalog,ops


def test_complete_schedule_and_clear_paths(built):
    candidate,catalog,_=built
    audit=gym.audit(candidate,catalog)
    assert audit['scheduledPlacements']==66
    assert audit['totalPlacements']==81
    assert sum(audit['actualZoneAreas'].values())==1800


def test_authored_primary_routes_connected():
    routes=unary_union([LineString(points).buffer(width/2,cap_style=2,join_style=2)
                        for _,points,width in gym.ROUTES])
    assert routes.geom_type=='Polygon'
    assert box(0,0,60,30).covers(routes)


def test_cardio_rows_face_front_without_moving_origins(built):
    candidate,_,_=built
    for slug,z,yaw in [('gym-expansion-cybex-710t',2.1,90),
                       ('gym-commercial-elliptical',6,180),
                       ('gym-commercial-stationary-bike',8.5,180)]:
        row=[p for p in candidate['placements'] if p['assetId']=='asset-'+slug]
        assert len(row)==6
        assert sorted(p['transform']['position']['x'] for p in row)==[15+3.5*i for i in range(6)]
        for p in row:
            assert p['transform']['position']['z']==z
            q=p['transform']['quaternion']
            assert q['y']==pytest.approx(math.sin(math.radians(yaw)/2))
            assert q['w']==pytest.approx(math.cos(math.radians(yaw)/2))


def test_excluded_assets_absent_and_all_new_types_present(built):
    candidate,_,_=built
    ids={p['assetId'] for p in candidate['placements']}
    assert len([i for i in ids if i.startswith('asset-gym-commercial-')])==19
    assert not ids.intersection({'asset-gym-commercial-exercise-machine',
                                'asset-gym-commercial-stl-equipment','asset-gym-commercial-weight-rack'})


@pytest.mark.parametrize('fault',['missing','outside','overlap','blocked-walkway'])
def test_geometry_audit_rejects_faults(built,fault):
    candidate,catalog,_=built
    bad=deepcopy(candidate)
    p=next(p for p in bad['placements'] if p['metadata']['gymRole']=='schedule')
    if fault=='missing':bad['placements'].remove(p)
    elif fault=='outside':p['transform']['position']['x']=-10
    elif fault=='overlap':
        other=next(q for q in bad['placements'] if q!=p and q['assetId']==p['assetId'])
        p['transform']=deepcopy(other['transform'])
    else:p['transform']['position']['z']=11
    with pytest.raises(AssertionError):gym.audit(bad,catalog)
