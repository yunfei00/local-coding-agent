# v0.9 自主工作流验收报告

验收：2026-11-05～06，Windows，Python 3.12（uv）、Node.js/Electron。基础 main：`7dbec0a5839f6af8b8621374c0e0f2b17108c200`。分支：`feature/v0.9-autonomous-workflow`。[PR #32](https://github.com/yunfei00/local-coding-agent/pull/32)。

**结论：BLOCKED，未达到完整验收和合并门槛。** 必需 Windows 在线模型 GUI 场景被真实锁屏及资源门禁阻断。其他可执行开发、验收已完成。PR 保持草稿，不合并 main；合并 SHA、合并后 CI 均为 NOT RUN。不创建 Release、Tag、安装包，不进入 v1.0。

## M1–M8

| 模块 | 实际实现 | 验证和边界 |
| --- | --- | --- |
| M1 规划 | 同一计划最多 30 节点 DAG、依赖/能力/角色/标准、pending 调整 | 图/循环/完成不可变自动化 PASS；Python/React 原生计划在线 PASS；最后新增 workflow_adjust 为 Mock 集成 PASS |
| M2 角色 | 同一 Runtime 四角色提示、模型快照、工具分发权限、审查退回、真实输入输出交接 | 两模型四角色真实 PASS；没有四套后台或仅四段文字 |
| M3 编排 | 原状态持久化、依赖阻断、排队、资源互斥、默认串行、最多两个无冲突后台任务 | 调度/GUI 互斥/低内存/恢复自动化 PASS；Windows GUI 场景 BLOCKED |
| M4 闭环 | 实际工具及独立验证、有限失败退回、错误签名、预算、保护原测试 | Python/React/失败修复真实 PASS；环境错误正确暂停；无进展自动化 PASS |
| M5 后台 | 队列持久化、排队即冻结零调用快照、原 Checkpoint、断线不决定执行生命周期 | 修改后暂停恢复与实际 WebSocket 重连 PASS；重启/取消/审批终态自动化 PASS |
| M6 模板 | 8 个 JSON 模板、参数验证、原生工具及同一计划存储 | 自动化及在线任务 PASS；有自定义加载器，无可视化模板编辑器 |
| M7 交付 | 原 Worktree/Diff/审批、只读 CI 查询、证据化中文交付报告 | 真实 Diff/报告 PASS；审批/私密 origin/无 Git 降级自动化 PASS；业务验收未授权提交或推送 |
| M8 UI | 原聊天可展开依赖/实际完成数/角色模型/验证/暂停/交付；设置角色模板 | 前端 67 PASS、类型和构建 PASS、Windows CI Smoke PASS；在线 Windows GUI 未验收 |

复用原 Unified Runtime、Provider、Tools、Permissions、Checkpoint、ExecutionBudget、项目记忆和检索。不建立第二套模型循环。每节点独立费用编辑器未实现，使用任务预算和角色阶段预留；不按角色重置预算。

## 自动化结果

| 检查 | 命令/证据 | 结果 |
| --- | --- | --- |
| 全量校验 | `uv run --locked python scripts/validation/check.py` | 4 阶段 PASS，退出 0、0 errors |
| 该次 Python | `validation-reports/20261106-014335-670546.log` | 共 664：648 PASS、16 SKIP、0 FAIL |
| 最后定向 | `uv run --locked python -m unittest discover -s tests -p 'test_v09_*.py' -v` | 33 PASS、0 FAIL；覆盖最后新增 3 项，与全量重叠，不相加 |
| 当前收集 | unittest discover | 667；最后 3 项由定向验证，最新全量见 PR CI |
| 前端 | `npm --prefix desktop run test` | 19 文件、67 PASS、0 FAIL，串行 |
| 类型/构建 | `npm --prefix desktop run typecheck`、`npm --prefix desktop run build` | PASS；既有 bundle 体积提示保留 |
| 凭据扫描 | `uv run --locked python scripts/validation/credential_scan.py` | 496 文件、0 findings；不保证覆盖任意未知密钥格式 |
| Diff | `git diff --check` | PASS |

16 SKIP 中 14 个是本机锁屏阻断的 Windows 桌面测试，另 2 个为平台条件，不计入 PASS。Windows CI 使用交互桌面强制门禁运行 M5。回归含原 L2/L3、Git、MCP、权限、Checkpoint、模型路由、记忆/检索、上下文及 Windows Computer Agent 适用用例。

## 真实模型和工程

详细过程及历史失败见[综合验收](integrated-acceptance.md)。业务运行通过生产认证 WebSocket → AgentServer → 同一工具循环。Agent 修改业务文件，外部驱动只准备故障、中断及独立核对；不是只请求 API 文本就算验收。

| 模型 | 实际验证 |
| --- | --- |
| deepseek-v4-pro-0813 | 文本/工具探针 PASS；Python、React 开发测试及单模型四角色修复 PASS |
| qwen3.8-2.4t-a95b | 文本/工具探针 PASS；Planner/Reviewer、真实交接、暂停恢复和重连 PASS |
| kimi-k3 | 首次文本 HTTP 400，BLOCKED；工具未运行，不反复尝试 |

两个禁止模型调用数 0，无 Ollama 真实请求。两个候选 profile 仅在隔离配置副本添加，原用户 Key、Endpoint、模型配置及额度不改。不用图像/视频生成模型做编程。

独立数据库去重后 92 次业务模型请求，另 5 次能力请求（含 1 次失败），共 **97 次模型 HTTP 请求**；另 1 次目录 GET。已知实际 Usage **1,111,012 Token**：DeepSeek 863,983，Qwen 247,029。缓存 221,952 是输入子集，不再叠加。一次取消 Qwen 请求缺准确 Usage，保留 42,727 的保守预留；kimi 失败请求 10,256 是估算，不冒充实际。费用 UNKNOWN。原始统计在本机 `validation-reports/v09-model-summary.json`。

真实角色模型切换 PASS；额度耗尽故障回退仅 Mock 集成验证，没有刻意耗尽真实额度。每次运行有请求、工具、Token、时间上限；没有无限重试。未知副作用不自动重放。

## Windows GUI 与资源

最后只读检查 `2026-11-05T18:10:06Z`（北京时间 11 月 6 日 02:10）：可用物理内存 **1,001,668,608 字节，约 955 MiB**，低于完整 GUI 启动门槛 1 GiB；提交余量约 18.9 GiB，同时返回 **DESKTOP_SESSION_LOCKED**。证据 `validation-reports/v09-gui-final-preflight.json`；早先记录保留。

未启动被阻断的在线 Windows GUI 任务，未绕过锁屏、降低门槛、修改 OS 或结束用户应用。React 独立 Chromium 中真实输入 2、3、点击计算得 5 且有截图，只证明 DOM，不证明 Windows UIA/视觉/焦点闭环。没有可清理的本轮孤儿进程能够解除该阻断。

## Git 和 CI

已推送源码 `a4d19502339cdf81b899d1b7c01d96b10a46a44c`，后续文档提交以 PR HEAD 为准。先前完整提交 `7ce0a236f7de153305e79f95553f6b904bda78c5` 的 [PR CI](https://github.com/yunfei00/local-coding-agent/actions/runs/42078054329) 和 [push CI](https://github.com/yunfei00/local-coding-agent/actions/runs/42078006619) 均 PASS，Windows/Ubuntu job 全通过，Windows 实际 M5 3 项及 Smoke 55 项均通过。最新源码/文档以 [PR Checks](https://github.com/yunfei00/local-coding-agent/pull/32/checks) 为准，旧提交 CI 不冒充新提交 CI。

原有未跟踪附件及 egg-info 保留。main 未合并，仍为基础 SHA；没有强制推送、Release 或 Tag。待资源与交互会话条件满足后完成真实场景 G，再检查合并门槛；当前不建议合并。
