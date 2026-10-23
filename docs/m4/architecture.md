# M4 自主验收架构与能力矩阵

> M4 收尾（PR #18 后）的续跑、恢复、诊断与验收保护矩阵，见 [continuation-recovery.md](continuation-recovery.md)。本文以下保留原 M4 历史基线，不能把当时的凭据状态视为当前实时配置。

日期：2026-10-23。基线 main `0b29397ab2d78abe777121080deda8b2b856d293`，分支 `codex/m4-autonomous-verification`。继续使用 M1 `AgentServer.run_tool_turn`、M2 `ProcessManager` 与 M3 `desktop_*`；没有第二套 Agent Loop，也没有增加 Planner/Reviewer/路由角色。

## 执行路径

TaskService 创建隔离 worktree → 在模型修改前冻结命令和 GUI 契约 → 同一个 Single Agent 读取、修改、调用工具 → 独立 VerificationEngine 执行构建/测试 → M2 启动真实应用 → M3 控件断言与截图 → 可选视觉观察 → 真实失败反馈回原控制器 → 有界修复 → 最终报告、Git Diff、人工审阅。

GUI 契约来自 Task 配置 `gui_verification` 或工程 `.lca/gui-verification.json`。文件发现有工作区约束和 32 KiB 上限；发现后写入任务快照，模型修改文件不会削弱当前任务断言。未配置 GUI 契约时报告 `GUI NOT RUN`，普通单元测试通过不代表 GUI 通过。识别项目/测试命令继续使用 M2 `discover_commands`；GUI 启动命令需要明确契约，不能凭项目名猜测验收标准。

视觉观察器由 `vision_profile_id` 选择，可与编码模型为同一 profile。它不进入原 ROLES，不接收工具 schema，不允许执行工具；请求仍通过已有 RoutedProvider/BudgetGuard，计入原任务时间、调用和 Token 限额。图像经过 M3 遮盖、JPEG 转换与独立上传审批。UI 文本始终是不可信观察数据。默认 UI Automation 不发送图像。

## 能力矩阵

| 能力 | M3 基线 | M4 实现与代码证据 |
| --- | --- | --- |
| 独立连接/持久化/切换 | 已实现；保存 key 后还需另存引用 | 已实现；`ModelSettingsSection` 保存 key 同时持久化连接引用，保留其他连接；`ModelCatalog.validate_catalog` 拒绝跨连接引用、非法端口 |
| 文本/视觉/Function Calling 实测 | 未实现，仅 models GET | 已实现；`core/model_diagnostics.py::ModelDiagnostics`，严格断言、独立状态、最小请求、无副作用虚拟工具 |
| 声明与实测能力区分 | 部分实现，supports_vision 声明 | 已实现独立展示；不依据模型名推测，不自动把声明改成“已验证” |
| JPEG 进入选定模型 | 已实现同一模型原生图片消息 | 已实现诊断和独立观察 profile；`synthetic_image`、`TaskService.observe`、M3 `image_message`，真实 HTTP/JPEG 回归 |
| 自主 GUI 修复闭环 | 部分实现：工具可用，无通用独立 GUI gate | 已实现显式契约；`gui_verification.run_gui` + 原 `TaskService.run` 的修复循环 |
| GUI 结果防自证 | 部分实现，依赖外部验证命令 | 已实现不可变 UIA 状态断言、M2 Job 成员检查、SHA256 截图证据；模型一句“通过”不改变结果 |
| 取消/超时/风险审批/清理 | 已实现 M2/M3 | 复用并覆盖独立验收阶段；每步/GUI/总任务边界，finally 清理，拒绝上传不调用观察器 |
| 修复记录与报告 | 部分实现，当前失败与次数 | 已实现最多 10 轮 `verification_history`、实时进度、每轮失败、最终 GUI PASS/NOT RUN 与 Diff |
| 无配置自然语言生成任意应用验收标准 | 未实现 | 部分实现：Agent 可操作工具，独立验收需显式/工程预设契约，无法确认时不宣称 GUI 成功 |
| 百炼用户凭据与付费实测 | 未实测 | 本机发现凭据引用缺失，无可用 key；文本/图片/工具真实付费测试 NOT RUN，见验收记录 |
| 所有 Windows 自绘/Electron 界面 | 部分实现 | 保持 M3 边界；真实 WinForms 闭环已验收，React/TS/Electron 构建与进程回归；不声称覆盖所有 GUI |

## 依赖与 M5 接口准备

没有新增自动化库。Pillow 从 Windows 专用改为跨平台安装，唯一新增用途是 Ubuntu/Windows 都能在内存生成诊断合成 JPEG，保留原图片处理用途。Windows UIA 仍只在 Windows 安装 pywinauto。

M5 可复用连接诊断报告、冻结 GUI 契约、`verification.progress`、`verification_history`、截图 artifact_id/SHA256、现有审批与进程会话接口。未来可增加验收模板与更丰富断言，不能绕过独立证据、上传授权、调用预算与取消。本次不进入 M5；百炼实际服务兼容性仍需可用凭据和显式 Live Test。
