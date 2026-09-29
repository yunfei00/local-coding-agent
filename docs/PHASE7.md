# Phase 7 - SQLite Persistence, Session Resume and Conversation Follow

Status: **implemented on `feature/v0.1-mvp`; pending local Windows acceptance**

## Goal

Phase 7 makes the Desktop useful as a daily development environment rather than a session-only prototype.

The following state now survives a full application restart:

- opened projects;
- active project;
- Threads per project;
- active Thread per project;
- user/assistant message history;
- Thread model selection;
- permission mode.

## Storage location

Electron passes its native user-data directory to the Python Agent through:

```text
LCA_DATA_DIR
```

The Agent creates:

```text
<userData>/local-coding-agent.sqlite3
```

The database is outside the Git repository and is not committed.

When the Python Agent is launched independently without `LCA_DATA_DIR`, it falls back to:

```text
~/.local-coding-agent/local-coding-agent.sqlite3
```

## SQLite schema

Phase 7 creates tables for:

```text
projects
threads
messages
tool_calls
approvals
settings
```

The first three and settings are used for current session resume.

`tool_calls` and `approvals` are reserved in the schema for richer historical execution playback in a later phase.

SQLite is configured with:

```text
foreign_keys = ON
journal_mode = WAL
synchronous = NORMAL
```

No new Python dependency is required; the standard-library `sqlite3` module is used.

## Runtime model

The existing in-memory structures remain the hot runtime state.

Mutations are written through to SQLite:

```text
create Thread -> memory + SQLite
change model  -> memory + SQLite
append chat   -> memory + SQLite
select Thread -> project state + SQLite
select project -> setting + SQLite
permission change -> setting + SQLite
```

At Agent startup, valid persisted project paths are hydrated back into Project Sessions.

If a previously stored project directory no longer exists, it remains in SQLite but is not loaded into the current runtime session.

## Graceful shutdown

Application shutdown now:

1. cancels active Turns;
2. waits for cancellation cleanup;
3. cleans up the Agent HTTP/WebSocket server;
4. closes SQLite.

This avoids closing the database while an active Turn is still unwinding.

## Conversation auto-follow

The right conversation pane now behaves like a coding-agent chat:

- while you remain near the bottom, new tokens/tool output keep the main pane pinned to the latest content;
- switching project or Thread starts at the latest content;
- sending a new message restores follow mode;
- terminal cards separately auto-follow their latest stdout/stderr.

This fixes the previous behavior where content could continue growing while the main scrollbar stayed above the newest content, making the page appear to move upward.

## Scroll up and down-arrow behavior

If you intentionally scroll up more than a small threshold, auto-follow pauses so the UI does not fight you.

A circular:

```text
↓
```

button appears near the bottom of the conversation pane.

Clicking it:

1. scrolls smoothly to the newest content;
2. hides the button;
3. restores automatic follow mode.

## Windows acceptance

Update and start:

```powershell
cd D:\code_2026\local-coding-agent

git checkout feature/v0.1-mvp
git pull origin feature/v0.1-mvp

.\scripts\dev\start.ps1
```

### Test A - persistence after restart

Open two different projects.

In project A:

- create at least two Threads;
- send messages in both;
- select a model;
- leave one Thread active.

Select a permission mode other than the default.

Close the Local Coding Agent application completely.

Start it again.

Expected:

- both existing project paths return in the left sidebar;
- the previously active project is selected;
- its previously active Thread is selected;
- Thread message history is restored;
- model selection is restored;
- permission mode is restored.

### Test B - live auto-follow

Send a task that produces a long streaming response or command output.

Do not touch the scrollbar.

Expected:

- the main conversation remains at the newest content;
- the visible content does not appear to drift upward;
- the terminal card also follows the newest output.

### Test C - manual history reading

While a long conversation exists, manually scroll upward.

Expected:

- auto-follow pauses;
- the UI does not force you back down;
- a circular down-arrow appears.

Click the arrow.

Expected:

- the conversation smoothly returns to the newest content;
- the arrow disappears;
- subsequent output follows the bottom again.

## Exit criteria

Phase 7 is accepted when:

- Windows and Ubuntu CI pass;
- projects survive full app restart;
- Threads and messages survive restart;
- active project/Thread are restored;
- model selection and permission mode are restored;
- normal live conversation stays pinned to the latest content;
- manual scroll-up is respected;
- the down-arrow returns to the latest content;
- terminal output follows its latest line.

After acceptance proceed to **Phase 8: real-world repository validation and reliability fixes**.
