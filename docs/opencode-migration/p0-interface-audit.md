# P0 接口与边界审计

上游源码固定为 `dc2ffcf8bf26f9e669b6aa22b95f50e12be15e06`。HTTP 路径以 v2 协议及实机 OpenAPI 为准。

| 模块 | 已核验接口与行为 | P0 证据 |
| --- | --- | --- |
| 启动与鉴权 | `serve --hostname 127.0.0.1 --port 0`，进程间随机密码，HTTP Basic 用户为 `opencode`。 `GET /api/info` 返回版本，无认证为 401。 | Windows 实测 |
| 新建与回查 | `POST /api/session` 接收标题及 `permissions` 规则，返回 `data.id`。 `GET /api/session` 可再次查到该 ID。 | Windows 实测 |
| 会话输入 | `POST /api/session/:sessionID/prompt` 是 v2 会话输入，协议区分入队及恢复选项。 | Gemma 真实会话实测 |
| 事件 | `GET /api/event` 提供实时 SSE。服务默认关闭历史 payload 持久化，重连应以 `GET /api/session/:sessionID` 快照对账。 | 初始事件、模型增量、工具和完成事件实测 |
| 取消与恢复 | `POST /api/session/:sessionID/interrupt` 接受可选 `resume`，回报 `interrupted`。对空闲会话为 `false`。取消活动请求后，重启仍可取得 `interrupted` 快照。 | 空闲、活动和重启实测，跨副作用恢复仍待证 |
| 权限 | 会话规则以 `action/resource/effect` 表示。 `Permission.Service.assert` 强制校验，`permission.evaluate` 扩展判断，`Session.setPermissions` 写入会话规则并发布事件。拒绝可返回 `Permission.BlockedError` 或 `Permission.DeclinedError`。 | 源码核验，内置工具和动态撤销待测 |
| MCP | `GET /api/mcp` 查询状态，`/api/experimental/mcp/:server` 提供管理接口。 | 源码核验，工具授权和取消待测 |
| 模型与预算 | `model.request` 可调整模型端点，`http.request` 位于真正的 HTTP 发送前。WebSocket 使用另一路传输扩展点，HTTP 回退经过 HTTP 扩展点。 | 源码核验，全路径硬闸待测 |
| 配置 | 使用独立 `OPENCODE_CONFIG_DIR`、`OPENCODE_TEST_HOME` 和 XDG 路径。POC 关闭项目配置、模型元数据抓取且配置空 Provider 列表。 | Windows 实测 |
| SDK | `@opencode/sdk` 的 2.2.6 发布元数据和固定代码清单一致，锁文件记录完整依赖树。 | npm 元数据与锁文件，产品集成待测 |

[会话协议](https://github.com/anomalyco/opencode/blob/dc2ffcf8bf26f9e669b6aa22b95f50e12be15e06/packages/protocol/src/groups/session.ts) · [事件协议](https://github.com/anomalyco/opencode/blob/dc2ffcf8bf26f9e669b6aa22b95f50e12be15e06/packages/protocol/src/groups/event.ts) · [鉴权](https://github.com/anomalyco/opencode/blob/dc2ffcf8bf26f9e669b6aa22b95f50e12be15e06/packages/server/src/auth.ts) · [权限](https://github.com/anomalyco/opencode/blob/dc2ffcf8bf26f9e669b6aa22b95f50e12be15e06/packages/core/src/permission.ts) · [MCP 协议](https://github.com/anomalyco/opencode/blob/dc2ffcf8bf26f9e669b6aa22b95f50e12be15e06/packages/protocol/src/groups/mcp.ts) · [模型请求](https://github.com/anomalyco/opencode/blob/dc2ffcf8bf26f9e669b6aa22b95f50e12be15e06/packages/core/src/session/model-request.ts#L337) · [服务配置](https://github.com/anomalyco/opencode/blob/dc2ffcf8bf26f9e669b6aa22b95f50e12be15e06/packages/cli/src/server-process.ts)

## 产品接缝

现有统一入口为 `AgentServer.run_tool_turn`（`agent/server/main.py`）。任务预算定义在 `agent/core/execution.py` 的 `ExecutionBudget`，现有授权由 `agent/permissions/policy.py` 与 `agent/permissions/authorization.py` 处理。P0 没有接管这些入口，也没有修改生产数据库或现有引擎。后续需要以这些实现为兼容基线。

预算硬闸的验证标准是拒绝后上游收到零请求。上线前至少需要在隔离端点验证重试、取消、并发及传输切换均受约束。若不能证明 hook 覆盖所有启用路径，可将模型连接限定到受控网关并禁止直连，先用无付费的隔离端点证明拒绝计数，再做真实 Ollama 测试。工具权限需要单独通过内置文件、Shell 和 MCP 的真实行为证据。
