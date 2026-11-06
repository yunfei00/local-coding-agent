# v1.0 验证命令与证据边界

从仓库根目录运行，Windows重型检查串行，Electron产品实例最多一个。不要与其他GUI自动化同时执行。

```powershell
$env:PYTHONUTF8='1'
uv run --locked python -m unittest discover -s tests
npm --prefix desktop run typecheck
npm --prefix desktop run test
npm --prefix desktop run build
node scripts/validation/desktop-smoke.cjs
uv run --locked python scripts/validation/credential_scan.py
git diff --check
```

完整产物验收：

```powershell
.\scripts\build\package-windows.ps1 -ReuseDependencies
```

脚本运行Python、冻结后端模板接口与真实原生worker、前端、Setup/Portable、55项Electron任务Smoke、权限/重启、方案A受控HTTP实装UI、聊天文件写入、无SDK PATH、卸载数据保护及SHA256。保护已有用户安装，不强制覆盖。锁屏或资源不足保留具体失败/BLOCKED证据，不修改系统设置或绕过会话保护。

更新单元套件含29项管理器和6项版本/元数据；HTTP与文件真实，下载来源元数据/传输映射受控。安装版补测的shell打开回调受控，不执行模拟exe；聊天SSE为Mock，但真实桌面入口、后端、工具写文件。它们不计为在线模型验收。已有真实API/GUI分项另见acceptance-report.md和历史原始报告。

Windows/Ubuntu核心CI不删减；Windows候选额外运行打包。正式tag工作流必须使用main内且已有成功CI的提交、PASS门槛与未存在的Release；最终还需下载实际发布字节复核SHA。Ubuntu不生成安装包。
