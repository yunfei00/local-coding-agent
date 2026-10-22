# M2 Electron 最小故障工程

`npm ci` 安装锁定的真实 Electron，`npm test` 执行真实 node:test；初始 math.cjs 用减法导致断言失败。

修复后 `npm start` 启动真正的 Electron main process，输出 M2_ELECTRON_READY，并写入 runtime/electron.json（Electron 版本、browser 进程 PID、真实 Node/Python 子进程 PID）。Linux 无 DISPLAY 时使用 xvfb-run；CI 自动准备 Xvfb。没有截图、鼠标键盘或窗口自动化。

自动化使用受管理进程启动/停止、Task.cancel、TTL 与 scope 清理，逐个检查这些 PID 已退出，不通过杀死全机同名进程来伪造无残留。LCA_M2_PYTHON 可指定测试用 Python；默认 python。Fixture 仅用于本地隔离测试，无发布或安装包步骤。
