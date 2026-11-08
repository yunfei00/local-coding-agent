# 独立 Tester 与状态型验证隔离

基线为 `b3014ba8a473589d4aaefb4b41a6fbb408bdd31e`，开发分支为 `feature/v1.1-release-candidate`。本轮针对库存 30，沿用原独立验收断言和本机配置的 `gemma4:31b`。

## 根因与修复前证据

- `agent/core/workflow.py` 的 DAG 校验只验证角色取值、依赖和环路，未从任务验证契约推导必需角色。基线上的确定性用例提交四个 Developer 步骤，运行时接受了计划，末步实际角色是 Developer。
- `run_command` 在调用方省略 `isolated_cwd` 时以交付目录启动。基线上的确定性增、查、改用例将已有交付文件从 `{"original":true}` 改成了 `{"record": 5}`。前次真实库存运行也在交付目录写入了测试记录，独立评分报 `DELIVERY_ASSERTION`。

## 执行机制

- `agent/core/verification.py` 根据明确独立验收要求、开发类型和功能测试要求推导义务。只读分析、普通问答和未要求独立验证的简单修改沿用原流程。
- `agent/server/main.py` 在计划提交及恢复执行入口检查 Tester 依赖是否覆盖 Developer 交付。缺失时先要求纠正一次，再优先补齐现有待执行 Tester 的无环依赖。确实缺少可复用节点时，补充一个来源为 `runtime_independent_verification` 的待执行节点。兼容旧顺序计划，保留已完成步骤、证据和检查点。缺少测试继续走既有的 Developer 补测交接，Tester 必须取得自身步骤的实际测试结果才能完成。
- 状态型开发中的验证命令由工具入口自动隔离，原工作区审批仍检查命令。受控启动器只执行单条受支持的 Python 调用，拒绝不支持的 shell 串联、后台进程和自定义外部 cwd，并返回可操作的提示。只读 Git 状态和 Diff 沿用原路径。
- `agent/tools/processes.py` 按任务和验证流程建立临时副本。同一 Developer 验证流程的命令共享数据，每个 Tester 步骤以及最终独立验证使用独立数据。副本读取符合原工程可见性规则的有界源码，跳过生产数据和凭据，临时目录与子进程 cwd 指向副本。Python 子进程继承同一环境。进程退出码、日志、命令证据仍由原工具记录。
- `agent/tools/verification_guard.py` 约束受支持的 Python 文件操作和同解释器子进程，包括普通 Python 代码动态构造的交付目录绝对路径。前后快照检查交付文件变化，发现变化即报告并阻断，保留原文件和证据，避免覆盖用户改动。Windows 构建脚本包含该保护资源。

Python 审计钩子用于防止验证代码误写及阻断已覆盖的路径操作。恶意原生代码或未覆盖的运行时接口需要操作系统隔离。非受支持的运行方式和依赖未复制数据的工程可能得到明确阻断。[Python 审计钩子的能力边界](https://docs.python.org/3/library/sys.html#sys.addaudithook)

## 回归和真实验收

Windows 本地定向回归 **145 通过、0 失败、1 跳过**，覆盖统一执行入口、工作流和恢复、三档权限、命令审批、进程生命周期、文件保护、独立评分器。新增断言验证四个 Developer 步骤会触发一次纠正，复用已有待执行 Tester，恢复旧计划时保留已完成步骤和证据，Tester 不能写文件，同一隔离数据支持多轮状态变化，Python 子进程尝试写交付目录绝对路径时被阻断。PowerShell 打包脚本语法、Git Diff 和凭据扫描通过。

两次运行都通过源码服务的 WebSocket 入口。基准报告的 `commit` 字段为启动时工作树的基线 HEAD，后端实际执行同一工作树中的当轮修复。两次间只补齐了 Tester 复用规则，基准任务和评分器未改动。

### Gemma 库存 30

| 轮次 | 端到端 | 原始独立评分 | 模型 / 工具 | 时间 | 输入 / 输出 Token |
|---|---|---|---:|---:|---:|
| 1 | FAIL，`WORKFLOW_ROLE_PERMISSION` | 对保留的交付副本单独运行，PASS | 23 / 27 | 299.92 秒 | 298996 / 8873 |
| 2 | PASS，`completed_verified` | 原断言在端到端运行内通过 | 27 / 30 | 324.59 秒 | 381821 / 8489 |

首轮前四个 Developer 步骤结束后，已有 Tester 在专属副本运行 unittest，6 项通过。计划中这个 Tester 少了文档步骤依赖，第一版补齐规则为此加了第二个 Tester。第二个 Tester 尝试直接运行库存新增命令，原有角色规则阻断了调用。交付目录无库存数据文件，原始独立评分在另一份副本通过。根据这条证据，将运行时规则改为优先补齐现有待执行 Tester 的无环依赖，避免不必要的二次交接。

第二轮只执行一个 Tester，五个持久化步骤均完成。Developer 的连续新增、查询与负数输入命令使用同一个临时 cwd，两次新增后查询得到 `ITEM1=15`，负数输入实际退出 1。Developer 自测两次失败，修正后退出 0。Tester 在另一 cwd 运行 7 项 unittest，退出 0。最后独立运行的 unittest 在第三个 cwd 执行 7 项并退出 0。独立评分器通过跨进程持久化、重复增加、负数和最终状态断言。交付目录只有 `inventory.py`、`storage.py`、`test_inventory.py`、`README.md`，无 `inventory.json`。

本地脱敏汇总保存在 `build/v11-planning-isolation-live-1/results.json` 和 `build/v11-planning-isolation-live-2/results.json`。原始事件、进程日志和评分证据可按每轮的 `evidence` 定位。

## 结论与交付

真实额度已使用 2/2。最终实现有一次端到端通过，首轮独立功能评分也通过，但这不足以证明最终实现已稳定复验。建议先对同一提交再做一次定向库存验收，再启动完整 RC。若再次出现 Tester 在取得证据后自行选择额外业务命令，可将已核准测试命令绑定到 Tester 的确定性执行步骤，模型保留结果分析职责。预计只涉及 Tester 调度和验证证据处理，角色权限、Provider 和基准断言均沿用。

[PR #38（Draft）](https://github.com/yunfei00/local-coding-agent/pull/38) · [Windows / Ubuntu CI](https://github.com/yunfei00/local-coding-agent/pull/38/checks)
