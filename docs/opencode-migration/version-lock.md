# P0 版本锁定

| 项目 | 实测或核验值 |
| --- | --- |
| 项目基线 | `7ffff6066edccb6b3e940d32a54a53604702e066` |
| OpenCode | `v2.2.6` |
| 上游 tag 实际指向 | `dc2ffcf8bf26f9e669b6aa22b95f50e12be15e06` |
| Windows x64 资产 | `opencode-windows-x64.zip` |
| 官方与本地归档 SHA256 | `f75c16b33b8523fe1ff41e7d97e3ae654a47d59a0e327def24db2d9291bb24be` |
| 解压后本地可执行文件 SHA256 | `98cb0aa854c7c015cf6febafa7afb872c359bfe5a823a526f3b4fd347a9e9677` |
| CLI 实测版本 | `opencode v2.2.6` |
| SDK | 固定源码清单和 npm 发布元数据均为 `@opencode/sdk@2.2.6` |
| 许可证 | MIT，Copyright (c) 2025 opencode |

CLI 资产从固定 Release 下载并比对官方 SHA256。SDK npm 依赖树由独立的 `scripts/validation/opencode/package-lock.json` 锁定。当前 POC 使用固定二进制直连 HTTP，产品未引入 SDK 依赖。将来打包时需要保留许可证及版权声明，并注明 Local Coding Agent 并非 OpenCode 官方产品。

隔离目录中的 `npm ci --ignore-scripts` 安装后，Node 24.14.0 能导入实际发行的 SDK 2.2.6。传递依赖 `@opentui/core@0.8.1` 声明需要 Node 26.4.0 或更高版本并产生引擎警告。SDK 在产品 Electron 中的嵌入运行尚未验证，已实测的方式是固定 Windows sidecar 和 v2 HTTP。

[固定 Release](https://github.com/anomalyco/opencode/releases/tag/v2.2.6) · [固定 SDK 源码清单](https://github.com/anomalyco/opencode/blob/dc2ffcf8bf26f9e669b6aa22b95f50e12be15e06/packages/sdk/package.json) · [固定许可证](https://github.com/anomalyco/opencode/blob/dc2ffcf8bf26f9e669b6aa22b95f50e12be15e06/LICENSE)

在仓库根目录执行以下 PowerShell。脚本会再次校验可执行文件才启动。

```powershell
$fixture = 'build/opencode-p0'
New-Item -ItemType Directory -Force $fixture | Out-Null
gh release download v2.2.6 --repo anomalyco/opencode --pattern opencode-windows-x64.zip --dir $fixture
if ($LASTEXITCODE -ne 0) { throw '下载失败' }
$zip = Join-Path $fixture 'opencode-windows-x64.zip'
$expected = (Get-Content scripts/validation/opencode/version-lock.json -Raw | ConvertFrom-Json).archive_sha256
if ((Get-FileHash -LiteralPath $zip).Hash -ne $expected) { throw 'SHA256 不匹配' }
Expand-Archive -LiteralPath $zip -DestinationPath (Join-Path $fixture 'verified-bin')
node scripts/validation/opencode/p0-service.cjs
uv run --locked python scripts/validation/opencode/p0-ollama-probe.py
```
