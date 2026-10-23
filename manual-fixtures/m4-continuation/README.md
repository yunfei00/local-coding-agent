# 有界续跑与恢复演示

本目录提供已有真实工程的组合入口，不复制第二份 GUI 或 Agent。只脚本化模型决策；文件、Git、终端、SQLite、审批与 Windows GUI 均使用真实实现。

在仓库根目录运行：

```powershell
uv run python manual-fixtures/m4-continuation/run.py
```

依次执行：

1. 复用 `v04-local-first`，19 次模型决策中实际读取/修复 calculator、执行 unittest、检查 Git Diff，跨过默认 16 轮。
2. 累计调用/Token/活动时间与续跑数上限，恢复不清零；Stop 清理真实进程；重复 start_process 不重复启动。
3. 已完成写入不重放、blocked 真实目录探测、未知副作用新审批、工具失败诊断、验收文件防改。
4. Windows 上复用 `m3-windows-gui` 标准 WinForms Edit，原 Single Agent 跨 slice 枚举、点击、输入、快捷键、滚动、截图，外部读取真实 JSON 状态并取消清理。
5. 复用 `m4-gui-repair/scenario.json`：实际 GUI 失败→源码修复→重新编译→确定性 GUI 验收。

非 Windows 明确跳过 Windows API 用例，仍运行跨平台部分。Windows 需当前用户可交互桌面，系统拒绝焦点则报告失败，不假装完成 SendInput。GUI 套件请串行执行，避免并行争抢前台。Tkinter Pane 输入不在验收范围。

不读取真实 API Key、不发送真实模型请求，不提交截图。全量验证仍使用 `uv run python scripts/validation/check.py` 和 `node scripts/validation/desktop-smoke.cjs`。
