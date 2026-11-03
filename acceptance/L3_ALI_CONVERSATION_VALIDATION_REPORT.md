# 阿里在线模型与同页自主开发验收

## 范围与结论

2026-11-03～2026-11-04，Windows 11 / Python 3.12.13（uv）/ Electron 38.8.6。沿用 `test/agent-functional-validation`，没有新建分支、合并 main、强推、发布 Tag/Release/安装包或删除用户历史。同页主体源码 `1f611054390e22af7820d0fc5f904325127b2177`，补充 GUI/错误恢复源码见收尾记录。

综合结论 **PARTIAL**：本轮同页自主开发、固定业务合同、同任务追加、重启恢复和真实阿里 Electron/视觉路径通过；部分指定模型仍准入失败或不能稳定完成 GUI，本机 1.5B 模型未完成本地自主任务，不能声称“所有模型、全部真实混合组合都 OK”。DeepSeek 历史 403/BLOCKED 仍见原 DeepSeek 报告，没有改写成 Qwen PASS。最终源码/CI 见收尾记录。

## 同页交互与实现

- `App.tsx` 复用原聊天输入框。选择“自主开发 · 自动验证”后提交目标；在线选择绑定到 Single Agent Executor，Ollama 选择绑定到 Local-only。已有高级 Task 面板继续负责 Local-first/四角色、自定义验证与诊断，不创建平行 Loop。
- `ConversationTask.tsx` 在消息流内显示实际阶段、调用模型、用量、计划、工具事实、独立测试、报告、Diff、暂停/停止/继续/接受按钮。详情折叠，输入框始终可编辑；自动跟随仍尊重手动阅读历史。
- `task.continue` 在同一 TaskPlan 上追加待执行步骤；保留 Task ID、Worktree、Completed、执行证据、模型/预算快照和累计请求账本。消息 ID 幂等，重发不会再启动执行；验证失败不会靠改数据库伪造通过。
- `state.append_message` 保存真正的用户需求与追加消息；内部执行提示不再作为重复用户消息保存，重启可恢复。手工 v0.3 Plan 与普通聊天仍使用原路径。
- 验收定位并修复新增链路缺口：Electron IPC 白名单漏接 `task.continue`；验证阶段原 Stop 仅依赖内部 turn 状态；进度卡在 flex 横向流中被裁切。现在分别接通请求、按 Task 活动状态显示 Stop、把卡片置于消息列内并增加位置断言。

运行中可编辑下一条消息，需暂停/结束后发送；本轮未实现运行中消息排队/实时引导。现有任务不会因底部切换模型而暗改配置。追加上限 32 条、总需求 32000 字符/100 步，达到时明确要求新会话，不是无限任务。

## 真实在线工程证据

使用已有阿里 OpenAI Compatible 连接和 Electron OS 安全凭据；控制器不获取密钥、不配置假 Provider、不替 Agent 写优惠券业务实现。只准备 L2 兼容基线、固定业务合同和独立验证器。用户说明连接使用免费额度；网关未返回可核实费用，费用标 UNKNOWN，不把 actual_cost=0 当作免费计费证明。

### 结构化 Planner 闭环

`validation-reports/ali-coupon-live.json`：Qwen3.7-plus，API-only，Task `d2978f8e-ac9c-44ce-921a-97bb2e28fa91`，33 次真实请求、31 次模型工具操作、2 次执行尝试、0 次 repair/escalation，终态 awaiting_approval。真实文件由 Agent 创建，52 项工程 unittest 与 git diff --check 成功，外部独立 12 项合同检查成功，原 L2 测试未修改、源工程未修改。Usage：输入 839416、输出 17195、合计 856611；缓存 79360 是输入子集，不再次相加；未结算预留 0。此首轮临时工程已由原控制器清理，保留 JSON/日志证据，不能声称文件仍存在。

### 同页开发、追加与独立验收

`validation-reports/ali-conversation-contract.json`：Qwen3.7-plus，经真实 Electron 聊天输入框提交，Task `7c239643-fb65-471d-b799-84411863ba55`。Agent 自行读取原文件和冻结合同、创建 coupon_engine.py/自写测试/中文 DELIVERY.md，运行验证与 Diff；外部监督未替写实现。

第一轮 13 次请求后追加报告需求，仍只有一个 Task、同一个 Worktree、原 Completed 步骤保留，后续累计到 17 次请求；两步最终均 completed，独立验证后为 awaiting_approval，没有自动接受、提交或合并。52 项工程测试（包含固定合同、L2 和模型自写测试）、外部独立 12 项检查、Diff、中文追加报告章节全部通过。源目录干净，冻结测试未修改。

最终 Usage：输入 251957、输出 13049、合计 265006，缓存 64384 为输入子集，estimated=false、in_flight_tokens=0，费用 UNKNOWN。22 次模型工具操作，2 次执行尝试，0 次编排 repair/escalation；初始失败命令/缺少实现的测试反馈在同一模型执行轮内由 Agent 处理，不能把 repairs=0 解释为从未遇到工具失败。

生成工程保留在本机 `validation-reports/coupon-project-7c239643-fb65-471d-b799-84411863ba55`。完整报告和工程由 Git 忽略，不发布截图或完整模型 Prompt。此在线试验启动基线为 fcab4e7 加当时工作区的冻结合同改动，已纳入最终源码 1f61105；最终源码的桌面布局、自动化回归与 CI 单独验证。

### 未通过的尝试也保留

- `ali-conversation-live.json`：Qwen3.8-flash 第 4 个请求 MODEL_TIMEOUT，保留预留；没有无限请求。
- `ali-glm-conversation-live.json`：GLM-5.3 首请求 HTTP 403；`ali-max-conversation-live.json`：Qwen3.8-max 首请求 403。不能仅据此确定是密钥、权限或免费额度问题。
- `ali-kimi-conversation-live.json`：kimi-k3 首请求 HTTP 400；该配置的兼容性未通过，不能当作 coding PASS。
- 两轮 Qwen 初始业务及外部 12 项测试成功，但桌面续作因 IPC/控制器接线未通过，原 FAIL 保留。
- `ali-conversation-verified.json`：同页续作成功，但模型将到期日字符串误作 date；自写测试通过，独立合同 2 ERROR。因此整轮 FAIL，没有把 awaiting_approval 等同最终业务验收通过。随后将同一固定合同放入受保护的用户测试，在新独立任务中让 Agent 自行实现/测试，得到上面的 PASS；没有削弱断言。
- 累计 session 账本保留旧请求和失败预留，不清零。按用户“无需反复提额、以实际工作为准”的授权提高本地验收会话上限，仍有请求超时、明确单轮重试上限和框架无进展/权限/进程树保护。未改变产品已有任务的预算快照。

## 自动化与原生桌面

| 检查 | 结果与证据 |
| --- | --- |
| 本机 validation/check.py | 463 项 Python：461 PASS、2 SKIP；前端 51 PASS；类型与构建 PASS。日志 20261103-203054-881033.log；这是补充两项最终测试前的基线，不和最终总数累加 |
| 新续作编排 | 29 项 PASS，含真实文件、unittest、Worktree 不变、原步骤保留、消息及幂等；conversation-orchestration.log |
| 最终控制器/固定合同 | 29 项 PASS；conversation-live-controller-final.log |
| 最终桌面烟测 | 51 PASS、0 SKIP；conversation-desktop-layout.log / desktop-smoke.json。包括同页启动/追加、实际 HTTP 工具、重启消息恢复、用量不变、卡片在聊天列内不裁切，以及原有删除、菜单、Git/Context、Stop、WebSocket 重连等 |
| Windows CI | 465 项 Python：463 PASS、2 SKIP；额外 focused M5 3 PASS（已经包含在全量中，不重复计数）；前端 51 PASS；桌面 51 PASS；类型/构建 PASS |
| Ubuntu CI | 465 项 Python：449 PASS、16 SKIP；前端 51 PASS；类型/构建 PASS。Windows 专属桌面按既有平台门禁跳过 |
| 凭据与 Diff | 397 文件扫描 0 findings；git diff --check 成功。模式扫描不能证明所有可能的秘密格式不存在 |

同页主体源码 CI：[41640594432](https://github.com/yunfei00/local-coding-agent/actions/runs/41640594432)，Windows/Ubuntu 均 success。完整日志本机 conversation-ci.log。已取消过期中间提交的 CI，未取消最终源码验收、删除或弱化关键测试。

## 补充真实 Electron / GUI 复测

`ali-electron-functional.json` 首轮 40 次请求：代码检查通过，独立 GUI 在保存状态断言失败；随后模型遗漏工具风险确认，留下未解决错误并以 PLAN_TOOLS_UNRESOLVED 暂停。没有假报通过。

`ali-electron-repair.json` 第二轮 37 次请求：依旧未通过 GUI 完整合同，终止于未解决工具/重复读取，无无限重放；这也不是 PASS。外部查看受控失败截图可见普通 Saved 与持久化值已改变，但合同期望 `Status: Saved: M5 verified A`，现有失败反馈仅告诉模型 DESKTOP_WAIT_TIMEOUT，丢掉了期望的控件名称。这是本轮新定位的软件信息丢失问题。

修复：b0abf3c 给 Single Agent 一次持久化、有预算检查的错误完成反馈；再次错误宣告完成、明确权限拒绝或额度不足仍停止，不替模型补工具参数、不绕过审批、不重放完成操作。ca94c37 保留最近两个失败 GUI 合同断言（控件名称/类型、状态/期望、错误码），排除实际屏幕正文和旧 runtime/window 句柄；同一摘要用于 Executor、诊断和升级上下文。未解决工具码单独保留，避免随后无关的成功命令清掉真正原因。

针对性回归：Single Agent 19 PASS（含实际失败→错误完成→修复→真实复测、重复完成停止、恢复不重置机会、额度不足不发请求），恢复/权限 19 PASS（明确拒绝不触发反馈），真实 M4 GUI 8 PASS（断言实际进入修复模型），诊断/WS 3 PASS（2000 条完整历史保留、传输有界、选择器脱敏），均未替换工具实现。日志分别为 gui-feedback-single-final.log、completion-repair-recovery.log、gui-feedback-m4-final.log、gui-feedback-diagnostics-final.log。

第三轮 `ali-electron-final.json` 在 ca94c37 对应的工作区运行：31 次真实请求，终态 paused，明确原因为 `desktop_wait (DESKTOP_WINDOW_STALE)` 尚无成功复测；没有忽略旧窗口失效强行完成。

第四轮 `ali-electron-flash.json` 改用已实际测试文本/工具/随机像素识别均通过的 Qwen3.8-flash。36 次请求，代码检查和全部 GUI 合同控件步骤成功，但最后视觉输出 schema 无效，整体 FAIL。过去的原始视觉正文未保存，不能断言它具体返回哪种错误类型。4c2bc48 明确完整 schema 边界，同一授权图片/Provider 最多一次格式修复，每次走原 Budget Guard；不接受默认空 errors、不执行观察模型工具、不重放 GUI。实际 Windows M4 11 项回归 PASS，包含错误格式→正确格式的两个 Observer 调用记账，及两次无效后停止。

第五轮 `ali-electron-observer-fixed.json` 已得到有效视觉 JSON，却将截图的 `EDIT CONTENT REDACTED` 安全遮盖误判为乱码并尝试修复。根因是工作器已经遮盖内容，但图片消息未带对应脱敏说明；这是框架上下文缺失。外部监督通过该隔离 Electron 的实际 IPC 暂停任务，51 次请求保留在账本，整轮 FAIL/TASK_PAUSED，不能冒充模型自行收敛或通过。

0cd3c5e 把捕获工具生成的遮盖数量/说明附到授权图片上下文，并要求 Observer 不从遮盖区域推测输入值或界面故障；仍检查未遮盖的可见问题，不删除模型 errors。密码框继续全黑、普通编辑框继续遮盖，未关闭审批、未泄露编辑内容。真实 M3 11 项：10 PASS、1 个非 Windows 契约 SKIP；4 项合同单测、2 项 Observer schema 单测、3 项诊断/WS 回归通过。

### 最终真实 Electron 全流程：PASS

`validation-reports/ali-electron-redaction-fixed.json`，源码 **0cd3c5e0a382c4e23ea1b0f960fac9d23fac2c47**，Task `5e18a505-2d80-4e47-ac1e-19b72a75b0d4`。Qwen3.8-flash 为 Executor 和独立只读 Observer，真实 Agent 自行修改 `src/App.tsx`；保留原测试、package scripts 和 `.lca` 合同。外部监督没有替写业务代码。

- npm run typecheck、npm test（2 项）、npm run build、git diff --check 全部真实成功。
- 实际启动受管理 Electron，按精确标题及所属进程树定位窗口。独立 12 步 GUI 合同（包含 6 次状态断言）通过：可编辑、写入 A 后保存/持久化、再写入 B 后保存/持久化。最后实际磁盘值 `M5 verified B`。
- Observer 收到真实 14390 字节 JPEG，tool_schema_count=0，图像 SHA256 `9f38750ad9fd263f12d372093e614b619b34c20ecf1a5866da69c47cfce9b3d9` 与本机保留 PNG 转换匹配。外部查看截图，Settings、保存状态、持久化文本、遮盖框与主要观察吻合。细小焦点边框颜色描述未作为通过依据，不能把模型视觉叙述当成逐像素断言。
- 最终 observations 明确输入内容被捕获工具遮盖、不可从图片评估原值；errors=[]。保存的具体值由 UIA/磁盘独立验证，而非由视觉模型猜测。
- 一次执行尝试、0 次编排 repair、计划唯一一步 completed，Task 正确进入 awaiting_approval。没有自动接受、提交或合并。
- 52 次真实请求：50 次 Executor、2 次 Observer，分别来自执行阶段与独立验证阶段；本轮未触发 schema 重试，不能把两个 Observer 调用误记成一次格式重试。
- Usage：输入 1256314、输出 17774、合计 **1274088**，缓存 234496 为输入子集；estimated=false、in_flight_tokens=0、费用 UNKNOWN。
- 原始 fixture 未修改、受保护验收文件未修改，Diff 非空；记录的 **15 个自有 PID 全部退出**。模型也曾遇到工具失败并据反馈纠正，repairs=0 只指 Task 层独立验证修复计数。

截图仅本机 `validation-reports/real-online-local-artifacts`，不提交。最终 PNG SHA256 `56e31de9f2643e3f33c8057ad7eb69eba110026b569df9859ec834bd5d7c2922`。该试验临时业务工程按控制器策略清理，Diff、哈希、测试、进程及请求证据保留；不声称完整 Electron 工程仍在磁盘。

另以原模型诊断入口检测 Qwen3.8-flash，文本/工具/随机图像挑战均 PASS，共 3 次模型请求；抓取 183 个可见模型名，未添加模型、未改变角色或聊天默认值，roles_preserved=true。见 ali-vision-capability.json。它证明基础视觉能力，不单独替代上述完整 GUI 工程。

### 真实本地模型对照

本机 Ollama `/api/tags` 成功，已安装 `qwen2.5-coder:1.5b`。使用既有 `v04_model_smoke.py --mode ollama --model qwen2.5-coder:1.5b --context 8192 --seconds 180` 运行隔离计算器任务：4 次真实本地 Planner 调用，1 次 MODEL_INVALID_RESULT、随后 3 次 PLAN_JSON_INVALID，达到持久规划上限后 paused；**API calls=0、API Token reservation=0**。日志 local-ollama-validation.log、v04-ollama-20261104-005501/result.json。服务连通/无远程调用成立，完整本地自主修复 FAIL；不将 1.5B 模型的结构化规划能力不足定为框架缺陷，不把它说成 Local-first 真实升级组合 PASS。

## 最终回归、代码审查与 Git

最终功能源码 **0cd3c5e0a382c4e23ea1b0f960fac9d23fac2c47**。双平台 CI [41677424169](https://github.com/yunfei00/local-coding-agent/actions/runs/41677424169) 全部 success，本机完整日志 ali-final-source-ci.log：

| 平台/检查 | 最终结果 |
| --- | --- |
| Windows Python | 474 项：472 PASS、2 SKIP、0 FAIL/ERROR |
| Ubuntu Python | 474 项：457 PASS、17 平台门禁 SKIP、0 FAIL/ERROR |
| 前端（两平台） | 51 PASS，类型检查与生产构建 PASS |
| Windows 原生桌面 | 51 PASS、0 SKIP，含同页追加/重启/消息/预算恢复；JSON 日志确认 ok=true |
| Windows focused M5 | 3 PASS，已包含在全量中，不重复累计 |
| 凭据扫描/Diff | 源码 397 个文件、0 findings；diff --check PASS，报告入库另扫 |

最终审查检查了：新增字段对旧 Task 的默认值；续作的合法状态、输入/总长度上限、消息 ID 幂等；模型/预算和 Worktree 保持；完成证据门禁；明确拒绝不重试；两类格式反馈均有固定上限、原预算检查和进程清理；脱敏说明不包含输入值。没有放开文件权限、自动发送到其他模型或降低既有验收断言。旧 v0.3/四角色混合路由/Checkpoints/Execution Journal 测试仍在全量中。

开发与验收均在 `test/agent-functional-validation`，对应现有 [Draft PR #27](https://github.com/yunfei00/local-coding-agent/pull/27)。复核 origin/main 仍为 `1657e53983da6e2c3bcf22144abe86ca03b70f80`，未合并。`.codex-attachments/` 与 `local_coding_agent.egg-info/` 原有未跟踪内容保留。源码提交和此报告分开，报告提交不包含业务实现、截图、API Key 或原始 Prompt；不创建 Tag、Release、安装包。

建议先审阅后按已通过的模型与流程做公司部署；**不建议把本轮结果描述为全模型稳定或完整 Codex 等价**。保留 Draft 分支，没有自动合并决定。仍缺运行中消息排队/实时引导；真实 Local-first CPU 模型→强 API 回交完整组合尚未通过本轮真实环境验收；Qwen3.7-plus 在同页优惠券工程通过但 M5 GUI 多次不收敛；GLM/Max/Kimi 的本轮准入失败保留。安全停止这些情况是预期门禁，不伪造 Completed。

## 2026-11-04 发布范围确认

在上述综合报告完成后，用户明确授权“现在合入主线并发布，以在线模型为准”。本次 v0.5.0 按已通过的在线自主开发与 GUI/视觉场景作为准入条件，允许合并与发布；原 PARTIAL 及本地模型/部分网关限制保留，不倒改历史测试结果。版本升级、合并、安装包与正式 Release 证据见 [v0.5.0 发布说明](../docs/releases/v0.5.0.md)。

## 边界与公司更新

本轮验证具体流程，不代表任意模型、任意仓库和任意网络环境均通过。DeepSeek 和部分 Ali 模型准入失败仍是真实限制；Local-first 的真实 CPU 本地模型→强模型升级组合本轮未复测，相关离线路由/预算回归通过。公司安全策略、网络代理、系统安装包启动和长期磁盘压力未在公司设备上自动重演。本轮没有新安装包，旧 v0.4.2 安装包不含这些源码变化。

公司更新完整命令和同页操作见 [company-validation.md](../docs/v0.4/company-validation.md) 与 [user-guide.md](../docs/v0.4/user-guide.md)。需完整退出应用，更新既有验证分支、uv sync --locked、npm.cmd --prefix desktop ci、npm.cmd --prefix desktop run build，再使用仓库原启动脚本；仅刷新界面不会更新 Electron IPC。模型安全凭据保留，无需清空配置或用户任务。按此前要求保留验证分支，不自动合并 main。
