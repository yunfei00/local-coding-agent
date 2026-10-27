# 工具 JSON、输出截断与空项目 Tkinter 验收

## 用户问题与已确认范围

用户口述：空目录创建 Tkinter 计算器，DeepSeek 在查看目录后提示 `Tool arguments must be valid JSON; no tool was executed`。该文字准确来自 OpenAI Compatible Provider 的工具参数解析器，不是空目录读取错误。公司当次原始响应没有取得，不能断定其参数错误一定由截断造成。

审计确认两个可修复的软件缺口：工具 JSON 解析错误直接终止现有 Agent Loop，缺少有限的同模型重生成；工具参数最终解析失败时，已经返回的 Provider Usage 没有经过 done chunk，账本会保留估算，遗漏可准确结算的用量。模型输出截断与普通语法错误也缺少清晰区分。

## 实现

- 继续复用原 Provider、Agent Loop、Task Runtime、审批、Worktree 和两个预算账本。
- 严格解析整个工具批次后才交给工具执行。批次中有一个无效参数，前面的合法调用也不执行；不猜测补引号、换行或截断内容。
- 区分 `MODEL_INVALID_TOOL_CALL`、`MODEL_TOOL_ARGUMENTS_TRUNCATED`、`MODEL_TRUNCATED` 与拒绝响应。长度限制的提示显示 `finish_reason` 和当前 `max_output_tokens`。
- 在原模型重试设置内，让同一个 Executor 用更小的代码片段重新生成参数。默认设置 2 意味着一次重生成；计数保存在原 Execution Budget 中，不因进入下一步清零。每次请求仍经过原 API 预算预检查，不自动切换模型或提高配置额度；连续失败保留 checkpoint 并停止。
- 记录 JSON 错误位置、行列、参数长度和静态错误类别，保留 HTTP、finish reason、请求输出上限；不保存参数内容、Prompt、文件正文或密钥。诊断区分传输 JSON 与工具 JSON 是否解析成功。
- HTTP 已完成且 Usage 齐全时，即使工具 JSON 无效，也按真实用量结算失败调用，调用次数照计；未提供 Usage 或中断时继续保守预留。

## 自动化证据

本机相关专项：Single Agent **16 PASS**、Provider **5 PASS**、混合 Provider **19 PASS**、真实在线控制器离线守卫 **27 PASS**。覆盖坏 JSON 后同模型重新生成 → 实际文件修改 → unittest/Diff；合法调用与坏调用混合的整个批次零执行；连续坏响应有上限；显式 API 次数为 1 时不得发送修复请求；截断工具参数分类；过滤/拒绝响应不重试也不执行工具；完整失败响应 Usage 结算、流中途损坏时不释放不确定预留；诊断不泄露参数内容。真实 Electron 的第 44 项检查确认同模型重生成后聊天恢复、无非法写入，且坏响应的 Unicode 正文从界面移除，避免与有效回复混在一起。

这些 HTTP Mock 测试证明错误分支和安全条件，不冒充真实模型推理。

## 真实在线结果

使用已有阿里连接与 OS 保护的凭据，在隔离 Git 工程中运行，Python 命令通过 uv。初始目录只有 `.git`，没有预写的计算器或测试。新增验证场景，没有改动已有 manual-fixtures 路径。

| 场景 | 模型 | 单次输出 | 请求 | 结果 |
| --- | --- | ---: | ---: | --- |
| 首次旧逻辑测试 | deepseek-v4.1-flash | 1024 | 3 | 截断、暂停，未创建计算器 |
| 有限重生成测试 | deepseek-v4.1-flash | 1024 | 4 | 重生成后再次截断，安全暂停 |
| 首次较大输出 | deepseek-v4.1-flash | 8192 | 24 | 计算器已创建，外部独立 8 项 Tk 控件测试通过；完整任务 FAIL，见下文验证配置问题 |
| 修正验证配置后 | deepseek-v4.1-flash | 8192 | 1 | HTTP 403、暂停；未完成真实完整复验 |
| 修正验证配置后 | qwen3.7-plus | 8192 | 8 | **PASS**：项目内 17 项 unittest、Diff 和外部独立 8 项 Tk 控件测试全部通过，待审查 |

前三次控制器把 Task 验证命令误设为工作区外脚本，受到现有路径权限拦截；保留为测试配置失败，不用来宣称修复前后效果对比，不把该拦截归为框架缺陷。随后改成项目内 `test_calculator.py`，控制器在 Task 结束后另行执行工作区外的固定验收。没有关闭审批或扩大 Workspace 权限。外部测试实际构建 Tk 窗口和控件、invoke 按钮并检查显示，不是截图推断，也不声称真实鼠标端到端操作。

DeepSeek 的 1024 样本实际出现 `finish_reason=length`，其中一次输出为 1024 且正文/工具为空。这支持单次输出限制过小会阻断任务的结论；本机真实调用没有重现公司那次原始坏 JSON。后续 403 不确定是额度、权限还是其他网关原因，不能宣称 Key 全面失效或 DeepSeek 原始错误已真实复验通过。按用户已授权的切换策略，后续完整闭环选择已配置的 Qwen3.7-plus。

总计 40 次 HTTP 请求，1 次完整 PASS、4 次 FAIL，失败没有改记成功。费用均未知；Usage 与估算预留分别标注，缓存 Token 属于输入子集。逐次脱敏证据见[JSON](tool-json-tkinter-2026-10-27.json)。在线运行使用当时工作区代码，原始报告的 development_sha 仅表示开发基线，不能当成未提交修改的完整指纹。

## 公司更新与复验

更新源码并完整重启 Electron/Agent，保留现有连接和 Key。新建空项目，输入 Tkinter 计算器需求，验证真实创建文件、项目内 unittest 与 Diff；输入框显示的 Chat 模型不自动替换 Task Executor。原失败 Task 保留模型和预算快照，建议用新 Task 复验。

Task diagnostics 可查看失败的具体 Call、HTTP、`finish_reason`、`requested_max_tokens`、`tool_parse_success` 与 `tool_json_error`。如果是 `length` 且单次输出仍为 1024，在 Models & Routing 的相应 Model Profile 中检查单次输出限制；本次成功样本使用 8192。这是单次响应限制，与任务总 Token 预算不同；不能通过增加总额度解决。没有自动修改用户已有 Profile，旧 Task 也不会因 Settings 保存而偷偷更换配置。

可复现的真实场景命令如下，`--live` 会发送真实 API 请求，可能收费，使用原累计账本及已有安全凭据。高累计上限来自本次用户明确授权，不是默认值：

```powershell
uv run --locked python scripts/validation/real_online_agent_e2e.py --live --scenario tkinter --strategy single-agent --model qwen3.7-plus --context-window 131072 --output-tokens 8192 --request-seconds 120 --max-calls 10000 --max-tokens 1000000000 --max-full-attempts 10 --max-seconds 7200 --authorize-budget-update --report validation-reports/company-tkinter.json
```

通过时，脚本将实际生成的 `calculator.py` 保留在报告所指的 `validation-reports/tkinter-live-<task-id>/`，可使用 `uv run --no-project python <完整路径>` 启动。本次没有发布安装包、Release 或 Tag；最终源码分支/合并状态以 PR 为准。
