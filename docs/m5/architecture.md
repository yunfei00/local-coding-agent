# M5 架构

M4 PR #20 已在 Windows/Ubuntu CI 通过后合并：main 921fdd950da368d6d5f587e31071ec3641389844。M5 从此基线创建 feature/m5-codex-e2e。

自然语言目标 → 原 TaskService → 受管理 Worktree → 原 run_tool_turn / ToolLoopGuard → 原文件、终端、ProcessManager、DesktopRuntime → 独立命令 VerificationEngine → 冻结 GUI 合约 run_gui → 失败证据回到同一 Executor → 有界修复 → awaiting_approval → 用户确认报告。

不创建新的 Agent Loop、路由器、数据库或权限系统。Single Agent 不增加 Planner/Reviewer 请求；原 Local-first 配置兼容保留。所有模型调用复用原预算，工具检查不消耗模型 Token。

恢复保留 source/workspace、Checkpoint、模型解析和预算账本。应用窗口由新一轮枚举获取 opaque ID，旧句柄不重放。源工程保持原样，变更只在 Worktree；不自动接受 Diff、提交用户工程或推送。
