# P1 Windows 验收

当前仅允许隔离诊断，禁止正式 OpenCode prompt。无需 Ollama 或付费 API。P0 安全预算门禁仍未通过。

## 自动回归

在仓库根目录 PowerShell 执行：

```powershell
git fetch origin
git switch feature/opencode-engine-migration
git pull --ff-only
uv sync
npm ci --prefix desktop
npm run desktop:typecheck
if ($LASTEXITCODE -ne 0) { throw "typecheck failed" }
npm run desktop:test
if ($LASTEXITCODE -ne 0) { throw "desktop tests failed" }
npm run desktop:build
if ($LASTEXITCODE -ne 0) { throw "build failed" }
node scripts/validation/desktop-smoke.cjs
if ($LASTEXITCODE -ne 0) { throw "smoke failed" }
```

## 实机诊断

按 version-lock.md 获取固定 v2.2.6 Windows EXE。启动桌面开发版（使用仓库 README 的启动命令），打开引擎菜单，选择 OpenCode 隔离诊断，选择该 EXE。预期显示 passed。验证取消文件选择、错误版本或校验和、重复点击、诊断期间退出。不得出现模型请求或真实工程文件修改。检查任务管理器中本次启动的 OpenCode 进程已退出，不要结束其他用户进程。

诊断目录位于应用 userData/opencode-diagnostic-*，包含独立配置、会话数据库和 bindings.json。不要提交这些目录。passed 仅证明隔离服务、会话映射、SSE 连接、快照和中断接口，不证明历史重放、真实任务执行、跨进程锁或预算安全。

## 发布门槛

最新提交双平台 CI 全绿；实机诊断通过；生产路由与后台任务生命周期互斥仍须实现和验证；P0 门禁解除前不得开放正式 OpenCode 执行。PR 保持 Draft。
