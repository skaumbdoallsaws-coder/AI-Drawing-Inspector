"""Stage, publish and revision-bound save the APEX basketball wall treatment."""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
from shutil import copytree
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
if sys.version_info[:2] == (3, 14):
    sys.path.insert(0, str(Path.home() / 'AppData/Roaming/Python/Python314/site-packages'))
from PIL import Image
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from tools.build_private_gym import LAYOUT, STORE, IDENTITY, write, saved_hashes
from tools.gym_theme_wall import theme_wall

OUT = ROOT / '.runtime/private-gym-apex-court-20261007'
DOWNLOADS = Path('C:/Users/might/Downloads')
GENERATED_PLAYER = Path('C:/Users/might/.codex/generated_images/019edb92-e756-71f1-b62e-d8d64d83b161/exec-b68ecc70-df73-4d42-8c39-aa7a35fd236f.png')
SPECS = [
    ('back', -1, '#45484b', DOWNLOADS / 'ChatGPT Image Oct 7, 2026, 11_34_22 PM-2.png'),
    ('left', 1, '#292d32', GENERATED_PLAYER),
    ('right', -1, '#292d32', DOWNLOADS / 'ChatGPT Image Oct 7, 2026, 11_34_21 PM-1.png'),
]


def change_document(before, replacements):
    candidate = deepcopy(before)
    for p in candidate['placements']:
        if p['placementId'] in replacements:
            p.update(deepcopy(replacements[p['placementId']]))
        relation = p.get('snapRelationship') or {}
        support = replacements.get(relation.get('supportPlacementId'))
        if support:
            relation['supportAssetDefinitionRevision'] = support['assetDefinitionRevision']
    for face in candidate['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['wallFaces']:
        if face['placementId'] in replacements:
            face['assetDefinitionRevision'] = replacements[face['placementId']]['assetDefinitionRevision']
    return candidate


def audit(before, after, replacements):
    expected = change_document(before, replacements)
    expected['updatedAt'] = after['updatedAt']
    assert expected == after, 'Unrelated content changed'
    assert len(replacements) in (1, 3)
    if len(replacements) == 1:
        assert set(replacements) == {'pl-private-gym-sports-court-back'}
    assert [p['transform'] for p in before['placements']] == [p['transform'] for p in after['placements']]
    for field in ('floor', 'floorMarkings', 'zones', 'routes'):
        assert before.get(field) == after.get(field)
    return dict(replacedWalls=len(replacements), placements=len(after['placements']), geometryUnchanged=True,
                flooringUnchanged=True, positionsUnchanged=True, exteriorColorsUnchanged=True,
                transparentPlayers=2 if len(replacements) == 1 else 3, wallLights=6, ceiling='open-air; no ceiling added')


def require_alpha(path):
    with Image.open(path) as im:
        assert im.mode == 'RGBA', str(path)
        histogram = im.getchannel('A').histogram()
        assert sum(histogram[:10]) > im.width * im.height * .15, 'Artwork lacks transparent background'


def main():
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['stage', 'publish-assets', 'save'])
    parser.add_argument('--branding-only', action='store_true', help='Remove only the blue player from the saved center wall')
    parser.add_argument('--center-branding', action='store_true', help='Center the existing branding above the unchanged hoop')
    args = parser.parse_args()
    if args.center_branding:
        args.branding_only = True
    specs = SPECS
    if args.branding_only:
        OUT = ROOT / '.runtime/private-gym-apex-branding-only-20261008'
        specs = [('back', -1, '#45484b', None)]
    if args.center_branding:
        OUT = ROOT / '.runtime/private-gym-apex-centered-20261008'
    target = STORE / 'layouts/local/site-local/layouts' / (LAYOUT + '.json')
    manifest = ROOT / PRIVATE_ASSET_MANIFEST
    staged = OUT / 'staged-project'
    if args.phase != 'stage':
        report = json.loads((OUT / 'report.json').read_text())
        if args.phase == 'save' and report['status'] == 'saved':
            assert json.loads(target.read_bytes()) == json.loads((OUT / 'saved.json').read_bytes())
            print(json.dumps(dict(status='already-saved')))
            return
        assert target.read_bytes() == (OUT / 'before.json').read_bytes(), 'Saved base changed'
        if args.phase == 'publish-assets':
            assert hashlib.sha256(manifest.read_bytes()).hexdigest() == report['publicationBaseCatalogHash'], 'Library changed'
            for relative in report['artifacts']:
                dest = ROOT / relative
                if dest.exists():
                    assert hashlib.sha256(dest.read_bytes()).hexdigest() == report['publicationBaseArtifacts'].get(relative), 'Published asset changed'
                RevisionedAuthorityRepository._atomic_write(dest, (staged / relative).read_bytes())
            RevisionedAuthorityRepository._atomic_write(manifest, (staged / PRIVATE_ASSET_MANIFEST).read_bytes())
            report['status'] = 'assets-published'
        else:
            assert manifest.read_bytes() == (staged / PRIVATE_ASSET_MANIFEST).read_bytes()
            for relative in report['artifacts']:
                assert (ROOT / relative).read_bytes() == (staged / relative).read_bytes()
            raw = (OUT / 'candidate.json').read_bytes()
            native = json.loads((OUT / 'native-check.json').read_text())
            assert native['status'] == 'preview-verified'
            assert native['candidateHash'] == hashlib.sha256(raw).hexdigest()
            before = json.loads((OUT / 'before.json').read_bytes())
            candidate = json.loads(raw)
            audit(before, candidate, report['replacements'])
            host = LocalFacilityLayoutHost(STORE, private_assets=True, private_asset_root=ROOT)
            try:
                receipt = host.service.save_layout(host.principal(), 'site-local', LAYOUT, candidate, report['baseRevision'])
            finally:
                host.close()
            audit(before, receipt['layout'], report['replacements'])
            write(OUT / 'saved.json', receipt['layout'])
            after = saved_hashes()
            assert all(after[k] == v for k, v in report['layoutHashes'].items() if k not in (target.name, 'registry.json'))
            report.update(status='saved', savedRevision=receipt['revision'], otherLayoutsUnchanged=True)
        write(OUT / 'report.json', report)
        print(json.dumps(dict(status=report['status'])))
        return

    OUT.mkdir(parents=True, exist_ok=True)
    raw, catalog_raw = target.read_bytes(), manifest.read_bytes()
    before = json.loads(raw)
    published = {}
    if (OUT / 'report.json').exists():
        previous = json.loads((OUT / 'report.json').read_text())
        assert previous['status'] == 'assets-published', 'Only an unpublished preview can be revised'
        assert manifest.read_bytes() == (staged / PRIVATE_ASSET_MANIFEST).read_bytes(), 'Published library changed'
        for relative in previous['artifacts']:
            assert (ROOT / relative).read_bytes() == (staged / relative).read_bytes(), 'Published asset changed'
            published[relative] = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        for path in target.parent.glob('*.json'):
            if path.name == 'registry.json':
                continue
            content = json.loads(path.read_bytes())
            assert not any(p.get('assetId', '').startswith('asset-private-gym-apex-court-') for p in content.get('placements', [])), 'Preview asset is already used by a saved layout'
        library = json.loads((OUT / 'catalog-before.json').read_bytes())
    else:
        library = json.loads(catalog_raw)
    for name, payload in [('before.json', raw), ('catalog-before.json', catalog_raw)]:
        snapshot = OUT / name
        if snapshot.exists():
            if name != 'catalog-before.json' or not published:
                assert snapshot.read_bytes() == payload, 'Staging source changed'
        else:
            snapshot.write_bytes(payload)
    logo_path = DOWNLOADS / 'Metallic Gold Wolf APEX Gym Logo.png'
    require_alpha(logo_path)
    logo = logo_path.read_bytes()
    artifacts, bindings = [], []
    for key, face, color, source in specs:
        if source is not None:
            require_alpha(source)
        pid = 'pl-private-gym-sports-court-' + key
        placement = next(p for p in before['placements'] if p['placementId'] == pid)
        old = next(a for a in library['assets'] if a['assetId'] == placement['assetId'])
        aid = 'asset-private-gym-apex-court-' + key
        if args.branding_only:
            aid += '-branding-only'
        if args.center_branding:
            aid += '-centered'
        assert not any(a['assetId'] == aid for a in library['assets'])
        folder = Path('generated/industrial_assets/private_gym/apex-court') / key
        if args.branding_only:
            folder = folder / 'branding-only'
        if args.center_branding:
            folder = folder / 'centered'
        artifact = (folder / 'model.glb').as_posix()
        png = source.read_bytes() if source is not None else None
        payload = theme_wall(old['dimensions'], png, face=face, logo_png=logo if key == 'back' else None,
                             logo_box=(0, 4.525, 4.95, 1.65) if args.center_branding else None)
        items = [(artifact, payload)]
        if png is not None:
            items.append(((folder / 'player.png').as_posix(), png))
        if key == 'back':
            items.append(((folder / 'apex-logo.png').as_posix(), logo))
        for relative, value in items:
            dest = staged / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(value)
            artifacts.append(relative)
        library['assets'].append(dict(assetId=aid, displayName='APEX Basketball ' + key.title() + ' Wall',
            category='Building Structures', dimensions=old['dimensions'], sourceToCanonical=IDENTITY,
            artifact=artifact, tags=['gym', 'sports', 'wall', 'artwork'],
            source=dict(kind='authored-textured-wall', artworkFile=str(source or logo_path),
                artworkSha256=hashlib.sha256(png or logo).hexdigest(), backgroundExtraction=key == 'left',
                generator=Path(__file__).name, lighting='visual concept; not a photometric qualification'),
            description='Same wall envelope; '+('APEX branding only' if args.branding_only else 'transparent player')+', metallic gold accents and warm local light.'))
        bindings.append(dict(placementId=pid, assetId=aid, color=color))
    library['summary']['total'] = len(library['assets'])
    write(staged / PRIVATE_ASSET_MANIFEST, library)
    stage = OUT / 'validation-store'
    for rel in ['authorities', 'layouts/local']:
        copytree(_native_fs_path(STORE / rel), _native_fs_path(stage / rel), dirs_exist_ok=True)
    host = LocalFacilityLayoutHost(stage, private_assets=True, private_asset_root=staged)
    try:
        catalog = {a['assetId']: a for a in host.authoritative_asset_catalog()}
        replacements = {b['placementId']: dict(assetId=b['assetId'],
            assetDefinitionRevision=catalog[b['assetId']]['assetDefinitionRevision'],
            appearance=dict(color=b['color'])) for b in bindings}
        candidate = change_document(before, replacements)
        checks = audit(before, candidate, replacements)
        spatial = host.service._diagnose_spatial(host.principal(), 'site-local', candidate)
        write(OUT / 'spatial.json', spatial)
        host.service._require_spatially_valid(spatial)
        receipt = host.service.save_layout(host.principal(), 'site-local', LAYOUT, candidate, layout_revision(before))
    finally:
        host.close()
    audit(before, receipt['layout'], replacements)
    write(OUT / 'candidate.json', receipt['layout'])
    write(OUT / 'report.json', dict(status='validated', baseRevision=layout_revision(before),
        replacements=replacements, checks=checks, artifacts=artifacts, layoutHashes=saved_hashes(),
        publicationBaseCatalogHash=hashlib.sha256(catalog_raw).hexdigest(), publicationBaseArtifacts=published))
    profile = json.loads((ROOT / '.runtime/private-gym-light-court-20261007/profile.json').read_text())
    profile.update(profileId='private-gym-apex-court', origin='http://127.0.0.1:8546',
                   dataRoot=str(OUT), backendId=str(uuid.uuid4()), storeId=str(uuid.uuid4()))
    if args.branding_only:
        profile.update(profileId='private-gym-apex-branding-only', origin='http://127.0.0.1:8547')
    if args.center_branding:
        profile.update(profileId='private-gym-apex-centered', origin='http://127.0.0.1:8548')
    write(OUT / 'profile.json', profile)
    def shot(name, position, target):
        return dict(name=name, position=dict(zip(('x', 'y', 'z'), position)),
                    target=dict(zip(('x', 'y', 'z'), target)), thresholds=dict(detail=1000, yellow=100))
    court = shot('01-apex-court', (71.5, 4.4, 15.8), (71.5, 2.7, 33))
    branding_shot = shot('02-center-branding', (71.5, 4.5, 25), (71.5, 4.525, 36)) if args.center_branding else shot('02-center-branding', (75.4, 3.1, 27), (76.5, 3, 36))
    write(OUT / 'review-config.json', dict(profileId=profile['profileId'],
        requiredEmbeddedLights=2 if args.branding_only else 6,
        requiredAssets=[b['assetId'] for b in bindings],
        requiredWallArt=['apex-emblem', 'discipline', 'higher-everyday'],
        shots=[court, branding_shot,
               shot('03-side-artwork', (72, 3.2, 24), (62, 2.8, 27))],
        finalShot=dict(court, name='04-saved-apex-court')))
    print(json.dumps(dict(status='validated', checks=checks)))


if __name__ == '__main__':
    main()
