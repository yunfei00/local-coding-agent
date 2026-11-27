export {};

declare global {
  interface AgentEnvelope {
    type: string;
    event_id?:string;
    request_id?: string | null;
    thread_id?: string | null;
    turn_id?: string | null;
    timestamp?: string;
    payload?: Record<string, unknown>;
  }

  interface Window {
    localAgent: {
      platform: string;
      readProjectDiff?: ()=>Promise<{status:string;unstaged:string;staged:string}>;
      searchProject?: (query:string,mode:"file"|"text")=>Promise<{hits:{file:string;line?:number;text?:string}[];truncated:boolean;skipped:number}>;
      cancelProjectSearch?: ()=>Promise<void>;
      sendLocalChatNext?: (message:string)=>Promise<void>;
      endLocalChat?: ()=>Promise<void>;
      listOpenCodeTasks?: ()=>Promise<{id:string;engine:"opencode";model:string;status:string;startedAt:string;endedAt?:string;events:number;verified:false}[]>;
      listSharedLocalProfiles?: ()=>Promise<{id:string;label:string;model:string;port:number;baseUrl:string;context:number;maxOutput:number}[]>;
      discoverOllamaModels?: (port:number)=>Promise<string[]>;
      diagnoseHistorySession?: (id:string,source?:"task")=>Promise<{sessionId:string;outcome:string;active:boolean;canResume:false;verified:false}|null>;
      listLocalChatHistory?: ()=>Promise<{id:string;model:string;createdAt:string;messages:string[];output:string;status:string;sessionId?:string;storageId?:string}[]>;
      runLocalChat?: (input:{model:string;prompt:string;port:number;followup?:string;messages?:string[];saveHistory?:boolean;profileId?:string;interactive?:boolean;fixtureTools?:boolean})=>Promise<{outcome:string;sessionId?:string;verified?:false;fixtureRoot?:string}>;
      onLocalChatProgress?: (handler:(progress:unknown)=>void)=>()=>void;
      cancelLocalChat?: (id?:string)=>Promise<void>;
      onLocalChatDelta?: (handler:(delta:string)=>void)=>()=>void;
      runEngineDiagnostic?: () => Promise<{status:string;sessionId?:string}>;
      getEngineStatus?: () => Promise<{selected: "legacy" | "opencode"; engines: Array<{id: "legacy" | "opencode"; available: boolean; version?: string; reason?: string}>}>;
    getOpenCodeProductionGate?: () => Promise<{enabled: boolean}>;
    setOpenCodeProductionGate?: (enabled: boolean) => Promise<{enabled: boolean}>;
      setWindowTheme: (theme: "light" | "dark") => Promise<void>;
      menuAction: (action: string) => Promise<void>;
      openProjectFolder: (projectId?:string) => Promise<void>;
      previewScreenshot: (path: string) => Promise<string>;
      copyText: (text: string) => Promise<{ok: boolean}>;
      notifyRendererReady: () => void;
      getAgentStatus: () => Promise<{
        state: "starting" | "ready" | "error" | "stopped";
        host?: string;
        port?: number;
        version?: string;
        protocol?: string;
        error?: string;
      }>;
      checkForUpdates: () => Promise<{
        ok: boolean;
        checked_at: string;
        current_version: string;
        latest_version?: string;
        update_available: boolean;
        release_url?: string;
        error?: string;
        automatic: false;
        can_auto_download: false;
        can_auto_install: false;
      }>;
      openReleasePage: (url: string) => Promise<{ ok: boolean }>;
      environment: () => Promise<AgentEnvelope>;
      backupData: () => Promise<AgentEnvelope>;
      downloadUpdate: () => Promise<{ready:boolean;version:string;sha256:string;notes:string}>;
      getUpdateState: () => Promise<import('../electron/updateManager').UpdateState>;
      cancelUpdateDownload: () => Promise<{cancelled:boolean}>;
      openUpdatePackage: () => Promise<{opened:boolean}>;
      openUpdateFolder: () => Promise<{opened:boolean}>;
      onUpdateState: (handler:(state:import('../electron/updateManager').UpdateState)=>void) => ()=>void;
      getDiagnostics: () => Promise<{
        event: AgentEnvelope;
        desktop: {
          app_version: string;
          packaged: boolean;
          platform: string;
          architecture: string;
          electron?: string;
          chrome?: string;
          node?: string;
          secret_storage: "os_protected" | "session_only" | "environment" | "none";
        };
      }>;
      copyDiagnostics: (report: string) => Promise<{ ok: boolean }>;
      getSettings: () => Promise<{
        event: AgentEnvelope;
        secret: {
          configured: boolean;
          stored: boolean;
          mode: "os_protected" | "session_only" | "environment" | "none";
        };
      }>;
      applySettings: (
        settings: Record<string, unknown>,
        secretUpdate?: {
          action?: "keep" | "set" | "clear";
          value?: string;
        }
      ) => Promise<{
        event: AgentEnvelope;
        provider: AgentEnvelope;
        secret: {
          configured: boolean;
          stored: boolean;
          mode: "os_protected" | "session_only" | "environment" | "none";
        };
      }>;
      resetSettings: () => Promise<{
        event: AgentEnvelope;
        provider: AgentEnvelope;
        secret: {
          configured: boolean;
          stored: boolean;
          mode: "os_protected" | "session_only" | "environment" | "none";
        };
      }>;
      listMcpServers: () => Promise<{
        event: AgentEnvelope;
        secrets: Record<
          string,
          {
            configured: boolean;
            keys: string[];
            stored: boolean;
            mode: "os_protected" | "session_only" | "environment" | "none";
          }
        >;
      }>;
      upsertMcpServer: (
        server: Record<string, unknown>,
        secretUpdate?: {
          action?: "keep" | "set" | "clear";
          values?: Record<string, string>;
        }
      ) => Promise<{
        event: AgentEnvelope;
        secrets: Record<
          string,
          {
            configured: boolean;
            keys: string[];
            stored: boolean;
            mode: "os_protected" | "session_only" | "environment" | "none";
          }
        >;
      }>;
      deleteMcpServer: (serverId: string) => Promise<{
        event: AgentEnvelope;
        secrets: Record<
          string,
          {
            configured: boolean;
            keys: string[];
            stored: boolean;
            mode: "os_protected" | "session_only" | "environment" | "none";
          }
        >;
      }>;
      refreshMcpServers: () => Promise<{
        event: AgentEnvelope;
        secrets: Record<
          string,
          {
            configured: boolean;
            keys: string[];
            stored: boolean;
            mode: "os_protected" | "session_only" | "environment" | "none";
          }
        >;
      }>;
      connectMcpServer: (serverId: string) => Promise<{ event: AgentEnvelope; secrets: Record<string, {configured:boolean;keys:string[];stored:boolean;mode:"os_protected"|"session_only"|"environment"|"none"}>; }>;
      disconnectMcpServer: (serverId: string) => Promise<{ event: AgentEnvelope; secrets: Record<string, {configured:boolean;keys:string[];stored:boolean;mode:"os_protected"|"session_only"|"environment"|"none"}>; }>;
      reconnectMcpServer: (serverId: string) => Promise<{ event: AgentEnvelope; secrets: Record<string, {configured:boolean;keys:string[];stored:boolean;mode:"os_protected"|"session_only"|"environment"|"none"}>; }>;
      getMcpHistory: (serverId?: string) => Promise<{ event: AgentEnvelope; secrets: Record<string, {configured:boolean;keys:string[];stored:boolean;mode:"os_protected"|"session_only"|"environment"|"none"}>; }>;
      exportMcpServers: () => Promise<{ event: AgentEnvelope }>;
      importMcpServers: (servers: Record<string, unknown>[]) => Promise<{ event: AgentEnvelope; secrets: Record<string, {configured:boolean;keys:string[];stored:boolean;mode:"os_protected"|"session_only"|"environment"|"none"}>; }>;
      getGitOverview: () => Promise<AgentEnvelope>;
      openManagedWorktree: (
        pathValue: string,
        model?: string
      ) => Promise<AgentEnvelope>;
      getContext: (threadId: string) => Promise<AgentEnvelope>;
      pinContext: (
        threadId: string,
        pathValue: string
      ) => Promise<AgentEnvelope>;
      unpinContext: (
        threadId: string,
        pathValue: string
      ) => Promise<AgentEnvelope>;
      refreshContext: (threadId: string) => Promise<AgentEnvelope>;
      getPromptRules: (threadId?: string) => Promise<AgentEnvelope>;
      setPromptRule: (
        scope: string,
        content: string,
        enabled: boolean,
        projectId?: string,
        threadId?: string
      ) => Promise<AgentEnvelope>;
      togglePromptRule: (
        scope: string,
        enabled: boolean,
        projectId?: string,
        threadId?: string
      ) => Promise<AgentEnvelope>;
      resetPromptRule: (
        scope: string,
        projectId?: string,
        threadId?: string
      ) => Promise<AgentEnvelope>;
      getPermission: () => Promise<AgentEnvelope>;
      setPermission: (mode: string, options?: {scope?:string;target?:string}) => Promise<AgentEnvelope>;
      respondApproval: (
        approvalId: string,
        decision: "allow_once" | "allow_turn" | "deny",
        turnId?: string
      ) => Promise<AgentEnvelope>;
      cancelApproval: (approvalId: string, turnId?: string) => Promise<any>;
      openProject: (model?: string) => Promise<{ canceled: boolean; event?: AgentEnvelope }>;
      projectCreationDefaults: () => Promise<{parent_path:string}>;
      chooseProjectParent: (defaultPath?:string) => Promise<{canceled:boolean; path?:string}>;
      createProject: (options: {name:string; parent_path:string; initialize_git:boolean; model?:string}) => Promise<AgentEnvelope>;
      getProject: () => Promise<AgentEnvelope>;
      listProjects: () => Promise<AgentEnvelope>;
      removeProject: (projectId:string) => Promise<AgentEnvelope>;
      selectProject: (projectId: string, model?: string) => Promise<AgentEnvelope>;
      listModels: () => Promise<AgentEnvelope>;
      selectModel: (threadId: string, model: string) => Promise<AgentEnvelope>;
      createThread: (model?: string, initialPrompt?:string) => Promise<AgentEnvelope>;
      deleteThread: (threadId:string, projectId:string) => Promise<AgentEnvelope>;
      listThreads: () => Promise<AgentEnvelope>;
      renameThread: (threadId: string, title: string, projectId?:string) => Promise<AgentEnvelope>;
      getThread: (threadId: string) => Promise<AgentEnvelope>;
      taskRequest: (threadId: string, operation: string, payload?: Record<string, unknown>) => Promise<AgentEnvelope>;
      planRequest: (threadId: string, operation: string, payload?: Record<string, unknown>) => Promise<AgentEnvelope>;
      startTurn: (threadId: string, prompt: string, model?: string, unified?: boolean, resume?:{run_id:string;confirm_workspace:boolean},routing?:{allow_fallback:boolean}) => Promise<AgentEnvelope>;
      appendTurn:(threadId:string,turnId:string,prompt:string,messageId:string)=>Promise<AgentEnvelope>;
      cancelTurn: (turnId: string) => Promise<{ ok: boolean }>;
      onAgentEvent: (handler: (event: AgentEnvelope) => void) => () => void;
    };
  }
}
