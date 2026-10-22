# v0.4 混合 Provider 审计

审计日期：2026-10-22。修改前分支 `feature/v0.4-local-first-agent`，提交 `2c2b518`，工作区干净，已执行 fetch。v0.4 尚未合并或发布；沿用当前分支。

## 原有链路与根因

1. `RuntimeSettings` 只有一个活动 `provider`，但同时持久化 Ollama 与 OpenAI Compatible 的地址、模型、上下文和温度；并非另一类配置被删除。
2. Settings 的 Provider 页按活动类型显示字段；`model.list` 使用 `server.provider`，因此一次只列一个服务的模型。
3. `ModelRouter` 已按角色区分 local/api，`TaskService.make_provider` 可以切换两类客户端，但每类只有一个地址，API 只有一个密钥，不能表达多个同类型服务。
4. Escalation 已通过独立角色调用诊断，无工具权限；诊断之后回到原 Executor。现有 Mock 测试覆盖此过程，但没有多个连接的真实 HTTP 路由验证。
5. 四角色配置保存在 `orchestration.config`，角色只有模型名和 route，没有连接或模型配置标识，同名模型无法可靠区分。
6. 任务保存 `config` 与无密钥的 `provider_settings` 快照，Checkpoint 恢复保留它们；新配置迁移不能回写已有任务。
7. `BudgetGuard` 在请求前预留、在请求后记录 Provider Usage；API 分类原本按 role.route。必须改为按解析后的连接类型分类，局域网 Ollama 仍为 local。
8. `model_requests` 是预算持久化记录；目前缺少连接/配置身份的调用追踪。应在同一记录上扩展，不建立平行日志账本。

## 复用与修改范围

复用 Agent Loop、Provider 客户端、Task Plans、TaskRuntimeStore、BudgetGuard、VerificationEngine、Execution Journal、Checkpoint、权限审批与 Git Worktree。新增连接/模型目录并扩展原 Router 的解析入口，沿用原任务生命周期。Electron 继续使用 safeStorage，Python/SQLite 只保存凭据引用。旧 API 密钥引用现有单密钥存储，不能复制明文到目录。

主要修改：`agent/llm/router.py`、`agent/core/orchestration.py`、连接目录、`desktop/electron/main.ts`、Settings 与 Task 面板、Mock HTTP 与 Electron 验收。默认配置进行确定性、可重复迁移；运行中及已有任务保持原快照。

## 风险及验证要求

重点检查同名模型、多个同类型端点、禁用/删除后悬空绑定、Local-only/API-only 策略拒绝、设置变更与恢复、Usage 与失败请求预留、密钥泄漏和 UI 重启持久化。不得以只修改下拉框替代后端验证。真实付费 API 不作为自动化测试依赖。

基线验证命令：`uv run python scripts/validation/check.py`（Python、TypeScript、Vitest、前端构建）；运行 `20261022-103939-436505`，197 Python / 32 Desktop，通过，0 失败。

## 修复结果与证据

新增 `model_catalog.py` 管理非秘密连接、模型配置及一次性事务迁移；角色继续复用原 config。迁移保留同名模型不同角色的输出/上下文/价格差异，必要时生成独立配置变体。已有任务完全不回写。

Router 通过冻结的 resolved_roles 创建各连接客户端；账本元数据记录实际连接和模型配置。Local-only/API-only 在绑定类型冲突时请求前拒绝，不替换模型。Settings 的 Models & Routing 和 Task 下拉框均展示所有连接模型。新密钥通过 Electron safeStorage 独立存储，原单密钥继续安全引用。

验证见 `tests/test_mixed_provider.py`（独立实际 HTTP Mock 端点、原工具和真实验证）及 `scripts/validation/desktop-smoke.cjs`（Windows 实际表单、四角色和安全凭据重启）。最终数量、构建及发布证据见 [验收记录](acceptance.md)。
