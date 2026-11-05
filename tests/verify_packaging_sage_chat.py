"""Opt-in real Sage turn through the main chat pane on a disposable package."""
from pathlib import Path
import argparse
import json
import time

from PIL import Image, ImageStat
from playwright.sync_api import sync_playwright, expect


def verify(url, output, *, live=False, headed=False):
    if not live:
        raise ValueError("Pass --live only after approval for a real Sage turn.")
    output.mkdir(parents=True, exist_ok=True)
    name = f"TEST live Sage packaging {int(time.time())}"
    prompt = ("Pack six copies of this imported part in the carton I have defined. "
              "Keep its dimensions unchanged and keep the saved 2 mm clearance and 1 mm gap. "
              "Apply a feasible arrangement, then validate the saved result. "
              "Keep unknown weights and the handling status unchanged; do not invent values. "
              "Do not add pads. Tell me briefly what still needs my input.")
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed, args=["--enable-unsafe-swiftshader"])
        context = browser.new_context(viewport={"width": 1600, "height": 1000})
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("dialog", lambda dialog: dialog.accept())
        try:
            page.goto(url.rstrip("/") + "/?packagingPilot=1", wait_until="domcontentloaded", timeout=60000)
            page.locator('[data-tab="training"]').click()
            page.locator('#trainingTypeRibbonTrigger').click()
            page.locator('#trainingTypeRibbonOption-packaging_shipping').click()
            frame = page.frame_locator('#packagingWorkspaceFrame')
            expect(frame.locator('#document-name')).to_be_visible(timeout=30000)
            frame.locator('#document-name').fill(name)
            asset = Path(__file__).resolve().parents[1] / 'generated/training/racing-bike/part_glb/RB-001_viewer.glb'
            frame.locator('[name="source_file"]').set_input_files(str(asset))
            frame.get_by_role('button', name='Import GLB', exact=True).click()
            expect(frame.locator('#editor')).to_contain_text('dimensions locked', timeout=35000)
            for key, value in {"quantity": 6, "clearance": 2, "gap": 1}.items():
                frame.locator(f'[name="{key}"]').fill(str(value))
            frame.get_by_role('button', name='Apply product', exact=True).click()
            frame.get_by_role('button', name='Add carton', exact=True).click()
            for axis, value in enumerate((30, 40, 30)):
                frame.locator(f'[name="inner_{axis}"]').fill(str(value))
                frame.locator(f'[name="outer_{axis}"]').fill(str(value + 4))
            frame.get_by_role('button', name='Apply carton', exact=True).click()
            frame.get_by_role('button', name='Save', exact=True).click()
            expect(frame.locator('#document-status')).to_contain_text('Saved')
            documents = page.request.get(url.rstrip('/') + '/api/packaging/documents').json()['documents']
            document_id = next(row['id'] for row in documents if row['name'] == name)
            document_url = url.rstrip('/') + '/api/packaging/documents/' + document_id
            original = page.request.get(document_url).json()['design']
            page.locator('#rightRailAgent').click()
            expect(page.locator('#agentInput')).to_be_visible()
            page.locator('#agentModelBtn').click()
            page.locator('[data-reasoning-level="medium"]').click()
            page.screenshot(path=str(output / 'before-chat.png'))
            print('Sending one real packaging request through the Sage chat pane.', flush=True)
            page.locator('#agentInput').fill(prompt)
            with page.expect_response(lambda response: '/api/agent/chat/v2/stream' in response.url,
                                      timeout=30000) as pending:
                page.locator('#agentSendBtn').click()
            response = pending.value
            if response.status != 200:
                raise AssertionError(f'Chat rejected: HTTP {response.status}: {response.text()}')
            body = response.text()
            events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith('data: ')]
            terminal = events[-1]
            # The terminal response is host-generated; do not log the admission token or raw requests.
            (output / 'terminal.json').write_text(json.dumps(terminal, indent=2), encoding='utf-8')
            if terminal.get('event') != 'response_completed':
                raise AssertionError(f'Sage did not complete: {json.dumps(terminal)}')
            final = terminal['final']
            evidence = final.get('codex_packaging') or {}
            assert evidence.get('mutationOutcome') == 'committed', evidence
            assert evidence.get('checkedPackaging') is True, evidence
            assert evidence.get('authMode') == 'chatgpt_plan' and evidence.get('apiFallback') is False
            assert final.get('memory', {}).get('mode') == 'enforce', final.get('memory')
            saved = page.request.get(document_url).json()['design']
            for key in ('product', 'constraints', 'quantity', 'name'):
                assert saved[key] == original[key], key
            assert saved['packages'][0]['carton'] == original['packages'][0]['carton']
            names = [row['tool'] for row in evidence['verifiedToolCalls'] if row['ok']]
            assert all(name in names for name in ('inspect_packaging', 'propose_packaging', 'edit_packaging', 'validate_packaging'))
            expect(frame.locator('#validation-panel')).to_contain_text('6 / 6 products placed', timeout=30000)
            expect(frame.locator('#validation-panel')).to_contain_text('Unknown')
            expect(frame.locator('#document-name')).to_be_enabled(timeout=10000)
            frame.get_by_role('button', name='Fit view', exact=True).click()
            expect(frame.locator('#scene-message')).to_have_text('', timeout=20000)
            page.screenshot(path=str(output / 'after-chat.png'))
            frame.locator('#viewport canvas').screenshot(path=str(output / 'canvas.png'))
            frame.get_by_role('button', name='Undo', exact=True).click()
            expect(frame.locator('#validation-panel')).to_contain_text('0 / 6 products placed')
            frame.get_by_role('button', name='Redo', exact=True).click()
            expect(frame.locator('#validation-panel')).to_contain_text('6 / 6 products placed')
            page.screenshot(path=str(output / 'after-manual-undo-redo.png'))
            deviations = ImageStat.Stat(Image.open(output / 'canvas.png').convert('RGB')).stddev
            assert max(deviations) > 8, deviations
            result = {'document_name': name, 'tool_names': names, 'auth_mode': evidence['authMode'],
                      'api_fallback': False, 'source_model': asset.name, 'physical_dimensions_verified': False,
                      'page_errors': errors, 'canvas_stddev': deviations, 'manual_undo_redo': True,
                      'response': final['response']}
            (output / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(json.dumps(result, indent=2), flush=True)
            assert not errors, errors
        except BaseException:
            page.screenshot(path=str(output / 'failure.png'))
            (output / 'failure-page.txt').write_text(page.locator('body').inner_text(), encoding='utf-8')
            if page.locator('#packagingWorkspaceFrame').count():
                (output / 'failure-editor.txt').write_text(
                    page.frame_locator('#packagingWorkspaceFrame').locator('body').inner_text(), encoding='utf-8')
            raise
        finally:
            context.close()
            browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8180')
    parser.add_argument('--output', type=Path, default=Path('.runtime/packaging-sage-browser'))
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--headed', action='store_true')
    args = parser.parse_args()
    verify(args.url, args.output, live=args.live, headed=args.headed)
