# v0.8 实现与使用

六个模块沿用统一聊天入口，无需选择普通/自主开发模式。模型选择增加自动模式；手动模型可明确允许回退。现有 Context 中增加项目记忆和工程检索，模型配置中增加能力摘要，进度卡显示实际模型、切换、压缩、知识命中和资源计数。

开发启动（PowerShell，在仓库根目录）：

```powershell
uv sync --locked
npm --prefix desktop ci
npm --prefix desktop run dev
```

回归：

```powershell
uv run --locked python scripts/validation/check.py
node scripts/validation/desktop-smoke.cjs
```

真实模型验收脚本沿用 scripts/validation/unified_live.py，通过 Electron 的实际聊天入口驱动；密钥由原 OS 安全存储解密，不写入仓库。所有受控工程和监督输出位于 validation-reports，监督输出不得写入被测工程导致伪代码变更。

```powershell
uv run --locked python scripts/validation/unified_live.py --help
```

先确认内存可用量，串行运行。资源不足标记 BLOCKED_RESOURCE，不反复启动；仅清理本轮创建的进程。真实验收结果以 acceptance-report.md 为准，不能将 Mock 或历史 v0.7 结果当成本次真实 PASS。
