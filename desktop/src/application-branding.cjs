'use strict';
const path = require('node:path');

const APP_NAME = 'InspectorPro';
const APP_ID = 'InspectorPro.Desktop';
const ICON_PATH = path.resolve(__dirname, '../assets/inspectorpro.ico');

function brandApplication(app, platform = process.platform) {
  app.setName(APP_NAME);
  if (platform === 'win32') app.setAppUserModelId(APP_ID);
}

function brandWindow(window, platform = process.platform) {
  if (platform === 'win32') {
    window.setAppDetails({ appId: APP_ID, appIconPath: ICON_PATH, appIconIndex: 0 });
  }
}

module.exports = { APP_NAME, APP_ID, ICON_PATH, brandApplication, brandWindow };
