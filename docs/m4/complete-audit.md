# M4 全面审计（2026-10-23）

基线 main `0000914809c46aefd1dd5987920db9e9eb88bd44`，已 fetch。未跟踪 egg-info 保留，不删除用户数据。PR #15（110c6a0）已有模型诊断/独立 GUI 合约；#16（cc82a84）增加视觉声明和黑屏回退；#17（83b34ee）区分编辑区隐私遮盖；#18（fd3e39f）改进非 Edit 诊断；#19（0000914）增加有界续跑和恢复。这些实现均继续复用。

| 范围 | 审计结论 | 代码/已有证据 | 本轮门禁 |
| --- | --- | --- | --- |
| M1 Single Agent | 已实现：单 Executor、原工具循环、真实测试独立完成门槛 | orchestration.py、test_single_agent.py | 全量回归 |
| M2 命令/后台进程 | 已实现：进程树/Job、流式日志、停止、项目执行 | execution.py、tools/processes.py、test_m2_projects.py | 真实进程回归 |
| M3 桌面 | 已实现：会话、PID/窗口代次、UIA、截图、授权 | desktop/runtime.py、worker.py、tests/test_m3* | 当前 Windows 真桌面 |
| M4 GUI 合约 | 已实现：冻结合约、失败修复、只读 Observer、截图上传审批 | gui_verification.py、test_m4_gui.py | 真实 WinForms 回归 |
| Chat 路由 | 存在缺陷：model.list/ensure_model_available 使用全局旧 Provider；run_tool_turn 按 model 字符串猜 Executor，同名跨连接可能错误 | server/main.py 1128、1733、1837 附近 | 统一 Profile 选择和实际 HTTP |
| Settings | 存在缺陷：Provider 和 Models & Routing 独立编辑，Chat 无法使用完整目录 | SettingsPanel.tsx、App.tsx | 单一目录；旧接口兼容 |
| Profile 视觉 | 已实现声明，但 Chat 会读取无关 Provider；独立 Observer 仅 GUI Task 合约可选 | model_catalog.py resolve、orchestration.py vision_binding | 三身份分别记录/路由 |
| 图像发送 | 存在缺陷：image_message 每次调用都返回同一历史图片，后续请求重复上传 | desktop/runtime.py image_message、main.py 2030 附近 | 每个捕获仅消费一次 |
| 截图诊断/隐私 | 已有 PrintWindow/前台回退、DPI、暗色有效性和 Edit 遮盖区分 | worker.py、test_m3_desktop.py | 当前真实窗口验证，失败不假 PASS |
| 预算/取消/恢复 | 已实现：Task 请求前预留、普通 Turn 有界执行、Stop/继续审批、未知副作用保留 | budget.py、execution.py、task_runtime.py、PR #19 | 全量回归和快照测试 |
| 配置/数据库 | 目录迁移幂等，任务 SQLite 快照保留 | model_catalog.py、persistence/store.py | 不重置；新增设置键/兼容旧绑定 |
| 真实在线模型 | 本轮尚未执行 | 用户历史百炼五项 PASS 只是用户证据 | 无本轮 Live 授权，不发送付费请求 |

自动化基线与最终数量另记验收文档；不以文档代替执行。当前会话通过 computer-use 已确认有交互桌面；后续只操作受控测试窗口，不捕获私人桌面。
