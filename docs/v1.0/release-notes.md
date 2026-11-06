# Local Coding Agent v1.0.0

仅发布Windows x64 Setup、Portable与SHA256SUMS.txt，Ubuntu继续保留后端兼容性CI，不提供Linux/macOS/ARM安装包。

- 统一聊天入口，复用自动规划、开发、审查、测试、修复与后台恢复。
- READ_ONLY、WORKSPACE、FULL_ACCESS统一后端决策；明确一次完全访问授权、全局/项目/任务覆盖、持久化、动态撤销和审计。普通授权操作不重复审批，高风险、凭据与Windows系统保护继续生效。
- 独立Electron/Python运行时，首次环境诊断；缺少Git仍可创建普通工程和聊天，不要求预装Python/uv/Node。
- 方案A软件更新：检查官方GitHub Release、流式下载、进度/取消、SHA256校验与缓存复核，用户手动打开安装。不自动退出、安装、重启或回滚。
- schema6→7一致性迁移、加密凭据保留、备份校验与离线恢复；日志脱敏和轮转。
- 修复冻结后端缺失工作流模板和动态时区模块、原生窗口激活、测试进程环境恢复、Windows备份连接释放，以及更新状态重置、元数据连接中断和窗口关闭竞态。

安装说明见windows-installer.md，操作说明见user-guide.md，验收结果见acceptance-report.md。实际发布状态以官方Release页面为准。

已知限制：安装包未签名；没有干净Windows系统验收；方案A未来线上版本手动安装未提前用虚构Release测试；同任务四角色+GUI组合历史未通过，新等待诊断在线复验曾被额度阻断。按用户最终决策复用真实分项、不重跑高成本组合，未执行项不标PASS。不宣称24小时压力或自动回滚能力。用户工程测试仍可能需要自行安装其开发依赖。
