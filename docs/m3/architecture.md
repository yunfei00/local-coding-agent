# M3 Windows 桌面架构

日期：2026-10-23。基线 `d194eb3a370694bab0a4add7ae874f36ab050bb7`；分支 `feature/m3-windows-desktop`。

M3 继续复用 `AgentServer.run_tool_turn`、Single Agent、Task Runtime、ApprovalManager、ToolResult 与 M2 ProcessManager。不建立桌面专用 Agent Loop，不扩展多模型协作、路由或预算策略。

## 执行路径

模型调用 → 原 Registry/Permission → 明确授权 → DesktopRuntime → 一次性 Windows worker → Windows UIA/Win32 → ToolResult → 原模型循环。桌面 API 不在 Agent 事件循环内阻塞；每个调用使用独立 Python 工作进程，由 M2 Windows Job 拥有，在超时/取消时终止。当前进程内所有 Registry 的桌面操作串行化，避免两个任务争抢输入焦点。

`agent/desktop/runtime.py` 管理轮次所属的不可猜测 window_id、截图产物、视觉附件与工作进程。`agent/desktop/worker.py` 管理 UIA 定位、原生窗口身份、当前用户/会话/完整性检查、DPI、焦点、遮盖与 SendInput。`agent/tools/desktop.py` 定义九个工具，由原 ToolRegistry 注册。`agent/server/main.py` 负责已有审批和事件路径，以及在下一次模型请求中附加真实图像。

窗口身份包括 HWND、PID、进程创建时间、会话、窗口类和窗口 generation 属性。generation 随窗口销毁失效，避免同一进程重用 HWND 后旧句柄仍有效。授权和 window_id 不跨 Agent turn 保存；恢复任务需重新枚举并授权。控件使用 UIA runtime_id、automation_id、control_type/name 的精确组合；歧义、缺失和树不完整均报错，不随意选择第一个匹配项。

九个工具全部注册。当前轮次尚无已枚举窗口时，模型只先收到 desktop_list_windows；有窗口句柄后再公开其余桌面工具。它们本来就依赖有效 window_id，此渐进发现避免普通编码任务额外携带整套 UI schema，不改变模型路由或预算规则。

## 能力矩阵与证据

| 能力 | M2 | M3 与代码证据 |
| --- | --- | --- |
| 枚举/窗口定位 | 未实现 | 已实现当前用户会话可访问的可见顶层窗口；`worker.identity/process_identity`、`DesktopRuntime.binding` |
| 窗口/屏幕截图 | 未实现 | 已实现 Windows PrintWindow/Pillow 窗口图像；虚拟屏幕尺寸模式仅保留授权窗口，其他像素黑色；`worker.execute` screenshot 分支 |
| 控件树与 UIA | 未实现 | 已实现有界树、精确选择、InvokePattern、ValuePattern 回读校验、ScrollPattern；树最多 200 节点/8 层，截断时拒绝截图及不确定定位 |
| 点击/键盘/滚动/等待 | 未实现 | 已实现 UIA 优先，显式坐标/滚轮回退，原子 SendInput down/up，状态轮询；`worker.focus/input_batch/find` |
| DPI/移动/多屏坐标 | 未实现 | 已实现 Per Monitor V2、物理坐标、每次重取客户区位置、虚拟屏幕负原点，尺寸/DPI 改变后坐标操作要求重新 inspect/capture；实测移动/缩放窗口；未覆盖所有异构多显示器硬件组合 |
| 权限与隐私 | 无桌面范围 | 已实现默认审批、轮次/窗口范围、上传单独审批、输入文本事件脱敏、编辑框遮盖、敏感控件拒绝、风险再审批；`permissions/policy.py`、`server._authorize_tool` |
| 模型视觉反馈 | 只有文本工具结果 | 已实现显式 supports_vision + share_with_model 授权后，将真实 JPEG 图像内容加入模型请求；OpenAI Compatible image_url 与 Ollama images；非视觉明确报告并走控件树 |
| 任务产物/诊断 | 进程日志 | 增加 artifact_id、SHA256、路径、时间、窗口 generation、尺寸/DPI、vision_feedback，写入原执行日志允许字段；Desktop ToolCard 展示结果 |
| Stop/超时 | M2 进程管理 | 复用任务取消；终止 UIA worker，不继续后续桌面操作；已发生的点击/应用异步行为不能撤销 |
| 实际 GUI/Single Agent | 未实现 | WinForms 原生控件、PrintWindow、UIA、SendInput、真实状态文件；完整 Task 启动/操作/视觉附件/独立验证/恢复/取消；`tests/test_m3_desktop.py` |

## 新依赖

- `pywinauto 0.6.9`：成熟 Windows 自动化库，使用 UIA backend；其 Windows 依赖为 pywin32、comtypes、six。窗口和控件定位不依赖应用内部测试后门。[UIA API](https://pywinauto.readthedocs.io/en/latest/code/pywinauto.controls.uiawrapper.html)。
- `Pillow 12.3.0`（锁文件实际版本）：原生位图转换、编辑框遮盖、PNG/JPEG 编码与尺寸归一化。[Pillow 文档](https://pillow.readthedocs.io/)。实际采集直接调用 Windows PrintWindow，不依赖 ImageGrab 对未感知 DPI 程序的尺寸切换行为，不使用 OCR 冒充图像识别。

两项直接依赖仅在 Windows 安装；Ubuntu 导入、权限、协议和全部非 GUI 回归不依赖 Windows 库。Windows API 面向 Windows 10 1703+ / Windows 11，实际平台结果见验收文档。

## 边界

只支持当前已解锁用户的 Default desktop，不访问 Session 0、其他用户会话、UAC、提权目标或锁屏。UIA 控件是否可用由应用决定；Chromium/Electron 应启用应用的辅助功能支持（可使用 force-renderer-accessibility），自绘/GPU/受保护内容可能没有控件树或有效截图，此时明确报错，不宣称完成识别。M3 的真实主验收为 WinForms；不据此宣称所有 Electron/自绘应用均通过。

源码通过 Python 模块启动 worker；冻结 Agent 预留 --desktop-worker 内部入口，避免把冻结二进制当作 Python 解释器执行 -m。按本阶段约束未打包安装程序，冻结依赖收集和安装后的运行没有被声明为已验收。

截图默认遮盖全部 Edit 控件和识别出的敏感控件，输入框具体字符不能通过截图核对；普通文本输入由 ValuePattern 回读比较，仅返回匹配布尔值。窗口截图可能为客户区；必须匹配实际客户区/窗口物理尺寸，未知布局拒绝保存。所有范围外窗口在屏幕模式下遮盖，不提供无约束全桌面采集。复杂树超过安全上限会失败。

PrintWindow 按目标程序自身 DPI 上下文绘制客户区，再按已查询的逻辑/物理客户区尺寸显式归一化，最后在物理 UIA 坐标中遮盖。对 DPI 未感知程序，不能在更大的物理位图中直接绘制后把黑色空白当成遮盖成功；fixture 验证输入区域全黑，同时验证客户区右下角没有错误的黑色填充。

桌面能力是应用权限控制，不是 OS 沙箱。控件标签风险和敏感信息识别是保守启发式，不能穷尽应用语义或任意自绘文字；用户应只授权无敏感内容的任务窗口。没有拖拽、持续按键、剪贴板读取、管理员操作、OCR 引擎、应用登录或远程用户会话功能。其他独立 Agent 实例/用户同时操作桌面仍可能争抢焦点。

详见 [工具接口](tools.md)、[安全策略](security.md)、[自动验收](acceptance.md)、[M4 准备](m4-readiness.md)。
