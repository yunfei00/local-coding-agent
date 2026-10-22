# M3 自动化验收

日期：2026-10-23。自动化使用 `uv run`；无需用户逐步截图或点击，无付费 API 依赖。Mock 只用于 Single Agent 的模型决策；审批由测试客户端经真实 ApprovalManager 响应，未替换窗口、UIA、截图、鼠标键盘、文件或进程实现。

## 实际 GUI 程序

`manual-fixtures/m3-windows-gui/app.ps1` 使用系统 WinForms/Win32 控件，在当前已解锁桌面启动。Settings 按钮启用输入框，Ctrl+K 修改状态，40 行内容提供真实滚动，定时器异步改变状态。密码框为空；风险按钮仅增加计数。状态 JSON 来自真实控件事件，不是模型或测试伪造结果。

`tests/test_m3_desktop.py` 包含 4 项跨平台契约和 6 项实际 Windows GUI 测试：

| 场景 | 实际证据 |
| --- | --- |
| 启动、枚举、定位、截图、控件树 | M2 启动真实 PowerShell/WinForms；按真实 PID 枚举；UIA 控件树含 SettingsButton/NameInput；Windows PrintWindow 图像有效 |
| 点击、中文输入、快捷键、滚动、等待 | UIA Invoke/Value + 回读；实际控件事件记录中文输入；SendInput CTRL+A/CTRL+K；真实 ScrollPattern/滚轮；定时器状态等待 |
| 截图结果与遮盖 | 前后实际图片有像素差异；Edit 实际区域像素全黑；屏幕模式尺寸与窗口模式核对；真实 PNG 转成 JPEG 附件 |
| 移动/窗口大小/坐标 | 原生 MoveWindow 后 UIA bounds 更新，物理坐标转换后真实点击；非视觉截图明确降级；关闭应用后旧句柄失效 |
| 安全拒绝 | 密码框输入、歧义选择、未经新确认的风险按钮均拒绝；真实 deny 审批后点击计数不变；不存在控件等待超时 |
| Stop/超时 | 正在执行真实 UIA wait 时取消，确认 worker PID 退出、后续未点击；超时同样清理；每例清理 GUI PID |
| Single Agent 完整 Task | 实际 task.start/同一 Agent Loop/M2 start_process/窗口枚举与操作；真实 JPEG 进入下一轮模型消息；独立 Python 命令读取 GUI 实际状态验证；正常结束关闭应用；Task.resume 后重新启动并授权，Task.cancel 清理应用与 worker |

测试只在非 Windows 上跳过真实 GUI 场景，不因 Windows GUI 失败而偷偷跳过。Windows 锁屏/服务会话等不可交互环境将明确失败。支持代码包含虚拟多屏负原点与每次物理 DPI 查询；本地验收不等价于已经测试所有多屏、缩放与 Windows 10 硬件组合。

## 命令与证据

```powershell
uv run python -m unittest discover -s tests -p test_m3_desktop.py -v
uv run python scripts/validation/check.py
node scripts/validation/desktop-smoke.cjs
uv run python -m compileall -q agent
git diff --check
```

所有原 Python/M1/M2/文件/终端/Git 回归继续执行，桌面包含 typecheck、Vitest 与源码 build。Windows/Ubuntu CI 启用同一完整测试发现；Windows 运行实际 GUI 和现有 desktop-smoke，Ubuntu 明确跳过 Windows GUI，其余契约和工程测试保留。

`validation-reports/m3-windows-gui.json`、`m3-single-agent.json` 保存 fixture 工具清单、截图尺寸、脱敏验证与取消结果；CI 仅上传 m3-*.json。测试截图只留本地忽略目录用于像素/视觉核对，不提交或上传。任务自身截图保存于本地应用数据目录，并关联原 task_plan_executions 的产物元数据。

本轮特别修复：客户区截图与外框偏移混淆导致遮盖偏移；物理 UIA 坐标与未感知 DPI 的测试线程混用；树截断时不能宣称唯一定位；原生焦点短暂无窗口时必须等待或报错。

最终本地/CI 数量与运行链接在对应 PR 验收记录中补充，以实际运行结果为准。远端 Windows/Ubuntu CI 成功后才合并 main；无 Tag、Release 或安装包，不提交 API Key。既有未跟踪 local_coding_agent.egg-info/ 不属于本次修改。
