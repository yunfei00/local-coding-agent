# 阿里模型真实产品仓库验收（2026-10-27）

## 验收范围

本次使用用户已保存的阿里连接、Windows 安全凭据、真实 Electron/Python Agent、真实 HTTP 模型请求和真实工具执行。没有使用 Mock 模型完成下表任务。独立克隆本产品已提交的 Git 仓库，在副本中明确预置两个回归：删除会话后重新出现、改名没有持久化。先运行测试确认原始失败，再让模型自行读取代码、修改 `agent/persistence/store.py` 与 `agent/server/state.py`、运行 unittest、检查 Diff。控制器在任务开始后不代替模型修复业务代码。

这证明模型能够修复真实产品代码中的受控回归，不代表已让模型自由开发任意公司项目，也不把注入的故障称为公司机器上新发现的问题。未上传公司文件或用户提供的参考截图。未修改生产工作区、已有 manual-fixtures 或测试契约；没有合并模型生成的工程副本。

## 实际结果

所有尝试单次输出配置为 8192；128K 指隔离任务的客户端上下文配置 131072，不代表已经验证服务端的完整上下文规格。未覆盖用户保存的 Settings。

| Model ID | 客户端上下文 | 结果 | HTTP 请求 | Token 记录 | 最终状态/原因 |
| --- | ---: | --- | ---: | ---: | --- |
| deepseek-v4.1-flash | 默认 32K | FAIL | 16 | 186,174 | paused / TOOL_LOOP_DETECTED |
| glm-5.3 | 默认 32K | FAIL | 15 | 163,862 | paused / TOOL_LOOP_DETECTED |
| deepseek-v4.1-flash | 128K | PASS | 14 | 452,161 | awaiting_approval |
| glm-5.3 | 128K | PASS | 19 | 644,047 | awaiting_approval |
| qwen3.8-max | 128K | PASS | 17 | 515,293 | awaiting_approval |
| qwen3.8-flash | 128K | PASS | 21 | 684,640 | awaiting_approval |
| qwen3.7-plus | 128K | PASS | 10 | 231,885 | awaiting_approval |
| qwen3.8-omni-flash | 128K | FAIL | 11 | 441,880（含估算） | 第 11 次 HTTP 403，暂停 |
| kimi-k3 | 128K | FAIL | 1 | 50,135（保守预留） | HTTP 400，暂停 |
| kimi/kimi-k3 | 128K | FAIL | 1 | 50,135（保守预留） | HTTP 400，暂停 |

合计 10 次工程尝试、125 次真实 HTTP 请求，5 PASS、5 FAIL。两个 Kimi ID 均来自已保存模型列表，实际服务拒绝当前请求；没有足够信息确定是参数、网关还是模型权限问题，不据此判定模型编码能力。Omni 在前十次成功响应后出现 403；不能据此宣称额度耗尽或所有模型的 Key 已失效，没有自动重试该鉴权错误。

前两次使用未设置上下文的旧 Profile，运行时采用默认窗口并出现重复读文件；显式扩大客户端上下文后，同样故障和模型完成了修复，实测请求输入超过 32K、上下文事件无裁剪。这支持上下文配置/裁剪影响该场景的判断；本次没有修改核心上下文算法，也没有声称所有重复循环都由上下文导致。循环保护仍会暂停无进展任务。

## PASS 的证据标准

每个 PASS 都有实际工具修改、非空允许范围 Diff、独立验证成功、原工程未改、测试文件未改，以及可关联 Task ID / Call ID / HTTP 状态和 Usage。任务最终停在待人工审查状态，未伪装为自动提交/合并完成。

控制器在模型任务结束后独立重跑三个模块：会话生命周期 8、持久化 2、项目注册 3，共 **13 个不同 unittest**，五次成功各自通过 13 项。不能把模型重复运行与控制器重跑相加为更多不同测试。每次独立运行使用当时的已提交副本，不包含后来新增的删除补查测试。还核对 `git diff --check`，未接受模型修改测试或绕过权限。

五个成功 Diff 均恢复删除过滤条件和改名保存调用；GLM 另加解释性注释，没有改变测试。逐次脱敏结果、实际输入/输出/缓存用量、HTTP 序列、独立命令、Task ID、小范围 Diff 与私有报告 SHA256 见 [结构化证据](alibaba-repository-acceptance-2026-10-27.json)。完整本机报告保存在被 Git 忽略的 `validation-reports/20261027-repository-*.json`，不发布原始 Prompt、文件内容、图片或凭据。

## 用量和边界

成功请求使用 Provider 返回的输入和输出 Usage，缓存 Token 属于输入 Token 子集，不再重复相加。失败请求没有完整 Usage 时保留保守预留，标记 estimated；上表含估算的行不能当作真实计费 Token。所有费用均为 **UNKNOWN**，没有价格或实际费用依据，不能用内部数值 0 表示免费，也不能保证阿里账户剩余额度。

累计本机验证账本还包含之前的其他场景，不能将其总量误称为本表 125 次请求。账本没有清零，不确定的预留没有事后释放成零。用户授权大额验证后使用较高累计上限，任务时间、请求超时、无进展循环和权限审批仍有效。

## 公司复验

源码更新、完整重启、配置和现有 fixture 的操作见[公司流程](../v0.4/company-validation.md)。普通 UI 可以直接选择已保存的模型；在新 Task 中用单 Agent 执行，避免将 Chat 选择误当成 Task Executor。若编辑 Profile 的上下文/输出，保存后新建 Task，旧 Task 继续保留原快照。

自动复现实际仓库场景的命令如下，`--live` 会发送真实 API 请求，可能产生费用；所列高累计上限对应本次已授权的验证，不是所有用户的默认限制。脚本使用已有安全凭据、保留已有累计账本，不需要把 Key 放进命令行或仓库：

```powershell
uv run --locked python scripts/validation/real_online_agent_e2e.py --live --scenario repository --strategy single-agent --model qwen3.7-plus --context-window 131072 --output-tokens 8192 --request-seconds 120 --max-calls 10000 --max-tokens 1000000000 --max-full-attempts 10 --max-seconds 7200 --authorize-budget-update --report validation-reports/company-repository-qwen3.7-plus.json
```

脚本成功标准包含真实模型请求、真实修改和独立测试，失败返回非零并保留原因。此仓库场景是无界面的真实 Electron 编码验证，不新增桌面视觉能力结论；之前的视觉证据单独见[解锁后验收](unlocked-real-online-acceptance-2026-10-26.md)。
