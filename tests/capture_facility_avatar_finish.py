"""Real Three.js close-up renders; no backend, provider, or layout writes."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time

from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.runtime' / ('avatar-finish-' + time.strftime('%Y%m%d-%H%M%S'))


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main():
    OUT.mkdir(parents=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(ROOT / 'static')))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1800, 'height': 820}, device_scale_factor=1)
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(base + '/facility_layout_avatar.js')
            page.set_content('<style>body{margin:0;background:#e9edf0;font:14px Arial;color:#33404a}main{display:flex}section{width:450px}h2{font-size:16px;text-align:center}canvas{display:block}</style><main></main>')
            page.add_script_tag(url=base + '/facility_layout_avatar.js')
            stats = page.evaluate("""async base => {
                const THREE = await import(base + '/vendor/three/0.184.0/build/three.module.min.js');
                window.views = [];
                for (const [label, angle] of [['Front', Math.PI], ['Three-quarter', 2.4], ['Side', Math.PI / 2], ['Back', 0]]) {
                    const section = document.createElement('section');
                    section.innerHTML = '<h2>' + label + '</h2>';
                    document.querySelector('main').append(section);
                    const renderer = new THREE.WebGLRenderer({antialias:true, preserveDrawingBuffer:true});
                    renderer.setSize(450, 740); renderer.setPixelRatio(1);
                    renderer.setClearColor(0xe9edf0); renderer.toneMapping = THREE.ACESFilmicToneMapping;
                    section.append(renderer.domElement);
                    const scene = new THREE.Scene();
                    scene.add(new THREE.HemisphereLight(0xffffff, 0x7b8490, 2.1));
                    const key = new THREE.DirectionalLight(0xffffff, 2.7); key.position.set(-3, 5, -4); scene.add(key);
                    const fill = new THREE.DirectionalLight(0xc9e8ff, 1.3); fill.position.set(3, 2, 2); scene.add(fill);
                    const camera = new THREE.PerspectiveCamera(30, 450 / 740, .01, 30);
                    camera.position.set(Math.sin(angle) * 4.5, 1.4, Math.cos(angle) * 4.5);
                    camera.lookAt(0, .96, 0);
                    const avatar = InspectorProFacilityAvatar.createAvatar(THREE); scene.add(avatar.root);
                    avatar.update({position:{x:0,y:0,z:0},heading:0,snap:true});
                    renderer.render(scene, camera);
                    views.push({renderer,scene,camera,avatar});
                }
                return views.map(v => ({...v.avatar.snapshot(), triangles:v.renderer.info.render.triangles}));
            }""", base)
            idle = OUT / 'operator-idle-views.png'
            page.screenshot(path=str(idle))
            page.evaluate("""() => {for (const v of views) {
                for(let i=0;i<15;i++) v.avatar.update({position:{x:0,y:0,z:0},distance:.023,deltaSeconds:.02});
                v.renderer.render(v.scene,v.camera);
            }}""")
            walking = OUT / 'operator-walking-views.png'
            page.screenshot(path=str(walking))
            with Image.open(idle) as a, Image.open(walking) as b:
                assert ImageChops.difference(a,b).getbbox(), 'Gait must visibly change the articulated body'
                for i in range(4):
                    crop = a.crop((i*450, 40, (i+1)*450, 780)).convert('RGB')
                    pixels = list(crop.getdata())
                    assert sum(1 for r,g,b in pixels if g > r * 1.03 and b < r * .7) > 1000
            assert not errors, errors
            page.evaluate('() => views.forEach(v => {v.avatar.dispose();v.renderer.dispose();})')
            browser.close()
            (OUT / 'result.json').write_text(json.dumps({'status':'passed','views':stats,'errors':errors}, indent=2))
            print(str(OUT), flush=True)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
