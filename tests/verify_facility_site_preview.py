"""Real gateway/geometry -> bridged proposal transport -> browser, no model call."""
import asyncio
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from playwright.sync_api import sync_playwright
from verify_facility_site_browser import ROOT, OUT, APP, SITE, open_layout, idle

def main():
    assert ROOT.name=='InspectorPro-CopilotTest'
    os.environ['PYTHON_DOTENV_DISABLED']='1'
    sys.path.insert(0,str(ROOT/'venv/Lib/site-packages'))
    sys.path.insert(0,str(ROOT/'app'))
    from ai_inspector.facility_layout.host import LocalFacilityLayoutHost
    from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway
    identity='fl-site-preview-'+str(int(time.time()))
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1600,'height':950})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        open_layout(page,'fl-site-acceptance-1792661687')
        page.evaluate("""async id=>{const a=window._trainFacilityLayoutAuthoringApp;
            const doc=JSON.parse(JSON.stringify(a.workspace.state.layout));
            doc.layoutId=id;doc.displayName='Site proposal review check';doc.status='draft';
            return a.transport.createLayout(doc);}""",identity)
        open_layout(page,identity)
        saved=page.evaluate(APP+'.session.getState()')
        site_id=saved['layout']['association']['siteId']
        reference={'siteId':site_id,'layoutId':identity,'revision':saved['baseRevision']}
        host=LocalFacilityLayoutHost(ROOT/'ui-data/facility-layout',private_assets=True,private_asset_root=ROOT/'app')
        try:
            gateway=FacilityEditGateway(host.agent_runtime,host.principal(),reference,turn_id='site-browser-check')
            area=next(a for a in saved['layout']['extensions']['facilitySiteContext']['areas'] if a['kind']=='parking')
            area=json.loads(json.dumps(area));area['label']='Parking review'
            for vertex in area['boundary']:vertex['x']+=40
            with ThreadPoolExecutor(max_workers=1) as executor:
                result=executor.submit(lambda:asyncio.run(gateway.call('preview_facility_operations',
                    {'operations':[{'op':'upsert_site_area','area':area}]}))).result(timeout=120)
            assert result['ok'],result
            assert result['data']['approvalRequired'] and not result['data']['saved']
            proposal_id=result['data']['proposalId']
            # Pending proposals are process-local. Bridge only this test proposal's
            # GET/DELETE to its owning host; geometry and validation stay real.
            def proposal_transport(route):
                if route.request.method=='GET':
                    payload=host.service.get_layout_proposal_preview(host.principal(),site_id,identity,proposal_id)
                elif route.request.method=='DELETE':
                    payload=host.service.cancel_layout_proposal(host.principal(),site_id,identity,proposal_id,'site-browser-check')
                else:
                    route.abort();return
                route.fulfill(status=200,content_type='application/json',body=json.dumps(payload))
            page.route('**/api/facility-layouts/'+site_id+'/'+identity+'/proposals/'+proposal_id+'**',proposal_transport)
            page.evaluate('reference=>'+APP+'.session.fetchAndInstallOperationProposal(reference)',
                {**reference,'proposalId':result['data']['proposalId']})
            idle(page)
            page.wait_for_selector('.ip-flw-site-title:text-is("Site proposal")')
            page.wait_for_selector('[data-site-finding="site_area_outside_property"]')
            assert page.get_by_role('button',name='Draw area',exact=True).count()==0
            assert page.evaluate(APP+'.session.getState().dirty') is False
            assert page.evaluate(SITE)==saved['layout']['extensions']['facilitySiteContext']
            assert 'Parking review' in page.locator('.ip-flw-site-canvas').text_content()
            assert 'site finding' in page.evaluate(APP+'.workspace.proposalCheckText.textContent')
            assert page.evaluate(APP+'.workspace.proposalCheckText.getAttribute("data-check-status")')=='warning'
            assert '1 site edit' in page.evaluate(APP+'.workspace.proposalChangeText.textContent')
            page.screenshot(path=str(OUT/'sc4-site-proposal.png'))
            page.evaluate(APP+'.session.dismissLayoutProposal()');idle(page)
            assert page.get_by_role('button',name='Areas',exact=True).is_visible()
            assert 'Parking review' not in page.locator('.ip-flw-site-canvas').text_content()
            current=host.service.get_layout(host.principal(),site_id,identity)
            assert current['revision']==reference['revision']
            assert current['layout']['extensions']['facilitySiteContext']==saved['layout']['extensions']['facilitySiteContext']
            print(json.dumps({'layoutId':identity,'realGatewayProposal':True,'proposalTransport':'test-host bridge','candidateFindingVisible':True,
                'siteReadOnly':True,'dismissRestoresSaved':True,'savedRevisionUnchanged':True,'pageErrors':errors}),flush=True)
            assert not errors,errors
        finally:
            host.close();browser.close()

if __name__=='__main__':main()
