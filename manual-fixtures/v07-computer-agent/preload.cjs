const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('fixture',{verified:()=>ipcRenderer.invoke('v07:verified'),pointer:data=>ipcRenderer.invoke('v07:pointer',data)});
