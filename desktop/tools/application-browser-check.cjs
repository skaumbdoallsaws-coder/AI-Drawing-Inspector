'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const { desktopCapturer } = require('electron');
const { ownedWindowSource } = require('./owned-window-source.cjs');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function run({ window, network, profile, output, ensureBrowser }) {
  window.setTitle('InspectorPro - Browser verification (isolated)');
  const source = JSON.parse(await fs.readFile(path.join(profile.dataRoot, 'application-check-source.json'), 'utf8'));
  assert.equal(profile.facilityRoot, source.isolatedFacilityRoot);
  assert.notEqual(path.dirname(source.originalPath), profile.facilityRoot);
  await fs.mkdir(output, {recursive:true});
  const report = { status:'running', checks:[], screenshots:[] };
  const persist = () => fs.writeFile(path.join(output,'browser-check.json'),JSON.stringify(report,null,2));
  const js = (code, contents=window.webContents) => contents.executeJavaScript(code,true);
  const until = async (predicate, label, ms=60000) => { const deadline=Date.now()+ms; while(Date.now()<deadline){if(await predicate())return;await pause(250);}throw Error(label); };
  const click = async (selector, contents=window.webContents) => {
    const p=await js(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});if(!e||e.disabled||e.closest('[inert]'))throw Error('Unavailable control');const r=e.getBoundingClientRect();if(!r.width||!r.height)throw Error('Hidden control');return{x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}})()`,contents);
    contents.focus(); for(const type of ['mouseMove','mouseDown','mouseUp'])contents.sendInputEvent({type,...p,button:'left',clickCount:1}); await pause(400);
  };
  const shot = async (name, target=window.webContents) => {
    const owner=target===window.webContents?window:pane&&target===pane.getHost().webContents?pane.getHost():null;
    if(owner){owner.show();owner.focus();}
    await pause(800);
    const image=owner?(await ownedWindowSource({window:owner,desktopCapturer})).image:await target.capturePage();
    await fs.writeFile(path.join(output,name+'.png'),image.toPNG());report.screenshots.push(name+'.png');return image;
  };
  const pagePixels = image => {
    const host=pane.getHost(),outer=host.getBounds(),content=host.getContentBounds(),vb=activeView().getBounds(),size=image.getSize();
    const sx=size.width/outer.width,sy=size.height/outer.height;
    return image.crop({x:Math.round((content.x-outer.x+vb.x)*sx),y:Math.round((content.y-outer.y+vb.y)*sy),width:Math.floor(vb.width*sx)-2,height:Math.floor(vb.height*sy)-2}).toBitmap();
  };
  const pdfShot = async name => {
    const started=Date.now();let image,darkFraction;
    do {
      window.show();window.focus();await pause(1000);
      image=(await ownedWindowSource({window,desktopCapturer})).image;
      const bitmap=pagePixels(image);let dark=0;
      for(let i=0;i<bitmap.length;i+=4)if(bitmap[i]<220&&bitmap[i+1]<220&&bitmap[i+2]<220)dark++;
      darkFraction=dark/(bitmap.length/4);
      if(darkFraction>0.02&&darkFraction<0.98)break;
    }while(Date.now()-started<45000);
    await fs.writeFile(path.join(output,name+'.png'),image.toPNG());report.screenshots.push(name+'.png');
    assert.ok(darkFraction>0.02&&darkFraction<0.98,'PDF viewport has no rendered paper');
    return {renderWaitMs:Date.now()-started,darkFraction};
  };
  const check = async (name, work) => {const item={name,status:'running'};report.checks.push(item);await persist();try{item.result=await work();item.status='passed';}catch(error){item.status='failed';item.error=error.message;await shot('failure-'+name).catch(()=>{});}await persist();};
  await until(()=>js(`!!window._trainFacilityLayoutAuthoringApp?.session.getState().loaded`),'facility-not-ready');
  const original = await js(`_trainFacilityLayoutAuthoringApp.session.getState()`);
  assert.equal(original.baseRevision,source.originalSha256);
  await js(`_trainFacilityLayoutAuthoringApp.session.editZoneLabel(${JSON.stringify(original.layout.zones[0].zoneId)},'Browser draft preservation check')`);
  const base=await js(`_trainFacilityLayoutAuthoringApp.session.getState()`);assert.equal(base.dirty,true);
  let pane;
  await check('rail-button-and-half-width',async()=>{
    assert.equal(await js(`document.getElementById('rightRailAgent').nextElementSibling.id`),'rightRailBrowser');
    await click('#rightRailBrowser');pane=await ensureBrowser();
    await until(()=>pane.snapshot().visible,'browser-not-visible');
    assert.equal(pane.chrome.getBounds().width,Math.round(window.getContentBounds().width/2));
    assert.ok(pane.splitter);assert.equal(pane.chrome.getBounds().y,42);
    await shot('01-half-width'); return {window:window.getContentBounds(),browser:pane.chrome.getBounds()};
  });
  if(!pane)throw Error('Browser unavailable');
  const command = request => js(`window.research.command(${JSON.stringify(request)})`,pane.chrome.webContents);
  const active = () => pane.snapshot().tabs.find(tab=>tab.id===pane.snapshot().activeId);
  const activeView = () => pane.getViews()[pane.snapshot().tabs.findIndex(tab=>tab.id===pane.snapshot().activeId)];
  await check('real-website-navigation',async()=>{
    await js(`document.getElementById('address').value='https://example.com';document.getElementById('address-form').requestSubmit()`,pane.chrome.webContents);
    await until(()=>!active().loading&&active().title==='Example Domain','public-page-not-loaded');
    assert.equal(active().error,null);await shot('02-public-website');return active();
  });
  await check('divider-resize-and-reset',async()=>{
    pane.splitter.webContents.focus();pane.splitter.webContents.sendInputEvent({type:'keyDown',keyCode:'Tab'});pane.splitter.webContents.sendInputEvent({type:'keyUp',keyCode:'Tab'});
    await js(`document.getElementById('splitter').focus()`,pane.splitter.webContents);
    pane.splitter.webContents.sendInputEvent({type:'keyDown',keyCode:'Left'});pane.splitter.webContents.sendInputEvent({type:'keyUp',keyCode:'Left'});
    await until(()=>pane.snapshot().splitFraction>0.5,'divider-did-not-resize');
    const width=pane.chrome.getBounds().width;assert.ok(width>window.getContentBounds().width/2);
    await command({action:'resize',value:0.5});
    const divider=pane.splitter.webContents;divider.focus();
    const wb=window.getContentBounds(),sb=pane.splitter.getBounds(),globalX=wb.x+sb.x+3,globalY=wb.y+sb.y+100;
    await js(`window.pointerEvidence=[];for(const type of ['pointerdown','pointermove','pointerup','lostpointercapture'])document.addEventListener(type,e=>{if(window.pointerEvidence.length<30)window.pointerEvidence.push({type:e.type,x:e.screenX,buttons:e.buttons,trusted:e.isTrusted});})`,divider);
    divider.sendInputEvent({type:'mouseMove',x:3,y:100,globalX,globalY});await pause(100);
    divider.sendInputEvent({type:'mouseDown',x:3,y:100,globalX,globalY,button:'left',clickCount:1});
    await pause(100);
    divider.sendInputEvent({type:'mouseMove',x:-77,y:100,globalX:globalX-80,globalY,modifiers:['leftButtonDown'],movementX:-80,movementY:0});
    try { await until(()=>pane.snapshot().splitFraction>0.53,'pointer-drag-did-not-resize',10000); }
    finally {
      divider.sendInputEvent({type:'mouseUp',x:3,y:100,globalX:globalX-80,globalY,button:'left',clickCount:1});
      await fs.writeFile(path.join(output,'pointer-debug.json'),JSON.stringify(await js('window.pointerEvidence',divider),null,2));
    }
    const dragged=pane.chrome.getBounds().width;await command({action:'resize',value:0.5});
    await shot('03-divider');return {keyboardWidth:width,draggedWidth:dragged};
  });
  await check('hide-and-reopen-preserves-tabs',async()=>{
    const views=pane.getViews(),ids=pane.snapshot().tabs.map(t=>t.id);
    await click('#hide',pane.chrome.webContents);assert.equal(pane.snapshot().visible,false);
    await click('#rightRailBrowser');assert.equal(pane.snapshot().visible,true);
    assert.deepEqual(pane.snapshot().tabs.map(t=>t.id),ids);assert.deepEqual(pane.getViews(),views);return {ids};
  });
  await check('multiple-tabs-and-history',async()=>{
    await click('#new',pane.chrome.webContents);const id=pane.snapshot().activeId;
    await command({action:'navigate',tabId:id,value:'https://example.com/?page=one'});
    await command({action:'navigate',tabId:id,value:'https://example.com/?page=two'});
    await until(()=>active().canGoBack,'history-not-available');await click('#back',pane.chrome.webContents);
    await until(()=>active().url.includes('page=one'),'back-did-not-navigate');await click('#forward',pane.chrome.webContents);
    await until(()=>active().url.includes('page=two'),'forward-did-not-navigate');
    await click('#reload',pane.chrome.webContents);await until(()=>!active().loading,'reload-did-not-finish');return {tabs:pane.snapshot().tabs.length};
  });
  await check('chat-link-opens-in-browser',async()=>{
    pane.hide();await click('#rightRailAgent');
    await js(`(()=>{const box=document.getElementById('agentMessages');const a=document.createElement('a');a.id='browserAcceptanceLink';a.href='https://www.google.com/';a.textContent='Browser verification link';a.style.cssText='display:block;padding:16px';box.append(a);box.scrollTop=box.scrollHeight;})()`);
    await click('#browserAcceptanceLink');await until(()=>pane.snapshot().tabs.some(t=>t.url==='https://www.google.com/'),'chat-link-not-opened');
    await until(()=>!active().loading,'google-still-loading');await shot('04-chat-link-google');
    await js(`document.getElementById('browserAcceptanceLink').remove()`);await click('#rightRailAgent');
    for(const tab of [...pane.snapshot().tabs])if(tab.id!==active().id)await command({action:'close',tabId:tab.id});
    return active();
  });
  const revision='89e24b00b06f31eeb6031a4cf42ddc588859b883609caac8353638c12d2f0295';
  for(const format of ['pdf','docx'])await check('local-'+format+'-preview',async()=>{
    const url=profile.origin+'/api/operations-manual/MMLE-50D/documents/'+revision+'/'+format;
    await js(`window.open(${JSON.stringify(url)},'_blank')`);
    if(format==='pdf')await pause(5000);
    await until(()=>active()?.kind==='document'&&!active().loading,'document-not-ready');
    assert.equal(active().error,null);assert.equal(active().url,url);
    const preferences=activeView().webContents.getLastWebPreferences();
    assert.equal(preferences.nodeIntegration,false);assert.equal(preferences.preload,undefined);
    const wasExpanded=pane.snapshot().expanded;let rendering;
    try {
      if(!wasExpanded)await click('#expand',pane.chrome.webContents);
      if(format==='pdf')rendering=await pdfShot('05-pdf-preview');
      else await shot('05-'+format+'-preview');
    } finally { if(pane.snapshot().expanded!==wasExpanded)await command({action:'expand'}); }
    return {...active(),rendering};
  });
  await check('save-original-document',async()=>{
    const saved=path.join(output,'downloaded-manual.docx');
    const completed=new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(Error('download-not-completed')),30000);
      window.webContents.session.once('will-download',(_event,item,contents)=>{
        assert.equal(contents,window.webContents);item.setSavePath(saved);
        item.once('done',(_e,state)=>{clearTimeout(timer);state==='completed'?resolve():reject(Error('download-'+state));});
      });
    });
    await command({action:'download',tabId:active().id});await completed;
    const bytes=await fs.readFile(saved);assert.equal(bytes.subarray(0,2).toString(),'PK');
    assert.equal(pane.snapshot().download.state,'completed');return {bytes:bytes.length,state:pane.snapshot().download.state};
  });
  await check('detached-window-and-redock',async()=>{
    const views=pane.getViews();await click('#detach',pane.chrome.webContents);
    await until(()=>pane.snapshot().detached,'browser-not-detached');const detached=pane.getHost();
    await shot('06-detached',detached.webContents);await shot('06-detached-page',activeView().webContents);
    await click('#detach',pane.chrome.webContents);assert.equal(pane.snapshot().detached,false);assert.deepEqual(pane.getViews(),views);return {sameTabs:true};
  });
  await check('narrow-window-and-expand',async()=>{
    if(pane.snapshot().expanded)await command({action:'expand'});
    const originalBounds=window.getBounds();window.unmaximize();window.setContentSize(900,700);await pause(600);
    assert.equal(pane.chrome.getBounds().width,window.getContentBounds().width);
    assert.equal(pane.splitter.getVisible(),false);await shot('07-narrow-browser');
    await click('#hide',pane.chrome.webContents);await shot('07-narrow-app');
    await click('#rightRailBrowser');window.setBounds(originalBounds);await pause(600);
    await click('#expand',pane.chrome.webContents);assert.equal(pane.chrome.getBounds().x,0);
    await click('#expand',pane.chrome.webContents);assert.ok(pane.chrome.getBounds().x>0);return {restored:true};
  });
  await check('public-pdf-preview',async()=>{
    pane.open('https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf');
    await pause(5000);
    await until(()=>!active().loading,'public-pdf-not-ready');assert.equal(active().error,null);
    const rendering=await pdfShot('08-public-pdf');return {...active(),rendering};
  });
  await check('private-network-refusal',async()=>{
    await command({action:'new'});const id=active().id;
    await assert.rejects(command({action:'navigate',tabId:id,value:'https://127.0.0.1:8480/api/profiles'}));
    const prefs=activeView().webContents.getLastWebPreferences();assert.equal(prefs.preload,undefined);assert.equal(prefs.nodeIntegration,false);return {privateAddressRejected:true};
  });
  await check('facility-unchanged',async()=>{
    pane.hide();const current=await js(`_trainFacilityLayoutAuthoringApp.session.getState()`);
    for(const key of ['layout','draftRevision','history','historyCursor','selection'])assert.deepEqual(current[key],base[key]);
    await click('.facility-ribbon-commandbar [data-facility-ribbon-command="undo"]');
    await until(()=>js(`_trainFacilityLayoutAuthoringApp.session.getState().draftRevision===${JSON.stringify(original.draftRevision)}`),'undo-not-restored');
    assert.deepEqual(await js(`_trainFacilityLayoutAuthoringApp.session.getState().layout`),original.layout);
    assert.equal(createHash('sha256').update(await fs.readFile(source.originalPath)).digest('hex'),source.originalSha256);
    assert.equal(network.getEvidence().saveCalls,0);return {originalUnchanged:true,unsavedDraftPreserved:true,undoRestored:true,saveCalls:0};
  });
  report.browser=pane.evidence();report.network=network.getEvidence();
  report.status=report.checks.every(c=>c.status==='passed')?'passed':'failed';await persist();return report;
}
module.exports={run};
