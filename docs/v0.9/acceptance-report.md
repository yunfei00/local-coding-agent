# v0.9 自主工作流验收报告

验收：2026-11-05～06，Windows，Python 3.12（uv）、Node.js/Electron。基础 main：`7dbec0a5839f6af8b8621374c0e0f2b17108c200`。分支：`feature/v0.9-autonomous-workflow`。[PR #32](https://github.com/yunfei00/local-coding-agent/pull/32)。

**功能验收结论：PASS。** 2026-11-06 06:18～06:21（北京时间）桌面解锁后，补跑必需 Windows 在线模型 GUI 场景通过，先前 BLOCKED 已关闭，历史记录保留。本次不创建 Release、Tag、安装包，不进入 v1.0。合并必须等待最终提交的必需 CI；实际合并 SHA 和合并后 CI 通过 [PR #32](https://github.com/yunfei00/local-coding-agent/pull/32) 执行记录核对，不把文档提交时尚未发生的合并写成已完成。

## M1–M8

| 模块 | 实际实现 | 验证和边界 |
| --- | --- | --- |
| M1 规划 | 同一计划最多 30 节点 DAG、依赖/能力/角色/标准、pending 调整 | 图/循环/完成不可变自动化 PASS；Python/React 原生计划在线 PASS；最后新增 workflow_adjust 为 Mock 集成 PASS |
| M2 角色 | 同一 Runtime 四角色提示、模型快照、工具分发权限、审查退回、真实输入输出交接 | 两模型四角色真实 PASS；没有四套后台或仅四段文字 |
| M3 编排 | 原状态持久化、依赖阻断、排队、资源互斥、默认串行、最多两个无冲突后台任务 | 调度/GUI 互斥/低内存/恢复自动化 PASS；解锁后 Windows GUI PASS |
| M4 闭环 | 实际工具及独立验证、有限失败退回、错误签名、预算、保护原测试 | Python/React/失败修复真实 PASS；环境错误正确暂停；无进展自动化 PASS |
| M5 后台 | 队列持久化、排队即冻结零调用快照、原 Checkpoint、断线不决定执行生命周期 | 修改后暂停恢复与实际 WebSocket 重连 PASS；重启/取消/审批终态自动化 PASS |
| M6 模板 | 8 个 JSON 模板、参数验证、原生工具及同一计划存储 | 自动化及在线任务 PASS；有自定义加载器，无可视化模板编辑器 |
| M7 交付 | 原 Worktree/Diff/审批、只读 CI 查询、证据化中文交付报告 | 真实 Diff/报告 PASS；审批/私密 origin/无 Git 降级自动化 PASS；业务验收未授权提交或推送 |
| M8 UI | 原聊天可展开依赖/实际完成数/角色模型/验证/暂停/交付；设置角色模板 | 前端 67 PASS、类型和构建 PASS、Windows CI Smoke PASS；在线 Windows GUI PASS |

复用原 Unified Runtime、Provider、Tools、Permissions、Checkpoint、ExecutionBudget、项目记忆和检索。不建立第二套模型循环。每节点独立费用编辑器未实现，使用任务预算和角色阶段预留；不按角色重置预算。

## 自动化结果

| 检查 | 命令/证据 | 结果 |
| --- | --- | --- |
| 全量校验 | `uv run --locked python scripts/validation/check.py` | 4 阶段 PASS，退出 0、0 errors |
| 该次 Python | `validation-reports/20261106-014335-670546.log` | 共 664：648 PASS、16 SKIP、0 FAIL |
| 最后定向 | `uv run --locked python -m unittest discover -s tests -p 'test_v09_*.py' -v` | 33 PASS、0 FAIL；覆盖最后新增 3 项，与全量重叠，不相加 |
| 最终源码 Python CI | 92b83c2 的 PR CI | Windows 667：665 PASS、2 SKIP；Ubuntu 667：650 PASS、17 SKIP；均 0 FAIL |
| 审查补充定向回归 | `uv run --locked python -m unittest discover -s tests -p test_v09_runtime_queue.py -v` | 14 PASS，新增 3 项；当前收集 670，最新完整结果见 PR Checks |
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

原轮次独立数据库去重后 92 次业务模型请求，另 5 次能力请求；本次 GUI 追加 17 次、审查修复后的后台任务追加 5 次，共 **119 次模型 HTTP 请求**，另 1 次目录 GET。已知实际 Usage **1,368,228 Token**：DeepSeek 863,983，Qwen 504,245。缓存 295,680 是输入子集，不再叠加。一次取消 Qwen 请求缺准确 Usage，保留 42,727 的保守预留；kimi 失败请求 10,256 是估算，不冒充实际。费用 UNKNOWN。原轮次统计在本机 `validation-reports/v09-model-summary.json`，新增验收统计单列在本轮报告及证据清单。

真实角色模型切换 PASS；额度耗尽故障回退仅 Mock 集成验证，没有刻意耗尽真实额度。每次运行有请求、工具、Token、时间上限；没有无限重试。未知副作用不自动重放。

## Windows GUI 与资源

历史只读检查 `2026-11-05T18:10:06Z`（北京时间 11 月 6 日 02:10）：可用物理内存约 955 MiB，低于门槛且 DESKTOP_SESSION_LOCKED；收尾曾降至约 783 MiB。旧证据保留，未反复启动、绕过锁屏、降低门槛或结束用户应用。

解锁后只补测 G，未重复已通过的业务用例。启动前可用内存约 6.3 GiB、DESKTOP_READY，结束前约 5.8 GiB。使用同一生产桌面入口和在线 qwen3.8-2.4t-a95b，17 次请求，实际输入 214,191 / 输出 4,141 Token（缓存 53,248）。Agent 自己启动受控 Electron 工程，读取本次 PID、定位/激活窗口、UIA 点击 Settings、输入随机值、Save、读取 Saved、截图并 stop_process。独立核对落盘值 GUI-554fdf9f、截图/UIA一致，Git 工作区干净，9 个本次 PID 均退出。两次目录越界及一次风险确认缺失被正常拦截，模型有界纠正后继续，原拒绝记录保留。

证据：`validation-reports/v09-gui-unlocked/report.json`、`cleanup-check.json` 及本机脱敏窗口截图。报告 PASS、控制器退出 0、无强制终止。运行状态 completed，outcome=completed_unverified，level=manual，changed_paths=[]：这是 GUI 操作验收通过，未运行代码测试，不伪造 completed_verified。诊断 22 行，Markdown/JSON 文件均存在。React DOM 结果与本次 Windows 工具闭环分别记录。

## Git 和 CI

### PR 审查后补充修复

真实 GUI 通过后，PR 自动审查发现并确认两项缺陷：排队时预建 unified 字典缺少 repairs，后续 setdefault 不补子字段，首次独立验证失败会 KeyError；预建 unified_config 跳过原初始化的时间收紧逻辑，使较短 API 任务时限未生效。源码修复提交 `36603f834545fdee08ddcf2b9a1cca828ebb2839` 在入队时初始化计数/收紧时限，并在读取旧快照时补缺省字段、重新应用冻结时限，保留既有次数、证据和设置快照。

新增回归覆盖实际后台路径的独立 unittest 失败→repairs=1→修改→复测通过、旧排队快照缺字段恢复及新 Settings 不污染旧任务、已累计超时的旧任务不发送首次请求。14 项定向测试 PASS。新在线后台任务 `v09-background-repair-review/report.json` 使用 Qwen 5 请求、38,884 实际 Token，真实命令 exit 1→Agent apply_patch→复测和独立 unittest exit 0，原测试未变、completed_verified、诊断 35 行。该在线任务 repairs=0（初始失败来自显式测试工具），不能冒充独立验证修复计数分支的在线覆盖；该分支由 Mock Provider 配合真实工具的新增回归证明。

补充修复只涉及快照缺省值及时间预算，没有修改 Windows 工具；无需重放已成功的 GUI 输入/保存。保留原 GUI 源码版本、时间与全部历史失败证据。

本次 GUI 实际源码 `92b83c2a3a6031602a26c1b617fc42cbf712bf77` 的 [PR CI](https://github.com/yunfei00/local-coding-agent/actions/runs/42082600128) 和 [push CI](https://github.com/yunfei00/local-coding-agent/actions/runs/42082591651) 均 PASS，Windows/Ubuntu 全绿，M5 3 项及 Smoke 55 项均通过。GUI 补验仅更新验收文档和脱敏证据，没有改业务源码。最终文档提交及合并后检查以 [PR Checks](https://github.com/yunfei00/local-coding-agent/pull/32/checks) 和 [main CI](https://github.com/yunfei00/local-coding-agent/actions/workflows/ci.yml?query=branch%3Amain) 为准，不用旧提交 CI 冒充新提交 CI。

原有未跟踪附件及 egg-info 保留，无强制推送。真实 GUI 阻断已关闭，全部关键功能验收通过；待最终必需 CI 全绿后可按用户授权合并。合并执行结果在 PR 中追加，本文不预填未知 SHA。
