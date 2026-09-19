'use strict';
// Lightweight native rendering check. The document fetch is a controlled fixture,
// not evidence of backend integration; the application driver covers that boundary.
const electron = require('electron');
const { app, BrowserWindow } = electron;
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const { createResearchPane } = require('../src/research-pane.cjs');
const { createDocumentPreview } = require('../src/document-preview.cjs');
const { ownedWindowSource } = require('./owned-window-source.cjs');
const output = path.resolve(process.argv[2]);
const pdfPath = path.resolve(process.argv[3]);
const faviconsOnly = process.argv.includes('--favicons-only');
app.setPath('userData', path.join(output, 'profile'));
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
let window, pane, documents;
const report = { status: 'running', checks: [] };
const persist = () => fs.writeFile(path.join(output, 'component-check.json'), JSON.stringify(report, null, 2));
async function run() {
  await fs.mkdir(output, { recursive: true }); await app.whenReady();
  window = new BrowserWindow({ title: 'InspectorPro browser component check', width: 1440, height: 800,
    webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
  await window.loadURL('data:text/html,<title>Browser component check</title><h2>Isolated browser rendering fixture</h2>');
  const bytes = await fs.readFile(pdfPath);
  documents = await createDocumentPreview({ electron, origin: 'http://127.0.0.1:8494', getCredential: () => 'a'.repeat(64),
    fetcher: async () => new Response(bytes, { headers: { 'content-type': 'application/pdf' } }) });
  pane = await createResearchPane({ window, electron, isApplicationSender: () => false, initialSplit: 0.5, documentPreview: documents });
  const js = (contents, code) => contents.executeJavaScript(code, true);
  const command = value => js(pane.chrome.webContents, `window.research.command(${JSON.stringify(value)})`);
  const check = async (name, work) => {
    const item = { name, status: 'running' }; report.checks.push(item); await persist();
    try { item.result = await work(); item.status = 'passed'; }
    catch (error) { item.status = 'failed'; item.error = error.stack; }
    report.evidence = pane.evidence(); await persist();
  };
  pane.show();
  await check('native-pointer-drag', async () => {
    const c = pane.splitter.webContents; c.focus();
    const b=window.getContentBounds(),v=pane.splitter.getBounds(),globalX=b.x+v.x+3,globalY=b.y+v.y+100;
    await js(c, `window.events=[];for(const type of ['pointerdown','pointermove','pointerup','lostpointercapture'])document.addEventListener(type,e=>events.push({type:e.type,x:e.screenX,buttons:e.buttons,trusted:e.isTrusted}));`);
    c.sendInputEvent({ type: 'mouseMove', x: 3, y: 100,globalX,globalY }); await pause(100);
    c.sendInputEvent({ type: 'mouseDown', x: 3, y: 100,globalX,globalY, button: 'left', clickCount: 1 }); await pause(100);
    c.sendInputEvent({ type: 'mouseMove', x: -77, y: 100,globalX:globalX-80,globalY, modifiers: ['leftButtonDown'], movementX: -80, movementY: 0 }); await pause(700);
    c.sendInputEvent({ type: 'mouseUp', x: 3, y: 100,globalX:globalX-80,globalY, button: 'left', clickCount: 1 });
    const events = await js(c, 'window.events');
    await fs.writeFile(path.join(output, 'pointer-events.json'), JSON.stringify(events, null, 2));
    assert.ok(pane.snapshot().splitFraction > 0.53, 'Pointer did not resize the pane');
    await command({ action: 'resize', value: 0.5 }); return events;
  });
  if(!faviconsOnly)await check('native-pdf-render', async () => {
    const id = pane.open('http://127.0.0.1:8494/generated/fixture.pdf');
    const view = pane.getViews().at(-1);
    report.console=[];view.webContents.on('console-message',(_event,details,message)=>report.console.push({level:details?.level??details,message:details?.message??message}));
    report.navigations=[];view.webContents.on('will-frame-navigate',(event,details)=>report.navigations.push({target:details?.url||event.url,isMainFrame:details?.isMainFrame??event.isMainFrame,prevented:event.defaultPrevented}));
    await pause(6000);
    const deadline=Date.now()+40000;
    while(pane.snapshot().tabs.find(t=>t.id===id).loading&&Date.now()<deadline)await pause(500);
    await pause(3000);
    const tab = pane.snapshot().tabs.find(t => t.id === id); assert.equal(tab.error, null);
    report.frames=view.webContents.mainFrame.framesInSubtree.map(f=>({url:f.url,name:f.name}));
    window.show();window.focus();
    const image = (await ownedWindowSource({window,desktopCapturer:electron.desktopCapturer})).image;
    await fs.writeFile(path.join(output, 'pdf.png'), image.toPNG());
    const size=image.getSize(),outer=window.getBounds(),content=window.getContentBounds(),vb=view.getBounds();
    const sx=size.width/outer.width,sy=size.height/outer.height;
    const bitmap = image.crop({x:Math.round((content.x-outer.x+vb.x)*sx),y:Math.round((content.y-outer.y+vb.y)*sy),width:Math.floor(vb.width*sx)-2,height:Math.floor(vb.height*sy)-2}).toBitmap(); let dark = 0;
    for (let i = 0; i < bitmap.length; i += 4) if (bitmap[i] < 220 && bitmap[i + 1] < 220 && bitmap[i + 2] < 220) dark++;
    assert.ok(dark / (bitmap.length / 4) > 0.02 && dark / (bitmap.length / 4) < 0.98, 'PDF viewport has no rendered paper');
    return { pixels: bitmap.length / 4, darkFraction: dark / (bitmap.length / 4), documents: documents.evidence() };
  });
  await check('google-and-linkedin-tab-icons', async () => {
    for(const tab of pane.snapshot().tabs)await command({action:'close',tabId:tab.id});
    const ids=[];
    for(const url of ['https://www.google.com/','https://www.linkedin.com/']){
      const id=pane.open(url);ids.push(id);
      const deadline=Date.now()+30000;
      while(!pane.snapshot().tabs.find(t=>t.id===id)?.favicon&&Date.now()<deadline)await pause(250);
      const tab=pane.snapshot().tabs.find(t=>t.id===id);
      assert.ok(tab?.favicon,`${url} did not provide a rendered favicon`);
    }
    await pause(1500);
    const rendered=await js(pane.chrome.webContents,`[...document.querySelectorAll('#tabs .tab')].map(tab=>({title:tab.querySelector('.tab-title')?.textContent,icon:!!tab.querySelector('img')?.complete,width:tab.querySelector('img')?.naturalWidth||0,box:tab.getBoundingClientRect().toJSON()}))`);
    assert.equal(rendered.length,2);assert.ok(rendered.every(t=>t.icon&&t.width>0));
    assert.match(rendered[0].title,/Google/i);assert.match(rendered[1].title,/LinkedIn/i);
    report.iconRendering=rendered;await persist();
    window.show();window.focus();await pause(1000);
    try {
      const toolbar=await pane.chrome.webContents.capturePage();
      await fs.writeFile(path.join(output,'website-icons-toolbar.png'),toolbar.toPNG());
    } catch(error) { report.toolbarCaptureError=String(error.message); }
    const image=(await ownedWindowSource({window,desktopCapturer:electron.desktopCapturer})).image;
    await fs.writeFile(path.join(output,'website-icons.png'),image.toPNG());
    const before=pane.snapshot().tabs.map(t=>t.favicon);pane.hide();pane.show();
    assert.deepEqual(pane.snapshot().tabs.map(t=>t.favicon),before);
    return {rendered,ids};
  });
  report.status = report.checks.every(c => c.status === 'passed') ? 'passed' : 'failed'; await persist();
}
let watchdog;
Promise.race([run(), new Promise((_, reject) => { watchdog = setTimeout(() => reject(Error('Component check deadline exceeded')), 150000); })])
  .catch(async error => { report.status = 'failed'; report.error = error.stack; await persist(); })
  .finally(async () => { clearTimeout(watchdog); await pane?.dispose(); await documents?.dispose(); window?.destroy(); app.quit(); });
