"""Offline release GLB/STEP upload, mesh, report and desktop/mobile rendering check."""
import argparse
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


def verify(dependencies, geometry_python, output):
    output = output.resolve()
    if not output.is_relative_to(ROOT / '.runtime'):
        raise ValueError('Evidence must stay in this integration worktree')
    output.mkdir(parents=True, exist_ok=False)
    dependencies = dependencies.resolve()
    sys.path.insert(0, str(dependencies))
    sys.path.insert(0, str(ROOT))
    import trimesh
    import numpy
    import PIL
    import reportlab
    import py3dbp
    from PIL import Image, ImageChops, ImageStat
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from playwright.sync_api import sync_playwright, expect
    import uvicorn
    from ai_inspector.facility_layout.authorization import FacilityPrincipal
    from ai_inspector.packaging_shipping.api import create_router
    from ai_inspector.packaging_shipping.service import PackagingService
    from ai_inspector.packaging_shipping.sources import GlbRuntime
    from ai_inspector.packaging_shipping.step_import import StepRuntime, _environment
    from ai_inspector.packaging_shipping.rating import EasyPostRating

    for module in (trimesh, numpy, PIL, reportlab, py3dbp):
        assert Path(module.__file__).resolve().is_relative_to(dependencies), module.__name__
    glb = output / 'release-ring.glb'
    glb.write_bytes(trimesh.creation.annulus(r_min=.012, r_max=.03, height=.04).export(file_type='glb'))
    step = output / 'release-bored-block.step'
    runtime = StepRuntime(geometry_python, output / 'state' / 'step-jobs')
    generator = """import sys,sysconfig
from pathlib import Path
prefix = Path(sys.executable).parent.parent
sys.path.append(sysconfig.get_path('purelib', vars={'base':str(prefix),'platbase':str(prefix)}))
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.gp import gp_Ax2, gp_Pnt, gp_Dir
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
from OCP.IFSelect import IFSelect_RetDone
writer=STEPControl_Writer()
block=BRepPrimAPI_MakeBox(120,60,40).Shape()
bore=BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(60,0,20),gp_Dir(0,1,0)),12,60).Shape()
assert writer.Transfer(BRepAlgoAPI_Cut(block,bore).Shape(),STEPControl_AsIs)==IFSelect_RetDone
assert writer.Write(sys.argv[1])==IFSelect_RetDone
"""
    subprocess.run([str(geometry_python), '-I', '-S', '-B', '-c', generator, str(step)],
                   env=_environment(runtime, output), cwd=output, capture_output=True, check=True, timeout=60,
                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    service = PackagingService(output / 'state')
    principal = FacilityPrincipal('release-check', 'local', ('site-local',), ('editor',))
    app = FastAPI()
    app.include_router(create_router(service, principal_resolver=lambda _: principal,
                       static_root=ROOT / 'static', rating=EasyPostRating(key=''),
                       source_runtime=GlbRuntime(dependencies), step_runtime=runtime))
    app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    url = 'http://127.0.0.1:' + str(listener.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level='error'))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    records, errors, external = [], [], []
    try:
        deadline = time.monotonic() + 15
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.05)
        assert server.started
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=['--enable-unsafe-swiftshader'])
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})

            def route(request):
                if not request.request.url.startswith(url + '/'):
                    external.append(request.request.url)
                    request.abort()
                else:
                    request.continue_()

            context.route('**/*', route)
            page = context.new_page()
            page.set_default_timeout(60000)
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('dialog', lambda dialog: dialog.accept())
            for kind, source in [('glb', glb), ('step', step)]:
                page.goto(url + '/packaging', wait_until='networkidle')
                page.locator('#command-product').click()
                page.locator('[name="source_file"]').set_input_files(source)
                endpoint = '/api/packaging/sources' + ('/step' if kind == 'step' else '')
                with page.expect_response(lambda response: response.request.method == 'POST' and endpoint + '?' in response.url) as response:
                    page.get_by_role('button', name='Import ' + kind.upper(), exact=True).click()
                uploaded = response.value
                assert uploaded.status == 200, uploaded.text()
                expect(page.locator('#scene-caption')).to_contain_text('imported geometry')
                expect(page.locator('#scene-message')).to_have_text('')
                stored = page.request.get(url + '/api/packaging/sources')
                assert stored.status == 200
                metadata = next(item for item in stored.json()['sources'] if item['name'] == source.name)
                print(kind + ' upload and persisted source: passed', flush=True)
                page.locator('#close-panel').click()
                page.get_by_role('button', name='Fit view', exact=True).click()
                page.wait_for_timeout(500)
                canvas = output / (kind + '-canvas.png')
                page.locator('#viewport canvas').screenshot(path=str(canvas))
                deviations = ImageStat.Stat(Image.open(canvas).convert('RGB')).stddev
                assert max(deviations) > 8, deviations
                page.screenshot(path=str(output / (kind + '-desktop.png')))
                page.get_by_role('button', name='Top', exact=True).click()
                page.wait_for_timeout(200)
                top = output / (kind + '-top.png')
                page.locator('#viewport canvas').screenshot(path=str(top))
                difference = ImageChops.difference(Image.open(canvas).convert('RGB'), Image.open(top).convert('RGB'))
                assert max(ImageStat.Stat(difference).mean) > .1
                page.set_viewport_size({'width': 390, 'height': 844})
                page.get_by_role('button', name='Fit view', exact=True).click()
                page.screenshot(path=str(output / (kind + '-mobile.png')))
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                page.set_viewport_size({'width': 1440, 'height': 1000})
                normalized = page.request.get(url + '/api/packaging/sources/' + metadata['id'] + '.glb')
                assert normalized.status == 200
                target = output / (kind + '-normalized.glb')
                target.write_bytes(normalized.body())
                scene = trimesh.load_scene(target, process=False)
                expected = [.12, .06, .04] if kind == 'step' else [.06, .06, .04]
                assert numpy.allclose(scene.extents, expected, atol=1e-6)
                assert len(scene.geometry) > 0
                if kind == 'step':
                    assert metadata['solid_count'] == 1
                    assert abs(metadata['volume_m3'] - (.12 * .06 * .04 - math.pi * .012**2 * .06)) < 1e-10
                name = 'Release ' + kind.upper()
                page.locator('#document-name').fill(name)
                page.get_by_role('button', name='Save', exact=True).click()
                expect(page.locator('#document-status')).to_contain_text('Saved')
                documents = page.request.get(url + '/api/packaging/documents').json()['documents']
                document = next(item for item in documents if item['name'] == name)
                report = page.request.get(url + '/api/packaging/documents/' + document['id'] + '/report.pdf',
                                          params={'revision': document['revision']})
                assert report.status == 200 and report.body().startswith(b'%PDF')
                (output / (kind + '-review.pdf')).write_bytes(report.body())
                records.append({'kind': kind, 'dimensions_m': metadata['dimensions_m'],
                                'canvas_stddev': deviations, 'mesh_count': len(scene.geometry)})
                print(kind + ' desktop/mobile render, mesh and report: passed', flush=True)
            assert not errors, errors
            assert not external, external
            context.close()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        listener.close()
        assert not thread.is_alive(), 'Local acceptance server did not stop'
    result = {'imports': records, 'page_errors': errors, 'external_requests': external,
              'released_app_dependencies': True, 'separate_step_runtime': True}
    (output / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dependency-root', type=Path, required=True)
    parser.add_argument('--geometry-python', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    verify(args.dependency_root, args.geometry_python, args.output)
