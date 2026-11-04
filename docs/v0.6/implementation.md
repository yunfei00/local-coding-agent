# v0.6 实现记录

基线与分支选择见 [基线审计](baseline-audit.md)。本轮在原 Agent Loop 上扩展，不新增执行器、Provider 系统或任务数据库。

## 已实现

- `agent/core/runtime_events.py`：同库事件元数据、唯一事件 ID、请求关联、追加消息幂等队列、事务应用、取消代际屏障、中断恢复与完整事件导出。
- `agent/server/main.py`：统一入口接受 `turn.append`；完整工具批次后应用；启动/恢复互斥；无 Plan 运行也可显式恢复原目标、预算和模型快照；恢复次数有界。
- `agent/core/orchestration.py`：高级 Task 复用相同追加队列、原计划与 Worktree；提供线程范围事件查询及导出。
- `agent/core/execution.py`、`task_runtime.py`、`task_plans.py`：复用既有预算、计划与状态持久化，允许外层事务原子保存。
- `agent/llm/base.py`、`openai_compatible.py`、`ollama.py`、`router.py`：可选请求元数据回调；明确区分未发送、未知发送和已收到响应；仅确定未发送的连接失败允许有限重试。
- `desktop/src/App.tsx`、Electron IPC：运行中追加按钮与 Stop 同时可用；失败保留输入；追加生效后创建后续回复段；无 Plan 恢复入口；按需事件诊断。
- 原有 Worktree、Git 审批、工具权限、MCP、Pinned Files、Windows UIA 与视觉工具保留。
- 真实验收进一步修复：显式增加执行预算同步作用于该运行的 API 快照，增量可编辑，并可选择追加本运行的全局预检上限；费用上限与既有消耗不重置。
- 未确认操作有独立审阅入口及原审批，状态是 reviewed 而非 succeeded，不能作为步骤完成证据；后续修改仍要求明确审批。等待审批的 RPC 不再阻塞同一 WebSocket 的审批响应。
- 所有计划步骤已完成但最终验证受阻时，同页恢复继续使用原运行 ID；不创建平行任务。高级 Task 继续走原 Worktree 恢复。
- 明确要求点击/输入的桌面请求不再因包含 desktop_inspect 而被误判成只读分析；必须有真实桌面动作证据，未配置独立 GUI 合约时显示待独立验收。`.runtime` 应用运行数据不当作源码变更。

## 数据兼容与边界

新增表只有 `runtime_events` 与 `runtime_followups`，均以既有 run/thread/plan 标识关联；不删除旧 Task、历史消息或 Checkpoint。旧运行没有保存原目标时明确拒绝猜测恢复，历史仍可查看。

追加消息正文是本机私有会话数据，单条最多 4000 字符，待处理最多 32 条/32000 字符；普通统一运行的合并目标最多 16000 字符。事件日志只保存消息 ID、计数和生效边界。

完整验收状态以 [验收报告](acceptance-report.md) 为准。实现存在不等于真实在线与 GUI 组合验收已通过。
