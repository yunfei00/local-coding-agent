# v0.6 统一运行时验收报告

日期：2026-11-04，Windows 11 / CPU / 16 GB，Python 使用项目 uv 环境。基线 `da24a647dc645dadea07d82ab4ae9d6bfb76659a`，分支 `feature/v0.6-unified-agent`。运行时代码 `865990ada40ea7e19e960895cc0cf2359ac89366`；最终文档和驱动提交以分支 Git 历史和 PR HEAD 为准。

## 实现与根因

扩展原 Agent、Task Plans、VerificationEngine、审批、预算、Provider 和 WebSocket，没有另建执行器或状态机。

- 原运行中输入缺少持久队列和完整工具批次边界：增加事务性 followup 队列、幂等 ID 和取消屏障，消息只应用一次。
- 普通运行中断后原目标和事件不足：保存原目标、模型与预算快照，从原运行恢复；旧数据缺少原目标时明确拒绝猜测。
- 请求失败难判断是否真正发送：关联准备、发送、响应头、首片段、完成、失败和预算结算；未知发送保守保留预留，实际 Usage 可用时释放多余预留。
- 内外层重试可能相乘：仅对确定未发送的适用错误有限重试；截断流不执行半截工具。
- 预算追加未更新 API 快照：显式批准后只增加原运行上限，保留使用记录，不修改日常 Settings，不自动追加。
- 计划步骤已完成但最终检查阻断时恢复 owner 错误：保留原执行，只重做未完成检查。
- 未知中断操作需审阅：用户核对后记 reviewed 而非 succeeded，不伪造步骤完成；后续副作用仍需审批。审批异步派发避免同一 WebSocket 等待死锁。
- 桌面动作曾被当作只读分析、运行产物误触发代码验证：修正动作意图解析，忽略生成的 `.runtime`；没有独立 GUI 合约时显示待独立验收。
- 最后补充用例进一步确认：工具/审批等待错误套用模型请求超时，600 秒任务实际约 100 秒即报累计耗尽。已将该边界改为任务 deadline，保留工具自身超时、取消和审批；模型 HTTP 仍有独立请求超时。没有增加任务默认预算。

详细文件与协议见 [implementation.md](implementation.md)、[state-machine.md](state-machine.md)、[api-tracing.md](api-tracing.md)、[recovery.md](recovery.md)。

## 自动化结果

| 检查 | 实际结果 | 本机日志 |
| --- | --- | --- |
| 修改前 Python 基线 | 520 项：518 PASS、2 SKIP | 基线审计 |
| 完整 Python | 549 项：547 PASS、2 SKIP、0 FAIL | `validation-reports/20261104-191955-799454.log` |
| 新增事件/HTTP/集成定向 | 最后修复后 31 PASS（新增超时隔离与总任务取消两项） | `validation-reports/v06-timeout-after.log` |
| 原统一运行时 | 41 PASS | `validation-reports/v06-unified-final.log` |
| 恢复回归 | 19 PASS | `validation-reports/v06-recovery-final.log` |
| 混合 Provider | 19 PASS | `validation-reports/v06-mixed-final.log` |
| 前端 | 18 文件、62 PASS | `validation-reports/v06-frontend-serial.log` |
| 类型检查、前端/Electron 构建 | PASS | `validation-reports/v06-complete-validation.log` |
| 实际 Electron desktop-smoke | 53 PASS、0 SKIP；最终构建复测同样通过 | `validation-reports/v06-desktop-smoke-final.log` |

定向套件包含在完整 Python 中，不能相加；原有两项条件跳过未改成通过。549 项全量摘要 Errors=0；最后工具超时修复新增两项（修复前一项实际失败，修复后 31 项全部通过），最终 HEAD 的 551 项完整回归由 CI 继续验证，不预先计为通过。

```powershell
uv sync --locked
$env:LCA_REQUIRE_INTERACTIVE_DESKTOP='1'
$env:VITEST_MAX_THREADS='1'
$env:VITEST_MIN_THREADS='1'
$env:NODE_OPTIONS='--max-old-space-size=256'
$env:GOMAXPROCS='2'
uv run --locked python scripts/validation/check.py
node scripts/validation/desktop-smoke.cjs
uv run --locked python scripts/validation/credential_scan.py
git diff --check
```

覆盖事件脱敏/幂等/事务回滚、终态保护、进程硬中断恢复、并发启动、真实文件修改与 unittest、追加只应用一次、快照预算保留、审阅不等于完成、真实 aiohttp WebSocket 审批往返、HTTP 分片/429/超时/取消及 GUI 证据要求。原 Git、MCP、Pinned Files、L2/L3 测试未删除。

## 真实模型与工程

通过生产 Electron IPC → 原 Agent → Provider → 工具入口执行。Codex 只准备缺陷工程、独立契约和驱动，没有代写被测实现；保留原 fixtures 路径和断言。

| 模型 | 真实结果 |
| --- | --- |
| qwen3.7-flash | 文本/工具 PASS；Python、优惠券、多步骤、修复、环境错误停止、上下文压缩、取消恢复、WebSocket 重连、追加、网络断流、Git 拒绝、Electron 和 Windows UIA PASS |
| qwen3-coder-flash | 文本/工具 PASS；问答/分析、React 多文件修改、类型检查/测试/构建、原运行审阅与恢复 PASS |
| glm-5.2 | 文本/工具 PASS；Python 实际修改、unittest、独立验证、Diff PASS（4 调用/18430 Token） |

18 个最终用例已有 PASS 证据，见 [脱敏 JSON](evidence/live-cases.json)。环境/审批 PASS 表示正确阻断，不表示代码完成。早期失败记录保留，修复后从原任务恢复，没有直接修改数据库伪造状态。

主要本机证据（以下均为 `validation-reports/` 下目录）：

| 用例 | 报告目录 | 独立证据 |
| --- | --- | --- |
| 问答、分析、Python、修复、环境、上下文、取消、WS | `v06-real-full-20261104` | 原断言、独立 unittest、真实事件 |
| 优惠券 | `v06-real-coupon-resume-20261104` | 全步骤完成、旧 completed 保留、冻结契约 exit 0、中文报告 |
| React | `v06-real-react-accepted-20261104` | App/math 修改、typecheck/test/build 全 0、原 owner 恢复 |
| Electron | `v06-real-electron-acceptance-20261104` | 12 调用/108224 Token；源码修复、三项检查 0、实际窗口保存成功 |
| Windows UIA | `v06-real-gui-serial-20261104` | 14 调用/220019 Token；启动、检查、点击、输入、保存、截图、停止 |
| Git 拒绝 | `v06-real-gui-approval-20261104` 的 approval 项 | 实际 deny、HEAD 未变；同报告旧 gui 失败不计 PASS |
| 网络断流 | `v06-real-network-20261104` | 实际 200 SSE 截断一次、7 次 HTTP/42870 Token（含估算）；保留失败账本、恢复、真实修改和 unittest 0 |
| 同页追加 | `v06-real-followup-20261104` | 15 调用/143579 Token；同线程 2 条用户消息、输入校验和独立测试通过 |
| GLM | `v06-real-glm-accepted-20261104` | patch、原断言不变、独立 unittest 0 |

Usage 属于相应数据库累计快照，包含失败/恢复时不能直接相加。优先服务端 Usage，其余标明估算/预留；费用未核实，保持未知。用户明确允许使用免费额度，验收隔离配置仍有有限请求、时间、超时与无进展停止。未调用 qwen3.7-plus、qwen3.8-flash 及变体，未修改原 Settings。

六个旧配置模型返回 400/403，单独 BLOCKED，不代表 Key 全部失效；见 [model-compatibility.md](model-compatibility.md)。没有可用视觉模型完成真实推理，视觉 NOT RUN；实际 UIA/截图不冒充视觉推理。

## Windows、诊断与限制

实际 Electron 和在线 Windows UIA 已运行，截图见 [windows-gui-acceptance.md](windows-gui-acceptance.md)。诊断只显示当前问题，完整 JSON 保留本机，不经 WebSocket 推送无限历史。事件只含白名单元数据，Cookie/凭据脱敏。

中途实际出现 VirtualAlloc failed、Node OOM 和低可用内存。保留失败日志，串行/单 worker 后全量通过；没有重启 Windows、停止无关应用或更改全局内存设置。

最终纯 GUI 结果语义补充用例 `v06-real-gui-semantics-20261104` 为 **BLOCKED**：可用内存 288 MB、系统提交量 44935430144 / 45414780928 字节、非分页池 9358344192 字节，桌面/IPC 无响应；后端记录 EXECUTION_TIMEOUT。已停止严格限定的本次驱动进程树、删除隔离的加密凭据副本，保留任务数据库及失败报告。不能仅凭资源指标排除产品缺陷，故不将本次失败改为 PASS。该补充用例未进入 18 项通过统计。驱动补上 IPC 90 秒和清理 10 秒等待上限，避免控制器本身无限等待；没有再次重复在线调用。

2026-11-05 只读检查同一数据库进一步发现：16 次模型调用、elapsed=99.734 秒、任务 limits.seconds=600，却为 EXECUTION_TIMEOUT。源码确认 `_authorize_tool` 外层错误使用 Provider 请求超时；修复前自动复现“工具等待超过模型请求上限导致 failed”，修复后该用例完成为未独立验证，并另证总任务到期仍取消。该软件缺陷已修正，不能把原失败完全归咎于主机资源；尚无修复后的真实 GUI 补充通过证据。

## CI 与最终门禁

源码与驱动提交 `8329cc158f13703584c08da4953e1c1817c45789` 的 push 和 PR 两次 CI 均为 Windows/Ubuntu 全通过：[push 41826050081](https://github.com/yunfei00/local-coding-agent/actions/runs/41826050081)、[PR 41826117426](https://github.com/yunfei00/local-coding-agent/actions/runs/41826117426)。包含 Python、类型检查、前端测试、构建、实际 Windows Electron GUI 与 desktop-smoke。PR 为 [#29](https://github.com/yunfei00/local-coding-agent/pull/29)，无合并冲突。

此前 `865990a` 的 Windows smoke 曾在 More → Diagnostics 菜单等待超时，Ubuntu 通过。该失败记录保留为 `validation-reports/v06-ci-8659-failed.log`，没有删断言；同一产品代码在本机最终 smoke 及上述两个独立 CI 均通过。仍属一次发生过的时序失败，不能声称从未失败。本文后续仅补充验收证据，最新 HEAD 的 CI 以 PR Checks 为准。

最终结论：**BLOCKED**。18 项已成功在线用例、完整回归、最终 desktop-smoke 和已确认 CI 有效，但纯 GUI 补充验收未完成，不宣称全部功能已验收。2026-11-05 继续时主机可用内存仅 147 MB、系统提交量 44872859648 / 45414780928 字节，未继续重复启动在线 GUI 任务。保留 PR，本轮不绕过门槛合并 main。没有创建正式 Release、Tag 或安装包。

下一步是主机资源恢复后，只执行 `gui --gui-only` 补充用例，检查真实桌面动作、无源码变更以及 `completed_unverified/manual` 结果；已有 Python/React/Electron 等 18 项不需要重新消耗模型额度。无需重新配置 Key 或增加日常预算。

## 公司更新

确认合并后，保存工作并完整退出应用，更新 main，执行 `uv sync --locked`、`npm --prefix desktop ci`、`npm --prefix desktop run build`，再按 README 启动。仅刷新页面不足以更新 Python 后端。原模型、Key、线程和预算保留，无需重填。Settings 只影响新任务；失败运行使用明确的原运行恢复入口，旧版没有原目标的运行需新任务。

已知限制：本轮不以真实 Ollama 为基准；真实视觉 NOT RUN；事件历史暂无自动轮转；无独立 GUI 合约时待人工验收。不能推论任意模型/工程/桌面操作均可自动验收。
