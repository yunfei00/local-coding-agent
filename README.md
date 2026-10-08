# Local Coding Agent

Local Coding Agent 是一个面向 Windows 本地开发环境的桌面 Coding Agent。目标是提供类似 Codex Desktop 的核心开发体验，同时让模型、Agent、工具链、数据和权限边界保持在用户自己的环境中。

> 稳定版本：**v0.2.0**
>
> 当前开发：**v0.3**（`feature/v0.3`）

## 当前能力

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
qwen3-coder:30b
```

Provider URL、模型、Context Window 和 Temperature 可以在 Settings 中配置。

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
git checkout feature/v0.3
git pull
.\scripts\dev\start.ps1
```

## 测试

Python：

```powershell
python -m compileall agent
python -m unittest discover -s tests -v
```

Desktop：

```powershell
npm --prefix desktop install
npm --prefix desktop run typecheck
npm --prefix desktop run test
npm --prefix desktop run build
```

每个开发阶段都要求 Windows + Ubuntu CI 通过。

## 发布

当前正式版本：

```text
v0.2.0
```

正式发布包含：

- `Local-Coding-Agent-0.2.0-x64-Setup.exe`
- `Local-Coding-Agent-0.2.0-x64-Portable.exe`
- `SHA256SUMS.txt`

Release：

https://github.com/yunfei00/local-coding-agent/releases/tag/v0.2.0

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

- `main`：最新正式稳定版本，目前为 v0.2.0。
- `feature/v0.3`：v0.3 主开发分支。
- 必要时再从 v0.3 分支拆短期功能分支。

## License

暂未确定。
