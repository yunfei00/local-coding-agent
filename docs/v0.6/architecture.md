# v0.6 统一执行与可靠性设计

基于最新 main 的 `AgentServer.run_tool_turn`、TaskService、TaskPlanStore、ExecutionBudget、BudgetGuard 和 VerificationEngine 扩展，不新增执行循环。

本轮扩展（实现和验收记录见 implementation、acceptance-report）：

1. 在同一 SQLite 中增加唯一事件日志和持久追加消息元数据，关联原 run/plan/thread/request。状态与事件尽量同事务写入，重复客户端 ID 幂等，代际隔离旧取消/重连事件。
2. 执行中消息先持久确认，在完整模型/工具批次结束后的下一次模型请求前生效；不能截断工具参数或插入未配对 tool 消息。保留原工具审批，追加消息不是提高权限。
3. 启动识别遗留的 unified running/verifying，标记可恢复中断，未结算请求保留保守预留。恢复使用原目标/模型/预算及工作区，未知副作用仍走原检查和确认。
4. Provider 通过可选元数据观察回调报告 prepared、dispatched、headers、streaming、completed、failed；仅记录计数/错误类型，不保存正文。预算/构造失败也明确记录未发送，网络尝试与已确认 HTTP 发送分开。
5. 取消事件成为当前尝试的终止屏障。显式恢复建立新尝试；不允许迟到回调将原 cancelled 改成 running/completed。恢复预算和无进展指纹持久化，不能每次重启清零。

统一界面沿用现有聊天卡片/按需面板，只增加“追加需求已排队/已生效”、中文恢复原因和请求追踪入口。高级 Task 与旧线程兼容；协议 1.0.0 以可选字段/新消息类型扩展。实现完成情况以 implementation 和验收报告为准，本设计不表示已完成。


v0.8 扩展：见 [智能模型与项目上下文架构](../v0.8/architecture.md)。当前验收状态以 v0.8/acceptance-report.md 为准；原功能保留。
