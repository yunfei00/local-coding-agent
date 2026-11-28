# MCP 自动化测试说明

## 单元/集成
- 现有：`tests/test_mcp_*.py`, `tests/test_permissions.py` 等。
- P0 新增：`tests/test_p0_mcp_acceptance.py`, `tests/test_p0_permission_matrix.py`。
- 新增测试服务：`tests/mcp_test_server.py`。
- OAuth 本地测试服务：`tests/oauth_protected_mcp_server.py` + `tests/oauth_mcp_fixture.py`。

## 真实验收脚本
- `scripts/validation/mcp_real_acceptance.py`：使用真实 stdio MCP 测试服务，验证 connect/discover/ping/echo/read/write/delete/long_running cancel/call_history/disconnect/reconnect。
- `scripts/validation/oauth_mcp_acceptance.py`：本地 OAuth 2.1 + 受保护 MCP HTTP 真实验收（未授权拒绝、PKCE、token/refresh、过期拒绝、客户端凭据清除、服务端撤销、重登、重启撤销态持久化、错误密码拒绝）。
- 报告输出：`validation-reports/p0-mcp-real-acceptance.json`、`validation-reports/p0-oauth-mcp-acceptance.json`（gitignored）。

## 运行
```powershell
uv run python scripts/validation/mcp_real_acceptance.py
uv run python scripts/validation/oauth_mcp_acceptance.py
uv run python -m unittest tests.test_p0_mcp_acceptance tests.test_p0_permission_matrix
uv run python -m unittest tests.test_mcp_client tests.test_mcp_lifetime tests.test_mcp_protocol tests.test_mcp_settings tests.test_mcp_runtime tests.test_permissions
```

## 说明
- Mock 测试不替代真实 MCP 集成验收。
- OAuth 测试使用本地回环地址、独立测试账号/数据，不依赖第三方商业服务。
- 第三方商业 MCP OAuth 兼容性无可用账号时标记 BLOCKED，不影响本地协议级验收结论。
- 真实在线模型调用 MCP 需要已配置模型凭据；缺少凭据/环境时标记 BLOCKED。
