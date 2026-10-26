# 解锁桌面后的真实在线 Electron 验收（2026-10-26）

## 实际环境与范围

Windows 11，已通过真实交互会话检查；uv 项目环境、Node/npm、Electron 与 Git。main 起始 SHA 为 `4d89487181e7e6ab21ca1642d6e3de625bdefeda`。本轮继续原功能分支和累计账本，不重新实现 M1～M5，不修改原 fixture，不创建 Tag、Release 或安装包，不开始 M6。

用户后续授权使用同一阿里连接的其他已配置/获取模型、按实际需要放宽预算并切换模型。因此本轮实际验证 Qwen Omni 单模型和 GLM + Omni，而不是把此前 Flash/Max 失败写成成功。Key 通过原 Electron safeStorage/凭据同步接口使用，未复制、解密输出、写入参数或 Git。

| 角色 | 实际 Model ID | Profile ID |
| --- | --- | --- |
| 方案 A Executor / Observer | qwen3.8-omni-flash | fetched-a24a1f72da349d20ea9e9aaf |
| 方案 B Executor | glm-5.3 | b0a62cdc-afb5-46f7-aea4-4656c2674434 |
| 方案 B Observer | qwen3.8-omni-flash | fetched-a24a1f72da349d20ea9e9aaf |

连接 ID 为 `763c8386-7de8-47a9-bd40-9a48edbfd02f`。模式为原 Single Agent online，模型调用真实在线；独立命令和桌面操作使用原 ToolRegistry、Approval、VerificationEngine、DesktopRuntime、Worktree。Codex 没有修实验副本业务代码。

## 真实任务结果

| 数据 | 方案 A：Qwen Omni | 方案 B：GLM + Qwen Omni |
| --- | --- | --- |
| Task ID | db26d728-1037-4ef8-aae8-b9075a386285 | 071f330b-7106-4422-94d5-99e6eaf768c4 |
| 后台终态 | awaiting_approval | awaiting_approval |
| 真实模型请求 | 36（Executor 33，Observer 3） | 40（Executor 37，Observer 3） |
| 服务端输入 Token | 404,082 | 424,052 |
| 服务端输出 Token | 12,121 | 8,114 |
| 输入输出合计 | 416,203 | 432,166 |
| 缓存 Token（输入子集） | 0 | 175,616 |
| 模型工具调用记录 | 43 | 61 |
| 实际业务文件 | src/App.tsx | src/App.tsx |
| 独立命令 | typecheck / 2 项 fixture 单测 / build / diff check 全通过 | 同左，全通过 |
| GUI 契约 | 两次不同输入、保存状态和持久化全部通过 | 同左，全部通过 |
| 清理 | 全部 15 个记录 PID 已退出 | 全部 10 个记录 PID 已退出 |
| 费用 | UNKNOWN | UNKNOWN |
| 原始控制器结果 | PASS，CLI 0 | RUNNING，CLI 2（报告竞态，见下文） |
| 实际 Task 与独立证据复核 | PASS | PASS；保留原始错误报告，修复后真实记录重放 PASS |

两组均使用原 `manual-fixtures/m5-electron-e2e` 的独立副本，由 Agent 实际修改磁盘。源工程保持原缺陷、Git 干净，已有测试和 `.lca` 契约没有改变。模型移除输入框禁用状态，并让保存完成后显示实际值；另同步规范化后的输入状态。没有自动接受实验报告、提交、推送或合并实验工程。

两组独立检查均包含真实 `npm run typecheck`、`npm test`、`npm run build`、`git diff --check`、GUI acceptance。不是仅凭模型的“完成”文本验收。fixture 的 2 个 Vitest 与产品前端测试数量分开计数。

## 真实视觉与回交

两组各有 3 个实际 JPEG 请求，HTTP 200，工具 Schema 数量为 0，均有服务端 Usage。截图来自受控 Electron 窗口，不是合成图；输入框隐私遮盖保持开启。

Codex 查看两组保存的最终 PNG，确认画面为 Settings、Display name、Save 橙色边框、`Saved: M5 verified B` 和持久化标签 `M5 verified B`，与 Observer 的实际 JSON 观察一致。最终 PNG SHA256 都为 `56e31de9f2643e3f33c8057ad7eb69eba110026b569df9859ec834bd5d7c2922`（确定性相同画面，但不同 Task 捕获记录）。重新按生产编码参数计算 JPEG SHA256，均匹配该 Task 的真实 wire image 记录，不仅检查 Schema 合法。

方案 B 的全部 Executor 请求为 GLM，wire_images 为空；图片只发送给 Qwen Observer。Observer 后出现 GLM 的真实模型请求和后续工具调用；原 runtime 将观察作为不可信文本反馈，既有 unified profile HTTP 测试验证具体回交路径。没有为追踪而保存完整敏感 Prompt，也不声称能够证明模型内部推理过程。

## 失败记录与修复

1. **输出截断**：先前 Omni Task `99a08e02-4e81-4e76-8684-bc2abf7c1415` 发出 32 次请求，实际修改/测试/GUI 检查后，在最终报告收到 HTTP 200 / finish_reason=length，MODEL_TRUNCATED 暂停，没有伪报完成。选中 Profile 原输出上限为 1024，不是累计预算耗尽。隔离重跑显式用 `--output-tokens 8192` 后得到方案 A 的完整 PASS。[官方模型能力](https://help.aliyun.com/en/model-studio/qwen3-8-omni-flash)允许更大的输出，但本轮没有扩大为无界响应。
2. **产品配置改善**：Settings 新建 API Profile 和目录探测工具的新 API Profile 默认输出 8192；本地模型默认仍为 1024。旧值和更大的自定义值不自动覆盖，旧 API Profile 可点 Use coding output limit 并保存。界面说明单次输出与 Task 累计 Token 是不同限制。真实 Settings smoke 验证提高、保留较大值、保存及重启恢复。新增 `requested_max_tokens` 日志记录，真实 HTTP 测试确认实际请求值。
3. **60 秒超时**：方案 B 的首次 Task `9cb49534-7c6a-477a-adac-67e7bea0c207` 第 4 次请求超时，保留该次 52,497 保守预留，不能写成实际 Usage。通过原预算配置使用 `--request-seconds 120` 重试后后台完整通过，仍有每请求、总时长、调用和防循环上限。
4. **终态报告竞态**：方案 B 后台已经通过，但关闭控制器时晚到的 task.updated 把最终报告覆盖为 RUNNING，还丢失 events/耗时字段。原报告及 CLI 2 原样保留。控制器现在锁定终态写入，晚事件不能覆盖；清理故障仍可将结果降为 FAIL，保留原始主因。Python 入口将不完整报告标为 CONTROLLER_REPORT_INCOMPLETE，不允许退出后仍显示 RUNNING。
5. **真实记录重放**：用同一 `finalResult` 函数复核方案 B 保存的实际调用、工具、5 项独立检查、Diff、截图和进程退出，再重放“终态后晚事件”，结果 PASS。没有追加一次付费任务，也没有由 Codex 重新修改业务文件。原始结果 RUNNING 与重放结果分别记录，不能把它写成修复后重新发出 40 次 API 请求。
6. **时间账本修复**：上述竞态使该尝试耗时字段缺失。按原 Task 持久化状态转换时间保守补记 350 秒，调用/Token 不变，写 accounting_corrections；不清零或退款。控制器也保留服务端 elapsed_seconds，防止异常路径漏记时间。
7. **审批误拒绝**：验收控制器原来拒绝点击受控窗口里的输入框。现仅额外允许已核验 PID/标题窗口内的 Edit/Display name；其他窗口、其他字段、全屏截图与危险命令仍拒绝。回归覆盖允许和拒绝两边，未放宽产品权限。

截至两组真实任务结束，Task 会话共 340 次真实请求，账本 3,859,748 Token；其中已知两次中断保守预留共 105,943，不当作真实服务端消耗。另有此前 23 次能力探测分开报告。账本尝试均已结算，无进行中的模型请求；单轮大上限为显式授权，不自动充值。

## 自动化门禁与公开证据

- 解锁后 M5 专项：3 项全部通过，142.273 秒；包含实际 Electron 输入保存、失败反馈修复、Pause/Resume、重启及 Stop 进程树。模型推理为 HTTP Mock，不能代替上述真实在线任务。
- 解锁后 desktop-smoke：32 项、零跳过，包括新输出预设、保存重启、角色绑定、聊天/面板、居中重命名、新项目弹框。
- Provider 专项 3 项、unified profiles 11 项通过；报告/预算入口守卫 26 项通过；输出预设所在前端专项 8 项、类型检查及构建通过。
- `fcfa64e0630c82abb7662825ee1e05d0b21977f8` 的 [Windows/Ubuntu CI](https://github.com/yunfei00/local-coding-agent/actions/runs/40262304544) 全绿。终态报告修复后再次运行完整 check.py，并要求 [PR #22 最新 checks](https://github.com/yunfei00/local-coding-agent/pull/22/checks) 全绿才合并。准确最终统计以该提交门禁及 PR 报告为准，不将跳过计为通过。

本机详细证据为 `validation-reports/20261026-unlocked-*.json/.log`，截图只留本机。公开子集见 [脱敏机器证据](unlocked-real-online-evidence-2026-10-26.json)。不提交 Key、完整 Prompt、图像 Base64、用户数据库或实验副本业务文件。Git 最终合并状态/SHA 由 [PR #22](https://github.com/yunfei00/local-coding-agent/pull/22) 记录，本轮不发布。

## 公司更新与复现

PR 合并后从 main 获取；合并前仍用 `feature/real-online-agent-validation`。保留未提交改动，不 reset/clean；有改动时另行克隆。使用 uv 环境：

```powershell
git status -sb
git fetch origin
git switch main
git pull --ff-only origin main
uv sync --locked
npm --prefix desktop ci --no-audit --no-fund
npm --prefix desktop run dev
```

若 PR 尚未合并，上面的 main 替换为功能分支。已有 API 模型检查 Maximum output tokens，必要时点 Use coding output limit 保存；旧 Task 继续保留原快照，新 Task 使用当前设置。GLM 可使用 120 秒请求超时；图片 Observer 选已实测的 Omni。Key 仍沿用原连接，不需为每个模型重填。

真实任务复现（其他机器使用其本地 Profile ID 或唯一同名 API Profile，不传 Key）：

```powershell
uv run python scripts/validation/real_online_agent_e2e.py --live --model qwen3.8-omni-flash --vision-model qwen3.8-omni-flash --output-tokens 8192 --request-seconds 120 --authorize-budget-update --max-calls 10000 --max-tokens 1000000000 --max-seconds 7200 --max-full-attempts 10
uv run python scripts/validation/real_online_agent_e2e.py --live --model glm-5.3 --vision-model qwen3.8-omni-flash --output-tokens 8192 --request-seconds 120 --authorize-budget-update --max-calls 10000 --max-tokens 1000000000 --max-seconds 7200 --max-full-attempts 10
```

## 实际能力边界

本轮证明了这两种实际模型配置在当前受控 Electron 工程中的编码、真实工具、视觉和独立验证基础闭环。不能因此保证所有公司工程可自动完成或全面替代 Codex。此前 Flash/Max 的完整任务失败、Qwen Plus 的多步骤失败仍保留；本轮没有把它们改写为 PASS。上下文估算仍为启发式、供应商费用未知、旧配置/旧快照不自动覆盖、实验临时目录清理后不可恢复，均为现有明确边界。之前的内核池异常不能据本轮成功认定已修复某个驱动。
