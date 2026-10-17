"""Read-only Playwright verification of the saved normal-desktop sports extension."""
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Path.home()/'AppData/Roaming/Python/Python314/site-packages'))
from PIL import Image
# Electron may keep optional fonts pending; verify the rendered pixels instead.
os.environ['PW_TEST_SCREENSHOT_NO_FONTS_READY']='1'
from playwright.sync_api import sync_playwright

OUT=ROOT/'.runtime/private-gym-sports-20261007'
CURRENT='window._trainFacilityLayoutAuthoringApp'


def main():
    if '--prepare' in sys.argv:
        profile=json.loads((OUT/'profile.json').read_text())
        profile.update(profileId='private-gym-sports-saved',origin='http://127.0.0.1:8542',
                       dataRoot=str(OUT/'saved-desktop'),backendId=str(uuid.uuid4()),storeId=str(uuid.uuid4()))
        (OUT/'saved-desktop').mkdir(exist_ok=True)
        (OUT/'saved-desktop/profile.json').write_text(json.dumps(profile,indent=2))
        return
    saved=json.loads((OUT/'saved.json').read_text())
    target=ROOT/'.runtime/facility-layout/layouts/local/site-local/layouts/fl-private-gym-20261007.json'
    before=hashlib.sha256(target.read_bytes()).hexdigest()
    report=dict(status='running',walk=[],captures={})
    def persist(): (OUT/'playwright-check.json').write_text(json.dumps(report,indent=2))
    persist()
    try:
        with sync_playwright() as p:
            browser=p.chromium.connect_over_cdp('http://127.0.0.1:9542',timeout=20000)
            client=browser.new_browser_cdp_session()
            deadline=time.monotonic()+120
            page=None
            while page is None and time.monotonic()<deadline:
                client.send('Target.getTargets')
                page=next((v for c in browser.contexts for v in c.pages if v.url.startswith('http://127.0.0.1:8542/')),None)
                time.sleep(.5)
            assert page is not None,'Normal desktop page did not open'
            page_client=page.context.new_cdp_session(page)
            page_client.send('Emulation.clearDeviceMetricsOverride')
            page.wait_for_function(CURRENT+'?.session?.getState().loaded',timeout=120000)
            def js(code):return page.evaluate(code)
            def capture(name):
                raw=page.screenshot(path=str(OUT/(name+'.png')))
                colors=len(Image.open(io.BytesIO(raw)).convert('RGB').getcolors(10000000) or [])
                assert colors>1000,'Blank or insufficiently rendered viewport'
                report['captures'][name]=dict(distinctColors=colors);persist()
            assert js(CURRENT+'.session.getState().layout')==saved
            assert not js(CURRENT+'.session.getState().dirty')
            js(CURRENT+".workspace._setViewMode('plan')")
            page.wait_for_timeout(1500);capture('06-saved-plan')
            js(CURRENT+".workspace._setViewMode('3d')")
            page.wait_for_function(CURRENT+'.workspace.threeAdapter.getDiagnostics().pendingLoads===0')
            page.wait_for_timeout(2000);capture('07-saved-desktop-3d')
            page.bring_to_front()
            js(CURRENT+".workspace.threeAdapter.exitWalkthrough('review-reset')")
            page.locator('#trainFacilityLayoutAuthoring canvas:visible').last.click()
            start=js(CURRENT+'.workspace.threeAdapter.enterWalkthrough({ignoreSelection:true,worldPoint:{x:59,z:11}})')
            report['walkStart']=start;persist()
            assert start['active']
            page.wait_for_function(CURRENT+'.workspace.threeAdapter.getWalkthroughState().locked',timeout=10000)
            for point in [dict(x=62.5,z=11),dict(x=62.5,z=14.4),dict(x=77,z=14.4),dict(x=77,z=17),dict(x=71.5,z=19),dict(x=71.5,z=29)]:
                plan=js(CURRENT+'.workspace.threeAdapter.navigateWalkthroughToPoint('+json.dumps(point)+')')
                assert plan['ok'],plan
                page.wait_for_function('!'+CURRENT+'.workspace.threeAdapter.getWalkthroughState().route.active',timeout=90000)
                state=js(CURRENT+'.workspace.threeAdapter.getWalkthroughState()')
                assert math.hypot(state['position']['x']-point['x'],state['position']['z']-point['z'])<.3,state
                report['walk'].append(dict(goal=point,position=state['position']));persist()
            capture('09-court-on-foot')
            js(CURRENT+".workspace.threeAdapter.exitWalkthrough('review')")
            assert js(CURRENT+'.session.getState().layout')==saved
            assert not js(CURRENT+'.session.getState().dirty')
            assert hashlib.sha256(target.read_bytes()).hexdigest()==before
            report.update(status='passed',savedBytesUnchanged=True,
                          compactWindowCoverage='not established: Electron viewport emulation stalled capture')
    except Exception as error:
        report.update(status='failed',error=str(error))
        raise
    finally:persist()


if __name__=='__main__':main()
