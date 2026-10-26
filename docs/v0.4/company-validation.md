# 公司环境验证流程

2026-10-26 最新源码：本轮修复仍在 `feature/real-online-agent-validation`，未合并 main。真实 GLM API-only 与 Omni Single Agent 的 calculator 修复已通过，当前本机锁屏下原生桌面在线验收未通过。公司请按[最新分支安装、配置与逐模型结果](../validation/alibaba-model-validation-2026-10-26.md)获取源码，避免下载 main 后误以为包含本轮修复。

本流程使用现有 manual-fixtures/v04-local-first，不要求自己编写工程。真实模型能力与路由框架验收分开记录；没有付费 API 凭据时使用下面的 HTTP Mock 自动化。

## Planning 修复的本轮验证约定

本轮按用户后续要求只使用 Mock，真实 DeepSeek API 为 **NOT RUN**；公司使用已有配置实测并口述结果。无需提供 Key、截图或自行查日志。更新源码与复现步骤见 [Planning 测试结果](../validation/planning-api-test-results.md)。

已有 API-only 模型配置可新建任务运行下文 calculator fixture。重点观察 Planning 是否进入 Executing；失败时 Task 直接显示错误码，Task diagnostics 可展开关联 Call ID、HTTP、解析、Schema、预算结算与状态转换。顶部 Pause active task / Cancel active task 在 Planning 等待时也可使用。无需删除历史任务、清空预算或重新填写凭据。

策略只验证角色绑定，不自动替换模型。API-only 与本地 Planner 冲突时会在调用模型和创建 Worktree 前明确暂停并记录 MODEL_POLICY_MISMATCH。旧任务使用原快照；新任务使用当前配置，显式 Apply configuration to paused task 才更新旧快照。

## 安装与服务

### Task 启动即 Paused、API 计数为零的修复

本轮只更新源码，旧 v0.4.2 安装包不包含此修复；不创建新 Release/Tag/安装包。详细原因见 [预算启动审计](../validation/task-start-budget-root-cause.md)，自动化结果见 [测试记录](../validation/task-start-budget-test-results.md)。

先退出正在运行的源码开发版，在仓库目录执行（有本地未提交修改时先保留，不执行 reset/clean）：

```powershell
git status -sb
git switch main
git pull --ff-only origin main
uv sync --locked
npm --prefix desktop ci --no-audit --no-fund
npm run dev
```

运行中的 Electron 和 Agent 必须退出重开才能加载更新。已有保存配置和凭据无需重新填写。Settings → Models & Routing 中确认 API-only 的 Planner/Executor/Reviewer 使用 API Profile，保存后新建 Task，直接使用下文已有 calculator fixture 和验证命令。观察实际 Planning → Executing → verifying；未通过测试不可接受报告。

新 Task 启动时读取最新保存 Settings，保留 Task 面板内主动编辑的字段。旧 Paused Task 仍保留原快照，直接 Resume 不会采用新默认值；可新建 Task，或重新打开 Task 面板，检查配置后明确 Apply configuration to paused task，再恢复。旧账本不会清零。

若再次在零调用时阻止，Task 将直接显示具体任务/全局字段、上限、已用/已预留、本次需要及估算输入与输出上限。`api_calls=0` 或 `api_tokens=0` 表示明确禁止；全局上限包含别的任务；首次预留还包含模型最大输出。依据显示字段检查配置及模型输出限制，不应笼统追加预算。只需口述字段和阶段即可，无需截图、上传日志或提供 Key。

安装发布页的 x64 Setup，或直接运行 Portable。发布地址见 README；公司电脑需允许 Ollama 服务与批准的 API 网关访问。安装包内置 Agent；工程验证命令仍需 Git、uv 和项目所用工具。

先执行 `Get-Command git, uv, ollama` 检查环境。缺少 uv 时，按 [uv 官方安装说明](https://docs.astral.sh/uv/getting-started/installation/) 可执行：

~~~powershell
winget install --id=astral-sh.uv -e
uv python install 3.12
~~~

Git 使用公司批准的发行版；本机 Ollama 使用 [官方 Windows 安装包](https://ollama.com/download/windows)，或直接连接公司已部署的 Ollama 服务。公司限制安装或访问时由 IT 提供相应工具与服务，不修改应用权限绕过限制。

开发运行（需仓库声明的 Node 环境）：

~~~powershell
uv sync --locked
npm.cmd --prefix desktop ci
.\scripts\dev\start.ps1
~~~

检查 Ollama，已运行托盘服务时无需重复 serve：

~~~powershell
ollama list
curl.exe http://127.0.0.1:11434/api/tags
~~~

需要两个小模型用于配置验证时，可在公司允许下载模型的前提下执行（下载占用磁盘和网络，不是付费 API 调用；不承诺小模型能完成复杂任务）：

~~~powershell
ollama pull qwen2.5-coder:1.5b
ollama pull qwen2.5-coder:3b
ollama list
~~~

公司局域网 Ollama 也选 Ollama 类型，填写管理员提供的实际地址，无需改代码或按 URL 猜测 API 类型。

## 配置两个本地和两个 API 模型

1. Settings → Models & Routing → Add connection，名称“公司 Ollama”，类型 Ollama，填写实际 Base URL。
2. Test connection / fetch models 保存并测试当前配置。点击列出的 Add model 按钮，或 Manually add model。添加两个实际安装的模型，填写 Model ID、显示名称、上下文与输出上限。
3. Add connection，名称“公司 API”，类型 OpenAI Compatible，填写获准的网关 Base URL（通常包含 /v1）。
4. 密码框输入公司分配的 Key，Save / clear connection key，再 Save model configuration。Key 不写入工程或配置 JSON。无 Key 的网关可保留空凭据。
5. 获取模型列表，添加两个获准的 API 模型；网关不支持列表时手动填实际 Model ID。根据服务文档配置上下文、输出限制、工具模式和价格。
6. 四个下拉框均能看到全部模型。推荐 Planner/Executor 选择本地编码模型、Reviewer 选择另一本地模型、Escalation 选择强 API 模型。允许多个角色共享模型；可临时选择四个不同配置确认独立绑定，再恢复本地 Reviewer。
7. Execution Policy 选 Local-first。本轮源码未配置预算时默认 200 次、1,000 万 Token、120 秒请求、3 次本地修复、7200 秒任务；全局默认 2,000 次、1 亿 Token。旧配置不会自动覆盖，可点击 Use long task budget 并保存；Settings → Agent 的 Use long task execution limits 提高旧步骤/工具额度。价格和费用上限保持原值，未知价格不虚构费用精度。
8. Save model configuration，关闭并重新启动软件，核对连接、模型和四角色。切换旧 Provider 页不应改变这些角色。模型/连接删除前先解除角色引用。

## 场景 A：本地修复

复制固定测试工程到新的临时目录，避免修改仓库模板：

~~~powershell
$fixtureDir = Join-Path $env:TEMP ("lca-company-" + [guid]::NewGuid().ToString("N"))
Copy-Item -LiteralPath .\manual-fixtures\v04-local-first -Destination $fixtureDir -Recurse
git -C $fixtureDir init -b main
git -C $fixtureDir add .
git -C $fixtureDir -c user.name=CompanyValidation -c user.email=validation@example.test commit -m "fixture baseline"
Write-Output $fixtureDir
~~~

在软件打开输出目录、Thread 和 Task；输入“读取 calculator.py，修复 add(a,b)，保持测试不变，使用实际工具并检查 Diff”。验证命令填两行：

~~~text
uv run --no-project python -m unittest discover -s tests -v
git diff --check
~~~

批准创建隔离 Worktree，观察 Planner → Executor → verifying → Reviewer → awaiting_approval；成功时 API 为零（前三角色均本地）。只有真实测试通过才能接受报告。小模型可能失败并暂停，记录模型与错误，不能伪记 completed，也不能据此认定跨 Provider 路由错误。

## 场景 B：可靠复现升级与预算，不产生真实 API 费用

在仓库执行：

~~~powershell
uv run python -m unittest discover -s tests -p test_mixed_provider.py -v
~~~

测试自带四个独立 HTTP Mock 服务和临时真实 Git 工程，验证错误修改 → 实际 unittest 失败 → 指定 API 连接诊断 → 原本地 Executor 修复 → 独立测试通过；同时核对 Authorization、模型 ID、Usage、缓存 Token。还验证 Local-only、零调用、Token 不足、API-only 零预算、429、超时、不可用服务、运行中修改设置和恢复，不依赖真实付费服务。

可选真实模型基础测试：

~~~powershell
uv run python scripts/validation/v04_model_smoke.py --mode ollama --model qwen2.5-coder:1.5b --seconds 120
~~~

该脚本输出真实结果与报告路径，修复失败返回非零，不会伪装验收成功。真实 API 生成需要显式 --allow-paid-api，可能收费；没有凭据不运行。

## 场景 C：恢复、权限与桌面

~~~powershell
uv run python -m unittest discover -s tests -p test_v04_orchestration.py -v
node scripts/validation/desktop-smoke.cjs
uv run python scripts/validation/check.py
~~~

分别覆盖多文件计划/真实验证/Checkpoint、暂停与 Stop 后代进程、恢复不重放已完成修改、预算不清零、源工作区保护、Git 与审批；Electron 自动化实际创建连接、添加模型、绑定角色、安全存钥、重启及发送任务。

Task 按需展开查看阶段、真实 Model call journal、API 次数/预留 Token/Usage/剩余预算、验证分类与日志文件、升级原因、最终状态。切换 Git/Context 面板后输入框仍能发送；Enter 发送、Shift+Enter 换行。Stop 后不应继续产生工具输出或遗留验证子进程。

## 判定

框架通过条件：自动化零失败、指定服务真实 HTTP 调用与回交成立、预算前置阻断成立、Windows UI 保存/重启成立、安装版和 Portable 可启动，文档及产物一致。公司业务能力另记：公司实际模型、网关认证/计费、网络代理与具体工程任务必须在公司环境核验。未运行的真实付费调用明确记“未验收”，不能用 Mock 数字冒充真实费用。
## M4/M5 源码更新

2026-10-24 后续验收使用用户已配置的 `qwen3.8-max`，执行与视觉使用同一在线 Profile。真实 Max 已完成 46 次请求、741,103 服务端 Token、2 次源码修改及 npm 工程检查，但 Task 因工具失败暂停，Max 视觉尚未运行；不得写成完整通过。Windows/Ubuntu CI 已通过的准确提交、当前命令、已用量和未完成事项见[在线验收最新结论](../validation/real-online-agent-acceptance.md#最新结论2026-10-24qwen-max)。本机另有约 12.37 GiB 非分页内核池异常及 Electron 退出确认失败，见[环境阻断与安全恢复](../validation/windows-kernel-memory-blocker.md)。保存工作并恢复环境后由 Agent 继续验证，不要求重新配模型、粘贴 Key 或增加预算。

当前源码的 Provider 与模型目录已统一；Single Agent、独立视觉、真实 Electron 实验工程和最新运行命令见 [M5 公司源码使用](../m5/user-guide.md) 和 [可复现实验工程](../../manual-fixtures/m5-electron-e2e/README.md)。M4/M5 不发布安装包，原 v0.4.2 安装版不包含本轮源码。真实付费推理已有实际 Qwen 请求和源码修改，但完整在线闭环尚未通过；详细 Task ID、服务端 Token、阻断与可复制命令见 [真实在线验收](../validation/real-online-agent-acceptance.md)。该记录与本机 HTTP Mock/真实 GUI 回归分别报告，不能互相替代。
