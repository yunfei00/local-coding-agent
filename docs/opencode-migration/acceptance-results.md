# v2.0.0 实际验收结果

记录日期为 2026 年 11 月 28 日。当前仍有发布阻断项。

| 阶段 | 结果 | 命令、耗时及证据 |
| --- | --- | --- |
| P0 代码审计 | PASS | [最终审计和基线 CI](final-audit.md) |
| P1 正式执行迁移 | PARTIAL | 聊天和 worktree Task 使用 OpenCode，Plan 和跨重启恢复仍有缺口 |
| P2 旧内核清理 | PARTIAL | 桌面 Python 确实进入数据模式，独立 Python 执行仍存在 |
| P3 真实 Ollama | PARTIAL | 本机 CPU `qwen3:4b` 对话和重启历史通过，120251 ms。默认 4096 上下文写入超时，616051 ms。8192 上下文、非默认环回端口真实写入通过，241790 ms。独立 Git 工程的完整 Task 在 609438 ms 超时并保留 worktree，未取得通过的验收结果 |
| P4 在线开发 | NOT RUN | 付费请求、Token 和费用均为零 |
| P5 Mock 正式产品回归 | PARTIAL | 正常 `--mock` 通过，14864 ms，`validation-reports/v2-opencode-desktop-mock.json`。丢弃文本和结束 `--drop-completion` 通过，22895 ms。仅丢弃文本 `--drop-text` 通过，15646 ms，`validation-reports/v2-opencode-desktop-text-recovery.json`。实际审批、项目边界、原生写入和终端、独立 unittest、Diff 与重启历史均有证据；20 项矩阵仍有缺口 |
| P6 独立更新 | PARTIAL | 更新器 6 项回归和锁定 v2.2.6 真进程协议探测通过，2717 ms。用 GitHub CLI 下载的官方归档实测 v2.2.5 → v2.2.6 → v2.2.5，通过 SHA256、解压、指针持久化及回退后重启，13464 ms。应用原生 HTTPS 传输在本机超时 |
| P7 安全和预算 | PARTIAL | 网关专项通过 HTTP 401/403/429/500、拒绝超预算以及清理错误响应中的凭据。文件边界专项使用真实 Windows junction。`credential_scan.py` 扫描 681 个跟踪文件，无发现；安全矩阵有缺口 |
| P8 Windows 候选 | PARTIAL | 本机候选在 `build/v2-candidate-reviewed`。Portable 两次无 Git、Node、uv、Python 的独立启动和 `read` 通过，退出后零候选残留进程。Actions 已生成两个二进制，基础 Portable 启动通过，打包版聊天超时，Setup 未执行。[GitHub Actions Artifact](https://github.com/yunfei00/local-coding-agent/actions/runs/46106043867/artifacts/15248154934) |
| P9 全量回归 | FAIL | 本机 `scripts/validation/check.py` 四阶段通过，Python 运行 779 项并跳过 2 项，桌面 174 项通过，证据为 `validation-reports/20261128-154351-790078.json`。Ubuntu CI 通过。Windows 正式产品 Mock 与丢失完成事件专项均通过，旧桌面脚本在历史 Python 协议重试断言失败。[bd02aca 的 CI](https://github.com/yunfei00/local-coding-agent/actions/runs/46123961373) |
| P10 中文文档 | PASS | 本目录文档随候选分支交付 |

Windows 专项使用原有真实 WinForms fixture。首次独立验收捕获故障，修复后复验通过，两轮均确认进程退出。`test_opencode_data_service.py` 最近完整专项为 5 项通过，33.973 秒，另覆盖真实 WebSocket 审批和暂停时的子进程清理。捆绑后端的 UIA 测试也通过，证据为 `build/packaged-v2-gui-smoke.json`。

曾在隔离 fixture 复现跨项目文件内容被发送到环回模型替身。修复后正式 Mock 端到端通过了相同边界检查。应用会通过锁定版的权限事件核对真实路径，拒绝外部目录和指向外部的 junction；这项回归未覆盖操作系统级沙箱、任意 shell 行为或全部第三方扩展。

升级与回退证据位于 `build/opencode-update-e2e-8645176fce7349e78cd87e84190841ea/cached-transfer-report.json`。Windows Portable 两轮证据在 `build/packaged-v2-reviewed-portable-1d6f0f132013481885a7adad40cb37b6/report.json`。本机已有正式安装，因此 Setup 使用干净 CI Runner 验证。

| 本机候选 | 大小（字节） | SHA256 |
| --- | ---: | --- |
| `Local-Coding-Agent-2.0.0-x64-Setup.exe` | 220338511 | `4fa7633682e9fa2ae43c709e4bc0808825fcd87a59c7c4b323237e581a821da5` |
| `Local-Coding-Agent-2.0.0-x64-Portable.exe` | 220108458 | `4ea228fc9344806df149802b2dc50e19e1a588f4c328d11225a42ee5dc63300a` |

含持久完成恢复修复的本机候选位于 `build/v2-candidate-recovery`。Portable 实际完成两轮无 SDK 启动、OpenCode 原生读取和聊天，并正常退出。证据为 `build/packaged-v2-recovery-b60c78b5e7a34777a86f2a9240aa4ebb/report.json`。

| 含恢复修复的本机候选 | 大小（字节） | SHA256 |
| --- | ---: | --- |
| `Local-Coding-Agent-2.0.0-x64-Setup.exe` | 220339273 | `2a5b0f62b17391eac680c307cd47e303d18ed324f105a206ed8eaed0d76f46d9` |
| `Local-Coding-Agent-2.0.0-x64-Portable.exe` | 220109226 | `78143420a489e2b3b33a99b64400bd1f756e5b5cde8a08523e4bea0141d4765e` |

`gh run download 46106043867` 下载的两个文件再次使用 `Get-FileHash -Algorithm SHA256` 校验，均与下载内 `SHA256SUMS.txt` 一致。与本机单独构建的文件请按不同 SHA256 对待。

同一个 Actions Portable 在本机第一轮无 SDK 原生读取和聊天通过，第二轮两次模型请求及真实读取已发生，但聊天验收标记失败并超时。对应证据为 `build/packaged-v2-action-portable-f98f0c2f2d3a4e50b4d5323c5649b19e/report.json`。仍需解决打包版两次启动的稳定性。

`8f488a6` 的干净 Runner 完成解包版、Portable 基础启动、Setup 实装、两轮无 SDK 基础启动、卸载后数据检查和 SHA256 校验。两种包装的第二轮聊天测试均超时，工作流结果仍为失败。该轮尚未包含完成记录恢复修复。[8f488a6 Windows 候选](https://github.com/yunfei00/local-coding-agent/actions/runs/46122729376)

`bd02aca` 干净 Runner 再次通过基础 Setup、Portable、无 SDK 重启、数据保留及 SHA256。聊天专项分别收到真实读取结果，但第一轮的应用退出计时超时。后续加入仅丢文本恢复及关闭上限，已由正式产品专项覆盖。[bd02aca Windows 候选](https://github.com/yunfei00/local-coding-agent/actions/runs/46123955582/artifacts/15254859197)

| Actions 候选 `e16e853` | 大小（字节） | SHA256 |
| --- | ---: | --- |
| `Local-Coding-Agent-2.0.0-x64-Setup.exe` | 220371196 | `64e573d7e4b5d49590dd806cf09309bdd9325a74dc99e103ed03d46702c6087d` |
| `Local-Coding-Agent-2.0.0-x64-Portable.exe` | 220141051 | `ec2baabbeebbc64f9c519b67768ece8102f8ed133d59126d9b75a298010db553` |

## P3 真实 Ollama 场景矩阵

本机 Windows 11、CPU 和已有 `qwen3:4b`。初始端口为 `127.0.0.1:11434`，后续隔离复验使用系统分配的环回端口。`/api/ps` 核实分配 8192 上下文，且显存占用为零。Mock、不依赖模型的验收与 CI 测试分别记录。

| 编号 | 场景 | 结果及证据 |
| --- | --- | --- |
| 1–2 | Windows 启动、OpenCode 自动启动 | PASS。正式 Electron 启动和引擎事件 |
| 3–5 | 界面创建普通项目、创建 Git 项目、打开设置 | NOT RUN。真实模型脚本打开既有隔离 fixture |
| 6–8 | 配置 Ollama、发现 `qwen3:4b`、聊天选取模型 | PARTIAL。环境配置与所选模型的真实响应已核对，未独立断言设置页面保存和目录发现 |
| 9–10 | 中文问答、流式输出 | PASS。中文挑战字串与实际增量事件 |
| 11–12 | 多轮上下文、文件读取 | NOT RUN |
| 13 | 文件创建 | PASS。复验用真实 `qwen3:4b`、一次性审批和文件独立读回。首次 4096 上下文在 616051 ms 超时 |
| 19 | 工具状态展示 | PASS。复验实际收到审批和 `tool.completed` |
| 14、21–23 | 修改、开发、测试、修复 | 完整任务 FAIL。真实模型运行超时，保留 worktree，独立验收未进入。详见真实 Task 记录 |
| 15–18、20 | 搜索、Shell、Git 状态、Git Diff、差异 | NOT RUN。正式产品 Mock 与独立 GUI 已取得有关证据 |
| 24–25 | 任务取消、取消后无残留 | NOT RUN。真实 WebSocket 暂停与独立进程清理见 P7 |
| 26–27 | 历史保存、重启恢复 | PASS。重新启动 Electron 后用挑战字串校验 |
| 28 | 模型服务失联 | NOT RUN |
| 29 | 非默认端口 | PASS。真实 `qwen3:4b` 在独立环回端口通过写入 |
| 30 | 执行引擎为 OpenCode | PASS。校验 `turn.completed` 的引擎身份 |

真实写入报告为 `validation-reports/v2-opencode-desktop-alternate-ollama.json`。完整 Task 使用 `run-local-ollama.ps1 -Scenario Task`，结果为 `validation-reports/v2-opencode-desktop-live-task.json`。原项目独立运行 unittest 捕获 `-1 != 5`，报告为 `validation-reports/lca-v2-live-ku2JGe/real-task-baseline.log`。本轮没有观察到修复成功或自动验收通过。

## P4 在线模型

本次没有产生真实在线模型调用。已授权模型的工程验收、真实用量、工具调用及自动修复为 NOT RUN。OpenCode 官方文档标明免费聊天档位要求通过 OpenCode 使用，Beam Free 另有地区限制。当前正式平台使用单模型兼容网关，没有把官方免费档位当成通用 API 接入。见 [OpenCode Console 官方模型说明](https://opencode.ai/docs/console/models/)。

## P5 Mock 场景矩阵

| 编号 | 场景 | 结果及证据 |
| --- | --- | --- |
| 1 | 模型发现 | PARTIAL。产品测试使用环回目录和明确模型，未单独测试发现错误 |
| 2–6 | Provider 转换、对话、流式、工具、反馈多轮 | PASS。`desktop-live.cjs --mock` 经过正式产品链路和真实 OpenCode |
| 7–8 | 断网与超时 | PARTIAL。`--drop-completion` 真实运行验证实时完成事件丢失；网络断开和请求超时组合仍未执行 |
| 9–12 | HTTP 401/403/429/500 | PARTIAL。`localModelGateway.test.ts` 通过真实环回 HTTP 校验，未分别做渲染器回归 |
| 13 | 额度耗尽 | PARTIAL。SQLite 单轮和全局上限、网关拒绝转发有回归 |
| 14 | 任务取消 | PARTIAL。Python 真实 WebSocket 提前停止验收并保留 worktree，未完成原生执行取消组合 |
| 15 | 服务异常恢复 | PARTIAL。正常重启和实时完成事件丢失已验证，原生子进程强制退出后恢复仍未执行 |
| 16 | 非默认端口 | PASS。正式产品使用随机环回端口 |
| 17 | 局域网地址 | NOT RUN |
| 18 | 禁止切换模型 | PARTIAL。模型不匹配请求在网关处被拒绝，未覆盖完整渲染器场景 |
| 19 | 权限审批 | PASS。正式产品的原生审批阻止写入直到一次性批准 |
| 20 | Key 不泄漏 | PARTIAL。网关不返回带凭据的错误正文，已扫描跟踪文件，未覆盖所有日志和模型组合 |
