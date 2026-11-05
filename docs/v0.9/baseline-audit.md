# v0.9 基线审计

审计时间：2026-11-05。远程 `main`：`7dbec0a5839f6af8b8621374c0e0f2b17108c200`。开发分支：`feature/v0.9-autonomous-workflow`。

## 工作区保护

获取远程后未发现更新。创建分支前仅有用户原有未跟踪目录 `.codex-attachments/`、`local_coding_agent.egg-info/`，保留原状。不执行 reset、clean、强制推送。

## 复用与缺口

| 模块 | 实际基线 | v0.9 扩展点 |
| --- | --- | --- |
| Unified Runtime | `AgentServer.run_tool_turn` 已统一问答、修改与复杂计划 | 继续使用此循环，加入角色约束和交接 |
| TaskPlanStore | SQLite 持久化、真实工具证据、完成不可回退、Checkpoint | 兼容添加 DAG、验收标准、角色、重试与预算元数据 |
| TaskRuntime/TaskService | 原有自主任务状态、配置快照、恢复、修复、升级 | 与统一入口保持兼容，不建立另一套模型调用循环 |
| Context/ExecutionBudget | 上下文压缩、持久化工具/Token/时间限制、重复操作保护 | 复用账本，角色切换不能清零 |
| 模型路由 | 三态能力证据、冻结快照、有界回退、禁止模型拦截 | 角色选择和任务模型白名单须独立于用户原始配置 |
| 项目上下文 | 长期记忆、增量检索、脱敏、项目隔离 | 直接复用 |
| 工具与审批 | ToolRegistry、MCP、权限、未知副作用恢复审批 | 角色权限是额外限制，不能扩大既有权限 |
| Git | 工作树、Diff、审批、提交流程 | 复用交付证据，禁止模型绕过 Git 审批 |
| Windows GUI | UIA、视觉回退、窗口授权、资源门槛、进程清理 | 串行回归，桌面焦点互斥 |
| WebSocket | 连接关闭会取消其拥有的 turn 并暂停任务 | 后台任务不能由传输连接决定生命周期 |
| 桌面界面 | 单聊天入口、计划与验证摘要、恢复/诊断 | 在现有可展开区展示角色及依赖进度 |

## 风险及兼容策略

1. 旧计划只有顺序位置，不能直接把它解释为可并发 DAG；旧数据保持顺序语义。
2. 工具成功证据只能来自持久化执行记录，角色模型的文字不能替代测试结果。
3. 断线恢复必须避免重放未知副作用；保留现有恢复审批。
4. 在同一 SQLite 中添加可选元数据，不能删除线程、计划、模型或凭据。新增字段缺失时按旧语义读取。
5. 低内存默认串行；并行必须先能证明资源不冲突。

## 本轮基线

`uv run --locked python -m unittest discover -s tests -p test_task_plans.py -v`

结果：6 PASS，0 FAIL，0 SKIP。这是本轮实际运行结果；v0.8 历史全量结果不冒充 v0.9 验收。

## 计划修改位置

`agent/task_plans.py`、`agent/llm/planning.py`、`agent/core/unified_runtime.py`、`agent/server/main.py`、既有 Runtime 配套调度模块、桌面进度组件与 IPC 类型、回归测试和验证驱动。

本文是改动前审计，未实现和未执行的项目不计为通过。
