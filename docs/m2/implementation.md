# M2：真实工程操作与终端执行可靠性

基线 `833c7e6f03e8f579bc60fa2a05b58baf7248d69d`（M1 / PR #12），分支 `feature/m2-project-execution`。复用 `AgentServer.run_tool_turn`、Single Agent、Task Runtime、权限、Worktree 与 VerificationEngine；未新增 Agent Loop、模型路由或预算功能。原多模型与 Local-first 保留。

## 能力矩阵与代码证据

| 能力 | M1 基线 | M2 实现及证据 |
| --- | --- | --- |
| 单在线模型执行与错误反馈 | 已实现 | 保留同一循环与 Provider；Python、React/TS、Electron 实际修复见 `tests/test_m2_projects.py::EngineeringTests` |
| Windows PowerShell | 部分：固定 Shell、缺少明确选择 | 已实现显式 `shell=powershell/auto`，UTF-8、原生命令退出码、缺失 Shell/工作目录诊断；`agent/tools/processes.py::shell_command/ProcessManager.launch`，`test_m2_processes.py` |
| Windows CMD | 未实现工具参数 | 已实现 `shell=cmd`，禁用 AutoRun，以本地命令脚本保留原生引号/变量语义；空格、中文路径与非零退出码使用真实 CMD 验证 |
| 跨平台命令 | 部分：优先 pwsh 可能改变 Linux 默认行为 | 已实现 POSIX 默认 Bash `-c`，不使用登录 Shell 重置 PATH；显式 PowerShell 可用时选择，缺失时明确报错 |
| 长运行/持续输出 | 部分：只能等待，最多 600 秒 | 已实现 1–86400 秒，默认 120 秒；前台与后台统一执行层，增量 UTF-8 解码、stdout/stderr、单调序号、有界尾部与日志；`agent/tools/processes.py` |
| 开发服务器生命周期 | 未实现 | 已实现 `start_process/read_process/stop_process`；返回不代表就绪，通过真实输出/HTTP 探测判断；`agent/tools/shell.py`、`ToolRegistry` |
| 所属范围与结束清理 | 部分：前台命令取消 | 已实现不可猜测的进程句柄、同轮次/工作区校验；正常结束、模型失败、取消、暂停、TTL 和服务关闭均进入清理；`run_tool_turn` 的 finally、`close_owner`、`close_async` |
| Windows 进程树 | 部分：启动后才分配 Job，存在抢先生成子进程的窗口 | 已实现 CREATE_SUSPENDED → 分配 KILL_ON_JOB_CLOSE Job → 恢复线程；先拥有再执行；`agent/tools/windows_job.py::WindowsJob.resume`；实际 Electron/Node/Python PID 检查 |
| POSIX 后代清理 | 部分：父进程退出即返回，可能留下管道持有者 | 已实现独立 session/process group，父进程退出后仍清理组；TERM 后 KILL，不因父进程先退出而漏掉忽略 TERM 的同组后代 |
| Git hook 超时/取消 | 部分：只 kill Git 父进程，取消未清理 | 已实现 Git 直接 argv 复用 ProcessManager；真实 pre-commit hook 的 Node/Python 后代取消测试；`agent/tools/git.py::_git` |
| 文件/Workspace | 已实现 | 保留真实读取、精确 Patch、路径约束及 Full Access 外部路径审批；所有工程测试通过生产工具改文件；`filesystem.py`、`workspace.py` |
| 项目识别 | 部分：Python/Node/Android/CMake | 已实现 React、TypeScript、Electron 标记与 typecheck/dev/start 提示；不再把任意 pyproject 当作 pytest；Python 建议使用 uv；`project_detection.py` |
| 危险命令确认 | 已实现直接命令风险判断 | 增加 start_process 同等检查、npm 直接脚本与 pre/post hook 递归风险检查、发布检测；实际拒绝审批后不启动进程；`permissions/policy.py::project_command_risk`、`tests/test_m2_permissions.py` |
| 多轮修复与防循环 | 已实现基础限制 | 保留重复调用、短循环、连续失败与模型轮数上限；只对有 TTL 的输出轮询增加有限次数；失败指纹只比较失败证据，避免随机进程 ID 破坏无进展判断 |
| 检查点恢复 | 已实现文件操作防重放 | 保留文件修改防重放；进程句柄不持久恢复，明确恢复任务可以启动新进程；`task_plans.py::mutation_fingerprint`，Electron Task.resume → Task.cancel 实测 |
| Diff 与独立验证 | 已实现 | 保留冻结验证命令、空测试检查与工作区指纹；Git 输出超出捕获上限报 GIT_OUTPUT_LIMIT，不接受局部 Diff 冒充完整结果；`verification.py`、`git.py` |
| 执行日志与诊断 | 部分：流式结果、验证日志、模型日志 | 新增本地命令日志、进程状态元数据、任务执行日志引用；超时保留部分输出；诊断导出含允许字段的 executions；Desktop Terminal 显示进程 ID/PID/Shell/日志路径 |
| 桌面截图/鼠标/键盘 | 未实现 | 未实现；留给 M3。只运行已有 desktop-smoke 回归，没有新增生产桌面自动化能力 |

## 工具接口

```json
{"name":"run_command","arguments":{"command":"npm run build","shell":"auto","cwd":".","timeout_seconds":600}}
{"name":"start_process","arguments":{"command":"npm run dev","timeout_seconds":1800}}
{"name":"read_process","arguments":{"process_id":"<返回句柄>","cursor":0,"wait_seconds":5}}
{"name":"stop_process","arguments":{"process_id":"<返回句柄>"}}
```

`start_process` 返回 `data.process_id`、PID、状态、日志路径、`next_cursor`。`read_process` 的 cursor 为上次返回的 next_cursor，新输出放在带游标的 chunks；stdout/stderr 是有界尾部。仅接受当前执行轮次创建的句柄，不接受任意系统 PID。后台进程最多同时 8 个，每个 Registry 最多保留 64 个会话；轮次结束会删除句柄、停止进程，日志继续保留。

开发服务器应由 `start_process` 启动、根据 read_process 输出或 HTTP 探测确认就绪，执行测试后 stop_process。不要用脱离管理的 daemon、Start-Process、nohup/disown 代替受管理句柄。单纯读到 “started” 不构成应用可用的证据。

Windows Job 在恢复子进程之前建立。正常命令结束时也清理后代，解决父进程已退出但后代仍持有输出管道的等待。POSIX 清理使用创建时确定的进程组 ID，不在父进程退出后重新查询不存在的 PID。

## 日志与诊断

日志存放于应用数据目录 `command-logs/process_<id>/`，不进入工程 Diff。`output.jsonl` 保留带 stream、cursor 的真实输出，最多 16 MiB；内存每路 stdout/stderr 最多 200,000 字符，chunks 总量也有上限。`process.json` 记录 PID、所属轮次、工作区、Shell、起止时间、退出状态及清理原因。CMD 还保留执行脚本 `command.cmd`；这些是本地调试资料，可能包含项目输出或命令内容，不应直接公开上传。

`task_plan_executions.metadata_json` 为兼容旧数据库的附加字段，记录允许范围内的进程/日志引用、退出状态、耗时和稳定错误码；不保存命令参数、输出正文或模型推理。Task diagnostics 在原模型调用日志之外展示 executions。验证结果同时关联命令执行日志。超时通过 ToolError.details 返回实际已采集输出，错误不会被伪装成成功。

## M3 接口准备

已具备：受管理应用进程启动、稳定 `process_id`、PID、所属轮次/工作区、输出与生命周期事件、取消/停止、日志和诊断引用；M3 可用这些标识关联后续窗口，继续经 Registry → 权限 → ToolResult 调用，复用 Single Agent。

尚未具备：Windows 窗口枚举/绑定、截图、视觉定位、鼠标键盘输入、焦点/遮挡检查以及这些动作的权限策略。建议 M3 单独定义 DesktopSession 与 ProcessReference 的关联，以及版本化 list_windows/capture/input 工具；不能把进程就绪视作窗口就绪。M2 没有实现这些接口，也不要求用户手工逐步验收。

## 已知边界

- 终端为非交互式管道，不是 PTY；没有 stdin 交互式会话、管理员提权或登录自动化。
- 进程不会跨 Agent turn 或重启持有。Windows Agent 退出时 Job 句柄关闭会清理后代；POSIX Agent 被 SIGKILL、后代主动另建 session 或由外部服务托管的 daemon 不在普通进程组保证范围内。
- 安全策略是审批启发式，不是完整 Shell 解释器或 OS 沙箱；无法穷尽脚本、依赖安装钩子中的间接行为。项目识别只给建议，不自动执行任意发布/破坏命令。
- 停止可能强制终止，不承诺应用关闭钩子完成；用户必须保存需要保留的数据。
- 大型输出会受明确上限约束；Git 超限返回错误，需要缩小检查范围。模型轮数、工具数及原预算限制继续生效；多轮工程回归将可配置模型轮数设为 32。
- 本轮不依赖真实付费 API；模型响应替身不能证明任意真实模型的大工程完成质量。
