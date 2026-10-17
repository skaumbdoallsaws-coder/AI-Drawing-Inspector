"""Second-pass geometry checks use an isolated store and the local private library."""
from copy import deepcopy
import json
import pytest
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from tools import build_private_gym as gym
from tools import detail_private_gym as detail


@pytest.fixture(scope='module')
def detailed(tmp_path_factory):
    stage=detail.OUT/'staged-project'
    if not (stage/PRIVATE_ASSET_MANIFEST).exists():pytest.skip('Private gym detail artifacts unavailable')
    host=LocalFacilityLayoutHost(tmp_path_factory.mktemp('gym-detail'),private_assets=True,private_asset_root=stage)
    try:catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
    finally:host.close()
    blank=json.loads((gym.ROOT/'tests/fixtures/facility_layout/empty_cell.json').read_text())
    blank.update(placements=[],zones=[],floorMarkings=[],routes=[],extensions=dict(facilityPlan=gym.PLAN))
    first,_=gym.build(catalog,blank)
    candidate,_=detail.detail(first,catalog)
    return first,candidate,catalog


def test_detail_preserves_equipment_and_clears_connected_paths(detailed):
    first,candidate,catalog=detailed
    checks=detail.audit(first,candidate,catalog)
    assert checks['placements']==93
    assert checks['scheduledPlacementsPreserved']==66
    assert checks['routes']==11
    assert checks['finishIntersections']==0


def test_tile_repeat_is_connected_unscaled_cad():
    path=gym.ROOT/'generated/industrial_assets/local_library/gym-commercial-inter-v4/model-display.glb'
    if not path.exists():pytest.skip('Private tile CAD unavailable')
    mesh,report=detail.mat_mesh(path)
    assert report['tileCount']==140
    assert report['nominalCoverageM2']==pytest.approx(29.624)
    assert report['smallPatchOverlapM2']==pytest.approx(0,abs=1e-7)
    assert mesh.extents==pytest.approx([9.24,.02,3.26])
    assert len(mesh.faces)==10640


@pytest.mark.parametrize('fault',['equipment-changed','furniture-in-path','paint-over-path'])
def test_detail_audit_rejects_regressions(detailed,fault):
    first,candidate,catalog=detailed
    bad=deepcopy(candidate)
    if fault=='equipment-changed':bad['placements'][0]['transform']['position']['x']+=.1
    elif fault=='furniture-in-path':
        p=next(p for p in bad['placements'] if p['metadata']['gymRole']=='support-furniture')
        p['transform']['position'].update(x=30,z=11)
    else:
        m=next(m for m in bad['floorMarkings'] if m['markingType']=='solid_line')
        m['transform']['position'].update(x=30,z=11)
    with pytest.raises(AssertionError):detail.audit(first,bad,catalog)
