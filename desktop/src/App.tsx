import {
  FormEvent,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState
} from "react";

import { ContextPanel } from "./components/ContextPanel";
import { AutonomousTaskPanel } from "./components/AutonomousTaskPanel";
import { TaskSnapshot } from "./lib/autonomousTask";
import { PlanPanel } from "./components/PlanPanel";
import { ExecutionSummary, TurnTrace } from "./components/ExecutionSummary";
import { MessageContent } from "./components/MessageContent";
import { DiagnosticsPanel } from "./components/DiagnosticsPanel";
import { GitPanel } from "./components/GitPanel";
import { SettingsPanel } from "./components/SettingsPanel";
import {
  DiffFile,
  DiffReviewMeta,
  ToolCard,
  ToolView
} from "./components/ToolCard";
import { appendOrderedToolChunk } from "./lib/toolStream";
import { shouldSubmitComposer } from "./lib/composer";
import { AgentState, formatAgentStatus } from "./lib/status";

type Status = {
  state: AgentState;
  host?: string;
  port?: number;
  version?: string;
  protocol?: string;
  error?: string;
};

type ModelInfo = {
  name: string;
  size?: number | null;
  family?: string | null;
  parameter_size?: string | null;
  quantization_level?: string | null;
};

type ProviderStatus = {
  provider: string;
  online: boolean;
  base_url: string;
  models: ModelInfo[];
  default_model?: string | null;
  preferred_model?: string | null;
  context_window: number;
  error?: { code?: string; message?: string } | null;
};

type PermissionMode = "read_only" | "workspace" | "full_access";

type ContextUsage = {
  context_window_tokens: number;
  reserved_output_tokens: number;
  input_budget_tokens: number;
  estimated_input_tokens: number;
  history_messages_total: number;
  history_messages_included: number;
  omitted_history_messages: number;
  runtime_messages_omitted: number;
  truncated_messages: number;
  context_sources?: Record<string, number>;
  utilization: number;
};

type ApprovalRequest = {
  id: string;
  turnId: string;
  tool: string;
  arguments: Record<string, unknown>;
  reason: string;
  risk: string;
};

type ProjectInfo = {
  id: string;
  path: string;
  name: string;
  tools: string[];
  thread_count: number;
  created_at?: string;
  updated_at?: string;
  active?: boolean;
  threads?: ThreadRecord[];
};

type ThreadRecord = {
  id: string;
  title: string;
  active_model?: string | null;
  created_at: string;
  updated_at: string;
};

type ChatItem = {
  id: string;
  role: "user" | "agent" | "system" | "tool";
  text: string;
  tool?: ToolView;
  trace?: TurnTrace;
};

type StoredMessage = {
  role: "user" | "assistant";
  content: string;
};

type ProjectSessionPayload = {
  project: ProjectInfo;
  threads: ThreadRecord[];
  activeThread: ThreadRecord | null;
  messages: StoredMessage[];
};

const initialStatus: Status = { state: "starting" };

function readThread(event: AgentEnvelope): ThreadRecord | null {
  const value = event.payload?.thread;
  if (!value || typeof value !== "object") {
    return null;
  }
  return value as ThreadRecord;
}

function readProvider(event: AgentEnvelope): ProviderStatus | null {
  const payload = event.payload;
  if (!payload || typeof payload.provider !== "string") {
    return null;
  }
  return payload as unknown as ProviderStatus;
}

function readPermission(event: AgentEnvelope): PermissionMode | null {
  const mode = event.payload?.mode;
  return mode === "read_only" || mode === "workspace" || mode === "full_access"
    ? mode
    : null;
}

function readProjectList(event: AgentEnvelope): ProjectInfo[] {
  const value = event.payload?.projects;
  return Array.isArray(value) ? [...(value as ProjectInfo[])].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }) || a.id.localeCompare(b.id)) : [];
}

function readProjectSession(event: AgentEnvelope): ProjectSessionPayload | null {
  const project = event.payload?.project;
  if (!project || typeof project !== "object") {
    return null;
  }

  const rawThreads = event.payload?.threads;
  const activeThread = event.payload?.active_thread;
  const rawMessages = event.payload?.messages;

  return {
    project: project as ProjectInfo,
    threads: Array.isArray(rawThreads) ? (rawThreads as ThreadRecord[]) : [],
    activeThread:
      activeThread && typeof activeThread === "object"
        ? (activeThread as ThreadRecord)
        : null,
    messages: Array.isArray(rawMessages)
      ? (rawMessages as StoredMessage[])
      : []
  };
}

function historyItems(
  projectId: string,
  threadId: string,
  messages: StoredMessage[]
): ChatItem[] {
  return messages.map((message, index) => ({
    id: "history:" + projectId + ":" + threadId + ":" + index,
    role: message.role === "assistant" ? "agent" : "user",
    text: message.content
  }));
}

function stringifyArguments(value: unknown): string {
  try {
    const text = JSON.stringify(value ?? {}, null, 0);
    return text.length > 500 ? text.slice(0, 500) + "…" : text;
  } catch {
    return String(value);
  }
}

function resultObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : {};
}

function App() {
  const [status, setStatus] = useState<Status>(initialStatus);
  const [provider, setProvider] = useState<ProviderStatus | null>(null);
  const [permissionMode, setPermissionMode] =
    useState<PermissionMode>("workspace");
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [renamingThread, setRenamingThread] = useState<{ projectId: string; thread: ThreadRecord } | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [expandedProjectIds, setExpandedProjectIds] = useState<string[]>(() => {
    try { const saved: unknown = JSON.parse(localStorage.getItem("lca-expanded-projects") ?? "[]");
      return Array.isArray(saved) ? saved.filter((id): id is string => typeof id === "string") : [];
    } catch { return []; }
  });
  const [theme, setTheme] = useState(() => localStorage.getItem("lca-theme") ?? "dark");
  const [projectThreadCache, setProjectThreadCache] = useState<Record<string, ThreadRecord[]>>({});
  const [workspace, setWorkspace] = useState<ProjectInfo | null>(null);
  const [selectedModel, setSelectedModel] = useState("");
  const [threads, setThreads] = useState<ThreadRecord[]>([]);
  const [activeThread, setActiveThread] = useState<ThreadRecord | null>(null);
  const [items, setItems] = useState<ChatItem[]>([]);
  const [input, setInput] = useState("");
  const [runningTurnId, setRunningTurnId] = useState<string | null>(null);
  const [uiError, setUiError] = useState<string | null>(null);
  const [showJumpToBottom, setShowJumpToBottom] = useState(false);
  const [contextUsage, setContextUsage] = useState<ContextUsage | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const [contextOpen, setContextOpen] = useState(false);
  const [gitOpen, setGitOpen] = useState(false);
  const [planOpen, setPlanOpen] = useState(false);
  const [taskOpen, setTaskOpen] = useState(false);
  const conversationRef = useRef<HTMLElement | null>(null);
  const autoFollowRef = useRef(true);
  const navigationInitializedRef = useRef(localStorage.getItem("lca-expanded-projects") !== null);
  const sendingRef = useRef(false);

  useEffect(() => { localStorage.setItem("lca-expanded-projects", JSON.stringify(expandedProjectIds)); }, [expandedProjectIds]);
  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem("lca-theme", theme); }, [theme]);
  useEffect(() => {
    setProjectThreadCache(cache => ({ ...cache, ...Object.fromEntries(projects
      .filter(project => project.threads).map(project => [project.id, project.threads!])) }));
  }, [projects]);
  useEffect(() => {
    if (workspace) setProjectThreadCache(cache => ({...cache, [workspace.id]: threads}));
  }, [workspace?.id, threads]);

  const scrollConversationToBottom = useCallback(
    (smooth = false) => {
      const element = conversationRef.current;
      autoFollowRef.current = true;
      setShowJumpToBottom(false);
      if (!element) {
        return;
      }
      element.scrollTo({
        top: element.scrollHeight,
        behavior: smooth ? "smooth" : "auto"
      });
    },
    []
  );

  const handleConversationScroll = useCallback(() => {
    const element = conversationRef.current;
    if (!element) {
      return;
    }
    const distance =
      element.scrollHeight - element.scrollTop - element.clientHeight;
    const nearBottom = distance <= 72;
    autoFollowRef.current = nearBottom;
    setShowJumpToBottom(!nearBottom);
  }, []);

  const applyProjectSession = useCallback((event: AgentEnvelope) => {
    const session = readProjectSession(event);
    if (!session) {
      return;
    }

    const activeProject = { ...session.project, active: true };
    setWorkspace(activeProject);
    setThreads(session.threads);
    setProjectThreadCache((cache) => ({ ...cache, [activeProject.id]: session.threads }));
    if (!navigationInitializedRef.current) {
      setExpandedProjectIds((ids) => ids.includes(activeProject.id) ? ids : [...ids, activeProject.id]);
      navigationInitializedRef.current = true;
    }
    setActiveThread(session.activeThread);
    setItems(
      session.activeThread
        ? historyItems(
            activeProject.id,
            session.activeThread.id,
            session.messages
          )
        : []
    );

    if (session.activeThread?.active_model) {
      setSelectedModel(session.activeThread.active_model);
    }

    setProjects((current) => {
      const next = current
        .filter((project) => project.id !== activeProject.id)
        .map((project) => ({ ...project, active: false }));
      return [...next, activeProject].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }) || a.id.localeCompare(b.id));
    });
  }, []);

  useEffect(() => {
    window.localAgent.notifyRendererReady();
  }, []);

  useLayoutEffect(() => {
    if (!autoFollowRef.current) {
      return;
    }
    const element = conversationRef.current;
    if (!element) {
      return;
    }
    element.scrollTop = element.scrollHeight;
    setShowJumpToBottom(false);
  }, [items, approvals]);

  useEffect(() => {
    autoFollowRef.current = true;
    const frame = window.requestAnimationFrame(() => {
      scrollConversationToBottom(false);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [workspace?.id, activeThread?.id, scrollConversationToBottom]);

  useEffect(() => {
    let active = true;

    const refresh = async () => {
      try {
        const next = await window.localAgent.getAgentStatus();
        if (active) {
          setStatus(next);
        }
      } catch (error) {
        if (active) {
          setStatus({ state: "error", error: String(error) });
        }
      }
    };

    void refresh();
    const timer = window.setInterval(() => void refresh(), 1000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    return window.localAgent.onAgentEvent((event) => {
      if (
        event.type === "project.opened" ||
        event.type === "project.selected"
      ) {
        applyProjectSession(event);
        return;
      }

      if (event.type === "thread.updated") {
        const thread = readThread(event);
        if (thread) {
          setThreads((current) => current.map((item) =>
            item.id === thread.id ? thread : item));
          setActiveThread((current) =>
            current?.id === thread.id ? thread : current);
        }
        return;
      }

      if (event.type === "thread.created") {
        const thread = readThread(event);
        if (thread) {
          setThreads((current) => [
            thread,
            ...current.filter((item) => item.id !== thread.id)
          ]);
          setActiveThread(thread);
          setSelectedModel(thread.active_model ?? "");
          setItems([]);
          setProjects((current) =>
            current.map((project) =>
              project.active
                ? { ...project, thread_count: project.thread_count + 1 }
                : project
            )
          );
        }
        return;
      }

      if (
        event.type === "permission.loaded" ||
        event.type === "permission.changed"
      ) {
        const mode = readPermission(event);
        if (mode) {
          setPermissionMode(mode);
        }
        return;
      }

      if (event.type === "approval.requested" && event.turn_id) {
        const approvalId = String(event.payload?.approval_id ?? "");
        if (!approvalId) {
          return;
        }
        setApprovals((current) => [
          ...current.filter((item) => item.id !== approvalId),
          {
            id: approvalId,
            turnId: event.turn_id ?? "",
            tool: String(event.payload?.tool ?? "tool"),
            arguments:
              event.payload?.arguments &&
              typeof event.payload.arguments === "object"
                ? (event.payload.arguments as Record<string, unknown>)
                : {},
            reason: String(event.payload?.reason ?? "Approval required."),
            risk: String(event.payload?.risk ?? "sensitive")
          }
        ]);
        return;
      }

      if (event.type === "approval.resolved") {
        const approvalId = String(event.payload?.approval_id ?? "");
        setApprovals((current) =>
          current.filter((item) => item.id !== approvalId)
        );
        return;
      }

      if (event.type === "model.selected") {
        const thread = readThread(event);
        if (thread) {
          setThreads((current) =>
            current.map((item) => (item.id === thread.id ? thread : item))
          );
          setActiveThread((current) =>
            current?.id === thread.id ? thread : current
          );
          setSelectedModel(thread.active_model ?? "");
        }
        return;
      }

      if (event.type === "turn.started" && event.turn_id) {
        setRunningTurnId(event.turn_id);
        setContextUsage(null);
        return;
      }

      if (event.type === "context.updated") {
        const payload = event.payload;
        if (
          payload &&
          typeof payload.estimated_input_tokens === "number" &&
          typeof payload.input_budget_tokens === "number"
        ) {
          setContextUsage(payload as unknown as ContextUsage);
        }
        return;
      }

      if (event.type === "turn.delta" && event.turn_id) {
        const delta = String(event.payload?.delta ?? "");
        setItems((current) => {
          const id = "agent:" + event.turn_id;
          const existing = current.find((item) => item.id === id);
          if (existing) {
            return current.map((item) =>
              item.id === id ? { ...item, text: item.text + delta } : item
            );
          }
          return [...current, { id, role: "agent", text: delta }];
        });
        return;
      }

      if (event.type === "tool.requested" && event.turn_id) {
        const callId = String(event.payload?.tool_call_id ?? "");
        const name = String(event.payload?.name ?? "tool");
        const rawArguments = event.payload?.arguments;
        const args =
          rawArguments && typeof rawArguments === "object"
            ? (rawArguments as Record<string, unknown>)
            : {};

        setItems((current) => [
          ...current,
          {
            id: "tool:" + callId,
            role: "tool",
            text: "",
            tool: {
              id: callId,
              name,
              arguments: args,
              status: "requested",
              chunks: [],
              command:
                name === "run_command"
                  ? String(args.command ?? "")
                  : undefined,
              cwd:
                name === "run_command"
                  ? String(args.cwd ?? ".")
                  : undefined
            }
          }
        ]);
        return;
      }

      if (event.type === "tool.started") {
        const callId = String(event.payload?.tool_call_id ?? "");
        setItems((current) =>
          current.map((item) =>
            item.id === "tool:" + callId && item.tool
              ? {
                  ...item,
                  tool: {
                    ...item.tool,
                    status: "running"
                  }
                }
              : item
          )
        );
        return;
      }

      if (event.type === "tool.output") {
        const callId = String(event.payload?.tool_call_id ?? "");
        const stream = String(event.payload?.stream ?? "");
        const eventName = String(event.payload?.event ?? "");

        setItems((current) =>
          current.map((item) => {
            if (item.id !== "tool:" + callId || !item.tool) {
              return item;
            }

            const sequenceValue = event.payload?.sequence;
            const sequence =
              typeof sequenceValue === "number"
                ? sequenceValue
                : (item.tool.lastSequence ?? 0) + 1;

            if (stream === "meta") {
              const pidValue = event.payload?.pid;
              const exitValue = event.payload?.exit_code;
              const durationValue = event.payload?.duration_ms;
              const reason =
                typeof event.payload?.reason === "string"
                  ? event.payload.reason
                  : undefined;
              const method =
                typeof event.payload?.method === "string"
                  ? event.payload.method
                  : undefined;

              let nextStatus = item.tool.status;
              if (eventName === "process_started") {
                nextStatus = "running";
              } else if (eventName === "process_terminating") {
                nextStatus = "stopping";
              } else if (eventName === "process_terminated") {
                nextStatus =
                  reason === "timeout" ? "timed_out" : "cancelled";
              } else if (eventName === "process_exited") {
                nextStatus =
                  Number(exitValue ?? 0) === 0 ? "completed" : "failed";
              }

              return {
                ...item,
                tool: {
                  ...item.tool,
                  status: nextStatus,
                  pid:
                    typeof pidValue === "number"
                      ? pidValue
                      : item.tool.pid,
                  cwd:
                    typeof event.payload?.cwd === "string"
                      ? event.payload.cwd
                      : item.tool.cwd,
                  command:
                    typeof event.payload?.command === "string"
                      ? event.payload.command
                      : item.tool.command,
                  exitCode:
                    typeof exitValue === "number"
                      ? exitValue
                      : item.tool.exitCode,
                  durationMs:
                    typeof durationValue === "number"
                      ? durationValue
                      : item.tool.durationMs,
                  streamTruncated:
                    eventName === "stream_truncated"
                      ? true
                      : item.tool.streamTruncated,
                  terminationReason:
                    reason ?? item.tool.terminationReason,
                  terminationMethod:
                    method ?? item.tool.terminationMethod,
                  lastSequence: Math.max(
                    item.tool.lastSequence ?? 0,
                    sequence
                  )
                }
              };
            }

            const output = String(event.payload?.text ?? "");
            if (!output || (stream !== "stdout" && stream !== "stderr")) {
              return item;
            }

            const merged = appendOrderedToolChunk(
              item.tool.chunks,
              {
                stream,
                text: output,
                sequence
              }
            );

            return {
              ...item,
              tool: {
                ...item.tool,
                chunks: merged.chunks,
                droppedOutputChars:
                  (item.tool.droppedOutputChars ?? 0) +
                  merged.droppedChars,
                streamTruncated:
                  item.tool.streamTruncated || merged.droppedChars > 0,
                lastSequence: Math.max(
                  item.tool.lastSequence ?? 0,
                  sequence
                )
              }
            };
          })
        );
        return;
      }

      if (event.type === "tool.completed") {
        const callId = String(event.payload?.tool_call_id ?? "");
        const rawResult = resultObject(event.payload?.result);
        const summary = String(rawResult.summary ?? "");
        const ok = Boolean(rawResult.ok);
        const data = resultObject(rawResult.data);
        const stdout = String(rawResult.stdout ?? "");
        const stderr = String(rawResult.stderr ?? "");
        const rawFiles = data.files;
        const diffFiles = Array.isArray(rawFiles)
          ? (rawFiles as DiffFile[])
          : undefined;
        const rawReview = data.review;
        const diffReview =
          rawReview && typeof rawReview === "object"
            ? (rawReview as DiffReviewMeta)
            : undefined;

        setItems((current) =>
          current.map((item) => {
            if (item.id !== "tool:" + callId || !item.tool) {
              return item;
            }

            let chunks = item.tool.chunks;
            let droppedOutputChars = item.tool.droppedOutputChars ?? 0;
            let lastSequence = item.tool.lastSequence ?? 0;

            if (chunks.length === 0) {
              if (stdout) {
                lastSequence += 1;
                const merged = appendOrderedToolChunk(chunks, {
                  stream: "stdout",
                  text: stdout,
                  sequence: lastSequence
                });
                chunks = merged.chunks;
                droppedOutputChars += merged.droppedChars;
              }
              if (stderr) {
                lastSequence += 1;
                const merged = appendOrderedToolChunk(chunks, {
                  stream: "stderr",
                  text: stderr,
                  sequence: lastSequence
                });
                chunks = merged.chunks;
                droppedOutputChars += merged.droppedChars;
              }
            }

            const rawError = resultObject(rawResult.error);
            const errorCode = String(rawError.code ?? "");
            const streamData = resultObject(data.stream);
            const timedOut = errorCode === "COMMAND_TIMEOUT";

            return {
              ...item,
              tool: {
                ...item.tool,
                status: timedOut
                  ? "timed_out"
                  : ok
                    ? "completed"
                    : "failed",
                summary,
                chunks,
                exitCode:
                  typeof rawResult.exit_code === "number"
                    ? rawResult.exit_code
                    : item.tool.exitCode,
                durationMs:
                  typeof rawResult.duration_ms === "number"
                    ? rawResult.duration_ms
                    : item.tool.durationMs,
                cwd:
                  typeof data.cwd === "string"
                    ? data.cwd
                    : item.tool.cwd,
                command:
                  typeof data.command === "string"
                    ? data.command
                    : item.tool.command,
                pid:
                  typeof data.pid === "number"
                    ? data.pid
                    : item.tool.pid,
                diffFiles,
                diffReview,
                additions:
                  typeof data.additions === "number"
                    ? data.additions
                    : undefined,
                deletions:
                  typeof data.deletions === "number"
                    ? data.deletions
                    : undefined,
                droppedOutputChars,
                streamTruncated:
                  item.tool.streamTruncated ||
                  droppedOutputChars > 0 ||
                  streamData.truncated === true,
                lastSequence
              }
            };
          })
        );
        return;
      }

      if (event.type === "file.changed" && event.turn_id) {
        const path = String(event.payload?.path ?? "");
        setItems((current) => [
          ...current,
          {
            id: "changed:" + event.turn_id + ":" + path + ":" + Date.now(),
            role: "system",
            text: "Changed file: " + path
          }
        ]);
        return;
      }

      if (event.type === "task.updated") {
        const task = event.payload?.task as TaskSnapshot | undefined;
        if (task) setItems(current => [...current.filter(item => item.id !== "task:" + task.id), {
          id:"task:" + task.id, role:"system", text:`Task · ${task.status} · API ${task.usage.api_calls} · Tokens reserved ${task.usage.reserved_tokens} · ${task.reason}`
        }]);
        return;
      }

      if (event.type === "turn.status" && event.turn_id) {
        const message = String(event.payload?.message ?? "Agent is working…");
        const id = "status:" + event.turn_id;
        setItems((current) => {
          const existing = current.find((item) => item.id === id);
          if (existing) {
            return current.map((item) =>
              item.id === id ? { ...item, text: message } : item
            );
          }
          return [...current, { id, role: "system", text: message }];
        });
        return;
      }

      if (event.type === "turn.metrics" && event.turn_id) {
        setItems(current => [...current.filter(item => item.id !== "metrics:" + event.turn_id),
          {id: "metrics:" + event.turn_id, role: "system", text: "", trace: event.payload as TurnTrace}]);
        return;
      }
      if (event.type === "turn.completed" && event.turn_id) {
        setApprovals((current) =>
          current.filter((item) => item.turnId !== event.turn_id)
        );
        setRunningTurnId((current) =>
          current === event.turn_id ? null : current
        );

        const verification = event.payload?.verification;
        if (
          verification &&
          typeof verification === "object" &&
          "complete" in verification &&
          !(verification as { complete?: boolean }).complete
        ) {
          const missingValue = (verification as { missing?: unknown }).missing;
          const missing = Array.isArray(missingValue)
            ? missingValue.map(String)
            : [];
          setItems((current) => [
            ...current,
            {
              id: "verification:" + event.turn_id,
              role: "system",
              text:
                "Verification incomplete: " +
                (missing.length ? missing.join(", ") : "unknown checks")
            }
          ]);
        }
        return;
      }

      if (event.type === "turn.cancelled" && event.turn_id) {
        setApprovals((current) =>
          current.filter((item) => item.turnId !== event.turn_id)
        );
        setRunningTurnId((current) =>
          current === event.turn_id ? null : current
        );
        setItems((current) => [
          ...current,
          {
            id: "system:" + event.turn_id,
            role: "system",
            text: "Turn cancelled."
          }
        ]);
        return;
      }

      if (event.type === "turn.failed" && event.turn_id) {
        setApprovals((current) =>
          current.filter((item) => item.turnId !== event.turn_id)
        );
        const message = String(event.payload?.message ?? "Agent turn failed.");
        setRunningTurnId((current) =>
          current === event.turn_id ? null : current
        );
        setUiError(message);
        setItems((current) => [
          ...current,
          {
            id: "system:" + event.turn_id,
            role: "system",
            text: "Turn failed: " + message
          }
        ]);
        return;
      }

      if (event.type === "error") {
        setUiError(String(event.payload?.message ?? "Agent error"));
      }
    });
  }, [applyProjectSession]);

  useEffect(() => {
    if (status.state !== "ready") {
      return;
    }

    const load = async () => {
      try {
        const [projectEvent, projectListEvent, modelEvent, permissionEvent] =
          await Promise.all([
            window.localAgent.getProject(),
            window.localAgent.listProjects(),
            window.localAgent.listModels(),
            window.localAgent.getPermission()
          ]);

        setProjects(readProjectList(projectListEvent));
        applyProjectSession(projectEvent);
        const loadedPermission = readPermission(permissionEvent);
        if (loadedPermission) {
          setPermissionMode(loadedPermission);
        }

        const providerStatus = readProvider(modelEvent);
        if (providerStatus) {
          setProvider(providerStatus);
          const modelNames = providerStatus.models.map((item) => item.name);
          setSelectedModel((current) => {
            if (current && modelNames.includes(current)) {
              return current;
            }
            return providerStatus.default_model ?? modelNames[0] ?? "";
          });
        }
      } catch (error) {
        setUiError(String(error));
      }
    };

    void load();
  }, [status.state, applyProjectSession]);

  const detail = useMemo(() => {
    if (status.state === "ready") {
      const endpoint =
        status.host && status.port
          ? status.host + ":" + status.port
          : "local process";
      return "Local runtime · " + endpoint;
    }
    return status.error ?? "Waiting for the local Agent process…";
  }, [status]);

  const contextLabel = useMemo(() => {
    if (!provider?.context_window) {
      return "";
    }
    const windowLabel = Math.round(provider.context_window / 1024) + "K";
    if (!contextUsage) {
      return windowLabel;
    }
    const used = Math.max(contextUsage.estimated_input_tokens, 0);
    const usedLabel =
      used >= 1024
        ? (used / 1024).toFixed(1) + "K"
        : String(used);
    return usedLabel + " / " + windowLabel;
  }, [provider, contextUsage]);

  const providerReady = Boolean(provider?.online && selectedModel);

  const openProject = async () => {
    if (runningTurnId) {
      return;
    }
    setUiError(null);
    try {
      const result = await window.localAgent.openProject(
        selectedModel || undefined
      );
      if (result.canceled || !result.event) {
        return;
      }
      applyProjectSession(result.event);
      const openedId = readProjectSession(result.event)?.project.id;
      if (openedId) setExpandedProjectIds(ids => ids.includes(openedId) ? ids : [...ids, openedId]);

      const listEvent = await window.localAgent.listProjects();
      setProjects(readProjectList(listEvent));
    } catch (error) {
      setUiError(String(error));
    }
  };

  const toggleProject = (project: ProjectInfo) => {
    const isExpanded = expandedProjectIds.includes(project.id);
    setExpandedProjectIds((ids) => isExpanded
      ? ids.filter((id) => id !== project.id)
      : [...ids, project.id]);
    if (!isExpanded && workspace?.id !== project.id) {
      void selectProject(project);
    }
  };

  const selectProject = async (project: ProjectInfo) => {
    if (runningTurnId || project.id === workspace?.id) {
      return;
    }

    setUiError(null);
    try {
      const event = await window.localAgent.selectProject(
        project.id,
        selectedModel || undefined
      );
      applyProjectSession(event);

      const listEvent = await window.localAgent.listProjects();
      setProjects(readProjectList(listEvent));
    } catch (error) {
      setUiError(String(error));
    }
  };

  const refreshModels = async () => {
    setUiError(null);
    try {
      const event = await window.localAgent.listModels();
      const next = readProvider(event);
      if (!next) {
        return;
      }
      setProvider(next);
      const names = next.models.map((item) => item.name);
      setSelectedModel((current) => {
        if (current && names.includes(current)) {
          return current;
        }
        return next.default_model ?? names[0] ?? "";
      });
    } catch (error) {
      setUiError(String(error));
    }
  };

  const createThread = async () => {
    setUiError(null);
    try {
      await window.localAgent.createThread(selectedModel || undefined);
    } catch (error) {
      setUiError(String(error));
    }
  };

  const loadThread = async (thread: ThreadRecord) => {
    if (runningTurnId || !workspace) {
      return;
    }

    setUiError(null);
    try {
      const event = await window.localAgent.getThread(thread.id);
      const loadedThread = readThread(event) ?? thread;
      const rawMessages = event.payload?.messages;
      const messages = Array.isArray(rawMessages)
        ? (rawMessages as StoredMessage[])
        : [];

      setActiveThread(loadedThread);
      setSelectedModel(
        loadedThread.active_model ?? provider?.default_model ?? ""
      );
      setItems(historyItems(workspace.id, loadedThread.id, messages));
    } catch (error) {
      setUiError(String(error));
    }
  };

  const openProjectThread = async (project: ProjectInfo, thread: ThreadRecord) => {
    if (runningTurnId) return;
    try {
      if (workspace?.id !== project.id) {
        const selected = await window.localAgent.selectProject(project.id);
        applyProjectSession(selected);
      }
      const event = await window.localAgent.getThread(thread.id);
      const loaded = readThread(event) ?? thread;
      setActiveThread(loaded);
      setSelectedModel(loaded.active_model ?? provider?.default_model ?? "");
      setItems(historyItems(project.id, loaded.id, (event.payload?.messages ?? []) as StoredMessage[]));
      setContextUsage(null);
    } catch (error) { setUiError(String(error)); }
  };

  const commitThreadRename = async () => {
    if (!renamingThread) return;
    const title = renameValue.trim();
    const target = renamingThread;
    setRenamingThread(null);
    if (!title || title === target.thread.title) return;
    try {
      if (workspace?.id !== target.projectId) {
        const selected = await window.localAgent.selectProject(target.projectId);
        applyProjectSession(selected);
      }
      const event = await window.localAgent.renameThread(target.thread.id, title);
      const updated = readThread(event);
      if (!updated) return;
      setThreads((items) => items.map((item) => item.id === updated.id ? updated : item));
      setProjectThreadCache((cache) => ({
        ...cache,
        [target.projectId]: (cache[target.projectId] ?? []).map((item) =>
          item.id === updated.id ? updated : item)
      }));
      setActiveThread((item) => item?.id === updated.id ? updated : item);
    } catch (error) {
      setUiError(String(error));
    }
  };

  const changePermission = async (mode: PermissionMode) => {
    setUiError(null);
    try {
      const event = await window.localAgent.setPermission(mode);
      const next = readPermission(event);
      if (next) {
        setPermissionMode(next);
      }
    } catch (error) {
      setUiError(String(error));
    }
  };

  const respondApproval = async (
    approval: ApprovalRequest,
    decision: "allow_once" | "allow_turn" | "deny"
  ) => {
    setUiError(null);
    try {
      await window.localAgent.respondApproval(
        approval.id,
        decision,
        approval.turnId
      );
      setApprovals((current) =>
        current.filter((item) => item.id !== approval.id)
      );
    } catch (error) {
      setUiError(String(error));
    }
  };

  const changeModel = async (model: string) => {
    setSelectedModel(model);
    setUiError(null);
    if (!activeThread) {
      return;
    }
    try {
      await window.localAgent.selectModel(activeThread.id, model);
    } catch (error) {
      setUiError(String(error));
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const prompt = input.trim();
    if (
      !workspace ||
      !activeThread ||
      !prompt ||
      runningTurnId ||
      !providerReady
      || sendingRef.current
    ) {
      return;
    }

    setUiError(null);
    sendingRef.current = true;
    const userItemId = "user:" + Date.now();
    autoFollowRef.current = true;
    setShowJumpToBottom(false);
    setItems((current) => [
      ...current,
      {
        id: userItemId,
        role: "user",
        text: prompt
      }
    ]);

    try {
      const started = await window.localAgent.startTurn(
        activeThread.id,
        prompt
      );
      if (started.turn_id) {
        setRunningTurnId(started.turn_id);
      }
      setInput(current => current.trim() === prompt ? "" : current);
    } catch (error) {
      setUiError(String(error));
      setRunningTurnId(null);
      setItems(current => current.filter(item => item.id !== userItemId));
    } finally {
      sendingRef.current = false;
    }
  };

  const stop = async () => {
    if (!runningTurnId) {
      return;
    }
    try {
      await window.localAgent.cancelTurn(runningTurnId);
    } catch (error) {
      setUiError(String(error));
    }
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">LC</span>
          <span className="brand-copy">
            <strong>Local Coding Agent</strong>
            <small>Local-first coding workspace</small>
          </span>
        </div>

        <div className="sidebar-actions">
          <button
            className="open-project"
            disabled={status.state !== "ready" || Boolean(runningTurnId)}
            onClick={() => void openProject()}
          >
            <span aria-hidden="true">＋</span>
            Open project
          </button>

          <button
            className="new-thread"
            disabled={
              status.state !== "ready" ||
              !providerReady ||
              !workspace ||
              Boolean(runningTurnId)
            }
            onClick={() => void createThread()}
          >
            <span aria-hidden="true">＋</span>
            New thread
          </button>
        </div>

        <div className="sidebar-scroll">
          <div className="section-label">PROJECTS</div>
          <div className="project-tree">
            {projects.length === 0 ? (
              <div className="empty-list">No projects opened</div>
            ) : projects.map((project) => (
              <div className="project-group" key={project.id}>
                <button className={"project-tree-header " + (workspace?.id === project.id ? "active" : "")}
                  disabled={Boolean(runningTurnId)} title={project.path}
                  aria-expanded={expandedProjectIds.includes(project.id)}
                  onClick={() => toggleProject(project)}>
                  <span className="project-tree-folder" aria-hidden="true">📁</span>
                  <span className="project-tree-name">{project.name}</span>
                  <span className="project-tree-count">{project.thread_count}</span>
                  <span className="project-tree-chevron" aria-hidden="true">{expandedProjectIds.includes(project.id) ? "⌄" : "›"}</span>
                </button>
                {expandedProjectIds.includes(project.id) && (
                  <div className="project-tree-threads">
                    {(workspace?.id === project.id ? threads : (projectThreadCache[project.id] ?? [])).length === 0 ? (
                      <div className="empty-list">No threads loaded</div>
                    ) : (workspace?.id === project.id ? threads : (projectThreadCache[project.id] ?? [])).map((thread) => (
                      <button key={thread.id}
                        className={"thread-item project-tree-thread " + (workspace?.id === project.id && activeThread?.id === thread.id ? "active" : "")}
                        disabled={Boolean(runningTurnId)} title={thread.title}
                        onContextMenu={(event) => {
                          event.preventDefault();
                          setRenamingThread({ projectId: project.id, thread });
                          setRenameValue(thread.title);
                        }}
                        onClick={() => {
                          void openProjectThread(project, thread);
                        }}>
                        <span className="project-tree-thread-icon" aria-hidden="true">◦</span>
                        <span className="project-tree-thread-name">{thread.title}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {renamingThread && (
          <div className="thread-rename-dialog" role="dialog" aria-label="Rename thread">
            <label htmlFor="thread-rename-input">Rename thread</label>
            <input id="thread-rename-input" autoFocus maxLength={120}
              value={renameValue} onChange={(event) => setRenameValue(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void commitThreadRename();
                if (event.key === "Escape") setRenamingThread(null);
              }} />
            <div className="thread-rename-actions">
              <button onClick={() => setRenamingThread(null)}>Cancel</button>
              <button disabled={!renameValue.trim()} onClick={() => void commitThreadRename()}>Save</button>
            </div>
          </div>
        )}
        <div className="sidebar-footer">
          <div className={"status-dot status-" + status.state} />
          <div>
            <div className="status-title">
              {formatAgentStatus(status.state)}
            </div>
            <div className="status-detail">{detail}</div>
          </div>
        </div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div className="topbar-title">
            <strong>{workspace?.name ?? "No project open"}</strong>
            <span>
              {activeThread
                ? activeThread.title
                : workspace
                  ? "Create or select a thread"
                  : "Open a local workspace to begin"}
            </span>
          </div>
          <div className="topbar-actions">
            <button
              className={
                "provider-pill " +
                (provider?.online ? "provider-online" : "provider-offline")
              }
              onClick={() => void refreshModels()}
              title="Refresh provider status and models"
            >
              <span className="provider-status-dot" aria-hidden="true" />
              <span className="provider-name">
                {provider?.provider ?? "Provider"}
              </span>
              <span className="provider-model">
                {selectedModel || (provider?.online ? "No model" : "Offline")}
              </span>
            </button>
            <button
              type="button"
              className={"git-button" + (gitOpen ? " active" : "")}
              disabled={!workspace}
              onClick={() => {
                setGitOpen((current) => !current);
                setPlanOpen(false); setTaskOpen(false);
                setContextOpen(false);
                setDiagnosticsOpen(false);
                setSettingsOpen(false);
              }}
              title="Git workflow and worktrees"
            >
              Git
            </button>
            <button type="button" className={"context-button" + (taskOpen ? " active" : "")} disabled={!activeThread}
              onClick={() => {setTaskOpen(current => !current); setPlanOpen(false); setGitOpen(false); setContextOpen(false); setDiagnosticsOpen(false); setSettingsOpen(false);}}
              title="Local-first autonomous task">Task</button>
            <button type="button" className={"context-button" + (planOpen ? " active" : "")}
              disabled={!activeThread}
              onClick={() => { setPlanOpen((current) => !current); setTaskOpen(false); setGitOpen(false); setContextOpen(false); setDiagnosticsOpen(false); setSettingsOpen(false); }}
              title="Persistent task plans and checkpoints">Plan</button>
            <button
              type="button"
              className={"context-button" + (contextOpen ? " active" : "")}
              disabled={!activeThread}
              onClick={() => {
                setContextOpen((current) => !current);
                setPlanOpen(false); setTaskOpen(false);
                setGitOpen(false);
                setDiagnosticsOpen(false);
                setSettingsOpen(false);
              }}
              title="Repository and pinned context"
            >
              Context
            </button>
            <button
              type="button"
              className={
                "diagnostics-button" + (diagnosticsOpen ? " active" : "")
              }
              onClick={() => {
                setDiagnosticsOpen((current) => !current);
                setPlanOpen(false); setTaskOpen(false);
                setGitOpen(false);
                setSettingsOpen(false);
                setContextOpen(false);
              }}
              title="Diagnostics"
            >
              Diagnostics
            </button>
            <button
              type="button"
              className={"settings-button" + (settingsOpen ? " active" : "")}
              onClick={() => {
                setSettingsOpen((current) => !current);
                setPlanOpen(false); setTaskOpen(false);
                setGitOpen(false);
                setDiagnosticsOpen(false);
                setContextOpen(false);
              }}
              title="Settings"
            >
              Settings
            </button>
            <button type="button" className="theme-button" aria-label="Toggle color theme" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>{theme === "dark" ? "☀" : "☾"}</button>
          </div>
        </header>

        <div className={"conversation-shell" + (gitOpen || planOpen || taskOpen || contextOpen || diagnosticsOpen ? " with-panel" : "")}>
          <section
            ref={conversationRef}
            className="conversation"
            onScroll={handleConversationScroll}
          >
          {items.length === 0 && approvals.length === 0 ? (
            <div className="welcome-card">
              <div className="eyebrow">
                {workspace ? "WORKSPACE READY" : "LOCAL-FIRST CODING"}
              </div>
              <h1>
                {workspace
                  ? "What would you like to build?"
                  : "Open a project to start coding locally."}
              </h1>
              <p>
                {workspace
                  ? "Ask the Agent to inspect, change, run, test or review this workspace. Tool execution stays inside the selected permission mode."
                  : "Projects and threads stay local to this desktop. Open a workspace to inspect code, run tools and review changes with your selected model."}
              </p>

              {workspace ? (
                <div className="welcome-status-grid">
                  <div>
                    <span>Provider</span>
                    <strong>{provider?.provider ?? "—"}</strong>
                  </div>
                  <div>
                    <span>Model</span>
                    <strong>{selectedModel || "—"}</strong>
                  </div>
                  <div>
                    <span>Permission</span>
                    <strong>{permissionMode.replace("_", " ")}</strong>
                  </div>
                  <div>
                    <span>Context</span>
                    <strong>{contextLabel || "Ready"}</strong>
                  </div>
                </div>
              ) : (
                <div className="welcome-actions">
                  <button
                    type="button"
                    disabled={status.state !== "ready"}
                    onClick={() => void openProject()}
                  >
                    Open project
                  </button>
                </div>
              )}

              {!provider?.online ? (
                <div className="provider-warning">
                  <strong>Provider unavailable</strong>
                  <span>
                    {provider?.error?.message ??
                      "Check the Provider section in Settings, then refresh the provider status."}
                  </span>
                </div>
              ) : null}
            </div>
          ) : (
            <div className="message-list">
              {items.map((item) =>
                item.trace ? <ExecutionSummary key={item.id} trace={item.trace} /> : item.role === "tool" && item.tool ? (
                  <ToolCard key={item.id} tool={item.tool} />
                ) : (
                  <div key={item.id} className={"message " + item.role}>
                    <div className="message-role">{item.role}</div>
                    <MessageContent text={item.text} markdown={item.role === "agent"} />
                  </div>
                )
              )}
              {approvals.map((approval) => (
                <div key={approval.id} className="approval-card">
                  <div className="approval-header">
                    <strong>Approval required</strong>
                    <span>{approval.risk}</span>
                  </div>
                  <div className="approval-tool">{approval.tool}</div>
                  <pre>{stringifyArguments(approval.arguments)}</pre>
                  <p>{approval.reason}</p>
                  <div className="approval-actions">
                    <button
                      type="button"
                      onClick={() =>
                        void respondApproval(approval, "allow_once")
                      }
                    >
                      Allow once
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        void respondApproval(approval, "allow_turn")
                      }
                    >
                      Allow for this turn
                    </button>
                    <button
                      type="button"
                      className="deny-button"
                      onClick={() => void respondApproval(approval, "deny")}
                    >
                      Deny
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
          </section>
          {showJumpToBottom ? (
            <button
              type="button"
              className="jump-to-bottom"
              aria-label="Jump to latest"
              title="Jump to latest"
              onClick={() => scrollConversationToBottom(true)}
            >
              ↓
            </button>
          ) : null}

          {gitOpen && workspace ? (
            <GitPanel
              projectName={workspace.name}
              selectedModel={selectedModel}
              running={runningTurnId !== null}
              onProjectOpened={(event) => {
                applyProjectSession(event);
                void window.localAgent.listProjects().then((listed) => {
                  setProjects(readProjectList(listed));
                });
              }}
              onClose={() => setGitOpen(false)}
            />
          ) : null}

          {taskOpen && activeThread ? <AutonomousTaskPanel key={activeThread.id} threadId={activeThread.id} running={runningTurnId !== null}
            onClose={() => setTaskOpen(false)} onSettings={() => {setTaskOpen(false); setSettingsOpen(true);}} /> : null}
          {planOpen && activeThread ? (
            <PlanPanel threadId={activeThread.id} onClose={() => setPlanOpen(false)} />
          ) : null}
          {contextOpen && activeThread ? (
            <ContextPanel
              threadId={activeThread.id}
              projectName={workspace?.name}
              running={runningTurnId !== null}
              onClose={() => setContextOpen(false)}
            />
          ) : null}
          {diagnosticsOpen ? <DiagnosticsPanel onClose={() => setDiagnosticsOpen(false)} /> : null}
        </div>

        <form className="composer" onSubmit={submit}>
          {uiError ? <div className="error-banner">{uiError}</div> : null}
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (
                shouldSubmitComposer({
                  key: event.key,
                  shiftKey: event.shiftKey,
                  isComposing: event.nativeEvent.isComposing
                })
              ) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            disabled={
              !workspace ||
              !activeThread ||
              status.state !== "ready" ||
              !providerReady
            }
            placeholder={
              !workspace
                ? "Open a project first."
                : !provider?.online
                  ? "Provider is offline."
                  : "Ask the Agent to inspect, test or modify this project…"
            }
          />
          <div className="composer-row">
            <div className="model-controls">
              <select
                className={
                  "permission-select permission-" + permissionMode
                }
                value={permissionMode}
                disabled={runningTurnId !== null}
                onChange={(event) =>
                  void changePermission(
                    event.target.value as PermissionMode
                  )
                }
                title="Permission mode"
              >
                <option value="read_only">Read Only</option>
                <option value="workspace">Workspace</option>
                <option value="full_access">Full Access</option>
              </select>
              <select
                className="model-select"
                value={selectedModel}
                disabled={
                  !provider?.online ||
                  runningTurnId !== null ||
                  provider.models.length === 0
                }
                onChange={(event) => void changeModel(event.target.value)}
              >
                {provider?.models.length ? (
                  provider.models.map((model) => (
                    <option key={model.name} value={model.name}>
                      {model.name}
                    </option>
                  ))
                ) : (
                  <option value="">No models</option>
                )}
              </select>
              <span className="composer-hints">
                {contextLabel ? (
                  <span className="context-chip">
                    Context {contextLabel}
                  </span>
                ) : null}
                <span>@file adds one-turn context</span>
                <span>Enter to send</span>
                <span>Shift+Enter newline</span>
              </span>
            </div>
            {runningTurnId ? (
              <button
                type="button"
                className="stop-button"
                onClick={() => void stop()}
              >
                Stop
              </button>
            ) : (
              <button
                type="submit"
                className="send-button"
                disabled={
                  !workspace ||
                  !activeThread ||
                  !input.trim() ||
                  status.state !== "ready" ||
                  !providerReady
                }
              >
                Send
              </button>
            )}
          </div>
        </form>


        {settingsOpen ? (
          <SettingsPanel
            projectId={workspace?.id}
            threadId={activeThread?.id}
            permissionMode={permissionMode}
            running={runningTurnId !== null}
            onClose={() => setSettingsOpen(false)}
            onPermissionChanged={(mode) => setPermissionMode(mode)}
            onProviderChanged={(event) => {
              const next = readProvider(event);
              if (!next) {
                return;
              }
              setProvider(next);
              const names = next.models.map((item) => item.name);
              setSelectedModel((current) => {
                if (current && names.includes(current)) {
                  return current;
                }
                return next.default_model ?? names[0] ?? "";
              });
            }}
          />
        ) : null}
      </main>
    </div>
  );
}

export default App;
