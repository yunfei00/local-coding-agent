# Task 首次 API 请求前暂停：审计与修复

基线：main `9aba5b41f07f045d00abf1f8cca44d0fc9e5a891`，v0.4.2 后未发布的 Planning 修复。工作区起始干净；本轮不创建 Tag、Release、安装包。不使用真实 API 或凭据。

## 已证实的问题与证据边界

1. `AutonomousTaskPanel` 只在挂载时读取配置，启动时提交整个缓存 `config`。如果后台/其他配置客户端在面板保持挂载时更新设置，旧预算（包括显式零）、策略和 Planner 绑定会覆盖后端最新 Settings。这个缓存覆盖路径已自动复现。进一步核对 App 后确认：正常打开 Settings 会关闭 Task 面板，重新打开会重新读取，因此不能把该缓存路径认定为公司当次根因；API-only 本身也不会自动把非零预算改为零。
2. `BudgetGuard.reserve` 用同一句错误描述任务和全局的调用数、Token 上限，且在账本插入前抛错。用户只能看见本任务的 0/0，无法区分零预算、首次请求预留超限和其他任务已消耗的全局预算。失败前的数值也没有持久化。
3. 零值与缺失值原有语义没有颠倒：缺失调用/Token 上限分别默认 3/30000；明确 0 保留，禁止 API；数字限制为 null 会拒绝配置，不应改为默认值。API-only 不自动增预算，也不读取历史任务配置。旧任务恢复保留原快照是正确行为。

公司当次究竟命中哪一个字段，旧版本错误没有留下足够数值，不能追溯断言。当前代码和 Mock 已证明上述软件缺陷和三类 0/0 拦截路径；更新后同类失败会显示具体字段。没有通过自动增预算、清账或关闭权限来规避。

## 真实调用链

| 阶段 | 实现与数据来源 | 失败处理 |
| --- | --- | --- |
| Settings 保存 | `ModelSettingsSection` → task.catalog.update → SQLite `orchestration.config` / `models.catalog.v1` | 校验模型、预算、连接；保留显式零 |
| Task 创建 | Task 面板比较挂载配置与用户编辑，仅提交 `config_overrides`；task.start 在后端重新读取最新 Settings | 仅合并实际编辑的字段，不复写未编辑的缓存预算/角色；原 `config` RPC 保留兼容 |
| 策略和角色 | validate_config → ModelCatalog.resolve → Role / Model Profile / Connection | 独立冻结 resolved_roles；API-only 与 Ollama 绑定冲突明确报错，不静默切收费模型 |
| 配置快照 | TaskRuntimeStore.create / save | config + resolved_roles + global_budget + provider_settings + config_source / config_snapshot_at 持久化；全局上限来自同次读取的保存设置 |
| Planning | TaskService.run → ModelRouter.resolve/plan → RoutedProvider.stream_chat | 检查策略、已有规划重试上限，不使用 Chat 下拉框推断 Planner |
| 预算预留 | BudgetGuard.reserve，SQLite BEGIN IMMEDIATE | 输入 UTF-8 字节估算（包含工具及 256 开销）+ 配置输出上限；先检查任务再检查全局，`used + required > limit` 才拒绝；相等可用 |
| HTTP 请求 | 预检查通过才插入 model_requests，随后原 OpenAI Compatible Provider 请求 | 预检查拒绝没有 HTTP，也没有已准入 Call；拒绝用独立 attempt_id 关联 Task、阶段、角色、模型 |
| 解析与执行 | 原结构化计划校验 → Executing → 原 Agent Loop / ToolRegistry | 继续复用 Planning 修复的上限和 Schema 诊断；原 Worktree、权限、审批不变 |
| 验证与结算 | VerificationEngine / unittest / Diff；BudgetGuard.finish | 可信 Usage 结算释放多余预留；未知请求保持占用；测试通过才 awaiting_approval，不自动 completed |
| 暂停/恢复 | TaskService ProviderError 处理 → last_error.budget → task.diagnostics | 事务回滚后保存拒绝详情；保留 JSON/Markdown；恢复不重置旧预算，不重复扣费 |

## 为什么零次调用也会被阻止

- `api_calls=0`：`0 + 本次 1 > 0`，必须禁止发送。
- `api_tokens=0` 或本次估算超限：即使已用为零，也需要先为输入和最大输出预留。例如输出上限 32768 已超过任务 30000 Token，尚未加入输入便不可能准入。
- `global_api_calls` / `global_api_tokens` 耗尽：本任务计数为零，全局仍包含其他任务、失败未知请求及重启前记录。

所有这些路径现在分别给出 scope、field、limit、used、required、remaining、api_calls、reserved_tokens、in_flight_tokens、输入/输出估算、费用预留、任务和全局上限、触发规则、检查时间、attempt_id、request_sent=false。拒绝记录不冒充一次真实模型调用。

## 界面与兼容性

Task 显示具体预算拒绝公式和 Settings 入口，Settings 说明零值和全局累计语义。新 Task 启动响应回显实际配置和当前保存默认值，后续任务的显式覆盖仍有效。旧 Task 不因 Settings 保存或重启改变快照；需要变更时由用户明确 Apply configuration to paused task，账本保留。手动配置/预算更新会更新时间和来源。

原 model_requests、Task Plans、Checkpoint、Provider、安全凭据存储继续复用，无数据库迁移或新生命周期。
