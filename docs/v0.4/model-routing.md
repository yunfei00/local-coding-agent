# 多连接模型路由

## 配置与解析

Settings → Models & Routing 将 Provider Connections、Model Profiles 与 Role Routing 分开保存。普通聊天仍沿用 Provider 页的活动模型；切换聊天 Provider 不会改变自主任务角色。

连接包含 connection_id、display_name、provider_type、base_url、credential_reference、enabled。允许多个 Ollama 或 OpenAI Compatible 连接。URL 不接受内嵌用户名、密码、查询参数或 fragment，凭据通过安全存储单独设置。

模型配置包含 model_profile_id、connection_id、model_id、display_name，以及可选 context_window、max_output_tokens、temperature、pricing、tool_mode。不同连接可以存在同名模型；下拉框同时显示连接、模型、类型与配置 ID。手动添加时避免重复；迁移可为同一模型保留不同角色参数的独立配置变体。

四角色独立绑定 model_profile_id。每次调用沿 Role → Model Profile → Provider Connection → 原 Provider Client 解析。新任务启动时保存 resolved_roles（含连接地址与模型限制）和全局预算快照，不含密钥。已有任务不被目录迁移或默认值更新回写。

## 策略

默认 Local-first：Planner、Executor、Reviewer 的初始分类为 local，Escalation 为 API。建议前三者绑定 Ollama，Escalation 绑定 API；用户显式选择的其他角色绑定也被尊重。简单任务使用本地 Reviewer 时 API 调用为零；若用户主动绑定 API Reviewer，审查请求也计入 API 预算。

Local-only 对 API 绑定报 MODEL_POLICY_MISMATCH，在发送之前拒绝，不会改用同名本地模型。达到修复限制暂停，不调用升级模型。API-only 要求实际执行的角色绑定 API 配置，每次调用同样通过 BudgetGuard，不因模式切换绕过预算。旧任务无 profile ID 的快照保留旧的策略强制分类行为以兼容恢复。

Ollama 是否属于 local 由 provider_type 决定，与 localhost、局域网或域名无关。连接失败明确暂停，不静默切换到其他收费连接。

## 存储和迁移

目录保存在 SQLite settings 的 models.catalog.v1，角色绑定沿用 orchestration.config。第一次读取时，将两类旧地址和各角色旧模型确定性迁移；旧 API 密钥使用 legacy-openai 引用，仍留在原安全存储中。迁移目录和默认绑定在一个事务中写入，重复执行不重复创建。损坏的数据报错并保留原记录。

新连接凭据使用 connection-<connection_id> 引用。Electron 的 model-secrets.json 仅保存 safeStorage 密文；OS 存储不可用时仅会话有效并显示提示。Python 只在内存中接收凭据，SQLite、任务、项目和日志均不保存密钥。不要复制密文到其他 Windows 账户期待直接解密；换电脑应重新安全输入凭据。

任务恢复继续使用原 resolved_roles 与预算账本。暂停后 Apply configuration to paused task 才显式刷新角色、地址与验证命令。更改凭据需先停止执行。删除绑定中的模型应先重新绑定角色；后端拒绝悬空或禁用的绑定。

## 实际调用与能力

model_requests 沿用预算账本，追加连接 ID、模型配置 ID 和 Provider 名称到请求元数据。Task 中的 Model call journal 来自服务端持久化记录，含角色、时间、模型、状态；API Token 来自实际远程请求 Usage，缺失时标为估算。失败、超时和恢复不清零预留。

Ollama /api/show 检查工具能力，不支持时使用严格 JSON 兼容；也可显式选择 auto/native/json。兼容调用仍走原工具权限、审批与 Git 保护。连接测试只读取模型列表，不证明模型能完成复杂编程任务。

升级输入仅包含有界目标、Diff、失败和尝试摘要，脱敏后发送；Escalation 无工具权限。收到建议后继续原 Executor，再由程序独立验证，不能以模型自述替代测试。
