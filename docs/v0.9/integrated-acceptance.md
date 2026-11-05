# v0.9 综合真实验收记录（进行中）

所有工程位于忽略的 `validation-reports` 隔离目录。驱动通过实际 Electron 界面/生产 IPC，业务修改由 Local Coding Agent 执行。Codex 只准备故障、驱动和独立检查。

| 场景 | 当前证据 | 结论 |
| --- | --- | --- |
| A Python Bug | `v09-workflow-python-independent/report.json`；unittest exit 0，原测试未修改 | PASS |
| B React 开发 | 待执行 | NOT RUN |
| C 四角色 | Planner/Reviewer Qwen，Developer/Tester DeepSeek；4/4 步骤及持久工具记录 | PASS（Python 场景） |
| D 两模型切换 | 同一运行角色交接实际切换，已完成步骤保留 | PASS（角色切换；非额度耗尽故障） |
| E 长任务中断恢复 | 首次 Planner 权限失败后原任务恢复成功；尚需修改后暂停专项 | 部分证据，待专项 |
| F 测试修复与无进展 | 自动化用例已增加；真实专项待执行 | NOT RUN |
| G Windows GUI | 待资源检查后串行执行 | NOT RUN |
| H Git 交付 | Python Diff 和程序报告存在；完整权限专项待回归 | 部分证据 |
| I 低内存 | 调度与 GUI 互斥/低内存序列化单元通过 | 单元 PASS，非真实 GUI PASS |

失败保留：`v09-kimi-capabilities`（HTTP 400）、`v09-workflow-python`（Planner 终端 Schema 与权限不一致）、`v09-workflow-python-resume`（业务运行完成，但驱动误用优惠券契约）。后者通过只核对已完成任务补验，补验没有增加模型请求。不能把前述失败报告改写成 PASS。

资源：近期启动前可用物理内存约 1.2 GiB，运行后曾低于 1 GiB，非分页池约 3.4 GiB。串行测试，不修改 OS 设置，不结束用户应用；本轮进程正常清理，详见每份 lifecycle 记录。
