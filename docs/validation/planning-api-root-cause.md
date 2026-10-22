# Planning/API 问题审计与根因

基线：main `e33cc26`（v0.4.2 发布后的文档合并）。本轮从干净工作区创建 `codex/fix-planning-api`，保留原提交历史。用户后续明确要求公司环境口述验证，本轮真实 API **NOT RUN**，仅使用回环 HTTP Mock。

## 观察与已证实的问题

用户观察的 24 次调用、46,776 预留 Token、Planning/Paused 和绑定冲突不是公司现场根因证据。本轮没有取得公司调用日志，不能断言公司实际 API 返回了哪种格式或错误。

已用该基线的原始 `TaskService.run` 与 `BudgetGuard`，连接本机 HTTP Mock 自动复现：API-only 下连续返回不同的无效计划，产生 **18 次 Planner + 6 次 Escalation = 24 次 HTTP**，仍未进入 Executing，最终 BUDGET 耗尽暂停。预留 **38,988**，Mock 报告输入 2,400、输出 480，实际合计 **2,880 Token**。数字与公司观察不同；这是受控复现而非真实 DeepSeek 消费。原基线完整测试 229 Python、32 Desktop、类型检查及构建通过，说明原测试未覆盖该组合。

确认的代码缺陷：

1. 无效计划复用执行修复计数 `repairs`。`escalate()` 每次诊断成功把它清零，规划再失败便重新开始。只有 200 次总迭代和预算/时间兜底，缺少独立规划进展上限；API-only 也沿用升级循环。
2. `ModelRouter.text()` 只拼接 content，Planner 忽略 tool_calls；JSON Schema 仅由提示和事后步骤验证表达。JSON 正确但结构不合法、空内容或输出截断没有完整区分。旧 OpenAI 客户端只解析 SSE data 行，application/json 返回可能变成空内容。
3. 完成且提供准确 Usage 的请求仍保留全部保守预留，界面中的 Reserved 容易被当作实际消费。多次规划/诊断把预留累积起来；没有证据表明同一 Call ID 被重复结算。取消/中断未知请求保留预留是必要保护，不能一概退还。
4. Model Call 账本已有 ID，但缺少 HTTP/结束时间/解析/Schema/下一状态，Task 捕获异常未进入全局错误列表。Task 按钮位于可滚动配置下方，Planning 时不易找到；诊断没有回答“为何未进入 Executing”。
5. Chat 使用活动 Provider 和会话模型；自主任务使用 `resolved_roles` 和预算快照。API-only 与已绑定 Ollama Planner 冲突时，原 Router 拒绝调用本身是正确保护。策略选择不应静默替换收费模型；问题是验证太晚、错误可见性不足。现在在 Worktree 和模型请求前验证角色，诊断包含角色/策略/阶段。

## 实际调用链

| 阶段 | 代码入口 | 模型/失败处理 |
| --- | --- | --- |
| Task 配置与开始 | AutonomousTaskPanel → preload.taskRequest → Electron agent:task-request → TaskService.handle | 保存策略、已解析角色、地址、模型参数和任务/全局预算快照；不使用聊天下拉框 |
| 路由预检与隔离 | TaskService.run → ModelRouter.resolve → 原 _authorize_tool/git_worktree_create | 策略冲突零模型请求；审批/权限不变，源项目不覆盖 |
| Planning | ModelRouter.plan → RoutedProvider.stream_chat → BudgetGuard.reserve | 持久化规划计数先递增；发送前事务检查任务/全局上限 |
| HTTP | OpenAICompatibleProvider.stream_chat / OllamaProvider.stream_chat | 记录状态、类型、起止时间；SSE/TCP 分片重组，兼容非流式 JSON；超时、网络、429 分类 |
| 计划契约 | agent/llm/planning.py + ModelRouter.plan | content JSON（含围栏）或一个 submit_plan；校验 schema/语义，拒绝空、截断和意外工具；不执行 Planner 工具 |
| 失败反馈 | TaskService.run 的规划分支 | 默认总计 4 次，允许 1..10；同一无效响应两次提前暂停。Local-first 最多一次规划诊断，API-only 不自动升级重试。计数不受 repairs 清零或 Resume 影响 |
| Executing | replace_unstarted_steps → planned=True → transition(executing) → 原 run_tool_turn | 只有计划有效才转入执行，复用 ToolRegistry、Task Plans、审批、执行指纹和 Checkpoint |
| 验证和完成 | VerificationEngine → Reviewer → awaiting_approval | 独立命令必须通过、Diff 和工作区指纹核对，不伪造 completed，不自动 commit/push/merge |
| 结算/取消/恢复 | BudgetGuard.finish、TaskRuntimeStore、task.pause/cancel/resume | 同 Call ID 仅结算一次；可信完整 Usage 释放多余 Token，未发送释放入账，超时/取消/无 Usage 保留预留；快照和计数保留 |
| 诊断 | 原 model_requests.usage_json + TaskRuntimeStore.transitions → task.diagnostics | JSON/Markdown 留存在应用数据 task-diagnostics；全局 Diagnostics 有任务错误摘要，Task 内可查看/复制 |

## 诊断内容与隐私

使用原 Task Plan ID 和 model_requests Call ID，没有第二套 Agent Loop、Provider Registry、状态机或付费重试器。记录请求序号、角色、阶段、Provider/Model/Profile、开始/结束、HTTP、finish_reason、响应表示、解析/Schema、错误码、重试次数、预留/释放/Usage、下一状态。没有真正发送的请求标 not_sent；没有 HTTP 响应时状态为 null，不伪造 200。

报告采用字段白名单，不包含目标正文、Prompt、用户文件、模型响应原文、Diff、Authorization、Cookie 或密钥。重复检测仅保存响应摘要哈希。网关可能回显请求的错误正文不会写入诊断。脱敏逐字符串进行，避免数字配置误匹配造成 JSON 损坏。旧历史账本保持原值，不修改既有消费记录或自动增加预算。

## 范围与仍需公司验证的事项

Mock 可以证明请求链、状态转换、次数/预算边界、工具和真实文件修改/测试；不能证明公司 DeepSeek 实际模型 ID、结构化输出能力、认证、代理、延迟或真实计费。保留这些边界，后续以用户公司口述的阶段/错误码继续定位。本轮不创建 Tag、Release 或安装包。
