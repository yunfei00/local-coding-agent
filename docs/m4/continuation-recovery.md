# M4 收尾：长任务续跑、阻塞恢复与验收保护

2026-10-23，基线 main `fd3e39f292b72990eb3d0e244be045c7fc0d1de5`（PR #18）。功能分支 `codex/m4-task-continuation-recovery`。不进入 M5。

## 审计结论与实现范围

历史 M1～M4 已实现单 Agent、进程管理、Windows UIA、图像回传、诊断和 GUI 独立验收。PR #16/#17 的截图修复与 PR #18 的 Edit 诊断继续保留，没有重写这些功能。公司 GLM 文本、工具、视觉与标准 Edit 的成功记录属于用户提供的真实验收背景，不冒充本轮百炼实测。

开始时无未合并 PR。远程 `fix/tkinter-pane-text-input` 为 `5a9d2e6e468b0e091c03ba1bd9bb0618c6d6129e`，本轮不合并、不删除。Pane 输入仍返回 `DESKTOP_EDIT_REQUIRED`，敏感控件保护继续生效。

| 能力 | 基线情况 | 本次实现及证据 |
| --- | --- | --- |
| 16 轮之后保留进度 | 部分实现：checkpoint 后直接结束 | `AgentServer.run_tool_turn` 在原循环跨 slice 继续，同一消息、ToolLoopGuard、权限、进程 owner；`turn.continuing` 可观察 |
| 累计预算 | Task 已有 API/时间预算；聊天轮次边界独立 | `core/execution.py::ExecutionBudget` 用 SQLite 持久化调用、Token 保守预留、续跑数与执行时间；恢复不清零 |
| blocked 安全恢复 | 主要依赖手改状态 | `AgentServer.recover_plan` 实际只读检查目录后转 in_progress，保留失败历史，不伪造 completed；Task 从原隔离 worktree 恢复 |
| 重启与未知副作用 | 已有 plan/checkpoint，运行中执行未区分 | `TaskPlanStore` 把未结执行标记 interrupted；有未知副作用时后续变更需新审批，不能凭模型文字宣告完成 |
| 重复变更/服务启动 | 已有文件指纹与循环检测 | 保留文件防重；`StartProcessTool` 复用同 owner/命令/目录的活进程，slice 不重复启动 |
| 最近工具失败诊断 | 信息分散 | 执行日志含工具、状态、耗时、退出码、固定错误分类/恢复动作；`RecentExecutions` 集成 Task/Plan |
| 测试预期保护 | 验收命令与 GUI 契约已冻结 | `acceptance_snapshot/acceptance_changes` 冻结已有测试、关键配置和 npm 验收脚本的散列；修改后暂停，允许新增测试 |
| 失败报告 | 成功报告较完整 | 暂停/失败/取消也保留实际测试、GUI 状态、Diff 和未完成原因 |
| Windows 焦点 | UIA SetFocus 不保证前台激活 | 先请求标准 SetForegroundWindow，再检查实际前台；拒绝时不发送输入，不修改 Windows 策略 |
| 任意 Pane 输入 / 任意 GUI 通用验收 | 未实现 | 本轮不实现；依赖标准 UIA 与显式确定性验收契约 |

## Phase A：两个不同的边界

`max_model_steps=16` 仍为单个 slice 上限，不是无限循环。默认允许额外续跑 2 次；同次执行最多 48 个逻辑模型步骤。实际请求（含重试）另受累计 64 次限制。调用同一 `run_tool_turn`，没有新增 Agent Loop，也没有独立 Planner 请求。

环境变量在创建任务预算时读取并冻结：

| 变量 | 默认值 | 上下限 |
| --- | --- | --- |
| `LCA_EXECUTION_MAX_CONTINUATIONS` | 2 | 0..8 |
| `LCA_EXECUTION_MODEL_CALLS` | 64 | 1..512 |
| `LCA_EXECUTION_TOKENS` | 2000000 | 1..20000000 |
| `LCA_EXECUTION_SECONDS` | 900 | 1..7200 |

Token 数是保守预留：完整请求 UTF-8 字节数（包含工具 schema、图片）加最大输出 Token，不是服务端实际计费量，不退款。Task 原有 RoutedProvider/BudgetGuard、输出限制、请求超时和总任务时间仍同时约束；先耗尽的边界生效。离线关闭程序的时间不计作活动执行时间，恢复前已消耗的活动时间不清零。

slice 到期先写 checkpoint，续跑沿用内存真实工具结果；重启只恢复脱敏执行元数据、计划、变更路径与既有产物引用，模型须重新读取实际状态。不会重放保存的工具参数。已完成文件变更指纹防重复；同 turn 活进程可复用，真正结束/Stop 时清理，重启后的旧进程/窗口句柄不得直接复用。

累计预算耗尽会暂停。Plan 的“增加执行预算”需明确点击确认，每次固定增加 16 次请求、500000 Token 保守预留、300 秒与 1 次续跑，均受绝对上限约束，历史消耗不变。Task 的 API/总时间预算仍需通过其既有配置入口明确增加，不会随此按钮自动放宽。

## Phase B/C：恢复不是清空失败

工具失败先记录诊断，原模型可在本次执行内修复并真实复测；如果最终停止，保留 blocked 与恢复动作。失败的命令/UIA 等待断言仍无同类成功复测时，禁止仅凭模型文字宣告完成；可选文件发现失败允许更换正确路径，最终仍受独立验收约束。重启前/取消时尚无结果的变更属于未知副作用：再次变更需单独审批，即使 Full access 也不能绕过；读目录等检查仍可进行。已成功重试的同指纹操作才会对账为 reconciled，其余未知操作继续阻止完成。

恢复动作按权限、环境、测试、模型、重复调用、控件兼容性分类。普通可恢复环境错误可在继续消息时先自动只读探测；其他 blocked 使用 Plan 的 Continue plan。后端真实检查工作目录后才转为 in_progress，保留原失败、已完成步骤、执行日志与 checkpoint。目录不存在则保持阻塞。新发现窗口仍需 M3 授权，失效的窗口/进程由模型通过现有工具重新发现，不能根据旧 ID 自动点击或重放启动命令。

Task 所属 Plan 只能转回 Task 恢复，不能在源工程聊天中误执行隔离 worktree 的步骤。历史任务、多个 Thread、连接配置和已有 SQLite 数据均不删除；只做加表/加列迁移。

普通聊天忽略暂停 Task 的计划，Composer 仍可发送消息，不会占用或清空 Task 的累计预算及 checkpoint。Windows 工具额外通过 WTSInfoEx 读取当前会话锁定状态；锁屏、非活动或未知会话明确拒绝，并在输入前再次检查。恢复桌面步骤时也先检查会话，不能用一次目录成功就跳过锁屏阻塞。实现依据 [WTSINFOEX_LEVEL1_W](https://learn.microsoft.com/en-us/windows/win32/api/wtsapi32/ns-wtsapi32-wtsinfoex_level1_w)。Windows 10/11 支持；不支持 Windows 7 的反转标志兼容。

新增诊断只保留固定中文原因与动作码，不保留输入参数、文件正文或工具输出。未知错误码归一化为 TOOL_FAILED。现有用户消息、终端验证日志和本地 Diff 仍按原产品规则保留并脱敏；不要把原终端输出当成新增隐私诊断日志上传。

## Phase D：独立证据与限制

复用原 TaskService → Single Agent → VerificationEngine → M2 ProcessManager → M3 desktop 工具。验收仍先确定性测试/构建，再执行冻结 GUI 契约；视觉结果只作观察，不能覆盖失败的 UIA/程序断言。既有测试、GUI 配置、关键类型检查配置和 npm test/build/typecheck 脚本在模型执行前散列快照；已有验收文件修改会暂停并要求审阅 Diff，不运行被改写的验收标准。暂停后用户明确 Apply configuration 才能刷新基线。

该保护是有边界的工程防误改机制，不是针对恶意仓库的沙箱。测试数据超过 2 MiB 或 2000 个已有验收项时明确停止，需缩小验收范围；不保证识别任意自定义测试框架的所有入口。新增测试可以执行，但不能替代已有断言。

演示与自动化入口见 `manual-fixtures/m4-continuation/README.md`；验收结果另记 `closure-acceptance.md`。无需本地 GPU 或大型模型。真实百炼只在现有 Live Test、可用凭据和明确授权/预算条件均满足时执行；本轮离线回归不发送付费请求。
