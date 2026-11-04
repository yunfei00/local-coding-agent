# 统一 Agent Runtime 架构审计与设计

基线：`origin/main` / `489157e197f63c57db2af827610e3010e0f3f9ab`（v0.5.0）。开发分支 `feature/unified-agent-runtime`。原有两个未跟踪目录保留；不修改 main、不合并、不发布。

## 审计结论

普通入口 `App.submit → startTurn → turn.start → AgentServer.run_tool_turn` 已支持 Provider、文件/终端/Git/MCP/桌面工具、权限审批、Pinned Context、上下文裁剪、ExecutionBudget 和执行日志。普通工具首次调用即创建单步骤计划，问答不创建计划；修改后仅提示模型自行验证，缺少程序独立选择并执行验证。

自主入口 `task.start → TaskService.run → run_tool_turn → VerificationEngine` 复用同一工具循环，但要求用户预选模式。其 Worktree、角色/预算快照、Checkpoint、独立测试、修复/升级和 Git 接受流程必须兼容保留。TaskPlanStore 已保护 Completed、不确定操作和重复副作用；只读检查可重跑。WebSocket 恢复已重新加载 Task，但普通聊天的界面状态轮询存在短暂延迟。

## 改造边界

- 主聊天默认统一入口；高级 Task 接口保留，不删除旧任务和模型配置。
- 在原工具循环扩展意图/复杂度元数据，不建立第二套循环、Provider 或状态机。问答不需要额外分类请求；实际读取为分析、实际变更为修改，模型可以提交结构化复杂计划。工具证据和多文件/长操作阈值提供确定性升级兜底，不能降低原权限。
- 简单工具任务保留原单步骤执行日志用于防重复，界面不强制展示复杂计划。复杂任务复用持久化计划、步骤推进、检查点、安全恢复。
- 程序在最后一次变更后独立发现并执行验证，复用 VerificationEngine 和 `_authorize_tool`。优先工程显式配置，再根据文件类型、清单和测试能力选择。没有测试能力时明确 Unverified，不能把 Diff 成功当测试成功。
- 结果是执行日志上的视图，不替换旧数据库状态：完成且验证、完成未验证、部分完成、失败、等待用户、取消。普通问答无需验证。
- 普通运行继续使用有界 ExecutionBudget，并在原账本记录远程请求。请求前调用与高级 Task 共用的预算检查，TaskRuntimeStore 汇总两种入口的全局用量。输入按字节保守预留加最大输出；真实 Usage 结算，未知或中断保留预留，不靠事后统计保证限额。所有真实验收另有有限累计请求、Token 和时间边界。

## 兼容与验证

旧 `turn.start` 调用仍可显式使用旧路径；主 UI 使用统一标志。旧 Task/Plan、Git/Context/Pinned Files/MCP、权限、模型目录均原地复用。新增元数据按缺失默认值读取，不清空任何配置。基线、回归和真实模型结论见最终验收报告；本设计文档不代表尚未运行的验收已通过。

## 实际调用链与数据

`App.submit → preload.startTurn(..., unified=true) → turn.start → chat_provider → run_tool_turn`。不额外请求模型分类；用户请求形态提供保守只读约束，原工具循环中模型提交 `agent_plan`（复用 PLAN_SCHEMA），实际工具、文件变化和操作数量决定升级。复杂计划写入原 TaskPlanStore；简单修改保留单步骤防重复日志但不强制展示复杂面板。

`ExecutionBudget.unified_*` 是原执行记录的附加 JSON，保存请求账本、元数据快照、文件基线、验证历史和当前结果，不建立新数据库状态机。恢复同一 Profile 使用冻结连接/模型/上下文/超时；显式更换 Profile 才使用新快照，预算和证据仍累计。快照只保存凭据引用，客户端继续从原安全存储取 Key。

每次模型请求经过原 ContextBudgetManager，计算工具 Schema 与输出预留。当前目标、步骤与 Completed ID 作为必需后缀重新构建；旧日志按原有有界事实记忆压缩。单条需求超过 16000 字符明确拒绝，不静默丢失目标。问答不提供无关工具；分析的修改工具即使由模型编造也会被服务端拒绝。

## 自动验证与完成

修改前懒加载元数据快照，覆盖受控 Shell/MCP 引发的写入和删除；跳过依赖、产物与符号链接。超过 20000 文件显式要求人工确认，不能宣称完整检测。验证选择优先显式工程命令，再发现受影响最近 package.json 的 typecheck/test/build 和 Python 工程测试；不安装不存在的测试器。TypeScript 没有类型检查能力时标记 Manual。自动拼接命令拒绝 Shell 特殊目录名，所有命令仍经过 `_authorize_tool`。

复杂计划中间步骤只做 Basic 检查，避免尚未实现的后续模块导致过早完整回归；末步骤独立执行 Targeted/Full，不能复用过期语法通过结果。VerificationEngine 捕获命令、退出码、耗时、完整日志和摘要。代码/断言失败有限修复，错误指纹无进展不再修复；环境/配置/网络/权限/超时直接给具体原因并保留恢复入口。只有真实工具证据能推进计划，Completed 不回退，原操作指纹保护和只读重跑沿用。

最终视图：`completed_verified`、`completed_unverified`、`partially_completed`、`failed`、`awaiting_user`、`cancelled`；原数据库状态保持兼容。纯问答无验证需求，不展示开发完成卡片。无工具修改证据的开发请求最多补正一次，随后明确失败。验证受阻不伪造 Completed。

## 同页状态、连接与诊断

`UnifiedProgress` 只显示最新运行；复杂任务按需显示计划，简单修改显示文件与验证。`task.runtime.list` 返回最新真实状态和 active_turn_ids，重连/重启重新同步；不通过前端配置推测调用。断线暂停并保存检查点，不关闭整个服务拥有的 MCP 连接；Stop 使用原取消与进程树清理。

`task.runtime.diagnostics` 导出约 140 行以内当前 Markdown 和本机完整 JSON，WebSocket 不传完整历史。过滤 Prompt、用户文件内容、原始参数和输出；继续调用原密钥脱敏，日志/数据库历史不删除。高级 Task 的 Worktree、角色绑定、追加需求、审批与接受报告流程保留；统一入口默认当前工作区，并不等于自动隔离 Worktree 或运行中引导。
