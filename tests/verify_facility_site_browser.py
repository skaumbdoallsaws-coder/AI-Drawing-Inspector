"""SC2/SC3 browser acceptance against the isolated test server; no model requests.
Creates a named test layout through the real API, never edits the source layout.
"""
import json
from pathlib import Path
import time
from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8491'
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'ui-data' / 'site-checks'
SOURCE = 'fl-eb787390-dec6-458d-9813-60aa7de09692'
APP = 'window._trainFacilityLayoutAuthoringApp'
SITE = APP + '.workspace.state.layout.extensions.facilitySiteContext'

def open_layout(page, layout_id):
    page.goto(BASE + '/?facilityLayoutId=' + layout_id)
    page.wait_for_function('!!window.InspectorProFacilityStructure', timeout=90000)
    page.get_by_role('tab', name='Workflows', exact=True).click()
    page.wait_for_selector('#trainingTypeRibbonSelect', state='attached')
    page.evaluate("""() => { const s=document.getElementById('trainingTypeRibbonSelect');
        s.value='facility_layout'; s.dispatchEvent(new Event('change',{bubbles:true})); }""")
    page.wait_for_function('!!(' + APP + '?.workspace)', timeout=120000)
    page.locator(".ip-flw-view-tab[data-view='site']").click()
    page.wait_for_selector('.ip-flw-site-building')

def idle(page):
    page.wait_for_function("document.querySelector('#ip-flw-site-view').getAttribute('aria-busy') !== 'true'")
    page.wait_for_timeout(150)

def point(page, x, z):
    return page.evaluate("""([x,z]) => { const e=document.querySelector('.ip-flw-site-canvas');
        const p=e.createSVGPoint(); p.x=x;p.y=-z; const s=p.matrixTransform(e.getScreenCTM());
        return {x:s.x,y:s.y}; }""", [x,z])

def click_point(page, x, z):
    p=point(page,x,z); page.mouse.click(p['x'],p['y'])

def main():
    assert ROOT.name == 'InspectorPro-CopilotTest', 'This check must never run against the desktop store'
    OUT.mkdir(parents=True, exist_ok=True)
    identity = 'fl-site-acceptance-' + str(int(time.time()))
    print('Checking '+identity,flush=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1600,'height':950})
        errors=[]; page.on('pageerror', lambda e: errors.append(str(e)))
        open_layout(page,SOURCE)
        result=page.evaluate("""async id => {const a=window._trainFacilityLayoutAuthoringApp;
            const doc=JSON.parse(JSON.stringify(a.workspace.state.layout));
            doc.layoutId=id;doc.displayName='Site acceptance - boundary and pose';doc.status='draft';
            delete doc.extensions.facilitySiteContext.property;
            return a.transport.createLayout(doc); }""",identity)
        assert result.get('layout'), list(result)
        open_layout(page,identity)
        interior=page.evaluate("JSON.stringify(["+APP+".workspace.state.layout.placements,"+APP+".workspace.state.layout.zones,"+APP+".workspace.state.layout.routes])")
        reference=page.evaluate(SITE+'.georeference')
        page.get_by_role('button',name='Property',exact=True).click()
        page.evaluate(APP+'.workspace.siteView.zoomBy(2)')
        page.get_by_role('button',name='Draw boundary',exact=True).click()
        for x,z in [(-40,-50),(90,-50),(90,70),(-40,70)]: click_point(page,x,z)
        page.get_by_role('button',name='Finish boundary',exact=True).click();idle(page)
        page.wait_for_function(SITE+'.property?.boundary.length === 4')
        page.get_by_label('Edge 1 type',exact=True).select_option('street')
        page.get_by_label('Street setback (m)',exact=True).fill('80')
        page.get_by_role('button',name='Apply setbacks and edge types',exact=True).click();idle(page)
        page.wait_for_selector('[data-site-finding="site_setback_violation"]')
        assert 'Edge 1' in page.locator('[data-site-finding="site_setback_violation"]').first.inner_text()
        page.screenshot(path=str(OUT/'sc2-setback-warning.png'))
        page.get_by_label('Street setback (m)',exact=True).fill('5')
        page.get_by_role('button',name='Apply setbacks and edge types',exact=True).click();idle(page)
        page.locator('.ip-flw-site-panel summary',has_text='Entrances').click()
        page.get_by_label('Entrance edge',exact=True).select_option('0')
        page.get_by_label('Entrance use',exact=True).select_option('trucks')
        page.get_by_label('Entrance width (m)',exact=True).fill('8')
        page.get_by_role('button',name='Add entrance',exact=True).click();idle(page)
        assert len(page.evaluate(SITE+'.property.entrances'))==1
        page.get_by_role('button',name='Building',exact=True).click()
        page.get_by_label('Building X (m)',exact=True).fill('5')
        page.get_by_label('Building Z (m)',exact=True).fill('0')
        page.get_by_label('True bearing (degrees)',exact=True).fill('30')
        before=page.evaluate(SITE)
        page.get_by_role('button',name='Apply building position',exact=True).click();idle(page)
        assert page.evaluate(SITE+'.buildingPose.bearingDegrees')==30
        assert page.evaluate(SITE+'.georeference')==reference
        assert interior==page.evaluate("JSON.stringify(["+APP+".workspace.state.layout.placements,"+APP+".workspace.state.layout.zones,"+APP+".workspace.state.layout.routes])")
        after=page.evaluate(SITE)
        page.evaluate(APP+'.session.undo()');idle(page)
        assert page.evaluate(SITE)==before
        page.evaluate(APP+'.session.redo()');idle(page)
        assert page.evaluate(SITE)==after
        handle=page.locator('circle[data-site-pose="move"]').bounding_box()
        page.mouse.move(handle['x']+handle['width']/2,handle['y']+handle['height']/2)
        page.mouse.down();page.mouse.move(handle['x']+handle['width']/2+35,handle['y']+handle['height']/2,steps=8);page.mouse.up();idle(page)
        assert page.evaluate(SITE+'.buildingPose.x') > after['buildingPose']['x']
        assert page.evaluate(SITE+'.property')==after['property']
        page.screenshot(path=str(OUT/'sc2-building-pose.png'))
        final=page.evaluate(SITE)
        page.evaluate(APP+'.session.save()');idle(page)
        open_layout(page,identity)
        assert page.evaluate(SITE)==final
        page.get_by_role('button',name='Property',exact=True).click()
        page.wait_for_selector('.ip-flw-site-metrics details')
        page.wait_for_timeout(1200)
        page.screenshot(path=str(OUT/'sc2-reopened.png'))
        print('SC2 passed; drawing outdoor areas',flush=True)
        page.evaluate(APP+'.workspace.siteView.zoomBy(0.75)')
        page.get_by_role('button',name='Areas',exact=True).click()
        rectangles=[('Truck court','truck_court',-30,-20,-5,5),('Trailers','trailer_parking',-30,5,-5,25),
            ('Drive','drive',-30,-30,70,-20),('Car parking','parking',40,20,70,40),
            ('Sidewalk','sidewalk',30,20,40,40),('Landscape','landscape',-30,35,20,55),
            ('Storage','outdoor_storage',40,45,60,60)]
        for index,(name,kind,x,z,right,top) in enumerate(rectangles):
            page.get_by_label('Outdoor area',exact=True).select_option('')
            page.get_by_label('Area name',exact=True).fill(name)
            page.get_by_label('Area kind',exact=True).select_option(kind)
            if index==0:
                page.get_by_role('button',name='Draw area',exact=True).click()
                for px,pz in [(x,z),(right,z),(right,top),(x,top)]:click_point(page,px,pz)
                page.get_by_role('button',name='Finish area',exact=True).click()
            else:
                page.get_by_label('Area vertices X, Z (m)',exact=True).fill(f'{x},{z}\n{right},{z}\n{right},{top}\n{x},{top}')
                page.get_by_role('button',name='Apply area',exact=True).click()
            idle(page)
            page.wait_for_function(SITE+f'.areas?.length === {index+1}')
        analysis=page.evaluate(APP+'.session.analyzeSiteContext()')
        assert not analysis['findings'],analysis
        assert len(analysis['metrics']['areas'])==7
        site_before=page.evaluate(SITE)
        page.get_by_role('button',name='Delete area',exact=True).click();idle(page)
        assert len(page.evaluate(SITE+'.areas'))==6
        page.evaluate(APP+'.session.undo()');idle(page)
        assert page.evaluate(SITE)==site_before
        page.evaluate(APP+'.session.redo()');idle(page)
        assert len(page.evaluate(SITE+'.areas'))==6
        page.evaluate(APP+'.session.undo()');idle(page)
        page.get_by_role('button',name='Building',exact=True).click()
        page.get_by_role('button',name='Walls and dock openings',exact=True).click()
        dialog=page.get_by_role('dialog',name='Perimeter walls',exact=True)
        dialog.get_by_role('button',name='Add opening',exact=True).click()
        dialog.get_by_label('Opening edge',exact=True).last.select_option('3')
        dialog.get_by_label('Opening start (m)',exact=True).last.fill('4')
        dialog.get_by_label('Opening end (m)',exact=True).last.fill('8')
        dialog.get_by_role('button',name='Apply',exact=True).click()
        dialog.wait_for(state='detached');idle(page)
        page.evaluate(APP+'.session.save()');idle(page)
        open_layout(page,identity)
        assert page.evaluate(SITE)==site_before
        page.get_by_role('button',name='Areas',exact=True).click()
        page.wait_for_selector('.ip-flw-site-metrics details')
        page.screenshot(path=str(OUT/'sc3-outdoor-plan.png'))
        print('SC3 site plan saved and reopened; checking 3D',flush=True)
        page.locator(".ip-flw-view-tab[data-view='3d']").click()
        page.wait_for_function(APP+'.workspace.threeAdapter?.getDiagnostics().site.areaIds.length === 7',timeout=120000)
        page.evaluate(APP+'.workspace.threeAdapter.topView()')
        page.wait_for_timeout(2500)
        diagnostics=page.evaluate(APP+'.workspace.threeAdapter.getDiagnostics()')
        assert diagnostics['site']['groundLoaded']
        assert diagnostics['cameraOrientation']['reference']=='true-north'
        assert min(diagnostics['cameraOrientation']['headingDegrees'],360-diagnostics['cameraOrientation']['headingDegrees'])<.01,diagnostics['cameraOrientation']
        page.screenshot(path=str(OUT/'sc3-outdoor-top.png'))
        from PIL import Image
        from collections import Counter
        pixels=Counter(Image.open(OUT/'sc3-outdoor-top.png').convert('RGB').getdata())
        green=sum(n for (r,g,b),n in pixels.items() if g>r*1.15 and g>b*1.1)
        assert green>2000,('missing grass and photo pixels',green)
        page.evaluate(APP+'.workspace.threeAdapter.fitFacility()');page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT/'sc3-outdoor-perspective.png'))
        page.set_viewport_size({'width':800,'height':700});page.wait_for_timeout(800)
        page.evaluate(APP+'.workspace.threeAdapter.fitFacility()');page.wait_for_timeout(800)
        page.screenshot(path=str(OUT/'sc3-compact.png'))
        print(json.dumps({'layoutId':identity,'boundaryDrawn':True,'edgeWarning':True,
            'entranceAdded':True,'poseEditedAndDragged':True,'interiorUnchanged':True,
            'undoRedo':True,'saveReopen':True,'outdoorAreas':7,'dockOpening':True,
            'siteAnalysisClean':True,'threeAreaIds':diagnostics['site']['areaIds'],
            'greenPixelCount':green,'pageErrors':errors}),flush=True)
        assert not errors,errors
        browser.close()

if __name__=='__main__':
    import sys
    if '--preview-only' in sys.argv:
        from verify_facility_site_preview import main as preview_main
        preview_main()
    else:
        main()
