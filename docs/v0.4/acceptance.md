# v0.4 混合模型协同验收

日期：2026-10-22。延续 feature/v0.4-local-first-agent，保留全部已有 v0.4 历史，合入 main 的 v0.3 正式发布文档；没有重建分支或清理用户文件。

交付状态：全部门禁通过，[PR #3](https://github.com/yunfei00/local-coding-agent/pull/3) 已以 merge 方式合并 main，提交 `1424f99a746bfa7736554a20bacc4be007902ba8`。`v0.4.0` Tag 指向该提交；[正式 Release](https://github.com/yunfei00/local-coding-agent/releases/tag/v0.4.0) 已于 2026-10-22 发布并设为 Latest，非 Draft、非 Prerelease。

## 根因与交付

原 RuntimeSettings 同时保存两类服务参数，但 Settings/model.list 只使用活动 Provider；角色只包含 local/api + model 字符串，无法表达多个同类型端点。并非只需更改下拉框。

现已分离 Connections / Profiles / Role Bindings，通过原 Router 与原 Provider 客户端真实调用。模型配置 ID 和连接 ID 消除同名冲突；默认 Local-first，可跨服务绑定四角色；Local-only/API-only 请求前校验类型，不静默替换收费模型。任务冻结解析后的角色、地址、模型参数和任务/全局预算；显式暂停配置或追加额度才更新快照，Usage 不清零。

复用 v0.3 Agent Loop、Task Plans、Checkpoints、Execution Journal、Approval、PermissionPolicy、Git Worktree、工具执行和进程树终止，复用 v0.4 BudgetGuard 与 VerificationEngine。新目录是配置扩展，没有第二套循环或状态机。

## 测试证据

| 检查 | 已取得结果 |
| --- | --- |
| 修改前基线 | 197 Python、32 Desktop，类型检查和构建通过，运行 20261022-103939-436505 |
| 中间完整回归 | 212 Python、32 Desktop，通过，运行 20261022-105008-630003 |
| 混合 HTTP 专项 | 19 项通过，validation-reports/mixed-provider-final-budget.log；已包括人工追加全局额度和单字段隔离回归 |
| Windows Electron | 18 项通过、0 跳过，validation-reports/mixed-provider-ui-final.log |
| 本机 Windows 完整构建 | 216 Python、32 Desktop、18 UI，11/11 阶段通过，.codex-v04-mixed-package-final.log（运行代码 0809369） |
| 最终运行代码 CI | f3a71dd；[Windows / Ubuntu CI](https://github.com/yunfei00/local-coding-agent/actions/runs/39715042904) 全通过 |
| 最终 Windows 候选包 | [39715039804](https://github.com/yunfei00/local-coding-agent/actions/runs/39715039804)，全部构建/启动检查通过，产物已上传 |
| 合并前最终文档提交 CI | 61d3172；[39715216855](https://github.com/yunfei00/local-coding-agent/actions/runs/39715216855) 与 [39715213073](https://github.com/yunfei00/local-coding-agent/actions/runs/39715213073) 全通过 |
| 正式发布构建 | [Release Windows 39715636791](https://github.com/yunfei00/local-coding-agent/actions/runs/39715636791)，216 Python、32 Desktop、18 UI，安装版/Portable 检查及发布成功 |

本机已验证解包版、Portable、Setup 静默安装后启动及清理、SHA256 复算。随后将全局额度的单字段更新收窄为仅修改显式传入字段，最终代码 f3a71dd 的专项、远端 CI、Windows Candidate 及正式发布构建全部通过。合并前已确认最终文档提交与该代码在运行文件、测试和构建配置上没有差异。

## 正式发布文件

| 文件 | 字节数 | SHA256 |
| --- | ---: | --- |
| Local-Coding-Agent-0.4.0-x64-Setup.exe | 114128920 | 93c9610a1e6af50a9d4fce2ad86f14f0dcd0bd013bdf4a4bb498669a9a1a1352 |
| Local-Coding-Agent-0.4.0-x64-Portable.exe | 113898909 | 69e55c730b3846a275d8f70680e70e89423c97d5777d20a6eeca280d233d23dd |

另有 `SHA256SUMS.txt`。三个 GitHub assets 的 state 均为 uploaded；已下载校验文件并逐项与 GitHub 上传摘要比对一致，Latest API 确认 v0.4.0。本机早先构建与正式远端构建的二进制不要求字节一致，以正式 Release 校验文件为准。

核心新增测试在 tests/test_mixed_provider.py，使用四个真正监听 HTTP 的独立 Mock 连接与原客户端，包含两个 Ollama、两个 API，同名模型、四角色独立解析、指定 API Reviewer、指定 Escalation、诊断后回到本地、真实文件修改和独立 unittest、Local-only、API-only、零调用、Token 不足、429、超时、不可用服务、LAN 分类、迁移幂等/损坏保留、共享模型参数保留、运行中修改 Settings 和 Checkpoint 恢复。

原回归继续验证 Git Worktree 不覆盖源文件、审批与权限、执行去重、多文件计划、Stop 终止真实后代进程。新增人工追加全局额度测试验证快照显式更新且账本不重置。

Windows UI 自动化实际打开 Settings，添加连接、手动添加两个本地与两个 API 模型、四个不同角色选择、保存安全凭据、重启、重新测试 API Authorization。之后本地任务零 API 完成真实 Patch/验证/报告审批，Git/Context/Plan/Diagnostics 打开时仍可发送，Stop、主题、会话、剪贴板及重启检查通过。截图：validation-reports/desktop-mixed-provider-settings.png。

## 真实模型与 API 边界

实际执行：

~~~powershell
uv run python scripts/validation/v04_model_smoke.py --mode ollama --model qwen2.5-coder:1.5b --seconds 120
~~~

报告：validation-reports/v04-ollama-20261022-105120/result.json。本机 CPU 模型通过新 Profile → Connection 解析完成规划与实际工具调用；本地请求 3 次、API 0 次，但未修复 calculator，独立测试失败后按 Local-only 限制暂停。脚本返回失败，没有把任务标 completed。基础连通性及路由有效，不代表小模型复杂编程能力通过。

真实付费 API 未调用，未验收实际网关计费、认证、公司代理与业务模型能力。HTTP Mock 验证实际客户端、端点、Authorization、输入/输出/缓存 Usage 与预算预留；这些数字不冒充真实消费。按本次任务要求，自动化无需真实收费 API，CPU 小模型只承担基础连通性验证。公司实际业务能力需按 [公司验证流程](company-validation.md) 单独记录。

## 代码审查与限制

已检查连接/模型/角色解析、目录幂等迁移、密钥引用及诊断脱敏、请求前预算、策略拒绝、快照与恢复、环境失败不升级、模型诊断无工具权限、独立测试完成门禁、原 Git 与审批链路。

审查修复了共享模型迁移时角色输出/上下文/价格差异的保留，以及人工增加全局预算后旧快照仍受原限额的问题。模型与预算身份均来自服务端账本，UI 不伪造调用记录。页面显示最近 1000 次实际调用；完整请求记录仍在 SQLite。

限制：Provider Tokenizer/计费可能与保守预留不同；费用上限需用户配置真实价格，供应商不遵守输出限制时仍需网关侧限额。错误类别为启发式。OS 安全存储不可用时密钥仅会话有效，无法解密旧密文会明确报错并保留文件。公司模型质量、代理、真实计费不在无凭据的本机验收范围内。

本地产物 Authenticode 状态为 NotSigned，未提供企业签名证书；公司部署需按实际软件安装策略处理，不能宣称已具备企业代码签名。

## 可复制验证

~~~powershell
uv sync --locked
npm.cmd --prefix desktop ci
uv run python scripts/validation/check.py
node scripts/validation/desktop-smoke.cjs
.\scripts\build\package-windows.ps1 -ReuseDependencies
~~~

固定场景 A 使用 manual-fixtures/v04-local-first；B 由混合 HTTP 专项复现；C 由 test_v04_orchestration.py 覆盖多文件、恢复与 Git 审批。没有更改旧 manual-fixtures 路径或测试约定。
