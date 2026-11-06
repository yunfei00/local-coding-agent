# v1.0 架构

复用 v0.9 Unified Agent Runtime，不创建第二套执行循环。工具继续经 _authorize_tool → PermissionPolicy → 原注册表执行。

权限由 AuthorizationSettings 在原 SQLite 内持久化；全局默认、项目覆盖、任务临时覆盖按优先级解析。已绑定计划通过 permission_task_key 保留原任务授权；每次操作重新检查，可撤销。

桌面主进程负责原生授权确认、Windows安全存储、GitHub更新下载及安装。后端负责任务暂停、Checkpoint、SQLite一致性备份和迁移检查。两者不把启动安装器误报为升级成功。

Windows保留PyInstaller后端和Electron NSIS x64，Ubuntu只保留后端与测试，不构建安装包。

## 主要实现文件

| 范围 | 文件/扩展点 |
| --- | --- |
| 统一授权 | agent/permissions/authorization.py；原 PermissionPolicy 与后端 _authorize_tool |
| 数据迁移 | agent/persistence；schema7、SQLite一致性备份、DataLock、离线检查与恢复 |
| 更新 | desktop 主进程 updateManager、IPC/preload、后端 maintenance RPC |
| 凭据/日志 | 原 safeStorage；vaultFile 原子读写保护、运行日志脱敏与轮转 |
| 首次体验/权限 | 原 React Settings、聊天工具栏、FirstRunCard，不增加新的 Agent 模式 |
| Windows | 原 desktop worker；新增冻结依赖完整性与目标窗口异常诊断 |
| 构建 | scripts/build/package-windows.ps1、Windows candidate 与 release workflows |
| 安装验收 | packaged_agent_smoke.py、packaged_gui_smoke.py、v10-permission-desktop.cjs、v10-upgrade.ps1、unified_live.py |

测试用原生 WinForms 程序只提供输入、保存和状态显示，不包含被测计算器实现。在线验收中代码、测试及交付报告由产品 Agent 生成；外部脚本只准备工程、提交目标与独立核对结果。
