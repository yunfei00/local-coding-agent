# v1.0 架构

复用 v0.9 Unified Agent Runtime，不创建第二套执行循环。工具继续经 _authorize_tool → PermissionPolicy → 原注册表执行。

权限由 AuthorizationSettings 在原 SQLite 内持久化；全局默认、项目覆盖、任务临时覆盖按优先级解析。已绑定计划通过 permission_task_key 保留原任务授权；每次操作重新检查，可撤销。

桌面主进程负责原生授权确认、Windows安全存储、GitHub更新下载及安装。后端负责任务暂停、Checkpoint、SQLite一致性备份和迁移检查。两者不把启动安装器误报为升级成功。

Windows保留PyInstaller后端和Electron NSIS x64，Ubuntu只保留后端与测试，不构建安装包。
