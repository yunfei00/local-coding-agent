# P1 Windows 实机验收手册

## 1. 范围与结论规则

P1 验收仅验证双引擎基础设施，不执行正式 OpenCode prompt，不调用付费 API，不需要 Ollama。P0 权限与预算门禁仍独立阻断正式执行。使用 Windows x64、Git、Node/npm、uv，选择独立测试工程；不要使用生产工程或清空现有数据。记录 Windows 版本、Git HEAD、Node/Python 版本及实际应用数据目录。

每项记录 PASS / FAIL / BLOCKED / NOT_RUN 和证据。只有所有必测项通过且同一 HEAD 的 Windows、Ubuntu CI 全绿，才允许宣布 P1 验收通过。不得将隔离诊断 passed 等同于真实编程通过。

## 2. 自动验收（仓库根目录 PowerShell）

```powershell
$ErrorActionPreference = 'Stop'
function Check { if ($LASTEXITCODE -ne 0) { throw "命令失败，退出码 $LASTEXITCODE" } }
git status --short
# 如果有未提交修改，先自行保存，禁止强制覆盖
if (git status --porcelain) { throw '工作区不干净，请先保存修改' }
git fetch origin; Check
git switch feature/opencode-engine-migration; Check
git pull --ff-only; Check
git rev-parse HEAD; Check
node --version; Check
uv sync --locked; Check
uv run python --version; Check
$env:LCA_TEST_PYTHON = (uv run python -c "import sys; print(sys.executable)")
npm ci --prefix desktop; Check
npm run agent:check; Check
npm run agent:test; Check
uv run python -m unittest discover -s tests -p test_engine_lease.py -v; Check
npm run desktop:typecheck; Check
npm run desktop:test; Check
npm run desktop:build; Check
node scripts/validation/desktop-smoke.cjs; Check
```

记录每条命令的退出码、测试通过/失败/跳过数及失败堆栈。pytest 单独执行是因为 agent:test 使用 unittest discover，不能据此认为 pytest 函数已运行。uv --with pytest 如需联网下载且环境禁止联网，标记 BLOCKED，不得跳过后声称通过。

## 3. 获取固定 OpenCode 二进制

```powershell
$fixture = 'build/opencode-p1'
New-Item -ItemType Directory -Force $fixture | Out-Null
$zip = Join-Path $fixture 'opencode-windows-x64.zip'
if (!(Test-Path $zip)) {
  gh release download v2.2.6 --repo anomalyco/opencode --pattern opencode-windows-x64.zip --dir $fixture
  Check
}
if ((Get-FileHash -LiteralPath $zip).Hash -ne 'f75c16b33b8523fe1ff41e7d97e3ae654a47d59a0e327def24db2d9291bb24be') { throw '归档校验失败' }
Expand-Archive -LiteralPath $zip -DestinationPath (Join-Path $fixture 'verified-bin') -Force
$exe = @(Get-ChildItem (Join-Path $fixture 'verified-bin') -Recurse -Filter opencode.exe)
if ($exe.Count -ne 1) { throw '可执行文件数量异常' }
if ((Get-FileHash -LiteralPath $exe[0].FullName).Hash -ne '98cb0aa854c7c015cf6febafa7afb872c359bfe5a823a526f3b4fd347a9e9677') { throw 'EXE 校验失败' }
$exe[0].FullName
& $exe[0].FullName --version; Check
npm run dev
```

预期版本 v2.2.6。无法访问 GitHub 时可以离线复制固定 ZIP，但必须校验。参考 [version-lock.md](version-lock.md)。npm run dev 保持运行，另开 PowerShell 做检查。

## 4. 必测矩阵

| ID | 操作 | 通过条件 |
| --- | --- | --- |
| A01 | 执行第2节全部命令 | 全部退出码0，新增测试确实执行 |
| A02 | 检查同一 HEAD CI | Windows/Ubuntu 均成功，必测步骤未跳过 |
| W01 | 打开引擎菜单 | 默认 Python；OpenCode 正式执行不可选 |
| W02 | 选择 OpenCode 隔离诊断，选固定 EXE | 显示 passed，产生独立会话绑定，服务退出 |
| W03 | 取消 EXE 选择 | cancelled，无新增运行进程 |
| W04 | 选择其他 EXE 或修改后的测试副本 | 校验失败，禁止启动 |
| W05 | 连续诊断3次、快速重复点击 | 不并发启动，正常诊断可重复通过 |
| W06 | 诊断期间关闭应用 | 本次启动的进程树退出；无意外残留锁 |
| W07 | 检查诊断目录 bindings.json | threadId/sessionId/engine/projectRoot 对应；不污染旧会话 |
| W08 | 检查诊断网络及工程 | 仅回环服务通信，无模型调用、无生产工程修改 |
| L01 | Python/Electron 双向锁测试 | 两方向竞争均拒绝，释放后可获取 |
| L02 | 异常与取消测试 | 正常异常退出释放锁；残留锁不自动抢占 |
| L03 | 在独立数据目录持锁，尝试普通对话 | 可恢复错误，界面不永久运行，不执行工具 |
| L04 | 同样条件启动统一后台任务 | paused，状态持久化，未执行工具 |
| L05 | 同样条件启动自主任务 | paused，运行标记清除，未执行工具 |
| L06 | 释放锁后手动恢复或新建任务 | 可正常启动，无自动重放 |
| L07 | 离线残留锁恢复演练 | 按恢复文档保留证据，重启后可获取 |
| R01 | 原 Python 引擎桌面回归 | 既有会话可打开，文件/Git/Shell smoke 不退化 |
| S01 | 权限与路由检查 | 隔离诊断拒绝 prompt、非白名单路由、非 deny-all 会话 |

W02 的 passed 只证明隔离服务、绑定、SSE 连接及快照、中断接口；不证明历史重放或真实任务执行。W08 如无网络观察证据则标记 NOT_RUN。

## 5. 锁竞争实机操作

仅在独立测试数据目录启动应用。关闭其他实例，另开 PowerShell，设置与应用一致的 LCA_DATA_DIR，执行：

```powershell
# 替换为测试应用实际使用的数据目录，不要使用生产目录
$env:LCA_DATA_DIR = 'C:\\lca-p1-test-data'
uv run python -c "import os; from agent.core.engine_lease import engine_lease; exec('with engine_lease(os.environ[\'LCA_DATA_DIR\']):\n input(\'Lease held; Enter to release: \')')"
```

保持持锁窗口打开，依次执行 L03–L05；检查任务状态及工作区无变化。按 Enter 释放后执行 L06。若没有可用的本地模型配置，涉及正常任务执行的检查标记 BLOCKED；禁止使用付费模型替代。人工恢复见 [engine-lease-recovery.md](engine-lease-recovery.md)。不要在活动任务期间删除锁。当前全局独占会限制多工程并行，此为待评估兼容性问题。

## 6. 验收报告模板

- HEAD：
- Windows / Node / Python：
- EXE SHA256：
- CI 链接：
- A01–S01：逐项填写 ID、结果、实际现象、日志/截图路径
- 未通过项及复现步骤：
- 最终结论：PASS / FAIL / BLOCKED
- 验收人及日期：

诊断目录在实际 userData 下的 opencode-diagnostic-*；保留日志但脱敏，不提交会话数据库、密钥、真实工程或用户数据。发现失败先修复，再针对新 HEAD 重跑。PR #40 保持 Draft；P0 门禁未解除前禁止正式 OpenCode prompt，不合并、不发布。
