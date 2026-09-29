import { contextBridge, ipcRenderer } from "electron";

type AgentEventHandler = (event: unknown) => void;

contextBridge.exposeInMainWorld("localAgent", {
  platform: process.platform,
  getAgentStatus: () => ipcRenderer.invoke("agent:get-status"),
  getPermission: () => ipcRenderer.invoke("agent:permission-get"),
  setPermission: (mode: string) =>
    ipcRenderer.invoke("agent:permission-set", mode),
  respondApproval: (
    approvalId: string,
    decision: "allow_once" | "allow_turn" | "deny",
    turnId?: string
  ) =>
    ipcRenderer.invoke(
      "agent:approval-respond",
      approvalId,
      decision,
      turnId
    ),
  openProject: (model?: string) => ipcRenderer.invoke("agent:project-open", model),
  getProject: () => ipcRenderer.invoke("agent:project-get"),
  listProjects: () => ipcRenderer.invoke("agent:project-list"),
  selectProject: (projectId: string, model?: string) =>
    ipcRenderer.invoke("agent:project-select", projectId, model),
  listModels: () => ipcRenderer.invoke("agent:model-list"),
  selectModel: (threadId: string, model: string) =>
    ipcRenderer.invoke("agent:model-select", threadId, model),
  createThread: (model?: string) => ipcRenderer.invoke("agent:thread-create", model),
  listThreads: () => ipcRenderer.invoke("agent:thread-list"),
  getThread: (threadId: string) => ipcRenderer.invoke("agent:thread-get", threadId),
  startTurn: (threadId: string, prompt: string) =>
    ipcRenderer.invoke("agent:turn-start", threadId, prompt),
  cancelTurn: (turnId: string) => ipcRenderer.invoke("agent:turn-cancel", turnId),
  onAgentEvent: (handler: AgentEventHandler) => {
    const listener = (_event: Electron.IpcRendererEvent, payload: unknown) => handler(payload);
    ipcRenderer.on("agent:event", listener);
    return () => ipcRenderer.removeListener("agent:event", listener);
  }
});
