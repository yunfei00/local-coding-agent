# v0.4 架构审计

日期：2026-10-22。修改运行代码前完成。基线：`9c73179`（v0.3 已人工验收并合并），工作区干净，远端 main 无新增提交。开发分支：`feature/v0.4-local-first-agent`。

## 可复用能力

- `agent/server/main.py` 的 `run_tool_turn` 是实际 Agent Loop：上下文裁剪、流式 Provider、ToolLoopGuard、权限/Approval、工具输出、真实计划证据、取消和检查点。继续使用此入口，不复制工具循环。
- `agent/task_plans.py` 的 SQLite 计划、步骤、执行证据、变更指纹和检查点；任务元数据应以原计划 ID 为主键扩展。
- `agent/llm` 的 Ollama、OpenAI 兼容 Provider；现有接口有流式取消、连接状态和错误分类，缺少任务路由、请求输出上限和完整使用量。
- `agent/tools` 的 Registry、Workspace、Shell 和 Windows Job Object；验证命令也须经运行时权限和 Approval，不新增绕过权限的 subprocess 执行器。
- `agent/tools/git.py` 的受管理 Worktree、Diff、提交准备和显式提交审批。自主任务默认创建隔离 Worktree，保留原工作区脏文件；不自行提交、推送或合并。
- Electron 的本地认证 WebSocket、safeStorage 密钥、React 消息流、Diff/Git/Context/Plan 按需侧栏、Enter/Shift+Enter 和滚动跟随。

## 缺失与风险

1. 当前 turn 不持久化完整执行状态。计划步骤状态不能表达 planning/verifying/escalating；应扩展原计划的任务运行元数据和合法状态转换。
2. 当前全局单 Provider，缺少角色路由和任务快照。不能在任务中修改全局 Provider，否则配置和活动会话会串用。
3. 当前没有 API 请求前预算预留。重试、超时和崩溃都可能已产生费用，不能在恢复时退还不确定的预留；全局账本需原子检查。
4. 现有 Loop 的完成事件不等于独立验收通过。自主任务必须在模型循环后直接运行配置的验证命令，并以退出码判定；没有命令时停止并明确说明。
5. Shell 输出有内存上限，但无验证完整日志文件。新增日志须在应用数据目录，摘要有限，不能把全仓库或密钥交给升级模型。
6. 已安装 CPU 小模型在 v0.3 真实读写请求未输出结构化工具调用。能力不足应明确报告，不能把 Mock 成功描述成真实模型成功。
7. README 的测试命令、开发分支和 main 描述仍有历史 v0.2/v0.3 内容，需随 v0.4 文档修正。

## 修改范围

计划扩展 `agent/task_plans.py`，新增编排、路由、预算和验证模块；为 `run_tool_turn` 注入任务 Provider/项目/计划及授权执行复用入口。扩展现有 Provider 的输出限制与统计。通过原协议、IPC 和按需 Task 界面展示状态、模型、预算、验证和报告。复用现有 fixtures 路径，另加 v0.4 场景，不改变旧契约。

## 基线验证

执行：`uv run python scripts/validation/check.py`。

- Python：174 通过，0 失败。
- Desktop：29 通过，0 失败。
- TypeScript 和生产 Build：通过。
- 本地报告：`validation-reports/20261022-012536-418102.json` 和同名日志（忽略、不上传）。
- CI 已支持 Windows/Ubuntu；候选包脚本包含 Agent、实际打包桌面、Portable、Setup 和哈希复算。正式发布工作流在版本 Tag 推送时构建并发布；本轮仅在全部门禁及真实环境验收满足后触发。

## 验收边界

自动化使用 Mock Provider 加真实临时 Git 工程和工具，不需要付费 API。另行记录本机 Ollama 和可选付费 API 实测。若真实环境验收未完成，保留功能分支并报告阻断，不创建正式 Tag 或发布。
