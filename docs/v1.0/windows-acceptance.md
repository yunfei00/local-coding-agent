# Windows 安装与 GUI 验收

日期：2026-11-06。系统为家中 Windows 开发电脑，物理内存约16GB。全部大型测试串行，产品 Electron 同时最多一个实例，原生测试窗口只用于本次隔离验收。未改系统虚拟内存、安全策略或用户模型配置。

## 已实际执行

| 项目 | 结果 | 证据与边界 |
| --- | --- | --- |
| Windows x64 Setup、Portable 构建 | PASS | 内置 Python 冻结后端、前端和依赖，非开发启动 |
| 中文/空格安装路径启动 | PASS | 实际 NSIS 安装目录含“安装目录 含空格” |
| 无外部 SDK PATH 启动 | PASS | PATH 隔离 Python/uv/Node/Git，实际安装版启动 |
| 无 Git 创建工程 | PASS | 创建普通工程和数据，不把 Git 初始化失败变成项目失败 |
| 安装版关闭、重启、数据保留 | PASS | 两次复用隔离数据目录及数据库断言 |
| v0.9 → v1.0 覆盖升级 | PASS | 真正旧版安装包启动、schema6资料、新安装包覆盖、启动后schema7核对 |
| 卸载后数据保留 | PASS | 本机独立资料保留；CI另测默认AppData合成资料 |
| 官方无更新检查 | PASS | 实际安装版请求GitHub Releases，无更高正式版本 |
| 权限IPC持久化与撤销 | PASS | 安装版主进程、后端与重启；原生确认选择使用Mock，不冒充真人点击 |
| 冻结后端原生UIA保存闭环 | PASS | 真实窗口发现、聚焦、输入、点击保存、文件和UIA结果核对，共5次操作 |
| 1cfb010安装版在线模型GUI分项 | PASS | DeepSeek真实输入/保存/读回/截图/stop，18请求214355实际Token，普通审批0 |
| 同一任务开发+四角色+GUI组合 | BLOCKED | wait条件未通过；9bfff23诊断增强的首个复验请求额度耗尽，无工具执行 |
| 干净无SDK Windows镜像 | BLOCKED | 本机未发现可用Sandbox/Hyper-V/VirtualBox/VMware/QEMU；PATH隔离不能替代 |
| 应用内有更新下载→安装→重启 | NOT RUN | 单元故障分支和手动覆盖升级已测，尚无真实新版本完整路径证据 |

在线模型驱动代码与GUI的结果见 acceptance-report.md；本表的“冻结后端原生UIA”不含模型，不计为在线端到端通过。

## 本机证据

- `validation-reports/v10-installed-acceptance-fixed.log`：安装、Portable、无SDK、重启、卸载、校验。
- `validation-reports/v10-fixed-upgrade-acceptance.log` 及 `build/v10-upgrade-35b975aa9cb940cba29587d4826998d9/report.json`：最新候选真实升级，所有迁移断言通过。
- `validation-reports/v10-permission-desktop-fixed/report.json`：四项安装版权限检查通过，正常退出，不强杀进程。
- `build/packaged-installed-gui-smoke.json`：最新安装版冻结后端真实原生操作全部通过。
- `validation-reports/v10-frozen-uia-diagnostic/report.json`、`v10-timezone-causal-probe/report.json`：源码窗口可见、冻结版不可见，以及补入动态模块后恢复的对照。
- `validation-reports/v10-clean-windows-environment.json`：可用干净Windows环境检查。
- `validation-reports/v10-installed-native-deepseek/report.json`：最后修复后的真实模型GUI通过，源码/原测试/HEAD不变，代码测试未运行，进程正常退出。
- `validation-reports/v10-final-uninstall-data-protection.json`：最新安装版实际卸载成功，两个隔离迁移数据库保留，原用户数据库哈希不变。
- `validation-reports/v10-last-uninstall-data-protection.json`：9bfff23安装版再次卸载成功，两个隔离迁移数据库及原用户数据库哈希保留。

原始失败保留：早期单次模型请求超时；旧候选冻结版遗漏win32timezone导致窗口列表为空；锁屏造成GUI用例无法执行。解锁后才补测，未把这些运行计为PASS。

另一项真实恢复补测发现“不是开发任务”被误识别成开发，GUI保存后错误启动工程测试及修复。新增7项回归并修复后才进行最后DeepSeek补测；失败记录仍保留，不能合并为通过。模型端两个Qwen额度耗尽后没有再调用，QwenMax的120秒超时单列。

最后纯GUI任务内部状态为 completed / completed_unverified / level none：产品没有独立GUI验收合约，不能声称运行了代码测试。外部验收依据真实保存文件、控件状态、截图和退出证据判为GUI PASS；两种状态表达不混淆。

后续组合任务没有整体通过，不能以各分项成功替代。9bfff23的等待超时反馈增强通过单元测试，但真实恢复首请求被API额度阻断，因此仍需在线复验。所有失败/取消记录保留，原始任务未被重写成完成。

## 可复制定向命令

```powershell
$env:PYTHONUTF8 = '1'
uv run --locked python -m unittest discover -s tests -v
npm.cmd --prefix desktop run typecheck
npm.cmd --prefix desktop test
node scripts/validation/desktop-smoke.cjs
.\scripts\build\package-windows.ps1 -ReuseDependencies
# 使用实际安装目录中的内置后端；测试只创建并清理自己的原生窗口。
$backend = Read-Host '输入安装目录 resources\agent\lca-agent.exe 的完整路径'
uv run --locked python scripts/validation/packaged_gui_smoke.py $backend --output build/packaged-installed-gui-smoke.json
```

真实在线驱动需要 --live、明确白名单、有限请求/Token/超时和实际安装路径；凭据由隔离Electron配置读取加密原件，不在命令行传Key。驱动只准备测试工程，不能代替Agent编写被测功能。

本机GUI解锁不等于具备干净Windows虚拟机。未满足必需安装/更新门槛前保留候选和PR，不合并或发布正式版。
