# Phase 4 - Full Agent Loop

Status: **implemented on `feature/v0.1-mvp`; pending local Windows acceptance**

## Goal

Phase 4 upgrades the Phase 3 bounded tool loop into a more reliable coding-agent execution loop.

The target behavior is:

```text
User task
  -> inspect project
  -> choose tools
  -> execute
  -> analyze real result
  -> recover from failures
  -> modify precisely
  -> validate
  -> inspect final diff
  -> finish with evidence
```

## Keyboard interaction

The composer now follows the desktop coding-agent convention:

```text
Enter       -> send
Shift+Enter -> newline
```

IME composition is respected. Pressing Enter while a Chinese/Japanese/Korean IME is still composing text does **not** send the message.

## Loop limits

Per Turn:

```text
max model steps: 16
max tool calls: 40
```

These are safety/no-progress bounds rather than normal targets.

## Repetition protection

Tool calls are fingerprinted from:

```text
tool name + canonical JSON arguments
```

The same exact call is allowed twice.

The third identical call is not executed. The model receives a structured `REPEATED_TOOL_CALL` result telling it to use the existing result or change approach.

After three blocked repeat attempts the Turn stops with:

```text
TOOL_LOOP_DETECTED
```

This prevents a local model from burning time indefinitely on a failed strategy.

## Failure recovery

A failed development command is returned to the model with the real:

- stdout
- stderr
- exit code
- duration
- cwd

A non-zero command does not automatically terminate the Turn. The model can inspect the failure and choose another action.

For transient Ollama connection failures that occur **before any output is produced**, the Agent performs one automatic retry.

Partial generations are not retried, which prevents duplicated output/actions.

## Context control

The active Ollama context remains 32K for the current 32 GB GPU baseline.

Phase 4 prevents tool output from consuming the entire context:

- older Thread history is bounded deterministically;
- the most recent history is preserved;
- large strings in tool results are truncated for the model;
- very large command outputs use bounded tails/excerpts;
- the Desktop still receives the real streaming command output.

The model-facing tool result budget defaults to approximately 24K characters per tool result.

## Completion verification

The Agent tracks file changes during a Turn.

After any file change it expects a **new Git diff inspection** after that change.

If the changed file looks like source code, it also expects a successful validation command after the latest code change.

Examples of code suffixes include:

```text
.py .js .ts .tsx .java .kt .go .rs .c .cpp .cs .ps1 .gradle
```

The model receives an explicit verification reminder after modifications.

The final `turn.completed` event contains:

```json
{
  "verification": {
    "complete": true,
    "missing": [],
    "changed_paths": []
  }
}
```

If the model still finishes without required verification, the Desktop shows a visible **Verification incomplete** message rather than silently presenting an unverified result as complete.

Documentation-only changes require final Git diff inspection but do not automatically require a test command.

## Project behavior

Phase 3 multi-project behavior remains:

- multiple projects can stay open during the current app session;
- each project owns independent Threads/messages/tools;
- switching project changes the active Workspace;
- opening a project automatically provides a default Thread.

Cross-restart persistence remains Phase 7 / SQLite.

## Windows acceptance

Update and start:

```powershell
cd D:\code_2026\local-coding-agent

git checkout feature/v0.1-mvp
git pull origin feature/v0.1-mvp

.\scripts\dev\bootstrap.ps1
.\scripts\dev\start.ps1
```

### Test A - keyboard

Open a project and type:

```text
检查一下这个项目是做什么的
```

Press **Enter**.

Expected: message sends without clicking Send.

Then type a multi-line prompt using **Shift+Enter** between lines.

Expected: newline is inserted and the prompt is not sent until plain Enter is pressed.

### Test B - failure recovery

Use a disposable/clean Git project and ask:

```text
检查这个项目现有测试。运行测试；如果失败，根据真实错误继续分析并修复，修复后重新测试，最后查看 Git diff。
```

Expected:

- Agent inspects project first.
- Real command output appears.
- If a command fails, the Turn stays alive.
- Agent changes approach or edits based on the real error.
- Validation is rerun after code changes.
- Git diff is inspected after the latest change.

### Test C - repetition guard

Ask a task that causes a missing-file/tool error, then observe behavior.

Expected: the Agent should change approach. If it requests the exact same tool call repeatedly, the third identical call is blocked and an unproductive repeated loop cannot run forever.

### Test D - context-heavy command

Run a test/build command with substantial output.

Expected:

- full live output remains visible in the Desktop;
- the Agent continues rather than overflowing its 32K model context;
- final response uses the relevant tail/summary of the tool result.

## Exit criteria

Phase 4 is accepted when:

- Windows and Ubuntu CI pass;
- Enter sends and Shift+Enter inserts a newline;
- IME composition does not accidentally send;
- failed commands can be analyzed and followed by additional steps;
- identical tool loops are bounded;
- large tool output is compacted for the model;
- source changes trigger diff/validation expectations;
- incomplete verification is visible;
- Stop still cancels the active Turn.

After acceptance proceed to **Phase 5: Permissions and Approval System**.
