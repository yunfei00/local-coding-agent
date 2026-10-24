# 真实在线模型自主开发验收

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

用户授权总上界为 40 次真实请求、60,000 Token、60 秒单请求、900 秒活动执行时间、最多一次完整重试，不自动扩大预算。本机 Profile 没有已核实的人民币价格单位，因此不假称能保证 ¥3 金额硬上限；入口采用 **12 次全会话请求的更保守上限**。请求前仍由生产 BudgetGuard 按字节保守预留，可能早于服务端实际 Token 达到上限而暂停，不能绕过。

`validation-reports/real-online-agent-session.json` 跨本入口重跑保留 Calls、Token 预留和时间。Qwen 与 GLM 共用该额度；中断不明确时保留整次分配，不自动退款或清零。每组最多两次完整执行。GLM 只有在同一会话 Qwen 已 PASS 且还有额度时才运行。普通 ExecutionBudget 默认限额保持不变。不要删除会话记录来继续付费调用。

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

正在执行；当前未将任何真实在线任务记为 PASS。完成后以本节最终记录及脱敏报告为准。

基线 M5 曾在 Stop 后的输出排空阶段超时，导致 TASK_INTERNAL_ERROR / PROCESS_CLEANUP_FAILED。`ProcessManager._monitor` 原先让 3 秒读取收尾超时直接逃出，同一失败协程在 close_owner 再次抛出。修复保留原 3 秒上限：进程树照常由 Job 终止，Stop 返回明确的 output_drain_timed_out / output_truncated；自然退出但输出未收全仍为 COMMAND_OUTPUT_FAILED，不能冒充测试通过。新增两个实际进程回归覆盖停机背压和正常退出背压，进程专项共 15 项（14 通过、1 POSIX 平台跳过）。

随后串行 M5 重测暴露 Chromium 输入 16 字符仅保留 12 字符，任务以 DESKTOP_VALUE_MISMATCH / PLAN_TOOLS_UNRESOLVED 暂停。原固定 10ms 逐字符间隔在繁忙的 React 渲染环境仍可能丢字。改为每个 Unicode 字符只发送一次，连续两次 UIA 读取确认实际前缀后才发送下一个字符；每次继续检查精确 RuntimeId 与前台窗口，等待最长 3 秒并受原工具总超时约束。缺字不会自动补发，既不关闭审批也不使用剪贴板或 JS 注入。原生非 Chromium Edit 保持 ValuePattern 路径。实际 M5 用例同时检查 each_prefix 证据。

前缀确认后的 M5 主流程通过，但临时目录清理出现 Chromium 文件锁；Ubuntu CI 又捕获已发 SIGKILL、后代仍短暂存活的竞态。WindowsJob 现在在终止前持有本 Job 的进程句柄、终止后有界等待句柄信号，避免 PID 重用，并在确认完成后关闭 Job；POSIX 等待原进程组没有非僵尸成员。不以信号已发送冒充已退出。[Windows Job 终止语义](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject)及[进程列表接口](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-queryinformationjobobject)为实现依据。

首次真实 Qwen Task：`e8f3c2e1-799d-41aa-9d87-70c7ea5cdba8`。Profile `224a7892-28cb-4d24-8c0f-280d35713725`，Connection `763c8386-7de8-47a9-bd40-9a48edbfd02f`。2 次 HTTP 200 / SSE / tool_calls，服务端输入 10563、输出 309、缓存 4096（为输入的子集，不重复相加）；调用了 10 个真实读取/目录工具，没有修改文件。随后 MODEL_CONTEXT_LIMIT 暂停，不能算修复或 GUI PASS。

根因：原 ContextBudgetManager 按字符近似 Token 裁剪且不扣除工具 Schema，而 Task BudgetGuard 按 UTF-8 字节保守检查整包。真实读取多个文件后，上游认为仍有空间，下游已超默认 32768 的保守窗口。修复在原 ContextBudgetManager 内增加请求级裁剪，复用原工具交换分组，使用与 BudgetGuard 相同的 sizing 函数并计入 Schema、输出、JSON 开销。只裁剪上下文，不提高窗口、不提高任务预算、不丢弃工具调用头或绕过最终预检。RoutedProvider 同时公开实际 Profile 输出上限，避免执行预算误用 Chat 预留值。新增 3 项测试含真实 HTTP Mock → 大文件读取 → 原工具修改 → unittest → Diff → awaiting_approval；原 Context 5 项回归亦通过。最终完整重试及门禁记录待补充。
