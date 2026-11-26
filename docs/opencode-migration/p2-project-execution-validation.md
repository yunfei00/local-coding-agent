# P2 工程执行验收：文件、Shell、Git

## 1. 当前可执行范围

当前正式工程入口仍为 Legacy，OpenCode 正式执行门禁未开放。以下 A 类为真实 OpenCode 独立工程自动化验收，B 类为正式入口开放后的验收规范，目前必须记为 NOT_RUN。不能用 Legacy 结果替代 OpenCode 证据。

仅在获授权的 Windows 测试环境运行；关闭本项目应用和 Agent，不使用客户工程或敏感数据。权限规则不是 OS 沙箱。无需付费 API，不自动下载模型。

## 2. 准备与一键运行（PowerShell）

在仓库根目录执行。先保存自己的修改，不强制覆盖。固定 OpenCode v2.2.6 的 opencode.exe 按 P0/P1 文档准备，放在 build/opencode-p0/verified-bin/opencode.exe。

```powershell
$ErrorActionPreference = 'Stop'
git status --short
git fetch origin
git switch feature/opencode-engine-migration
git pull --ff-only
git rev-parse HEAD
ollama list
$exe = 'build/opencode-p0/verified-bin/opencode.exe'
Get-FileHash $exe -Algorithm SHA256
powershell -NoProfile -File scripts/validation/opencode/p2-acceptance.ps1 -Model 'gpt-oss:20b' -Port 11434
```

EXE SHA256 必须为 98cb0aa854c7c015cf6febafa7afb872c359bfe5a823a526f3b4fd347a9e9677。模型必须实际存在；可替换为 gemma4:31b 等已安装模型。公司网络或依赖安装失败应记录 BLOCKED，不视为模型失败。

脚本先执行静态回归，再运行三轮真实模型测试。每轮新建 fixture，最多28次本地请求，网关期限900秒；整个脚本耗时可能更长。不要并行启动其他 Agent。

## 3. A 类自动验收

| ID | 实际任务 | 独立通过条件 |
|---|---|---|
| A01 | 读取 seed.txt | OpenCode 工具成功事件及随机标识匹配 |
| A02 | 创建 result.txt | 内容为随机标识加 -VERIFIED，原文件不变 |
| A03 | 修复 add.cjs | 减法改加法，固定测试文件不变，可信副本测试通过 |
| A04 | Shell | 执行 echo P2_SHELL_CHECK 并返回标识 |
| A05 | Git status | 执行 git status --short 并报告 add.cjs |
| A06 | Git diff | 执行 git diff -- add.cjs 并报告文件 |
| A07 | 上下文保存 | 返回 READY，不使用工具 |
| A08 | 同一 Session 召回 | 返回此前随机标识 |
| A09 | 中断与重启 | 请求关闭、持久化状态、重启无活动任务 |
| A10 | 独立验收 | 文件集合及 VerificationEngine 固定测试通过 |

Git 用例只验证 status/diff，不验证 commit、分支或 push。当前工具事件与文本检查不能单独证明任意命令执行能力；保留原始证据供复核。

## 4. 结果与反馈

脚本打印 Evidence directory。该目录下 p2-acceptance-*/summary.json 为总报告，round-*.json 和 round-*.stderr.txt 为各轮结果；每轮详细 report.json、independent-verification.json 在 build/opencode-p0/model-* 下。

三轮均 PASS 且进程清理确认才算 A 类通过。失败时提供 HEAD、模型名、summary.json、失败轮次报告和 stderr（先检查并脱敏）。若锁残留，不要盲删；按 engine-lease-recovery.md 处理。

## 5. B 类正式工程验收（当前 NOT_RUN）

正式入口开放后，在全新无敏感资料的测试工程中创建 seed.txt、add.cjs 和固定测试文件，初始化 Git。界面明确选择 OpenCode，任务记录必须显示 engine=opencode、工程 ID、原始 Session ID，且原 Legacy 引擎未执行同一任务。

| ID | 界面输入或操作 | 通过条件 |
|---|---|---|
| B01 | 读取 seed.txt 并报告内容 | 真实文件工具事件、内容一致 |
| B02 | 创建 result.txt，写入 seed.txt 内容 | 文件落盘且源文件不变 |
| B03 | 修复 add.cjs 加法错误并运行测试 | 实际 Diff 正确，独立测试退出码0 |
| B04 | 执行 echo P2_SHELL_CHECK | Shell 工具证据与输出一致 |
| B05 | 执行 git status --short、git diff -- add.cjs | Git 工具证据与独立 Git 输出一致 |
| B06 | 继续对话，询问上一轮随机标识 | 同一 Session ID，正确召回 |
| B07 | 运行中取消 | 确认中断，无后续写入 |
| B08 | 暂停、继续 | 状态真实、无重复副作用；未支持则 NOT_RUN |
| B09 | 异常退出并重启 | 原 Session 状态核验，无自动重放 |
| B10 | 权限拒绝与撤销 | 禁止操作无实际副作用，独立核验 |

B 类必须使用正式工程入口，而非本地纯文本实验弹框。安全、预算及独立验收门禁未通过前不得开放正式执行。A 类通过不能替代 B 类通过。

参见 [P2 Windows 验收](p2-windows-validation.md)。
