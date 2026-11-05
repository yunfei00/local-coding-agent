# 状态与事件

高级 Task 保留 `TaskRuntimeStore.TRANSITIONS`：pending → planning → executing → verifying，必要时 repairing/escalating，独立验证通过后 awaiting_approval。暂停、取消与失败保留原数据。

统一 Chat 保留原 `unified.phase` 与 outcome：executing、verifying、repairing、paused、failed、cancelled、completed；结果区分已验证、未验证、部分完成、等待用户与失败。

## 本轮约束

1. 每个尝试使用 turn ID 作为 generation；事件使用唯一 event_id，模型请求使用独立 request_id。
2. 状态与对应事件同事务保存。UI 继续使用 revision，重连查询真实持久状态。
3. 当前 generation 已取消后不能接受迟到的 executing/completed。已完成终态也不能被迟到失败改回失败。
4. 显式恢复入口核对线程、原运行、工作区确认、终态与原始目标后建立新 generation。旧事件不能修改新尝试。
5. 主动取消不自动恢复；断线或后端中断标记 paused，保留预算与证据。
6. 追加需求在完整工具批次之后、下次请求之前生效；不会插入未配对的 tool_calls/tool 消息。
7. reviewed 是执行 Journal 中的人工审阅标记，不是成功、计划完成或验证通过；完整历史保留，不能据此生成成功证据。
8. 桌面交互没有成功动作时拒绝模型的文字完成声明；有动作但未附独立 GUI 合约时使用 Completed & Unverified / Manual Required，不将界面点击等同于代码测试通过。

阶段迁移不代表验收通过。完成必须复用原独立验证结果和步骤执行证据；不能以模型文字自评替代。

相关测试：`tests/test_v06_runtime_events.py`、`test_v06_runtime_integration.py`、`test_unified_runtime.py`、原 Task/L3 状态测试。
