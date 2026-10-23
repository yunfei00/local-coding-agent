# M5 综合验收

模型决策采用本机 HTTP Mock，实际文件、Worktree、npm、Electron、Windows UIA/输入/截图、独立断言均执行。真实付费模型推理 NOT RUN；用户历史百炼五项 PASS 不作为本轮测试。

| 场景 | 自动证据 |
| --- | --- |
| Python 真修复与 unittest | test_m2_projects.py，原工程与 Worktree 对比 |
| React/TypeScript 真修复 | test_m2_projects.py 的 typecheck/test/build |
| Electron 双缺陷闭环 | test_m5_electron_e2e.py：真实 React 受控输入、保存与两次不同值 |
| JPEG 指定观察模型 | 本机 HTTP 核对真实 JPEG、m5-vision、无 tools |
| 第一轮不完整修复 | 真实 GUI 状态断言失败、失败截图反馈同 Executor |
| 第二轮修复 | 再构建、再启动、GUI 断言与 saved.json 一致 |
| Stop / Pause | 实际 Electron 与已记录 renderer 子进程退出 |
| Resume | 同 Worktree 继续，已完成 apply_patch 次数不增加，预算继续累计 |
| 模型独立与切换 | M4 test_unified_chat_profiles.py 和 desktop-smoke，实际双连接同名模型 |
| 上传拒绝 | Observer HTTP 次数不增加，任务 paused / APPROVAL_DENIED |
| 重启恢复 | 新 Agent 实例读取相同 Task 快照/预算；desktop-smoke 实际重启项目、Thread、配置 |
| 契约篡改 | 改 start / GUI 合约后暂停，不以模型声明完成 |

复现（从仓库根目录）：

```powershell
uv sync --locked
npm --prefix desktop ci --no-audit --no-fund
uv run python -m unittest discover -s tests -p test_m5_electron_e2e.py -v
uv run python scripts/validation/check.py
node scripts/validation/desktop-smoke.cjs
uv run python scripts/validation/credential_scan.py
git diff --check
```

Windows CI 设置 LCA_REQUIRE_INTERACTIVE_DESKTOP=1，没有交互桌面会失败而非静默跳过；Ubuntu 不宣称 Windows GUI PASS。保留脱敏 m5-electron-e2e.json，包含 Diff、真实断言、修复轮次、HTTP 图像字节数和清理结果，无原图或 Base64。最终数量与 CI 链接在门禁结束后记录。

## 本机专项实测

2026-10-23：m5-bounded-full-scenario.log，3 项通过、0 失败，167.233 秒。主用例为真实 Electron/Windows 闭环，另两项为启动脚本反篡改和契约/旧快照兼容测试。不是三项都冒充 GUI 操作。

首轮真实 typecheck、2 项 Vitest、build、diff 检查通过，但保存状态 GUI 断言报 DESKTOP_WAIT_TIMEOUT，不能验收。相同 Executor 收到真实失败后补第二处源码；重新运行命令和新 Electron GUI，两个不同输入的状态、持久化和 saved.json 全部通过，进入 awaiting_approval。共两轮修复、一次追加修复；源工程仍保留原缺陷。

此专项包含后续生命周期验证，共本机 HTTP coder 42 次、vision 3 次；次数随真实启动轮询可能变化，不是固定的在线请求数。3 次视觉传输来自当前实际捕获（首次工具观察、独立成功验收、恢复后新窗口验收），并非历史图像重复发送。每次新捕获仍经过授权；拒绝上传场景没有新增 Observer 请求，状态按预期 paused / APPROVAL_DENIED。

Pause 与 Stop 均核对实际 Electron main 和记录的 renderer/utility 子进程退出；Resume 保留两次 apply_patch，不重放；重启新 Agent 保留项目、Thread 模型、Task、执行记录、角色快照和累计预算。报告 m5-electron-e2e.json 为本机脱敏证据，图片只留本机。

M5 [PR #21](https://github.com/yunfei00/local-coding-agent/pull/21) 的最终 Windows/Ubuntu CI 和完整 check.py/desktop-smoke 仍为合并门禁，不能用此专项代替。真实在线模型推理 NOT RUN。
