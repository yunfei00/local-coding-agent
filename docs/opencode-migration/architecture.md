# v2.0.0 执行架构

桌面 Composer 和 Task 从 `desktop/electron/main.ts` 进入同一套 OpenCode 执行路径。Electron 校验 Thread 和项目归属，管理运行租约、进程、权限、模型连接及 SSE。`openCodeRuntime.ts` 按项目和运行时版本绑定持久会话。收到执行结束事件后才更新桌面状态。

OpenCode 承担模型推理和原生工具。兼容接口转发器使用每次运行独有的环回凭证，固定到选择的模型，限制时长、请求数和输出 Token。在线请求先向 Python 预留预算，再由 Electron 发送到已选择的连接。

原生文件操作先通过 OpenCode 权限事件。Electron 核对目标属于当前项目或 worktree，并检查链接的实际目标。工作区模式的写入仍需一次性审批。Shell 始终询问，使用既有项目命令策略拦截系统和未经明确指示的 Git 发布操作。

Python 持久化项目、Thread、任务、Plan、Checkpoint 和消息，执行既有审批、受管理 Git worktree、确定性命令和 Windows GUI 验收。验收报告根据实际工具结果计算。
