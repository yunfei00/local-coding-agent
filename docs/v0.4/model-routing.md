# 模型路由

Task 面板提供 Local-first（默认）、Local-only、API-only。普通聊天保留 v0.3 当前 Provider，不隐式变成自主任务。自主任务的 Planner、Executor、Reviewer、Escalation 可分别填写模型名，也可以全部共用一个模型。空模型名继承 Settings 中对应 Provider 的配置，不根据模型名称分支。

Local-only 强制所有角色使用本地 Provider，包括升级角色，达到修复上限直接暂停且不会发起 API 请求。API-only 强制全部角色使用 OpenAI 兼容 Provider，规划、执行、审查均计入预算。Local-first 按角色 route 路由，默认规划/执行/审查使用本地，升级使用 API。用户可显式改变角色 route。

移除了旧版隐式选择大型 30B 模型的默认值。已有用户配置继续保留；新安装应明确在 Settings 或角色中填写实际安装的模型名，未配置时提示 MODEL_NOT_CONFIGURED，不下载或猜测模型。

每个任务保存不含密钥的 Provider 配置快照。后续 Settings 不影响正在执行的任务。暂停后可点击 Apply configuration to paused task，显式应用当前 Task 配置并从 Settings 刷新 Provider 地址。API Key 继续由 Electron 安全存储、会话或环境提供，绝不保存到任务配置/SQLite。

Models and budget 中可测试本地/API 连接，不生成模型 Token。Ollama 使用 `/api/show` 检查工具能力；已知不支持原生 tools 时切换严格 JSON 工具兼容，并显示提示。未知能力可在高级配置中指定 `tool_mode`：`auto`、`native`、`json`。JSON 兼容只接受完整 JSON 对象、已公开的工具名及对象参数，仍执行原权限与审批。模型无法遵守结构时记录无效输出并有限修复，不能把回答文本当作执行。

高级配置每个角色支持 `context_window`、`output_limit`、`input_price`、`output_price`。价格按百万 Token、用户所用货币配置；不会猜测供应商价格。OpenAI 兼容 API 的工具能力与价格通常不在 `/models` 中提供，需按服务真实能力配置；不声称仅靠连接测试即可验证工具能力。

请求通过异步 HTTP 取消/超时释放；错误区分不可用、认证、429、无效结构、上下文限制和超时。升级角色无工具权限，收到诊断后由 Executor 继续。升级上下文仅包含有限目标、Diff、验证失败及尝试摘要并脱敏，不自动上传整个仓库、完整日志或隐藏推理。
