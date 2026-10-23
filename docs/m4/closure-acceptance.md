# M4 收尾验收记录

日期：2026-10-23。基线 main PR #18，`fd3e39f292b72990eb3d0e244be045c7fc0d1de5`。变更说明与能力矩阵见 [continuation-recovery.md](continuation-recovery.md)，62 份既有文档的审计索引见 [historical-audit.md](historical-audit.md)。不重复实现已完成的截图/视觉能力，不进入 M5。

## 专项自动化

| 验收 | 结果与真实证据 |
| --- | --- |
| Phase A | `test_execution_recovery.py`：19 次决策跨默认 16 轮，实际 patch、unittest、Git Diff，checkpoint/累计调用可查；同 owner 重复启动只创建一个真实进程；续跑上限、调用/Token/活动时间预算与取消清理 |
| Phase B | 已完成文件写入不重放；blocked 实际目录探测后只转 in_progress；目录消失保持 blocked；真实 SQLite 重启后未知副作用需新审批，拒绝后无写入；原 `test_v03_runtime.py` 9 项通过 |
| Phase C | 连续 4 个真实工具失败后 last_tool/错误码/耗时/固定恢复动作可见；不持久化参数和文件正文；格式异常错误码不进入诊断；15 项新增核心回归全部通过 |
| Phase D | 修改已有测试预期会暂停独立验收；新测试可新增；失败命令不能被无关 file_exists 成功掩盖；已有 Python 故障修复 2 项真实 E2E 通过 |
| 桌面 UI | typecheck 通过，Vitest 13 个文件/43 项通过；desktop-smoke 通过，包括真实目录恢复、Composer、Task/Plan/Context/Git/Diagnostics 非模态输入、多项目/Thread/重命名、重启恢复 |
| 编译/安全 | Python compileall 通过；凭据与私有产物扫描通过（暂存后再次扫描）；没有 API Key、真实截图、用户数据库进入提交 |

## Windows 桌面状态

本机真实调用 WTSInfoEx 检测到当前会话锁定，前台进程为 LockApp。早期未加会话检查时 M3 SendInput/前台用例报 DESKTOP_FOCUS_FAILED；未冒充通过，也未解锁、改变系统策略或绕过限制。补充会话保护后，交互套件明确 SKIPPED：DESKTOP_SESSION_LOCKED；跨平台与真实会话拒绝测试继续运行。

早期 M4 WinForms 套件 7 项曾实际执行并通过（UIA、真实编译/进程/JSON 断言），但这不能替代增加锁屏保护后的最终交互验收。最终 Windows GUI 结论以可交互 Windows CI 为准。Windows CI 设置 `LCA_REQUIRE_INTERACTIVE_DESKTOP=1`，锁屏/桌面不可用会失败，不能静默跳过交互套件。

桌面 smoke 的原生剪贴板读回在本机会话不可用，报告明确 SKIPPED，renderer 复制反馈已测。不能把 renderer 检查等同于系统剪贴板成功。

## 全量与交付

本机 `uv run python scripts/validation/check.py` 全部四阶段通过，零错误，运行编号 `20261023-165733-476926`：Python 342 项（329 通过、13 跳过；包括 11 项交互 GUI 因锁屏跳过及 2 项平台不适用），桌面 Vitest 13 个文件/43 项通过，typecheck 与 build 通过。最新 desktop-smoke 28 项检查通过，原生剪贴板读回明确跳过。新增核心专项 15 项通过，既有持久化运行时专项 9 项通过；已修复回归中发现的可选探测误阻塞，以及旧用例对新验收保护状态的预期差异。

Windows/Ubuntu CI 的精确数量与运行链接记录在本次 PR 的中文验收结果中，状态可在 [CI 工作流](https://github.com/yunfei00/local-coding-agent/actions/workflows/ci.yml) 核对；必须两平台全部成功才允许合并。Windows GUI 证据由 CI 的 M3/M4 JSON 产物与逐项 unittest 日志提供，不能用本机 SKIPPED 代替。专项日志和全量 JSON 在本地 `validation-reports/`，不提交截图或用户内容。

## 真实模型

本轮真实文本 API：NOT RUN；真实视觉 API：NOT RUN；真实 Function Calling：NOT RUN。付费请求 0 次，服务端 Token 无新增数据，未产生本轮请求费用。Mock/本地 HTTP 替身不算百炼通过。未获本轮有预算 Live Test 授权，不读取或修改用户已有凭据、Ollama 或在线连接。

## 用户操作验收入口

自动化已覆盖，可选查看：打开既有项目/Thread → Plan 查看累计执行与最近工具诊断 → blocked 点击 Continue plan → 检查目录成功后在原 Thread/Task 恢复 → 需要增加累计边界时点击“增加执行预算”并确认 → Stop 停止当前执行与进程树。Task 的 API/时间额度仍在 Task 配置中明确调整。成功报告需独立测试/GUI 契约通过并提供 Diff；失败保留原因与未完成事项。

离线复现：`uv run python manual-fixtures/m4-continuation/run.py`。在解锁的可交互 Windows 运行全部 GUI 用例；在锁屏或非 Windows 环境明确跳过对应交互部分，不需要逐项人工点按钮验收。

已知限制：Tkinter Pane 输入仍未实现；旧窗口/进程需重新发现并授权；不支持锁屏/UAC/跨用户会话；Token 预留是保守字节估算，实际费用依据服务端 usage；保护已有测试不是恶意仓库隔离沙箱，超出有界发现规模会停止。

## 修改文件

- Python 执行/持久化：`agent/core/execution.py`、`agent/server/main.py`、`agent/task_plans.py`。
- 任务验收/进程：`agent/core/orchestration.py`、`agent/core/verification.py`、`agent/tools/processes.py`、`agent/tools/shell.py`。
- Windows：`agent/desktop/session.py`、`agent/desktop/worker.py`（未引入 Pane 输入）。
- 桌面 UI/桥接：`desktop/electron/main.ts`、`desktop/src/components/PlanPanel.tsx`、`AutonomousTaskPanel.tsx`、`RecentExecutions.tsx`、`desktop/src/lib/autonomousTask.ts`。
- 新增回归：`tests/test_execution_recovery.py`、`tests/windows_desktop_support.py`、`desktop/src/components/RecentExecutions.test.tsx`。
- 扩展既有回归：`tests/test_agent_reliability.py`、`test_m3_desktop.py`、`test_m4_gui.py`、`test_v04_orchestration.py`、`scripts/validation/desktop-smoke.cjs`。
- CI/演示/说明：`.github/workflows/ci.yml`、`manual-fixtures/m4-continuation/`、`README.md`、本目录架构与收尾文档。没有新增第三方依赖。
