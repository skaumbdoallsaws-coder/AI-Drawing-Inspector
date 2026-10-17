"""Use the pinned thumbnail scene with direct, bounded loopback GLB transfers."""
import json
import math
from pathlib import Path
import shutil
import struct
import tempfile
import threading
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

from PIL import Image
from playwright.sync_api import sync_playwright
import render_industrial_asset_thumbnail as base


def render_streamed_asset_thumbnail(input_path, output_path, *, evidence_path=None,
        width=480, height=300, background='#eef3f7', source_transform=None,
        maximum_input_bytes=512*1024*1024, maximum_output_bytes=8*1024*1024,
        timeout_ms=180000, **options):
    source = base.validate_glb_container(input_path, maximum_input_bytes=maximum_input_bytes)
    model = source['path']
    assert output_path.resolve() != model
    assert base.MIN_DIMENSION <= width <= base.MAX_DIMENSION and base.MIN_DIMENSION <= height <= base.MAX_DIMENSION
    with model.open('rb') as stream:
        stream.seek(12)
        length, kind = struct.unpack('<II', stream.read(8))
        assert kind == 0x4E4F534A
        document = json.loads(stream.read(length))
    assert not document.get('extensionsRequired'), 'Unsupported GLB extensions'
    assert all('uri' not in value for key in ('buffers', 'images') for value in document.get(key, [])), 'GLB must be self-contained'
    transform = base._normalize_source_transform(source_transform)
    rgb = base._parse_hex_color(background)
    config = dict(background=background, cameraDirection=base._normalize_direction((1, .72, 1)),
                  fovDegrees=35, height=height, width=width, sourceTransform=transform)
    handler_base = base._make_handler(renderer_page=base._renderer_html(config))

    class Handler(handler_base):
        def end_headers(self):
            self.send_header('Content-Security-Policy', "default-src 'self' data:; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data: blob:")
            super().end_headers()

        def do_GET(self):
            request_path = urlsplit(self.path).path
            if request_path == base.INPUT_ENDPOINT:
                self.send_response(200)
                self.send_header('Content-Type', 'model/gltf-binary')
                self.send_header('Content-Length', str(model.stat().st_size))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                if self.command != 'HEAD':
                    with model.open('rb') as stream:
                        shutil.copyfileobj(stream, self.wfile, 1024*1024)
                return
            if request_path not in {base.PAGE_ENDPOINT, '/favicon.ico'} and not request_path.startswith('/static/vendor/three/0.184.0/'):
                self.send_error(404)
                return
            super().do_GET()

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    errors, finished, external = [], [], []
    try:
        with tempfile.TemporaryDirectory(prefix='ip-gym-preview-') as temporary, sync_playwright() as p:
            browser = p.chromium.launch(executable_path=str(base._find_browser_executable(p, None)), headless=True)
            try:
                context = browser.new_context(viewport={'width': width, 'height': height}, device_scale_factor=1)
                # Avoid copying large GLBs through the DevTools interception API.
                context.on('request', lambda r: external.append(r.url) if not r.url.startswith(origin + '/') else None)
                page = context.new_page()
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.on('requestfailed', lambda r: errors.append(dict(url=r.url, failure=r.failure)))
                page.on('response', lambda r: errors.append(f'HTTP {r.status} {r.url}') if r.status >= 400 else None)
                page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
                page.on('requestfinished', lambda r: finished.append(r.url))
                page.goto(origin + base.PAGE_ENDPOINT, wait_until='load', timeout=timeout_ms)
                page.wait_for_function("() => ['complete','error'].includes(window.__industrialThumbnailResult?.state)", timeout=timeout_ms)
                result = page.evaluate('() => window.__industrialThumbnailResult')
                assert result['state'] == 'complete', result
                page.wait_for_load_state('networkidle')
                png = Path(temporary) / 'render.png'
                page.locator('#viewport').screenshot(path=str(png), animations='disabled')
                assert not errors and not external, (errors, external)
                assert origin + base.INPUT_ENDPOINT in finished
                assert result['threeRevision'] == '184' and result['canvas'] == {'width': width, 'height': height}
                assert result['triangleCount'] > 0 and result['meshCount'] > 0
                assert all(math.isfinite(v) for key in ('min', 'max', 'size') for v in result['bounds'][key])
                with Image.open(png) as image:
                    pixels = base._image_metrics(image, background_rgb=rgb)
                assert pixels['nonblank'], pixels
                output = base._publish_image(png, output_path, maximum_output_bytes=maximum_output_bytes)
                evidence = dict(schemaVersion='industrial-asset-thumbnail-evidence-v1', passed=True,
                    checks=dict(validGlb2=True, actualBoundsFinite=True, boundedDimensions=True,
                        boundedOutputBytes=True, geometryRenderable=True, inputTransferFinished=True,
                        localAssetsOnly=True, nonblankPixels=True, pinnedThreeRevision=True),
                    source=dict(artifactName=model.name, byteLength=source['byteLength'], containerVersion=2, sha256=base.sha256_file(model)),
                    output=dict(**output, pixelValidation=pixels),
                    geometry={k: result[k] for k in ('bounds', 'meshCount', 'primitiveCount', 'triangleCount')},
                    network=dict(externalRequestCount=0, failedRequestCount=0, failedResponseCount=0, offlineOnly=True),
                    renderer=dict(browser=browser.version, transport='loopback_stream', threeRevision='184',
                        sourceTransform=transform, camera=result['camera'], renderCalls=result['renderCalls'],
                        renderedTriangles=result['renderedTriangles'], runnerSha256=base.sha256_file(Path(__file__)),
                        threeModuleSha256=base.sha256_file(base.THREE_MODULE), gltfLoaderSha256=base.sha256_file(base.GLTF_LOADER)))
                if evidence_path:
                    base._atomic_write_bytes(evidence_path, base.canonical_json_bytes(evidence))
                return evidence
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
