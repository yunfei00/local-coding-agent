# v0.8 实现与使用

六个模块沿用统一聊天入口，无需选择普通/自主开发模式。模型选择增加自动模式；手动模型可明确允许回退。现有 Context 中增加项目记忆和工程检索，模型配置中增加能力摘要，进度卡显示实际模型、切换、压缩、知识命中和资源计数。

开发启动（PowerShell，在仓库根目录）：

```powershell
uv sync --locked
npm --prefix desktop ci
npm --prefix desktop run dev
```

回归：

```powershell
uv run --locked python scripts/validation/check.py
node scripts/validation/desktop-smoke.cjs
```

真实模型验收脚本沿用 scripts/validation/unified_live.py，通过 Electron 的实际聊天入口驱动；密钥由原 OS 安全存储解密，不写入仓库。所有受控工程和监督输出位于 validation-reports，监督输出不得写入被测工程导致伪代码变更。

```powershell
uv run --locked python scripts/validation/unified_live.py --help
```

先确认内存可用量，串行运行。资源不足标记 BLOCKED_RESOURCE，不反复启动；仅清理本轮创建的进程。真实验收结果以 acceptance-report.md 为准，不能将 Mock 或历史 v0.7 结果当成本次真实 PASS。

## 日常使用

1. 原 Settings 的连接、模型和安全凭据继续使用，不要求迁移或重新填写密钥。
2. 聊天底部选择具体模型，或选“自动选择（按已确认能力）”。手动模式的“允许模型自动回退”默认关闭；未知能力会明确提示检测，不会静默视为支持。
3. 直接输入需求。概念问答不创建复杂计划；工程问题按只读分析；实际代码变更后自动验证；复杂任务自动保存计划。
4. 点击 Context，展开“项目长期记忆与工程检索”。可搜索真实文件片段、管理来源、编辑删除记忆和关闭自动提取。运行中不能修改记忆快照。
5. 明确规则可输入“记住：本工程必须使用 unittest，交付摘要使用中文。”。原文按用户约定保存，代码块与 Markdown 引用不会作为可信保存授权。
6. 环境修复通过原审批；拒绝不会被绕过。系统 PATH、代理、全局软件和缓存不自动修改。
7. 进度卡展示当前模型、切换原因、知识命中、压缩、预算和恢复。失败先看当前诊断，完整历史保留在本地 JSON。Stop 和恢复沿用既有入口。

## 公司电脑更新源码

先退出旧版应用并保留自己的未提交修改。工作区干净时在 PowerShell 执行：

```powershell
git status -sb
git fetch origin
git switch main
git pull --ff-only origin main
uv sync --locked
npm --prefix desktop ci
npm --prefix desktop run dev
```

原模型、API Key、工程、任务及线程保留。旧安装包不会因拉取源码自动更新；本轮没有安装包产物。不安装或测试 Ollama。自动路由需要当前配置的有效能力证据；配置改变或证据过期时，通过原模型能力检测更新。

## 真实验收复现（会消耗所选模型额度）

先构建桌面端。以下命令仅发现已有连接的模型 ID，不生成文本，不输出密钥；每次输出目录必须为新的隔离目录：

```powershell
npm --prefix desktop run build
uv run --locked python scripts/validation/unified_live.py --live --discover-only --output validation-reports/company-v08-discovery --max-calls 6 --max-tokens 120000
```

从实际发现结果中选择允许的模型。以下为本次实际存在的示例，未来 ID 不存在时必须替换，不能靠名称假定能力：

```powershell
uv run --locked python scripts/validation/unified_live.py --live --suite --automatic-routing --case project-memory --case knowledge-fix --case environment-repair --candidate-model qwen3.8-2.4t-a95b --discovery-report validation-reports/company-v08-discovery/report.json --only-model qwen3.8-2.4t-a95b --max-calls 30 --max-tokens 400000 --validation-task-calls 20 --validation-task-tokens 300000 --request-seconds 120 --output-tokens 4096 --output validation-reports/company-v08-projects
```

该脚本创建受控计算工程，保留原测试与验证配置，通过真实 Electron 聊天提交；不会替 Agent 修复业务代码。能力探针和实际任务分开计数。运行结束检查 report.json 的逐项结果，PARTIAL/FAIL/BLOCKED 都不等于通过。重启记忆专项可加 `--case memory-reopen --reopen-memory-report` 指向此前通过的 project-memory 报告；只能复用仓库 validation-reports 内的数据。

隔离 Git PATH 故障使用 `--case environment-git --isolate-git-path`；Python 依赖故障使用 `--case environment-python`，脚本自带 vendor 测试依赖，必须由 Agent 申请 uv 同步审批。监督进程只用 `uv run --no-sync` 独立检查，不替 Agent 安装依赖。
