export {};

declare global {
  interface AgentEnvelope {
    type: string;
    request_id?: string | null;
    thread_id?: string | null;
    turn_id?: string | null;
    timestamp?: string;
    payload?: Record<string, unknown>;
  }

  interface Window {
    localAgent: {
      platform: string;
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
        secrets: Record<string, unknown>;
      }>;
      refreshMcpServers: () => Promise<{
        event: AgentEnvelope;
        secrets: Record<string, unknown>;
      }>;
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
      setPermission: (mode: string) => Promise<AgentEnvelope>;
      respondApproval: (
        approvalId: string,
        decision: "allow_once" | "allow_turn" | "deny",
        turnId?: string
      ) => Promise<AgentEnvelope>;
      openProject: (model?: string) => Promise<{ canceled: boolean; event?: AgentEnvelope }>;
      getProject: () => Promise<AgentEnvelope>;
      listProjects: () => Promise<AgentEnvelope>;
      selectProject: (projectId: string, model?: string) => Promise<AgentEnvelope>;
      listModels: () => Promise<AgentEnvelope>;
      selectModel: (threadId: string, model: string) => Promise<AgentEnvelope>;
      createThread: (model?: string) => Promise<AgentEnvelope>;
      listThreads: () => Promise<AgentEnvelope>;
      getThread: (threadId: string) => Promise<AgentEnvelope>;
      startTurn: (threadId: string, prompt: string) => Promise<AgentEnvelope>;
      cancelTurn: (turnId: string) => Promise<{ ok: boolean }>;
      onAgentEvent: (handler: (event: AgentEnvelope) => void) => () => void;
    };
  }
}
