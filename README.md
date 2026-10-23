# Local Coding Agent

Local Coding Agent 是一个面向 Windows 本地开发环境的桌面 Coding Agent。目标是提供类似 Codex Desktop 的核心开发体验，同时让模型、Agent、工具链、数据和权限边界保持在用户自己的环境中。

> 当前代码版本：**v0.4.2**
>
> 最近正式发布：[**v0.4.2**](https://github.com/yunfei00/local-coding-agent/releases/tag/v0.4.2)

v0.3 增加 MCP stdio/HTTP、Repository Map、Pinned Context、Git Stage/Unstage 与 Worktree、持久化任务计划和执行统计。桌面支持项目树独立展开、会话改名、Markdown/代码复制、浅深主题，以及不遮挡输入框的右侧面板。人工验收已通过；自动化证据与主线集成记录见 [最终验收记录](docs/v0.3-final-validation.md)。

本地依赖统一由 uv 与 npm 锁文件管理：

```powershell
uv sync --locked
npm.cmd --prefix desktop ci
uv run python scripts/validation/check.py
```

## M1 单在线模型 Agent 闭环（源码）

M2 增加统一终端与受管理进程工具 `start_process` / `read_process` / `stop_process`，支持 PowerShell、CMD、Bash、持续输出、超时和进程树清理，并提供 Python、React/TypeScript、真实 Electron 的工程回归。见 [M2 实施与能力矩阵](docs/m2/implementation.md) / [自动验收](docs/m2/acceptance.md)。本阶段不包含 M3 桌面截图、鼠标和键盘自动化。

Task → Task strategy 选择 **Single Agent (online)**，在 Models and budget 中绑定一个 OpenAI Compatible 的 **executor task profile**，填写目标后启动。模型直接读取文件、执行终端、修改代码、接收真实工具结果并继续调用工具；无需配置 Planner、Reviewer 或本地模型。任务仍在受管理 Worktree 中执行，完成后由真实命令独立验证并展示 Diff；支持暂停、取消、检查后恢复。

沿用已有 API 调用上限；多轮工具任务需要足够的调用次数，默认 3 次可能提前停止。切换模式不修改用户显式预算。Key 继续使用桌面安全存储，不写入任务配置。详见 [M1 能力与架构审计](docs/m1/architecture-audit.md)、[验收记录](docs/m1/acceptance.md)、[M2–M5 接口规划](docs/m1/roadmap.md)。本阶段不创建 Tag、Release 或安装包。

## v0.4 Local-first Autonomous Coding

Task 面板按需启动自主任务：默认 Local-first，规划/执行/审查使用本地模型，有限升级调用 API；支持 Local-only、API-only、四角色配置、持久化阶段、暂停/取消/恢复、请求前任务/全局预算、独立验证和完成报告。实际执行复用 v0.3 Agent Loop、权限、Approval、计划、Checkpoint、Shell 与受管理 Worktree，不自动提交、推送或合并。

Settings → Models & Routing 同时配置多个 Ollama/API 连接和模型，四角色独立跨连接绑定；任务冻结解析快照，API 预检按实际连接类型计费。旧配置自动迁移，原 API Key 保留安全存储。普通聊天的 Provider 选择不改变自主任务角色。

v0.4.2 修复旧会话模型与底部显示不一致：发送请求携带当前 Chat model，后端验证后保存并执行，不再误用上一个 Provider 的模型名。不可用的旧模型会明确标注并阻止发送。见 [聊天模型同步修复](docs/v0.4/chat-model-sync.md)。

main 另包含 Planning 重试与诊断修复（尚未发布安装包）：独立持久化规划上限、JSON/工具计划兼容、真实 Usage 结算和 Task 顶部取消入口。见 [根因与调用链](docs/validation/planning-api-root-cause.md) / [测试与公司源码更新](docs/validation/planning-api-test-results.md)。本轮真实 API 按用户要求 NOT RUN。

Task 启动预算检查也已补充具体任务/全局字段、限额、已用/预留、本次所需及模型输出上限；新任务读取最新 Settings，仅覆盖 Task 面板中主动编辑的字段，旧任务保留快照。见 [预算启动审计](docs/validation/task-start-budget-root-cause.md) / [测试记录](docs/validation/task-start-budget-test-results.md)。此修复同样只在源码 main，旧 v0.4.2 安装包不含修复。

真实 CPU Ollama 已验证新路由、规划与实际工具调用，但小模型未完成修复；真实付费 API 尚未验收。跨 Provider、升级回交、Usage、预算和恢复通过实际 HTTP Mock 验证，不能将其视为真实付费消费或公司模型能力证明。构建和发布状态见 [验收记录](docs/v0.4/acceptance.md)。

- [架构审计](docs/v0.4/architecture-audit.md) / [设计](docs/v0.4/design.md)
- [模型路由](docs/v0.4/model-routing.md) / [预算](docs/v0.4/budget-control.md)
- [独立验证](docs/v0.4/verification.md) / [公司部署与使用](docs/v0.4/user-guide.md)
- [混合 Provider 审计](docs/v0.4/mixed-provider-audit.md) / [公司环境完整验证流程](docs/v0.4/company-validation.md)

## 当前能力

v0.4.1 调整桌面字体和控件尺寸：正文/输入框 16px、常规界面 14px、辅助文字 12px。会话右侧 `…` 或右键菜单 → Rename，在居中弹框中改名；侧栏 New project 在居中弹框中选择名称、位置与是否初始化 Git。详见 [桌面交互更新](docs/v0.4/desktop-usability.md)。

v0.2.0 已经完成可用的单 Agent 本地开发闭环：

```text
打开本地项目
  -> 创建 / 恢复 Thread
  -> 向 Agent 提出开发任务
  -> Agent 读取 / 搜索代码
  -> 执行本机命令
  -> 流式查看 stdout / stderr
  -> 根据真实错误继续分析
  -> 修改文件 / Patch
  -> 重新测试
  -> 查看逐文件 Git Diff
  -> 输出完成总结
```

主要能力：

- Electron + React + TypeScript Desktop。
- Python Agent Core，本地 WebSocket + JSON 协议。
- Ollama Provider。
- OpenAI-compatible Provider。
- Provider / Agent / Context / Prompt Rules / Safety 设置。
- Global / Project / Thread Prompt Rules。
- SQLite 持久化的 Project / Thread / Message / Tool 状态。
- Context Budget 管理。
- Agent Loop 重复调用、失败上限、重试和取消保护。
- Python / Node / Android / CMake 项目检测。
- 文件读取、目录浏览、搜索、写入和 Patch。
- PowerShell / CMD / Git / Python / Node / Gradle 等本机命令执行。
- 实时 stdout / stderr、PID、Stop 和进程树终止。
- Git status / diff / log。
- 多文件 Diff Review、rename / binary / large diff 处理。
- Read Only / Workspace / Full Access 权限模式。
- 高风险操作 Approval。
- Diagnostics 与一键复制脱敏报告。
- 手动更新检查。
- Windows Setup + Portable 发布包。

## Provider

### Ollama

Ollama 是默认 Provider，适合完全本地运行。

已经验证过的开发环境包括本地代码模型，例如：

```text
qwen2.5-coder:1.5b
```

Provider URL、模型、Context Window 和 Temperature 可以在 Settings 中配置。

本轮在 Windows CPU 环境验证了该 1.5B 模型的聊天、Stop 与历史恢复；文件读写任务未发出结构化工具调用，记录为模型能力限制。多步骤工具行为使用确定性 Provider 和实际工具回归验证。

### OpenAI-compatible

支持标准 OpenAI-compatible Chat Completions / streaming / tool calls 接口。

API Key 不以明文写入 SQLite：

- 优先使用 Electron OS-protected storage；
- 无安全存储能力时仅使用 session/environment；
- Diagnostics 和日志会进行脱敏。

## 安全边界

Local Coding Agent 始终以运行时 Permission Policy 为准。

权限模式：

- **Read Only**：只允许读取、搜索和只读 Git 操作。
- **Workspace**：允许在当前 Workspace 内修改文件和执行命令。
- **Full Access**：允许更宽的本机操作，但高风险操作仍需要 Approval。

重要规则：

- Prompt Rules 不能绕过 Permission / Approval。
- Agent 不得覆盖无关的已有未提交修改。
- Agent 不得因为自己的判断主动创建 Git commit。
- Agent 不得因为自己的判断主动 Git push / 发布。
- **只有用户当前请求明确要求 commit / push 时，才允许进入相应审批流程。**

## 协议

Desktop 与 Python Agent 使用独立于产品版本的语义协议版本。

当前协议：

```text
1.0.0
```

兼容策略：

- Desktop 当前支持 protocol major `1`。
- `1.x.x` 视为兼容。
- 不兼容 major 会在 WebSocket 建立前明确拒绝，并显示 `Unsupported Agent protocol`。
- 产品版本（例如 v0.2.0 / v0.3.0）与协议版本独立演进。

## Windows 开发启动

前提：

- Windows 10 / Windows 11
- Python 3.11+
- Node.js
- npm
- Ollama（使用本地 Provider 时）

启动：

```powershell
git switch main
git pull
.\scripts\dev\start.ps1
```

## 测试

Python：

```powershell
uv run python -m compileall agent
uv run python -m unittest discover -s tests -v
```

Desktop：

```powershell
npm.cmd --prefix desktop ci
npm --prefix desktop run typecheck
npm --prefix desktop run test
npm --prefix desktop run build
```

每个开发阶段都要求 Windows + Ubuntu CI 通过。

## 发布

当前正式版本：

```text
v0.4.0
```

正式发布包含：

- `Local-Coding-Agent-0.4.0-x64-Setup.exe`
- `Local-Coding-Agent-0.4.0-x64-Portable.exe`
- `SHA256SUMS.txt`

Release：

https://github.com/yunfei00/local-coding-agent/releases/tag/v0.4.0

## v0.3 方向

v0.3 的主题是：

> **Extensible, repo-aware and task-isolated local coding agent**

主要阶段：

1. Protocol / docs cleanup。
2. MCP client foundation。
3. MCP safety + Settings。
4. Repository Map + `@file` / pinned context。
5. Git workflow v3 + task worktrees。
6. Persistent task plans + checkpoints。
7. Execution / context observability。
8. v0.3 hardening / RC。

完整路线：

- [v0.3 Development Roadmap](docs/v0.3-roadmap.md)

v0.3 明确暂不包含：

- Full Multi-Agent orchestration。
- SSH Remote Workspace。
- Browser / computer control。
- Semantic vector index。
- Full Monaco IDE。
- Plugin Marketplace。

这些能力在 v0.3 基础稳定后再进入后续版本。

## 架构

```text
Electron Desktop
      |
      | local WebSocket / JSON
      v
Python Agent Server
      |
      +-- Agent Loop
      +-- Context Budget
      +-- Permission / Approval
      +-- Tool Registry
      +-- Prompt Rules
      |
      +-- Ollama Provider
      +-- OpenAI-compatible Provider
      |
      +-- SQLite
```

详细文档：

- [系统架构](docs/ARCHITECTURE.md)
- [v0.1 实施计划](docs/V0.1_PLAN.md)
- [v0.2 Roadmap](docs/v0.2-roadmap.md)
- [v0.3 Roadmap](docs/v0.3-roadmap.md)

## 开发原则

1. **Agent 与 UI 解耦**：Electron 不承担 Agent 推理编排。
2. **Provider 可替换**：模型后端不能写死在 Agent Loop。
3. **统一 Tool 协议**：内置工具和后续 MCP 工具进入统一执行路径。
4. **权限先于自动化**：任何扩展能力不得绕过 Permission / Approval。
5. **真实闭环优先**：真实读取、执行、修改和验证优先于展示效果。
6. **Windows 原生体验优先**：Windows 是首要运行平台，同时维持 Ubuntu CI。
7. **每阶段可验收**：每个 Phase 都必须有自动化回归和明确验收条件。
8. **稳定版本冻结**：新版本开发只进入对应 feature 分支，正式验收前不修改 main。

## 分支策略

- `main`：已验收并正式发布的 v0.4.0。
- `feature/v0.4-local-first-agent`：保留 v0.4 开发历史，已通过 PR #3 合并主线。
- 后续开发在功能分支进行，验收通过后再进入主线。

## License

M3 Windows 桌面工具：[架构与能力矩阵](docs/m3/architecture.md)、[工具接口](docs/m3/tools.md)、[权限与安全](docs/m3/security.md)、[自动验收](docs/m3/acceptance.md)、[M4 准备](docs/m3/m4-readiness.md)。

M4 收尾：[长任务续跑、阻塞恢复与能力矩阵](docs/m4/continuation-recovery.md)、[验收记录](docs/m4/closure-acceptance.md)、[离线真实工具/GUI 演示](manual-fixtures/m4-continuation/README.md)。

暂未确定。
