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
| 在线模型真实调用 MCP | TODO | 需使用已配置模型最小化验证并记录额度；本轮未消耗额度 |
| 审批单次/持久/拒绝/撤销全链路 GUI 证据 | TODO | 后端/API/单测覆盖，GUI 手动证据待用户确认 |
| MCP 服务端任务取消（不支持取消提示） | PARTIAL | 客户端取消已记录；服务端不支持取消时需明确提示“已请求/不支持”，不假成功不假回滚 |
| OAuth 产品集成（OpenCode 原生/桌面登录注销） | PARTIAL | 本地协议级真实验收 PASS；产品 UI/原生 OpenCode OAuth 集成需按目标环境继续接入 |
| 第三方商业 MCP OAuth 兼容性 | BLOCKED | 无外部商业 OAuth MCP 账号/服务；本地协议级验收已完成 |
| 公司受限模式全入口绕过自动化 | PARTIAL | 策略/单测覆盖主要入口，需继续补齐子Agent/后台任务/外部程序所有入口的端到端证据 |
| Windows GUI/安装包验收 | BLOCKED | 需用户在 Windows 桌面环境手动确认 |

## 证据文件
- `validation-reports/p0-mcp-real-acceptance.json`（gitignored，本地生成）
- `validation-reports/p0-oauth-mcp-acceptance.json`（gitignored，本地生成）
- `validation-reports/p0-real-model-mcp.json`（gitignored，本地生成；当前环境 BLOCKED）
- `tests/test_p0_mcp_acceptance.py`
- `tests/test_p0_permission_matrix.py`
- `scripts/validation/oauth_mcp_acceptance.py`
- `scripts/validation/p0_real_model_mcp_check.py`
