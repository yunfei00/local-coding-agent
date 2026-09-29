# Phase 3 - Tool System v1

Status: **implemented on `feature/v0.1-mvp`; pending local Windows acceptance**

## Goal

Phase 3 turns Local Coding Agent from a local chat application into a coding agent that can inspect, modify and validate one explicitly selected local project.

The selected directory is the **Workspace security boundary**.

## Workspace flow

```text
Open project
   -> Electron folder picker
   -> project.open
   -> Python resolves the real path
   -> ToolRegistry is created for that workspace
   -> Threads are created for that workspace
```

Changing the workspace clears the Phase 3 in-memory Thread state.

Persistence across app restarts remains Phase 7.

## Tools

Phase 3 exposes nine tools to Ollama:

```text
list_directory
read_file
search_files
write_file
apply_patch
run_command
git_status
git_diff
git_log
```

### apply_patch

Phase 3 uses a deterministic exact-text patch:

```text
path
old_text
new_text
replace_all=false
```

It refuses ambiguous replacements unless the model explicitly requests `replace_all`.

## Workspace guard

All file paths are:

1. expanded;
2. resolved to a real/canonical path;
3. compared with the canonical Workspace root;
4. rejected if they escape the Workspace.

This prevents ordinary `..\` traversal and resolved symlink/junction escapes from silently writing outside the selected project.

## Shell

Windows uses:

```text
powershell.exe -NoProfile -NonInteractive -Command
```

Shell output streams to the Desktop as `tool.output`.

The Tool Result records:

- stdout
- stderr
- exit_code
- duration_ms
- cwd

A non-zero command exit code is returned to the model as a real result. It does not automatically terminate the Turn.

## Temporary Phase 3 command restrictions

The full approval system arrives in Phase 5.

Until then, Phase 3 blocks obvious destructive operations including:

- Remove-Item / del / erase / rmdir
- rm with options
- git reset --hard
- git clean
- git push
- destructive checkout overwrite
- format
- shutdown/restart
- registry modification

The model is explicitly instructed not to bypass these restrictions.

## Minimum tool loop

To validate Tool System v1, Phase 3 includes a bounded tool loop:

```text
User
 -> Ollama
 -> tool_calls
 -> ToolRegistry
 -> tool result
 -> role=tool
 -> Ollama
 -> next tool_calls or final answer
```

Maximum:

```text
12 tool steps per Turn
```

Phase 4 hardens this into the full Agent Loop with better repetition detection, recovery policies, context control and completion behavior.

## Desktop events

The Desktop now displays:

- `tool.requested`
- `tool.started`
- `tool.output`
- `tool.completed`
- `file.changed`

This makes local execution observable rather than hidden.

## CI tests

Automated tests verify:

- Workspace path escape is rejected.
- All nine tools are registered.
- write/read/search work.
- exact patch works.
- ambiguous patch is rejected.
- destructive command blocking works.
- a safe shell command runs.
- Ollama provider streaming tests still pass.
- Desktop typecheck/tests/build pass.

## Windows acceptance

Update and start:

```powershell
cd D:\code_2026\local-coding-agent

git checkout feature/v0.1-mvp
git pull origin feature/v0.1-mvp

.\scripts\dev\bootstrap.ps1
.\scripts\dev\start.ps1
```

### Test A - read-only inspection

Open a small Git project.

Create a new Thread and ask:

```text
先不要修改任何文件。检查这个项目的目录结构、Git 状态和主要入口文件，然后告诉我这个项目是做什么的。
```

Expected:

- Tool cards appear.
- Agent uses list/read/search/git tools.
- No files change.

### Test B - controlled code change

Use a disposable/test project or a project with clean Git status.

Ask:

```text
先查看 Git 状态。给项目新增一个非常简单的 README_TEST.md，内容写“Local Coding Agent Phase 3 test”。然后查看 Git diff，确认修改结果。
```

Expected:

- `git_status`
- `write_file`
- `git_diff`
- Changed file event
- final explanation

Delete/revert the test file manually after acceptance if desired.

### Test C - command execution

On a project with a known test command ask the Agent to run it, for example:

```text
不要修改代码，只运行现有测试，并根据真实输出告诉我是否通过。
```

Expected:

- `run_command`
- live command output
- real exit code
- no fabricated success

## Exit criteria

Phase 3 is accepted when:

- Windows and Ubuntu CI pass.
- Workspace selection works.
- Path guard works.
- Qwen3-Coder emits real tool calls.
- File tools work on a real project.
- Shell output is visible.
- Git status/diff work.
- A controlled file change is visible in Git diff.
- Stop can cancel an active command/model turn.
- No access outside the selected workspace occurs.

After acceptance proceed to **Phase 4: Full Agent Loop**.


## Phase 3 UX corrections

The Phase 3 desktop behavior was adjusted after local Windows acceptance feedback:

- Opening a project automatically creates/selects a default Thread.
- The prompt is immediately usable after opening a project; creating a Thread manually is optional.
- Multiple opened projects remain available during the current app session.
- Each project owns its own Workspace, Tool Registry, Threads and messages.
- Switching projects changes the active Workspace without discarding the others.
- Reopening the same project path reuses its existing in-memory project session.
- Sidebar scrolling and conversation scrolling are independent.
- The app window itself does not use page-level scrolling.

Cross-restart project/thread persistence is intentionally still Phase 7 and will use SQLite.
