import { app, BrowserWindow, ipcMain } from "electron";
import { ChildProcessWithoutNullStreams, spawn } from "node:child_process";
import path from "node:path";

type AgentStatus = {
  state: "starting" | "ready" | "error" | "stopped";
  host?: string;
  port?: number;
  version?: string;
  protocol?: string;
  error?: string;
};

let mainWindow: BrowserWindow | null = null;
let agentProcess: ChildProcessWithoutNullStreams | null = null;
let agentToken: string | null = null;
let agentStatus: AgentStatus = { state: "starting" };
let stdoutBuffer = "";
let shuttingDown = false;

function repoRoot(): string {
  return path.resolve(__dirname, "..", "..");
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
        state: "ready",
        host: ready.host,
        port: ready.port,
        version: ready.version,
        protocol: ready.protocol
      };
      console.log("[desktop] Agent ready on " + ready.host + ":" + ready.port);
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

async function stopAgent(): Promise<void> {
  shuttingDown = true;
  const current = agentProcess;

  if (!current) {
    return;
  }

  if (agentStatus.state === "ready" && agentStatus.port && agentToken) {
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
