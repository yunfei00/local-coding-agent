# Local Coding Agent

一个面向 Windows 本地开发环境的 Coding Agent，目标是实现类似 Codex Desktop 的核心开发体验，但模型、Agent、工具链和权限体系完全由自己掌控。

> 当前阶段：**v0.1.0 规划完成，尚未进入正式编码。**

## 项目目标

第一阶段不做完整 IDE，而是优先打通 Coding Agent 最核心的闭环：

```text
打开本地项目
  -> 向 Agent 提出开发任务
  -> Agent 理解项目
  -> 读取 / 搜索代码
  -> 执行本机命令
  -> 根据错误继续分析
  -> 修改代码
  -> 自动重新测试
  -> 展示 Git Diff
  -> 给出完成总结
```

首要运行平台为 **Windows 10 / Windows 11**，首个模型后端为 **Ollama 本地模型**。

## v0.1.0 核心技术路线

- Desktop：Electron + React + TypeScript
- Agent Core：Python
- Agent 通信：本地 WebSocket + JSON 消息协议
- LLM Provider：Ollama，接口层预留 OpenAI-compatible Provider
- 数据持久化：SQLite
- 本地执行：PowerShell / CMD / Git / Python / Node / Gradle / ADB 等
- 代码变更：文件工具 + Patch + Git Diff
- 权限：Read Only / Workspace / Full Access

## v0.1.0 必须实现

1. 本地项目选择与最近项目。
2. Thread / Turn 会话模型。
3. Ollama 服务检测、本地模型列表、流式输出。
4. Agent Loop。
5. 文件读取、目录浏览、搜索、写入、Patch。
6. Windows 命令执行与实时 stdout / stderr。
7. Git status / diff / log。
8. 危险操作审批。
9. 会话持久化与恢复。
10. 类 Codex 的桌面交互布局。
11. 一个真实项目上的“发现测试失败 -> 修改 -> 重测 -> 成功”完整闭环。
12. Windows 开发启动脚本、测试和基础 CI。

## v0.1.0 不做

为了保证第一版尽快形成真正可用的闭环，以下功能后置：

- 完整 IDE / Monaco 编辑器
- MCP
- 多 Agent
- 云端任务
- SSH 远程 Agent
- Android 专用 Agent
- 自动 Git push / 自动合并
- 插件市场
- 向量数据库 / 全仓库长期语义索引
- 多用户和账号系统

## 计划文档

- [v0.1.0 实施计划](docs/V0.1_PLAN.md)
- [系统架构](docs/ARCHITECTURE.md)

## 目标目录结构

```text
local-coding-agent/
├─ desktop/
│  ├─ electron/
│  └─ src/
├─ agent/
│  ├─ core/
│  ├─ llm/
│  ├─ tools/
│  ├─ permissions/
│  ├─ persistence/
│  └─ server/
├─ shared/
├─ tests/
├─ scripts/
├─ docs/
└─ README.md
```

## v0.1.0 最终验收场景

在 Windows 上选择一个真实 Git 仓库，然后输入：

> 检查这个项目为什么测试失败，并修复。修复后重新运行测试，直到通过，并把修改内容告诉我。

系统应能够：

```text
读取仓库
-> 查看 Git 状态
-> 找到测试命令
-> 执行测试
-> 捕获错误
-> 定位相关代码
-> 修改
-> 再次运行测试
-> 必要时继续循环
-> 测试通过
-> 展示 Git Diff
-> 输出最终总结
```

该流程跑通即视为 **v0.1.0 核心能力成立**。

## 开发原则

1. **Agent 与 UI 解耦**：Electron 不直接承担 Agent 推理逻辑。
2. **Provider 可替换**：Ollama 只是第一个 Provider，不能写死。
3. **工具统一协议**：所有文件、Shell、Git 操作都通过 Tool 接口。
4. **权限先于自动化**：任何高风险能力必须有明确边界。
5. **真实闭环优先于 UI 完美**：第一版优先把执行链做通。
6. **Windows 原生体验优先**：首先服务本机开发，而不是 Web 化。
7. **每阶段可验收**：每完成一个阶段都必须能独立验证。

## 分支策略

- `main`：稳定基线和已验收内容
- `feature/v0.1-mvp`：v0.1.0 主开发分支
- 必要时从主开发分支再切短期功能分支

正式编码开始前，从当前 `main` 创建 `feature/v0.1-mvp`。

## License

暂未确定。进入公开发布前再选择合适的开源许可证。
