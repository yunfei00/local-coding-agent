# v0.4 自主任务设计

## 执行路径

自主任务是现有持久化 Task Plan 的扩展，ID 与计划一致。Server 接收任务请求，在原审批路径创建受管理 Worktree，然后按角色调用 Provider。Planner 输出结构化步骤；Executor 使用原 `run_tool_turn`、ToolRegistry 和 PermissionPolicy 执行。Verification Engine 直接调用相同授权工具入口运行用户配置或项目检测得到的命令；失败摘要进入下一次本地修复。达到修复阈值或重复循环后，仅向强模型发送有限的目标、Diff、失败和已尝试摘要，不授予工具。建议交还 Executor。最后独立验证、Review、报告和 Git 审批门禁。

状态：pending → planning → executing → verifying → awaiting_approval → completed；失败可进入 repairing/escalating，任何活动状态可暂停、失败或取消。恢复沿用同一计划、执行指纹和预算账本。完成仅表示已验证且用户确认报告，不表示自动提交、推送或合并。

## 预算与故障

每个 API 请求在发送前原子预留输入保守估算和最大输出，计入任务及全局限制。超时、取消和未知结果保留预留；完整可信 Usage 结算后释放多余 Token 预留，请求未发送则释放入账。请求有输出限制和超时；Provider 不能保证精确 Token/货币硬上限时界面必须明确精度。耗尽后暂停，无自动追加预算或无限 API 重试。Planning 使用独立持久化计数和重复响应检测，升级不再重置规划上限。

配置与任务快照不含密钥，继续使用 Electron 安全存储和 Agent session/environment。验证日志保存在数据目录，模型只得到有限摘要。活动任务配置与后续设置隔离。

## 测试和发布门禁

新增状态机、预算、路由、实际工具循环和协议测试；复验 v0.3，执行 Electron 实际 UI 自动化和 Windows 打包。真实模型结果单列；没有真实 API 验收或真实本地修复证据时保留分支，不把 Mock 验收扩大为真实环境结论。
