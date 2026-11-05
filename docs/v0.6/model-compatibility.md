# 真实模型兼容性

2026-11-04 通过生产 Electron IPC、原安全凭据存储和隔离配置执行。没有输出/导出密钥，没有修改用户原配置。禁止调用 `qwen3.7-plus`、`qwen3.8-flash` 及其后缀变体；Python 与 Node 驱动均内置排除。

最初严格沿用既有 Settings：任务 Token 上限 30000、全局 300000。基础探测及短用例后，真实代码任务被保守预留阻止，明确记录为未通过，没有清零预算伪造成功。用户随后明确表示这些模型免费、按实际工作验证；后续只在隔离验收配置中授权更大、仍有限的预算。常规正向任务最多 40 次请求、2000000 Token、600 秒，整次驱动最多 100 次请求、3000000 Token、3600 秒；单请求 60 秒。恢复驱动额外最多 25 次请求、500000 Token、900 秒。原 Settings 不变，不充值，不无限重试。

| 已配置模型 | 实际 HTTP | 结论 |
| --- | --- | --- |
| qwen3.8-max | 403 | BLOCKED：该模型访问被拒绝，不能据此断言全局 Key 失效 |
| glm-5.3 | 403 | BLOCKED：该模型访问被拒绝 |
| deepseek-v4.1-flash | 403 | BLOCKED：该模型访问被拒绝 |
| kimi-k3 | 400 | BLOCKED：请求被服务端拒绝，未证明工具能力 |
| qwen3.8-omni-flash | 403 | BLOCKED；真实视觉未运行 |
| kimi/kimi-k3 | 400 | BLOCKED：请求被服务端拒绝，未证明工具能力 |

该连接的模型发现接口实际可用，但模型列出不代表账号可调用。随后从实际返回的 ID 中选择下列三个未被用户禁止的模型，均通过真实文本和工具调用检测：

| 模型 | 真实 Agent 验收 |
| --- | --- |
| qwen3.7-flash | Python 修改、输入校验、优惠券多文件任务、失败修复、环境错误、上下文压力、暂停恢复、WebSocket 重连、运行中追加、真实响应流中断、Git 拒绝、Electron 与 Windows UIA |
| qwen3-coder-flash | Python 问答/分析；实际 React/TypeScript 修改、typecheck/test/build、应用重启后原运行恢复与中断审阅 |
| glm-5.2 | 实际 Python 加法修复、原 unittest、独立验证与 Diff |

同一凭据下其他模型成功说明不能把上述 403/400 简化为“所有模型 Key 错误”。不可用的单个模型不阻断其他可用模型验收；不会静默切换到收费模型。上下文窗口为隔离配置值，服务端真实最大值未核实，不根据名称作保证。

发现记录在本机 `validation-reports/v06-discovery-20261104/report.json`。提交的脱敏分项证据见 [live-cases.json](evidence/live-cases.json)，完整本机报告与命令见验收报告。Provider 未返回费用，金额保持未知；有准确 Usage 的请求使用真实 Token，其余明确保留估算/预留。

可复现基础检测（仍受既有 Settings 预算约束）：

```powershell
uv run --locked python scripts/validation/unified_live.py --live --discover-only --request-seconds 20 --max-calls 6 --max-tokens 100000 --output validation-reports/v06-discovery-recheck
```

输出目录必须尚不存在。完整真实驱动会消耗模型额度，必须在授权范围内显式使用 --live；不需要基础回归连接付费 API。基础检测全不可用时真实开发用例为 BLOCKED，不运行无限重试，不自动转向其他收费模型。
