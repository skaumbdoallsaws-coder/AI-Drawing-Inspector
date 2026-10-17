"""Read-only viewport and wall-dialog checks against the active local gym backend."""
import hashlib
import io
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Path.home()/'AppData/Roaming/Python/Python314/site-packages'))
os.environ['PW_TEST_SCREENSHOT_NO_FONTS_READY']='1'
from PIL import Image
from playwright.sync_api import sync_playwright

OUT=ROOT/'.runtime/private-gym-exterior-20261007'
APP='window._trainFacilityLayoutAuthoringApp'


def main():
    target=ROOT/'.runtime/facility-layout/layouts/local/site-local/layouts/fl-private-gym-20261007.json'
    before=hashlib.sha256(target.read_bytes()).hexdigest()
    saved=json.loads(target.read_bytes())
    report=dict(status='running',captures=[],errors=[])
    def persist():(OUT/'browser-check.json').write_text(json.dumps(report,indent=2))
    persist()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page(viewport=dict(width=1440,height=900))
            page.set_default_timeout(60000)
            page.on('pageerror',lambda error:report['errors'].append(str(error)))
            response=page.goto('http://127.0.0.1:8544/?facilityLayoutId=fl-private-gym-20261007',wait_until='domcontentloaded',timeout=120000)
            if response is None or not response.ok:
                status=response.status if response else 'no response'
                raise RuntimeError(f'Browser entry refused ({status}); desktop authentication is not bypassed by this check.')
            page.get_by_role('tab',name='Workflows',exact=True).click()
            page.select_option('#trainingTypeRibbonSelect','facility_layout')
            page.wait_for_function(APP+'?.session.getState().loaded',timeout=150000)
            assert page.evaluate(APP+'.session.getState().layout')==saved
            page.evaluate(APP+".workspace._setViewMode('3d')")
            page.wait_for_function(APP+'.workspace.threeAdapter.getDiagnostics().pendingLoads===0 && '+APP+'.workspace.threeAdapter.getDiagnostics().exteriorArtwork?.filter(a=>a.status==="ready").length===3',timeout=150000)
            page.evaluate('''()=>{const a='''+APP+'''.workspace.threeAdapter,v=a.getCameraView();
                a.applyCameraView({...v,position:{x:14,y:2.5,z:-11},target:{x:14,y:1.8,z:0},up:{x:0,y:1,z:0}});}''')
            for width,height in [(1440,900),(900,700),(390,844)]:
                page.set_viewport_size(dict(width=width,height=height))
                page.wait_for_timeout(1200)
                raw=page.screenshot(path=str(OUT/f'browser-{width}.png'))
                colors=len(Image.open(io.BytesIO(raw)).convert('RGB').getcolors(10000000) or [])
                assert colors>1000
                report['captures'].append(dict(width=width,height=height,distinctColors=colors));persist()
            page.set_viewport_size(dict(width=1440,height=900))
            page.evaluate('InspectorProFacilityWalls.openDialog('+APP+'.workspace)')
            dialog=page.get_by_role('dialog',name='Perimeter walls')
            assert dialog.get_by_label('Exterior finish',exact=True).is_checked()
            assert dialog.get_by_label('Exterior color',exact=True).input_value()==saved['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['color']
            page.screenshot(path=str(OUT/'browser-wall-settings.png'))
            dialog.get_by_role('button',name='Cancel',exact=True).click()
            assert page.evaluate(APP+'.session.getState().layout')==saved
            assert not page.evaluate(APP+'.session.getState().dirty')
            assert hashlib.sha256(target.read_bytes()).hexdigest()==before
            report.update(status='passed',savedBytesUnchanged=True)
            browser.close()
    except Exception as error:
        report.update(status='failed',error=str(error));raise
    finally:persist()


if __name__=='__main__':main()
