# Windows 使用说明

从官方 GitHub Releases 下载 Windows x64 Setup 或 Portable，并与同页 SHA256SUMS.txt 比较：

```powershell
Get-FileHash .\Local-Coding-Agent-1.0.0-x64-Setup.exe -Algorithm SHA256
Get-FileHash .\Local-Coding-Agent-1.0.0-x64-Portable.exe -Algorithm SHA256
```

Setup双击按当前用户安装；Portable放在自选目录直接启动。应用包含Electron和Python后端，启动无需预装Python、uv、Node或Git。项目本身的测试可能仍需自己的开发依赖。当前包未签名，请核实下载来源，不绕过系统安全控制。

首次选择或创建工程，配置OpenAI兼容连接，获取模型并保存。保存检查连接，不自动发送文本/能力探针。不覆盖旧模型配置；Ollama兼容保留但不要求安装。

同一聊天框输入需求即可问答、分析、开发、测试和修复；复杂任务使用持久化计划与角色协作。Enter发送，Shift+Enter换行，Context、Git、MCP、工具和计划按需展开。

聊天工具栏选择权限；设置 → 权限与安全管理全局、项目和任务覆盖，优先级为任务 > 项目 > 全局。完全访问首次明确确认后，普通授权操作不再反复审批，重启/角色切换/模型切换保留有效授权。随时撤销并停止任务；高风险操作、凭据与Windows安全边界仍受保护。撤销时请检查高级覆盖，不要只修改较低优先级的全局默认。

设置 → 关于 → 软件更新采用方案A：检查正式Release、下载、SHA256校验，用户主动打开并手动安装。下载不停止后台任务；安装前保存工作、停止任务、正常退出，按需独立备份。没有自动安装、自动重启或自动回滚。Portable下载后手动替换。数据备份与离线恢复见 data-migration.md。

没有Git时仍可创建普通工程、聊天和文件操作，Git专属操作显示依赖提示。升级/卸载保留用户数据；不要把用户工程放在安装目录。

验收使用当前Windows实装和受控PATH，不是干净系统。已有真实在线代码/四角色/GUI分项证据继续有效；同一任务四角色+GUI组合历史未通过、不标为PASS，按最终要求不作为发布阻断。完整范围见 acceptance-report.md。
