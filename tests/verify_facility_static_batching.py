"""Actual Three.js geometry and responsive WebGL checks; no backend or provider."""
import json
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlsplit

from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.runtime/walkthrough-performance-20260928/webgl'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {'errors': [], 'viewports': []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        page.on('pageerror', lambda e: report['errors'].append(str(e)))

        def route(request):
            file = (ROOT / unquote(urlsplit(request.request.url).path).lstrip('/')).resolve()
            if not file.is_relative_to(ROOT) or not file.is_file():
                request.fulfill(status=404, body='Missing fixture')
                return
            mime = 'text/javascript' if file.suffix == '.js' else mimetypes.guess_type(file)[0]
            request.fulfill(path=str(file), content_type=mime or 'application/octet-stream')

        page.route('**/*', route)
        try:
            page.goto('http://fixture.test/tests/fixtures/facility_layout/rendering/static-batching.html')
            page.wait_for_function('window.batchReady')
            report['geometry'] = page.evaluate('runBatchTests()')
            for width, height in [(1440, 900), (900, 700), (390, 844)]:
                page.set_viewport_size({'width': width, 'height': height})
                page.evaluate('prepareCapture()')
                first = OUT / f'cad-{width}.png'
                page.screenshot(path=str(first))
                page.evaluate('animateCapture()')
                page.wait_for_timeout(800)
                second = OUT / f'cad-moving-{width}.png'
                page.screenshot(path=str(second))
                with Image.open(first) as a, Image.open(second) as b:
                    colors = len(a.convert('RGB').getcolors(a.width*a.height) or [])
                    assert colors > 100, ('Blank canvas', width, colors)
                    assert ImageChops.difference(a.convert('RGB'), b.convert('RGB')).getbbox(), 'Scene did not move'
                report['viewports'].append({'width':width, 'height':height, 'colors':colors, 'moving':True})
            page.evaluate('disposeCapture()')
            assert not report['errors'], report['errors']
            report['status'] = 'passed'
        except Exception as error:
            report['status'] = 'failed'
            report['failure'] = str(error)
            raise
        finally:
            (OUT/'report.json').write_text(json.dumps(report, indent=2))
            browser.close()
    print(json.dumps(report))


if __name__ == '__main__':
    main()
