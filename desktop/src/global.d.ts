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
