"""Browser check: placing the Site footprint by hand (select, drag, turn, nudge, centre readout), against an ISOLATED
test server.

Usage: python tests/verify_facility_site_footprint_browser.py --base http://127.0.0.1:PORT [--out DIR] [--photo]
    [--headed]
Creates one disposable layout ("Footprint check ...", a copy of the server's default layout with a site at
example coordinates) through the app's own API, saves it, and touches no other layout. Refuses the desktop app
(8480) and the packaging pilot (8181). --photo uses the app's own "Fetch a photo" (public USGS imagery); without
it the map has no photo. No model requests.
"""
import argparse
import json
import math
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

APP = 'window._trainFacilityLayoutAuthoringApp'
SITE = APP + '.workspace.state.layout.extensions.facilitySiteContext'
DEGREE = chr(176)
# Example coordinates (the app's own placeholder): downtown Minneapolis.
SITE_CONTEXT = {'version': 1, 'georeference': {'originLatitude': 44.9778, 'originLongitude': -93.265,
                'placedBy': 'coordinates', 'label': 'Footprint check (example coordinates)'},
                'buildingPose': {'x': -20.0, 'z': -15.0, 'bearingDegrees': 0.0}}


def open_app(page, base, layout_id='', site=True):
    page.goto(base + '/' + ('?facilityLayoutId=' + layout_id if layout_id else ''))
    page.wait_for_function('!!window.InspectorProFacilityStructure', timeout=90000)
    page.get_by_role('tab', name='Workflows', exact=True).click()
    page.wait_for_selector('#trainingTypeRibbonSelect', state='attached')
    page.evaluate("""() => { const s=document.getElementById('trainingTypeRibbonSelect');
        s.value='facility_layout'; s.dispatchEvent(new Event('change',{bubbles:true})); }""")
    page.wait_for_function('!!(' + APP + '?.workspace)', timeout=120000)
    if site:
        page.locator(".ip-flw-view-tab[data-view='site']").click()
        page.wait_for_selector('.ip-flw-site-building')
        idle(page)


def idle(page):
    page.wait_for_function("document.querySelector('#ip-flw-site-view')?.getAttribute('aria-busy') !== 'true'")
    page.wait_for_timeout(200)


def screen(page, x, z):
    """Page position of a property point (+X east, +Z north)."""
    return page.evaluate("""([x,z]) => { const e=document.querySelector('.ip-flw-site-canvas');
        const p=e.createSVGPoint(); p.x=x; p.y=-z; const s=p.matrixTransform(e.getScreenCTM());
        return [s.x, s.y]; }""", [x, z])


def footprint(page):
    """The drawn outline (property metres), its centre and side lengths, the saved pose and the map's view box."""
    return page.evaluate("""() => { const pts=document.querySelector('.ip-flw-site-building').getAttribute('points')
            .trim().split(/\\s+/).map(p => p.split(',').map(Number)).map(([x,y]) => ({x, z: -y}));
        const side=(a,b)=>Math.hypot(b.x-a.x,b.z-a.z);
        const svg=document.querySelector('.ip-flw-site-canvas');
        return {outline: pts, centre: {x:(pts[0].x+pts[2].x)/2, z:(pts[0].z+pts[2].z)/2},
            sides: [side(pts[0],pts[1]), side(pts[1],pts[2]), side(pts[2],pts[3]), side(pts[3],pts[0])],
            pose: JSON.parse(JSON.stringify(""" + SITE + """.buildingPose)),
            viewBox: svg.getAttribute('viewBox'), mpp: svg.viewBox.baseVal.width / svg.clientWidth}; }""")


def geo(page, x, z):
    """Latitude and longitude of a property point, read off the site photo (None without one)."""
    return page.evaluate("""([x,z]) => { const s=""" + SITE + """; const image=s.imagery && s.imagery[0];
        return image ? window.InspectorProFacilitySite.latLonAt(image, x, z) : null; }""", [x, z])


def count(page, selector):
    return page.locator(selector).count()


def body_point(page):
    """A screen point on the footprint's own body, not under a street label, to press it."""
    point = page.evaluate("""() => { const poly=document.querySelector('.ip-flw-site-building');
        const r=poly.getBoundingClientRect();
        for (let ring=0; ring<5; ring+=1) for (const fx of [0.5-ring*0.08, 0.5+ring*0.08])
            for (const fy of [0.5-ring*0.08, 0.5+ring*0.08]) {
                const x=r.left+r.width*fx, y=r.top+r.height*fy;
                if (document.elementFromPoint(x, y)===poly) return [x, y];
            }
        return null; }""")
    assert point, 'no free point on the footprint'
    return point


def centre_readout(page):
    """The Building settings' centre readout as signed latitude and longitude, and its text."""
    text = page.locator('.ip-flw-site-centre').text_content()
    parts = text.split(': ', 1)[1].split(', ')
    values = []
    for part in parts:
        number, hemisphere = part.split(DEGREE + ' ')
        values.append(float(number) * (1 if hemisphere in ('N', 'E') else -1))
    return values, text


def empty_point(page):
    """A point on the map itself (photo or background), well clear of the footprint, its handle and the controls."""
    point = page.evaluate("""() => { const map=document.querySelector('#ip-flw-site-view').getBoundingClientRect();
        const marks=[...document.querySelectorAll('.ip-flw-site-building,.ip-flw-site-selection,[data-site-pose]')]
            .map(e => e.getBoundingClientRect());
        for (let fy=0.85; fy>0.1; fy-=0.05) for (let fx=0.9; fx>0.3; fx-=0.05) {
            const x=map.left+map.width*fx, y=map.top+map.height*fy;
            const hit=document.elementFromPoint(x, y);
            const onMap=hit && (hit.matches('svg.ip-flw-site-canvas') || hit.matches('svg.ip-flw-site-canvas image'));
            const clear=marks.every(r => x < r.left-80 || x > r.right+80 || y < r.top-80 || y > r.bottom+80);
            if (onMap && clear) return [x, y];
        }
        return null; }""")
    assert point, 'no empty map point found'
    return point


def close(actual, expected, tolerance, what):
    assert abs(actual - expected) <= tolerance, f'{what}: {actual} != {expected} (+/- {tolerance})'


def turn_handle(page, centre, degrees, shift=False, shot=None):
    """Drag the rotation handle around the footprint's centre by `degrees` (clockwise on screen)."""
    box = page.locator('circle[data-site-pose="rotate"]').bounding_box()
    knob = (box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
    middle = screen(page, centre['x'], centre['z'])
    radius = math.hypot(knob[0] - middle[0], knob[1] - middle[1])
    start = math.atan2(knob[0] - middle[0], middle[1] - knob[1])
    page.mouse.move(*knob)
    page.mouse.down()
    if shift:
        page.keyboard.down('Shift')
    label = None
    for step in range(1, 13):
        angle = start + math.radians(degrees) * step / 12
        page.mouse.move(middle[0] + radius * math.sin(angle), middle[1] - radius * math.cos(angle))
    if count(page, '.ip-flw-site-angle'):
        label = page.locator('.ip-flw-site-angle').text_content()
    if shot:
        page.screenshot(path=str(shot))
    page.mouse.up()
    if shift:
        page.keyboard.up('Shift')
    idle(page)
    return label


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', required=True)
    parser.add_argument('--out', default='ui-data/site-checks/footprint')
    parser.add_argument('--photo', action='store_true')
    parser.add_argument('--headed', action='store_true')
    args = parser.parse_args()
    base = args.base.rstrip('/')
    if urlparse(base).port in (8480, 8181):
        raise SystemExit('Refusing: that port is the desktop app or the packaging pilot. Use an isolated server.')
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = {'checks': []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        page = browser.new_page(viewport={'width': 1600, 'height': 950})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        open_app(page, base, site=False)
        identity = 'fl-footprint-check-' + str(int(time.time()))
        created = page.evaluate("""async ([id, site]) => { const a=window._trainFacilityLayoutAuthoringApp;
            const doc=JSON.parse(JSON.stringify(a.workspace.state.layout));
            doc.layoutId=id; doc.displayName='Footprint check'; doc.status='draft';
            doc.extensions=Object.assign({}, doc.extensions || {}, {facilitySiteContext: site});
            return a.transport.createLayout(doc); }""", [identity, SITE_CONTEXT])
        assert created.get('layout'), list(created)
        report['layoutId'] = identity
        open_app(page, base, identity)
        interior = page.evaluate('JSON.stringify([' + APP + '.workspace.state.layout.placements,' + APP
                                 + '.workspace.state.layout.zones,' + APP + '.workspace.state.layout.routes])')
        if args.photo:
            page.locator('.ip-flw-site-expand').click()
            page.get_by_role('button', name='Fetch a photo', exact=True).click()
            page.wait_for_function(SITE + '.imagery?.length > 0', timeout=180000)
            idle(page)
            if count(page, '.ip-flw-site-collapse'):
                page.locator('.ip-flw-site-collapse').click()
            report['photo'] = page.evaluate(SITE + '.imagery[0].source')
        start = footprint(page)
        size = sorted({round(side, 6) for side in start['sides']})
        report['footprintSizeMeters'] = size
        page.screenshot(path=str(out / '01-unselected.png'))
        assert count(page, '.ip-flw-site-selection') == 0

        # 1. A click selects: outline, rotation handle, no resize handles, the Building fields open.
        page.mouse.click(*screen(page, start['centre']['x'], start['centre']['z']))
        idle(page)
        assert count(page, '.ip-flw-site-selection') == 1, 'not selected'
        assert count(page, 'circle[data-site-pose="rotate"]') == 1
        assert count(page, '[data-site-pose]') == 2 and count(page, '.ip-flw-site-handle') == 0, 'unexpected handles'
        assert page.get_by_label('Building X (m)', exact=True).is_visible()
        page.screenshot(path=str(out / '02-selected.png'))
        report['checks'].append('click selects: dashed outline + rotation handle, no corner/edge/centre handles, '
                                'Building fields open')

        # 2. Drag the selected footprint: the map stays still, one save, size unchanged.
        mpp = start['mpp']
        here = screen(page, start['centre']['x'] + 4, start['centre']['z'] - 3)
        page.mouse.move(*here)
        page.mouse.down()
        page.mouse.move(here[0] + 150, here[1] + 60, steps=12)
        live_x = float(page.get_by_label('Building X (m)', exact=True).input_value())
        page.mouse.up()
        idle(page)
        moved = footprint(page)
        assert moved['viewBox'] == start['viewBox'], 'the map moved during a footprint drag'
        close(moved['pose']['x'] - start['pose']['x'], 150 * mpp, 1.5 * mpp, 'moved east')
        close(moved['pose']['z'] - start['pose']['z'], -60 * mpp, 1.5 * mpp, 'moved south')
        close(live_x, moved['pose']['x'], 0.01, 'the X field followed the drag')
        assert moved['pose']['bearingDegrees'] == start['pose']['bearingDegrees']
        for a, b in zip(moved['sides'], start['sides']):
            close(a, b, 1e-6, 'side length after the move')
        report['move'] = {'dxMeters': round(moved['pose']['x'] - start['pose']['x'], 3),
                          'dzMeters': round(moved['pose']['z'] - start['pose']['z'], 3),
                          'centreLatLonBefore': geo(page, start['centre']['x'], start['centre']['z']),
                          'centreLatLonAfter': geo(page, moved['centre']['x'], moved['centre']['z'])}
        page.screenshot(path=str(out / '03-moved.png'))
        report['checks'].append('the selected footprint drags rigidly; the map stays still; fields follow live')

        # 3. Turn by the handle: about the centre, the angle shows while turning.
        label = turn_handle(page, moved['centre'], 30, shot=out / '04-turning.png')
        turned = footprint(page)
        assert label and label.endswith(DEGREE), label
        close(turned['pose']['bearingDegrees'], 30, 0.6, 'bearing after the turn')
        close(turned['centre']['x'], moved['centre']['x'], 0.01, 'centre x kept')
        close(turned['centre']['z'], moved['centre']['z'], 0.01, 'centre z kept')
        assert count(page, '.ip-flw-site-angle') == 0, 'angle readout left behind'
        for a, b in zip(turned['sides'], start['sides']):
            close(a, b, 1e-6, 'side length after the turn')
        assert turned['viewBox'] == start['viewBox'], 'the map moved during a turn'
        report['turn'] = {'label': label, 'bearing': turned['pose']['bearingDegrees']}
        page.screenshot(path=str(out / '05-turned.png'))
        # Shift: 15 degree steps.
        turn_handle(page, turned['centre'], 22, shift=True)
        snapped = footprint(page)
        assert snapped['pose']['bearingDegrees'] % 15 == 0, snapped['pose']
        report['turn']['shiftSnapped'] = snapped['pose']['bearingDegrees']
        report['checks'].append('the handle turns the footprint about its centre; angle readout while turning; '
                                'Shift snaps to 15 degrees')

        # 4. A click on empty map deselects and folds the pane back.
        empty = empty_point(page)
        page.mouse.click(*empty)
        idle(page)
        assert count(page, '.ip-flw-site-selection') == 0, 'still selected'
        assert page.locator('.ip-flw-site-expand').is_visible(), 'pane not folded back'
        page.screenshot(path=str(out / '06-deselected.png'))
        report['checks'].append('a click on empty map deselects and folds the pane back')

        # 5. Navigation: dragging empty map pans; the wheel zooms; neither moves the footprint.
        page.mouse.move(*empty)
        page.mouse.down()
        page.mouse.move(empty[0] - 90, empty[1] - 40, steps=8)
        page.mouse.up()
        panned = footprint(page)
        assert panned['viewBox'] != snapped['viewBox'] and panned['pose'] == snapped['pose'], 'pan'
        assert count(page, '.ip-flw-site-selection') == 0, 'a pan selected the footprint'
        page.mouse.wheel(0, -400)
        page.wait_for_timeout(300)
        zoomed = footprint(page)
        assert zoomed['mpp'] < panned['mpp'] and zoomed['pose'] == snapped['pose'], 'wheel zoom'
        for a, b in zip(zoomed['outline'], snapped['outline']):
            close(a['x'], b['x'], 1e-6, 'outline anchored after zoom')
        report['checks'].append('dragging empty map pans; the wheel zooms; the footprint stays at the same place')

        # 6. PowerPoint-style: a press on the unselected footprint selects it, and dragging on moves it at once.
        # The drag carries it toward the middle of the map, so the nudges and measuring below stay on screen.
        grab = body_point(page)
        target = page.evaluate("""() => { const r=document.querySelector('#ip-flw-site-view').getBoundingClientRect();
            return [r.left + r.width * 0.55, r.top + r.height * 0.6]; }""")
        shift_x, shift_y = target[0] - grab[0], target[1] - grab[1]
        if math.hypot(shift_x, shift_y) < 80:
            shift_x, shift_y = shift_x - 120, shift_y + 60
        page.mouse.move(*grab)
        page.mouse.down()
        assert count(page, '.ip-flw-site-selection') == 1, 'not selected on the press'
        readout_before = centre_readout(page)[1]
        page.mouse.move(grab[0] + shift_x, grab[1] + shift_y, steps=10)
        readout_live = centre_readout(page)[1]
        page.mouse.up()
        idle(page)
        carried = footprint(page)
        assert carried['viewBox'] == zoomed['viewBox'], 'the map moved during a one-step drag'
        close(carried['pose']['x'] - zoomed['pose']['x'], shift_x * zoomed['mpp'], 1.5 * zoomed['mpp'],
              'one-step move east-west')
        close(carried['pose']['z'] - zoomed['pose']['z'], -shift_y * zoomed['mpp'], 1.5 * zoomed['mpp'],
              'one-step move north-south')
        assert carried['pose']['bearingDegrees'] == zoomed['pose']['bearingDegrees']
        assert readout_live != readout_before, 'the centre readout did not follow the drag'
        report['checks'].append('a press on the unselected footprint selects it and a drag from there moves it in the '
                                'same motion; the map stays still')

        # 7. Arrow keys nudge the selected footprint: 1 m, Shift 10 m, north up; the burst saves as one undo step.
        page.keyboard.press('ArrowRight')
        page.keyboard.press('ArrowRight')
        page.keyboard.press('Shift+ArrowUp')
        close(float(page.get_by_label('Building X (m)', exact=True).input_value()), carried['pose']['x'] + 2, 1e-6,
              'X field after nudging east 2 m')
        close(float(page.get_by_label('Building Z (m)', exact=True).input_value()), carried['pose']['z'] + 10, 1e-6,
              'Z field after nudging north 10 m')
        page.wait_for_function(SITE + '.buildingPose.z > ' + repr(carried['pose']['z'] + 9.5), timeout=10000)
        idle(page)
        nudged = footprint(page)
        assert nudged['viewBox'] == carried['viewBox'], 'the map moved during a nudge'
        close(nudged['pose']['x'], carried['pose']['x'] + 2, 1e-6, 'saved east nudge')
        close(nudged['pose']['z'], carried['pose']['z'] + 10, 1e-6, 'saved north nudge')
        page.screenshot(path=str(out / '08-nudged.png'))
        page.evaluate(APP + '.session.undo()')
        idle(page)
        assert page.evaluate(SITE + '.buildingPose') == carried['pose'], 'one undo takes back the whole burst'
        page.evaluate(APP + '.session.redo()')
        idle(page)
        assert page.evaluate(SITE + '.buildingPose') == nudged['pose'], 'redo the nudges'
        report['nudge'] = {'from': carried['pose'], 'to': nudged['pose']}
        report['checks'].append('arrow keys nudge 1 m (Shift 10 m) north up; the burst saves as one undo step')

        # 8. The centre readout: WGS84 as the site plan PDF gives it, and on the photo at the centre.
        latlon, text = centre_readout(page)
        expected = page.evaluate("""([x, z]) => { const s=""" + SITE + """; const S=window.InspectorProFacilitySite;
            return 'Building centre: ' + S.formatLatLon(S.propertyToLatLon(x, z, s.georeference.originLatitude,
                s.georeference.originLongitude)); }""", [nudged['centre']['x'], nudged['centre']['z']])
        assert text == expected, (text, expected)
        on_photo = geo(page, nudged['centre']['x'], nudged['centre']['z'])
        if on_photo:
            close(latlon[0], on_photo['latitude'], 2e-5, 'readout latitude against the photo')
            close(latlon[1], on_photo['longitude'], 2e-5, 'readout longitude against the photo')
        report['centreReadout'] = {'text': text, 'photo': on_photo}
        report['checks'].append('the Building settings show the centre in WGS84, as the site plan PDF does'
                                + (', matching the photo' if on_photo else ''))
        # Esc from the real keyboard reaches the map after a press on the footprint, and deselects.
        page.keyboard.press('Escape')
        idle(page)
        assert count(page, '.ip-flw-site-selection') == 0, 'Esc did not deselect'
        assert page.locator('.ip-flw-site-expand').is_visible(), 'pane not folded back after Esc'
        report['checks'].append('Esc from the keyboard deselects and folds the pane back')

        # 9. Measuring ignores the footprint (and entering it deselects).
        latest = footprint(page)
        page.mouse.click(*body_point(page))  # selected again, so the measure button has a selection to clear
        idle(page)
        assert count(page, '.ip-flw-site-selection') == 1
        page.locator('.ip-flw-site-measure-toggle').click()
        assert count(page, '.ip-flw-site-selection') == 0, 'measuring kept the selection'
        ends = [screen(page, latest['centre']['x'], latest['centre']['z']),
                screen(page, latest['centre']['x'] + 10, latest['centre']['z'])]
        for end in ends:
            assert page.evaluate("""([x, y]) => { const hit=document.elementFromPoint(x, y);
                return !!(hit && hit.closest('svg.ip-flw-site-canvas')); }""", end), ('measure point off the map', end)
        for end in ends:
            page.mouse.click(*end)
        hint = page.locator('.ip-flw-site-measure-hint').inner_text()
        if 'Distance: ' not in hint:
            page.screenshot(path=str(out / 'fail-measure.png'))
        assert 'Distance: ' in hint, ('no distance measured', hint)
        measured = float(hint.split('Distance: ')[1].split(' m')[0])
        close(measured, 10, 3 * latest['mpp'], 'measured 10 m across the footprint')
        assert count(page, '.ip-flw-site-selection') == 0, 'measuring selected the footprint'
        assert page.evaluate(SITE + '.buildingPose') == latest['pose'], 'measuring moved the footprint'
        report['measured'] = hint
        page.keyboard.press('Escape')
        assert page.locator('.ip-flw-site-measure-toggle').get_attribute('aria-pressed') == 'false', 'Esc kept measuring'
        report['checks'].append('measuring across the footprint measures and never selects or moves it; Esc ends it')

        # 10. The typed fields still apply; undo and redo.
        page.locator('.ip-flw-site-expand').click()
        page.locator('.ip-flw-site-panel').get_by_role('button', name='Building', exact=True).click()
        assert count(page, '.ip-flw-site-selection') == 1, 'the Building settings select the footprint'
        page.get_by_label('True bearing (degrees)', exact=True).fill('12.5')
        page.get_by_role('button', name='Apply building position', exact=True).click()
        idle(page)
        assert page.evaluate(SITE + '.buildingPose.bearingDegrees') == 12.5
        typed = footprint(page)
        page.evaluate(APP + '.session.undo()')
        idle(page)
        assert page.evaluate(SITE + '.buildingPose') == latest['pose'], 'undo'
        page.evaluate(APP + '.session.redo()')
        idle(page)
        assert page.evaluate(SITE + '.buildingPose') == typed['pose'], 'redo'
        report['checks'].append('typed bearing applies; undo and redo are exact')

        # 11. Save, reopen: the same place and turn; the interior untouched.
        page.evaluate(APP + '.session.save()')
        idle(page)
        open_app(page, base, identity)
        reopened = footprint(page)
        assert reopened['pose'] == typed['pose'], (reopened['pose'], typed['pose'])
        for a, b in zip(reopened['sides'], start['sides']):
            close(a, b, 1e-6, 'side length after reopening')
        assert interior == page.evaluate('JSON.stringify([' + APP + '.workspace.state.layout.placements,' + APP
                                         + '.workspace.state.layout.zones,' + APP + '.workspace.state.layout.routes])')
        page.screenshot(path=str(out / '07-reopened.png'))
        report['checks'].append('saved and reopened at the same place and bearing; interior unchanged')
        report['finalPose'] = reopened['pose']
        report['pageErrors'] = errors
        print(json.dumps(report, indent=1), flush=True)
        assert not errors, errors
        browser.close()


if __name__ == '__main__':
    main()
