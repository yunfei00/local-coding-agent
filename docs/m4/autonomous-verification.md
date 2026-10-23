# 自主 GUI 验收与修复

契约放在 Task 的 GUI acceptance contract 或工程 `.lca/gui-verification.json`，例如：

```json
{
  "command": "npm start",
  "window_title": "My App",
  "timeout_seconds": 120,
  "steps": [
    {"tool":"desktop_click","arguments":{"selector":{"automation_id":"SettingsButton"}}},
    {"tool":"desktop_wait","arguments":{"selector":{"automation_id":"StatusLabel"},"state":"name","expected":"Settings ready","seconds":5}},
    {"tool":"desktop_wait","arguments":{"selector":{"automation_id":"NameInput"},"state":"enabled","seconds":5}}
  ]
}
```

可选 `vision_profile_id` 指向已保存并声明视觉能力的模型，包括 Executor 自己。配置在模型编辑前冻结；恢复沿用快照，只有暂停后明确 Apply configuration 才刷新。至少有一个独立控件状态断言，禁止模型提供 window_id 或更改上传/超时边界。窗口按精确标题及新启动 M2 Windows Job 的成员 PID 双重定位；不会操作同名其他应用。

每轮先执行真实构建/测试，然后启动应用，轮询等待目标窗口，inspect、操作、断言、截图，并在可选授权下发送视觉观察。WinForms Add-Type 编译发生在每次实际启动时。每步桌面操作最多 40 秒，枚举/截图更短；单 GUI 验收配置为 5..300 秒。异常补充本地失败截图最多 15 秒；总任务超时仍覆盖整个流程。Stop 取消当前 worker，finally 清理整个应用进程树；不可撤销已经发生的点击。

失败结果包括具体断言选择器、状态/预期、错误码及截图引用，进入现有 Single Agent 下一轮提示。`local_repairs` 是最大修复次数（默认 3），重复相同失败指纹连续两次停止；总任务/请求/验证时间、API 预算和固定 200 次外层安全界限继续生效。无独立规划阶段、无额外角色诊断。权限、环境或上传拒绝暂停，不自动消费更多模型调用。

任务 UI 展示阶段进度、轮次/修复数、最近 10 轮独立验收记录和最终 GUI PASS/NOT RUN。最终报告仍需审阅 Diff 后接受；不会自动 commit/push/merge。用户的这一开发交付任务另行明确授权了 PR/合并，与产品运行权限无关。

`manual-fixtures/m4-gui-repair/scenario.json` 复用 M3 WinForms：最初点击 Settings 后状态错误且输入框禁用。测试中模型第一轮只修状态，独立 GUI 发现 NameInput 仍禁用，下一轮收到实际失败后修复 Enabled=true，重新编译/启动并真实输入。最终 JSON 状态来自实际 WinForms 事件，截图来自 Windows PrintWindow，源工作区保持干净，修改仅在隔离 worktree。

```powershell
uv run python -m unittest discover -s tests -p test_m4_gui.py -v
```

该命令无需付费模型，在可交互 Windows 上真实执行。非 Windows 明确 SKIPPED，不伪造 GUI。仍会执行跨平台契约测试。原 Python/React+TS/Electron 工程操作测试继续完整运行；本次不把 WinForms GUI 验收等同于所有 Electron 界面验收。
