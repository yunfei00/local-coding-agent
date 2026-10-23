# M5 Electron + React + TypeScript 实验工程

两处预置缺陷保留在 src/App.tsx：Settings 输入框禁用、保存后状态不更新。单元测试验证姓名归一与长度，独立 GUI 契约验证实际 React 状态、两次不同输入及持久化，不能以单元测试通过代替 GUI 通过。

从仓库根目录运行自动验收（仅本机 HTTP Mock 模型，无付费 API）：

```powershell
uv sync --locked
uv run python -m unittest discover -s tests -p test_m5_electron_e2e.py -v
```

Windows 必须解锁且具备交互桌面；Linux 只执行契约测试，真实 GUI 明确平台跳过。自动入口会复制工程、初始化独立 Git、创建 Task Worktree、安装锁定依赖，调用原 Agent 工具，最后关闭所有受控进程并清理临时工程。无需自己编写测试工程。

手工查看原始缺陷：

```powershell
npm --prefix manual-fixtures/m5-electron-e2e ci --no-audit --no-fund
npm --prefix manual-fixtures/m5-electron-e2e run typecheck
npm --prefix manual-fixtures/m5-electron-e2e test
npm --prefix manual-fixtures/m5-electron-e2e run build
npm --prefix manual-fixtures/m5-electron-e2e start
```

独立实验副本（不要在本仓库目录内重新 git init）：

```powershell
$fixtureCopy = Join-Path $env:TEMP ("lca-m5-" + [guid]::NewGuid().ToString("N"))
Copy-Item -LiteralPath ".\manual-fixtures\m5-electron-e2e" -Destination $fixtureCopy -Recurse -Force
git -C $fixtureCopy init -b main
git -C $fixtureCopy add .
git -C $fixtureCopy -c user.name="M5 fixture" -c user.email="m5@example.test" commit -m "M5 baseline"
Write-Host $fixtureCopy
```

在 Agent 打开输出的目录、创建 Single Agent Task，输入：“检查 Electron Settings，修复输入框及保存状态；运行测试、启动程序、操作和截图；根据独立失败证据继续修复，不改变测试与验收契约。”依赖安装需要 npm ci。验收命令与窗口断言在 .lca/ 中；任务开始前冻结。上传图片和 Save 操作需要相应审批。

运行时只在该工程 .runtime 中保存姓名、Electron 配置和 PID；窗口固定标题，受控窗口置顶以隔离桌面遮挡。退出窗口后清理：

```powershell
npm --prefix manual-fixtures/m5-electron-e2e run clean
```

clean 只删除本工程 .runtime；若记录中的进程仍活着则拒绝，不杀不确定 PID。Task 的 Stop 使用原受管理 Job 终止整个进程树。node_modules/dist 为可再生目录，不由此清理命令删除。
