# v0.6 基线审计

审计日期：2026-11-04。选择基线 `da24a647dc645dadea07d82ab4ae9d6bfb76659a`（最新 origin/main），开发分支 `feature/v0.6-unified-agent`。保留原有 `.codex-attachments/`、`local_coding_agent.egg-info/`，不清理用户数据。

## 选择依据

- `feature/unified-agent-runtime` 的 `7703fc4` 是 main 的祖先，两者文件差异为空；PR #28 已由远端合并。main 的 CI `41787509665` 成功。上一轮最终功能提交的 Windows/Ubuntu 回归分别为 518/503 通过、2/17 跳过，共 520 项，前端 57、桌面 smoke 52。
- `fix/l3-recovery-loop-20261103` 基于较早的 `8edd26d`，有 3 个未合入提交。逐段核对发现，其 blocked 恢复限次、失败摘要限长、持久验证历史限长已通过 `c590190` 等提交移植到 main；main 还保留完整验证归档和 GUI 图像身份。直接合入该旧分支没有新增可靠性收益，反而可能回退新代码，因此不合并、不盲目 cherry-pick。
- 其他近期功能分支的有效主流程已被 main 收录（PR #19～#28）。本轮不以分支名称或版本号推断能力完成。

## 能力核对

| 能力 | 基线分类 | 代码、测试与真实证据 |
| --- | --- | --- |
| Chat Agent Loop / Single Agent Online | 已实现并通过真实验证 | `agent/server/main.py::run_tool_turn`；`tests/test_single_agent.py`、`test_unified_runtime.py`；上一轮两款 Qwen 的真实修改/测试闭环 |
| 统一聊天入口与自动选择策略 | 部分实现 | `unified_runtime.py` 请求约束、native agent_plan、实际工具证据；`App.tsx::submit` 已无模式选择，但执行中发送被直接拦截 |
| 多角色 Provider 路由 / MCP | 已实现但本轮真实组合验证不足 | `agent/llm/router.py`、`model_catalog.py`、`agent/mcp/`；混合 Provider、MCP 生命周期回归；不得把 HTTP Mock 说成真实 Local-first 升级 |
| 自动规划与验证 | 已实现但验证不足 | 原 PLAN_SCHEMA / VerificationEngine；Python 真实修改通过，指定优惠券仍超时/403；当前真实 React/TS 与 Electron 新入口验收不足 |
| Worktree / Git 审批 | 已实现并通过真实工具验证 | `TaskService`、`agent/tools/git.py`、`test_git_workflow_v3.py`；高级 Task 隔离执行，统一 Chat 默认当前工作区，不能混称自动隔离 |
| Checkpoint / 计划幂等 | 已实现并通过真实验证 | `task_plans.py`、`test_execution_recovery.py`；Completed 不回退、只读验证重跑、未知副作用需确认；真实 Stop/WS 恢复通过 |
| 普通统一运行的崩溃恢复 | 存在缺陷 | 启动只调用 autonomous Task 的 recover；无 Task 行的 unified execution 可能遗留 executing，尤其尚无 Plan 的运行缺少恢复入口 |
| 运行中追加需求 | 未实现 | 前端 submit 遇 runningTurnId/active Task 返回；无持久消息队列和工具安全边界应用机制 |
| 状态持久化与取消竞争 | 部分实现 | Task TRANSITIONS 和 Unified phase 已保存；协议 envelope 无 event_id，Unified phase 没有持久的取消代际保护与统一事件历史 |
| 请求追踪与预算 | 部分实现 | BudgetGuard / ExecutionBudget 已预留、结算并共享全局计数；Provider 有 HTTP/流计数，但没有 prepared→dispatch→headers→stream→complete 事件链；请求构造/预检未发出缺少统一可查询证据 |
| Windows UIA、视觉、真实 GUI | 已实现并通过真实验证，统一入口证据不足 | `agent/desktop/`、`gui_verification.py`、M3/M4/M5；历史在线 GUI 单模型/Observer 通过，不能倒填成本轮新 Runtime 的在线 GUI 验收 |
| 权限与审批 | 已实现且回归充分 | `permissions/policy.py`、`approval.py`、`_authorize_tool`、拒绝/跨工作区/进程树测试；本轮必须原地复用 |
| 上下文与持久事实记忆 | 已实现并通过真实验证 | `context.py`、`execution.py`、RepositoryInstructions；真实长历史裁剪通过，语义压缩和通用 Skills 不在本轮重复开发 |
| 诊断与历史归档 | 已实现但需扩展 | `task_diagnostics.py`、`unified_runtime.export_diagnostics`；当前摘要有界，完整 JSON 留本机；需增加事件、请求未发出原因和恢复竞争证据 |
| CI 与 Windows 桌面流程 | 已实现 | `.github/workflows/ci.yml`；双平台 Python、前端、Windows M5/smoke。安装包不在本轮自动发布范围 |

## 本轮修改边界

继续扩展原循环和两个现有账本；新增事件/追加消息仅作原执行的持久元数据，不建立平行 Provider、工具调度或执行引擎。优先补运行中追加、启动中断识别、状态代际/唯一事件、请求生命周期和有界恢复。工具权限、Worktree、模型/预算快照及用户数据保留。

## 基线命令与结果

已执行 Git status/remote/fetch --prune/branch/log/祖先检查。uv 0.11.2、Python 3.12.13、Node 24.14.0、npm 11.9.0；使用项目 uv 环境。开始源码修改前已启动完整 Python 基线，日志 `validation-reports/v06-baseline-python.log`，完成后在 acceptance-report 记录真实数量与退出码。历史成功不替代本轮未运行测试。

## 外部风险

上一轮六款允许模型最后请求返回 403，另两款完整套件各 9/10；不能假定本轮额度自动恢复。qwen3.7-plus、qwen3.8-flash 及已知同名变体继续禁用。真实测试读取本机安全存储、采用明确总预算，不写 Key，不擅自扩额、充值或切换禁止模型。必需真实模型/GUI 验收受阻时保留 PR，不绕过门槛合并。
