# MCP 真实验收报告（阶段性）

## 已执行（真实）
| 项目 | 结果 | 证据 |
|---|---|---|
| MCP stdio 连接 | PASS | `scripts/validation/mcp_real_acceptance.py` |
| 工具发现 | PASS | 同上，发现 ping/echo/read_file/write_file/delete_file/long_running/get_call_history |
| 参数传递/读写删/副作用 | PASS | 同上，临时目录文件真实创建/读取/删除 |
| 长任务取消（客户端取消） | PASS | 同上，long_running 取消；`test_p0_mcp_acceptance.py` 记录 cancelled |
| 调用历史 | PASS | 同上，get_call_history 返回记录 |
| 断开/重连 | PASS | 同上 |
| MCP runtime 持久化/重启恢复 | PASS | `tests/test_p0_mcp_acceptance.py::test_restart_persistence` |
| 权限矩阵基线/RESTRICTED bypass | PASS | `tests/test_p0_permission_matrix.py` |
| OAuth 2.1 本地协议级验收 | PASS | `scripts/validation/oauth_mcp_acceptance.py` + `tests/oauth_protected_mcp_server.py` + `tests/oauth_mcp_fixture.py`（未授权拒绝、授权码+PKCE、token、refresh、过期拒绝、客户端清除凭据、服务端撤销、撤销后拒绝、重登恢复、重启撤销态持久化、错误密码拒绝） |

## 待执行/阻塞
| 项目 | 状态 | 原因 |
|---|---|---|
| 本地模型真实调用 MCP | BLOCKED | 当前环境未配置可用本地模型/Ollama 运行实例；需要用户环境提供 |
| 在线模型真实调用 MCP（qwen4-max） | PASS | 通过桌面已配置 Alibaba Bailian 连接真实调用 `qwen4-max` + 本地 stdio MCP test server：模型发起 `write_file`/`read_file` MCP tool calls，MCP 真实执行，文件副作用落盘，最终回答包含 `MCP_MODEL_OK`。证据：`validation-reports/p0-real-model-mcp.json`（gitignored，本地保留）。小额度消耗（3 轮，总 tokens ~2795）。 |
| 在线模型真实调用 MCP（kimi/kimi-k3.1-pro） | BLOCKED | 使用同一已配置连接调用返回 HTTP 400 `InvalidParameter: The product is not activated, please confirm that you have activated products and try after activation`。非本地凭据缺失；为账号/产品未激活。未重复消耗额度。 |
| 审批单次/持久/拒绝/撤销全链路 | PARTIAL | 后端 ApprovalManager 覆盖 allow_once/allow_turn/deny/cancel pending/cancel turn；MCP 工具权限持久化撤销（allow->deny）经 refresh+重启持久化验证。证据：`tests/test_p0_approval_cancel_chain.py`。GUI 手动证据仍待用户确认。 |
| MCP 服务端任务取消（不支持取消提示） | PASS（客户端语义） | 客户端取消记录 `cancel_note` 明确说明“server may not support cancellation; side effects not rolled back”，不假成功不假回滚。证据：`tests/test_p0_mcp_acceptance.py`、`tests/test_p0_approval_cancel_chain.py`、`validation-reports/p0-mcp-real-acceptance.json`。GUI/运行中任务端到端展示仍建议手动确认。 |
| OAuth 产品集成（OpenCode 原生/桌面登录注销） | PARTIAL | 本地协议级真实验收 PASS；产品 UI/原生 OpenCode OAuth 集成需按目标环境继续接入 |
| 第三方商业 MCP OAuth 兼容性 | BLOCKED | 无外部商业 OAuth MCP 账号/服务；本地协议级验收已完成 |
| 公司受限模式全入口绕过自动化 | PARTIAL | 策略/单测覆盖 RESTRICTED 白名单、MCP allow/ask/deny、desktop/shell/git/外部进程/未知工具阻断；后端 `_authorize_tool` 真实入口 E2E 验证 RESTRICTED 阻断 shell/write/delete/git/stage/start_process。证据：`tests/test_p0_permission_matrix.py`、`tests/test_p0_approval_cancel_chain.py`、`tests/test_p0_restricted_bypass_e2e.py`。仍需补齐子Agent/后台任务/所有产品入口端到端自动化证据。 |
| Windows GUI/安装包验收 | BLOCKED | 需用户在 Windows 桌面环境手动确认 |

## 证据文件
- `validation-reports/p0-mcp-real-acceptance.json`（gitignored，本地生成）
- `validation-reports/p0-oauth-mcp-acceptance.json`（gitignored，本地生成）
- `validation-reports/p0-real-model-mcp.json`（gitignored，本地生成；qwen4-max PASS，kimi/kimi-k3.1-pro BLOCKED）
- `tests/test_p0_mcp_acceptance.py`
- `tests/test_p0_permission_matrix.py`
- `tests/test_p0_approval_cancel_chain.py`
- `tests/test_p0_restricted_bypass_e2e.py`
- `scripts/validation/oauth_mcp_acceptance.py`
- `scripts/validation/p0_real_model_mcp_check.py`
