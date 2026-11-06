# Windows x64 安装包

沿用 Electron Builder NSIS 和 PyInstaller onedir。后端、Python运行时及依赖位于 resources/agent，前端在 asar 内。安装版目标文件 Local-Coding-Agent-1.0.0-x64-Setup.exe；Portable保留为可选Windows x64产物，不支持自动安装更新。没有Linux/macOS/ARM发布包。

NSIS按当前用户安装，不请求提权；卸载默认不删除应用数据。中文及空格目录的实际安装、启动、升级已验证；不能用 npm run dev 代替安装版验收。当前没有发布签名证书，不能把构建工具的 signing 日志当作可信发行者签名。

构建命令（PowerShell）：

```powershell
.\scripts\build\package-windows.ps1 -ReuseDependencies
Get-FileHash .\desktop\release\Local-Coding-Agent-1.0.0-x64-Setup.exe -Algorithm SHA256
```

冻结后端必须显式收集 workflow_templates.json 和动态模块 win32timezone。前者缺失会导致编排模板接口失败，后者缺失会使原生窗口身份读取失败。打包脚本会实际请求已冻结后端的模板接口，并通过独立原生程序测试窗口发现、输入、点击保存及文件/UIA 双重验证。

安装验收临时隐藏 PATH 中的 Python、uv、Node 与 Git，确认内置后端启动、无 Git 工程创建与重启。此测试证明应用运行不依赖外部开发工具链；测试机本身仍是有开发工具的 Windows，不等于全新无 SDK 镜像。

本轮实际产物及安装结果以 acceptance-report.md 为准。CI 候选以 Actions Artifact 留存 14 天，不是正式 Release，不提供不存在的正式下载链接。
