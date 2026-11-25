# 执行锁安全恢复（人工离线）

锁位于实际 LCA_DATA_DIR（默认桌面 userData）下的 engine-execution.lock。owner 为 PID:随机令牌。PID 不存在不能证明子进程已经退出，禁止自动抢占。

1. 保存任务诊断与 Checkpoint。关闭所有使用同一数据目录的桌面实例、Python Agent 和 OpenCode。
2. 在 Windows 任务管理器/进程树核对本次 Agent、Sidecar 及其启动的工具子进程全部停止。若不能确认，重启 Windows，并在启动任何 Agent 前恢复。
3. 确认实际数据目录，保留锁目录作为证据；在所有执行进程停止的前提下，将 engine-execution.lock 重命名为 engine-execution.lock.recovered-日期时间。不要删除任务数据库或 Checkpoint。
4. 重启应用，检查任务状态，人工确认工作区后恢复；禁止自动重放工具操作。

此流程不是在线自动恢复，也不是进程树终止证明。若多个实例使用不同数据目录，当前协议不提供跨目录互斥。正式 OpenCode 执行仍禁止。
