# 上下文与长任务连续性

复用 ContextBudgetManager 和持久 ExecutionBudget。保留系统安全指令、最新目标、计划状态、真实工具证据和恢复信息，优先裁剪可重建历史。完整工具调用/返回成对保留，模型摘要不能替代真实工具执行账本。

统一 Runtime 默认压缩阈值 0.85；可用 LCA_CONTEXT_COMPRESSION_THRESHOLD 设置 0.5–1。项目记忆、检索、RepositoryMap 分别限于可用来源预算的 15%、20%、30%，计划与显式上下文优先。压缩仍不足时报告实际构成，不能通过增加累计 API Token 预算冒充扩展模型上下文。

LCA_EXECUTION_TOOL_CALLS 默认 1000（最大 10000）；LCA_EXECUTION_STAGE_TOKENS 默认 50000000（最大 1000000000）。计数与阶段保守预留持久化，恢复不会清零。阶段预留用于硬保护，不能标作真实计费；真实 Token Usage 沿用请求账本。

原 ToolLoopGuard、计划操作指纹和无进展停止机制继续生效。成功副作用不自动重放，未知结果要求检查；只读验证允许安全重跑。模型切换不创建新运行或重置预算。恢复及压缩状态在现有进度卡展示。
