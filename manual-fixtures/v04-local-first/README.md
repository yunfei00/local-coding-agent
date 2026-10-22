# v0.4 固定验收工程

此目录是只读模板；运行脚本会复制到新的临时 Git 工程，保留旧 Phase 24/25/26 fixtures 契约。

A：修复 `calculator.py` 的加法错误，运行真实 unittest，检查 Diff；可用本机 Ollama 进行真实能力验收。

B：Mock 本地模型先错误修改，再由有限 Mock API 给出诊断，本地继续修复；见 `test_failure_escalation_advice_returns_to_local`。

C：真实临时 Worktree 中修改文件、独立测试、Checkpoint、取消/恢复和审批；见 `test_cancelled_task_resume_does_not_replay_completed_mutation`、`test_pause_verification_kills_real_descendant_and_retains_checkpoint` 及 v0.4 多文件验收测试。

运行 Mock 验收（无付费请求）：

```powershell
uv run python -m unittest discover -s tests -p test_v04_orchestration.py -v
```

真实 Ollama（模型名由命令明确指定，CPU 可能较慢）：

```powershell
uv run python scripts/validation/v04_model_smoke.py --mode ollama --model qwen2.5-coder:1.5b
```

脚本的真实 API 模式必须显式提供 `--allow-paid-api`，可能产生费用；未提供凭据时不运行。详见 v0.4 验收文档。
