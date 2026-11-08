'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

module.exports = async function checkDrawingSidebar({ window, output }) {
  const js = async code => {
    const result = await window.webContents.executeJavaScript(`(async()=>{try{return {ok:true,value:await (${code})};}catch(error){return {ok:false,message:error.message,stack:error.stack};}})()`, true);
    if (!result.ok) throw Error(result.message + '\n' + result.stack + '\nExpression: ' + code);
    return result.value;
  };
  const pause = () => new Promise(resolve => setTimeout(resolve, 350));
  const button = `document.querySelector('.activity-bar-icon[data-panel="explorer"]')`;
  const initialTheme = await js('document.documentElement.dataset.theme');
  const initialZoom = window.webContents.getZoomFactor();
  const report = { captures: [], states: [] };
  try {
    window.webContents.setZoomFactor(1);
    report.geometry = await js(`(async()=>{
      const b=${button}, images=[...b.querySelectorAll('img')];
      await Promise.all(images.map(image=>image.decode()));
      const bounds=()=>[b,b.parentElement,...images].map(el=>{const r=el.getBoundingClientRect();return [r.x,r.y,r.width,r.height]});
      const current=bounds(),sources=images.map(image=>image.src);
      for(let i=0;i<images.length;i++) images[i].src='/static/assets/shell-icons/'+(i?'light':'dark')+'/drawing.svg';
      await Promise.all(images.map(image=>image.decode()));
      const previous=bounds();
      images.forEach((image,i)=>image.src=sources[i]);await Promise.all(images.map(image=>image.decode()));
      const image=images[0],canvas=document.createElement('canvas');canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;
      const context=canvas.getContext('2d');context.drawImage(image,0,0);
      const pixels=context.getImageData(0,0,canvas.width,canvas.height).data;
      let clear=0,solid=0;for(let i=3;i<pixels.length;i+=4){if(!pixels[i])clear++;if(pixels[i]>=250)solid++;}
      return {current,previous,clear,solid,title:b.title};
    })()`);
    assert.deepEqual(report.geometry.current, report.geometry.previous, 'Sidebar/button/icon geometry changed');
    assert.equal(report.geometry.title, 'Drawing');
    assert.ok(report.geometry.clear > 1000 && report.geometry.solid > 1000, 'Artwork needs transparent margins and an opaque sheet');

    for (const theme of ['dark', 'light']) {
      await js(`document.documentElement.dataset.theme=${JSON.stringify(theme)}`);
      if (await js(`${button}.classList.contains('active')`)) await js(`${button}.click()`);
      await pause();
      assert.equal(await js(`${button}.classList.contains('active')`), false);
      for (const state of ['idle', 'hover', 'selected']) {
        const point = state === 'hover' ? await js(`(()=>{const r=${button}.getBoundingClientRect();return{x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};})()`) : { x: 600, y: 400 };
        window.webContents.sendInputEvent({ type: 'mouseMove', ...point });
        if (state === 'selected') await js(`${button}.click()`);
        await pause();
        const observed = await js(`(()=>{const b=${button},image=[...b.querySelectorAll('img')].find(el=>getComputedStyle(el).display!=='none'),r=image.getBoundingClientRect();return{active:b.classList.contains('active'),hover:b.matches(':hover'),width:r.width,height:r.height,opacity:getComputedStyle(image).opacity,tooltip:b.querySelector('.activity-tooltip').textContent,panelVisible:document.querySelector('.left-panel').checkVisibility()};})()`);
        assert.deepEqual([observed.width, observed.height], [27, 27]);
        assert.equal(observed.active, state === 'selected');
        assert.equal(observed.tooltip, 'Drawing');
        if (state === 'selected') assert.equal(observed.panelVisible, true, 'Drawing no longer opens its panel');
        report.states.push({ theme, state, ...observed });
        const region = await js(`(()=>{const r=${button}.parentElement.getBoundingClientRect();return{x:Math.floor(r.x),y:0,width:600,height:340};})()`);
        const name = 'drawing-sidebar-' + theme + '-' + state + '.png';
        const capture = await window.webContents.capturePage(region);
        assert.ok(!capture.isEmpty());
        await fs.writeFile(path.join(output, name), capture.toPNG());
        report.captures.push(name);
      }
      await js(`${button}.click()`);
      await pause();
      assert.equal(await js(`${button}.classList.contains('active')`), false, 'Drawing no longer closes its panel');
    }
    await js(`document.documentElement.dataset.theme='dark'`);
    await pause();
    await fs.writeFile(path.join(output, 'drawing-sidebar-full.png'), (await window.webContents.capturePage()).toPNG());
    report.captures.push('drawing-sidebar-full.png');
  } finally {
    await js(`document.documentElement.dataset.theme=${JSON.stringify(initialTheme || 'dark')}`);
    window.webContents.setZoomFactor(initialZoom);
  }
  return report;
};
