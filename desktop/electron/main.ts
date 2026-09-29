import { app, BrowserWindow, dialog, ipcMain } from "electron";
import { ChildProcessWithoutNullStreams, spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { appendFileSync, existsSync, mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import WebSocket from "ws";

const APP_ID = "com.yunfei.localcodingagent";
app.setAppUserModelId(APP_ID);

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
let quitInProgress = false;
let quitReady = false;
const pending = new Map<string, PendingRequest>();

function repoRoot(): string {
  return path.resolve(__dirname, "..", "..");
}

function projectPythonPath(): string {
  return process.platform === "win32"
    ? path.join(repoRoot(), ".venv", "Scripts", "python.exe")
    : path.join(repoRoot(), ".venv", "bin", "python");
}

function packagedAgentPath(): string {
  return path.join(
    process.resourcesPath,
    "agent",
    process.platform === "win32" ? "lca-agent.exe" : "lca-agent"
  );
}

function logDirectory(): string {
  return path.join(app.getPath("userData"), "logs");
}

function appendRuntimeLog(fileName: string, message: string): void {
  try {
    const directory = logDirectory();
    mkdirSync(directory, { recursive: true });
    appendFileSync(
      path.join(directory, fileName),
      new Date().toISOString() + " " + message + "\n",
      "utf8"
    );
  } catch (error) {
    console.error("[desktop] Unable to write runtime log", error);
  }
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

    const smokeFile = process.env.LCA_PACKAGED_SMOKE_FILE;
    if (smokeFile) {
      try {
        writeFileSync(
          smokeFile,
          JSON.stringify(
            {
              ok: true,
              version: ready.version,
              protocol: ready.protocol,
              host: ready.host,
              port: ready.port,
              packaged: app.isPackaged
            },
            null,
            2
          ),
          "utf8"
        );
        appendRuntimeLog("desktop.log", "Packaged smoke marker written: " + smokeFile);
        setTimeout(() => app.quit(), 250);
      } catch (error) {
        appendRuntimeLog(
          "desktop.log",
          "Unable to write packaged smoke marker: " + String(error)
        );
      }
    }
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
        appendRuntimeLog("agent.log", "[stdout] " + line);
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
      appendRuntimeLog(
        "desktop.log",
        "Agent ready on " + ready.host + ":" + ready.port + " protocol=" + ready.protocol
      );
      connectAgentWebSocket(ready);
    } catch (error) {
      agentStatus = {
        state: "error",
        error: "Invalid Agent ready payload: " + String(error)
      };
    }
  }
}

function launchAgent(
  command: string,
  args: string[],
  cwd: string,
  virtualEnv?: string
): ChildProcessWithoutNullStreams {
  const environment: NodeJS.ProcessEnv = {
    ...process.env,
    PYTHONUNBUFFERED: "1",
    LCA_DATA_DIR: app.getPath("userData")
  };
  if (virtualEnv) {
    environment.VIRTUAL_ENV = virtualEnv;
  }

  appendRuntimeLog(
    "desktop.log",
    "Launching Agent command=" + command + " cwd=" + cwd
  );

  const child = spawn(
    command,
    args,
    {
      cwd,
      env: environment,
      windowsHide: true
    }
  );

  child.stdout.on("data", updateFromAgentStdout);
  child.stderr.on("data", (chunk: Buffer) => {
    const message = chunk.toString("utf8").trimEnd();
    console.error("[agent:stderr]", message);
    if (message) {
      appendRuntimeLog("agent.log", "[stderr] " + message);
    }
  });
  child.on("exit", (code, signal) => {
    agentProcess = null;
    agentToken = null;
    agentSocket = null;
    rejectPending("Agent process exited.");
    appendRuntimeLog(
      "desktop.log",
      "Agent exited code=" + code + " signal=" + signal
    );
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

  const configuredAgent = process.env.LCA_AGENT_EXECUTABLE;
  if (configuredAgent) {
    if (!existsSync(configuredAgent)) {
      agentStatus = {
        state: "error",
        error: "Configured Agent executable was not found: " + configuredAgent
      };
      return;
    }
    agentProcess = launchAgent(
      configuredAgent,
      ["--port", "0"],
      path.dirname(configuredAgent)
    );
  } else if (app.isPackaged) {
    const bundledAgent = packagedAgentPath();
    if (!existsSync(bundledAgent)) {
      const message = "Bundled Agent executable is missing: " + bundledAgent;
      agentStatus = {
        state: "error",
        error: message
      };
      appendRuntimeLog("desktop.log", message);
      return;
    }
    agentProcess = launchAgent(
      bundledAgent,
      ["--port", "0"],
      path.dirname(bundledAgent)
    );
  } else {
    const configuredPython = process.env.LCA_PYTHON;
    const python = configuredPython || projectPythonPath();

    if (!configuredPython && !existsSync(python)) {
      agentStatus = {
        state: "error",
        error: "Project .venv is missing. Run .\\scripts\\dev\\bootstrap.ps1 first."
      };
      return;
    }

    console.log("[desktop] Agent Python: " + python);
    agentProcess = launchAgent(
      python,
      ["-m", "agent.server.main", "--port", "0"],
      repoRoot(),
      path.join(repoRoot(), ".venv")
    );
  }

  agentProcess.once("error", (error) => {
    const message = "Unable to start Agent process: " + String(error);
    appendRuntimeLog("desktop.log", message);
    agentStatus = {
      state: "error",
      error: message
    };
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
    }, 15000);

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

  const current = agentProcess;
  const currentPort = agentStatus.port;
  const currentToken = agentToken;

  if (agentSocket) {
    agentSocket.close();
    agentSocket = null;
  }

  if (!current) {
    return;
  }

  if (currentPort && currentToken) {
    try {
      await fetch("http://127.0.0.1:" + currentPort + "/shutdown", {
        method: "POST",
        headers: {
          Authorization: "Bearer " + currentToken
        }
      });
    } catch {
      // Best-effort graceful shutdown; force kill below if still alive.
    }
  }

  if (current.exitCode === null) {
    await Promise.race([
      new Promise<void>((resolve) => {
        current.once("exit", () => resolve());
      }),
      new Promise<void>((resolve) => {
        setTimeout(resolve, 1500);
      })
    ]);
  }

  if (current.exitCode === null) {
    appendRuntimeLog("desktop.log", "Agent did not stop gracefully; forcing termination.");
    current.kill();
    await Promise.race([
      new Promise<void>((resolve) => {
        current.once("exit", () => resolve());
      }),
      new Promise<void>((resolve) => {
        setTimeout(resolve, 700);
      })
    ]);
  }
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
ipcMain.handle("agent:permission-get", async () => {
  return sendRequest("permission.get", "permission.loaded");
});
ipcMain.handle("agent:permission-set", async (_event, mode: string) => {
  return sendRequest("permission.set", "permission.changed", { mode });
});
ipcMain.handle(
  "agent:approval-respond",
  async (
    _event,
    approvalId: string,
    decision: "allow_once" | "allow_turn" | "deny",
    turnId?: string
  ) => {
    return sendRequest(
      "approval.respond",
      "approval.resolved",
      { approval_id: approvalId, decision },
      turnId ? { turnId } : {}
    );
  }
);
ipcMain.handle("agent:project-open", async (_event, model?: string) => {
  const selection = await dialog.showOpenDialog({
    properties: ["openDirectory"],
    title: "Open coding workspace"
  });
  if (selection.canceled || !selection.filePaths[0]) {
    return { canceled: true };
  }
  const event = await sendRequest(
    "project.open",
    "project.opened",
    model
      ? { path: selection.filePaths[0], model }
      : { path: selection.filePaths[0] }
  );
  return { canceled: false, event };
});
ipcMain.handle("agent:project-get", async () => {
  return sendRequest("project.get", "project.loaded");
});
ipcMain.handle("agent:project-list", async () => {
  return sendRequest("project.list", "project.listed");
});
ipcMain.handle(
  "agent:project-select",
  async (_event, projectId: string, model?: string) => {
    return sendRequest(
      "project.select",
      "project.selected",
      model ? { project_id: projectId, model } : { project_id: projectId }
    );
  }
);
ipcMain.handle("agent:model-list", async () => {
  return sendRequest("model.list", "model.listed");
});
ipcMain.handle("agent:model-select", async (_event, threadId: string, model: string) => {
  return sendRequest("model.select", "model.selected", { model }, { threadId });
});
ipcMain.handle("agent:thread-create", async (_event, model?: string) => {
  return sendRequest(
    "thread.create",
    "thread.created",
    model ? { model } : {}
  );
});
ipcMain.handle("agent:thread-list", async () => {
  return sendRequest("thread.list", "thread.listed");
});
ipcMain.handle("agent:thread-get", async (_event, threadId: string) => {
  return sendRequest(
    "thread.get",
    "thread.loaded",
    { thread_id: threadId },
    { threadId }
  );
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
  appendRuntimeLog(
    "desktop.log",
    "Application ready version=" + app.getVersion() + " packaged=" + app.isPackaged
  );
  startAgent();
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("before-quit", (event) => {
  if (quitReady) {
    return;
  }

  event.preventDefault();
  if (quitInProgress) {
    return;
  }

  quitInProgress = true;
  void stopAgent().finally(() => {
    quitReady = true;
    app.quit();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
