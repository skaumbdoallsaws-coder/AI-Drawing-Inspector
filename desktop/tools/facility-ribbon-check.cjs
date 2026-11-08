'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

// Only called by the disposable native profile, never the user's running app.
module.exports = async function checkFacilityRibbon({ window, output }) {
  const report = { checks: [], sizes: [], captures: [] };
  const js = async code => {
    const answer = await window.webContents.executeJavaScript(`(async()=>{try{return{ok:true,value:await (${code})};}catch(e){return{ok:false,error:e.message};}})()`, true);
    if (!answer.ok) throw Error(answer.error + '\nExpression: ' + code);
    return answer.value;
  };
  const pause = (ms = 400) => new Promise(resolve => setTimeout(resolve, ms));
  const until = async (code, label, timeout = 90000) => {
    const end = Date.now() + timeout;
    while (Date.now() < end) { if (await js(code)) return; await pause(150); }
    throw Error(label);
  };
  const click = async selector => {
    await js(`(()=>{const b=document.querySelector(${JSON.stringify(selector)});if(!b||b.disabled||!b.checkVisibility())throw Error('Unavailable: '+${JSON.stringify(selector)});b.click();})()`);
    await pause();
  };
  const persist = () => fs.writeFile(path.join(output, 'facility-ribbon.json'), JSON.stringify(report, null, 2));
  async function shot(name, crop = false) {
    await pause();
    const region = crop ? await js(`(()=>{const r=document.querySelector('.facility-layout-ribbon').getBoundingClientRect(),z=${window.webContents.getZoomFactor()};return{x:Math.floor(r.x*z),y:Math.floor(r.y*z),width:Math.ceil(r.width*z),height:Math.ceil(r.height*z)};})()`) : undefined;
    const image = await window.webContents.capturePage(region);
    await fs.writeFile(path.join(output, name + '.png'), image.toPNG());
    report.captures.push(name + '.png'); await persist();
  }
  const originalZoom = window.webContents.getZoomFactor();
  const originalBounds = window.getBounds();
  const originalTheme = await js('document.documentElement.dataset.theme');
  const app = '_trainFacilityLayoutAuthoringApp';
  try {
    window.webContents.setZoomFactor(1);
    await click('#trainingTypeRibbonTrigger');
    await click('#trainingTypeRibbonOption-facility_layout');
    await until(`!!window.${app}?.session?.getState().loaded`, 'Facility did not mount');
    if (await js(`document.querySelector('[data-panel="explorer"]')?.classList.contains('active')`)) await click('[data-panel="explorer"]');
    await js(`${app}.session.createZones([
      {label:'TEST Receiving',zoneType:'storage',minX:2,minZ:2,width:8,depth:8},
      {label:'TEST Assembly',zoneType:'workcell',minX:12,minZ:2,width:12,depth:8},
      {label:'TEST Shipping',zoneType:'storage',minX:26,minZ:2,width:8,depth:8}
    ])`);
    await js(`${app}.session.save()`);
    const before = await js(`${app}.session.getState().layout`);
    report.initial = { layout: before.layoutId, zones: before.zones.length, placements: before.placements.length };
    await js(`(()=>{const s=${app}.session,state=s.getState(),ids=state.layout.placements.slice(0,3).map(p=>p.placementId);if(ids.length)s.selectMany(ids);else if(state.layout.zones.length)s.select(state.layout.zones[0].zoneId);})()`);
    report.assets = await js(`(async()=>{
      const urls=[...new Set([...document.querySelectorAll('.facility-dimensional-icon img')].map(i=>i.src))],results=[];
      for(const url of urls){const im=new Image();im.src=url;await im.decode();const c=document.createElement('canvas');c.width=128;c.height=128;const x=c.getContext('2d');x.drawImage(im,0,0,128,128);const p=x.getImageData(0,0,128,128).data;let clear=0,solid=0;for(let i=3;i<p.length;i+=4){if(!p[i])clear++;if(p[i]>240)solid++;}results.push({url,clear,solid});}return results;
    })()`);
    for (const asset of report.assets) assert.ok(asset.clear > 500 && asset.solid > 40, 'Missing alpha or artwork: ' + asset.url);
    report.checks.push('all referenced primary and small artwork decodes with transparent and solid pixels');
    await persist();

    window.unmaximize();
    for (const [width, zoom, theme] of [[1680,1,'dark'],[1680,1,'light'],[1500,1,'dark'],[1453,1,'dark'],[1440,1,'dark'],[1280,1,'dark'],[1213,1,'dark'],[1100,1,'dark'],[1013,1,'dark'],[950,1.25,'dark'],[900,2,'dark']]) {
      window.setSize(width, 850); window.webContents.setZoomFactor(zoom);
      await js(`document.documentElement.dataset.theme=${JSON.stringify(theme)}`); await pause(800);
      const sizing = await js(`(()=>{
        const ribbon=document.querySelector('.facility-layout-ribbon'),bar=ribbon.querySelector('.facility-ribbon-shell'),r=bar.getBoundingClientRect(),visible=[...bar.querySelectorAll('.documentation-ribbon-command')].filter(b=>b.checkVisibility());
        const clipped=visible.filter(b=>{const p=b.getBoundingClientRect();return p.right>r.right+1||p.bottom>r.bottom+1||p.left<r.left-1||p.top<r.top-1;}).map(b=>b.title);
        const labels=visible.filter(b=>!b.classList.contains('facility-icon-only')).map(b=>{const l=b.querySelector('.documentation-command-label'),p=l.getBoundingClientRect(),q=b.getBoundingClientRect();return{title:b.title,width:p.width,height:p.height,scroll:l.scrollWidth,client:l.clientWidth,outside:p.right>q.right+1||p.bottom>q.bottom+1};});
        return{width:r.width,height:ribbon.getBoundingClientRect().height,clipped,labels,groups:[...bar.querySelectorAll('[data-facility-ribbon-group]')].filter(g=>g.checkVisibility()).map(g=>g.dataset.facilityRibbonGroup)};
      })()`);
      report.sizes.push({ requestedWidth: width, zoom, theme, ...sizing }); await persist();
      await shot(`facility-${width}-${zoom}-${theme}`, true);
      assert.deepEqual(sizing.clipped, [], 'Ribbon commands clipped at ' + sizing.width);
      assert.equal(sizing.height, 58, 'Ribbon height changed');
      assert.deepEqual(sizing.labels.filter(l=>l.outside || l.scroll > l.client + 1), [], 'Label clipped');
      const access = await js(`(()=>{
        const root=document.querySelector('.facility-ribbon-commandbar'),menus=[...root.querySelectorAll('.documentation-ribbon-menu')];
        // Open only menus whose triggers are visible, including disabled menu triggers:
        // this measures option reachability independent of whether today's selection enables them.
        for(const m of menus){const b=m.parentElement.querySelector('.documentation-ribbon-menu-trigger');m.style.display=b?.checkVisibility()?'block':'none';}
        const reachable=[...new Set([...root.querySelectorAll('[data-facility-ribbon-command]')].filter(b=>b.checkVisibility()).map(b=>b.dataset.facilityRibbonCommand))];
        for(const m of menus)m.style.display='none';
        const states=${app}.workspace.getCommandStates();
        const errors=[...root.querySelectorAll('[data-facility-ribbon-command]')].filter(b=>{const s=states[b.dataset.facilityRibbonCommand];return b.disabled!==(!s||Boolean(s.disabled))||!b.title||!b.getAttribute('aria-label');}).map(b=>b.dataset.facilityRibbonCommand);
        return{reachable,missing:Object.keys(FACILITY_LAYOUT_RIBBON_COMMANDS).filter(c=>!['select','pan'].includes(c)&&!reachable.includes(c)),errors};
      })()`);
      assert.deepEqual(access.missing, [], 'Inaccessible command at ' + sizing.width);
      assert.deepEqual(access.errors, [], 'Command state/title differs from workspace');
    }
    report.checks.push('all 42 ribbon commands reachable at tested widths; labels fit; height stays 58px; state and accessible titles match the workspace');
    window.webContents.setZoomFactor(1); window.setSize(1680, 900); await pause(700);
    await js(`document.documentElement.dataset.theme='dark'`);
    await shot('facility-overview');
    const menus = await js(`[...document.querySelectorAll('.facility-ribbon-commandbar [data-facility-command-menu]')].map(b=>({commands:b.dataset.facilityCommandMenu,disabled:b.disabled}))`);
    for (const menu of menus.filter(m => !m.disabled)) {
      const sel = '[data-facility-command-menu=' + JSON.stringify(menu.commands) + ']';
      await click(sel);
      assert.equal(await js(`document.querySelector(${JSON.stringify(sel)}).getAttribute('aria-expanded')`), 'true');
      await shot('facility-menu-' + menu.commands.split(',')[0]);
      await click(sel);
    }
    await click('#facilityLayoutOverflowMenuRibbon'); await shot('facility-menu-more'); await click('#facilityLayoutOverflowMenuRibbon');
    const zoneMenu = '[data-facility-command-menu="rectangle-zone,polygon-zone,bulk-zones"]';
    await click(zoneMenu);
    await click('.facility-ribbon-commandbar .documentation-ribbon-menu [data-facility-ribbon-command="rectangle-zone"]');
    await until(`${app}.workspace.getCommandStates()['rectangle-zone'].active`, 'Zone tool did not activate');
    assert.equal(await js(`document.querySelector('.facility-ribbon-commandbar [data-facility-ribbon-command="rectangle-zone"]').getAttribute('aria-pressed')`), 'true');
    await js(`${app}.workspace.executeCommand('select')`);
    await click('.facility-ribbon-icon-grid [data-facility-ribbon-command="fit"]');
    assert.deepEqual(await js(`${app}.session.getState().layout`), before, 'Presentation exercise changed geometry');
    report.checks.push('real menu clicks open/close; rectangle-zone enters the actual tool; Fit executes; geometry unchanged');
    report.status = 'passed';
    await persist();
  } catch (error) {
    report.status = 'failed'; report.error = error.stack; await persist(); await shot('facility-failure').catch(()=>{}); throw error;
  } finally {
    window.webContents.setZoomFactor(originalZoom); window.setBounds(originalBounds);
    await js(`document.documentElement.dataset.theme=${JSON.stringify(originalTheme || 'dark')}`).catch(()=>{});
  }
  return report;
};
