'use strict';
const { contextBridge, ipcRenderer } = require('electron');
if (process.isMainFrame) {
  contextBridge.exposeInMainWorld('research', Object.freeze({
    command: value => ipcRenderer.invoke('desktop-research:command', value),
    subscribe(listener) {
      if (typeof listener !== 'function') throw new TypeError('Listener required');
      const handler = (_event, value) => listener(value);
      ipcRenderer.on('desktop-research:state', handler);
      return () => ipcRenderer.removeListener('desktop-research:state', handler);
    },
    onAddressFocus(listener) {
      if (typeof listener !== 'function') throw new TypeError('Listener required');
      const handler = () => listener();
      ipcRenderer.on('desktop-research:focus-address', handler);
      return () => ipcRenderer.removeListener('desktop-research:focus-address', handler);
    },
  }));
}
