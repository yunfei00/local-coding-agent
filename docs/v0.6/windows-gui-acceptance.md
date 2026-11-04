# Windows GUI 验收

平台：Windows 11，Python 3.12（uv）、Node 24、Electron 38。保留既有 manual-fixtures 路径与测试契约。

## 三层证据

1. Python 原生 GUI/M3/M4/M5：实际窗口、UIA、输入、截图与 Observer 测试；要求交互桌面，不能用 Mock 结果替代。
2. Electron desktop-smoke：真实桌面程序/Renderer/IPC/后端/HTTP 传输，模型由本地 HTTP Mock 控制。覆盖统一聊天、真实文件及 unittest/Diff、设置、审批、取消、恢复、Git/Context/MCP 等。
3. 在线模型 + 真实 GUI：使用已通过能力检查的 qwen3.7-flash，经统一聊天入口调用实际 Windows UIA；以新随机显示名、Saved 状态、磁盘持久化值和本机截图交叉验证，不允许用直接写入 saved.json 代替界面动作。

本轮 desktop-smoke 已通过 53 项、无跳过，扩展检查运行中追加消息、一次应用、请求事件关联和完整事件 JSON 导出。真实在线模型已完成 Electron 源码修复、typecheck/test/build，独立启动窗口编辑保存；另一次真实在线任务使用 UIA 完成定位、点击、输入、保存、读取状态、截图和停止进程。输入框按隐私策略在截图中遮盖，底部显示的是随机测试值。

![在线模型操作后的实际窗口](evidence/windows-gui.png)

截图 SHA256：`a9bdc00cd6a89a74bb5afec8e1c36b593fe4de5cc997e2e527c27d1149d2ba5d`。这是窗口截图，没有上传给模型，不代表真实视觉推理验收。对应元数据见 [脱敏在线证据](evidence/live-cases.json)。

未附独立 GUI 合约的交互在产品中保持待独立验收；本报告的 GUI PASS 来自外部实际结果检查。高级 Task 的已有冻结 GUI 合约与 Observer 回归保留，不能把本地 HTTP Mock Observer 说成真实视觉模型。

命令：

```powershell
$env:LCA_REQUIRE_INTERACTIVE_DESKTOP='1'
uv run --locked python -m unittest discover -s tests -p test_m5_electron_e2e.py -v
npm --prefix desktop run build
node scripts/validation/desktop-smoke.cjs
```

只操作测试程序及隔离目录，不删除用户历史、关闭无关应用或自动恢复用户任务。

本机曾在并行 Vitest/多个桌面运行叠加时遇到 VirtualAlloc/V8 内存失败，原始失败报告保留。后续采用串行桌面验收、单 worker 前端测试；一次 React 进程回归在资源恢复后单独复测通过。CI 的首次冷启动窗口枚举超时已按真实 UIA 工具允许的 60 秒预算处理，保留所有窗口、输入、截图、停止和恢复断言，没有跳过真实 GUI 测试。

最终构建的 desktop-smoke 已再次 53 项全部通过，`8329cc1` 的 push/PR 两次 Windows CI 亦通过。但新增的纯 GUI 结果语义补充在线用例在资源耗尽时无响应，标记 BLOCKED，详见 [验收报告](acceptance-report.md)。已有动作成功不替代这项最终语义验收，因此当前保留 PR，未合并 main。
