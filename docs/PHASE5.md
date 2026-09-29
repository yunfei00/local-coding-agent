# Phase 5 - Permissions and Approval System

Status: **implemented on `feature/v0.1-mvp`; pending local Windows acceptance**

## Goal

Phase 5 moves security decisions out of the model prompt and into a runtime policy layer.

The Agent now has three permission modes:

```text
Read Only
Workspace
Full Access
```

The selected mode is enforced by Python before every tool execution.

## Read Only

Visible tools:

```text
list_directory
read_file
search_files
git_status
git_diff
git_log
```

The model does not receive:

```text
write_file
apply_patch
run_command
```

The backend also rejects those tools if they are somehow requested directly.

Use Read Only when you only want analysis or inspection.

## Workspace

This is the default mode.

The Agent can:

- read the selected project;
- modify files inside the selected project;
- run development commands with the selected project as the normal working boundary;
- inspect Git state/diff/log.

Normal development operations do not require approval.

Sensitive command patterns do require approval, including:

```text
file/directory deletion
git reset --hard
git clean
git checkout -- / git restore
git push
format / shutdown / restart
registry writes/deletes
```

Explicit parent-path and external absolute-path command references are rejected in Workspace mode.

## Full Access

Full Access keeps all Workspace tools and additionally permits explicit absolute paths outside the current project.

Project-external access is **not silent**.

An external path request produces an approval card before execution.

Examples:

```text
read_file C:\outside\config.txt
run_command with cwd C:\outside
write_file C:\outside\generated.txt
```

Sensitive commands continue to require approval even in Full Access.

Full Access therefore means "eligible after policy + approval", not "model may do anything silently".

## Approval decisions

When an operation requires approval, the Turn pauses and Desktop displays:

```text
Approval required

Tool
Arguments
Reason
Risk

[Allow once] [Allow for this turn] [Deny]
```

### Allow once

Executes that operation once.

A later matching request asks again.

### Allow for this turn

Executes the operation and remembers the exact approval key until the current Turn ends.

The grant is automatically cleared on completion, failure, Stop or cancellation.

### Deny

The tool is not executed.

The model receives a structured `APPROVAL_DENIED` tool result and can choose a safer alternative.

## Runtime boundary

Approval is implemented independently of the LLM.

The model cannot approve its own operation.

Flow:

```text
Qwen tool_call
  -> PermissionPolicy.evaluate()
  -> allowed?
       no -> PERMISSION_DENIED
       yes
        -> approval required?
             no -> execute
             yes
              -> approval.requested
              -> wait
              -> user decision
              -> execute or deny
```

## Workspace escape defense

File tools still canonicalize paths before execution.

Workspace mode rejects canonical paths outside the selected project, including ordinary `..\` escapes and resolved symlink/junction escapes.

The command policy also rejects explicit:

- parent path escapes such as `..\`;
- absolute paths outside the workspace.

Full Access can permit them only through approval.

### Current shell limitation

The command policy provides application-level path/risk checks, but it is not yet a Windows kernel sandbox.

A sufficiently indirect shell expression could reference operating-system resources in ways that are difficult to prove from command text alone.

For that reason:

- Read Only exposes no shell tool;
- Workspace is intended for normal project development commands;
- known risky/external patterns are denied or approved;
- Full Access is explicitly user-selected.

A stronger native process sandbox can be added later without changing the approval protocol.

## Desktop controls

The composer now contains a permission selector:

```text
Read Only | Workspace | Full Access
```

The selector is disabled while a Turn is running so the security boundary cannot change halfway through an operation.

The existing keyboard behavior remains:

```text
Enter       -> send
Shift+Enter -> newline
```

## Windows acceptance

Update and start:

```powershell
cd D:\code_2026\local-coding-agent

git checkout feature/v0.1-mvp
git pull origin feature/v0.1-mvp

.\scripts\dev\bootstrap.ps1
.\scripts\dev\start.ps1
```

### Test A - Read Only

Select **Read Only**.

Ask:

```text
检查这个项目，告诉我主要入口文件是什么。然后尝试在根目录创建 SHOULD_NOT_EXIST.txt。
```

Expected:

- Agent can inspect the project.
- It should not receive normal write/shell tools.
- `SHOULD_NOT_EXIST.txt` must not be created.

### Test B - Workspace normal edit

Select **Workspace**.

Ask:

```text
在根目录创建 PHASE5_TEST.txt，内容写 Phase 5 workspace test，然后查看 Git diff。
```

Expected:

- normal workspace write executes without an approval popup;
- file is created;
- Git diff is inspected.

### Test C - dangerous command approval

Use a clean disposable Git test project.

Ask:

```text
执行 git clean -fd，但执行之前不要替我做决定。
```

Expected:

- Desktop shows an **Approval required** card;
- command has not run yet.

Click **Deny**.

Expected:

- command is not executed;
- Agent receives the denial and continues/finishes safely.

Repeat with **Allow once** only on a disposable repository where the operation is safe to test.

### Test D - Allow for this turn

Cause the same approved operation to be requested again in one Turn.

Choose **Allow for this turn**.

Expected:

- the matching approval key is reused during that Turn;
- a new Turn does not inherit the approval.

### Test E - Full Access external read

Select **Full Access**.

Ask the Agent to read a harmless text file outside the selected project by absolute path.

Expected:

- approval card appears before reading;
- Deny prevents access;
- Allow once permits the single read.

Switch back to Workspace and retry.

Expected:

- external access is denied by policy rather than offered for approval.

## Exit criteria

Phase 5 is accepted when:

- Windows and Ubuntu CI pass;
- all three permission modes can be selected;
- Read Only cannot write or execute;
- Workspace normal development works without unnecessary prompts;
- known destructive/publishing commands require approval;
- Full Access external paths require approval;
- Allow once works;
- Allow for this turn is cleared after the Turn;
- Deny prevents execution;
- Stop clears pending approval state;
- the model cannot self-approve.

After acceptance proceed to **Phase 6: Command Execution / Terminal hardening and richer Diff UX**.
