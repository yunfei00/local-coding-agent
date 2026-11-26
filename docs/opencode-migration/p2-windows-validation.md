# P2 Windows 验收（隔离实验）

状态：代码已提交，实际 CI 与 Windows/Ollama 验收尚未完成。P0/P1 安全及实机门禁仍然保留，禁止正式工程 OpenCode 执行、付费调用、自动合并或发布。

## 1. 准备

使用 P1 验收的固定版本 v2.2.6 EXE，SHA256 98cb0aa854c7c015cf6febafa7afb872c359bfe5a823a526f3b4fd347a9e9677。CLI 编程验收要求将其放在 build/opencode-p0/verified-bin/opencode.exe。不得使用 latest。Windows x64、Git、Node、uv、已运行的 Ollama（或获授权的本地回环转发）。关闭所有本项目应用和 Agent；用独立测试数据目录，不使用生产工程。模型必须已经安装，不自动拉取。

## 2. 自动化验证

在项目根目录的 PowerShell 执行，先检查工作区，不清理用户文件：

```powershell
$ErrorActionPreference = 'Stop'
function Check { if ($LASTEXITCODE -ne 0) { throw "退出码 $LASTEXITCODE" } }
git status --short
if (git status --porcelain) { throw '请先保存工作区修改' }
git fetch origin; Check
git switch feature/opencode-engine-migration; Check
git pull --ff-only; Check
git rev-parse HEAD; Check
uv sync --locked; Check
$env:LCA_TEST_PYTHON = (uv run python -c "import sys; print(sys.executable)")
npm ci --prefix desktop; Check
npm run agent:check; Check
uv run python -m unittest discover -s tests -p test_engine_lease.py -v; Check
npm run agent:test; Check
npm run desktop:typecheck; Check
npm run desktop:test; Check
npm run desktop:build; Check
node scripts/validation/desktop-smoke.cjs; Check
node --test scripts/validation/opencode/p2-fixture.test.cjs; Check
```

## 3. 本地对话实验

```powershell
$env:LCA_DATA_DIR = 'C:\lca-p2-test-data'
$env:LCA_DESKTOP_DATA_DIR = $env:LCA_DATA_DIR
$env:LCA_ENABLE_EXPERIMENTAL_LOCAL_CHAT = '1'
npm run dev
```

打开“引擎 → OpenCode 本地对话实验”，填写实际回环端口和模型名，选择已校验 EXE。
- Q01：第一轮要求只输出 15，观察流式文本与终态。
- Q02：第一轮给一个随机代号并要求记住；第二轮询问代号，核对实际输出。
- Q03：生成较长文本时点击停止；只有确认中断后才显示已中断，异常须显示未确认。
- Q04：选择错误 EXE、错误端口、错误模型，均不得假报成功。
- Q05：退出应用后检查本应用拥有的子进程，不得影响其他 OpenCode 实例。
- Q06：默认原引擎仍可用，未启用环境变量时禁止启动实验。

单次实验仅一至两轮，非持久会话；8192 上下文、512 最大输出，最多 4/8 次请求、累计 262144 输入字节、480 秒网关期限；无工具、无在线付费。用量事件仅用于展示，不是硬 Token 预算。

## 4. 三轮真实编程验收

关闭 GUI 后在同一 PowerShell 中执行：

```powershell
$env:LCA_DATA_DIR = 'C:\lca-p2-test-data'
$exe = 'build/opencode-p0/verified-bin/opencode.exe'
if (!(Test-Path $exe)) { throw '请先按 P0/P1 文档准备固定版本 EXE' }
if ((Get-FileHash $exe -Algorithm SHA256).Hash.ToLower() -ne '98cb0aa854c7c015cf6febafa7afb872c359bfe5a823a526f3b4fd347a9e9677') { throw 'EXE 校验失败' }
ollama list
node scripts/validation/opencode/p2-runner.cjs 11434 gemma4:31b
```

模型、端口可改为实际已安装值（例如 gpt-oss:20b）。每轮在 build/opencode-p0/model-* 创建全新 fixture，调用 OpenCode 原生工具；三个独立轮次，每轮最大 28 次本地请求、900 秒网关期限。固定权限只允许指定测试文件与指定命令，仍非 OS 沙箱；禁止在生产数据目录、带敏感资料或客户工程的环境运行。每轮独立校验实际文件内容、原测试、固定测试执行退出码、取消与重启状态。失败不自动重放。

| ID | 用例 | 通过条件 |
|---|---|---|
| C01 | p2_read | 读工具成功，返回随机文件标识 |
| C02 | p2_create | 读及写工具成功，result.txt 正确，seed 不变 |
| C03 | p2_repair | 读及改工具成功，修复文件正确，测试不变 |
| C04 | p2_shell | 固定 echo 命令成功，返回预期输出 |
| C05 | p2_git_status | 原生 Shell 执行固定 git status |
| C06 | p2_git_diff | 原生 Shell 执行固定 git diff |
| C07/C08 | p2_context_store/recall | 同一 Session 保持随机代号 |
| C09 | interrupt_and_restart | 中断、请求关闭、持久化状态、重启后无活动任务 |
| V01 | fixtureVerified | 文件集合和内容独立检查通过 |
| V02 | independentVerification | 原 VerificationEngine 固定可信副本测试通过 |

查看 C:\lca-p2-test-data\p2-acceptance-*\summary.json、round-*.json 以及每轮 report.json 和 independent-verification.json。所有三轮及全部用例通过才判 CLI fixture PASS。若锁残留，必须先确认所有进程停止，按 engine-lease-recovery.md 人工处理，不得盲删。

## 5. 未完成的正式迁移

上述 fixture 和文本实验不能替代正式 P2 Gate。尚待接入真实项目的统一 Agent 入口、文件搜索、Diff 展示、完整工具执行卡片、任意多轮交互与持久化恢复、实际用户权限映射及预算；付费 Provider 仅配置元数据。P0 权限、预算、进程树安全未通过前保持正式入口关闭。CI 与 Windows 实机证据必须补齐，不得将 Mock 或已提交代码认作 PASS。
