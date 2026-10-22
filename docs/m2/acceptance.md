# M2 自动化验收

日期：2026-10-22（Asia/Shanghai）。基线 `833c7e6f03e8f579bc60fa2a05b58baf7248d69d`，分支 `feature/m2-project-execution`。

## 方法与真实性

`tests/test_m2_projects.py` 只用 ModelResponses 模拟模型决策，生产 Single Agent、Task Runtime、真实文件工具、Shell、Git、Worktree、VerificationEngine 均实际执行。审批由测试客户端通过真实 ApprovalManager 响应，不替换工具实现或伪造构建/测试结果。没有使用付费 API。

| 工程/场景 | 实际验收内容 | 证据 |
| --- | --- | --- |
| Python 故障工程 | 复用 `manual-fixtures/v04-local-first`；真实 read_file、失败 unittest、Patch、重测、Diff、独立验证；模型后续请求包含真实 FAILED | `EngineeringTests.test_python_actual_failure_feedback_patch_unittest_diff` |
| React + TypeScript | 新增 `manual-fixtures/m2-react-ts`；真实 npm ci、TS2322、修复类型、node:test 数学断言失败、第二次修复、npm test、tsc + Vite build、真实 Vite HTTP 首页和转换模块探测、关闭服务与端口 | `test_react_typescript_multiround_repair_build_server_and_stop` |
| Electron | 新增 `manual-fixtures/m2-electron`；真实 npm ci、失败 node:test、修复、重测、真实 Electron browser/main process 启动，验证真实版本与 Electron/Node/Python PID；显式停止、Task.resume 后 Task.cancel、TTL、scope 清理均检查 PID 已退出 | `test_electron_real_main_node_python_descendants_stop_and_cancel` |
| 模型失败与正常结束 | 后台进程未显式停止时，模型异常或正常结束都会清理所属范围 | `test_model_failure_after_background_start_cleans_turn_scope`、`test_normal_model_finish_cleans_unstopped_background` |
| 终端基础与持续输出 | PowerShell、CMD、默认 Shell，含空格/中文工作目录及文件名、真实非零退出码、UTF-8 跨 chunk、有界尾部与实际日志、后台游标轮询、句柄隔离 | `tests/test_m2_processes.py` |
| 取消与超时 | 前台取消、后台 TTL、正常父进程退出、输出回调断开，均验证所属 Node/Python 后代退出；POSIX 忽略 TERM 的同组后代也终止 | `ProcessTests`，平台限定测试分别在 Windows/Ubuntu 执行 |
| Git hook | 真实 pre-commit hook 启动 Node/Python，取消 Git 操作后验证后代退出 | `test_git_hook_cancel_cleans_real_node_python_descendants` |
| 风险命令 | npm 脚本及 pre/post hook 风险检查；真实拒绝审批后 sentinel 保留、无进程启动；Read Only 与外部工作目录边界 | `tests/test_m2_permissions.py` |
| M1 兼容 | 原有 Single Agent HTTP 协议、失败反馈、取消、有限修复与多角色/Local-first 测试保留 | 全量 Python 回归 |
| Desktop | 原有 desktop-smoke；新增 TerminalCard 渲染后台输出、PID/Shell/日志与超时状态的单测；没有新增截图或输入自动化产品功能 | `desktop/src/components/ToolCard.test.tsx`、`scripts/validation/desktop-smoke.cjs` |

测试不会杀死全机所有 node.exe/python.exe/Electron 进程。只记录并检查测试创建的 PID 与所属进程树，避免影响用户已经打开的应用。PID 存活检查使用 Windows OpenProcess/GetExitCodeProcess，POSIX 检查 PID/非僵尸状态；真实端口通过连接失败确认关闭。

## 自动执行

```powershell
uv run python -m unittest discover -s tests -p "test_m2*.py" -v
uv run python scripts/validation/check.py
node scripts/validation/desktop-smoke.cjs
uv run python -m compileall -q agent
git diff --check
```

`check.py` 运行全部 Python、Desktop typecheck、全部 Vitest 与源码 build。CI 在 Windows/Ubuntu 使用 uv run；Linux 为真实 Electron 无窗口测试准备 Xvfb，Windows 额外跑真实 Electron desktop-smoke。各工程的执行结果、真实输出、Diff、执行元数据与清理事件保留为 `validation-reports/m2-project-*.json`，CI 上传对应 artifact；本地日志和临时依赖不提交。

本轮修复的回归问题：CMD 参数引号、失败指纹被随机进程 ID 干扰、旧检查点误阻止恢复后重新启动服务器，以及原工具清单测试需要包含新增工具。

## 本地最终结果

| 检查 | 结果 |
| --- | --- |
| `validation/check.py` | Errors: 0，全部阶段退出码 0；报告 `validation-reports/20261022-223227-908043.json` |
| 全量 Python | 291 项，OK（1 项 POSIX 限定测试在 Windows 跳过） |
| 后补专项 | 最终进程专项 13 项 OK（同一 POSIX 项跳过），包含全量之后补充的“父进程退出后输出消费者异常不能算成功”用例；最终测试集合 292 项由 CI 全量覆盖 |
| Electron 恢复与日志 | 独立重跑通过；Task.resume 后真实应用重启、Task.cancel 清理，以及两次 start_process 进程日志均核对 |
| Desktop | typecheck 通过；11 个测试文件、38 项 Vitest 通过；源码 build 通过 |
| desktop-smoke | 26 项通过，`ok: true`、`skipped: []`；最终日志 `validation-reports/m2-desktop-smoke-final.log` |
| compileall / diff --check / 暂存凭据扫描 | 通过 |

远端 Windows/Ubuntu CI 必须通过才合并 PR，实际检查和 artifact 见此变更的 GitHub PR。无 Tag、Release 或安装包。既有未跟踪 `local_coding_agent.egg-info/` 不属于本次修改，不提交、不删除。

## M3 启动条件

M2 提供受管理应用进程、PID/句柄/所属范围、状态和输出事件、取消、日志与失败诊断，适合 M3 关联窗口与应用生命周期。M3 的窗口枚举、截图、视觉识别、鼠标键盘、焦点和权限接口尚未实现，需另行设计与自动化验收。M2 不以这些功能作为完成条件。

边界与遗留限制详见 [实施说明](implementation.md)：非 PTY、进程不跨轮次保存、POSIX 特殊 daemon/强制杀 Agent 的边界、审批启发式及输出限制。
