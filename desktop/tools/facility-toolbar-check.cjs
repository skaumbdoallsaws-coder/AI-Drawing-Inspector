'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

// Runs after the ribbon check has created a layout in the disposable profile.
module.exports = async function checkFacilityToolbar({ window, output }) {
  const report = { checks: [], sizes: [], captures: [] };
  const app = 'window._trainFacilityLayoutAuthoringApp';
  const workspace = app + '.workspace';
  const toolbar = '.ip-flw-three-navigation';
  const js = async code => {
    const result = await window.webContents.executeJavaScript(`(async()=>{try{return{ok:true,value:await (${code})};}catch(e){return{ok:false,error:e.message};}})()`, true);
    if (!result.ok) throw Error(result.error + '\n' + code);
    return result.value;
  };
  const pause = (ms = 350) => new Promise(resolve => setTimeout(resolve, ms));
  const persist = () => fs.writeFile(path.join(output, 'facility-toolbar.json'), JSON.stringify(report, null, 2));
  const selector = command => `${toolbar} [data-three-command="${command}"]`;
  const click = async sel => {
    await js(`(()=>{const b=document.querySelector(${JSON.stringify(sel)});if(!b||b.disabled||!b.checkVisibility())throw Error('Unavailable '+${JSON.stringify(sel)});b.click();})()`);
    await pause();
  };
  const capture = async (name, crop = false, scope = toolbar) => {
    const region = crop ? await js(`(()=>{const r=document.querySelector(${JSON.stringify(scope)}).getBoundingClientRect(),z=${window.webContents.getZoomFactor()};return{x:Math.floor(r.x*z)-4,y:Math.floor(r.y*z)-4,width:Math.ceil(r.width*z)+8,height:Math.ceil(r.height*z)+8};})()`) : undefined;
    const image = await window.webContents.capturePage(region);
    await fs.writeFile(path.join(output, name + '.png'), image.toPNG());
    report.captures.push(name + '.png');
    return image;
  };
  const before = await js(`${app}.session.getState().layout`);
  const originalBounds = window.getBounds();
  const originalZoom = window.webContents.getZoomFactor();
  const originalTheme = await js('document.documentElement.dataset.theme');
  try {
    window.unmaximize(); window.setSize(1680, 900); window.webContents.setZoomFactor(1);
    await click('#trainFacilityLayoutAuthoring [data-view="3d"]');
    const deadline = Date.now() + 90000;
    while (!(await js(`!!${workspace}.threeAdapter && !!document.querySelector('.ip-flw-three-view canvas')`))) {
      if (Date.now() > deadline) throw Error('3D viewport did not mount');
      await pause(150);
    }
    await pause(1500);
    report.commands = await js(`[...document.querySelectorAll('${toolbar} [data-three-command]')].map(b=>({command:b.dataset.threeCommand,title:b.title,disabled:b.disabled,src:b.querySelector('img')?.getAttribute('src')}))`);
    assert.deepEqual(report.commands.map(b=>b.command), ['fit-layout','zoom-out','zoom-in','pan','view-orientation','display-settings','appearance','layers','orbit','walkthrough','avatar-view','drone','switch-immersive','walk-to-selected','camera-settings','viewpoints','record','fit-facility','grid']);
    assert.ok(report.commands.every(b=>b.title));
    assert.equal(new Set(report.commands.filter(b=>b.src).map(b=>b.src)).size, 18);
    report.assets = await js(`(async()=>{
      const urls=[...new Set([...document.querySelectorAll('${toolbar} img')].map(i=>i.src))],items=[];
      for(const url of urls){const im=new Image();im.src=url;await im.decode();const c=document.createElement('canvas');c.width=64;c.height=64;const ctx=c.getContext('2d');ctx.drawImage(im,0,0,64,64);const p=ctx.getImageData(0,0,64,64).data;let clear=0,solid=0;for(let i=3;i<p.length;i+=4){if(!p[i])clear++;if(p[i]>240)solid++;}items.push({url,clear,solid});}return items;
    })()`);
    assert.ok(report.assets.every(a=>a.clear>100 && a.solid>30), 'Artwork missing or not transparent');
    report.checks.push('19 original commands in original order with titles; all 18 image symbols distinct and decoded with transparency');
    for (const [width, zoom, theme] of [[1680,1,'dark'],[1680,1,'light'],[1200,1.25,'dark'],[900,2,'dark']]) {
      window.setSize(width,900); window.webContents.setZoomFactor(zoom);
      await js(`document.documentElement.dataset.theme=${JSON.stringify(theme)}`); await pause(700);
      const sizing = await js(`(()=>{
        const bar=document.querySelector('${toolbar}'),r=bar.closest('.ip-flw-three-view').getBoundingClientRect(),bs=[...bar.querySelectorAll('[data-three-command]')];
        const boxes=bs.map(b=>{const p=b.getBoundingClientRect();return{command:b.dataset.threeCommand,x:p.x,y:p.y,width:p.width,height:p.height,right:p.right,bottom:p.bottom,icon:b.querySelector('img')?.getBoundingClientRect().width};});
        return{width:r.width,clipped:boxes.filter(b=>b.x<r.left-1||b.right>r.right+1||b.bottom>r.bottom+1),overlap:boxes.filter((b,i)=>boxes.some((c,j)=>j>i&&b.x<c.right-1&&b.right>c.x+1&&b.y<c.bottom-1&&b.bottom>c.y+1)),boxes};
      })()`);
      report.sizes.push({ width, zoom, theme, ...sizing }); await persist();
      await capture(`facility-toolbar-${width}-${zoom}-${theme}`,true);
      assert.deepEqual(sizing.clipped,[], 'Toolbar clipped');
      assert.deepEqual(sizing.overlap,[], 'Toolbar buttons overlap');
      assert.ok(sizing.boxes.every(b=>b.height===28 && (!b.icon || b.icon===24)), 'Existing button or icon size changed');
    }
    report.checks.push('24px icons and 28px controls retained; no clipping or overlap at 100%, 125%, and 200% scaling; dark/light screenshots captured');
    window.webContents.setZoomFactor(1); window.setSize(1680,900);
    await js(`document.documentElement.dataset.theme='dark'`); await pause(700);
    await capture('facility-toolbar-overview');
    const canvasRegion = await js(`(()=>{const r=document.querySelector('.ip-flw-three-view canvas').getBoundingClientRect();return{x:Math.round(r.x+60),y:Math.round(r.y+100),width:Math.round(r.width-120),height:Math.round(r.height-160)};})()`);
    const scene = await window.webContents.capturePage(canvasRegion);
    const pixels = scene.toBitmap(), colors = new Set();
    for(let i=0;i<pixels.length;i+=64) colors.add(`${pixels[i]},${pixels[i+1]},${pixels[i+2]}`);
    assert.ok(colors.size>100, '3D canvas is blank');
    await click(selector('view-orientation'));
    assert.deepEqual(await js(`[...document.querySelectorAll('${toolbar} [data-three-view]')].map(b=>b.dataset.threeView)`),['front','top','right','iso']);
    await capture('facility-toolbar-orientation');
    await click(`${toolbar} [data-three-view="top"]`); await pause(700);
    assert.match(await js(`document.querySelector('${selector('view-orientation')} img').src`),/view-top\.png$/);
    const changedScene = await window.webContents.capturePage(canvasRegion);
    assert.notDeepEqual(changedScene.toBitmap(), pixels, 'Orientation did not change the scene');
    await click(selector('view-orientation')); await click(`${toolbar} [data-three-view="iso"]`);
    for (const [command, state] of [['display-settings','threeSettingsOpen'],['layers','layerPanelOpen'],['viewpoints','threeViewpointsOpen']]) {
      await click(selector(command)); assert.equal(await js(`${workspace}.${state}`),true);
      await capture('facility-toolbar-' + command);
      await click(selector(command)); assert.equal(await js(`${workspace}.${state}`),false);
    }
    const initialGrid = await js(`${workspace}.threeGridVisible`);
    await click(selector('grid')); assert.equal(await js(`${workspace}.threeGridVisible`),!initialGrid);
    await click(selector('grid')); assert.equal(await js(`${workspace}.threeGridVisible`),initialGrid);
    await click(selector('pan')); assert.equal(await js(`${workspace}.threeNavigationMode`),'pan');
    await click(selector('orbit')); assert.equal(await js(`${workspace}.threeNavigationMode`),'orbit');
    for (const command of ['zoom-in','zoom-out','fit-layout','fit-facility']) await click(selector(command));
    await click(selector('record')); assert.equal(await js(`${workspace}.recordingState.panelOpen`),true);
    await click(selector('record')); assert.equal(await js(`${workspace}.recordingState.panelOpen`),false);
    assert.deepEqual(await js(`${app}.session.getState().layout`),before,'Visual checks changed layout geometry');
    report.checks.push('nonblank 3D scene changes with orientation; original menus, grid, pan/orbit, zoom, fit and record panel respond; layout geometry unchanged');
    const plan = '.ip-flw-plan-navigation';
    const planSelector = command => `${plan} [data-plan-command="${command}"]`;
    // Keep selection-editing panels out of the viewport-only visual exercise.
    await js(`${app}.session.clearSelection()`);
    await click('#trainFacilityLayoutAuthoring [data-view="plan"]');
    report.planCommands = await js(`[...document.querySelectorAll('${plan} [data-plan-command]')].map(b=>({command:b.dataset.planCommand,title:b.title,label:b.getAttribute('aria-label'),src:b.querySelector('img')?.getAttribute('src')}))`);
    assert.deepEqual(report.planCommands.map(b=>b.command),['select','pan','zoom-out','zoom-in','fit-facility','fit-layout','reset-view','grid','snap','layers','unit']);
    assert.ok(report.planCommands.every(b=>b.title && b.label));
    assert.equal(new Set(report.planCommands.filter(b=>b.src).map(b=>b.src)).size,10);
    report.planAssets = await js(`(async()=>{
      const items=[];
      for(const img of document.querySelectorAll('${plan} img')){
        await img.decode();const c=document.createElement('canvas');c.width=64;c.height=64;const ctx=c.getContext('2d');ctx.drawImage(img,0,0,64,64);const p=ctx.getImageData(0,0,64,64).data;let clear=0,solid=0;for(let i=3;i<p.length;i+=4){if(!p[i])clear++;if(p[i]>240)solid++;}items.push({src:img.getAttribute('src'),clear,solid,filter:getComputedStyle(img).filter});
      }return items;
    })()`);
    assert.ok(report.planAssets.every(a=>a.clear>100 && a.solid>30 && a.filter==='none'));
    report.planSizes = [];
    for (const [width,zoom,theme] of [[1680,1,'dark'],[1680,1,'light'],[1200,1.25,'dark'],[900,2,'dark'],[600,1,'dark']]) {
      window.setSize(width,900);window.webContents.setZoomFactor(zoom);
      await js(`document.documentElement.dataset.theme=${JSON.stringify(theme)}`);await pause(650);
      const sizing=await js(`(()=>{
        const bar=document.querySelector('${plan}'),r=bar.closest('.ip-flw-plan-view').getBoundingClientRect(),ruler=document.querySelector('.ip-flw-plan-ruler-top')?.getBoundingClientRect();
        const boxes=[...bar.querySelectorAll('[data-plan-command]')].map(b=>{const p=b.getBoundingClientRect();return{command:b.dataset.planCommand,x:p.x,y:p.y,width:p.width,height:p.height,right:p.right,bottom:p.bottom,icon:b.querySelector('img')?.getBoundingClientRect().width};});
        const unit=bar.querySelector('[data-plan-command="unit"]');
        const covered=[...bar.querySelectorAll('[data-plan-command]')].filter(b=>{const p=b.getBoundingClientRect(),hit=document.elementFromPoint(p.x+p.width/2,p.y+p.height/2);return hit!==b&&!b.contains(hit);}).map(b=>b.dataset.planCommand);
        return{width:r.width,clipped:boxes.filter(b=>b.x<r.left-1||b.right>r.right+1||b.y<r.top-1||b.bottom>r.bottom+1||(ruler&&b.y<ruler.bottom-1)),overlap:boxes.filter((b,i)=>boxes.some((c,j)=>j>i&&b.x<c.right-1&&b.right>c.x+1&&b.y<c.bottom-1&&b.bottom>c.y+1)),covered,unitFits:unit.scrollWidth<=unit.clientWidth,boxes};
      })()`);
      report.planSizes.push({width,zoom,theme,...sizing});await persist();
      await capture(`facility-plan-toolbar-${width}-${zoom}-${theme}`,true,plan);
      assert.deepEqual(sizing.clipped,[],'Plan toolbar clipping');assert.deepEqual(sizing.overlap,[],'Plan toolbar overlap');
      assert.deepEqual(sizing.covered,[],'Plan viewport controls are obscured');
      assert.ok(sizing.unitFits && sizing.boxes.every(b=>b.width===28 && b.height===28 && (!b.icon||b.icon===24)));
    }
    window.setSize(1680,900);window.webContents.setZoomFactor(1);
    await js(`document.documentElement.dataset.theme='dark'`);await pause(650);
    await click(planSelector('select'));assert.equal(await js(`${workspace}.toolMode`),'select');
    await capture('facility-plan-toolbar-overview');
    await click(planSelector('pan'));assert.equal(await js(`${workspace}.toolMode`),'pan');
    await click(planSelector('select'));
    const viewBefore=await js(`${workspace}.topAdapter.getViewportState()`);
    await click(planSelector('zoom-in'));
    assert.notDeepEqual(await js(`${workspace}.topAdapter.getViewportState()`),viewBefore);
    await click(planSelector('zoom-out'));
    for(const command of ['fit-facility','fit-layout','reset-view']) await click(planSelector(command));
    for(const [command,setting] of [['grid','showGrid'],['snap','snapToGrid']]) {
      const initial=await js(`${workspace}.planPreferences.${setting}`);
      await click(planSelector(command));assert.equal(await js(`${workspace}.planPreferences.${setting}`),!initial);
      assert.equal(await js(`document.querySelector('${planSelector(command)}').getAttribute('aria-pressed')`),String(!initial));
      await click(planSelector(command));assert.equal(await js(`${workspace}.planPreferences.${setting}`),initial);
    }
    const unitBefore=await js(`${workspace}.planPreferences.unit`);
    await click(planSelector('unit'));assert.notEqual(await js(`${workspace}.planPreferences.unit`),unitBefore);
    assert.equal(await js(`document.querySelector('${planSelector('unit')}').textContent`),await js(`${workspace}.planPreferences.unit`));
    await capture('facility-plan-toolbar-alternate-unit',true,plan);
    await click(planSelector('unit'));assert.equal(await js(`${workspace}.planPreferences.unit`),unitBefore);
    await click(planSelector('layers'));assert.equal(await js(`${workspace}.layerPanelOpen`),true);
    await capture('facility-plan-toolbar-layers');await click(planSelector('layers'));
    assert.equal(await js(`${workspace}.layerPanelOpen`),false);
    assert.deepEqual(await js(`${app}.session.getState().layout`),before,'Plan toolbar changed geometry');
    report.checks.push('Plan: all 11 commands retained; shared 24px artwork with no glow; dark/light and 100/125/200% sizing; native select, pan, zoom, fit, grid, snap, units and layers work without geometry changes');
    report.status='passed'; await persist();
  } catch(error) {
    report.status='failed';report.error=error.stack;await persist();await capture('facility-toolbar-failure').catch(()=>{});throw error;
  } finally {
    window.webContents.setZoomFactor(originalZoom);window.setBounds(originalBounds);
    await js(`document.documentElement.dataset.theme=${JSON.stringify(originalTheme||'dark')}`).catch(()=>{});
  }
  return report;
};
