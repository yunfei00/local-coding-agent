# v0.4.1 桌面交互更新

## 字体和控件

参考 Codex 桌面的文字层级统一为正文/聊天输入 16px、常规界面/设置/代码 14px、辅助文字 12px。侧栏项目、会话和按钮同时增加高度与间距；不是使用页面缩放。较窄窗口中工具栏自动换行，Settings 根据工具栏实际高度布局，避免覆盖按钮。

## 会话改名

悬停会话后点击右侧 `…`，或右键会话，在菜单中选择 Rename。也支持会话聚焦后 Shift+F10 打开菜单。名称在居中弹框中编辑，初始文字全选；Enter 保存，Escape、Cancel 或点击遮罩取消。保存错误保留在弹框中。

不再使用侧栏左下角的改名输入区。改名请求携带所属项目 ID，修改非当前项目的会话不会切换工作区；名称复用原 SQLite 会话存储，重启后保留。

## 新建项目

1. 点击侧栏 New project，填写 Project name。
2. Location 默认为 Windows 文档目录，Choose… 打开原生目录选择器以选择父目录。
3. Initialize Git repository 默认勾选，可取消。
4. Create project 创建独立新文件夹，通过原有项目注册和打开流程进入新会话。

项目名遵循 Windows 文件名规则，不允许路径穿越、绝对路径或保留设备名称。父目录必须已经存在，同名文件或目录一律拒绝，不复用、不覆盖。取消弹框不会创建目录；运行中的任务会在后端阻止新建。

Git 初始化使用现有 Git 工具，只创建空仓库，不创建提交，不推送。Git 不可用时保留目录、打开项目并给出警告。自主任务使用受管理 Worktree 前仍需用户准备初始提交。原 Open project 按钮用于已有工程。

## 实现与验证

复用原项目注册、会话存储、IPC、Git helper 和权限系统；新增 project.create 请求和可选的 thread.rename.project_id。未另建项目数据库或任务生命周期。

- `tests/test_project_creation.py`：7 项，覆盖目录保护、Windows 名称、活动任务阻止、Git 失败提示、会话改名不切换项目及持久化。
- 完整回归：223 项 Python、32 项桌面单元测试通过，类型检查和构建通过。
- `scripts/validation/desktop-smoke.cjs`：21 项真实 Electron 检查通过、0 跳过；覆盖新建/取消/重名保护/Git、居中改名/Enter/Escape、重启恢复、字体实际计算值、900/1180px 布局，以及既有模型路由、审批、Worktree、聊天和面板回归。

可复制验证命令：

```powershell
uv sync --locked
npm.cmd --prefix desktop ci
uv run python scripts/validation/check.py
node scripts/validation/desktop-smoke.cjs
```

Windows 本机完整打包的 11 个阶段全部通过：223 项 Python、32 项桌面单元测试，以及打包后的 21 项 Electron 回归均通过；解包版、Portable、Setup 安装/启动/卸载与 SHA256 校验通过。

远端 [Windows / Linux CI](https://github.com/yunfei00/local-coding-agent/actions/runs/39719814146) 和 [Windows 候选包](https://github.com/yunfei00/local-coding-agent/actions/runs/39719824555) 通过。Windows runner 使用短路径时，测试已改为比较文件系统规范路径。功能经 [PR #6](https://github.com/yunfei00/local-coding-agent/pull/6) 合并至 `d844d7d8392173cf151528a47cce54ab81c8ffdc`，Tag 为 `v0.4.1`。正式产物状态见 [验收记录](acceptance.md)。
