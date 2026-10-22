# v0.4.2 聊天模型同步修复

## 原因

旧会话保存 `active_model`。启动、刷新模型或更改普通聊天 Provider 时，界面可显示新服务的默认模型，但原 turn.start 只发送 prompt/thread_id，后端继续使用旧会话模型。例如底部显示 GPT-OSS，后端却验证 Ollama 中不存在的 DeepSeek API 模型名。此错误发生在模型推理请求之前，不能据此判断 GPT-OSS 不受支持。

另一个显示问题是原生 select 在 value 不属于任何 option 时可能显示首个模型，看起来已经选中，但状态仍是旧值。手动切换一次再切回会触发 model.select，因而暂时解决问题。

## 修复

普通聊天的 Renderer → preload → Electron IPC → turn.start 现在携带实际选择的模型。后端先验证模型可用性，再通过原有会话存储保存，在同一请求中启动该模型；实际 model.selected/turn.started 事件返回已确认状态。错误或不可用模型不修改原会话，不发送推理请求，不静默回退到其他模型。省略 model 的旧客户端继续使用原会话选择。

旧会话若含不可用模型，下拉框显式显示 unavailable；Send 禁用，用户选择可用模型后继续。底部 Chat model 和 Settings → Provider 控制普通聊天；Models & Routing 控制自主 Task 的四角色。此次不改变自主任务路由、预算快照、Checkpoint、权限或 Git 工作流。

不需要清理数据库、删除会话或移除旧 API Key。升级前可临时手动切换一次模型，再切回目标模型；也可使用当前模型新建会话。

## 验证

`tests/test_chat_model_selection.py` 六项专项已通过：真实 Agent Loop 使用 Mock Provider，覆盖覆盖旧模型、实际调用参数、会话及消息重启恢复、旧客户端兼容、无效模型不回退、空值/类型校验、Provider 离线和活动请求阻止。

Electron 回归增加实际 HTTP Mock：先保存 API DeepSeek 会话，再切换 Ollama 并重启；确认底部 GPT-OSS 与旧会话值不同，发送后唯一推理请求为 Ollama `/api/chat` 的 `gpt-oss:20b`，随后重启验证模型持久化。另检查加载不可用模型时的明确提示与发送门禁。

```powershell
uv sync --locked
npm.cmd --prefix desktop ci
uv run python -m unittest discover -s tests -p test_chat_model_selection.py -v
uv run python scripts/validation/check.py
node scripts/validation/desktop-smoke.cjs
```

最终打包与发布结果见 [验收记录](acceptance.md)。Mock 使用示例模型名验证传递与路由，不代表本机安装了真实 GPT-OSS 20B 或验收了该模型编程能力。
