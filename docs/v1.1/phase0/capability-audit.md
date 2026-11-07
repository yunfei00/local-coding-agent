# v1.1 Phase 0 能力审计

基线为 `e343a4e7fa4ae5e078fd3624f2d4e4d28f6c4ea7`，与公开 v1.0.1 标签一致。下表的历史真实证据来自 `reports/v1.0.1-gemma-stability/acceptance-report.md`、`reports/v1.0.1-gemma-runtime/acceptance-report.md` 及 `docs/v0.9`。历史证据只覆盖其明确记录的场景。Phase 0 结果单独统计。

| 范围 | 能力状态 | 源码和覆盖 | 限制、风险与优先级 |
|---|---|---|---|
| 意图、规划、多步执行 | 已实现且真实验证 | `agent/server/main.py`、`agent/core/unified_runtime.py`、`agent/core/workflow.py`；`tests/test_unified_runtime.py`，历史多模块空白工程 | 复杂度分类、计划质量和跨文件依赖的真实样本仍少。P0 |
| 工具调用、文件修改 | 已实现且真实验证 | `agent/tools/registry.py`、`agent/tools/filesystem.py`、`agent/tools/workspace.py`；历史 A、C、D | 不保证多文件改动原子提交。P0 |
| 纠错、循环检测、完成判定 | 已实现且真实验证 | `agent/server/main.py`、`agent/core/execution.py`、`agent/core/verification.py`；历史 C、CLI 复验 | 模型声明和交付状态分离，缺少通用可执行需求合同。P0 |
| 取消、恢复、Checkpoint | 已实现且真实验证 | `agent/core/task_runtime.py`、`agent/task_plans.py`、`agent/core/background.py`；原 benchmark R 和 `tests/test_v09_workflow.py` | 恢复质量取决于持久化证据；外部操作结果不确定时需确认。P0 |
| 上下文管理 | 已实现且真实验证 | `agent/core/context.py`、`agent/core/execution.py`；`tests/test_api_context_fit.py`，Gemma 长响应与阶段执行报告 | 仍需跨长任务测试关键信息压缩。P1 |
| 创建和修改 Python 工程 | 已实现且真实验证 | `agent/server/projects.py`、`agent/tools/filesystem.py`；历史 3 个工程、C | 旧样本以小工程为主。P0 |
| TypeScript、React 和构建 | 已实现且真实验证 | `agent/core/project_detection.py`、`agent/core/verification.py`；v0.9 React 记录，桌面构建 | Phase 0 使用零安装 ESM，React 用例验证业务层，未挂载 DOM。P0 |
| Git 分支、差异、提交 | 已实现且真实验证 | `agent/tools/git.py`、`agent/core/workflow_delivery.py`；历史 E，`tests/test_git_workflow_v3.py` | 大规模冲突和复杂 Git 历史的通用修复仍需取证。P0 |
| 依赖安装、环境恢复 | 部分实现 | `agent/tools/shell.py`、`agent/tools/environment.py`、`agent/core/environment_diagnostics.py` | 可调用系统工具，缺失安全、可复现的跨环境依赖求解流程。P0 |
| 自动测试与交付验证 | 已实现且真实验证 | `agent/core/verification.py`、`agent/plan_verification.py`、`agent/core/workflow_delivery.py`；历史 Python 和 React | 项目测试与用户需求可能脱节，需要独立合同及差异证据。P0 |
| GitHub 集成与 CI 修复 | 部分实现 | `agent/tools/git.py` 的 GitHub origin 只读 CI 查询，`.github/workflows/ci.yml` | 尚无专用远程 CI 诊断、补丁、重跑的产品闭环。P1 |
| Ollama、OpenAI 兼容接口、工具协议 | 已实现且真实验证 | `agent/llm/ollama.py`、`agent/llm/openai_compatible.py`；`tests/test_ollama_provider.py` 与历史 Ollama/在线测试 | 模型支持的协议和返回形态不同。P1 |
| 能力检测、模型切换和路由 | 已实现且真实验证 | `agent/core/model_diagnostics.py`、`agent/core/model_routing.py`、`agent/llm/router.py`；v0.8/v0.9 路由证据与 `tests/test_v08_routing.py` | 本轮只使用一个固定模型，模型切换沿用历史证据。P1 |
| 输出长度、上下文、超时与恢复 | 已实现且真实验证 | `agent/llm/ollama.py`、`agent/core/execution.py`、`agent/core/runtime_events.py`；Gemma Runtime 报告 | Ollama 默认输出由服务决定，长上下文受服务器资源约束。P1 |
| UIA、截图、窗口识别、前台 | 已实现且真实验证 | `agent/desktop/runtime.py`、`agent/desktop/session.py`、`agent/tools/desktop.py`；历史 F 与 `tests/test_m3_desktop.py` | 锁屏、UAC、安全桌面以及窗口权限会阻断。P1 |
| 鼠标、键盘、保存、真实结果校验 | 已实现且真实验证 | `agent/desktop/worker.py`、`agent/core/gui_verification.py`；历史 F-desktop 文件读回和前台 PID 证据 | 应用特定业务验证仍需外部合同。P1 |
| 权限与安全边界 | 已实现且真实验证 | `agent/permissions/policy.py`、`agent/permissions/approval.py`；`tests/test_v10_permissions.py` 和 v1.0 安装验收 | 终端权限是审批策略，不能充当 OS 沙箱。P0 |
| MCP | 已实现但缺少真实验证 | `agent/mcp/runtime.py`、`agent/tools/mcp.py`；`tests/test_mcp_runtime.py` 测试服务器 | 本轮缺少真实第三方 MCP 的隔离验收。P1 |
| Skills | 未实现 | `agent/core/repository_instructions.py` 读取工程指令，`workflow_templates.py` 提供模板 | 工程指令与模板无法构成 Skills 的安装、发现和调用生命周期。暂缓 |
| 浏览器操作 | 部分实现 | `agent/tools/desktop.py` 可通过通用 Windows 工具操作浏览器；Playwright 只用于验收驱动 | 未找到产品级 DOM 浏览工具。P1 |
| 工程索引与检索 | 已实现且真实验证 | `agent/core/project_knowledge.py`、`agent/core/repository_map.py`、`agent/tools/knowledge.py`；v0.8 报告和 `tests/test_v08_knowledge.py` | 词法和符号检索，语义召回不是当前基线。P1 |
| 多模型角色协作 | 已实现且真实验证 | `agent/core/workflow.py`、`agent/core/orchestration.py`、`agent/llm/router.py`；v0.9 协作证据 | 本轮排除多模型变量。P1 |
| 多机调度 | 未实现 | `agent/core/background.py` 和 `workflow.py` 的队列、并发冲突规则限于本地运行时 | 无远程工作节点、租约、分布式恢复。暂缓 |

