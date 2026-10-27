# 基础 Coding Agent 差距审计与本轮交付

日期：2026-10-28（Asia/Shanghai）。审计基线 `main / 6353034`，源码产品版本仍为 v0.4.2。比较对象是公开描述的编程 Agent 工作流，不是 Codex 私有实现或模型智能水平。不用一个没有测量依据的“完成百分比”表示差距。

## 比较依据与真实调用链

OpenAI 官方将 harness 描述为管理任务、上下文、工具、进度、失败和审批的执行系统，见 [Codex harness](https://developers.openai.com/blog/codex-as-a-platform)。仓库指令与长任务上下文的公开说明见 [Codex prompting guide](https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide)。本项目继续使用自己的兼容 Provider 和执行架构；没有改成依赖 Codex 服务。

Chat：`turn.start → 线程/模型校验 → run_tool_turn → ContextBudgetManager → Provider.stream_chat → 完整工具调用解析 → PermissionPolicy/Approval → ToolRegistry → 真实结果/执行日志 → 下一轮模型 → 验证与 Diff`。

Task：`task.start → Settings/模型/预算冻结 → TaskRuntime → Worktree → Single Agent 或现有四角色规划 → 同一个 run_tool_turn → VerificationEngine → awaiting_approval`。取消、Checkpoint、预算、工具重复保护不另建平行实现。

## 基础能力矩阵

| 范围 | 审计结论 | 代码/证据 |
| --- | --- | --- |
| 理解目标、多轮读写/搜索/精确 Patch | 已有；取决于所选模型质量，不代表任意模型都能稳定完成 | `server/main.py`、`tools/filesystem.py`、真实阿里工程验收 |
| 终端、持续进程、真实退出码、停止进程树 | 已有 | `tools/processes.py`、M2/M4 回归 |
| 自动验证、失败修复、保护原有测试 | 已有 | `core/verification.py`、`core/orchestration.py`、M4/M5 |
| Git Diff、独立 Worktree、审批后接受 | 已有；不自动覆盖源工程或自动合并 | `tools/git.py`、Git v3 回归 |
| 暂停/取消/检查后恢复、预算快照 | 已有 | `core/task_runtime.py`、`core/budget.py`、execution recovery 回归 |
| 多 Provider、模型身份、Usage 与诊断 | 已有；真实不同模型仍可能拒绝请求或返回错误 | 混合 Provider、Planning/预算回归及逐次真实验收 |
| Windows 截图/UIA/受控 GUI 验证 | 已有；限定授权窗口与交互会话 | M3/M4/M5，不是通用锁屏/跨用户自动化 |
| 仓库 `AGENTS.md` | 本轮补齐工作区根目录与显式目标的目录链 | `core/repository_instructions.py`、本轮专项与真实 API |
| 裁剪后与恢复时保留执行事实 | 本轮补齐有界事实记忆，复用执行账本/Checkpoint | `core/execution.py`、Plan 折叠“执行上下文” |
| 执行中追加消息/排队与改向 | 仍缺；Chat `submit` 在运行时拒绝新提交，输入框可编辑 | 不把可输入等同于已支持 steering；后续首要交互工作 |
| 模型生成的语义压缩、长期决策记忆 | 仍缺；本轮事实记忆不保存完整推理、源码或完整工具对话 | 不声称实现 Codex 的压缩算法或无损长记忆 |
| 通用 SKILL.md 加载/调用生命周期 | 尚未实现；现有 Prompt Rules/MCP 可用 | 后续扩展，不与仓库指令混称 |
| OS 级强隔离 | 尚未实现；当前是应用权限检查与进程 Job | 不将 Workspace/Full Access 描述为操作系统沙箱 |

本轮优先解决会让 Agent 在真实仓库中遗漏规范、反复读文件、恢复后不了解已有修改的两个基础缺口。后续优先级为：追加指令/队列 → 可审计的语义压缩与完整工具会话恢复 → 技能调用；强隔离需独立设计和 Windows 验收。并行 Agent、云端执行、插件市场不计入本轮基本编程闭环。

## 实际实现与边界

`RepositoryInstructions` 不扫描整个仓库，只加载根目录和结构化工具路径（path/cwd）的祖先目录，每目录优先非空 `AGENTS.override.md`，否则 `AGENTS.md`。更深目录只对其子树生效；不读取宿主 `~/.codex` 或工作区外文件，不隐式跟随指令文件符号链接。单文件 32 KiB、已加载总量 64 KiB；UTF-8、权限/大小异常明确失败，不静默忽略规则。目录指令改变或删除时，下一次该目录链发现会更新。外部文件即使 Full Access 也不会被自动读取。

新目标目录有未读指令时，本批模型工具全部不执行；先更新指令，再让同一模型重新决策，消耗原有调用/步骤/时间额度。Planner 同样获得根指令。Shell 内部字符串不做不可靠的静态路径推断，提示模型先通过显式路径工具发现相关目录链；这不是任意 shell/MCP 写入的强制 AGENTS 沙箱。用户请求和运行时权限/审批优先，仓库文件不能授权提交、发布或绕过权限。

工作记忆保存在已有 `agent_execution_runs.data_json`，随计划与 Checkpoint 使用原 ID 恢复，旧记录没有该字段仍可打开。保留最近 16 条工具事实、最多 24 个修改路径、最后命令与 Diff 的真实状态和序号，整体约束 12,000 字符；请求快照按模型窗口进一步收缩。事实含工具名、路径、行号范围、成功/错误码和退出码；不保存命令正文、Prompt、文件正文、stdout、截图、凭据或旧进程句柄。路径中的已知秘密会脱敏。Plan 中按需展开查看，历史成功明确不等于最新文件验证通过；不会因此跳过独立验收。

权限指令和当前用户请求放不进上下文时明确 `MODEL_CONTEXT_LIMIT`，不能静默截短后发送。不会自动改大用户模型上下文或预算。正常裁剪仍保持完整 tool-call/result 组，原循环/重试/取消/预算保护保留。

## 本轮验证

专项：`tests/test_agent_context_continuity.py` 覆盖目录链/覆盖/变更、外部读取边界、大小与编码、先读规则再修改、只读阻断、真实 SQLite 重启、有界脱敏记忆、实际裁剪后的文件修复、真实 unittest 与 Diff。前端新增折叠证据组件测试；既有 execution recovery 18 项通过。完整回归与最新双平台 CI 的最终数量以本轮 PR 检查为准，未完成门禁前不合并。

真实 Qwen：使用已保存的 `qwen3.7-plus` 和桌面安全凭据，实际 Electron IPC → Task → HTTP → 工具。Task `d885e14a-fdb2-48c6-b032-6e4b70e84894`，5 次 HTTP 请求，实际输入 24,695、输出 558、总计 25,253 Token；缓存 11,904 是输入子集，不能重复相加；费用 UNKNOWN。最终 `awaiting_approval`，仅修改 `calculator.py`，根/测试两份指令已加载且未改，原测试未改，独立 unittest 2 项通过，Diff 非空。没有提交模型修复副本或修改生产工程。

这次真实运行证明指令/事实记忆进入实际调用链；强制裁剪与重启场景由脚本模型 + 真实工具/SQLite 专项覆盖，不把此次短任务冒充真实模型长上下文压力测试。原始本地报告 `validation-reports/20261028-continuity-live-qwen3.7-plus.json` 不入 Git，脱敏结果见本文。累计真实验证账本未清零，失败预留未退回为零。

## 公司更新与复验

```powershell
git switch main
git pull --ff-only origin main
uv sync --locked
npm.cmd --prefix desktop ci
.\scripts\dev\start.ps1
```

先保存工作并完整退出旧 Electron/Agent，再启动。旧安装包不包含本次修复；本轮不建 Tag、Release 或安装包。已有 Settings、Key、项目、会话、任务和预算继续保留，无需重配；已有 Task 保留模型/预算快照，新执行读取当时的工作区指令。

以下复用既有 fixture，指令只在临时副本创建；`--live` 会发送实际请求，费用由服务商决定。本机累计上限与之前授权一致，不是每次清零：

```powershell
uv run --locked python -m unittest discover -s tests -p test_agent_context_continuity.py -v
uv run --locked python scripts/validation/real_online_agent_e2e.py --live --scenario calculator --with-instructions --strategy single-agent --model qwen3.7-plus --context-window 131072 --output-tokens 8192 --request-seconds 120 --max-calls 10000 --max-tokens 1000000000 --max-full-attempts 10 --max-seconds 7200 --authorize-budget-update --report validation-reports/company-instructions-qwen.json
```

查看报告 `result`、`execution_context`、`disk_evidence.independent_unittest`、`calls` 与 Diff。没有安全凭据会明确 NOT RUN；不能当作 API 通过。不需要用户编写新测试工程。
