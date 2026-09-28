import { contextBridge, ipcRenderer } from "electron";

type AgentEventHandler = (event: unknown) => void;

contextBridge.exposeInMainWorld("localAgent", {
  platform: process.platform,
  getAgentStatus: () => ipcRenderer.invoke("agent:get-status"),
  createThread: (title?: string) => ipcRenderer.invoke("agent:thread-create", title),
  listThreads: () => ipcRenderer.invoke("agent:thread-list"),
  startTurn: (threadId: string, prompt: string) =>
    ipcRenderer.invoke("agent:turn-start", threadId, prompt),
  cancelTurn: (turnId: string) => ipcRenderer.invoke("agent:turn-cancel", turnId),
  onAgentEvent: (handler: AgentEventHandler) => {
    const listener = (_event: Electron.IpcRendererEvent, payload: unknown) => handler(payload);
    ipcRenderer.on("agent:event", listener);
    return () => ipcRenderer.removeListener("agent:event", listener);
  }
});
