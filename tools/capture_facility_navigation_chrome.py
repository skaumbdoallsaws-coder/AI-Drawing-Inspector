"""Exercise workflow switching and the Facility Asset Library through the UI."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default=(
        'http://127.0.0.1:8167/?facilityLayoutId=fl-reference-manual-20260812'
        '&build=facility-assets-rail'
    ))
    parser.add_argument('--output', type=Path,
                        default=Path('.runtime/facility-navigation-chrome'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    errors = {'page': [], 'console': [], 'http5xx': []}
    report = {'url': args.url, 'checks': [], 'errors': errors}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1920, 'height': 1080})
        page.set_default_timeout(60_000)
        page.on('pageerror', lambda error: errors['page'].append(str(error)))
        page.on('console', lambda message: errors['console'].append(message.text)
                if message.type == 'error' else None)
        page.on('response', lambda response: errors['http5xx'].append(response.url)
                if response.status >= 500 else None)
        page.goto(args.url, wait_until='load', timeout=120_000)
        page.wait_for_function('window.__inspectorProMainScriptReady === true')
        saved_url = urljoin(args.url,
                           '/api/facility-layouts/site-local/fl-reference-manual-20260812')
        before = page.request.get(saved_url).body()

        def workflow(kind: str) -> None:
            page.locator('#trainingTypeRibbonTrigger').click()
            page.locator(f'#trainingTypeRibbonOption-{kind}').click()
            expect(page.locator('#trainingTypeRibbonTrigger')).to_have_attribute(
                'aria-expanded', 'false'
            )

        def check_facility_chrome() -> None:
            expect(page.locator('#trainShell')).to_have_class(
                re.compile(r'.*\bfacility-layout-focus\b.*')
            )
            expect(page.locator('#trainSetupPanel')).to_be_hidden()
            expect(page.locator('#trainLeftRailSetup')).to_have_count(0)
            expect(page.locator('#trainFacilityLayoutAssets')).to_be_visible()

        page.locator('.tab[data-tab="training"]').click()
        workflow('maintenance')
        page.locator('#trainLeftRailSetup').click()
        expect(page.locator('#trainSetupPanel')).to_be_visible()
        report['checks'].append('Training Setup works in Maintenance Training')

        workflow('facility_layout')
        check_facility_chrome()
        page.wait_for_function("""() => {
            const app = window._trainFacilityLayoutAuthoringApp;
            return app && app.getState().loaded
                && app.session.getState().layout.placements.length === 827;
        }""", timeout=180_000)
        draft_before = page.evaluate(
            'JSON.stringify(_trainFacilityLayoutAuthoringApp.session.getState().layout)'
        )
        page.evaluate('window.__chromeCheckedApp = _trainFacilityLayoutAuthoringApp')
        report['checks'].append('Dropdown transition replaces Training Setup with Asset Library')

        library = page.locator('.ip-flw-asset-browser')
        rail = page.locator('#trainFacilityLayoutAssets')
        rail.click()
        expect(library).to_be_visible()
        expect(rail).to_have_attribute('aria-expanded', 'true')
        expect(library.locator('.ip-flw-asset-card')).to_have_count(148)
        check_facility_chrome()
        for theme in ('light', 'dark'):
            page.evaluate('theme => document.documentElement.setAttribute("data-theme", theme)', theme)
            page.screenshot(path=str(args.output / f'assets-{theme}.png'))
        report['checks'].append('Rail opens all 148 assets with no visible Training PropertyManager')

        rail.click()
        expect(library).to_be_hidden()
        expect(rail).to_have_attribute('aria-expanded', 'false')
        page.evaluate('document.documentElement.setAttribute("data-theme", "light")')
        page.screenshot(path=str(args.output / 'facility-plan.png'))
        report['checks'].append('Second rail click closes the library')

        page.evaluate('window._trainingTogglePanel("setup", true)')
        expect(library).to_be_visible()
        check_facility_chrome()
        page.get_by_role('button', name='Close asset library', exact=True).click()
        expect(library).to_be_hidden()
        expect(rail).to_have_attribute('aria-expanded', 'false')
        assert page.evaluate('window.__chromeCheckedApp === _trainFacilityLayoutAuthoringApp')
        assert page.evaluate(
            'JSON.stringify(_trainFacilityLayoutAuthoringApp.session.getState().layout)'
        ) == draft_before
        report['checks'].append('Setup shortcut and close button preserve the same editor and draft')

        workflow('maintenance')
        expect(page.locator('#trainFacilityLayoutAssets')).to_have_count(0)
        page.locator('#trainLeftRailSetup').click()
        expect(page.locator('#trainSetupPanel')).to_be_visible()
        workflow('facility_layout')
        check_facility_chrome()
        page.wait_for_function('window._trainFacilityLayoutAuthoringApp.getState().loaded')
        rail.click()
        expect(library).to_be_visible()
        expect(library.locator('.ip-flw-asset-card')).to_have_count(148)
        report['checks'].append('Round trip restores the correct rail in each workflow')

        after = page.request.get(saved_url).body()
        assert before == after
        report['savedLayoutUnchanged'] = True
        report['savedReceiptSha256'] = hashlib.sha256(after).hexdigest()
        assert not any(errors.values()), errors
        browser.close()

    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
