export type AgentState = "starting" | "ready" | "error" | "stopped";

export function formatAgentStatus(state: AgentState): string {
  switch (state) {
    case "ready":
      return "Agent Connected";
    case "starting":
      return "Agent Starting";
    case "error":
      return "Agent Error";
    case "stopped":
      return "Agent Stopped";
  }
}
