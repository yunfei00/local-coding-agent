# Phase 1 - Thread / Turn WebSocket Protocol

Status: **implemented on `feature/v0.1-mvp`; pending local Windows acceptance**

## Goal

Phase 1 turns the Phase 0 process bootstrap into a real bidirectional Agent transport.

This phase intentionally uses a simulated response generator. The goal is to validate Thread / Turn semantics, streaming events, cancellation, reconnection boundaries and Desktop IPC before introducing Ollama in Phase 2.

## Implemented protocol

Desktop -> Agent:

- `client.hello`
- `thread.create`
- `thread.list`
- `thread.get`
- `turn.start`
- `turn.cancel`

Agent -> Desktop:

- `server.ready`
- `thread.created`
- `thread.listed`
- `thread.loaded`
- `turn.started`
- `turn.delta`
- `turn.completed`
- `turn.cancelled`
- `error`

Each message uses the common envelope:

```json
{
  "type": "turn.delta",
  "request_id": null,
  "thread_id": "thread_xxx",
  "turn_id": "turn_xxx",
  "timestamp": "ISO-8601",
  "payload": {}
}
```

## Security boundary

- Agent listens on `127.0.0.1` only.
- Dynamic port.
- Random process token.
- WebSocket requires the Bearer token.
- Renderer does not receive the token.
- Electron Main owns the WebSocket.
- Renderer receives a minimal typed API through preload / IPC.
- `contextIsolation: true`.
- `nodeIntegration: false`.

## Thread state

Phase 1 stores Threads in memory only.

Persistence intentionally remains Phase 7. Closing the Agent process clears Phase 1 threads.

## Turn state

A Turn can emit multiple streaming events.

Current Phase 1 test implementation:

```text
turn.start
 -> turn.started
 -> turn.delta
 -> turn.delta
 -> ...
 -> turn.completed
```

If Stop is pressed:

```text
turn.cancel
 -> running asyncio task cancelled
 -> turn.cancelled
```

Phase 2 replaces the simulator with Ollama streaming while keeping these events.

## Windows verification

Update the development branch:

```powershell
git checkout feature/v0.1-mvp
git pull origin feature/v0.1-mvp
.\scripts\dev\bootstrap.ps1
.\scripts\dev\start.ps1
```

Then verify:

1. Status becomes **Agent Connected** and shows `phase1`.
2. Click **+ New thread**.
3. A `New thread` entry appears.
4. Enter any test prompt and click **Send**.
5. Your message appears.
6. Simulated Agent text arrives progressively instead of appearing all at once.
7. Send another prompt and press **Stop** while text is streaming.
8. UI displays **Turn cancelled.**
9. Application remains responsive.
10. Close the app and confirm no orphan Python Agent remains.

Expected simulated response starts with:

```text
Phase 1 protocol is working.
```

## Exit criteria

Phase 1 is accepted when:

- Windows and Ubuntu CI pass.
- WebSocket authenticates successfully.
- Thread can be created and listed.
- Turn can be started.
- Delta events stream to the Desktop.
- Turn can be cancelled.
- Invalid requests return structured errors.
- Closing the Desktop terminates the Agent.
- Local Windows UI verification passes.

After acceptance proceed to **Phase 2: Ollama Provider**.
