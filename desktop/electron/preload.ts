import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("localAgent", {
  platform: process.platform,
  getAgentStatus: () => ipcRenderer.invoke("agent:get-status")
});
