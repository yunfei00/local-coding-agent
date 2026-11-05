# M1～M5 能力矩阵

2026-11-05：v0.7 Windows Computer Agent 专项见 [v0.7 验收](v0.7/acceptance-report.md)。窗口/UIA/输入/记事本/计算器/文件管理器与本地浏览器执行结果分别记录，真实模型视觉回退仍有失败及服务端 403 阻断；不把 Mock、坐标工具集成或图片接口成功当作真实视觉任务通过。

2026-11-04：v0.6 已实现运行中追加需求、关联事件与普通统一运行中断恢复。三个阿里云模型完成实际开发测试，Python、React、Electron、网络断流及原运行恢复已有证据。见 [v0.6 验收](v0.6/acceptance-report.md)中的逐项结果与未验证限制；下文历史矩阵保留原阶段证据。

2026-10-28 更新：下表保留阶段范围；当前源码/真实模型证据以[基础 Agent 差距审计](validation/basic-agent-gap-2026-10-28.md)、[阿里真实仓库验收](validation/alibaba-repository-acceptance-2026-10-27.md)为准。当前仍缺执行中追加指令、通用 Skills 和模型语义压缩，不宣称与 Codex 完全等同。

| 能力 | 阶段 | 实现/当前验收 |
| --- | --- | --- |
| 单在线模型、多轮真实工具调用、文件修改、独立测试、Diff | M1 | 已实现；Mock 决策 + 真实工具自动验收 |
| Python/React/TypeScript/Electron 执行、后台进程与树清理 | M2 | 已实现；真实程序/进程验收，在线决策尚未验收 |
| Windows 会话、窗口身份、UIA、输入、截图、上传审批 | M3 | 已实现；真实 WinForms 验收，拒绝路径保留 |
| 冻结 GUI 合约、失败反馈修复、恢复、验收反篡改 | M4 | 已实现；真实 Windows GUI 多轮修复自动验收 |
| 统一 Profile、独立 Chat/Executor/Observer、同名连接路由 | M4 全面修复 | 已实现；HTTP/Windows 截图协议验收；见 m4/complete-validation.md |
| React+TS Electron Settings 双缺陷自主修复 | M5 | 本机真实 Electron 多轮修复、UIA、JPEG HTTP、Pause/Resume/Stop/拒绝/重启专项通过；最终门禁见 m5/end-to-end-acceptance.md |
| 用户百炼五项能力 | 历史用户证据 | 用户报告通过；非本轮新测试 |
| 在线模型自主开发 | 后续独立实测 | 5 个模型通过受控真实仓库修复；失败尝试单列，见 2026-10-27 报告，不能倒填为早期 M4/M5 的真实验收 |
| 仓库 AGENTS 指令与持久执行事实 | 2026-10-28 源码 | 目录链指令先于目标工具、有界记忆随执行账本恢复；Qwen 5 次真实 API、2 项独立 unittest 通过，见基础差距审计 |
