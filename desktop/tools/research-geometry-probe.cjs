'use strict';
const { app, BrowserWindow, desktopCapturer, WebContentsView, screen } = require('electron');
const fs = require('node:fs/promises');
const fsSync = require('node:fs');
const path = require('node:path');
const { readWindowGeometry } = require('./window-geometry.cjs');
const { ownedWindowSource } = require('./owned-window-source.cjs');
const output = process.argv.at(-1);
if (!path.isAbsolute(output)) throw new Error('Absolute fresh diagnostic directory required');
fsSync.mkdirSync(output, { recursive: false });
app.setPath('userData', path.join(output, 'profile'));
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const preferences = { sandbox: true, contextIsolation: true, nodeIntegration: false };
let window, right;
const report = { schemaVersion: 1, purpose: 'controlled-native-view-probe', stages: [] };
const persist = () => fs.writeFile(path.join(output, 'result.json'), JSON.stringify(report, null, 2));
app.whenReady().then(async () => {
  try {
    window = new BrowserWindow({ title: 'InspectorPro Native View Probe', width: 1400, height: 850,
      show: false, webPreferences: preferences });
    await window.loadURL('data:text/html,' + encodeURIComponent('<title>InspectorPro Native View Probe</title><body style="margin:0;background:#cce0ee;font:24px system-ui"><header style="background:#263943;color:white;padding:24px">Application</header><main style="padding:32px">Native resize and capture fixture</main></body>'));
    right = new WebContentsView({ webPreferences: preferences });
    window.contentView.addChildView(right);
    await right.webContents.loadURL('data:text/html,' + encodeURIComponent('<body style="margin:0;background:#eff8ee;font:24px system-ui"><header style="background:#267c6d;color:white;padding:24px">Research</header><main style="padding:32px">Isolated native view</main></body>'));
    const wide = window.getSize();
    for (const [name, size] of [['first-wide', wide], ['narrow', [900,700]], ['return-wide', wide]]) {
      window.setSize(...size);
      const { width, height } = window.getContentBounds();
      right.setBounds({ x: Math.max(0,width-520), y: 0, width: Math.min(520,width), height });
      window.show(); window.focus(); await delay(700);
      const stage = { name, geometry: readWindowGeometry({ window, screen, requestedOuterSize: size }),
        title: window.getTitle(), mediaSourceId: window.getMediaSourceId(),
        focused: window.isFocused(), researchBounds: right.getBounds() };
      report.stages.push(stage); await persist();
      try {
        const owned = await ownedWindowSource({ window, desktopCapturer });
        await fs.writeFile(path.join(output, name + '.png'), owned.image.toPNG());
        stage.capture = { status: 'captured', observations: owned.observations };
      } catch (error) { stage.capture = { status: 'unavailable', message: error.message, observations: error.observations }; }
      await persist();
    }
  } catch (error) { report.error = { message: error.message, stack: error.stack }; }
  finally {
    if (right && !right.webContents.isDestroyed()) right.webContents.close({ waitForBeforeUnload: false });
    if (window && !window.isDestroyed()) window.destroy();
    await persist(); app.quit();
  }
}).catch(error => { console.error(error); app.exit(1); });
