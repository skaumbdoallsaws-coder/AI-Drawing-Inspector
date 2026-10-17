"""Isolated Playwright rendering checks; no application store or provider calls."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import sys
from threading import Thread
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai_inspector.facility_layout.perimeter_walls import compile_perimeter_walls
from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright


def verify(output):
    layout = {'placements': [], 'extensions': {}}
    boundary = [dict(x=x, z=z) for x, z in [(3,3),(27,3),(27,15),(17,15),(17,27),(3,27)]]
    layout['extensions']['facilityPerimeterWalls'] = compile_perimeter_walls({
        'boundarySource':'polygon', 'boundary':boundary, 'heightMeters':4, 'thicknessMeters':.3,
        'openings':[dict(edge=0,startMeters=9,endMeters=13)]}, layout)
    html = '''<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="stylesheet" href="/static/facility_layout_workspace.css">
    <style>html,body{margin:0;width:100%;height:100%}#root{min-width:0;min-height:0}#scene{position:absolute;inset:0}</style>
    <script type="importmap">{"imports":{"three":"/static/vendor/three/0.184.0/build/three.module.min.js"}}</script>
    <script src="/static/facility_layout_avatar.js"></script>
    <script src="/static/walkthrough_camera_settings.js"></script>
    <script src="/static/facility_layout_walls.js"></script><script src="/static/facility_layout_three_adapter.js"></script>
    </head><body><main id="root" class="ip-flw-root"><div id="scene"></div></main>
    <script type="module">
    import * as THREE from 'three';
    import {OrbitControls} from '/static/vendor/three/0.184.0/examples/jsm/controls/OrbitControls.js';
    const layout=LAYOUT;
    window.adapter=InspectorProFacilityThree.createThreeAdapter({THREE,OrbitControls,
        worldBounds:{minX:0,minZ:0,maxX:40,maxZ:30,floorY:0}});
    adapter.mount(document.getElementById('scene'));await adapter.setScene({layout,assetCatalog:[]});
    const v=adapter.getCameraView();v.position={x:43,y:36,z:46};v.target={x:15,y:0,z:15};
    v.up={x:0,y:1,z:0};v.fov=45;adapter.applyCameraView(v);
    window.workspace={root:document.getElementById('root'),document,capabilities:{manualAuthoring:true},
        _selectedZoneRecord:()=>null,session:{getState:()=>({loaded:true,layout,draftRevision:'test'})}};
    window.ready=true;
    </script></body></html>'''.replace('LAYOUT', json.dumps(layout))

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == '/':
                body = html.encode()
                self.send_response(200); self.send_header('Content-Type', 'text/html')
                self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
            elif self.path.startswith('/static/'):
                super().do_GET()
            else:
                self.send_error(404)

    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(ROOT)))
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    report = {'status':'running', 'viewports':[]}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--enable-unsafe-swiftshader'])
            try:
                for width, height in [(1440,900),(390,700)]:
                    page = browser.new_page(viewport={'width':width,'height':height})
                    errors = []
                    def record_error(error):
                        errors.append(str(error))
                        (output / 'page-errors.json').write_text(json.dumps(errors))
                    page.on('pageerror', record_error)
                    page.goto(f'http://127.0.0.1:{server.server_port}/')
                    page.wait_for_function('window.ready === true'); page.wait_for_timeout(600)
                    visible = page.screenshot(path=str(output / f'{width}-walls.png'))
                    diagnostics = page.evaluate('adapter.getDiagnostics()')
                    assert diagnostics['perimeterWallCount'] > 0 and not diagnostics['degraded']
                    page.evaluate('adapter.setLayerVisibility({walls:false})'); page.wait_for_timeout(300)
                    hidden = page.screenshot(path=str(output / f'{width}-hidden.png'))
                    diff = ImageChops.difference(Image.open(BytesIO(visible)).convert('RGB'),
                                                Image.open(BytesIO(hidden)).convert('RGB'))
                    changed = sum(1 for pixel in diff.getdata() if max(pixel) > 20)
                    assert changed > 500, f'Wall pixels were missing at {width}px'
                    page.evaluate('adapter.setLayerVisibility({walls:true})')
                    before = page.evaluate('adapter.getCameraView()')
                    page.mouse.move(width//2,height//2); page.mouse.wheel(0,-250); page.wait_for_timeout(500)
                    assert page.evaluate('adapter.getCameraView()') != before
                    page.evaluate('InspectorProFacilityWalls.openDialog(workspace)')
                    dialog = page.get_by_role('dialog', name='Perimeter walls')
                    dialog.wait_for(state='visible'); page.wait_for_timeout(300)
                    page.screenshot(path=str(output / f'{width}-dialog.png'))
                    bounds = dialog.bounding_box()
                    assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width
                    assert bounds['y'] >= 0 and bounds['y'] + bounds['height'] <= height
                    page.get_by_role('button',name='Cancel',exact=True).click()
                    assert not errors, errors
                    report['viewports'].append({'width':width,'height':height,'changedWallPixels':changed,
                        'cameraInteraction':True,'dialogFits':True})
                    page.close()
            finally:
                browser.close()
        report['status'] = 'passed'
    except Exception as error:
        report.update(status='failed', error=str(error))
        raise
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        (output / 'report.json').write_text(json.dumps(report, indent=2))


if __name__ == '__main__':
    output = Path(sys.argv[1]); output.mkdir(parents=True, exist_ok=False)
    try:
        verify(output)
    except Exception:
        (output / 'error.txt').write_text(traceback.format_exc())
        raise
