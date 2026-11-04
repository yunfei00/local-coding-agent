# 请求追踪与隐私

调用链：聊天 IPC → `turn.start`/Task 入口 → 原配置快照 → 预算预检/预留 → Provider → HTTP → 结构化解析 → 原工具权限与执行 → 独立验证。

事件关联 run_id、thread_id、request_id 和唯一 event_id。事件阶段：

| 事件 | 含义 |
| --- | --- |
| request.prepared | 准备请求；预算或构造失败也有此记录 |
| request.dispatched | 开始网络尝试，不等价于服务端已接受 |
| request.reserved / settled | 原预算账本预留/结算，含预留、释放、实际 Usage 或估算标记 |
| response.headers_received | 已确认收到 HTTP 响应头 |
| response.streaming | 已接收首个有效响应数据 |
| response.completed | Provider 完整响应，仍须经过语义/工具参数校验 |
| request.failed / interrupted | 请求失败或中断 |

`request_sent=false` 表示确定未发送；`null` 表示无法确认；`true` 表示已收到 HTTP 响应。未知状态保留保守预算，不能当作未发送退款。

元数据白名单包括 HTTP 状态、内容类型、finish_reason、流片段/字符数、Usage、耗时、重试与预算字段。不保存 API Key、Authorization、Cookie、完整 Prompt、用户文件正文或推理正文。精确密钥及 Cookie 再脱敏。

Task 当前诊断按需展示最近事件；`task.runtime.events` 按线程授权查询，默认 100 条、最多 500 条。导出完整 JSON 写入本机 `unified-diagnostics`，只通过 WebSocket 返回路径，历史不静默删除。当前未实现自动事件轮转；本机数据库可能随长期使用增大。

Provider 的 `response.completed` 是传输证据，后续无效工具参数仍然失败，不执行工具。测试见 `test_v06_request_tracing.py`。
