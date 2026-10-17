from copy import deepcopy
import json
from pathlib import Path
import pytest
from shapely.geometry import Polygon
from shapely.ops import unary_union
from ai_inspector.facility_layout.perimeter_walls import compile_perimeter_walls, validate_perimeter_walls, KEY
from ai_inspector.facility_layout.plan_settings import default_plan_settings
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.facility_layout.wall_finishes import MAX_WALL_ARTWORKS


def layout():
    doc=json.loads((Path(__file__).parent/'fixtures/facility_layout/empty_cell.json').read_text())
    doc.setdefault('extensions',{})['facilityPlan']=default_plan_settings()
    return doc


def settings(**kwargs):
    return dict(boundarySource='plan',heightMeters=3,thicknessMeters=.2,openings=[],**kwargs)


def geometry(value):
    return unary_union([Polygon([(p['x'],p['z']) for p in panel]) for panel in value['panels']])


def finish():
    return dict(color='#282B2D', artworks=[dict(artworkId='emblem', edge=0,
        startMeters=8, widthMeters=8, bottomMeters=0, heightMeters=3,
        imagePath='/generated/facility-wall-art/'+'a'*64+'.png', backingColor='#aaa9a2')])


def test_finish_is_revisioned_without_changing_physical_walls_or_openings():
    doc=layout(); value=settings(); value['openings']=[dict(edge=0,startMeters=5,endMeters=7)]
    base=compile_perimeter_walls(value,doc); value['exteriorFinish']=finish()
    changed=compile_perimeter_walls(value,doc)
    assert changed['panels']==base['panels']
    assert changed['settings']['exteriorFinish']['color']=='#282b2d'
    assert geometry(changed).equals(geometry(base))
    result=apply_facility_layout_operations(doc,[dict(op='set_perimeter_walls',wallSettings=value)])['document']
    validate_perimeter_walls(result)
    assert result['placements']==doc['placements']
    reset=deepcopy(value); reset.pop('exteriorFinish')
    assert apply_facility_layout_operations(result,[dict(op='set_perimeter_walls',wallSettings=reset)])['document']['extensions'][KEY]==base


@pytest.mark.parametrize('key,value', [('color','red'),('panelWidthMeters',0),('panelHeightMeters',False),
    ('jointWidthMeters',float('nan')),('unknown',True),('artworks',[{}]),('accentStrips',[{}])])
def test_invalid_finish_fails_closed(key,value):
    f=finish(); f[key]=value
    with pytest.raises(ValueError):compile_perimeter_walls(settings(exteriorFinish=f),layout())


@pytest.mark.parametrize('patch', [dict(startMeters=39),dict(edge=5),dict(heightMeters=4),
    dict(imagePath='https://example.com/logo.png'),dict(imagePath='/generated/facility-wall-art/../../a.png'),
    dict(uv=[0,0,0,1]),dict(uv=[0,0,True,1]),dict(artworkId=''),dict(widthMeters=.01)])
def test_bad_art_geometry_or_untrusted_sources_rejected(patch):
    f=finish();f['artworks'][0].update(patch)
    with pytest.raises(ValueError):compile_perimeter_walls(settings(exteriorFinish=f),layout())


def test_art_cannot_hide_doorways_and_wall_bindings_cannot_go_stale():
    value=settings(exteriorFinish=finish());value['openings']=[dict(edge=0,startMeters=10,endMeters=12)]
    with pytest.raises(ValueError,match='door'):compile_perimeter_walls(value,layout())
    doc=layout();doc['placements']=[dict(placementId='wall',assetDefinitionRevision='a'*64)]
    f=finish();f['wallFaces']=[dict(placementId='wall',assetDefinitionRevision='a'*64,face='positive_z',color='#282b2d')]
    value=settings(exteriorFinish=f)
    compile_perimeter_walls(value,doc)
    doc['placements'][0]['assetDefinitionRevision']='b'*64
    with pytest.raises(ValueError,match='stale'):compile_perimeter_walls(value,doc)


def test_duplicate_art_ids_and_excessive_panel_counts_rejected():
    f=finish();f['artworks'].append(deepcopy(f['artworks'][0]))
    with pytest.raises(ValueError,match='unique'):compile_perimeter_walls(settings(exteriorFinish=f),layout())
    doc=layout();doc['extensions']['facilityPlan']['widthMeters']=10000
    with pytest.raises(ValueError,match='budget'):compile_perimeter_walls(settings(exteriorFinish=finish()),doc)


def test_interior_art_is_revisioned_without_changing_exterior_or_wall_geometry():
    f=finish();interior=deepcopy(f['artworks'][0])
    interior.update(artworkId='inside',side='interior')
    baseline=compile_perimeter_walls(settings(exteriorFinish=f),layout())
    f['artworks'].append(interior)
    changed=compile_perimeter_walls(settings(exteriorFinish=f),layout())
    assert changed['panels']==baseline['panels']
    art=changed['settings']['exteriorFinish']['artworks']
    assert art[0]==baseline['settings']['exteriorFinish']['artworks'][0]
    assert 'side' not in art[0] and art[1]['side']=='interior'


@pytest.mark.parametrize('side',[None,True,{},'inside','both'])
def test_invalid_artwork_side_is_rejected(side):
    f=finish();f['artworks'][0]['side']=side
    with pytest.raises(ValueError,match='side'):compile_perimeter_walls(settings(exteriorFinish=f),layout())


def test_combined_interior_exterior_artwork_budget_is_bounded():
    f=finish();template=f['artworks'][0]
    f['artworks']=[dict(template,artworkId='art-'+str(i),side='interior' if i%2 else 'exterior') for i in range(MAX_WALL_ARTWORKS)]
    compile_perimeter_walls(settings(exteriorFinish=f),layout())
    f['artworks'].append(dict(template,artworkId='overflow'))
    with pytest.raises(ValueError,match='excessive'):compile_perimeter_walls(settings(exteriorFinish=f),layout())


def test_interior_art_cannot_cover_an_opening():
    f=finish();f['artworks'][0]['side']='interior'
    value=settings(exteriorFinish=f);value['openings']=[dict(edge=0,startMeters=10,endMeters=12)]
    with pytest.raises(ValueError,match='door'):compile_perimeter_walls(value,layout())


def test_interior_paint_preserves_geometry_exterior_and_artwork():
    doc=layout(); value=settings(exteriorFinish=finish())
    base=compile_perimeter_walls(value,doc)
    value['interiorColor']='#3B4147'
    painted=compile_perimeter_walls(value,doc)
    assert painted['settings'].pop('interiorColor')=='#3b4147'
    assert painted==base
    result=apply_facility_layout_operations(doc,[dict(op='set_perimeter_walls',wallSettings=value)])['document']
    validate_perimeter_walls(result)
    assert result['extensions'][KEY]['settings']['interiorColor']=='#3b4147'
    standalone=compile_perimeter_walls(settings(interiorColor='#3B4147'),doc)
    assert 'exteriorFinish' not in standalone['settings']


@pytest.mark.parametrize('color',[None,True,{},'gray','#fff','#3B414700','3B4147'])
def test_invalid_interior_paint_is_rejected(color):
    with pytest.raises(ValueError,match='Interior wall color'):
        compile_perimeter_walls(settings(interiorColor=color),layout())
