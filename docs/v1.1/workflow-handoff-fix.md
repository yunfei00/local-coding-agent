# v1.1 库存工作流交接修复

基线 `ee3f1ebc745ef90205c5ba0bc67ff18965e84fc6`。本报告随修复提交到 `feature/v1.1-release-candidate`。[PR #38 提交](https://github.com/yunfei00/local-coding-agent/pull/38/commits)

## 根因与修复

旧库存 30 在 Tester 没有可用测试的情况下仍进入该角色。历史 Gemma 日志记录两次越权写请求，最终为 `WORKFLOW_ROLE_PERMISSION`。原修复路径要求已经存在真实失败命令，缺少测试时没有相应的角色回退条件。确定性集成复现以 Developer 完成实现、工程没有测试为起点，旧流程没有生成补测步骤，结果为 `partially_completed`。

- `agent/task_plans.py` 为缺失测试增加一次有界的 Developer 补测节点。Tester 原依赖和已完成节点保留，缺失状态进入检查点，没有虚构失败命令。补测后仍无声明则保留 `BLOCKED`。
- `agent/core/workflow.py` 校验 Developer 的声明，包括根目录的 unittest 脚本、精确命令、工作目录、预期退出 0、隔离范围和脚本哈希。运行时还记录交接版本指纹。
- `agent/server/main.py` 在进入 Tester 前检查是否缺少测试。Tester 仍然只执行获准的命令，有交接时只能执行所声明的隔离命令，并核对脚本哈希。退出状态和工具调用留在真实账本，零测试不作为通过。真实测试失败继续走已有 Developer 修复路径。最终独立评分契约保留。

## 确定性回归

新集成用例真实执行了 Developer → 补测 Developer → Tester。Tester 获得真实退出 0 和当前步骤证据。脚本对相对路径的写入发生在隔离目录，交付目录中原文件保持原字节。另有测试覆盖只有一次缺失交接修复、再次缺失被阻断，以及缺失时无伪造命令记录。权限、取消恢复、文件保护、工作流、过程工具和基准的相关本地测试合计 126 通过、1 跳过。Tester 权限、审批、重复执行防护均保持。隔离工作目录沿用现有执行机制，其保护范围以相对路径和授权检查为准。

## 真实 Gemma

| 独立运行 | 状态 | 实际证据 |
|---|---|---|
| 库存 30 第 1 次 | FAIL | `DELIVERY_ASSERTION`，外部命令退出 1。236.64 秒，17 次模型请求，26 次工具调用，输入 212458、输出 6776 Token。 |
| 后续运行 | NOT_RUN | 首次失败在角色交接之外，按止损规则停止。 |

模型为 `gemma4:31b`。它生成的四个步骤全部分配给 Developer，真实运行没有进入新 Tester 交接分支。Gemma 的交付说明写道“测试过程中使用了独立的 `test_inventory.json` 文件，以避免污染生产数据”，并报告 unittest 7 项通过。工具轨迹同时记录了未设置 `isolated_cwd` 的存储探测和 `python inventory.py add …`。独立评分前，交付目录的 `inventory.json` 已含合成测试键 `apple`、`SKU1`、`SKU2`，因此原断言失败。真实运行没有发生 Tester 权限拒绝。

确定性场景的正确交接为 Developer 声明 `test_delivery.py`，命令 `python -m unittest discover -s . -p test_delivery.py -v`，工作目录 `.`，预期 `[0]`，数据范围 `owned_scratch`。Tester 的真实进程在隔离工作目录执行，原文件保护和独立评分均有各自证据。

## 交付结论

真实库存稳定性门槛未达，暂缓完整 RC 验收。后续可在确定性工作流中要求状态型验证任务包含独立 Tester，并让所有临时写入共用一个可审阅的隔离脚本，避免 Developer 早期直接在交付目录试跑；这属于真实运行暴露的另一个问题，本轮保持修复范围。没有使用在线模型，没有重跑 30 项全套或旧 21 项。PR #38 保持 Draft，未合并 main，未发布。[Windows / Ubuntu CI](https://github.com/yunfei00/local-coding-agent/pull/38/checks)
