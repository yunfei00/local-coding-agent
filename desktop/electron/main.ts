import { app, BrowserWindow, ipcMain } from "electron";
import { ChildProcessWithoutNullStreams, spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import path from "node:path";
import WebSocket from "ws";

type AgentStatus = {
  state: "starting" | "ready" | "error" | "stopped";
  host?: string;
  port?: number;
  version?: string;
  protocol?: string;
  error?: string;
};

type AgentEnvelope = {
  type: string;
  request_id?: string | null;
  thread_id?: string | null;
  turn_id?: string | null;
  timestamp?: string;
  payload?: Record<string, unknown>;
};

type PendingRequest = {
  expectedType: string;
  resolve: (value: AgentEnvelope) => void;
  reject: (error: Error) => void;
  timer: NodeJS.Timeout;
};

let mainWindow: BrowserWindow | null = null;
let agentProcess: ChildProcessWithoutNullStreams | null = null;
let agentSocket: WebSocket | null = null;
let agentToken: string | null = null;
let agentStatus: AgentStatus = { state: "starting" };
let stdoutBuffer = "";
let shuttingDown = false;
const pending = new Map<string, PendingRequest>();

function repoRoot(): string {
  return path.resolve(__dirname, "..", "..");
}

function broadcastAgentEvent(event: AgentEnvelope): void {
  for (const window of BrowserWindow.getAllWindows()) {
    window.webContents.send("agent:event", event);
  }
}

function rejectPending(reason: string): void {
  for (const [requestId, item] of pending) {
    clearTimeout(item.timer);
    item.reject(new Error(reason));
    pending.delete(requestId);
  }
}

function handleAgentMessage(raw: WebSocket.RawData): void {
  let event: AgentEnvelope;

  try {
    event = JSON.parse(raw.toString("utf8")) as AgentEnvelope;
  } catch (error) {
    console.error("[desktop] Invalid Agent WebSocket JSON", error);
    return;
  }

  broadcastAgentEvent(event);

  const requestId = event.request_id;
  if (!requestId) {
    return;
  }

  const item = pending.get(requestId);
  if (!item) {
    return;
  }

  if (event.type === "error") {
    clearTimeout(item.timer);
    pending.delete(requestId);
    item.reject(new Error(String(event.payload?.message ?? "Agent request failed")));
    return;
  }

  if (event.type === item.expectedType) {
    clearTimeout(item.timer);
    pending.delete(requestId);
    item.resolve(event);
  }
}

function connectAgentWebSocket(ready: {
  host: string;
  port: number;
  token: string;
  version: string;
  protocol: string;
}): void {
  agentSocket?.close();

  const socket = new WebSocket("ws://" + ready.host + ":" + ready.port + "/ws", {
    headers: {
      Authorization: "Bearer " + ready.token
    }
  });
  agentSocket = socket;

  socket.on("open", () => {
    agentStatus = {
      state: "ready",
      host: ready.host,
      port: ready.port,
      version: ready.version,
      protocol: ready.protocol
    };
    console.log("[desktop] Agent WebSocket connected");
  });

  socket.on("message", handleAgentMessage);

  socket.on("error", (error) => {
    console.error("[desktop] Agent WebSocket error", error);
    if (!shuttingDown) {
      agentStatus = {
        state: "error",
        host: ready.host,
        port: ready.port,
        version: ready.version,
        protocol: ready.protocol,
        error: String(error)
      };
    }
  });

  socket.on("close", () => {
    rejectPending("Agent WebSocket disconnected.");
    if (!shuttingDown && agentProcess) {
      agentStatus = {
        state: "error",
        host: ready.host,
        port: ready.port,
        version: ready.version,
        protocol: ready.protocol,
        error: "Agent WebSocket disconnected."
      };
    }
  });
}

function updateFromAgentStdout(chunk: Buffer): void {
  stdoutBuffer += chunk.toString("utf8");
  const lines = stdoutBuffer.split(/\r?\n/);
  stdoutBuffer = lines.pop() ?? "";

  for (const line of lines) {
    if (!line.startsWith("LCA_AGENT_READY ")) {
      if (line.trim()) {
        console.log("[agent]", line);
      }
      continue;
    }

    try {
      const ready = JSON.parse(line.slice("LCA_AGENT_READY ".length)) as {
        host: string;
        port: number;
        token: string;
        version: string;
        protocol: string;
      };
      agentToken = ready.token;
      agentStatus = {
        state: "starting",
        host: ready.host,
        port: ready.port,
        version: ready.version,
        protocol: ready.protocol
      };
      connectAgentWebSocket(ready);
    } catch (error) {
      agentStatus = {
        state: "error",
        error: "Invalid Agent ready payload: " + String(error)
      };
    }
  }
}

function launchAgent(command: string, argsPrefix: string[] = []): ChildProcessWithoutNullStreams {
  const child = spawn(
    command,
    [...argsPrefix, "-m", "agent.server.main", "--port", "0"],
    {
      cwd: repoRoot(),
      env: {
        ...process.env,
        PYTHONUNBUFFERED: "1"
      },
      windowsHide: true
    }
  );

  child.stdout.on("data", updateFromAgentStdout);
  child.stderr.on("data", (chunk: Buffer) => {
    console.error("[agent:stderr]", chunk.toString("utf8").trimEnd());
  });
  child.on("exit", (code, signal) => {
    agentProcess = null;
    agentToken = null;
    agentSocket = null;
    rejectPending("Agent process exited.");
    if (!shuttingDown) {
      agentStatus = {
        state: code === 0 ? "stopped" : "error",
        error: code === 0 ? undefined : "Agent exited with code=" + code + ", signal=" + signal
      };
    }
  });

  return child;
}

function startAgent(): void {
  agentStatus = { state: "starting" };

  const configuredPython = process.env.LCA_PYTHON;
  if (configuredPython) {
    agentProcess = launchAgent(configuredPython);
    agentProcess.once("error", (error) => {
      agentStatus = { state: "error", error: String(error) };
    });
    return;
  }

  const primary = process.platform === "win32" ? "python" : "python3";
  agentProcess = launchAgent(primary);
  agentProcess.once("error", (error) => {
    if (process.platform === "win32") {
      console.warn("[desktop] python was not available, trying py -3");
      agentProcess = launchAgent("py", ["-3"]);
      agentProcess.once("error", (fallbackError) => {
        agentStatus = { state: "error", error: String(fallbackError) };
      });
      return;
    }
    agentStatus = { state: "error", error: String(error) };
  });
}

function sendRequest(
  type: string,
  expectedType: string,
  payload: Record<string, unknown> = {},
  ids: { threadId?: string; turnId?: string } = {}
): Promise<AgentEnvelope> {
  const socket = agentSocket;
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    return Promise.reject(new Error("Agent WebSocket is not connected."));
  }

  const requestId = "req_" + randomUUID().replace(/-/g, "");
  const message: AgentEnvelope = {
    type,
    request_id: requestId,
    thread_id: ids.threadId,
    turn_id: ids.turnId,
    timestamp: new Date().toISOString(),
    payload
  };

  return new Promise<AgentEnvelope>((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(requestId);
      reject(new Error("Agent request timed out: " + type));
    }, 10000);

    pending.set(requestId, {
      expectedType,
      resolve,
      reject,
      timer
    });

    socket.send(JSON.stringify(message), (error) => {
      if (error) {
        clearTimeout(timer);
        pending.delete(requestId);
        reject(error);
      }
    });
  });
}

async function stopAgent(): Promise<void> {
  shuttingDown = true;
  rejectPending("Application is closing.");

  if (agentSocket) {
    agentSocket.close();
    agentSocket = null;
  }

  const current = agentProcess;
  if (!current) {
    return;
  }

  if (agentStatus.port && agentToken) {
    try {
      await fetch("http://127.0.0.1:" + agentStatus.port + "/shutdown", {
        method: "POST",
        headers: {
          Authorization: "Bearer " + agentToken
        }
      });
    } catch {
      // Best-effort graceful shutdown; force kill below if still alive.
    }
  }

  setTimeout(() => {
    if (agentProcess === current) {
      current.kill();
    }
  }, 700).unref();
}

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1180,
    height: 780,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: "#111111",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  const devUrl = process.env.VITE_DEV_SERVER_URL;
  if (devUrl) {
    void mainWindow.loadURL(devUrl);
  } else {
    void mainWindow.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  }
}

ipcMain.handle("agent:get-status", () => agentStatus);
ipcMain.handle("agent:thread-create", async (_event, title?: string) => {
  return sendRequest("thread.create", "thread.created", title ? { title } : {});
});
ipcMain.handle("agent:thread-list", async () => {
  return sendRequest("thread.list", "thread.listed");
});
ipcMain.handle("agent:turn-start", async (_event, threadId: string, prompt: string) => {
  return sendRequest(
    "turn.start",
    "turn.started",
    { prompt },
    { threadId }
  );
});
ipcMain.handle("agent:turn-cancel", async (_event, turnId: string) => {
  const socket = agentSocket;
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    throw new Error("Agent WebSocket is not connected.");
  }
  const message: AgentEnvelope = {
    type: "turn.cancel",
    request_id: "req_" + randomUUID().replace(/-/g, ""),
    turn_id: turnId,
    timestamp: new Date().toISOString(),
    payload: {}
  };
  socket.send(JSON.stringify(message));
  return { ok: true };
});

app.whenReady().then(() => {
  startAgent();
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("before-quit", () => {
  void stopAgent();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
