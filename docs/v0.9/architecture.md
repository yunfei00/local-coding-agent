# v0.9 架构

统一入口仍为 Electron IPC → WebSocket → `AgentServer.run_tool_turn`。没有第二套模型执行循环。工作流是在原 TaskPlanStore、ExecutionBudget、RuntimeLedger、工具权限与 Checkpoint 上增加可选元数据。

复杂任务可使用 `workflow_template` 或带 DAG 字段的 `agent_plan`；简单问答和小修改继续直接执行。角色切换发生在步骤边界，保留同一执行 ID、已完成操作、上下文、预算与测试证据。

`workflow.py` 提供图验证、角色约束与资源冲突判断；`background.py` 仅负责排队及事件转发，不执行模型或工具。原状态通过运行快照与计划保存，后台队列记录不替代执行证据。断线后客户端从原 `task.runtime.list/events` 同步。

数据迁移为 SQLite 原表添加 `workflow_json`，以及审查和后台队列表；缺失元数据的旧计划保持顺序语义。原线程、模型、API Key、任务与 Checkpoint 不清空。模型 Key 沿用 Electron 安全存储，快照只保存 credential_reference。

新 UI 沿用一个聊天入口，只扩展进度卡和已有模型设置中的可展开区。
