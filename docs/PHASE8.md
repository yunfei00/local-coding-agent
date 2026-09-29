# Phase 8 - Real-world Repository Validation

Status: **implemented on `feature/v0.1-mvp`; pending final local Windows / Ollama acceptance**

## Goal

Phase 8 is the reliability gate for v0.1.0.

No large new product surface is introduced here. The purpose is to prove that the components from Phase 0 through Phase 7 work together as one coding-agent system:

```text
task
 -> inspect
 -> execute real test/build
 -> observe failure
 -> read relevant code
 -> make a precise change
 -> rerun validation
 -> inspect final Diff
 -> summarize only observed results
```

## Reliability fixes found during Phase 8

### file_exists

The original v0.1 plan included `file_exists`, but the Phase 3 registry did not actually expose it.

Phase 8 adds it so the Agent can cheaply detect manifests, wrappers and configuration without deliberately generating read errors:

```text
pyproject.toml
package.json
gradlew.bat
settings.gradle.kts
CMakeLists.txt
```

`file_exists` is read-only and is available in all permission modes.

### Existing user changes

The system prompt now explicitly requires the Agent to preserve unrelated uncommitted user work, inspect the relevant Git diff before editing an already-dirty target file, and prefer the smallest compatible change.

Runtime path and permission guards remain authoritative.

## Deterministic Agent E2E in CI

Phase 8 adds a Fake Provider that supplies deterministic Tool Calls while the rest of the stack remains real.

The tests use the actual Agent Server loop, Tool Registry, Permission policy, filesystem, PowerShell/Bash runner, Git repository, patch implementation, verification tracker and SQLite message persistence.

The Fake Provider only decides the next Tool Call.

### Python fixture

CI creates a temporary Git repository with a real bug:

```python
def add(a, b):
    return a - b
```

The scripted Agent performs:

```text
file_exists
 -> run real unittest (FAIL)
 -> read_file
 -> apply_patch
 -> run real unittest again (PASS)
 -> git_diff
 -> final answer
```

The E2E test requires the first command to return a non-zero exit code and the second command to exit 0. It also verifies that real failed/successful Tool Results are fed back into later model calls and that final verification is complete.

### Node fixture

CI creates a temporary Node repository with a real failing `node:test` test and `package.json`.

The scripted Agent performs:

```text
file_exists package.json
 -> npm test (FAIL)
 -> read_file
 -> apply_patch
 -> npm test (PASS)
 -> git_diff
 -> final answer
```

Node is installed before the Python E2E suite on both Windows and Ubuntu CI.

## One-command repository self check

Windows:

```powershell
cd D:\\code_2026\\local-coding-agent
.\\scripts\\validation\\phase8-self-check.ps1
```

It runs Python compile, all Python tests, deterministic Python/Node Agent E2E, Desktop typecheck/tests/build and final Git status.

## Real Ollama validation

The deterministic E2E proves framework correctness but does not prove Qwen3-Coder quality.

For final local validation, run the Desktop with the installed local model and use a clean/disposable or safely version-controlled project.

Recommended prompt:

```text
先查看 Git 状态并识别这个项目的测试方式。

运行现有测试。
如果失败，根据真实错误定位相关文件并修复。
不要覆盖与本任务无关的已有未提交修改。

修复后重新运行测试，直到通过或明确说明无法继续的外部原因。
最后查看 Git diff，并总结：
1. 原始失败
2. 修改了什么
3. 最终运行了什么验证
4. 最终是否真实通过
```

Expected behavior:

- targeted inspection rather than a blind full-repository dump;
- real test/build output;
- non-zero command result does not end the Turn;
- relevant source is read before editing;
- minimal change;
- validation after the latest code change;
- final Git Diff after the latest change;
- no fabricated success.

## Android real-project validation

A real Android target was checked: `yunfei00/AutoTestSceneApp`.

Its current main branch contains:

```text
gradlew
gradlew.bat
settings.gradle.kts
build.gradle.kts
app/build.gradle.kts
```

The project currently uses Android Gradle Plugin 9.2.0. Its GitHub Android workflow sets up JDK 21, Android SDK platform 36.1 and runs:

```text
./gradlew testDebugUnitTest lintDebug assembleDebug --no-daemon --stacktrace
```

For the Windows Local Coding Agent validation, use the equivalent:

```powershell
.\\gradlew.bat testDebugUnitTest lintDebug assembleDebug --no-daemon --stacktrace
```

A local environment preflight helper is included:

```powershell
cd D:\\code_2026\\local-coding-agent
.\\scripts\\validation\\phase8-android-preflight.ps1 -ProjectPath D:\\code_2026\\AutoTestSceneApp
```

Then open the Android project in Local Coding Agent and use:

```text
先检查 Git 状态和 Gradle Wrapper。

运行：
.\\gradlew.bat testDebugUnitTest lintDebug assembleDebug --no-daemon --stacktrace

如果存在代码级失败，根据真实错误定位并修复。
不要修改与错误无关的代码。
每次修改后重新验证。
最后查看 Git diff 并告诉我最终哪几个 Gradle task 真实通过。
```

If Android SDK/JDK prerequisites are missing, the Agent should report that external prerequisite clearly instead of inventing a code fix.

## Manual stress checks

### Stop

Run a long build/test and press **Stop**.

Expected: the Turn is cancelled, the shell process tree is terminated and no lingering Gradle/Java/Python/Node child continues consuming resources.

### Permission

Use Workspace mode for normal validation. Dangerous Git/delete/publish operations must still enter the Phase 5 approval flow.

### Long output

Run a verbose build with `--stacktrace`.

Expected: UI remains responsive, terminal card follows recent output, model receives compacted result context, and conversation bottom-follow remains stable unless the user intentionally scrolls up.

### Restart resume

After a real validation Turn, close the application and reopen it.

Expected: project/thread/chat history returns and selected model/permission mode are restored.

## Phase 8 exit criteria

Phase 8 is accepted when:

- Windows and Ubuntu CI pass;
- deterministic Python Agent E2E passes;
- deterministic Node Agent E2E passes;
- `file_exists` is available and permission-safe;
- local Qwen3-Coder completes at least one real failure -> fix -> pass -> Diff task;
- Android Gradle validation can be initiated correctly on the Windows development machine;
- Stop leaves no child process running;
- Diff is accurate;
- existing user changes are preserved;
- session resume remains reliable.

After acceptance proceed to **Phase 9: Windows packaging and v0.1.0 Release**.
