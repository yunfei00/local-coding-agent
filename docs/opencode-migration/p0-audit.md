# P0 架构审计（OpenCode 核心替换）

> 审计日期：2026-11-26
> 审计分支：`feature/opencode-engine-migration`
> 审计 HEAD：`4e9d8e5fb5e8d9510a8dccad6c8bc1635f12ac2b`
> 审计人：AI coding agent（基于仓库源码、文档、测试、git 历史）

## 1. 范围与方法

- 阅读了 `README.md`、`docs/opencode-migration/*`、`pyproject.toml`、`package.json`、`desktop/package.json`、`.github`（无 workflows 目录）、CI/验证脚本布局。
- 检查了 `git diff --stat origin/main...HEAD`（37 files, 7583 insertions, 8 deletions）。
- 检查了 Electron 主进程 OpenCode 接入：`desktop/electron/main.ts`、`preload.ts`、`engineAdapter.ts`、`openCodeSupervisor.ts`、`engineSessionStore.ts`、`engineEventBridge.ts`、`openCodeEvents.ts`、`engineLease.ts`、`workspaceEngineLock.ts` 及对应测试。
- 检查了 Python Agent 执行入口：`agent/server/main.py`（`run_tool_turn`）、`agent/core/agent_loop.py`、`agent/core/orchestration.py`、`agent/core/unified_runtime.py`、`agent/core/task_runtime.py`、`agent/core/background.py`、`agent/core/execution.py`、`agent/core/model_routing.py`、`agent/core/model_catalog.py`、`agent/core/settings.py`、`agent/permissions/*`、`agent/llm/*`。
- 检查了现有测试/验证：`tests/test_engine_lease.py`、`desktop/electron/*opencode*test*`、`scripts/validation/opencode/*`、`scripts/validation/desktop-smoke.cjs`。
- 未运行破坏性命令；未修改用户未跟踪文件。

## 2. 当前架构快照

### 2.1 桌面层（保留目标）

- **Electron 主进程**：`desktop/electron/main.ts`（1617 行）。负责窗口、菜单、Agent 子进程 spawn、WebSocket 连接 Python Agent、IPC、更新、诊断、OpenCode 诊断 sidecar。
- **Preload**：`desktop/electron/preload.ts`（163 行）。暴露 `window.localAgent` IPC，包括 `runEngineDiagnostic`、`getEngineStatus`、`taskRequest`、settings/project/thread/chat 相关能力。
- **Renderer**：`desktop/src/App.tsx`（1947 行）+ components/lib。已有中文 UI、项目管理、聊天、Task/Plan/Git/Context/Diagnostics 面板、Settings。App 中已有 OpenCode 菜单项“OpenCode 隔离诊断”和引擎状态显示，但正式执行仍走旧 Python Agent。
- **打包**：`desktop/package.json` electron-builder 配置，win nsis+portable x64，`extraResources` 打包 `../build/agent-dist/lca-agent`。版本 `1.1.0`。

### 2.2 Python Agent 层（当前正式执行核心，待替换）

- **入口/传输**：Electron spawn Python agent（开发态 `.venv` python，打包态 `lca-agent`），通过本地 WebSocket `/ws` JSON 协议通信。`desktop/electron/main.ts` 含 `connectAgentWebSocket`、`sendAgentRequest`、pending request/stream 处理。
- **统一执行入口**：`agent/server/main.py` 的 `AgentServer.run_tool_turn(...)`（约 2402 行起），被 tests 广泛直接调用；也被 orchestration/background 调用。`agent/core/agent_loop.py` 提供工具循环/历史裁剪/guard 辅助。
- **运行时**：`agent/core/unified_runtime.py`、`task_runtime.py`、`orchestration.py`、`background.py`、`execution.py`、`verification.py`、`workflow*.py` 等组成复杂自主执行/验证/恢复体系。
- **模型/Provider**：`agent/llm/*`、`agent/core/model_catalog.py`、`model_routing.py`、`settings.py`。Settings/Provider/模型配置、凭证、路由、诊断逻辑主要在 Python + Electron Settings UI/IPC。
- **权限**：`agent/permissions/policy.py`、`authorization.py`，`agent/tools/*` 通过权限/审批执行。
- **持久化**：`agent/persistence/*`（SQLite）、项目/线程/消息/任务/检查点/记忆等。
- **非 Agent 但仍需评估保留的模块**：settings 存储/迁移、项目管理、数据迁移、备份、部分 diagnostics、MCP 设置持久化、凭证存储桥接等。P4 删除前必须逐项确认。

### 2.3 已有 OpenCode P1 基础（实验/诊断性质）

`origin/main...HEAD` 新增 OpenCode 基础设施，当前为 **fail-closed 诊断接入**：

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| `desktop/electron/openCodeSupervisor.ts` | 已实现（受限） | Windows sidecar 启动、固定 SHA256 校验、隔离 env、随机密码、`/api/info` 健康检查、只允许 `/api/info`、`/api/session`(deny-all)、`GET/interrupt session`、SSE `/api/event`。**硬编码二进制 hash=98cb0aa...，硬编码版本 2.2.6**。 |
| `desktop/electron/engineAdapter.ts` | 已实现（fail-closed） | `OpenCodeAdapter.send()` 抛出“security and budget gates pending”；`EngineRouter.run()` 拒绝非 legacy。 |
| `desktop/electron/engineEventBridge.ts` | 已实现 | SSE 读取、snapshot 对账、dedupe、断线重连重试、translated event。 |
| `desktop/electron/engineSessionStore.ts` | 已实现 | thread->engine/session binding，immutable，原子写。 |
| `desktop/electron/engineLease.ts` + `workspaceEngineLock.ts` | 已实现 | Electron 侧 lease/锁。Python 侧有 `agent/core/engine_lease.py`。 |
| `desktop/electron/main.ts` | 部分接入 | 有 `migrationSidecar`、`agent:engine-diagnostic` IPC、菜单项“OpenCode 隔离诊断”；正式聊天仍走 Python Agent WebSocket。 |
| `desktop/src/App.tsx` | 部分接入 | 有 OpenCode 诊断菜单、引擎状态展示；无正式 OpenCode 聊天路径。 |
| `scripts/validation/opencode/*` | 已有 P0/P1 脚本 | version-lock、p0-service/model/ollama-probe、package-lock。 |

## 3. 旧 Agent 执行入口清单（P4 删除候选）

### 3.1 明确的正式执行入口

- `agent/server/main.py:run_tool_turn` — 统一工具/聊天 turn 执行入口；大量 tests 直接调用。
- `agent/server/main.py` WebSocket 请求分发 — Electron 通过 WS 调用 chat/task/tool turn。
- `agent/core/agent_loop.py` — 历史裁剪、工具 payload 压缩、loop guard。
- `agent/core/unified_runtime.py` — unified runtime 计划/执行/恢复。
- `agent/core/orchestration.py` — 多角色/自主编排，调用 `server.run_tool_turn`。
- `agent/core/background.py` — 后台任务执行，受 engine lease 影响。
- `agent/core/task_runtime.py`、`workflow.py`、`workflow_delivery.py`、`verification.py` — 任务/工作流/验证执行。

### 3.2 旧模型调用与工具调度

- `agent/llm/*` — Provider 客户端、流式、tool calls。
- `agent/core/model_routing.py`、`model_catalog.py`、`budget.py` — 路由、预算、模型选择。
- `agent/tools/*` — 旧工具注册表和工具实现（filesystem/shell/git/desktop/mcp/processes 等）。
- `agent/permissions/*` — 审批与策略执行。

### 3.3 Electron 侧旧链路

- `desktop/electron/main.ts` 中 Python agent spawn/connect/reconnect/pending request/WebSocket message handling。
- `desktop/electron/preload.ts` 中 chat/task/diagnostics IPC（部分可保留外形，内部实现需切换）。
- Renderer 中依赖旧事件/状态形状的聊天与任务 UI。

## 4. OpenCode 实验/临时实现清单

- **正式产品不应保留的实验入口**：App 菜单“OpenCode 隔离诊断”；`agent:engine-diagnostic` IPC；`migrationSidecar` 诊断流程；手动选择 EXE 的诊断 UX。
- **临时限制**：`EngineRouter.run` 仅允许 legacy；`OpenCodeAdapter.send` 固定抛错；`openCodeSupervisor.request` 只允许 deny-all session/info/interrupt。
- **硬编码版本/哈希**：supervisor 内固定 `HASH` 和版本字符串 `2.2.6`；需改为可维护的版本锁/校验机制（仍固定版本，但不要散落魔法值）。
- **隔离配置**：supervisor 当前 `OPENCODE_CONFIG_CONTENT` 强制空 providers + deny provider.use；正式集成需替换为从 LCA Settings 生成的受控配置。
- **P0/P1 验证脚本**：`scripts/validation/opencode/*` 可保留为验证资产，但需区分“诊断脚本”与“正式产品路径”。

## 5. Settings/Provider/模型/凭证/权限/项目接口审计

### 5.1 Settings 与模型配置

- 现有 Settings 是用户可见配置来源（README/代码结构表明）。必须在 P2 保持 **Settings 单一事实来源**。
- 需要梳理：Electron settings IPC、Python settings/model catalog 持久化、renderer Settings 页面字段、凭证存储（Electron safeStorage / desktop secrets / env）。
- 风险：现有 OpenCode supervisor 完全绕过用户 Settings，使用空 provider 配置；正式接入必须把 LCA Provider 配置转换为 OpenCode 配置，并保留上下文长度/输出长度。

### 5.2 Provider/模型要求差距（对照用户任务）

| 要求 | 当前状态 | 差距 |
| --- | --- | --- |
| localhost Ollama | 旧 Agent 支持；OpenCode 正式未接入 | 需要生成 OpenCode provider/model 配置并验证 |
| 局域网 Ollama（192.168/10.x） | 旧 Agent/设置需确认；OpenCode 未接入 | 需要明确允许 LAN 地址并保留安全边界 |
| OpenAI Compatible | 旧 Agent 支持；OpenCode 未接入 | 需要配置转换与 API key 注入 |
| 复用 API Key/安全凭证 | 旧 Agent 有；OpenCode 未接入 | 需要安全注入，禁止落盘明文/日志泄露 |
| 模型列表/切换 | 旧 UI 有 | 需要映射到 OpenCode session/model 调用 |
| 上下文长度/最大输出长度 | 旧设置有 | 不得硬编码 2048；需透传到 OpenCode 配置/请求 |
| 连接测试/模型发现/错误诊断 | 旧设置部分有 | 需要覆盖 OpenCode 路径 |
| 额度耗尽停止，不自动切费模型 | 旧 runtime 有预算/路由逻辑 | OpenCode 路径必须强制预算/授权闸门 |
| Settings 修改后 OpenCode 加载最新配置 | 未实现 | 需要配置刷新/重启策略 |

### 5.3 权限

- 旧权限由 `agent/permissions/policy.py`、`authorization.py`、工具层审批实现。
- OpenCode 自身有 permission/session rules；P1 诊断使用 deny-all。正式接入必须映射 LCA 权限模式（Read Only/Workspace/Full Access）到 OpenCode 权限/审批策略，且不能伪造。
- FULL_ACCESS 已授权后不应重复普通文件/命令确认；受限模式保留约束。

### 5.4 项目/会话

- 现有项目管理、线程、历史、任务管理需保留。OpenCode session 需与 LCA thread/project 绑定（已有 `EngineSessionStore` 雏形，但仅诊断）。
- 需要明确：thread id、OpenCode session id、project root、worktree、engine lease 的生命周期。

## 6. 当前已知问题/风险（审计发现）

1. **正式执行仍是旧 Python Agent**。OpenCode 只在诊断 sidecar 中可启动；`send` 被禁用。
2. **双链路并存风险**。现有代码已有 legacy/opencode adapter/router 抽象，但 router 拒绝 opencode。P3/P4 需要收敛为单正式链路。
3. **OpenCode supervisor 过度受限且硬编码**。仅 Windows、固定 hash/版本、deny-all session、禁止 prompt route。这适合 P1 诊断，不适合正式产品。
4. **Settings 未接入 OpenCode**。用户已有模型配置无法驱动 OpenCode。
5. **UI 存在实验入口**。“OpenCode 隔离诊断”菜单是 P1 诊断能力，不应作为最终正式产品主入口；P3 要移除独立实验窗口/入口或转为内部诊断。
6. **版本目标不一致**。根/desktop/pyproject 目前 1.1.0；任务要求 v2.0.0。
7. **打包未包含 OpenCode runtime**。electron-builder 只 extraResources Python agent dist。
8. **测试基线有环境敏感项**。历史 P0 记录提到部分 Electron 集成测试在本机有 timeout；本轮验收中 `npm run agent:test` 会因 `tests/test_engine_lease.py` 被 unittest discover 导入 pytest 报错（命令级失败），但 pytest 单跑通过。
9. **desktop typecheck 曾有重复 import**。本轮验收中发现并已本地修复 `desktop/electron/main.ts` 重复导入；需提交并回归。
10. **无 `.github/workflows`**。需确认 CI 来源（可能在 GitHub 远端分支/历史有别处？本地未见 workflows 文件）；需检查远端 CI 配置。
11. **安全闸门未闭合**。P0 文档明确 MCP/权限矩阵/付费预算硬闸仍 BLOCKED。正式 OpenCode 执行前必须有明确策略与证据，不能假装通过。

## 7. P1-P5 缺口清单（按用户要求）

### P1 正式 OpenCode 服务集成
- [ ] 自动发现内置 OpenCode 可执行文件（打包/开发态）。
- [ ] 自动启动/关闭、随机回环端口、认证、健康检查、超时、异常退出检测、恢复、日志、进程树清理、防重复启动/孤儿进程。
- [ ] 版本/二进制完整性校验（可维护的 version lock）。
- [ ] 会话创建/查询/发送/取消/删除/恢复。
- [ ] 流式事件处理；区分请求受理与任务完成；任务完成后释放执行锁。
- [ ] 冲突任务防护。

### P2 复用原有 Settings/模型配置
- [ ] LCA Settings 作为唯一模型配置来源。
- [ ] Provider 配置转换为 OpenCode 配置。
- [ ] localhost/局域网 Ollama、OpenAI Compatible、在线模型连接。
- [ ] 复用 API Key/安全凭证存储。
- [ ] 模型列表/切换、上下文长度、最大输出长度透传。
- [ ] 连接测试/模型发现/错误诊断。
- [ ] 模型失败/认证失败/额度耗尽/超时处理；不自动切费模型；额度耗尽停止。
- [ ] API Key 不泄露。
- [ ] 无新增用户可见 OpenCode Settings；配置修改后 OpenCode 加载最新配置。

### P3 接管正式聊天窗口和工程执行
- [ ] 删除独立 OpenCode 对话实验窗口作为正式入口。
- [ ] OpenCode 接入原有主聊天窗口。
- [ ] 普通对话、多轮、流式、文件读写搜、Shell、Git、自动规划/开发/测试/修复、diff 展示、工具状态、取消、历史、恢复、工程切换、异常恢复、错误展示。
- [ ] 所有工程操作针对用户当前真实工程目录。
- [ ] 复用权限设置；FULL_ACCESS 已授权不重复普通确认。
- [ ] 普通对话和自主开发统一使用 OpenCode Agent。

### P4 删除旧 Agent 核心并整理
- [ ] 删除旧 Agent Loop、旧模型调用调度、旧工具调用调度、旧自主开发执行器、重复 Provider 路由/会话状态/权限判断、实验窗口/开关/阻断逻辑、无用 IPC/类型/Python 模块/临时测试/过时文档。
- [ ] 保留必要非 Agent Python 模块时不得继续承担正式 Agent 执行。
- [ ] 最终仅一套正式 Agent 执行链路。

### P5 Windows 打包和完整验收
- [ ] Windows Setup/Portable，内置 OpenCode Runtime，固定版本+SHA256，许可证声明，配置迁移，首次启动检查，安装/卸载/打包后运行验证。
- [ ] 版本 v2.0.0。
- [ ] 完成 30 项验收矩阵并记录真实结果。

## 8. 建议实施顺序（立即开始执行）

1. **P0 收尾**：提交本审计文档；修复已发现的 typecheck 重复 import；记录 agent:test pytest-import 问题处理策略（排除 pytest 文件或改 runner）。
2. **P1**：把 OpenCodeSupervisor 从“诊断受限”升级为“正式 runtime 管理器”；保留 version lock/checksum；实现配置注入、session/prompt/event/cancel/delete/recover；把执行锁释放绑定到终态。
3. **P2**：实现 Settings->OpenCode config translator；复用凭证；模型列表/切换/上下文/输出长度透传；连接测试与错误分类。
4. **P3**：在 Electron 主进程建立 OpenCode-backed chat/task execution service，替换 `run_tool_turn` WS 调用路径；适配 renderer 现有消息/工具/计划/审批事件。
5. **P4**：移除旧执行链路和实验 UI；清理 Python/TS 死代码与测试。
6. **P5**：打包 OpenCode runtime、升级版本、更新文档、跑 CI/验收、更新 PR。

## 9. 审计结论

当前分支已有 P1 诊断级 OpenCode 基础设施，但**距离“正式替换 Agent 核心”还有显著缺口**：OpenCode 不能执行正式 prompt，Settings 未映射，主聊天仍走 Python Agent，打包未内置 OpenCode，旧 Agent 执行链路完整存在。可以在此分支上继续演进，但必须按 P1-P5 逐步替换并保持可验证，不得伪造通过。
