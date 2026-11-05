# v0.8.0 智能模型与项目上下文验收报告

日期：2026-11-05（Asia/Shanghai）。范围仅 v0.8，不进入 v0.9，不创建 Release、Tag 或安装包。

## 结论与 Git 门禁

功能与必需真实场景验收：**PASS**。最终提交必须通过双平台 CI 才可合并；不把历史失败、Mock、跳过或模型调用前退出计为通过。

- 基础 main：`00954ecd921c28823764e02e3a2d91b3c2720454`，开发前已 fetch，交付前再次确认没有更早或更新基线被覆盖。
- 分支：`feature/v0.8-intelligent-context`。PR：[#31](https://github.com/yunfei00/local-coding-agent/pull/31)。分支最终 SHA 由 PR HEAD 提供，本文件不预写自身提交的自引用 SHA。
- 已验证实现提交：`d2153f37b0e959d959cac3847be553dd6aa52309`；随后补充工程问答的只读路由兜底及 SQL 故障回归，均有本机验证。
- 已完成双平台 CI：[41999594128](https://github.com/yunfei00/local-coding-agent/actions/runs/41999594128)，Windows/Ubuntu 均成功。最终报告所在提交仍以 [PR Checks](https://github.com/yunfei00/local-coding-agent/pull/31/checks) 实际结果为门禁。
- 合并 SHA、最终主线 CI 以 PR 的合并事件和最终交付消息为准；报告入库时不能预填尚未生成的合并 SHA。没有直接开发 main、reset、clean、强推或删除历史数据。

## 环境与证据边界

Windows 11、16 GB 内存、CPU 环境；Agent 使用 uv 管理的 Python 3.12，Node/Electron 使用项目锁定依赖。隔离依赖工程可以使用已安装的 Python 3.13，明确禁止自动下载 Python。测试串行，最多一个受控 LCA 桌面实例；必要的 Electron 目标应用仅在 GUI 用例内启动和清理。实际测试前可用内存约 4.1–5.8 GiB；非分页池约 2.1–3.3 GiB。未修改系统虚拟内存，未结束用户程序。

早期桌面锁定造成真实焦点测试失败/跳过及 Smoke 阻断，证据保留。解锁后完整 Electron Smoke 55 检查通过，真实视觉用例也通过；当前本机完整 Python 回归仅 2 项平台契约跳过，没有用早期跳过充当 GUI PASS。

所有在线任务通过原 Electron IPC、聊天框和统一 Agent 入口提交。Codex 只准备隔离工程、冻结原始测试/验证配置、驱动 UI 并独立检查；业务 Bug 和新增文件由 Local Coding Agent 实际修改。API Key 沿用 OS 安全存储，只在内存使用，未写入代码、报告或索引。未连接、安装或下载 Ollama。

## 六个模块

| 模块 | 交付与复用 | 验收证据 |
| --- | --- | --- |
| M1 智能模型路由 | 扩展 ModelCatalog 的能力三态、配置指纹/有效期、可用性与成功证据；自动/手动、明确回退授权、有界轮换；原 Provider 和请求账本保留 | 路由/HTTP Mock/冻结配置回归；真实 A→B 切换；普通问答、代码、视觉及工程问答能力选择 |
| M2 项目记忆 | 原 SQLite 版本 6，项目隔离、事务、修订、来源哈希、过期、去重、CRUD、自动开关；明确用户约定原文保存 | 新会话/应用重启真实读取 unittest 与中文交付约定；Electron CRUD；真实 SQL 写失败后旧值保留并可恢复写入 |
| M3 工程检索 | 复用 RepositoryMap/文件读取边界，增量内容/文件名/符号索引、真实行号和来源，无 Embedding | mathcore 跨文件真实缺陷定位与修复；忽略/链接/凭据/大文件/删除/索引损坏回归 |
| M4 上下文连续性 | 原 ContextBudgetManager、RuntimeLedger、Checkpoint、计划与循环保护；有界知识分区、压缩阈值、阶段/工具预算 | 长历史压缩；模型切换保留已执行修改；真实 Stop/Resume 与 WebSocket 重连；完成步骤保持 |
| M5 环境诊断 | 原 ProcessManager 与审批；只读 Git/npm/Electron/uv/Python/Provider 检查，批准后项目级修复、实际复查与历史知识 | 隔离 Git PATH、不可用 npm 代理、本地 Python 依赖三类真实故障均通过；全局安装/代理/缓存操作不自动执行 |
| M6 可观测性 | 原 Context、Settings 与进度卡内增加模型证据、选择原因、记忆、检索、压缩、预算与恢复；不增加开发模式 | 前端 65 项、Electron Smoke 55 检查；聊天输入与既有 Git/Context/诊断继续可用 |

旧入口保持原预算与请求开销；统一入口默认启用知识能力。Worktree 项目会话不沿用主目录知识缓存，批准的项目 PATH 在打开工程和新建 Git 进程时恢复。现有 Task Plans、审批、MCP、Pinned Files、Git 和 v0.7 Computer Agent 没有平行重写。

## 自动化结果

| 检查 | 实际结果 | 日志/说明 |
| --- | --- | --- |
| 本机最终完整 Python | **625 项：623 PASS、2 SKIP、0 FAIL/ERROR** | `validation-reports/20261105-194856-027847.log`，833.399 秒 |
| 额外 SQL 存储故障测试 | **1 PASS** | `v08-sql-fault-final.log`，完整回归启动后新增，未重复计入 625 |
| 当前唯一 Python 用例合计 | **626 项：624 PASS、2 SKIP** | 最终提交 CI 应执行整个目录，以实际 Checks 为准 |
| 新增核心测试 | 59 项，含知识/路由/环境/原 Runtime HTTP Mock | 57 项批次通过，工程问答包含在最终完整回归，新增 SQL 单项另行通过 |
| 前端 | **65 PASS，0 FAIL** | 19 文件；完整 check.py 运行结果 |
| TypeScript / Electron 构建 | **PASS** | check.py 四阶段退出码均为 0，Errors: 0 |
| Electron Smoke | **55 检查 PASS，0 SKIP** | `v08-desktop-smoke-unlocked.log` / `desktop-smoke.json`；含真实桌面、HTTP Mock 决策和实际测试执行，不能算作付费在线模型结果 |
| GUI 驱动保护 | **4 PASS** | `v08-live-driver-guard-final.log` |
| 已完成 Windows CI | 624 项：622 PASS、2 SKIP；65 前端、Smoke 与构建成功 | 实现提交 d2153f3，run 41999594128；不与最终两项新增用例混算 |
| 已完成 Ubuntu CI | 624 项：607 PASS、17 SKIP；65 前端与构建成功 | Windows 原生 GUI 不适用于 Ubuntu，17 SKIP 不算 PASS |

Mock 仅用于可重复的额度、429/超时/网络、能力不足、禁止模型、快照、工具重复保护等错误分支；测试不需要真实 API。真实模型场景单列如下。

## 真实工程与模型结果

| 场景 | 最后有效结果 | 实际模型及证据目录 |
| --- | --- | --- |
| A 工程理解、项目知识保存 | PASS，无源码修改 | qwen3.8-2.4t-a95b；`v08-real-memory-literal` |
| A 关闭应用后新会话读取规则 | PASS，命中 3 条记忆，恢复 unittest 与中文交付要求 | qwen3.8-2.4t-a95b；`v08-real-memory-reopen-literal` |
| B 跨文件缺陷、真实 unittest/Diff | PASS，原测试保留，mathcore.py 实际修复 | qwen3.8-2.4t-a95b；`v08-real-projects` / knowledge-fix |
| C 自动能力选择和故障回退 | PASS，A 修改后切换 B；只有一次成功源码修改 | qwen3.8-2.4t-a95b → qwen3.8-27b；`v08-real-routing-recovery` / routing |
| D npm 代理故障 | PASS，经审批只移除项目代理，复查通过 | qwen3.8-2.4t-a95b；`v08-real-projects` / environment-repair |
| D Git PATH 故障 | PASS，只改测试应用进程/项目子进程 PATH，真实 git_status 与 unittest 成功 | qwen3.8-27b；`v08-real-git-environment` |
| D Python 依赖缺失 | PASS，Agent 经审批执行 uv sync；监督端 no-sync 导入成功，源码/声明冻结，Git 干净 | qwen3.8-27b；`v08-real-python-environment-repair` |
| E 长历史压缩 | PASS，保留当前目标，未改文件 | qwen3.8-2.4t-a95b；`v08-real-memory-repair` / context |
| E 中断后安全继续 | PASS，第一步已完成 ID 保留，第二步完成，独立测试与 Diff 成功 | qwen3.8-2.4t-a95b；`v08-real-interruption-isolated`，17 次请求、205020 Token 预留/用量混合值含估算，不能当作精确实际计费 |
| E WebSocket 断开恢复 | PASS，实际断开、重新连接、暂停并恢复原运行 | qwen3.8-27b；`v08-real-routing-recovery` / websocket |
| F v0.7 Computer Agent 回归 | PASS，真实窗口/UIA失败/图片请求/坐标点击/实际结果验证/停止清理 | qwen3.8-max-0902；`v08-real-visual-repair`，16 请求、177343 服务端 Token |
| 工程文件的解释型问答 | PASS，自动选择工具模型、实际读取源码、只读分析 | qwen3.8-27b；`v08-real-workspace-question`，3 请求、15033 Token |

三个模型均通过真实文本/工具探测；max-0902 另通过随机图片挑战与实际窗口视觉验收。其它模型的视觉能力不臆测为支持。上下文 65536 是本轮隔离配置，不代表已核实 Provider 最大窗口。qwen3.8-flash、qwen3.7-plus 及变体零生成/探针请求，未修改原模型目录或密钥。

C 的额度错误是**一次受控 HTTP 403 注入**，前后 A/B 模型均真实在线；不是声称实际耗尽了阿里免费额度。没有为测试故意烧完配额。模型断网/限流/实际超时分别保留分类，不通过无限重试掩盖。

## 历史失败与修复

1. 首轮完整 Python：613 项中 594 PASS、15 FAIL、2 ERROR、2 SKIP。长编排反馈超出 500 字符搜索限制，以及新工具/上下文挤占旧入口小预算。修复查询有界化和旧入口兼容；受影响回归 144 PASS/6 桌面锁定 SKIP，随后完整回归无失败。
2. 工程理解被“不修改代码”中的“修改”误判成开发；仅 GUI 操作被“不得修改文件”误判成只读分析。修复不同边界，真实理解和视觉复测均通过。
3. 新会话记住测试框架却遗漏中文交付规则。用户明确“记住：”按原文保存为 user；代码块和 Markdown 引用不作为可信授权，敏感内容拒绝保存。真实应用重启复测通过。
4. Windows 连续探针时间戳相同，旧成功证据掩盖新失败；改用完整探针内容摘要标识版本，固定同时间戳的回归通过。失败 CI run 41996092914 保留，修复后的双平台 run 41999594128 成功。
5. Git 修复仅覆盖旧 ProcessManager，新增 Git 进程未继承项目 PATH；修复 Workspace/新进程/重启恢复，清空 PATH 的实际 Git 测试与在线用例通过。
6. 依赖安装生成 `.egg-info` 被误算成业务变更。自动源码快照和索引排除标准依赖元数据；验证 fixture 正常忽略生成目录，仍冻结 pyproject、uv.lock、vendor 源文件与原测试。在线复测通过，未降低断言。
7. 27b 的一次中断恢复请求超过 60 秒，在候选池已被前一个受控额度测试停用 A 的情况下停止。文件和完成步骤保留，未伪造成功；独立测试使用另一已验证模型及 120 秒请求上限后通过。原失败仍列为 FAIL，WebSocket 用例继续由 27b 真实通过。

共 18 条真实场景执行记录：13 PASS、5 历史 FAIL。最终 12 类场景均有 PASS，不把历史 FAIL 改写为 PASS。完整本地原件及哈希见 [脱敏证据索引](evidence-summary.json)。

## 请求、Token 与隐私

按唯一运行 ID 去重：Runtime HTTP 尝试 114，独立能力探针 11，其中受控故障响应 1 不到阿里上游；生成请求尝试上界 124，不含 /models GET。取消时发送状态不明的尝试仍计入上界，不从预算预留反推精确 HTTP 成功数。

Provider 已报告输入 1067313、输出 59545，合计 **1126858 Token**；缓存输入子集 273664 已包含在输入中，不能再次相加。有 4 个运行含取消/失败后未知 Usage 或估算预留，费用未知，不把预留或返回的默认 0 当成真实零费用。

所有验证使用有限请求/时间/Token 上限，原用户 Settings 未改。数据、配置和预算快照沿用原持久化；没有从任务恢复清零预算，也没有通过自动换模型绕过预算。

## 核心文件与文档

- 路由：`agent/core/model_routing.py`，扩展原 Catalog、ModelDiagnostics、Provider 与 AgentServer。
- 知识：`project_files.py`、`project_knowledge.py`、`tools/knowledge.py`、SQLiteStore 和 RepositoryMap。
- 连续性：`context.py`、`execution.py`、`unified_runtime.py`、原 orchestration/Checkpoint。
- 环境：`environment_diagnostics.py`、`tools/environment.py`、ProcessManager、Git 工具和项目会话。
- UI：原 App/Context/UnifiedProgress 与新增 ProjectKnowledgePanel、ModelCapabilitySummary；Electron 原 IPC 适配。
- 测试：四个 test_v08 模块、原迁移测试、桌面 Smoke、原真实验收驱动。没有删除旧测试或改变 manual-fixtures 路径。

v0.8 十份中文文档、README、统一架构、能力矩阵和使用/测试说明已更新。公司源码部署与可复制验证命令见 [implementation.md](implementation.md)。

## 已知边界

- 不提供语义向量搜索、通用语义矛盾证明或完整 DLP；使用可解释关键词/符号索引、标题/来源冲突、用户确认和保守敏感内容过滤。当前代码事实优先，模型候选不能覆盖可信记录。
- 物理 SQLite 损坏不会自动删除重建用户数据；派生索引损坏可重建，主数据故障需保留原件后恢复备份。
- 请求超时、真实额度耗尽或全部候选不可用仍会保存状态并停止，不能承诺模型一定完成任意任务。未核实的价格、最大窗口与能力保持未知。
- GUI 需要解锁桌面与可用资源；本轮没有刻意压至 1 GiB 以下运行，高压门禁用无服务测试验证。未测试公司真实网络、代理与网关，不能将家庭环境结果冒称公司 PASS。
- 本轮仅源码交付，不生成安装版/Portable/Release/Tag；Ollama 保留但未真实测试。
