# 旧 Agent 清理

桌面启动 Python 时传入 `--data-service`。该模式拒绝旧 `turn.start`、`turn.append`、`task.start`、`task.resume`、`task.continue`、`task.append`。Composer 和 Task IPC 使用 OpenCode。

桌面实验引擎切换和聊天回退入口已移除。独立 Python 启动模式仍保留，历史测试仍依赖它。需要将历史产品验收迁移后再删除旧执行模块。

保留项目和 Thread 数据、审批、Git worktree、系统凭据引用、模型配置、预算 SQLite 台账、进程管理、Windows UIA 和验收。依赖审计见[最终审计](final-audit.md)。
