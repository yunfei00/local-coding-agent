# 真实在线模型自主开发验收

## 2026-10-26 补充验证

同一阿里连接已获取 180 个模型名称、添加五个候选 Profile。GLM 的真实 API-only calculator 闭环（12 次请求、61,158 Token）与 Omni 的真实 Single Agent calculator 闭环（6 次请求、34,071 Token）通过；Max/Plus/Omni 有随机图片识别证据。另修复计划未前进时反复收费诊断的问题，保留 Qwen Plus 多步规划的实际失败。**当前本机锁屏，完整 M5 桌面在线验收仍未通过，不合并 main。** 最新公司下载分支、模型结果及命令见 [2026-10-26 阿里模型验证](alibaba-model-validation-2026-10-26.md)。下文 2026-10-24 数据保留为历史，不代表当前累计值。

## 最新结论（2026-10-24，Qwen Max）

按用户最新要求，本轮后续只使用已配置的 **`qwen3.8-max`**（执行与视觉均指向该在线 Profile），不再切回 Flash 或开始 GLM。完整在线验收仍为 **FAIL，不能合并或宣称完成**。Windows/Ubuntu CI 通过与本机真实在线闭环失败分别记录。

- 真实 Task `4ed592db-cfc9-4123-923f-2b5e05934033`：46 次真实 HTTP 模型请求，输入 727,849、输出 13,254，合计 **741,103 服务端 Token**；缓存 252,160 为输入子集。2 次模型实际修改 `App.tsx`；实际 npm ci、typecheck、test、build、git diff --check 均退出 0。
- 任务最终因连续工具失败进入 paused / `TOOL_FAILURE_LIMIT`，涉及受控 Electron 停止确认、桌面输入/审批失败与重复读取；未进入独立验收。此次没有发生 Max 图像请求，**Max 视觉理解 NOT RUN**，不能用 Profile 的视觉能力标记或此前 Flash 图像响应代替。
- 当前累计 146 次真实请求，服务端已确认 1,797,324 Token；另有早前超时请求 53,446 不确定预留，账本共 1,850,770。费用 UNKNOWN；未核实供应商免费额度或金额，不自动充值。
- 本次专用入口已按用户授权放宽到累计 **10,000 次请求 / 1,000,000,000 Token / 7200 秒活动时间**，保留全部已用账本、单请求 60 秒、权限及循环保护。旧版小预算不是 Max 本次失败原因。
- 最新代码 `3582adf9243fec39b4f98f1b530dc8e89e742d87` 的 CI [run 40071929862](https://github.com/yunfei00/local-coding-agent/actions/runs/40071929862) 全部通过：Windows Python 396 项（394 通过、2 跳过）；Ubuntu 396 项（380 通过、16 跳过）；两端前端均 46 通过，typecheck/build 通过。Windows 额外 3 项真实 Electron 专项及 desktop-smoke 通过；模型推理为 HTTP Mock，不是真实在线模型验收。
- 本机最后一次完整 `check.py` 是较早版本：Python 387 项，5 failure、3 error、2 skip（7 个不同失败用例，其中一个兼有 teardown error）；桌面 46 项、typecheck/build 通过。不能拿远程 CI 改写本机失败结果。
- 后续只读诊断发现 16 GB 主机非分页内核池约 **12.37 GiB**，物理内存 99% 使用、可用内存曾为 88 MB，复查降至 24 MB。原生专项仍报 `PROCESS_CLEANUP_FAILED`；即使退出码为 1，保留的进程句柄仍未发信号且存在文件锁。内存压力是明确的环境异常，尚未证明是所有失败的唯一原因。详见 [Windows 内核内存阻断](windows-kernel-memory-blocker.md)。在该状态下暂停新的付费任务，先保存证据、等待安全重启后继续；没有擅自重启或停止无关进程。

### 恢复后的当前命令

仅适用于本机已授权连接，保留现有 session 文件；不在命令行传递 Key：

```powershell
git switch feature/real-online-agent-validation
git pull --ff-only
uv sync --locked
npm --prefix desktop ci --no-audit --no-fund
npm --prefix desktop run build

# 先串行运行真实桌面 + Mock 推理回归，不产生付费请求
uv run python -m unittest discover -s tests -p test_m5_electron_e2e.py -k test_actual_electron -v
uv run python scripts/validation/check.py

# 前述门禁通过后继续用户指定的 Max；同一模型也用于视觉
uv run python scripts/validation/real_online_agent_e2e.py --live --model qwen3.8-max --vision-model qwen3.8-max --executor-profile 4ac4bab1-1da5-4a72-b944-f4b4e8b63354 --vision-profile 4ac4bab1-1da5-4a72-b944-f4b4e8b63354 --authorize-budget-update --max-calls 10000 --max-tokens 1000000000 --max-seconds 7200 --max-full-attempts 3
```

这些 Profile ID 仅属于本机；其他电脑先配置实际同名在线 Profile，再传该机器的 ID。Max 当前只进行了一次完整 Task，另一次 Task 创建前的 Electron 启动失败为 NOT RUN / 0 请求，不算完整重试。入口会归档报告，但会清理临时数据库/Worktree；**不能恢复已经清理的 Max 失败任务**，本次重跑是新任务而非旧 Checkpoint 恢复。原用户数据库和凭据不被替换。

### 本轮后续修复与限制

Chromium 前缀确认存在一个确定缺陷：第二次成功的 UIA 读取跨过等待截止时，旧代码仍报值不匹配。现改为先确认连续两次成功再检查超时；丢失焦点或确实不匹配仍失败，字符不重放。4 项确定性回归通过。清空输入也要求连续两次为空。

Electron 冷启动从 90 秒改为有界 180 秒，入口另加 360 秒启动 watchdog；真实就绪标记的测试期限适度延长但不取消断言。停止路径只对保留句柄且核验属于当前 Job 的窗口发 WM_CLOSE，再终止该 Job，等待实际句柄信号最多 30 秒；保留退出码、待退出 PID、耗时及清理阶段。额外针对已核验句柄的终止请求在本机得到 access denied，**未证明能修复环境中的延迟退出**。不提权、不按陌生 PID 杀进程、不把非零退出码或发送信号当作退出确认。

以下旧章节保留各次历史授权、Flash 尝试和诊断过程；执行时以上述 Max 命令与当前结论为准。

## 范围与判定

基线 main：`4d89487181e7e6ab21ca1642d6e3de625bdefeda`。本轮不重新实现 M1～M5，不发布、打 Tag、打包或开始 M6。

入口为 `scripts/validation/real_online_agent_e2e.py` 及同名 `.cjs` 控制器。控制器启动当前源码构建的真实 Electron，通过现有 preload IPC 打开隔离实验工程、创建新 Thread 和 Single Agent Task。执行使用原 AgentServer、TaskService、ToolRegistry、Permission/Approval、Model Router、OpenAICompatibleProvider、BudgetGuard、VerificationEngine 和 Windows DesktopRuntime。

入口没有 Mock 模型，也不修改实验业务源码。`manual-fixtures/m5-electron-e2e` 的两处缺陷、已有测试和 `.lca` 契约保留。原 fixture 不变，模型只能在原 Task 创建的独立 Worktree 修改。已有 `test_m5_electron_e2e.py` 是另一组本机 HTTP Mock 推理回归，不能替代本入口的真实在线结论。

只有以下证据同时满足才输出 PASS：真实请求 HTTP 200 与服务端 Usage、真实工具修改、独立 typecheck/test/build/diff 检查、独立真实 GUI 断言、受控截图、无工具权限的 Observer 实际 JPEG 请求及有效观察、原始工程保持干净、契约未改变、持久化值正确、进入 awaiting_approval、受控进程全部退出。模型自然语言声称完成不计为通过。视觉内容仍须与保存的受控截图/UIA 证据核对；不能仅凭 JSON Schema 合法证明识图正确。

## 本机安全凭据

默认只读 `%APPDATA%\local-coding-agent-desktop\local-coding-agent.sqlite3` 的公开模型目录，不复制用户数据库、Thread、消息或公司文件。精确选择已保存的 Model ID；同名在线 Profile 有多个时必须显式提供 ID。不猜测端点、不测试其他模型、不静默更换收费模型。

真实执行时，Electron 保持原当前用户的 userData / safeStorage 上下文，使用既有读取与 `task.credentials.update` 接口；Agent 通过独立 `LCA_DATA_DIR` 使用全新的临时数据库。密钥文件和 OS 加密上下文不复制、不自行解密、不返回 Key。仅当 `task.credential.status` 明确为 os_protected 且当前连接已配置时才启动 Task。正常 Electron 日志/浏览器运行数据可能更新，原用户 SQLite、模型配置及凭据不被替换。不要同时启动使用同一 userData 的旧实例。

当前入口使用受保护的本机模型连接凭据；不承诺自动识别任意环境变量名。没有合法可访问的凭据时输出 NOT RUN，不要求聊天粘贴 Key。

## 有界预算

初始授权总上界为 40 次真实请求、60,000 Token、60 秒单请求、900 秒活动执行时间、最多一次完整重试。本机 Profile 没有已核实的人民币价格单位，因此初始入口采用 **12 次全会话请求的更保守上限**，不假称能保证 ¥3 金额硬上限。累计 6 次请求、36,601 Token 后，用户明确批准将累计上限改为 **40 次请求、200,000 Token，并再执行一次完整任务**；单请求 60 秒及累计 900 秒活动时间不变，费用未知。更新记录写入 session，之前的调用、Token 和时间不清零。请求前仍由生产 BudgetGuard 按字节保守预留，可能早于服务端实际 Token 达到上限而暂停，不能绕过。

第三次任务后，用户又明确授权一次完整重试，随后进一步要求：按实际工作需要追加预算，不再逐次询问。本轮后续采用有限的累计 **80 次模型请求、500,000 Token、1800 秒活动时间、Qwen 最多 6 次完整任务**，单请求仍为 60 秒。不是无限重试；每次明确调整写入会话更新记录，Provider 不会自行扩大预算或切换模型。费用继续标为未知，不改变正式产品默认限额。

随后用户明确要求取消小 Token 限制或将其放得很大。本轮最新累计上界为 **200 次请求、10,000,000 Token、7200 秒活动时间**；调用与 Token 已用量仍继续累计，单请求仍 60 秒，Qwen 完整尝试最多 6 次。隔离后端通过已有环境配置把每轮模型步数放到 100、工具调用放到 200，ExecutionBudget 使用同一剩余额度与时间。只覆盖本次隔离运行；原重复调用 3 次、连续失败 4 次、权限、审批与无进展检查保持启用。不会因新建 Task 而清零会话账本，也不自动换收费模型。

`validation-reports/real-online-agent-session.json` 跨本入口重跑保留 Calls、Token 预留和时间。Qwen 与 GLM 共用额度；中断不明确时保留整次分配，不自动退款或清零。每组默认最多两次完整执行，仅在明确授权参数下修改；达到完整任务次数上限仍停止。GLM 只有在同一会话 Qwen 已 PASS 且还有额度时才运行。不要删除会话记录来继续付费调用。

用户最新要求也已落实到正式产品：未配置预算的 Task 默认 200 次 API / 1,000 万 Token / 2 小时，全局默认 2,000 次 / 1 亿 Token；Loop 默认每片 100 步 / 512 工具，内部 ExecutionBudget 默认 512 次 / 2 亿保守预留 / 2 小时。保留原循环、失败、审批和停止机制。已有配置和任务不自动改写；Settings/Task 的 **Use long task budget** 可显式提高旧额度，Settings → Agent 的 **Use long task execution limits** 提高旧步骤/工具限制，保存后用于后续执行。费用上限、角色、重试和已用账本保留，更新执行限额不再可能把已经较大的 Token 额度反向缩小。

凭据前置失败、尚未创建 Task 的尝试仍归档，但不算完整任务重试；不会产生模型请求。初版入口将密文放进另一个 Electron userData 时没有建立可用的原安全上下文，因而没有证明凭据可用。最终入口通过原应用安全接口正常读取，未使用独立解密程序或复制 OS 主密钥。

## 可复制命令

在已解锁的 Windows 桌面、仓库根目录运行，GUI 专项与真实在线验收串行执行：

```powershell
git fetch origin
uv sync --locked
npm --prefix desktop ci --no-audit --no-fund
npm --prefix desktop run build

# 离线：只读模型目录与桌面就绪检查，无付费请求
uv run python scripts/validation/real_online_agent_e2e.py

# 已授权的真实请求，仅 qwen3.8-flash + qwen3.8-flash
uv run python scripts/validation/real_online_agent_e2e.py --live

# 仅在用户已明确授权本节扩展累计额度及第三次任务时使用；保留既有用量
uv run python scripts/validation/real_online_agent_e2e.py --live --authorize-budget-update --max-calls 40 --max-tokens 200000 --max-full-attempts 3

# 本次用户进一步授权的后续验证额度；不能将该命令视为其他人的付费授权
uv run python scripts/validation/real_online_agent_e2e.py --live --authorize-budget-update --max-calls 80 --max-tokens 500000 --max-seconds 1800 --max-full-attempts 6

# 用户最新授权：大额度，原循环/无进展与审批检查保持启用
uv run python scripts/validation/real_online_agent_e2e.py --live --authorize-budget-update --max-calls 200 --max-tokens 10000000 --max-seconds 7200 --max-full-attempts 6

# 仅在上一组 PASS、仍有额度时；不要求 GLM 支持视觉
uv run python scripts/validation/real_online_agent_e2e.py --live --model glm-5.3
```

若同名在线 Profile 不唯一，分别添加 `--executor-profile 实际ID --vision-profile 实际QwenID`。不传 API Key 参数。退出码 0 表示离线前置完成或完整在线 PASS，在线失败/NOT RUN 为 2；须读取 JSON 的 result 区分。

控制器只自动答复本轮用户明确授权范围内的 allow_once：受管理任务 Worktree、工程验证/启动命令、由受控工程真实 PID 记录识别的精确 M5 窗口、该窗口图像上传。全屏截图、其他窗口、未知 PID、坐标盲点、提交推送及无关危险动作被拒绝；不启用 Full Access 或 allow_turn。正式产品审批机制保持生效。

## 证据位置

- `validation-reports/real-online-agent-acceptance.json`：本轮机器可读脱敏报告。
- 同名 `.md`：中文摘要。
- `real-online-agent-attempt-N.json`：每次有界尝试归档，保留失败记录。
- `real-online-agent-session.json`：跨尝试预算账本，不含 Key。
- `real-online-local-artifacts/`：仅本机受控 fixture 窗口 PNG；不提交 Git，不上传 CI。

报告记录 Task/Profile/Connection/Call ID、HTTP 状态、Usage 精度、工具请求、实际 Diff、验证历史、GUI 断言和清理结果，不包含 API Key、完整敏感 Prompt 或图像 Base64。临时 Worktree 执行结束后清理，报告中的旧运行时路径可能已不存在；保留的本机截图另列 local_path。

独立回归：

```powershell
uv run python scripts/validation/check.py
uv run python -m unittest discover -s tests -p test_m5_electron_e2e.py -v
uv run python -m unittest discover -s tests -p test_unified_chat_profiles.py -v
uv run python -m unittest discover -s tests -p test_real_online_acceptance.py -v
node scripts/validation/desktop-smoke.cjs
uv run python scripts/validation/credential_scan.py
git diff --check
```

## 本轮实测记录

真实在线验收尚未 PASS。以下为实际发生的请求与结果；HTTP 成功、修改源码不等于整个任务通过。

| Qwen Task | HTTP 请求 | 输入 / 输出 Token | 终态与阻断 | 实际修改 / 测试 / GUI |
| --- | ---: | ---: | --- | --- |
| `e8f3c2e1-799d-41aa-9d87-70c7ea5cdba8` | 2 | 10,563 / 309 | paused / MODEL_CONTEXT_LIMIT | 无修改；未验证 |
| `05988205-69b9-4fff-b972-0887d320c14c` | 4 | 24,839 / 890 | paused / BUDGET_EXHAUSTED | 无修改；未验证 |
| `b7b9dcd4-5216-4b2e-aa52-0c76b8d23e60` | 14 | 98,591 / 4,662 | paused / MAX_TOOL_CALLS | 实际修复 App.tsx 两处；npm ci 成功，未运行类型检查/测试/GUI |
| `907ea26a-002f-4795-8e7b-18a3e555c9af` | 31 | 211,969 / 5,020 | paused / PROCESS_CLEANUP_FAILED（前序工具上限被覆盖） | 无修改；实际 npm ci、类型检查、单测、构建通过；真实 Electron、UIA、2 次 JPEG API；GUI 全流程未通过 |
| `ed36e450-f36a-4b92-82ef-79fa7234a45b` | 9 | 前 8 次服务端 Usage 合计 76,119；最后一次 53,446 为不确定预留 | paused / MODEL_TIMEOUT | 无修改；npm ci、类型检查/单测/构建命令退出 0；最后一次 HTTP 200 SSE 在 60 秒截止前未完整结束，未获得可信 Usage；不是预算耗尽 |
| `77567e1d-76ba-4859-88bf-005cd1b60530` | 40 | 601,798 / 21,461 | paused / TOOL_FAILURE_LIMIT，独立保留清理确认超时 | 2 次实际 App.tsx patch；类型检查、单测、构建成功；83 次真实工具调用、2 次实际 JPEG 视觉请求；截图显示 Saved: M5 verified A/B，磁盘值 M5 verified B；未进入独立验收 |

前六次 Task 累计 100 次真实请求，服务端已确认输入加输出共 **1,056,221 Token**，另有第五次超时请求的 **53,446 保守预留**，合计账本 1,109,667；不能把未知预留写成服务端真实 Usage。费用仍 UNKNOWN。第六次已经跨过旧 40 工具限制，未达到最新大预算，最终由真实连续失败/重复调用保护停止。其两个 PNG 均在本机保留且重编码 JPEG 指纹与真实请求匹配；Codex 查看像素确认保存状态 A/B，但未保留模型观察全文，模型语义理解仍未独立完成核对。不能将业务修改生效等同完整 Agent PASS。

第六次暴露上下文裁剪后遗失进程句柄、重复核对后不收尾的问题。现在每次请求附加一份可重新生成的精简状态，列出本轮自己的活动 process_id/PID/state、已改文件数量、尚缺 Diff/命令检查和失败计数，并说明完成后由原 Task 验证器独立验证。摘要不包含命令、输出、路径、环境或其他任务进程，不累积为历史，不标注未经验证的 GUI 为通过。另将 Job 的 kill-on-close 释放放在保留进程句柄后、实际退出等待前，退出判定仍需原句柄信号；进程专项 15 项中 14 通过、1 POSIX 平台跳过，真实 Electron 行为需继续验证。

前四次完整 Task 合计 **51 次实际请求、356,843 服务端输入加输出 Token**，缓存为输入子集，不重复相加。第三次任务使用当时累计剩余 34 次请求、163,399 Token；第四次任务使用后来明确授权的 80 次/500,000 Token 累计额度。原始工程保持干净，测试和 `.lca` 契约没有改动。GLM 组因 Qwen 尚未通过前置门禁而 NOT RUN。不能宣称完整在线自主开发通过，不能以 Mock 视觉结果代替。

第四次 Task 的真实视觉传输已发生：两个无工具权限 Observer 调用均 HTTP 200，JPEG 分别 13,899 / 14,301 字节，输入 Token 586 / 588，输出 250 / 365。它们包含在上述 31 次调用及 Usage 中，不能重复相加。此前入口仅保留独立验证阶段截图，未保留这两次模型主动截图及观察正文，因此本轮只能确认图像传输与响应成功，语义核对 NOT RUN；不能把它写成完整视觉验收 PASS。后续入口已增加失败任务的受控窗口 PNG 留存、重编码 JPEG 指纹与实际 wire 指纹匹配，以及进程退出阶段/待退出 PID 的脱敏日志留存。

另一次 Electron 启动前置在创建 Task 前超时，结果 NOT RUN、0 API 请求；后续把本地启动等待从 45 秒调整为有界 90 秒并成功创建上述第四次任务。API 单请求超时仍为 60 秒，启动故障没有伪报为模型通过。

第三次实际 Diff：移除输入框 `disabled={true}`，保存后将状态更新为 ``Saved: ${value}``。这些修改来自真实 Qwen 工具调用，Codex 没有修改实验源码。尚无独立验证证据证明功能完成。

基线 M5 曾在 Stop 后的输出排空阶段超时，导致 TASK_INTERNAL_ERROR / PROCESS_CLEANUP_FAILED。`ProcessManager._monitor` 原先让 3 秒读取收尾超时直接逃出，同一失败协程在 close_owner 再次抛出。修复保留原 3 秒上限：进程树照常由 Job 终止，Stop 返回明确的 output_drain_timed_out / output_truncated；自然退出但输出未收全仍为 COMMAND_OUTPUT_FAILED，不能冒充测试通过。新增两个实际进程回归覆盖停机背压和正常退出背压，进程专项共 15 项（14 通过、1 POSIX 平台跳过）。

随后串行 M5 重测暴露 Chromium 输入 16 字符仅保留 12 字符，任务以 DESKTOP_VALUE_MISMATCH / PLAN_TOOLS_UNRESOLVED 暂停。原固定 10ms 逐字符间隔在繁忙的 React 渲染环境仍可能丢字。改为每个 Unicode 字符只发送一次，连续两次 UIA 读取确认实际前缀后才发送下一个字符；每次继续检查精确 RuntimeId 与前台窗口，等待最长 3 秒并受原工具总超时约束。缺字不会自动补发，既不关闭审批也不使用剪贴板或 JS 注入。原生非 Chromium Edit 保持 ValuePattern 路径。实际 M5 用例同时检查 each_prefix 证据。

前缀确认后的 M5 主流程通过，但临时目录清理出现 Chromium 文件锁；Ubuntu CI 又捕获已发 SIGKILL、后代仍短暂存活的竞态。WindowsJob 现在在终止前持有本 Job 的进程句柄，发送终止并释放 kill-on-close Job，再有界等待保留进程句柄信号，避免 PID 重用；关闭 Job 本身不算确认成功。POSIX 等待原进程组没有非僵尸成员。不以信号已发送冒充已退出。[Windows Job 终止语义](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject)及[进程列表接口](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-queryinformationjobobject)为实现依据。

首次真实 Qwen Task：`e8f3c2e1-799d-41aa-9d87-70c7ea5cdba8`。Profile `224a7892-28cb-4d24-8c0f-280d35713725`，Connection `763c8386-7de8-47a9-bd40-9a48edbfd02f`。2 次 HTTP 200 / SSE / tool_calls，服务端输入 10563、输出 309、缓存 4096（为输入的子集，不重复相加）；调用了 10 个真实读取/目录工具，没有修改文件。随后 MODEL_CONTEXT_LIMIT 暂停，不能算修复或 GUI PASS。

根因：原 ContextBudgetManager 按字符近似 Token 裁剪且不扣除工具 Schema，而 Task BudgetGuard 按 UTF-8 字节保守检查整包。初次修复把两者统一成字节检查，避免了直接超窗，但真实第四次任务又暴露过度裁剪：把计费预留的“字节上界”当成“上下文 Token 占用”，导致大部分工作窗被固定 Schema 消耗，早期源码很快被丢弃。31 次请求实际输入共 211,969 Token，其中 2 次视觉输入共 1174；这是框架工作记忆不足的证据，不能只增加 API 额度掩盖。

最终将两个量分开：API Token/费用请求前预留仍按完整 UTF-8 字节保守计算；上下文使用包含 Schema、输出及 framing 的 **UTF-8 字节数/2 启发式 Token 估算**，原 fitter 与 Guard 使用同一上下文估算。估算方法明确标为 `utf8_bytes_div2_estimate`，不是供应商精确 tokenizer，供应商真实超窗错误仍保留并受原有限重试约束。模型窗口配置没有增大，原 32768 fallback 保留；计费硬预算也没有除以 2。只改上下文选择，不丢弃工具调用头或绕过最终预检。RoutedProvider 同时公开实际 Profile 输出上限，避免执行预算误用 Chat 预留值。

后续定位并修复：

- 上下文先截断所有工具结果再删除历史，导致最新源码也被截断；现在先删除较早的完整工具交换，仅最新一组仍装不下时截断结果，工具调用头保持完整。
- 历史按单消息裁剪可能保留无调用头的工具结果；现在历史也以完整交换分组保留。
- Observer 反馈误记为新的用户意图；改为带明确不可信标记的模型观察，真正的用户目标仍为当前任务锚点。
- Single Agent 的 relay 把预算异常转换为普通 ProviderError，丢失字段/限额/已用/本次需要量；现在保留原 BudgetExceeded 详情和角色。
- 验证器清理失败被统一标为 TASK_INTERNAL_ERROR；现在按原 ToolError code 暂停，保留失败阶段，避免把环境清理问题升级给收费模型。进程日志增加清理阶段及仅本 Job 内待退出 PID 的诊断，不记录输出、环境或凭据。
- 后置清理异常覆盖原 Loop 错误；现在保留原 MAX_TOOL_CALLS 等主因，并在 `last_error.cleanup` 中单独记录清理异常。
- 本机实际出现 5 秒退出确认截止后，后续收尾确认 4 个受控 Electron PID 均已退出；退出确认调整为有界 10 秒，仍等待本 Job 的实际进程句柄信号，超时照常失败。新增确认耗时、进程数量与 pending PID 证据，不能把发送终止信号当作退出。两秒后台进程超时回归改用实际 CMD 启动同一 Node/Python 进程树，隔离 PowerShell 冷启动超过两秒的环境影响；测试进程期限仍为两秒。

专项证据：请求上下文与 HTTP Task 10 项通过（含真实工具修改 calculator、真实 unittest/Diff，以及显式清理故障注入）；任务启动预算 10 项通过；统一 Profile/Observer 11 项通过；入口安全与预算守卫 15 项通过；原 Context 5 项通过；实际进程 15 项中 14 通过、1 POSIX 平台跳过。故障注入与本机 HTTP Mock 均不算真实收费推理成功。

## 复用与核心文件

| 文件 | 本轮变化 |
| --- | --- |
| `agent/core/context.py` / `budget.py` | 上下文估算与计费预留分离，前后上下文检查一致，保留完整工具交换；未配置预算默认提高 |
| `agent/core/execution.py` / `settings.py` / Settings 与 Task UI | 提高内部执行额度，显式旧额度预设；保持原循环保护和预算账本，补充本轮进程句柄摘要 |
| `agent/server/main.py` / `core/orchestration.py` | 原 Loop/Task relay 保留预算与清理错误；Observer 不再替换用户意图 |
| `agent/llm/router.py` | RoutedProvider 使用实际 Profile 输出上限 |
| `agent/llm/openai_compatible.py` | 真实图像请求只记录 MIME、字节数、SHA256 和工具 Schema 数量 |
| `agent/tools/processes.py` / `windows_job.py` | 原进程监控处理排空失败、确认本 Job/进程组退出，保留清理阶段 |
| `agent/desktop/worker.py` | 原 Chromium 输入路径逐前缀确认；没有剪贴板、JS 注入或盲目重放 |
| `scripts/validation/real_online_agent_e2e.py` / `.cjs` | 新增可复现的真实 Electron IPC 验收控制器与累计预算账本 |
| `tests/test_api_context_fit.py` / `test_real_online_acceptance.py` | 新增上下文/真实工具 HTTP 闭环与入口守卫回归 |
| `tests/test_m2_processes.py` / `test_m5_electron_e2e.py` / `test_unified_chat_profiles.py` | 扩展既有实际进程、Electron/UIA、角色/视觉回归 |

没有增加第二套 Agent Loop、Provider、状态机或权限系统。沿用原 TaskRuntime、TaskPlan、Checkpoint、ExecutionJournal、ModelRouter、BudgetGuard、VerificationEngine、Git Worktree、ApprovalManager 和 DesktopRuntime。

本机首次完整基线为 Python 358 项，1 个测试失败并伴随该测试 teardown 错误、2 项跳过；桌面 45 项、typecheck/build 通过。后续本机 M5 专项仍出现输入未确认及 Job 退出确认超时/Chromium 文件锁；最新诊断明确为 `job_exit_confirmation`，不能声称本机 GUI 已全部通过。某次仅发送终止信号后很快退出，并不证明所有后代已退出；保留确认失败，不能通过忽略异常让验收变绿。本机当时可用物理内存约 144 MB，仅作为环境事实记录，不将其直接认定为唯一根因。早期提交 `c53ef86882f3de088aec369cf0d0c97e09cec112` 的 Windows/Ubuntu CI（run `40047247624`）均通过，最终版本的完整门禁仍须按对应 SHA 单独核实。
