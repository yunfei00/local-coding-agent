# Windows 源码使用

仓库根目录执行；已有未提交修改先保留，不执行 reset/clean：

```powershell
git switch main
git pull --ff-only origin main
uv sync --locked
npm --prefix desktop ci --no-audit --no-fund
npm --prefix desktop run dev
```

需 Windows 交互桌面、Git、uv、Node 22/npm；无需独立 GPU。Python 使用项目 .venv，由 uv 管理。无本轮安装包/Portable，旧 v0.4.2 安装包不会自动包含源码变更。

1. Settings → Models & Routing 使用已有连接和安全 Key；选择 Default Chat Model。Chat 下拉框按连接分组搜索，每 Thread 独立保存。
2. Open project 打开自己的工程或 fixture 实验副本，New thread 创建会话。Task → Single Agent (online)，选择 Executor。需要独立视觉时选择 Task Vision Observer；若不上传图片，使用确定性 UIA。
3. 输入具体目标、保留项目测试命令。fixture 已提供 .lca 验收文件，模型不应修改它们。模型调用受当前预算约束，复杂任务可能在默认调用数用尽后暂停；查看具体限制，不自动追加。
4. 启动 Task，审阅每次文件、命令、桌面及图片上传审批；Save 等风险操作仍需显式授权。只允许操作受控测试窗口；不要将私人截图发往模型。
5. 展开工具卡查看终端输出、Task timeline 看状态与修复轮次，Screenshot artifacts 本地预览失败/成功截图；Completion report and Git review 查看 Diff。
6. 只有独立命令和 GUI 全部通过才进入 awaiting_approval。检查每项 PASS、Diff、实际应用行为后 Accept verified report；这不是自动提交或合并工程。失败/无验证不能看作完成；不接受可 Cancel，Worktree 保留供检查，不覆盖源工程。
7. 运行时用 Cancel active task / Pause active task；恢复前检查 Worktree 与 Checkpoint，明确确认 Resume。旧窗口不会复用。改 Settings 后新 Task 使用新值，暂停旧 Task 需 Apply configuration 才更新快照。

完整可运行实验工程与自动入口见 manual-fixtures/m5-electron-e2e/README.md。本机 HTTP Mock 不使用已保存的真实密钥。真实模型测试须用户明确授权费用与图片传输。本轮已按用户授权执行真实 Qwen Flash 和 Qwen Max，实际修改文件和工程检查成功，但完整在线闭环仍未通过；Max 视觉尚未运行。最新精确结果和当前分支命令见[真实在线验收](../validation/real-online-agent-acceptance.md)，本机内核内存异常及恢复流程见[环境阻断](../validation/windows-kernel-memory-blocker.md)。本轮尚未合并 main，验证本轮修复需使用该记录中的功能分支；上述 main 命令只更新已合并版本。
