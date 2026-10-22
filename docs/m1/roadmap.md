# M2–M5 接口规划

以下为 M1 之后的建议接口顺序，尚未实现，不是既有功能承诺。后续阶段应优先增强单在线模型执行可靠性，保留多模型的兼容接口。

| 阶段 | 目标与拟定接口 | 复用边界 | 进入/完成条件 |
| --- | --- | --- | --- |
| M2：任务验收与执行契约 | 在 `task.start` 增加版本化 `acceptance`（验收命令、受保护基线、测试变更策略）；定义 `TaskOutcome` 区分模型结束、验证通过和用户接受 | 继续使用 `TaskRuntimeStore`、`VerificationEngine`、工具结果结构；旧请求缺省语义保持兼容 | 入口：M1 全量与两系统 CI 通过；出口：真实多文件修复、失败恢复、测试被弱化与验收不完整均有测试，真实在线模型另行验收 |
| M3：上下文与持久会话 | `ConversationStore.append_tool_exchange(request_id, assistant, results)`；完整 call/result 组持久化；可替换 `ContextCompressor`，返回来源和省略清单 | 保留 Provider 的 `stream_chat` 与 `ProviderChunk`；不会改造为模型路由 | 完成条件：重启后不重放已完成的写操作；超长工具输出不会破坏协议；对话/文件内容遵守本地存储策略 |
| M4：工作区审查与权限 | `WorkspaceSnapshot`、`ChangeSet`（tracked/untracked、base SHA、摘要、测试变更）；版本化 Approval scope，任务报告关联不可变快照 | 沿用 Worktree、Git Diff、权限模式、ApprovalManager 和全工作区 fingerprint | 完成条件：审查后文件变化会使验收过期；拒绝/取消无残留子进程；明确应用权限与 OS 沙箱的区别 |
| M5：桌面开发体验与系统验收 | 版本化 `task.timeline`/`task.artifacts` 查询，统一推理摘要、工具、错误、日志与 Diff 导航；真实在线模型环境回归入口 | 沿用 WebSocket envelope、Task 快照、desktop-smoke；Key 继续由 safeStorage 管理 | 完成条件：Windows 桌面完整交互回归、真实模型人工场景记录、跨平台核心 CI；发布需另行授权 |

共同约束：错误保持稳定 `code` 与阶段，取消沿用任务/轮次 ID；Provider 只解释协议，工具执行只经过 Registry 与权限；新增数据库字段/消息需兼容旧任务。测试只替换模型，不伪造磁盘或终端结果。

M1 已提供可启动 M2 的工具执行、验证、取消和诊断基础。真实在线模型的质量、公司网关细节、OS 级沙箱、自动应用/合并任务 Worktree 均不计为已完成。若要以公司模型作为 M2 的上线依据，应单独执行真实在线验收并记录结果，不使用 Mock 测试替代。
