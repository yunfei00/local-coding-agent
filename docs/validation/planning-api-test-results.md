# Planning/API 修复测试与公司验证

## 验证分类

- **HTTP Mock PASS**：新增 `tests/test_planning_api.py` 18 项；实际原客户端、Agent Loop、Worktree、Patch、unittest、Diff、SQLite 和取消/恢复路径，不连接外部 API。
- **真实 API NOT RUN**：按用户后续明确指示取消本轮真实 DeepSeek 测试。没有使用凭据，没有发送付费 HTTP 请求，没有实际付费 Token Usage，也未验证真实 Model ID。不存在真实 API PASS 声明。
- 原基线：229 Python、32 Desktop，类型检查/构建通过。既有混合 Provider 专项 19 项、v0.4 编排专项 23 项通过。最终完整回归和 CI 结果以本节后续记录为准。

## 本地最终结果

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| validation/check.py | 247 Python、32 Desktop，0 失败；类型检查和构建通过 | 20261022-165548-948539.json / .log |
| HTTP Planning 专项 | 18 PASS、0 FAIL | planning-api-verified.log |
| 混合 Provider | 19 PASS、0 FAIL | planning-mixed.log |
| v0.4 编排（含最终恢复修复） | 23 PASS、0 FAIL | planning-orchestration-final.log |
| Electron desktop-smoke | 24 检查通过、0 跳过，含 Planning 阻塞取消和报告访问 | planning-desktop-final.log |

日志位于本机忽略的 validation-reports；公开文档只记录无敏感内容的结论。最终代码双平台 CI 状态见 [PR #10 检查](https://github.com/yunfei00/local-coding-agent/pull/10/checks)，合并门禁要求全部成功。报告中解析/Schema 为 null 表示未进入该检查，不冒充成功或验证失败。中断恢复时遗留 reserved 调用标为 interrupted，保留占用与 ID，并记录 TASK_INTERRUPTED/MODEL_INTERRUPTED。

## A–J 与关键附加覆盖

| 场景 | 自动化证据与结果 |
| --- | --- |
| A 正常计划 | 进入 Executing，隔离目录真实修改 calculator.py，运行 unittest 和 git diff --check，通过后 awaiting_approval；源文件不变，报告含真实 Diff |
| B 非 JSON | PLAN_JSON_INVALID；反馈给同一配置的 Planner，有效响应后执行 |
| C Schema 错误 | PLAN_SCHEMA_INVALID；区分 JSON 已解析与 Schema 不通过；数组也属 Schema 错误 |
| D 分片流 | 每 3 字节发送含中文的 SSE，重组成功；原 aiohttp 行读取本来就能重组 TCP 分片，没有把它虚构为旧缺陷 |
| E 不同输出形式 | SSE content、普通 application/json、原生 submit_plan、分段工具名/arguments、JSON 工具兼容模式均可提交计划 |
| F 连续无效 | 相同无效响应两次即 PLAN_NO_PROGRESS，第三次不请求 |
| G 修复/诊断仍失败 | 4 次不同无效本地计划 + 至多一次 API Mock 诊断后 PLAN_RETRY_LIMIT，不因 escalation 重置上限 |
| H 预算限制 | 零 API、Token 不足均零 HTTP；一次调用用尽后不发送第二次；全局限制继续由混合 Provider 回归验证 |
| I 规划中取消 | 请求被取消，状态 cancelled，未知预留保留，诊断保留 Call ID 和取消类型 |
| J 暂停后恢复 | 计数保留、同一账本不重复扣减，新调用使用新 Call ID；恢复后真实修复和测试通过；规划上限耗尽后 Resume 不产生新请求 |
| 超时/429/截断/空响应 | 具体类型、HTTP/finish_reason 和失败元数据，暂停且不伪造完成 |
| 结算/脱敏 | 准确 Usage 释放多余预留；未发送不计 API；未知保留；报告不含测试秘密、Prompt/文件正文/网关回显；数字字段仍是有效 JSON |
| 绑定冲突 | API-only/Ollama Planner 在 Worktree 和 HTTP 之前明确拒绝，诊断指明 planner |

Mock 正常 API-only 流程为 Planner 1、Executor 2、Reviewer 1，共 4 次 HTTP，Mock 返回每次输入 100/输出 20，最终占用 480 Token。它们是模拟 Usage，绝不是 DeepSeek 真实消费。默认 API 3 次/30000 Token 没有提高；低预算应明确停止，不承诺任何 API-only 工程都能在三次调用内完成。

## 完整可复制命令

```powershell
uv sync --locked
npm.cmd --prefix desktop ci
uv run python -m unittest discover -s tests -p test_planning_api.py -v
uv run python -m unittest discover -s tests -p test_mixed_provider.py -v
uv run python -m unittest discover -s tests -p test_v04_orchestration.py -v
uv run python scripts/validation/check.py
node scripts/validation/desktop-smoke.cjs
```

桌面自动化已实际验证 Planning 阻塞时顶部取消按钮可见、可以终止请求，随后从 Task 打开 JSON/Markdown 诊断。暂停、失败及待审批任务也可直接 Cancel task，无需先恢复；取消保留 Worktree、历史和预算。回归继续覆盖模型配置、会话、聊天、审批、Worktree、Stop 和原 UI 行为。

## 公司电脑更新与口述验证

本轮只提交 main 源码，不发布新安装包。已安装的 v0.4.2 可执行文件不会自动包含修复；在公司源码目录、确认没有未提交改动后更新并开发运行：

```powershell
git status -sb
git switch main
git pull --ff-only origin main
uv sync --locked
npm.cmd --prefix desktop ci
.\scripts\dev\start.ps1
```

如存在自己的改动，先保留，不运行 reset/clean。模型连接和凭据沿用现有本机设置，不需要提交、传送或重新提供 Key。

复用 [公司验证流程](../v0.4/company-validation.md) 的 `manual-fixtures/v04-local-first` 场景 A，已有复制/Git 初始化命令，不需要手写工程。使用现有 API-only 配置新建任务，目标“修复 calculator.py 的加法错误并运行 unittest”。先观察是否到 Executing，再观察独立测试和报告；可在 Planning 中点击顶部 Cancel active task 测试停止。已有暂停任务仍保留旧配置快照，不能用聊天模型下拉框替代 Task 角色绑定。

口述“停在哪个阶段、界面错误码、Planning attempts、API calls、是否通过 unittest”即可；不要求截图、查本地日志、增加预算或提供凭据。若上限/绑定不符合，会明确报告 BUDGET_EXHAUSTED / MODEL_POLICY_MISMATCH；不会隐藏失败。需要细节时 Task diagnostics 已直接显示 Call/HTTP/Schema/下一状态。
