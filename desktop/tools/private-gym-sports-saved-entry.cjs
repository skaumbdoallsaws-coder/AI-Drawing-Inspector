'use strict';
const {app}=require('electron');
app.commandLine.appendSwitch('remote-debugging-address','127.0.0.1');
app.commandLine.appendSwitch('remote-debugging-port','9542');
app.once('browser-window-created',(_event,window)=>{
  window.webContents.once('did-finish-load',()=>{
    window.maximize();window.show();window.webContents.setBackgroundThrottling(false);
  });
});
require('../src/entry.cjs');
