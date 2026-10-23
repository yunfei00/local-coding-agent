# 历史文档审计索引

2026-10-23，以 main PR #18 为起点。审阅既有架构、各阶段验收、模型/预算、任务持久化、Windows 安全和 GUI 证据；旧版本发布记录仅保留为历史，不按其安装包/Release 流程执行。

- M1：保留唯一 Single Agent；不引入 Planner/Reviewer 新角色。
- M2：保留所有权、Job/process tree、真实终端与日志。
- M3：保留窗口身份、敏感控件拒绝、图像上传审批和实际像素；Pane 分支独立保留。
- M4：沿用诊断、冻结 GUI 契约和独立断言；本次补累计执行边界、恢复路径、隐私诊断及已有测试基线。
- v0.3/v0.4：保留多项目、Thread、非模态 Plan/Git/Context、历史任务、工作树与原配置，不扩展多模型路由。
- planning/task-start 专项：不恢复无限 Planning 重试，保留持久化 API 预算与请求日志。聊天续跑额度和 Task API 额度同时生效。

开始检查时 GitHub 无打开 PR；main fd3e39f，PR #16/#17/#18 已合并。未合并 Tkinter 分支保留原 SHA。当前实现矩阵见 [continuation-recovery.md](continuation-recovery.md)，下表为审计覆盖索引（不是重新验收所有历史结论）。

| 文档 | 标题 |
| --- | --- |
| `docs/ARCHITECTURE.md` | 系统架构 |
| `docs/local-validation.md` | 编号式本地自动验收 |
| `docs/m1/acceptance.md` | M1 自动化验收记录 |
| `docs/m1/architecture-audit.md` | M1 架构审计与能力矩阵 |
| `docs/m1/roadmap.md` | M2–M5 接口规划 |
| `docs/m2/acceptance.md` | M2 自动化验收 |
| `docs/m2/implementation.md` | M2：真实工程操作与终端执行可靠性 |
| `docs/m3/acceptance.md` | M3 自动化验收 |
| `docs/m3/architecture.md` | M3 Windows 桌面架构 |
| `docs/m3/m4-readiness.md` | M4 接口准备 |
| `docs/m3/security.md` | M3 权限与安全策略 |
| `docs/m3/tools.md` | 桌面工具接口 |
| `docs/m4/acceptance.md` | M4 自动验收记录 |
| `docs/m4/architecture.md` | M4 自主验收架构与能力矩阵 |
| `docs/m4/autonomous-verification.md` | 自主 GUI 验收与修复 |
| `docs/m4/model-diagnostics.md` | 模型连接诊断 |
| `docs/m4/vision-validation.md` | 视觉能力与截图验证 |
| `docs/PHASE0.md` | Phase 0 - Project Bootstrap |
| `docs/PHASE1.md` | Phase 1 - Thread / Turn WebSocket Protocol |
| `docs/PHASE2.md` | Phase 2 - Ollama Provider |
| `docs/PHASE3.md` | Phase 3 - Tool System v1 |
| `docs/PHASE4.md` | Phase 4 - Full Agent Loop |
| `docs/PHASE5.md` | Phase 5 - Permissions and Approval System |
| `docs/PHASE6.md` | Phase 6 - Terminal Execution and Diff Review |
| `docs/PHASE7.md` | Phase 7 - SQLite Persistence, Session Resume and Conversation Follow |
| `docs/PHASE8.md` | Phase 8 - Real-world Repository Validation |
| `docs/PHASE9.md` | Phase 9 - Windows Packaging and v0.1.0 Release |
| `docs/PYTHON_ENV.md` | Python 环境 |
| `docs/V0.1_PLAN.md` | v0.1.0 实施计划 |
| `docs/v0.2-phase15-validation.md` | v0.2 Phase 15 — Terminal / Tool Stream 人工验收 |
| `docs/v0.2-phase16-validation.md` | v0.2 Phase 16 — Diff / Review v2 人工验收 |
| `docs/v0.2-phase17-validation.md` | v0.2 Phase 17 — Settings 人工验收 |
| `docs/v0.2-phase18-validation.md` | v0.2 Phase 18 — Diagnostics 人工验收 |
| `docs/v0.2-phase19-validation.md` | v0.2 Phase 19 — Update Check + UI Polish 人工验收 |
| `docs/v0.2-roadmap.md` | v0.2 Development Roadmap |
| `docs/v0.3-final-audit.md` | v0.3 最终开发审计 |
| `docs/v0.3-final-validation.md` | v0.3 最终验收记录 |
| `docs/v0.3-implementation-notes.md` | v0.3 本轮实现与验收说明 |
| `docs/v0.3-manual-acceptance.md` | v0.3 最后人工验收 |
| `docs/v0.3-phase22-mcp-foundation.md` | v0.3 Phase 22 — MCP Client Foundation |
| `docs/v0.3-phase23-validation.md` | v0.3 Phase 23 — MCP Safety + Settings 人工验收 |
| `docs/v0.3-phase24-validation.md` | v0.3 Phase 24 — Repository Map + Explicit Context 验收 |
| `docs/v0.3-phase25-validation.md` | v0.3 Phase 25 — Git Workflow v3 + Task Worktree 验收 |
| `docs/v0.3-phase26-validation.md` | v0.3 Phase 26 — 持久化任务计划与检查点验收 |
| `docs/v0.3-phase27-validation.md` | v0.3 Phase 27 — 执行与上下文观测验收 |
| `docs/v0.3-phase28-release-checklist.md` | v0.3 Phase 28 — 工程加固与候选版门禁 |
| `docs/v0.3-roadmap.md` | v0.3 Development Roadmap |
| `docs/v0.4/acceptance.md` | v0.4 混合模型协同验收 |
| `docs/v0.4/architecture-audit.md` | v0.4 架构审计 |
| `docs/v0.4/budget-control.md` | API 预算控制 |
| `docs/v0.4/chat-model-sync.md` | v0.4.2 聊天模型同步修复 |
| `docs/v0.4/company-validation.md` | 公司环境验证流程 |
| `docs/v0.4/design.md` | v0.4 自主任务设计 |
| `docs/v0.4/desktop-usability.md` | v0.4.1 桌面交互更新 |
| `docs/v0.4/mixed-provider-audit.md` | v0.4 混合 Provider 审计 |
| `docs/v0.4/model-routing.md` | 多连接模型路由 |
| `docs/v0.4/user-guide.md` | 公司电脑部署与使用 |
| `docs/v0.4/verification.md` | 独立验证 |
| `docs/validation/planning-api-root-cause.md` | Planning/API 问题审计与根因 |
| `docs/validation/planning-api-test-results.md` | Planning/API 修复测试与公司验证 |
| `docs/validation/task-start-budget-root-cause.md` | Task 首次 API 请求前暂停：审计与修复 |
| `docs/validation/task-start-budget-test-results.md` | Task 预算启动修复：测试结果 |
