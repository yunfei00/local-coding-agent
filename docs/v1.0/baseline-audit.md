# v1.0 基线审计

基线：7325c04ea6b2b378ed446c4b5159161309aba6ca；2026-11-06 fetch 后 origin/main 无更新。分支 feature/v1.0-windows-release。原未跟踪附件和 egg-info 保留。

| 模块 | 现状与改造点 |
| --- | --- |
| Runtime | v0.9 统一入口、逻辑角色、后台队列、Checkpoint、真实验证可直接复用 |
| 权限 | 已有三档及统一 _authorize_tool；FULL_ACCESS 仍逐项审批，只有全局配置；需显式一次同意、项目/任务覆盖、撤销及审计 |
| Windows 工具 | 已有 UIA/视觉、窗口绑定、UAC/锁屏/敏感控件保护、worker 进程树释放；保留硬阻断 |
| 打包 | 现有 PyInstaller onedir + Electron NSIS/Portable，后端独立；脚本已有安装/卸载 smoke，但不是干净 OS 的完整在线验收 |
| 无 Git | project.create 已捕获 Git 初始化失败并保留工程；需补充无工具 PATH 的回归及中文提示 |
| 更新 | 只有 GitHub Release 检查/打开页面，缺下载、校验、任务保护和安装流程 |
| 数据 | SQLite schema6/WAL 与安全存储凭据；有未来版本拒绝，需升级备份、完整性检测、恢复入口 |
| UI | 原单聊天/Enter/滚动/按需面板可复用；权限入口英文且运行中禁用，需中文与实时撤销 |
| CI | Windows/Ubuntu 全量及桌面 smoke；发布 workflow 会上传 Setup/Portable。v1.0 候选构建不能自动发布 |

本轮权限单元基线见 validation-reports/v10-permission-baseline.log。Python 全程 uv run。

本机未发现 Get-VM、WindowsSandbox.exe，不能把 PATH 隔离测试称为干净 Windows 镜像。最终用户决策不要求干净OS；使用当前Windows真实安装与隔离PATH，差异记录为覆盖限制，不冒充干净系统通过。
