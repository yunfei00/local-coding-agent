# 桌面工具接口

所有工具共用 `timeout_seconds`（0.1–60 秒，默认 15，含排队时间）。非 Windows 返回 `DESKTOP_UNSUPPORTED`；无授权返回 `DESKTOP_CONSENT_REQUIRED`；Read Only 不显示桌面工具。工具结果均走原 ToolResult 和 tool.completed 事件。

| 工具 | 参数与行为 |
| --- | --- |
| desktop_list_windows | 可选 pid；枚举当前用户会话可访问的可见顶层窗口，含无标题窗口，返回 window_id、PID、标题、物理 bounds、DPI；窗口标题回传模型需审批 |
| desktop_screenshot | window_id；scope=window/screen，默认 window；share_with_model 默认 false。返回本地 PNG 产物引用、SHA256、captured_at、尺寸、物理 origin/client_origin/client_size、DPI、遮盖数、vision_feedback |
| desktop_inspect | window_id；返回有界 UIA controls、runtime_id、parent_runtime_id、automation_id、control_type、非敏感 name、enabled/visible、物理 bounds。不读 Value 内容 |
| desktop_focus_window | window_id；恢复最小化窗口并请求焦点，Windows 未授予焦点则报错 |
| desktop_click | window_id + selector，默认 method=uia（InvokePattern）；坐标回退 method=coordinate、x/y、confirm_risk=true，需新审批和先前 inspect/capture 的有效几何信息 |
| desktop_type_text | window_id + selector + text（最多 4000 字符）；仅普通 Edit + ValuePattern，敏感控件/疑似密钥文本拒绝；回读值但只返回 value_verified/字符数，不保存输入值 |
| desktop_keypress | window_id、可选 selector、keys；如 CTRL+A、TAB、CTRL+K。仅命名键/组合，原子 down/up，不接受脚本或持续按住；非基础导航键需 confirm_risk=true 与新审批，系统/会话切换组合禁止 |
| desktop_scroll | window_id、可选 selector、direction=up/down/left/right、amount=1–10；优先 ScrollPattern；滚轮回退需 confirm_risk=true 与新审批，并检查焦点/遮挡 |
| desktop_wait | window_id + selector；state=exists/enabled/disabled/visible/hidden/name，name 使用 expected；seconds=0–30，默认 5。轮询真实控件状态，可取消，未达到状态返回 DESKTOP_WAIT_TIMEOUT |

selector 允许 automation_id/name/control_type/runtime_id，均为精确匹配。优先使用 inspect 返回的 runtime_id 或 automation_id，多个匹配会返回 `DESKTOP_SELECTOR_AMBIGUOUS`；树不完整返回 `DESKTOP_TREE_LIMIT`，不猜测目标。

```json
{"name":"desktop_list_windows","arguments":{"pid":1234}}
{"name":"desktop_inspect","arguments":{"window_id":"window_<实际返回值>"}}
{"name":"desktop_click","arguments":{"window_id":"window_<实际返回值>","selector":{"automation_id":"SettingsButton"}}}
{"name":"desktop_type_text","arguments":{"window_id":"window_<实际返回值>","selector":{"automation_id":"NameInput"},"text":"普通测试内容"}}
{"name":"desktop_screenshot","arguments":{"window_id":"window_<实际返回值>","share_with_model":false}}
```

坐标为当前窗口客户区物理像素，控件 bounds 为物理屏幕坐标。模型从截图定位时需根据 origin、client_origin、pixel_to_screen_scale 及 model_image_size 转换；不能把缩略图坐标直接当作屏幕坐标。窗口移动会重新计算客户区原点；客户区尺寸或 DPI 改变会拒绝旧坐标，需重新 inspect/capture。UIA 优先，不需要模型手动换算移动后的坐标。

产物位于应用数据目录 `desktop-artifacts/turn_<id>/capture_<id>.png`，不进入工程 Diff；任务结束保留本地 PNG，窗口句柄与视觉附件失效。超时/失败的未完成截图删除。单张 PNG 上限 32 MiB；模型附件为最长边 768 像素 JPEG，保持真实像素，不生成 OCR 描述。

在 Task Models 中仅为实际支持图像的 Model Profile 启用 Vision image input（supports_vision，缺省 false）。截图发送还需 share_with_model=true 及独立授权。`vision_feedback=image_attached` 才代表真实图像进入下一轮模型请求；否则明确为 local_artifact_only 或 model_not_vision_capable_use_control_tree。普通 Chat 未声明能力时不假定视觉支持。接口通路经过自动测试，未以付费模型识别质量作为回归依据。

稳定错误码还包括 DESKTOP_WINDOW_SCOPE / DESKTOP_WINDOW_STALE、DESKTOP_SESSION_DENIED / USER_DENIED / ELEVATION_DENIED、DESKTOP_SENSITIVE_CONTROL / SENSITIVE_INPUT、DESKTOP_RISK_APPROVAL_REQUIRED、DESKTOP_FOCUS_FAILED / WINDOW_OCCLUDED、DESKTOP_CAPTURE_GEOMETRY_UNKNOWN、DESKTOP_UIA_PATTERN_UNAVAILABLE、DESKTOP_TIMEOUT。Windows 异常仅记录类型、原生错误码和内部位置，不记录 UI 异常正文。


## 2026-10-23 记事本大面积黑屏的隐私遮盖修正

截图链路会遮盖所有 UIA Edit 控件，防止代码、聊天、凭据等文字意外上传。旧版对普通编辑区也整块填黑；对于 Windows 记事本，编辑区域占满绝大部分客户区，结果看上去像截图失败，实际上可能是**隐私遮盖而非底层捕获失败**。

现改为先判断原始捕获是否为空，再对普通编辑区填充浅灰色不透明占位区域并标注 `EDIT CONTENT REDACTED`，敏感/密码控件仍为黑色。结果附带 `redacted_area_fraction` 与 `redaction_policy`，告知视觉模型实际画面有多少区域被遮盖。**这不是公开记事本文字内容的开关**；即使空白记事本，编辑区也按同一规则处理，图像不能用于判断编辑区内的真实文字。需要验证文本输入时必须使用受控 UI Automation 或独立测试状态断言。

若原始截图确实黑屏，仍触发受限的前台窗口屏幕回退，窗口被遮挡时安全失败，不捕获其他应用；不同 DPI/多显示器/现代记事本版本仍需公司实机复测。截图返回成功不等于所有用户可见内容都已完整呈现。
