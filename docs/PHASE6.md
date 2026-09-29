# Phase 6 - Terminal Execution and Diff Review

Status: **implemented on `feature/v0.1-mvp`; pending local Windows acceptance**

## Goal

Phase 6 improves the two most visible coding-agent surfaces:

1. command execution;
2. reviewing code changes.

The Agent Loop, permission policy and approval system from earlier phases remain active.

## Terminal-style command cards

`run_command` now emits structured live events:

```text
process_started
stdout chunks
stderr chunks
process_exited
```

The Desktop renders these as a command card with:

- command;
- cwd;
- PID;
- running/completed/failed state;
- live stdout;
- live stderr;
- exit code;
- duration.

stdout and stderr remain distinct in the UI.

The UI retains a bounded recent output window so extremely noisy commands do not make the renderer unbounded.

## Stop kills the command process tree

Previously cancellation killed only the direct PowerShell/Bash process.

That can leave child processes alive, for example:

```text
gradle -> java
npm -> node child
python -> subprocess
build script -> compiler
```

Phase 6 starts commands in an isolatable process group/session and stops the tree:

### Windows

```text
CREATE_NEW_PROCESS_GROUP
taskkill /PID <pid> /T /F
```

### Linux/macOS

```text
new process session
SIGTERM process group
short grace period
SIGKILL if still running
```

Timeout uses the same tree termination path.

## Structured Git Diff

`git_diff` now returns structured file/hunk/line data in addition to normal textual diff output.

Per file it exposes:

- path;
- status;
- additions;
- deletions;
- binary flag;
- hunks;
- old/new line numbers;
- added/deleted/context lines.

The Desktop renders a reviewable file list with expandable hunks.

Large previews are bounded to protect the UI.

## Untracked files

Normal `git diff` does not show untracked files.

Phase 6 additionally queries:

```text
git ls-files --others --exclude-standard
```

Untracked UTF-8/text files are synthesized as added-file previews.

Binary and very large new files are represented safely without dumping unlimited content.

This means a newly generated source file can be reviewed before commit.

## Permission behavior

Phase 5 remains unchanged:

```text
Read Only
Workspace
Full Access
```

Sensitive commands still pause for approval.

The process-tree kill path is internal runtime cleanup and does not bypass the permission system.

## Windows acceptance

Update and start:

```powershell
cd D:\code_2026\local-coding-agent

git checkout feature/v0.1-mvp
git pull origin feature/v0.1-mvp

.\scripts\dev\start.ps1
```

### Test A - live command card

Workspace mode:

```text
运行一个现有的测试命令，并把结果告诉我。不要修改代码。
```

Expected:

- terminal-style card appears;
- command and cwd are visible;
- stdout/stderr stream while running;
- PID appears after process start;
- exit code and duration appear when complete.

### Test B - Stop process tree

Ask:

```text
运行一个会持续一段时间的现有构建或测试命令，我会手动点击 Stop。
```

Click **Stop** while it is running.

Expected:

- Turn becomes cancelled;
- command stops quickly;
- child build/test process does not continue consuming CPU/GPU in the background.

For Windows you can optionally verify in Task Manager that the related child process disappears.

### Test C - tracked Diff

Use a disposable Git project and ask the Agent to make a small edit and then inspect Git diff.

Expected:

- a DIFF card appears;
- changed file is listed;
- added/deleted lines have separate styling;
- old/new line numbers are visible.

### Test D - new untracked file

Ask:

```text
新建 PHASE6_TEST.txt，写两行内容，然后查看 Git diff。
```

Expected:

- `PHASE6_TEST.txt` appears in the DIFF card even though it is untracked;
- it is labeled `untracked`;
- its lines appear as additions.

Delete/revert the test file after acceptance if desired.

## Exit criteria

Phase 6 is accepted when:

- Windows and Ubuntu CI pass;
- command stdout/stderr stream in a terminal-style card;
- cwd/PID/exit code/duration are visible;
- Stop terminates a long command promptly;
- tracked Git modifications render as file/hunk/line Diff;
- untracked text files appear in Diff review;
- permissions/approval behavior from Phase 5 remains intact.

After acceptance proceed to **Phase 7: SQLite persistence and session resume**.
