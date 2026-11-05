# v0.8 基线审计

日期：2026-11-05。已 `git fetch origin`，最新 main 为 `00954ecd921c28823764e02e3a2d91b3c2720454`，其合并后 Windows/Ubuntu CI（41975733096）成功。创建 `feature/v0.8-intelligent-context`；没有已有同名开发成果。保留 `.codex-attachments/`、egg-info，未覆盖用户数据。

| 范围 | 现状 | 扩展点 |
| --- | --- | --- |
| Runtime / L2 / L3 | 已实现，可复用 | `AgentServer.run_tool_turn`、TaskService、同一 SQLite、ToolLoopGuard；不得新增执行循环 |
| Provider / 连接与四角色 | 已实现，可复用 | ModelCatalog 的连接/模型身份、凭据引用、快照和 ModelRouter；当前 Chat 固定模型，无能力规则自动路由 |
| 能力检测 | 部分实现 | ModelDiagnostics 的真实文本/图片/工具探针、配置指纹；缺统一三态、有效期、可用性/成功率和选择原因。不得按模型名称推断能力 |
| 回退 | 部分实现 | 同模型网络/格式有限重试已有；无保留原执行账本的跨模型回退；需明确手动授权边界 |
| 长期项目记忆 | 部分实现 | PromptRules 已有项目规则，Pinned Context 已有显式文件，ExecutionBudget 有运行级工具事实；缺项目知识跨会话管理、候选/已验证区分及过期来源检测 |
| 工程检索 | 部分实现且存在安全缺口 | RepositoryMap 已有符号/文件元数据及增量刷新，SearchFiles 有真实行号片段；缺持久内容索引、全文排序、损坏重建；现有 RepositoryMap 没有完整 gitignore/符号链接读取边界，索引扩展必须先修复 |
| 上下文 | 已实现，可增强 | ContextBudgetManager、字节估算、工具批次完整性、有界工作记忆、原始目标和持久计划已存在；增加项目知识分区预算、压缩/恢复可观测性、阶段/工具上限 |
| 恢复/预算/审批 | 已实现，可复用 | RuntimeLedger、Checkpoint、ExecutionBudget、BudgetGuard 保留真实证据和未知副作用审阅；模型切换不能重置任何计数或重放成功操作 |
| 环境诊断 | 部分实现 | 工程识别/命令建议、错误分类、脱敏诊断已存在；缺统一可执行只读探针、受审批修复及验证知识沉淀 |
| Windows Computer Agent | 已实现，可复用 | v0.7 窗口/UIA/截图回执/输入/取消和资源保护；本轮只做受影响回归 |
| 桌面 UI | 已实现，可扩展 | 主聊天、模型选择、Context、按需任务/诊断；增加中文自动/手动选择、记忆/检索及状态，不增加开发模式 |
| Git/MCP | 已实现，必须兼容 | 原注册、工作区权限、Worktree 和审批；新知识工具纳入同一 ToolRegistry |

基线验证：`uv run --locked python -m unittest discover -s tests -p test_mixed_provider.py -v`：19 PASS；同命令 `test_context.py`：5 PASS。对应日志 `validation-reports/v08-baseline-models.log`、`v08-baseline-context.log`。已验证 HTTP Mock 不等于真实模型验收；未连接 Ollama。完整回归在实现冻结后串行执行。

设计边界：现有 Catalog/持久化/RepositoryMap 上增加能力、记忆和内容索引元数据；模型调用仍经过原请求预算与执行日志；知识内容属于带来源的不可信数据，不提升工具权限。未知能力不能当成支持。禁止模型拦截必须在真实发送前、探针与路由入口同时生效；不修改日常模型配置。
