'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { createResearchPane } = require('../src/research-pane.cjs');

const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const iconData='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aEZoAAAAASUVORK5CYII=';

async function fixture(options = {}) {
  const handlers = new Map(), sessions = [], children = [], layouts = [], contents = [], external = [];
  class Contents extends EventEmitter {
    constructor(preferences) { super(); contents.push(this); this.preferences=preferences; this.mainFrame={url:''}; this.navigationHistory={canGoBack:()=>false,canGoForward:()=>false}; }
    setWindowOpenHandler(handler) { this.popup=handler; }
    setWebRTCIPHandlingPolicy(value) { this.rtc=value; }
    async loadURL(url) { this.mainFrame.url=url; this.emit('did-start-loading'); this.emit('did-navigate',{},url); this.emit('did-stop-loading'); }
    send() {}
    focus() { for (const item of contents) item.focused = item === this; this.emit('focus'); }
    stop() { this.stopped = true; }
    isDestroyed() { return !!this.closed; }
    isFocused() { return !!this.focused; }
    close() { this.closed=true; }
  }
  class View {
    constructor({webPreferences}) { this.webContents=new Contents(webPreferences); }
    setBounds(value) { this.bounds=value; }
    setVisible(value) { this.visible=value; }
  }
  function createSession(partition) {
    const value=new EventEmitter(); value.partition=partition; value.webRequest={};
    value.fetch=options.fetch;
    for(const method of ['onBeforeRequest','onBeforeSendHeaders']) value.webRequest[method]=fn=>{value[method]=fn;};
    for(const method of ['setPermissionCheckHandler','setPermissionRequestHandler','setDevicePermissionHandler','setDisplayMediaRequestHandler']) value[method]=fn=>{value[method+'Value']=fn;};
    value.setProxy=async config=>{value.proxy=config;}; value.closeAllConnections=async()=>{value.closed=true;}; value.clearStorageData=async()=>{value.cleared=true;};
    sessions.push(value); return value;
  }
  const window=new EventEmitter(); window.isDestroyed=()=>false; window.isFocused=()=>window.focused!==false; window.getContentBounds=()=>({width:1440,height:800});
  window.contentView={addChildView(view){const index=children.indexOf(view);if(index>=0)children.splice(index,1);children.push(view);},removeChildView(view){const index=children.indexOf(view);if(index>=0)children.splice(index,1);}};
  window.webContents={focus(){for(const item of contents)item.focused=false;}};
  const detachedWindows=[];
  const createDetachedWindow=()=>{
    const child=new EventEmitter(), views=[];
    child.isDestroyed=()=>!!child.destroyed; child.isFocused=()=>true; child.getContentBounds=()=>({width:1000,height:700});
    child.contentView={addChildView(v){const i=views.indexOf(v);if(i>=0)views.splice(i,1);views.push(v);},removeChildView(v){const i=views.indexOf(v);if(i>=0)views.splice(i,1);}};
    child.show=()=>{child.visible=true;};child.hide=()=>{child.visible=false;};child.focus=()=>{};child.destroy=()=>{child.destroyed=true;};child.views=views;
    detachedWindows.push(child);return child;
  };
  const pane=await createResearchPane({window, initialSplit:options.split||null, topInset:options.topInset||0,
    createDetachedWindow:options.detachable?createDetachedWindow:null, documentPreview:options.documentPreview||null,
    electron:{WebContentsView:View,session:{fromPartition:createSession},
    ipcMain:{handle(name,fn){handlers.set(name,fn);},removeHandler(name){handlers.delete(name);}},shell:{openExternal:async url=>external.push(url)},
    dialog:{showMessageBox:options.showMessageBox||async function(){return {response:0};}}},isApplicationSender:()=>false,onLayout:value=>layouts.push(value)});
  const trusted={sender:pane.chrome.webContents,senderFrame:pane.chrome.webContents.mainFrame};
  return {pane,sessions,children,layouts,window,external,detachedWindows,request:(value,event=trusted)=>handlers.get('desktop-research:command')(event,value)};
}

test('site icons survive hide and detach, but are cleared by main-frame navigation',async()=>{
  const f=await fixture({split:0.5,detachable:true});
  try {
    f.pane.open('https://example.com/');await new Promise(resolve=>setImmediate(resolve));
    const contents=f.pane.getViews()[0].webContents;
    contents.emit('page-favicon-updated',{},[iconData]);await new Promise(resolve=>setImmediate(resolve));
    assert.equal(f.pane.snapshot().tabs[0].favicon,iconData);
    f.pane.hide();f.pane.show();f.pane.detach();f.pane.dock();
    assert.equal(f.pane.snapshot().tabs[0].favicon,iconData);
    contents.emit('did-start-navigation',{},'https://example.com/frame',false,false);
    assert.equal(f.pane.snapshot().tabs[0].favicon,iconData);
    contents.emit('did-start-navigation',{},'https://example.org/',false,true);
    assert.equal(f.pane.snapshot().tabs[0].favicon,null);
    for(const [url,resourceType,allowed] of [[iconData,'image',true],[iconData,'script',false],['https://example.com/favicon.ico','image',false],['data:image/svg+xml;base64,PHN2Zz4=','image',false]]) {
      let result;f.sessions[1].onBeforeRequest({url,resourceType},value=>result=value);assert.equal(result.cancel,!allowed);
    }
  } finally {await f.pane.dispose();}
});

test('late favicon responses cannot overwrite a new page or revive a closed tab',async()=>{
  const pending=[];const signals=[];
  const f=await fixture({fetch:(_url,options)=>{const value=deferred();pending.push(value);signals.push(options.signal);return value.promise;}});
  try {
    const id=f.pane.open('https://example.com/');await new Promise(resolve=>setImmediate(resolve));
    const contents=f.pane.getViews()[0].webContents;
    contents.emit('page-favicon-updated',{},['https://example.com/icon.png']);
    await f.request({action:'navigate',tabId:id,value:'https://example.org/'});
    assert.equal(signals[0].aborted,true);
    pending[0].resolve(new Response(Buffer.from(iconData.split(',')[1],'base64')));
    await new Promise(resolve=>setImmediate(resolve));assert.equal(f.pane.snapshot().tabs[0].favicon,null);
    contents.emit('page-favicon-updated',{},['https://example.org/icon.png']);
    await f.request({action:'close',tabId:id});assert.equal(signals[1].aborted,true);
    pending[1].resolve(new Response(Buffer.from(iconData.split(',')[1],'base64')));
    await new Promise(resolve=>setImmediate(resolve));assert.equal(f.pane.snapshot().tabs.length,0);
  } finally {await f.pane.dispose();}
});

test('normal browser starts half width, resizes, detaches and docks the same tabs',async()=>{
  const f=await fixture({split:0.5,topInset:42,detachable:true});
  try {
    const id=f.pane.open('https://example.com/');
    assert.equal(f.pane.chrome.bounds.width,720);assert.equal(f.pane.chrome.bounds.y,42);
    const view=f.pane.getViews()[0], splitter=f.pane.splitter;
    await f.request({action:'resize',value:0.4},{sender:splitter.webContents,senderFrame:splitter.webContents.mainFrame});
    assert.equal(f.pane.chrome.bounds.width,576);
    await assert.rejects(f.request({action:'resize',value:0.95}),{code:'research_split_invalid'});
    await assert.rejects(f.request({action:'new'},{sender:splitter.webContents,senderFrame:splitter.webContents.mainFrame}),{code:'research_sender_rejected'});
    f.pane.detach();assert.equal(f.pane.snapshot().detached,true);assert.equal(f.pane.getViews()[0],view);
    assert.equal(f.detachedWindows[0].views.includes(view),true);assert.equal(f.layouts.at(-1).visible,false);
    f.pane.dock();assert.equal(f.pane.snapshot().detached,false);assert.equal(f.pane.snapshot().activeId,id);
    assert.equal(f.detachedWindows[0].destroyed,true);assert.equal(f.children.includes(view),true);
  } finally {await f.pane.dispose();}
});

test('closing a detached browser docks tabs; closing a pending document releases late bytes',async()=>{
  const load=deferred(),released=[];
  const f=await fixture({split:0.5,detachable:true,documentPreview:{session:{},accepts:url=>url.startsWith('http://127.0.0.1/'),prepare:()=>load.promise,release:url=>released.push(url)}});
  try{
    const id=f.pane.open('http://127.0.0.1/report.pdf');
    const preferences=f.pane.getViews()[0].webContents.preferences;
    assert.equal(preferences.plugins,true);assert.equal(preferences.preload,undefined);
    f.pane.detach();let prevented=false;f.detachedWindows[0].emit('close',{preventDefault(){prevented=true;}});
    assert.equal(prevented,true);assert.equal(f.pane.snapshot().detached,false);
    await f.request({action:'close',tabId:id});load.resolve({url:'https://snapshot.invalid/id',title:'PDF'});
    await new Promise(resolve=>setImmediate(resolve));assert.deepEqual(released,['https://snapshot.invalid/id']);
  } finally {await f.pane.dispose();}
});

test('research tabs preserve identity when hidden, deduplicate, bound count, and dispose resources',async()=>{
  const f=await fixture();
  try {
    const id=f.pane.open('https://example.com/'); await new Promise(resolve=>setImmediate(resolve));
    assert.equal(f.pane.open('https://example.com/'),id);
    const contents=f.pane.getViews()[0].webContents;
    contents.focus();
    f.pane.hide(); assert.equal(f.pane.snapshot().visible,false); assert.equal(contents.closed,undefined);
    f.pane.show(); assert.equal(f.pane.getViews()[0].webContents,contents);
    assert.equal(contents.preferences.preload,undefined); assert.equal(contents.preferences.nodeIntegration,false); assert.equal(contents.rtc,'disable_non_proxied_udp');
    assert.equal(contents.preferences.disableDialogs,true);
    for(let i=1;i<8;i++) f.pane.open();
    assert.throws(()=>f.pane.open(),{code:'research_tab_limit'});
    await f.request({action:'close',tabId:id}); assert.equal(contents.closed,true);
    f.pane.suspend(true); assert.ok(f.pane.getViews().every(view=>!view.visible));
    assert.equal(f.sessions[0].proxy.proxyBypassRules,'<-loopback>');
  } finally { await f.pane.dispose(); }
  assert.equal(f.children.length,0); assert.equal(f.sessions[0].closed,true); assert.equal(f.sessions[0].cleared,true);
});

test('a superseded load failure cannot replace a newer successful navigation', async()=>{
  const f=await fixture();
  try {
    const id=f.pane.open(), contents=f.pane.getViews()[0].webContents;
    const older=deferred(), newer=deferred();
    contents.loadURL=url=>url.endsWith('/old')?older.promise:newer.promise;
    const first=f.request({action:'navigate',tabId:id,value:'https://example.com/old'});
    const second=f.request({action:'navigate',tabId:id,value:'https://example.com/new'});
    contents.emit('did-navigate',{},'https://example.com/new'); contents.emit('did-stop-loading'); newer.resolve();
    await second;
    older.reject(Object.assign(new Error('late failure'),{code:'ERR_FAILED'})); await first;
    assert.equal(f.pane.snapshot().tabs[0].url,'https://example.com/new');
    assert.equal(f.pane.snapshot().tabs[0].error,null);
    assert.equal(f.pane.snapshot().tabs[0].loading,false);
    assert.equal(f.pane.getViews()[0].visible,true);
  } finally { await f.pane.dispose(); }
});

for(const ending of ['stop','back','forward','crash','close','dispose']) test('late navigation failure after '+ending+' cannot revive a tab or overwrite state',async()=>{
  const f=await fixture();
  try {
    const id=f.pane.open(), contents=f.pane.getViews()[0].webContents, pending=deferred();
    contents.loadURL=()=>pending.promise;
    const navigation=f.request({action:'navigate',tabId:id,value:'https://example.com/'});
    if(ending==='dispose') await f.pane.dispose();
    else if(ending==='crash') contents.emit('render-process-gone');
    else {
      contents.navigationHistory={canGoBack:()=>true,canGoForward:()=>true,goBack(){},goForward(){}};
      await f.request({action:ending,tabId:id});
    }
    const before=f.pane.snapshot();
    pending.reject(Object.assign(new Error('late failure'),{code:'ERR_FAILED'})); await navigation;
    assert.deepEqual(f.pane.snapshot(),before);
  } finally { await f.pane.dispose(); }
});

for(const state of ['hidden','suspended','background','unfocused','window-unfocused','closed','disposed']) test('popup from '+state+' research cannot open or reveal views',async()=>{
  const f=await fixture();
  try {
    const id=f.pane.open('https://example.com/'), contents=f.pane.getViews()[0].webContents;
    await new Promise(resolve=>setImmediate(resolve)); contents.focus();
    if(state==='hidden') f.pane.hide();
    if(state==='suspended') f.pane.suspend(true);
    if(state==='background') f.pane.open();
    if(state==='unfocused') f.pane.chrome.webContents.focus();
    if(state==='window-unfocused') f.window.focused=false;
    if(state==='closed') await f.request({action:'close',tabId:id});
    if(state==='disposed') await f.pane.dispose();
    const before=f.pane.snapshot();
    assert.deepEqual(contents.popup({url:'https://example.org/'}),{action:'deny'});
    assert.deepEqual(f.pane.snapshot(),before);
  } finally { await f.pane.dispose(); }
});

test('late toolbar commands cannot bypass a hidden or suspended research pane',async()=>{
  const f=await fixture();
  try {
    const id=f.pane.open();
    for(const state of ['hidden','suspended']) {
      if(state==='hidden') f.pane.hide(); else f.pane.suspend(true);
      for(const action of ['new','activate','navigate','reload','expand','external','close']) {
        await assert.rejects(f.request({action,tabId:id,value:'https://example.com/'}),{code:'research_not_interactive'});
      }
      assert.equal((await f.request({action:'state'})).tabs.length,1);
      if(state==='hidden') f.pane.show(); else {
        assert.throws(()=>f.pane.open(),{code:'research_suspended'});
        assert.throws(()=>f.pane.show(),{code:'research_suspended'});
        f.pane.suspend(false);
      }
    }
  } finally { await f.pane.dispose(); }
});

for(const change of ['none','navigate','hide','suspend','activate-other','close','dispose']) test('external-browser confirmation is bound to its original active tab: '+change,async()=>{
  const answer=deferred(), f=await fixture({showMessageBox:()=>answer.promise});
  try {
    const id=f.pane.open('https://example.com/'); await new Promise(resolve=>setImmediate(resolve));
    const opening=f.request({action:'external',tabId:id});
    if(change==='navigate') await f.request({action:'navigate',tabId:id,value:'https://example.org/'});
    if(change==='hide') f.pane.hide();
    if(change==='suspend') f.pane.suspend(true);
    if(change==='activate-other') f.pane.open();
    if(change==='close') await f.request({action:'close',tabId:id});
    if(change==='dispose') await f.pane.dispose();
    answer.resolve({response:1}); await opening;
    assert.deepEqual(f.external,change==='none'?['https://example.com/']:[]);
  } finally { await f.pane.dispose(); }
});

test('research IPC denies outside frames, unknown actions, arbitrary fields and private navigation',async()=>{
  const f=await fixture();
  try {
    const id=f.pane.open();
    await assert.rejects(f.request({action:'state'},{sender:{},senderFrame:{}}),{code:'research_sender_rejected'});
    await assert.rejects(f.request({action:'executeJavaScript',value:'process.exit()'}),{code:'research_command_invalid'});
    await assert.rejects(f.request({action:'state',path:'secret'}),{code:'research_command_invalid'});
    await assert.rejects(f.request({action:'navigate',tabId:id,value:'https://127.0.0.1'}),{code:'research_address_rejected'});
    await assert.rejects(f.request({action:'close',tabId:'missing'}),{code:'research_tab_missing'});
    let result;
    f.sessions[0].onBeforeRequest({url:'http://127.0.0.1:8000/api/profiles'},value=>{result=value;}); assert.equal(result.cancel,true);
    for (const url of ['chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/index.html','chrome://resources/js/assert.js']) {
      f.sessions[0].onBeforeRequest({url},value=>{result=value;}); assert.equal(result.cancel,false);
    }
    for (const url of ['chrome://settings','chrome-extension://other/index.html','file:///C:/private']) {
      f.sessions[0].onBeforeRequest({url},value=>{result=value;}); assert.equal(result.cancel,true);
    }
    f.sessions[0].onBeforeSendHeaders({url:'https://example.com',requestHeaders:{'X-InspectorPro-Desktop-Token':'secret'}},value=>{result=value;});
    assert.deepEqual(result,{cancel:false,requestHeaders:{}});
  } finally { await f.pane.dispose(); }
});

test('unchanged browser state does not repeatedly resize the engineering canvas',async()=>{
  const f=await fixture();
  try {
    f.pane.open(); const count=f.layouts.length;
    for(let i=0;i<5;i++) f.pane.layout();
    assert.equal(f.layouts.length,count);
    f.pane.suspend(true); assert.equal(f.layouts.at(-1).visible,false);
    f.pane.suspend(true,'application-overlay'); f.pane.suspend(false);
    assert.equal(f.pane.snapshot().suspended,true);
    f.pane.suspend(false,'application-overlay'); assert.equal(f.pane.snapshot().suspended,false);
  } finally { await f.pane.dispose(); }
});

test('reload belongs to focused research only, never another engineering view',async()=>{
  const f=await fixture();
  try {
    f.pane.open(); f.window.webContents.focus(); assert.equal(f.pane.reloadFocused(),false);
    f.pane.chrome.webContents.focused=true; assert.equal(f.pane.reloadFocused(),true);
    f.pane.hide(); assert.equal(f.pane.reloadFocused(),false);
  } finally { await f.pane.dispose(); }
});

test('research and control sessions deny device, capture and permission grants',async()=>{
  const f=await fixture();
  try {
    for (const session of f.sessions) {
      assert.equal(session.setPermissionCheckHandlerValue({},'media','https://example.com',{}),false);
      assert.equal(session.setDevicePermissionHandlerValue({deviceType:'usb'}),false);
      for (const permission of ['media','pointerLock','fullscreen','clipboard-read','notifications','unknown']) {
        let granted;
        session.setPermissionRequestHandlerValue({},permission,value=>{granted=value;},{});
        assert.equal(granted,false,permission);
      }
      let media;
      session.setDisplayMediaRequestHandlerValue({},value=>{media=value;});
      assert.deepEqual(media,{});
    }
  } finally { await f.pane.dispose(); }
});

test('research popups and failed renderers cannot gain an app bridge or a native window',async()=>{
  const f=await fixture();
  try {
    const id=f.pane.open('https://example.com/');
    await new Promise(resolve=>setImmediate(resolve));
    const contents=f.pane.getViews()[0].webContents;
    contents.focus();
    assert.deepEqual(contents.popup({url:'file:///private'}),{action:'deny'});
    assert.equal(f.pane.getViews().length,1);
    assert.deepEqual(contents.popup({url:'https://example.org/'}),{action:'deny'});
    assert.equal(f.pane.getViews().length,2);
    assert.ok(f.pane.getViews().every(view=>!view.webContents.preferences.preload));
    contents.emit('render-process-gone');
    assert.ok(f.pane.snapshot().tabs.find(tab=>tab.id===id).error);
    await f.request({action:'reload',tabId:id});
    assert.equal(f.pane.snapshot().tabs.find(tab=>tab.id===id).error,null);
    let prevented=false;
    f.sessions[0].emit('will-download',{preventDefault(){prevented=true;}},{},{});
    assert.equal(prevented,true);
  } finally { await f.pane.dispose(); }
});
