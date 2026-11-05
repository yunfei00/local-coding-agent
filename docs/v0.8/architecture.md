# v0.8 架构与兼容边界

继续使用 AgentServer 的统一聊天入口和 run_tool_turn。能力路由仅解析具体 Provider，模型切换发生在未执行工具的请求边界；已有 ExecutionBudget、RuntimeLedger、Checkpoint、计划状态及权限保留。没有第二套 Agent Loop。

调用链：聊天选择（自动/手动）→ ModelCatalog → CapabilityRegistry → 冻结连接/模型/能力快照 → 原 Provider → 原预算预留 → 工具注册表/审批 → 实际验证 → 同一执行日志。手动切换收费模型必须显式允许回退。

项目知识使用同一个 SQLiteStore，数据库版本从 5 迁移到 6，新增项目记忆与派生索引表，不清空既有工程、线程、任务、连接和凭据。知识按 project_id 外键隔离。源文件检查共用 ProjectFiles；RepositoryMap 也补齐 gitignore 和符号链接边界。Worktree 的项目会话重新绑定知识对象，不能沿用主目录缓存。

项目记忆、检索片段均为有来源的数据，不改变系统指令、审批或工作区权限。环境修复始终进入原审批机制，包括 FullAccess；不自动修改系统 PATH、代理或安装系统软件。

扩展文件：core/model_routing.py、project_knowledge.py、project_files.py、environment_diagnostics.py；tools/knowledge.py、environment.py。前端仅扩展现有模型选择、Context 和 UnifiedProgress。
