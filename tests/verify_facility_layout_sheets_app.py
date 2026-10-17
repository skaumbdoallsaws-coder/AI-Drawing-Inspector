"""Exercise real layout sheets on an isolated backend; never write the user's layout."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = 'fl-reference-manual-20260812'
PORT = 8491
BASE = f'http://127.0.0.1:{PORT}'
OUT = ROOT / '.runtime' / ('layout-sheets-' + time.strftime('%Y%m%d-%H%M%S'))
HIDDEN = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def main():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', PORT))
    subprocess.run([sys.executable, 'desktop/tools/prepare-application-check.py',
                    '--destination', str(OUT), '--port', str(PORT)], cwd=ROOT, check=True, creationflags=HIDDEN)
    source = json.loads((OUT / 'application-check-source.json').read_text())
    env = dict(os.environ, INSPECTORPRO_FACILITY_LAYOUT_ROOT=str(OUT / 'facility'))
    for name in ['VIEWER_V2', 'MANUAL_EDIT', 'CONSTRAINTS', 'ROUTING']:
        env['INSPECTORPRO_FACILITY_LAYOUT_' + name] = '1'
    env['INSPECTORPRO_INDUSTRIAL_ASSET_LIBRARY'] = '1'
    errors, mutations = [], []
    report = {'status': 'running', 'output': str(OUT)}
    with (OUT / 'server.log').open('w', encoding='utf8') as log:
        server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'server:app', '--host', '127.0.0.1',
                                   '--port', str(PORT)], cwd=ROOT, env=env, stdout=log, stderr=log, creationflags=HIDDEN)
        try:
            deadline = time.monotonic() + 120
            while True:
                try:
                    with urllib.request.urlopen(BASE + '/api/facility-layout-bootstrap', timeout=3) as response:
                        if response.status == 200:
                            break
                except Exception:
                    if server.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError('Isolated backend failed to start; see server.log')
                    time.sleep(.5)
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 900})
                page.set_default_navigation_timeout(120000)
                dialogs = []
                def handle_dialog(dialog):
                    dialogs.append({'type': dialog.type, 'message': dialog.message})
                    if dialog.type == 'beforeunload':
                        dialog.accept()
                    else:
                        dialog.dismiss()
                page.on('dialog', handle_dialog)
                original_wait = page.wait_for_function
                def wait_with_evidence(*args, **kwargs):
                    try:
                        return original_wait(*args, **kwargs)
                    except Exception:
                        page.screenshot(path=str(OUT / 'failure.png'))
                        report['failureState'] = page.evaluate("({error:document.querySelector('.ip-layout-sheet-error')?.textContent,layout:window._trainFacilityLayoutAuthoringApp?.session.getState().layout.layoutId,three:window._trainFacilityLayoutAuthoringApp?.workspace.threeAdapter?.getDiagnostics(),pool:_trainFacilityRendererPool?.getDiagnostics(),tabs:document.querySelector('.ip-layout-sheets')?.outerHTML})")
                        raise
                page.wait_for_function = wait_with_evidence
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: mutations.append({'url': request.url, 'method': request.method})
                        if '/api/facility-layouts/' in request.url and request.method in ('POST', 'PUT', 'DELETE') else None)
                page.goto(BASE + '/?facilityLayoutId=' + REFERENCE, wait_until='domcontentloaded')
                page.get_by_role('tab', name='Workflows', exact=True).click()
                page.wait_for_selector('#trainingTypeRibbonSelect', state='attached')
                page.evaluate("""() => {const s=document.getElementById('trainingTypeRibbonSelect');
                    s.value='facility_layout';s.dispatchEvent(new Event('change',{bubbles:true}));}""")
                page.wait_for_function("window._trainFacilityLayoutAuthoringApp?.workspace && document.querySelector('.ip-layout-sheet-add')", timeout=120000)
                page.evaluate("window._setLeftPanelContent('structure',{reveal:true})")
                page.evaluate("window.__sheetOriginalApp = window._trainFacilityLayoutAuthoringApp")
                original = page.evaluate("_trainFacilityLayoutAuthoringApp.session.getState()")
                assert len(original['layout']['placements']) == 827
                await_idle = lambda: page.wait_for_function("!document.querySelector('.ip-layout-sheet-add').disabled && !_trainFacilityLayoutAuthoringApp.session.getState().busy", timeout=60000)
                await_idle()
                page.evaluate("_trainFacilitySheets.refresh()")
                inventory = page.evaluate("_trainFacilitySheets.state()")
                assert len(inventory['availableLayouts']) >= 2
                assert [row['layoutId'] for row in inventory['layouts']] == [REFERENCE]
                assert page.locator('.ip-layout-sheet-tab').count() == 1
                assert page.locator('.ip-layout-sheet-open').count() == 0
                assert page.get_by_role('button', name='Delete layout', exact=True).is_disabled()
                assert page.locator('#structureTreeHost [data-row-kind="layout-sheet"]').count() == 0
                page.screenshot(path=str(OUT / 'startup-only-requested-layout.png'))
                page.evaluate("_trainFacilityLayoutAuthoringApp.session.renameLayout('Manual unsaved test')")
                edited = page.evaluate("_trainFacilityLayoutAuthoringApp.session.getState()")
                assert edited['dirty']
                page.get_by_role('button', name='Add blank layout', exact=True).click()
                page.wait_for_function(f"_trainFacilityLayoutAuthoringApp.session.getState().layout.layoutId !== '{REFERENCE}'", timeout=60000)
                await_idle()
                first = page.evaluate("_trainFacilityLayoutAuthoringApp.session.getState()")
                for key in ('zones', 'placements', 'routes', 'floorMarkings', 'processBindings'):
                    assert first['layout'][key] == [], key
                assert first['layout']['sourceShellRef'] == original['layout']['sourceShellRef']
                lifecycle = page.evaluate('_desktopObserveApplication()')
                assert lifecycle['dirty'] and 'facility' in lifecycle['affected']
                first_tab = page.locator(f'.ip-layout-sheet-tab[data-layout-id="{first["layout"]["layoutId"]}"]')
                first_tab.dblclick()
                rename_dialog = page.get_by_role('dialog', name='Rename layout', exact=True)
                rename_dialog.get_by_label('Layout name').fill('   ')
                rename_dialog.get_by_role('button', name='Rename', exact=True).click()
                assert rename_dialog.is_visible()
                rename_dialog.get_by_label('Layout name').fill('Cancelled')
                page.keyboard.press('Escape')
                assert page.evaluate("_trainFacilityLayoutAuthoringApp.session.getState().layout.displayName") == first['layout']['displayName']
                first_tab.focus()
                page.keyboard.press('F2')
                rename_dialog.get_by_label('Layout name').fill('Assembly alternative')
                page.screenshot(path=str(OUT / 'rename-layout.png'))
                dialog_bounds = rename_dialog.bounding_box()
                assert abs(dialog_bounds['x'] + dialog_bounds['width'] / 2 - 720) < 2
                assert abs(dialog_bounds['y'] + dialog_bounds['height'] / 2 - 450) < 2
                rename_dialog.get_by_role('button', name='Rename', exact=True).click()
                page.wait_for_function("_trainFacilityLayoutAuthoringApp.session.getState().layout.displayName === 'Assembly alternative'")
                await_idle()
                first_edited = page.evaluate("_trainFacilityLayoutAuthoringApp.session.getState()")
                page.get_by_role('button', name='Add blank layout', exact=True).click()
                page.wait_for_function("id => _trainFacilityLayoutAuthoringApp.session.getState().layout.layoutId !== id", arg=first['layout']['layoutId'], timeout=60000)
                await_idle()
                second = page.evaluate("_trainFacilityLayoutAuthoringApp.session.getState()")
                assert not second['layout']['placements']
                # The first click switches an inactive tab; the second must still rename it.
                first_tab.dblclick()
                rename_dialog.wait_for()
                assert rename_dialog.get_by_label('Layout name').input_value() == 'Assembly alternative'
                rename_dialog.get_by_role('button', name='Cancel', exact=True).click()
                page.locator(f'.ip-layout-sheet-tab[data-layout-id="{second["layout"]["layoutId"]}"]').click()
                await_idle()
                page.evaluate("_trainFacilityLayoutAuthoringApp.workspace._setViewMode('3d')")
                report['blankRenderer'] = page.evaluate("({three:_trainFacilityLayoutAuthoringApp.workspace.threeAdapter?.getDiagnostics(),root:_trainFacilityLayoutAuthoringApp.workspace.root.outerHTML.slice(0,600),pool:_trainFacilityRendererPool?.getDiagnostics()})")
                page.wait_for_function("document.querySelector('#trainFacilityLayoutAuthoring[data-view-mode=\"3d\"] canvas')")
                assert not page.evaluate("_trainFacilityLayoutAuthoringApp.workspace.threeAdapter.getDiagnostics().degraded")
                assert page.evaluate("_trainFacilityRendererPool.getDiagnostics().createdCount") == 1
                page.screenshot(path=str(OUT / 'blank-3d.png'))
                page.locator(f'#structureTreeHost [data-layout-id="{REFERENCE}"]').click()
                page.wait_for_function("window._trainFacilityLayoutAuthoringApp === window.__sheetOriginalApp")
                restored = page.evaluate("_trainFacilityLayoutAuthoringApp.session.getState()")
                page.evaluate("_trainFacilityLayoutAuthoringApp.workspace._setViewMode('3d')")
                page.wait_for_function("_trainFacilityLayoutAuthoringApp.workspace.threeAdapter.getDiagnostics().pendingLoads === 0", timeout=120000)
                assert not page.evaluate("_trainFacilityLayoutAuthoringApp.workspace.threeAdapter.getDiagnostics().degraded")
                assert page.evaluate("_trainFacilityRendererPool.getDiagnostics().createdCount") == 1
                page.screenshot(path=str(OUT / 'restored-manual-3d.png'))
                page.evaluate("_trainFacilityLayoutAuthoringApp.workspace._setViewMode('plan')")
                for key in ('layout', 'history', 'historyCursor', 'draftRevision', 'selection'):
                    assert restored[key] == edited[key], key
                page.evaluate("_trainFacilityLayoutAuthoringApp.session.undo()")
                assert page.evaluate("_trainFacilityLayoutAuthoringApp.session.getState().layout.displayName") == original['layout']['displayName']
                assert page.evaluate("_trainFacilityLayoutAuthoringApp.workspace.viewMode") == 'plan'
                page.locator(f'.ip-layout-sheet-tab[data-layout-id="{first["layout"]["layoutId"]}"]').click()
                await_idle()
                active = page.evaluate("_trainFacilityLayoutAuthoringApp.session.getState()")
                assert active['draftRevision'] == first_edited['draftRevision']
                assert active['history'] == first_edited['history']
                assert not any(x['method'] == 'PUT' for x in mutations)
                page.evaluate("_trainFacilityLayoutAuthoringApp.session.save()")
                await_idle()
                assert not page.evaluate("_trainFacilityLayoutAuthoringApp.session.getState().dirty")
                # Archive only the isolated second blank; cancelling preserves it first.
                page.locator(f'.ip-layout-sheet-tab[data-layout-id="{second["layout"]["layoutId"]}"]').click()
                await_idle()
                page.get_by_role('button', name='Delete layout', exact=True).click()
                delete_dialog = page.get_by_role('dialog', name='Delete layout', exact=True)
                delete_dialog.get_by_role('button', name='Cancel', exact=True).click()
                assert page.locator('.ip-layout-sheet-tab').count() == 3
                page.get_by_role('button', name='Delete layout', exact=True).click()
                page.screenshot(path=str(OUT / 'delete-layout.png'))
                delete_dialog.get_by_role('button', name='Delete', exact=True).click()
                page.wait_for_function("document.querySelectorAll('.ip-layout-sheet-tab').length === 2")
                await_idle()
                archived = page.request.get(BASE + '/api/facility-layouts/site-local/' + second['layout']['layoutId']).json()
                assert archived['layout']['status'] == 'archived'
                page.locator(f'.ip-layout-sheet-tab[data-layout-id="{first["layout"]["layoutId"]}"]').click()
                await_idle()
                for width, height in [(1440, 900), (900, 700)]:
                    page.set_viewport_size({'width': width, 'height': height})
                    page.screenshot(path=str(OUT / f'sheets-{width}.png'))
                    bounds = page.locator('.ip-layout-sheets').bounding_box()
                    assert bounds and bounds['width'] > 100 and bounds['y'] + bounds['height'] <= height
                    assert page.locator('.ip-layout-sheet-add').is_visible()
                report['beforeReload'] = page.evaluate("_trainFacilitySheets.observation()")
                assert not report['beforeReload']['dirty']
                assert not report['beforeReload']['pending']
                page.reload(wait_until='domcontentloaded')
                page.get_by_role('tab', name='Workflows', exact=True).click()
                page.wait_for_selector('#trainingTypeRibbonSelect', state='attached')
                page.evaluate("""() => {const s=document.getElementById('trainingTypeRibbonSelect');
                    s.value='facility_layout';s.dispatchEvent(new Event('change',{bubbles:true}));}""")
                page.wait_for_function("window._trainFacilityLayoutAuthoringApp?.workspace && document.querySelector('.ip-layout-sheet-add')", timeout=120000)
                await_idle()
                page.evaluate("window._setLeftPanelContent('structure',{reveal:true})")
                page.evaluate("_trainFacilitySheets.refresh()")
                assert page.locator('.ip-layout-sheet-tab').count() == 1
                assert page.evaluate("_trainFacilityLayoutAuthoringApp.session.getState().layout.displayName") == 'Assembly alternative'
                assert page.locator('.ip-layout-sheet-open').count() == 0
                assert second['layout']['layoutId'] not in [row['layoutId'] for row in page.evaluate('_trainFacilitySheets.state().availableLayouts')]
                page.get_by_role('button', name='Add blank layout', exact=True).click()
                page.wait_for_function("document.querySelectorAll('.ip-layout-sheet-tab').length === 2")
                await_idle()
                third = page.evaluate('_trainFacilityLayoutAuthoringApp.session.getState()')
                page.locator(f'.ip-layout-sheet-tab[data-layout-id="{third["layout"]["layoutId"]}"]').dblclick()
                rename_dialog.get_by_label('Layout name').fill('Unsaved to discard')
                rename_dialog.get_by_role('button', name='Rename', exact=True).click()
                page.wait_for_function("_trainFacilityLayoutAuthoringApp.session.getState().layout.displayName === 'Unsaved to discard'")
                await_idle()
                # Lose the response only after the real backend commits the archive.
                archive_url = '**/api/facility-layouts/site-local/' + third['layout']['layoutId'] + '/archive'
                def lose_archive_reply(route):
                    response = route.fetch()
                    assert response.ok
                    route.abort('failed')
                page.route(archive_url, lose_archive_reply)
                page.get_by_role('button', name='Delete layout', exact=True).click()
                assert 'Unsaved changes' in delete_dialog.inner_text()
                delete_dialog.get_by_role('button', name='Delete', exact=True).click()
                page.wait_for_function("document.querySelectorAll('.ip-layout-sheet-tab').length === 1")
                await_idle()
                page.unroute(archive_url, lose_archive_reply)
                assert not page.evaluate('_trainFacilitySheets.observation().pending')
                assert page.evaluate('_trainFacilityLayoutAuthoringApp.session.getState().layout.layoutId') == first['layout']['layoutId']
                assert page.locator('#structureTreeHost [data-row-kind="layout-sheet"]').count() == 0
                assert page.locator('.ip-layout-sheet-tab[data-layout-id="fl-main"]').count() == 0
                page.screenshot(path=str(OUT / 'after-delete.png'))
                # Recheck dialog placement and visible controls at both theme/size boundaries.
                for theme, width, height in [('dark', 900, 700), ('light', 1440, 900)]:
                    page.set_viewport_size({'width': width, 'height': height})
                    page.evaluate("theme => document.documentElement.setAttribute('data-theme', theme)", theme)
                    page.locator('.ip-layout-sheet-tab').dblclick()
                    rename_dialog.wait_for()
                    bounds = rename_dialog.bounding_box()
                    assert abs(bounds['x'] + bounds['width'] / 2 - width / 2) < 2
                    assert abs(bounds['y'] + bounds['height'] / 2 - height / 2) < 2
                    page.screenshot(path=str(OUT / f'rename-{theme}-{width}.png'))
                    rename_dialog.get_by_role('button', name='Cancel', exact=True).click()
                assert not errors, errors
                assert all('/' + REFERENCE not in x['url'] or x['url'].endswith('/preview') for x in mutations)
                report.update(status='passed', checks=['two blank sheets', 'exact source references', 'tree switching',
                    'retained manual draft and Undo', 'independent histories', 'explicit active Save', 'reload', 'wide and narrow',
                    'startup excludes unrelated saved layouts', 'Open dropdown removed', 'active and inactive double-click rename',
                    'F2 rename and Escape cancellation', 'blank rename rejected', 'confirmed archive and cancellation',
                    'dirty sheet deletion with lost acknowledgment', 'archived sheet absent after reload', 'last sheet protected'],
                    layouts=[REFERENCE, first['layout']['layoutId'], second['layout']['layoutId']], mutations=mutations, pageErrors=errors, dialogs=dialogs)
                browser.close()
        except Exception as error:
            report.update(status='failed', error=repr(error), pageErrors=errors, mutations=mutations)
            raise
        finally:
            server.terminate()
            try: server.wait(timeout=15)
            except subprocess.TimeoutExpired: server.kill(); server.wait(timeout=10)
            report['backendStopped'] = server.poll() is not None
            report['originalUnchanged'] = hashlib.sha256(Path(source['originalPath']).read_bytes()).hexdigest() == source['originalSha256']
            (OUT / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf8')
            print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
