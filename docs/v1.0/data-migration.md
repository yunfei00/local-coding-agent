# 数据迁移与恢复

schema 6 → 7 前执行SQLite quick_check和一致性backup，保留工程、消息、计划、Checkpoint、记忆/索引、配置和权限。model-secrets.json、provider-secrets.json、mcp-secrets.json及Local State按加密原件备份。Windows凭据仍受原用户DPAPI保护，不保证跨Windows账户恢复。

备份采用临时目录、哈希清单和原子重命名，分块计算哈希，失败不覆盖源。低磁盘、数据库损坏、未来版本和备份篡改明确失败，不静默清空。旧连续授权语义改变时需一次明确确认，不自动扩大v0.9权限。

完整退出应用后离线恢复（先确认数据目录）：

```powershell
$env:LCA_DATA_DIR = Join-Path $env:APPDATA 'local-coding-agent-desktop'
$env:LCA_DESKTOP_DATA_DIR = $env:LCA_DATA_DIR
$install = @(Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue | Where-Object DisplayName -eq 'Local Coding Agent')[0].InstallLocation
if (-not $install) { throw '未发现当前用户安装目录，请从安装目录运行内置后端' }
$backend = Join-Path $install 'resources\agent\lca-agent.exe'
$backup = Read-Host '输入本数据目录 backups 下要恢复的完整备份目录'
& $backend --inspect-backup $backup
if ($LASTEXITCODE -ne 0) { throw '备份校验失败，停止恢复' }
& $backend --restore-backup $backup
```

开发环境等价命令：uv run --locked python -m agent.server.main --restore-backup '备份目录'。仅恢复本数据目录backups内的有效备份；恢复前另存当前数据，恢复后重启核对。应用启动器锁防止在线恢复。不会还原用户工程源码或自动重放未知操作。
