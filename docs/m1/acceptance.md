# M1 自动化验收记录

日期：2026-10-22。基线：`8c44ca6`。分支：`feature/m1-single-agent`。本机 Windows、Python 3.12.13（uv）、Node 24.14.0；CI 使用 Python 3.12 / Node 22，Windows 与 Ubuntu。

## 验收方法

新增 `tests/test_single_agent.py` 使用本地 aiohttp HTTP 服务仅替代模型响应，调用生产 `OpenAICompatibleProvider`、Task Runtime、Agent Loop、权限/Approval、文件工具、终端、Git 和 VerificationEngine。测试客户端通过实际 ApprovalManager 回答审批事件，没有 Mock 工具、文件修改、测试结果或审批实现。

测试复制现有 `manual-fixtures/v04-local-first` 到临时 Git 仓库，再由实际 Worktree 工具创建隔离执行目录；不修改原 fixture，也不需要补充测试数据。

| 场景 | 自动化证据 |
| --- | --- |
| 一次返回两个同参数、不同 ID 的工具调用 | 两次真实 read_file 均执行，后续请求含两个配对的工具结果；严格 HTTP 检查 arguments 是 JSON 字符串 |
| 多轮真实失败→修复→重测 | 实际 unittest 返回失败和退出码 1 → 模型收到真实结果 → apply_patch 修改磁盘文件 → 实际 unittest 返回 0 → 真实 git_diff |
| 单模型隔离 | 所有 HTTP 请求只用 `m1-model` / executor / api；缺失 Planner、Reviewer、Escalation profile 不阻塞；不调用 submit_plan、不升级 |
| 独立验证失败修复 | 第一次模型结束后，真实独立测试失败；真实错误反馈给同一个 Executor，再次 Patch 后独立验证通过 |
| 工具错误恢复 | 实际读取不存在文件返回结构化错误，下一请求收到失败结果后继续修改并通过验证 |
| HTTP 401、超时 | 暂停并记录稳定错误码及 HTTP/请求日志，不进入规划重试 |
| 畸形工具参数、截断响应 | 不执行畸形写文件、不接受截断回答为成功 |
| HTTP 中取消 | 任务和请求日志变为 cancelled，移除运行任务 |
| 真实终端中取消 | 实际子进程先写 started.txt；取消后延迟写入的 orphan.txt 不出现 |
| 无进展上限 | 相同独立验证失败后以 SINGLE_AGENT_NO_PROGRESS 暂停，所有请求仍为同一模型 |
| 本地 Executor 误绑定 | MODEL_POLICY_MISMATCH，HTTP 前暂停，不静默使用本地模型 |
| 上下文极限 | 超大工具调用组以 MODEL_CONTEXT_LIMIT 停止，不删除 assistant 头后发送孤立结果 |
| Desktop | 实际 Electron/React/Python，从 Task UI 选择 Single Agent 和在线 Executor，六次模型请求完成 read/test/patch/retest/diff/final，验证磁盘、独立命令及报告 |

## 自动执行入口

```powershell
uv run python -m unittest discover -s tests -p test_single_agent.py -v
uv run python scripts/validation/check.py
node scripts/validation/desktop-smoke.cjs
git diff --check
```

`check.py` 自动运行全部 Python unittest、Desktop typecheck、Vitest 与源码 build。CI 的 `Core checks` 在 Windows/Ubuntu 自动发现新增测试；Windows 额外运行实际桌面 smoke。本阶段只做源码构建，不执行安装包打包脚本。

执行中修复：严格 OpenAI 出站参数格式、同参数不同 ID 被错误合并、异常工具参数被当作空对象、独立验证反馈二次截断、过大上下文中工具结果失去对应调用，以及 Desktop Task 快照类型缺少 strategy。Smoke 原有取消测试的固定 500ms 等待改为等待实际规划请求，避免本机并发验证时误判。

## 最终本地结果

| 检查 | 结果 |
| --- | --- |
| Single Agent 专项 HTTP/真实工具测试 | 11 项通过 |
| 全量 Python unittest | 269 项通过 |
| Desktop typecheck | 通过 |
| Desktop Vitest | 10 个文件、36 项通过 |
| Desktop 源码 build | 通过，未打包安装程序 |
| `validation/check.py` | 全部阶段退出码 0，Errors: 0；报告 `validation-reports/20261022-175916-041665.json` |
| desktop-smoke | 通过，`ok: true`、`skipped: []`；证据 `validation-reports/desktop-smoke.json` 和 `desktop-m1-single-agent.png` |
| Python compileall / Git diff --check | 通过 |

本地原始日志与截图保留在被 Git 忽略的 `validation-reports/`，不提交临时工作区或运行数据。CI 与合并结果见本变更的 GitHub PR 检查；合并仅在 Windows/Ubuntu `Core checks` 全部通过后执行。

## 边界与未解决事项

- 未调用真实付费在线模型或公司网关。HTTP 替身验证生产协议和执行路径，不能证明真实模型的任务完成质量。
- 保留已有显式 API 调用/Token/时间限制；默认 3 次 API 调用可能不足以完成多轮任务，用户需要配置足够次数。没有新增预算或路由功能。
- 仍要求 Git 仓库、受管理 Worktree、现有审批和可运行的本机测试环境；模型结束后必须独立验证，不自动应用、提交或合并该应用产生的任务修改。
- 语义上下文压缩、完整工具会话持久化、OS 级沙箱、验收测试防弱化尚未实现。后续契约见 [M2–M5 规划](roadmap.md)。
- 没有创建 Tag、Release、安装包，也没有提交真实 API Key。
