# v2.0.0 实际验收结果

记录日期为 2026 年 11 月 28 日。当前仍有发布阻断项。

| 阶段 | 结果 | 命令、耗时及证据 |
| --- | --- | --- |
| P0 代码审计 | PASS | [最终审计和基线 CI](final-audit.md) |
| P1 正式执行迁移 | PARTIAL | 聊天和 worktree Task 使用 OpenCode，Plan 和跨重启恢复仍有缺口 |
| P2 旧内核清理 | PARTIAL | 桌面 Python 确实进入数据模式，独立 Python 执行仍存在 |
| P3 真实 Ollama | PARTIAL | `node scripts/validation/opencode/desktop-live.cjs`，CPU 上 `qwen3:4b` 对话和重启历史通过，120251 ms，`validation-reports/v2-opencode-desktop-live.json`。同脚本 `--project-write` 超时失败，616051 ms，`validation-reports/v2-opencode-desktop-live-tool.json` |
| P4 在线开发 | NOT RUN | 付费请求、Token 和费用均为零 |
| P5 Mock 正式产品回归 | PARTIAL | `node scripts/validation/opencode/desktop-live.cjs --mock` 通过，24230 ms，`validation-reports/v2-opencode-desktop-mock.json`。实际 Electron、锁定 OpenCode、一次性文件审批、跨项目读取拦截、正式 Task、隔离 Git worktree、独立 unittest、Diff、重启历史均有证据；20 项矩阵未完成 |
| P6 独立更新 | PARTIAL | 更新器 6 项回归和锁定 v2.2.6 真进程协议探测通过，2717 ms。用 GitHub CLI 下载的官方归档实测 v2.2.5 → v2.2.6 → v2.2.5，通过 SHA256、解压、指针持久化及回退后重启，13464 ms。应用原生 HTTPS 传输在本机超时 |
| P7 安全和预算 | PARTIAL | 网关专项通过 HTTP 401/403/429/500、拒绝超预算以及清理错误响应中的凭据。文件边界专项使用真实 Windows junction。`credential_scan.py` 扫描 681 个跟踪文件，无发现；安全矩阵有缺口 |
| P8 Windows 候选 | PARTIAL | 本机候选在 `build/v2-candidate-reviewed`。Portable 两次无 Git、Node、uv、Python 的独立启动和 `read` 通过，退出后零候选残留进程。Actions 已生成两个二进制，基础 Portable 启动通过，打包版聊天超时，Setup 未执行。[GitHub Actions Artifact](https://github.com/yunfei00/local-coding-agent/actions/runs/46106043867/artifacts/15248154934) |
| P9 全量回归 | FAIL | 本机 Windows `uv run --no-sync python -u -m unittest discover -s tests -v` 运行 779 项，2 项跳过，耗时 1013.661 秒，`validation-reports/v2-python-full-live.log`。桌面 173 项通过。Ubuntu CI 通过。Windows CI 在旧桌面脚本的历史 Python 协议重试断言失败。[e16e853 的 CI](https://github.com/yunfei00/local-coding-agent/actions/runs/46106047599) |
| P10 中文文档 | PASS | 本目录文档随候选分支交付 |

Windows 专项使用原有真实 WinForms fixture。首次独立验收捕获故障，修复后复验通过，两轮均确认进程退出。`test_opencode_data_service.py` 最近完整专项为 5 项通过，33.973 秒，另覆盖真实 WebSocket 审批和暂停时的子进程清理。捆绑后端的 UIA 测试也通过，证据为 `build/packaged-v2-gui-smoke.json`。

曾在隔离 fixture 复现跨项目文件内容被发送到环回模型替身。修复后正式 Mock 端到端通过了相同边界检查。应用会通过锁定版的权限事件核对真实路径，拒绝外部目录和指向外部的 junction；这项回归未覆盖操作系统级沙箱、任意 shell 行为或全部第三方扩展。

升级与回退证据位于 `build/opencode-update-e2e-8645176fce7349e78cd87e84190841ea/cached-transfer-report.json`。Windows Portable 两轮证据在 `build/packaged-v2-reviewed-portable-1d6f0f132013481885a7adad40cb37b6/report.json`。本机已有正式安装，因此 Setup 使用干净 CI Runner 验证。

| 本机候选 | 大小（字节） | SHA256 |
| --- | ---: | --- |
| `Local-Coding-Agent-2.0.0-x64-Setup.exe` | 220338511 | `4fa7633682e9fa2ae43c709e4bc0808825fcd87a59c7c4b323237e581a821da5` |
| `Local-Coding-Agent-2.0.0-x64-Portable.exe` | 220108458 | `4ea228fc9344806df149802b2dc50e19e1a588f4c328d11225a42ee5dc63300a` |
