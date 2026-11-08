'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

// Runs only under the disposable native Packaging acceptance profile.
module.exports = async function checkSidebarIcons({ window, output, ensureBrowser }) {
  const js = async code => {
    const result = await window.webContents.executeJavaScript(`(async()=>{try{return{ok:true,value:await (${code})};}catch(e){return{ok:false,error:e.message};}})()`, true);
    if (!result.ok) throw Error(result.error + '\nExpression: ' + code);
    return result.value;
  };
  const pause = (ms = 350) => new Promise(resolve => setTimeout(resolve, ms));
  const until = async (condition, label) => {
    const deadline = Date.now() + 15000;
    while (Date.now() < deadline) { if (await condition()) return; await pause(100); }
    throw Error(label);
  };
  const controls = [
    { name: 'drawing', selector: '[data-panel="explorer"]', title: 'Drawing', size: 27 },
    { name: 'model', selector: '[data-panel="model"]', title: '3D Model', size: 27 },
    { name: 'structure', selector: '[data-panel="structure"]', title: 'Structure', size: 27 },
    { name: 'appearance', selector: '[data-panel="library"]', title: 'Appearances, Scenes and Decals', size: 27 },
    { name: 'results', selector: '#rightRailResults', title: 'Results', size: 24 },
    { name: 'sage', selector: '#rightRailAgent', title: 'Agent', size: 24 },
    { name: 'browser', selector: '#rightRailBrowser', title: 'Browser', size: 22 },
  ];
  const element = selector => `document.querySelector(${JSON.stringify(selector)})`;
  const click = async selector => { await js(`${element(selector)}.click()`); await pause(); };
  const initial = await js(`({theme:document.documentElement.dataset.theme,tab:document.querySelector('.tab.active')?.dataset.tab})`);
  const initialZoom = window.webContents.getZoomFactor();
  const report = { checks: [], states: [], captures: [] };
  try {
    window.webContents.setZoomFactor(1);
    report.assets = await js(`(async()=>{
      const evidence=[];
      for(const spec of ${JSON.stringify(controls)}) {
        const button=document.querySelector(spec.selector),images=[...button.querySelectorAll('img')];
        await Promise.all(images.map(image=>image.decode()));
        const image=images.find(image=>getComputedStyle(image).display!=='none');
        const rect=()=>{const r=button.getBoundingClientRect();return[r.x,r.y,r.width,r.height]};
        const current=rect();
        // The former glyphs occupied these same SVG/span slots; test layout independently of artwork.
        const legacy=document.createElement('span');legacy.style.cssText='display:block;width:'+spec.size+'px;height:'+spec.size+'px';
        image.replaceWith(legacy);const previous=rect();legacy.replaceWith(image);
        const canvas=document.createElement('canvas');canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;
        const context=canvas.getContext('2d');context.drawImage(image,0,0);
        const pixels=context.getImageData(0,0,canvas.width,canvas.height).data;
        let clear=0,solid=0,minX=canvas.width,minY=canvas.height,maxX=0,maxY=0;
        for(let i=3;i<pixels.length;i+=4){if(pixels[i]===0)clear++;if(pixels[i]>=250)solid++;
          if(pixels[i]>=128){const p=(i-3)/4,x=p%canvas.width,y=Math.floor(p/canvas.width);minX=Math.min(minX,x);minY=Math.min(minY,y);maxX=Math.max(maxX,x);maxY=Math.max(maxY,y);}}
        evidence.push({name:spec.name,current,previous,clear,solid,title:button.title,source:image.getAttribute('src'),
          ink:[minX/canvas.width,minY/canvas.height,maxX/canvas.width,maxY/canvas.height]});
      }
      return evidence;
    })()`);
    for (const asset of report.assets) {
      assert.deepEqual(asset.current, asset.previous, asset.name + ' changed button layout');
      assert.ok(asset.clear > 1000 && asset.solid > 1000, asset.name + ' needs real alpha and solid artwork');
      assert.ok(asset.source.endsWith(asset.name + '-dimensional-v1.png'));
      assert.ok(asset.ink.every(edge => edge > 0 && edge < 1), asset.name + ' touches image boundary');
    }
    report.checks.push('all seven separate transparent assets load; no clipped artwork or button layout changes');

    for (const theme of ['dark', 'light']) {
      await js(`document.documentElement.dataset.theme=${JSON.stringify(theme)}`);
      for (const zoom of [1, 1.25]) {
        window.webContents.setZoomFactor(zoom); await pause();
        for (const spec of controls) {
          const state = await js(`(()=>{const b=${element(spec.selector)},image=[...b.querySelectorAll('img')].find(el=>getComputedStyle(el).display!=='none'),r=image.getBoundingClientRect();return{title:b.title,size:[r.width,r.height],tooltip:b.querySelector('.activity-tooltip,.right-rail-tooltip').textContent};})()`);
          assert.deepEqual(state.size, [spec.size, spec.size], spec.name + ' slot size');
          assert.equal(state.title, spec.title);
          assert.ok(state.tooltip.length);
          const point = await js(`(()=>{const r=${element(spec.selector)}.getBoundingClientRect();return{x:Math.round((r.x+r.width/2)*${zoom}),y:Math.round((r.y+r.height/2)*${zoom})};})()`);
          await until(async()=>{
            window.webContents.sendInputEvent({ type: 'mouseMove', ...point }); await pause(40);
            return js(`${element(spec.selector)}.matches(':hover')`);
          }, spec.name + ' hover at ' + theme + ' ' + zoom);
          report.states.push({theme,zoom,name:spec.name,...state});
        }
        window.webContents.sendInputEvent({ type: 'mouseMove', x: 600, y: 400 }); await pause();
        for (const [side, selector] of [['left','.activity-bar'],['right','.right-activity-rail']]) {
          const region=await js(`(()=>{const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect(),z=${zoom};return{x:Math.floor(r.x*z),y:Math.floor(r.y*z),width:Math.ceil(r.width*z),height:Math.ceil(210*z)};})()`);
          const name=`sidebar-${side}-${theme}-${zoom}.png`;
          await fs.writeFile(path.join(output,name),(await window.webContents.capturePage(region)).toPNG()); report.captures.push(name);
        }
        const name=`sidebars-${theme}-${zoom}.png`;
        await fs.writeFile(path.join(output,name),(await window.webContents.capturePage()).toPNG());report.captures.push(name);
      }
    }
    report.checks.push('light/dark, 100%/125%: existing icon sizes, titles, tooltips and hover targets preserved');
    window.webContents.setZoomFactor(1);
    await js(`document.documentElement.dataset.theme='dark'`);
    for (const selector of ['[data-panel="explorer"]','[data-panel="structure"]','[data-panel="library"]']) {
      await click(selector);
      assert.equal(await js(`${element(selector)}.classList.contains('active')`), true);
      assert.equal(await js(`document.querySelector('.left-panel').checkVisibility()`), true);
      await click(selector);
      assert.equal(await js(`${element(selector)}.classList.contains('active')`), false);
    }
    await click('[data-panel="model"]');
    assert.equal(await js(`document.querySelector('.tab.active').dataset.tab`), '3dmodel');
    await click('.tab[data-tab="training"]');
    for (const [selector,mode] of [['#rightRailResults','results'],['#rightRailAgent','agent']]) {
      await click(selector); assert.equal(await js(`window._getRightDockMode()`),mode);
      await click(selector); assert.equal(await js(`window._getRightDockMode()`),null);
    }
    await click('#rightRailBrowser');
    const browser = await ensureBrowser();
    await until(()=>browser.snapshot().visible,'Browser did not open');
    assert.equal(await js(`document.getElementById('rightRailBrowser').getAttribute('aria-expanded')`),'true');
    await click('#rightRailBrowser');
    await until(()=>!browser.snapshot().visible,'Browser did not close');
    assert.equal(await js(`document.getElementById('rightRailBrowser').getAttribute('aria-expanded')`),'false');
    report.checks.push('Drawing/Structure/Appearances toggle their panels; Model switches workspace; Results/Sage toggle their dock; Browser opens/closes its real pane');
  } finally {
    await js(`document.documentElement.dataset.theme=${JSON.stringify(initial.theme || 'dark')}`);
    window.webContents.setZoomFactor(initialZoom);
  }
  return report;
};
