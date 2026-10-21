# v0.4 验收与阻断记录

日期：2026-10-22。开发分支：`feature/v0.4-local-first-agent`，基于已验收的 v0.3 main `9c73179`。本页区分 Mock、真实工具、真实模型，不以 Mock 替代真实环境结果。

## 可复制的自动化命令

```powershell
uv sync --locked
npm.cmd --prefix desktop ci
uv run python scripts/validation/check.py
node scripts/validation/desktop-smoke.cjs
.\scripts\build\package-windows.ps1
```

新增测试使用 Mock Provider 和真实临时 Git 工程、原工具、原权限、独立 Worktree 与实际 unittest。覆盖本地成功零 API、失败后升级并回交本地、零调用/Token 不足/费用和全局限制、API 超时/429/断网、本地不可用、重复失败、失败不完成、取消恢复、真实后代进程终止、原工作区保留、重启账本和前端快照。

A：`manual-fixtures/v04-local-first` 的 Python 加法 Bug，Mock + 真实工具和独立测试验证完整成功路径。真实本地模型结果见下方。

B：`test_failure_escalation_advice_returns_to_local`：错误修改导致实际 unittest 失败，Mock API 仅返回建议，本地模型继续实际修改，独立验证通过。

C：`test_multifile_plan_checkpoint_and_git_review`、`test_cancelled_task_resume_does_not_replay_completed_mutation` 与 `test_pause_verification_kills_real_descendant_and_retains_checkpoint`：多文件计划、检查点、恢复去重、终止树与审批门禁。旧 fixtures 路径未改变。

## 真实 Ollama

执行：

```powershell
uv run python scripts/validation/v04_model_smoke.py --mode ollama --model qwen2.5-coder:1.5b
```

本机 CPU、8192 上下文：已连接，生成了结构化计划，通过 JSON 兼容实际调用 `read_file`，但没有完成文件修复。独立 unittest 两项断言失败，达到本地限制后 paused；本地请求 3 次，API 0 次。未标记 completed。报告在本地 `validation-reports/v04-ollama-20261022-014150/result.json`。

这证明连接、计划、兼容调用、真实验证和停止条件工作，但不能证明该小模型能自主完成场景 A，更不能宣称真实本地修复验收通过。

## 本地自动化证据

- 基线：174 Python、29 Desktop 测试通过。
- 验收运行 `20261022-015127-798572`：192 Python、32 Desktop 测试通过，TypeScript/Build 通过，0 失败。之后审查修复由最终运行和远端 CI 继续核对。
- 实际 Electron：15 项检查完成，包括自主任务 Mock Ollama → Worktree 审批 → 真实 Patch → 真实测试 → 报告确认，以及 v0.3 MCP、面板发送、Stop、改名、主题与重启。
- 当前 Windows 会话的系统剪贴板写入已知探针后也读回空值；该环境下仅验证渲染和复制 IPC 确认，系统剪贴板实际内容单列 skipped，不能声称原生剪贴板验收通过。真实桌面会话或远端 Windows CI 应继续复核。

## 最终代码审查

已检查任务状态转换、账本幂等与恢复、API 前置预检、审批路径、源工作区保护、模型回交、验证日志与上下文边界。修复 Read Only 早期 Git 特例、任务快照迟到响应、测试后未跟踪文件变化、费用估算数值溢出、验证发现阶段的外部符号链接读取，并对模型接收的验证摘要脱敏。验证日志完整流保存在本地，不发送完整日志到升级模型。

当前明确限制：Provider Tokenizer/价格精度需用户配置且不能替代供应商侧限额；错误分类为启发式；验证/快照有有界大小；任意自然语言计划验证条件仍需实际输出审查。任务接受报告不自动产生 Git commit，后续 Git 操作保留原显式授权与审批。

## 可选真实 API（可能收费）

没有可用真实 API 凭据时不运行、不猜测密钥。需要在公司允许的终端配置环境变量并显式同意费用：

```powershell
$env:LCA_OPENAI_BASE_URL = "https://your-approved-host/v1"
$env:LCA_OPENAI_MODEL = "your-approved-model"
# 使用会话环境或安全凭据注入 LCA_OPENAI_API_KEY，不写入脚本或 Git。
uv run python scripts/validation/v04_model_smoke.py --mode api --model $env:LCA_OPENAI_MODEL --context 32768 --allow-paid-api
```

该命令是 API-only 真实调用，可能收费，限制为 3 次/30000 Token。未提供 `--allow-paid-api` 会在任何网络生成请求前拒绝。当前真实付费 API 集成尚未验收；Mock 的成功不改变此结论。

## 合并和发布门禁

必须完成新增/回归测试、实际 UI、Windows 产物和最终审查，并满足真实环境验收后，才合并 main、创建 v0.4.0 Tag 并走现有 Release Windows 流程。当前真实本地场景 A 未通过、真实 API 未验收，保留功能分支，不创建正式 Tag/Release。自动化和 Windows 产物的最终结果在完成后补录，不能将待运行项目写成通过。
