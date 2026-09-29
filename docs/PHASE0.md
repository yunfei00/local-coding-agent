# Phase 0 - Project Bootstrap

Status: **implemented on `feature/v0.1-mvp`**

## What Phase 0 establishes

Phase 0 intentionally does not implement the Agent Loop yet. It establishes the process boundaries and development contract that later phases build on.

Implemented:

- Electron + React + TypeScript desktop skeleton.
- Python Agent package.
- Electron Main Process launches the Python Agent as a child process.
- Agent binds to `127.0.0.1` on a dynamic port.
- Agent generates a private per-process token.
- Health endpoint requires that token.
- Electron Renderer receives only a minimal status API through preload.
- `contextIsolation: true` and `nodeIntegration: false`.
- Basic desktop visual shell.
- Python unit test.
- TypeScript/Vitest test.
- Windows bootstrap/start/diagnostic scripts.
- Windows + Ubuntu CI checks.

## Local Windows verification

From the repository root:

```powershell
.\scripts\diagnostics\check-env.ps1
.\scripts\dev\bootstrap.ps1
.\scripts\dev\start.ps1
```

Expected result:

1. Electron window opens.
2. The bottom-left status changes from **Agent Starting** to **Agent Connected**.
3. The status detail shows a dynamic `127.0.0.1:<port>` address.
4. Phase 0 welcome panel is visible.

Backend-only verification:

```powershell
.\scripts\dev\start-agent.ps1
```

The console should print one line beginning with:

```text
LCA_AGENT_READY
```

## Why Phase 0 uses HTTP instead of WebSocket

The HTTP endpoint is only a bootstrap health contract. Phase 1 replaces/extends this boundary with the real local WebSocket + JSON protocol for Thread / Turn / events / cancellation.

Keeping the Phase 0 health server in the Python standard library means the first development milestone has no backend framework dependency and can be validated before protocol work starts.

## Exit criteria

Phase 0 is accepted when:

- CI passes.
- Windows bootstrap succeeds.
- Electron starts.
- Agent child process reaches Ready state.
- Closing the app terminates the Agent process.
- No Renderer Node integration is enabled.

After acceptance, development proceeds to **Phase 1: Agent Server and communication protocol**.
