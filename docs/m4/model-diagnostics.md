# 模型连接诊断

Settings → Models & Routing：选择已保存的连接和属于该连接的模型 profile，使用 `Test Connection` 或 `Test Vision`。诊断不保存或覆盖模型配置；测试前应保存正在编辑的配置。保存 API Key 会同时保存该连接引用，避免凭据已保护但连接未引用的状态。诊断期间配置字段冻结，聊天和 Stop 仍可响应。

默认未勾选 Live Test 时只做本地配置检查，网络、文本、视觉、工具均为 NOT RUN。独立字段 `configuration` 检查模型、启用状态、绑定、URL、凭据是否存在。原 Fetch model list 仅为模型发现，明确不代表能力实测。

## Live Test 边界

只有显式勾选 Live Test 或 CLI `--live-test` 才发模型 POST。完整 Test Vision 最多三次：文本、视觉、Function Calling；Test Connection 跳过视觉，最多两次。单请求 60 秒，诊断总超时 295 秒，最大输出 256 Token，不自动重试；相同连接禁止并发诊断。鉴权/模型/网络等文本请求异常立即停止，不追加调用。错误报告只包含错误码与 HTTP 状态，不包含 key、Authorization、服务端回显正文。

文本必须精确返回 `LCA_OK`；工具必须返回一个原生 `lca_diagnostic_echo` 调用及 JSON `{"value":"LCA_OK"}`，只检查，不执行。视觉见 [视觉验证](vision-validation.md)。HTTP 200 本身只代表请求到达，不代表能力通过。

输出包含连接/文本/视觉/工具 PASS、FAIL 或 NOT RUN、配置状态、模型 ID、UTC 测试时间、持续时间、请求尝试数、每阶段 HTTP 状态与服务端 Token/费用。缺失 Token 是 null，未知费用是 null 并明确提示；网络中断时是否计费不可确定。Mock/本地 HTTP 模型替身的回归结果不等于真实在线模型通过。

## 一键脚本

```powershell
uv run python scripts/validation/model_diagnostics.py --profile <已保存的model_profile_id>
# 仅当明确授权、环境中已有 LCA_DIAGNOSTIC_API_KEY 时进行付费测试：
uv run python scripts/validation/model_diagnostics.py --profile <model_profile_id> --live-test
```

`--data-dir` 可指定已有数据库目录。CLI 只读 SQLite、不迁移/覆盖配置，只从环境 `LCA_DIAGNOSTIC_API_KEY` 获取针对所选 profile 的 key；不接受明文 key 参数，避免 shell 历史记录。Electron safeStorage 密钥由 UI 原安全路径加载，CLI 不擅自解密或搬运；仅有加密 key 的主机使用 Settings 一键入口即可。Ctrl+C 取消 CLI；UI 使用 Stop diagnostics。任何未经 Live Test 的阶段都不得显示 PASS。

CLI 配置不完整或已启用的真实测试失败返回退出码 2；本地配置检查通过但网络未运行可返回 0，JSON 中仍明确 NOT RUN。

协议为 `task.model.diagnostic`（connection_id、model_profile_id、live、vision）和 `task.model.diagnostic.cancel`。服务端校验 profile 属于连接；长请求独立调度，WebSocket 仍可接收聊天和取消，断开连接取消其诊断。回归使用真实 HTTP/WebSocket 证明非阻塞。

百炼 OpenAI Compatible 参考：[官方文本接口](https://www.alibabacloud.com/help/en/model-studio/text-generation)、[官方图像理解](https://docs.modelstudio.console.alibabacloud.com/en/model-studio/vision)。文档声明不能替代当前连接、地区、鉴权和图像请求的实际验证。
