"""Small real-browser UI check for shared walkthrough settings, without backend."""
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.runtime'/('walk-camera-controls-'+time.strftime('%Y%m%d-%H%M%S'))
OUT.mkdir(parents=True,exist_ok=True)
report={'status':'running','cases':[],'errors':[]}
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page()
    page.on('pageerror',lambda e:report['errors'].append(str(e)))
    def serve(route):
        path=route.request.url.removeprefix('http://camera.test/')
        if path.startswith('static/'):
            file=(ROOT/path).resolve()
            assert file.is_relative_to(ROOT/'static')
            kind='image/svg+xml' if file.suffix=='.svg' else 'image/png'
            route.fulfill(body=file.read_bytes(),content_type=kind)
        else:route.fulfill(body='<html><head></head><body><button id="settings" aria-label="Walkthrough camera settings"><img src="/static/assets/global-toolbar-icons/gear.png" alt=""></button></body></html>',content_type='text/html')
    page.route('http://camera.test/**',serve)
    try:
        page.goto('http://camera.test/')
        page.add_style_tag(content=(ROOT/'static/walkthrough_camera_settings.css').read_text())
        page.add_style_tag(content='''body{margin:0;background:var(--bg-panel);color:var(--text-primary)}
            #settings{position:absolute;right:12px;top:12px;width:32px;height:32px;display:grid;place-items:center;background:var(--bg-panel);border:1px solid var(--border-color)}
            #settings img{width:24px;height:24px}''')
        page.add_script_tag(content=(ROOT/'static/walkthrough_camera_settings.js').read_text())
        workspace=(ROOT/'static/facility_layout_workspace.js').read_text(encoding='utf8')
        assert "'Walkthrough camera settings', 'settings', false)" in workspace
        page.add_script_tag(content=workspace)
        page.evaluate('''()=>{const button=InspectorProFacilityWorkspace.Workspace.prototype._threeNavigationButton.call(
            {document,options:{}},'camera-settings','Walkthrough camera settings','settings',false);
            button.id='settings';document.getElementById('settings').replaceWith(button);}''')
        assert page.locator('#settings img').get_attribute('src')=='/static/assets/global-toolbar-icons/gear.png'
        page.evaluate('''()=>{window.changes=[];window.control=InspectorProWalkthroughCamera.createControl({document,button:document.getElementById('settings'),onChange:v=>changes.push(v)});}''')
        for theme,width,height in [('dark',900,700),('light',900,700),('dark',360,560),('light',360,560)]:
            page.set_viewport_size({'width':width,'height':height})
            page.evaluate('''theme=>{const r=document.documentElement;r.dataset.theme=theme;
                r.style.setProperty('--bg-panel',theme==='dark'?'#1d222c':'#ffffff');
                r.style.setProperty('--text-primary',theme==='dark'?'#e4e8ed':'#172331');
                r.style.setProperty('--border-color',theme==='dark'?'#647180':'#b9c5cf');}''',theme)
            page.locator('#settings').click()
            panel=page.get_by_role('dialog',name='Walkthrough camera settings')
            panel.get_by_role('button',name='Wide',exact=True).click()
            slider=panel.get_by_label('Follow distance',exact=True)
            slider.focus();page.keyboard.press('ArrowRight')
            assert float(slider.input_value())>9
            assert page.evaluate('document.activeElement.dataset.cameraField')=='distance'
            page.evaluate('control.sync(InspectorProWalkthroughCamera.load())')
            assert page.evaluate('document.activeElement.dataset.cameraField')=='distance'
            assert panel.locator('[aria-pressed="true"]').count()==0
            panel.get_by_label('Reset camera settings',exact=True).click()
            assert float(slider.input_value())==5
            panel.get_by_role('button',name='Wide',exact=True).click()
            box=panel.bounding_box()
            assert box['x']>=0 and box['y']>=0 and box['x']+box['width']<=width and box['y']+box['height']<=height
            # Verify text/background contrast using actual composited colors from Chromium.
            colors=panel.get_by_role('button',name='Close',exact=True).evaluate('''el=>{
                const s=getComputedStyle(el),canvas=document.createElement('canvas');canvas.width=canvas.height=1;
                const c=canvas.getContext('2d');return ['color','backgroundColor'].map(k=>{c.fillStyle=s[k];c.fillRect(0,0,1,1);return [...c.getImageData(0,0,1,1).data].slice(0,3);});}''')
            def luminance(rgb):
                v=[x/255 for x in rgb]
                v=[x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4 for x in v]
                return sum(a*b for a,b in zip(v,[.2126,.7152,.0722]))
            a,b=map(luminance,colors)
            contrast=(max(a,b)+.05)/(min(a,b)+.05)
            assert contrast>=4.5,(theme,colors,contrast)
            page.wait_for_function('[...document.images].every(i=>i.complete&&i.naturalWidth>0)')
            page.screenshot(path=str(OUT/f'{theme}-{width}.png'))
            report['cases'].append({'theme':theme,'width':width,'height':height,'contrast':contrast,'panel':box})
            page.keyboard.press('Escape')
            assert panel.is_hidden() and page.locator('#settings').evaluate('el=>document.activeElement===el')
        page.locator('#settings').click()
        page.evaluate("document.getElementById('settings').style.display='none'")
        page.wait_for_function('control.panel.hidden')
        page.evaluate('control.dispose()')
        assert page.locator('.ip-walk-camera-panel').count()==0
        assert not report['errors'],report['errors']
        report['status']='passed'
    except Exception as e:
        report.update(status='failed',error=repr(e));raise
    finally:
        browser.close()
        (OUT/'result.json').write_text(json.dumps(report,indent=2))
        print(str(OUT),flush=True)
