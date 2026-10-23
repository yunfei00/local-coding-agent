# M1～M5 能力矩阵

| 能力 | 阶段 | 实现/当前验收 |
| --- | --- | --- |
| 单在线模型、多轮真实工具调用、文件修改、独立测试、Diff | M1 | 已实现；Mock 决策 + 真实工具自动验收 |
| Python/React/TypeScript/Electron 执行、后台进程与树清理 | M2 | 已实现；真实程序/进程验收，在线决策尚未验收 |
| Windows 会话、窗口身份、UIA、输入、截图、上传审批 | M3 | 已实现；真实 WinForms 验收，拒绝路径保留 |
| 冻结 GUI 合约、失败反馈修复、恢复、验收反篡改 | M4 | 已实现；真实 Windows GUI 多轮修复自动验收 |
| 统一 Profile、独立 Chat/Executor/Observer、同名连接路由 | M4 全面修复 | 已实现；HTTP/Windows 截图协议验收；见 m4/complete-validation.md |
| React+TS Electron Settings 双缺陷自主修复 | M5 | 本机真实 Electron 多轮修复、UIA、JPEG HTTP、Pause/Resume/Stop/拒绝/重启专项通过；最终门禁见 m5/end-to-end-acceptance.md |
| 用户百炼五项能力 | 历史用户证据 | 用户报告通过；非本轮新测试 |
| 本轮在线模型自主开发 | M4/M5 | NOT RUN，无本轮 Live 授权，不用 Mock 代替 |
