# v1.0 Windows 正式版验收报告

日期：2026-11-06（北京时间）。**发布结论：BLOCKED，保留 PR，不合并 main，不创建 Tag 或正式 Release。** 缺少干净 Windows 镜像验收、真实有更新的应用内升级闭环，且同一任务串联开发/四角色/GUI的组合验收仍未完成，最后复验被API额度阻断。单项通过不等于正式版全部通过。

基础 main：`7325c04ea6b2b378ed446c4b5159161309aba6ca`。开发分支：`feature/v1.0-windows-release`。PR：[#33](https://github.com/yunfei00/local-coding-agent/pull/33)。产品版本1.0.0仅表示候选版本号。

本机：Windows 11家庭版中文版，10.0.26200，约16GB；uv 0.11.2、Python 3.12.13、Node v24.14.0、Electron 38.8.6。CI按仓库工作流使用Windows/Ubuntu、Python3.12和Node22。具体脱敏环境记录见 evidence-summary.json。

## M1–M9

| 模块 | 实现与验收 |
| --- | --- |
| M1 统一权限 | 三档权限、首次持续授权、全局/项目/任务覆盖、动态撤销、审计；真实代码/GUI分项普通审批0，高风险仍保护；严格同一任务完整组合仍BLOCKED |
| M2 独立安装 | Electron + PyInstaller onedir + NSIS x64，真实安装/Portable/中文空格路径/无SDK PATH/无Git工程/卸载数据保留通过；干净OS仍BLOCKED |
| M3 首次体验 | 中文环境卡、选择/创建工程、多连接模型配置、保存连接检查，不因缺少Git/开发SDK阻止主界面；保留原配置 |
| M4 稳定性 | 复用队列、Checkpoint、上下文/预算/循环保护，新增脱敏轮转、DataLock、冻结UIA诊断和安全聚焦；组合任务被未解决的wait条件挡住，诊断增强尚未在线复验；未宣称24小时压力通过 |
| M5 更新 | GitHub稳定更新、用户两次确认、受限下载、SHA重校验、任务暂停与备份、重启版本凭据；12项单测及真实无更新检查通过，有更新完整线上路径NOT RUN |
| M6 界面 | 同一聊天入口、中文权限选择/撤销、首次诊断、更新/备份入口、模型布局修复，保留原Git/Context/MCP与滚动/发送行为 |
| M7 数据安全 | schema6→7真实覆盖升级、SQLite一致性备份、加密凭据原件保留、备份清单哈希与离线恢复、损坏/未来版本拒绝通过 |
| M8 真实安装 | 本机与CI实际NSIS；代码四角色和1cfb010安装版DeepSeek GUI分项通过；严格单任务组合及最新等待诊断在线复验BLOCKED，干净OS阻断 |
| M9 发布 | 候选构建、校验与PR已准备；未满足正式发布门槛，未合并/打Tag/发布 |

## 自动化测试

最终产品代码 `9bfff2335530e90ae24b755f1d4fc59d8ba4286a` 的已完成去重全量：

| 检查 | 结果 |
| --- | --- |
| Windows Python | 712运行，710 PASS、2 SKIP、0 FAIL |
| Ubuntu Python | 712运行，695 PASS、17 SKIP、0 FAIL |
| React/TypeScript/Vitest | 22文件、84 PASS、0 FAIL |
| Electron实际任务Smoke | 55项PASS、0 SKIP；模型决策使用Mock，真实窗口/文件/进程，不算真实付费模型验收 |
| 类型检查、前端/Electron构建 | PASS |
| 冻结原生worker | 5个真实操作PASS；无模型 |
| 安装版权限IPC | 4项PASS；原生确认选择Mock，真实IPC/后端与重启 |
| 更新器 | 12项单测PASS；官方无更新检查PASS；有更新线上安装NOT RUN |

最终代码Windows/Ubuntu CI：[run 42194575907](https://github.com/yunfei00/local-coding-agent/actions/runs/42194575907)，包含类型检查、前端构建与55项Electron实际任务Smoke，全部通过。完整Windows安装候选：[run 42194575897](https://github.com/yunfei00/local-coding-agent/actions/runs/42194575897)，712项、冻结原生操作、安装/重启/无SDK PATH/无Git工程/卸载保留数据及校验全部通过。历史701/708项不代替最后712项。

GUI范围新增7项、等待诊断新增4项回归全部PASS，已包含在712项中；受影响的统一Runtime45项、Computer16项、模型路由22项、等待/窗口套件10项均PASS，验收驱动5项PASS。这些定向数不能再加到去重全量上。1cfb010安装版DeepSeek纯GUI分项通过，后续组合失败保留。

## 真实在线模型与历史失败

凭据由安装版Electron安全存储读取；报告不含Key。使用原配置的阿里兼容连接，仅在独立测试资料中选择模型与预算，没有改用户设置。历史能力证据保留原时间，不能充作本轮新探测。未调用禁止模型，没有Ollama真实测试。费用接口未提供，标为未知；失败/未知Usage保留保守预留，不计成零。

| 运行 | 真实结果 |
| --- | --- |
| v10-installed-live / workflow-python | PASS。Qwen27B开发/测试、Qwen2.4t规划/独立审查，真实文件修改、unittest、Diff、四角色交接及completed_verified；普通审批0 |
| 同运行 / revocation | PASS。撤销后写入被拒、目标文件未生成，被拒任务如实failed |
| 同运行 / native-gui | FAIL。第一模型请求60秒超时，未执行GUI；不得当PASS |
| v10-installed-native-retest | FAIL。旧冻结包丢失win32timezone，窗口发现为空，最终重复动作保护停止；12请求116169实际Token |
| v10-installed-release-task | BLOCKED（原始驱动FAIL）。Qwen2.4t返回HTTP403/MODEL_QUOTA_EXHAUSTED，2请求，保守账本50041；停止再用该模型 |
| v10-installed-release-task-27b | 未完成。10请求150661实际Token后，下一请求保守预留88731超过本次224994限制，未发送；真实代码和测试保留 |
| v10-installed-release-resume | BLOCKED（原始驱动FAIL）。原任务正常追加预算并保留完成步骤；Qwen27B返回额度耗尽；仅再发1请求，保守预留55868 |
| v10-installed-native-max | GUI操作PASS，原运行未完成。QwenMax实际输入/保存/读回/截图；12请求139506实际Token，收尾前触及本次12次上限 |
| v10-installed-native-max-resume | FAIL。8新增请求119875实际Token后完成，但错误执行了无关代码测试/修改，不满足纯GUI约束；不能将模型声称completed_verified当本用例PASS |
| v10-installed-native-final | BLOCKED（原始驱动FAIL）。修复后正确识别interaction，但QwenMax首请求120秒超时，无工具执行；1次请求保守预留31821 |
| v10-installed-native-deepseek | **PASS**。最新1cfb010实际安装版，DeepSeek真实启动/发现窗口/激活/UIA/输入/保存/读回/截图/停止，18请求214355实际Token；代码/原测试/HEAD均不变，无代码测试，普通审批0，撤销成功，正常退出0 |
| v10-installed-comprehensive-deepseek | BLOCKED。组合任务首请求即HTTP403/MODEL_QUOTA_EXHAUSTED，1次、35279保守Token，无工具执行 |
| v10-installed-comprehensive-flash | 未完成。新候选真实文本/工具探测通过后执行组合任务；27请求含2次探测，537971实际Token。代码与外部独立测试通过、GUI文件已保存；Planner完成，Developer未完成，Reviewer/Tester未执行。下一次保守预留超限，请求未发出 |
| v10-installed-comprehensive-flash-resume | 未完成。原任务恢复，新增12请求、345362保守Token；到验收控制器调用上限后由控制器取消，不是用户手工取消；保留原始记录，不将它称为任务完成 |
| v10-installed-comprehensive-flash-final | FAIL。新增21请求、534285保守Token，最终PLAN_TOOLS_UNRESOLVED：desktop_wait超时没有同类成功复验。Planner仍完成，其余阻断；没有伪造通过 |
| v10-installed-comprehensive-flash-diagnostic | BLOCKED。安装9bfff23诊断修复后恢复同一任务，首请求额度耗尽；新增1次、64316保守Token，无工具执行，故新的错误反馈未被真实模型复验 |

第一组3用例合计18请求，208796保守Token（包含首个超时的预留，不能当全为实际Usage）；其余行相互独立或明确为增量，不能把累计账本重复相加。

最后GUI的成功保存值和截图来自真实桌面工具，不是Codex直接写结果文件。实际图片也已独立查看，包含对应“已保存”状态。内部completed_unverified/level none表示没有独立代码测试合约，外部GUI验收依据文件、控件、截图和退出判PASS，不能冒充代码测试通过。模型超时、额度、验收脚本预算不足、源码缺陷分别记录，没有增加产品默认预算掩盖问题。

本轮上述记录合计144次模型生成/工具请求尝试（不含模型列表等连接GET），保守账本2604305 Token；含超时、控制器取消和403未获得准确Usage的预留，**不是全部实际计费Token**。已发送失败请求不记为零，恢复不清空账本；历史能力探测未重复计入，新Flash两次探测已计入。费用接口未提供，不能给出虚构金额。只有分项及明确满足各自合同的运行记PASS，未把组合任务的开发/GUI局部成功拼成整体PASS。

## 本轮根因与修复

1. 冻结包缺工作流JSON：PyInstaller显式添加绝对资源路径，真实WS模板接口作为打包门禁。
2. 冻结包缺动态win32timezone：源码可见同一窗口、冻结不可见的对照确认；补模块后真实发现/聚焦/输入/点击/读回均通过。目标PID身份失败现在报具体环境错误，不静默返回空列表。
3. Windows前台激活失败：普通激活失败后只可点击同一已校验窗口暴露的原生标题栏；不点客户区/遮挡窗口、不改系统前台策略。
4. 测试环境恢复为空的ELECTRON_RUN_AS_NODE仍启用Node模式：缺失变量改为真正删除，保留退出码和自有子进程证据。
5. 安装器实际卸载名/注册表名带版本：兼容实际NSIS命名并保护已有安装，不误判Portable/覆盖用户安装。
6. GUI否定开发意图与恢复边界：“不是开发任务”不应触发开发；恢复按原目标收窄GUI范围，GUI保存数据不触发无关工程测试，代码写入/终端修复在工具层拒绝，真实界面证据仍必需。
7. Windows备份连接生命周期、分离凭据目录恢复、模型布局与Git危险refspec保护等均有回归。
8. 组合任务中的desktop_wait反复超时。原错误不含观测差异，新增脱敏的当前控件名称/稳定ID、精确相等（不支持正则/前缀）说明，保护敏感/编辑内容和异常文本；仍必须真正满足等待条件，不忽略失败。新增4项测试，等待/窗口套件10项及Computer16项通过；真实模型复验首请求被额度阻断，不能宣称这项已在线解决。

主要文件：`agent/permissions/authorization.py`、`agent/permissions/policy.py`、`agent/server/main.py`、`agent/core/unified_runtime.py`、`agent/persistence/backup.py`、`agent/persistence/store.py`、`agent/tools/delete_file.py`、`agent/desktop/worker.py`；桌面 `main.ts/preload.ts/updateManager.ts/vaultFile.ts/runtimeLog.ts`、`App.tsx/SettingsPanel.tsx/FirstRunCard.tsx/styles.css`；打包与验收脚本、NSIS/CI工作流及新增权限/备份/GUI范围测试。复用原Runtime、计划/Checkpoint、Provider、Git Worktree、MCP和工具审批，没有第二套执行器。

## 迁移、构建与交付

真实v0.9安装包启动并种入schema6资料，再覆盖安装v1.0，安装版自身迁移到schema7；聊天、待执行计划、Checkpoint、记忆、加密凭据、工程文件与迁移备份均通过。旧资料只用于隔离测试，不覆盖用户工程或历史。

`1cfb010`候选已从GitHub Actions实际下载并核对两份SHA256，artifact ID `13490211076`、[run 42188962308](https://github.com/yunfei00/local-coding-agent/actions/runs/42188962308)，保留14天，不是Release：

| 文件 | 下载候选SHA256 |
| --- | --- |
| Local-Coding-Agent-1.0.0-x64-Setup.exe | d15059493daa0cc823dd41e7e4ad7a1f73fbaf1f79f9d222dd876fdd92e3a536 |
| Local-Coding-Agent-1.0.0-x64-Portable.exe | f10b64b78f32cea361d5cc42bde585f67848d518b5cea63fb32c37a8cc437c2d |

本地构建与CI构建字节不同，不能混用校验文件。最后代码修复后的候选校验和以其自身SHA256SUMS和新CI为准。

最新9bfff23本地实际构建/安装/卸载的候选（不是上述已下载的历史CI字节）：

| 文件 | 本地最新SHA256 |
| --- | --- |
| Local-Coding-Agent-1.0.0-x64-Setup.exe | 7c5fd84774f5445650765b10faf947a6da3f381806079e11296a571d2666c80c |
| Local-Coding-Agent-1.0.0-x64-Portable.exe | 333214706dab4f110706e7834d912b5527d0fde4c2c6cd49358b64f9e7359ebd |

对应本机 `desktop/release/SHA256SUMS.txt`；实际安装后的后端哈希与本地冻结构建一致。最后卸载退出0、两个隔离迁移数据库保留、原用户数据库哈希不变。本次创建的测试进程最终为0。完整脱敏摘要见 evidence-summary.json；不提交私有原始日志和截图。

## 未完成与风险

- **BLOCKED**：无可用干净无SDK Windows虚拟机/隔离OS；本机PATH隐藏和有SDK的Windows CI不能冒充该项。
- **NOT RUN**：官方新版本应用内下载→校验→安装→重启完整成功路径；单元Mock及手动覆盖升级不能替代。
- **BLOCKED**：同一任务串联完整开发/审查/测试/GUI尚未通过；最后9bfff23的等待诊断反馈被Flash额度耗尽阻断，不能以1cfb010的GUI单项成功替代。恢复保留Planner完成和既有文件/测试，不伪造Reviewer/Tester完成。
- 本轮已测的Qwen27B/Qwen2.4t/DeepSeek Pro/DeepSeek Flash均出现额度阻断，QwenMax出现请求超时；这不表示其他未测白名单模型都不可用。停止继续尝试新模型，保留有界失败证据，不无限消耗额度。
- 安装包无发行者签名；不绕过SmartScreen/UAC。无已验证自动回滚，不保证DPAPI凭据跨Windows账户恢复。
- 终端风险规则不是Windows OS沙箱；长时间24小时内存压力未验证。

保持main不变、PR为草稿，不创建正式下载链接。全部必需门槛通过后才可另行合并/发布。本机完整脱敏摘要与命令日志在 `validation-reports/v10-*`；原始凭据、截图、用户目录与完整模型Prompt不提交GitHub。
