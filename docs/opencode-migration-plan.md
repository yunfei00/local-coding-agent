# OpenCode Agent 引擎迁移开发计划（P0–P5）

> 状态：设计已批准，尚未实施。目标：以 OpenCode 替换 Local Coding Agent 的通用 Agent 核心，保留 Windows Electron 产品与专用工具。本文为 Codex 的唯一阶段实施入口。
>
> **固定基线：OpenCode `v2.2.6`**（官方 Release：2026-11-06；Git tag `v2.2.6`）。禁止使用 `latest` 或 `dev` 作为可复现基线。P0 必须解析该 tag 的完整 commit SHA，记录 Windows x64 发行物 SHA256、SDK 实际版本及锁文件；不得自行假定 CLI 与 SDK 版本号相同。任何升级须单独评审、测试。
>
> 本项目基线：Local Coding Agent `main`，启动时记录完整 commit SHA。工作仅在**一个**开发分支 `feature/opencode-engine-migration` 进行；阶段之间继续使用同一分支。每阶段 CI 全绿才进入下一阶段；全部验收通过后才申请合并 main。不得自行发布 Release。

## 0. 目标、非目标、约束

**目标**：Windows 10/11 x64 Setup/Portable 离线可启动（模型可本地 Ollama），Electron + React + TS 界面不重写；OpenCode 负责通用会话、模型、工具循环、上下文、Git/文件/Shell；现有 Python 服务保留 Windows GUI、Office、独立验证等差异化能力。保持历史项目/会话可读、原引擎可回退、用户授权语义与隐私边界。

**非目标**：Fork OpenCode、复制其核心源码到 Python、重写 UI、修改 OpenCode 上游、一次性删除旧 Agent、保证本地模型能力等同云端模型。

**不可妥协**：
- 一个任务只允许一个执行引擎；双引擎不得同时操作同一工作目录/工作树。
- 用户当前明确授权才允许 commit/push/发布；不得覆盖无关未提交修改。
- FULL_ACCESS 一次确认后普通操作无需重复审批，但高风险（递归删除、force push、系统修改、凭据读取/外传、UAC/锁屏等）继续限制。撤销授权立即影响新操作。
- 不能仅在 Python ToolRegistry 限权：OpenCode 自带文件/Shell 工具同样必须受控。权限失配时 fail closed，不以 Prompt 代替强制校验。
- 不泄露 API Key、Prompt、工程文件正文到诊断日志；本地服务仅 loopback、随机鉴权，禁止开放无认证 HTTP 服务。
- 所有真实在线模型调用必须显式启用并设请求数/Token/时间硬上限；额度耗尽即停止。默认测试不花费在线额度。
- 不因进程重启重复执行有副作用操作；不确定状态标为待人工确认，不能自动重放。
- CI Mock 与真实模型验收分别记录，不以 Mock PASS 冒充实机 PASS。
- 先运行现有基线测试并保存证据，不以迁移为由放宽或删除原测试。

## 1. 已知源码边界（实施前再核验）

Local Coding Agent：
- `agent/server/main.py`：`AgentServer.run_tool_turn` 与 WebSocket 统一入口。
- `agent/core/execution.py`：ExecutionBudget、执行/恢复元数据。
- `agent/core/workflow.py`：DAG 与角色策略，不是独立 Agent Loop。
- `agent/permissions/policy.py`、`agent/permissions/authorization.py`：权限与授权。
- `docs/UNIFIED_AGENT_RUNTIME_ARCHITECTURE.md`、`docs/v0.9/architecture.md`、`docs/v1.0/permission-model.md`：现有契约。
- `desktop/`：Electron 主进程、preload、React；需实际定位启动、IPC、事件与配置文件，不得凭空指定函数名。
- `scripts/validation/` 与 `tests/`：回归与真实验收。

OpenCode v2.2.6：
- `packages/core/src/session/session.ts`：Session 接口。
- `packages/core/src/session/prompt.ts`：Prompt 准备、附件与插件 hook。
- `packages/core/src/session/execution.ts`、`inbox.ts`、`store.ts`：执行、消息队列、持久化；须核验接口和行为。
- SDK、Server、Permission、MCP 的准确入口须从固定 tag 源码/生成类型/文档核验。**禁止混用 v1 SDK 示例与 v2 API**。
- 上游仓库：https://github.com/anomalyco/opencode；固定版本：https://github.com/anomalyco/opencode/releases/tag/v2.2.6
- 许可证：MIT；打包时保留原许可证和版权声明，产品文档注明非 OpenCode 官方产品。

## 2. 目标架构

```text
Electron Renderer (现有中文 UI)
    -> preload / IPC (不暴露 Key、任意 URL)
    -> Electron Main: EngineSupervisor + EngineAdapter
         |-> OpenCode v2.2.6 Windows x64 sidecar (本地鉴权 HTTP/事件)
         |       -> Session/Model/Agent/内置工具/权限
         |       -> MCP/Plugin bridge -> Python 专用工具服务
         |-> Legacy Python Agent（过渡回退；不与 OpenCode 同任务并发）
    -> 现有项目/历史 SQLite（只读旧记录 + 新 ID 映射）
    -> 原独立验证器/执行审计/预算外部硬闸
```

新增抽象建议：`AgentEngine`（create/resume/send/cancel/status/events/permissions）、`OpenCodeAdapter`、`LegacyAdapter`、`EngineSupervisor`、`SessionMapping`、`EventTranslator`、`PermissionBridge`、`ToolBridge`。具体文件名以代码风格为准。不要让 renderer 直接连接 OpenCode 服务；主进程托管、鉴权、事件转发与进程回收。

**数据原则**：保留旧 SQLite 与原任务，不强行转换历史 Checkpoint 为 OpenCode Session；新建映射 `local_thread_id / engine / opencode_session_id / project_root / version / created_at`。新旧引擎的 Session 不共享可变执行状态；旧任务由旧引擎恢复。重启后先核对远端 Session/执行状态再允许继续。

**预算原则**：OpenCode usage 用于显示/结算；外部独立执行闸负责调用次数、Token 预留、时间和付费额度，超限阻断后续请求。不能只靠事后统计；如上游无可拦截的前置模型请求接口，必须记录风险并在 P0 判定阻断，提出可执行替代方案。

## 3. P0：固定版本与可行性验证（必须先过）

交付：`docs/opencode-migration/p0-interface-audit.md`、`docs/opencode-migration/version-lock.md`、独立 Windows POC（隔离目录）、`docs/opencode-migration/p0-results.md`。

工作：
1. 核验 OpenCode v2.2.6 tag 完整 SHA、MIT、Windows x64 CLI/sidecar、SHA256、可复现下载/离线启动；核对 SDK 兼容版本及锁定方式。若 v2.2.6 无可用 Windows 发行物，明确 BLOCKED，禁止偷偷换版本。
2. 阅读固定 tag 的 Session、Server、SDK、事件、Permission、MCP、Provider、取消/恢复/配置源码，制作“实际函数/端点/参数/事件/异常/链接”表。
3. Windows POC：由 Node/Electron main 测试进程启动本地服务、健康检查、鉴权、Session 新建/发送/流式事件/取消/重连/退出、异常进程回收、端口占用。
4. Ollama 测试 `gemma4:31b` 与 `gpt-oss:20b`（存在才执行，缺失记 SKIP），各跑纯问答、读文件、修改临时文件、命令执行、失败恢复；明确模型调用格式、上下文限制。
5. 验证可否对 OpenCode **内置**文件/Shell 工具强制权限、运行中撤销、危险命令拒绝；验证 MCP 工具权限和取消。测试绕过路径，不接受仅靠提示词。
6. 验证可否在每次付费请求之前强制预算硬闸；不能证明则 BLOCKED。
7. POC 不改正式 Agent 逻辑，不污染用户 OpenCode 全局配置；配置、缓存、数据库、端口隔离。

**P0 Gate**：真实 Windows Session/流式/取消/恢复/鉴权/权限/预算硬闸均有证据；任何安全或预算阻断未解决，不得进入 P1。

## 4. P1：适配层与双引擎

交付：EngineAdapter 接口、OpenCode sidecar 进程管理、持久 ID 映射、统一事件模型、选择开关、单任务引擎锁及回退测试。

- 仅新任务可选 OpenCode；默认仍为旧引擎，待 P5 再切换默认。
- 事件至少映射：started, text_delta, reasoning/status（遵守隐私）, tool_started, tool_result, permission_requested, usage, completed, failed, cancelled, disconnected。
- UI 现有 Chat/Task 的状态、Diff、诊断保持可用；断线重连不重复发 Prompt；事件按 ID 去重。
- 进程退出、应用关闭、升级/卸载、异常终止时清理本应用拥有的子进程，不杀用户已有 OpenCode 进程。
- **Gate**：新旧引擎隔离，取消与重连稳定；现有回归 CI 全绿。

## 5. P2：通用编程功能迁移

交付：OpenCode 新会话支持模型选择、问答、读取/搜索、编辑/Patch、Shell、Git status/diff、自动验证和结果展示。

- OpenCode 内置工具为唯一通用工具执行者；禁止重复转发同一 Shell/File 操作给 Python。
- 现有 VerificationEngine 作为独立结果核验，不把模型自称成功当成功。
- 维持工作区边界、原有 Worktree 策略；不覆盖用户修改，不自动提交/推送。
- 新任务保存模型/Provider 解析快照，API Key 不进入 SQLite 或前端。
- **Gate**：标准代码工程任务三次重复验收，实际文件与测试证据一致；失败可解释。

## 6. P3：权限与 Python 差异化工具

交付：PermissionBridge、ToolBridge、Windows GUI、Office、MCP 接入与专项安全回归。

- 映射 READ_ONLY / WORKSPACE / FULL_ACCESS，优先级任务 > 项目 > 全局；一次确认授权；撤销立即生效。
- 对 OpenCode 内置工具和 Python 扩展工具均强制执行；高风险操作始终独立判断。
- Python GUI/Office 通过已验证的 MCP/插件接口暴露，严格参数 Schema、超时、取消、错误分类；窗口绑定、UAC/锁屏与截图限制保留。
- 原 Office 工具自身错误不能算引擎修复，必须独立真实生成 Word/Excel/PPT 并打开回读。
- **Gate**：越权 0、重复副作用 0、GUI/Office 回归达标、CI 全绿。

## 7. P4：可靠性、数据与 Windows 打包

交付：Setup/Portable 内置 OpenCode sidecar、安装升级与回滚、会话恢复、审计与诊断。

- Windows 干净环境不需要另装 Node/Bun/Python/Git 才能启动软件（Git 相关能力可清楚提示受限）。
- 安装包携带 OpenCode 版本与 MIT LICENSE；SHA256、文件来源、第三方依赖清单。
- 旧历史只读可查；旧任务仍用旧引擎恢复；新任务持久映射；断电/重启时不自动重放未知副作用。
- 并发/超时/预算/取消/退出清理与敏感数据脱敏测试。
- **Gate**：Windows Setup 与 Portable 真实安装、重启恢复、权限与数据回归通过。

## 8. P5：A/B 验收、默认引擎与发布决策

交付：`docs/opencode-migration/final-acceptance.md`、中文 A/B 报告、发布/回退决策。

- 旧 Agent vs OpenCode：同一模型、同一工程初始快照、同一 Prompt、同等权限和预算，每任务至少三轮；分别统计成功、验证、Token、耗时、错误、重复副作用。
- 测试矩阵：问答/读取、单文件修复、多文件工程、Git、终端、长任务/上下文、取消/重连、权限、Windows GUI、Office、无 Git 工程。
- 必须包含历史失败：无正文/工具调用、Office 参数 TypeError、Office sheets 错误、显示成功但文件未生成、重复执行与取消后残留。
- 目标：通用编程成功率不低于旧引擎，目标 ≥90%；越权 0、重复副作用 0；专用能力不退化。成功须由独立断言证明。
- 通过后才将**新任务**默认引擎改为 OpenCode；旧引擎保留至少一个稳定发布周期，不在本轮删除。
- 任何 Gate 失败则保留 Legacy 默认，输出 BLOCKED 原因和最小修复建议；不伪造通过、不无限循环尝试。

## 9. Codex 执行约定

1. 从 `main` 创建唯一分支 `feature/opencode-engine-migration`（已存在则复用，不覆盖用户工作）。按 P0→P5 顺序执行，每阶段生成文档、代码、测试、验收证据和 commit。
2. 每阶段先定位真实源码，再实现最小修改；禁止假设接口、跳过权限检查或大规模无关重构。
3. 每次修改后运行 Python 单测、Electron typecheck/test/build、相关 smoke、Windows 真实测试；检查 GitHub Actions，CI 不绿先修复，不能进入下一阶段。
4. P0 若遇到安全/预算/发行物硬阻断，停止后续阶段并报告；不以 Mock 替代。
5. 真实付费 API 默认禁用；可用本地 Ollama 做真实验证。用户未明确授权的远程额度调用禁止。
6. 最终提供：固定上游版本与 SHA、逐阶段 commit、变更文件、PASS/FAIL/SKIP、测试命令与证据、遗留问题、PR 链接。不要自行合并 main 或发布。

## 10. 推荐命令（Codex 根据系统实际环境执行）

```powershell
git switch main
git pull --ff-only
git switch -c feature/opencode-engine-migration
uv run --locked python -m unittest discover -s tests -v
npm run desktop:typecheck
npm run desktop:test
npm run desktop:build
```

如分支已存在，不重复创建；先检查未提交文件，禁止强制清理。Windows 实机与 GitHub CI 均为合并门禁。
