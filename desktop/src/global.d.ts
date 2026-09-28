export {};

declare global {
  interface Window {
    localAgent: {
      platform: string;
      getAgentStatus: () => Promise<{
        state: "starting" | "ready" | "error" | "stopped";
        host?: string;
        port?: number;
        version?: string;
        protocol?: string;
        error?: string;
      }>;
    };
  }
}
