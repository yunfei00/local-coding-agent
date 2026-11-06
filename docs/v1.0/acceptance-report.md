# v1.0.0 最终整合验收报告

日期：2026-11-06，北京时间。基础main：`7325c04ea6b2b378ed446c4b5159161309aba6ca`。现有分支`feature/v1.0-windows-release`，继续PR [#33](https://github.com/yunfei00/local-coding-agent/pull/33)，未创建第二套Runtime或新PR。

当前阶段：最新产品代码的本机打包与核心CI通过，正在完成最终文档提交和PR门槛；**尚未合并或正式发布**。发布资产与main SHA由合并及发布后的记录给出，不提前填写。最终用户决策：方案A、当前Windows实装、复用有效真实分项；干净系统和高成本四角色+GUI同任务组合不再是门槛。旧报告及失败完整保留在history/before-final-policy-*，没有把历史FAIL改成PASS。

## 功能与实现

| 范围 | 结果/范围 |
| --- | --- |
| M1 权限 | READ_ONLY/WORKSPACE/FULL_ACCESS；任务>项目>全局；首次一次确认、持久化、动态撤销、每次工具后端重查；角色/模型/恢复沿用有效授权；高风险和Windows边界保留 |
| M2 安装 | Electron+PyInstaller+NSIS x64、Portable；中文空格路径，内置后端，不依赖开发SDK启动；无Git可创建普通工程 |
| M3 首次体验 | 中文配置、已有多连接/模型保留、非必需依赖不阻断；不启动或测试Ollama |
| M4 稳定性 | 原Checkpoint/队列/有限修复/上下文/GUI互斥；DataLock、日志脱敏轮转；未知副作用不重放 |
| M5 更新 | 方案A：实际状态、稳定SemVer、官方源、流下载/进度/取消/磁盘检查、SHA与缓存重校验、用户手动打开；无自动暂停/退出/安装/重启 |
| M6 界面 | 单一聊天框、权限/模型/进度、关于内软件更新、工具/Git/Context按需展开 |
| M7 数据 | schema6→7一致性迁移、加密凭据保留、备份清单和离线恢复 |
| M8 安装验收 | 当前机器Setup/Portable真实运行，受控PATH无SDK/无Git；不宣称干净系统 |
| M9 发布 | 本机回归通过；等待最终文档提交的PR CI、main CI及正式资产构建下载复核 |

主要变更：`agent/permissions/authorization.py`、原PermissionPolicy和`agent/server/main.py`，`agent/core/unified_runtime.py`、`agent/persistence/{store,backup}.py`、`agent/desktop/worker.py`；`desktop/electron/{main,preload,updateManager,updateCheck,vaultFile,runtimeLog}.ts`、`desktop/src/components/{SettingsPanel,UpdateSettings,FirstRunCard}.tsx`；原App/样式、打包/安装/GUI/权限/升级验收脚本、Windows/Ubuntu及发布工作流。完整差异见PR，不复制Provider/工具/任务状态机。

## 最后整合修复

1. 移除旧方案B的安装器自动启动、退出和任务暂停路径，旧install IPC明确拒绝；打开仅用户操作触发。
2. 状态查询首次读取缓存覆盖AVAILABLE/ERROR的问题修复，缓存只在IDLE恢复。
3. 缓存缺失/篡改、JSON损坏、路径穿越和符号链接失败关闭；不回显损坏缓存内容。
4. 元数据响应中断补齐error/aborted处理及总超时，避免未处理异常；关闭窗口时安全发事件，用户退出取消下载。
5. SemVer数字精确比较，下载后/缓存恢复/手动打开三次校验。

## 自动化与实际产物

| 检查 | 已有/当前结果 |
| --- | --- |
| Windows Python | 本轮712运行首轮706 PASS、2 SKIP、2 FAIL+2 ERROR；4项受影响GUI补测全部PASS；Windows CI清洁全量710 PASS、2 SKIP、0 FAIL |
| Ubuntu Python | 本轮CI：712运行，695 PASS、17 SKIP、0 FAIL |
| React/TypeScript/Vitest | 当前63d9e16：22文件102 PASS、0 FAIL（更新器29+版本/元数据6已包含，不重复相加） |
| Electron smoke | 本轮Windows核心CI与本机最新实包均55 PASS、0 SKIP、0 FAIL |
| 类型/前端/Electron build | PASS，最新完整打包/安装/卸载完成 |
| 安装版方案A | 4项PASS：实际安装版UI/IPC/后端及真实HTTP下载/文件/SHA；受控Release元数据和shell打开回调，不执行测试安装字节 |
| 安装版权限 | 4项PASS：一次确认、拒绝、重启、撤销；确认选择Mock，IPC/后端真实 |
| Setup聊天/文件/重启 | PASS，两次实际安装版启动、4次Mock SSE请求；真实输入框Enter/WS/文件工具/读回，退出0，stripped PATH无SDK/无Git |
| Portable聊天/文件/重启 | PASS，两次便携包启动、4次Mock SSE请求；实际前后端及文件，退出0 |

本轮日志：`validation-reports/v10-plan-a-frontend-final102.log`、`v10-plan-a-full-package.log`；安装版报告`validation-reports/v10-plan-a-desktop/report.json`、权限报告与`build/v10-plan-a-{setup,portable}-chat/report.json`。完整打包脚本把上述补测纳入串行门禁，报告复制到`build/packaged-*-smoke.json`供CI留存。Mock模型测试只证明集成路径，不冒充在线模型验收。

## 真实模型和GUI：复用分项证据

本轮整合未发新的模型生成请求，更新改动不影响Provider/Agent模型路径。按用户决策保留此前分项：

- `v10-installed-live/workflow-python`：真实Qwen2.4t规划/独立审查、Qwen27B开发/测试，文件修改、unittest、Diff和四角色交接，completed_verified，普通审批0。撤销后拒绝写入且文件未生成。
- `v10-installed-native-deepseek`：产品1cfb010实际安装版，DeepSeek Pro真实UIA/窗口激活/输入/保存/读回/截图/停止；18请求214355实际Token，普通审批0、撤销有效、正常退出0、源码不变。不运行代码测试的GUI任务为completed_unverified，不冒充代码验证。
- 历史组合、超时、额度失败继续记录于history与evidence-summary.json；没有将其部分成功拼成组合PASS。旧合计144请求/2604305保守账本含未知Usage预留，不等于实际计费；本轮新增为0。

当前禁止qwen3.8-flash/qwen3.7-plus，不用别名规避；不重新调用已耗尽历史模型。无Ollama真实连接。API Key不写日志、文档或仓库。

## 数据与安装边界

历史真实v0.9 NSIS写入schema6后覆盖v1.0：schema7、聊天/计划/Checkpoint/记忆、加密凭据原件、用户文件和迁移备份均保留。卸载不默认删除用户数据。本轮只用自有build下安装路径与隔离资料，不覆盖现有用户配置；不结束无关程序、不改虚拟内存。

## 限制

未签名；未在干净Windows系统验收；未运行未来正式版本线上手动安装；高成本同任务四角色+GUI组合历史未通过，最新等待诊断在线复验曾被额度阻断。按最终决策，这些明确覆盖限制不单独阻止发布，不标PASS。不宣称24小时压力或自动回滚。用户工程仍可能需要自身SDK。

发布必须等待最后完整回归、PR和main CI，通过后用main源码构建并实际下载核对Setup/Portable/SHA。当前功能与实装门槛通过；PR最终提交、main及正式发布证据仍按实际流程检查。

## 本轮本机GUI失败与补测（21:55–21:59）

`v10-plan-a-full-package.log`保留原712项完整运行：706 PASS、2 SKIP、2 FAIL、2 ERROR，退出1。四项为M3控件操作、坐标回退、单Agent图像反馈及M5 Electron多轮恢复。工具记录DESKTOP_FOCUS_FAILED，Windows没有授予绑定窗口焦点，未发送客户区/键盘输入；Mock模型的断言因缺少GUI证据返回HTTP500，引出任务暂停。不能把Mock HTTP错误归咎真实API。

用户确认解锁后，会话只读检查INTERACTIVE_READY；仅重跑这4项，`v10-plan-a-gui-affected-retest.log`：172.760秒、4 PASS、0 FAIL，包含实际GUI、取消/恢复/重启。没有降低焦点保护、忽略断言或修改测试。不能仅凭后台存在LogonUI进程判定锁屏；首轮确证为焦点未授予。

为避免再次执行已通过706项和2个SKIP，本机从已完成测试证据继续打包，`v10-plan-a-package-resumed.log`明确标注复用完整首轮+4项补测。仓库正式打包脚本与CI未跳过任何测试。核心CI源码63d9e16：[push 42226827834](https://github.com/yunfei00/local-coding-agent/actions/runs/42226827834)、[PR 42226835466](https://github.com/yunfei00/local-coding-agent/actions/runs/42226835466)均Windows/Ubuntu全绿。前一方案A候选[42226380653](https://github.com/yunfei00/local-coding-agent/actions/runs/42226380653)完整安装门禁通过，最新63d9e16候选[42226827888](https://github.com/yunfei00/local-coding-agent/actions/runs/42226827888)亦成功，完成全部构建/安装/新补测及产物校验。

## 最新本机实际产物（22:06）

产品代码63d9e16；后续仅文档和报告归档路径变更。`v10-plan-a-package-resumed.log`退出0，WINDOWS PACKAGE BUILD PASSED。编译/冻结后端、模板接口、真实原生worker五操作、类型检查、102前端、55项实包Electron、Portable、Setup、权限4项、方案A4项、两种实际包各2次聊天/文件/重启、无SDK/无Git、卸载数据保留及SHA全部完成。完整首轮712与4项补测如前单独保留，未伪装成一次干净运行。

`build/packaged-{gui,permission,updater,setup-chat,portable-chat,setup-no-sdk,uninstall}-smoke.json`提供结果。Setup/Portable聊天各4次受控Mock请求、真实前后端/工具文件写入；更新下载真实字节，但受控元数据和shell回调，未自动执行任何安装器。原权限/数据系统及真实模型分项复用不受方案A变更影响。

本地候选（不是待发布main构建的最终字节）：Setup SHA256 `006d215d51a2cf19a47412f718a0666f4767c91a2de70dc47d14ec7c5d4d5752`；Portable `d0366afa1571d8cb2cc802baeb53e743bb41dfa2e992cb79645d51d51253dd2c`。正式下载必须比较同一Release的SHA256SUMS，不能混用本地候选值。

## 合并与发布检查点

2026-11-06 22:09：产品63d9e16的Windows/Ubuntu核心CI、最新Windows安装候选42226827888及本机实际包验收全部通过，功能/实装门槛PASS。没有发现未解决P0/P1。最新文档与Smoke证据归档路径提交还须重新通过PR检查；之后转Ready、合并并等待main CI。当前未创建Tag或Release。正式发布时从main构建、实际下载两种exe和SHA清单；最终main SHA/发布文件哈希以Release附带的发布校验记录为准。
