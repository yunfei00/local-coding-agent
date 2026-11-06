# Windows 实装最终验收

本机Windows 11、16GB内存，测试串行，Electron产品最多一实例。使用实际NSIS安装的exe与实际Portable，不用开发启动代替。不要求干净OS，但受控PATH不等于全新系统。

| 范围 | 状态 | 证据/边界 |
| --- | --- | --- |
| Setup安装/启动/前后端/中文空格路径 | PASS | v10-plan-a-install.json、实际安装目录及独立数据 |
| Setup创建/打开工程、聊天、文件写入、重启 | PASS | v10-plan-a-setup-chat/report.json；两次运行，Mock SSE，真实文件工具 |
| Portable前后端/工程/聊天/重启 | PASS | v10-plan-a-portable-chat/report.json；两次运行 |
| 无Python/Node/uv/Git PATH | PASS | 内置后端，四种外部工具检测均false，非Git工程仍聊天/写文件 |
| 更新方案A实际UI | PASS | v10-plan-a-desktop/report.json，4项；受控HTTP实际文件下载，不执行模拟安装器 |
| FULL_ACCESS IPC/重启 | PASS | v10-plan-a-permissions；4项，原生确认选择Mock |
| 真实代码四角色/权限撤销 | PASS，复用 | v10-installed-live；真实API、工具、unittest、Diff |
| 真实Windows GUI | PASS，复用 | v10-installed-native-deepseek，真实UIA/保存/读回/截图/退出 |
| v0.9→v1.0升级、数据及卸载 | PASS，复用 | v10-fixed-upgrade-acceptance.log、独立build/v10-upgrade-*/report.json |
| 本机完整Python/GUI补测 | PASS，保留首轮失败 | 706首轮通过、2跳过，4项焦点失败解锁后全部补测通过；CI清洁全量710通过/2跳过 |
| 最新本机产物打包 | PASS，退出0 | v10-plan-a-package-resumed.log，复用已完成测试+4项补测；实包55项、Setup/Portable/更新/权限/聊天/无SDK/卸载/SHA均通过 |
| 干净Windows OS | NOT RUN，不要求 | 本机安装与PATH隔离不能冒充干净系统 |
| 同任务四角色+GUI组合 | 历史未通过，本轮不要求 | 失败详情原样留存history，不改成PASS |
| 自动安装/重启/回滚 | 不属于方案A | 用户手动安装 |

重跑（PowerShell，从仓库根目录）：

```powershell
$env:PYTHONUTF8='1'
.\scripts\build\package-windows.ps1 -ReuseDependencies
```

该命令全量Python/前端、冻结后端及原生worker、Electron55项、Portable/Setup启动/聊天/更新/权限/无SDK/重启/卸载，按阶段串行执行；发现已有用户安装时保护并拒绝覆盖。只清理本次自有进程与临时安装，不修改用户工程、原配置或系统内存。

单项脚本见scripts/validation/v10-plan-a-desktop.cjs、packaged_chat_smoke.cjs、v10-permission-desktop.cjs。前两项本地服务不使用模型密钥，不代表真实在线模型复验。当前安装产物与最终正式Release字节可能不同，SHA不可混用。
