# 阿里模型真实验证（2026-10-26）

代码基线：`feature/real-online-agent-validation` / `fac8be67b31f53a84c0259e0d78629bcfd6de0dd`。本轮复用现有 Electron IPC、ModelCatalog、Provider、TaskService、Task Plans、审批及 Worktree，没有第二套 Agent Loop。

**GLM API-only 和 Qwen Omni Single Agent 的真实 Python 修复闭环已通过。完整 M5 原生桌面在线闭环仍未通过，不合并 main。** 当前本机 Windows 会话锁定，原生 GUI 用例明确跳过；没有解锁、切换桌面或用合成图代替真实桌面截图。

## 模型目录与真实能力

用户授权复用同一阿里连接的安全 Key、获取和添加模型，并在额度耗尽后切换可用模型。通过 `task.connection.test` 实际获取 **180 个模型名称**，在原连接增加五个 Profile：`qwen3.7-plus`、`deepseek-v4.1-flash`、`kimi-k3`、`qwen3.8-omni-flash`、`kimi/kimi-k3`。同连接同名重复导入不会创建副本；保留原 Key、地址、角色绑定、Chat/Observer 默认值、预算和已有模型参数。

列表存在不等于当前凭据一定能调用。截图中的图像/视频生成等模型属于其他用途；依据[官方模型分类](https://www.alibabacloud.com/help/en/model-studio/models)，本轮只选择对话、编码和图像理解模型，没有把生成图片/视频、语音或 Embedding 模型批量绑定为编码角色。

使用产品现有 `task.model.diagnostic`，真实测试精确文本、图片随机 CHECK 值及无副作用函数调用。随机值只在合成图像像素中，不在 Prompt；模型返回的探测函数不执行。视觉声明只在实际图像挑战通过后开启；声明变更使旧诊断按原指纹机制成为 STALE，需新诊断确认，不能伪造持续有效。

| 实际 Model ID | 文本 | 视觉 | 工具调用 | 请求与结论 |
| --- | --- | --- | --- | --- |
| qwen3.8-max | PASS | PASS | PASS | 3 次 HTTP 200；本轮已实际验证视觉能力，但不是 M5 桌面通过 |
| qwen3.7-plus | 两次 PASS | 两次 PASS | 第一次 PASS，第二次 FAIL | 6 次请求，返回断言不稳定，保留失败 |
| glm-5.3 | PASS | FAIL | PASS | 3 次 HTTP 200，未通过图片内容断言，不推荐作当前 Observer |
| deepseek-v4.1-flash | PASS | FAIL | PASS | 3 次请求，视觉阶段 MODEL_INVALID_RESULT |
| kimi-k3 | FAIL | NOT RUN | NOT RUN | 1 次 HTTP 400，未继续其他探测 |
| kimi/kimi-k3 | FAIL | NOT RUN | NOT RUN | 已列出的别名仍 HTTP 400，停止该名称探测 |
| qwen3.8-omni-flash | 两次 PASS | 两次 PASS | 两次 PASS | 6 次请求 |

能力探测共 **23 次实际生成请求**，不包含在 Task 会话账本中；HTTP 400 也计为发出的请求，缺 Usage 不当作零消耗。探测工具总 `PASS` 仅表示目录操作完成、路由保留，不能代替逐模型能力或自主任务通过。官方[视觉说明](https://www.alibabacloud.com/help/en/model-studio/add-vision-skill)与实际探测分别记录；不只凭名称判定能力。

## 真实修改、测试与 Diff

复用 `manual-fixtures/v04-local-first`，复制到临时 Git 工程后由原 Task 建 Worktree。控制器不修改业务源码，独立验证直接执行 `uv run --no-project python -m unittest discover -s tests -v` 和 `git diff --check`。

| Task ID | 模型 / 策略 | 请求 / 服务端 Token | 结果 |
| --- | --- | --- | --- |
| 9c07062e-97f6-4bd9-9b9e-d9dfaa6971c6 | qwen3.7-plus / API-only，修复前 | 28 / 231,618 | 代码和测试已通过，计划进度卡住；通过原 Pause IPC 停止，保留账本 |
| 8204af73-1f06-43ea-a87f-89a7fd431a27 | qwen3.7-plus / API-only，中间版本 | 18 / 147,161 | 后台 awaiting_approval，控制器因 CRLF/LF 字节比较误报 FAIL；保留原记录，不追溯改成 PASS |
| bdba1691-8e10-4fd7-b2e1-1aa7c6e37260 | qwen3.7-plus / API-only，保护后 | 18 / 146,578 | TASK_PLAN_NO_PROGRESS 自动暂停：相同计划未前进，不再无限诊断 |
| 083b28a7-1e3a-4913-9f8f-2d76d9cf3ada | glm-5.3 / API-only | **12 / 61,158** | **PASS**：planning → executing → verifying → awaiting_approval；真实 Planner/Executor/Reviewer |
| 9a3a0681-f82a-45e7-92a3-e1ffa41dc566 | qwen3.8-omni-flash / Single Agent | **6 / 34,071** | **PASS**：真实修改、独立验证、Diff、awaiting_approval |

两个 PASS 的 Diff 均只含 `calculator.py` 中 `return a - b` 改成 `return a + b`；2 个 unittest 通过，测试内容和原 Task 冻结的契约保持，源工程干净。Token Usage 为服务端值，结算后 in-flight 为 0。未自动 Accept、提交或合并实验工程。

Task 会话累计 **228 次请求、账本 2,471,356 Token**：服务端已确认 **2,417,910**，另保留此前中断请求的 **53,446 不确定预留**。缓存不重复相加；23 次能力探测另计。费用 UNKNOWN，没有充值或验证供应商余额。本轮没有明确额度耗尽证据，不把主动换模型或 HTTP 400 伪称为余额耗尽。

## 根因与修复

1. 模型在首个步骤做完整项工作，后续计划仍要求基线失败或纯报告，非空 verification 又需要当前步骤内的成功命令，导致代码/测试通过但计划卡住。Planner 现在提示生成紧凑、可实际执行的步骤；执行每次追加当前步骤，并在上下文保留前去掉临时快照，避免旧步骤累积。
2. 原 Task 将“测试通过但计划未完成”反复当成代码修复失败，追加 repair step 和收费诊断。现在比较测试、Diff、计划状态：有进展则继续原计划；相同未完成计划连续两次不变，以 TASK_PLAN_NO_PROGRESS 暂停，记录已完成/剩余步数和测试已通过的证据。
3. 真失败在一次诊断后仍是相同失败与 Diff，以 REPAIR_NO_PROGRESS 停止，不重复升级；只有成功诊断后才记录，未发送请求的预算拦截不算已诊断。
4. 已验证步骤之间允许重新检查/测试，仍保留工具总预算、失败计数、改动证据和防止重复写入的持久化日志；同一步内原重复/循环保护仍有效。
5. 新增 calculator 验证场景，锁屏可测真实代码/API，不放宽原生桌面安全检查。独立测试内容比较兼容正常 Git CRLF/LF 转换，继续核对测试哈希、内容和实际 Diff。

Qwen Plus 多步执行仍有实际失败，不宣称所有模型都能完成任务；自动停止有效不等于模型规划能力全部修复。公司优先尝试已通过的 GLM API-only 或 Omni Single Agent。

## 自动回归证据

代码 `fac8be67b31f53a84c0259e0d78629bcfd6de0dd` 的 [CI 40258421855](https://github.com/yunfei00/local-coding-agent/actions/runs/40258421855) Windows / Ubuntu 全部通过：

- Windows Python 406 项：404 通过、2 跳过、0 失败；额外 3 项真实 Electron 专项通过；46 项前端、typecheck、build、desktop-smoke 通过。
- Ubuntu Python 406 项：390 通过、16 跳过、0 失败；46 项前端、typecheck、build 通过。
- 本机中间完整回归 `20261026-101254-642835`：403 项中 388 通过、15 跳过、0 失败，前端 46 项与 typecheck/build 通过。它开始于最后三项测试加入前，不写成最新全部测试。
- 最新功能代码的本机完整回归 `20261026-102306-909169`：**406 项中 391 通过、15 跳过、0 失败**（515.877 秒）；前端 46 项、typecheck/build 全部通过。原生会话相关跳过仍不算通过。
- 本机单独 desktop-smoke 因真实会话锁定而在 desktop_window_probe 前置失败，没有绕过。Windows CI 的 smoke 通过与本机未完成分开记录。
- 新增入口守卫 22 项、LoopGuard 11 项专项通过；多步骤、API 上下文快照不累积、计划无进展、诊断后同一失败不再付费重试四项新增编排回归通过。以上 Mock/单元证据不替代前面的真实在线 Task。

可公开的逐模型 Usage、实际 Diff、独立验证和状态转换子集见 [脱敏 JSON 证据](alibaba-model-evidence-2026-10-26.json)。没有提交 Key、Prompt、图像或临时运行路径。

## 公司电脑安装与配置

**本轮尚未合并 main。** 新目录下载功能分支，旧 v0.4.2 安装版不包含这些修复：

```powershell
git clone --branch feature/real-online-agent-validation https://github.com/yunfei00/local-coding-agent.git local-coding-agent-validation
Set-Location local-coding-agent-validation
uv sync --locked
npm --prefix desktop ci --no-audit --no-fund
npm --prefix desktop run dev
```

已有源码且无未提交修改时：

```powershell
git status -sb
git fetch origin
git switch feature/real-online-agent-validation
git pull --ff-only origin feature/real-online-agent-validation
uv sync --locked
npm --prefix desktop ci --no-audit --no-fund
npm --prefix desktop run dev
```

有未提交修改则保留原目录、另行克隆，不 reset/clean。模型和 Key 沿用当前 Windows 用户安全设置。Settings 用同一 Alibaba 连接 Fetch model list 后添加实际模型名；API-only 选 GLM，Single Agent 可选 Omni，视觉 Observer 可选已测 Omni/Max。同名模型确认连接正确。

旧小预算不被源码覆盖，可点 Settings/Task 的 Use long task budget、Settings → Agent 的 Use long task execution limits 并保存；这是保留旧设置后的显式预设，不能替代本轮根因修复。新 Task 用当前配置，旧 Task 保留快照，必要时 Apply configuration 或创建新 Task。固定工程复制方法见[公司场景 A](../v0.4/company-validation.md#场景-a本地修复)，选择在线策略即可，不用自己写测试。

## 自动验证命令

连接 ID 使用该电脑 Settings 中的实际 ID，不在命令行输入 Key。live 命令会消耗服务额度，本机已获授权；其他使用者按其服务授权运行：

```powershell
node scripts/validation/saved_model_probe.cjs --connection YOUR_CONNECTION_ID
node scripts/validation/saved_model_probe.cjs --connection YOUR_CONNECTION_ID --models glm-5.3,qwen3.8-omni-flash --import --live

uv run python scripts/validation/real_online_agent_e2e.py --live --scenario calculator --strategy api-only --model glm-5.3 --authorize-budget-update --max-calls 10000 --max-tokens 1000000000 --max-seconds 7200 --max-full-attempts 10
uv run python scripts/validation/real_online_agent_e2e.py --live --scenario calculator --strategy single-agent --model qwen3.8-omni-flash --authorize-budget-update --max-calls 10000 --max-tokens 1000000000 --max-seconds 7200 --max-full-attempts 10

uv run python scripts/validation/check.py
node scripts/validation/desktop-smoke.cjs
```

原始脱敏报告留在本机 `validation-reports/20261026-*.json` 和累计 session。临时实验数据库/Worktree 会清理，不能承诺恢复已经清理的实验任务。没有将用户数据库、Key、截图或完整请求提交 GitHub。
