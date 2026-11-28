# Windows x64 候选构建

`scripts/dev/prepare-opencode.ps1` 按锁文件校验并放置 `opencode.exe` 和 `LICENSE`。`scripts/build/package-windows.ps1` 验证依赖、后端、桌面和完整候选。输出位于 `desktop/release`，包含 Setup、Portable 和 `SHA256SUMS.txt`。

GitHub Actions 的 Windows installer candidate 工作流收集候选和隔离日志。安装脚本在检测到已有安装后停止，保留用户环境。用 `Get-FileHash -Algorithm SHA256` 校验，运行时用全新的数据目录。当前产物见[验收结果](acceptance-results.md)。
