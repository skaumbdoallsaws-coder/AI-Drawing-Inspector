"""Render the Facility library's own thumbnails with one camera and fixed lighting.

Usage:
    python tools/facility_library/render_thumbnails.py [--only appearances|scenes] [--ids ID[,ID...]]

--ids renders only those appearances or scenes (for example a newly added group), so
the other thumbnails stay byte-for-byte as they are.

Headless Chromium (Playwright) loads the application's own three.js build, the
library manifests and facility_layout_finishes.js through a request route, so
no server is needed and the thumbnails match what the viewport renders:

* every appearance on a 0.5 m sphere, neutral room light plus one key light
  (a Lights finish in a dim room on a dark backdrop, so its glow color shows);
* every scene as a chrome and a white sphere on a floor under that scene.

PNGs are written to static/facility_library/thumbnails/{appearances,scenes}/.
"""
import argparse
import base64
import mimetypes
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "static"
OUTPUT = STATIC / "facility_library" / "thumbnails"
ORIGIN = "http://library.local"

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<script type="importmap">{"imports":{"three":"/static/vendor/three/0.184.0/build/three.module.min.js",
"three/addons/":"/static/vendor/three/0.184.0/examples/jsm/"}}</script>
<script src="/static/facility_layout_library.js"></script>
<script src="/static/facility_layout_finishes.js"></script>
</head><body style="margin:0;background:transparent"><script type="module">
import * as THREE from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { HDRLoader } from 'three/addons/loaders/HDRLoader.js';
const lib = window.InspectorProFacilityLibrary, fin = window.InspectorProFacilityFinishes;

function makeRenderer(width, height, alpha) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1);
  renderer.setSize(width, height);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  return renderer;
}

async function appearances(library, ids) {
  const renderer = makeRenderer(192, 192, true);
  const pmrem = new THREE.PMREMGenerator(renderer);
  const room = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  const textures = fin.createTextureCache(THREE, { anisotropy: 8 });
  const scene = new THREE.Scene();
  scene.environment = room;
  const key = new THREE.DirectionalLight(0xffffff, 1.4);
  key.position.set(2, 3, 2.5);
  scene.add(key);
  const camera = new THREE.PerspectiveCamera(28, 1, 0.01, 10);
  camera.position.set(0, 0.14, 1.3);
  camera.lookAt(0, 0, 0);
  const sphere = new THREE.SphereGeometry(0.25, 96, 64);
  const bounds = { min: { x: -0.25, y: -0.25, z: -0.25 }, max: { x: 0.25, y: 0.25, z: 0.25 } };
  // See-through finishes need something behind them, or glass reads as gray.
  const checker = document.createElement('canvas');
  checker.width = checker.height = 64;
  const context = checker.getContext('2d');
  for (let y = 0; y < 8; y += 1) for (let x = 0; x < 8; x += 1) {
    context.fillStyle = (x + y) % 2 ? '#3a4652' : '#c9d2da';
    context.fillRect(x * 8, y * 8, 8, 8);
  }
  const checkerTexture = new THREE.CanvasTexture(checker);
  checkerTexture.colorSpace = THREE.SRGBColorSpace;
  const backdrop = new THREE.Mesh(new THREE.PlaneGeometry(1.4, 1.4), new THREE.MeshBasicMaterial({ map: checkerTexture }));
  backdrop.position.set(0, 0, -0.6);
  // A light is drawn as a lamp seen in a dim room (dark backdrop, key light and room turned down), so its glow
  // color shows; under the full key light every pale lens would clip to the same white.
  const dim = new THREE.Mesh(new THREE.PlaneGeometry(1.4, 1.4), new THREE.MeshBasicMaterial({ color: 0x1b2129 }));
  dim.position.set(0, 0, -0.6);
  const out = {};
  for (const row of library.appearances.values()) {
    if (ids && !ids.includes(row.appearanceId)) continue;
    const resolved = lib.resolveAppearance(library, { appearanceId: row.appearanceId }, {});
    const material = fin.createFinishMaterial(THREE, resolved, { textures, scale: 1 });
    const mapping = fin.mappingFor(THREE, null, resolved, bounds);
    const geometry = mapping ? fin.finishGeometry(THREE, sphere, null, mapping) : sphere;
    const mesh = new THREE.Mesh(geometry, material);
    const seeThrough = (resolved.transmission || 0) > 0 || resolved.opacity < 1;
    if (seeThrough) scene.add(backdrop);
    if (resolved.emission) {
      scene.add(dim);
      key.intensity = 0.35;
      scene.environmentIntensity = 0.3;
    }
    scene.add(mesh);
    await textures.whenSettled();
    renderer.render(scene, camera);
    out[row.appearanceId] = renderer.domElement.toDataURL('image/png');
    scene.remove(mesh);
    scene.remove(backdrop);
    scene.remove(dim);
    key.intensity = 1.4;
    scene.environmentIntensity = 1;
    material.dispose();
    if (geometry !== sphere) geometry.dispose();
  }
  return out;
}

async function scenes(library, ids) {
  const renderer = makeRenderer(240, 176, false);
  const pmrem = new THREE.PMREMGenerator(renderer);
  const room = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  const out = {};
  for (const row of library.scenes.values()) {
    if (ids && !ids.includes(row.sceneId)) continue;
    const resolved = lib.resolveScene(library, { version: 1, sceneId: row.sceneId });
    const scene = new THREE.Scene();
    let equirect = null;
    if (resolved.environment === 'room') scene.environment = room;
    else if (resolved.environmentUrl) {
      equirect = await new HDRLoader().loadAsync(resolved.environmentUrl);
      equirect.mapping = THREE.EquirectangularReflectionMapping;
      scene.environment = pmrem.fromEquirectangular(equirect).texture;
    }
    scene.environmentIntensity = resolved.environmentIntensity || 1;
    scene.background = /^#/.test(resolved.background) ? new THREE.Color(resolved.background)
      : resolved.background === 'environment' && equirect ? equirect : new THREE.Color('#2b333e');
    scene.add(new THREE.HemisphereLight(0xffffff, 0x334155, resolved.ambient));
    const sun = new THREE.DirectionalLight(0xffffff, resolved.directional);
    sun.position.set(8, 16, 10);
    scene.add(sun);
    renderer.toneMappingExposure = resolved.exposure;
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(6, 6), new THREE.MeshStandardMaterial({ color: 0x8a9096, roughness: 0.85 }));
    floor.rotation.x = -Math.PI / 2;
    const chrome = new THREE.Mesh(new THREE.SphereGeometry(0.3, 64, 48), new THREE.MeshStandardMaterial({ color: 0xffffff, metalness: 1, roughness: 0.06 }));
    chrome.position.set(-0.36, 0.3, 0);
    const white = new THREE.Mesh(new THREE.SphereGeometry(0.3, 64, 48), new THREE.MeshStandardMaterial({ color: 0xf2f2f2, roughness: 0.45 }));
    white.position.set(0.36, 0.3, 0);
    // The chrome ball stands for a library finish, so it follows the app's rule:
    // a room of its own in Classic, else the scene at twice its strength.
    chrome.material.envMap = scene.environment || room;
    chrome.material.envMapIntensity = scene.environment
      ? Math.min(2, 2 * (resolved.environmentIntensity || 0)) : 0.7;
    scene.add(floor, chrome, white);
    const camera = new THREE.PerspectiveCamera(32, 240 / 176, 0.05, 50);
    camera.position.set(0, 0.95, 2.1);
    camera.lookAt(0, 0.28, 0);
    renderer.render(scene, camera);
    out[row.sceneId] = renderer.domElement.toDataURL('image/png');
  }
  return out;
}

window.renderThumbnails = async function (only, ids) {
  const library = await lib.createLibraryStore().load();
  return {
    appearances: only === 'scenes' ? {} : await appearances(library, ids),
    scenes: only === 'appearances' ? {} : await scenes(library, ids),
  };
};
window.thumbnailPageReady = true;
</script></body></html>"""


def serve(route):
    path = route.request.url[len(ORIGIN):].split("?", 1)[0]
    if path == "/render.html":
        return route.fulfill(status=200, body=PAGE, content_type="text/html")
    target = (ROOT / path.lstrip("/")).resolve()
    if not path.startswith("/static/") or not target.is_relative_to(STATIC.resolve()) or not target.is_file():
        return route.fulfill(status=404, body="not found")
    content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    if target.suffix == ".hdr":
        content_type = "application/octet-stream"
    return route.fulfill(status=200, body=target.read_bytes(), content_type=content_type)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", choices=["appearances", "scenes"])
    parser.add_argument("--ids", help="comma-separated appearance or scene ids to render (default: all)")
    args = parser.parse_args()
    ids = [item.strip() for item in args.ids.split(",") if item.strip()] if args.ids else None
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        try:
            page = browser.new_page()
            page.route(ORIGIN + "/**", serve)
            page.goto(ORIGIN + "/render.html")
            page.wait_for_function("window.thumbnailPageReady === true", timeout=60000)
            result = page.evaluate("([only, ids]) => window.renderThumbnails(only, ids)", [args.only, ids])
        finally:
            browser.close()
    written = 0
    for kind, rows in result.items():
        folder = OUTPUT / kind
        folder.mkdir(parents=True, exist_ok=True)
        for identifier, data_url in rows.items():
            (folder / f"{identifier}.png").write_bytes(base64.b64decode(data_url.split(",", 1)[1]))
            written += 1
    print(f"wrote {written} thumbnails to {OUTPUT}")


if __name__ == "__main__":
    main()
