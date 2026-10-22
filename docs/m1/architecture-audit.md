# M1 架构审计与能力矩阵

审计基线：`origin/main` 的 `8c44ca6`。开发分支：`feature/m1-single-agent`。范围是单个在线模型自主执行真实工具；保留 v0.4 多角色功能，本轮不新增模型路由、预算功能或发布产物。

“已实现”表示有代码和自动化证据，不等同于所有公司网关或真实大模型都已人工验收。

| 能力 | 基线 | M1 结果 | 代码与测试证据 |
| --- | --- | --- | --- |
| 多轮模型→工具→结果→模型 | 部分实现：内部循环已有，OpenAI 回传参数格式不符合严格网关 | 已实现：arguments 在 OpenAI 出站边界序列化，call ID 与结果配对，不合并不同 ID 的相同调用 | `agent/server/main.py::run_tool_turn`；`agent/llm/openai_compatible.py::_wire_messages`；`tests/test_single_agent.py::test_online_multiround_actual_failure_patch_retest_diff` |
| 单在线模型自主任务 | 未实现：API-only 仍调用 Planner/Executor/Reviewer | 已实现：`single-agent` 只解析、创建并调用在线 Executor，其他角色的缺失配置不阻塞 | `agent/core/orchestration.py::TaskService.run`；`agent/core/model_catalog.py::resolve`；同上 HTTP 集成测试 |
| Agent Loop 防循环 | 已实现：轮数、工具数、相同调用、短循环、连续错误限制 | 已实现并保留；截断和空回答不能冒充完成 | `agent/core/agent_loop.py::ToolLoopGuard`；`agent/server/main.py::run_tool_turn`；`tests/test_agent_reliability.py` |
| Task Runtime | 已实现：SQLite 阶段、任务快照、检查点、重启恢复 | 已实现并增加 `pending → executing`，单目标步骤保存真实执行证据 | `agent/core/task_runtime.py::TRANSITIONS`；`agent/task_plans.py::record_execution`；`tests/test_single_agent.py` |
| Orchestration | 已实现：Local-first、Local-only、API-only、四角色、独立验证 | 已实现并保留；Single Agent 不依赖规划、审查或升级 | `agent/core/orchestration.py::run`；`agent/llm/router.py::ModelRouter.resolve`；`tests/test_v04_orchestration.py` |
| 独立结构化规划 | 已实现且有持久上限，不是无限重试 | 原模式保留；Single Agent 不发送规划请求，尝试数为 0 | `TaskService.run`；`agent/llm/planning.py`；`tests/test_single_agent.py` |
| 文件读取/搜索/写入/Patch | 已实现：真实文件系统、路径约束、结构化错误 | 已实现并复用；集成测试读取 fixture、真实 Patch 并检查磁盘结果 | `agent/tools/filesystem.py`；`agent/tools/workspace.py`；`tests/test_tools.py`；`tests/test_single_agent.py` |
| 终端与流式输出 | 已实现：真实子进程、stdout/stderr、超时、进程树终止 | 已实现并复用；真实测试先失败再通过；取消后延迟文件不会生成 | `agent/tools/shell.py::RunCommandTool.execute`；`agent/tools/windows_job.py`；`tests/test_single_agent.py::test_cancel_real_terminal_kills_delayed_write` |
| Git/隔离工作区 | 已实现：Status、Diff、Stage、Commit、受管理 Worktree | 已实现并复用；自主任务不能自动 commit/push/merge，原工作区保持独立 | `agent/tools/git.py`；`agent/core/orchestration.py::autonomous_git_block/task_project`；`tests/test_v03_runtime.py`；Single Agent 集成测试 |
| 工具失败反馈与修复 | 部分实现：普通循环支持，任务步骤遇失败会阻塞本轮 | 已实现：Single Agent 的探索性失败直接反馈，可在同一轮继续修复；独立验证仍是最终门槛 | `run_tool_turn(single_agent=True)`；`test_tool_error_is_fed_back_and_model_can_recover`；`test_independent_failure_returns_to_same_executor_for_repair` |
| 取消/暂停/检查后恢复 | 已实现：任务、HTTP、终端、审批取消 | 已实现并沿用；Single Agent 不允许恢复时静默改为本地模型 | `TaskService.handle/run`；`agent/permissions/approval.py`；`tests/test_single_agent.py`；已有恢复测试 |
| 错误诊断 | 已实现：请求元数据、阶段、HTTP 状态、脱敏 JSON/Markdown | 已实现：增加畸形工具参数、截断、上下文不足、同模型无进展/修复上限等明确错误 | `agent/core/task_diagnostics.py`；`agent/llm/openai_compatible.py::_finalize_tool_calls`；Single Agent 错误与超时测试 |
| 上下文管理 | 部分实现：有预算与工具分组，极大调用可能丢弃 assistant 头 | 部分实现：不再发送孤立工具结果；过大交换以 `MODEL_CONTEXT_LIMIT` 停止；尚无语义压缩 | `agent/core/context.py::_force_fit_group`；`tests/test_context.py::test_oversized_tool_exchange_never_orphans_results` |
| 独立验收 | 已实现：配置/发现命令、空测试识别、日志、全工作区指纹 | 已实现并复用；模型文字不能覆盖真实失败，验证失败回给同一 Executor，重复失败停止 | `agent/core/verification.py::VerificationEngine`；`TaskService.workspace_fingerprint/run`；`tests/test_single_agent.py` |
| Desktop UI | 已实现：项目、聊天、工具事件、Task、Approval、Git、Diagnostics | 已实现：Task 与 Settings 增加 Single Agent，Task 只显示 Executor，保留取消入口和结果报告 | `desktop/src/components/AutonomousTaskPanel.tsx`；`ModelSettingsSection.tsx`；`scripts/validation/desktop-smoke.cjs` |
| MCP 扩展工具 | 已实现：stdio/HTTP 与权限元数据 | 已实现并保留，Single Agent 复用当前工具注册表；未新增单模式 MCP 专项能力 | `agent/mcp/runtime.py`；`agent/tools/mcp.py`；`tests/test_mcp_runtime.py`；desktop-smoke |
| 真实付费模型完成能力 | 未实现验收 | 未实现验收：本轮只替代模型响应，不使用或提交真实 Key | 端到端测试使用本地 aiohttp 模型替身和生产 Provider；不将自动化结果表述为真实云模型能力 |
| 持久化完整工具对话重放 | 未实现 | 未实现：运行中完整结果回传，跨尝试保留任务证据/命令/检查点和对话摘要；不声称恢复 HTTP 流 | `run_tool_turn` 的内存 messages 与 `state.append_exchange`；M2–M5 接口规划 |

## 单模式实际调用链

```text
Desktop Task: single-agent + 一个在线 Executor
  → task.start：冻结配置，仅解析 Executor binding
  → Runtime：pending → executing；持久化目标步骤（无模型规划请求）
  → 创建/检查受管理 Worktree（现有审批）
  → 一个 OpenAICompatibleProvider 实例
  → run_tool_turn：模型推理/原生工具调用
      → 现有权限与 Approval → 真实文件/终端/Git 工具
      → 带 call ID 的真实结果 → 同一个在线模型 → 后续调用
  → verifying：生产终端工具运行冻结的独立验证命令 + Git Diff
  → 通过：awaiting_approval，展示报告/日志/Diff
  → 失败：真实证据回给同一 Executor；重复失败或上限 → paused
```

`single-agent` 作为既有配置 `strategy` 的新枚举，避免维护另一套工具执行器。继续使用现有请求日志、预算和权限；不增加隐式路由或预算调整。旧默认模式仍为 Local-first，历史任务保留原配置。原有 3 次 API 调用默认值可能不够完成多轮任务，UI 明确说明应由用户配置足够次数；显式 0 仍生效。

独立测试只能证明配置命令执行成功；不能证明任意自然语言目标已经满足，也不能防止模型修改测试来弱化断言。M2 应增加任务验收契约和测试文件变更审查，当前完成仍需用户查看 Diff。命令权限是现有应用策略，不是操作系统级沙箱。
