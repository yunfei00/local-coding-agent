const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('fixture',{load:()=>ipcRenderer.invoke('fixture:load'),save:value=>ipcRenderer.invoke('fixture:save',value)});
