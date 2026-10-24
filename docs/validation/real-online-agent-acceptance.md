# 真实在线模型自主开发验收

## 范围与判定

基线 main：`4d89487181e7e6ab21ca1642d6e3de625bdefeda`。本轮不重新实现 M1～M5，不发布、打 Tag、打包或开始 M6。

入口为 `scripts/validation/real_online_agent_e2e.py` 及同名 `.cjs` 控制器。控制器启动当前源码构建的真实 Electron，通过现有 preload IPC 打开隔离实验工程、创建新 Thread 和 Single Agent Task。执行使用原 AgentServer、TaskService、ToolRegistry、Permission/Approval、Model Router、OpenAICompatibleProvider、BudgetGuard、VerificationEngine 和 Windows DesktopRuntime。

入口没有 Mock 模型，也不修改实验业务源码。`manual-fixtures/m5-electron-e2e` 的两处缺陷、已有测试和 `.lca` 契约保留。原 fixture 不变，模型只能在原 Task 创建的独立 Worktree 修改。已有 `test_m5_electron_e2e.py` 是另一组本机 HTTP Mock 推理回归，不能替代本入口的真实在线结论。

只有以下证据同时满足才输出 PASS：真实请求 HTTP 200 与服务端 Usage、真实工具修改、独立 typecheck/test/build/diff 检查、独立真实 GUI 断言、受控截图、无工具权限的 Observer 实际 JPEG 请求及有效观察、原始工程保持干净、契约未改变、持久化值正确、进入 awaiting_approval、受控进程全部退出。模型自然语言声称完成不计为通过。视觉内容仍须与保存的受控截图/UIA 证据核对；不能仅凭 JSON Schema 合法证明识图正确。

## 本机安全凭据

默认只读 `%APPDATA%\local-coding-agent-desktop\local-coding-agent.sqlite3` 的公开模型目录，不复制用户数据库、Thread、消息或公司文件。精确选择已保存的 Model ID；同名在线 Profile 有多个时必须显式提供 ID。不猜测端点、不测试其他模型、不静默更换收费模型。

真实执行时，只有原始 `model-secrets.json`、`provider-secrets.json` 的密文复制到本机当前用户的临时应用目录。原 Electron main 的 safeStorage 读取和既有 `task.credentials.update` 负责凭据同步；控制器不自行解密、不返回 Key，不绕过操作系统保护。仅当 `task.credential.status` 明确为 os_protected 且当前连接已配置时才启动 Task。结束后删除临时密文副本。

当前入口使用受保护的本机模型连接凭据；不承诺自动识别任意环境变量名。没有合法可访问的凭据时输出 NOT RUN，不要求聊天粘贴 Key。

## 有界预算

用户授权总上界为 40 次真实请求、60,000 Token、60 秒单请求、900 秒活动执行时间、最多一次完整重试，不自动扩大预算。本机 Profile 没有已核实的人民币价格单位，因此不假称能保证 ¥3 金额硬上限；入口采用 **12 次全会话请求的更保守上限**。请求前仍由生产 BudgetGuard 按字节保守预留，可能早于服务端实际 Token 达到上限而暂停，不能绕过。

`validation-reports/real-online-agent-session.json` 跨本入口重跑保留 Calls、Token 预留和时间。Qwen 与 GLM 共用该额度；中断不明确时保留整次分配，不自动退款或清零。每组最多两次完整执行。GLM 只有在同一会话 Qwen 已 PASS 且还有额度时才运行。普通 ExecutionBudget 默认限额保持不变。不要删除会话记录来继续付费调用。

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
