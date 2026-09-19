'use strict';
const {contextBridge,ipcRenderer}=require('electron');
if(process.isMainFrame&&process.argv.includes('--isolated-facility-managed-recovery-harness')) {
  contextBridge.exposeInMainWorld('FacilityRecoveryTest',Object.freeze({
    capabilities:()=>Object.freeze({mode:'isolated-facility-recovery-harness',managedBackendRecovery:true,interactive:true,researchBrowsing:false,save:false}),
    persist:record=>ipcRenderer.invoke('facility-managed-test:persist',record),
    clear:record=>ipcRenderer.invoke('facility-managed-test:clear',record),
  }));
}
