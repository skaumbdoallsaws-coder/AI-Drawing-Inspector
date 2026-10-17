from copy import deepcopy
import pytest

from tests.test_facility_wall_finishes import layout, settings, finish
from ai_inspector.facility_layout.perimeter_walls import compile_perimeter_walls
from ai_inspector.facility_layout.wall_finishes import MAX_WALL_ARTWORKS


def fitted(**patch):
    return dict(dict(artworkId='fit', imagePath='/generated/facility-wall-art/'+'b'*64+'.png',
        uv=[0,.2,1,.8], target=dict(edge=1,side='interior'), region=[.1,0,.8,1], coverage=.97), **patch)


def test_fitted_art_preserves_geometry_and_tracks_wall_height():
    doc=layout(); value=settings(exteriorFinish=finish())
    base=compile_perimeter_walls(value,doc)
    value['exteriorFinish']['fittedArtworks']=[fitted()]
    changed=compile_perimeter_walls(value,doc)
    assert changed['panels']==base['panels']
    assert changed['settings']['exteriorFinish']['fittedArtworks']==[fitted()]
    value['heightMeters']=5
    assert compile_perimeter_walls(value,doc)['settings']['exteriorFinish']['fittedArtworks']==[fitted()]


def test_placed_art_binds_occurrence_not_stale_definition():
    doc=layout(); doc['placements']=[dict(placementId='wall',assetDefinitionRevision='a'*64)]
    art=fitted(target=dict(placementId='wall',face='negative_x'))
    value=settings(exteriorFinish=dict(finish(),fittedArtworks=[art]))
    compile_perimeter_walls(value,doc)
    doc['placements'][0]['assetDefinitionRevision']='b'*64
    compile_perimeter_walls(value,doc)
    doc['placements']=[]
    with pytest.raises(ValueError,match='missing'): compile_perimeter_walls(value,doc)


@pytest.mark.parametrize('patch',[
    dict(coverage=1.1),dict(coverage=True),dict(region=[0,0,2,1]),dict(region=[0,0,0,1]),
    dict(uv=[0,0,float('nan'),1]),dict(uv=[0,1,1,0]),dict(imagePath='https://bad/image.png'),
    dict(target=dict(edge=99,side='interior')),dict(target=dict(edge=True,side='interior')),
    dict(target=dict(edge=0,side='both')),dict(target=dict(placementId='missing',face='positive_z')),
    dict(target=dict(edge=0,side='interior',placementId='wall')),dict(backingColor='#FFFFFF'),
])
def test_bad_fitted_art_fails_closed(patch):
    value=settings(exteriorFinish=dict(finish(),fittedArtworks=[fitted(**patch)]))
    with pytest.raises(ValueError):compile_perimeter_walls(value,layout())


def test_fitted_art_cannot_cover_openings_or_duplicate_existing_ids():
    value=settings(exteriorFinish=dict(finish(),fittedArtworks=[fitted(target=dict(edge=0,side='interior'),region=[0,0,1,1])]))
    value['openings']=[dict(edge=0,startMeters=2,endMeters=3)]
    with pytest.raises(ValueError,match='door'):compile_perimeter_walls(value,layout())
    value['openings']=[];value['exteriorFinish']['fittedArtworks'][0]['artworkId']='emblem'
    with pytest.raises(ValueError,match='unique'):compile_perimeter_walls(value,layout())


def test_combined_art_budget():
    value=settings(exteriorFinish=dict(finish(),fittedArtworks=[fitted(artworkId='fit-'+str(i)) for i in range(MAX_WALL_ARTWORKS-1)]))
    compile_perimeter_walls(value,layout())
    value['exteriorFinish']['fittedArtworks'].append(fitted(artworkId='overflow'))
    with pytest.raises(ValueError,match='budget'):compile_perimeter_walls(value,layout())


def test_expanded_room_collection_preserves_existing_artwork_and_panels():
    value=settings(exteriorFinish=finish())
    template=value['exteriorFinish']['artworks'][0]
    value['exteriorFinish']['artworks']=[dict(template,artworkId='legacy-'+str(i)) for i in range(22)]
    value['exteriorFinish']['fittedArtworks']=[fitted(artworkId='fit-'+str(i)) for i in range(10)]
    before=compile_perimeter_walls(value,layout())
    value['exteriorFinish']['fittedArtworks'].extend(fitted(artworkId='new-'+str(i)) for i in range(3))
    after=compile_perimeter_walls(value,layout())
    assert after['panels']==before['panels']
    assert after['settings']['exteriorFinish']['artworks']==before['settings']['exteriorFinish']['artworks']
    assert after['settings']['exteriorFinish']['fittedArtworks'][:10]==before['settings']['exteriorFinish']['fittedArtworks']


def test_fitted_only_budget_is_bounded():
    value=settings(exteriorFinish=dict(finish(),artworks=[],fittedArtworks=[fitted(artworkId='fit-'+str(i)) for i in range(MAX_WALL_ARTWORKS)]))
    compile_perimeter_walls(value,layout())
    value['exteriorFinish']['fittedArtworks'].append(fitted(artworkId='overflow'))
    with pytest.raises(ValueError,match='excessive'):compile_perimeter_walls(value,layout())


def test_recovery_candidate_has_only_requested_graphics():
    from tools import add_private_gym_recovery_art as art
    import json
    if not (art.OUT/'candidate.json').exists():pytest.skip('Local recovery artwork not staged')
    before=json.loads((art.OUT/'before.json').read_text())
    after=json.loads((art.OUT/'candidate.json').read_text())
    records=json.loads((art.OUT/'report.json').read_text())['records']
    assert art.audit(before,after,records)['unchangedPlacements']==len(before['placements'])
    changed=deepcopy(after);changed['placements'][0]['transform']['scale']=2
    with pytest.raises(AssertionError):art.audit(before,changed,records)


def test_recovery_alpha_fit_preserves_all_visible_pixels_and_correct_sides():
    from tools import add_private_gym_recovery_art as art
    import json
    if not (art.OUT/'report.json').exists():pytest.skip('Local recovery artwork not staged')
    report=json.loads((art.OUT/'report.json').read_text())
    records={r['artworkId']:r for r in report['records']}
    assert records['recovery-wolf']['target']==dict(placementId=art.WEST_WALL,face='positive_z')
    assert records['recovery-discipline']['target']==dict(edge=0,side='interior')
    assert records['recovery-ocean']['target']==dict(edge=1,side='interior')
    for source in report['sources']:
        original=art.Path.home()/'Downloads'/source['file']
        staged=art.OUT/'staged-project'/source['artifact']
        assert original.read_bytes()==staged.read_bytes()
        with art.Image.open(original) as image:
            alpha=image.getchannel('A')
            box=alpha.point(lambda v:255 if v>=3 else 0).getbbox()
            crop=source['alphaBounds']
            assert crop[0]<=box[0] and crop[1]<=box[1] and crop[2]>=box[2] and crop[3]>=box[3]
        if source['artworkId']=='recovery-discipline':
            assert crop[1]>300 and crop[3]<1100, 'Invisible margins made the slogan too small'
