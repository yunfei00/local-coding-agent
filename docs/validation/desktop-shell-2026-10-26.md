# 桌面外观与项目导航验收（2026-10-26）

## 本轮实现

- 统一深浅主题中性色。按用户提供的两张 ChatGPT 外观截图取色：深色主区 `#181818`、侧栏 `#191C1D`、外框 `#1A2225`、卡片 `#232323`、前景 `#FFFFFF`；浅色主区/卡片 `#FFFFFF`、侧栏 `#F8FCFD`、外框 `#ECF6F9`、选中底色 `#EBF0F1`、前景 `#1A1C1E`。保留原有 16/14/12px 字体层级。
- Windows 使用原生标题栏按钮覆盖：窗口按钮与会话标题、项目副标题和操作共用一行 44px 高度；删除 Electron 默认菜单栏。900px 宽度省略副标题，主标题截断，不换行。
- 全窗口顶部为“文件／编辑／视图／帮助”与标题、操作、原生窗口按钮共用的一行，删除项目区域内重复的标题行。编辑菜单调用白名单中的 Electron 原生编辑操作并恢复输入焦点；视图菜单支持明确选择深浅主题和缩放；文件和帮助菜单复用既有项目、退出和诊断能力。
- 顶部 Open 打开当前项目的文件管理器，另保留 Git、Task、Context 图标。More 收纳 Plan、Diagnostics、刷新模型、切换主题。现有功能均可访问；本项目专有工具不冒充 Codex 未实现的菜单功能。
- Projects 右侧 `+` → Add existing folder / Create new project。移除侧栏原来三个独立 New project / Open project / New thread 按钮。各项目右侧 `+` 创建该项目的新会话，非当前项目先使用原选择项目流程切换。
- 项目按项目和会话最近更新时间降序排列，同时间保持稳定的服务端顺序，旧数据缺失时间时保留顺序。创建、改名、开始/结束聊天后从后端刷新；重启继续使用持久化时间。
- Settings 打开为独立设置页，关闭后回到原会话。将设置、MCP、Git、Context、Diagnostics 中旧的中性颜色改用共享主题变量，清理浅色下的黑卡片/黑底栏和浅字标题；语义错误、警告、成功和 Diff 颜色继续单独处理。
- 左下角仅保留 Settings；删除 Agent Connected、进程端口和顶部 Provider 徽标。所有模型继续来自现有配置目录，连接类型、角色、预算、凭据存储不变。运行错误仍显示在输入区和 Diagnostics，不以移除徽标隐藏故障。

## 本机验证

- `npm --prefix desktop run typecheck`：PASS。
- `npm --prefix desktop test`：48 PASS，0 FAIL。
- `npm --prefix desktop run build`：PASS；原有 bundle 大小提示保留。
- `uv run python -m unittest discover -s tests -p test_project_creation.py -v`：7 PASS，0 FAIL；新建目录和 Git 保护逻辑未变，仅更新重名时的菜单指引。
- `node scripts/validation/desktop-smoke.cjs`：39 PASS，0 FAIL，0 SKIP。包含真实 Electron/Agent、原生 HWND 截图、两套主题和参考主色计算值、文件/编辑/视图/帮助菜单、原生全选与编辑焦点恢复、设置独立页及浅色卡片/底栏/次要按钮、900/1180px 单行布局、菜单键盘导航/Escape/点击外部关闭、按更新时间排序、跨项目新建会话及重启恢复。覆盖原有多 Provider 配置、任务、审批、Worktree、停止和所有面板打开时发送消息。
- Open 菜单通过真实 IPC 解析后端当前目录；`shell.openPath` 在该检查中被 Mock，避免向用户桌面打开多余 Explorer。其余菜单、配置、聊天、目录创建及测试文件修改均使用隔离的真实 Electron/Agent 流程。
- 对最终深浅主题的聊天和设置截图进行了人工视觉检查，并对照用户截图的主色。颜色来自图片平坦区域的主要 RGB 值，前景来自参考界面显示的颜色字段；不以通用灰阶替代，也不宣称复刻系统 Mica 随壁纸变化的透明效果。截图仅保留于本地 `validation-reports/`，不包含真实用户配置；公开检查清单见 [JSON](desktop-shell-2026-10-26.json)。

本轮使用隔离 HTTP Mock，不消耗付费模型额度。未重新运行上一轮真实在线模型任务；未创建 Tag、Release 或安装包。Windows/Ubuntu 完整 CI 由 PR 执行，结论以该提交的实际 Actions 结果为准。

## 更新和使用

关闭旧开发进程后，在仓库目录运行：

```powershell
git fetch origin
git switch main
git pull --ff-only origin main
uv sync --locked
npm --prefix desktop ci --no-audit --no-fund
npm --prefix desktop run dev
```

这次涉及 Electron 窗口配置，需要重新启动应用；无需重建旧任务或重新输入模型 Key。旧安装包不包含源码变更。
