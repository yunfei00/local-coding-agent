# Windows x64 安装包

沿用 Electron Builder NSIS 和 PyInstaller onedir。后端、Python运行时及依赖位于 resources/agent，前端在 asar 内。安装版目标文件 Local-Coding-Agent-1.0.0-x64-Setup.exe；Portable保留为可选Windows x64产物，不支持自动安装更新。没有Linux/macOS/ARM发布包。

NSIS按当前用户安装，不请求提权；卸载默认不删除应用数据。安装路径可变，必须补测中文及空格。不能用 npm run dev 代替安装版验收。

构建命令（PowerShell）：

```powershell
.\scripts\build\package-windows.ps1 -ReuseDependencies
Get-FileHash .\desktop\release\Local-Coding-Agent-1.0.0-x64-Setup.exe -Algorithm SHA256
```

本轮实际产物及安装结果以 acceptance-report.md 为准；未构建不算通过。
