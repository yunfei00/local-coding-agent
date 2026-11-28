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
| P6 独立更新 | PARTIAL | 更新器 6 项回归、锁定 v2.2.6 真进程协议探测通过，2717 ms；未真实升级到其他发布版本 |
| P7 安全和预算 | PARTIAL | 网关专项通过 HTTP 401/403/429/500、拒绝超预算以及清理错误响应中的凭据。文件边界专项使用真实 Windows junction。`credential_scan.py` 扫描 681 个跟踪文件，无发现；安全矩阵有缺口 |
| P8 Windows 候选 | PARTIAL | 权限修复前的本机候选均已生成。其解包版本两次无 SDK 启动，实测使用 OpenCode v2.2.6 和原生读取，证据在 `build/packaged-v2-unpacked-2e1cc921bfe3445c8d9f06a82136091b/report.json`。需验证权限修复后的候选和 clean-profile Setup |
| P9 全量回归 | PARTIAL | [df07383 的 CI](https://github.com/yunfei00/local-coding-agent/actions/runs/46102821030) Ubuntu 通过，Windows 旧桌面脚本在历史 Python 协议重试断言失败；初次本机 `check.py` 受 Git 继承环境影响，桌面各阶段通过 |
| P10 中文文档 | PASS | 本目录文档随候选分支交付 |

Windows 专项使用原有真实 WinForms fixture。首次独立验收捕获故障，修复后复验通过，两轮均确认进程退出。`test_opencode_data_service.py` 最近完整专项为 5 项通过，33.973 秒，另覆盖真实 WebSocket 审批和暂停时的子进程清理。捆绑后端的 UIA 测试也通过，证据为 `build/packaged-v2-gui-smoke.json`。

曾在隔离 fixture 复现跨项目文件内容被发送到环回模型替身。修复后正式 Mock 端到端通过了相同边界检查。应用会通过锁定版的权限事件核对真实路径，拒绝外部目录和指向外部的 junction；这项回归未覆盖操作系统级沙箱、任意 shell 行为或全部第三方扩展。
