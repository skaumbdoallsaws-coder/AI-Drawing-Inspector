"""Private library assets may provide conservative convex footprint components."""
import json
import math
import pytest
from ai_inspector.facility_layout.host import build_private_local_asset_catalog, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.spatial import placement_spatial_records, oriented_box_polygon, polygons_intersect


def catalog(tmp_path, polygons=None):
    spec = dict(assetId='asset-corner-desk', displayName='Corner desk', category='Office',
                description='Measured corner desk', artifact='generated/corner.glb',
                dimensions=dict(width=2, depth=2, height=1.7),
                sourceToCanonical=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1])
    if polygons is not None:
        spec['footprintPolygons'] = polygons
    target = tmp_path / PRIVATE_ASSET_MANIFEST
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(schemaVersion=1,assets=[spec])))
    return next(a for a in build_private_local_asset_catalog(tmp_path) if a['assetId']==spec['assetId'])


def polygon(points):
    return [dict(x=x,z=z) for x,z in points]


def test_components_preserve_open_space_and_change_revision(tmp_path):
    before=catalog(tmp_path)
    components=[polygon([(-1,-1),(-.2,-1),(-.2,1),(-1,1)]),
                polygon([(-.2,-1),(1,-1),(1,-.2),(-.2,-.2)])]
    after=catalog(tmp_path,components)
    assert after['definition']['geometry']['footprintPolygons']==components
    assert before['definition']['geometry']['aabb']==after['definition']['geometry']['aabb']
    assert before['assetDefinitionRevision']!=after['assetDefinitionRevision']
    placement=dict(placementId='desk',assetId=after['assetId'],transform=dict(
        position=dict(x=0,y=0,z=0),quaternion=dict(x=0,y=0,z=0,w=1),scale=1))
    records=placement_spatial_records(placement,after)
    assert len(records)==2
    chair=oriented_box_polygon((.24,.24),(.2935,.275),math.radians(225))
    assert not any(polygons_intersect(r.polygon,chair) for r in records)
    for drawer in [(-.65,.5),(.5,-.65)]:
        misplaced=oriented_box_polygon(drawer,(.2935,.275),math.radians(225))
        assert any(polygons_intersect(r.polygon,misplaced) for r in records)


@pytest.mark.parametrize('bad', [[], [[]], [polygon([(0,0),(1,1),(0,1),(1,0)])],
    [polygon([(-1,-1),(1,-1),(0,0),(1,1),(-1,1)])],
    [polygon([(-2,-1),(1,-1),(1,1),(-1,1)])],
    [polygon([(0,0),(1,0),(0,0),(0,1)])],
    [polygon([(0,0),(1,0),(2,0)])],
    [polygon([(0,0),(float('nan'),0),(0,1)])],
    [polygon([(0,0),(True,0),(0,1)])],
    [[dict(x=0,z=0,y=0),dict(x=1,z=0),dict(x=0,z=1)]],
    [polygon([(0,0),(.5,0),(0,.5)])]*65])
def test_invalid_components_are_rejected(tmp_path,bad):
    with pytest.raises(ValueError, match='footprint'):
        catalog(tmp_path,bad)
