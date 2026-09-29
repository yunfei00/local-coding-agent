import { contextBridge, ipcRenderer } from "electron";

type AgentEventHandler = (event: unknown) => void;

contextBridge.exposeInMainWorld("localAgent", {
  platform: process.platform,
  notifyRendererReady: () => ipcRenderer.send("renderer:ready"),
  getAgentStatus: () => ipcRenderer.invoke("agent:get-status"),
  getSettings: () => ipcRenderer.invoke("agent:settings-get"),
  applySettings: (
    settings: Record<string, unknown>,
    secretUpdate?: {
      action?: "keep" | "set" | "clear";
      value?: string;
    }
  ) =>
    ipcRenderer.invoke(
      "agent:settings-apply",
      settings,
      secretUpdate
    ),
  resetSettings: () => ipcRenderer.invoke("agent:settings-reset"),
  getPromptRules: (threadId?: string) =>
    ipcRenderer.invoke("agent:prompt-rules-get", threadId),
  setPromptRule: (
    scope: string,
    content: string,
    enabled: boolean,
    projectId?: string,
    threadId?: string
  ) =>
    ipcRenderer.invoke(
      "agent:prompt-rule-set",
      scope,
      content,
      enabled,
      projectId,
      threadId
    ),
  togglePromptRule: (
    scope: string,
    enabled: boolean,
    projectId?: string,
    threadId?: string
  ) =>
    ipcRenderer.invoke(
      "agent:prompt-rule-toggle",
      scope,
      enabled,
      projectId,
      threadId
    ),
  resetPromptRule: (
    scope: string,
    projectId?: string,
    threadId?: string
  ) =>
    ipcRenderer.invoke(
      "agent:prompt-rule-reset",
      scope,
      projectId,
      threadId
    ),
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
