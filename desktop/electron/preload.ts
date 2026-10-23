import { contextBridge, ipcRenderer } from "electron";

type AgentEventHandler = (event: unknown) => void;

contextBridge.exposeInMainWorld("localAgent", {
  platform: process.platform,
  previewScreenshot: (path: string) => ipcRenderer.invoke("agent:screenshot-preview", path),
  copyText: (text: string) => ipcRenderer.invoke("clipboard:copy-text", text),
  notifyRendererReady: () => ipcRenderer.send("renderer:ready"),
  getAgentStatus: () => ipcRenderer.invoke("agent:get-status"),
  checkForUpdates: () => ipcRenderer.invoke("agent:update-check"),
  openReleasePage: (url: string) =>
    ipcRenderer.invoke("agent:update-open-release", url),
  getDiagnostics: () => ipcRenderer.invoke("agent:diagnostics-get"),
  copyDiagnostics: (report: string) =>
    ipcRenderer.invoke("agent:diagnostics-copy", report),
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
  listMcpServers: () => ipcRenderer.invoke("agent:mcp-list"),
  upsertMcpServer: (
    server: Record<string, unknown>,
    secretUpdate?: {
      action?: "keep" | "set" | "clear";
      values?: Record<string, string>;
    }
  ) =>
    ipcRenderer.invoke(
      "agent:mcp-upsert",
      server,
      secretUpdate
    ),
  deleteMcpServer: (serverId: string) =>
    ipcRenderer.invoke("agent:mcp-delete", serverId),
  refreshMcpServers: () =>
    ipcRenderer.invoke("agent:mcp-refresh"),
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
  getGitOverview: () =>
    ipcRenderer.invoke("agent:git-overview"),
  openManagedWorktree: (pathValue: string, model?: string) =>
    ipcRenderer.invoke(
      "agent:git-worktree-open",
      pathValue,
      model
    ),
  getContext: (threadId: string) =>
    ipcRenderer.invoke("agent:context-get", threadId),
  pinContext: (threadId: string, pathValue: string) =>
    ipcRenderer.invoke("agent:context-pin", threadId, pathValue),
  unpinContext: (threadId: string, pathValue: string) =>
    ipcRenderer.invoke("agent:context-unpin", threadId, pathValue),
  refreshContext: (threadId: string) =>
    ipcRenderer.invoke("agent:context-refresh", threadId),
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
  projectCreationDefaults: () => ipcRenderer.invoke("agent:project-create-defaults"),
  chooseProjectParent: (defaultPath?: string) => ipcRenderer.invoke("agent:project-choose-parent", defaultPath),
  createProject: (options: {name:string; parent_path:string; initialize_git:boolean; model?:string}) => ipcRenderer.invoke("agent:project-create", options),
  getProject: () => ipcRenderer.invoke("agent:project-get"),
  listProjects: () => ipcRenderer.invoke("agent:project-list"),
  selectProject: (projectId: string, model?: string) =>
    ipcRenderer.invoke("agent:project-select", projectId, model),
  listModels: () => ipcRenderer.invoke("agent:model-list"),
  selectModel: (threadId: string, model: string) =>
    ipcRenderer.invoke("agent:model-select", threadId, model),
  createThread: (model?: string) => ipcRenderer.invoke("agent:thread-create", model),
  listThreads: () => ipcRenderer.invoke("agent:thread-list"),
  taskRequest: (threadId: string, operation: string, payload: Record<string, unknown> = {}) =>
    ipcRenderer.invoke("agent:task-request", threadId, operation, payload),
  planRequest: (threadId: string, operation: string, payload: Record<string, unknown> = {}) =>
    ipcRenderer.invoke("agent:plan-request", threadId, operation, payload),
  renameThread: (threadId: string, title: string, projectId?: string) => ipcRenderer.invoke("agent:thread-rename", threadId, title, projectId),
  getThread: (threadId: string) => ipcRenderer.invoke("agent:thread-get", threadId),
  startTurn: (threadId: string, prompt: string, model?: string) =>
    ipcRenderer.invoke("agent:turn-start", threadId, prompt, model),
  cancelTurn: (turnId: string) => ipcRenderer.invoke("agent:turn-cancel", turnId),
  onAgentEvent: (handler: AgentEventHandler) => {
    const listener = (_event: Electron.IpcRendererEvent, payload: unknown) => handler(payload);
    ipcRenderer.on("agent:event", listener);
    return () => ipcRenderer.removeListener("agent:event", listener);
  }
});
