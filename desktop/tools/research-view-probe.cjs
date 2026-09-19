'use strict';
const {app,BrowserWindow,View,desktopCapturer,WebContentsView}=require('electron');
const fs=require('node:fs/promises');
const path=require('node:path');
const output=process.argv.at(-1);
if(!path.isAbsolute(output)) throw new Error('Absolute fresh diagnostic directory required');
app.setPath('userData',path.join(output,'profile'));
let window;
app.whenReady().then(async()=>{
  await fs.mkdir(output,{recursive:true});
  const result={};
  try {
    window=new BrowserWindow({title:'InspectorPro Research View Probe',width:1100,height:700,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false}});
    await window.loadURL('data:text/html,<title>InspectorPro Research View Probe</title><body style="background:lightblue">Application</body>');
    const initial=window.contentView;
    result.before={type:initial.constructor.name,hasContents:initial.webContents===window.webContents,children:initial.children.map(view=>({type:view.constructor.name,hasContents:view.webContents===window.webContents}))};
    const original={webContents:window.webContents};
    if(original.webContents===window.webContents){
      const root=window.contentView;
      const right=new WebContentsView({webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false}});
      root.addChildView(right);right.setBounds({x:600,y:0,width:480,height:640});
      await right.webContents.loadURL('data:text/html,<body style="background:lightgreen">Research</body>');
      await new Promise(resolve=>setTimeout(resolve,500));
      result.after={innerWidth:await window.webContents.executeJavaScript('innerWidth'),sameContents:original.webContents===window.webContents};
      await fs.writeFile(path.join(output,'application.png'),(await window.webContents.capturePage()).toPNG());
      await fs.writeFile(path.join(output,'research.png'),(await right.webContents.capturePage()).toPNG());
      result.expectedSource=window.getMediaSourceId();
      const sources=await desktopCapturer.getSources({types:['window'],thumbnailSize:{width:1600,height:1000}});
      result.sources=sources.map(source=>({id:source.id,empty:source.thumbnail.isEmpty(),owned:source.name==='InspectorPro Research View Probe'}));
      const source=sources.find(item=>item.id.split(':')[1]===result.expectedSource.split(':')[1]);
      if(source&&!source.thumbnail.isEmpty()) await fs.writeFile(path.join(output,'native.png'),source.thumbnail.toPNG());
      const handle=window.getNativeWindowHandle();
      const value=handle.length===8?handle.readBigUInt64LE().toString():String(handle.readUInt32LE());
      result.printWindow=await new Promise((resolve,reject)=>require('node:child_process').execFile('powershell.exe',
        ['-NoProfile','-NonInteractive','-File',path.join(__dirname,'capture-owned-window.ps1'),'-WindowHandle',value,
          '-OwnerProcessId',String(process.pid),'-OutputPath',path.join(output,'owned-native.png')],
        {windowsHide:true,timeout:15000},(error,stdout,stderr)=>error?reject(new Error(stderr||error.message)):resolve(JSON.parse(stdout))));
      right.webContents.close({waitForBeforeUnload:false});
    }
  } catch(error){result.error={message:error.message,stack:error.stack};}
  finally {await fs.writeFile(path.join(output,'result.json'),JSON.stringify(result,null,2));if(window&&!window.isDestroyed())window.destroy();app.quit();}
}).catch(error=>{console.error(error);app.exit(1);});
